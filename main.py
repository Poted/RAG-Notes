import os
import time
import hashlib
import json
from typing import Optional, List, Dict
from dotenv import load_dotenv
import chromadb
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from google import genai
from google.genai import types
from datetime import datetime
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi import Depends, status
import secrets

from prompts import get_extraction_prompt, get_analysis_prompt, get_system_instructions, get_contextualize_prompt

security = HTTPBasic()
load_dotenv()

ADMIN_USER = os.environ.get("ADMIN_USER")
ADMIN_PASS = os.environ.get("ADMIN_PASS")

def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    is_user_ok = secrets.compare_digest(credentials.username, ADMIN_USER)
    is_pass_ok = secrets.compare_digest(credentials.password, ADMIN_PASS)
    if not (is_user_ok and is_pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

api_key = os.environ.get("API_KEY")
client = genai.Client(api_key=api_key)

chroma_client = chromadb.PersistentClient(path="./chroma_db")
chat_history: Dict[str, List[Dict[str, str]]] = {}
embedder = None

def get_embedder():
    global embedder
    if embedder is None:
        from sentence_transformers import SentenceTransformer
        embedder = SentenceTransformer('all-MiniLM-L6-v2')
    return embedder

def generate_with_retry(model_name, prompt, config=None, retries=3, delay=10):
    for attempt in range(retries):
        try:
            return client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise e

def chunk_text(text: str, size: int = 4000, overlap: int = 400):
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += size - overlap
    return chunks

def contextualize_query(model_name, session_id: str, question: str):
    history = chat_history.get(session_id, [])
    if not history:
        return question
    history_str = "\n".join([f"{m['role']}: {m['content']}" for m in history])
    prompt = get_contextualize_prompt(history_str, question)
    response = generate_with_retry(model_name, prompt)
    return response.text.strip()

app = FastAPI(title="RAG Agent")

class ContextRequest(BaseModel):
    name: str

class DocumentRequest(BaseModel):
    text: str
    context_name: str
    model_name: str

class QueryRequest(BaseModel):
    question: str
    session_id: str = "default"
    context_name: str
    model_name: str

class QueryAnalysis(BaseModel):
    is_analytical: bool
    category: str | None
    standalone_question: str

class FactEntry(BaseModel):
    fact: str
    date: str | None
    category: str

class ExtractedData(BaseModel):
    entries: list[FactEntry]

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/icon.png")

@app.get("/models", dependencies=[Depends(authenticate)])
async def list_models():
    try:
        models = client.models.list()
        return {"models": [m.name for m in models if "generateContent" in m.supported_generation_methods]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/contexts", dependencies=[Depends(authenticate)])
async def list_contexts():
    try:
        collections = chroma_client.list_collections()
        return {"contexts": [c.name for c in collections]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/contexts", dependencies=[Depends(authenticate)])
async def create_context(req: ContextRequest):
    try:
        chroma_client.create_collection(name=req.name)
        return {"message": "Created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/contexts/{context_name}", dependencies=[Depends(authenticate)])
async def delete_context(context_name: str):
    try:
        chroma_client.delete_collection(name=context_name)
        return {"message": "Deleted"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/documents", dependencies=[Depends(authenticate)])
async def list_documents(context_name: str = Query(...), limit: int = 10, offset: int = 0, search: Optional[str] = None):
    try:
        collection = chroma_client.get_collection(name=context_name)
        total = collection.count()
        if total == 0:
            return {"total": 0, "documents": []}

        if search:
            all_data = collection.get()
            docs_all = []
            search_lower = search.lower()
            if all_data['ids']:
                for i in range(len(all_data['ids'])):
                    content = all_data['documents'][i]
                    if search_lower in content.lower():
                        docs_all.append({"id": all_data['ids'][i], "content": content})
            docs_all = docs_all[::-1]
            return {"total": len(docs_all), "documents": docs_all[offset:offset+limit]}
        else:
            start = max(0, total - offset - limit)
            actual_limit = min(limit, total - offset)
            if actual_limit <= 0: return {"total": total, "documents": []}
            results = collection.get(limit=actual_limit, offset=start)
            docs = [{"id": results['ids'][i], "content": results['documents'][i]} for i in range(len(results['ids']))]
            return {"total": total, "documents": docs[::-1]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/documents", dependencies=[Depends(authenticate)])
async def delete_document(context_name: str = Query(...), doc_id: str = Query(...)):
    try:
        collection = chroma_client.get_collection(name=context_name)
        collection.delete(ids=[doc_id])
        return {"message": "Deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/session/{session_id}", dependencies=[Depends(authenticate)])
async def reset_session(session_id: str):
    chat_history[session_id] = []
    return {"message": "Cleared"}

@app.post("/add_document", dependencies=[Depends(authenticate)])
async def add_document(request: DocumentRequest):
    try:
        collection = chroma_client.get_collection(name=request.context_name)
        current_date = datetime.now().strftime("%Y-%m-%d")
        chunks = chunk_text(request.text)
        inst = get_embedder()
        pending_docs, pending_embeddings, pending_ids, pending_metadatas = [], [], [], []
        cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=ExtractedData, temperature=0.1)

        for i, chunk in enumerate(chunks):
            if i > 0: time.sleep(1.5)
            prompt = get_extraction_prompt(current_date, chunk)
            resp = generate_with_retry(request.model_name, prompt, config=cfg)
            data = json.loads(resp.text.strip().replace("```json", "").replace("```", ""))
            for entry in data.get("entries", []):
                fact_text = entry.get("fact")
                fact_date = entry.get("date")
                if not fact_text: continue
                display_text = f"{fact_date}: {fact_text}" if fact_date else fact_text
                fid = hashlib.md5(display_text.encode('utf-8')).hexdigest()
                pending_docs.append(display_text)
                pending_embeddings.append(inst.encode(display_text).tolist())
                pending_ids.append(fid)
                pending_metadatas.append({"category": entry.get("category", "general"), "date": fact_date})

        if pending_ids:
            collection.upsert(documents=pending_docs, embeddings=pending_embeddings, ids=pending_ids, metadatas=pending_metadatas)
        return {"message": "Knowledge updated", "facts_count": len(pending_ids)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query", dependencies=[Depends(authenticate)])
async def query(request: QueryRequest):
    try:
        collection = chroma_client.get_collection(name=request.context_name)
        raw_question = request.question.strip()
        current_date = datetime.now().strftime("%Y-%m-%d")
        cfg_analyze = types.GenerateContentConfig(response_mime_type="application/json", response_schema=QueryAnalysis, temperature=0.0)
        
        analysis_resp = generate_with_retry(request.model_name, get_analysis_prompt(current_date, raw_question), config=cfg_analyze)
        analysis = json.loads(analysis_resp.text.strip().replace("```json", "").replace("```", ""))
        
        is_stats = analysis.get("is_analytical", False)
        cat = analysis.get("category")
        q = analysis.get("standalone_question", raw_question)
        
        if is_stats:
            where_clause = {"category": cat.lower()} if cat and cat.lower() != "general" else None
            res = collection.get(where=where_clause) if where_clause else collection.get(limit=500)
            ctx = "\n".join(res.get('documents', []))
        else:
            inst = get_embedder()
            res = collection.query(query_embeddings=[inst.encode(q).tolist()], n_results=15)
            ctx = "\n\n".join(res.get('documents', [])[0]) if res.get('documents') else ""

        final_prompt = f"{get_system_instructions(current_date)}\n\nContext:\n{ctx}\n\nQuestion: {q}\n\nAnswer:"
        resp = generate_with_retry(request.model_name, final_prompt)
        
        if request.session_id not in chat_history: chat_history[request.session_id] = []
        chat_history[request.session_id].append({"role": "user", "content": raw_question})
        chat_history[request.session_id].append({"role": "assistant", "content": resp.text})
        
        return {"answer": resp.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

app.mount("/static", StaticFiles(directory="static"), name="static")
@app.get("/", dependencies=[Depends(authenticate)])
async def index(): return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    print(f"Running on port 8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
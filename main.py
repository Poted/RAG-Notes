import os
import time
import hashlib
import json
import socket
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

api_key = os.environ.get("GEMINI_API_KEY")
model_name = os.environ.get("MODEL_NAME")
client = genai.Client(api_key=api_key)

chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_or_create_collection(name="documents")

chat_history: Dict[str, List[Dict[str, str]]] = {}
embedder = None

def get_embedder():
    global embedder
    if embedder is None:
        from sentence_transformers import SentenceTransformer
        embedder = SentenceTransformer('all-MiniLM-L6-v2')
    return embedder

def generate_with_retry(prompt, config=None, retries=3, delay=10):
    for attempt in range(retries):
        try:
            return client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
        except Exception as e:
            if attempt < retries - 1:
                print(f"Retrying Gemini API ({attempt + 1}/{retries}) due to: {e}")
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

def contextualize_query(session_id: str, question: str):
    history = chat_history.get(session_id, [])
    if not history:
        return question
    history_str = "\n".join([f"{m['role']}: {m['content']}" for m in history])
    prompt = f"History:\n{history_str}\n\nFollow-up: {question}\n\nRephrase to standalone question:"
    response = generate_with_retry(prompt)
    return response.text.strip()

app = FastAPI(title="RAG Agent")

class DocumentRequest(BaseModel):
    text: str

class QueryRequest(BaseModel):
    question: str
    session_id: str = "default"

class QueryAnalysis(BaseModel):
    is_analytical: bool
    category: str | None
    standalone_question: str

class ExtractedFacts(BaseModel):
    facts: list[str]

class FactEntry(BaseModel):
    fact: str
    date: str | None
    category: str

class ExtractedData(BaseModel):
    entries: list[FactEntry]

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/icon.png")

@app.get("/documents", dependencies=[Depends(authenticate)])
async def list_documents(limit: int = 10, offset: int = 0, search: Optional[str] = None):
    try:
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
                        docs_all.append({
                            "id": all_data['ids'][i], 
                            "content": content
                        })
            
            docs_all = docs_all[::-1]
            paginated_docs = docs_all[offset:offset+limit]
            return {"total": len(docs_all), "documents": paginated_docs}
        
        else:
            start = max(0, total - offset - limit)
            actual_limit = min(limit, total - offset)
            
            if actual_limit <= 0:
                return {"total": total, "documents": []}

            results = collection.get(limit=actual_limit, offset=start)
            docs = []
            for i in range(len(results['ids'])):
                docs.append({"id": results['ids'][i], "content": results['documents'][i]})
            
            return {"total": total, "documents": docs[::-1]}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/documents", dependencies=[Depends(authenticate)])
async def delete_document(doc_id: str = Query(...)):
    try:
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
        current_date = datetime.now().strftime("%Y-%m-%d")
        chunks = chunk_text(request.text)
        inst = get_embedder()
        
        pending_docs, pending_embeddings, pending_ids, pending_metadatas = [], [], [], []
        
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json", 
            response_schema=ExtractedData,
            temperature=0.1
        )

        for i, chunk in enumerate(chunks):
            if i > 0:
                time.sleep(1.5)
            
            prompt = f"""
            Extract SHORT, ATOMIC facts from the text.
            
            RULES:
            1. If it is a personal event, log, or action, determine the 'date' using {current_date} as today. Use YYYY-MM-DD.
            2. If it is static knowledge, specification, or general fact, set 'date' to null.
            3. Assign a simple 1-word 'category'.
            4. The 'fact' string should be a clean sentence.
            
            Text to process:
            {chunk}
            """
            
            resp = generate_with_retry(prompt, config=cfg)
            
            try:
                clean_json = resp.text.strip().replace("```json", "").replace("```", "")
                data = json.loads(clean_json)
                
                for entry in data.get("entries", []):
                    fact_text = entry.get("fact")
                    fact_date = entry.get("date")
                    fact_cat = entry.get("category", "general")
                    
                    if not fact_text:
                        continue
                        
                    display_text = f"{fact_date}: {fact_text}" if fact_date else fact_text
                    fid = hashlib.md5(display_text.encode('utf-8')).hexdigest()
                    
                    meta = {"category": fact_cat}
                    if fact_date:
                        meta["date"] = fact_date

                    pending_docs.append(display_text)
                    pending_embeddings.append(inst.encode(display_text).tolist())
                    pending_ids.append(fid)
                    pending_metadatas.append(meta)
                    
            except Exception:
                raise Exception("Failed to parse facts from AI response.")

        if pending_ids:
            collection.upsert(
                documents=pending_docs,
                embeddings=pending_embeddings,
                ids=pending_ids,
                metadatas=pending_metadatas
            )
                
        return {"message": "Knowledge updated", "facts_count": len(pending_ids)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query", dependencies=[Depends(authenticate)])
async def query(request: QueryRequest):
    try:
        raw_question = request.question.strip()
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        prompt_analyze = f"""
        Analyze the user question.
        Current date: {current_date}
        1. 'is_analytical': true if the user asks for stats, chart, average, sum, count, or uses 'analyze:' prefix.
        2. 'category': guess the category from the question. Return null if general.
        3. 'standalone_question': rephrase the question to be standalone.
        
        Question: {raw_question}
        """
        
        cfg_analyze = types.GenerateContentConfig(
            response_mime_type="application/json", 
            response_schema=QueryAnalysis,
            temperature=0.0
        )
        
        analysis_resp = generate_with_retry(prompt_analyze, config=cfg_analyze)
        clean_json = analysis_resp.text.strip().replace("```json", "").replace("```", "")
        analysis = json.loads(clean_json)
        
        is_stats = analysis.get("is_analytical", False)
        cat = analysis.get("category")
        q = analysis.get("standalone_question", raw_question)
        
        where_clause = None
        if cat and cat.lower() != "general":
            where_clause = {"category": cat.lower()}
            
        if is_stats:
            if where_clause:
                res = collection.get(where=where_clause)
            else:
                res = collection.get(limit=500)
            
            docs = res.get('documents', [])
            ctx = "\n".join(docs) if docs else ""
        else:
            inst = get_embedder()
            if where_clause:
                res = collection.query(query_embeddings=[inst.encode(q).tolist()], n_results=15, where=where_clause)
            else:
                res = collection.query(query_embeddings=[inst.encode(q).tolist()], n_results=15)
                
            docs = res.get('documents', [])
            ctx = "\n\n".join(docs[0]) if docs and docs[0] else ""

        system_instructions = f"""
        Current Date: {current_date}
        You are a highly intelligent, conversational AI assistant.
        
        CORE RULES:
        1. Talk naturally. Use your vast general knowledge to answer the user's questions thoroughly.
        2. The provided Context is your "memory" of the user. Use it to personalize the interaction ONLY when it makes sense. 
        3. DO NOT force connections.
        4. ONLY act as a strict data analyst and generate charts ([CHART]JSON[/CHART]) if the user explicitly asked to calculate/chart their personal data or trends.
        5. If exact numerical values are missing, use general knowledge to provide reasonable average estimates. DO NOT refuse to calculate. State clearly that you are using estimated averages.
        6. Exclude missing days from calculations. Calculate averages ONLY based on present context.
        7. Resolve relative dates using {current_date}.
        """
        
        final_prompt = f"{system_instructions}\n\nContext:\n{ctx}\n\nQuestion: {q}\n\nAnswer:"
        resp = generate_with_retry(final_prompt)
        
        if request.session_id not in chat_history: 
            chat_history[request.session_id] = []
        chat_history[request.session_id].append({"role": "user", "content": raw_question})
        chat_history[request.session_id].append({"role": "assistant", "content": resp.text})
        
        return {"answer": resp.text}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", dependencies=[Depends(authenticate)])
async def index():
    return FileResponse("static/index.html")

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

if __name__ == "__main__":
    import uvicorn
    local_ip = get_ip()
    print(f"\n" + "="*40)
    print(f"RAG AGENT RUNNING")
    print(f"Local URL:  http://localhost:8000")
    print(f"Mobile URL: http://{local_ip}:8000")
    print(f"="*40 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
import json
import hashlib
import sqlite3
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

from config import ADMIN_USER, ADMIN_PASS, DB_PATH
from schemas import ContextRequest, DocumentRequest, QueryRequest, QueryAnalysis, ExtractedData
from database import chroma_client, save_chat_message, clear_chat_history, get_chat_history
from ai_engine import client, generate_with_retry, get_embedder, chunk_text
from prompts import get_extraction_prompt, get_analysis_prompt, get_system_instructions
from google.genai import types

router = APIRouter()
security = HTTPBasic()

def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    is_user_ok = secrets.compare_digest(credentials.username, ADMIN_USER)
    is_pass_ok = secrets.compare_digest(credentials.password, ADMIN_PASS)
    if not (is_user_ok and is_pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

@router.get("/models")
async def list_models(_: str = Depends(authenticate)):
    try:
        models = client.models.list()
        excluded = ["embedding", "aqa", "imagen", "veo", "tts", "audio", "banana", "robotics", "computer-use", "deep-research"]
        return {"models": [m.name for m in models if not any(x in m.name.lower() for x in excluded)]}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to fetch models.")

@router.get("/contexts")
async def list_contexts(_: str = Depends(authenticate)):
    return {"contexts": [c.name for c in chroma_client.list_collections()]}

@router.post("/contexts")
async def create_context(req: ContextRequest, _: str = Depends(authenticate)):
    try:
        chroma_client.create_collection(name=req.name)
        return {"message": "Created"}
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to create context.")

@router.delete("/contexts/{context_name}")
async def delete_context(context_name: str, _: str = Depends(authenticate)):
    try:
        chroma_client.delete_collection(name=context_name)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM history WHERE context_name=?", (context_name,))
        return {"message": "Deleted"}
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to delete context.")

@router.get("/documents")
async def list_documents(context_name: str = Query(...), limit: int = 10, offset: int = 0, search: str = None, _: str = Depends(authenticate)):
    try:
        col = chroma_client.get_collection(name=context_name)
        total = col.count()
        if total == 0: return {"total": 0, "documents": []}
        if search:
            data = col.get()
            docs = [{"id": data['ids'][i], "content": data['documents'][i]} for i in range(len(data['ids'])) if search.lower() in data['documents'][i].lower()]
            return {"total": len(docs), "documents": docs[::-1][offset:offset+limit]}
        else:
            start = max(0, total - offset - limit)
            res = col.get(limit=min(limit, total - offset), offset=start)
            docs = [{"id": res['ids'][i], "content": res['documents'][i]} for i in range(len(res['ids']))]
            return {"total": total, "documents": docs[::-1]}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list documents.")

@router.delete("/documents")
async def delete_document(context_name: str = Query(...), doc_id: str = Query(...), _: str = Depends(authenticate)):
    try:
        col = chroma_client.get_collection(name=context_name)
        col.delete(ids=[doc_id])
        return {"message": "Deleted"}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to delete document.")

@router.get("/history")
async def get_history(session_id: str, context_name: str = Query(...), _: str = Depends(authenticate)):
    try:
        return {"history": get_chat_history(session_id, context_name, limit=100)}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to retrieve history.")

@router.delete("/session/{session_id}")
async def reset_session(session_id: str, context_name: str = Query(...), _: str = Depends(authenticate)):
    try:
        clear_chat_history(session_id, context_name)
        return {"message": "Cleared"}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to clear session.")

@router.post("/add_document")
async def add_document(request: DocumentRequest, _: str = Depends(authenticate)):
    try:
        col = chroma_client.get_collection(name=request.context_name)
        cur_date = datetime.now().strftime("%Y-%m-%d")
        inst = get_embedder()
        cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=ExtractedData, temperature=0.1)
        for chunk in chunk_text(request.text):
            resp = generate_with_retry(request.model_name, get_extraction_prompt(cur_date, chunk), config=cfg)
            data = json.loads(resp.text.strip().replace("```json", "").replace("```", ""))
            p_docs, p_embs, p_ids, p_metas = [], [], [], []
            for entry in data.get("entries", []):
                txt = f"{entry['date']}: {entry['fact']}" if entry.get('date') else entry['fact']
                p_docs.append(txt)
                p_embs.append(inst.encode(txt).tolist())
                p_ids.append(hashlib.md5(txt.encode()).hexdigest())
                p_metas.append({"category": entry.get("category", "general"), "date": entry.get("date")})
            if p_ids: col.upsert(documents=p_docs, embeddings=p_embs, ids=p_ids, metadatas=p_metas)
        return {"message": "Done"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/query")
async def query(request: QueryRequest, _: str = Depends(authenticate)):
    try:
        col = chroma_client.get_collection(name=request.context_name)
        cur_date = datetime.now().strftime("%Y-%m-%d")
        hist = get_chat_history(request.session_id, request.context_name, limit=4)
        h_str = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in hist]) if hist else "No history."
        cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=QueryAnalysis, temperature=0.0)
        ana_resp = generate_with_retry(request.model_name, get_analysis_prompt(cur_date, h_str, request.question), config=cfg)
        ana = json.loads(ana_resp.text.strip().replace("```json", "").replace("```", ""))
        q = ana.get("standalone_question", request.question)
        
        if ana.get("is_analytical"):
            where = {"category": ana['category'].lower()} if ana.get('category') and ana['category'].lower() != "general" else None
            res = col.get(where=where) if where else col.get(limit=500)
            
            if not res or not res.get('documents') or len(res['documents']) == 0:
                res = col.get(limit=500)
                
            ctx = "\n".join(res['documents'])
        else:
            res = col.query(query_embeddings=[get_embedder().encode(q).tolist()], n_results=15)
            ctx = "\n\n".join(res['documents'][0]) if res['documents'] else ""
            
        resp = generate_with_retry(request.model_name, f"{get_system_instructions(cur_date, h_str)}\n\nContext:\n{ctx}\n\nQuestion: {q}\n\nAnswer:")
        save_chat_message(request.session_id, request.context_name, "user", request.question)
        save_chat_message(request.session_id, request.context_name, "assistant", resp.text)
        return {"answer": resp.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
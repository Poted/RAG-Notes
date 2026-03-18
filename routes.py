import json
import hashlib
import sqlite3
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from google.genai import types

from config import DB_PATH
from schemas import ContextRequest, DocumentRequest, QueryRequest, QueryAnalysis, ExtractedData
from database import (
    chroma_client, save_chat_message, clear_chat_history, 
    get_chat_history, verify_user, add_user, get_user_col_name, get_vector_collection
)
from ai_engine import client, generate_with_retry, chunk_text
from prompts import get_extraction_prompt, get_analysis_prompt, get_system_instructions

router = APIRouter()
security = HTTPBasic()

class RegisterRequest(BaseModel):
    username: str
    password: str

@router.post("/register")
async def register(req: RegisterRequest):
    if add_user(req.username, req.password):
        return {"message": "User created"}
    raise HTTPException(status_code=400, detail="User already exists")
    
def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    if not verify_user(credentials.username, credentials.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )
    return credentials.username

@router.post("/auth")
async def unified_auth(req: RegisterRequest):
    if not req.username or not req.password:
        raise HTTPException(status_code=400, detail="Missing credentials")
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT password_hash FROM users WHERE username = ?", (req.username,))
        row = cursor.fetchone()
    if not row:
        add_user(req.username, req.password)
        return {"message": "Account created"}
    if verify_user(req.username, req.password):
        return {"message": "Logged in"}
    raise HTTPException(status_code=401, detail="Invalid password")

@router.get("/models")
async def list_models(_: str = Depends(authenticate)):
    try:
        models = client.models.list()
        excluded = ["embedding", "aqa", "imagen", "veo", "tts", "audio", "banana", "robotics", "computer-use", "deep-research"]
        return {"models": [m.name for m in models if not any(x in m.name.lower() for x in excluded)]}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch models.")

@router.get("/contexts")
async def list_contexts(username: str = Depends(authenticate)):
    prefix = f"u_{username}_"
    all_cols = chroma_client.list_collections()
    user_cols = [c.name.replace(prefix, "") for c in all_cols if c.name.startswith(prefix)]
    return {"contexts": user_cols}

@router.post("/contexts")
async def create_context(req: ContextRequest, username: str = Depends(authenticate)):
    try:
        get_vector_collection(username, req.name)
        return {"message": "Created"}
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to create context.")

@router.delete("/contexts/{context_name}")
async def delete_context(context_name: str, username: str = Depends(authenticate)):
    try:
        full_name = get_user_col_name(username, context_name)
        chroma_client.delete_collection(name=full_name)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM history WHERE username=? AND context_name=?", (username, context_name))
        return {"message": "Deleted"}
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to delete context.")

@router.get("/documents")
async def list_documents(context_name: str = Query(...), limit: int = 10, offset: int = 0, search: str = None, username: str = Depends(authenticate)):
    try:
        col = get_vector_collection(username, context_name)
        total = col.count()
        if total == 0: return {"total": 0, "documents": []}
        data = col.get()
        docs = [{"id": data['ids'][i], "content": data['documents'][i]} for i in range(len(data['ids']))]
        if search:
            docs = [d for d in docs if search.lower() in d['content'].lower()]
        return {"total": len(docs), "documents": docs[::-1][offset:offset+limit]}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list documents.")

@router.get("/history")
async def get_history(session_id: str, context_name: str = Query(...), username: str = Depends(authenticate)):
    try:
        return {"history": get_chat_history(session_id, username, context_name, limit=100)}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to retrieve history.")

@router.delete("/session/{session_id}")
async def reset_session(session_id: str, context_name: str = Query(...), username: str = Depends(authenticate)):
    try:
        clear_chat_history(session_id, username, context_name)
        return {"message": "Cleared"}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to clear session.")

@router.post("/add_document")
async def add_document(request: DocumentRequest, username: str = Depends(authenticate)):
    try:
        col = get_vector_collection(username, request.context_name)
        cur_date = datetime.now().strftime("%Y-%m-%d")
        cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=ExtractedData, temperature=0.1)
        for chunk in chunk_text(request.text):
            resp = generate_with_retry(request.model_name, get_extraction_prompt(cur_date, chunk), config=cfg)
            data = resp.parsed
            p_docs, p_ids, p_metas = [], [], []
            for entry in data.entries:
                txt = f"{entry.date}: {entry.fact}" if entry.date else entry.fact
                p_docs.append(txt)
                p_ids.append(hashlib.md5(txt.encode()).hexdigest())
                p_metas.append({"category": entry.category or "general", "date": entry.date, "owner": username})
            if p_ids: col.upsert(documents=p_docs, ids=p_ids, metadatas=p_metas)
        return {"message": "Done"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/query")
async def query(request: QueryRequest, username: str = Depends(authenticate)):
    try:
        col = get_vector_collection(username, request.context_name)
        cur_date = datetime.now().strftime("%Y-%m-%d")
        hist = get_chat_history(request.session_id, username, request.context_name, limit=4)
        h_str = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in hist]) if hist else "No history."
        cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=QueryAnalysis, temperature=0.0)
        ana_resp = generate_with_retry(request.model_name, get_analysis_prompt(cur_date, h_str, request.question), config=cfg)
        ana = ana_resp.parsed
        q = ana.standalone_question or request.question
        if ana.is_analytical:
            where = {"category": ana.category.lower()} if ana.category and ana.category.lower() != "general" else None
            res = col.get(where=where) if where else col.get(limit=500)
            if not res or not res.get('documents') or len(res['documents']) == 0:
                res = col.get(limit=500)
            ctx = "\n".join(res['documents'])
        else:
            res = col.query(query_texts=[q], n_results=15)
            ctx = "\n\n".join(res['documents'][0]) if res['documents'] else ""
        resp = generate_with_retry(request.model_name, f"{get_system_instructions(cur_date, h_str)}\n\nContext:\n{ctx}\n\nQuestion: {q}\n\nAnswer:")
        save_chat_message(request.session_id, username, request.context_name, "user", request.question)
        save_chat_message(request.session_id, username, request.context_name, "assistant", resp.text)
        return {"answer": resp.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
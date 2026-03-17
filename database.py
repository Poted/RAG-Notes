import sqlite3
import chromadb
from config import CHROMA_PATH, DB_PATH

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS history (session_id TEXT, context_name TEXT, role TEXT, content TEXT)")

def save_chat_message(session_id: str, context_name: str, role: str, content: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO history (session_id, context_name, role, content) VALUES (?, ?, ?, ?)", (session_id, context_name, role, content))

def clear_chat_history(session_id: str, context_name: str = None):
    with sqlite3.connect(DB_PATH) as conn:
        if context_name:
            conn.execute("DELETE FROM history WHERE session_id=? AND context_name=?", (session_id, context_name))
        else:
            conn.execute("DELETE FROM history WHERE session_id=?", (session_id,))

def get_chat_history(session_id: str, context_name: str, limit: int = 4):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT role, content FROM history WHERE session_id=? AND context_name=? ORDER BY rowid DESC LIMIT ?", (session_id, context_name, limit))
        rows = cursor.fetchall()
        return [{"role": row[0], "content": row[1]} for row in reversed(rows)]
import sqlite3
import chromadb
from google import genai
from chromadb.utils.embedding_functions import EmbeddingFunction
from config import CHROMA_PATH, DB_PATH, API_KEY
from werkzeug.security import generate_password_hash

client = genai.Client(api_key=API_KEY)

class GoogleEmbeddings(EmbeddingFunction):
    def __call__(self, input: list[str]) -> list[list[float]]:
        result = client.models.embed_content(
            model='text-embedding-004',
            contents=input,
            config={'task_type': 'retrieval_document'}
        )
        return [emb.values for emb in result.embeddings]

embedding_fn = GoogleEmbeddings()
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

def get_user_col_name(username: str, context_name: str) -> str:
    return f"u_{username}_{context_name}"

def get_vector_collection(username: str, context_name: str):
    collection_name = get_user_col_name(username, context_name)
    return chroma_client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_fn
    )

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history (
                session_id TEXT, 
                username TEXT, 
                context_name TEXT, 
                role TEXT, 
                content TEXT
            )
        """)

def save_chat_message(session_id: str, username: str, context_name: str, role: str, content: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO history (session_id, username, context_name, role, content) VALUES (?, ?, ?, ?, ?)", 
                     (session_id, username, context_name, role, content))

def clear_chat_history(session_id: str, username: str, context_name: str = None):
    with sqlite3.connect(DB_PATH) as conn:
        if context_name:
            conn.execute("DELETE FROM history WHERE session_id=? AND username=? AND context_name=?", (session_id, username, context_name))
        else:
            conn.execute("DELETE FROM history WHERE session_id=? AND username=?", (session_id, username))

def get_chat_history(session_id: str, username: str, context_name: str, limit: int = 4):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            SELECT role, content FROM history 
            WHERE session_id=? AND username=? AND context_name=? 
            ORDER BY rowid DESC LIMIT ?
        """, (session_id, username, context_name, limit))
        rows = cursor.fetchall()
        return [{"role": row[0], "content": row[1]} for row in reversed(rows)]

def add_user(username, password):
    hash_pw = generate_password_hash(password)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, hash_pw))
        return True
    except sqlite3.IntegrityError:
        return False

def verify_user(username, password):
    from werkzeug.security import check_password_hash
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if row and check_password_hash(row[0], password):
            return True
    return False
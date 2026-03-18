import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")
DATA_DIR = "/app/data"

os.makedirs(DATA_DIR, exist_ok=True)

CHROMA_PATH = os.path.join(DATA_DIR, "chroma_db")
DB_PATH = os.path.join(DATA_DIR, "chat_history.db")
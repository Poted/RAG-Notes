import time
from google import genai
from config import API_KEY

client = genai.Client(api_key=API_KEY)
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
            return client.models.generate_content(model=model_name, contents=prompt, config=config)
        except Exception as e:
            err = str(e).lower()
            if "429" in err or "503" in err:
                if attempt < retries - 1:
                    time.sleep(delay)
                else:
                    raise Exception("API Quota Exceeded (429) or Service Unavailable. Please wait a moment and try again.")
            elif "404" in err:
                raise Exception(f"Model not found: {model_name}. It might be restricted or unavailable.")
            elif "400" in err:
                raise Exception("Bad Request (400). The model rejected the input.")
            else:
                raise Exception("An unexpected error occurred while communicating with the AI model.")

def chunk_text(text: str, size: int = 4000, overlap: int = 400):
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += size - overlap
    return chunks
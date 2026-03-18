import time
from google import genai
from config import API_KEY

client = genai.Client(api_key=API_KEY)

def generate_with_retry(model_name, prompt, config=None, retries=3, delay=10):
    m_name = model_name.replace("models/", "")
    for attempt in range(retries):
        try:
            return client.models.generate_content(model=m_name, contents=prompt, config=config)
        except Exception as e:
            err = str(e).lower()
            if "429" in err or "503" in err:
                if attempt < retries - 1:
                    time.sleep(delay)
                else:
                    raise Exception("API Quota Exceeded. Please wait a moment.")
            else:
                raise Exception(f"AI Error: {str(e)}")

def chunk_text(text: str, size: int = 4000, overlap: int = 400):
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text): break
        start += size - overlap
    return chunks
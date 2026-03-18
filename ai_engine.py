import time
import google.generativeai as genai
from config import API_KEY

genai.configure(api_key=API_KEY)

def generate_with_retry(model_name, prompt, config=None, retries=3, delay=10):
    model_id = model_name.replace("models/", "")
    model = genai.GenerativeModel(model_id)
    
    for attempt in range(retries):
        try:
            return model.generate_content(prompt, generation_config=config)
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
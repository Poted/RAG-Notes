from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from database import init_db
from routes import router

app = FastAPI(title="Context Notes", description="An agent for managing and querying contextual information.", version="1.0")

init_db()

app.include_router(router)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def index():
    return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    print("Running on port 8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
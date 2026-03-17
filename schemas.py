from pydantic import BaseModel
from typing import Optional, List

class ContextRequest(BaseModel):
    name: str

class DocumentRequest(BaseModel):
    text: str
    context_name: str
    model_name: str

class QueryRequest(BaseModel):
    question: str
    session_id: str = "default"
    context_name: str
    model_name: str

class QueryAnalysis(BaseModel):
    is_analytical: bool
    category: str | None
    standalone_question: str

class FactEntry(BaseModel):
    fact: str
    date: str | None
    category: str

class ExtractedData(BaseModel):
    entries: list[FactEntry]
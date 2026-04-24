from typing import Optional
from pydantic import BaseModel


class QueryRequest(BaseModel):
    question: str
    llm_model: str = "gemini-2.5-flash"
    uploaded_table: Optional[str] = None

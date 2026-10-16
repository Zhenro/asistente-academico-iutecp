import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List

try:
    from src.config import FRONTEND_DIR, DOCUMENTS_DIR
    from src.rag_engine import rag_engine
    from src.ingestion import build_vector_store
except ImportError:
    from config import FRONTEND_DIR, DOCUMENTS_DIR
    from rag_engine import rag_engine
    from ingestion import build_vector_store

app = FastAPI(
    title="IUTECP - Asistente Virtual Académico",
    description="API RAG para resolución de consultas estudiantiles e institucionales del IUTECP",
    version="1.0.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    try:
        from src.config import CHROMA_DB_DIR
    except ImportError:
        from config import CHROMA_DB_DIR
    sqlite_file = CHROMA_DB_DIR / "chroma.sqlite3"
    if not sqlite_file.exists():
        print("[*] Base vectorial no encontrada. Indexando automáticamente...")
        build_vector_store()


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    answer: str
    sources: List[str]


@app.get("/")
async def serve_index():
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Interfaz web no encontrada")
    return FileResponse(index_file)


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")
    
    try:
        result = rag_engine.generate_response(request.message)
        return ChatResponse(
            answer=result["answer"],
            sources=result["sources"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar consulta: {str(e)}")


@app.get("/api/documents")
async def list_documents():
    docs = []
    for pdf in DOCUMENTS_DIR.glob("*.pdf"):
        docs.append({
            "name": pdf.name,
            "size_kb": round(pdf.stat().st_size / 1024, 2)
        })
    return {"documents": docs, "total": len(docs)}


@app.post("/api/reindex")
async def trigger_reindex():
    try:
        count = build_vector_store()
        return {"status": "success", "message": f"Se reindexaron {count} fragmentos con éxito."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error durante reindexación: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="127.0.0.1", port=8000, reload=True)

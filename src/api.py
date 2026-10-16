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
    print("[*] Precargando fragmentos de documentos en memoria...")
    chunks = rag_engine._get_memory_chunks()
    print(f"[OK] {len(chunks)} fragmentos precargados exitosamente en memoria.")

    # Auto-registrar Webhook de Telegram si hay token
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    ext_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("SERVER_PUBLIC_URL")
    if not ext_url and os.getenv("RENDER_EXTERNAL_HOSTNAME"):
        ext_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}"
    if not ext_url and tg_token:
        ext_url = "https://asistente-academico-iutecp.onrender.com"

    if tg_token and ext_url:
        webhook_target = f"{ext_url.rstrip('/')}/api/telegram-webhook"
        print(f"[*] Registrando webhook de Telegram: {webhook_target}")
        import urllib.request
        try:
            req = urllib.request.Request(f"https://api.telegram.org/bot{tg_token}/setWebhook?url={webhook_target}")
            res = urllib.request.urlopen(req, timeout=8)
            print(f"[OK] Webhook de Telegram registrado: {res.read().decode()}")
        except Exception as e:
            print(f"[!] Error registrando webhook de Telegram: {e}")


class ChatRequest(BaseModel):
    message: str
    session_id: str = None


class ResetRequest(BaseModel):
    session_id: str


class ChatResponse(BaseModel):
    answer: str
    sources: List[str]


def send_telegram_message(token: str, chat_id: int, text: str):
    import urllib.request
    import json
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        # Fallback a texto plano si falla el parseo de Markdown
        payload_plain = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
        req_plain = urllib.request.Request(url, data=payload_plain, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req_plain, timeout=10)
        except Exception as e:
            print(f"[!] Error enviando mensaje a Telegram: {e}")


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
        result = rag_engine.generate_response(request.message, session_id=request.session_id)
        return ChatResponse(
            answer=result["answer"],
            sources=result["sources"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar consulta: {str(e)}")


@app.post("/api/chat/reset")
async def reset_session_endpoint(request: ResetRequest):
    rag_engine.clear_session(request.session_id)
    return {"status": "success", "message": f"Sesión {request.session_id} reiniciada."}


@app.post("/api/telegram-webhook")
async def telegram_webhook(update: dict):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return {"status": "ignored", "reason": "TELEGRAM_BOT_TOKEN no configurada"}
    
    message = update.get("message") or update.get("edited_message")
    if not message or "text" not in message:
        return {"status": "ignored"}
        
    chat_id = message["chat"]["id"]
    text = message["text"].strip()
    user_name = message.get("from", {}).get("first_name", "Estudiante")
    session_id = f"tg_{chat_id}"

    if text.startswith("/start"):
        welcome_msg = (
            f"¡Hola {user_name}! 👋\n\n"
            "Soy el *Asistente Académico Oficial del IUTECP*.\n\n"
            "Puedo ayudarte a resolver consultas sobre:\n"
            "• 📋 Requisitos de nuevo ingreso y TernaNet\n"
            "• 🏢 Sedes, ubicaciones y teléfonos\n"
            "• 💳 Pagos de matrícula en cuotas con Cashea\n"
            "• 📊 Escala de notas y pérdida por inasistencias (PI)\n"
            "• 🎓 Servicio comunitario, pasantías y grado\n\n"
            "¿Qué consulta tienes hoy? Escríbela y te orientaré de inmediato."
        )
        send_telegram_message(token, chat_id, welcome_msg)
        return {"status": "ok"}

    if text.startswith("/reset"):
        rag_engine.clear_session(session_id)
        send_telegram_message(token, chat_id, "🔄 *Historial de conversación reiniciado.* ¿En qué otra consulta puedo orientarte?")
        return {"status": "ok"}

    # Procesar consulta con RAG y memoria multi-turno
    result = rag_engine.generate_response(text, session_id=session_id)
    reply_text = result["answer"]
    if result.get("sources"):
        reply_text += "\n\n📚 *Fuentes oficiales:* " + ", ".join(result["sources"])

    send_telegram_message(token, chat_id, reply_text)
    return {"status": "ok"}


@app.get("/api/telegram-status")
async def telegram_status():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    configured = bool(token)
    webhook_url = None
    if configured:
        import urllib.request
        try:
            req = urllib.request.Request(f"https://api.telegram.org/bot{token}/getWebhookInfo")
            res = urllib.request.urlopen(req, timeout=5)
            info = json.loads(res.read().decode())
            webhook_url = info.get("result", {}).get("url")
        except Exception:
            pass
    return {
        "configured": configured,
        "webhook_url": webhook_url
    }


@app.get("/api/telegram-setup")
async def telegram_setup():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return {"status": "error", "message": "TELEGRAM_BOT_TOKEN no configurado en variables de entorno."}

    ext_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("SERVER_PUBLIC_URL")
    if not ext_url and os.getenv("RENDER_EXTERNAL_HOSTNAME"):
        ext_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}"
    if not ext_url:
        ext_url = "https://asistente-academico-iutecp.onrender.com"

    webhook_target = f"{ext_url.rstrip('/')}/api/telegram-webhook"
    import urllib.request
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_target}")
        res = urllib.request.urlopen(req, timeout=8)
        result = json.loads(res.read().decode())
        return {"status": "success", "webhook_target": webhook_target, "telegram_response": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


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

import os
import json
import urllib.request
import re
import socket
from datetime import datetime
from pathlib import Path

# Forzar resolución IPv4 para peticiones salientes (evita que Linux/Render cuelgue en IPv6 sin ruta)
_orig_getaddrinfo = socket.getaddrinfo
def _getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    if host and "telegram.org" in str(host):
        family = socket.AF_INET
    return _orig_getaddrinfo(host, port, family, type, proto, flags)
socket.getaddrinfo = _getaddrinfo_ipv4
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional

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
        import asyncio
        async def _register_webhook_bg():
            try:
                loop = asyncio.get_running_loop()
                res_data = await loop.run_in_executor(None, telegram_api_call, tg_token, f"setWebhook?url={webhook_target}", None, 20)
                print(f"[OK] Webhook de Telegram registrado: {res_data}")
            except Exception as e:
                print(f"[!] Error registrando webhook de Telegram: {e}")
        asyncio.create_task(_register_webhook_bg())


class ChatRequest(BaseModel):
    message: str
    session_id: str = None


class ResetRequest(BaseModel):
    session_id: str


class ChatResponse(BaseModel):
    answer: str
    sources: List[str]


def telegram_api_call(token: str, method: str, payload: dict = None, timeout: int = 20) -> dict:
    """Realiza peticiones seguras a la API de Telegram con User-Agent personalizado y timeout generoso."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode())


def send_telegram_chat_action(token: str, chat_id: int, action: str = "typing"):
    """Envía un indicador de acción (typing, record_voice) a Telegram."""
    try:
        telegram_api_call(token, "sendChatAction", {"chat_id": chat_id, "action": action}, timeout=10)
    except Exception:
        pass


def download_telegram_file(token: str, file_id: str) -> bytes:
    """Descarga el contenido binario de un archivo (audio/voz) desde Telegram."""
    data = telegram_api_call(token, f"getFile?file_id={file_id}", timeout=20)
    file_path = data.get("result", {}).get("file_path")
    if not file_path:
        raise ValueError("No se pudo obtener la ruta del archivo en Telegram.")
    
    download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    req = urllib.request.Request(download_url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    })
    with urllib.request.urlopen(req, timeout=25) as res:
        return res.read()


def send_telegram_message(token: str, chat_id: int, text: str):
    try:
        telegram_api_call(token, "sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=15)
    except Exception:
        # Fallback a texto plano si falla el parseo de Markdown
        try:
            telegram_api_call(token, "sendMessage", {"chat_id": chat_id, "text": text}, timeout=15)
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
    if not message:
        return {"status": "ignored"}
        
    chat_id = message["chat"]["id"]
    user_name = message.get("from", {}).get("first_name", "Estudiante")
    session_id = f"tg_{chat_id}"

    text = message.get("text", "").strip() if message.get("text") else None
    voice = message.get("voice") or message.get("audio")
    is_voice = False

    # 1. Procesar Nota de Voz / Audio si no hay texto
    if not text and voice:
        try:
            file_id = voice.get("file_id")
            mime_type = voice.get("mime_type", "audio/ogg")
            audio_bytes = download_telegram_file(token, file_id)
            transcription = rag_engine.transcribe_audio(audio_bytes, mime_type=mime_type)
            if transcription:
                text = transcription
                is_voice = True
            else:
                return {
                    "method": "sendMessage",
                    "chat_id": chat_id,
                    "text": "⚠️ No logré escuchar con claridad la nota de voz. ¿Podrías grabarla de nuevo o escribir tu consulta?"
                }
        except Exception as e:
            print(f"[!] Error procesando audio de Telegram: {e}")
            return {
                "method": "sendMessage",
                "chat_id": chat_id,
                "text": "⚠️ Ocurrió un error al procesar el audio. Por favor intenta de nuevo o escribe tu consulta en texto."
            }

    if not text:
        return {"status": "ignored"}

    # 2. Comandos especiales
    if text.startswith("/start"):
        welcome_msg = (
            f"¡Hola {user_name}! 👋\n\n"
            "Soy el *Asistente Académico Oficial del IUTECP*.\n\n"
            "Puedes hacerme tus consultas por *texto* o enviarme una *nota de voz* 🎙️ sobre:\n"
            "• 📋 Requisitos de nuevo ingreso y TernaNet\n"
            "• 🏢 Sedes, ubicaciones y teléfonos\n"
            "• 💳 Pagos de matrícula en cuotas con Cashea\n"
            "• 📊 Escala de notas y pérdida por inasistencias (PI)\n"
            "• 🎓 Servicio comunitario, pasantías y grado\n\n"
            "¿Qué consulta tienes hoy? Escríbela o envíame un audio."
        )
        return {
            "method": "sendMessage",
            "chat_id": chat_id,
            "text": welcome_msg,
            "parse_mode": "Markdown"
        }

    if text.startswith("/reset"):
        rag_engine.clear_session(session_id)
        return {
            "method": "sendMessage",
            "chat_id": chat_id,
            "text": "🔄 *Historial de conversación reiniciado.* ¿En qué otra consulta puedo orientarte?",
            "parse_mode": "Markdown"
        }

    # 3. Procesar consulta con RAG y memoria multi-turno
    result = rag_engine.generate_response(text, session_id=session_id)
    
    reply_text = ""
    if is_voice:
        reply_text += f"🎙️ *Escuché:* \"_{text}_\"\n\n"
    reply_text += result["answer"]
    if result.get("sources"):
        reply_text += "\n\n📚 *Fuentes oficiales:* " + ", ".join(result["sources"])

    # Respuesta directa en el cuerpo HTTP del Webhook (cero cuelgues salientes)
    return {
        "method": "sendMessage",
        "chat_id": chat_id,
        "text": reply_text,
        "parse_mode": "Markdown"
    }


@app.get("/api/telegram-status")
async def telegram_status():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    configured = bool(token)
    webhook_url = "https://asistente-academico-iutecp.onrender.com/api/telegram-webhook"
    return {
        "configured": configured,
        "webhook_url": webhook_url,
        "mode": "webhook_direct_reply"
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
    try:
        result = telegram_api_call(token, f"setWebhook?url={webhook_target}", timeout=25)
        return {"status": "success", "webhook_target": webhook_target, "telegram_response": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "iutecp2026").strip()

def verify_admin(x_admin_key: Optional[str]):
    if not x_admin_key or x_admin_key.strip() != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Clave de administrador incorrecta o no suministrada.")
    return True


@app.get("/admin")
async def serve_admin():
    admin_file = FRONTEND_DIR / "admin.html"
    if not admin_file.exists():
        raise HTTPException(status_code=404, detail="Panel de administración no encontrado.")
    return FileResponse(admin_file)


class AdminLoginRequest(BaseModel):
    password: str


@app.post("/api/admin/login")
async def admin_login(req: AdminLoginRequest):
    if req.password.strip() == ADMIN_PASSWORD:
        return {"status": "ok", "message": "Autenticación exitosa."}
    raise HTTPException(status_code=401, detail="Contraseña incorrecta.")


@app.get("/api/admin/documents")
async def admin_list_documents(x_admin_key: Optional[str] = Header(None)):
    verify_admin(x_admin_key)
    try:
        from src.ingestion import extract_text_from_pdf
    except ImportError:
        from ingestion import extract_text_from_pdf

    docs = []
    for pdf in sorted(DOCUMENTS_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True):
        mtime = datetime.fromtimestamp(pdf.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
        size_kb = round(pdf.stat().st_size / 1024, 2)
        try:
            pages = len(extract_text_from_pdf(pdf))
        except Exception:
            pages = 1
        docs.append({
            "name": pdf.name,
            "size_kb": size_kb,
            "modified_at": mtime,
            "pages": pages
        })
    total_chunks = len(rag_engine._get_memory_chunks())
    return {
        "documents": docs,
        "total_documents": len(docs),
        "total_chunks": total_chunks,
        "bot_username": "IutecpAsistenteBot"
    }


@app.post("/api/admin/upload")
async def admin_upload_document(file: UploadFile = File(...), x_admin_key: Optional[str] = Header(None)):
    verify_admin(x_admin_key)
    
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se permiten documentos en formato PDF.")

    # Sanitizar nombre de archivo
    clean_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', file.filename)
    if not clean_name.lower().endswith(".pdf"):
        clean_name += ".pdf"

    target_path = DOCUMENTS_DIR / clean_name
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="El archivo PDF subido está vacío.")

    with open(target_path, "wb") as f:
        f.write(content)

    # Recargar fragmentos RAG en caliente
    chunks_count = rag_engine.reload_documents()

    return {
        "status": "success",
        "message": f"Documento '{clean_name}' cargado con éxito en la base de conocimientos.",
        "filename": clean_name,
        "total_chunks": chunks_count
    }


@app.delete("/api/admin/documents/{filename}")
async def admin_delete_document(filename: str, x_admin_key: Optional[str] = Header(None)):
    verify_admin(x_admin_key)
    
    target_path = DOCUMENTS_DIR / filename
    # Prevenir Path Traversal
    if not target_path.resolve().is_relative_to(DOCUMENTS_DIR.resolve()) or not target_path.exists():
        raise HTTPException(status_code=404, detail="El documento especificado no existe.")

    target_path.unlink()
    chunks_count = rag_engine.reload_documents()

    return {
        "status": "success",
        "message": f"Documento '{filename}' eliminado del sistema.",
        "total_chunks": chunks_count
    }


@app.get("/api/admin/documents/{filename}/download")
async def admin_download_document(filename: str, x_admin_key: Optional[str] = Header(None)):
    verify_admin(x_admin_key)
    target_path = DOCUMENTS_DIR / filename
    if not target_path.resolve().is_relative_to(DOCUMENTS_DIR.resolve()) or not target_path.exists():
        raise HTTPException(status_code=404, detail="El documento especificado no existe.")
    return FileResponse(target_path, filename=filename, media_type="application/pdf")


@app.post("/api/admin/reindex")
async def admin_trigger_reindex(x_admin_key: Optional[str] = Header(None)):
    verify_admin(x_admin_key)
    chunks_count = rag_engine.reload_documents()
    return {
        "status": "success",
        "message": f"Base de conocimientos reindexada. Total de fragmentos activos: {chunks_count}",
        "total_chunks": chunks_count
    }


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
        count = rag_engine.reload_documents()
        return {"status": "success", "message": f"Se reindexaron {count} fragmentos con éxito."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error durante reindexación: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="127.0.0.1", port=8000, reload=True)

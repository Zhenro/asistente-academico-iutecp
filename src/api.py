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
import httpx
import asyncio
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

try:
    from src.config import FRONTEND_DIR, DOCUMENTS_DIR
    from src.rag_engine import rag_engine
    from src.ingestion import build_vector_store
    import src.analytics as analytics
    import src.ternanet as ternanet
except ImportError:
    from config import FRONTEND_DIR, DOCUMENTS_DIR
    from rag_engine import rag_engine
    from ingestion import build_vector_store
    import analytics
    import ternanet

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

# Pool de conexiones HTTP persistentes con Keep-Alive para máxima velocidad
httpx_client: Optional[httpx.AsyncClient] = None


@app.on_event("startup")
async def startup_event():
    global httpx_client
    httpx_client = httpx.AsyncClient(
        timeout=httpx.Timeout(25.0, connect=10.0),
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
        headers={"User-Agent": "IUTECP-Assistant/2.0 (FastAPI; Render Cloud)"}
    )

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
        async def _register_webhook_bg():
            try:
                res_data = await telegram_api_call(tg_token, f"setWebhook?url={webhook_target}", None, 20)
                print(f"[OK] Webhook de Telegram registrado: {res_data}")
            except Exception as e:
                print(f"[!] Error registrando webhook de Telegram: {e}")
        asyncio.create_task(_register_webhook_bg())

    # ⏰ Optimización Keep-Warm: evitar que Render Free hiberne cada 15 minutos
    if ext_url:
        async def _keep_warm_loop():
            while True:
                await asyncio.sleep(540)  # Ping cada 9 minutos
                try:
                    if httpx_client and not httpx_client.is_closed:
                        ping_url = f"{ext_url.rstrip('/')}/api/health"
                        res = await httpx_client.get(ping_url)
                        if res.status_code == 200:
                            print(f"[Keep-Warm] Ping activo exitoso: 200 OK")
                except Exception as e:
                    print(f"[Keep-Warm] Notice: {e}")
        asyncio.create_task(_keep_warm_loop())


@app.on_event("shutdown")
async def shutdown_event():
    global httpx_client
    if httpx_client and not httpx_client.is_closed:
        await httpx_client.aclose()


@app.get("/api/health")
async def health_endpoint():
    """Endpoint ultra-rápido para monitoreo de estado y Keep-Warm ping."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "memory_chunks": len(rag_engine._get_memory_chunks())
    }


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    student_cedula: Optional[str] = None


class ResetRequest(BaseModel):
    session_id: str


class StudentIdentifyRequest(BaseModel):
    cedula: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    sources: List[str]
    query_id: Optional[str] = None
    student: Optional[Dict[str, Any]] = None
    cached: Optional[bool] = False


async def telegram_api_call(token: str, method: str, payload: dict = None, timeout: float = 20.0) -> dict:
    """Realiza peticiones asíncronas con pool HTTP persistente a la API de Telegram."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    if httpx_client and not httpx_client.is_closed:
        if payload is not None:
            r = await httpx_client.post(url, json=payload, timeout=timeout)
        else:
            r = await httpx_client.get(url, timeout=timeout)
        return r.json()
    else:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"} if payload else {"User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode())


async def send_telegram_chat_action(token: str, chat_id: int, action: str = "typing"):
    """Envía un indicador de acción (typing, record_voice) a Telegram de forma no bloqueante."""
    try:
        await telegram_api_call(token, "sendChatAction", {"chat_id": chat_id, "action": action}, timeout=8.0)
    except Exception:
        pass


async def download_telegram_file(token: str, file_id: str) -> bytes:
    """Descarga el contenido binario de un archivo (audio/voz) desde Telegram usando pool persistente."""
    data = await telegram_api_call(token, f"getFile?file_id={file_id}", timeout=20.0)
    file_path = data.get("result", {}).get("file_path")
    if not file_path:
        raise ValueError("No se pudo obtener la ruta del archivo en Telegram.")
    
    download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    if httpx_client and not httpx_client.is_closed:
        r = await httpx_client.get(download_url, timeout=25.0)
        return r.content
    else:
        req = urllib.request.Request(download_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as res:
            return res.read()


async def send_telegram_message(token: str, chat_id: int, text: str):
    """Envía un mensaje a Telegram con reintento automático si falla el formato Markdown."""
    try:
        await telegram_api_call(token, "sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=15.0)
    except Exception:
        try:
            await telegram_api_call(token, "sendMessage", {"chat_id": chat_id, "text": text}, timeout=15.0)
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
        result = rag_engine.generate_response(
            request.message, 
            session_id=request.session_id,
            student_cedula=request.student_cedula
        )
        query_id = analytics.record_query(
            query=request.message,
            channel="web",
            answer=result["answer"],
            sources=result.get("sources", [])
        )
        return ChatResponse(
            answer=result["answer"],
            sources=result["sources"],
            query_id=query_id,
            student=result.get("student"),
            cached=result.get("cached", False)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar consulta: {str(e)}")


@app.post("/api/chat/stream")
async def chat_stream_endpoint(request: ChatRequest):
    """🌊 Optimización Streaming: Transmite tokens en tiempo real a la interfaz web (Server-Sent Events)."""
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")
    
    return StreamingResponse(
        rag_engine.generate_response_stream(
            query=request.message,
            session_id=request.session_id,
            student_cedula=request.student_cedula
        ),
        media_type="text/event-stream"
    )


@app.post("/api/chat/reset")
async def reset_session_endpoint(request: ResetRequest):
    rag_engine.clear_session(request.session_id)
    return {"status": "success", "message": f"Sesión {request.session_id} reiniciada."}


@app.post("/api/student/identify")
async def student_identify_endpoint(request: StudentIdentifyRequest):
    """Permite al estudiante autenticarse o seleccionarse por cédula para vincular su expediente a la sesión."""
    clean = ternanet.normalize_cedula(request.cedula)
    student = ternanet.get_student_by_cedula(clean)
    if not student:
        raise HTTPException(
            status_code=404, 
            detail=f"No se encontró ningún estudiante con cédula {request.cedula} en TernaNet."
        )
    
    if request.session_id:
        rag_engine.set_session_student(request.session_id, clean)
        
    return {
        "status": "success",
        "student": student,
        "message": f"Identificado exitosamente como {student['nombre']} ({student['carrera']})"
    }


@app.get("/api/student/profile/{cedula}")
async def get_student_profile_endpoint(cedula: str):
    """Consulta pública o interna del expediente simulado de TernaNet."""
    clean = ternanet.normalize_cedula(cedula)
    student = ternanet.get_student_by_cedula(clean)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado en TernaNet.")
    return student


@app.get("/api/students/list")
async def get_all_students_endpoint():
    """Retorna los expedientes de estudiantes para selección rápida en la UI."""
    return ternanet.load_students()


async def handle_telegram_message_async(token: str, message: dict):
    """Procesa mensajes de texto y notas de voz en segundo plano sin bloquear el webhook."""
    chat_id = message["chat"]["id"]
    user_name = message.get("from", {}).get("first_name", "Estudiante")
    session_id = f"tg_{chat_id}"

    text = message.get("text", "").strip() if message.get("text") else None
    voice = message.get("voice") or message.get("audio") or message.get("video_note")
    is_voice = False

    # CASO AUDIO / NOTA DE VOZ
    if not text and voice:
        await send_telegram_chat_action(token, chat_id, "record_voice")
        try:
            file_id = voice.get("file_id")
            mime_type = voice.get("mime_type", "audio/ogg")
            audio_bytes = await download_telegram_file(token, file_id)
            
            await send_telegram_chat_action(token, chat_id, "typing")
            transcription = rag_engine.transcribe_audio(audio_bytes, mime_type=mime_type)
            if transcription:
                text = transcription
                is_voice = True
            else:
                await send_telegram_message(
                    token, 
                    chat_id, 
                    "⚠️ No logré escuchar con claridad la nota de voz. Por favor intenta grabarla de nuevo o escribe tu consulta."
                )
                return
        except Exception as e:
            print(f"[!] Error procesando nota de voz de Telegram: {e}")
            await send_telegram_message(
                token, 
                chat_id, 
                "⚠️ Ocurrió un inconveniente al procesar la nota de voz. Por favor intenta enviarla de nuevo o escribe tu consulta en texto."
            )
            return

    if not text:
        return

    # COMANDOS ESPECIALES
    if text.startswith("/start"):
        welcome_msg = (
            f"¡Hola {user_name}! 👋\n\n"
            "Soy el *Asistente Académico Oficial del IUTECP*.\n\n"
            "Puedes hacerme tus consultas por *texto* o enviarme una *nota de voz* 🎙️ sobre:\n"
            "• 📋 Requisitos de nuevo ingreso y TernaNet\n"
            "• 🏢 Sedes, ubicaciones y teléfonos\n"
            "• 💳 Pagos de matrícula en cuotas con Cashea\n"
            "• 📊 Escala de notas y pérdida por inasistencias (PI)\n"
            "• 🎓 Servicio comunitario, pasantías y grado\n"
            "• 👤 Consultas con tu expediente: Escribe `/estudiante <tu_cedula>`\n\n"
            "¿Qué consulta tienes hoy? Escríbela o envíame un audio."
        )
        await send_telegram_message(token, chat_id, welcome_msg)
        return

    if text.startswith(("/estudiante", "/cedula", "/perfil", "/login")):
        clean_cand = ternanet.detect_cedula_in_text(text)
        if clean_cand:
            st = ternanet.get_student_by_cedula(clean_cand)
            if st:
                rag_engine.set_session_student(session_id, clean_cand)
                msg = (
                    f"🎓 *¡Identificado con éxito en TernaNet!*\n\n"
                    f"👤 *Estudiante:* {st['nombre']}\n"
                    f"🆔 *Cédula:* {st['cedula_formato']}\n"
                    f"📚 *Carrera:* {st['carrera']} ({st['sede']})\n"
                    f"📊 *Semestre:* {st['semestre']}to | *Avance:* {st['porcentaje_carrera']}%\n"
                    f"💳 *Estatus Financiero:* {st['estatus_arancelario']}\n\n"
                    "¡Listo! Ahora todas tus consultas (servicio comunitario, pasantías, pagos, notas) se responderán cruzando la normativa con tu expediente."
                )
                await send_telegram_message(token, chat_id, msg)
                return
            else:
                await send_telegram_message(token, chat_id, f"⚠️ La cédula {clean_cand} no se encuentra registrada en el sistema de prueba de TernaNet.")
                return
        else:
            current_st = rag_engine.get_session_student(session_id)
            if current_st:
                sc = current_st.get("servicio_comunitario", {})
                sc_txt = sc.get("estatus", "N/A") if isinstance(sc, dict) else str(sc)
                pas = current_st.get("pasantias", {})
                pas_txt = pas.get("estatus", "N/A") if isinstance(pas, dict) else str(pas)
                msg = (
                    f"🎓 *Expediente TernaNet Activo:*\n\n"
                    f"👤 *Nombre:* {current_st['nombre']}\n"
                    f"🆔 *Cédula:* {current_st['cedula_formato']}\n"
                    f"📚 *Carrera:* {current_st['carrera']} ({current_st['sede']})\n"
                    f"📊 *Semestre:* {current_st['semestre']}to ({current_st['porcentaje_carrera']}% aprobados)\n"
                    f"📈 *Promedio:* {current_st['promedio']} / 20\n"
                    f"🤝 *Servicio Comunitario:* {sc_txt}\n"
                    f"💼 *Pasantías:* {pas_txt}\n\n"
                    "💡 *Tip:* Para consultar con otra cédula, escribe: `/estudiante <cedula>`"
                )
                await send_telegram_message(token, chat_id, msg)
                return
            else:
                await send_telegram_message(
                    token, 
                    chat_id, 
                    "ℹ️ Para identificarte con tu expediente de TernaNet escribe:\n`/estudiante <tu_cédula>`\n\nEjemplo: `/estudiante 27346776`"
                )
                return

    if text.startswith("/reset"):
        rag_engine.clear_session(session_id)
        await send_telegram_message(token, chat_id, "🔄 *Historial de conversación reiniciado.* ¿En qué otra consulta puedo orientarte?")
        return

    # GENERAR RESPUESTA RAG
    await send_telegram_chat_action(token, chat_id, "typing")
    result = rag_engine.generate_response(text, session_id=session_id)
    
    analytics.record_query(
        query=text,
        channel="telegram",
        answer=result["answer"],
        sources=result.get("sources", [])
    )

    reply_text = ""
    if is_voice:
        reply_text += f"🎙️ *Escuché:* \"_{text}_\"\n\n"
    reply_text += result["answer"]
    if result.get("sources"):
        reply_text += "\n\n📚 *Fuentes oficiales:* " + ", ".join(result["sources"])

    await send_telegram_message(token, chat_id, reply_text)


@app.post("/api/telegram-webhook")
async def telegram_webhook(update: dict, background_tasks: BackgroundTasks):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return {"status": "ignored", "reason": "TELEGRAM_BOT_TOKEN no configurada"}
    
    message = update.get("message") or update.get("edited_message")
    if not message:
        return {"status": "ignored"}

    # Responder 200 OK inmediatamente a Telegram y procesar en segundo plano
    background_tasks.add_task(handle_telegram_message_async, token, message)
    return {"status": "ok"}


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


class FeedbackRequest(BaseModel):
    query_id: str
    rating: str  # "up" or "down"
    comment: Optional[str] = None


@app.post("/api/feedback")
async def submit_feedback(req: FeedbackRequest):
    if req.rating not in ["up", "down"]:
        raise HTTPException(status_code=400, detail="Calificación debe ser 'up' o 'down'.")
    success = analytics.record_feedback(req.query_id, req.rating, req.comment)
    return {"status": "success" if success else "not_found"}


@app.get("/api/admin/analytics")
async def admin_get_analytics(x_admin_key: Optional[str] = Header(None)):
    verify_admin(x_admin_key)
    return analytics.get_analytics_summary()


@app.get("/api/admin/analytics/export")
async def admin_export_analytics_csv(x_admin_key: Optional[str] = Header(None)):
    verify_admin(x_admin_key)
    csv_content = analytics.export_csv()
    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="reporte_consultas_iutecp.csv"'}
    )


@app.delete("/api/admin/analytics/reset")
async def admin_reset_analytics(x_admin_key: Optional[str] = Header(None)):
    verify_admin(x_admin_key)
    analytics.reset_analytics()
    return {"status": "success", "message": "Historial de analítica reseteado exitosamente."}


@app.get("/api/admin/students")
async def admin_get_students(x_admin_key: Optional[str] = Header(None)):
    verify_admin(x_admin_key)
    return ternanet.load_students()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="127.0.0.1", port=8000, reload=True)

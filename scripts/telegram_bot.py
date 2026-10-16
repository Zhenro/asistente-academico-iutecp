"""
Bot de Telegram para el Asistente Académico IUTECP.
Ejecuta:
    python scripts/telegram_bot.py
"""
import os
import sys
import time
import json
import urllib.request
from pathlib import Path
from dotenv import load_dotenv

# Base dir
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Cargar .env
load_dotenv(BASE_DIR / ".env")

from src.rag_engine import rag_engine

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        # Fallback a texto plano
        payload_plain = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
        req_plain = urllib.request.Request(url, data=payload_plain, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req_plain, timeout=10)
        except Exception as e:
            print(f"[!] Error enviando a Telegram: {e}")

def main():
    if not TOKEN:
        print("=" * 65)
        print(" [!] ERROR: TELEGRAM_BOT_TOKEN no encontrada en tu archivo .env")
        print("=" * 65)
        print("Pasos para obtener tu token en 1 minuto:")
        print("1. Abre Telegram y busca al usuario oficial: @BotFather")
        print("2. Escribe el comando: /newbot")
        print("3. Asigna un nombre al bot (ej. Asistente IUTECP)")
        print("4. Asigna un usuario terminado en 'bot' (ej. iutecp_asistente_bot)")
        print("5. Copia el token que te da BotFather y colócalo en tu .env:")
        print("   TELEGRAM_BOT_TOKEN=tu_token_aqui\n")
        sys.exit(1)

    print("=" * 65)
    print("  IUTECP - BOT DE TELEGRAM EN EJECUCIÓN (Polling Local)  ")
    print("=" * 65)

    # Eliminar cualquier webhook previo para permitir polling local
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook", timeout=5)
    except Exception:
        pass

    # Obtener info del bot
    try:
        res = urllib.request.urlopen(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=5)
        bot_info = json.loads(res.read().decode()).get("result", {})
        print(f"[+] Conectado como: @{bot_info.get('username')} ({bot_info.get('first_name')})")
        print("[+] Esperando mensajes de estudiantes... (Presiona CTRL+C para salir)\n")
    except Exception as e:
        print(f"[!] Error conectando con la API de Telegram: {e}")
        sys.exit(1)

    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={offset}&timeout=20"
            req = urllib.request.Request(url)
            res = urllib.request.urlopen(req, timeout=25)
            data = json.loads(res.read().decode())

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message")
                if not msg or "text" not in msg:
                    continue

                chat_id = msg["chat"]["id"]
                text = msg["text"].strip()
                user_name = msg.get("from", {}).get("first_name", "Estudiante")
                session_id = f"tg_{chat_id}"

                print(f"[>] Mensaje de {user_name} ({chat_id}): {text}")

                if text.startswith("/start"):
                    welcome = (
                        f"¡Hola {user_name}! 👋\n\n"
                        "Soy el *Asistente Académico Oficial del IUTECP*.\n\n"
                        "Puedo orientarte sobre:\n"
                        "• 📋 Requisitos de nuevo ingreso\n"
                        "• 🏢 Sedes y teléfonos de atención\n"
                        "• 💳 Pagos en cuotas con Cashea\n"
                        "• 📊 Calificaciones y pérdida de materia (PI)\n"
                        "• 🎓 Servicio comunitario y requisitos de grado\n\n"
                        "¿En qué puedo ayudarte hoy?"
                    )
                    send_telegram(TOKEN, chat_id, welcome)
                    continue

                if text.startswith("/reset"):
                    rag_engine.clear_session(session_id)
                    send_telegram(TOKEN, chat_id, "🔄 *Historial de conversación reiniciado.* ¿Qué otra consulta tienes?")
                    continue

                # Generar respuesta con RAG y memoria multi-turno
                res_rag = rag_engine.generate_response(text, session_id=session_id)
                reply = res_rag["answer"]
                if res_rag.get("sources"):
                    reply += "\n\n📚 *Fuentes oficiales:* " + ", ".join(res_rag["sources"])

                send_telegram(TOKEN, chat_id, reply)
                print(f"[<] Respuesta enviada a {user_name}")

        except KeyboardInterrupt:
            print("\n[+] Deteniendo bot de Telegram...")
            break
        except Exception as e:
            time.sleep(2)

if __name__ == "__main__":
    main()

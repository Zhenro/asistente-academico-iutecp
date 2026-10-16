"""
Punto de entrada principal para el Asistente Virtual IUTECP.
Ejecuta:
    python run.py
"""
import os
import sys
import uvicorn
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from src.config import DOCUMENTS_DIR, CHROMA_DB_DIR
from src.ingestion import build_vector_store

def main():
    print("=" * 65)
    print("  IUTECP - ASISTENTE VIRTUAL DE CONSULTAS ACADÉMICAS (RAG)  ")
    print("=" * 65)
    
    # Check if vector db exists or needs indexing
    chroma_sqlite = CHROMA_DB_DIR / "chroma.sqlite3"
    if not chroma_sqlite.exists() or len(list(DOCUMENTS_DIR.glob("*.pdf"))) == 0:
        print("[*] Base de datos vectorial no detectada o vacía. Iniciando indexación...")
        build_vector_store()
    else:
        print(f"[+] Base vectorial detectada en: {CHROMA_DB_DIR}")

    print("\n[+] Iniciando servidor web en: http://127.0.0.1:8000")
    print("[+] Abre tu navegador para interactuar con el Asistente Virtual")
    print("[+] Presiona CTRL + C para detener el servidor.\n")
    
    uvicorn.run("src.api:app", host="127.0.0.1", port=8000, reload=False)

if __name__ == "__main__":
    main()

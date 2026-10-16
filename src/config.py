import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

# Paths
DOCUMENTS_DIR = BASE_DIR / "data" / "documents"
CHROMA_DB_DIR = BASE_DIR / "data" / "chroma_db"
FRONTEND_DIR = BASE_DIR / "frontend"

# Ensure directories exist
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)

# LLM & API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Default Model Selection
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "gemini" if GEMINI_API_KEY else "openai" if OPENAI_API_KEY else "offline")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# RAG Settings
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "600"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))
TOP_K_RESULTS = int(os.getenv("TOP_K_RESULTS", "4"))

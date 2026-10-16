import os
from pathlib import Path
from pypdf import PdfReader
import chromadb
from chromadb.utils import embedding_functions

try:
    from src.config import DOCUMENTS_DIR, CHROMA_DB_DIR, CHUNK_SIZE, CHUNK_OVERLAP
except ImportError:
    from config import DOCUMENTS_DIR, CHROMA_DB_DIR, CHUNK_SIZE, CHUNK_OVERLAP


def extract_text_from_pdf(pdf_path: Path):
    reader = PdfReader(str(pdf_path))
    pages_text = []
    for page_idx, page in enumerate(reader.pages):
        text = page.extract_text()
        if text:
            pages_text.append({"page": page_idx + 1, "text": text.strip()})
    return pages_text


def split_text_into_chunks(text: str, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
        if end >= len(words):
            break
    return chunks


def build_vector_store():
    print(f"[*] Iniciando indexación de documentos en: {DOCUMENTS_DIR}")
    
    # Initialize ChromaDB persistent client
    client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    
    # Use Chroma's default lightweight embedding function (runs locally)
    emb_fn = embedding_functions.DefaultEmbeddingFunction()
    
    # Get or recreate collection
    try:
        client.delete_collection(name="iutecp_knowledge_base")
    except Exception:
        pass
    
    collection = client.create_collection(
        name="iutecp_knowledge_base",
        embedding_function=emb_fn,
        metadata={"description": "Documentos normativos y guias oficiales IUTECP"}
    )
    
    pdf_files = list(DOCUMENTS_DIR.glob("*.pdf"))
    if not pdf_files:
        print("[!] No se encontraron archivos PDF en la carpeta de documentos.")
        return 0

    total_chunks = 0
    all_ids = []
    all_documents = []
    all_metadatas = []

    for pdf_file in pdf_files:
        print(f" -> Procesando: {pdf_file.name}")
        pages = extract_text_from_pdf(pdf_file)
        
        for p in pages:
            chunks = split_text_into_chunks(p["text"], chunk_size=120, overlap=30)
            for chunk_idx, chunk in enumerate(chunks):
                chunk_id = f"{pdf_file.stem}_p{p['page']}_c{chunk_idx}"
                all_ids.append(chunk_id)
                all_documents.append(chunk)
                all_metadatas.append({
                    "source": pdf_file.name,
                    "page": p["page"],
                    "chunk_id": chunk_id
                })
                total_chunks += 1

    if all_documents:
        # Add to ChromaDB in batches
        batch_size = 50
        for i in range(0, len(all_documents), batch_size):
            collection.add(
                ids=all_ids[i:i + batch_size],
                documents=all_documents[i:i + batch_size],
                metadatas=all_metadatas[i:i + batch_size]
            )
            
    print(f"[OK] Indexacion completada con exito. Total de fragmentos indexados: {total_chunks}")
    return total_chunks


if __name__ == "__main__":
    build_vector_store()

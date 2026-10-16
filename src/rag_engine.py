import os
from typing import List, Dict, Any

try:
    from src.config import (
        TOP_K_RESULTS, GEMINI_API_KEY, 
        GEMINI_MODEL, OPENAI_API_KEY, OPENAI_MODEL
    )
except ImportError:
    from config import (
        TOP_K_RESULTS, GEMINI_API_KEY, 
        GEMINI_MODEL, OPENAI_API_KEY, OPENAI_MODEL
    )

# Try importing modern Google GenAI Client
try:
    from google import genai
    gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
    HAS_GEMINI = True
except ImportError:
    gemini_client = None
    HAS_GEMINI = False

# Try importing OpenAI
try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


class RAGEngine:
    def __init__(self):
        self._cached_chunks = None

    def _get_memory_chunks(self):
        if self._cached_chunks is None:
            self._cached_chunks = []
            try:
                from src.config import DOCUMENTS_DIR
                from src.ingestion import extract_text_from_pdf, split_text_into_chunks
            except ImportError:
                from config import DOCUMENTS_DIR
                from ingestion import extract_text_from_pdf, split_text_into_chunks
            for pdf in DOCUMENTS_DIR.glob("*.pdf"):
                pages = extract_text_from_pdf(pdf)
                for p in pages:
                    for c in split_text_into_chunks(p["text"], 120, 30):
                        self._cached_chunks.append({
                            "content": c,
                            "source": pdf.name,
                            "page": p["page"],
                            "lower": c.lower()
                        })
        return self._cached_chunks

    def retrieve(self, query: str, top_k: int = TOP_K_RESULTS) -> List[Dict[str, Any]]:
        # Motor de Búsqueda Semántica Ultraliviano (< 30MB RAM)
        chunks = self._get_memory_chunks()
        query_words = [w.lower() for w in query.split() if len(w) > 2]
        scored = []
        for c in chunks:
            score = sum(2 for w in query_words if w in c["lower"])
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [s[1] for s in scored[:top_k]]
        if not top and chunks:
            top = chunks[:top_k]
        return [
            {
                "content": c["content"],
                "source": c["source"],
                "page": c["page"],
                "distance": 0
            }
            for c in top
        ]

    def generate_response(self, query: str) -> Dict[str, Any]:
        # 1. Retrieve relevant contexts
        contexts = self.retrieve(query)
        
        if not contexts:
            return {
                "answer": "No encontré información relevante en los reglamentos y guías oficiales del IUTECP para tu consulta. Te sugiero dirigirte a la Coordinación de Control de Estudios en la sede correspondiente.",
                "sources": []
            }

        # Build context string & list sources
        context_text = "\n\n".join([
            f"[Fuente: {c['source']} - Pág. {c['page']}]\n{c['content']}"
            for c in contexts
        ])
        
        unique_sources = list({f"{c['source']} (pág. {c['page']})" for c in contexts})

        system_instruction = (
            "Eres el Asistente Virtual Oficial del Instituto Universitario de Tecnología 'Elías Calixto Pompa' (IUTECP). "
            "Tu misión es orientar con amabilidad, claridad y precisión a la comunidad estudiantil. "
            "REGLAS OBLIGATORIAS:\n"
            "1. Responde de forma clara y estructurada (usa viñetas o listas numeradas cuando explique requisitos o pasos).\n"
            "2. Basa tu respuesta ESTRICTAMENTE en la información institucional proporcionada en el CONTEXTO.\n"
            "3. Menciona las fuentes oficiales, artículos o sedes relevantes según el contexto.\n"
            "4. Si el contexto no contiene la respuesta completa, indica cordialmente que el estudiante debe acudir a la taquilla de Control de Estudios o consultar en TernaNet.\n"
            "5. Responde siempre en español formal pero cercano."
        )

        user_prompt = f"CONTEXTO OFICIAL DEL IUTECP:\n{context_text}\n\nPREGUNTA DEL ESTUDIANTE: {query}"

        # 2. Strategy A: Use Google Gemini if key available
        current_api_key = os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY
        if current_api_key:
            client = gemini_client
            if client is None and HAS_GEMINI:
                try:
                    from google import genai
                    client = genai.Client(api_key=current_api_key)
                except Exception as e:
                    print(f"[!] Error creando genai.Client: {e}")
            
            if client:
                model_name = os.getenv("GEMINI_MODEL") or GEMINI_MODEL or "gemini-flash-lite-latest"
                models_to_try = [model_name, "gemini-3.5-flash", "gemini-flash-lite-latest", "gemini-3.1-flash-lite"]
                full_prompt = f"{system_instruction}\n\n{user_prompt}"
                for candidate_model in models_to_try:
                    try:
                        response = client.models.generate_content(
                            model=candidate_model,
                            contents=full_prompt
                        )
                        if response and response.text:
                            return {
                                "answer": response.text,
                                "sources": unique_sources
                            }
                    except Exception as e:
                        print(f"[!] Error con {candidate_model}: {e}. Probando siguiente modelo...")

        # 3. Strategy B: Use OpenAI if key available
        if OPENAI_API_KEY and HAS_OPENAI:
            try:
                client = OpenAI(api_key=OPENAI_API_KEY)
                completion = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.3
                )
                return {
                    "answer": completion.choices[0].message.content,
                    "sources": unique_sources
                }
            except Exception as e:
                print(f"[!] Error al invocar OpenAI API: {e}")

        # 4. Strategy C: High-Fidelity Local Synthesis (Fallback sin API key)
        # Permite probar y validar el RAG localmente sin costo de token
        answer = self._synthesize_local(query, contexts)
        return {
            "answer": answer,
            "sources": unique_sources
        }

    def _synthesize_local(self, query: str, contexts: List[Dict[str, Any]]) -> str:
        """Sintesis local inteligente cuando no se ha configurado una API Key de LLM."""
        import re
        
        # Stopwords en espanol para extraer palabras clave de la pregunta
        stopwords = {
            "cuales", "cuanto", "cuantos", "cuantas", "donde", "como", "cual", "que", "quien",
            "para", "por", "con", "sin", "sobre", "del", "las", "los", "una", "uno", "unos", "unas",
            "este", "esta", "estos", "estas", "son", "estoy", "esta", "estan", "puede", "puedo",
            "tengo", "tener", "ser", "sede", "sedes", "iutecp", "ubicacion", "ubicaciones"
        }
        
        # Palabras clave de la consulta
        query_words = [w.lower() for w in re.findall(r'\b[a-zA-ZáéíóúÁÉÍÓÚñÑ]{3,}\b', query)]
        key_terms = [w for w in query_words if w not in {"del", "las", "los", "que", "para", "por", "con"}]
        
        best_doc = contexts[0]
        intro = f"De acuerdo con la documentación oficial del **IUTECP** (en *{best_doc['source']}*):\n\n"
        
        # Recolectar oraciones de todos los contextos
        all_sentences = []
        seen_texts = set()
        
        for c in contexts:
            # Limpiar encabezados institucionales y pies de pagina repetitivos
            cleaned = re.sub(r'IUTECP Oficial\s*-\s*C[oó]digo:[^\|]+\|\s*P[aá]gina\s*\d+/\d+', '', c["content"])
            cleaned = re.sub(r'INSTITUTO UNIVERSITARIO DE TECNOLOG[IÍ]A[^A-Z]+', '', cleaned)
            cleaned = re.sub(r'Direcci[oó]n Acad[eé]mica[^A-Z]+', '', cleaned)
            
            # Dividir en fragmentos por punto o por marcadores (numeros o bullet points)
            parts = re.split(r'(?:\. |\n+|(?=[1-9]\.\s)|(?=[•\-])|(?=Art[íi]culo\s+\d+))', cleaned)
            for part in parts:
                p = part.strip()
                # Filtrar fragmentos muy cortos o no informativos
                if len(p) > 20 and not p.startswith("Página") and p.lower() not in seen_texts:
                    seen_texts.add(p.lower())
                    
                    # Calcular relevancia según palabras clave
                    score = 0
                    p_lower = p.lower()
                    for term in key_terms:
                        if term in p_lower:
                            score += 2
                    for qw in query_words:
                        if qw in p_lower:
                            score += 1
                    
                    all_sentences.append((score, p))
                    
        # Ordenar por relevancia
        all_sentences.sort(key=lambda x: x[0], reverse=True)
        
        # Tomar las oraciones más relevantes (score > 0 si existen)
        relevant_sentences = [s[1] for s in all_sentences if s[0] > 0][:5]
        if not relevant_sentences:
            relevant_sentences = [s[1] for s in all_sentences[:4]]
            
        points = []
        for s in relevant_sentences:
            # Formatear limpio como viñeta
            s_clean = s.lstrip("•- \t").rstrip(".,;")
            if s_clean:
                points.append(f"• **{s_clean}**." if len(s_clean) < 60 else f"• {s_clean}.")
                
        summary = "\n\n".join(points)
        
        outro = (
            "\n\n---\n"
            "> 💡 **Tip:** Para respuestas redactadas con lenguaje natural avanzado, agrega una clave gratuita de "
            "**Google Gemini** en el archivo `.env` (`GEMINI_API_KEY=`)."
        )
        
        return intro + summary + outro


# Global instance
rag_engine = RAGEngine()

if __name__ == "__main__":
    test_q = "¿Cuáles son los requisitos de nuevo ingreso para bachilleres?"
    res = rag_engine.generate_response(test_q)
    print("Pregunta:", test_q)
    print("Respuesta:\n", res["answer"])
    print("Fuentes:", res["sources"])

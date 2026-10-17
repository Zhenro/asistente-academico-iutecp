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
        self.session_memories: Dict[str, List[Dict[str, str]]] = {}

    def clear_session(self, session_id: str):
        if session_id in self.session_memories:
            del self.session_memories[session_id]

    def reload_documents(self) -> int:
        """Limpia la memoria caché y recarga todos los documentos PDF activos."""
        self._cached_chunks = None
        chunks = self._get_memory_chunks()
        return len(chunks)

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

    def retrieve(self, query: str, top_k: int = TOP_K_RESULTS, history: List[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        # Motor de Búsqueda Semántica Ultraliviano (< 30MB RAM)
        chunks = self._get_memory_chunks()
        
        # Palabras clave de la consulta actual
        query_words = [w.lower() for w in query.split() if len(w) > 2]
        
        # Si hay historial previo, incorporar términos clave del turno anterior para preguntas de seguimiento
        if history:
            for item in history[-2:]:
                query_words.extend([w.lower() for w in item.get("content", "").split() if len(w) > 4])
        
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

    def generate_response(self, query: str, session_id: str = None) -> Dict[str, Any]:
        # Obtener historial de la sesión si existe
        history = self.session_memories.get(session_id, []) if session_id else []

        # 1. Retrieve relevant contexts (considerando contexto de historial)
        contexts = self.retrieve(query, history=history)
        
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

        # Formatear historial reciente para el prompt
        history_text = ""
        if history:
            formatted_turns = []
            for h in history[-4:]:
                role_label = "Estudiante" if h["role"] == "user" else "Asistente"
                formatted_turns.append(f"{role_label}: {h['content']}")
            history_text = "HISTORIAL RECIENTE DE LA CONVERSACIÓN:\n" + "\n".join(formatted_turns) + "\n\n"

        system_instruction = (
            "Eres el Asistente Virtual Oficial del Instituto Universitario de Tecnología 'Elías Calixto Pompa' (IUTECP). "
            "Tu misión es orientar con amabilidad, claridad y precisión a la comunidad estudiantil. "
            "REGLAS OBLIGATORIAS:\n"
            "1. Responde de forma clara y estructurada (usa viñetas o listas numeradas cuando explique requisitos o pasos).\n"
            "2. Basa tu respuesta ESTRICTAMENTE en la información institucional proporcionada en el CONTEXTO.\n"
            "3. Recuerda y utiliza el HISTORIAL DE LA CONVERSACIÓN para responder preguntas de seguimiento (ej. pronombres como 'allí', 'eso', 'esa sede', etc.).\n"
            "4. Menciona las fuentes oficiales, artículos o sedes relevantes según el contexto.\n"
            "5. Si el contexto no contiene la respuesta completa, indica cordialmente que el estudiante debe acudir a la taquilla de Control de Estudios o consultar en TernaNet.\n"
            "6. Responde siempre en español formal pero cercano."
        )

        user_prompt = f"{history_text}CONTEXTO OFICIAL DEL IUTECP:\n{context_text}\n\nNUEVA PREGUNTA DEL ESTUDIANTE: {query}"

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
                            answer = response.text
                            # Guardar en memoria de sesión
                            if session_id:
                                if session_id not in self.session_memories:
                                    self.session_memories[session_id] = []
                                self.session_memories[session_id].append({"role": "user", "content": query})
                                self.session_memories[session_id].append({"role": "assistant", "content": answer})
                                self.session_memories[session_id] = self.session_memories[session_id][-6:]
                            return {
                                "answer": answer,
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

    def transcribe_audio(self, audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
        """Transcribe notas de voz estudiantiles usando Gemini Multimodal."""
        if not gemini_client:
            raise RuntimeError("Gemini Client no está configurado.")
        
        from google.genai import types
        
        # Estandarizar mime_type para Gemini
        m = (mime_type or "audio/ogg").lower()
        if "mp3" in m or "mpeg" in m:
            clean_mime = "audio/mp3"
        elif "wav" in m:
            clean_mime = "audio/wav"
        elif "m4a" in m or "aac" in m:
            clean_mime = "audio/aac"
        elif "flac" in m:
            clean_mime = "audio/flac"
        else:
            clean_mime = "audio/ogg"

        part = types.Part.from_bytes(data=audio_bytes, mime_type=clean_mime)
        prompt = (
            "Eres el transcriptor del Asistente Académico del Instituto Universitario de Tecnología 'Elías Calixto Pompa' (IUTECP) en Venezuela.\n"
            "Tu tarea es transcribir textualmente en español la nota de voz o consulta enviada por el estudiante.\n\n"
            "GLOSARIO OBLIGATORIO Y REGLAS DE CORRECCIÓN FONÉTICA:\n"
            "• 'Cashea': Método de pago en cuotas del IUTECP. Si el estudiante dice 'caché', 'cashe', 'cajea' o 'cash', DEBES transcribirlo como 'Cashea'.\n"
            "• 'TernaNet': Sistema y portal del IUTECP. Si suena 'internet', 'ternanet', 'tierranet', transcribe 'TernaNet'.\n"
            "• 'IUTECP': Siglas del instituto.\n"
            "• 'PI': Pérdida de materia por inasistencias.\n"
            "• Sedes: Guatire, Caracas, Barcelona, Puerto La Cruz, Anzoátegui.\n"
            "• Carreras: Informática, Administración, Contaduría, Publicidad, Mercadeo.\n"
            "• Términos frecuentes: Servicio Comunitario, Pasantías, Solvencias, Pensum, Grado, Semestre, Materias preladas, Arancel.\n\n"
            "INSTRUCCIONES:\n"
            "1. Transcribe con total exactitud lo que dice el hablante, aplicando el glosario institucional para nombres propios y términos clave.\n"
            "2. Responde ÚNICAMENTE con la transcripción exacta. No agregues saludos, explicaciones, comillas ni texto introductorio."
        )
        try:
            from google.genai import types as genai_types
            config = genai_types.GenerateContentConfig(
                temperature=0.0
            )
            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[part, prompt],
                config=config
            )
            if response and response.text:
                return response.text.strip().strip('"').strip("'")
            return ""
        except Exception as e:
            print(f"[!] Error transcribiendo audio con Gemini ({GEMINI_MODEL}): {e}")
            raise


# Global instance
rag_engine = RAGEngine()

if __name__ == "__main__":
    test_q = "¿Cuáles son los requisitos de nuevo ingreso para bachilleres?"
    res = rag_engine.generate_response(test_q)
    print("Pregunta:", test_q)
    print("Respuesta:\n", res["answer"])
    print("Fuentes:", res["sources"])

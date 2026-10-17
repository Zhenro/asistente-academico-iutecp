import os
import re
import time
import json
import asyncio
from typing import List, Dict, Any, Optional, AsyncGenerator

try:
    from src.config import (
        TOP_K_RESULTS, GEMINI_API_KEY, 
        GEMINI_MODEL, OPENAI_API_KEY, OPENAI_MODEL
    )
    from src.ternanet import (
        get_student_by_cedula, detect_cedula_in_text,
        format_student_context_for_rag, normalize_cedula
    )
    import src.analytics as analytics
except ImportError:
    from config import (
        TOP_K_RESULTS, GEMINI_API_KEY, 
        GEMINI_MODEL, OPENAI_API_KEY, OPENAI_MODEL
    )
    from ternanet import (
        get_student_by_cedula, detect_cedula_in_text,
        format_student_context_for_rag, normalize_cedula
    )
    import analytics

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
        self.session_students: Dict[str, str] = {}  # session_id -> cedula
        self._query_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl_seconds = 3600  # 1 hora de validez
        self._max_cache_entries = 250

    def _make_cache_key(self, query: str, student: Optional[Dict[str, Any]]) -> str:
        clean = re.sub(r'[^a-zA-Z0-9áéíóúñÁÉÍÓÚÑ]', '', query.lower().strip())
        ced = student.get("cedula", "anon") if student else "anon"
        return f"{clean}::{ced}"

    def _get_from_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        if cache_key in self._query_cache:
            entry = self._query_cache[cache_key]
            if time.time() - entry["timestamp"] < self._cache_ttl_seconds:
                return entry["data"]
            else:
                del self._query_cache[cache_key]
        return None

    def _save_to_cache(self, cache_key: str, data: Dict[str, Any]):
        if len(self._query_cache) >= self._max_cache_entries:
            oldest_key = next(iter(self._query_cache))
            del self._query_cache[oldest_key]
        self._query_cache[cache_key] = {
            "timestamp": time.time(),
            "data": data
        }

    def set_session_student(self, session_id: str, cedula: str):
        """Asocia una cédula de estudiante de TernaNet a una sesión."""
        if session_id and cedula:
            clean = normalize_cedula(cedula)
            self.session_students[session_id] = clean

    def get_session_student(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene los datos de TernaNet del estudiante vinculado a la sesión."""
        if not session_id or session_id not in self.session_students:
            return None
        return get_student_by_cedula(self.session_students[session_id])

    def clear_session(self, session_id: str):
        if session_id in self.session_memories:
            del self.session_memories[session_id]
        if session_id in self.session_students:
            del self.session_students[session_id]

    def reload_documents(self) -> int:
        """Limpia la memoria caché y recarga todos los documentos PDF activos."""
        self._cached_chunks = None
        self._query_cache.clear()
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

    def generate_response(self, query: str, session_id: str = None, student_cedula: str = None) -> Dict[str, Any]:
        # Detección / Vinculación de Estudiante TernaNet
        active_student = None
        if student_cedula:
            self.set_session_student(session_id, student_cedula)
        elif session_id:
            # Chequear si en la pregunta se menciona una cédula (ej. 'mi cedula es 27346776')
            detected = detect_cedula_in_text(query)
            if detected:
                self.set_session_student(session_id, detected)

        if session_id:
            active_student = self.get_session_student(session_id)
        elif student_cedula:
            active_student = get_student_by_cedula(student_cedula)

        # Obtener historial de la sesión si existe
        history = self.session_memories.get(session_id, []) if session_id else []

        # ⚡ Optimización 1: In-Memory Cache Lookup (Respuesta instantánea < 10ms para consultas repetidas)
        cache_key = self._make_cache_key(query, active_student)
        cached_result = self._get_from_cache(cache_key)
        if cached_result and not history:
            if session_id:
                if session_id not in self.session_memories:
                    self.session_memories[session_id] = []
                self.session_memories[session_id].append({"role": "user", "content": query})
                self.session_memories[session_id].append({"role": "assistant", "content": cached_result["answer"]})
                self.session_memories[session_id] = self.session_memories[session_id][-6:]
            return {
                **cached_result,
                "student": active_student,
                "cached": True
            }

        # 1. Retrieve relevant contexts (considerando contexto de historial)
        contexts = self.retrieve(query, history=history)
        
        if not contexts:
            msg = "No encontré información relevante en los reglamentos y guías oficiales del IUTECP para tu consulta. Te sugiero dirigirte a la Coordinación de Control de Estudios en la sede correspondiente."
            if active_student:
                msg = f"Hola, {active_student.get('nombre')}. {msg}"
            return {
                "answer": msg,
                "sources": [],
                "student": active_student
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

        student_prompt_inject = ""
        if active_student:
            student_context = format_student_context_for_rag(active_student)
            student_prompt_inject = f"{student_context}\n\n"
            system_instruction += (
                "\n\n=======================================================\n"
                "ATENCIÓN - PERFIL DEL ESTUDIANTE IDENTIFICADO EN TERNANET:\n"
                f"{student_context}\n"
                "DIRECTRICES OBLIGATORIAS PARA ESTE ESTUDIANTE:\n"
                f"1. Dirígete cordialmente al estudiante por su nombre ('{active_student.get('nombre')}').\n"
                "2. Cruza los requisitos y normativas del IUTECP (créditos exigidos, materias cursadas, semestres, prelaciones, servicio comunitario, pasantías, cuotas de Cashea y solvencias) DIRECTAMENTE con los datos reales de su expediente.\n"
                "   - Ejemplo Servicio Comunitario: En el IUTECP se exige tener aprobado al menos el 50% de los créditos de la carrera. Verifica su porcentaje aprobado en el expediente e indícale con precisión si ya puede inscribirlo o cuántos créditos le faltan.\n"
                "   - Ejemplo Pasantías: Revisa si cumple con el avance de semestres/créditos y su estatus de pasantías.\n"
                "   - Ejemplo Pagos/Cashea: Si consulta sobre pagos o matrícula, dile con precisión sus cuotas pagadas/pendientes y fechas.\n"
                "3. Ofrece una orientación personalizada, motivadora y clara.\n"
                "=======================================================\n"
            )

        user_prompt = f"{history_text}{student_prompt_inject}CONTEXTO OFICIAL DEL IUTECP:\n{context_text}\n\nNUEVA PREGUNTA DEL ESTUDIANTE: {query}"

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
                            
                            # ⚡ Guardar en Caché Inteligente
                            self._save_to_cache(cache_key, {
                                "answer": answer,
                                "sources": unique_sources
                            })
                            return {
                                "answer": answer,
                                "sources": unique_sources,
                                "student": active_student
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
                answer = completion.choices[0].message.content
                self._save_to_cache(cache_key, {"answer": answer, "sources": unique_sources})
                return {
                    "answer": answer,
                    "sources": unique_sources,
                    "student": active_student
                }
            except Exception as e:
                print(f"[!] Error al invocar OpenAI API: {e}")

        # 4. Strategy C: High-Fidelity Local Synthesis (Fallback sin API key)
        answer = self._synthesize_local(query, contexts, student=active_student)
        self._save_to_cache(cache_key, {"answer": answer, "sources": unique_sources})
        return {
            "answer": answer,
            "sources": unique_sources,
            "student": active_student
        }

    async def generate_response_stream(
        self, query: str, session_id: str = None, student_cedula: str = None
    ) -> AsyncGenerator[str, None]:
        """Transmite la respuesta token por token en tiempo real (Server-Sent Events)."""
        active_student = None
        if student_cedula:
            self.set_session_student(session_id, student_cedula)
        elif session_id:
            detected = detect_cedula_in_text(query)
            if detected:
                self.set_session_student(session_id, detected)

        if session_id:
            active_student = self.get_session_student(session_id)
        elif student_cedula:
            active_student = get_student_by_cedula(student_cedula)

        # Enviar evento inicial de metadatos
        yield f"data: {json.dumps({'type': 'start', 'student': active_student})}\n\n"

        history = self.session_memories.get(session_id, []) if session_id else []
        cache_key = self._make_cache_key(query, active_student)
        cached_result = self._get_from_cache(cache_key)

        # ⚡ Si está en caché: transmitir en ráfagas ultra-rápidas
        if cached_result and not history:
            full_text = cached_result["answer"]
            words = full_text.split(" ")
            for i in range(0, len(words), 5):
                chunk = " ".join(words[i:i+5]) + " "
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
                await asyncio.sleep(0.015)

            if session_id:
                if session_id not in self.session_memories:
                    self.session_memories[session_id] = []
                self.session_memories[session_id].append({"role": "user", "content": query})
                self.session_memories[session_id].append({"role": "assistant", "content": full_text})
                self.session_memories[session_id] = self.session_memories[session_id][-6:]

            query_id = analytics.record_query(
                query=query,
                channel="web",
                answer=full_text,
                sources=cached_result.get("sources", [])
            )
            yield f"data: {json.dumps({'type': 'done', 'sources': cached_result.get('sources', []), 'student': active_student, 'cached': True, 'query_id': query_id})}\n\n"
            return

        contexts = self.retrieve(query, history=history)
        if not contexts:
            msg = "No encontré información relevante en los reglamentos y guías oficiales del IUTECP para tu consulta. Te sugiero dirigirte a la Coordinación de Control de Estudios en la sede correspondiente."
            if active_student:
                msg = f"Hola, {active_student.get('nombre')}. {msg}"
            
            query_id = analytics.record_query(
                query=query,
                channel="web",
                answer=msg,
                sources=[]
            )
            yield f"data: {json.dumps({'type': 'token', 'content': msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'sources': [], 'student': active_student, 'query_id': query_id})}\n\n"
            return

        context_text = "\n\n".join([
            f"[Fuente: {c['source']} - Pág. {c['page']}]\n{c['content']}"
            for c in contexts
        ])
        unique_sources = list({f"{c['source']} (pág. {c['page']})" for c in contexts})

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
            "3. Recuerda y utiliza el HISTORIAL DE LA CONVERSACIÓN para responder preguntas de seguimiento.\n"
            "4. Menciona las fuentes oficiales, artículos o sedes relevantes según el contexto.\n"
            "5. Si el contexto no contiene la respuesta completa, indica cordialmente que el estudiante debe acudir a Control de Estudios o consultar en TernaNet.\n"
            "6. Responde siempre en español formal pero cercano."
        )

        student_prompt_inject = ""
        if active_student:
            student_context = format_student_context_for_rag(active_student)
            student_prompt_inject = f"{student_context}\n\n"
            system_instruction += (
                "\n\n=======================================================\n"
                "ATENCIÓN - PERFIL DEL ESTUDIANTE IDENTIFICADO EN TERNANET:\n"
                f"{student_context}\n"
                "DIRECTRICES OBLIGATORIAS PARA ESTE ESTUDIANTE:\n"
                f"1. Dirígete cordialmente al estudiante por su nombre ('{active_student.get('nombre')}').\n"
                "2. Cruza los requisitos y normativas del IUTECP DIRECTAMENTE con los datos reales de su expediente.\n"
                "3. Ofrece una orientación personalizada, motivadora y clara.\n"
                "=======================================================\n"
            )

        user_prompt = f"{history_text}{student_prompt_inject}CONTEXTO OFICIAL DEL IUTECP:\n{context_text}\n\nNUEVA PREGUNTA DEL ESTUDIANTE: {query}"
        full_prompt = f"{system_instruction}\n\n{user_prompt}"

        current_api_key = os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY
        stream_success = False
        full_answer = ""

        if current_api_key and gemini_client:
            model_name = os.getenv("GEMINI_MODEL") or GEMINI_MODEL or "gemini-flash-lite-latest"
            models_to_try = [model_name, "gemini-3.5-flash", "gemini-flash-lite-latest"]
            for candidate_model in models_to_try:
                try:
                    stream = gemini_client.models.generate_content_stream(
                        model=candidate_model,
                        contents=full_prompt
                    )
                    for chunk in stream:
                        if chunk.text:
                            full_answer += chunk.text
                            yield f"data: {json.dumps({'type': 'token', 'content': chunk.text})}\n\n"
                    stream_success = True
                    break
                except Exception as e:
                    print(f"[!] Error streaming con {candidate_model}: {e}")

        if not stream_success:
            res = self.generate_response(query, session_id=session_id, student_cedula=student_cedula)
            full_answer = res["answer"]
            words = full_answer.split(" ")
            for i in range(0, len(words), 5):
                chunk = " ".join(words[i:i+5]) + " "
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
                await asyncio.sleep(0.015)

        if session_id:
            if session_id not in self.session_memories:
                self.session_memories[session_id] = []
            self.session_memories[session_id].append({"role": "user", "content": query})
            self.session_memories[session_id].append({"role": "assistant", "content": full_answer})
            self.session_memories[session_id] = self.session_memories[session_id][-6:]

        self._save_to_cache(cache_key, {
            "answer": full_answer,
            "sources": unique_sources
        })

        query_id = analytics.record_query(
            query=query,
            channel="web",
            answer=full_answer,
            sources=unique_sources
        )

        yield f"data: {json.dumps({'type': 'done', 'sources': unique_sources, 'student': active_student, 'query_id': query_id})}\n\n"

    def _synthesize_local(self, query: str, contexts: List[Dict[str, Any]], student: Optional[Dict[str, Any]] = None) -> str:
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
        if student:
            intro = f"¡Hola, **{student.get('nombre')}**! 🎓 Revisando tu expediente en **TernaNet** ({student.get('carrera')}, {student.get('semestre')}do/to semestre) y la documentación oficial del **IUTECP**:\n\n"
        
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

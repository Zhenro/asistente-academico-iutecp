"""
Módulo de Analítica, Métricas de Satisfacción y Detección de Vacíos Normativos para el IUTECP.
"""
import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from src.config import DATA_DIR
except ImportError:
    from config import DATA_DIR

ANALYTICS_FILE = DATA_DIR / "analytics.json"


def _load_data() -> Dict[str, Any]:
    if not ANALYTICS_FILE.exists():
        initial = {"queries": []}
        _save_data(initial)
        return initial
    try:
        with open(ANALYTICS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"queries": []}


def _save_data(data: Dict[str, Any]):
    try:
        with open(ANALYTICS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[!] Error guardando analytics.json: {e}")


def _classify_topic(query: str) -> str:
    q = query.lower()
    if any(k in q for k in ["cashea", "cuota", "pago", "pagar", "arancel", "costo", "precio", "banco", "transferencia"]):
        return "Pagos y Cashea"
    if any(k in q for k in ["sede", "guatire", "caracas", "barcelona", "puerto la cruz", "anzoategui", "ubicacion", "telefono", "direccion"]):
        return "Sedes y Contacto"
    if any(k in q for k in ["nota", "pi", "inasistencia", "corte", "aprobar", "aprobatoria", "evaluacion", "examen"]):
        return "Notas y Reglamentos (PI)"
    if any(k in q for k in ["ingreso", "bachiller", "requisito", "recaudo", "carpeta", "inscripcion", "inscribir", "ternanet"]):
        return "Admisión y TernaNet"
    if any(k in q for k in ["servicio comunitario", "comunitario", "pasantia", "grado", "solvencia", "titulo"]):
        return "Servicio Comunitario y Grado"
    if any(k in q for k in ["carrera", "informatica", "administracion", "contaduria", "mercadeo", "publicidad", "turno", "sabatino", "nocturno"]):
        return "Oferta Académica y Turnos"
    return "Otras Consultas"


def _is_knowledge_gap(answer: str, sources: List[str]) -> bool:
    """Detecta si la respuesta del asistente indica un vacío normativo o falta de datos."""
    ans = answer.lower()
    if not sources or len(sources) == 0:
        return True
    indicators = [
        "no dispongo de información oficial",
        "no se encuentra en las normativas",
        "no se especifica en los reglamentos",
        "no aparece en los documentos",
        "te sugiero consultar directamente en control de estudios",
        "no cuento con esa información",
        "no tengo registro de",
        "no está disponible en las fuentes oficiales"
    ]
    return any(ind in ans for ind in indicators)


def record_query(query: str, channel: str, answer: str, sources: List[str]) -> str:
    """Registra una consulta en la base de datos de analítica."""
    query_id = "q_" + uuid.uuid4().hex[:10]
    topic = _classify_topic(query)
    is_gap = _is_knowledge_gap(answer, sources)
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    entry = {
        "id": query_id,
        "timestamp": now,
        "channel": channel,
        "query": query.strip(),
        "topic": topic,
        "is_gap": is_gap,
        "sources": sources,
        "rating": None,
        "comment": None
    }

    data = _load_data()
    data.setdefault("queries", [])
    data["queries"].append(entry)
    
    # Mantener máximo 500 registros para optimizar memoria y disco
    if len(data["queries"]) > 500:
        data["queries"] = data["queries"][-500:]

    _save_data(data)
    return query_id


def record_feedback(query_id: str, rating: str, comment: Optional[str] = None) -> bool:
    """Registra calificación (up o down) para una consulta dada."""
    data = _load_data()
    queries = data.get("queries", [])
    for q in reversed(queries):
        if q.get("id") == query_id:
            q["rating"] = rating
            if comment:
                q["comment"] = comment.strip()
            _save_data(data)
            return True
    return False


def get_analytics_summary() -> Dict[str, Any]:
    """Genera métricas consolidadas para el panel de administración."""
    data = _load_data()
    queries = data.get("queries", [])
    total = len(queries)

    web_count = sum(1 for q in queries if q.get("channel") == "web")
    tg_count = sum(1 for q in queries if q.get("channel") == "telegram")

    rated = [q for q in queries if q.get("rating")]
    up_count = sum(1 for q in rated if q.get("rating") == "up")
    down_count = sum(1 for q in rated if q.get("rating") == "down")
    satisfaction_rate = round((up_count / len(rated) * 100), 1) if rated else 100.0

    # Conteo por temas
    topics_count: Dict[str, int] = {}
    for q in queries:
        t = q.get("topic", "Otras Consultas")
        topics_count[t] = topics_count.get(t, 0) + 1

    sorted_topics = [
        {"topic": k, "count": v, "percent": round((v / total * 100), 1) if total else 0}
        for k, v in sorted(topics_count.items(), key=lambda x: x[1], reverse=True)
    ]

    # Vacíos informativos detectados
    gaps = [
        {
            "id": q.get("id"),
            "timestamp": q.get("timestamp"),
            "query": q.get("query"),
            "channel": q.get("channel"),
            "topic": q.get("topic")
        }
        for q in reversed(queries) if q.get("is_gap")
    ][:20]

    # Consultas recientes
    recent = [
        {
            "id": q.get("id"),
            "timestamp": q.get("timestamp"),
            "query": q.get("query"),
            "channel": q.get("channel"),
            "topic": q.get("topic"),
            "rating": q.get("rating"),
            "is_gap": q.get("is_gap")
        }
        for q in reversed(queries)
    ][:30]

    return {
        "total_queries": total,
        "channels": {
            "web": web_count,
            "telegram": tg_count
        },
        "satisfaction": {
            "rate": satisfaction_rate,
            "total_rated": len(rated),
            "up": up_count,
            "down": down_count
        },
        "topics": sorted_topics,
        "gaps": gaps,
        "total_gaps": len([q for q in queries if q.get("is_gap")]),
        "recent_queries": recent
    }


def export_csv() -> str:
    """Genera un archivo CSV en texto plano con el registro histórico de consultas."""
    data = _load_data()
    queries = data.get("queries", [])
    lines = ["ID,Fecha,Canal,Tema,Consulta,Vacio_Normativo,Calificacion,Comentario"]
    for q in queries:
        qid = q.get("id", "")
        ts = q.get("timestamp", "")
        ch = q.get("channel", "")
        top = f'"{q.get("topic", "")}"'
        query_esc = f'"{q.get("query", "").replace(chr(34), chr(39))}"'
        gap = "SI" if q.get("is_gap") else "NO"
        rat = q.get("rating") or "Sin calificar"
        comm = f'"{q.get("comment", "").replace(chr(34), chr(39))}"' if q.get("comment") else ""
        lines.append(f"{qid},{ts},{ch},{top},{query_esc},{gap},{rat},{comm}")
    return "\n".join(lines)


def reset_analytics():
    """Borra el historial de analítica."""
    _save_data({"queries": []})

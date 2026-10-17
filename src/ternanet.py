"""
Módulo de Integración y Simulación de TernaNet para el IUTECP.
Permite autenticación y consulta de expedientes académicos por Cédula de Identidad.
"""
import re
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from src.config import DATA_DIR
except ImportError:
    from config import DATA_DIR

STUDENTS_FILE = DATA_DIR / "students.json"


def normalize_cedula(cedula_raw: str) -> str:
    """Limpia una cédula eliminando puntos, guiones, espacios y prefijos V/E."""
    if not cedula_raw:
        return ""
    return re.sub(r"[^0-9]", "", str(cedula_raw))


def load_students() -> List[Dict[str, Any]]:
    """Carga los expedientes de estudiantes desde students.json."""
    if not STUDENTS_FILE.exists():
        return []
    try:
        with open(STUDENTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] Error leyendo students.json: {e}")
        return []


def get_student_by_cedula(cedula: str) -> Optional[Dict[str, Any]]:
    """Busca un estudiante en TernaNet por su número de cédula."""
    clean = normalize_cedula(cedula)
    if not clean:
        return None
    
    students = load_students()
    for s in students:
        if normalize_cedula(s.get("cedula", "")) == clean:
            return s
    return None


def detect_cedula_in_text(text: str) -> Optional[str]:
    """
    Detecta si en un mensaje el estudiante menciona su cédula.
    Ejemplos: 'mi cédula es 27.346.776', 'soy V-28416131', '30566388', '/estudiante 30155465'
    """
    if not text:
        return None
    
    # 1. Comandos directos tipo /estudiante 12345678 o /cedula 12345678
    cmd_match = re.search(r"/(?:estudiante|cedula|login)\s+([0-9\.\-vVeE]+)", text)
    if cmd_match:
        cand = normalize_cedula(cmd_match.group(1))
        if len(cand) >= 6:
            return cand

    # 2. Patrones con palabras clave: cédula / ci / soy / expediente / v-
    patterns = [
        r"(?:c[eé]dula|ci|c\.i\.|identidad|expediente|soy|alumno|estudiante)[\s:=]+([0-9\.\-vVeE]{6,12})",
        r"\b[vVeE]?[\-\.\s]?([0-9]{1,2}\.[0-9]{3}\.[0-9]{3})\b",
        r"\b[vVeE][\-\s]?([0-9]{7,8})\b"
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            cand = normalize_cedula(m.group(1))
            if 6 <= len(cand) <= 9:
                return cand

    # 3. Números aislados de 7 u 8 dígitos que correspondan a cédulas venezolanas
    num_matches = re.findall(r"\b([0-9]{7,8})\b", text)
    for num in num_matches:
        if get_student_by_cedula(num):
            return num

    return None


def format_student_context_for_rag(student: Dict[str, Any]) -> str:
    """
    Genera un bloque de contexto institucional estructurado sobre el estudiante
    para inyectarlo en el prompt de Gemini junto a las normativas de RAG.
    """
    if not student:
        return ""

    materias_str = ", ".join(f"{m['nombre']} (Nota act: {m.get('nota_acumulada', '-')})" for m in student.get("materias_actuales", []))
    if not materias_str:
        materias_str = "Ninguna (Plan de estudios culminado / Graduando)"

    sc = student.get("servicio_comunitario", {})
    if isinstance(sc, dict):
        sc_desc = f"{sc.get('estatus')} - {sc.get('observacion') or sc.get('proyecto', '')}"
    else:
        sc_desc = str(sc)

    pas = student.get("pasantias", {})
    if isinstance(pas, dict):
        pas_desc = f"{pas.get('estatus')} - {pas.get('empresa', '')} {pas.get('observacion', '')}"
    else:
        pas_desc = str(pas)

    solv = student.get("solvencias", {})
    solv_list = []
    if isinstance(solv, dict):
        for k, v in solv.items():
            solv_list.append(f"{k.capitalize()}: {'Solvente' if v else 'Pendiente'}")
    solv_str = ", ".join(solv_list)

    cashea_str = "No aplica (Plan regular)"
    if student.get("cashea"):
        c = student["cashea"]
        cashea_str = f"{c.get('plan')}, Cuotas pagadas: {c.get('cuotas_pagadas')}/{c.get('cuotas_totales')}, Próximo vencimiento: {c.get('proximo_vencimiento')}"

    return (
        f"\n--- INFORMACIÓN DEL EXPEDIENTE DEL ESTUDIANTE (TERNANET OFICIAL) ---\n"
        f"• Nombre del Estudiante: {student.get('nombre')}\n"
        f"• Cédula: {student.get('cedula_formato')} ({student.get('cedula')})\n"
        f"• Carrera: {student.get('carrera')} (Sede: {student.get('sede')})\n"
        f"• Semestre en curso: {student.get('semestre')}do/to Semestre (Turno: {student.get('turno')})\n"
        f"• Créditos aprobados: {student.get('creditos_aprobados')} de {student.get('creditos_totales')} ({student.get('porcentaje_carrera')}%)\n"
        f"• Promedio ponderado acumulado: {student.get('promedio')} / 20\n"
        f"• Materias que cursa actualmente: {materias_str}\n"
        f"• Estatus Servicio Comunitario: {sc_desc}\n"
        f"• Estatus Pasantías: {pas_desc}\n"
        f"• Estatus Arancelario y Cashea: {student.get('estatus_arancelario')} | Cashea: {cashea_str}\n"
        f"• Solvencias Institucionales: {solv_str}\n"
        f"----------------------------------------------------------------------\n"
    )

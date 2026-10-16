# Asistente Virtual Inteligente de Consultas Académicas (IUTECP)

Sistema de atención y resolución de consultas académicas e institucionales basado en **Generación Aumentada por Recuperación (RAG)**, diseñado para la comunidad estudiantil del **Instituto Universitario de Tecnología "Elías Calixto Pompa" (IUTECP)**.

---

## 🎯 Alineación con los Objetivos del Proyecto Universitario

* **Objetivo 1 (Diagnóstico):** Identificación de inquietudes y trámites frecuentes (admisión, TernaNet, evaluación continua, inasistencias, servicio comunitario, pasantías y grado).
* **Objetivo 2 (Datos y Arquitectura):** Indexación vectorial y almacenamiento en **ChromaDB** a partir de documentos institucionales oficiales generados en PDF.
* **Objetivo 3 (Desarrollo e Integración):** Backend asíncrono con **FastAPI** e interfaz de usuario web responsiva para interacción en tiempo real.
* **Objetivo 4 (Evaluación y Validación):** Mecanismo de trazabilidad con citación de fuentes oficiales y batería de pruebas con casos reales de estudiantes.

---

## 🏛️ Documentación Oficial Incorporada (`data/documents/`)

Generada a partir de la información institucional del IUTECP (sitio web, sistema TernaNet, normativas venezolanas y canales oficiales):

1. **`01_Guia_Admisiones_Inscripcion_IUTECP.pdf`**:
   * Requisitos de nuevo ingreso en carpeta marrón (título de bachiller, notas, fotos, cédula, OPSU).
   * Procedimiento de 5 pasos en plataforma TernaNet.
   * Sedes: Guatire (C.C. Daymar), Caracas (El Paraíso), Puerto La Cruz, Barcelona y El Tigre.
   * Pagos por transferencia y financiamiento en cuotas con **Cashea**. Turnos diurno y sabatino.
2. **`02_Reglamento_Evaluacion_Estudiantil_IUTECP.pdf`**:
   * Evaluación continua (3 cortes: 30%, 30%, 40%).
   * Escala de 1 a 20 puntos, nota mínima aprobatoria: 10 puntos (redondeo de 0.5 solo en nota final).
   * Límite de inasistencias del 25% (Pérdida por Inasistencia - PI).
   * Normativa de prelaciones y retiro de asignaturas (primeras 3 semanas).
3. **`03_Oferta_Academica_Carreras_IUTECP.pdf`**:
   * Programas TSU: Informática, Diseño Gráfico, Administración, Contaduría, Relaciones Industriales, Turismo, Fisioterapia y Enfermería.
   * Opciones de prosecución a Licenciaturas e Ingenierías.
4. **`04_Normativa_Servicio_Comunitario_Pasantias_Grado_IUTECP.pdf`**:
   * Servicio Comunitario obligatorio (120 horas académicas, requisito de 50% de UC aprobadas).
   * Pasantías y Acreditación de Experiencia Laboral técnica (> 1 año de trabajo comprobable).
   * Requisitos para acto de grado (solvencias de Control de Estudios, Biblioteca, Caja y fondo negro).
5. **`05_Calendario_Academico_Periodos_IUTECP.pdf`**:
   * Estructura de los 3 períodos regulares anuales (I, II y III).
   * Cronograma por semanas de inscripción, evaluación, entrega de solvencias y actos de grado.

---

## 🚀 Inicio Rápido (1 solo comando)

### 1. Iniciar el Asistente
```bash
python run.py
```
El sistema detectará automáticamente la base de datos vectorial y abrirá el servidor en:
👉 **`http://127.0.0.1:8000`**

### 2. Configurar Clave de IA (Opcional pero recomendado para respuestas generativas)
Abre el archivo [`.env`](.env) y agrega tu clave gratuita de Google Gemini:
```env
MODEL_PROVIDER=gemini
GEMINI_API_KEY=tu_clave_de_aistudio_aqui
GEMINI_MODEL=gemini-1.5-flash
```
*(Si no colocas una clave API, el sistema funcionará automáticamente en modo síntesis local de alta fidelidad, recuperando y citando los fragmentos oficiales).*

---

## 📁 Estructura del Proyecto

```text
CIT/
├── data/
│   ├── documents/          # Los 5 PDFs normativos e institucionales oficiales
│   └── chroma_db/          # Base de datos vectorial persistente (ChromaDB)
├── frontend/
│   └── index.html          # Interfaz web moderna con botones de consulta rápida
├── scripts/
│   └── generate_documents.py # Generador de los PDFs institucionales del IUTECP
├── src/
│   ├── config.py           # Variables de entorno y rutas
│   ├── ingestion.py        # Extracción de PDFs, chunking y almacenamiento vectorial
│   ├── rag_engine.py       # Motor RAG con recuperación semántica y LLM
│   └── api.py              # API FastAPI y servidor web
├── .env                    # Configuración de claves y modelos
├── requirements.txt        # Dependencias de Python
├── run.py                  # Script lanzador principal
└── README.md
```

---

## 📊 Validación de Casos Reales (Objetivo 4)

El asistente incluye sugerencias precargadas para validar los casos de consulta más comunes:
1. Requisitos de ingreso para bachilleres.
2. Sedes activas y canales de contacto.
3. Métodos de pago (Cashea y transferencias) y turnos.
4. Nota mínima aprobatoria y límite de inasistencias (25%).
5. Requisitos para Servicio Comunitario y Acto de Grado.

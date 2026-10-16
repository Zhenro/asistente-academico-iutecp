import os
from fpdf import FPDF

class InstitutionalPDF(FPDF):
    def __init__(self, title_text, document_code):
        super().__init__()
        self.title_text = title_text
        self.document_code = document_code
        self.set_auto_page_break(auto=True, margin=20)
        self.add_page()

    def header(self):
        self.set_font("helvetica", "B", 10)
        self.set_text_color(20, 50, 100)
        self.cell(0, 6, "INSTITUTO UNIVERSITARIO DE TECNOLOGÍA 'ELÍAS CALIXTO POMPA' (IUTECP)", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("helvetica", "I", 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, "Dirección Académica y Coordinación de Control de Estudios - Documentación Oficial", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(20, 50, 100)
        self.set_line_width(0.4)
        self.line(15, self.get_y() + 2, 195, self.get_y() + 2)
        self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"IUTECP Oficial - Código: {self.document_code} | Página {self.page_no()}/{{nb}}", align="C")

    def chapter_title(self, label):
        self.set_font("helvetica", "B", 14)
        self.set_text_color(15, 40, 90)
        self.cell(0, 10, label, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(200, 200, 200)
        self.set_line_width(0.2)
        self.line(15, self.get_y(), 195, self.get_y())
        self.ln(3)

    def section_title(self, label):
        self.set_font("helvetica", "B", 11)
        self.set_text_color(30, 70, 130)
        self.cell(0, 8, label, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body_paragraph(self, text):
        self.set_font("helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 6, text)
        self.ln(2)

    def bullet_item(self, bold_prefix, text):
        self.set_font("helvetica", "B", 10)
        self.set_text_color(30, 30, 30)
        self.cell(6, 6, chr(149), align="R")
        self.cell(len(bold_prefix) * 2.3 + 2, 6, f" {bold_prefix} ", align="L")
        self.set_font("helvetica", "", 10)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 6, text)
        self.ln(1)


def create_doc1(output_dir):
    pdf = InstitutionalPDF("GUIA DE ADMISIONES E INSCRIPCION", "IUTECP-ADM-2026")
    pdf.chapter_title("GUÍA OFICIAL DE ADMISIONES, INSCRIPCIÓN Y NORMAS DE MATRÍCULA")
    
    pdf.section_title("1. Información General y Sedes del IUTECP")
    pdf.body_paragraph(
        "El Instituto Universitario de Tecnología 'Elías Calixto Pompa' (IUTECP) es una institución universitaria venezolana "
        "dedicada a la formación de Técnicos Superiores Universitarios (TSU) y prosecución académica. La institución cuenta con "
        "las siguientes sedes activas:"
    )
    pdf.bullet_item("Sede Guatire:", "Av. Principal, C.C. Daymar, Nivel P1, Local P1-50, Urbanización Valle Arriba, Sector Quemaito, Guatire, Estado Miranda. Teléfonos: 0412-8973480 / 0412-7148130.")
    pdf.bullet_item("Sede Caracas:", "Av. Estadio, Edificio IUTECP, adyacente al Estadio Nacional Brígido Iriarte, El Paraíso, Caracas, Dto. Capital.")
    pdf.bullet_item("Sedes Oriente:", "Sede Puerto La Cruz, Sede Barcelona y Sede El Tigre (Estado Anzoátegui).")
    
    pdf.ln(3)
    pdf.section_title("2. Requisitos de Inscripción para Nuevos Ingresos (Bachilleres)")
    pdf.body_paragraph(
        "Todo aspirante que desee cursar estudios regulares de TSU en el IUTECP debe presentar en carpeta marrón tamaño oficio "
        "con gancho los siguientes recaudos obligatorios ante la Coordinación de Control de Estudios:"
    )
    pdf.bullet_item("1. Cédula de Identidad:", "Original y dos (2) copias ampliadas y legibles.")
    pdf.bullet_item("2. Título de Bachiller:", "Original a la vista y fondo negro autenticado y certificado.")
    pdf.bullet_item("3. Notas Certificadas:", "De 1ero a 5to año de educación media / diversificada (original y copia).")
    pdf.bullet_item("4. Partida de Nacimiento:", "Copia en buen estado (y original a la vista).")
    pdf.bullet_item("5. Fotografías:", "Tres (3) fotos recientes tipo carnet en fondo blanco.")
    pdf.bullet_item("6. Certificado OPSU / SNI:", "Constancia de inscripción o asignación del Sistema Nacional de Ingreso.")
    pdf.bullet_item("7. Planilla TernaNet:", "Comprobante emitido tras completar el registro de aspirante en el portal en línea.")
    
    pdf.ln(3)
    pdf.section_title("3. Procedimiento Digital en la Plataforma TernaNet")
    pdf.body_paragraph(
        "La gestión académica del IUTECP se realiza a través de la plataforma TernaNet (www.iutecp.net / portal TernaNet). "
        "El estudiante debe seguir estos pasos:"
    )
    pdf.bullet_item("Paso 1 - Registro de Aspirante:", "Crear usuario en TernaNet con correo electrónico activo y número de cédula.")
    pdf.bullet_item("Paso 2 - Carga Digital de Recaudos:", "Adjuntar documentos escaneados en formato JPG o PNG legibles.")
    pdf.bullet_item("Paso 3 - Selección de Materias:", "Elegir las asignaturas correspondientes según la oferta del período y el turno deseado.")
    pdf.bullet_item("Paso 4 - Validación de Prelaciones:", "El sistema verifica que no existan materias pendientes del ciclo anterior. Si una materia aparece bloqueada (en color rojo/naranja), el estudiante debe dirigirse a Control de Estudios.")
    pdf.bullet_item("Paso 5 - Comprobante de Inscripción:", "Generar la orden de pago y la Planilla Oficial de Inscripción.")

    pdf.ln(3)
    pdf.section_title("4. Horarios, Modalidades y Métodos de Pago")
    pdf.body_paragraph(
        "El IUTECP ofrece tres modalidades de horario: Turno Mañana (7:30 am a 12:30 pm), Turno Tarde (1:00 pm a 5:30 pm) y Turno Sabatino "
        "orientado a profesionales y trabajadores (7:30 am a 4:30 pm los días sábados). También se cuenta con soporte en el Campus Virtual (academia.campusiutecp.com)."
    )
    pdf.body_paragraph(
        "Opciones de Pago Oficiales: Pagos mediante transferencias bancarias a las cuentas institucionales oficiales, taquillas de caja en sede, "
        "y opción de financiamiento fraccionado de matrícula y mensualidades a través de la aplicación Cashea."
    )
    
    path = os.path.join(output_dir, "01_Guia_Admisiones_Inscripcion_IUTECP.pdf")
    pdf.output(path)
    print(f"Generado: {path}")


def create_doc2(output_dir):
    pdf = InstitutionalPDF("REGLAMENTO DE EVALUACION ESTUDIANTIL", "IUTECP-REG-EVAL")
    pdf.chapter_title("REGLAMENTO GENERAL DE EVALUACIÓN DEL RENDIMIENTO ESTUDIANTIL")

    pdf.section_title("Capítulo I: Principios de la Evaluación y Planificación Docente")
    pdf.body_paragraph(
        "Artículo 1. La evaluación del rendimiento estudiantil en el IUTECP es continua, formativa, acumulativa, integral y sistemática. "
        "Tiene como propósito certificar el logro de las competencias de cada unidad curricular."
    )
    pdf.body_paragraph(
        "Artículo 2. En la primera semana de clases de cada período, el docente debe presentar y discutir con los estudiantes el "
        "Plan de Evaluación, el cual se registrará en el sistema institucional TernaNet. Ninguna actividad evaluativa individual "
        "podrá tener una ponderación mayor al 30% del total de la asignatura."
    )

    pdf.ln(3)
    pdf.section_title("Capítulo II: Escala de Calificaciones y Criterios de Aprobación")
    pdf.body_paragraph(
        "Artículo 3. La escala de calificación es numérica, de uno (1) a veinte (20) puntos, siendo diez (10) puntos la calificación "
        "mínima aprobatoria en cualquier unidad curricular."
    )
    pdf.body_paragraph(
        "Artículo 4. En la calificación definitiva de la asignatura, las fracciones iguales o superiores a cero punto cinco (0.5) puntos "
        "se redondearán al número entero inmediatamente superior. Este redondeo solo aplica para la nota final definitiva."
    )
    pdf.body_paragraph(
        "Artículo 5. Los cortes de notas se dividen en tres lapsos continuos durante el período académico: Primer Corte (30%), "
        "Segundo Corte (30%) y Tercer Corte (40%). Los docentes deben cargar las calificaciones en TernaNet dentro de los cinco (5) días "
        "hábiles posteriores a la aplicación de cada evaluación."
    )

    pdf.ln(3)
    pdf.section_title("Capítulo III: Régimen de Asistencia y Pérdida por Inasistencias (PI)")
    pdf.body_paragraph(
        "Artículo 6. La asistencia a las actividades académicas presenciales, laboratorios y sesiones sincrónicas es de carácter obligatorio."
    )
    pdf.body_paragraph(
        "Artículo 7. El estudiante que acumule un porcentaje de inasistencias injustificadas superior al veinticinco por ciento (25%) "
        "del total de horas de clase dictadas en la asignatura perderá el derecho a continuar siendo evaluado y reprobará con la mención "
        "Pérdida por Inasistencia (PI), equivalente a una nota de 01 punto en el registro de Control de Estudios."
    )

    pdf.ln(3)
    pdf.section_title("Capítulo IV: Prelaciones, Retiro de Materias y Carga Académica")
    pdf.body_paragraph(
        "Artículo 8. Las prelaciones son de obligatorio cumplimiento según la malla curricular vigente. Un estudiante no podrá cursar "
        "una materia si no ha aprobado formalmente la asignatura que le precede."
    )
    pdf.body_paragraph(
        "Artículo 9. El retiro formal de una o varias asignaturas se realiza ante la Coordinación de Control de Estudios dentro de las "
        "primeras tres (3) semanas lectivas del período. La materia retirada formalmente no afecta el promedio ponderado del estudiante."
    )
    pdf.body_paragraph(
        "Artículo 10. La carga académica ordinaria máxima por período es de 22 a 24 Unidades de Crédito (UC). Aquellos estudiantes "
        "con índice académico destacado (igual o superior a 16.00 puntos) podrán solicitar una carga extraordinaria de hasta 3 UC adicionales."
    )

    path = os.path.join(output_dir, "02_Reglamento_Evaluacion_Estudiantil_IUTECP.pdf")
    pdf.output(path)
    print(f"Generado: {path}")


def create_doc3(output_dir):
    pdf = InstitutionalPDF("OFERTA ACADEMICA Y CARRERAS TSU", "IUTECP-OFERTA-ACAD")
    pdf.chapter_title("OFERTA ACADÉMICA OFICIAL Y PERFILES PROFESIONALES IUTECP")

    pdf.section_title("1. Estructura General de los Estudios")
    pdf.body_paragraph(
        "Los programas académicos del IUTECP conducen a la obtención del título oficial de Técnico Superior Universitario (TSU). "
        "Tienen una duración regular de seis (6) períodos académicos (3 años de estudio), organizados en modalidad trimestral/semestral, "
        "con posibilidad de prosecución a Licenciaturas e Ingenierías a través de convenios universitarios."
    )

    pdf.ln(3)
    pdf.section_title("2. Carreras del Área Tecnológica e Informática")
    pdf.bullet_item("TSU en Informática:", "Capacitado en desarrollo de software, gestión de bases de datos relacionales y no relacionales, "
                   "arquitectura de redes de computadoras, ciberseguridad básica y mantenimiento preventivo y correctivo de sistemas de información.")
    pdf.bullet_item("TSU en Diseño Gráfico:", "Especialista en comunicación visual, composición tipográfica, diseño editorial, animación digital, "
                   "identidad corporativa y producción publicitaria multimedia.")

    pdf.ln(3)
    pdf.section_title("3. Carreras del Área Administrativa y Ciencias Sociales")
    pdf.bullet_item("TSU en Administración de Empresas:", "Formación en planificación financiera, gestión de inventarios, formulación y evaluación "
                   "de proyectos de inversión, procesos de compras y logística empresarial.")
    pdf.bullet_item("TSU en Contaduría:", "Experto en teneduría de libros, preparación de estados financieros, auditoría tributaria bajo normativa "
                   "fiscal venezolana (SENIAT), sistemas de costeo y control presupuestario.")
    pdf.bullet_item("TSU en Relaciones Industriales:", "Especializado en gestión del talento humano, reclutamiento y selección de personal, cálculo "
                   "de nómina, seguridad y salud laboral (LOPCYMAT) y aplicación de la LOTTT.")
    pdf.bullet_item("TSU en Turismo:", "Gestión de servicios de hospitalidad y hotelería, diseño de itinerarios turísticos nacionales e internacionales, "
                   "operación de agencias de viajes y desarrollo de proyectos de ecoturismo sustentable.")

    pdf.ln(3)
    pdf.section_title("4. Carreras del Área de Ciencias de la Salud")
    pdf.bullet_item("TSU en Fisioterapia:", "Capacitado en técnicas de rehabilitación muscular, electroterapia, kinesiología, tratamiento de lesiones "
                   "deportivas y neurológicas y promoción del bienestar biomecánico.")
    pdf.bullet_item("TSU en Enfermería:", "Formado en atención clínica directa de pacientes, administración de medicamentos bajo prescripción médica, "
                   "asistencia en quirófano, control de signos vitales y programas de salud comunitaria.")

    pdf.ln(3)
    pdf.section_title("5. Prosecución a Licenciatura")
    pdf.body_paragraph(
        "Los egresados de TSU del IUTECP tienen acceso directo a programas de prosecución académica mediante convenios con instituciones "
        "universitarias aliadas para culminar los títulos de Licenciado en Administración, Licenciado en Contaduría Pública o Ingeniero en Sistemas "
        "en lapsos reducidos de 3 a 4 períodos adicionales."
    )

    path = os.path.join(output_dir, "03_Oferta_Academica_Carreras_IUTECP.pdf")
    pdf.output(path)
    print(f"Generado: {path}")


def create_doc4(output_dir):
    pdf = InstitutionalPDF("SERVICIO COMUNITARIO, PASANTIAS Y GRADO", "IUTECP-SC-PAS-GRAD")
    pdf.chapter_title("NORMATIVA DE SERVICIO COMUNITARIO, PASANTÍAS Y REQUISITOS DE GRADO")

    pdf.section_title("Título I: Servicio Comunitario del Estudiante Universitario")
    pdf.body_paragraph(
        "Artículo 1. En estricto cumplimiento de la Ley de Servicio Comunitario del Estudiante de Educación Superior de Venezuela, "
        "el Servicio Comunitario es un requisito indispensable y obligatorio para optar al título de Técnico Superior Universitario."
    )
    pdf.body_paragraph(
        "Artículo 2. Requisitos de Elegibilidad: El estudiante podrá inscribir el Servicio Comunitario únicamente tras haber aprobado "
        "un mínimo del cincuenta por ciento (50%) del total de las Unidades de Crédito del plan de estudios de su carrera."
    )
    pdf.body_paragraph(
        "Artículo 3. Duración y Fases: El Servicio Comunitario tiene una duración mínima de ciento veinte (120) horas académicas, "
        "que deben cumplirse en un período no menor a tres (3) meses ni mayor a doce (12) meses. Incluye: Taller de Inducción, Elaboración "
        "del Proyecto Comunitario con comunidades organizadas (Consejos Comunales, ONG o instituciones públicas), Ejecución en campo, y "
        "Presentación del Informe Final ante la Coordinación de Servicio Comunitario."
    )

    pdf.ln(3)
    pdf.section_title("Título II: Pasantías Profesionales y Acreditación de Experiencia Laboral")
    pdf.body_paragraph(
        "Artículo 4. Las Pasantías Profesionales representan el período de práctica técnica en una organización o empresa pública o privada, "
        "cursándose en el sexto (6to) período de la carrera. Se asignará un Tutor Académico (docente IUTECP) y un Tutor Empresarial."
    )
    pdf.body_paragraph(
        "Artículo 5. Modalidad de Acreditación de Experiencia Laboral: Aquellos estudiantes que se encuentren laborando de manera activa en "
        "un área directamente afín al perfil de su carrera técnica con una antigüedad comprobable no menor a un (1) año continuo, podrán solicitar "
        "la convalidación de su pasantía mediante la presentación de: Constancia de trabajo sellada con desglose de funciones, organigrama institucional, "
        "Memoria Técnica de Experiencia Laboral y defensa ante un jurado calificador."
    )

    pdf.ln(3)
    pdf.section_title("Título III: Requisitos Obligatorios para Optar al Título de Grado")
    pdf.body_paragraph(
        "Artículo 6. Para ser proclamado Técnico Superior Universitario y participar en el Acto Solemne de Grado del IUTECP, el estudiante "
        "debe cumplir y consignar los siguientes recaudos en la fecha estipulada por la Secretaría General:"
    )
    pdf.bullet_item("1. Récord Académico Completo:", "Haber aprobado la totalidad del 100% de las materias y unidades crédito del pensum.")
    pdf.bullet_item("2. Certificado de Servicio Comunitario:", "Constancia formal de aprobación de las 120 horas de servicio comunitario.")
    pdf.bullet_item("3. Aprobación de Pasantía / TEG:", "Acta de aprobación del Informe Final de Pasantías o Trabajo Especial de Grado.")
    pdf.bullet_item("4. Solvencia de Control de Estudios:", "Verificación del expediente de notas y entrega de fondo negro del título de bachiller.")
    pdf.bullet_item("5. Solvencia de Biblioteca:", "Constancia de no adeudar libros ni material bibliográfico o audiovisual.")
    pdf.bullet_item("6. Solvencia Administrativa y Caja:", "Paz y salvo de aranceles de matrícula, cuotas y aranceles de derecho a grado.")
    pdf.bullet_item("7. Fotografías de Grado:", "Dos (2) fotos tamaño carnet con vestimenta formal para el registro del título y libro de actas.")

    path = os.path.join(output_dir, "04_Normativa_Servicio_Comunitario_Pasantias_Grado_IUTECP.pdf")
    pdf.output(path)
    print(f"Generado: {path}")


def create_doc5(output_dir):
    pdf = InstitutionalPDF("CALENDARIO ACADEMICO OFICIAL", "IUTECP-CAL-2026")
    pdf.chapter_title("CRONOGRAMA Y CALENDARIO ACADÉMICO OFICIAL ANUAL")

    pdf.section_title("1. Organización de los Períodos Académicos")
    pdf.body_paragraph(
        "El año académico del IUTECP se organiza en tres (3) períodos regulares de catorce (14) a dieciséis (16) semanas lectivas cada uno:"
    )
    pdf.bullet_item("Período I:", "Inicia en Enero y culmina en Abril.")
    pdf.bullet_item("Período II:", "Inicia en Mayo y culmina en Agosto.")
    pdf.bullet_item("Período III:", "Inicia en Septiembre y culmina en Diciembre.")

    pdf.ln(3)
    pdf.section_title("2. Cronograma de Actividades por Semanas del Período")
    pdf.bullet_item("Semanas Previas:", "Inscripción en línea por TernaNet de estudiantes regulares y recepción de carpetas de nuevo ingreso.")
    pdf.bullet_item("Semana 1:", "Inicio formal de clases presenciales y sabatinas. Discusión y firma del Plan de Evaluación con los estudiantes.")
    pdf.bullet_item("Semanas 1 a 3:", "Lapso improrrogable para ajustes de inscripción, cambio de sección y retiro formal de asignaturas en Control de Estudios.")
    pdf.bullet_item("Semanas 4 a 5:", "Primer Corte de Evaluaciones Parciales (Ponderación: 30%). Publicación y carga de notas en TernaNet.")
    pdf.bullet_item("Semana 6:", "Taller de Inducción obligatorio para estudiantes aptos para iniciar Servicio Comunitario (50% de UC aprobadas).")
    pdf.bullet_item("Semanas 8 a 9:", "Segundo Corte de Evaluaciones Parciales (Ponderación: 30%). Reporte de alertas de inasistencias.")
    pdf.bullet_item("Semanas 12 a 13:", "Tercer Corte de Evaluaciones Finales (Ponderación: 40%). Entrega de informes de pasantías y proyectos.")
    pdf.bullet_item("Semana 14:", "Cierre definitivo de actas de notas por los docentes en TernaNet. Reclamos y correcciones de calificaciones.")
    pdf.bullet_item("Semana 15 a 16:", "Recepción de recaudos de grado y entrega de solvencias institucionales ante la Secretaría General.")
    pdf.bullet_item("Cierre de Período:", "Celebración de los Actos Solemnes de Grado para los egresados de TSU.")

    pdf.ln(3)
    pdf.section_title("3. Atención y Contacto de Control de Estudios")
    pdf.body_paragraph(
        "Para solicitudes de constancias de estudio, notas certificadas, carnets estudiantiles o trámites presenciales, "
        "el horario de taquilla en las sedes de Guatire y Caracas es de lunes a viernes de 8:00 am a 1:00 pm y de 2:00 pm a 4:30 pm, "
        "y los días sábados de 8:30 am a 1:00 pm."
    )

    path = os.path.join(output_dir, "05_Calendario_Academico_Periodos_IUTECP.pdf")
    pdf.output(path)
    print(f"Generado: {path}")


if __name__ == "__main__":
    docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "documents")
    os.makedirs(docs_dir, exist_ok=True)
    
    print(f"Generando documentos oficiales del IUTECP en: {docs_dir}")
    create_doc1(docs_dir)
    create_doc2(docs_dir)
    create_doc3(docs_dir)
    create_doc4(docs_dir)
    create_doc5(docs_dir)
    print("¡Todos los 5 documentos PDF fueron creados exitosamente!")

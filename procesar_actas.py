"""
Procesar actas escaneadas con Azure Document Intelligence (nivel
gratis F0: 500 páginas/mes) en vez de OCR local.

Se cambió de Tesseract a esto porque las actas reales son manuscritas
y vienen en una tabla con bordes — Tesseract no lograba leer ni
siquiera el texto IMPRESO del encabezado (se probó sobre una acta
real y la salida fue ilegible). Azure Document Intelligence sí está
hecho para tablas + letra manuscrita.

QUÉ HACE
--------
1. Manda cada PDF de actas_pdf/ directo a Azure (modelo
   "prebuilt-layout", que detecta tablas). Ya no hace falta convertir
   el PDF a imagen nosotros — Azure procesa el PDF directamente.
2. De la tabla que devuelve, toma la columna "Nombre completo" y la
   columna "N° identificación" de cada fila (salta la fila de
   encabezado).
3. Busca la sede una sola vez, en el texto del documento que queda
   FUERA de la tabla (el campo "SEDE:" de arriba), contra la lista en
   sedes.txt.
4. Si el nombre o la cédula quedaron muy cortos, o no se detectó
   sede, la fila se marca "REVISAR" en vez de darla por buena.
5. Copia el PDF completo (la acta, no cada persona) a una carpeta
   organizada por sede — igual que antes.
6. Genera actas_index.xlsx y data.js, igual que antes.

REQUISITOS
----------
1. Crear un recurso "Azure AI Document Intelligence" en el portal de
   Azure, nivel de precio F0 (gratis, 500 páginas/mes). De ahí sacas
   el ENDPOINT y una API KEY (pestaña "Keys and Endpoint").
2. Definir esos dos valores como variables de entorno ANTES de correr
   el script (no los pongas escritos directo en el código):
       export AZURE_DOCINTEL_ENDPOINT="https://TU-RECURSO.cognitiveservices.azure.com/"
       export AZURE_DOCINTEL_KEY="tu-clave-aqui"
3. pip install azure-ai-documentintelligence openpyxl

OJO — VERIFICA EL MAPEO DE COLUMNAS
-------------------------------------
Corre esto con DEBUG_OCR = True sobre 2-3 actas reales primero y
revisa en consola la línea "Encabezados detectados:" — ahí confirmas
que COLUMNA_NOMBRE / COLUMNA_CEDULA (más abajo) apuntan a las
columnas correctas. Si alguna acta trae columnas en otro orden,
ajusta esos dos números.
"""

import os
import re
import json
import time
import shutil
from pathlib import Path

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
from azure.ai.documentintelligence import DocumentIntelligenceClient
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

# ── CONFIGURACIÓN ────────────────────────────────────────────────────

CARPETA_PDFS = Path("./actas_pdf")
SALIDA_EXCEL = Path("./actas_index.xlsx")
SALIDA_DATAJS = Path("./data.js")
SEDES_CONOCIDAS_ARCHIVO = Path("./sedes.txt")

CARPETA_ORGANIZADAS = Path("./actas_organizadas")
COPIAR_EN_VEZ_DE_MOVER = True   # True = conserva los PDF originales intactos

DEBUG_OCR = True
UMBRAL_CONFIANZA = 0.75  # celdas donde Azure no estaba seguro se marcan "revisar"
                          # aunque el nombre/cédula se vean completos. Súbelo (ej.
                          # 0.85) si quieres que revise MÁS filas a mano; bájalo
                          # (ej. 0.6) si te está marcando demasiadas de más.

# Respaldo por si el encabezado de la tabla no se pudo leer (poco
# probable, es texto impreso, no manuscrito): el script primero
# intenta detectar las columnas "nombre" e "identificación" buscando
# esas palabras en el encabezado; si no las encuentra, usa estos
# índices fijos como último recurso.
COLUMNA_NOMBRE = 1
COLUMNA_CEDULA = 2

AZURE_ENDPOINT = os.environ.get("AZURE_DOCINTEL_ENDPOINT")
AZURE_KEY = os.environ.get("AZURE_DOCINTEL_KEY")

PAUSA_ENTRE_LLAMADAS = 2  # segundos — para no pegarle al límite de tasa del nivel gratis


# ── UTILIDADES (igual que antes) ─────────────────────────────────────

def normalizar_texto(txt: str) -> str:
    reemplazos = str.maketrans("áéíóúñ", "aeioun")
    return txt.lower().translate(reemplazos)


def sanear_para_archivo(texto: str) -> str:
    texto = re.sub(r'[\\/:*?"<>|]', '', texto)
    return texto.strip().replace(" ", "_")


def cargar_sedes_conocidas() -> list:
    if not SEDES_CONOCIDAS_ARCHIVO.exists():
        SEDES_CONOCIDAS_ARCHIVO.write_text("ICV\nHIC\nCTE\n", encoding="utf-8")
        print(f"Creé {SEDES_CONOCIDAS_ARCHIVO.resolve()} con una lista de partida.")
        print("Ábrelo y agrega ahí las sedes que falten antes de seguir.\n")
    return [
        linea.strip()
        for linea in SEDES_CONOCIDAS_ARCHIVO.read_text(encoding="utf-8").splitlines()
        if linea.strip()
    ]


def detectar_sede(texto: str, sedes_conocidas: list) -> str:
    """Busca la sede solo en las primeras líneas del documento (donde
    suele estar el campo 'SEDE:'), con límite de palabra para evitar
    que una sigla corta haga match dentro de otra palabra."""
    primeras_lineas = "\n".join((texto or "").splitlines()[:15])
    texto_norm = normalizar_texto(primeras_lineas)
    for s in sedes_conocidas:
        patron = r'\b' + re.escape(normalizar_texto(s)) + r'\b'
        if re.search(patron, texto_norm):
            return s
    return ""


def organizar_pdf(ruta_original: Path, sede: str) -> str:
    """Copia (o mueve) la acta completa a una carpeta por sede. No se
    renombra con datos de una persona porque el archivo pertenece a
    todas las de su tabla."""
    carpeta_destino = CARPETA_ORGANIZADAS / (sanear_para_archivo(sede) if sede else "sede_desconocida")
    carpeta_destino.mkdir(parents=True, exist_ok=True)

    ruta_destino = carpeta_destino / ruta_original.name
    contador = 2
    base_stem = ruta_destino.stem
    while ruta_destino.exists():
        ruta_destino = carpeta_destino / f"{base_stem}__{contador}{ruta_destino.suffix}"
        contador += 1

    if COPIAR_EN_VEZ_DE_MOVER:
        shutil.copy2(ruta_original, ruta_destino)
    else:
        shutil.move(str(ruta_original), str(ruta_destino))

    return ruta_destino.relative_to(CARPETA_ORGANIZADAS.parent).as_posix()


# ── AZURE DOCUMENT INTELLIGENCE ──────────────────────────────────────

def analizar_con_azure(client, ruta_pdf: Path, reintentos=3):
    """Manda el PDF a Azure y espera el resultado. Reintenta si el
    servicio responde 'ocupado' (429) — común en el nivel gratis."""
    for intento in range(1, reintentos + 1):
        try:
            with open(ruta_pdf, "rb") as f:
                poller = client.begin_analyze_document(
                    "prebuilt-layout", body=f, content_type="application/octet-stream"
                )
            return poller.result()
        except HttpResponseError as e:
            if e.status_code == 429 and intento < reintentos:
                espera = 15 * intento
                print(f"   Límite de tasa alcanzado, esperando {espera}s antes de reintentar...")
                time.sleep(espera)
            else:
                raise


def encontrar_tabla_de_personas(result):
    """Azure a veces detecta más de una tabla en la página — por
    ejemplo, la tablita del membrete de arriba (logo + título del
    formato) además de la tabla real de personas. Nos quedamos con la
    que tiene una columna que dice 'nombre' en su fila de encabezado;
    si ninguna hace match (raro), usamos la que tenga más filas como
    respaldo."""
    mejor_tabla = None
    mejor_conteo_filas = -1
    for tabla in result.tables:
        celdas_fila0 = [c for c in tabla.cells if c.row_index == 0]
        tiene_nombre = any("nombre" in normalizar_texto(c.content or "") for c in celdas_fila0)
        if tiene_nombre:
            return tabla
        if tabla.row_count > mejor_conteo_filas:
            mejor_conteo_filas = tabla.row_count
            mejor_tabla = tabla
    return mejor_tabla


def encontrar_columnas(tabla):
    """Busca en la fila de encabezado cuál columna es 'nombre' y cuál
    es la de identificación/cédula, en vez de asumir índices fijos —
    así no importa si alguna acta trae las columnas en otro orden."""
    celdas_fila0 = {c.column_index: normalizar_texto(c.content or "") for c in tabla.cells if c.row_index == 0}
    col_nombre = col_cedula = None
    for idx, texto in celdas_fila0.items():
        if "nombre" in texto and col_nombre is None:
            col_nombre = idx
        if any(clave in texto for clave in ("identificacion", "cedula", "c.c")) and col_cedula is None:
            col_cedula = idx
    return col_nombre, col_cedula


def _en_rango(palabra, spans):
    """¿La palabra cae dentro de alguno de estos rangos de texto
    (spans)? Así se sabe qué palabras pertenecen a qué celda."""
    for span in spans:
        if palabra.span.offset >= span.offset and (palabra.span.offset + palabra.span.length) <= (span.offset + span.length):
            return True
    return False


def confianza_minima_de_celda(celda, todas_las_palabras):
    """La confianza de una celda = la más baja entre las palabras que
    Azure reconoció dentro de ella. None si no se pudo calcular (no
    penaliza en ese caso, tampoco garantiza nada)."""
    if celda is None:
        return None
    confianzas = [p.confidence for p in todas_las_palabras if _en_rango(p, celda.spans)]
    return min(confianzas) if confianzas else None


def extraer_de_resultado(result, sedes_conocidas: list):
    """Saca la sede (buscada en el texto general, fuera de la tabla) y
    las filas de personas (de la tabla de personas detectada, saltando
    el encabezado)."""
    sede = detectar_sede(result.content, sedes_conocidas)

    if DEBUG_OCR:
        print(f"   Tablas detectadas: {len(result.tables)}")
        for i, t in enumerate(result.tables):
            print(f"     Tabla {i}: {t.row_count} filas x {t.column_count} columnas")
        print("   --- Texto completo (result.content) ---")
        print(result.content)
        print("   ----------------------------------------")

    registros = []
    if not result.tables:
        return sede, registros

    tabla = encontrar_tabla_de_personas(result)
    if tabla is None:
        return sede, registros

    filas = {}
    celdas_por_pos = {}
    for celda in tabla.cells:
        filas.setdefault(celda.row_index, {})[celda.column_index] = (celda.content or "").strip()
        celdas_por_pos[(celda.row_index, celda.column_index)] = celda

    todas_las_palabras = [p for pagina in (result.pages or []) for p in (pagina.words or [])]

    col_nombre, col_cedula = encontrar_columnas(tabla)
    if col_nombre is None:
        col_nombre = COLUMNA_NOMBRE
    if col_cedula is None:
        col_cedula = COLUMNA_CEDULA

    if DEBUG_OCR:
        print("   Encabezados detectados:", filas.get(0))
        print(f"   Columna nombre: {col_nombre}, columna cédula: {col_cedula}")

    for idx_fila in sorted(filas):
        if idx_fila == 0:
            continue  # fila de encabezado
        columnas = filas[idx_fila]
        nombre = columnas.get(col_nombre, "").strip()
        cedula = re.sub(r"[^\d]", "", columnas.get(col_cedula, ""))

        if not nombre and not cedula:
            continue  # fila vacía

        celda_nombre = celdas_por_pos.get((idx_fila, col_nombre))
        celda_cedula = celdas_por_pos.get((idx_fila, col_cedula))
        conf_nombre = confianza_minima_de_celda(celda_nombre, todas_las_palabras)
        conf_cedula = confianza_minima_de_celda(celda_cedula, todas_las_palabras)

        baja_confianza = (
            (conf_nombre is not None and conf_nombre < UMBRAL_CONFIANZA)
            or (conf_cedula is not None and conf_cedula < UMBRAL_CONFIANZA)
        )

        if DEBUG_OCR and baja_confianza and len(cedula) >= 6 and len(nombre) >= 4:
            print(f"   ⚠ Fila {idx_fila}: '{nombre}' / '{cedula}' se ve completa pero Azure dudó "
                  f"(confianza nombre={conf_nombre}, cédula={conf_cedula})")

        revisar = len(cedula) < 6 or len(nombre) < 4 or not sede or baja_confianza
        registros.append({"nombre": nombre, "cedula": cedula, "sede": sede, "revisar": revisar})

    return sede, registros


def procesar_carpeta():
    if not AZURE_ENDPOINT or not AZURE_KEY:
        print("Falta configurar AZURE_DOCINTEL_ENDPOINT y AZURE_DOCINTEL_KEY como variables de entorno.")
        return []

    client = DocumentIntelligenceClient(endpoint=AZURE_ENDPOINT, credential=AzureKeyCredential(AZURE_KEY))
    sedes_conocidas = cargar_sedes_conocidas()

    pdfs = sorted(CARPETA_PDFS.glob("*.pdf"))
    if not pdfs:
        print(f"No encontré PDFs en {CARPETA_PDFS.resolve()}")
        return []

    todos_los_registros = []
    for i, ruta in enumerate(pdfs, start=1):
        print(f"[{i}/{len(pdfs)}] Procesando {ruta.name}...")
        result = analizar_con_azure(client, ruta)
        sede, registros_pdf = extraer_de_resultado(result, sedes_conocidas)

        if not registros_pdf:
            print(f"   ⚠ No se detectó ninguna tabla/fila en {ruta.name} — revisar a mano.")
        else:
            ruta_organizada = organizar_pdf(ruta, sede)
            for r in registros_pdf:
                r["archivo"] = ruta_organizada
                todos_los_registros.append(r)

            n_revisar = sum(1 for r in registros_pdf if r["revisar"])
            aviso = f", {n_revisar} para revisar" if n_revisar else ""
            print(f"   {len(registros_pdf)} personas detectadas (sede: {sede or '¿?'}){aviso}")

        time.sleep(PAUSA_ENTRE_LLAMADAS)

    return todos_los_registros


def guardar_excel(registros: list):
    wb = Workbook()
    ws = wb.active
    ws.title = "Actas"

    ws.append(["Cédula", "Nombre", "Sede", "Archivo PDF", "Revisar"])
    for celda in ws[1]:
        celda.font = Font(bold=True)

    fill_revisar = PatternFill(start_color="FCEBD5", end_color="FCEBD5", fill_type="solid")

    for r in registros:
        ws.append([r["cedula"], r["nombre"], r["sede"], r["archivo"], "SÍ" if r["revisar"] else ""])
        if r["revisar"]:
            fila = ws.max_row
            for col in range(1, 6):
                ws.cell(row=fila, column=col).fill = fill_revisar

    for col, ancho in zip("ABCDE", [14, 34, 12, 42, 10]):
        ws.column_dimensions[col].width = ancho

    wb.save(SALIDA_EXCEL)
    print(f"\nExcel guardado en: {SALIDA_EXCEL.resolve()}")


def guardar_datajs(registros: list):
    datos_js = [
        {"cedula": r["cedula"], "nombre": r["nombre"], "sede": r["sede"], "archivo": r["archivo"], "revisar": r["revisar"]}
        for r in registros
    ]
    contenido = "const ACTAS = " + json.dumps(datos_js, ensure_ascii=False, indent=2) + ";\n"
    SALIDA_DATAJS.write_text(contenido, encoding="utf-8")
    print(f"data.js guardado en: {SALIDA_DATAJS.resolve()}")
    print("(en buscador_actas.html, reemplaza el arreglo ACTAS de ejemplo por:")
    print(' <script src="data.js"></script>  antes del <script> principal)')


if __name__ == "__main__":
    registros = procesar_carpeta()
    if registros:
        guardar_excel(registros)
        guardar_datajs(registros)
        n_revisar = sum(1 for r in registros if r["revisar"])
        print(f"\nListo: {len(registros)} personas indexadas, {n_revisar} para revisar a mano.")

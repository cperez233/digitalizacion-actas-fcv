"""
Genera unas actas de prueba (PDF) con una tabla de verdad (líneas de
cuadrícula, como la real) para poder probar procesar_actas.py de
punta a punta —incluyendo si Azure detecta bien la tabla y las
columnas— ANTES de gastar páginas del nivel gratis en actas reales.

Importante: el contenido de las celdas aquí es texto normal (no
manuscrito), así que esto no prueba qué tan bien lee Azure la letra a
mano — para eso no hay atajo, toca con actas reales. Esto solo valida
que la tubería completa (llamar a Azure, leer la tabla, sacar sede,
organizar el PDF, generar Excel/data.js) funciona de punta a punta.

USO
---
python generar_actas_prueba.py
"""

import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

CARPETA_SALIDA = Path("./actas_pdf")
CARPETA_SALIDA.mkdir(exist_ok=True)

SEDES = ["ICV", "HIC", "CTE"]
COLUMNAS = ["Fecha capacit.", "Nombre completo", "N° identificación", "Cargo", "Fecha ingreso", "Dirigida por", "Firma"]
ANCHOS_COL = [100, 290, 150, 110, 100, 100, 90]

NOMBRES = [
    "María Fernanda Rojas Duarte", "Carlos Andrés Villamizar Prada",
    "Laura Camila Ortiz Sepúlveda", "Jorge Eliécer Amaya Rueda",
    "Sandra Milena Peña Cárdenas", "Diego Fernando Serrano Gómez",
]

RUTA_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
RUTA_FONT_NORMAL = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def cargar_fuentes():
    try:
        return (
            ImageFont.truetype(RUTA_FONT_BOLD, 20),
            ImageFont.truetype(RUTA_FONT_NORMAL, 16),
        )
    except OSError:
        f = ImageFont.load_default()
        return f, f


def generar_acta(sede: str, personas: list, ruta_pdf: Path):
    font_titulo, font_texto = cargar_fuentes()

    x0, y0 = 40, 90
    alto_fila = 34
    n_filas = len(personas) + 1  # +1 por el encabezado
    ancho_tabla = sum(ANCHOS_COL)
    alto_img = y0 + n_filas * alto_fila + 40

    img = Image.new("RGB", (x0 * 2 + ancho_tabla, alto_img), "white")
    draw = ImageDraw.Draw(img)

    draw.text((x0, 25), f"SEDE: {sede}", font=font_titulo, fill="black")

    xs = [x0]
    for ancho in ANCHOS_COL:
        xs.append(xs[-1] + ancho)

    # líneas horizontales
    for i in range(n_filas + 1):
        y = y0 + i * alto_fila
        draw.line([(x0, y), (x0 + ancho_tabla, y)], fill="black", width=2)
    # líneas verticales
    for x in xs:
        draw.line([(x, y0), (x, y0 + n_filas * alto_fila)], fill="black", width=2)

    # encabezado
    for i, col in enumerate(COLUMNAS):
        draw.text((xs[i] + 4, y0 + 8), col, font=font_texto, fill="black")

    # filas de datos
    for fila_i, nombre in enumerate(personas, start=1):
        y = y0 + fila_i * alto_fila + 8
        cedula = str(random.randint(10_000_000, 1_120_000_000))
        valores = ["01/03/24", nombre, cedula, "Sistemas", "10/01/20", "JR", ""]
        for i, val in enumerate(valores):
            draw.text((xs[i] + 4, y), val, font=font_texto, fill="black")

    img.save(ruta_pdf, "PDF")


if __name__ == "__main__":
    for i, sede in enumerate(SEDES, start=1):
        personas = random.sample(NOMBRES, k=4)
        ruta = CARPETA_SALIDA / f"acta_prueba_{i}.pdf"
        generar_acta(sede, personas, ruta)
        print(f"Generada: {ruta}  (sede {sede}, {len(personas)} personas)")

    print(f"\n{len(SEDES)} actas de prueba listas en {CARPETA_SALIDA.resolve()}")
    print("Ahora corre: python procesar_actas.py  (con AZURE_DOCINTEL_ENDPOINT y AZURE_DOCINTEL_KEY ya exportadas)")

"""
Divide los PDF de varias páginas (uno por sede, con todas las actas
juntas) en PDF de una sola página cada uno — una acta por archivo.

POR QUÉ HACE FALTA ESTE PASO
------------------------------
1. El nivel gratis (F0) de Azure Document Intelligence SOLO analiza
   las primeras 2 páginas de cada documento que le mandes — sin
   avisar que se saltó el resto. Si le mandas un PDF de 37 páginas de
   una sola vez, te vas a quedar sin datos de las páginas 3 en
   adelante, sin ningún error que te lo diga.
2. Además, si "Ver PDF" abriera un archivo de 37 páginas, cada
   persona tendría que buscar su propia página a mano. Dividiendo,
   cada quien abre solo su acta.

QUÉ HACE
--------
Por cada PDF en actas_pdf/ con más de 1 página:
- Lo divide en archivos de 1 página: NombreOriginal_pagina_001.pdf,
  _pagina_002.pdf, etc. — y los deja en actas_pdf/.
- Mueve el PDF original (el de muchas páginas) a
  actas_pdf_originales/, para no perderlo y que no se vuelva a
  procesar por accidente en la siguiente corrida.

Los PDF que ya tenían 1 sola página se dejan tal cual, no se tocan.

REQUISITOS
----------
pip install pymupdf

USO
---
python dividir_pdfs.py
(y después, como siempre: python procesar_actas.py)
"""

import fitz  # PyMuPDF
from pathlib import Path

CARPETA_PDFS = Path("./actas_pdf")
CARPETA_ORIGINALES = Path("./actas_pdf_originales")


def dividir_pdf(ruta: Path) -> int:
    doc = fitz.open(ruta)
    n_paginas = len(doc)

    if n_paginas <= 1:
        doc.close()
        return 0

    for i in range(n_paginas):
        nuevo = fitz.open()
        nuevo.insert_pdf(doc, from_page=i, to_page=i)
        nombre_salida = f"{ruta.stem}_pagina_{i+1:03d}.pdf"
        nuevo.save(CARPETA_PDFS / nombre_salida)
        nuevo.close()

    doc.close()

    CARPETA_ORIGINALES.mkdir(exist_ok=True)
    ruta.rename(CARPETA_ORIGINALES / ruta.name)

    return n_paginas


if __name__ == "__main__":
    pdfs = sorted(CARPETA_PDFS.glob("*.pdf"))
    if not pdfs:
        print(f"No encontré PDFs en {CARPETA_PDFS.resolve()}")
    else:
        total_paginas = 0
        total_divididos = 0
        for ruta in pdfs:
            n = dividir_pdf(ruta)
            if n:
                print(f"Dividido: {ruta.name} -> {n} páginas")
                total_paginas += n
                total_divididos += 1

        if total_divididos == 0:
            print("Ningún PDF tenía más de 1 página — no había nada que dividir.")
        else:
            print(f"\nListo: {total_divididos} PDF divididos en {total_paginas} páginas individuales.")
            print("Los originales quedaron a salvo en actas_pdf_originales/.")
            print("Ahora corre: python procesar_actas.py")

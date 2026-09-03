# Digitalización de Actas — FCV

Pipeline para digitalizar y hacer buscables las actas físicas de "Conocimiento de Políticas de Seguridad de la Información" — formularios manuscritos, uno por sede, con varias personas firmando por hoja.

Lo construí durante mi práctica profesional en el área de Talento Humano de la **Fundación Cardiovascular de Colombia (FCV)**. El pedido original era un Excel indexado a mano (sede, cédula, nombre, en qué PDF está cada quien); esto lo automatiza de punta a punta.

## Qué hace

1. **`dividir_pdfs.py`** — separa los PDF de varias páginas (uno por sede, con todas las actas juntas) en un PDF por página/acta.
2. **`procesar_actas.py`** — le hace OCR a cada acta con [Azure AI Document Intelligence](https://azure.microsoft.com/products/ai-services/ai-document-intelligence) (maneja manuscrita + detecta la tabla real, no texto plano), extrae cédula/nombre/sede, organiza cada PDF en carpetas por sede, y genera un Excel indexado + los datos para el buscador.
3. **`buscador_actas.html`** — un buscador de una sola página (sin backend, sin instalar nada) para filtrar por cédula, nombre o sede, con botones para ver o descargar el PDF de cada quien.
4. **`generar_actas_prueba.py`** — genera actas de prueba con datos ficticios, para probar todo el pipeline sin depender de documentos reales.

## Por qué quedó así

- **OCR en la nube en vez de local (Tesseract)**: las actas son manuscritas y en tabla con bordes reales — Tesseract ni siquiera leía bien el texto impreso del encabezado. Azure Document Intelligence sí está hecho para eso, y el nivel gratis (F0, 500 páginas/mes) cubre el volumen real sin costo.
- **Filas marcadas "revisar" en vez de asumir que todo salió bien**: si el nombre/cédula quedaron muy cortos, o Azure tuvo poca confianza al leer una palabra (aunque el dato se vea completo), la fila se marca para revisión humana en vez de darse por buena en silencio.
- **Cada PDF se organiza, no se renombra por persona**: como cada página tiene ~7–10 personas, el archivo pertenece a todas ellas — se organiza por sede, no se le pone el nombre de una sola.

## Nota sobre los datos

Este repo **no incluye** ninguna acta real, el Excel generado, ni `data.js` — esos archivos tienen cédulas y nombres reales de empleados y quedan excluidos vía `.gitignore`. Para probar el pipeline sin datos reales, usa `generar_actas_prueba.py`, que genera actas ficticias con la misma estructura de tabla.

## Cómo correrlo

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Credenciales de Azure Document Intelligence (nivel Free F0)
export AZURE_DOCINTEL_ENDPOINT="https://TU-RECURSO.cognitiveservices.azure.com/"
export AZURE_DOCINTEL_KEY="tu-clave"

# Probar con actas ficticias (no hace falta tener actas reales)
python generar_actas_prueba.py
python dividir_pdfs.py
python procesar_actas.py

# Abrir buscador_actas.html en el navegador
```

## Stack

Python (Azure AI Document Intelligence, PyMuPDF, openpyxl) + HTML/CSS/JS sin frameworks para el buscador.

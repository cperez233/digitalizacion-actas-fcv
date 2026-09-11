🇪🇸 Español | 🇬🇧 [English version](README.md)

---

# Digitalización de Actas — FCV

Pipeline para digitalizar y hacer buscables las actas físicas de "Conocimiento de Políticas de Seguridad de la Información" — formularios manuscritos, uno por sede, con varias personas firmando por hoja.

Lo construí durante mi práctica profesional en el área de **Ciberseguridad** de la **Fundación Cardiovascular de Colombia (FCV)**. El pedido original era un Excel indexado a mano (sede, cédula, nombre, en qué PDF está cada quien); esto lo automatiza de punta a punta.

## Qué hace

**Pipeline principal** (en este orden):

1. **`dividir_pdfs.py`** — separa los PDF de varias páginas (uno por sede, con todas las actas juntas) en un PDF por página/acta. Necesario porque el nivel gratis de Azure solo analiza las primeras 2 páginas de cada documento que le mandes.
2. **`procesar_actas.py`** — le hace OCR a cada acta con [Azure AI Document Intelligence](https://azure.microsoft.com/products/ai-services/ai-document-intelligence) (maneja manuscrita + detecta la tabla real, no texto plano), extrae cédula/nombre/sede, limpia el nombre (solo letras, un espacio entre palabras, Mayúscula Inicial), organiza cada PDF en carpetas por sede, y genera `actas_index.xlsx` + `data.js`.
3. **Revisión manual** — abres `actas_index.xlsx`, corriges lo que haga falta, y borras el "SÍ" de la columna Revisar en las filas que ya verificaste.
4. **`actualizar_buscador_desde_excel.py`** — regenera `data.js` a partir del Excel ya corregido, para que el buscador quede sincronizado sin editar nada a mano.
5. **`buscador_actas.html`** — el buscador en sí: una sola página (sin backend, sin instalar nada) para filtrar por cédula, nombre o sede, con botones para ver o descargar el PDF de cada quien.

**Para probar sin datos reales:**

- **`generar_actas_prueba.py`** — genera actas ficticias con la misma estructura de tabla, para probar todo el pipeline sin depender de documentos reales.

## Sobre la precisión

Esto no reemplaza una revisión humana final. La letra manuscrita de cada persona varía muchísimo — algunas son perfectamente legibles, otras casi ilegibles ni para un humano — y la ortografía de nombres poco comunes puede confundirse fácilmente con errores de OCR (un nombre real pero raro y un nombre mal leído se ven parecido, y el sistema no siempre puede distinguirlos). Por eso cada fila que Azure no leyó con confianza queda marcada "revisar" en vez de darse por buena en silencio — pero eso reduce cuánto hay que revisar a mano, no lo elimina. Se evaluó y se descartó a propósito "corregir" nombres contra un diccionario genérico de nombres en español: el riesgo de que "corrija" un nombre real pero inusual hacia uno más común (y equivocado) es mayor que el problema que resolvería.

## Por qué quedó así

- **OCR en la nube en vez de local (Tesseract)**: las actas son manuscritas y en tabla con bordes reales — Tesseract ni siquiera leía bien el texto impreso del encabezado. Azure Document Intelligence sí está hecho para eso, y el nivel gratis (F0, 500 páginas/mes) cubre el volumen real sin costo.
- **Filas marcadas "revisar" en vez de asumir que todo salió bien**: si el nombre/cédula quedaron muy cortos, o Azure tuvo poca confianza al leer una palabra (aunque el dato se vea completo), la fila se marca para revisión humana en vez de darse por buena en silencio.
- **Cada PDF se organiza, no se renombra por persona**: como cada página tiene varias personas, el archivo pertenece a todas ellas — se organiza por sede, no se le pone el nombre de una sola.
- **El Excel es la fuente de verdad después de la primera pasada**: una vez lo revisas y corriges a mano, `actualizar_buscador_desde_excel.py` es el único comando que hace falta correr — nunca se edita `data.js` directamente.

## Seguridad y Arquitectura de Producción

El visualizador y buscador web fueron reforzados siguiendo estándares estrictos de ciberseguridad institucional (OWASP Top 10 / directrices CWE):
- **Autenticación con roles (`server.py`)**: Servicio HTTP ligero en Python con base de datos SQLite (`database/fcv_auth.db`), contraseñas hasheadas con SHA-256 + salt criptográfica, comparación de tiempo constante (`secrets.compare_digest`) y protección contra fuerza bruta (bloqueo de 30s tras 5 intentos fallidos).
- **Prevención DOM XSS (CWE-79 / CWE-116)**: Construcción 100% nativa con nodos DOM (`document.createElement`, `textContent`) — sin uso de `innerHTML` inseguro.
- **Content Security Policy (CSP) estricta**: Cero CDNs externas. Tipografías (Montserrat, Inter) y logos alojados localmente para mitigar fallas de SRI (CWE-345) y fugas a terceros (CWE-200).
- **Anti-Clickjacking (CWE-1021)**: Aplicado con cabeceras `X-Frame-Options: SAMEORIGIN` y `frame-ancestors 'self'`.
- **Privacidad del Servidor (CWE-497)**: Cabecera ofuscada a `Server: FCV-SecureServer`; bloqueo total por URL a `database/` y archivos `.db` (HTTP 403 Prohibido).

## Nota sobre los datos

Este repositorio **no incluye** ninguna acta real, ni el Excel generado, ni `data.js` — dichos archivos contienen información confidencial (cédulas, nombres reales y documentos médicos/administrativos) y están estrictamente protegidos mediante `.gitignore`.

Para pruebas de desarrollo del buscador web sin datos sensibles, se incluye la plantilla [`data.example.js`](data.example.js):
```bash
cp data.example.js data.js
```

## Cómo correrlo

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 1. Ejecución del pipeline de procesamiento (opcional si se prueba con datos de ejemplo)
# Credenciales de Azure Document Intelligence (nivel Free F0)
export AZURE_DOCINTEL_ENDPOINT="https://TU-RECURSO.cognitiveservices.azure.com/"
export AZURE_DOCINTEL_KEY="tu-clave"

python generar_actas_prueba.py
python dividir_pdfs.py
python procesar_actas.py
python actualizar_buscador_desde_excel.py

# 2. Iniciar el Servidor Seguro de Búsqueda
python3 server.py 8080

# Ingresar a http://127.0.0.1:8080 en el navegador.
```

## Stack

Python (Azure AI Document Intelligence, PyMuPDF, openpyxl, SQLite3) + HTML5/CSS3/JS nativo (accesibilidad WCAG AAA, modo Claro/Oscuro, tipografías locales).


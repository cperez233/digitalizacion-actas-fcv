🇬🇧 English | 🇪🇸 [Versión en español](README.es.md)

---

# Actas Digitization — FCV

Pipeline to digitize and make searchable physical "Information Security Policy Acknowledgment" records — handwritten forms, one per site, with multiple people signing per page.

I built this during my professional internship in the **Cybersecurity** area at **Fundación Cardiovascular de Colombia (FCV)**. The original request was a manually indexed Excel sheet (site, ID number, name, which PDF each person is in); this automates the whole thing end to end.

## What it does

**Main pipeline** (in this order):

1. **`dividir_pdfs.py`** — splits multi-page PDFs (one per site, with all records together) into one PDF per page/record. Needed because Azure's free tier only analyzes the first 2 pages of any document you send it.
2. **`procesar_actas.py`** — runs OCR on each record with [Azure AI Document Intelligence](https://azure.microsoft.com/products/ai-services/ai-document-intelligence) (handles handwriting + detects the actual table, not plain text), extracts ID number/name/site, cleans up the name (letters only, single spaces, Title Case), organizes each PDF into folders by site, and generates `actas_index.xlsx` + `data.js`.
3. **Manual review** — open `actas_index.xlsx`, fix whatever needs fixing, and clear the "SÍ" in the Review column for rows you've already verified.
4. **`actualizar_buscador_desde_excel.py`** — regenerates `data.js` from the corrected Excel, so the search tool stays in sync without editing anything by hand.
5. **`buscador_actas.html`** — the search tool itself: a single page (no backend, nothing to install) to filter by ID number, name, or site, with buttons to view or download each person's PDF.

**To test without real data:**

- **`generar_actas_prueba.py`** — generates fake records with the same table structure, to test the whole pipeline without depending on real documents.

## On accuracy

This doesn't replace a final human review. Handwriting varies a lot from person to person — some is perfectly legible, some is barely readable even for a human — and unusual name spellings can easily be confused with OCR errors (a real but uncommon name and a misread name can look alike, and the system can't always tell them apart). That's why any row Azure didn't read with confidence gets flagged for review instead of being silently accepted — but that reduces how much needs manual review, it doesn't eliminate it. "Correcting" names against a generic Spanish name dictionary was considered and deliberately ruled out: the risk of it "correcting" a real but unusual name into a more common (and wrong) one outweighs the problem it would solve.

## Why it's built this way

- **Cloud OCR instead of local (Tesseract)**: the records are handwritten, in a real bordered table — Tesseract couldn't even read the printed header text reliably. Azure Document Intelligence is built for exactly this, and the free tier (F0, 500 pages/month) covers the real volume at no cost.
- **Rows flagged "review" instead of assuming everything's fine**: if the name/ID came out too short, or Azure had low confidence reading a word (even if the value looks complete), the row gets flagged for human review instead of being trusted silently.
- **Each PDF gets organized, not renamed per person**: since each page has several people on it, the file belongs to all of them — it gets organized by site, not named after just one person.
- **The Excel is the source of truth after the first pass**: once you review and correct it by hand, `actualizar_buscador_desde_excel.py` is the only command you need to run — `data.js` is never edited directly.

## About the data

This repo does **not** include any real record, the generated Excel, or `data.js` — those files contain real employee names and ID numbers and are excluded via `.gitignore`. To test the pipeline without real data, use `generar_actas_prueba.py`, which generates fake records with the same table structure.

## How to run it

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Azure Document Intelligence credentials (Free F0 tier)
export AZURE_DOCINTEL_ENDPOINT="https://YOUR-RESOURCE.cognitiveservices.azure.com/"
export AZURE_DOCINTEL_KEY="your-key"

# Test with fake records (no real documents needed)
python generar_actas_prueba.py
python dividir_pdfs.py
python procesar_actas.py

# After reviewing/correcting actas_index.xlsx by hand:
python actualizar_buscador_desde_excel.py

# Open buscador_actas.html in the browser
```

## Stack

Python (Azure AI Document Intelligence, PyMuPDF, openpyxl) + framework-free HTML/CSS/JS for the search tool.

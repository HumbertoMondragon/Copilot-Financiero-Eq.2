# Financial Normalizer

Parses P&L statements (Estado de Resultados) from Excel, text PDF, scanned PDF, or raw prose and normalizes them into a single JSON schema.

## Setup

```bash
pip install -r requirements.txt
```

For scanned PDFs, also install system dependencies:
- **Tesseract OCR**: https://github.com/UB-Mannheim/tesseract/wiki (Windows) or `brew install tesseract`
- **Poppler** (for pdf2image): https://github.com/oschwartz10612/poppler-windows/releases (Windows) or `brew install poppler`

Set your API key:
```bash
export ANTHROPIC_API_KEY=sk-ant-...   # or add to .env
```

## Usage

```python
from financial_normalizer.normalizer import normalize

result = normalize("path/to/estado_resultados.xlsx", cliente_id="cliente_abc")
print(result["meses"]["ENERO 2026"]["kpis"]["ebitda"])
```

## Run tests

```bash
# From the repo root
pytest financial_normalizer/tests/test_validator.py -v
```

## Generate synthetic fixtures

```bash
python -m financial_normalizer.tests.create_fixtures
```

Writes `financial_normalizer/tests/data/sample_enero_2026.xlsx` and `.txt`.

## Add a client profile

Edit `profiles.py`:
```python
PROFILES["cliente_abc"] = {
    "hint": "This client reports food costs separately under 'Costo Alimentos'.",
    "synonyms": {"Costo Alimentos": "total_costo"},
    "scale": 1000.0,  # they report in thousands
}
```

## Architecture

```
normalizer.py          ← entry point, parser selection, LLM fallback
parsers/
  parser_excel.py      ← openpyxl + pandas, handles merged cells & hierarchy
  parser_pdf_texto.py  ← pdfplumber, table extraction then line-by-line fallback
  parser_pdf_escaneado.py ← pdf2image + OpenCV + pytesseract
  parser_llm.py        ← Anthropic API fallback for unstructured/failing docs
validator.py           ← arithmetic consistency checks (2% tolerance)
profiles.py            ← per-client synonyms, hints, scale factors
utils.py               ← clean_currency, almost_equal, detect_months
tests/
  fixtures.py          ← arithmetically consistent synthetic data
  test_validator.py    ← pytest unit tests
  create_fixtures.py   ← generates .xlsx and .txt test files
```

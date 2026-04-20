"""
file_parser.py – Extract text from uploaded attachments
=========================================================
Supported types:
  - PDF         → pypdf (already installed)
  - DOCX        → python-docx (already installed)
  - XLSX/XLSM   → openpyxl (already installed)
  - Images (PNG/JPG/WEBP/GIF) → Claude vision API
  - TXT/CSV     → plain read
"""

import io
import os
import base64
from pathlib import Path

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc",
    ".xlsx", ".xlsm", ".xls", ".csv",
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".txt",
}

MAX_TEXT_CHARS = 8000   # clip per file before sending to LLM


# ── PDF ───────────────────────────────────────────────────────────────────────

def _parse_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages  = []
    for page in reader.pages[:20]:       # cap at 20 pages
        text = page.extract_text() or ""
        if text.strip():
            pages.append(text.strip())
    return "\n\n".join(pages)


# ── DOCX ──────────────────────────────────────────────────────────────────────

def _parse_docx(data: bytes) -> str:
    from docx import Document
    doc  = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    # Also grab table cells
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                text += "\n" + " | ".join(cells)
    return text


# ── XLSX / XLSM ───────────────────────────────────────────────────────────────

def _parse_xlsx(data: bytes) -> str:
    import openpyxl
    wb    = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines = []
    for sheet_name in wb.sheetnames[:5]:          # cap at 5 sheets
        ws = wb[sheet_name]
        lines.append(f"[Sheet: {sheet_name}]")
        row_count = 0
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None and str(c).strip()]
            if cells:
                lines.append(" | ".join(cells))
                row_count += 1
            if row_count >= 100:                   # cap rows per sheet
                break
    wb.close()
    return "\n".join(lines)


# ── CSV ───────────────────────────────────────────────────────────────────────

def _parse_csv(data: bytes) -> str:
    import csv
    text   = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    lines  = []
    for i, row in enumerate(reader):
        if i >= 100:
            break
        lines.append(" | ".join(row))
    return "\n".join(lines)


# ── Images (Claude vision) ────────────────────────────────────────────────────

def _parse_image(data: bytes, mime_type: str, api_key: str) -> str:
    try:
        import anthropic
        client  = anthropic.Anthropic(api_key=api_key)
        b64     = base64.standard_b64encode(data).decode("utf-8")
        message = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime_type, "data": b64},
                    },
                    {
                        "type": "text",
                        "text": (
                            "This is an attachment from a customer request for an electrical "
                            "control cabinet. Extract all technical information visible: "
                            "power ratings, motor counts, IP ratings, dimensions, component "
                            "references, wiring details, or any specs. Be concise and structured."
                        ),
                    },
                ],
            }],
        )
        return message.content[0].text
    except Exception as e:
        return f"[Image could not be parsed: {e}]"


# ── Plain text ────────────────────────────────────────────────────────────────

def _parse_txt(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


# ── Public API ────────────────────────────────────────────────────────────────

IMAGE_MIMES = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif":  "image/gif",
}


def parse_file(filename: str, data: bytes, api_key: str = "") -> dict:
    """
    Parse a single uploaded file and return:
      {name, type, text, error, char_count}
    """
    ext  = Path(filename).suffix.lower()
    name = Path(filename).name

    if ext not in SUPPORTED_EXTENSIONS:
        return {"name": name, "type": ext, "text": "", "error": f"Unsupported file type: {ext}", "char_count": 0}

    try:
        if ext == ".pdf":
            raw = _parse_pdf(data)
        elif ext in (".docx", ".doc"):
            raw = _parse_docx(data)
        elif ext in (".xlsx", ".xlsm", ".xls"):
            raw = _parse_xlsx(data)
        elif ext == ".csv":
            raw = _parse_csv(data)
        elif ext in IMAGE_MIMES:
            mime = IMAGE_MIMES[ext]
            raw  = _parse_image(data, mime, api_key)
        else:
            raw = _parse_txt(data)

        raw = raw.strip()
        clipped = raw[:MAX_TEXT_CHARS]
        if len(raw) > MAX_TEXT_CHARS:
            clipped += f"\n... [truncated — {len(raw)} chars total]"

        return {"name": name, "type": ext.lstrip("."), "text": clipped, "error": None, "char_count": len(clipped)}

    except Exception as e:
        return {"name": name, "type": ext.lstrip("."), "text": "", "error": str(e), "char_count": 0}


def build_attachments_context(parsed_files: list) -> str:
    """
    Build a context block to inject into the LLM prompt.
    Only includes files that parsed successfully.
    """
    sections = []
    for f in parsed_files:
        if f.get("text") and not f.get("error"):
            sections.append(
                f"=== Attached file: {f['name']} ===\n{f['text']}"
            )
    if not sections:
        return ""
    return "\n\n".join(sections)

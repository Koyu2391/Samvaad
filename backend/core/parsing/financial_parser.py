"""
Financial document parser.

Strategy (in order of preference):
  1. Docling (preserves tables, layout) - best for structured financial docs
  2. PyMuPDF/pdfplumber (text + table extraction) - fallback if Docling unavailable
  3. Tesseract OCR (for scanned pages) - triggered when extracted text is empty/sparse

Outputs LangChain `Document` objects with rich metadata:
  - source_file, page, type (text/table/heading)
  - chunk_index, financial_section (if detected)
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


# ── Backends (lazy-loaded) ─────────────────────────────────────────────────

def _docling_available() -> bool:
    try:
        import docling  # noqa
        return True
    except ImportError:
        return False


def _tesseract_available() -> bool:
    try:
        import pytesseract  # noqa
        return True
    except ImportError:
        return False


# ── Output container ───────────────────────────────────────────────────────

@dataclass
class ParsedDocument:
    """Container for the structured output of parsing a single file."""
    filename: str
    documents: List[Document] = field(default_factory=list)  # text chunks
    tables: List[dict] = field(default_factory=list)         # extracted tables
    page_count: int = 0
    used_ocr: bool = False
    used_docling: bool = False
    error: Optional[str] = None


# ── Financial section detection ────────────────────────────────────────────

FINANCIAL_SECTION_PATTERNS = {
    "balance_sheet": r"\b(balance\s+sheet|statement of (financial position|assets and liabilities))\b",
    "income_statement": r"\b(income statement|profit (and|&) loss|p&l|statement of operations|earnings)\b",
    "cash_flow": r"\b(cash flow|statement of cash flows)\b",
    "md_and_a": r"\b(management['’]?s discussion and analysis|md&a)\b",
    "risk_factors": r"\b(risk factors)\b",
    "notes": r"\b(notes to (the )?financial statements?)\b",
    "auditor_report": r"\b(independent auditor['’]?s report|opinion)\b",
}


def _detect_financial_section(text: str) -> Optional[str]:
    lowered = text.lower()
    for label, pattern in FINANCIAL_SECTION_PATTERNS.items():
        if re.search(pattern, lowered):
            return label
    return None


# ── Docling parsing ────────────────────────────────────────────────────────

def _parse_with_docling(file_path: str, filename: str) -> ParsedDocument:
    """Parse a PDF with Docling, preserving table structure."""
    from docling.document_converter import DocumentConverter

    parsed = ParsedDocument(filename=filename, used_docling=True)
    converter = DocumentConverter()
    result = converter.convert(file_path)
    doc = result.document

    # Markdown export preserves tables as markdown tables
    md_text = doc.export_to_markdown()

    # Page-by-page extraction (Docling exposes pages via document structure)
    try:
        page_count = len(doc.pages) if hasattr(doc, "pages") else 1
    except Exception:
        page_count = 1
    parsed.page_count = page_count

    # Build a single Document per logical section to preserve context
    # Then chunk in a downstream step
    section = _detect_financial_section(md_text[:2000])
    parsed.documents.append(
        Document(
            page_content=md_text,
            metadata={
                "source_file": filename,
                "page": 0,
                "type": "markdown",
                "financial_section": section,
                "parser": "docling",
            },
        )
    )

    # Extract tables separately for downstream financial queries
    try:
        for tbl_idx, table in enumerate(getattr(doc, "tables", []) or []):
            try:
                tbl_md = table.export_to_markdown()
                parsed.tables.append({
                    "index": tbl_idx,
                    "markdown": tbl_md,
                    "page": getattr(table, "page_number", None),
                })
            except Exception:
                continue
    except Exception:
        pass

    return parsed


# ── pdfplumber + OCR fallback ──────────────────────────────────────────────

def _parse_with_pdfplumber(file_path: str, filename: str) -> ParsedDocument:
    """Fallback parser using pdfplumber for text + tables, OCR for scanned pages."""
    import pdfplumber

    parsed = ParsedDocument(filename=filename)
    pages_text: List[tuple[int, str, bool]] = []  # (page_num, text, was_ocrd)

    try:
        with pdfplumber.open(file_path) as pdf:
            parsed.page_count = len(pdf.pages)

            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""

                # If page yielded no text → likely scanned → OCR
                used_ocr = False
                if len(text.strip()) < 30 and _tesseract_available():
                    text = _ocr_page(file_path, i) or text
                    used_ocr = bool(text and len(text.strip()) >= 30)
                    if used_ocr:
                        parsed.used_ocr = True

                # Extract tables on this page (preserve as markdown)
                try:
                    for tbl_idx, tbl in enumerate(page.extract_tables() or []):
                        if not tbl or len(tbl) < 2:
                            continue
                        md_table = _table_to_markdown(tbl)
                        parsed.tables.append({
                            "index": f"{i}_{tbl_idx}",
                            "markdown": md_table,
                            "page": i,
                        })
                        # Inject the markdown table into the page text so it gets indexed
                        text = (text or "") + "\n\n" + md_table
                except Exception:
                    pass

                pages_text.append((i, text or "", used_ocr))
    except Exception as e:
        parsed.error = f"pdfplumber failed: {e}"
        return parsed

    for page_num, text, was_ocrd in pages_text:
        if not text.strip():
            continue
        section = _detect_financial_section(text[:2000])
        parsed.documents.append(
            Document(
                page_content=text,
                metadata={
                    "source_file": filename,
                    "page": page_num,
                    "type": "text" if not was_ocrd else "ocr",
                    "financial_section": section,
                    "parser": "pdfplumber" + ("+ocr" if was_ocrd else ""),
                },
            )
        )

    return parsed


def _table_to_markdown(rows: list) -> str:
    """Convert a list-of-lists table to a markdown table."""
    if not rows or not rows[0]:
        return ""
    cleaned = [
        ["" if cell is None else str(cell).strip() for cell in row]
        for row in rows
        if any(c is not None for c in row)
    ]
    if not cleaned:
        return ""
    header = cleaned[0]
    sep = ["---"] * len(header)
    body = cleaned[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for row in body:
        # Pad/truncate to header length
        padded = (row + [""] * len(header))[: len(header)]
        lines.append("| " + " | ".join(padded) + " |")
    return "\n".join(lines)


def _ocr_page(file_path: str, page_index: int) -> Optional[str]:
    """OCR a single PDF page using pdf2image + pytesseract. Returns None on failure."""
    try:
        import pytesseract
        from PIL import Image
        import fitz  # PyMuPDF — already installed via pymupdf4llm
    except ImportError:
        return None

    try:
        with fitz.open(file_path) as pdf:
            if page_index >= pdf.page_count:
                return None
            page = pdf[page_index]
            # Render at 2x for better OCR quality
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            import io
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            return pytesseract.image_to_string(img)
    except Exception as e:
        print(f"[ocr] page {page_index} failed: {e}")
        return None


# ── Public API ─────────────────────────────────────────────────────────────

def _pdf_is_scanned(file_path: str) -> bool:
    """Check if PDF has extractable text. Returns True if scanned (no text)."""
    try:
        import fitz
        with fitz.open(file_path) as doc:
            for page in doc:
                if page.get_text().strip():
                    return False
        return True
    except Exception:
        return False


def parse_document(file_path: str, filename: Optional[str] = None) -> ParsedDocument:
    """
    Parse a document into structured chunks + tables.

    Strategy:
      1. For text-based PDFs → fast path with pdfplumber (no OCR, no Docling overhead)
      2. For scanned PDFs → Docling (with RapidOCR) for best layout/table recovery
      3. Non-PDFs → plain text handler
    """
    if filename is None:
        filename = os.path.basename(file_path)

    if file_path.lower().endswith(".pdf"):
        is_scanned = _pdf_is_scanned(file_path)

        if is_scanned and _docling_available():
            # Scanned PDF — Docling with OCR
            try:
                return _parse_with_docling(file_path, filename)
            except Exception as e:
                print(f"[parser] Docling failed for scanned {filename}: {e}; trying pdfplumber")
                return _parse_with_pdfplumber(file_path, filename)

        # Text-based PDF — fast path, no OCR needed
        return _parse_with_pdfplumber(file_path, filename)

    # Plain text / email / transcripts
    if file_path.lower().endswith((".txt", ".eml", ".md")):
        return _parse_text_file(file_path, filename)

    # Unknown extension
    parsed = ParsedDocument(filename=filename, error=f"Unsupported file type: {filename}")
    return parsed


def _parse_text_file(file_path: str, filename: str) -> ParsedDocument:
    parsed = ParsedDocument(filename=filename, page_count=1)
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        if filename.lower().endswith(".eml"):
            # Strip email headers — keep body
            from email import policy
            from email.parser import BytesParser
            with open(file_path, "rb") as fb:
                msg = BytesParser(policy=policy.default).parse(fb)
            text = msg.get_body(preferencelist=("plain", "html"))
            text = text.get_content() if text else ""
        parsed.documents.append(
            Document(
                page_content=text,
                metadata={
                    "source_file": filename,
                    "page": 0,
                    "type": "text",
                    "financial_section": _detect_financial_section(text[:2000]),
                    "parser": "text",
                },
            )
        )
    except Exception as e:
        parsed.error = str(e)
    return parsed


def chunk_for_financial_rag(
    parsed: ParsedDocument,
    chunk_size: int = 800,
    chunk_overlap: int = 200,
) -> List[Document]:
    """
    Chunk a parsed document for indexing.

    Financial docs use a smaller chunk size (800 vs default 1200) for precision
    on numerical answers. Markdown tables are kept intact (chunked separately
    only if they exceed chunk_size).
    """
    # Use markdown-aware splitter — keeps headers and tables together where possible
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=[
            "\n## ", "\n### ", "\n#### ",  # markdown headers
            "\n\n", "\n", ". ", " ", "",
        ],
    )

    all_chunks: List[Document] = []
    for doc in parsed.documents:
        sub_chunks = splitter.split_documents([doc])
        for idx, chunk in enumerate(sub_chunks):
            chunk.metadata["chunk_index"] = idx
            chunk.metadata.setdefault("source_file", parsed.filename)
            all_chunks.append(chunk)

    # Also index each table as its own chunk (avoids splitting financial tables)
    for tbl in parsed.tables:
        all_chunks.append(
            Document(
                page_content=tbl["markdown"],
                metadata={
                    "source_file": parsed.filename,
                    "page": tbl.get("page"),
                    "type": "table",
                    "table_index": tbl["index"],
                    "parser": "table-extractor",
                },
            )
        )

    return all_chunks

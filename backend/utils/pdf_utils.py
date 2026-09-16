import base64
import streamlit as st
import hashlib

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from langchain_core.documents import Document
except ImportError:
    Document = None

# Ver 1.0: Initial PDF utils with basic extraction and display functions.
# def display_pdf(file_bytes: bytes) -> None:
#     """Render a PDF inline in the Streamlit app using an iframe."""
#     st.markdown("### PDF Preview")
#     base64_pdf = base64.b64encode(file_bytes).decode("utf-8")
#     pdf_display = f"""
#         <iframe
#             src="data:application/pdf;base64,{base64_pdf}"
#             width="400"
#             height="100%"
#             type="application/pdf"
#             style="height:100vh; width:100%"
#         ></iframe>
#     """
#     st.markdown(pdf_display, unsafe_allow_html=True)


# # def extract_tables_from_pdf(pdf_path: str, filename: str) -> list:
# #     """
# #     Extract tables from a PDF using pdfplumber and convert each to
# #     a markdown-formatted Document chunk for indexing.

# #     Returns an empty list if pdfplumber is not installed or extraction fails.
# #     """
# #     if pdfplumber is None or Document is None:
# #         return []

# #     table_docs = []

# #     try:
# #         with pdfplumber.open(pdf_path) as pdf:
# #             for page_num, page in enumerate(pdf.pages):
# #                 tables = page.extract_tables()

# #                 for table_idx, table in enumerate(tables):
# #                     if not table:
# #                         continue

# #                     # Build markdown rows
# #                     rows = []
# #                     for row in table:
# #                         cleaned = [str(cell).strip() if cell else "" for cell in row]
# #                         rows.append("| " + " | ".join(cleaned) + " |")

# #                     if len(rows) < 2:
# #                         continue

# #                     # Insert separator after header row
# #                     header_sep = "| " + " | ".join(["---"] * len(table[0])) + " |"
# #                     rows.insert(1, header_sep)

# #                     markdown_table = "".join(rows)

# #                     doc = Document(
# #                         page_content=f"[TABLE from page {page_num + 1}]\n{markdown_table}",
# #                         metadata={
# #                             "source": pdf_path,
# #                             "source_file": filename,
# #                             "page": page_num,
# #                             "type": "table",
# #                             "table_index": table_idx,
# #                         },
# #                     )
# #                     print(f"Extracted table from {filename} page {page_num + 1}, table {table_idx + 1}")
# #                     table_docs.append(doc)
# #                     print(table_docs)

# #     except Exception as e:
# #         st.warning(f"Could not extract tables from {filename}: {e}")

# #     return table_docs


# Ver 2.0: Rewrote table extraction to fix markdown rendering and skip nearly-empty tables.
# def extract_tables_from_pdf(pdf_path: str, filename: str) -> list:
#     """
#     Extract tables from a PDF using pdfplumber and convert each to
#     a markdown-formatted Document chunk for indexing.
 
#     Improvements over original:
#     - Rows are newline-separated so markdown renders correctly
#     - Multi-line cell content is collapsed to a single line
#     - Nearly-empty tables are skipped
#     - Duplicate tables (by content hash) are skipped
 
#     Returns an empty list if pdfplumber is not installed or extraction fails.
#     """
#     if pdfplumber is None or Document is None:
#         return []
 
#     table_docs = []
#     seen_hashes = set()
 
#     try:
#         with pdfplumber.open(pdf_path) as pdf:
#             for page_num, page in enumerate(pdf.pages):
#                 tables = page.extract_tables()
 
#                 for table_idx, table in enumerate(tables):
#                     if not table:
#                         continue
 
#                     # Skip tables that are mostly empty
#                     non_empty = sum(
#                         1 for row in table
#                         for cell in row
#                         if cell and str(cell).strip()
#                     )
#                     if non_empty < 3:
#                         continue
 
#                     # Build markdown rows — collapse newlines inside cells
#                     rows = []
#                     for row in table:
#                         cleaned = [
#                             str(cell).replace("\n", " ").strip() if cell else ""
#                             for cell in row
#                         ]
#                         rows.append("| " + " | ".join(cleaned) + " |")
 
#                     if len(rows) < 2:
#                         continue
 
#                     # Insert separator after header row
#                     header_sep = "| " + " | ".join(["---"] * len(table[0])) + " |"
#                     rows.insert(1, header_sep)
 
#                     # FIX: join with newlines so markdown table is valid
#                     markdown_table = "\n".join(rows)
 
#                     # Skip duplicate tables
#                     content_hash = hashlib.md5(markdown_table.encode()).hexdigest()
#                     if content_hash in seen_hashes:
#                         continue
#                     seen_hashes.add(content_hash)
 
#                     doc = Document(
#                         page_content=f"[TABLE from page {page_num + 1}]\n{markdown_table}",
#                         metadata={
#                             "source": pdf_path,
#                             "source_file": filename,
#                             "page": page_num,
#                             "type": "table",
#                             "table_index": table_idx,
#                         },
#                     )
#                     print(f"Extracted table from {filename} page {page_num + 1}, table {table_idx + 1}")
#                     table_docs.append(doc)
 
#     except Exception as e:
#         st.warning(f"Could not extract tables from {filename}: {e}")
    
#     print(table_docs)
#     return table_docs

# Ver 3.0: Added content hashing to skip duplicate tables and improved logging.
# def extract_tables_from_pdf(pdf_path: str, filename: str) -> list:
#     """
#     Extract tables from a PDF using pdfplumber and convert each to
#     a markdown-formatted Document chunk for indexing.

#     - Rows are newline-separated so markdown renders correctly
#     - Multi-line cell content is collapsed to a single line
#     - Nearly-empty tables are skipped
#     - Duplicate tables (by content hash) are skipped

#     Returns an empty list if pdfplumber is not installed or extraction fails.
#     """
#     if pdfplumber is None or Document is None:
#         return []

#     table_docs = []
#     seen_hashes = set()

#     try:
#         with pdfplumber.open(pdf_path) as pdf:
#             for page_num, page in enumerate(pdf.pages):
#                 tables = page.extract_tables()

#                 for table_idx, table in enumerate(tables):
#                     if not table:
#                         continue

#                     # Skip tables that are mostly empty
#                     non_empty = sum(
#                         1 for row in table
#                         for cell in row
#                         if cell and str(cell).strip()
#                     )
#                     if non_empty < 3:
#                         continue

#                     # Build markdown rows — collapse newlines inside cells
#                     rows = []
#                     for row in table:
#                         cleaned = [
#                             str(cell).replace("\n", " ").strip() if cell else ""
#                             for cell in row
#                         ]
#                         rows.append("| " + " | ".join(cleaned) + " |")

#                     if len(rows) < 2:
#                         continue

#                     # Insert separator after header row
#                     header_sep = "| " + " | ".join(["---"] * len(table[0])) + " |"
#                     rows.insert(1, header_sep)

#                     markdown_table = "\n".join(rows)

#                     # Skip duplicate tables
#                     content_hash = hashlib.md5(markdown_table.encode()).hexdigest()
#                     if content_hash in seen_hashes:
#                         continue
#                     seen_hashes.add(content_hash)

#                     doc = Document(
#                         page_content=f"[TABLE from page {page_num + 1}]\n{markdown_table}",
#                         metadata={
#                             "source": pdf_path,
#                             "source_file": filename,
#                             "page": page_num,
#                             "type": "table",
#                             "table_index": table_idx,
#                         },
#                     )
#                     print(f"Extracted table from {filename} page {page_num + 1}, table {table_idx + 1}")

                    
#                     table_docs.append(doc)

#     except Exception as e:
#         st.warning(f"Could not extract tables from {filename}: {e}")

#     print(table_docs)
#     return table_docs


# ver 4.0: pymupdf4llm

import hashlib
 
try:
    import pymupdf4llm
except ImportError:
    pymupdf4llm = None
 
try:
    from langchain_core.documents import Document
except ImportError:
    try:
        from langchain.schema import Document
    except ImportError:
        Document = None
 
 
def load_pdf_as_markdown(pdf_path: str, filename: str) -> list:
    """
    Load a PDF and convert each page to a markdown Document using pymupdf4llm.
 
    pymupdf4llm preserves tables, headers, and text layout as clean markdown
    in a single pass — no separate table extraction needed.
 
    - Each page becomes one Document
    - Tables are rendered as proper markdown tables
    - Duplicate pages are skipped (by content hash)
 
    Returns an empty list if pymupdf4llm is not installed or extraction fails.
    """
    if pymupdf4llm is None:
        raise ImportError("pymupdf4llm is not installed. Run: pip install pymupdf4llm")
 
    if Document is None:
        raise ImportError("langchain is not installed.")
 
    docs = []
    seen_hashes = set()
 
    try:
        # page_chunks=True returns one dict per page
        pages = pymupdf4llm.to_markdown(pdf_path, page_chunks=True)
 
        for page_data in pages:
            text = page_data.get("text", "").strip()
            if not text:
                continue
 
            # pymupdf4llm metadata uses 'page' key (0-indexed)
            page_num = page_data.get("metadata", {}).get("page", pages.index(page_data))
 
            # Skip duplicate pages
            content_hash = hashlib.md5(text.encode()).hexdigest()
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)
 
            doc = Document(
                page_content=text,
                metadata={
                    "source": pdf_path,
                    "source_file": filename,
                    "page": page_num,
                    "type": "text",
                },
            )
            docs.append(doc)
 
    except Exception as e:
        raise RuntimeError(f"Could not load {filename}: {e}")
    
    # print(docs) Debug: log extracted documents
    return docs
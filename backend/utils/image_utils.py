"""
image_utils.py — Extract images from PDFs using PyMuPDF (fitz).

For each page in the PDF every embedded image larger than MIN_IMAGE_SIZE_PX
is extracted, converted to RGB PNG, and saved to:
    <output_dir>/images/<filename_stem>_p<page>_img<idx>.png

Returns a list of dicts:
    {
        "path":        absolute path to saved PNG,
        "filename":    original PDF filename,
        "page":        0-indexed page number,
        "img_index":   image index on that page,
        "width":       pixel width,
        "height":      pixel height,
        "img_id":      unique string id  "<stem>_p<page>_img<idx>",
        "ocr_text":    text extracted from image via OCR,
        "caption":     extracted figure/table caption from surrounding text
    }
"""

import os
import io
import re
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from config import MIN_IMAGE_SIZE_PX

# Try to import OCR libraries (optional)
try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False
    print("[image_utils] pytesseract not found - OCR disabled")


def extract_ocr_text(pil_img: Image.Image) -> str:
    """Extract text from image using OCR."""
    if not HAS_TESSERACT:
        return ""

    try:
        text = pytesseract.image_to_string(pil_img, config='--psm 6')
        # Clean up the text
        text = ' '.join(text.split())  # normalize whitespace
        return text.strip()
    except Exception as e:
        print(f"[image_utils] OCR failed: {e}")
        return ""


def detect_table_in_image(pil_img: Image.Image, ocr_text: str) -> bool:
    """
    Heuristic to detect if an image is likely a table.
    Returns True if the image appears to contain tabular data.
    """
    # Check OCR text for table indicators
    table_indicators = [
        'table', '|', '---', '===',  # Common table markers
        '\t\t',  # Multiple tabs suggest columns
    ]

    # Count lines and check for consistent structure
    if ocr_text:
        lines = ocr_text.split('\n')
        # Tables usually have multiple lines
        if len(lines) < 3:
            return False

        # Check for table indicators in text
        text_lower = ocr_text.lower()
        if any(indicator in text_lower for indicator in table_indicators):
            return True

        # Check for numerical data in multiple lines (common in tables)
        numeric_lines = sum(1 for line in lines if re.search(r'\d', line))
        if numeric_lines > len(lines) * 0.5:  # >50% lines contain numbers
            return True

    # Check image aspect ratio - tables are often wider than tall
    width, height = pil_img.size
    aspect_ratio = width / height
    if aspect_ratio > 1.5:  # Wide images might be tables
        return True

    return False


def extract_caption_from_page(page: fitz.Page, page_num: int, img_idx: int) -> tuple[str, str]:
    """
    Try to extract figure/table caption from the page text.
    Returns: (caption_text, image_type) where image_type is 'table' or 'figure'
    """
    try:
        page_text = page.get_text("text")

        # Try to find captions for this specific image
        # Common patterns with various numbering schemes
        patterns = {
            'table': [
                rf"(?:Table|TABLE)\s*(\d+[a-z]?)[\.\:]?\s*([^\n]+)",
            ],
            'figure': [
                rf"(?:Figure|Fig\.|FIG\.?)\s*(\d+[a-z]?)[\.\:]?\s*([^\n]+)",
            ]
        }

        best_caption = ""
        best_score = 0
        image_type = "figure"  # default

        for img_type, pattern_list in patterns.items():
            for pattern in pattern_list:
                for match in re.finditer(pattern, page_text, re.IGNORECASE | re.MULTILINE):
                    fig_num = match.group(1)
                    caption = match.group(2).strip()

                    # Score this caption based on relevance
                    score = 1
                    # Prefer captions with numbers close to the image index
                    try:
                        num = int(re.sub(r'[^0-9]', '', fig_num))
                        # If the figure number is close to image index, boost score
                        if abs(num - (img_idx + 1)) <= 2:
                            score += 2
                    except:
                        pass

                    # Boost if it contains keywords that might be in the image
                    keywords = ['attention', 'transformer', 'architecture', 'model',
                               'layer', 'matrix', 'vector', 'embedding', 'scaling',
                               'query', 'key', 'value', 'multi-head', 'bleu', 'score']
                    if any(kw in caption.lower() for kw in keywords):
                        score += 1

                    if score > best_score:
                        best_score = score
                        best_caption = caption
                        image_type = img_type

        # Limit caption length
        if best_caption and len(best_caption) > 250:
            best_caption = best_caption[:250] + "..."

        return best_caption, image_type

    except Exception as e:
        print(f"[image_utils] Caption extraction failed: {e}")
        return "", "figure"


def extract_images_from_pdf(
    pdf_path: str,
    filename: str,
    output_dir: str,
) -> list[dict]:
    """Extract all non-trivial images from a PDF and save as PNGs."""
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    stem = Path(filename).stem
    results: list[dict] = []

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"[image_utils] Cannot open {filename}: {e}")
        return results

    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)

        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                img_bytes  = base_image["image"]
                img_ext    = base_image.get("ext", "png")

                pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                w, h    = pil_img.size

                # Skip tiny images (icons, bullets, borders)
                if w < MIN_IMAGE_SIZE_PX or h < MIN_IMAGE_SIZE_PX:
                    continue

                img_id   = f"{stem}_p{page_num}_img{img_idx}"
                img_name = f"{img_id}.png"
                img_path = os.path.join(images_dir, img_name)

                pil_img.save(img_path, "PNG")

                # Extract OCR text from the image
                ocr_text = extract_ocr_text(pil_img)

                # Try to find caption in page text and detect image type
                caption, img_type_from_caption = extract_caption_from_page(page, page_num, img_idx)

                # Detect if this is a table using heuristics
                is_table = detect_table_in_image(pil_img, ocr_text)

                # Determine final type: prefer caption-based detection, then heuristic
                if img_type_from_caption == "table":
                    img_type = "table"
                elif is_table:
                    img_type = "table"
                else:
                    img_type = "figure"

                results.append(
                    {
                        "path":      img_path,
                        "filename":  filename,
                        "page":      page_num,
                        "img_index": img_idx,
                        "width":     w,
                        "height":    h,
                        "img_id":    img_id,
                        "ocr_text":  ocr_text,
                        "caption":   caption,
                        "type":      img_type,  # "table" or "figure"
                    }
                )
            except Exception as e:
                print(f"[image_utils] Skip xref {xref} on page {page_num}: {e}")
                continue

    doc.close()
    print(f"[image_utils] Extracted {len(results)} images from {filename}")
    return results

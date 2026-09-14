"""Đọc tài liệu (PDF, DOCX, TXT, MD, ảnh) và chia thành các đoạn (chunk) để truy hồi.

Hỗ trợ Gemini Vision cho PDF dạng ảnh scan (từng trang được thử trích xuất text
trước, trang nào không có text mới render thành ảnh rồi nhận diện) và cho ảnh
chụp/scan tải lên trực tiếp (PNG/JPG/…)."""
import io
import os
import re
import uuid

from pypdf import PdfReader
from docx import Document as DocxDocument
from PIL import Image

try:
    import fitz  # PyMuPDF — render trang PDF thành ảnh để OCR
except ImportError:
    fitz = None

import llm_client

CHUNK_SIZE = 900  # ký tự
CHUNK_OVERLAP = 150

OCR_DPI = 150
MIN_TEXT_LEN_BEFORE_OCR = 25  # ít hơn ngần này ký tự -> coi như trang scan, thử OCR
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}


class OCRUnavailableError(Exception):
    """Gemini Vision chưa sẵn sàng hoặc không đọc được tài liệu."""


def _ocr_image(img):
    try:
        return llm_client.extract_text_from_image(img)
    except llm_client.NotConfiguredError as e:
        raise OCRUnavailableError(
            "Chưa cấu hình Google AI API key để đọc tài liệu bằng Gemini Vision. "
            "Vào Cài đặt để nhập key."
        ) from e
    except Exception as e:
        raise OCRUnavailableError(f"Gemini Vision không đọc được ảnh tài liệu: {e}") from e


def _ocr_pdf_page(fitz_doc, page_index):
    page = fitz_doc[page_index]
    zoom = OCR_DPI / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return _ocr_image(img)


def extract_pages(file_path, ext, use_ocr=True, progress=None, on_partial_pages=None):
    """Trả về list[(text, position_label)] — mỗi phần tử là một trang/khối gốc.
    on_partial_pages(pages_so_far): nếu được truyền, sẽ được gọi sau mỗi trang PDF
    đã xử lý xong, để nơi gọi có thể tự lưu tạm tiến trình (phòng khi tiến trình
    bị tắt đột ngột giữa chừng)."""
    ext = ext.lower()
    if ext == ".pdf":
        reader = PdfReader(file_path)
        n_pages = len(reader.pages)
        fitz_doc = None
        pages = []
        try:
            for i in range(n_pages):
                if progress:
                    progress(i + 1, n_pages)
                text = (reader.pages[i].extract_text() or "").strip()
                ocr_used = False
                if use_ocr and len(text) < MIN_TEXT_LEN_BEFORE_OCR and fitz is not None:
                    if fitz_doc is None:
                        fitz_doc = fitz.open(file_path)
                    try:
                        ocr_text = _ocr_pdf_page(fitz_doc, i).strip()
                    except OCRUnavailableError:
                        raise
                    except Exception:
                        ocr_text = ""
                    if len(ocr_text) > len(text):
                        text = ocr_text
                        ocr_used = True
                if text:
                    label = f"Trang {i + 1}" + (" (OCR)" if ocr_used else "")
                    pages.append((text, label))
                if on_partial_pages:
                    try:
                        on_partial_pages(pages)
                    except Exception:
                        pass
        finally:
            if fitz_doc is not None:
                fitz_doc.close()
        return pages

    if ext in IMAGE_EXTS:
        img = Image.open(file_path)
        text = _ocr_image(img).strip()
        if not text:
            raise ValueError("Không nhận diện được chữ nào trong ảnh này (OCR trống).")
        return [(text, "Ảnh (OCR)")]

    if ext == ".docx":
        doc = DocxDocument(file_path)
        paras = [p.text for p in doc.paragraphs if p.text.strip()]
        # Gom mỗi ~15 đoạn văn thành một "trang" ảo để có vị trí trích dẫn hợp lý
        pages = []
        block = []
        block_no = 1
        for p in paras:
            block.append(p)
            if len(block) >= 15:
                pages.append(("\n".join(block), f"Đoạn {block_no}"))
                block = []
                block_no += 1
        if block:
            pages.append(("\n".join(block), f"Đoạn {block_no}"))
        return pages

    if ext in (".txt", ".md"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        # Chia theo khối ~1500 ký tự làm "trang" ảo
        pages = []
        for i in range(0, len(text), 1500):
            block = text[i : i + 1500]
            if block.strip():
                pages.append((block, f"Vị trí {i}"))
        return pages

    raise ValueError(f"Định dạng chưa hỗ trợ: {ext}")


def chunk_text(text, overlap=CHUNK_OVERLAP, size=CHUNK_SIZE):
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunk = text[start:end]
        chunks.append(chunk)
        if end == len(text):
            break
        start = end - overlap
    return chunks


def build_document(pages, original_name, ext, doc_id=None):
    """Dựng document {id, name, source_type, ocr_pages, chunks} từ danh sách
    (text, position) đã trích xuất được — dùng chung cho cả bản lưu tạm (đang
    quét dở) lẫn bản hoàn chỉnh khi quét xong."""
    chunks = []
    ocr_pages = 0
    for page_text, position in pages:
        if "(OCR)" in position:
            ocr_pages += 1
        for piece in chunk_text(page_text):
            chunks.append(
                {
                    "id": uuid.uuid4().hex[:8],
                    "text": piece,
                    "position": position,
                }
            )
    return {
        "id": doc_id or uuid.uuid4().hex[:10],
        "name": original_name,
        "source_type": ext.lstrip("."),
        "ocr_pages": ocr_pages,
        "chunks": chunks,
    }


def parse_document(file_path, original_name, use_ocr=True, progress=None, on_partial_pages=None, doc_id=None):
    ext = os.path.splitext(original_name)[1]
    pages = extract_pages(file_path, ext, use_ocr=use_ocr, progress=progress, on_partial_pages=on_partial_pages)
    doc = build_document(pages, original_name, ext, doc_id=doc_id)

    if not doc["chunks"]:
        raise ValueError(
            "Không trích xuất được nội dung văn bản nào từ tệp này (kể cả sau khi thử OCR)."
        )

    return doc

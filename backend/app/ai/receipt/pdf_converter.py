"""In-memory PDF to PNG converter (never writes uploaded receipts to local disk)."""

from __future__ import annotations

import io

import pypdfium2 as pdfium


def render_pdf_bytes_to_png_pages(
    pdf_bytes: bytes,
    *,
    max_pages: int = 5,
    scale: float = 2.0,
) -> list[bytes]:
    """Render up to `max_pages` of a PDF into PNG byte buffers purely in memory."""
    doc = pdfium.PdfDocument(pdf_bytes)
    rendered: list[bytes] = []
    try:
        total_pages = min(len(doc), max_pages)
        for idx in range(total_pages):
            page = doc[idx]
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil()
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            rendered.append(buf.getvalue())
            page.close()
    finally:
        doc.close()
    return rendered

from __future__ import annotations

from pathlib import Path

from .model import Page


def render_pdf_pages(pdf_path: Path, output_dir: Path, url_prefix: str, scale: float = 1.45) -> list[Page]:
    import pypdfium2 as pdfium

    output_dir.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(str(pdf_path))
    pages: list[Page] = []
    try:
        for index in range(len(document)):
            page = document[index]
            width, height = page.get_size()
            image = page.render(scale=scale).to_pil()
            name = f"page-{index + 1:04d}.webp"
            image.save(output_dir / name, "WEBP", quality=88, method=4)
            pages.append(Page(index + 1, float(width), float(height), f"{url_prefix}/{index + 1}/image"))
            page.close()
    finally:
        document.close()
    return pages

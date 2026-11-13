from __future__ import annotations

import logging
import math
import re
import threading
from collections.abc import Callable
from pathlib import Path

from .model import BBox, Block, Evidence, Page

LOGGER = logging.getLogger(__name__)
_PARSER = None
_PARSER_LOCK = threading.Lock()


def _parser():
    global _PARSER
    if _PARSER is None:
        from deepdoc.parser.pdf_parser import RAGFlowPdfParser

        _PARSER = RAGFlowPdfParser()
    return _PARSER


def _save_region(image, target: Path) -> bool:
    if image is None:
        return False
    try:
        if hasattr(image, "save"):
            image.save(target, "WEBP", quality=90)
            return True
        if isinstance(image, (list, tuple)) and image and hasattr(image[0], "save"):
            image[0].save(target, "WEBP", quality=90)
            return True
    except Exception:
        LOGGER.exception("Failed to save DeepDOC region image: %s", target)
    return False


def _score(value) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else 0.82
    except (TypeError, ValueError, OverflowError):
        return 0.82


def _plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return str(value)


def _normalize_position(item, pages: list[Page]) -> dict | None:
    if len(item) < 5:
        return None
    page_number = int(item[0])
    x0, x1, y0, y1 = float(item[1]), float(item[2]), float(item[3]), float(item[4])
    original = (page_number, x0, y0, x1, y1)
    # DeepDOC batch mode can retain a batch-global Y offset while resetting the
    # accompanying page number. Walk the real page heights to restore a local
    # coordinate and physical page instead of emitting a 25,000-point bbox.
    while 1 <= page_number <= len(pages) and y0 >= pages[page_number - 1].height:
        height = pages[page_number - 1].height
        y0 -= height
        y1 -= height
        page_number += 1
    if not 1 <= page_number <= len(pages):
        return None
    page = pages[page_number - 1]
    if y1 <= 0 or y0 >= page.height or x1 <= 0 or x0 >= page.width:
        return None
    x0, x1 = max(0.0, x0), min(page.width, x1)
    y0, y1 = max(0.0, y0), min(page.height, y1)
    if x1 <= x0 or y1 <= y0:
        return None
    result = {"page": page_number, "bbox": [x0, y0, x1, y1]}
    if original != (page_number, x0, y0, x1, y1):
        result["coordinate_repaired"] = True
        result["source_position"] = list(original)
    return result


def _position_slices(positions, raw_type: str, pages: list[Page]) -> list[dict]:
    slices = [normalized for item in positions if (normalized := _normalize_position(item, pages)) is not None]
    if not slices:
        return []
    page_number = int(slices[0]["page"])
    if raw_type.lower() != "table" or len({item["page"] for item in slices}) <= 1:
        return slices
    pages = sorted({item["page"] for item in slices})
    # A real cross-page table occupies consecutive pages.  DeepDOC can attach a
    # tiny, repeated-text match from a distant page to an otherwise valid table;
    # treating that as a continuation corrupts both the page index and output.
    contiguous: set[int] = {page_number}
    for candidate in range(page_number - 1, pages[0] - 1, -1):
        if candidate in pages:
            contiguous.add(candidate)
        else:
            break
    for candidate in range(page_number + 1, pages[-1] + 1):
        if candidate in pages:
            contiguous.add(candidate)
        else:
            break
    return [item for item in slices if item["page"] in contiguous]


def parse_pdf_with_deepdoc(
    pdf_path: Path,
    regions_dir: Path,
    region_url_prefix: str,
    pages: list[Page],
    progress: Callable[[float, str], None] | None = None,
) -> list[Block]:
    regions_dir.mkdir(parents=True, exist_ok=True)

    def callback(value=0.0, message=""):
        if progress:
            progress(float(value or 0.0), str(message or "DeepDOC"))

    with _PARSER_LOCK:
        boxes = _parser().parse_into_bboxes(str(pdf_path), callback=callback)
    page_by_number = {page.number: page for page in pages}
    result: list[Block] = []
    for order, box in enumerate(boxes):
        positions = box.get("positions") or []
        raw_type = str(box.get("layout_type") or "text")
        position_slices = _position_slices(positions, raw_type, pages)
        position = position_slices[0] if position_slices else None
        page_number = int(position["page"]) if position else max(1, min(len(pages), int(box.get("page_number") or 1)))
        bbox = BBox(*position["bbox"]) if position else None
        text = str(box.get("text") or "").strip()
        table_html = text if "<table" in text.lower() else ""
        block_id = f"deepdoc-{order}"
        region_name = f"{block_id}.webp"
        region_path = regions_dir / region_name
        keep_region = raw_type.lower() in {"table", "figure", "image", "equation", "title", "document title"} or not text
        region_url = ""
        if keep_region and _save_region(box.get("image"), region_path):
            region_url = f"{region_url_prefix}/{region_name}"
        attributes = {
            "deepdoc_layout": raw_type,
            "layout_number": _plain(box.get("layoutno")),
            "deepdoc_score": _score(box.get("score")),
            "position_slices": position_slices,
        }
        if any(item.get("coordinate_repaired") for item in position_slices):
            attributes["coordinate_repaired"] = True
        attributes["spans_pages"] = len({item["page"] for item in attributes["position_slices"]}) > 1
        page = page_by_number.get(page_number)
        if page and bbox:
            attributes["near_page_top"] = bbox.y0 <= page.height * 0.12
            attributes["near_page_bottom"] = bbox.y1 >= page.height * 0.88
        result.append(
            Block(
                id=block_id,
                type=raw_type,
                text=re.sub(r"@@[\t0-9.\-]+?##", "", text),
                page=page_number,
                bbox=bbox,
                html=table_html,
                reading_order=order,
                confidence=_score(box.get("score")),
                region_image=region_url,
                attributes=attributes,
                evidence=[Evidence("deepdoc", block_id, _score(box.get("score")), "OCR/layout/table pipeline")],
            )
        )
        for page_slice in attributes["position_slices"] or [{"page": page_number}]:
            target_page = page_by_number.get(page_slice["page"])
            if target_page and block_id not in target_page.block_ids:
                target_page.block_ids.append(block_id)
    return result

from __future__ import annotations

import re
from html import escape, unescape
from pathlib import Path

import pdfplumber

from .model import BBox, Block, Evidence, Page, ParseIssue

PAGE_LABEL_RE = re.compile(r"^(?:\d{1,4}|[IVXLCDM]{1,8})$", re.IGNORECASE)
SECTION_START_RE = re.compile(r"^(?:[a-z]\)\s*)?(?:\d+(?:\.\d+){0,6}|前言|目录)\b", re.IGNORECASE)
LEADER_RE = re.compile(r"[.．。·…]{2,}")


def _join_words(words: list[dict]) -> str:
    parts: list[str] = []
    previous_right: float | None = None
    average_height = sum(float(word.get("bottom", 0)) - float(word.get("top", 0)) for word in words) / max(1, len(words))
    for word in words:
        text = str(word.get("text", ""))
        if not text:
            continue
        if previous_right is not None:
            gap = float(word.get("x0", 0)) - previous_right
            if gap > max(2.5, average_height * 0.28):
                parts.append(" ")
        parts.append(text)
        previous_right = float(word.get("x1", 0))
    return "".join(parts).strip()


def _group_lines(words: list[dict]) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for word in sorted(words, key=lambda item: (float(item.get("top", 0)), float(item.get("x0", 0)))):
        top = float(word.get("top", 0))
        height = max(1.0, float(word.get("bottom", top + 1)) - top)
        target: list[dict] | None = None
        best_distance = float("inf")
        for row in rows[-4:]:
            row_top = sum(float(item.get("top", 0)) for item in row) / len(row)
            row_height = sum(max(1.0, float(item.get("bottom", 0)) - float(item.get("top", 0))) for item in row) / len(row)
            distance = abs(top - row_top)
            if distance <= max(2.2, min(height, row_height) * 0.38) and distance < best_distance:
                target = row
                best_distance = distance
        if target is None:
            rows.append([word])
        else:
            target.append(word)
    return [sorted(row, key=lambda item: float(item.get("x0", 0))) for row in rows]


def _toc_parts(words: list[dict], page_width: float) -> tuple[str, str] | None:
    if len(words) < 2:
        return None
    right_column = [word for word in words if float(word.get("x0", 0)) >= page_width * 0.72]
    if not right_column:
        return None
    label = _join_words(right_column).replace(" ", "").strip(".．。·… ")
    if not PAGE_LABEL_RE.fullmatch(label):
        return None
    label_left = min(float(word.get("x0", 0)) for word in right_column)
    title_words = [word for word in words if float(word.get("x1", 0)) < label_left - 1]
    title = _join_words(title_words).strip()
    title = re.sub(r"[.．。·…\s]+$", "", title).strip()
    if len(title) < 2:
        return None
    full_text = _join_words(words)
    # This function only runs on pages already identified as a TOC window.
    # Some PDFs encode leader dots as drawing commands rather than characters,
    # so a right-aligned page label is valid evidence even without literal dots.
    if not (LEADER_RE.search(full_text) or SECTION_START_RE.match(title) or re.match(r"^[§a-zA-Z一二三四五六七八九十、]", title)):
        return None
    return title, label.upper() if label.isalpha() else label


def _native_rows(page) -> list[tuple[list[dict], str]]:
    """Return visual text rows from both word and character channels.

    Word extraction is clean on ordinary prose, while Word-generated TOCs can
    store leaders and page labels as separately positioned characters.  The
    character channel recovers those rows without invoking OCR.
    """

    candidates: list[tuple[list[dict], str]] = []
    words = page.extract_words(x_tolerance=1.8, y_tolerance=2.0, keep_blank_chars=False, use_text_flow=False)
    candidates.extend((row, "words") for row in _group_lines(words))
    characters = [item for item in page.chars if str(item.get("text", "")).strip()]
    candidates.extend((row, "characters") for row in _group_lines(characters))
    return candidates


def _line_key(text: str, bbox: tuple[float, float, float, float]) -> tuple[str, int, int]:
    compact = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text).lower()
    return compact, round((bbox[1] + bbox[3]) / 2), round(bbox[0])


def _normalize_table(rows: list[list[str | None]] | None) -> list[list[str]]:
    if not rows:
        return []
    normalized = [[re.sub(r"\s+", " ", str(cell or "")).strip() for cell in row] for row in rows]
    normalized = [row for row in normalized if any(row)]
    if not normalized:
        return []
    width = max(len(row) for row in normalized)
    normalized = [row + [""] * (width - len(row)) for row in normalized]
    keep_columns = [column for column in range(width) if any(row[column] for row in normalized)]
    return _repair_numeric_grid([[row[column] for column in keep_columns] for row in normalized])


def _numeric_parts(value: str) -> list[str]:
    normalized = value.replace("，", ",").strip()
    if not normalized or re.search(r"[A-Za-z\u4e00-\u9fff]", normalized):
        return []
    return re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?(?:\s*[–—~-]\s*\d+(?:,\d{3})*(?:\.\d+)?)?", normalized)


def _repair_numeric_grid(rows: list[list[str]]) -> list[list[str]]:
    """Repair two conservative coordinate-extraction failure shapes.

    The operation only redistributes existing numeric tokens; it never creates
    or guesses a value.  This covers a common PDF text-layer behavior where a
    row boundary or a thousands separator lands in the adjacent cell.
    """

    repaired = [list(row) for row in rows]
    for index in range(len(repaired) - 1):
        row, following = repaired[index], repaired[index + 1]
        if len(row) == len(following) == 2:
            left, right = _numeric_parts(row[0]), _numeric_parts(row[1])
            next_left, next_right = _numeric_parts(following[0]), _numeric_parts(following[1])
            if len(left) == 1 and len(right) == 2 and len(next_left) == 1 and not next_right:
                row[1], following[1] = right[0], right[1]
            elif len(left) == 2 and len(right) == 1 and not next_left and len(next_right) == 1:
                row[0], following[0] = left[0], left[1]
        for column in range(len(row) - 1):
            suffix = re.fullmatch(r"(.*?)\s+(\d{1,3},)\s*", row[column])
            following_range = re.fullmatch(r"(\d{3}\s*[–—~-]\s*\d{1,3},\d{3})", row[column + 1].strip())
            if suffix and suffix.group(1).strip() and following_range:
                row[column] = suffix.group(1).strip()
                row[column + 1] = suffix.group(2) + following_range.group(1)
    return repaired


def _table_html(rows: list[list[str]]) -> str:
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>")
    return "<table>" + "".join(body) + "</table>"


def _number_tokens(value: str) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?:[–—~-]\d+(?:\.\d+)?)?", value))


def _text_layer_trustworthy(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    return bool(compact) and compact.count("\ufffd") / len(compact) < 0.01


def _bbox_overlap(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    x0, y0 = max(left[0], right[0]), max(left[1], right[1])
    x1, y1 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    left_area = max(1.0, (left[2] - left[0]) * (left[3] - left[1]))
    right_area = max(1.0, (right[2] - right[0]) * (right[3] - right[1]))
    return intersection / min(left_area, right_area)


def recover_native_pdf_tables(pdf_path: Path, blocks: list[Block]) -> tuple[list[ParseIssue], dict[str, int]]:
    """Recover ruled/native PDF tables conservatively and keep DeepDOC as fallback."""
    targets = [block for block in blocks if block.type.lower() == "table" and block.page and block.bbox]
    issues: list[ParseIssue] = []
    metrics = {
        "candidate_count": len(targets),
        "recovered_count": 0,
        "rejected_count": 0,
        "missing_table_count": 0,
        "superseded_fragment_count": 0,
    }
    superseded_ids: set[str] = set()
    with pdfplumber.open(str(pdf_path)) as document:
        for block in targets:
            page = document.pages[block.page - 1]
            bbox = block.bbox
            crop_box = (
                max(0.0, bbox.x0 - 2),
                max(0.0, bbox.y0 - 2),
                min(float(page.width), bbox.x1 + 2),
                min(float(page.height), bbox.y1 + 2),
            )
            if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
                metrics["rejected_count"] += 1
                continue
            crop = page.crop(crop_box)
            strategies = [
                {
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance": 3,
                    "join_tolerance": 3,
                    "intersection_tolerance": 4,
                },
                {
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text",
                    "min_words_vertical": 2,
                    "min_words_horizontal": 1,
                    "intersection_tolerance": 5,
                },
            ]
            accepted: list[list[str]] = []
            accepted_strategy = ""
            original_numbers = _number_tokens(unescape(re.sub(r"<[^>]+>", " ", block.text or block.html)))
            for strategy in strategies:
                candidate = _normalize_table(crop.extract_table(strategy))
                if len(candidate) < 2 or len(candidate[0]) < 2:
                    continue
                cells = [cell for row in candidate for cell in row]
                if not _text_layer_trustworthy(" ".join(cells)):
                    continue
                fill_ratio = sum(bool(cell) for cell in cells) / len(cells)
                candidate_numbers = _number_tokens(" ".join(cells))
                number_recall = len(original_numbers & candidate_numbers) / len(original_numbers) if original_numbers else 1.0
                if fill_ratio < 0.55 or number_recall < 0.9:
                    continue
                accepted = candidate
                accepted_strategy = str(strategy["vertical_strategy"])
                break
            if not accepted:
                metrics["rejected_count"] += 1
                block.attributes["native_table_recovery"] = "rejected"
                continue
            block.attributes.update(
                {
                    "native_table_recovery": "accepted",
                    "native_table_strategy": accepted_strategy,
                    "deepdoc_html_preserved": block.html,
                }
            )
            block.html = _table_html(accepted)
            block.text = "\n".join("\t".join(row) for row in accepted)
            block.evidence.append(Evidence("pdf_native_table", f"page:{block.page}:bbox:{crop_box}", 0.96, "native PDF table lines/text grid"))
            metrics["recovered_count"] += 1
            issues.append(ParseIssue("native_table_recovered", "已用 PDF 原生文字坐标和表格线重建单元格网格", "info", block.id, block.page))
        occupied = {
            page_number: [(block.bbox.x0, block.bbox.y0, block.bbox.x1, block.bbox.y1) for block in targets if block.page == page_number and block.bbox]
            for page_number in range(1, len(document.pages) + 1)
        }
        line_settings = {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "intersection_tolerance": 4,
        }
        next_order = max((block.reading_order for block in blocks), default=-1) + 1
        for page_number, page in enumerate(document.pages, start=1):
            for table_index, table in enumerate(page.find_tables(line_settings)):
                bbox = tuple(float(value) for value in table.bbox)
                if any(_bbox_overlap(bbox, existing) >= 0.55 for existing in occupied[page_number]):
                    continue
                candidate = _normalize_table(table.extract())
                if len(candidate) < 2 or len(candidate[0]) < 2:
                    continue
                cells = [cell for row in candidate for cell in row]
                fill_ratio = sum(bool(cell) for cell in cells) / len(cells)
                if fill_ratio < 0.55 or not _text_layer_trustworthy(" ".join(cells)):
                    continue
                block_id = f"native-table-{page_number}-{table_index}"
                text = "\n".join("\t".join(row) for row in candidate)
                superseded = [
                    source
                    for source in blocks
                    if source.page == page_number
                    and source.bbox
                    and source.type.lower() not in {"table", "figure", "image"}
                    and _bbox_overlap(bbox, (source.bbox.x0, source.bbox.y0, source.bbox.x1, source.bbox.y1)) >= 0.7
                ]
                superseded_ids.update(source.id for source in superseded)
                blocks.append(
                    Block(
                        id=block_id,
                        type="table",
                        text=text,
                        page=page_number,
                        bbox=BBox(*bbox),
                        html=_table_html(candidate),
                        reading_order=next_order,
                        confidence=0.96,
                        attributes={
                            "native_table_recovery": "detected_missing",
                            "native_table_strategy": "lines",
                            "superseded_block_ids": [source.id for source in superseded],
                        },
                        evidence=[Evidence("pdf_native_table", f"page:{page_number}:bbox:{bbox}", 0.96, "ruled table absent from DeepDOC output")],
                    )
                )
                next_order += 1
                occupied[page_number].append(bbox)
                metrics["missing_table_count"] += 1
                issues.append(ParseIssue("native_table_added", "发现 DeepDOC 遗漏的有线表格，已从 PDF 原生网格补回", "info", block_id, page_number))
    if superseded_ids:
        blocks[:] = [block for block in blocks if block.id not in superseded_ids]
        metrics["superseded_fragment_count"] = len(superseded_ids)
    return issues, metrics


def _compact(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", value).lower()


def _shingles(value: str, width: int = 4) -> set[str]:
    compact = _compact(value)
    if len(compact) <= width:
        return {compact} if compact else set()
    return {compact[index : index + width] for index in range(len(compact) - width + 1)}


def measure_native_pdf_coverage(pdf_path: Path, blocks: list[Block], pages: list[Page]) -> list[ParseIssue]:
    """Compare DeepDOC output with the PDF text layer before any post-processing."""
    issues: list[ParseIssue] = []
    blocks_by_page: dict[int, list[Block]] = {}
    for block in blocks:
        if block.page:
            blocks_by_page.setdefault(block.page, []).append(block)
    with pdfplumber.open(str(pdf_path)) as document:
        for page_number, pdf_page in enumerate(document.pages, start=1):
            native = pdf_page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            if not _text_layer_trustworthy(native):
                pages[page_number - 1].attributes["native_text_coverage"] = {"status": "unavailable", "reason": "unreliable_character_mapping"}
                continue
            expected = _shingles(native)
            if len(expected) < 10:
                continue
            candidate = "\n".join(
                unescape(re.sub(r"<[^>]+>", " ", block.text or block.html)) for block in blocks_by_page.get(page_number, [])
            )
            actual = _shingles(candidate)
            text_recall = len(expected & actual) / len(expected)
            expected_numbers = _number_tokens(native)
            actual_numbers = _number_tokens(candidate)
            number_recall = len(expected_numbers & actual_numbers) / len(expected_numbers) if expected_numbers else 1.0
            page = pages[page_number - 1]
            page.attributes["native_text_coverage"] = {
                "text_shingle_recall": round(text_recall, 3),
                "number_recall": round(number_recall, 3),
                "native_character_count": len(_compact(native)),
            }
            if text_recall < 0.72 or number_recall < 0.9:
                issues.append(
                    ParseIssue(
                        "source_content_gap",
                        f"DeepDOC 与 PDF 原生文字层覆盖不一致：正文 {text_recall:.0%}，数字/编号 {number_recall:.0%}",
                        "error",
                        page=page_number,
                    )
                )
    return issues


def extract_native_pdf_lines(pdf_path: Path, page_numbers: set[int] | None = None) -> list[Block]:
    """Extract trustworthy native PDF lines and TOC row hints.

    DeepDOC remains the visual parser.  This channel is deliberately limited to
    PDFs with a real text layer and is primarily used to recover reading order
    and the title/page relationship on dense table-of-contents pages.
    """

    blocks: list[Block] = []
    with pdfplumber.open(str(pdf_path)) as document:
        for page_number, page in enumerate(document.pages, start=1):
            if page_numbers is not None and page_number not in page_numbers:
                continue
            accepted: dict[tuple[str, int, int], Block] = {}
            for line_number, (words_in_line, extraction_channel) in enumerate(_native_rows(page)):
                text = _join_words(words_in_line)
                if not text:
                    continue
                x0 = min(float(word["x0"]) for word in words_in_line)
                y0 = min(float(word["top"]) for word in words_in_line)
                x1 = max(float(word["x1"]) for word in words_in_line)
                y1 = max(float(word["bottom"]) for word in words_in_line)
                attributes = {
                    "native_pdf_line": True,
                    "page_width": float(page.width),
                    "native_extraction_channel": extraction_channel,
                }
                toc = _toc_parts(words_in_line, float(page.width))
                if toc:
                    attributes.update({"toc_title": toc[0], "target_page_label": toc[1], "native_toc_row": True})
                bbox = (x0, y0, x1, y1)
                candidate = Block(
                    id=f"native-{page_number}-{extraction_channel}-{line_number}",
                    type="native_line",
                    text=text,
                    page=page_number,
                    bbox=BBox(*bbox),
                    confidence=0.99,
                    attributes=attributes,
                    evidence=[Evidence("pdf_native", f"page:{page_number}:{extraction_channel}:{line_number}", 0.99, "native PDF text and coordinates")],
                )
                key = _line_key(text, bbox)
                previous = accepted.get(key)
                if previous is None or (candidate.attributes.get("native_toc_row") and not previous.attributes.get("native_toc_row")):
                    accepted[key] = candidate
            blocks.extend(sorted(accepted.values(), key=lambda item: (item.bbox.y0, item.bbox.x0)))
    return blocks

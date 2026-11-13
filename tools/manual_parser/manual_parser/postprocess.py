from __future__ import annotations

import html
import re
from collections import Counter
from collections.abc import Iterable
from copy import deepcopy
from difflib import SequenceMatcher
from itertools import pairwise

from .model import Block, Page, ParseIssue
from .structure import (
    aggregate_safety_notices,
    canonical_reading_order,
    classify_page_furniture,
    classify_semantic_symbols,
    enrich_toc,
    recover_lists,
    refine_heading_types,
)
from .table_grid import assess_table_integrity, parse_table_grid, repair_numeric_alignment, table_grid_to_html

HEADING_NUMBER_RE = re.compile(r"^(?:第[一二三四五六七八九十百]+[章节]|\d+(?:\.\d+){1,5})[\s、.　]*")
CHINESE_SECTION_RE = re.compile(
    r"^[一二三四五六七八九十百]+、\s*.{1,24}(?:注意事项|预防措施|使用本手册|起吊说明|操作说明|拆装说明|标准紧固扭矩表|准备工作|总则)$"
)
LIST_PREFIX_RE = re.compile(r"^\s*(?:\d+|[A-Za-z]|[一二三四五六七八九十]+)[.)）(（、．]\s*[•●▪◦·-]?\s*", re.DOTALL)
CAPTION_RE = re.compile(r"^(?:图|表)\s*[A-Za-z0-9一二三四五六七八九十.-]+(?:[：:、.\s]|$)")
PAGE_LABEL_PATTERN = r"(?:\d{1,4}|[IVXLCDM]{1,8})"
TOC_RE = re.compile(rf"^(.{{2,160}}?)(?:[.．。·…]{{2,}}|\s{{3,}}|\t+)\s*({PAGE_LABEL_PATTERN})$", re.IGNORECASE)
PAGE_LABEL_RE = re.compile(rf"^[\s.．。·…]*({PAGE_LABEL_PATTERN})[\s.．。·…]*$", re.IGNORECASE)
WARNING_RE = re.compile(r"^(危险|警告|注意|小心|提示|重要|说明)\s*[！!：:]?")
SENTENCE_END_RE = re.compile(r"[。！？!?；;：:]$|[.!?;:]$")
ANCHOR_RE = re.compile(
    r"(?:[A-Z]{1,8}[-_/]?[A-Z0-9]{2,}|\d+(?:\.\d+)*(?:\s?(?:V|A|kW|kWh|MPa|bar|mm|cm|m|kg|h|℃|°C|N·m|Nm|%))?|\b\d{3,}\b)",
    re.IGNORECASE,
)


def clean_text(value: str) -> str:
    value = value.replace("\u3000", " ").replace("\ufeff", "")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff，。；：！？、）】])", "", value)
    value = re.sub(r"(?<=[（【])\s+(?=[\u4e00-\u9fff])", "", value)
    value = re.sub(r"(?<=[\u4e00-\u9fff])\s*[•●▪◦·]\s*(?=[\u4e00-\u9fff])", "", value)
    value = re.sub(r" *\n *", "\n", value)
    return value.strip()


def anchors(text: str) -> set[str]:
    visible_text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return {re.sub(r"\s+", "", item).lower() for item in ANCHOR_RE.findall(visible_text)}


def _page_labels(text: str) -> list[str]:
    if re.search(r"\d\.\d", text):
        return []
    labels = re.findall(PAGE_LABEL_PATTERN, text, flags=re.IGNORECASE)
    residue = re.sub(PAGE_LABEL_PATTERN, "", text, flags=re.IGNORECASE)
    if not labels or re.sub(r"[\s.．。·…]", "", residue):
        return []
    return [label.upper() if label.isalpha() else label for label in labels]


def anchor_recall(reference: str, candidate: str) -> float:
    expected = anchors(reference)
    if not expected:
        return 1.0
    return len(expected & anchors(candidate)) / len(expected)


def normalize_types(blocks: Iterable[Block]) -> list[Block]:
    type_map = {
        "text": "paragraph",
        "body": "paragraph",
        "title": "heading",
        "document title": "heading",
        "section_header": "heading",
        "section header": "heading",
        "figure": "figure",
        "image": "figure",
        "table": "table",
        "caption": "caption",
        "header": "page_header",
        "footer": "page_footer",
        "equation": "equation",
        "reference": "reference",
    }
    result = []
    for block in blocks:
        block.text = clean_text(block.text)
        raw_type = block.type.lower().strip().replace("-", "_")
        block.attributes.setdefault("source_type", raw_type)
        block.type = type_map.get(raw_type, raw_type or "paragraph")
        if raw_type == "document title" and not block.level:
            block.level = 1
        if block.type == "heading":
            block.text = re.sub(r"^(\d+(?:\.\d+)+)(?=[\u4e00-\u9fff])", r"\1 ", block.text)
        list_prefix = LIST_PREFIX_RE.match(block.text)
        if block.type == "paragraph" and (
            (HEADING_NUMBER_RE.match(block.text) and len(block.text) <= 80 and not list_prefix)
            or CHINESE_SECTION_RE.match(block.text)
        ):
            block.type = "heading"
            block.confidence = min(block.confidence, 0.86)
            block.attributes["heading_inferred"] = True
        if CAPTION_RE.match(block.text) and len(block.text) <= 160:
            block.type = "caption"
        warning = WARNING_RE.match(block.text)
        if warning:
            block.type = "warning"
            block.attributes["warning_level"] = warning.group(1)
        toc = TOC_RE.match(block.text.replace("\n", " "))
        if toc:
            block.type = "toc_entry"
            block.attributes.update({"toc_title": toc.group(1).strip(), "target_page_label": toc.group(2)})
        result.append(block)
    return result


def _native_toc_replacements(native_lines: list[Block] | None) -> dict[int, list[Block]]:
    if not native_lines:
        return {}
    pages: dict[int, list[Block]] = {}
    for block in native_lines:
        if block.page:
            pages.setdefault(block.page, []).append(block)
    replacements: dict[int, list[Block]] = {}
    for page, lines in pages.items():
        entries_by_key: dict[tuple[str, str], Block] = {}
        for line in lines:
            if not line.attributes.get("native_toc_row"):
                continue
            key = (
                re.sub(r"\s+", "", str(line.attributes.get("toc_title", ""))).lower(),
                str(line.attributes.get("target_page_label", "")).upper(),
            )
            previous = entries_by_key.get(key)
            if previous is None or line.attributes.get("native_extraction_channel") == "characters":
                entries_by_key[key] = line
        entries = list(entries_by_key.values())
        headers = [line for line in lines if "目录" in re.sub(r"\s+", "", line.text) and len(line.text) <= 24]
        # Continuation pages often omit the word "目录".  A high density of
        # rows ending in a right-column page label is sufficient evidence.
        if len(entries) < 5 or (not headers and len(entries) < 9):
            continue
        output: list[Block] = []
        if headers:
            header = min(headers, key=lambda item: item.bbox.y0 if item.bbox else 0)
            output.append(
                Block(
                    id=f"toc-heading-{page}",
                    type="heading",
                    text=header.text,
                    page=page,
                    bbox=deepcopy(header.bbox),
                    level=1,
                    confidence=header.confidence,
                    attributes={"toc_page": True, "source_type": "native_pdf"},
                    evidence=deepcopy(header.evidence),
                )
            )
        for index, line in enumerate(sorted(entries, key=lambda item: (item.bbox.y0 if item.bbox else 0, item.bbox.x0 if item.bbox else 0))):
            title = str(line.attributes["toc_title"]).strip()
            target = str(line.attributes["target_page_label"]).strip()
            output.append(
                Block(
                    id=f"toc-native-{page}-{index}",
                    type="toc_entry",
                    text=f"{title} …… {target}",
                    page=page,
                    bbox=deepcopy(line.bbox),
                    reading_order=index + bool(headers),
                    confidence=line.confidence,
                    attributes={
                        "toc_title": title,
                        "target_page_label": target,
                        "reading_order_repaired": True,
                        "toc_page": True,
                        "source_type": "native_pdf",
                    },
                    evidence=deepcopy(line.evidence),
                )
            )
        replacements[page] = output
    return replacements


def _split_toc_titles(block: Block) -> list[tuple[str, float]]:
    text = clean_text(block.text.replace("\n", " "))
    text = re.sub(r"[.．。·…]{2,}\s*$", "", text).strip()
    if not text:
        return []
    starts = list(re.finditer(r"(?<!\S)(?:[a-z]\)\s*)?\d+(?:\.\d+){0,6}\s+", text, re.IGNORECASE))
    if len(starts) <= 1:
        parts = [text]
    else:
        prefix = text[: starts[0].start()].strip(" .．。·…")
        parts = [prefix] if prefix else []
        parts.extend(text[item.start() : starts[index + 1].start() if index + 1 < len(starts) else len(text)].strip() for index, item in enumerate(starts))
    parts = [re.sub(r"[.．。·…]+$", "", part).strip() for part in parts if part.strip(" .．。·…")]
    if not block.bbox:
        return [(part, float(index)) for index, part in enumerate(parts)]
    height = max(1.0, (block.bbox.y1 - block.bbox.y0) / max(1, len(parts)))
    return [(part, block.bbox.y0 + (index + 0.5) * height) for index, part in enumerate(parts)]


def _deepdoc_toc_replacements(blocks: list[Block]) -> dict[int, list[Block]]:
    pages: dict[int, list[Block]] = {}
    for block in blocks:
        if block.page and block.bbox:
            pages.setdefault(block.page, []).append(block)
    replacements: dict[int, list[Block]] = {}
    for page, group in pages.items():
        headers = [block for block in group if "目录" in re.sub(r"\s+", "", block.text) and len(block.text) <= 24]
        toc_header = min(headers, key=lambda item: item.bbox.y0) if headers else None
        max_x = max((block.bbox.x1 for block in group if block.bbox), default=1.0)
        right_edge = max_x * 0.72
        label_blocks = [block for block in group if block.bbox and block.bbox.x0 >= right_edge and _page_labels(block.text)]
        direct = [block for block in group if TOC_RE.match(clean_text(block.text.replace("\n", " ")))]
        title_like = [
            block
            for block in group
            if block.bbox
            and block.bbox.x0 < right_edge
            and (HEADING_NUMBER_RE.match(block.text) or re.match(r"^(?:[a-z]\)\s*)?(?:\d+|前言|目录)\b", block.text, re.IGNORECASE))
        ]
        if not ((headers and len(title_like) + len(direct) >= 5 and len(label_blocks) + len(direct) >= 3) or (len(title_like) >= 8 and len(label_blocks) + len(direct) >= 6)):
            continue

        rows: list[tuple[float, Block]] = []
        consumed: set[str] = set()
        for source in direct:
            match = TOC_RE.match(clean_text(source.text.replace("\n", " ")))
            if not match:
                continue
            title = re.sub(r"[.．。·…]+$", "", match.group(1)).strip()
            target = match.group(2).upper()
            source.type = "toc_entry"
            source.text = f"{title} …… {target}"
            source.attributes.update({"toc_title": title, "target_page_label": target, "reading_order_repaired": True, "toc_page": True})
            rows.append((((source.bbox.y0 + source.bbox.y1) / 2), source))
            consumed.add(source.id)

        labels: list[tuple[float, str, Block]] = []
        for source in label_blocks:
            values = _page_labels(source.text)
            height = max(1.0, (source.bbox.y1 - source.bbox.y0) / len(values))
            labels.extend((source.bbox.y0 + (index + 0.5) * height, value, source) for index, value in enumerate(values))

        used_labels: set[int] = set()
        title_fragments: list[tuple[float, str, Block]] = []
        for source in title_like:
            if source.id in consumed or source is toc_header:
                continue
            title_fragments.extend((center, title, source) for title, center in _split_toc_titles(source))
        for center, title, source in sorted(title_fragments):
            possible = [(abs(center - label_center), index, label_center, target, label_source) for index, (label_center, target, label_source) in enumerate(labels) if index not in used_labels]
            if not possible:
                continue
            distance, label_index, _label_center, target, label_source = min(possible)
            source_height = max(1.0, source.bbox.y1 - source.bbox.y0)
            label_height = max(1.0, label_source.bbox.y1 - label_source.bbox.y0) / max(1, len(_page_labels(label_source.text)))
            if distance > max(8.0, source_height, label_height) * 0.9:
                continue
            used_labels.add(label_index)
            block = Block(
                id=f"toc-deepdoc-{page}-{len(rows)}",
                type="toc_entry",
                text=f"{title} …… {target}",
                page=page,
                bbox=type(source.bbox)(source.bbox.x0, center - source_height / 2, label_source.bbox.x1, center + source_height / 2),
                confidence=min(source.confidence, label_source.confidence),
                attributes={"toc_title": title, "target_page_label": target, "reading_order_repaired": True, "toc_page": True},
                evidence=[*source.evidence, *label_source.evidence],
            )
            rows.append((center, block))

        if len(rows) < 5:
            continue
        output: list[Block] = []
        if toc_header:
            header = toc_header
            header.type = "heading"
            header.level = 1
            header.attributes["toc_page"] = True
            output.append(header)
        output.extend(block for _center, block in sorted(rows, key=lambda item: item[0]))
        replacements[page] = output
    return replacements


def _apply_toc_reconstruction(blocks: list[Block], native_lines: list[Block] | None) -> list[Block]:
    deepdoc = _deepdoc_toc_replacements(blocks)
    native = _native_toc_replacements(native_lines)
    replacements: dict[int, list[Block]] = {}
    for page in set(deepdoc) | set(native):
        candidates = [*(native.get(page) or []), *(deepdoc.get(page) or [])]
        header = next((block for block in candidates if block.attributes.get("toc_page") and block.type == "heading"), None)
        unique: dict[tuple[str, str], Block] = {}
        for block in candidates:
            if block.type != "toc_entry":
                continue
            key = (
                re.sub(r"\s+", "", str(block.attributes.get("toc_title") or block.text.split("……", 1)[0])).lower(),
                str(block.attributes.get("target_page_label", "")).upper(),
            )
            previous = unique.get(key)
            if previous is None or block.attributes.get("source_type") == "native_pdf":
                unique[key] = block
        output = ([header] if header else []) + sorted(
            unique.values(), key=lambda item: (item.bbox.y0 if item.bbox else float("inf"), item.bbox.x0 if item.bbox else 0)
        )
        if len(unique) >= 5:
            replacements[page] = output
    if not replacements:
        return blocks
    by_page: dict[int, list[Block]] = {}
    for block in blocks:
        if block.page:
            by_page.setdefault(block.page, []).append(block)
    reconstructed_pages: dict[int, list[Block]] = {}
    for page in sorted(replacements):
        if page not in by_page:
            reconstructed_pages[page] = replacements[page]
            continue
        replacement = replacements[page]
        replacement_text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", " ".join(block.text for block in replacement)).lower()
        preserved: list[Block] = []
        for original in by_page[page]:
            compact = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", original.text).lower()
            if not compact:
                if original.type in {"figure", "table", "equation"}:
                    preserved.append(original)
                continue
            locally_covered = False
            if original.bbox:
                nearby = [
                    candidate
                    for candidate in replacement
                    if candidate.bbox
                    and min(original.bbox.y1, candidate.bbox.y1) - max(original.bbox.y0, candidate.bbox.y0) > 0
                ]
                local_text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", " ".join(item.text for item in nearby)).lower()
                locally_covered = bool(local_text) and SequenceMatcher(None, compact, local_text).ratio() >= 0.78
            if compact in replacement_text or locally_covered:
                continue
            if original.type in {"figure", "table", "equation"}:
                preserved.append(original)
                continue
            # Native TOC rows are authoritative for a dense TOC page.  Drop
            # old DeepDOC leader/page-number fragments and fused rows when
            # their vertical band is already represented by reconstructed
            # entries.  Keeping them created contradictory duplicate entries.
            page_label_noise = bool(re.fullmatch(r"[\s.．。·…IVXLCDM\d]+", original.text, re.IGNORECASE))
            nearby_entries = [
                candidate
                for candidate in replacement
                if candidate.type == "toc_entry"
                and candidate.bbox
                and original.bbox
                and min(original.bbox.y1, candidate.bbox.y1) - max(original.bbox.y0, candidate.bbox.y0) > 0
            ]
            nearby_text = re.sub(
                r"[^0-9A-Za-z\u4e00-\u9fff]",
                "",
                " ".join(item.text for item in nearby_entries),
            ).lower()
            fragment_score = SequenceMatcher(None, compact, nearby_text).ratio() if nearby_text else 0.0
            if page_label_noise or (nearby_entries and (fragment_score >= 0.42 or len(compact) <= 20)):
                continue
            # Never delete an unresolved source region merely because another
            # channel reconstructed part of the page.  This is the guard that
            # prevents dense TOC pages from losing an entire vertical band.
            original.attributes["toc_fragment_unresolved"] = True
            original.attributes["toc_page"] = True
            preserved.append(original)
        combined = [*replacement, *preserved]
        combined.sort(key=lambda item: (item.bbox.y0 if item.bbox else float("inf"), item.bbox.x0 if item.bbox else 0, item.reading_order))
        reconstructed_pages[page] = combined
    # Keep unplaced OOXML blocks at their source position.  Moving every
    # unplaced block to the beginning before page reconstruction caused the
    # entire DOCX stream to be inferred as physical page 1.
    output: list[Block] = []
    emitted_pages: set[int] = set()
    for block in blocks:
        page = block.page
        if page in reconstructed_pages:
            if page not in emitted_pages:
                output.extend(reconstructed_pages[page])
                emitted_pages.add(page)
            continue
        output.append(block)
    for page in sorted(set(reconstructed_pages) - emitted_pages):
        output.extend(reconstructed_pages[page])
    for order, block in enumerate(output):
        block.reading_order = order
    return output


def _bbox_intersection_ratio(left: Block, right: Block) -> float:
    if not left.bbox or not right.bbox or left.page != right.page:
        return 0.0
    x0, y0 = max(left.bbox.x0, right.bbox.x0), max(left.bbox.y0, right.bbox.y0)
    x1, y1 = min(left.bbox.x1, right.bbox.x1), min(left.bbox.y1, right.bbox.y1)
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    left_area = max(1.0, (left.bbox.x1 - left.bbox.x0) * (left.bbox.y1 - left.bbox.y0))
    return intersection / left_area


def recover_missing_native_lines(
    blocks: list[Block], native_lines: list[Block] | None, pages: list[Page] | None
) -> tuple[list[Block], list[ParseIssue]]:
    """Add only native PDF lines demonstrably absent from DeepDOC output."""

    if not native_lines or not pages:
        return blocks, []
    toc_pages = {
        line.page
        for line in native_lines
        if line.page and line.attributes.get("native_toc_row")
    }
    toc_density = Counter(line.page for line in native_lines if line.attributes.get("native_toc_row"))
    eligible_pages = {
        page.number
        for page in pages
        if float(page.attributes.get("native_text_coverage", {}).get("text_shingle_recall", 1.0)) < 0.985
        or float(page.attributes.get("native_text_coverage", {}).get("number_recall", 1.0)) < 0.995
    }
    by_page: dict[int, list[Block]] = {}
    for block in blocks:
        if block.page:
            by_page.setdefault(block.page, []).append(block)
    recovered: list[Block] = []
    for line in native_lines:
        if not line.page or line.page not in eligible_pages or (line.page in toc_pages and toc_density[line.page] >= 5):
            continue
        compact = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", line.text).lower()
        if len(compact) < 2:
            continue
        matched = False
        for existing in by_page.get(line.page, []):
            existing_compact = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", _visible_text(existing)).lower()
            overlap = _bbox_intersection_ratio(line, existing)
            score = SequenceMatcher(None, compact, existing_compact).ratio() if existing_compact else 0.0
            native_marker = LIST_PREFIX_RE.match(line.text)
            existing_marker = LIST_PREFIX_RE.match(existing.text)
            native_is_better = bool(
                overlap >= 0.35
                and (
                    (native_marker and not existing_marker and score >= 0.72)
                    or (existing_compact in compact and len(compact) > len(existing_compact) and score >= 0.72)
                )
            )
            if native_is_better and existing.type not in {"table", "figure", "equation"}:
                existing.attributes.update(
                    {
                        "fusion_action": "replace",
                        "native_source_id": line.id,
                        "replaced_text": existing.text,
                    }
                )
                existing.text = line.text
                existing.evidence.extend(deepcopy(line.evidence))
                existing.confidence = max(existing.confidence, line.confidence)
                matched = True
                break
            if compact in existing_compact or existing_compact in compact and len(existing_compact) >= max(4, len(compact) * 0.75):
                matched = True
                break
            if overlap >= 0.7 and (score >= 0.68 or existing.type in {"table", "figure", "equation"}):
                matched = True
                break
        if matched:
            continue
        candidate = deepcopy(line)
        candidate.id = f"native-gap-{line.id}"
        candidate.type = "paragraph"
        candidate.attributes.update({"source_type": "pdf_native", "native_gap_recovery": True})
        candidate.reading_order = max((block.reading_order for block in blocks), default=0) + len(recovered) + 1
        recovered.append(candidate)
        by_page.setdefault(candidate.page, []).append(candidate)
    if not recovered:
        return blocks, []
    issues = [
        ParseIssue("native_text_recovered", f"已从 PDF 原生文字层补回 {count} 个 DeepDOC 遗漏行", "info", page=page)
        for page, count in sorted(Counter(block.page for block in recovered).items())
    ]
    return [*blocks, *recovered], issues


def deduplicate_fused_blocks(blocks: list[Block]) -> list[Block]:
    """Remove spatial duplicates after native/DeepDOC fusion.

    Native text is used to improve an existing visual block.  It must not be
    appended as a second cover title or paragraph at nearly the same position.
    """

    output: list[Block] = []
    figures = [block for block in blocks if block.type == "figure"]
    for candidate in blocks:
        if candidate.type not in {"heading", "paragraph", "list_item"} or not candidate.bbox:
            output.append(candidate)
            continue
        compact = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", candidate.text).lower()
        duplicate_index: int | None = None
        for index in range(len(output) - 1, -1, -1):
            existing = output[index]
            if existing.page != candidate.page:
                break
            if existing.type not in {"heading", "paragraph", "list_item"} or not existing.bbox:
                continue
            existing_compact = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", existing.text).lower()
            if not compact or not existing_compact:
                continue
            overlap = max(_bbox_intersection_ratio(candidate, existing), _bbox_intersection_ratio(existing, candidate))
            score = SequenceMatcher(None, compact, existing_compact).ratio()
            if overlap >= 0.35 and score >= 0.78:
                duplicate_index = index
                break
        if duplicate_index is None:
            output.append(candidate)
            continue
        existing = output[duplicate_index]
        candidate_rank = (
            bool(candidate.attributes.get("fusion_action") == "replace"),
            candidate.type == "heading",
            len(compact),
            candidate.confidence,
        )
        existing_rank = (
            bool(existing.attributes.get("fusion_action") == "replace"),
            existing.type == "heading",
            len(re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", existing.text)),
            existing.confidence,
        )
        kept, removed = (candidate, existing) if candidate_rank > existing_rank else (existing, candidate)
        if sum(part.get("type") == "image" for part in removed.parts) > sum(
            part.get("type") == "image" for part in kept.parts
        ):
            kept.parts = deepcopy(removed.parts)
        for figure in figures:
            if figure.attributes.get("source_paragraph_id") != removed.id:
                continue
            figure.attributes.update({"source_paragraph_id": kept.id, "source_parent_id": kept.id})
            if figure.parent_id == removed.id:
                figure.parent_id = kept.id
        kept.attributes.setdefault("deduplicated_block_ids", []).append(removed.id)
        kept.evidence.extend(item for item in removed.evidence if item not in kept.evidence)
        output[duplicate_index] = kept
    return output


def repair_toc_reading_order(blocks: list[Block]) -> list[Block]:
    """Pair TOC titles with right-column page labels before normal reading order."""
    replacements: dict[str, list[Block]] = {}
    removed: set[str] = set()
    page_groups: dict[int, list[Block]] = {}
    for block in blocks:
        if block.page and block.bbox:
            page_groups.setdefault(block.page, []).append(block)
    for page, group in page_groups.items():
        number_blocks = [block for block in group if _page_labels(block.text)]
        if not number_blocks:
            continue
        # DeepDOC sometimes creates one left-column block and one page-number
        # block. Split them into logical entries while retaining page evidence.
        for numbers in number_blocks:
            labels = _page_labels(numbers.text)
            if len(labels) < 2:
                continue
            candidates = [
                block
                for block in group
                if block.id != numbers.id
                and block.bbox
                and block.bbox.x0 < numbers.bbox.x0
                and len([line for line in block.text.splitlines() if line.strip()]) == len(labels)
            ]
            if not candidates:
                continue
            titles = min(candidates, key=lambda item: abs(((item.bbox.y0 + item.bbox.y1) / 2) - ((numbers.bbox.y0 + numbers.bbox.y1) / 2)))
            title_lines = [line.strip() for line in titles.text.splitlines() if line.strip()]
            entries = []
            height = max(1.0, (titles.bbox.y1 - titles.bbox.y0) / len(title_lines))
            for index, (title, target) in enumerate(zip(title_lines, labels, strict=True)):
                entries.append(
                    Block(
                        id=f"toc-{page}-{titles.id}-{index}",
                        type="toc_entry",
                        text=f"{title} …… {target}",
                        page=page,
                        bbox=type(titles.bbox)(titles.bbox.x0, titles.bbox.y0 + index * height, numbers.bbox.x1, titles.bbox.y0 + (index + 1) * height),
                        reading_order=min(titles.reading_order, numbers.reading_order) + index,
                        confidence=min(titles.confidence, numbers.confidence),
                        attributes={"toc_title": title, "target_page_label": target, "reading_order_repaired": True},
                        evidence=[*titles.evidence, *numbers.evidence],
                    )
                )
            replacements[titles.id] = entries
            removed.add(numbers.id)

        # The other common shape is one block per row. Pair by baseline and
        # require at least three pairs to avoid treating ordinary numbers as TOC.
        single_numbers = [block for block in number_blocks if len(_page_labels(block.text)) == 1 and block.id not in removed]
        pairs: list[tuple[Block, Block]] = []
        used_titles: set[str] = set()
        for number in single_numbers:
            possible = [
                block
                for block in group
                if block.id not in removed
                and block.id not in used_titles
                and block.id != number.id
                and block.bbox
                and block.bbox.x0 < number.bbox.x0
                and not PAGE_LABEL_RE.fullmatch(block.text.strip())
            ]
            if not possible:
                continue
            title = min(possible, key=lambda item: abs(((item.bbox.y0 + item.bbox.y1) / 2) - ((number.bbox.y0 + number.bbox.y1) / 2)))
            distance = abs(((title.bbox.y0 + title.bbox.y1) / 2) - ((number.bbox.y0 + number.bbox.y1) / 2))
            if distance <= max(title.bbox.y1 - title.bbox.y0, number.bbox.y1 - number.bbox.y0) * 1.2:
                pairs.append((title, number))
                used_titles.add(title.id)
        if len(pairs) >= 3:
            for title, number in pairs:
                target_match = PAGE_LABEL_RE.fullmatch(number.text.strip())
                target = target_match.group(1).upper() if target_match else number.text.strip()
                title.type = "toc_entry"
                title.text = f"{title.text.strip()} …… {target}"
                title.attributes.update({"toc_title": title.text.rsplit(" …… ", 1)[0], "target_page_label": target, "reading_order_repaired": True})
                title.bbox.x1 = max(title.bbox.x1, number.bbox.x1)
                title.evidence.extend(number.evidence)
                removed.add(number.id)
    output: list[Block] = []
    for block in blocks:
        if block.id in replacements:
            output.extend(replacements[block.id])
        elif block.id not in removed:
            output.append(block)
    for order, block in enumerate(output):
        block.reading_order = order
    return output


INLINE_HEADING_RE = re.compile(
    r"^((?:[一二三四五六七八九十百]+、)?\s*.{2,28}?(?:安全预防措施|注意事项|操作说明|拆装说明|工作步骤|维修步骤|检查方法|故障诊断|使用本手册|起吊说明|标准紧固扭矩表))"
    r"(?=(?:错误|正确|当|如果|在|为|本|操作|使用|进行|紧固|螺栓))(.+)$",
    re.DOTALL,
)

SECOND_HEADING_RE = re.compile(r"^(?:紧固扭矩表|螺栓和螺母|起吊|钢丝绳)(?:[-—－].*)?$")


def split_inline_headings(blocks: list[Block]) -> list[Block]:
    output: list[Block] = []
    for block in blocks:
        match = (
            INLINE_HEADING_RE.match(block.text)
            if block.type in {"paragraph", "heading"} and not block.attributes.get("toc_page")
            else None
        )
        if not match:
            output.append(block)
            continue
        heading = deepcopy(block)
        body = deepcopy(block)
        heading.id = f"{block.id}-inline-heading"
        heading.type = "heading"
        heading.text = match.group(1).strip()
        heading.level = 2 if re.match(r"^[一二三四五六七八九十百]+、", heading.text) else 3
        heading.attributes.update({"inline_heading_recovered": True, "split_from_block": block.id})
        body.id = f"{block.id}-inline-body"
        body.text = match.group(2).strip()
        body.type = "heading" if SECOND_HEADING_RE.match(body.text) else "paragraph"
        body.level = 3 if body.type == "heading" else None
        body.attributes["split_from_block"] = block.id
        if block.bbox:
            split_y = min(block.bbox.y1, block.bbox.y0 + max(10.0, (block.bbox.y1 - block.bbox.y0) / 3))
            heading.bbox.y1 = split_y
            body.bbox.y0 = split_y
        output.extend([heading, body])
    return output


def extract_caption_overflow(blocks: list[Block]) -> list[Block]:
    """Keep long prose out of table captions without discarding its text."""

    output: list[Block] = []
    for block in blocks:
        if block.type != "table" or not block.html:
            output.append(block)
            continue
        match = re.search(r"<caption[^>]*>(.*?)</caption>", block.html, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            output.append(block)
            continue
        caption = clean_text(re.sub(r"<[^>]+>", "", html.unescape(match.group(1))))
        caption_markers = len(re.findall(r"(?:^|[。；])\s*\d+[)）]", caption))
        is_real_caption = bool(CAPTION_RE.match(caption)) and len(caption) <= 80 and caption_markers <= 1
        if is_real_caption:
            output.append(block)
            continue
        block.html = block.html[: match.start()] + block.html[match.end() :]
        block.attributes.update({"caption_overflow_extracted": True, "raw_caption_text": caption})
        fragments = [item.strip() for item in re.split(r"(?=\d+[)）])|(?=注[：:])", caption) if item.strip()]
        before: list[Block] = []
        after: list[Block] = []
        for index, value in enumerate(fragments or [caption]):
            prose = deepcopy(block)
            prose.id = f"{block.id}-caption-overflow-{index}"
            prose.type = (
                "heading"
                if len(value) <= 40 and re.match(r"^[一二三四五六七八九十]+、", value) and not re.search(r"[。！？；]", value)
                else "paragraph"
            )
            prose.level = 1 if prose.type == "heading" else None
            prose.text = value
            prose.html = ""
            prose.region_image = ""
            prose.attributes = {
                "source_type": "table_caption_overflow",
                "split_from_block": block.id,
                "caption_overflow": True,
            }
            (before if index == 0 and re.match(r"^\d+[)）]", value) else after).append(prose)
        output.extend([*before, block, *after])
    return output


def _vertical_gap(left: Block, right: Block) -> float | None:
    if not left.bbox or not right.bbox or left.page != right.page:
        return None
    return right.bbox.y0 - left.bbox.y1


def _should_merge_lines(left: Block, right: Block) -> bool:
    if left.type != "paragraph" or right.type != "paragraph":
        return False
    if left.page != right.page or not left.text or not right.text:
        return False
    if SENTENCE_END_RE.search(left.text) or HEADING_NUMBER_RE.match(right.text):
        return False
    gap = _vertical_gap(left, right)
    if gap is not None:
        line_height = max(1.0, left.bbox.y1 - left.bbox.y0)  # type: ignore[union-attr]
        if gap < -line_height * 0.25 or gap > line_height * 1.35:
            return False
        if abs(left.bbox.x0 - right.bbox.x0) > line_height * 2.2:  # type: ignore[union-attr]
            return False
    if re.search(r"[，、（(\-/]$", left.text):
        return True
    if re.search(r"[\u4e00-\u9fff]$", left.text) and re.match(r"[\u4e00-\u9fff]", right.text):
        return True
    return bool(re.search(r"[A-Za-z0-9-]$", left.text) and re.match(r"[A-Za-z0-9]", right.text))


def merge_broken_lines(blocks: list[Block]) -> list[Block]:
    if not blocks:
        return []
    merged: list[Block] = []
    for source in blocks:
        current = deepcopy(source)
        if merged and _should_merge_lines(merged[-1], current):
            previous = merged[-1]
            joiner = " " if re.search(r"[A-Za-z0-9]$", previous.text) and re.match(r"[A-Za-z0-9]", current.text) else ""
            if previous.parts or current.parts:
                if not previous.parts:
                    previous.parts = [{"type": "text", "text": previous.text}]
                incoming = deepcopy(current.parts) if current.parts else [{"type": "text", "text": current.text}]
                if joiner:
                    if previous.parts[-1].get("type") == "text":
                        previous.parts[-1]["text"] = str(previous.parts[-1].get("text", "")) + joiner
                    else:
                        previous.parts.append({"type": "text", "text": joiner})
                if incoming and previous.parts[-1].get("type") == incoming[0].get("type") == "text":
                    previous.parts[-1]["text"] = str(previous.parts[-1].get("text", "")) + str(incoming[0].get("text", ""))
                    incoming = incoming[1:]
                previous.parts.extend(incoming)
            previous.text += joiner + current.text
            previous.evidence.extend(current.evidence)
            previous.attributes.setdefault("merged_block_ids", []).append(current.id)
            previous.confidence = min(previous.confidence, current.confidence)
            if previous.bbox and current.bbox:
                previous.bbox.x0 = min(previous.bbox.x0, current.bbox.x0)
                previous.bbox.y0 = min(previous.bbox.y0, current.bbox.y0)
                previous.bbox.x1 = max(previous.bbox.x1, current.bbox.x1)
                previous.bbox.y1 = max(previous.bbox.y1, current.bbox.y1)
            continue
        merged.append(current)
    for order, block in enumerate(merged):
        block.reading_order = order
    return merged


def infer_heading_level(block: Block) -> int:
    text = block.text.strip()
    if re.match(r"^第[一二三四五六七八九十百]+章", text):
        return 1
    if re.match(r"^[一二三四五六七八九十百]+、", text):
        return 2
    match = re.match(r"^(\d+(?:\.\d+)*)", text)
    if match:
        return min(6, match.group(1).count(".") + 1)
    if block.level:
        return max(1, min(6, block.level))
    return 2


def build_heading_tree(blocks: list[Block]) -> list[dict]:
    roots: list[dict] = []
    toc_root = next((block for block in blocks if block.attributes.get("toc_root")), None)
    if toc_root:
        toc_root.parent_id = None
        toc_root.attributes["section_path"] = ["目录"]
        toc_node = {
            "id": toc_root.id,
            "title": "目录",
            "level": 1,
            "page": toc_root.page,
            "path": ["目录"],
            "kind": "toc_root",
            "children": [],
            "block_ids": [],
        }
        roots.append(toc_node)
        toc_nodes: dict[str, dict] = {}
        for block in (item for item in blocks if item.type == "toc_entry"):
            title = str(block.attributes.get("toc_title") or block.text.split("……", 1)[0]).strip()
            node = {
                "id": block.id,
                "title": title,
                "level": int(block.attributes.get("toc_level", block.level or 1)),
                "page": block.page,
                "path": block.attributes.get("section_path", ["目录", title]),
                "kind": "toc_entry",
                "printed_page_label": block.attributes.get("printed_page_label", ""),
                "target_pdf_page": block.attributes.get("target_pdf_page"),
                "target_heading_id": block.attributes.get("target_heading_id"),
                "resolution_status": block.attributes.get("resolution_status", "unresolved"),
                "children": [],
                "block_ids": [],
            }
            toc_nodes[block.id] = node
        for block in (item for item in blocks if item.type == "toc_entry"):
            node = toc_nodes[block.id]
            parent = toc_nodes.get(block.parent_id or "")
            if parent:
                parent["children"].append(node)
            else:
                block.parent_id = toc_root.id
                toc_node["children"].append(node)

    stack: list[dict] = []
    for block in blocks:
        if block.attributes.get("toc_root") or block.type == "toc_entry":
            continue
        if block.type != "heading":
            if block.attributes.get("toc_page") or block.attributes.get("search_role") == "navigation":
                if toc_root:
                    block.parent_id = toc_root.id
                    block.attributes["section_path"] = ["目录"]
                    toc_node["block_ids"].append(block.id)
                continue
            if stack:
                block.parent_id = stack[-1]["id"]
                stack[-1]["block_ids"].append(block.id)
                block.attributes["section_path"] = [item["title"] for item in stack]
            continue
        block.level = infer_heading_level(block)
        if (
            stack
            and stack[-1]["level"] == 2
            and block.level <= 2
            and not re.match(r"^(?:第[一二三四五六七八九十百]+章|\d+(?:\.\d+)*|[一二三四五六七八九十百]+、)", block.text)
        ):
            block.level = 3
        while stack and stack[-1]["level"] >= block.level:
            stack.pop()
        block.attributes["section_path"] = [item["title"] for item in stack] + [block.text]
        node = {
            "id": block.id,
            "title": block.text,
            "level": block.level,
            "page": block.page,
            "path": block.attributes["section_path"],
            "children": [],
            "block_ids": [],
        }
        if stack:
            block.parent_id = stack[-1]["id"]
            stack[-1]["children"].append(node)
        else:
            roots.append(node)
        stack.append(node)
    return roots


def ensure_toc_root(blocks: list[Block]) -> list[Block]:
    """Create one navigation root and suppress per-page TOC headings."""

    toc_entries = [block for block in blocks if block.type == "toc_entry" or block.attributes.get("toc_page")]
    toc_pages = sorted({block.page for block in toc_entries if block.page})
    if not toc_pages:
        return blocks
    first_page = toc_pages[0]
    headings = [
        block
        for block in blocks
        if block.page in toc_pages
        and block.type == "heading"
        and "目录" in re.sub(r"\s+", "", block.text)
        and len(block.text) <= 24
    ]
    root = min(headings, key=lambda block: (block.page or first_page, block.bbox.y0 if block.bbox else 0)) if headings else None
    if root is None:
        first_entry = min(
            (block for block in blocks if block.page == first_page and block.type == "toc_entry"),
            key=lambda block: block.bbox.y0 if block.bbox else 0,
        )
        root = Block(
            id="toc-root",
            type="heading",
            text="目录",
            page=first_page,
            bbox=None,
            level=1,
            reading_order=max(0, first_entry.reading_order - 1),
            attributes={"source_type": "synthetic", "toc_page": True},
        )
        blocks.append(root)
    root.text = "目录"
    root.level = 1
    root.attributes.update({"toc_root": True, "toc_page": True, "search_role": "navigation", "qa_eligible": False})
    for heading in headings:
        if heading.id == root.id:
            continue
        heading.type = "page_header"
        heading.attributes.update({"toc_page": True, "repeated_furniture": True, "toc_continuation_header": True})
    return canonical_reading_order(blocks)


def recover_printed_page_labels(pages: list[Page] | None, native_lines: list[Block] | None) -> None:
    if not pages or not native_lines:
        return
    page_map = {page.number: page for page in pages}
    for line in native_lines:
        page = page_map.get(line.page or -1)
        if not page or not line.bbox or line.bbox.y1 < page.height * 0.86:
            continue
        match = PAGE_LABEL_RE.fullmatch(clean_text(line.text))
        if not match:
            continue
        label = match.group(1)
        page.printed_page_label = label.upper() if label.isalpha() else label


def split_compound_captions(blocks: list[Block]) -> list[Block]:
    output: list[Block] = []
    marker = re.compile(r"(?=(?:图|表)\s*[A-Za-z0-9一二三四五六七八九十]+(?:[.．-][A-Za-z0-9一二三四五六七八九十]+)*)")
    for block in blocks:
        if block.type != "caption":
            output.append(block)
            continue
        starts = [match.start() for match in marker.finditer(block.text)]
        if len(starts) < 2:
            output.append(block)
            continue
        starts.append(len(block.text))
        for index, start in enumerate(starts[:-1]):
            child = deepcopy(block)
            child.id = f"{block.id}-caption-{index}"
            child.text = block.text[start : starts[index + 1]].strip(" .；;")
            child.attributes.update({"split_from_block": block.id, "compound_caption_split": True})
            if child.bbox:
                height = (block.bbox.y1 - block.bbox.y0) / (len(starts) - 1)
                child.bbox.y0 = block.bbox.y0 + index * height
                child.bbox.y1 = block.bbox.y0 + (index + 1) * height
            output.append(child)
    return output


def link_figures_and_captions(blocks: list[Block]) -> None:
    for block in blocks:
        if block.type != "caption":
            continue
        figures = [item for item in blocks if item.type in {"figure", "table"} and item.page == block.page and item.id != block.id]
        if not figures:
            continue
        if block.bbox:
            located = [item for item in figures if item.bbox]
            ranked = []
            for item in located:
                vertical = min(abs(block.bbox.y0 - item.bbox.y1), abs(item.bbox.y0 - block.bbox.y1))
                horizontal_overlap = max(0.0, min(block.bbox.x1, item.bbox.x1) - max(block.bbox.x0, item.bbox.x0))
                min_width = max(1.0, min(block.bbox.x1 - block.bbox.x0, item.bbox.x1 - item.bbox.x0))
                ranked.append((vertical + (0 if horizontal_overlap / min_width >= 0.25 else 80), item))
            if not ranked:
                continue
            distance, target = min(ranked, key=lambda pair: pair[0])
            if distance > 120:
                block.attributes["caption_unlinked_reason"] = "no_nearby_visual_region"
                continue
        else:
            target = min(figures, key=lambda item: abs(item.reading_order - block.reading_order))
        block.parent_id = target.id
        block.attributes.update({"source_parent_id": target.id, "caption_target_id": target.id})
        if block.id not in target.children:
            target.children.append(block.id)
        target.attributes.setdefault("caption_block_ids", []).append(block.id)
        existing = str(target.attributes.get("caption", "")).strip()
        if not existing or SequenceMatcher(None, existing, block.text).ratio() >= 0.6:
            target.attributes["caption"] = block.text
        else:
            block.attributes["caption_unlinked_reason"] = "target_already_has_different_caption"


def classify_table_intent(block: Block) -> str:
    text = re.sub(r"<[^>]+>", " ", block.html or block.text)
    text = clean_text(html.unescape(text))
    warning_hits = len(re.findall(r"危险|警告|注意|提示|小心", text))
    rows = len(re.findall(r"<tr\b", block.html, re.IGNORECASE))
    cells = len(re.findall(r"<t[dh]\b", block.html, re.IGNORECASE))
    numeric = len(re.findall(r"\d", text))
    empty_cells = len(re.findall(r"<t[dh][^>]*>\s*</t[dh]>", block.html, re.IGNORECASE))
    columns, _ = _table_signature(block) or (0, ())
    if warning_hits and rows <= 4:
        return "warning_container"
    if cells <= 1 and block.attributes.get("contains_image"):
        return "image_container"
    if rows <= 2 and cells <= 4 and len(text) > 80:
        return "layout_container"
    if columns == 2 and rows >= 2 and (empty_cells or numeric < 4):
        return "key_value_table"
    if numeric >= 4 or columns >= 3:
        return "data_table"
    return "layout_table"


def normalize_table_structure(blocks: list[Block]) -> list[ParseIssue]:
    issues: list[ParseIssue] = []
    for block in blocks:
        if block.type != "table" or not block.html:
            continue
        # DeepDOC sometimes serializes harmless whitespace inside tag starts.
        block.html = re.sub(r"<(table|thead|tbody|tfoot|tr|th|td|caption)\s+>", r"<\1>", block.html, flags=re.IGNORECASE)
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", block.html, flags=re.IGNORECASE | re.DOTALL)
        row_widths: list[int] = []
        merged = False
        empty = 0
        cells = 0
        for row in rows:
            row_cells = re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", row, flags=re.IGNORECASE | re.DOTALL)
            width = 0
            for attributes, value in row_cells:
                colspan = re.search(r"\bcolspan\s*=\s*['\"]?(\d+)", attributes, re.IGNORECASE)
                rowspan = re.search(r"\browspan\s*=\s*['\"]?(\d+)", attributes, re.IGNORECASE)
                width += int(colspan.group(1)) if colspan else 1
                merged = merged or bool(colspan or rowspan)
                cells += 1
                empty += not clean_text(re.sub(r"<[^>]+>", "", html.unescape(value)))
            if row_cells:
                row_widths.append(width)
        columns = max(row_widths, default=0)
        ragged = bool(row_widths and any(width != columns for width in row_widths))
        block.attributes.update(
            {
                "table_rows": len(rows),
                "table_columns": columns,
                "has_merged_cells": merged,
                "empty_cell_ratio": round(empty / cells, 3) if cells else 1.0,
                "ragged_rows": ragged,
            }
        )
        caption = re.search(r"<caption[^>]*>(.*?)</caption>", block.html, flags=re.IGNORECASE | re.DOTALL)
        if caption:
            block.attributes["caption"] = clean_text(re.sub(r"<[^>]+>", "", html.unescape(caption.group(1))))
        grid = parse_table_grid(block.html)
        numeric_repairs = repair_numeric_alignment(grid)
        if numeric_repairs:
            block.html = table_grid_to_html(grid)
            block.text = "\n".join(
                "\t".join(
                    str(cell.get("text", "")) if cell and "ref" not in cell else ""
                    for cell in row
                )
                for row in grid.get("grid", [])
            )
            block.attributes["automatic_grid_repairs"] = numeric_repairs
            repaired_cells = list(grid.get("cells", []))
            block.attributes["empty_cell_ratio"] = (
                round(sum(not str(cell.get("text", "")).strip() for cell in repaired_cells) / len(repaired_cells), 3)
                if repaired_cells
                else 1.0
            )
        block.attributes["table_grid"] = grid
        if grid.get("caption") and not block.attributes.get("caption"):
            block.attributes["caption"] = grid["caption"]
        source_channels = {item.channel for item in block.evidence}
        source_type = (
            "ooxml"
            if "ooxml" in source_channels
            else "pdf_native_table"
            if "pdf_native_table" in source_channels
            else str(block.attributes.get("source_type", "visual"))
        )
        intent = classify_table_intent(block)
        if intent == "warning_container":
            warning_text = clean_text(" ".join(str(cell.get("text", "")) for cell in grid.get("cells", [])))
            warning = WARNING_RE.search(warning_text)
            level = warning.group(1) if warning else "警告"
            body = WARNING_RE.sub("", warning_text, count=1).strip(" ！!：:")
            block.type = "safety_notice"
            block.text = f"{level}！{body}" if body else f"{level}！"
            block.attributes.update(
                {
                    "table_intent": intent,
                    "warning_level": level,
                    "label": level,
                    "body": body,
                    "safety_layout_source": "table_container",
                }
            )
            continue
        status, reasons = assess_table_integrity(grid, source_type, intent)
        block.attributes.update(
            {
                "table_intent": intent,
                "integrity_status": status,
                "integrity_reasons": reasons,
                "qa_eligible": status == "verified",
                "table_structure_source": source_type,
            }
        )
        if status == "unsafe":
            issues.append(ParseIssue("unsafe_table", "表格数值对应关系可能已经错位，禁止作为可信参数表直接使用：" + "；".join(reasons), "error", block.id, block.page))
        elif status == "review_required":
            issues.append(ParseIssue("table_review_required", "表格结构需要复核：" + "；".join(reasons), "warning", block.id, block.page))
        if ragged:
            issues.append(ParseIssue("ragged_table", "表格各行列数不一致，已保留原始单元格并标记复核", "warning", block.id, block.page))
        if cells and empty / cells >= 0.45:
            issues.append(ParseIssue("sparse_table", "表格空单元格较多，可能是版式容器或存在合并单元格", "info", block.id, block.page))
    return issues


def mark_table_continuations(blocks: list[Block]) -> list[ParseIssue]:
    issues: list[ParseIssue] = []
    tables = [block for block in blocks if block.type == "table"]
    for block in tables:
        block.attributes["table_intent"] = classify_table_intent(block)
        if block.attributes.get("spans_pages"):
            pages = sorted({item.get("page") for item in block.attributes.get("position_slices", []) if item.get("page")})
            if pages:
                issues.append(ParseIssue("table_spans_pages", f"DeepDOC 已将第 {pages[0]}-{pages[-1]} 页识别为一个跨页表", "info", block.id, pages[0]))
    for previous, current in pairwise(tables):
        if not previous.page or not current.page or current.page != previous.page + 1:
            continue
        previous_signature = _table_signature(previous)
        current_signature = _table_signature(current)
        same_columns = previous_signature and current_signature and previous_signature[0] == current_signature[0]
        repeated_header = bool(set(previous_signature[1]) & set(current_signature[1])) if same_columns else False
        boundary_near = bool(previous.attributes.get("near_page_bottom") and current.attributes.get("near_page_top"))
        caption_says_continue = bool(re.search(r"续(?:表|上表)|continued", current.text + current.html, re.IGNORECASE))
        if same_columns and (repeated_header or boundary_near or caption_says_continue):
            current.continuation_of = previous.continuation_of or previous.id
            current.attributes["cross_page_confidence"] = 0.9 if repeated_header else 0.72
            issues.append(ParseIssue("table_continuation", f"检测到跨页连续表：第 {previous.page}-{current.page} 页", "info", current.id, current.page))
    return issues


def _table_signature(block: Block) -> tuple[int, tuple[str, ...]] | tuple[()]:
    html_text = block.html or block.text
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not rows:
        return ()
    first_cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rows[0], flags=re.IGNORECASE | re.DOTALL)
    labels = tuple(clean_text(re.sub(r"<[^>]+>", "", html.unescape(cell))).lower()[:32] for cell in first_cells if clean_text(re.sub(r"<[^>]+>", "", cell)))
    return len(first_cells), labels


def validate_blocks(blocks: list[Block]) -> list[ParseIssue]:
    issues: list[ParseIssue] = []
    seen = Counter(block.text for block in blocks if block.text and len(block.text) > 8)
    for text, count in seen.items():
        if count >= 4:
            issues.append(ParseIssue("repeated_furniture", f"疑似重复页眉/页脚出现 {count} 次：{text[:40]}", "info"))
    for block in blocks:
        if block.type == "table" and not block.html and len(block.text) < 8:
            issues.append(ParseIssue("empty_table", "表格区域没有可靠的结构化内容", "warning", block.id, block.page))
        if block.confidence < 0.55:
            issues.append(ParseIssue("low_confidence", "该区域识别置信度较低，建议人工复核", "warning", block.id, block.page))
    ordered_groups: dict[str, list[Block]] = {}
    for block in blocks:
        if block.type == "list_item" and block.attributes.get("ordered"):
            ordered_groups.setdefault(str(block.attributes.get("list_id", "")), []).append(block)
    for group in ordered_groups.values():
        numbers = []
        for block in group:
            match = re.match(r"^(\d+)", str(block.attributes.get("marker", "")))
            if match:
                numbers.append((int(match.group(1)), block))
        for (previous, _), (current, block) in pairwise(numbers):
            if current > previous + 1:
                issues.append(
                    ParseIssue(
                        "list_sequence_gap",
                        f"有序列表编号从 {previous} 跳到 {current}，中间项目可能遗漏",
                        "warning",
                        block.id,
                        block.page,
                    )
                )
    inferred_pages = Counter(block.page for block in blocks if block.attributes.get("page_inferred") and block.page)
    inferred_total = sum(inferred_pages.values())
    if inferred_total >= 20:
        page, count = inferred_pages.most_common(1)[0]
        if count / inferred_total >= 0.6:
            issues.append(
                ParseIssue(
                    "page_inference_concentration",
                    f"推断页码的内容有 {count}/{inferred_total} 个集中在第 {page} 页，文档顺序可能失控",
                    "error",
                    page=page,
                )
            )
    return issues


def _inline_parts_markdown(block: Block, figures: dict[str, Block]) -> str:
    output: list[str] = []
    for part in block.parts:
        if part.get("type") == "text":
            output.append(str(part.get("text", "")))
            continue
        figure = figures.get(str(part.get("figure_id", "")))
        asset = str(part.get("asset") or (figure.region_image if figure else ""))
        caption = str(figure.attributes.get("caption", "插图") if figure else "插图").replace("]", "\\]")
        if asset:
            output.append(f"![{caption}]({asset})")
    return "".join(output).strip()


def _table_cell_image_markdown(block: Block, figures: dict[str, Block]) -> list[str]:
    output: list[str] = []
    for cell in block.attributes.get("cells", []):
        for figure_id in cell.get("figure_ids", []):
            figure = figures.get(str(figure_id))
            if not figure or not figure.region_image:
                continue
            caption = str(figure.attributes.get("caption") or f"表格单元格 R{int(cell['row']) + 1}C{int(cell['column']) + 1}")
            output.append(
                f"**表格单元格 R{int(cell['row']) + 1}C{int(cell['column']) + 1}：** "
                f"![{caption.replace(']', '\\]')}]({figure.region_image})"
            )
    return output


def to_markdown(blocks: list[Block]) -> str:
    output: list[str] = []
    figures = {block.id: block for block in blocks if block.type == "figure"}
    embedded_figure_ids = {
        str(part.get("figure_id"))
        for block in blocks
        for part in block.parts
        if part.get("type") == "image" and part.get("figure_id")
    }
    embedded_figure_ids.update(
        str(figure_id)
        for block in blocks
        if block.type == "table"
        for cell in block.attributes.get("cells", [])
        for figure_id in cell.get("figure_ids", [])
    )
    for block in blocks:
        if block.type in {"page_header", "page_footer"}:
            continue
        if block.type == "heading":
            output.append(f"{'#' * infer_heading_level(block)} {block.text}")
        elif block.type in {"warning", "safety_notice"}:
            value = str(block.attributes.get("body") or block.text)
            lines = value.splitlines() or [value]
            output.append("\n".join(f"> **{block.attributes.get('warning_level', '提示')}** {line}" if index == 0 else f"> {line}" for index, line in enumerate(lines)))
        elif block.type == "list_item":
            raw_marker = str(block.attributes.get("marker") or "").strip()
            marker = raw_marker if block.attributes.get("ordered") and raw_marker else "-"
            indent = "  " * int(block.attributes.get("list_level", 0))
            value = _inline_parts_markdown(block, figures) if block.parts else block.text
            output.append(f"{indent}{marker} {value}")
        elif block.type == "table":
            status = str(block.attributes.get("integrity_status", "review_required"))
            reasons = "；".join(str(item) for item in block.attributes.get("integrity_reasons", []))
            if status == "unsafe":
                region = f" 原始表格图像：{block.region_image}" if block.region_image else ""
                output.append(
                    f"> **[UNSAFE_TABLE · 已隔离]** 此表的行列或数值对应关系无法可靠证明，禁止作为技术参数或问答依据。"
                    f"{(' 原因：' + reasons) if reasons else ''}{region}"
                )
                raw_text = clean_text(block.text)
                if not raw_text:
                    grid = block.attributes.get("table_grid", {})
                    rows: dict[int, list[dict]] = {}
                    for cell in grid.get("cells", []):
                        rows.setdefault(int(cell.get("row", 0)), []).append(cell)
                    raw_text = "\n".join(
                        " | ".join(
                            str(cell.get("text", "")).strip()
                            for cell in sorted(cells, key=lambda item: int(item.get("column", 0)))
                        ).strip(" |")
                        for _row, cells in sorted(rows.items())
                    )
                if raw_text:
                    output.append(
                        "> **[RAW_TABLE_TEXT · 仅供复核]** 以下文字按源单元格顺序保留，不代表可靠的行列对应关系。\n"
                        + "\n".join(f"> {line}" for line in raw_text.splitlines() if line.strip())
                    )
            elif status == "review_required":
                output.append(
                    f"> **[TABLE_REVIEW_REQUIRED]** 此表格需要人工复核后才能作为技术参数依据。"
                    f"{(' 原因：' + reasons) if reasons else ''}"
                )
                if block.html:
                    output.append(block.html)
                elif block.text:
                    output.append(block.text)
            elif block.html:
                output.append(block.html)
            elif block.text:
                output.append(block.text)
            output.extend(_table_cell_image_markdown(block, figures))
        elif block.type == "figure":
            if block.id in embedded_figure_ids:
                continue
            caption = block.attributes.get("caption", "插图")
            output.append(f"![{caption}]({block.region_image})" if block.region_image else f"*[{caption}]*")
            figure_text = clean_text(str(block.attributes.get("visual_description") or block.text or ""))
            if figure_text:
                output.append(f"**图中可检索文字/说明：** {figure_text}")
        elif block.type == "caption":
            output.append(f"*{block.text}*")
        elif block.parts:
            output.append(_inline_parts_markdown(block, figures))
        elif block.text:
            output.append(block.text)
    return "\n\n".join(output).strip() + "\n"


def _visible_text(block: Block) -> str:
    return clean_text(html.unescape(re.sub(r"<[^>]+>", " ", block.text or block.html or "")))


def _record_page_coverage(reference: list[Block], candidate: list[Block], pages: list[Page] | None) -> list[ParseIssue]:
    if not pages:
        return []
    issues: list[ParseIssue] = []
    for page in pages:
        before = "\n".join(_visible_text(block) for block in reference if block.page == page.number and _visible_text(block))
        after = "\n".join(_visible_text(block) for block in candidate if block.page == page.number and _visible_text(block))
        expected_chars = len(re.sub(r"\s+", "", before))
        actual_chars = len(re.sub(r"\s+", "", after))
        char_ratio = min(1.0, actual_chars / expected_chars) if expected_chars else 1.0
        recall = anchor_recall(before, after)
        page.attributes["coverage"] = {
            "source_characters": expected_chars,
            "result_characters": actual_chars,
            "character_ratio": round(char_ratio, 3),
            "anchor_recall": round(recall, 3),
        }
        if char_ratio < 0.75 or recall < 0.9:
            issues.append(ParseIssue("page_content_loss", f"该页后处理覆盖率异常：字符 {char_ratio:.0%}，关键数字/编号 {recall:.0%}", "error", page=page.number))
    return issues


def run_postprocessing(
    blocks: list[Block], native_pdf_lines: list[Block] | None = None, pages: list[Page] | None = None
) -> tuple[list[Block], list[dict], str, list[ParseIssue]]:
    reference = deepcopy(blocks)
    normalized = normalize_types(blocks)
    native_completed, recovery_issues = recover_missing_native_lines(normalized, native_pdf_lines, pages)
    native_repaired = _apply_toc_reconstruction(native_completed, native_pdf_lines)
    repaired = repair_toc_reading_order(native_repaired)
    caption_repaired = extract_caption_overflow(repaired)
    ordered = canonical_reading_order(caption_repaired, pages)
    ordered = deduplicate_fused_blocks(ordered)
    ordered = ensure_toc_root(ordered)
    recover_printed_page_labels(pages, native_pdf_lines)
    issues = [*recovery_issues, *classify_page_furniture(ordered, pages)]
    split_headings = split_inline_headings(ordered)
    refine_heading_types(split_headings)
    listed = recover_lists(split_headings)
    merged = merge_broken_lines(listed)
    structured = aggregate_safety_notices(merged)
    structured = split_compound_captions(structured)
    enrich_toc(structured, pages)
    classify_semantic_symbols(structured, pages)
    link_figures_and_captions(structured)
    issues.extend(normalize_table_structure(structured))
    issues.extend(mark_table_continuations(structured))
    tree = build_heading_tree(structured)
    issues.extend(_record_page_coverage(reference, structured, pages))
    issues.extend(validate_blocks(structured))
    for order, block in enumerate(structured):
        block.reading_order = order
    return structured, tree, to_markdown(structured), issues

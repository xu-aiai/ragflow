from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from .model import BBox, Block, Evidence, Page


def _key(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text).lower()


def _text_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return min(len(left), len(right)) / max(len(left), len(right)) * 0.22 + 0.78
    return SequenceMatcher(None, left[:6000], right[:6000]).ratio()


def _copy_visual_evidence(native: Block, visual: Block, *, copy_geometry: bool) -> None:
    if copy_geometry or not native.page:
        native.page = visual.page
        native.bbox = visual.bbox
    if visual.region_image:
        native.region_image = visual.region_image
    native.confidence = min(native.confidence, visual.confidence)
    native.attributes.setdefault("visual_block_ids", []).append(visual.id)
    native.attributes.setdefault("visual_block_id", visual.id)
    native.attributes.update(
        {
            key: value
            for key, value in visual.attributes.items()
            if key in {"near_page_top", "near_page_bottom", "deepdoc_layout", "deepdoc_score", "position_slices", "spans_pages"}
        }
    )
    native.evidence.extend(item for item in visual.evidence if item not in native.evidence)


def _ordered_native_lines(lines: list[Block] | None) -> list[Block]:
    return sorted(
        [line for line in lines or [] if line.page and line.bbox and _key(line.text)],
        key=lambda line: (line.page or 0, line.bbox.y0 if line.bbox else 0, line.bbox.x0 if line.bbox else 0),
    )


def _best_line_span(target: Block, lines: list[Block], cursor: int) -> tuple[int, int, float] | None:
    wanted = _key(target.text)
    if len(wanted) < 2 or not lines:
        return None
    window_start = max(0, cursor - 3)
    window_end = min(len(lines), cursor + (260 if target.type == "table" else 150))
    maximum_span = 80 if target.type == "table" else 18
    threshold = 0.88 if len(wanted) < 10 else 0.72
    first_anchor = wanted[: min(8, len(wanted))]
    best: tuple[int, int, float] | None = None
    for start in range(window_start, window_end):
        first = _key(lines[start].text)
        if not first:
            continue
        if (
            first_anchor not in first
            and first[: min(8, len(first))] not in wanted
            and _text_score(wanted[:80], first[:80]) < 0.42
        ):
            continue
        joined = ""
        first_page = lines[start].page
        for end in range(start, min(window_end, start + maximum_span)):
            line = lines[end]
            if first_page and line.page and line.page > first_page + 1:
                break
            joined += _key(line.text)
            score = _text_score(wanted, joined)
            distance_penalty = min(0.06, max(0, start - cursor) * 0.0004)
            adjusted = score - distance_penalty
            if best is None or adjusted > best[2]:
                best = (start, end + 1, adjusted)
            if wanted == joined or (len(joined) > len(wanted) * 1.45 and score < threshold):
                break
    if best and best[2] >= threshold:
        return best
    return None


def _copy_line_geometry(block: Block, matched_lines: list[Block], score: float) -> None:
    page_groups: dict[int, list[Block]] = defaultdict(list)
    for line in matched_lines:
        if line.page:
            page_groups[line.page].append(line)
    if not page_groups:
        return
    first_page = min(page_groups)
    first_lines = [line for line in page_groups[first_page] if line.bbox]
    if first_lines:
        block.page = first_page
        block.bbox = BBox(
            min(line.bbox.x0 for line in first_lines if line.bbox),
            min(line.bbox.y0 for line in first_lines if line.bbox),
            max(line.bbox.x1 for line in first_lines if line.bbox),
            max(line.bbox.y1 for line in first_lines if line.bbox),
        )
    slices = []
    for page, group in sorted(page_groups.items()):
        located = [line for line in group if line.bbox]
        if not located:
            continue
        slices.append(
            {
                "page": page,
                "bbox": [
                    min(line.bbox.x0 for line in located if line.bbox),
                    min(line.bbox.y0 for line in located if line.bbox),
                    max(line.bbox.x1 for line in located if line.bbox),
                    max(line.bbox.y1 for line in located if line.bbox),
                ],
            }
        )
    block.attributes.update(
        {
            "alignment_channel": "pdf_native",
            "alignment_score": round(score, 3),
            "native_line_ids": [line.id for line in matched_lines],
            "position_slices": slices,
            "spans_pages": len(page_groups) > 1,
        }
    )
    for line in (matched_lines[0], matched_lines[-1]):
        block.evidence.extend(item for item in line.evidence if item not in block.evidence)


def _interpolate_missing_pages(blocks: list[Block], page_count: int) -> None:
    anchors = [(index, block.page) for index, block in enumerate(blocks) if block.page]
    if not anchors:
        if page_count:
            for index, block in enumerate(blocks):
                ratio = index / max(1, len(blocks) - 1)
                block.page = max(1, min(page_count, round(1 + (page_count - 1) * ratio)))
                block.attributes.update({"page_inferred": True, "page_inference_strategy": "ooxml_proportional_fallback"})
        return
    for index, block in enumerate(blocks):
        if block.page:
            continue
        previous = next(((anchor_index, page) for anchor_index, page in reversed(anchors) if anchor_index < index), None)
        following = next(((anchor_index, page) for anchor_index, page in anchors if anchor_index > index), None)
        if previous and following:
            left_index, left_page = previous
            right_index, right_page = following
            ratio = (index - left_index) / max(1, right_index - left_index)
            inferred = round(int(left_page) + (int(right_page) - int(left_page)) * ratio)
        elif previous:
            inferred = int(previous[1])
        elif following:
            inferred = int(following[1])
        else:
            continue
        block.page = max(1, min(page_count, inferred))
        block.attributes.update({"page_inferred": True, "page_inference_strategy": "ooxml_source_order_interpolation"})


def _bbox_overlap(left: Block, right: Block) -> float:
    if not left.bbox or not right.bbox or left.page != right.page:
        return 0.0
    x0, y0 = max(left.bbox.x0, right.bbox.x0), max(left.bbox.y0, right.bbox.y0)
    x1, y1 = min(left.bbox.x1, right.bbox.x1), min(left.bbox.y1, right.bbox.y1)
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area = max(1.0, (right.bbox.x1 - right.bbox.x0) * (right.bbox.y1 - right.bbox.y0))
    return intersection / area


def _visual_covered(visual: Block, native_by_page: dict[int, list[Block]]) -> bool:
    value = _key(visual.text or visual.html)
    if not value or not visual.page:
        return False
    for native in native_by_page.get(visual.page, []):
        candidate = _key(native.text or native.html)
        if not candidate:
            continue
        score = _text_score(value, candidate)
        if score >= 0.88 or (_bbox_overlap(native, visual) >= 0.45 and score >= 0.58):
            coverage_key = "covered_native_line_ids" if visual.attributes.get("native_pdf_line") else "covered_visual_block_ids"
            native.attributes.setdefault(coverage_key, []).append(visual.id)
            native.evidence.extend(item for item in visual.evidence if item not in native.evidence)
            return True
    return False


def fuse_ooxml_and_visual(
    native_blocks: list[Block],
    visual_blocks: list[Block],
    pages: list[Page],
    native_pdf_lines: list[Block] | None = None,
) -> list[Block]:
    """Fuse DOCX semantics with rendered-page evidence without losing either stream."""

    lines = _ordered_native_lines(native_pdf_lines)
    line_cursor = 0
    used_line_ids: set[str] = set()
    for source_order, native in enumerate(native_blocks):
        native.attributes.setdefault("ooxml_source_order", source_order)
        native.attributes.setdefault("source_reading_order", source_order)
        if native.type == "figure" or not native.text:
            continue
        match = _best_line_span(native, lines, line_cursor)
        if not match:
            continue
        start, end, score = match
        matched_lines = lines[start:end]
        _copy_line_geometry(native, matched_lines, score)
        used_line_ids.update(line.id for line in matched_lines)
        line_cursor = max(line_cursor, end)

    exact: dict[str, list[Block]] = defaultdict(list)
    prefix: dict[str, list[Block]] = defaultdict(list)
    for visual in visual_blocks:
        value = _key(visual.text or visual.html)
        if value:
            exact[value].append(visual)
            prefix[value[:16]].append(visual)
    used_visual: set[str] = set()
    for native in native_blocks:
        value = _key(native.text or native.html)
        if not value:
            continue
        candidates = [item for item in exact.get(value, []) if item.id not in used_visual]
        if not candidates:
            candidates = [item for item in prefix.get(value[:16], []) if item.id not in used_visual]
        candidates = [item for item in candidates if not native.page or item.page == native.page]
        if not candidates:
            continue
        match = max(candidates, key=lambda item: _text_score(value, _key(item.text or item.html)))
        if _text_score(value, _key(match.text or match.html)) < 0.62:
            continue
        used_visual.add(match.id)
        _copy_visual_evidence(native, match, copy_geometry=not bool(native.page))

    _interpolate_missing_pages(native_blocks, len(pages))

    for kind in ("table", "figure"):
        native_by_page: dict[int, list[Block]] = defaultdict(list)
        visual_by_page: dict[int, list[Block]] = defaultdict(list)
        for block in native_blocks:
            if block.type == kind and block.page and not block.attributes.get("visual_block_id"):
                native_by_page[block.page].append(block)
        for block in visual_blocks:
            visual_kind = "figure" if block.type.lower() in {"figure", "image"} else block.type.lower()
            if visual_kind == kind and block.page and block.id not in used_visual:
                visual_by_page[block.page].append(block)
        for page, native_group in native_by_page.items():
            visual_group = sorted(
                visual_by_page.get(page, []),
                key=lambda block: (block.bbox.y0 if block.bbox else 0, block.bbox.x0 if block.bbox else 0),
            )
            for native, visual in zip(native_group, visual_group, strict=False):
                used_visual.add(visual.id)
                _copy_visual_evidence(native, visual, copy_geometry=True)

    native_by_page: dict[int, list[Block]] = defaultdict(list)
    for native in native_blocks:
        if native.page:
            native_by_page[native.page].append(native)

    supplements: list[Block] = []
    for visual in visual_blocks:
        if visual.id in used_visual or _visual_covered(visual, native_by_page):
            continue
        visual.attributes.update({"fusion_role": "visual_fallback", "qa_eligible": visual.type.lower() != "table"})
        supplements.append(visual)

    unused_lines = [line for line in lines if line.id not in used_line_ids and not line.attributes.get("native_toc_row")]
    for line in unused_lines:
        if _visual_covered(line, native_by_page):
            continue
        fallback = Block(
            id=f"docx-native-fallback-{line.id}",
            type="paragraph",
            text=line.text,
            page=line.page,
            bbox=line.bbox,
            confidence=line.confidence,
            attributes={
                "source_type": "pdf_native",
                "fusion_role": "native_pdf_fallback",
                "source_reading_order": line.reading_order,
            },
            evidence=list(line.evidence),
        )
        supplements.append(fallback)

    combined = [*native_blocks, *supplements]
    for order, block in enumerate(combined):
        block.reading_order = order
        if not block.evidence:
            block.evidence.append(Evidence("fusion", block.id, block.confidence, "unmatched block"))
    for page in pages:
        page.block_ids = [
            block.id
            for block in combined
            if block.page == page.number or any(item.get("page") == page.number for item in block.attributes.get("position_slices", []))
        ]
    return combined

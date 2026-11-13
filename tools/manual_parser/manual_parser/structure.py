from __future__ import annotations

import re
from collections import Counter, defaultdict
from copy import deepcopy
from difflib import SequenceMatcher

from .model import Block, Page, ParseIssue

PAGE_LABEL_RE = re.compile(r"^[.．。·…\s]*(\d{1,4}|[IVXLCDM]{1,8})[.．。·…\s]*$", re.IGNORECASE)
NUMBERED_TITLE_RE = re.compile(r"^(?:第[一二三四五六七八九十百]+[章节]|\d+(?:\.\d+){1,5})[\s、.　]*")
LIST_MARKER_RE = re.compile(r"^\s*((?:\d+[.)）(（、．]|[A-Za-z][.)）(（、．]|[一二三四五六七八九十]+[、.)）]|[•●▪◦·★\-–—]))\s*[•●▪◦·]?\s*(.+)$", re.DOTALL)
TRAILING_BULLET_RE = re.compile(r"\s*[•●▪◦·]\s*$")
WARNING_LABEL_RE = re.compile(r"^(危险|警告|注意|小心|提示|重要)(?:说明)?\s*[！!：:]?\s*(.*)$", re.DOTALL)


def canonical_reading_order(blocks: list[Block], pages: list[Page] | None = None) -> list[Block]:
    """Put every object into a page-aware stream with XY-cut column ordering."""
    for block in blocks:
        block.attributes.setdefault("source_reading_order", block.reading_order)
    known_pages = [(block.reading_order, block.page) for block in blocks if block.page]
    for block in blocks:
        if block.page or not known_pages:
            continue
        source_order, inferred_page = min(known_pages, key=lambda item: abs(item[0] - block.reading_order))
        block.page = int(inferred_page)
        block.attributes.update({"page_inferred": True, "page_inferred_from_order": source_order})
    page_widths = {page.number: page.width for page in pages or []}
    grouped: defaultdict[int, list[Block]] = defaultdict(list)
    unplaced: list[Block] = []
    for block in blocks:
        slices = block.attributes.get("position_slices") or []
        slice_pages = [item.get("page") for item in slices if item.get("page")]
        page_number = block.page or (min(slice_pages) if slice_pages else None)
        if page_number:
            grouped[int(page_number)].append(block)
        else:
            unplaced.append(block)
    ordered: list[Block] = []
    for page_number in sorted(grouped):
        group = grouped[page_number]
        width = page_widths.get(page_number) or max((block.bbox.x1 for block in group if block.bbox), default=1.0)
        ordered.extend(_order_page(group, width))
    ordered.extend(sorted(unplaced, key=lambda block: block.reading_order))
    for index, block in enumerate(ordered):
        block.reading_order = index
    return ordered


def _order_page(blocks: list[Block], page_width: float) -> list[Block]:
    located = [block for block in blocks if block.bbox]
    unlocated = [block for block in blocks if not block.bbox]
    if len(located) <= 1:
        return _merge_unlocated(located, unlocated)
    wide = [
        block
        for block in located
        if (block.bbox.x1 - block.bbox.x0) >= page_width * 0.62
        or (block.bbox.x0 <= page_width * 0.32 and block.bbox.x1 >= page_width * 0.68)
    ]
    wide_ids = {block.id for block in wide}
    separators = sorted(wide, key=lambda block: (_center_y(block), block.bbox.x0))
    narrow = [block for block in located if block.id not in wide_ids]
    bands: list[list[Block]] = [[] for _ in range(len(separators) + 1)]
    for block in narrow:
        band = sum(_center_y(separator) < _center_y(block) for separator in separators)
        bands[band].append(block)
    output: list[Block] = []
    for index, band in enumerate(bands):
        output.extend(_order_band(band, page_width))
        if index < len(separators):
            separators[index].attributes["reading_order_strategy"] = "full_width_separator"
            output.append(separators[index])
    for block in output:
        block.attributes.setdefault("reading_order_strategy", "xy_cut")
    return _merge_unlocated(output, unlocated)


def _order_band(blocks: list[Block], page_width: float) -> list[Block]:
    if len(blocks) <= 1:
        return blocks
    intervals = sorted(
        ((block.bbox.x0, block.bbox.x1, block) for block in blocks if block.bbox),
        key=lambda item: (item[0], item[1], item[2].reading_order),
    )
    split_candidates: list[tuple[float, float]] = []
    right_edge = intervals[0][1]
    for index in range(1, len(intervals)):
        next_left = intervals[index][0]
        left_count = index
        right_count = len(intervals) - index
        gap = next_left - right_edge
        if gap >= page_width * 0.06 and left_count >= 2 and right_count >= 2:
            split_candidates.append((gap, (next_left + right_edge) / 2))
        right_edge = max(right_edge, intervals[index][1])
    if split_candidates:
        _gap, split = max(split_candidates)
        left = [block for block in blocks if block.bbox and (block.bbox.x0 + block.bbox.x1) / 2 < split]
        left_ids = {block.id for block in left}
        right = [block for block in blocks if block.id not in left_ids]
        if left and right and all(block.bbox.x1 <= split for block in left) and all(block.bbox.x0 >= split for block in right):
            for block in blocks:
                block.attributes["reading_order_columns"] = 2
            return [*_order_band(left, page_width), *_order_band(right, page_width)]
    return sorted(blocks, key=lambda block: (block.bbox.y0, block.bbox.x0, block.reading_order))


def _center_y(block: Block) -> float:
    return (block.bbox.y0 + block.bbox.y1) / 2 if block.bbox else float(block.reading_order)


def _merge_unlocated(located: list[Block], unlocated: list[Block]) -> list[Block]:
    output = list(located)
    for block in sorted(unlocated, key=lambda item: item.attributes.get("source_reading_order", item.reading_order)):
        source_order = block.attributes.get("source_reading_order", block.reading_order)
        before = [
            item
            for item in output
            if item.attributes.get("source_reading_order", item.reading_order) <= source_order
        ]
        after = [
            item
            for item in output
            if item.attributes.get("source_reading_order", item.reading_order) > source_order
        ]
        if before:
            anchor = max(before, key=lambda item: item.attributes.get("source_reading_order", item.reading_order))
            insert_at = output.index(anchor) + 1
        elif after:
            anchor = min(after, key=lambda item: item.attributes.get("source_reading_order", item.reading_order))
            insert_at = output.index(anchor)
        else:
            insert_at = len(output)
        block.attributes["reading_order_strategy"] = "source_order_interpolation"
        output.insert(insert_at, block)
    return output


def classify_page_furniture(blocks: list[Block], pages: list[Page] | None) -> list[ParseIssue]:
    if not pages:
        return []
    page_map = {page.number: page for page in pages}
    issues: list[ParseIssue] = []
    occurrences: defaultdict[str, list[Block]] = defaultdict(list)
    for block in blocks:
        if block.attributes.get("toc_root"):
            continue
        compact = re.sub(r"\s+", "", block.text).strip(".．。·…")
        page = page_map.get(block.page or -1)
        if not page or not compact:
            continue
        near_top = bool(block.attributes.get("near_page_top")) or bool(block.bbox and block.bbox.y0 <= page.height * 0.12)
        near_bottom = bool(block.attributes.get("near_page_bottom")) or bool(block.bbox and block.bbox.y1 >= page.height * 0.88)
        if PAGE_LABEL_RE.fullmatch(compact) and near_bottom:
            label = PAGE_LABEL_RE.fullmatch(compact).group(1)  # type: ignore[union-attr]
            page.printed_page_label = label.upper() if label.isalpha() else label
            block.type = "page_footer"
            block.attributes["printed_page_label"] = page.printed_page_label
        if near_top or near_bottom:
            occurrences[compact.lower()].append(block)
    for text, repeated in occurrences.items():
        page_count = len({block.page for block in repeated})
        if page_count < 3 or len(text) > 80:
            continue
        for block in repeated:
            if block.attributes.get("toc_root"):
                continue
            page = page_map.get(block.page or -1)
            if not page or not block.bbox:
                continue
            block.type = "page_header" if block.bbox.y0 <= page.height * 0.5 else "page_footer"
            block.attributes["repeated_furniture"] = True
        issues.append(ParseIssue("page_furniture", f"已识别并隔离重复页眉/页脚：{repeated[0].text[:40]}", "info"))
    return issues


def refine_heading_types(blocks: list[Block]) -> None:
    for index, block in enumerate(blocks):
        if block.type != "heading":
            continue
        if block.attributes.get("toc_page"):
            continue
        text = block.text.strip()
        compact = re.sub(r"\s+", "", text).upper()
        chinese_chapter = re.match(r"^([一二三四五六七八九十百]+)、\s*(.{2,32})$", text)
        if compact in {"XCMG", "IXCMG"}:
            block.type = "page_header"
            block.attributes["heading_demoted_reason"] = "logo_ocr"
        elif PAGE_LABEL_RE.fullmatch(compact):
            block.type = "page_footer"
            block.attributes["heading_demoted_reason"] = "page_label"
        elif chinese_chapter and not re.search(r"[。！？；]", chinese_chapter.group(2)):
            block.level = 2
            block.attributes["heading_scheme"] = "chinese_chapter"
        elif LIST_MARKER_RE.match(text) or re.match(r"^\s*\d+[.)）(（、．]", text):
            block.type = "paragraph"
            block.attributes["heading_demoted_reason"] = "list_item"
        elif len(text) > 90 or (len(text) > 45 and re.search(r"[。！？；]", text)):
            block.type = "paragraph"
            block.attributes["heading_demoted_reason"] = "sentence_like"
        elif (
            re.search(r"[。！？；]$", text)
            and not NUMBERED_TITLE_RE.match(text)
            and index > 0
            and blocks[index - 1].type == "paragraph"
            and not re.search(r"[。！？；]$", blocks[index - 1].text)
        ):
            block.type = "paragraph"
            block.attributes["heading_demoted_reason"] = "broken_paragraph_tail"
        elif not NUMBERED_TITLE_RE.match(text) and re.search(r"必须|不得|禁止|格外小心|保修和担保索赔", text):
            block.type = "callout"
            block.attributes["heading_demoted_reason"] = "emphasis_callout"


def recover_lists(blocks: list[Block]) -> list[Block]:
    """Recover list items and groups while keeping the original block coordinates."""
    prepared: list[Block] = []
    for source in blocks:
        block = deepcopy(source)
        if block.type == "paragraph":
            # A numeric marker followed by an OCR bullet is still one ordered
            # item (for example ``4）•当需要两个人……``).  Record the marker
            # before splitting inline bullet lists so it cannot become a
            # marker-only item.
            prefixed = LIST_MARKER_RE.match(block.text)
            if prefixed and re.match(r"^(?:\d+|[A-Za-z]|[一二三四五六七八九十百]+)[.)）(（、．]$", prefixed.group(1)):
                block.attributes["forced_list_marker"] = prefixed.group(1)
                block.text = prefixed.group(2).strip()
            # DeepDOC may keep an entire bullet list in one layout box. Split
            # explicit markers only after intra-word OCR bullets were removed.
            pieces = re.split(r"\s*[•●▪◦·]\s*", block.text)
            pieces = [piece.strip() for piece in pieces if piece.strip()]
            if len(pieces) >= 2:
                for piece_index, piece in enumerate(pieces):
                    child = deepcopy(block)
                    child.id = f"{block.id}-list-{piece_index}"
                    child.text = piece
                    child.attributes["forced_list_marker"] = (
                        (block.attributes.get("forced_list_marker") or "•") if piece_index == 0 else "•"
                    )
                    child.attributes["split_from_block"] = block.id
                    if child.bbox:
                        height = (block.bbox.y1 - block.bbox.y0) / len(pieces)
                        child.bbox.y0 = block.bbox.y0 + piece_index * height
                        child.bbox.y1 = block.bbox.y0 + (piece_index + 1) * height
                    prepared.append(child)
                continue
            star = re.search(r"(?<=[。！？])★(?=\S)", block.text)
            if star:
                for piece_index, piece in enumerate((block.text[: star.start()], block.text[star.start() + 1 :])):
                    child = deepcopy(block)
                    child.id = f"{block.id}-star-{piece_index}"
                    child.text = piece.strip()
                    child.attributes["split_from_block"] = block.id
                    if piece_index:
                        child.attributes["forced_list_marker"] = "★"
                    prepared.append(child)
                continue
        prepared.append(block)
    for index, block in enumerate(prepared):
        if block.type != "paragraph" or not TRAILING_BULLET_RE.search(block.text):
            continue
        block.text = TRAILING_BULLET_RE.sub("", block.text).strip()
        block.attributes["recovered_trailing_bullet"] = True
        block.attributes["forced_list_marker"] = "•"
        # A marker-only visual block may be emitted immediately before its text.
        if not block.text and index + 1 < len(prepared) and prepared[index + 1].page == block.page:
            prepared[index + 1].attributes["forced_list_marker"] = "•"

    output: list[Block] = []
    current_list: str | None = None
    list_index = 0
    last_level = 0
    base_indent: float | None = None
    for block in prepared:
        forced_marker = block.attributes.pop("forced_list_marker", None)
        marker_match = LIST_MARKER_RE.match(block.text) if block.type == "paragraph" else None
        native_list = bool(block.attributes.get("is_list"))
        native_ordered = bool(re.search(r"number|编号|数字", str(block.attributes.get("style", "")), re.IGNORECASE))
        marker = forced_marker or (marker_match.group(1) if marker_match else "") or ("1." if native_list and native_ordered else "•" if native_list else "")
        if marker:
            if marker_match:
                block.text = marker_match.group(2).strip()
                if block.parts:
                    remaining = marker_match.start(2)
                    for part in block.parts:
                        if part.get("type") != "text" or remaining <= 0:
                            continue
                        value = str(part.get("text", ""))
                        consumed = min(len(value), remaining)
                        part["text"] = value[consumed:]
                        remaining -= consumed
            native_list_id = str(block.attributes.get("native_list_id", ""))
            if native_list_id:
                current_list = f"list-ooxml-{native_list_id}"
            elif current_list is None:
                list_index += 1
                current_list = f"list-{block.page or 0}-{list_index}"
                base_indent = block.bbox.x0 if block.bbox else None
            level = int(block.attributes.get("native_list_level", _list_level(block, base_indent, last_level)))
            block.type = "list_item"
            block.attributes.update(
                {
                    "list_id": current_list,
                    "list_level": level,
                    "ordered": native_ordered
                    or bool(re.match(r"(?:\d+|[A-Za-z]|[一二三四五六七八九十百]+)[.)）(（、．]", marker)),
                    "marker": marker,
                }
            )
            last_level = level
            output.append(block)
            continue
        if output and output[-1].type == "list_item" and block.type == "paragraph" and _is_list_continuation(output[-1], block):
            previous = output[-1]
            joiner = " " if re.search(r"[A-Za-z0-9]$", previous.text) and re.match(r"[A-Za-z0-9]", block.text) else ""
            if previous.parts or block.parts:
                if not previous.parts:
                    previous.parts = [{"type": "text", "text": previous.text}]
                incoming = deepcopy(block.parts) if block.parts else [{"type": "text", "text": block.text}]
                if joiner:
                    if previous.parts[-1].get("type") == "text":
                        previous.parts[-1]["text"] = str(previous.parts[-1].get("text", "")) + joiner
                    else:
                        previous.parts.append({"type": "text", "text": joiner})
                if incoming and previous.parts[-1].get("type") == incoming[0].get("type") == "text":
                    previous.parts[-1]["text"] = str(previous.parts[-1].get("text", "")) + str(incoming[0].get("text", ""))
                    incoming = incoming[1:]
                previous.parts.extend(incoming)
            previous.text += joiner + block.text
            previous.attributes.setdefault("merged_block_ids", []).append(block.id)
            previous.evidence.extend(block.evidence)
            if previous.bbox and block.bbox:
                previous.bbox.x1 = max(previous.bbox.x1, block.bbox.x1)
                previous.bbox.y1 = max(previous.bbox.y1, block.bbox.y1)
            continue
        if block.type in {"page_header", "page_footer"}:
            output.append(block)
            continue
        current_list = None
        last_level = 0
        base_indent = None
        output.append(block)
    return output


def _list_level(block: Block, base_indent: float | None, fallback: int) -> int:
    if not block.bbox or base_indent is None:
        return fallback
    indent = max(0.0, float(block.bbox.x0) - base_indent)
    return max(0, min(5, round(indent / 24)))


def _is_list_continuation(previous: Block, current: Block) -> bool:
    if previous.page != current.page or not previous.bbox or not current.bbox:
        return False
    line_height = max(1.0, previous.bbox.y1 - previous.bbox.y0)
    gap = current.bbox.y0 - previous.bbox.y1
    close_vertically = -line_height * 0.2 <= gap <= max(line_height * 1.6, 18.0)
    continuation_indent = current.bbox.x0 >= previous.bbox.x0 - max(line_height * 3.0, 36.0)
    return close_vertically and continuation_indent and not re.search(r"[。！？；]$", previous.text)


def aggregate_safety_notices(blocks: list[Block]) -> list[Block]:
    output: list[Block] = []
    index = 0
    while index < len(blocks):
        source = blocks[index]
        match = WARNING_LABEL_RE.match(source.text) if source.type in {"warning", "paragraph"} else None
        if not match:
            output.append(source)
            index += 1
            continue
        level = match.group(1)
        body_parts = [match.group(2).strip()] if match.group(2).strip() else []
        merged_ids: list[str] = []
        cursor = index + 1
        while cursor < len(blocks) and len(body_parts) < 3 and not (body_parts and re.search(r"[。！？!?]$", body_parts[-1])):
            candidate = blocks[cursor]
            if candidate.page != source.page or candidate.type not in {"paragraph", "list_item"}:
                break
            if source.bbox and candidate.bbox:
                line_height = max(1.0, source.bbox.y1 - source.bbox.y0)
                if candidate.bbox.y0 - source.bbox.y1 > line_height * 8:
                    break
            body_parts.append(candidate.text)
            merged_ids.append(candidate.id)
            if re.search(r"[。！？!?]$", candidate.text):
                cursor += 1
                break
            cursor += 1
        source.type = "safety_notice"
        body = "".join(body_parts)
        source.text = f"{level}！{body}" if body else f"{level}！"
        source.attributes.update({"warning_level": level, "label": level, "body": body})
        if merged_ids:
            source.attributes["merged_block_ids"] = [*source.attributes.get("merged_block_ids", []), *merged_ids]
            source.children.extend(merged_ids)
        output.append(source)
        index = max(index + 1, cursor)
    return output


def enrich_toc(blocks: list[Block], pages: list[Page] | None = None) -> None:
    headings = [block for block in blocks if block.type == "heading" and not block.attributes.get("toc_page")]
    page_by_label = {
        page.printed_page_label.upper(): page.number
        for page in pages or []
        if page.printed_page_label
    }
    max_physical_page = max((page.number for page in pages or []), default=0)
    toc_root = next((block for block in blocks if block.attributes.get("toc_root")), None)
    page_min_x: dict[int, float] = {}
    for block in blocks:
        if block.type == "toc_entry" and block.page and block.bbox:
            page_min_x[block.page] = min(page_min_x.get(block.page, block.bbox.x0), block.bbox.x0)
    for block in blocks:
        if block.type != "toc_entry":
            continue
        title = str(block.attributes.get("toc_title") or block.text.split("……", 1)[0]).strip()
        number = re.match(r"^(\d+(?:\.\d+)*)", title)
        if number:
            level = number.group(1).count(".") + 1
        elif block.bbox and block.page in page_min_x:
            level = 1 + max(0, round((block.bbox.x0 - page_min_x[block.page]) / 24))
        else:
            level = 1
        block.attributes["toc_level"] = min(6, level)
        block.level = min(6, level)
        target_label = str(block.attributes.get("target_page_label", "")).upper()
        for stale_key in ("target_heading_id", "target_physical_page", "target_pdf_page", "target_match_score", "resolution_status"):
            block.attributes.pop(stale_key, None)
        block.attributes.update(
            {
                "printed_page_label": target_label,
                "search_role": "navigation",
                "qa_eligible": False,
            }
        )
        target_page = page_by_label.get(target_label)
        if target_page:
            block.attributes["target_pdf_page"] = target_page
            wanted = _title_key(title)
            nearby_headings = [heading for heading in headings if heading.page and abs(heading.page - target_page) <= 1]
            candidates = [
                (SequenceMatcher(None, wanted, _title_key(heading.text)).ratio(), heading)
                for heading in nearby_headings
                if wanted
            ]
            if candidates:
                score, target = max(candidates, key=lambda item: item[0])
                if score >= 0.82:
                    block.attributes.update(
                        {
                            "target_heading_id": target.id,
                            "target_pdf_page": target.page,
                            "target_match_score": round(score, 3),
                            "resolution_status": "verified" if target.page == target_page else "nearby_heading",
                        }
                    )
                else:
                    block.attributes["resolution_status"] = "page_resolved"
            else:
                block.attributes["resolution_status"] = "page_resolved"
        elif target_label.isdigit() and int(target_label) > max_physical_page:
            block.attributes["resolution_status"] = "out_of_parse_range"
        else:
            block.attributes["resolution_status"] = "unresolved"
    stack: list[Block] = []
    previous_page: int | None = None
    for block in [item for item in blocks if item.type == "toc_entry"]:
        if previous_page is not None and block.page and block.page > previous_page + 1:
            stack.clear()
        level = int(block.attributes.get("toc_level", 1))
        while stack and int(stack[-1].attributes.get("toc_level", 1)) >= level:
            stack.pop()
        if stack:
            block.parent_id = stack[-1].id
            if block.id not in stack[-1].children:
                stack[-1].children.append(block.id)
        elif toc_root:
            block.parent_id = toc_root.id
            if block.id not in toc_root.children:
                toc_root.children.append(block.id)
        path = ["目录", *[str(item.attributes.get("toc_title") or item.text) for item in stack], title]
        block.attributes["section_path"] = path
        stack.append(block)
        previous_page = block.page or previous_page


def classify_semantic_symbols(blocks: list[Block], pages: list[Page] | None) -> None:
    if not pages:
        return
    page_map = {page.number: page for page in pages}
    keywords = {
        "safety_warning": ("危险", "警告", "安全"),
        "weight": ("重量", "质量", "起吊"),
        "tightening_torque": ("紧固扭矩", "拧紧力矩", "扭矩"),
        "apply_adhesive": ("涂敷", "涂胶", "密封胶"),
        "coolant": ("冷却液", "防冻液"),
    }
    for index, block in enumerate(blocks):
        if block.type != "figure" or not block.bbox or not block.page:
            continue
        page = page_map.get(block.page)
        if not page:
            continue
        area_ratio = ((block.bbox.x1 - block.bbox.x0) * (block.bbox.y1 - block.bbox.y0)) / max(1.0, page.width * page.height)
        if area_ratio > 0.06:
            continue
        neighbors = [item for item in blocks[max(0, index - 3) : index + 4] if item.page == block.page and item.id != block.id]
        context = " ".join(item.text for item in neighbors)
        symbol = next((name for name, values in keywords.items() if any(value in context for value in values)), "")
        if symbol:
            block.attributes.update({"semantic_symbol": symbol, "search_text": f"[{symbol}] {context[:160]}"})
            block.attributes.setdefault("caption", f"语义图标：{symbol}")


def _title_key(value: str) -> str:
    value = re.sub(r"^\s*(?:第[一二三四五六七八九十百]+[章节]|\d+(?:\.\d+)*)[\s、.　]*", "", value)
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", value).lower()


def page_type_counts(blocks: list[Block]) -> dict[int, Counter[str]]:
    result: defaultdict[int, Counter[str]] = defaultdict(Counter)
    for block in blocks:
        if block.page:
            result[block.page][block.type] += 1
    return dict(result)

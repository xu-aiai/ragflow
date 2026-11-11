"""阶段 5a：文档树切分与块规整（规格 §3.A）。"""
from __future__ import annotations

import re

from ..images import cell_image_files
from ..numbering import strip_literal_prefix
from ..schemas import ImageBlock, ListBlock, ParaBlock, ParaImagePart, ParaTextPart, Section, StepsBlock, TableBlock, WarningBlock
from ..tables import classify_table

_LIST_RE = re.compile(r"^[●○·◆■□▲△]")
_STEP_RE = re.compile(r"^\d+\s*[.、)]|^[①②③④⑤⑥⑦⑧⑨⑩]")
_CAPTION_RE = re.compile(r"^(图\s*\d+[-–—~]\d+)")
_SENTENCE_END_RE = re.compile(r"[。！？；.!?;…][\"'”’）)]*$")


def build_tree(doc_code, elements, audit, image_files=None, literal=False, merge_pairs=None):
    """image_files: rId → 文件名（阶段 4 产物）。仅合并用户确认的段落边界。"""
    image_files = image_files or {}
    sections: list[Section] = []
    stack: list[Section] = []
    seen_ids: set[str] = set()
    pending = None  # 正在聚合的 list/steps 块

    def close_pending():
        nonlocal pending
        if pending is not None and stack:
            stack[-1].blocks.append(pending)
        pending = None

    def append_text_boxes(sec, para, src):
        if not para.text_boxes:
            return
        close_pending()
        for text in para.text_boxes:
            sec.blocks.append(ParaBlock(text=text, src=[src]))

    for el in elements:
        # ---- 标题：开新节 ----
        if el.kind == "para" and el.heading_level is not None:
            close_pending()
            raw_title = (el.para.text or "").strip()
            title = strip_literal_prefix(raw_title) if literal else raw_title
            if el.编号:
                sid = f"{doc_code}-{el.编号}"
                if sid in seen_ids:
                    # 编号重复（如 B 手册字面编号撞车）：id 是树挂接与深链的锚，
                    # 重复即成环风险，进审核清单由人工确认，绝不静默放行。
                    audit.add("文档树", f"section_id 重复：{sid}（{raw_title[:40]}）", sid)
                else:
                    seen_ids.add(sid)
            else:
                sid = f"{doc_code}-U{len(sections) + 1:02d}"
                audit.add("文档树", f"无编号标题，合成 ID {sid}：{raw_title[:40]}", sid)
            crumb = [
                f"{s.章节号} {s.标题}" if s.章节号 else s.标题
                for s in stack
                if s.层级 < el.heading_level
            ]
            sec = Section(
                section_id=sid,
                seq=len(sections),
                章节号=el.编号,
                标题=title,
                层级=el.heading_level,
                parent=next((s.section_id for s in reversed(stack) if s.层级 < el.heading_level), None),
                面包屑=" > ".join(crumb + [f"{el.编号} {title}" if el.编号 else title]),
                src=[el.index],
            )
            while stack and stack[-1].层级 >= el.heading_level:
                stack.pop()
            stack.append(sec)
            sections.append(sec)
            continue

        sec = stack[-1] if stack else None
        if sec is None:
            continue  # 首个标题之前的内容（封面等）不入树
        if el.kind == "table":
            close_pending()
            grid = el.table.grid
            kind = el.forced_kind or classify_table(grid, sec.章节号)
            if kind == "warning":
                sec.blocks.append(_warning_block(grid, el.index))
            elif kind == "layout":
                _dissolve_layout(sec, el.table, image_files, audit, el.index)
            else:
                sec.blocks.append(TableBlock(
                    header=grid[0], rows=grid[1:],
                    cell_images=cell_image_files(el.table, image_files),
                    col_spans=el.table.col_spans, row_spans=el.table.row_spans, src=[el.index],
                ))
            continue

        # ---- 段落 ----
        text = (el.para.text or "").strip()
        if not text and not el.para.image_rids:
            append_text_boxes(sec, el.para, el.index)
            continue
        if el.para.image_rids:
            close_pending()
            if text and any(part.kind == "image" for part in el.para.parts):
                sec.blocks.append(_inline_para_block(sec, el.para, image_files, audit, el.index))
            else:
                for rid in el.para.image_rids:
                    _append_image(sec, rid, image_files, audit, el.index)
                if text:
                    sec.blocks.append(ParaBlock(text=text, src=[el.index]))
            append_text_boxes(sec, el.para, el.index)
            continue
        # 题注并入前一个图片块
        m = _CAPTION_RE.match(text)
        if m and sec.blocks and isinstance(sec.blocks[-1], ImageBlock) and sec.blocks[-1].图号 is None:
            sec.blocks[-1].图号 = m.group(1)
            sec.blocks[-1].题注 = text
            append_text_boxes(sec, el.para, el.index)
            continue
        if _LIST_RE.match(text):
            if not isinstance(pending, ListBlock):
                close_pending()
                pending = ListBlock(style="check")
            pending.items.append(_LIST_RE.sub("", text).strip())
            pending.src.append(el.index)
            append_text_boxes(sec, el.para, el.index)
            continue
        if el.para.has_num_pr or _STEP_RE.match(text):
            if not isinstance(pending, StepsBlock):
                close_pending()
                pending = StepsBlock()
            pending.items.append(_STEP_RE.sub("", text).strip() if not el.para.has_num_pr else text)
            pending.src.append(el.index)
            append_text_boxes(sec, el.para, el.index)
            continue
        close_pending()
        sec.blocks.append(ParaBlock(text=text, src=[el.index]))
        append_text_boxes(sec, el.para, el.index)
    close_pending()
    approved = {
        (int(pair["previous"]), int(pair["current"]))
        for pair in (merge_pairs or [])
    }
    for section in sections:
        _merge_confirmed_paragraphs(section, elements, approved)
    return sections


def _is_continuation_text(previous_text: str, current_text: str) -> bool:
    return bool(
        len(previous_text) >= 12
        and current_text
        and not _SENTENCE_END_RE.search(previous_text)
        and not current_text.startswith(("图", "表", "注：", "注意："))
    )


def _merge_confirmed_paragraphs(section: Section, elements, approved: set[tuple[int, int]]) -> None:
    """仅合并用户确认的来源边界，保留原文和全部来源锚点。"""
    source = {el.index: el for el in elements if el.kind == "para" and el.para is not None}
    blocks = section.blocks
    i = 1
    while i < len(blocks):
        previous, current = blocks[i - 1], blocks[i]
        if not isinstance(previous, ParaBlock) or not isinstance(current, ParaBlock):
            i += 1
            continue
        if not previous.src or not current.src:
            i += 1
            continue
        prev_id, current_id = previous.src[-1], current.src[0]
        if (prev_id, current_id) not in approved:
            i += 1
            continue
        prev_el, current_el = source.get(prev_id), source.get(current_id)
        if prev_el is None or current_el is None:
            i += 1
            continue
        prev_style = (prev_el.para.style or "").strip().casefold()
        current_style = (current_el.para.style or "").strip().casefold()
        if prev_id + 1 != current_id or prev_style != current_style:
            i += 1
            continue
        prev_text = previous.text.rstrip()
        current_text = current.text.lstrip()
        if not _is_continuation_text(prev_text, current_text):
            i += 1
            continue
        if previous.parts or current.parts:
            previous.parts = (previous.parts or [ParaTextPart(text=prev_text)]) + (current.parts or [ParaTextPart(text=current_text)])
        previous.text = prev_text + current_text
        previous.src.extend(current.src)
        del blocks[i]


def _append_image(sec, rid, image_files, audit, src=None):
    name = image_files.get(rid)
    if name:
        sec.blocks.append(ImageBlock(file=name, src=[src] if src is not None else []))
    else:
        audit.add("图片", f"{sec.section_id} 图片 rId={rid} 未提取", sec.section_id)


def _inline_para_block(sec, para, image_files, audit, src):
    parts = []
    for part in para.parts:
        if part.kind == "text":
            parts.append(ParaTextPart(text=part.text))
            continue
        name = image_files.get(part.rid)
        if name:
            parts.append(ParaImagePart(file=name))
        else:
            audit.add("图片", f"{sec.section_id} 图片 rId={part.rid} 未提取", sec.section_id)
    return ParaBlock(text=para.text.strip(), parts=parts, src=[src])


def _dissolve_layout(sec, table, image_files, audit, src):
    """排版表溶解成段落 + 图（保持单元格顺序）。"""
    rids_grid = table.cell_rids
    for r, row in enumerate(table.grid):
        for c, cell in enumerate(row):
            text = (cell or "").strip()
            if text:
                sec.blocks.append(ParaBlock(text=text, src=[src]))
            rids = rids_grid[r][c] if r < len(rids_grid) and c < len(rids_grid[r]) else []
            for rid in rids:
                _append_image(sec, rid, image_files, audit, src)


def _warning_block(grid, src):
    cells = [c.strip() for row in grid for c in row if (c or "").strip()]
    level = _warn_level(cells[0] if cells else "")
    return WarningBlock(level=level, text="\n".join(cells[1:]) if len(cells) > 1 else (cells[0] if cells else ""), src=[src])


def _warn_level(first: str) -> str:
    for lv in ("危险", "警告", "注意"):
        if first.startswith(lv):
            return lv
    low = first.lower()
    for word, lv in (("achtung", "警告"), ("warning", "警告"), ("caution", "注意"), ("attention", "注意")):
        if low.startswith(word):
            return lv
    return "注意"

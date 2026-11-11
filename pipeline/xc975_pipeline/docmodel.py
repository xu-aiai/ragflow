"""阶段 1：docx → DocumentModel（保序元素流）。

段落与表格按文档流顺序交错；图片以 rId 锚定在所在段落；
表格网格在此时展开合并单元格（vMerge 续行前向填充、gridSpan 展开）。
Word 自动目录包在 w:sdt 中，展开 sdtContent 一并读入（否则整页目录丢失）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph

MC_NAMESPACE = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
MC_CHOICE_TAG = MC_NAMESPACE + "Choice"
MC_FALLBACK_TAG = MC_NAMESPACE + "Fallback"
TEXT_BOX_TAG = qn("w:txbxContent")


def _has_ancestor(node, tag, stop=None):
    parent = node.getparent()
    while parent is not None and parent is not stop:
        if parent.tag == tag:
            return True
        parent = parent.getparent()
    return False


def _is_fallback_copy(box):
    node = box.getparent()
    while node is not None:
        if node.tag == MC_FALLBACK_TAG:
            alternate = node.getparent()
            if alternate is None:
                return False
            return any(choice.tag == MC_CHOICE_TAG and choice.find(".//" + TEXT_BOX_TAG) is not None for choice in alternate)
        node = node.getparent()
    return False


def _text_boxes_in(element):
    texts = []
    for box in element.findall(".//" + TEXT_BOX_TAG):
        if _is_fallback_copy(box):
            continue
        lines = []
        for p in box.iter(qn("w:p")):
            if _has_ancestor(p, TEXT_BOX_TAG, stop=box):
                continue
            line = "".join(t.text or "" for t in p.iter(qn("w:t")) if not _has_ancestor(t, TEXT_BOX_TAG, stop=p))
            if line.strip():
                lines.append(line)
        if lines:
            texts.append("\n".join(lines))
    return texts


def _iter_blocks(parent):
    """按文档流顺序产出块级节点，展开 w:sdt（自动目录域）。"""
    for child in parent.iterchildren():
        if child.tag == qn("w:sdt"):
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                yield from _iter_blocks(content)
        else:
            yield child


@dataclass
class ParaPart:
    kind: str  # "text" | "image"
    text: str = ""
    rid: str = ""


@dataclass
class Para:
    style: str = ""
    text: str = ""
    image_rids: list[str] = field(default_factory=list)
    text_boxes: list[str] = field(default_factory=list)
    has_num_pr: bool = False
    parts: list[ParaPart] = field(default_factory=list)


@dataclass
class Table:
    grid: list[list[str]] = field(default_factory=list)
    # 与 grid 同构的单元格图片 rId 网格（表格内嵌图是手册插图的大头）
    cell_rids: list[list[list[str]]] = field(default_factory=list)
    col_spans: list[list[int]] = field(default_factory=list)
    row_spans: list[list[int]] = field(default_factory=list)


@dataclass
class Element:
    kind: str  # "para" | "table"
    index: int
    para: Para | None = None
    table: Table | None = None
    # 阶段 2 填充：
    heading_level: int | None = None
    编号: str | None = None
    # 人工改标（工作台 overrides）：非空时优先于自动表格分类
    forced_kind: str | None = None


def parse_docx(path: str) -> tuple[list[Element], object]:
    """返回 (保序元素流, python-docx Document)。Document 供阶段 4 取图片部件。"""
    doc = Document(str(path))
    elements: list[Element] = []
    for idx, child in enumerate(_iter_blocks(doc.element.body)):
        if child.tag == qn("w:p"):
            elements.append(Element("para", idx, para=_read_para(Paragraph(child, doc))))
        elif child.tag == qn("w:tbl"):
            grid, cell_rids, col_spans, row_spans = table_grid(DocxTable(child, doc))
            elements.append(Element("table", idx, table=Table(grid=grid, cell_rids=cell_rids, col_spans=col_spans, row_spans=row_spans)))
    return elements, doc


def _image_rids(node) -> list[str]:
    """图片关系 ID：新格式 a:blip@r:embed + 老格式 v:imagedata@r:id（.doc 转换常见）。"""
    rids = [rid for blip in node.findall(".//" + qn("a:blip")) if (rid := blip.get(qn("r:embed")))]
    rids += [rid for img in node.findall(".//{urn:schemas-microsoft-com:vml}imagedata") if (rid := img.get(qn("r:id")))]
    return rids


def _para_parts(p: Paragraph) -> list[ParaPart]:
    parts: list[ParaPart] = []

    def append_text(text: str) -> None:
        if not text:
            return
        if parts and parts[-1].kind == "text":
            parts[-1].text += text
        else:
            parts.append(ParaPart(kind="text", text=text))

    def walk(node) -> None:
        for child in node.iterchildren():
            if child.tag == qn("w:t"):
                append_text(child.text or "")
            elif child.tag == qn("w:tab"):
                append_text("\t")
            elif child.tag in (qn("w:br"), qn("w:cr")):
                append_text("\n")
            elif child.tag in (qn("w:drawing"), qn("w:pict"), qn("w:object")):
                parts.extend(ParaPart(kind="image", rid=rid) for rid in _image_rids(child))
            elif child.tag == "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent":
                choice = child.find("{http://schemas.openxmlformats.org/markup-compatibility/2006}Choice")
                fallback = child.find("{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback")
                if choice is not None or fallback is not None:
                    walk(choice if choice is not None else fallback)
            elif child.tag in (
                qn("w:r"), qn("w:hyperlink"), qn("w:smartTag"), qn("w:ins"),
                qn("w:fldSimple"), qn("w:customXml"), qn("w:sdt"), qn("w:sdtContent"),
            ):
                walk(child)

    walk(p._p)
    return parts


def _read_para(p: Paragraph) -> Para:
    try:
        style = p.style.name if p.style is not None else ""
    except Exception:
        style = ""
    rids = _image_rids(p._p)
    text_boxes = [text for child in p._p for text in _text_boxes_in(child)]
    ppr = p._p.find(qn("w:pPr"))
    has_num = ppr is not None and ppr.find(qn("w:numPr")) is not None
    return Para(style=style, text=p.text or "", image_rids=rids, text_boxes=text_boxes, has_num_pr=has_num, parts=_para_parts(p))


def table_grid(tbl: DocxTable):
    """返回文本、图片、跨列和跨行网格；文本与图片网格保留展开后的逻辑列。"""
    rows: list[list[str]] = []
    rids_grid: list[list[list[str]]] = []
    col_spans: list[list[int]] = []
    merges: list[list[str | None]] = []
    for tr in tbl._tbl.findall(qn("w:tr")):
        row: list[str] = []
        rids_row: list[list[str]] = []
        span_row: list[int] = []
        merge_row: list[str | None] = []
        for tc in tr.findall(qn("w:tc")):
            span = 1
            vm = None
            tcpr = tc.find(qn("w:tcPr"))
            if tcpr is not None:
                gs = tcpr.find(qn("w:gridSpan"))
                if gs is not None:
                    span = int(gs.get(qn("w:val")))
                vm = tcpr.find(qn("w:vMerge"))
            text = _cell_text(tc)
            merge = None
            if vm is not None:
                merge = vm.get(qn("w:val")) or "continue"
                if merge != "restart":
                    col = len(row)
                    if rows and col < len(rows[-1]):
                        text = rows[-1][col]
            cell_rids = _image_rids(tc)
            row.extend([text] * span)
            rids_row.extend([cell_rids] * span)
            span_row.extend([span] * span)
            merge_row.extend([merge] * span)
        rows.append(row)
        rids_grid.append(rids_row)
        col_spans.append(span_row)
        merges.append(merge_row)

    row_spans: list[list[int]] = []
    for r, row in enumerate(rows):
        span_row = []
        for c in range(len(row)):
            merge = merges[r][c]
            if merge == "continue":
                span_row.append(0)
                continue
            rowspan = 1
            if merge == "restart":
                for next_row in range(r + 1, len(rows)):
                    if c >= len(rows[next_row]) or merges[next_row][c] != "continue":
                        break
                    rowspan += 1
            span_row.append(rowspan)
        row_spans.append(span_row)
    return rows, rids_grid, col_spans, row_spans


def _cell_text(tc) -> str:
    parts = [
        "".join(t.text or "" for t in p.iter(qn("w:t")))
        for p in tc.findall(qn("w:p"))
    ]
    # 单元格内的嵌套表格：文本并入单元格（结构不另立元素）
    for tbl in tc.findall(qn("w:tbl")):
        for tr in tbl.findall(qn("w:tr")):
            parts.append(" | ".join(
                "".join(t.text or "" for t in cell.iter(qn("w:t")))
                for cell in tr.findall(qn("w:tc"))
            ))
    return "\n".join(x for x in parts if x).strip()

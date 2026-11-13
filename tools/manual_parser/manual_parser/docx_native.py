from __future__ import annotations

import html
import mimetypes
import re
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from docx.document import Document as DocumentType
    from docx.table import Table
    from docx.text.paragraph import Paragraph

from .model import Block, Evidence

DRAWING_IMAGE_TAG = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
VML_IMAGE_TAG = "{urn:schemas-microsoft-com:vml}imagedata"
REL_EMBED_ATTRIBUTE = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
REL_ID_ATTRIBUTE = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
ALTERNATE_CONTENT_TAG = "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent"
CHOICE_TAG = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Choice"
FALLBACK_TAG = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


def _iter_blocks(document: DocumentType) -> Iterator[Paragraph | Table]:
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    def walk(parent) -> Iterator[Paragraph | Table]:
        for child in parent.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, document)
            elif child.tag == qn("w:tbl"):
                yield Table(child, document)
            elif child.tag in {qn("w:sdt"), qn("w:sdtContent"), qn("w:customXml")}:
                yield from walk(child)

    yield from walk(document.element.body)


def _xml_text(element: Any, *, exclude_text_boxes: bool = False) -> str:
    """Read field, hyperlink, and tracked-insertion text in XML order."""

    from docx.oxml.ns import qn

    parts: list[str] = []
    text_box_tag = qn("w:txbxContent")
    for node in element.iter():
        if exclude_text_boxes:
            parent = node.getparent()
            inside_text_box = False
            while parent is not None and parent is not element:
                if parent.tag == text_box_tag:
                    inside_text_box = True
                    break
                parent = parent.getparent()
            if inside_text_box:
                continue
        if node.tag == qn("w:t"):
            parts.append(node.text or "")
        elif node.tag == qn("w:tab"):
            parts.append("\t")
        elif node.tag in {qn("w:br"), qn("w:cr")}:
            parts.append("\n")
    value = "".join(parts)
    value = re.sub(r"[ \t]+\n", "\n", value)
    return value.strip()


def _toc_style_level(style: str) -> int | None:
    match = re.search(r"(?:^|\s)(?:TOC|目录)\s*([1-9])(?:\s|$)", style, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _toc_text_parts(text: str) -> tuple[str, str] | None:
    match = re.match(r"^(.{2,200}?)(?:\t+|[.．。·…]{2,}|\s{3,})\s*(\d{1,4}|[IVXLCDM]{1,8})\s*$", text, re.IGNORECASE)
    if not match:
        return None
    title = match.group(1).strip(" .．。·…\t")
    label = match.group(2)
    return title, label.upper() if label.isalpha() else label


def _heading_level(paragraph: Paragraph) -> int | None:
    from docx.oxml.ns import qn

    style = paragraph.style.name if paragraph.style else ""
    match = re.search(r"(?:Heading|标题)\s*([1-9])", style, re.IGNORECASE)
    if match:
        return int(match.group(1))
    outline = paragraph._p.pPr.find(qn("w:outlineLvl")) if paragraph._p.pPr is not None else None
    if outline is not None:
        try:
            return int(outline.get(qn("w:val"))) + 1
        except (TypeError, ValueError):
            pass
    return None


def _paragraph_shading(paragraph: Paragraph) -> str:
    from docx.oxml.ns import qn

    if paragraph._p.pPr is None:
        return ""
    shading = paragraph._p.pPr.find(qn("w:shd"))
    return (shading.get(qn("w:fill")) or "") if shading is not None else ""


def _image_relationship_ids(element: Any) -> list[str]:
    """Read DrawingML and VML image relationships without XPath prefix state."""

    relationship_ids: list[str] = []
    for node in element.iter():
        if node.tag == DRAWING_IMAGE_TAG:
            relationship_id = node.get(REL_EMBED_ATTRIBUTE)
        elif node.tag == VML_IMAGE_TAG:
            relationship_id = node.get(REL_ID_ATTRIBUTE)
        else:
            continue
        if relationship_id:
            relationship_ids.append(relationship_id)
    return relationship_ids


def _append_text_part(parts: list[dict[str, str]], value: str) -> None:
    if not value:
        return
    if parts and parts[-1]["type"] == "text":
        parts[-1]["text"] += value
    else:
        parts.append({"type": "text", "text": value})


def _inline_parts(element: Any) -> list[dict[str, str]]:
    """Preserve the text/image/text sequence inside a paragraph or table cell."""

    from docx.oxml.ns import qn

    parts: list[dict[str, str]] = []
    text_box_tag = qn("w:txbxContent")

    def walk(node: Any) -> None:
        for child in node.iterchildren():
            if child.tag == text_box_tag:
                continue
            if child.tag == qn("w:t"):
                _append_text_part(parts, child.text or "")
            elif child.tag == qn("w:tab"):
                _append_text_part(parts, "\t")
            elif child.tag in {qn("w:br"), qn("w:cr")}:
                _append_text_part(parts, "\n")
            elif child.tag == DRAWING_IMAGE_TAG:
                relationship_id = child.get(REL_EMBED_ATTRIBUTE)
                if relationship_id:
                    parts.append({"type": "image", "relationship_id": relationship_id})
            elif child.tag == VML_IMAGE_TAG:
                relationship_id = child.get(REL_ID_ATTRIBUTE)
                if relationship_id:
                    parts.append({"type": "image", "relationship_id": relationship_id})
            elif child.tag == ALTERNATE_CONTENT_TAG:
                choice = child.find(CHOICE_TAG)
                fallback = child.find(FALLBACK_TAG)
                selected = choice if choice is not None else fallback
                if selected is not None:
                    walk(selected)
            else:
                walk(child)

    walk(element)
    while parts and parts[0]["type"] == "text" and not parts[0]["text"]:
        parts.pop(0)
    while parts and parts[-1]["type"] == "text" and not parts[-1]["text"]:
        parts.pop()
    return parts


def _element_images(
    document: DocumentType,
    relationship_ids: list[str],
    assets_dir: Path,
    prefix: str,
    order: int,
    source_element_id: str,
) -> list[Block]:
    blocks: list[Block] = []
    for image_order, relationship_id in enumerate(relationship_ids):
        part = document.part.related_parts.get(relationship_id)
        blob = getattr(part, "blob", None)
        if not blob:
            continue
        content_type = getattr(part, "content_type", "application/octet-stream")
        part_name = PurePosixPath(str(getattr(part, "partname", "")))
        extension = part_name.suffix or mimetypes.guess_extension(content_type) or ".bin"
        safe_relationship_id = re.sub(r"[^0-9A-Za-z_-]", "_", relationship_id)
        name = f"docx-{safe_relationship_id}{extension}"
        asset_path = assets_dir / name
        if not asset_path.exists():
            asset_path.write_bytes(blob)
        display_path = asset_path
        converted_from = ""
        if extension.lower() in {".wmf", ".emf"}:
            try:
                from .office import _run_soffice

                display_path = _run_soffice(asset_path, assets_dir, "png")
                converted_from = extension.lower()
            except Exception:  # noqa: BLE001 - the original vector asset remains available for download
                display_path = asset_path
        blocks.append(
            Block(
                id=f"ooxml-figure-{order}-{image_order}",
                type="figure",
                reading_order=order,
                region_image=f"{prefix}/{display_path.name}",
                attributes={
                    "content_type": content_type,
                    "source_part_name": str(part_name),
                    "display_conversion": f"{converted_from}->png" if converted_from else "",
                    "relationship_id": relationship_id,
                    "source_element_id": source_element_id,
                    "source_reference_index": image_order,
                },
                evidence=[Evidence("ooxml", relationship_id, 1.0, "DOCX embedded image relationship")],
            )
        )
    return blocks


def _materialize_parts(parts: list[dict[str, str]], images: list[Block]) -> list[dict[str, Any]]:
    images_by_relationship: dict[str, list[Block]] = {}
    for image in images:
        images_by_relationship.setdefault(str(image.attributes.get("relationship_id", "")), []).append(image)
    output: list[dict[str, Any]] = []
    for part in parts:
        if part["type"] == "text":
            output.append({"type": "text", "text": part.get("text", "")})
            continue
        relationship_id = part.get("relationship_id", "")
        candidates = images_by_relationship.get(relationship_id, [])
        image = candidates.pop(0) if candidates else None
        if image is None:
            output.append({"type": "image", "relationship_id": relationship_id, "missing_asset": True})
            continue
        output.append(
            {
                "type": "image",
                "figure_id": image.id,
                "relationship_id": relationship_id,
                "asset": image.region_image,
            }
        )
    return output


def _text_boxes(paragraph: Paragraph) -> list[str]:
    """Read DrawingML/VML text boxes that Paragraph.text intentionally omits."""
    from docx.oxml.ns import qn

    values: list[str] = []
    seen: set[str] = set()
    for box in paragraph._element.xpath(".//w:txbxContent"):
        lines = []
        for item in box.iter(qn("w:p")):
            line = "".join(node.text or "" for node in item.iter(qn("w:t"))).strip()
            if line:
                lines.append(line)
        text = "\n".join(lines).strip()
        # Word commonly stores identical DrawingML and VML fallback copies.
        if text and text not in seen:
            seen.add(text)
            values.append(text)
    return values


def _cell_property(tc: Any, name: str) -> str:
    from docx.oxml.ns import qn

    tc_pr = tc.tcPr
    node = tc_pr.find(qn(f"w:{name}")) if tc_pr is not None else None
    return (node.get(qn("w:val")) or "continue") if node is not None else ""


def _table_html(table: Table) -> tuple[str, str, dict]:
    from docx.oxml.ns import qn
    from docx.table import _Cell

    rows: list[list[dict]] = []
    vertical: dict[int, dict] = {}
    plain_rows: list[list[str]] = []
    shading_values: set[str] = set()
    cells: list[dict[str, Any]] = []
    for row_index, row in enumerate(table.rows):
        output_row: list[dict] = []
        plain_row: list[str] = []
        column = 0
        for tc in row._tr.tc_lst:
            cell = _Cell(tc, table)
            shading = tc.tcPr.find(qn("w:shd")) if tc.tcPr is not None else None
            if shading is not None and shading.get(qn("w:fill")):
                shading_values.add(shading.get(qn("w:fill")))
            text = "\n".join(
                value
                for value in (_xml_text(paragraph) for paragraph in tc.iter(qn("w:p")))
                if value
            )
            try:
                colspan = max(1, int(_cell_property(tc, "gridSpan") or "1"))
            except ValueError:
                colspan = 1
            vertical_merge = _cell_property(tc, "vMerge")
            if vertical_merge and vertical_merge != "restart" and column in vertical:
                vertical[column]["rowspan"] += 1
                plain_row.extend([text] * colspan)
                column += colspan
                continue
            inline_parts = _inline_parts(tc)
            record = {
                "row": row_index,
                "column": column,
                "text": text,
                "colspan": colspan,
                "rowspan": 1,
                "parts": inline_parts if any(part["type"] == "image" for part in inline_parts) else [],
                "relationship_ids": [part["relationship_id"] for part in inline_parts if part["type"] == "image"],
                "figure_ids": [],
                "images": [],
            }
            output_row.append(record)
            cells.append(record)
            plain_row.extend([text] * colspan)
            if vertical_merge == "restart":
                for offset in range(colspan):
                    vertical[column + offset] = record
            else:
                for offset in range(colspan):
                    vertical.pop(column + offset, None)
            column += colspan
        rows.append(output_row)
        plain_rows.append(plain_row)
    parts = ["<table>"]
    for row in rows:
        parts.append("<tr>")
        for cell in row:
            attrs = []
            if cell["colspan"] > 1:
                attrs.append(f' colspan="{cell["colspan"]}"')
            if cell["rowspan"] > 1:
                attrs.append(f' rowspan="{cell["rowspan"]}"')
            parts.append(f"<td{''.join(attrs)}>{html.escape(cell['text']).replace(chr(10), '<br>')}</td>")
        parts.append("</tr>")
    parts.append("</table>")
    text = "\n".join(" | ".join(value for value in row if value) for row in plain_rows if any(row))
    attributes = {
        "rows": len(rows),
        "columns": max((sum(cell["colspan"] for cell in row) for row in rows), default=0),
        "has_merged_cells": any(cell["colspan"] > 1 or cell["rowspan"] > 1 for row in rows for cell in row),
        "shading_values": sorted(shading_values),
        "cells": cells,
    }
    return "".join(parts), text, attributes


def parse_docx(path: Path, assets_dir: Path, asset_url_prefix: str) -> list[Block]:
    from docx import Document
    from docx.text.paragraph import Paragraph

    document = Document(str(path))
    assets_dir.mkdir(parents=True, exist_ok=True)
    blocks: list[Block] = []
    order = 0
    for source_index, item in enumerate(_iter_blocks(document)):
        if isinstance(item, Paragraph):
            text = _xml_text(item._p, exclude_text_boxes=True)
            inline_parts = _inline_parts(item._p)
            relationship_ids = [part["relationship_id"] for part in inline_parts if part["type"] == "image"]
            images: list[Block] = []
            level = _heading_level(item)
            style = item.style.name if item.style else ""
            toc_level = _toc_style_level(style)
            source_element_id = f"paragraph:{source_index}"
            if text or relationship_ids:
                toc = _toc_text_parts(text) if toc_level else None
                block_type = "toc_entry" if toc else "caption" if re.search(r"Caption|题注", style, re.IGNORECASE) else "heading" if level else "paragraph"
                shading = _paragraph_shading(item)
                num_pr = item._p.pPr.numPr if item._p.pPr is not None else None
                native_list = bool(num_pr is not None and not toc)
                native_list_level = int(num_pr.ilvl.val) if native_list and num_pr.ilvl is not None else 0
                native_list_id = str(num_pr.numId.val) if native_list and num_pr.numId is not None else ""
                attributes = {
                    "style": style,
                    "shading": shading,
                    "is_list": native_list,
                    "native_list_level": native_list_level,
                    "native_list_id": native_list_id,
                    "source_element_id": source_element_id,
                    "has_inline_images": bool(relationship_ids),
                }
                if toc:
                    text = f"{toc[0]} …… {toc[1]}"
                    attributes.update(
                        {
                            "toc_title": toc[0],
                            "target_page_label": toc[1],
                            "toc_level": toc_level,
                            "toc_page": True,
                            "search_role": "navigation",
                            "qa_eligible": False,
                        }
                    )
                paragraph_id = f"ooxml-{order}"
                images = _element_images(
                    document,
                    relationship_ids,
                    assets_dir,
                    asset_url_prefix,
                    order + 1,
                    source_element_id,
                )
                materialized_parts = _materialize_parts(inline_parts, images) if relationship_ids else []
                blocks.append(
                    Block(
                        id=paragraph_id,
                        type=block_type,
                        text=text,
                        parts=materialized_parts,
                        level=toc_level if toc else level,
                        reading_order=order,
                        attributes=attributes,
                        evidence=[Evidence("ooxml", source_element_id, 1.0, "DOCX native paragraph")],
                    )
                )
                order += 1
            else:
                paragraph_id = ""
            for text_box_order, text_box in enumerate(_text_boxes(item)):
                blocks.append(
                    Block(
                        id=f"ooxml-textbox-{order}-{text_box_order}",
                        type="paragraph",
                        text=text_box,
                        reading_order=order,
                        attributes={"native_container": "text_box"},
                        evidence=[Evidence("ooxml", f"textbox:{order}:{text_box_order}", 1.0, "DOCX native text box")],
                    )
                )
                order += 1
            for image in images:
                if paragraph_id:
                    image.attributes.update(
                        {
                            "source_paragraph_id": paragraph_id,
                            "source_parent_id": paragraph_id,
                            "inline": True,
                        }
                    )
                    image.parent_id = paragraph_id
                image.reading_order = order
                order += 1
            blocks.extend(images)
        else:
            table_html, text, attributes = _table_html(item)
            table_id = f"ooxml-table-{order}"
            source_element_id = f"table:{source_index}"
            attributes["source_element_id"] = source_element_id
            table_images: list[Block] = []
            next_image_order = order + 1
            for cell in attributes["cells"]:
                relationship_ids = list(cell.pop("relationship_ids"))
                if not relationship_ids:
                    continue
                cell_id = f"{source_element_id}:r{cell['row']}:c{cell['column']}"
                cell_images = _element_images(
                    document,
                    relationship_ids,
                    assets_dir,
                    asset_url_prefix,
                    next_image_order,
                    cell_id,
                )
                for image in cell_images:
                    image.attributes.update(
                        {
                            "source_table_id": table_id,
                            "source_parent_id": table_id,
                            "source_row": cell["row"],
                            "source_column": cell["column"],
                            "source_cell_id": cell_id,
                        }
                    )
                    image.parent_id = table_id
                cell["parts"] = _materialize_parts(cell["parts"], cell_images)
                cell["figure_ids"] = [image.id for image in cell_images]
                cell["images"] = [image.region_image for image in cell_images]
                table_images.extend(cell_images)
                next_image_order += len(cell_images)
            attributes["contains_image"] = bool(table_images)
            attributes["cell_images"] = [
                {
                    "row": cell["row"],
                    "column": cell["column"],
                    "figure_ids": cell["figure_ids"],
                    "images": cell["images"],
                }
                for cell in attributes["cells"]
                if cell["figure_ids"]
            ]
            blocks.append(
                Block(
                    id=table_id,
                    type="table",
                    text=text,
                    html=table_html,
                    reading_order=order,
                    attributes=attributes,
                    evidence=[Evidence("ooxml", source_element_id, 1.0, "DOCX native table grid, merge, and cell media")],
                )
            )
            order += 1
            for image in table_images:
                image.reading_order = order
                blocks.append(image)
                order += 1
    return blocks

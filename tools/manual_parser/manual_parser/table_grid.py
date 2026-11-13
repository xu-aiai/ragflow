from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
from typing import Any


@dataclass
class _Cell:
    text: str
    row: int
    column: int
    rowspan: int
    colspan: int
    header: bool


@dataclass
class _ParsedTable:
    rows: list[list[_Cell]] = field(default_factory=list)
    caption: str = ""


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.table = _ParsedTable()
        self._row: list[_Cell] | None = None
        self._cell_parts: list[str] | None = None
        self._cell_attrs: dict[str, str] = {}
        self._cell_header = False
        self._caption_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []
            self._cell_attrs = {key.lower(): value or "" for key, value in attrs}
            self._cell_header = tag == "th"
        elif tag == "br" and self._cell_parts is not None:
            self._cell_parts.append("\n")
        elif tag == "caption":
            self._caption_parts = []

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)
        elif self._caption_parts is not None:
            self._caption_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._row is not None and self._cell_parts is not None:
            rowspan = _positive_int(self._cell_attrs.get("rowspan"), 1)
            colspan = _positive_int(self._cell_attrs.get("colspan"), 1)
            text = _clean("".join(self._cell_parts))
            self._row.append(_Cell(text, -1, -1, rowspan, colspan, self._cell_header))
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.table.rows.append(self._row)
            self._row = None
        elif tag == "caption" and self._caption_parts is not None:
            self.table.caption = _clean("".join(self._caption_parts))
            self._caption_parts = None


def _positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        return default
    return max(1, min(parsed, 100))


def _clean(value: str) -> str:
    value = value.replace("\u3000", " ").replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    return re.sub(r" *\n *", "\n", value).strip()


def parse_table_grid(html_text: str) -> dict[str, Any]:
    """Convert table HTML into a span-aware grid without guessing missing values."""
    parser = _TableParser()
    parser.feed(html_text or "")
    parser.close()
    occupied: dict[tuple[int, int], dict[str, Any]] = {}
    origins: list[dict[str, Any]] = []
    max_column = 0
    for row_index, source_row in enumerate(parser.table.rows):
        column = 0
        for source in source_row:
            while (row_index, column) in occupied:
                column += 1
            cell_id = f"r{row_index}c{column}"
            origin = {
                "id": cell_id,
                "row": row_index,
                "column": column,
                "rowspan": source.rowspan,
                "colspan": source.colspan,
                "header": source.header,
                "text": source.text,
            }
            origins.append(origin)
            for row_offset in range(source.rowspan):
                for column_offset in range(source.colspan):
                    key = (row_index + row_offset, column + column_offset)
                    occupied[key] = origin if not row_offset and not column_offset else {"ref": cell_id}
            column += source.colspan
            max_column = max(max_column, column)
    row_count = max((row for row, _column in occupied), default=-1) + 1
    column_count = max(max_column, max((column for _row, column in occupied), default=-1) + 1)
    grid = [[occupied.get((row, column)) for column in range(column_count)] for row in range(row_count)]
    return {
        "row_count": row_count,
        "column_count": column_count,
        "caption": parser.table.caption,
        "cells": origins,
        "grid": grid,
        "header_cell_ids": [cell["id"] for cell in origins if cell["header"]],
    }


def _numeric_parts(value: str) -> list[str]:
    normalized = value.replace("，", ",").strip()
    if not normalized or re.search(r"[A-Za-z\u4e00-\u9fff]", normalized):
        return []
    return re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?(?:\s*[–—~-]\s*\d+(?:,\d{3})*(?:\.\d+)?)?", normalized)


def repair_numeric_alignment(grid: dict[str, Any]) -> list[str]:
    """Repair only token-conserving numeric alignment failures in-place."""

    cells = [cell for cell in grid.get("cells", []) if int(cell.get("rowspan", 1)) == 1 and int(cell.get("colspan", 1)) == 1]
    by_position = {(int(cell["row"]), int(cell["column"])): cell for cell in cells}
    row_count = int(grid.get("row_count", 0))
    column_count = int(grid.get("column_count", 0))
    repairs: list[str] = []
    if column_count == 2:
        for row_index in range(row_count - 1):
            row = [by_position.get((row_index, column)) for column in range(2)]
            following = [by_position.get((row_index + 1, column)) for column in range(2)]
            if any(cell is None for cell in [*row, *following]):
                continue
            left, right = _numeric_parts(str(row[0]["text"])), _numeric_parts(str(row[1]["text"]))
            next_left, next_right = _numeric_parts(str(following[0]["text"])), _numeric_parts(str(following[1]["text"]))
            if len(left) == 1 and len(right) == 2 and len(next_left) == 1 and not str(following[1]["text"]).strip():
                row[1]["text"], following[1]["text"] = right[0], right[1]
                repairs.append(f"rows:{row_index}-{row_index + 1}:right-column")
            elif len(left) == 2 and len(right) == 1 and not str(following[0]["text"]).strip() and len(next_right) == 1:
                row[0]["text"], following[0]["text"] = left[0], left[1]
                repairs.append(f"rows:{row_index}-{row_index + 1}:left-column")
    for row_index in range(row_count):
        for column in range(column_count - 1):
            left = by_position.get((row_index, column))
            right = by_position.get((row_index, column + 1))
            if not left or not right:
                continue
            suffix = re.fullmatch(r"(.*?)\s+(\d{1,3},)\s*", str(left.get("text", "")))
            following_range = re.fullmatch(r"(\d{3}\s*[–—~-]\s*\d{1,3},\d{3})", str(right.get("text", "")).strip())
            if suffix and suffix.group(1).strip() and following_range:
                left["text"] = suffix.group(1).strip()
                right["text"] = suffix.group(2) + following_range.group(1)
                repairs.append(f"row:{row_index}:thousands-separator")
    return repairs


def table_grid_to_html(grid: dict[str, Any]) -> str:
    rows: list[str] = []
    row_count = int(grid.get("row_count", 0))
    cells = list(grid.get("cells", []))
    for row_index in range(row_count):
        row_cells = sorted((cell for cell in cells if int(cell.get("row", -1)) == row_index), key=lambda cell: int(cell.get("column", 0)))
        parts: list[str] = []
        for cell in row_cells:
            tag = "th" if cell.get("header") else "td"
            attrs = ""
            if int(cell.get("rowspan", 1)) > 1:
                attrs += f' rowspan="{int(cell["rowspan"])}"'
            if int(cell.get("colspan", 1)) > 1:
                attrs += f' colspan="{int(cell["colspan"])}"'
            parts.append(f"<{tag}{attrs}>{escape(str(cell.get('text', '')))}</{tag}>")
        if parts:
            rows.append("<tr>" + "".join(parts) + "</tr>")
    caption = str(grid.get("caption", "")).strip()
    caption_html = f"<caption>{escape(caption)}</caption>" if caption else ""
    return "<table>" + caption_html + "".join(rows) + "</table>"


def assess_table_integrity(grid: dict[str, Any], source_type: str, intent: str) -> tuple[str, list[str]]:
    """Return a conservative status: verified, review_required, or unsafe."""
    cells = grid.get("cells", [])
    rows = int(grid.get("row_count", 0))
    columns = int(grid.get("column_count", 0))
    reasons: list[str] = []
    if rows == 0 or columns == 0 or not cells:
        return "unsafe", ["没有可验证的单元格网格"]
    empty_ratio = sum(not cell.get("text") for cell in cells) / len(cells)
    if columns >= 2 and empty_ratio >= 0.45:
        reasons.append("空单元格比例过高")
    if rows >= 3 and columns >= 2:
        numeric_rows = 0
        suspicious_rows = 0
        by_row: dict[int, list[dict[str, Any]]] = {}
        for cell in cells:
            by_row.setdefault(int(cell["row"]), []).append(cell)
        candidate_rows = [values for row, values in sorted(by_row.items()) if row > 0 and any(cell.get("text") for cell in values)]
        # Compare numeric data rows with one another.  Unit/header rows such as
        # ``mm | mm | Nm | kgm`` legitimately contain zero numbers and must not
        # be interpreted as a sudden loss of four numeric cells.
        first_data_row = next(
            (
                index
                for index, values in enumerate(candidate_rows)
                if sum(bool(re.search(r"\d", str(cell.get("text", "")))) for cell in values) >= 2
            ),
            len(candidate_rows),
        )
        data_rows = candidate_rows[first_data_row:]
        occupancy: list[int] = []
        numeric_counts: list[int] = []
        for row_cells in data_rows:
            values = [str(cell.get("text", "")) for cell in row_cells]
            numeric_cells = sum(bool(re.search(r"\d", value)) for value in values)
            occupancy.append(sum(int(cell.get("colspan", 1)) for cell in row_cells if cell.get("text")))
            numeric_counts.append(numeric_cells)
            numeric_rows += numeric_cells >= 2
            suspicious_rows += numeric_cells >= 3 and len(values) < columns
        if numeric_rows >= 2 and suspicious_rows:
            reasons.append("数值行的单元格数量不稳定，可能发生串行或错位")
        if len(occupancy) >= 2 and max(occupancy) - min(occupancy) >= 2:
            reasons.append("相邻数据行的非空列数量突变，可能有内容被挤入上一行")
        if len(numeric_counts) >= 2 and max(numeric_counts) - min(numeric_counts) >= 2:
            reasons.append("相邻数据行的数值数量突变，数值对应关系可能错位")
    verified_sources = {"ooxml", "docx", "word", "pdf_native_table"}
    if intent == "data_table" and source_type not in verified_sources:
        reasons.append("数据表来自视觉解析，数值对应关系尚未由原生结构校验")
    if any("可能" in reason for reason in reasons) or (empty_ratio >= 0.65 and intent == "data_table"):
        return "unsafe", reasons
    if reasons:
        return "review_required", reasons
    if source_type in verified_sources:
        return "verified", []
    return "review_required", ["视觉解析表格需人工抽查数值对应关系"]

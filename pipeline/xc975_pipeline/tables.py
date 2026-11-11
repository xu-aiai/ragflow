"""阶段 3：表格分类（树块规整与 B1/C 抽取的共同枢纽，规格 §6.2）。"""
from __future__ import annotations

_WARNING_WORDS = ("注意", "警告", "危险", "achtung", "warning", "caution", "attention")


def _norm(s: str) -> str:
    return (s or "").strip().lower()


TABLE_KINDS = ("warning", "fault_code", "period", "layout", "data")


def classify_table(grid: list[list[str]], section_number: str | None = None) -> str:
    """返回 warning / fault_code / period / layout / data 之一。"""
    return classify_table_detailed(grid, section_number)[0]


def classify_table_detailed(grid: list[list[str]], section_number: str | None = None) -> tuple[str, str]:
    """返回 (分类, 判定依据)，依据供工作台展示与人工复核。"""
    if not grid or not grid[0]:
        return "layout", "空表格，按排版容器处理"
    first = next((c for row in grid for c in row if (c or "").strip()), "")
    n_cols = max(len(r) for r in grid)
    if _norm(first) and any(_norm(first).startswith(w) for w in _WARNING_WORDS) and n_cols <= 2:
        return "warning", f"首格以警告词开头（{_trunc(first)}）且列数 ≤ 2"
    if len(grid) == 1 or n_cols == 1:
        return "layout", "单行或单列，判定为排版容器"
    header = [(c or "").strip() for c in grid[0]]
    has_code = any("代码" in c or c == "码" for c in header)
    has_name = any("名称" in c for c in header)
    if has_code and has_name:
        return "fault_code", "表头同时含代码列与名称列"
    if section_number:
        if section_number.startswith("3.10"):
            return "fault_code", f"位于故障码章节 {section_number}"
        if section_number.startswith("3.3"):
            return "period", f"位于保养周期章节 {section_number}"
    if any((c or "").strip().startswith("●") for row in grid for c in row):
        return "period", "单元格含 ● 周期标记"
    return "data", "未命中专门规则，按通用数据表处理"


def _trunc(s: str, n: int = 12) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"

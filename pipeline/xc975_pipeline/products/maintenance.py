"""阶段 5c：C 保养周期规则（规格 §3.C，第一批仅周期规则，确定性）。

真实形态（A 手册实测）：
- 周期小节标题自带周期："每250小时/每月维护保养" → interval 250h + 日历"每月"；
- 小节下的 ● 段落清单逐条即规则；清单里可能混有累积短语（"同时进行每10、50、100小时…"）；
- 首保语句 "对于第一个250小时，还需进行："——项目在冒号后同行或后续 ● 清单；
- B/C 手册若为表格形态（表头含周期列），仍按表格解析。
匹配不上的内容进审核清单，不猜。
"""
from __future__ import annotations

import re

from ..schemas import MaintenanceRule

_PERIOD_TITLE_RE = re.compile(r"每(\d+)\s*小时(?:\s*/\s*(每[^/\s]*?))?\s*(?:的\s*)?(?:维护保养|保养)")
_ACCUM_RE = re.compile(r"同时进行每([\d、,，\s]+?)小时")
_FIRST_RE = re.compile(r"第\s*一\s*个\s*(\d+)\s*小时[^\d]*?还需进行[:：]?(.*)")
_INTERVAL_RE = re.compile(r"(\d+)\s*(?:小时|h|H)")
_BULLET_RE = re.compile(r"^[●○·◆■□▲△]\s*")


def extract_rules(elements, doc_code: str, variant: str, audit) -> list[MaintenanceRule]:
    rules: list[MaintenanceRule] = []
    counters: dict[str, int] = {}
    section: tuple[str | None, str] | None = None
    period_hours: int | None = None
    period_calendar: str | None = None
    accum_hours: list[int] = []
    section_rules: list[MaintenanceRule] = []
    first_pending: int | None = None

    def flush_section():
        if accum_hours and section_rules:
            top = max(accum_hours)
            for r in section_rules:
                hours = r.触发.get("小时")
                if r.触发.get("类型") == "interval" and hours and hours > top:
                    r.累积 = [f"M-{h}-*" for h in accum_hours]

    def next_id(hours: int, first: bool = False) -> str:
        key = f"{hours}-FIRST" if first else str(hours)
        counters[key] = counters.get(key, 0) + 1
        return f"M-{key}-{counters[key]:02d}"

    def emit(hours: int, item: str, first: bool = False, src: int | None = None) -> None:
        r = MaintenanceRule(
            rule_id=next_id(hours, first),
            适用变体=variant,
            触发=({"类型": "one_time_first_cycle", "小时": hours} if first
                  else {"类型": "interval", "小时": hours, "日历": period_calendar, "关系": "先到为准"}),
            内容=item,
            来源=[f"{doc_code}-{section[0]}"] if section and section[0] else [],
            src=[src] if src is not None else [],
        )
        rules.append(r)
        section_rules.append(r)

    for el in elements:
        if el.kind == "para" and el.heading_level is not None:
            flush_section()
            section = (el.编号, (el.para.text or "").strip())
            m = _PERIOD_TITLE_RE.search(section[1])
            period_hours = int(m.group(1)) if m else None
            period_calendar = m.group(2) if m else None
            accum_hours, section_rules = [], []
            first_pending = None
            continue
        if section is None:
            continue
        if el.kind == "table":
            if el.table is not None and period_hours:
                _parse_period_table(el.table.grid, section, doc_code, variant, audit, next_id, rules, section_rules, el.index)
            continue
        text = (el.para.text or "").strip()
        if not text:
            continue
        m = _ACCUM_RE.search(text)
        if m:
            accum_hours = [int(x) for x in re.findall(r"\d+", m.group(1))]
            continue
        m = _FIRST_RE.search(text)
        if m:
            hours = int(m.group(1))
            inline = [x.strip() for x in re.split(r"[、,，;；]", m.group(2)) if x.strip()]
            if inline:
                for item in inline:
                    emit(hours, item, first=True, src=el.index)
                first_pending = None
            else:
                first_pending = hours
            continue
        if _BULLET_RE.match(text):
            item = _BULLET_RE.sub("", text).strip()
            if first_pending is not None:
                emit(first_pending, item, first=True, src=el.index)
            elif period_hours is not None:
                emit(period_hours, item, src=el.index)
            continue
        first_pending = None  # 普通段落结束首保收集
    flush_section()
    return rules


def _parse_period_table(grid, section, doc_code, variant, audit, next_id, rules, section_rules, src):
    """表格形态的周期表（B/C 手册）：行=项目、列=周期（表头含 "N小时"）。"""
    header = [(c or "").strip() for c in grid[0]]
    hour_cols: dict[int, int] = {}
    for i, cell in enumerate(header):
        m = _INTERVAL_RE.search(cell)
        if m:
            hour_cols[i] = int(m.group(1))
    if not hour_cols:
        audit.add("保养", f"{section[0]} 周期表表头无周期列：{header[:4]}", section[0])
        return
    for row in grid[1:]:
        cells = [(c or "").strip() for c in row]
        item = cells[0] if cells else ""
        if not item or item.startswith("●"):
            continue
        for col, hours in hour_cols.items():
            if col < len(cells) and cells[col].startswith("●"):
                r = MaintenanceRule(
                    rule_id=next_id(hours),
                    适用变体=variant,
                    触发={"类型": "interval", "小时": hours},
                    内容=item,
                    来源=[f"{doc_code}-{section[0]}"] if section[0] else [],
                    src=[src],
                )
                rules.append(r)
                section_rules.append(r)

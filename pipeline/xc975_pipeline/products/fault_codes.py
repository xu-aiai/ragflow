"""阶段 5b：B1 故障码注册表（规格 §3.B1）。

定位 3.10.x（A）/ 1.8.2（B）下分类为 fault_code 的表。网格已在阶段 1 展开
vMerge（续行前向填充）；同一故障多等级行折叠为一条（取最高等级，进审核）；
空解决措施打"待审"标。
"""
from __future__ import annotations

from ..schemas import FaultCode
from ..tables import classify_table

_HEADER_MAP = {
    "代码": "代码", "码": "代码", "故障代码": "代码", "序号": "代码",
    "故障名称": "故障名称", "名称": "故障名称",
    "触发条件": "触发条件", "故障原因": "触发条件", "触发": "触发条件",
    "故障等级": "故障等级", "等级": "故障等级",
    "解决措施": "解决措施", "措施": "解决措施", "处理方法": "解决措施", "排除方法": "解决措施",
}


def _map_header(cell: str) -> str | None:
    """表头映射：先精确后包含（真实表头有"故障触发条件""故障处理方法"等变体）。"""
    c = (cell or "").strip()
    if not c:
        return None
    if c in _HEADER_MAP:
        return _HEADER_MAP[c]
    for key, val in _HEADER_MAP.items():
        if key in c:
            return val
    return None

_KNOWN_CONTROLLERS = ["行走电控", "液压电控", "水冷机组", "动力电池", "多合一"]

# code_id 前缀（规格示例 WL-027）；除行走电控外的前缀待确认，未定用控制器名兜底
_CONTROLLER_PREFIX = {"行走电控": "WL"}


def _to_int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _controller_from_title(title: str) -> str | None:
    for name in _KNOWN_CONTROLLERS:
        if name in title:
            return name
    return None


def extract_fault_codes(elements, doc_code: str, variant: str, audit) -> list[FaultCode]:
    codes: dict[tuple[str, int], FaultCode] = {}
    order: list[tuple[str, int]] = []
    section: tuple[str | None, str] | None = None
    for el in elements:
        if el.kind == "para" and el.heading_level is not None:
            section = (el.编号, (el.para.text or "").strip())
            continue
        if el.kind != "table" or el.table is None or section is None:
            continue
        if (el.forced_kind or classify_table(el.table.grid, section[0])) != "fault_code":
            continue
        controller = _controller_from_title(section[1]) or section[1]
        prefix = _CONTROLLER_PREFIX.get(controller)
        grid = el.table.grid
        header = [_map_header(c) for c in grid[0]]
        if "代码" not in header or "故障名称" not in header:
            audit.add("故障码", f"{section[0]} 表头无法映射：{grid[0]}", section[0])
            continue
        if prefix is None:
            audit.add("故障码", f"控制器 {controller} 的 code_id 前缀未定，用控制器名兜底", section[0])
        for row in grid[1:]:
            rec = {h: row[i] for i, h in enumerate(header) if h is not None and i < len(row)}
            code_num = _to_int(rec.get("代码"))
            if code_num is None:
                if (rec.get("代码") or "").strip():
                    audit.add("故障码", f"代码非数字：{rec.get('代码')!r}", section[0])
                continue
            key = (controller, code_num)
            level = _to_int(rec.get("故障等级"))
            if key in codes:
                if level is not None and (codes[key].故障等级 is None or level > codes[key].故障等级):
                    codes[key].故障等级 = level
                audit.add("故障码", f"{controller} 代码 {code_num} 同码多等级行，折叠取最高", section[0])
                continue
            measure = (rec.get("解决措施") or "").strip() or None
            cid = f"{prefix}-{code_num:03d}" if prefix else f"{controller}-{code_num:03d}"
            codes[key] = FaultCode(
                code_id=cid,
                控制器=controller,
                代码=str(code_num),
                故障名称=(rec.get("故障名称") or "").strip() or f"未命名{code_num}",
                触发条件=(rec.get("触发条件") or "").strip() or None,
                故障等级=level,
                解决措施=measure,
                适用变体=variant,
                来源=[f"{doc_code}-{section[0]}"] if section[0] else [],
                src=[el.index],
                审核标记=None if measure else "待审-空措施",
            )
            order.append(key)
    return [codes[k] for k in order]

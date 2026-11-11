from xc975_pipeline.audit import AuditLog
from xc975_pipeline.docmodel import parse_docx
from xc975_pipeline.numbering import inject_numbers
from xc975_pipeline.products.fault_codes import extract_fault_codes


def test_extract_fault_codes(manual_a):
    elements, _ = parse_docx(str(manual_a))
    inject_numbers(elements, "auto")
    audit = AuditLog()
    codes = extract_fault_codes(elements, "A", "国内干桥", audit)
    assert len(codes) == 3
    c27 = next(c for c in codes if c.代码 == "27")
    assert c27.code_id == "WL-027"
    assert c27.控制器 == "行走电控"
    assert c27.故障名称 == "堵转保护"
    assert c27.故障等级 == 3
    assert c27.解决措施 == "停车，不可长时间低速大扭矩使用电机。"
    assert c27.审核标记 is None
    assert c27.来源 == ["A-3.10.1"]
    assert c27.适用变体 == "国内干桥"
    c28 = next(c for c in codes if c.代码 == "28")
    assert c28.审核标记 == "待审-空措施"
    c101 = next(c for c in codes if c.代码 == "101")
    assert c101.code_id == "WL-101"
    assert c101.触发条件 == "预充超时"                      # 子串表头映射（"故障触发条件"）
    assert any("多等级" in e["说明"] for e in audit.entries)

from xc975_pipeline.audit import AuditLog
from xc975_pipeline.docmodel import parse_docx
from xc975_pipeline.numbering import inject_numbers
from xc975_pipeline.products.maintenance import extract_rules


def test_extract_rules(manual_a):
    elements, _ = parse_docx(str(manual_a))
    inject_numbers(elements, "auto")
    audit = AuditLog()
    rules = extract_rules(elements, "A", "国内干桥", audit)
    by_id = {r.rule_id: r for r in rules}
    assert by_id["M-100-01"].内容 == "检查电池组电压状态"
    assert by_id["M-250-01"].内容 == "检查电池组电压状态"
    assert by_id["M-500-01"].内容 == "检查电池组电压状态"
    assert by_id["M-250-02"].内容 == "更换前后桥轮毂油"
    assert by_id["M-250-03"].内容 == "更换液压油箱呼吸器滤芯"
    # 累积：本节高周期规则引用低周期
    assert by_id["M-250-01"].累积 == ["M-10-*", "M-50-*", "M-100-*"]
    assert by_id["M-500-01"].累积 == ["M-10-*", "M-50-*", "M-100-*"]
    assert by_id["M-100-01"].累积 == []
    assert by_id["M-250-01"].来源 == ["A-3.3.5"]
    assert elements[by_id["M-250-01"].src[0]].kind == "table"  # 溯源指向周期表元素
    # 段落清单形态（真实 A 手册形态）
    assert by_id["M-250-04"].内容 == "检查电池组电压状态。"
    assert by_id["M-250-04"].累积 == ["M-10-*", "M-50-*", "M-100-*"]
    assert by_id["M-250-04"].触发["关系"] == "先到为准"
    # 首保
    first = [r for r in rules if r.触发["类型"] == "one_time_first_cycle"]
    assert [r.rule_id for r in first] == ["M-250-FIRST-01", "M-250-FIRST-02"]
    assert first[0].内容 == "更换前后桥轮毂油"
    assert first[1].内容 == "更换液压油箱呼吸器滤芯"
    assert first[0].来源 == ["A-3.3.5"]
    assert elements[first[0].src[0]].para.text.startswith("对于第一个250小时")
    assert len(rules) == 9

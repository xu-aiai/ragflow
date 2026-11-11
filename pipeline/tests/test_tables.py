from xc975_pipeline.docmodel import parse_docx
from xc975_pipeline.tables import classify_table, classify_table_detailed


def test_classify_warning():
    assert classify_table([["警告"], ["机器起动不了"]]) == "warning"
    assert classify_table([["Achtung!"], ["Hochspannung"]]) == "warning"


def test_classify_fault_code():
    grid = [["代码", "故障名称", "触发条件", "故障等级", "解决措施"], ["27", "堵转保护", "x", "3", "y"]]
    assert classify_table(grid) == "fault_code"


def test_classify_period():
    grid = [["保养项目", "每100小时", "每250小时"], ["检查电池", "●", "●"]]
    assert classify_table(grid) == "period"


def test_classify_layout():
    assert classify_table([["只有一行"]]) == "layout"
    assert classify_table([["a"], ["b"]]) == "layout"


def test_classify_detailed_reason():
    kind, reason = classify_table_detailed([["警告"], ["机器起动不了"]])
    assert kind == "warning" and "警告词" in reason
    kind, reason = classify_table_detailed([["代码", "故障名称"], ["27", "堵转保护"]])
    assert kind == "fault_code" and "表头" in reason
    kind, reason = classify_table_detailed([["a", "b"], ["c", "d"]], "3.10.1")
    assert kind == "fault_code" and "3.10.1" in reason
    kind, reason = classify_table_detailed([["a", "b"], ["c", "d"]])
    assert kind == "data" and reason


def test_vmerge_forward_fill(manual_a):
    elements, _ = parse_docx(str(manual_a))
    grids = [el.table.grid for el in elements if el.kind == "table"]
    fault = grids[-2]  # 倒数第二张是 vMerge 故障码表（最后一张是序号表头表）
    assert fault[2][1] == "堵转保护"
    assert fault[2][2] == "转速小于20，力矩大于2800，持续30秒"
    assert fault[2][4] == "停车，不可长时间低速大扭矩使用电机。"
    assert fault[3][4] == ""

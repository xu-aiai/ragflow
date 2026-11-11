import base64
import sys
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _tiny_png(color) -> bytes:
    """生成另一张小图（同字节图片会被 python-docx 复用同一部件，测不出独立提取）。"""
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (2, 2), color).save(buf, format="PNG")
    return buf.getvalue()


def build_manual_a(path: Path) -> Path:
    """构造一份迷你 A 手册：标题文本不带编号（同真实 A/C 手册，编号靠位置推导）。"""
    doc = Document()
    doc.add_heading("总则", level=1)                        # 1
    doc.add_heading("操作", level=1)                        # 2
    for name in ["液晶屏", "充电", "转向", "制动"]:           # 2.1-2.4
        doc.add_heading(name, level=2)
    doc.add_heading("起动之前", level=2)                     # 2.5
    doc.add_heading("日常检查", level=3)                     # 2.5.1
    doc.add_paragraph("为了最大限度地延长机器的使用寿命，先进行全面的日常检查后再上机起动机器。")
    layout = doc.add_table(rows=1, cols=1)                  # 排版用表 → 溶解
    layout.cell(0, 0).text = "本手册适用于XC975-EV。"
    warn = doc.add_table(rows=2, cols=1)                    # 警告框（表格形态）
    warn.cell(0, 0).text = "警告"
    warn.cell(1, 0).text = "机器在5s～10s内起动不了，应等1min后再重复起动。"
    doc.add_paragraph("●检查冷却液液位")
    doc.add_paragraph("●检查液压油油位")
    doc.add_picture(BytesIO(TINY_PNG))                      # 插图
    doc.add_paragraph("图2-38 日常检查位置")                  # 题注
    lt = doc.add_table(rows=1, cols=2)                      # 排版表（文+图）→ 溶解含图
    lt.cell(0, 0).text = "驾驶室外观如图所示。"
    lt.cell(0, 1).paragraphs[0].add_run().add_picture(BytesIO(_tiny_png((255, 0, 0))))
    doc.add_heading("故障与保养", level=1)                   # 3
    doc.add_heading("润滑周期", level=2)                     # 3.1
    doc.add_heading("日常保养", level=2)                     # 3.2
    doc.add_heading("定期保养项目", level=2)                 # 3.3
    for name in ["每10小时的保养", "每50小时的保养", "每100小时的保养", "每500小时的保养"]:
        doc.add_heading(name, level=3)                      # 3.3.1-3.3.4
    doc.add_heading("每250小时的保养", level=3)              # 3.3.5
    doc.add_paragraph("同时进行每10、50、100小时的维护保养。")
    period = doc.add_table(rows=4, cols=4)                  # ● 矩阵周期表
    for i, h in enumerate(["保养项目", "每100小时", "每250小时", "每500小时"]):
        period.cell(0, i).text = h
    rows = [
        ["检查电池组电压状态", "●", "●", "●"],
        ["更换前后桥轮毂油", "", "●", ""],
        ["更换液压油箱呼吸器滤芯", "", "●", ""],
    ]
    for r, row in enumerate(rows, start=1):
        for c, v in enumerate(row):
            period.cell(r, c).text = v
    doc.add_paragraph("●检查电池组电压状态。")                # 段落清单形态的周期项
    doc.add_paragraph("●检查液压油箱呼吸器滤芯。")
    doc.add_paragraph("对于第一个250小时，还需进行：更换前后桥轮毂油、更换液压油箱呼吸器滤芯")
    for name in ["电气系统", "液压系统", "传动系统", "水冷机组", "动力电池", "充电系统"]:
        doc.add_heading(name, level=2)                      # 3.4-3.9
    doc.add_heading("故障代码", level=2)                     # 3.10
    doc.add_heading("行走电控", level=3)                     # 3.10.1
    fault = doc.add_table(rows=4, cols=5)                   # 故障码表（含 vMerge 续行）
    for i, h in enumerate(["代码", "故障名称", "触发条件", "故障等级", "解决措施"]):
        fault.cell(0, i).text = h
    fault.cell(1, 0).text = "27"
    fault.cell(1, 1).text = "堵转保护"
    fault.cell(1, 2).text = "转速小于20，力矩大于2800，持续30秒"
    fault.cell(1, 3).text = "2"
    fault.cell(1, 4).text = "停车，不可长时间低速大扭矩使用电机。"
    fault.cell(2, 0).text = "27"
    fault.cell(2, 3).text = "3"
    fault.cell(3, 0).text = "28"
    fault.cell(3, 1).text = "接触器故障"
    fault.cell(3, 2).text = "闭合指令与反馈不一致"
    fault.cell(3, 3).text = "1"
    fault.cell(3, 4).text = ""
    fault.cell(1, 1).merge(fault.cell(2, 1))                # 名称/触发/措施 纵向合并
    fault.cell(1, 2).merge(fault.cell(2, 2))
    fault.cell(1, 4).merge(fault.cell(2, 4))
    ft2 = doc.add_table(rows=2, cols=5)                      # 序号表头（多合一形态）
    for i, h in enumerate(["序号", "故障名称", "故障触发条件", "故障等级", "解决措施"]):
        ft2.cell(0, i).text = h
    ft2.cell(1, 0).text = "101"
    ft2.cell(1, 1).text = "预充故障"
    ft2.cell(1, 2).text = "预充超时"
    ft2.cell(1, 3).text = "2"
    ft2.cell(1, 4).text = "检查预充回路。"
    doc.save(str(path))
    return path


@pytest.fixture
def manual_a(tmp_path: Path) -> Path:
    return build_manual_a(tmp_path / "manual_A.docx")

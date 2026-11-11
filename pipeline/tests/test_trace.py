from xc975_pipeline.audit import AuditLog
from xc975_pipeline.docmodel import parse_docx
from xc975_pipeline.numbering import inject_numbers
from xc975_pipeline.products.fault_codes import extract_fault_codes
from xc975_pipeline.products.tree import build_tree


def test_blocks_carry_source_elements(manual_a):
    elements, _ = parse_docx(str(manual_a))
    inject_numbers(elements, "auto")
    audit = AuditLog()
    sections = build_tree("A", elements, audit)

    sec = next(s for s in sections if s.标题 == "起动之前")
    assert elements[sec.src[0]].para.text == "起动之前"

    blocks = [b for s in sections for b in s.blocks]
    para = next(b for b in blocks if b.type == "para" and "为了最大限度" in b.text)
    assert elements[para.src[0]].para.text == para.text
    warning = next(b for b in blocks if b.type == "warning")
    assert elements[warning.src[0]].kind == "table"
    lst = next(b for b in blocks if b.type == "list")
    assert len(lst.src) == len(lst.items) == 2
    table = next(b for b in blocks if b.type == "table")
    assert elements[table.src[0]].kind == "table"

    codes = extract_fault_codes(elements, "A", "国内干桥", audit)
    assert codes
    assert all(elements[c.src[0]].kind == "table" for c in codes)


def test_stage1_embeds_table_grids_and_image_files(manual_a, tmp_path):
    import json
    from xc975_pipeline.runner import run_stages

    runs = tmp_path / "runs"
    meta = run_stages(str(manual_a), "A", "国内干桥", "202608", runs)
    run_dir = runs / meta["run_id"]
    stage = json.loads((run_dir / "stage_1.json").read_text(encoding="utf-8"))

    table = next(item for item in stage["元素"] if item["类型"] == "table" and item["分类"] == "fault_code")
    assert table["网格"][0] == ["代码", "故障名称", "触发条件", "故障等级", "解决措施"]
    assert any(row[0] == "27" for row in table["网格"][1:])

    image = next(item for item in stage["元素"] if item["类型"] == "para" and item["图片"])
    assert image["图片文件"]
    assert all((run_dir / "img" / name).is_file() for name in image["图片文件"])


def test_stage1_preserves_inline_image_order(tmp_path):
    import json
    from io import BytesIO

    from conftest import TINY_PNG
    from docx import Document
    from xc975_pipeline.runner import run_stages

    doc = Document()
    doc.add_heading("安全注意事项", level=1)
    paragraph = doc.add_paragraph()
    paragraph.add_run("本手册中的")
    paragraph.add_run().add_picture(BytesIO(TINY_PNG))
    paragraph.add_run("符号用来表示安全预防措施。")
    source = tmp_path / "inline.docx"
    doc.save(str(source))

    runs = tmp_path / "runs"
    meta = run_stages(str(source), "A", "国内干桥", "202608", runs)
    stage = json.loads((runs / meta["run_id"] / "stage_1.json").read_text(encoding="utf-8"))
    element = stage["元素"][1]

    assert [(part["type"], part.get("text", part.get("file"))) for part in element["parts"]] == [
        ("text", "本手册中的"),
        ("image", "A_1_01.png"),
        ("text", "符号用来表示安全预防措施。"),
    ]


def test_table_cell_images_stay_in_their_cells(tmp_path):
    import json
    from io import BytesIO

    from conftest import TINY_PNG
    from docx import Document
    from xc975_pipeline.runner import run_stages

    doc = Document()
    doc.add_heading("符号说明", level=1)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "符号"
    table.cell(0, 1).text = "项目"
    table.cell(1, 0).paragraphs[0].add_run().add_picture(BytesIO(TINY_PNG))
    table.cell(1, 1).text = "安全"
    source = tmp_path / "table-cell-image.docx"
    doc.save(str(source))

    runs = tmp_path / "runs"
    meta = run_stages(str(source), "A", "国内干桥", "202608", runs)
    run_dir = runs / meta["run_id"]
    stage1 = json.loads((run_dir / "stage_1.json").read_text(encoding="utf-8"))
    stage2 = json.loads((run_dir / "stage_2.json").read_text(encoding="utf-8"))

    table_element = next(element for element in stage1["元素"] if element["类型"] == "table")
    assert table_element["cell_images"] == [[[], []], [["A_1_01.png"], []]]
    table_block = stage2["章节"][0]["blocks"][0]
    assert table_block["type"] == "table"
    assert table_block["cell_images"] == [[[], []], [["A_1_01.png"], []]]
    assert len(stage2["章节"][0]["blocks"]) == 1


def test_table_preserves_row_and_column_spans(tmp_path):
    import json

    from docx import Document
    from xc975_pipeline.runner import run_stages

    doc = Document()
    doc.add_heading("测试项目", level=1)
    table = doc.add_table(rows=3, cols=6)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "符号"
    table.cell(0, 4).text = "名称"
    table.cell(1, 0).text = "程序下载"
    table.cell(1, 1).text = "A"
    table.cell(1, 2).text = "1"
    table.cell(1, 4).text = "笔记本电脑"
    table.cell(2, 2).text = "2"
    table.cell(2, 4).text = "USBCAN 盒"
    table.cell(0, 1).merge(table.cell(0, 3))
    table.cell(1, 2).merge(table.cell(1, 3))
    table.cell(2, 2).merge(table.cell(2, 3))
    table.cell(1, 0).merge(table.cell(2, 0))
    table.cell(1, 1).merge(table.cell(2, 1))
    source = tmp_path / "table-spans.docx"
    doc.save(str(source))

    runs = tmp_path / "runs"
    meta = run_stages(str(source), "A", "国内干桥", "202608", runs)
    run_dir = runs / meta["run_id"]
    stage1 = json.loads((run_dir / "stage_1.json").read_text(encoding="utf-8"))
    stage2 = json.loads((run_dir / "stage_2.json").read_text(encoding="utf-8"))

    table_element = next(element for element in stage1["元素"] if element["类型"] == "table")
    assert table_element["col_spans"] == [[1, 3, 3, 3, 1, 1], [1, 1, 2, 2, 1, 1], [1, 1, 2, 2, 1, 1]]
    assert table_element["row_spans"] == [[1, 1, 1, 1, 1, 1], [2, 2, 1, 1, 1, 1], [0, 0, 1, 1, 1, 1]]
    table_block = stage2["章节"][0]["blocks"][0]
    assert table_block["col_spans"] == table_element["col_spans"]
    assert table_block["row_spans"] == table_element["row_spans"]

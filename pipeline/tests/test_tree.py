from xc975_pipeline.audit import AuditLog
from xc975_pipeline.docmodel import Element, Para, parse_docx
from xc975_pipeline.images import extract_images
from xc975_pipeline.numbering import inject_numbers
from xc975_pipeline.products.tree import build_tree


def _prepare(manual_a, tmp_path):
    elements, doc = parse_docx(str(manual_a))
    inject_numbers(elements, "auto")
    audit = AuditLog()
    image_files = extract_images(doc, elements, tmp_path / "img", "A", audit=audit)
    sections = build_tree("A", elements, audit, image_files)
    return sections, image_files, audit


def test_tree_structure(manual_a, tmp_path):
    sections, _, _ = _prepare(manual_a, tmp_path)
    assert len(sections) == 25
    s = next(s for s in sections if s.section_id == "A-2.5.1")
    assert s.章节号 == "2.5.1"
    assert s.标题 == "日常检查"
    assert s.层级 == 3
    assert s.parent == "A-2.5"
    assert s.面包屑 == "2 操作 > 2.5 起动之前 > 2.5.1 日常检查"


def test_blocks(manual_a, tmp_path):
    sections, image_files, audit = _prepare(manual_a, tmp_path)
    s = next(s for s in sections if s.section_id == "A-2.5.1")
    types = [b.type for b in s.blocks]
    assert types == ["para", "para", "warning", "list", "image", "para", "image"]
    assert s.blocks[1].text == "本手册适用于XC975-EV。"
    assert s.blocks[2].level == "警告"
    assert "1min" in s.blocks[2].text
    assert s.blocks[3].style == "check"
    assert s.blocks[3].items == ["检查冷却液液位", "检查液压油油位"]
    img = s.blocks[4]
    assert img.file == "A_2_5_1_01.png"
    assert img.图号 == "图2-38"
    assert img.题注 == "图2-38 日常检查位置"
    assert (tmp_path / "img" / "A_2_5_1_01.png").exists()
    assert s.blocks[5].text == "驾驶室外观如图所示。"       # 文+图排版表溶解
    assert s.blocks[6].file == "A_2_5_1_02.png"             # 表格内嵌图
    assert (tmp_path / "img" / "A_2_5_1_02.png").exists()
    assert len(audit) == 0


def test_inline_image_stays_between_text_parts(tmp_path):
    from io import BytesIO

    from conftest import TINY_PNG
    from docx import Document

    doc = Document()
    doc.add_heading("安全注意事项", level=1)
    paragraph = doc.add_paragraph()
    paragraph.add_run("本手册中的")
    paragraph.add_run().add_picture(BytesIO(TINY_PNG))
    paragraph.add_run("符号用来表示安全预防措施。")
    path = tmp_path / "inline.docx"
    doc.save(str(path))

    elements, parsed_doc = parse_docx(str(path))
    inject_numbers(elements, "auto")
    audit = AuditLog()
    image_files = extract_images(parsed_doc, elements, tmp_path / "img", "A", audit=audit)
    sections = build_tree("A", elements, audit, image_files)

    assert len(sections[0].blocks) == 1
    block = sections[0].blocks[0]
    assert block.type == "para"
    assert block.text == "本手册中的符号用来表示安全预防措施。"
    assert [(part.type, part.text if part.type == "text" else part.file) for part in block.parts] == [
        ("text", "本手册中的"),
        ("image", "A_1_01.png"),
        ("text", "符号用来表示安全预防措施。"),
    ]


def test_tables_become_table_blocks(manual_a, tmp_path):
    sections, _, _ = _prepare(manual_a, tmp_path)
    s339 = next(s for s in sections if s.section_id == "A-3.3.5")
    tbl = next(b for b in s339.blocks if b.type == "table")
    assert tbl.header == ["保养项目", "每100小时", "每250小时", "每500小时"]
    assert len(tbl.rows) == 3
    s310 = next(s for s in sections if s.section_id == "A-3.10.1")
    assert any(b.type == "table" for b in s310.blocks)


def test_duplicate_section_id_goes_to_audit(tmp_path):
    """B 手册字面编号撞车 → section_id 重复进审核清单（工作台树渲染依赖该数据防环）。"""
    from docx import Document

    doc = Document()
    doc.add_heading("1 概述", level=1)
    doc.add_heading("1.1 液压系统", level=2)
    doc.add_heading("1.1 传动系统", level=2)  # 字面编号撞车
    path = tmp_path / "dup.docx"
    doc.save(str(path))

    elements, _ = parse_docx(str(path))
    inject_numbers(elements, "literal")
    audit = AuditLog()
    sections = build_tree("B", elements, audit, {}, literal=True)

    assert sum(1 for s in sections if s.section_id == "B-1.1") == 2
    assert any("section_id 重复" in e["说明"] and "B-1.1" in e["说明"] for e in audit.entries)


def _split_paragraph_elements():
    return [
        Element("para", 0, para=Para(style="Heading 1", text="前言"), heading_level=1),
        Element("para", 1, para=Para(style="Body Text Indent", text="这是一个被转换过程拆开的正文段落，前半句没有结束")),
        Element("para", 2, para=Para(style="Body Text Indent", text="标点，后半句应当回到同一段落。")),
    ]


def test_split_continuation_paragraphs_wait_for_confirmation():
    sections = build_tree("B", _split_paragraph_elements(), AuditLog())
    assert len(sections[0].blocks) == 2


def test_merges_only_user_confirmed_paragraphs():
    sections = build_tree("B", _split_paragraph_elements(), AuditLog(), merge_pairs=[{"previous": 1, "current": 2}])
    assert len(sections[0].blocks) == 1
    assert sections[0].blocks[0].text == "这是一个被转换过程拆开的正文段落，前半句没有结束标点，后半句应当回到同一段落。"
    assert sections[0].blocks[0].src == [1, 2]

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


def test_inline_formatting_is_preserved(tmp_path):
    from docx import Document

    doc = Document()
    doc.add_heading("格式", level=1)
    paragraph = doc.add_paragraph("普通")
    bold = paragraph.add_run("粗体")
    bold.bold = True
    italic = paragraph.add_run("斜体")
    italic.italic = True
    superscript = paragraph.add_run("上标")
    superscript.font.superscript = True
    subscript = paragraph.add_run("下标")
    subscript.font.subscript = True
    path = tmp_path / "formatting.docx"
    doc.save(str(path))

    elements, _ = parse_docx(str(path))
    inject_numbers(elements, "auto")
    sections = build_tree("A", elements, AuditLog())

    assert [
        (part.text, part.bold, part.italic, part.vert_align)
        for part in sections[0].blocks[0].parts
    ] == [
        ("普通", False, False, None),
        ("粗体", True, False, None),
        ("斜体", False, True, None),
        ("上标", False, False, "superscript"),
        ("下标", False, False, "subscript"),
    ]


def test_captions_warnings_and_operation_headings_are_semantic_blocks():
    from xc975_pipeline.docmodel import Table

    elements = [
        Element("para", 0, para=Para(style="Heading 1", text="1 驱动桥"), heading_level=1, 编号="1"),
        Element("para", 1, para=Para(image_rids=["r1"])),
        Element("para", 2, para=Para(text="图1.2 驱动桥结构")),
        Element("para", 3, para=Para(text="表1.3 紧固参数")),
        Element("table", 4, table=Table(grid=[["项目", "值"], ["扭矩", "10 Nm"]])),
        Element("para", 5, para=Para(text="★ 注意：")),
        Element("para", 6, para=Para(text="1）拆卸防护罩")),
        Element("para", 7, para=Para(text="2）安装防护罩")),
        Element("para", 8, para=Para(text="★ 放出桥内的润滑油")),
    ]

    sections = build_tree("B", elements, AuditLog(), {"r1": "drive.png"}, literal=True)
    blocks = sections[0].blocks

    assert [block.type for block in blocks] == ["image", "table", "warning", "para"]
    assert blocks[0].图号 == "图1.2" and blocks[0].题注 == "图1.2 驱动桥结构"
    assert blocks[1].表号 == "表1.3" and blocks[1].题注 == "紧固参数"
    assert blocks[2].level == "注意" and blocks[2].items == ["拆卸防护罩", "安装防护罩"]
    assert blocks[3].role == "subheading" and blocks[3].text == "放出桥内的润滑油"


def test_lettered_caption_is_split_across_following_images():
    elements = [
        Element("para", 0, para=Para(style="Heading 1", text="5 扭矩"), heading_level=1, 编号="5"),
        Element("para", 1, para=Para(text="★ 图A                         ★ 图B")),
        Element("para", 2, para=Para(image_rids=["r1", "r2"])),
    ]

    sections = build_tree("B", elements, AuditLog(), {"r1": "a.png", "r2": "b.png"}, literal=True)

    assert [block.type for block in sections[0].blocks] == ["image", "image"]
    assert [block.图号 for block in sections[0].blocks] == ["图A", "图B"]
    assert [block.题注 for block in sections[0].blocks] == ["图A", "图B"]


def test_tables_become_table_blocks(manual_a, tmp_path):
    sections, _, _ = _prepare(manual_a, tmp_path)
    s339 = next(s for s in sections if s.section_id == "A-3.3.5")
    tbl = next(b for b in s339.blocks if b.type == "table")
    assert tbl.header == ["保养项目", "每100小时", "每250小时", "每500小时"]
    assert len(tbl.rows) == 3
    s310 = next(s for s in sections if s.section_id == "A-3.10.1")
    assert any(b.type == "table" for b in s310.blocks)


def test_duplicate_literal_numbers_get_unique_ids_and_correct_parents(tmp_path):
    from docx import Document

    doc = Document()
    doc.add_heading("1 电气系统", level=1)
    doc.add_heading("1.2 电机", level=2)
    doc.add_heading("2 传动系统", level=1)
    doc.add_heading("2.1 驱动桥", level=2)
    doc.add_heading("2.1.5 拆装说明", level=3)
    doc.add_heading("§1.2 拆卸轮边减速器", level=3)
    doc.add_heading("§1.2.1 拆卸轮边端盖", level=4)
    path = tmp_path / "dup.docx"
    doc.save(str(path))

    elements, _ = parse_docx(str(path))
    inject_numbers(elements, "literal")
    audit = AuditLog()
    sections = build_tree("B", elements, audit, {}, literal=True)

    assert len({s.section_id for s in sections}) == len(sections)
    assert sections[-2].parent == sections[4].section_id
    assert sections[-1].parent == sections[-2].section_id
    assert any("章节号重复" in e["说明"] and "B-1.2" in e["说明"] for e in audit.entries)


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

from docx import Document
from docx.oxml import parse_xml

from xc975_pipeline.audit import AuditLog
from xc975_pipeline.docmodel import parse_docx
from xc975_pipeline.numbering import inject_numbers
from xc975_pipeline.products.tree import build_tree

NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:v="urn:schemas-microsoft-com:vml"'
)


def _paragraphs(*texts):
    return "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in texts)


def _drawing_box(*texts, inner=""):
    return f"""<w:drawing>
      <wp:inline><a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
        <wps:wsp><wps:txbx><w:txbxContent>{_paragraphs(*texts)}{inner}</w:txbxContent></wps:txbx></wps:wsp>
      </a:graphicData></a:graphic></wp:inline>
    </w:drawing>"""


def _vml_box(*texts):
    return f"""<w:pict><v:shape><v:textbox><w:txbxContent>{_paragraphs(*texts)}</w:txbxContent></v:textbox></v:shape></w:pict>"""


def _anchor(paragraph, payload):
    paragraph._p.append(parse_xml(f"<w:r {NS}>{payload}</w:r>"))


def _parse(doc, tmp_path):
    path = tmp_path / "text_boxes.docx"
    doc.save(path)
    elements, _ = parse_docx(str(path))
    return elements


def test_drawing_and_vml_text_boxes_are_extracted(tmp_path):
    doc = Document()
    drawing = doc.add_paragraph("DRAWING ANCHOR")
    _anchor(drawing, _drawing_box("DRAWING ONE", "DRAWING TWO"))
    vml = doc.add_paragraph("VML ANCHOR")
    _anchor(vml, _vml_box("LEGACY CALLOUT"))

    elements = _parse(doc, tmp_path)

    assert elements[0].para.text == "DRAWING ANCHOR"
    assert elements[0].para.text_boxes == ["DRAWING ONE\nDRAWING TWO"]
    assert elements[1].para.text_boxes == ["LEGACY CALLOUT"]


def test_alternate_content_text_box_is_read_once(tmp_path):
    doc = Document()
    paragraph = doc.add_paragraph("ANCHOR")
    _anchor(paragraph, f"""<mc:AlternateContent>
      <mc:Choice Requires="wps">{_drawing_box("CALLOUT")}</mc:Choice>
      <mc:Fallback>{_vml_box("CALLOUT")}</mc:Fallback>
    </mc:AlternateContent>""")

    elements = _parse(doc, tmp_path)

    assert elements[0].para.text_boxes == ["CALLOUT"]


def test_fallback_only_text_box_is_kept(tmp_path):
    doc = Document()
    paragraph = doc.add_paragraph("ANCHOR")
    _anchor(paragraph, f"""<mc:AlternateContent>
      <mc:Choice Requires="wps"><w:t>NO TEXT BOX</w:t></mc:Choice>
      <mc:Fallback>{_vml_box("FALLBACK ONLY")}</mc:Fallback>
    </mc:AlternateContent>""")

    elements = _parse(doc, tmp_path)

    assert elements[0].para.text_boxes == ["FALLBACK ONLY"]


def test_nested_text_box_and_table_text_are_extracted_without_duplicates(tmp_path):
    doc = Document()
    paragraph = doc.add_paragraph("ANCHOR")
    table = "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>CELL A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>CELL B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    _anchor(paragraph, _drawing_box("OUTER", inner=table + _vml_box("INNER")))

    elements = _parse(doc, tmp_path)

    assert elements[0].para.text_boxes == ["OUTER\nCELL A\nCELL B", "INNER"]


def test_text_boxes_become_ordered_blocks_including_empty_anchor(tmp_path):
    doc = Document()
    doc.add_heading("General", level=1)
    paragraph = doc.add_paragraph("BEFORE")
    _anchor(paragraph, _drawing_box("CALLOUT"))
    empty_anchor = doc.add_paragraph()
    _anchor(empty_anchor, _vml_box("EMPTY ANCHOR CALLOUT"))
    doc.add_paragraph("AFTER")
    elements = _parse(doc, tmp_path)
    inject_numbers(elements, "auto")

    sections = build_tree("A", elements, AuditLog())

    assert [(block.type, block.text) for block in sections[0].blocks] == [
        ("para", "BEFORE"),
        ("para", "CALLOUT"),
        ("para", "EMPTY ANCHOR CALLOUT"),
        ("para", "AFTER"),
    ]
    assert sections[0].blocks[1].src == [1]
    assert sections[0].blocks[2].src == [2]


def test_stage_snapshot_exposes_text_boxes(tmp_path):
    import json

    from xc975_pipeline.runner import run_stages

    doc = Document()
    doc.add_heading("General", level=1)
    paragraph = doc.add_paragraph("ANCHOR")
    _anchor(paragraph, _drawing_box("CALLOUT"))
    source = tmp_path / "source.docx"
    doc.save(source)

    meta = run_stages(str(source), "A", "国内干桥", "202608", tmp_path / "runs")

    stage = json.loads((tmp_path / "runs" / meta["run_id"] / "stage_1.json").read_text(encoding="utf-8"))
    assert stage["文本框"] == 1
    assert stage["元素"][1]["文本框"] == ["CALLOUT"]

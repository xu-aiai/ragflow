from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

from xc975_pipeline.docmodel import Element, Para, parse_docx
from xc975_pipeline.numbering import inject_numbers, parse_toc_entry


def test_sdt_content_included(tmp_path):
    doc = Document()
    doc.add_paragraph("封面")
    sdt = parse_xml(
        f'<w:sdt {nsdecls("w")}><w:sdtContent>'
        '<w:p><w:r><w:t>一、安全注意事项\t3</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>00 总则\t2</w:t></w:r></w:p>'
        '</w:sdtContent></w:sdt>'
    )
    doc.element.body.insert(1, sdt)  # 插到 sectPr 之前，保持文档流顺序
    doc.add_paragraph("正文")
    p = tmp_path / "sdt.docx"
    doc.save(str(p))
    elements, _ = parse_docx(str(p))
    texts = [el.para.text for el in elements]
    assert "一、安全注意事项\t3" in texts
    assert texts[0] == "封面" and texts[-1] == "正文"


def test_parse_toc_entry_literal():
    assert parse_toc_entry("一、安全注意事项\t3") == ("1", "安全注意事项", "3")
    assert parse_toc_entry("00 总则\t2") == ("0", "总则", "2")
    assert parse_toc_entry("前 言\tI") is None
    assert parse_toc_entry("2.5.1 日常检查\t38") == ("2.5.1", "日常检查", "38")


def test_vml_images_and_nested_table_text(tmp_path):
    from io import BytesIO

    from conftest import TINY_PNG

    doc = Document()
    doc.add_picture(BytesIO(TINY_PNG))
    rid = doc.paragraphs[-1]._p.findall(".//" + qn("a:blip"))[0].get(qn("r:embed"))
    vml_xml = (
        f'<w:p {nsdecls("w")}><w:r><w:pict>'
        f'<v:shape xmlns:v="urn:schemas-microsoft-com:vml" style="width:100px;height:100px">'
        f'<v:imagedata xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="{rid}"/>'
        '</v:shape></w:pict></w:r></w:p>'
    )
    doc.element.body.insert(1, parse_xml(vml_xml))
    tbl = doc.add_table(rows=1, cols=1)
    tbl.cell(0, 0).text = "外层"
    nested = parse_xml(
        f'<w:tbl {nsdecls("w")}><w:tr><w:tc><w:p><w:r><w:t>嵌套内容</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    )
    tbl.cell(0, 0)._tc.append(nested)
    p = tmp_path / "vml.docx"
    doc.save(str(p))
    elements, _ = parse_docx(str(p))
    assert elements[1].para.image_rids == [rid]  # VML 图片也入流
    table_el = next(e for e in elements if e.kind == "table")
    assert "嵌套内容" in table_el.table.grid[0][0]


def test_toc_paragraphs_not_headings():
    els = [
        Element("para", 0, para=Para(style="toc 2", text="一、安全注意事项\t3")),
        Element("para", 1, para=Para(style="Heading 1", text="一、安全注意事项")),
    ]
    inject_numbers(els, "literal")
    assert els[0].heading_level is None  # 目录段不当正文标题
    assert els[1].heading_level == 1 and els[1].编号 == "1"

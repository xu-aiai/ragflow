from __future__ import annotations

import base64
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from manual_parser.docx_native import _image_relationship_ids, parse_docx
from manual_parser.postprocess import link_figures_and_captions, to_markdown

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class DocxNativeTests(unittest.TestCase):
    def test_vml_image_relationship_does_not_require_xpath_prefix_registration(self):
        from docx import Document
        from docx.oxml.ns import qn
        from lxml import etree

        element = etree.fromstring(
            b'<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            b'xmlns:v="urn:schemas-microsoft-com:vml" '
            b'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            b'<w:r><w:pict><v:shape><v:imagedata r:id="rId42"/></v:shape></w:pict></w:r></w:p>'
        )
        self.assertEqual(["rId42"], _image_relationship_ids(element))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "vml.docx"
            document = Document()
            paragraph = document.add_paragraph()
            paragraph.add_run().add_picture(BytesIO(TINY_PNG))
            drawing = paragraph._p.find(".//" + qn("a:blip"))
            relationship_id = drawing.get(qn("r:embed"))
            fallback = etree.fromstring(
                (
                    '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
                    'xmlns:v="urn:schemas-microsoft-com:vml" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    f'<w:pict><v:shape><v:imagedata r:id="{relationship_id}"/></v:shape></w:pict></w:r>'
                ).encode()
            )
            paragraph._p.append(fallback)
            document.save(source)

            blocks = parse_docx(source, root / "assets", "/assets")
            native = next(block for block in blocks if block.attributes.get("source_element_id") == "paragraph:0")
            self.assertEqual(2, len([part for part in native.parts if part["type"] == "image"]))

    def test_preserves_text_image_text_order_and_caption_trace(self):
        from docx import Document

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "inline.docx"
            document = Document()
            paragraph = document.add_paragraph()
            paragraph.add_run("本手册中的")
            paragraph.add_run().add_picture(BytesIO(TINY_PNG))
            paragraph.add_run("符号用来表示安全预防措施。")
            document.add_paragraph("图 1 安全符号", style="Caption")
            document.save(source)

            blocks = parse_docx(source, root / "assets", "/assets")
            native = next(block for block in blocks if block.attributes.get("source_element_id") == "paragraph:0")
            figure = next(block for block in blocks if block.type == "figure")
            caption = next(block for block in blocks if block.type == "caption")

            self.assertEqual(["text", "image", "text"], [part["type"] for part in native.parts])
            self.assertEqual("本手册中的", native.parts[0]["text"])
            self.assertEqual(figure.id, native.parts[1]["figure_id"])
            self.assertEqual("符号用来表示安全预防措施。", native.parts[2]["text"])
            self.assertEqual(native.id, figure.attributes["source_paragraph_id"])
            self.assertEqual(figure.attributes["relationship_id"], native.parts[1]["relationship_id"])

            link_figures_and_captions(blocks)
            self.assertEqual(figure.id, caption.attributes["caption_target_id"])
            self.assertEqual("图 1 安全符号", figure.attributes["caption"])
            markdown = to_markdown(blocks)
            self.assertEqual(1, markdown.count(f"]({figure.region_image})"))
            self.assertLess(markdown.index("本手册中的"), markdown.index(f"]({figure.region_image})"))
            self.assertLess(markdown.index(f"]({figure.region_image})"), markdown.index("符号用来表示安全预防措施。"))

    def test_keeps_repeated_image_references_and_table_cell_coordinates(self):
        from docx import Document

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "table-images.docx"
            document = Document()
            paragraph = document.add_paragraph()
            paragraph.add_run().add_picture(BytesIO(TINY_PNG))
            paragraph.add_run().add_picture(BytesIO(TINY_PNG))
            table = document.add_table(rows=2, cols=2)
            table.cell(0, 0).text = "符号"
            table.cell(0, 1).text = "项目"
            table.cell(1, 0).paragraphs[0].add_run().add_picture(BytesIO(TINY_PNG))
            table.cell(1, 1).text = "安全"
            document.save(source)

            blocks = parse_docx(source, root / "assets", "/assets")
            paragraph_block = next(block for block in blocks if block.attributes.get("source_element_id") == "paragraph:0")
            table_block = next(block for block in blocks if block.type == "table")
            paragraph_figures = [part for part in paragraph_block.parts if part["type"] == "image"]
            cell = next(item for item in table_block.attributes["cells"] if item["row"] == 1 and item["column"] == 0)
            cell_figure = next(block for block in blocks if block.id == cell["figure_ids"][0])

            self.assertEqual(2, len(paragraph_figures))
            self.assertEqual(2, len({part["figure_id"] for part in paragraph_figures}))
            self.assertEqual([1, 0], [cell_figure.attributes["source_row"], cell_figure.attributes["source_column"]])
            self.assertEqual(table_block.id, cell_figure.attributes["source_table_id"])
            self.assertEqual(table_block.id, cell_figure.attributes["source_parent_id"])
            self.assertEqual(cell["images"][0], cell["parts"][0]["asset"])
            self.assertIn("表格单元格 R2C1", to_markdown(blocks))


if __name__ == "__main__":
    unittest.main()

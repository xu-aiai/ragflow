from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manual_parser import deepdoc_engine
from manual_parser.docx_native import _toc_style_level, _toc_text_parts
from manual_parser.fusion import fuse_ooxml_and_visual
from manual_parser.model import BBox, Block, Evidence, Page
from manual_parser.native_pdf import _toc_parts
from manual_parser.table_grid import assess_table_integrity, parse_table_grid
from manual_parser.vlm import RegionVisionRecognizer


class _FakeDeepDoc:
    def parse_into_bboxes(self, _path, callback):
        callback(1.0, "done")
        return [
            {
                "layout_type": "table",
                "text": "<table><tr><td>E101</td><td>618V</td></tr></table>",
                "positions": [[1, 10, 200, 700, 840], [2, 10, 200, 20, 180]],
                "score": 0.91,
                "image": None,
            }
        ]


class _FakeVlm(RegionVisionRecognizer):
    def __init__(self):
        super().__init__()
        self.endpoint = "http://unused"

    def recognize(self, image_path: Path, block: Block) -> dict:
        return {
            "type": "table",
            "text": "E101 | 618V",
            "html": "<table><tr><td>E101</td><td>618V</td></tr></table>",
            "confidence": 0.99,
        }


class _FakeDeepDocPhantomTable:
    def parse_into_bboxes(self, _path, callback):
        callback(1.0, "done")
        return [
            {
                "layout_type": "table",
                "text": "<table><tr><td>版本号</td><td>V01</td></tr></table>",
                "positions": [[4, 68, 551, 48, 362], [9, 132, 470, 564, 574]],
                "score": 0.9,
                "image": None,
            }
        ]


class _FakeDeepDocBatchGlobalFigure:
    def parse_into_bboxes(self, _path, callback):
        callback(1.0, "done")
        return [{"layout_type": "figure", "text": "图内文字", "positions": [[1, 40, 500, 25431, 25500]], "score": 0.9, "image": None}]


class ComponentTests(unittest.TestCase):
    def test_docx_toc_style_is_navigation_not_a_business_list(self):
        self.assertEqual(3, _toc_style_level("TOC 3"))
        self.assertEqual(2, _toc_style_level("目录 2"))
        self.assertEqual(("2.1 整机外形图", "46"), _toc_text_parts("2.1 整机外形图\t46"))

    def test_docx_fusion_aligns_one_ooxml_paragraph_to_multiple_pdf_lines(self):
        pages = [Page(number, 600, 800, f"/{number}") for number in range(1, 5)]
        native = [
            Block(
                "ooxml-1",
                "paragraph",
                "液压油不足时应立即停机，并按照规定补充液压油。",
                evidence=[Evidence("ooxml", "paragraph:1")],
            )
        ]
        lines = [
            Block("line-1", "native_line", "液压油不足时应立即停机，", 3, BBox(60, 100, 400, 120), evidence=[Evidence("pdf_native", "p3:1")]),
            Block("line-2", "native_line", "并按照规定补充液压油。", 3, BBox(60, 122, 360, 142), evidence=[Evidence("pdf_native", "p3:2")]),
        ]
        visual = [
            Block("visual-1", "text", "液压油不足时应立即停机，", 3, BBox(60, 100, 400, 120), evidence=[Evidence("deepdoc", "v1")]),
            Block("visual-2", "text", "并按照规定补充液压油。", 3, BBox(60, 122, 360, 142), evidence=[Evidence("deepdoc", "v2")]),
        ]
        fused = fuse_ooxml_and_visual(native, visual, pages, lines)
        self.assertEqual(1, len(fused))
        self.assertEqual(3, fused[0].page)
        self.assertEqual("pdf_native", fused[0].attributes["alignment_channel"])
        self.assertEqual(["visual-1", "visual-2"], fused[0].attributes["covered_visual_block_ids"])

    def test_docx_fusion_keeps_uncovered_visual_text_as_fallback(self):
        pages = [Page(1, 600, 800, "/1")]
        native = [Block("native", "paragraph", "原生段落。", evidence=[Evidence("ooxml", "p1")])]
        visual = [Block("visual-only", "text", "只存在于渲染页面的文字。", 1, BBox(60, 200, 480, 225))]
        fused = fuse_ooxml_and_visual(native, visual, pages)
        fallback = next(block for block in fused if block.id == "visual-only")
        self.assertEqual("visual_fallback", fallback.attributes["fusion_role"])

    def test_docx_unmatched_blocks_use_monotonic_page_interpolation(self):
        pages = [Page(number, 600, 800, f"/{number}") for number in range(1, 6)]
        native = [
            Block("left", "paragraph", "第二页锚点文字。", evidence=[Evidence("ooxml", "p1")]),
            Block("image", "figure", region_image="/image.png", evidence=[Evidence("ooxml", "image:1")]),
            Block("right", "paragraph", "第五页锚点文字。", evidence=[Evidence("ooxml", "p2")]),
        ]
        lines = [
            Block("line-left", "native_line", "第二页锚点文字。", 2, BBox(60, 100, 300, 120)),
            Block("line-right", "native_line", "第五页锚点文字。", 5, BBox(60, 100, 300, 120)),
        ]
        fused = fuse_ooxml_and_visual(native, [], pages, lines)
        image = next(block for block in fused if block.id == "image")
        self.assertEqual(4, image.page)
        self.assertEqual("ooxml_source_order_interpolation", image.attributes["page_inference_strategy"])

    def test_native_numeric_table_ignores_unit_header_when_checking_alignment(self):
        html = """<table>
        <tr><td>螺栓螺径</td><td>对边宽度</td><td>紧固扭矩</td><td></td></tr>
        <tr><td>mm</td><td>mm</td><td>Nm</td><td>kgm</td></tr>
        <tr><td>6</td><td>10</td><td>11.8-14.7</td><td>1.2-1.5</td></tr>
        <tr><td>8</td><td>13</td><td>27-34</td><td>2.8-3.5</td></tr>
        </table>"""
        status, reasons = assess_table_integrity(parse_table_grid(html), "pdf_native_table", "data_table")
        self.assertEqual("verified", status)
        self.assertEqual([], reasons)

    def test_character_level_toc_page_label_is_reassembled(self):
        items = []
        x = 90.0
        for character in "2.1.5 拆装说明":
            items.append({"text": character, "x0": x, "x1": x + 7, "top": 100, "bottom": 112})
            x += 7
        for character in "......":
            items.append({"text": character, "x0": x, "x1": x + 5, "top": 100, "bottom": 112})
            x += 5
        for offset, character in enumerate("160"):
            items.append({"text": character, "x0": 510 + offset * 7, "x1": 516 + offset * 7, "top": 100, "bottom": 112})
        self.assertEqual(("2.1.5 拆装说明", "160"), _toc_parts(items, 595))

    def test_deepdoc_cross_page_positions_are_preserved(self):
        original = deepdoc_engine._PARSER
        deepdoc_engine._PARSER = _FakeDeepDoc()
        try:
            with tempfile.TemporaryDirectory() as directory:
                pages = [Page(1, 595, 842, "/p1"), Page(2, 595, 842, "/p2")]
                blocks = deepdoc_engine.parse_pdf_with_deepdoc(Path(directory) / "fake.pdf", Path(directory), "/regions", pages)
            self.assertTrue(blocks[0].attributes["spans_pages"])
            self.assertEqual([1, 2], [item["page"] for item in blocks[0].attributes["position_slices"]])
            self.assertEqual(["deepdoc-0"], pages[1].block_ids)
        finally:
            deepdoc_engine._PARSER = original

    def test_vlm_cannot_replace_ooxml_table_grid(self):
        with tempfile.TemporaryDirectory() as directory:
            job_dir = Path(directory)
            (job_dir / "regions").mkdir()
            (job_dir / "regions" / "table.webp").write_bytes(b"image")
            native_html = '<table><tr><td rowspan="2">E101</td><td>618V</td></tr></table>'
            block = Block(
                "table",
                "table",
                text="E101 618V",
                html=native_html,
                region_image="/api/jobs/x/regions/table.webp",
                evidence=[Evidence("ooxml", "table:1")],
            )
            blocks, issues, metrics = _FakeVlm().enhance([block], job_dir)
            self.assertEqual([], issues)
            self.assertEqual(native_html, blocks[0].html)
            self.assertTrue(blocks[0].attributes["vlm_validated_native_table"])
            self.assertEqual(1, metrics["accepted"])

    def test_nonconsecutive_table_position_is_not_a_cross_page_table(self):
        original = deepdoc_engine._PARSER
        deepdoc_engine._PARSER = _FakeDeepDocPhantomTable()
        try:
            with tempfile.TemporaryDirectory() as directory:
                pages = [Page(number, 595, 842, f"/p{number}") for number in range(1, 10)]
                block = deepdoc_engine.parse_pdf_with_deepdoc(Path(directory) / "fake.pdf", Path(directory), "/regions", pages)[0]
            self.assertFalse(block.attributes["spans_pages"])
            self.assertEqual([4], [item["page"] for item in block.attributes["position_slices"]])
            self.assertEqual([], pages[8].block_ids)
        finally:
            deepdoc_engine._PARSER = original

    def test_batch_global_figure_coordinate_is_restored_to_physical_page(self):
        original = deepdoc_engine._PARSER
        deepdoc_engine._PARSER = _FakeDeepDocBatchGlobalFigure()
        try:
            with tempfile.TemporaryDirectory() as directory:
                pages = [Page(number, 595, 842, f"/p{number}") for number in range(1, 40)]
                block = deepdoc_engine.parse_pdf_with_deepdoc(Path(directory) / "fake.pdf", Path(directory), "/regions", pages)[0]
            self.assertEqual(31, block.page)
            self.assertLess(block.bbox.y1, 842)
            self.assertTrue(block.attributes["coordinate_repaired"])
        finally:
            deepdoc_engine._PARSER = original

    def test_official_paddle_pipeline_uses_region_prompt(self):
        response_body = {
            "result": {
                "layoutParsingResults": [
                    {
                        "prunedResult": {"parsing_res_list": [{"block_label": "table", "block_content": "<table><tr><td>E101</td></tr></table>", "score": 0.95}]},
                        "markdown": {"text": "<table><tr><td>E101</td></tr></table>"},
                    }
                ]
            }
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(response_body).encode()

        recognizer = RegionVisionRecognizer()
        recognizer.endpoint = "http://paddle/layout-parsing"
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "table.webp"
            image.write_bytes(b"image")
            with patch("manual_parser.vlm.urlopen", return_value=FakeResponse()) as mocked:
                result = recognizer.recognize(image, Block("t", "table", "E101"))
        request = mocked.call_args.args[0]
        payload = json.loads(request.data)
        self.assertFalse(payload["useLayoutDetection"])
        self.assertEqual("table", payload["promptLabel"])
        self.assertEqual("table", result["type"])
        self.assertIn("<table", result["html"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UiContractTests(unittest.TestCase):
    def test_result_pagination_controls_and_page_filter_are_wired(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        for element_id in ("resultPageControls", "resultPrevPage", "resultPageNumber", "resultPageCount", "resultNextPage"):
            self.assertIn(f'id="{element_id}"', html)
            self.assertIn(f'$("{element_id}")', script)
        self.assertIn("slice.page === state.page", script)
        self.assertIn("renderDocument();", script)

    def test_large_json_and_block_metadata_are_lazy(self):
        script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('name === "json" && state.result && !state.jsonRendered', script)
        self.assertIn('details.addEventListener("toggle"', script)

    def test_trust_and_portable_export_controls_are_visible(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="downloadPackage"', html)
        self.assertIn("数值对应关系不安全", script)
        self.assertIn("TOC L", script)

    def test_docx_inline_and_table_cell_images_are_rendered_in_place(self):
        script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "static" / "manual-parser.css").read_text(encoding="utf-8")
        self.assertIn("function inlineParts", script)
        self.assertIn("function injectTableCellImages", script)
        self.assertIn("embeddedFigureIds.has(block.id)", script)
        self.assertIn(".inline-part-image", styles)
        self.assertIn(".table-cell-image", styles)


if __name__ == "__main__":
    unittest.main()

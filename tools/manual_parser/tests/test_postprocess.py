from __future__ import annotations

import unittest

from manual_parser.model import BBox, Block, Evidence, Page
from manual_parser.postprocess import (
    anchor_recall,
    build_heading_tree,
    deduplicate_fused_blocks,
    mark_table_continuations,
    merge_broken_lines,
    normalize_types,
    repair_toc_reading_order,
    run_postprocessing,
)


class PostprocessTests(unittest.TestCase):
    def test_deduplication_rebinds_inline_figure_to_kept_paragraph(self):
        native = Block(
            "native",
            "paragraph",
            "安全符号说明",
            1,
            BBox(10, 10, 200, 40),
            parts=[{"type": "image", "figure_id": "figure", "asset": "/image.png"}],
        )
        visual = Block(
            "visual",
            "paragraph",
            "安全符号说明",
            1,
            BBox(10, 10, 200, 40),
            attributes={"fusion_action": "replace"},
        )
        figure = Block(
            "figure",
            "figure",
            page=1,
            parent_id="native",
            attributes={"source_paragraph_id": "native", "source_parent_id": "native"},
        )

        deduplicated = deduplicate_fused_blocks([native, visual, figure])

        kept = next(block for block in deduplicated if block.id == "visual")
        self.assertEqual(native.parts, kept.parts)
        self.assertEqual("visual", figure.parent_id)
        self.assertEqual("visual", figure.attributes["source_paragraph_id"])

    def test_chinese_line_break_is_merged(self):
        blocks = [
            Block("a", "text", "检查液压油温是否正", 1, BBox(10, 10, 100, 20)),
            Block("b", "text", "常，并清洁散热器。", 1, BBox(10, 21, 100, 31)),
        ]
        merged = merge_broken_lines(normalize_types(blocks))
        self.assertEqual(1, len(merged))
        self.assertEqual("检查液压油温是否正常，并清洁散热器。", merged[0].text)

    def test_warning_and_toc_are_typed(self):
        blocks = normalize_types([
            Block("a", "text", "警告：维修前必须切断高压电源"),
            Block("b", "text", "3.2 液压系统 ........ 48"),
        ])
        self.assertEqual("warning", blocks[0].type)
        self.assertEqual("toc_entry", blocks[1].type)

    def test_anchor_conflict_is_detected(self):
        reference = "故障码 E1024，母线电压 618V，扭矩 320N·m"
        self.assertLess(anchor_recall(reference, "故障码 E1024，母线电压 618V"), 0.8)
        self.assertEqual(1.0, anchor_recall(reference, reference))

    def test_cross_page_table_continuation(self):
        first = Block("t1", "table", page=2, html="<table><tr><td>故障码</td><td>说明</td></tr><tr><td>E1</td><td>A</td></tr></table>", attributes={"near_page_bottom": True})
        second = Block("t2", "table", page=3, html="<table><tr><td>故障码</td><td>说明</td></tr><tr><td>E2</td><td>B</td></tr></table>", attributes={"near_page_top": True})
        issues = mark_table_continuations([first, second])
        self.assertEqual("t1", second.continuation_of)
        self.assertEqual("table_continuation", issues[0].code)

    def test_heading_tree_uses_levels(self):
        blocks = [Block("h1", "heading", "1 概述", level=1), Block("p", "paragraph", "正文"), Block("h2", "heading", "1.1 安全", level=2)]
        tree = build_heading_tree(blocks)
        self.assertEqual("h1", tree[0]["id"])
        self.assertEqual("h2", tree[0]["children"][0]["id"])
        self.assertEqual("h1", blocks[1].parent_id)

    def test_toc_columns_are_paired(self):
        blocks = [
            Block("titles", "paragraph", "1 概述\n2 安全要求\n3 保养", 2, BBox(20, 20, 180, 80), reading_order=0),
            Block("pages", "paragraph", "1\n5\n19", 2, BBox(220, 20, 240, 80), reading_order=1),
        ]
        repaired = repair_toc_reading_order(blocks)
        self.assertEqual(3, len(repaired))
        self.assertTrue(all(block.type == "toc_entry" for block in repaired))
        self.assertEqual("2 安全要求", repaired[1].attributes["toc_title"])
        self.assertEqual("5", repaired[1].attributes["target_page_label"])

    def test_native_pdf_toc_replaces_deepdoc_heading_and_page_fragments(self):
        deepdoc = [
            Block("h", "title", "a)目录", 5, BBox(60, 80, 130, 105)),
            Block("wrong", "title", "1.1 主要用途", 5, BBox(90, 150, 180, 165)),
            Block("page", "text", ". 1", 5, BBox(520, 150, 540, 165)),
        ]
        native = [
            Block("nh", "native_line", "a)目录", 5, BBox(60, 80, 130, 105)),
            Block(
                "n1",
                "native_line",
                "1.1 主要用途 ........ 1",
                5,
                BBox(90, 150, 540, 165),
                attributes={"native_toc_row": True, "toc_title": "1.1 主要用途", "target_page_label": "1"},
            ),
            Block(
                "n2",
                "native_line",
                "1.2 产品信息 ........ 3",
                5,
                BBox(90, 168, 540, 183),
                attributes={"native_toc_row": True, "toc_title": "1.2 产品信息", "target_page_label": "3"},
            ),
            Block("n3", "native_line", "1.3 目标群体 ........ 4", 5, BBox(90, 186, 540, 201), attributes={"native_toc_row": True, "toc_title": "1.3 目标群体", "target_page_label": "4"}),
            Block("n4", "native_line", "1.4 警告提示 ........ 5", 5, BBox(90, 204, 540, 219), attributes={"native_toc_row": True, "toc_title": "1.4 警告提示", "target_page_label": "5"}),
            Block("n5", "native_line", "1.5 文本结构 ........ 6", 5, BBox(90, 222, 540, 237), attributes={"native_toc_row": True, "toc_title": "1.5 文本结构", "target_page_label": "6"}),
        ]
        blocks, _tree, markdown, _issues = run_postprocessing(deepdoc, native)
        self.assertEqual(["heading", "toc_entry", "toc_entry", "toc_entry", "toc_entry", "toc_entry"], [block.type for block in blocks])
        self.assertEqual("3", blocks[2].attributes["target_page_label"])
        self.assertNotIn("## 1.1", markdown)

    def test_partial_native_toc_never_deletes_unresolved_source_region(self):
        page = Page(7, 595, 842, "/7")
        deepdoc = [
            Block("header", "title", "目录", 7, BBox(280, 40, 320, 54)),
            Block("missing-band", "paragraph", "§1.1 拆卸制动钳 …… 160\n§5.2 更换制动钳总成 …… 199", 7, BBox(100, 70, 520, 400)),
            Block("bottom", "paragraph", "2.2 传动轴 …… 201", 7, BBox(95, 430, 525, 445)),
        ]
        native = [
            Block(f"n{index}", "native_line", f"2.{index} 目录项 …… {200 + index}", 7, BBox(95, 430 + index * 20, 525, 445 + index * 20), attributes={"native_toc_row": True, "toc_title": f"2.{index} 目录项", "target_page_label": str(200 + index)})
            for index in range(1, 7)
        ]
        parsed, _tree, _markdown, _issues = run_postprocessing(deepdoc, native, [page])
        self.assertTrue(any("拆卸制动钳" in block.text for block in parsed))
        self.assertTrue(any(block.attributes.get("toc_fragment_unresolved") for block in parsed))

    def test_global_order_puts_page_one_figure_before_page_fifteen_text(self):
        pages = [Page(number, 600, 800, f"/{number}") for number in range(1, 16)]
        blocks = [
            Block("late", "paragraph", "第十五页", 15, BBox(40, 100, 500, 130), reading_order=0),
            Block("cover", "figure", page=1, bbox=BBox(40, 100, 500, 700), reading_order=1),
        ]
        parsed, _tree, _markdown, _issues = run_postprocessing(blocks, pages=pages)
        self.assertEqual(["cover", "late"], [block.id for block in parsed])

    def test_two_column_page_reads_down_left_column_then_right(self):
        page = Page(1, 600, 800, "/1")
        blocks = [
            Block("right-2", "paragraph", "右二", 1, BBox(340, 120, 540, 140), reading_order=0),
            Block("left-1", "paragraph", "左一。", 1, BBox(50, 60, 250, 80), reading_order=1),
            Block("heading", "heading", "双栏说明", 1, BBox(40, 10, 560, 40), reading_order=2),
            Block("right-1", "paragraph", "右一。", 1, BBox(340, 60, 540, 80), reading_order=3),
            Block("left-2", "paragraph", "左二。", 1, BBox(50, 120, 250, 140), reading_order=4),
        ]
        parsed, _tree, _markdown, _issues = run_postprocessing(blocks, pages=[page])
        self.assertEqual(["heading", "left-1", "left-2", "right-1", "right-2"], [block.id for block in parsed])

    def test_unmatched_ooxml_block_keeps_source_position(self):
        page = Page(2, 600, 800, "/2")
        blocks = [
            Block("before", "paragraph", "前文。", 2, BBox(50, 80, 500, 100), reading_order=10),
            Block("native", "paragraph", "OOXML 中间段。", reading_order=11, evidence=[Evidence("ooxml", "paragraph:11")]),
            Block("after", "paragraph", "后文。", 2, BBox(50, 140, 500, 160), reading_order=12),
        ]
        parsed, _tree, _markdown, _issues = run_postprocessing(blocks, pages=[page])
        self.assertEqual(["before", "native", "after"], [block.id for block in parsed])
        self.assertEqual(2, parsed[1].page)

    def test_structure_path_is_exposed_on_content(self):
        blocks = [
            Block("h1", "heading", "1 安全", page=1, level=1),
            Block("h2", "heading", "1.1 起吊", page=1, level=2),
            Block("p", "paragraph", "使用合格钢丝绳。", page=1),
        ]
        _tree = build_heading_tree(blocks)
        self.assertEqual(["1 安全", "1.1 起吊"], blocks[-1].attributes["section_path"])

    def test_list_and_safety_notice_are_structured(self):
        pages = [Page(1, 600, 800, "/1")]
        blocks = [
            Block("warning", "paragraph", "警告！", 1, BBox(40, 80, 100, 100)),
            Block("warning-body", "paragraph", "起吊前必须检查钢丝绳。", 1, BBox(40, 102, 500, 122)),
            Block("item", "paragraph", "• 如果钢丝绳损坏，立即更换。", 1, BBox(50, 150, 500, 172)),
        ]
        parsed, _tree, _markdown, _issues = run_postprocessing(blocks, pages=pages)
        self.assertEqual("safety_notice", parsed[0].type)
        self.assertEqual("起吊前必须检查钢丝绳。", parsed[0].attributes["body"])
        self.assertEqual("list_item", parsed[1].type)
        self.assertEqual("•", parsed[1].attributes["marker"])

    def test_numbered_and_nested_pdf_lists_are_not_headings(self):
        page = Page(1, 600, 800, "/1")
        blocks = [
            Block("one", "text", "1. 检查钢丝绳", 1, BBox(50, 80, 300, 100)),
            Block("nested", "text", "• 检查绳卡", 1, BBox(74, 104, 300, 124)),
            Block("two", "text", "2. 更换损坏部件", 1, BBox(50, 128, 300, 148)),
        ]
        parsed, _tree, _markdown, _issues = run_postprocessing(blocks, pages=[page])
        self.assertTrue(all(block.type == "list_item" for block in parsed))
        self.assertEqual([0, 1, 0], [block.attributes["list_level"] for block in parsed])
        self.assertEqual(parsed[0].attributes["list_id"], parsed[2].attributes["list_id"])

    def test_numbered_sentence_heading_is_demoted_and_original_marker_is_kept(self):
        page = Page(1, 600, 800, "/1")
        blocks = [
            Block("parent", "heading", "安全要求", 1, BBox(50, 40, 250, 60)),
            Block("sentence", "heading", "2.严禁在腐蚀性、易燃性、爆炸性气体环境中使用本产品。", 1, BBox(50, 80, 500, 110)),
            Block("letter", "paragraph", "a. 检查电源。", 1, BBox(50, 120, 300, 140)),
        ]
        parsed, _tree, markdown, _issues = run_postprocessing(blocks, pages=[page])
        sentence = next(block for block in parsed if block.id == "sentence")
        letter = next(block for block in parsed if block.id == "letter")
        self.assertEqual("list_item", sentence.type)
        self.assertEqual("2.", sentence.attributes["marker"])
        self.assertEqual("a.", letter.attributes["marker"])
        self.assertIn("a. 检查电源。", markdown)

    def test_inline_bullets_and_broken_list_tail_are_recovered(self):
        page = Page(14, 600, 800, "/14")
        blocks = [
            Block("many", "paragraph", "检查垫片。• 当起吊部件时使用合格吊具。• 清洁周围区域。", 14, BBox(70, 60, 520, 150)),
            Block("item", "paragraph", "• 当涂粘合剂时，在螺纹部位涂2～3", 14, BBox(98, 180, 520, 192)),
            Block("tail", "paragraph", "滴粘合剂。", 14, BBox(70, 205, 130, 218)),
        ]
        parsed, _tree, _markdown, _issues = run_postprocessing(blocks, pages=[page])
        items = [block for block in parsed if block.type == "list_item"]
        self.assertGreaterEqual(len(items), 4)
        self.assertTrue(any("2～3滴粘合剂" in block.text for block in items))

    def test_printed_page_label_is_metadata_not_body(self):
        page = Page(9, 600, 800, "/9")
        blocks = [Block("page-number", "paragraph", "1", 9, BBox(295, 760, 305, 780))]
        parsed, _tree, markdown, _issues = run_postprocessing(blocks, pages=[page])
        self.assertEqual("1", page.printed_page_label)
        self.assertEqual("page_footer", parsed[0].type)
        self.assertNotIn("1", markdown)

    def test_toc_has_its_own_root_and_unparsed_targets_are_not_false_matched(self):
        pages = [Page(number, 600, 800, f"/{number}") for number in range(1, 16)]
        blocks = [
            Block("body-major", "heading", "03液压系统", 3, BBox(60, 100, 260, 130), level=1),
            Block("toc-header", "heading", "目录", 4, BBox(60, 40, 160, 70), level=1, attributes={"toc_page": True}),
        ]
        for index, (title, target) in enumerate(
            [("00总则", "2"), ("一、安全注意事项", "3"), ("01电气系统", "46"), ("02传动系统", "150"), ("03液压系统", "204")]
        ):
            blocks.append(
                Block(
                    f"toc-{index}",
                    "toc_entry",
                    f"{title} …… {target}",
                    4,
                    BBox(60 + (20 if index == 1 else 0), 100 + index * 30, 520, 120 + index * 30),
                    attributes={"toc_title": title, "target_page_label": target, "toc_page": True},
                )
            )
        parsed, tree, _markdown, _issues = run_postprocessing(blocks, pages=pages)
        root = next(block for block in parsed if block.attributes.get("toc_root"))
        entries = [block for block in parsed if block.type == "toc_entry"]
        self.assertEqual("目录", root.text)
        self.assertTrue(all(block.attributes["section_path"][0] == "目录" for block in entries))
        self.assertTrue(all(block.parent_id != "body-major" for block in entries))
        electric = next(block for block in entries if block.attributes["toc_title"] == "01电气系统")
        self.assertEqual("out_of_parse_range", electric.attributes["resolution_status"])
        self.assertNotIn("target_heading_id", electric.attributes)
        self.assertEqual("toc_root", tree[0]["kind"])

    def test_chinese_chapter_heading_and_fullwidth_ordered_marker_are_preserved(self):
        page = Page(10, 600, 800, "/10")
        blocks = [
            Block("major", "heading", "00总则", 10, BBox(50, 40, 250, 70), level=1),
            Block("chapter", "paragraph", "一、安全注意事项", 10, BBox(50, 90, 280, 120)),
            Block("item", "paragraph", "4）•当需要两个人或多人工作时，应指定负责人。", 10, BBox(70, 140, 520, 170)),
        ]
        parsed, tree, markdown, _issues = run_postprocessing(blocks, pages=[page])
        chapter = next(block for block in parsed if block.id == "chapter")
        item = next(block for block in parsed if block.type == "list_item")
        self.assertEqual("heading", chapter.type)
        self.assertEqual(2, chapter.level)
        self.assertEqual("4）", item.attributes["marker"])
        self.assertTrue(item.attributes["ordered"])
        self.assertEqual("当需要两个人或多人工作时，应指定负责人。", item.text)
        self.assertIn("4） 当需要两个人或多人工作时", markdown)
        self.assertEqual("chapter", tree[0]["children"][0]["id"])

    def test_glued_chinese_chapter_title_is_split_from_body(self):
        page = Page(12, 600, 800, "/12")
        blocks = [
            Block(
                "glued",
                "heading",
                "二、如何阅读使用本手册本维修手册在重要的安全和质量控制部分使用符号。",
                12,
                BBox(50, 100, 520, 150),
                level=1,
            )
        ]
        parsed, _tree, _markdown, _issues = run_postprocessing(blocks, pages=[page])
        heading = next(block for block in parsed if block.type == "heading")
        paragraph = next(block for block in parsed if block.type == "paragraph")
        self.assertEqual("二、如何阅读使用本手册", heading.text)
        self.assertTrue(paragraph.text.startswith("本维修手册"))

    def test_native_line_replaces_matching_text_when_it_restores_list_number(self):
        page = Page(
            11,
            600,
            800,
            "/11",
            attributes={"native_text_coverage": {"text_shingle_recall": 0.8, "number_recall": 0.5}},
        )
        deepdoc = [Block("old", "paragraph", "检查液压油。", 11, BBox(70, 100, 400, 125))]
        native = [Block("native", "native_line", "10）检查液压油。", 11, BBox(70, 100, 400, 125))]
        parsed, _tree, markdown, _issues = run_postprocessing(deepdoc, native, [page])
        item = next(block for block in parsed if block.type == "list_item")
        self.assertEqual("old", item.id)
        self.assertEqual("10）", item.attributes["marker"])
        self.assertEqual("replace", item.attributes["fusion_action"])
        self.assertIn("10） 检查液压油。", markdown)

    def test_spatially_overlapping_cover_title_is_not_duplicated(self):
        page = Page(1, 600, 800, "/1")
        blocks = [
            Block("short", "heading", "XC975-EV装载机维修保养手册（宁德423+微特桥）", 1, BBox(60, 120, 540, 170)),
            Block("complete", "heading", "XC975-EV装载机维修保养手册（宁德423+微特利+干桥）", 1, BBox(60, 120, 540, 170)),
        ]
        parsed, _tree, _markdown, _issues = run_postprocessing(blocks, pages=[page])
        headings = [block for block in parsed if block.type == "heading"]
        self.assertEqual(1, len(headings))
        self.assertIn("微特利+干桥", headings[0].text)

    def test_visual_numeric_table_is_not_marked_verified(self):
        table = Block(
            "table",
            "table",
            page=12,
            html="<table><tr><th>直径</th><th>载荷</th></tr><tr><td>18</td><td>3.6</td></tr><tr><td>20</td><td>4.4</td></tr></table>",
        )
        blocks, _tree, _markdown, issues = run_postprocessing([table])
        self.assertEqual(3, blocks[0].attributes["table_grid"]["row_count"])
        self.assertEqual("review_required", blocks[0].attributes["integrity_status"])
        self.assertTrue(any(issue.code == "table_review_required" for issue in issues))
        self.assertFalse(blocks[0].attributes["qa_eligible"])

    def test_shifted_numeric_rows_are_unsafe(self):
        table = Block(
            "shifted",
            "table",
            page=12,
            html=(
                "<table><tr><td>直径</td><td>载荷</td></tr>"
                "<tr><td>18</td><td>3.6</td><td>4.4</td></tr>"
                "<tr><td>20</td></tr></table>"
            ),
        )
        blocks, _tree, _markdown, issues = run_postprocessing([table])
        self.assertEqual("unsafe", blocks[0].attributes["integrity_status"])
        self.assertFalse(blocks[0].attributes["qa_eligible"])
        self.assertTrue(any(issue.code == "unsafe_table" for issue in issues))

    def test_two_column_numeric_rows_are_repaired_without_inventing_values(self):
        table = Block(
            "wire-rope",
            "table",
            page=12,
            html=(
                "<table><tr><th>直径</th><th>载荷</th></tr>"
                "<tr><td>18</td><td>3.6 4.4</td></tr><tr><td>20</td><td></td></tr>"
                "<tr><td>30 40</td><td>10.0</td></tr><tr><td></td><td>18.0</td></tr></table>"
            ),
        )
        blocks, _tree, _markdown, _issues = run_postprocessing([table])
        rows = blocks[0].attributes["table_grid"]["grid"]
        self.assertEqual(("18", "3.6"), (rows[1][0]["text"], rows[1][1]["text"]))
        self.assertEqual(("20", "4.4"), (rows[2][0]["text"], rows[2][1]["text"]))
        self.assertEqual(("30", "10.0"), (rows[3][0]["text"], rows[3][1]["text"]))
        self.assertEqual(("40", "18.0"), (rows[4][0]["text"], rows[4][1]["text"]))

    def test_thousands_separator_fragment_is_moved_back_to_torque_cell(self):
        table = Block(
            "torque",
            "table",
            page=15,
            html="<table><tr><td>27</td><td>41 1,</td><td>150 – 1,440</td><td>118-147</td></tr></table>",
            evidence=[Evidence("pdf_native_table", "p15")],
        )
        blocks, _tree, _markdown, _issues = run_postprocessing([table])
        row = blocks[0].attributes["table_grid"]["grid"][0]
        self.assertEqual("41", row[1]["text"])
        self.assertEqual("1,150 – 1,440", row[2]["text"])

    def test_unsafe_table_values_are_quarantined_from_markdown(self):
        table = Block(
            "unsafe",
            "table",
            page=1,
            html="<table><tr><td>直径</td><td>载荷</td></tr><tr><td>18</td><td>3.6</td><td>4.4</td></tr><tr><td>20</td></tr></table>",
        )
        _blocks, _tree, markdown, _issues = run_postprocessing([table])
        self.assertIn("UNSAFE_TABLE", markdown)
        self.assertIn("RAW_TABLE_TEXT", markdown)
        self.assertIn("18", markdown)
        self.assertNotIn("<table>", markdown)

    def test_numbered_heading_depth_overrides_incorrect_word_style_level(self):
        blocks = [
            Block("chapter", "heading", "2 产品说明", page=1, level=1),
            Block("section-one", "heading", "2.1 整机外形图和部件名称图", page=1, level=2),
            Block("section-two", "heading", "2.2 驾驶室仪表和操纵装置", page=1, level=3),
        ]
        tree = build_heading_tree(blocks)
        chapter = tree[0]
        self.assertEqual(["section-one", "section-two"], [node["id"] for node in chapter["children"]])

    def test_missing_native_body_line_is_recovered_on_low_coverage_page(self):
        page = Page(13, 600, 800, "/13", attributes={"native_text_coverage": {"text_shingle_recall": 0.8, "number_recall": 1.0}})
        blocks = [Block("tail", "paragraph", "零件的原始位置，产生严重的事故。", 13, BBox(70, 205, 300, 218))]
        native = [
            Block("full-warning", "native_line", "用一根钢丝绳起吊零件时，可能会使零件转动，钢丝绳捻松或滑离缠绕", 13, BBox(70, 175, 520, 198), attributes={"native_pdf_line": True}),
            Block("tail-native", "native_line", "零件的原始位置，产生严重的事故。", 13, BBox(70, 205, 300, 218), attributes={"native_pdf_line": True}),
        ]
        parsed, _tree, _markdown, issues = run_postprocessing(blocks, native, [page])
        self.assertTrue(any("钢丝绳捻松" in block.text for block in parsed))
        self.assertTrue(any(issue.code == "native_text_recovered" for issue in issues))

    def test_ooxml_table_grid_is_qa_eligible(self):
        table = Block(
            "native",
            "table",
            page=1,
            html="<table><tr><th>直径</th><th>载荷</th></tr><tr><td>18</td><td>3.6</td></tr></table>",
            evidence=[Evidence("ooxml", "table:1", 1.0)],
        )
        blocks, _tree, _markdown, _issues = run_postprocessing([table])
        self.assertEqual("verified", blocks[0].attributes["integrity_status"])
        self.assertTrue(blocks[0].attributes["qa_eligible"])

    def test_visual_warning_box_becomes_one_safety_notice(self):
        box = Block(
            "warning-box",
            "table",
            page=3,
            html="<table><tr><td>警告！</td></tr><tr><td>维修前必须切断电源。</td></tr></table>",
        )
        blocks, _tree, _markdown, _issues = run_postprocessing([box])
        self.assertEqual("safety_notice", blocks[0].type)
        self.assertEqual("警告", blocks[0].attributes["warning_level"])
        self.assertEqual("维修前必须切断电源。", blocks[0].attributes["body"])


if __name__ == "__main__":
    unittest.main()

from xc975_pipeline.docmodel import Element, Para, parse_docx
from xc975_pipeline.numbering import (
    cross_check_toc,
    heading_level,
    inject_numbers,
    literal_number,
    parse_toc_entry,
    strip_literal_prefix,
)


def test_heading_style_case_insensitive():
    assert heading_level("heading 3") == 3
    assert heading_level("Heading 2") == 2
    assert heading_level("heading") == 1
    assert heading_level("正文文本") is None


def test_outline_level_fallback():
    assert heading_level("自定义样式", outline_lvl=2) == 3
    assert heading_level("自定义样式", outline_lvl=9) is None


def test_literal_number_b_formats():
    assert literal_number("00 总则") == "0"
    assert literal_number("01 电气") == "1"
    assert literal_number("一、故障表现与诊断排除") == "1"
    assert literal_number("§1.1 范围") == "1.1"
    assert literal_number("1.2.4.1 拆装工序") == "1.2.4.1"
    assert literal_number("10.5.2 手打编号") == "10.5.2"
    assert literal_number("无编号标题") is None


def test_strip_literal_prefix():
    assert strip_literal_prefix("00 总则") == "总则"
    assert strip_literal_prefix("§1.1 范围") == "范围"
    assert strip_literal_prefix("一、故障表现") == "故障表现"
    assert strip_literal_prefix("1.2.4.1 拆装工序") == "拆装工序"


def test_position_derivation(manual_a):
    elements, _ = parse_docx(str(manual_a))
    audit = inject_numbers(elements, "auto")
    assert audit == []
    heads = [(el.编号, el.para.text.strip()) for el in elements if el.heading_level is not None]
    assert ("2.5", "起动之前") in heads
    assert ("2.5.1", "日常检查") in heads
    assert ("3.3.5", "每250小时的保养") in heads
    assert ("3.10.1", "行走电控") in heads
    assert len(heads) == 25


def test_parse_toc_entry():
    assert parse_toc_entry("2.5.1 日常检查\t57") == ("2.5.1", "日常检查", "57")
    assert parse_toc_entry("2.2.6 蓄电池断路开关......... 30") == ("2.2.6", "蓄电池断路开关", "30")
    assert parse_toc_entry("2 操作") == ("2", "操作", None)


def test_cross_check_toc_reports_stale_and_conflict():
    el = Element("para", 0, para=Para(style="heading 1", text="日常检查"))
    el.heading_level = 1
    el.编号 = "2.5.1"
    msgs = cross_check_toc([el], [("2.5.1", "日常检查", "57"), ("2.2.6", "蓄电池断路开关", "30")])
    assert len(msgs) == 1 and "陈旧" in msgs[0]
    msgs = cross_check_toc([el], [("9.9", "日常检查", "57")])
    assert len(msgs) == 1 and "不一致" in msgs[0]


def test_cross_check_same_title_pairs_in_order():
    """同名标题（如"电气系统"在保养章与故障章各一次）按出现顺序配对，不误报。"""
    els = []
    for num in ("2.3.4", "3.5.1"):
        el = Element("para", 0, para=Para(style="heading 2", text="电气系统"))
        el.heading_level = 2
        el.编号 = num
        els.append(el)
    assert cross_check_toc(els, [("2.3.4", "电气系统", "1"), ("3.5.1", "电气系统", "2")]) == []
    msgs = cross_check_toc(els, [("9.9", "电气系统", "1")])
    assert len(msgs) == 1 and "不一致" in msgs[0]

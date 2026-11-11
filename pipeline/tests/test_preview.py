from types import SimpleNamespace

import pytest

from xc975_pipeline import webapp
from xc975_pipeline.preview import build_page_map, render_page_png
from xc975_pipeline.runner import run_stages


@pytest.fixture
def client(manual_a, tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(webapp, "RUNS_ROOT", runs)
    meta = run_stages(str(manual_a), "A", "国内干桥", "202608", runs)
    return webapp.app.test_client(), meta["run_id"], runs


def test_preview_render_on_demand(client, monkeypatch):
    client, run_id, runs = client
    r = client.get(f"/api/runs/{run_id}/preview")
    assert r.get_json()["文件"] is None

    def fake_render(source, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "manual_A.pdf").write_bytes(b"%PDF-1.4 fake")
        return "manual_A.pdf"

    monkeypatch.setattr(webapp, "render_preview", fake_render)
    r = client.post(f"/api/runs/{run_id}/preview")
    assert r.status_code == 200 and r.get_json()["文件"] == "manual_A.pdf"
    # 假 PDF 无法构建分页映射，但预览本身可用
    assert r.get_json()["页数"] == 0

    # 已生成则复用，不再调用转换器
    def fail_render(*args):
        raise RuntimeError("不应再调用")

    monkeypatch.setattr(webapp, "render_preview", fail_render)
    assert client.post(f"/api/runs/{run_id}/preview").status_code == 200


def test_preview_unavailable(client, monkeypatch):
    client, run_id, _ = client

    def fail_render(*args):
        raise RuntimeError("未检测到 LibreOffice")

    monkeypatch.setattr(webapp, "render_preview", fail_render)
    r = client.post(f"/api/runs/{run_id}/preview")
    assert r.status_code == 503
    assert "LibreOffice" in r.get_json()["error"]


def test_toc_entries_map_and_body_skips_toc_page(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "前言 正文内容", fontname="china-s")
    pdf.new_page().insert_text((72, 72), "目录\n一、安全注意事项…………3\n00 总则…………2\n二、如何阅读使用本手册……6", fontname="china-s")
    pdf.new_page().insert_text((72, 72), "一、安全注意事项 正文", fontname="china-s")
    pdf_path = tmp_path / "toc.pdf"
    pdf.save(pdf_path)
    pdf.close()
    elements = [
        SimpleNamespace(kind="para", index=0, para=SimpleNamespace(text="一、安全注意事项\t3", style="toc 2")),
        SimpleNamespace(kind="para", index=1, para=SimpleNamespace(text="一、安全注意事项", style="Heading 2")),
    ]
    info = build_page_map(pdf_path, elements)
    assert info["元素页"]["0"] == 2  # 目录条目 → 目录页
    assert info["元素页"]["1"] == 3  # 正文标题 → 正文页，不错配到目录


def test_table_maps_via_first_cell_when_header_split(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = pymupdf.open()
    # 列头排在表题之前：整行拼接不连续，需退化为首格匹配
    pdf.new_page().insert_text((72, 72), "钢丝绳直径(mm)\n容许载荷(t)\n钢丝绳（标准的S型钢丝绳）", fontname="china-s")
    pdf_path = tmp_path / "tbl.pdf"
    pdf.save(pdf_path)
    pdf.close()
    grid = [["钢丝绳（标准的S型钢丝绳）", "钢丝绳直径(mm)", "容许载荷(t)"], ["10", "1.0"]]
    elements = [SimpleNamespace(kind="table", index=0, table=SimpleNamespace(grid=grid))]
    info = build_page_map(pdf_path, elements)
    assert info["元素页"]["0"] == 1


def test_page_map_and_png(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = pymupdf.open()
    page1 = pdf.new_page()
    page1.insert_text((72, 72), "第一章 总则 内容与保养手册", fontname="china-s")
    page1.insert_text((72, 100), "续行更多内容", fontname="china-s")
    pdf.new_page().insert_text((72, 72), "日常检查 为了最大限度地延长机器的使用寿命", fontname="china-s")
    pdf_path = tmp_path / "a.pdf"
    pdf.save(pdf_path)
    pdf.close()

    elements = [
        SimpleNamespace(kind="para", index=0, para=SimpleNamespace(text="第一章 总则 内容与保养手册续行更多内容")),
        SimpleNamespace(kind="para", index=1, para=SimpleNamespace(text="为了最大限度地延长机器的使用寿命")),
        SimpleNamespace(kind="para", index=2, para=SimpleNamespace(text="不存在的内容XYZ不存在的内容")),
        SimpleNamespace(kind="para", index=3, para=SimpleNamespace(text="短")),  # 太短不映射
    ]
    info = build_page_map(pdf_path, elements)
    assert info["页数"] == 2
    assert info["元素页"] == {"0": 1, "1": 2}
    # 区域：每个命中元素都落到所在页的某个文本块上
    assert info["区域"][1][0]["ids"] == [0]
    assert info["区域"][2][0]["ids"] == [1]
    box = info["区域"][1][0]["box"]
    assert len(box) == 4 and all(0 <= v <= 100 for v in box)
    # 多行文本块归并为段落级区域：高度覆盖两行，而不是只有首行
    assert box[3] > 3

    out = render_page_png(pdf_path, 2, tmp_path / "page_2.png")
    assert out.read_bytes().startswith(b"\x89PNG")
    with pytest.raises(ValueError):
        render_page_png(pdf_path, 3, tmp_path / "page_3.png")


def test_short_last_line_is_included_in_element_region(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "严禁在提升机或起重机吊起部件的状态下，对该部件进行", fontname="china-s")
    page.insert_text((72, 98), "维修。", fontname="china-s")
    pdf_path = tmp_path / "short-last-line.pdf"
    pdf.save(pdf_path)
    pdf.close()
    elements = [
        SimpleNamespace(
            kind="para",
            index=220,
            para=SimpleNamespace(text="严禁在提升机或起重机吊起部件的状态下，对该部件进行维修。", style="Normal"),
        )
    ]

    info = build_page_map(pdf_path, elements)

    box = info["区域"][1][0]["box"]
    assert box[3] > 3


def test_short_paragraphs_map_by_exact_pdf_line(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "准备工作", fontname="china-s")
    page.insert_text((72, 98), "维修", fontname="china-s")
    pdf_path = tmp_path / "short-paragraphs.pdf"
    pdf.save(pdf_path)
    pdf.close()
    elements = [
        SimpleNamespace(kind="para", index=210, para=SimpleNamespace(text="准备工作", style="Subtitle")),
        SimpleNamespace(kind="para", index=211, para=SimpleNamespace(text="维修", style="Normal")),
    ]

    info = build_page_map(pdf_path, elements)

    assert info["元素页"] == {"210": 1, "211": 1}
    assert [region["ids"] for region in info["区域"][1]] == [[210], [211]]


def test_repeated_short_text_maps_to_successive_lines(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "总则", fontname="china-s")
    pdf.new_page().insert_text((72, 72), "总则", fontname="china-s")
    pdf_path = tmp_path / "repeated-short-text.pdf"
    pdf.save(pdf_path)
    pdf.close()
    elements = [
        SimpleNamespace(kind="para", index=38, para=SimpleNamespace(text="总则", style="Normal")),
        SimpleNamespace(kind="para", index=192, para=SimpleNamespace(text="总则", style="Heading 1")),
    ]

    info = build_page_map(pdf_path, elements)

    assert info["元素页"] == {"38": 1, "192": 2}


def test_paragraph_split_across_pages_maps_both_pages(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    first_page_text = "8）务必将所有部件按原位组装。用新部件更换任何损坏的部件和"
    second_page_text = "不能重复使用的部件。安装软管和导线时应注意避免在机器工作时被其它部件擦伤。"
    pdf = pymupdf.open()
    first_page = pdf.new_page()
    first_page.insert_text((72, 720), first_page_text, fontname="china-s")
    first_page.insert_text((72, 760), "3", fontname="china-s")
    pdf.new_page().insert_text((72, 72), second_page_text, fontname="china-s")
    pdf_path = tmp_path / "cross-page.pdf"
    pdf.save(pdf_path)
    pdf.close()
    elements = [
        SimpleNamespace(
            kind="para",
            index=223,
            para=SimpleNamespace(text=first_page_text + second_page_text, style="Normal"),
        )
    ]

    info = build_page_map(pdf_path, elements)

    assert info["元素页"]["223"] == 1
    assert info["元素页组"]["223"] == [1, 2]
    assert info["区域"][1][0]["ids"] == [223]
    assert info["区域"][2][0]["ids"] == [223]


def test_table_with_short_header_maps_and_highlights_all_rows(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    following_text = "下表与图B中的螺栓相对应"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "螺栓螺径", fontname="china-s")
    page.insert_text((72, 98), "mm mm Nm kgm", fontname="china-s")
    page.insert_text((72, 124), "6 10 11.8-14.7 1.2-1.5", fontname="china-s")
    page.insert_text((72, 180), following_text, fontname="china-s")
    page.insert_text((72, 210), "螺栓螺径", fontname="china-s")
    page.insert_text((72, 236), "mm mm Nm kgm", fontname="china-s")
    page.insert_text((72, 262), "6 10 5.9-9.8 0.6-1.0", fontname="china-s")
    page.insert_text((72, 300), "图A", fontname="china-s")
    pdf_path = tmp_path / "short-table-header.pdf"
    pdf.save(pdf_path)
    pdf.close()
    grid = [
        ["螺栓螺径", "对边宽度", "紧固扭矩", "紧固扭矩"],
        ["mm", "mm", "Nm", "kgm"],
        ["6", "10", "11.8-14.7", "1.2-1.5"],
    ]
    second_grid = [grid[0], grid[1], ["6", "10", "5.9-9.8", "0.6-1.0"]]
    elements = [
        SimpleNamespace(kind="table", index=288, table=SimpleNamespace(grid=grid)),
        SimpleNamespace(kind="para", index=289, para=SimpleNamespace(text=following_text, style="Normal")),
        SimpleNamespace(kind="table", index=290, table=SimpleNamespace(grid=second_grid)),
        SimpleNamespace(kind="para", index=291, para=SimpleNamespace(text="图A", style="Normal")),
    ]

    info = build_page_map(pdf_path, elements)

    assert info["元素页"] == {"288": 1, "289": 1, "290": 1, "291": 1}
    for element_id in (288, 290):
        regions = [region for region in info["区域"][1] if region["ids"] == [element_id]]
        assert len(regions) == 1
        assert regions[0]["box"][3] > 3


def test_image_only_paragraph_maps_pdf_image_blocks(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from conftest import TINY_PNG

    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "图A 图B", fontname="china-s")
    page.insert_image(pymupdf.Rect(72, 120, 200, 250), stream=TINY_PNG)
    page.insert_image(pymupdf.Rect(300, 120, 500, 250), stream=TINY_PNG)
    page.insert_text((72, 300), "紧固扭矩表", fontname="china-s")
    pdf_path = tmp_path / "image-only.pdf"
    pdf.save(pdf_path)
    pdf.close()
    elements = [
        SimpleNamespace(kind="para", index=291, para=SimpleNamespace(text="图A 图B", image_rids=[], style="Normal")),
        SimpleNamespace(kind="para", index=292, para=SimpleNamespace(text=" ", image_rids=["r1", "r2"], style="Caption")),
        SimpleNamespace(kind="para", index=293, para=SimpleNamespace(text="紧固扭矩表", image_rids=[], style="Subtitle")),
    ]

    info = build_page_map(pdf_path, elements)

    assert info["元素页"]["292"] == 1
    assert info["元素页组"]["292"] == [1]
    image_regions = [region for region in info["区域"][1] if region["ids"] == [292]]
    assert len(image_regions) == 2


def test_unmapped_element_retries_all_pages_after_forward_miss(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "电气系统", fontname="china-s")
    pdf.new_page().insert_text((72, 72), "电气系统", fontname="china-s")
    pdf.new_page().insert_text((72, 72), "这是一个足够长的测试段落内容", fontname="china-s")
    pdf_path = tmp_path / "forward-miss.pdf"
    pdf.save(pdf_path)
    pdf.close()
    elements = [
        SimpleNamespace(kind="para", index=0, para=SimpleNamespace(text="这是一个足够长的测试段落内容", style="Normal")),
        SimpleNamespace(kind="para", index=1, para=SimpleNamespace(text="电气系统", style="Heading 1")),
        SimpleNamespace(kind="para", index=2, para=SimpleNamespace(text="电气系统", style="Heading 1")),
    ]

    info = build_page_map(pdf_path, elements)

    assert info["元素页"] == {"0": 3, "1": 1, "2": 2}
    assert info["区域"][2][0]["ids"] == [2]

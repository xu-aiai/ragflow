"""PROTOTYPE：用自部署 JEV-27B-VL 检查真实版面元素，不写入解析结果。"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
JEV_REPO = Path(os.environ.get("JEV_REPO", r"D:\repository\JEV-27B-DEMO"))
sys.path.insert(0, str(JEV_REPO / "common"))
from jev_client import decide, decide_mm  # noqa: E402

RUN = "20261104_085807_B"
RUN_DIR = HERE / "runs" / RUN
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONTENT_OPTIONS = [
    "完整：解析内容覆盖原图，文字、数字和表格对应关系没有影响使用的错误",
    "识别不完整：原图清晰，但解析结果存在缺字、漏行、错并、错位或截断",
    "原文不清：原图模糊、遮挡或分辨率不足，无法可靠核对",
    "无法判断：现有图文信息不足以得出结论",
]
REPAIR_OPTIONS = [
    "无需处理：当前解析结果可以直接使用",
    "换解析器：原图清晰完整，当前解析器遗漏或识别错误，换一种版面解析方法可能恢复",
    "人工修正：适合人工对照原图局部修正，或自动解析难以可靠恢复",
    "人工复核：无法确定最佳处理方式，需要人先判断",
]
BOUNDARY_OPTIONS = [
    "独立完整：当前元素自身句意和条目完整，不需要与相邻元素合并",
    "需与上一块合并：当前元素是上一元素的续句、续项或被拆开的后半部分",
    "需与下一块合并：当前元素的句意或条目在下一元素才完整",
    "三块需要合并：上一、当前、下一元素共同表达一个被拆开的句意或条目",
    "无法判断：相邻内容不足或关系不清楚",
]


def page_result(method: str, page: int) -> dict:
    return json.loads((RUN_DIR / "parse" / method / f"page_{page}.json").read_text(encoding="utf-8"))


def block_context(method: str, page: int, block_id: str) -> tuple[dict, dict]:
    result = page_result(method, page)
    index = next(i for i, block in enumerate(result["块"]) if str(block["ID"]) == block_id)
    blocks = result["块"]
    context = {
        "上一元素": {"类型": blocks[index - 1]["类型"], "内容": blocks[index - 1]["内容"]} if index else None,
        "当前元素": blocks[index],
        "下一元素": {"类型": blocks[index + 1]["类型"], "内容": blocks[index + 1]["内容"]} if index + 1 < len(blocks) else None,
    }
    return blocks[index], context


def crop_image(page: int, block: dict) -> str:
    pdf_path = next((RUN_DIR / "preview").glob("*.pdf"))
    left, top, width, height = block["区域"]
    with pymupdf.open(pdf_path) as pdf:
        source_page = pdf[page - 1]
        clip = pymupdf.Rect(
            source_page.rect.x0 + source_page.rect.width * left / 100,
            source_page.rect.y0 + source_page.rect.height * top / 100,
            source_page.rect.x0 + source_page.rect.width * (left + width) / 100,
            source_page.rect.y0 + source_page.rect.height * (top + height) / 100,
        )
        image = source_page.get_pixmap(dpi=150, clip=clip, alpha=False).tobytes("png")
    return "data:image/png;base64," + base64.b64encode(image).decode("ascii")


def ranked(probabilities: dict[str, float]) -> dict:
    return {
        "选择": max(probabilities, key=probabilities.get),
        "概率": {key: round(value, 4) for key, value in sorted(probabilities.items(), key=lambda item: -item[1])},
    }


def judge(method: str, page: int, block_id: str, semantic_only: bool = False) -> dict:
    block, context = block_context(method, page, block_id)
    started = time.perf_counter()
    output = {"解析器": method, "页": page, "块": block_id, "类型": block["类型"]}
    if not semantic_only:
        state = [
            "以下是版面解析后的一个元素及其原图。只核对当前元素，不要把相邻元素的文字算作当前元素必须包含的内容。\n"
            + json.dumps(context, ensure_ascii=False)
            + "\n当前元素原图：",
            {"image": crop_image(page, block)},
        ]
        content = decide_mm(
            "choice",
            state,
            "当前元素的解析内容是否完整、准确地覆盖了它自己的原图？只判断内容识别，不判断是否应与相邻元素合并。",
            CONTENT_OPTIONS,
        )
        repair = decide_mm(
            "choice",
            state,
            "针对当前元素的内容识别质量，最合适的处理方式是什么？",
            REPAIR_OPTIONS,
        )
        output["内容完整性"] = ranked(content)
        output["修复建议"] = ranked(repair)
    else:
        boundary = decide(
            "choice",
            context,
            "当前元素在语义上是独立完整的，还是被错误拆分、需要与相邻元素合并？只判断句意和条目边界，不判断 OCR 错字。",
            BOUNDARY_OPTIONS,
        )
        output["语义边界"] = ranked(boundary)
    output["耗时秒"] = round(time.perf_counter() - started, 3)
    return output


def main() -> None:
    cases = [
        ("ragflow", 14, "314", False, "DeepDoc 错位表格"),
        ("paddleocr", 14, "12", False, "PaddleOCR-VL 正确表格"),
        ("ragflow", 14, "307", True, "明显断句的前半段"),
        ("ragflow", 14, "308", True, "明显断句的后半段"),
        ("ragflow", 14, "312", True, "正常独立段落"),
    ]
    for method, page, block_id, semantic_only, title in cases:
        print(f"\n=== {title} ===")
        print(json.dumps(judge(method, page, block_id, semantic_only), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

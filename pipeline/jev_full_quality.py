"""EVALUATION RUNNER：自部署 JEV 全文质检，按页保存，可断点续跑。"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import base64
import json
import os
import sys
import time
from pathlib import Path

import pymupdf

from jev_quality_prototype import BOUNDARY_OPTIONS, CONTENT_OPTIONS, REPAIR_OPTIONS, ranked
from jev_client import decide, decide_mm

HERE = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SEMANTIC_SKIP_TYPES = {"table", "figure", "image", "equation"}


def _crop(pdf_page, region: list[float]) -> str:
    left, top, width, height = region
    clip = pymupdf.Rect(
        pdf_page.rect.x0 + pdf_page.rect.width * left / 100,
        pdf_page.rect.y0 + pdf_page.rect.height * top / 100,
        pdf_page.rect.x0 + pdf_page.rect.width * (left + width) / 100,
        pdf_page.rect.y0 + pdf_page.rect.height * (top + height) / 100,
    )
    image = pdf_page.get_pixmap(dpi=150, clip=clip, alpha=False).tobytes("png")
    return "data:image/png;base64," + base64.b64encode(image).decode("ascii")


def _context(blocks: list[dict], index: int) -> dict:
    block = blocks[index]
    return {
        "上一元素": {"类型": blocks[index - 1]["类型"], "内容": blocks[index - 1]["内容"]} if index else None,
        "当前元素": block,
        "下一元素": {"类型": blocks[index + 1]["类型"], "内容": blocks[index + 1]["内容"]} if index + 1 < len(blocks) else None,
    }


def _judge(block: dict, context: dict, image: str | None) -> dict:
    result = {}
    try:
        state = [
            "以下是版面解析后的一个元素及其原图。只核对当前元素，不要把相邻元素的文字算作当前元素必须包含的内容。\n"
            + json.dumps(context, ensure_ascii=False)
            + "\n当前元素原图：",
            {"image": image},
        ] if image else context
        chooser = decide_mm if image else decide
        content = chooser(
            "choice",
            state,
            "当前元素的解析内容是否完整、准确地覆盖了它自己的原图？只判断内容识别，不判断是否应与相邻元素合并。",
            CONTENT_OPTIONS,
        )
        result["内容完整性"] = ranked(content)
        if max(content, key=content.get).startswith("识别不完整"):
            repair = chooser(
                "choice",
                state,
                "针对当前元素的内容识别质量，最合适的处理方式是什么？",
                REPAIR_OPTIONS,
            )
            result["修复建议"] = ranked(repair)
        if str(block.get("类型", "")).lower() not in SEMANTIC_SKIP_TYPES and block.get("内容"):
            boundary = decide(
                "choice",
                context,
                "当前元素在语义上是独立完整的，还是被错误拆分、需要与相邻元素合并？只判断句意和条目边界，不判断 OCR 错字。",
                BOUNDARY_OPTIONS,
            )
            result["语义边界"] = ranked(boundary)
    except Exception as exc:
        result["错误"] = f"{type(exc).__name__}: {exc}"
    return result


def process_page(pdf_path: Path, result_path: Path, output_path: Path, workers: int) -> dict:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    blocks = result.get("块", [])
    page_number = result["页"]
    existing = {}
    if output_path.is_file():
        existing = json.loads(output_path.read_text(encoding="utf-8")).get("块", {})
    pending = [i for i, block in enumerate(blocks) if str(block["ID"]) not in existing or "错误" in existing[str(block["ID"])]]
    judgments = dict(existing)
    if pending:
        with pymupdf.open(pdf_path) as pdf:
            page = pdf[page_number - 1]
            inputs = []
            for index in pending:
                block = blocks[index]
                image = _crop(page, block["区域"]) if block.get("区域") else None
                inputs.append((block, _context(blocks, index), image))
        with cf.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_judge, *item): item[0] for item in inputs}
            for future in cf.as_completed(futures):
                block = futures[future]
                judgments[str(block["ID"])] = future.result()
    output = {"页": page_number, "方式": "ragflow", "模型": "autotrust/JEV-27B-VL", "块": judgments}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    temporary.replace(output_path)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="20261104_085807_B")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--pages", type=int, nargs="*")
    args = parser.parse_args()
    workers = max(1, min(8, args.workers))
    run_dir = HERE / "runs" / args.run
    pdf_path = next((run_dir / "preview").glob("*.pdf"))
    result_paths = sorted((run_dir / "parse" / "ragflow").glob("page_*.json"), key=lambda p: int(p.stem.split("_")[1]))
    if args.pages:
        wanted = set(args.pages)
        result_paths = [path for path in result_paths if int(path.stem.split("_")[1]) in wanted]
    started = time.perf_counter()
    total = complete = incomplete = failed = 0
    for index, result_path in enumerate(result_paths, 1):
        page_started = time.perf_counter()
        page_number = int(result_path.stem.split("_")[1])
        output = process_page(
            pdf_path,
            result_path,
            run_dir / "quality" / "ragflow" / f"page_{page_number}.json",
            workers,
        )
        values = list(output["块"].values())
        page_complete = sum(v.get("内容完整性", {}).get("选择", "").startswith("完整") for v in values)
        page_incomplete = sum(v.get("内容完整性", {}).get("选择", "").startswith("识别不完整") for v in values)
        page_failed = sum("错误" in v for v in values)
        total += len(values)
        complete += page_complete
        incomplete += page_incomplete
        failed += page_failed
        print(
            f"[{index}/{len(result_paths)}] 第 {page_number} 页：元素 {len(values)}，完整 {page_complete}，"
            f"不完整 {page_incomplete}，失败 {page_failed}，耗时 {time.perf_counter() - page_started:.1f}s",
            flush=True,
        )
    print(
        f"完成：元素 {total}，完整 {complete}，不完整 {incomplete}，失败 {failed}，"
        f"总耗时 {time.perf_counter() - started:.1f}s",
        flush=True,
    )


if __name__ == "__main__":
    main()

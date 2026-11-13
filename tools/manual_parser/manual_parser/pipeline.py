from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from pathlib import Path

from .deepdoc_engine import parse_pdf_with_deepdoc
from .docx_native import parse_docx
from .fusion import fuse_ooxml_and_visual
from .model import DocumentResult, ParseIssue
from .native_pdf import extract_native_pdf_lines, measure_native_pdf_coverage, recover_native_pdf_tables
from .office import prepare_office_document
from .postprocess import run_postprocessing
from .render import render_pdf_pages
from .vlm import RegionVisionRecognizer

Progress = Callable[[float, str], None]
PIPELINE_REVISION = "xcmg-manual-parser/2.6.0"


def _stage_record(name: str, component: str, started: float, **details) -> dict:
    return {"name": name, "component": component, "elapsed_seconds": round(time.perf_counter() - started, 3), **details}


class ManualParsingPipeline:
    def __init__(self) -> None:
        self.vlm = RegionVisionRecognizer()

    @property
    def cache_signature(self) -> str:
        return f"{PIPELINE_REVISION}|vlm={int(self.vlm.enabled)}|model={self.vlm.model}"

    def parse(self, job_id: str, source: Path, job_dir: Path, progress: Progress) -> DocumentResult:
        suffix = source.suffix.lower()
        if suffix not in {".pdf", ".doc", ".docx"}:
            raise ValueError("仅支持 .pdf、.doc、.docx")
        work_dir = job_dir / "work"
        pages_dir = job_dir / "pages"
        regions_dir = job_dir / "regions"
        assets_dir = job_dir / "assets"
        for directory in (work_dir, pages_dir, regions_dir, assets_dir):
            directory.mkdir(parents=True, exist_ok=True)
        stages: list[dict] = []
        issues: list[ParseIssue] = []
        total_started = time.perf_counter()

        progress(0.02, "准备文档")
        stage = time.perf_counter()
        native_docx: Path | None = None
        if suffix == ".pdf":
            visual_pdf = work_dir / "source.pdf"
            shutil.copy2(source, visual_pdf)
        else:
            native_docx, visual_pdf = prepare_office_document(source, work_dir)
        stages.append(_stage_record("normalize", "LibreOffice/native PDF", stage, visual_pdf=visual_pdf.name, has_ooxml=bool(native_docx)))

        progress(0.08, "生成页面预览")
        stage = time.perf_counter()
        pages = render_pdf_pages(visual_pdf, pages_dir, f"/api/jobs/{job_id}/pages")
        stages.append(_stage_record("render", "PDFium", stage, page_count=len(pages)))

        progress(0.14, "DeepDOC 版面解析")
        stage = time.perf_counter()

        def deepdoc_progress(value: float, message: str) -> None:
            progress(0.14 + max(0.0, min(1.0, value)) * 0.54, message)

        visual_blocks = parse_pdf_with_deepdoc(visual_pdf, regions_dir, f"/api/jobs/{job_id}/regions", pages, deepdoc_progress)
        stages.append(_stage_record("deepdoc", "RAGFlow DeepDOC OCR + layout + table", stage, block_count=len(visual_blocks)))

        progress(0.69, "核对 PDF 原生文字坐标")
        stage = time.perf_counter()
        toc_starts = {
            block.page
            for block in visual_blocks
            if block.page and "目录" in "".join(block.text.split()) and len(block.text) <= 24
        }
        toc_pages = {
            page_number
            for start in toc_starts
            for page_number in range(start, min(len(pages), start + 11) + 1)
        }
        try:
            native_pdf_lines = extract_native_pdf_lines(visual_pdf)
        except Exception as exc:  # noqa: BLE001 - DeepDOC remains the fallback for scans/encrypted PDFs
            native_pdf_lines = []
            issues.append(ParseIssue("native_text_unavailable", f"PDF 原生文字层不可用：{type(exc).__name__}", "info"))
        stages.append(
            _stage_record(
                "native_pdf_evidence",
                "pdfplumber native text coordinates",
                stage,
                candidate_pages=len(pages),
                toc_candidate_pages=len(toc_pages),
                line_count=len(native_pdf_lines),
            )
        )

        progress(0.70, "校验 PDF 原生表格网格")
        stage = time.perf_counter()
        try:
            if native_docx:
                native_table_metrics = {"candidate_count": 0, "recovered_count": 0, "rejected_count": 0, "skipped_for_ooxml": True}
            else:
                table_issues, native_table_metrics = recover_native_pdf_tables(visual_pdf, visual_blocks)
                issues.extend(table_issues)
        except Exception as exc:  # noqa: BLE001 - native grid is an enhancement, not the only table channel
            native_table_metrics = {"candidate_count": 0, "recovered_count": 0, "rejected_count": 0}
            issues.append(ParseIssue("native_table_unavailable", f"PDF 原生表格校验不可用：{type(exc).__name__}", "info"))
        stages.append(_stage_record("native_table_grid", "pdfplumber coordinates + ruled table recovery", stage, **native_table_metrics))

        progress(0.72, "核对 PDF 原生文字覆盖率")
        stage = time.perf_counter()
        if not native_docx:
            try:
                coverage_issues = measure_native_pdf_coverage(visual_pdf, visual_blocks, pages)
            except Exception as exc:  # noqa: BLE001 - scans legitimately have no native text channel
                coverage_issues = []
                issues.append(ParseIssue("native_coverage_unavailable", f"PDF 原生文字覆盖核对不可用：{type(exc).__name__}", "info"))
            issues.extend(coverage_issues)
            stages.append(_stage_record("native_text_coverage", "PDF text-layer coverage guard", stage, issue_count=len(coverage_issues)))

        if native_docx:
            progress(0.73, "读取 DOCX 原生结构")
            stage = time.perf_counter()
            native_blocks = parse_docx(native_docx, assets_dir, f"/api/jobs/{job_id}/assets")
            blocks = fuse_ooxml_and_visual(native_blocks, visual_blocks, pages, native_pdf_lines)
            stages.append(
                _stage_record(
                    "structure_fusion",
                    "OOXML + native PDF + DeepDOC evidence fusion",
                    stage,
                    native_blocks=len(native_blocks),
                    fused_blocks=len(blocks),
                    aligned_blocks=sum(bool(block.attributes.get("alignment_channel")) for block in blocks),
                    inferred_page_blocks=sum(bool(block.attributes.get("page_inferred")) for block in blocks),
                    visual_fallback_blocks=sum(block.attributes.get("fusion_role") == "visual_fallback" for block in blocks),
                    native_fallback_blocks=sum(block.attributes.get("fusion_role") == "native_pdf_fallback" for block in blocks),
                )
            )
            coverage_stage = time.perf_counter()
            try:
                coverage_issues = measure_native_pdf_coverage(visual_pdf, blocks, pages)
            except Exception as exc:  # noqa: BLE001 - converted PDFs may still have an unavailable text layer
                coverage_issues = []
                issues.append(ParseIssue("native_coverage_unavailable", f"DOCX 转换 PDF 的原生文字覆盖核对不可用：{type(exc).__name__}", "info"))
            issues.extend(coverage_issues)
            stages.append(
                _stage_record(
                    "native_text_coverage",
                    "converted PDF text-layer coverage guard",
                    coverage_stage,
                    issue_count=len(coverage_issues),
                )
            )
        else:
            blocks = visual_blocks

        progress(0.76, "区域视觉理解")
        stage = time.perf_counter()

        def vlm_progress(value: float, message: str) -> None:
            progress(0.76 + max(0.0, min(1.0, value)) * 0.14, message)

        blocks, vlm_issues, vlm_metrics = self.vlm.enhance(blocks, job_dir, vlm_progress)
        issues.extend(vlm_issues)
        stages.append(_stage_record("region_vlm", "PaddleOCR-VL region recognizer", stage, **vlm_metrics))

        progress(0.91, "重建文档结构与跨页关系")
        stage = time.perf_counter()
        blocks, tree, markdown, post_issues = run_postprocessing(blocks, native_pdf_lines, pages)
        issues.extend(post_issues)
        for page in pages:
            page.block_ids = [
                block.id
                for block in blocks
                if block.page == page.number or any(item.get("page") == page.number for item in block.attributes.get("position_slices", []))
            ]
        stages.append(_stage_record("manual_reconstruction", "XCMG manual rules + document tree", stage, heading_count=sum(1 for block in blocks if block.type == "heading"), table_count=sum(1 for block in blocks if block.type == "table")))

        progress(0.99, "保存统一结果")
        metrics = {
            "elapsed_seconds": round(time.perf_counter() - total_started, 3),
            "page_count": len(pages),
            "block_count": len(blocks),
            "type_counts": {kind: sum(1 for block in blocks if block.type == kind) for kind in sorted({block.type for block in blocks})},
            "vlm": vlm_metrics,
            "issue_count": len(issues),
            "page_coverage": {
                str(page.number): page.attributes.get("coverage", {}) for page in pages
            },
        }
        return DocumentResult(job_id, source.name, suffix.lstrip("."), pages, blocks, tree, markdown, issues, metrics, stages)

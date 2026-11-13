from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from collections.abc import Callable
from pathlib import Path
from urllib.request import Request, urlopen

from .model import Block, Evidence, ParseIssue
from .postprocess import anchor_recall

SYSTEM_PROMPT = """你是工程机械手册的版面区域识别器。只转录图片中能看到的内容，不补写常识。
返回严格 JSON：{"type":"paragraph|heading|table|figure|caption|warning|equation","text":"...","html":"...","description":"...","confidence":0.0}。
表格必须在 html 中保留行列、rowspan 和 colspan；警告框保留等级；示意图只描述可见部件、箭头和标注。
所有型号、故障码、针脚号、数值和单位必须逐字保留，不确定字符用 [?]，不得猜测。"""


def _extract_json(content: str) -> dict:
    content = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL | re.IGNORECASE)
    if fenced:
        content = fenced.group(1)
    else:
        start, end = content.find("{"), content.rfind("}")
        if start >= 0 and end > start:
            content = content[start : end + 1]
    value = json.loads(content)
    if not isinstance(value, dict):
        raise TypeError("VLM response is not a JSON object")
    return value


def _find_content_records(value) -> list[dict]:
    records: list[dict] = []
    if isinstance(value, dict):
        if any(key in value for key in ("block_content", "rec_text", "block_label")):
            records.append(value)
        for child in value.values():
            records.extend(_find_content_records(child))
    elif isinstance(value, list):
        for child in value:
            records.extend(_find_content_records(child))
    return records


class RegionVisionRecognizer:
    """Fixed region-level stage using PaddleOCR-VL's pipeline or VLM API."""

    def __init__(self) -> None:
        self.endpoint = os.getenv("MANUAL_PARSER_VLM_ENDPOINT", "").strip()
        self.api_key = os.getenv("MANUAL_PARSER_VLM_API_KEY", "").strip()
        self.model = os.getenv("MANUAL_PARSER_VLM_MODEL", "PaddleOCR-VL-1.6-0.9B").strip()
        self.timeout = int(os.getenv("MANUAL_PARSER_VLM_TIMEOUT", "180"))

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)

    def recognize(self, image_path: Path, block: Block) -> dict:
        if self.endpoint.rstrip("/").endswith("/layout-parsing"):
            return self._recognize_paddle_pipeline(image_path, block)
        return self._recognize_openai(image_path, block)

    def _recognize_paddle_pipeline(self, image_path: Path, block: Block) -> dict:
        prompt_label = "table" if block.type == "table" else "formula" if block.type == "equation" else "ocr"
        payload = {
            "file": base64.b64encode(image_path.read_bytes()).decode("ascii"),
            "fileType": 1,
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useLayoutDetection": False,
            "promptLabel": prompt_label,
            "temperature": 0,
            "prettifyMarkdown": False,
            "returnMarkdownImages": False,
            "visualize": False,
        }
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            response_body = json.loads(response.read().decode("utf-8"))
        pages = response_body.get("result", {}).get("layoutParsingResults", [])
        if not pages:
            raise ValueError(f"PaddleOCR-VL returned no layoutParsingResults: {str(response_body)[:800]}")
        page = pages[0]
        markdown = str((page.get("markdown") or {}).get("text") or "").strip()
        records = _find_content_records(page.get("prunedResult") or {})
        record = records[0] if records else {}
        content = str(record.get("block_content") or record.get("rec_text") or record.get("content") or markdown).strip()
        label = str(record.get("block_label") or record.get("label") or prompt_label).lower()
        mapped_type = {
            "table": "table",
            "formula": "equation",
            "display_formula": "equation",
            "inline_formula": "equation",
            "doc_title": "heading",
            "paragraph_title": "heading",
            "figure_title": "caption",
            "image": "figure",
        }.get(label, block.type)
        candidate = content or markdown
        return {
            "type": mapped_type,
            "text": candidate,
            "html": candidate if "<table" in candidate.lower() else markdown if "<table" in markdown.lower() else "",
            "description": "",
            "confidence": float(record.get("score") or 0.82),
        }

    def _recognize_openai(self, image_path: Path, block: Block) -> dict:
        mime = mimetypes.guess_type(image_path.name)[0] or "image/webp"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"DeepDOC 初判类型={block.type}。请识别这个区域；初始文本仅用于核对字符：{block.text[:1600]}",
                        },
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                    ],
                },
            ],
        }
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
        return _extract_json(str(content))

    def enhance(
        self,
        blocks: list[Block],
        job_dir: Path,
        progress: Callable[[float, str], None] | None = None,
    ) -> tuple[list[Block], list[ParseIssue], dict]:
        if not self.enabled:
            return blocks, [], {"enabled": False, "processed": 0, "accepted": 0, "rejected": 0}
        candidates = [block for block in blocks if block.region_image and block.type in {"table", "figure", "equation", "warning", "heading"}]
        issues: list[ParseIssue] = []
        accepted = 0
        rejected = 0
        for index, block in enumerate(candidates):
            asset_group = "assets" if "/assets/" in block.region_image else "regions"
            image_path = job_dir / asset_group / Path(block.region_image).name
            if not image_path.exists():
                continue
            if progress:
                progress(index / max(1, len(candidates)), f"区域视觉理解 {index + 1}/{len(candidates)}")
            try:
                result = self.recognize(image_path, block)
                candidate_text = str(result.get("text") or "").strip()
                candidate_html = str(result.get("html") or "").strip()
                confidence = max(0.0, min(1.0, float(result.get("confidence") or 0.0)))
                reference = block.html or block.text
                candidate = candidate_html or candidate_text
                recall = anchor_recall(reference, candidate)
                block.attributes["vlm"] = {"confidence": confidence, "anchor_recall": recall, "model": self.model}
                if reference and recall < 0.8:
                    rejected += 1
                    issues.append(ParseIssue("vlm_anchor_conflict", f"视觉模型遗漏或修改了关键编号/数值，已保留原结果（锚点召回 {recall:.0%}）", "warning", block.id, block.page))
                    continue
                if confidence < 0.55:
                    rejected += 1
                    continue
                recognized_type = str(result.get("type") or "").strip().lower()
                if recognized_type in {"paragraph", "heading", "table", "figure", "caption", "warning", "equation"}:
                    block.type = recognized_type
                has_native_table = block.type == "table" and any(evidence.channel == "ooxml" for evidence in block.evidence)
                if candidate_text and not has_native_table:
                    block.text = candidate_text
                if candidate_html and "<table" in candidate_html.lower() and not has_native_table:
                    block.html = candidate_html
                if has_native_table:
                    block.attributes["vlm_validated_native_table"] = True
                description = str(result.get("description") or "").strip()
                if description:
                    block.attributes["visual_description"] = description
                block.confidence = max(block.confidence, confidence)
                block.evidence.append(Evidence("region_vlm", block.id, confidence, f"anchor_recall={recall:.3f}"))
                accepted += 1
            except Exception as exc:  # noqa: BLE001 - one failed region must not fail a 250-page job
                rejected += 1
                issues.append(ParseIssue("vlm_error", f"区域视觉理解失败，已保留 DeepDOC/OOXML 结果：{type(exc).__name__}: {exc}", "warning", block.id, block.page))
        return blocks, issues, {"enabled": True, "processed": len(candidates), "accepted": accepted, "rejected": rejected, "model": self.model}

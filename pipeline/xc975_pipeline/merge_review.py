"""规则筛选段落边界，JEV 提供建议，用户确认后才允许合并。"""
from __future__ import annotations

import datetime as dt
import functools
import json
import os
import re
import urllib.request
from pathlib import Path

from .audit import AuditLog
from .convert import convert_to_docx
from .docmodel import parse_docx
from .numbering import inject_numbers
from .products.tree import _is_continuation_text, build_tree

JEV_MODEL = "autotrust/JEV-27B-VL"
_SUGGESTION_ID_RE = re.compile(r"^\d+-\d+$")


def _read(path: Path, default=None):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(path)


def _approved_pairs(run_dir: Path) -> set[tuple[int, int]]:
    overrides = _read(run_dir / "overrides.json", {})
    return {
        (int(pair["previous"]), int(pair["current"]))
        for pair in overrides.get("段落合并", [])
    }


def find_merge_candidates(sections: list[dict], styles: dict[int, str]) -> list[dict]:
    candidates = []
    for section in sections:
        blocks = section.get("blocks", [])
        for index in range(1, len(blocks)):
            previous, current = blocks[index - 1], blocks[index]
            if previous.get("type") != "para" or current.get("type") != "para":
                continue
            if not previous.get("src") or not current.get("src"):
                continue
            previous_id, current_id = previous["src"][-1], current["src"][0]
            if previous_id + 1 != current_id:
                continue
            if (styles.get(previous_id) or "").strip().casefold() != (styles.get(current_id) or "").strip().casefold():
                continue
            previous_text = previous.get("text", "").rstrip()
            current_text = current.get("text", "").lstrip()
            if not _is_continuation_text(previous_text, current_text):
                continue
            candidates.append({
                "id": f"{previous_id}-{current_id}",
                "section_id": section.get("section_id", ""),
                "section_title": section.get("标题", ""),
                "previous": {"element_id": previous_id, "text": previous_text},
                "current": {"element_id": current_id, "text": current_text},
                "merged_text": previous_text + current_text,
                "src": [*previous["src"], *current["src"]],
                "rule": "来源连续、段落样式一致、前段无句末标点",
            })
    return candidates


@functools.lru_cache(maxsize=1)
def _jev_decider():
    base_url = os.environ.get("JEV_URL", "http://localhost:8000").rstrip("/").removesuffix("/v1")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {"Content-Type": "application/json"}
    if os.environ.get("JEV_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['JEV_API_KEY']}"

    def call(path, payload=None, timeout=120):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers)
        with opener.open(req, timeout=timeout) as response:
            return json.load(response)

    try:
        info = call("/v1/decide/info", timeout=15)
    except Exception as exc:
        raise RuntimeError(f"无法连接 JEV 服务 {base_url}：{exc}") from exc
    actual_model = info.get("model")
    if actual_model != JEV_MODEL:
        raise RuntimeError(f"JEV 模型不匹配：需要 {JEV_MODEL}，服务实际为 {actual_model or '未知'}")

    def decide(kind, state, question):
        result = call("/v1/decide", {"kind": kind, "state": state, "question": question})
        return dict(zip(result["options"], result["probabilities"], strict=True))

    return decide


def judge_with_jev(candidate: dict) -> dict[str, float]:
    state = {
        "章节": candidate["section_title"],
        "前一段": candidate["previous"]["text"],
        "后一段": candidate["current"]["text"],
    }
    return _jev_decider()(
        "noul",
        state,
        "后一段是否从句中接续前一段尚未结束的句子，即两段之间的换行是解析或文档转换造成的错误断段？"
        "仅主题相关、引出下文、独立列表项或独立步骤不属于错误断段。",
    )


def _validated_probabilities(value) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != {"false", "true"}:
        raise ValueError("JEV 必须返回 false/true 概率")
    probabilities = {key: float(value[key]) for key in ("false", "true")}
    if any(not 0 <= probability <= 1 for probability in probabilities.values()):
        raise ValueError("JEV 概率必须位于 [0,1]")
    return probabilities


def suggestions_path(run_dir: Path) -> Path:
    return run_dir / "review" / "merge_suggestions.json"


def get_merge_suggestions(run_dir: Path) -> dict:
    return _read(suggestions_path(run_dir), {"模型": JEV_MODEL, "建议": []})


def _candidate_sections(run_dir: Path, stage2: dict) -> list[dict]:
    """从原始文档重建未合并树，兼容旧快照已经自动合并的情况。"""
    meta = _read(run_dir / "run.json", {})
    source = Path(meta.get("输入", ""))
    if not source.is_file():
        return stage2.get("章节", [])
    if source.suffix.lower() == ".doc":
        source = convert_to_docx(source, run_dir / "converted")
    elements, _ = parse_docx(str(source))
    overrides = _read(run_dir / "overrides.json", {})
    forced = overrides.get("表格分类", {})
    for element in elements:
        if element.kind == "table" and str(element.index) in forced:
            element.forced_kind = forced[str(element.index)]
    literal = meta.get("文档") == "B"
    inject_numbers(elements, "literal" if literal else "auto")
    sections = build_tree(meta.get("文档", "A"), elements, AuditLog(), literal=literal)
    return [section.model_dump() for section in sections]


def create_merge_suggestions(run_dir: Path, judge=None) -> dict:
    stage1 = _read(run_dir / "stage_1.json")
    stage2 = _read(run_dir / "stage_2.json")
    if not stage1 or not stage2:
        raise FileNotFoundError("缺少阶段 1 或阶段 2 快照")
    styles = {int(item["ID"]): item.get("样式", "") for item in stage1.get("元素", []) if item.get("类型") == "para"}
    candidates = find_merge_candidates(_candidate_sections(run_dir, stage2), styles)
    previous = {item["id"]: item for item in get_merge_suggestions(run_dir).get("建议", [])}
    approved = _approved_pairs(run_dir)
    if judge is None and candidates:
        _jev_decider()
        judge = judge_with_jev
    suggestions = []
    for candidate in candidates:
        pair = (candidate["previous"]["element_id"], candidate["current"]["element_id"])
        suggestion = {
            **candidate,
            "状态": "confirmed" if pair in approved else "pending",
            "probability": None,
            "probabilities": None,
        }
        try:
            probabilities = _validated_probabilities(judge(candidate))
            suggestion["probabilities"] = probabilities
            suggestion["probability"] = probabilities["true"]
            suggestion.pop("错误", None)
        except Exception as exc:
            suggestion["状态"] = "error"
            suggestion["错误"] = f"{type(exc).__name__}: {exc}"
        suggestions.append(suggestion)
    candidate_ids = {item["id"] for item in candidates}
    for suggestion_id, old in previous.items():
        pair = (old["previous"]["element_id"], old["current"]["element_id"])
        if suggestion_id not in candidate_ids and pair in approved:
            old["状态"] = "confirmed"
            suggestions.append(old)
    result = {
        "模型": JEV_MODEL,
        "生成时间": dt.datetime.now().isoformat(timespec="seconds"),
        "建议": suggestions,
    }
    _write(suggestions_path(run_dir), result)
    return result


def confirm_merge(run_dir: Path, suggestion_id: str, confirmed: bool) -> dict:
    if not _SUGGESTION_ID_RE.fullmatch(suggestion_id):
        raise ValueError("非法合并建议 ID")
    result = get_merge_suggestions(run_dir)
    suggestion = next((item for item in result.get("建议", []) if item["id"] == suggestion_id), None)
    if suggestion is None:
        raise FileNotFoundError("合并建议不存在")
    if suggestion.get("状态") == "error" and confirmed:
        raise ValueError("JEV 判断失败，请先重新生成建议")

    suggestion["状态"] = "confirmed" if confirmed else "rejected"
    suggestion["确认时间"] = dt.datetime.now().isoformat(timespec="seconds")
    pair = {"previous": suggestion["previous"]["element_id"], "current": suggestion["current"]["element_id"]}
    overrides_path = run_dir / "overrides.json"
    overrides = _read(overrides_path, {"表格分类": {}})
    overrides.setdefault("表格分类", {})
    approved = [item for item in overrides.get("段落合并", []) if item != pair]
    if confirmed:
        approved.append(pair)
        version_dir = run_dir / "review" / "versions" / suggestion_id
        before = version_dir / "stage_2_before.json"
        if not before.is_file():
            before.parent.mkdir(parents=True, exist_ok=True)
            before.write_bytes((run_dir / "stage_2.json").read_bytes())
            _write(version_dir / "suggestion.json", suggestion)
    overrides["段落合并"] = approved
    _write(overrides_path, overrides)
    _write(suggestions_path(run_dir), result)
    return suggestion

import json

from xc975_pipeline import webapp
from xc975_pipeline.merge_review import JEV_MODEL, confirm_merge, create_merge_suggestions


def _write_run(run_dir):
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({"run_id": run_dir.name}), encoding="utf-8")
    (run_dir / "stage_1.json").write_text(json.dumps({"元素": [
        {"ID": 1, "类型": "para", "样式": "Body Text"},
        {"ID": 2, "类型": "para", "样式": "Body Text"},
    ]}), encoding="utf-8")
    sections = [{
        "section_id": "A-1", "标题": "检查", "blocks": [
            {"type": "para", "text": "这是一段在文档转换时被错误拆开的正文，前半句没有结束", "src": [1]},
            {"type": "para", "text": "标点，后半段应该由用户确认后合并。", "src": [2]},
        ],
    }]
    (run_dir / "stage_2.json").write_text(json.dumps({"章节": sections}, ensure_ascii=False), encoding="utf-8")
    return sections


def test_jev_only_creates_preview_without_mutating_snapshot(tmp_path):
    run_dir = tmp_path / "runs" / "A"
    sections = _write_run(run_dir)
    before = (run_dir / "stage_2.json").read_bytes()

    result = create_merge_suggestions(run_dir, judge=lambda candidate: {"false": 0.07, "true": 0.93})

    assert result["模型"] == JEV_MODEL == "autotrust/JEV-27B-VL"
    assert len(result["建议"]) == 1
    suggestion = result["建议"][0]
    assert suggestion["状态"] == "pending"
    assert suggestion["probability"] == 0.93
    assert suggestion["previous"]["text"] == sections[0]["blocks"][0]["text"]
    assert suggestion["current"]["text"] == sections[0]["blocks"][1]["text"]
    assert suggestion["merged_text"] == sections[0]["blocks"][0]["text"] + sections[0]["blocks"][1]["text"]
    assert suggestion["src"] == [1, 2]
    assert (run_dir / "stage_2.json").read_bytes() == before


def test_confirmation_records_rule_and_preserves_before_snapshot(tmp_path):
    run_dir = tmp_path / "runs" / "A"
    _write_run(run_dir)
    before = (run_dir / "stage_2.json").read_bytes()
    created = create_merge_suggestions(run_dir, judge=lambda candidate: {"false": 0.02, "true": 0.98})
    suggestion_id = created["建议"][0]["id"]

    confirmed = confirm_merge(run_dir, suggestion_id, True)

    assert confirmed["状态"] == "confirmed"
    overrides = json.loads((run_dir / "overrides.json").read_text(encoding="utf-8"))
    assert overrides["段落合并"] == [{"previous": 1, "current": 2}]
    version = run_dir / "review" / "versions" / suggestion_id / "stage_2_before.json"
    assert version.read_bytes() == before
    assert (run_dir / "stage_2.json").read_bytes() == before


def test_rejection_does_not_add_approved_rule(tmp_path):
    run_dir = tmp_path / "runs" / "A"
    _write_run(run_dir)
    created = create_merge_suggestions(run_dir, judge=lambda candidate: {"false": 0.81, "true": 0.19})

    rejected = confirm_merge(run_dir, created["建议"][0]["id"], False)

    assert rejected["状态"] == "rejected"
    overrides = json.loads((run_dir / "overrides.json").read_text(encoding="utf-8"))
    assert overrides["段落合并"] == []

    regenerated = create_merge_suggestions(run_dir, judge=lambda candidate: {"false": 0.07, "true": 0.93})
    assert regenerated["建议"][0]["状态"] == "pending"


def test_candidates_come_from_source_when_snapshot_already_auto_merged(tmp_path):
    from docx import Document

    run_dir = tmp_path / "runs" / "A"
    sections = _write_run(run_dir)
    source = run_dir / "source.docx"
    doc = Document()
    doc.add_heading("检查", level=1)
    doc.add_paragraph(sections[0]["blocks"][0]["text"], style="Body Text")
    doc.add_paragraph(sections[0]["blocks"][1]["text"], style="Body Text")
    doc.save(source)
    (run_dir / "run.json").write_text(json.dumps({"run_id": "A", "输入": str(source), "文档": "A"}), encoding="utf-8")
    merged = [{**sections[0], "blocks": [{
        "type": "para",
        "text": sections[0]["blocks"][0]["text"] + sections[0]["blocks"][1]["text"],
        "src": [1, 2],
    }]}]
    (run_dir / "stage_2.json").write_text(json.dumps({"章节": merged}, ensure_ascii=False), encoding="utf-8")

    result = create_merge_suggestions(run_dir, judge=lambda candidate: {"false": 0.05, "true": 0.95})

    assert len(result["建议"]) == 1
    assert result["建议"][0]["src"] == [1, 2]
    assert result["建议"][0]["previous"]["text"] == sections[0]["blocks"][0]["text"]


def test_merge_review_endpoints(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    run_dir = runs / "A"
    _write_run(run_dir)
    monkeypatch.setattr(webapp, "RUNS_ROOT", runs)
    monkeypatch.setattr("xc975_pipeline.merge_review._jev_decider", lambda: None)
    monkeypatch.setattr("xc975_pipeline.merge_review.judge_with_jev", lambda candidate: {"false": 0.1, "true": 0.9})
    client = webapp.app.test_client()

    response = client.post("/api/runs/A/merge-suggestions")
    assert response.status_code == 200
    suggestion = response.get_json()["建议"][0]

    response = client.post(f"/api/runs/A/merge-suggestions/{suggestion['id']}", json={"确认": True})
    assert response.status_code == 200
    assert response.get_json()["状态"] == "confirmed"
    assert client.get("/api/runs/A/merge-suggestions").get_json()["建议"][0]["状态"] == "confirmed"

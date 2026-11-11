import json
import time

import pytest

from xc975_pipeline import webapp
from xc975_pipeline.runner import run_stages


def _stage(runs, run_id, n):
    return json.loads((runs / run_id / f"stage_{n}.json").read_text(encoding="utf-8"))


def _events(runs, run_id):
    f = runs / run_id / "events.jsonl"
    if not f.is_file():
        return []
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


def _max_seq(events):
    return max((e.get("seq", 0) for e in events), default=0)


def _events(runs, run_id):
    f = runs / run_id / "events.jsonl"
    if not f.is_file():
        return []
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


def _max_seq(runs, run_id):
    return max((e.get("seq", 0) for e in _events(runs, run_id)), default=0)


def _wait_for_rerun(runs, run_id, prev_seq, timeout=30):
    """重跑异步执行：等 seq 大于 prev_seq 的新 run_done（rerun 会清空事件文件，不能按条数判据）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(e["类型"] == "run_done" and e.get("seq", 0) > prev_seq for e in _events(runs, run_id)):
            return json.loads((runs / run_id / "run.json").read_text(encoding="utf-8"))
        time.sleep(0.1)
    raise TimeoutError(f"run {run_id} 未在 {timeout}s 内完成重跑")


def _fault_table_id(stage1):
    return next(e["ID"] for e in stage1["元素"] if e["类型"] == "table" and e["分类"] == "fault_code")


def test_overrides_change_products(manual_a, tmp_path):
    runs = tmp_path / "runs"
    meta = run_stages(str(manual_a), "A", "国内干桥", "202608", runs)
    run_id = meta["run_id"]
    tid = _fault_table_id(_stage(runs, run_id, 1))
    n_before = len(_stage(runs, run_id, 2)["故障码"])
    assert n_before > 0

    # 手工把故障码表改成数据表 → 故障码产物减少；重跑复用同一 run 目录
    run_stages(str(manual_a), "A", "国内干桥", "202608", runs,
               overrides={"表格分类": {str(tid): "data"}}, run_id=run_id)
    entry = next(e for e in _stage(runs, run_id, 1)["元素"] if e["ID"] == tid)
    assert entry["分类"] == "data"
    assert entry["人工"] and "人工指定" in entry["依据"]
    assert len(_stage(runs, run_id, 2)["故障码"]) < n_before


@pytest.fixture
def client(manual_a, tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(webapp, "RUNS_ROOT", runs)
    meta = run_stages(str(manual_a), "A", "国内干桥", "202608", runs)
    return webapp.app.test_client(), meta["run_id"], runs


def test_override_endpoints(client):
    client, run_id, runs = client
    tid = _fault_table_id(_stage(runs, run_id, 1))
    n_before = len(_stage(runs, run_id, 2)["故障码"])

    r = client.post(f"/api/runs/{run_id}/overrides", json={"元素": tid, "分类": "data"})
    assert r.status_code == 200
    assert r.get_json()["表格分类"][str(tid)] == "data"

    prev_seq = _max_seq(runs, run_id)
    r = client.post(f"/api/runs/{run_id}/rerun")
    assert r.status_code == 200
    assert r.get_json()["run_id"] == run_id
    meta = _wait_for_rerun(runs, run_id, prev_seq)
    assert not meta.get("错误")
    entry = next(e for e in _stage(runs, run_id, 1)["元素"] if e["ID"] == tid)
    assert entry["分类"] == "data" and entry["人工"]
    assert len(_stage(runs, run_id, 2)["故障码"]) < n_before

    # 恢复自动判定
    r = client.post(f"/api/runs/{run_id}/overrides", json={"元素": tid, "分类": None})
    assert r.get_json()["表格分类"] == {}
    prev_seq = _max_seq(runs, run_id)
    client.post(f"/api/runs/{run_id}/rerun")
    _wait_for_rerun(runs, run_id, prev_seq)
    assert len(_stage(runs, run_id, 2)["故障码"]) == n_before


def test_override_validation(client):
    client, run_id, _ = client
    assert client.post(f"/api/runs/{run_id}/overrides", json={"元素": 1, "分类": "bogus"}).status_code == 400
    assert client.post(f"/api/runs/{run_id}/overrides", json={"元素": "x", "分类": "data"}).status_code == 400
    assert client.post("/api/runs/../etc/overrides", json={"元素": 1, "分类": "data"}).status_code in (400, 404)

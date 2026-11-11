"""流水交互（事件流）测试：runner 落盘事件序列 + webapp 异步运行与 SSE/JSON 事件接口。"""
import json
import time

import pytest

from xc975_pipeline import webapp
from xc975_pipeline.runner import STAGES, run_stages


def _events(runs, run_id):
    f = runs / run_id / "events.jsonl"
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


def _max_seq(events):
    return max((e.get("seq", 0) for e in events), default=0)


def _wait_for_run(runs, run_id, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            meta = json.loads((runs / run_id / "run.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            time.sleep(0.1)  # 线程正在写入，稍等重读
            continue
        if "结束" in meta:
            return meta
        time.sleep(0.1)
    raise TimeoutError(f"run {run_id} 未在 {timeout}s 内结束")


def test_run_emits_stage_events(manual_a, tmp_path):
    runs = tmp_path / "runs"
    meta = run_stages(str(manual_a), "A", "国内干桥", "202608", runs)
    events = _events(runs, meta["run_id"])
    types = [e["类型"] for e in events]

    assert types[0] == "run_start"
    assert types[-1] == "run_done"
    for n in range(len(STAGES)):
        assert (f"stage_start", n) in [(e["类型"], e["阶段"]) for e in events]
        done = next(e for e in events if e["类型"] == "stage_done" and e["阶段"] == n)
        assert done["摘要"] == meta["阶段"][str(n)]["摘要"]
        assert done["耗时"] == meta["阶段"][str(n)]["耗时"]
    # 步骤事件：每个阶段至少一步，都落在本阶段 start 与 done 的 seq 之间
    steps = [e for e in events if e["类型"] == "step"]
    assert steps, "每个阶段应发出细粒度 step 事件供界面实时展示"
    assert all(e["摘要"] for e in steps)
    for n in range(len(STAGES)):
        own = [e for e in steps if e["阶段"] == n]
        assert own, f"阶段 {n} 缺少 step 事件"
        start = next(e for e in events if e["类型"] == "stage_start" and e["阶段"] == n)
        done = next(e for e in events if e["类型"] == "stage_done" and e["阶段"] == n)
        assert all(start["seq"] < e["seq"] < done["seq"] for e in own)
    # seq 单调递增
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)


def test_run_records_running_state_incrementally(manual_a, tmp_path, monkeypatch):
    """stage_start 先把阶段标记为"运行中"并落盘 run.json，前端轮询时能看到中间状态。"""
    runs = tmp_path / "runs"
    seen = []
    from xc975_pipeline import runner as runner_mod

    real_write_json = runner_mod.write_json

    def spy(path, data):
        if str(path).endswith("run.json"):
            seen.append(json.loads(json.dumps(data, ensure_ascii=False)))
        return real_write_json(path, data)

    monkeypatch.setattr(runner_mod, "write_json", spy)
    run_stages(str(manual_a), "A", "国内干桥", "202608", runs)
    running = [m for m in seen if any(s.get("状态") == "运行中" for s in m.get("阶段", {}).values())]
    assert running, "运行中状态应被增量写入 run.json"
    assert all("结束" not in m for m in seen[:-1]), "中间写入不应带结束时间"


def test_event_seq_continues_across_rerun(manual_a, tmp_path):
    """rerun 清空事件文件但 seq 连续——SSE 与轮询靠 seq 判重，重置会丢重跑事件。"""
    runs = tmp_path / "runs"
    meta = run_stages(str(manual_a), "A", "国内干桥", "202608", runs)
    run_id = meta["run_id"]
    first_max = _max_seq(_events(runs, run_id))
    run_stages(str(manual_a), "A", "国内干桥", "202608", runs, run_id=run_id)
    events = _events(runs, run_id)
    assert min(e["seq"] for e in events) == first_max + 1
    assert events[-1]["类型"] == "run_done"


@pytest.fixture
def client(manual_a, tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(webapp, "RUNS_ROOT", runs)
    return webapp.app.test_client(), runs, manual_a


def test_api_run_is_async_and_streams_events(client):
    client, runs, manual = client
    r = client.post("/api/run", json={"path": str(manual), "doc": "A"})
    assert r.status_code == 200
    run_id = r.get_json()["run_id"]
    meta = _wait_for_run(runs, run_id)
    assert not meta.get("错误")

    # JSON 事件回放：首尾是 run 级事件，中间是各阶段 start/step/done
    events = client.get(f"/api/runs/{run_id}/events").get_json()
    assert [e["类型"] for e in events][-1] == "run_done"
    assert events[0]["类型"] == "run_start"
    assert len(events) > 2 + len(STAGES) * 2  # 含细粒度 step 事件
    assert all(e["类型"] in ("run_start", "run_done", "stage_start", "stage_done", "stage_fail", "step")
               for e in events)

    # SSE 流：运行已结束，一次性拿到全部事件
    resp = client.get(f"/api/runs/{run_id}/stream")
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"
    body = resp.get_data(as_text=True)
    assert "event" not in body  # 纯 data: 帧
    assert body.count("data: ") == len(events)
    assert "run_done" in body


def test_api_run_failure_closes_stream(client):
    client, runs, _ = client
    bad = runs.parent / "broken.docx"
    bad.write_bytes(b"not a docx at all")
    r = client.post("/api/run", json={"path": str(bad), "doc": "A"})
    run_id = r.get_json()["run_id"]
    meta = _wait_for_run(runs, run_id)
    assert meta.get("错误")
    events = client.get(f"/api/runs/{run_id}/events").get_json()
    assert events[-1]["类型"] == "run_done"
    assert events[-1]["摘要"] == meta["错误"]
    assert any(e["类型"] == "stage_fail" for e in events)

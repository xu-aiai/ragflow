"""管线工作台（本地 Web UI）：逐步执行抽取并可视化每阶段结果。

    python workbench.py             # → http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import threading
import time
import traceback
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

from .convert import convert_to_docx
from .docmodel import parse_docx
from .merge_review import confirm_merge, create_merge_suggestions, get_merge_suggestions
from .preview import PREVIEW_MAP_VERSION, build_page_map, find_preview_pdf, render_page_png, render_preview, soffice_available
from .runner import run_stages
from .tables import TABLE_KINDS

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PIPELINE_ROOT / "web"
RUNS_ROOT = PIPELINE_ROOT / "runs"
DEFAULT_MANUALS_DIR = r"D:\AI智能体部\车载屏\铲运上车"

_RUN_ID_RE = re.compile(r"^[\w.-]+$")

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="/web")


@app.after_request
def _no_cache_static(resp):
    """工作台静态文件禁用缓存，避免浏览器拿到旧版 JS/CSS。"""
    if request.path.startswith("/web/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/api/manuals")
def api_manuals():
    d = Path(request.args.get("dir") or DEFAULT_MANUALS_DIR)
    files = []
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in (".docx", ".doc"):
                files.append({"name": p.name, "path": str(p), "size": p.stat().st_size})
    return jsonify({"dir": str(d), "files": files})


def _launch_run(kwargs: dict) -> None:
    """后台线程执行管线；任何逃逸异常都兜底落盘，前端靠 run_done 事件收尾。"""
    run_id = kwargs["run_id"]

    def worker():
        try:
            run_stages(**kwargs)
        except Exception as e:  # noqa: BLE001 —— 兜底：保证 run.json 与事件流一定闭环
            traceback.print_exc()
            run_dir = RUNS_ROOT / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            meta_path = run_dir / "run.json"
            meta = {}
            if meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    meta = {}
            meta.update({"run_id": run_id, "结束": dt.datetime.now().isoformat(timespec="seconds"), "错误": str(e)})
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            events_path = run_dir / "events.jsonl"
            seq = 0
            if events_path.is_file():
                for line in events_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        try:
                            seq = max(seq, json.loads(line).get("seq", 0))
                        except json.JSONDecodeError:
                            pass
            with events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"seq": seq + 1, "时间": meta["结束"], "类型": "run_done",
                                    "阶段": None, "摘要": str(e)}, ensure_ascii=False) + "\n")

    threading.Thread(target=worker, daemon=True, name=f"pipeline-{run_id}").start()


@app.post("/api/run")
def api_run():
    body = request.get_json(force=True)
    doc = body.get("doc", "A")
    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{doc}"
    _launch_run({
        "input_path": body["path"],
        "doc_code": doc,
        "variant": body.get("variant", "国内干桥"),
        "version": body.get("version", "202608"),
        "runs_root": RUNS_ROOT,
        "img_width": int(body.get("img_width", 800)),
        "run_id": run_id,
    })
    return jsonify({"run_id": run_id})


@app.get("/api/runs")
def api_runs():
    runs = []
    if RUNS_ROOT.is_dir():
        for d in sorted(RUNS_ROOT.iterdir(), reverse=True):
            f = d / "run.json"
            if d.is_dir() and f.is_file():
                runs.append(json.loads(f.read_text(encoding="utf-8")))
    return jsonify(runs)


@app.get("/api/runs/<run_id>")
def api_run_detail(run_id):
    if not _RUN_ID_RE.match(run_id):
        return jsonify({"error": "非法 run id"}), 400
    f = RUNS_ROOT / run_id / "run.json"
    if not f.is_file():
        return jsonify({"error": "run 不存在"}), 404
    return jsonify(json.loads(f.read_text(encoding="utf-8")))


@app.get("/api/runs/<run_id>/stage/<int:n>")
def api_stage(run_id, n):
    if not _RUN_ID_RE.match(run_id):
        return jsonify({"error": "非法 run id"}), 400
    f = RUNS_ROOT / run_id / f"stage_{n}.json"
    if not f.is_file():
        return jsonify({"error": f"阶段 {n} 无快照"}), 404
    return jsonify(json.loads(f.read_text(encoding="utf-8")))


def _overrides_path(run_id: str) -> Path:
    return RUNS_ROOT / run_id / "overrides.json"


def _read_overrides(run_id: str) -> dict:
    f = _overrides_path(run_id)
    if f.is_file():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"表格分类": {}}


@app.get("/api/runs/<run_id>/overrides")
def api_get_overrides(run_id):
    if not _RUN_ID_RE.match(run_id):
        return jsonify({"error": "非法 run id"}), 400
    return jsonify(_read_overrides(run_id))


@app.post("/api/runs/<run_id>/overrides")
def api_set_override(run_id):
    """手工打标：{"元素": <表格元素ID>, "分类": "fault_code"}；分类为 null 表示恢复自动判定。"""
    if not _RUN_ID_RE.match(run_id):
        return jsonify({"error": "非法 run id"}), 400
    if not (RUNS_ROOT / run_id / "run.json").is_file():
        return jsonify({"error": "run 不存在"}), 404
    body = request.get_json(force=True)
    element_id = str(body.get("元素", ""))
    kind = body.get("分类")
    if not element_id.isdigit():
        return jsonify({"error": "元素 ID 必须是数字"}), 400
    if kind is not None and kind not in TABLE_KINDS:
        return jsonify({"error": f"分类必须是 {'/'.join(TABLE_KINDS)} 之一或 null"}), 400
    overrides = _read_overrides(run_id)
    if kind is None:
        overrides["表格分类"].pop(element_id, None)
    else:
        overrides["表格分类"][element_id] = kind
    _overrides_path(run_id).write_text(json.dumps(overrides, ensure_ascii=False, indent=1), encoding="utf-8")
    return jsonify(overrides)


@app.get("/api/runs/<run_id>/merge-suggestions")
def api_get_merge_suggestions(run_id):
    if not _RUN_ID_RE.match(run_id):
        return jsonify({"error": "非法 run id"}), 400
    if not (RUNS_ROOT / run_id / "run.json").is_file():
        return jsonify({"error": "run 不存在"}), 404
    return jsonify(get_merge_suggestions(RUNS_ROOT / run_id))


@app.post("/api/runs/<run_id>/merge-suggestions")
def api_create_merge_suggestions(run_id):
    if not _RUN_ID_RE.match(run_id):
        return jsonify({"error": "非法 run id"}), 400
    run_dir = RUNS_ROOT / run_id
    if not (run_dir / "run.json").is_file():
        return jsonify({"error": "run 不存在"}), 404
    try:
        return jsonify(create_merge_suggestions(run_dir))
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except (RuntimeError, ValueError) as e:
        return jsonify({"error": str(e)}), 503


@app.post("/api/runs/<run_id>/merge-suggestions/<suggestion_id>")
def api_confirm_merge(run_id, suggestion_id):
    if not _RUN_ID_RE.match(run_id):
        return jsonify({"error": "非法 run id"}), 400
    run_dir = RUNS_ROOT / run_id
    if not (run_dir / "run.json").is_file():
        return jsonify({"error": "run 不存在"}), 404
    body = request.get_json(force=True)
    if type(body.get("确认")) is not bool:
        return jsonify({"error": "确认必须是布尔值"}), 400
    try:
        return jsonify(confirm_merge(run_dir, suggestion_id, body["确认"]))
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/runs/<run_id>/rerun")
def api_rerun(run_id):
    """带着已保存的人工改标重跑整条管线（覆盖同一 run 的快照）；异步执行。"""
    if not _RUN_ID_RE.match(run_id):
        return jsonify({"error": "非法 run id"}), 400
    f = RUNS_ROOT / run_id / "run.json"
    if not f.is_file():
        return jsonify({"error": "run 不存在"}), 404
    meta = json.loads(f.read_text(encoding="utf-8"))
    _launch_run({
        "input_path": meta["输入"],
        "doc_code": meta["文档"],
        "variant": meta["变体"],
        "version": meta["版本"],
        "runs_root": RUNS_ROOT,
        "overrides": _read_overrides(run_id),
        "run_id": run_id,
    })
    return jsonify({"run_id": run_id})


@app.get("/api/runs/<run_id>/events")
def api_events(run_id):
    """历史运行的事件流（JSON 数组），供过程日志回放。"""
    if not _RUN_ID_RE.match(run_id):
        return jsonify({"error": "非法 run id"}), 400
    f = RUNS_ROOT / run_id / "events.jsonl"
    if not f.is_file():
        return jsonify([])
    events = [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    return jsonify(events)


@app.get("/api/runs/<run_id>/stream")
def api_event_stream(run_id):
    """运行事件 SSE 流：从开头回放，run_done 事件后关闭。"""
    if not _RUN_ID_RE.match(run_id):
        return jsonify({"error": "非法 run id"}), 400
    events_path = RUNS_ROOT / run_id / "events.jsonl"

    def generate():
        last_seq = 0
        last_yield = time.monotonic()
        deadline = time.monotonic() + 1800  # 单次运行最长守候 30 分钟
        while time.monotonic() < deadline:
            sent = False
            if events_path.is_file():
                for line in events_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event.get("seq", 0) <= last_seq:
                        continue
                    last_seq = event["seq"]
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    sent = True
                    last_yield = time.monotonic()
                    if event["类型"] == "run_done":
                        return
            if not sent:
                time.sleep(0.3)
                if time.monotonic() - last_yield > 15:
                    yield ": heartbeat\n\n"  # 保持代理/浏览器连接不断
                    last_yield = time.monotonic()

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _preview_info(run_dir: Path, name: str | None) -> dict:
    info = {"文件": name, "可生成": soffice_available(), "页数": 0, "元素页": {}}
    pages = run_dir / "preview" / "pages.json"
    if name and pages.is_file():
        info.update(json.loads(pages.read_text(encoding="utf-8")))
    return info


@app.get("/api/runs/<run_id>/preview")
def api_preview_status(run_id):
    if not _RUN_ID_RE.match(run_id):
        return jsonify({"error": "非法 run id"}), 400
    return jsonify(_preview_info(RUNS_ROOT / run_id, find_preview_pdf(RUNS_ROOT / run_id / "preview")))


@app.post("/api/runs/<run_id>/preview")
def api_preview_render(run_id):
    """按需生成原文 PDF 与元素→页码映射。已生成则直接复用。"""
    if not _RUN_ID_RE.match(run_id):
        return jsonify({"error": "非法 run id"}), 400
    f = RUNS_ROOT / run_id / "run.json"
    if not f.is_file():
        return jsonify({"error": "run 不存在"}), 404
    meta = json.loads(f.read_text(encoding="utf-8"))
    out_dir = RUNS_ROOT / run_id / "preview"
    name = find_preview_pdf(out_dir)
    if not name:
        try:
            name = render_preview(meta["输入"], out_dir)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 503
    info = _preview_info(RUNS_ROOT / run_id, name)
    if not info["页数"] or "区域" not in info or info.get("映射版本") != PREVIEW_MAP_VERSION:
        try:
            src = meta["输入"]
            if Path(src).suffix.lower() == ".doc":
                src = str(convert_to_docx(src, RUNS_ROOT / run_id / "converted"))
            elements, _ = parse_docx(src)
            info.update(build_page_map(out_dir / name, elements))
        except Exception:
            pass  # 分页映射是增强能力，失败不影响原文预览
    return jsonify(info)


@app.get("/runs/<run_id>/preview/page/<int:n>.png")
def api_preview_page(run_id, n):
    """按页渲染原文 PNG（缓存到 preview/page_N.png）。"""
    if not _RUN_ID_RE.match(run_id):
        return jsonify({"error": "非法 run id"}), 400
    out_dir = RUNS_ROOT / run_id / "preview"
    name = find_preview_pdf(out_dir)
    if not name:
        return jsonify({"error": "原文 PDF 尚未生成"}), 404
    out = out_dir / f"page_{n}.png"
    if not out.is_file():
        try:
            render_page_png(out_dir / name, n, out)
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
    return send_from_directory(out_dir, out.name)


@app.get("/runs/<run_id>/preview/<path:filename>")
def api_preview_file(run_id, filename):
    if not _RUN_ID_RE.match(run_id):
        return jsonify({"error": "非法 run id"}), 400
    return send_from_directory(RUNS_ROOT / run_id / "preview", filename)


@app.get("/runs/<run_id>/img/<path:filename>")
def api_img(run_id, filename):
    if not _RUN_ID_RE.match(run_id):
        return jsonify({"error": "非法 run id"}), 400
    return send_from_directory(RUNS_ROOT / run_id / "img", filename)


def main() -> None:
    ap = argparse.ArgumentParser(prog="workbench", description="XC975-EV 抽取管线工作台")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    RUNS_ROOT.mkdir(exist_ok=True)
    print(f"XC975-EV 抽取管线工作台：http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)

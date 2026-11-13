from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import subprocess
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from manual_parser.pipeline import ManualParsingPipeline
from manual_parser.storage import JobStore

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = Path(os.getenv("MANUAL_PARSER_DATA", "/data")).resolve()
MAX_UPLOAD = int(os.getenv("MANUAL_PARSER_MAX_UPLOAD_MB", "500")) * 1024 * 1024
logging.basicConfig(
    level=getattr(logging, os.getenv("MANUAL_PARSER_LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
STORE = JobStore(DATA / "jobs")
PIPELINE = ManualParsingPipeline()
EXECUTOR = ThreadPoolExecutor(max_workers=max(1, int(os.getenv("MANUAL_PARSER_WORKERS", "1"))), thread_name_prefix="manual-parser")
TASK_LOCK = threading.Lock()
TASKS: dict[str, tuple[object, threading.Event]] = {}
STORE.recover_interrupted()


class JobCancelled(Exception):
    pass


def _run_job(job_id: str, cancel_event: threading.Event) -> None:
    status = STORE.status(job_id)
    directory = STORE.job_dir(job_id)
    source = directory / status["source"]
    STORE.update(job_id, status="running", progress=0.01, message="开始解析", error="")

    def progress(value: float, message: str) -> None:
        if cancel_event.is_set():
            raise JobCancelled()
        STORE.update(job_id, status="running", progress=round(max(0.0, min(0.99, value)), 4), message=message)

    try:
        result = PIPELINE.parse(job_id, source, directory, progress).to_dict()
        result["filename"] = status["filename"]
        STORE.save_result(job_id, result)
        STORE.update(job_id, status="completed", progress=1.0, message="解析完成", has_result=True)
    except JobCancelled:
        STORE.update(job_id, status="cancelled", message="用户已取消解析", error="")
    except Exception as exc:  # noqa: BLE001 - persist background failures for the UI
        (directory / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        STORE.update(job_id, status="failed", progress=1.0, message="解析失败", error=f"{type(exc).__name__}: {exc}")
    finally:
        with TASK_LOCK:
            TASKS.pop(job_id, None)


def _submit_job(job_id: str) -> None:
    cancel_event = threading.Event()
    future = EXECUTOR.submit(_run_job, job_id, cancel_event)
    with TASK_LOCK:
        TASKS[job_id] = (future, cancel_event)


def _cancel_job(job_id: str) -> dict:
    status = STORE.status(job_id)
    if status["status"] not in {"queued", "running", "cancelling"}:
        return status
    with TASK_LOCK:
        task = TASKS.get(job_id)
    if not task:
        return STORE.update(job_id, status="interrupted", message="任务进程不存在，已标记为中断")
    future, cancel_event = task
    cancel_event.set()
    if future.cancel():
        with TASK_LOCK:
            TASKS.pop(job_id, None)
        return STORE.update(job_id, status="cancelled", message="用户已取消排队任务", error="")
    return STORE.update(job_id, status="cancelling", message="正在安全停止解析", error="")


class Handler(BaseHTTPRequestHandler):
    server_version = "XCMGManualParser/0.1"

    def _json(self, status: int, value) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, download_name: str = "") -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        size = path.stat().st_size
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        elif path.suffix.lower() in {".html", ".js", ".css"}:
            self.send_header("Cache-Control", "no-cache")
        else:
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                self.wfile.write(chunk)

    def do_GET(self) -> None:
        route = urlsplit(self.path).path
        if route == "/health":
            self._json(
                HTTPStatus.OK,
                {
                    "status": "ready",
                    "pipeline": "deepdoc+native-pdf+ooxml+optional-region-vlm+xcmg-reconstruction",
                    "pipeline_revision": PIPELINE.cache_signature,
                    "vlm_enabled": PIPELINE.vlm.enabled,
                },
            )
            return
        if route == "/api/jobs":
            self._json(HTTPStatus.OK, {"items": STORE.list()})
            return
        parts = [unquote(item) for item in route.strip("/").split("/") if item]
        if len(parts) >= 3 and parts[:2] == ["api", "jobs"]:
            job_id = parts[2]
            try:
                if len(parts) == 3:
                    value = STORE.status(job_id)
                    value["has_result"] = (STORE.job_dir(job_id) / "result.json").exists()
                    self._json(HTTPStatus.OK, value)
                    return
                if parts[3:] == ["result"]:
                    self._json(HTTPStatus.OK, STORE.result(job_id))
                    return
                if len(parts) == 6 and parts[3] == "pages" and parts[5] == "image":
                    page = int(parts[4])
                    self._file(STORE.job_dir(job_id) / "pages" / f"page-{page:04d}.webp")
                    return
                if len(parts) == 5 and parts[3] in {"regions", "assets"}:
                    name = Path(parts[4]).name
                    if name != parts[4]:
                        raise KeyError("invalid asset")
                    self._file(STORE.job_dir(job_id) / parts[3] / name)
                    return
                if parts[3:] == ["download", "json"]:
                    self._file(STORE.job_dir(job_id) / "result.json", f"{job_id}.json")
                    return
                if parts[3:] == ["download", "markdown"]:
                    self._file(STORE.job_dir(job_id) / "result.md", f"{job_id}.md")
                    return
                if parts[3:] == ["download", "package"]:
                    self._file(STORE.export_package(job_id), f"{job_id}-parser-result.zip")
                    return
            except (KeyError, ValueError):
                self._json(HTTPStatus.NOT_FOUND, {"error": "job or artifact not found"})
                return
        if route == "/" or route == "/index.html":
            self._file(STATIC / "index.html")
            return
        if route.startswith("/static/"):
            name = Path(route.removeprefix("/static/")).name
            if name != route.removeprefix("/static/"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._file(STATIC / name)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        route = urlsplit(self.path).path
        parts = [unquote(item) for item in route.strip("/").split("/") if item]
        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "cancel":
            try:
                self._json(HTTPStatus.OK, _cancel_job(parts[2]))
            except KeyError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "job not found"})
            return
        if route != "/api/jobs":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if size <= 0 or size > MAX_UPLOAD:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": f"文件大小必须在 1 到 {MAX_UPLOAD // 1024 // 1024}MB 之间"})
            return
        filename = unquote(self.headers.get("X-Filename", "upload.pdf"))
        if Path(filename).suffix.lower() not in {".pdf", ".doc", ".docx"}:
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "只支持 PDF、DOC、DOCX"})
            return
        try:
            job = STORE.create_from_stream(filename, self.rfile, size)
        except (OSError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": f"上传内容不完整：{exc}"})
            return
        reusable = STORE.find_reusable(job["content_sha256"], PIPELINE.cache_signature, exclude_id=job["id"])
        if reusable:
            STORE.delete(job["id"])
            self._json(HTTPStatus.OK, {**reusable, "cache_hit": True})
            return
        job = STORE.update(job["id"], pipeline_signature=PIPELINE.cache_signature)
        _submit_job(job["id"])
        self._json(HTTPStatus.ACCEPTED, job)

    def do_DELETE(self) -> None:
        route = urlsplit(self.path).path
        parts = [unquote(item) for item in route.strip("/").split("/") if item]
        if len(parts) != 3 or parts[:2] != ["api", "jobs"]:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            status = STORE.status(parts[2])
            if status["status"] in {"queued", "running", "cancelling"}:
                self._json(HTTPStatus.CONFLICT, {"error": "请先取消正在运行或排队的任务"})
                return
            STORE.delete(parts[2])
        except KeyError:
            self._json(HTTPStatus.NOT_FOUND, {"error": "job not found"})
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone XCMG manual parsing service")
    parser.add_argument("--host", default=os.getenv("MANUAL_PARSER_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MANUAL_PARSER_PORT", "9392")))
    args = parser.parse_args()
    company_fonts = Path("/usr/local/share/fonts/company")
    if company_fonts.is_dir() and any(path.suffix.lower() in {".ttf", ".otf", ".ttc"} for path in company_fonts.iterdir()):
        subprocess.run(["fc-cache", "-f", str(company_fonts)], check=False, timeout=120)
    print(f"MANUAL_PARSER_READY http://{args.host}:{args.port} data={DATA}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

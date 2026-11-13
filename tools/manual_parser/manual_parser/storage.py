from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

JOB_ID_RE = re.compile(r"^[a-f0-9]{24}$")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class JobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def job_dir(self, job_id: str) -> Path:
        if not JOB_ID_RE.fullmatch(job_id):
            raise KeyError("invalid job id")
        return self.root / job_id

    def create(self, filename: str, content: bytes) -> dict[str, Any]:
        return self.create_from_stream(filename, _BytesReader(content), len(content))

    def create_from_stream(self, filename: str, stream: BinaryIO, size: int) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:24]
        directory = self.root / job_id
        directory.mkdir(parents=True)
        safe_name = Path(filename).name or "upload.pdf"
        source = directory / f"source{Path(safe_name).suffix.lower()}"
        remaining = size
        digest = hashlib.sha256()
        try:
            with source.open("wb") as output:
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("request body ended before Content-Length")
                    output.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        status = {
            "id": job_id,
            "filename": safe_name,
            "source": source.name,
            "status": "queued",
            "progress": 0.0,
            "message": "等待解析",
            "created_at": _now(),
            "updated_at": _now(),
            "error": "",
            "content_sha256": digest.hexdigest(),
            "pipeline_signature": "",
        }
        self._write_json(directory / "status.json", status)
        return status

    def _write_json(self, path: Path, value: Any) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def status(self, job_id: str) -> dict[str, Any]:
        path = self.job_dir(job_id) / "status.json"
        if not path.exists():
            raise KeyError(job_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def update(self, job_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            current = self.status(job_id)
            current.update(changes)
            current["updated_at"] = _now()
            self._write_json(self.job_dir(job_id) / "status.json", current)
            return current

    def save_result(self, job_id: str, result: dict[str, Any]) -> None:
        directory = self.job_dir(job_id)
        self._write_json(directory / "result.json", result)
        (directory / "result.md").write_text(result.get("markdown", ""), encoding="utf-8")

    def result(self, job_id: str) -> dict[str, Any]:
        path = self.job_dir(job_id) / "result.json"
        if not path.exists():
            raise KeyError(job_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def export_package(self, job_id: str) -> Path:
        directory = self.job_dir(job_id)
        result_json = directory / "result.json"
        result_markdown = directory / "result.md"
        if not result_json.exists() or not result_markdown.exists():
            raise KeyError(job_id)
        target = directory / "parser-result.zip"
        if target.exists() and target.stat().st_mtime >= max(result_json.stat().st_mtime, result_markdown.stat().st_mtime):
            return target
        portable_markdown = result_markdown.read_text(encoding="utf-8")
        portable_markdown = re.sub(rf"/api/jobs/{re.escape(job_id)}/(regions|assets)/", r"\1/", portable_markdown)
        temporary = target.with_suffix(".zip.tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("result.md", portable_markdown)
            archive.write(result_json, "result.json")
            archive.writestr(
                "README.txt",
                "本包包含解析 Markdown、完整 JSON 和图像资源。Markdown 中标为 UNSAFE_TABLE 的表格已隔离，禁止直接用于技术参数问答。\n",
            )
            for folder_name in ("regions", "assets"):
                folder = directory / folder_name
                if not folder.is_dir():
                    continue
                for path in folder.iterdir():
                    if path.is_file():
                        archive.write(path, f"{folder_name}/{path.name}")
        os.replace(temporary, target)
        return target

    def delete(self, job_id: str) -> None:
        directory = self.job_dir(job_id)
        if not (directory / "status.json").exists():
            raise KeyError(job_id)
        with self._lock:
            shutil.rmtree(directory)

    def find_reusable(self, content_sha256: str, pipeline_signature: str, exclude_id: str = "") -> dict[str, Any] | None:
        for status in self.list(limit=10_000):
            if status.get("id") == exclude_id:
                continue
            if status.get("content_sha256") != content_sha256 or status.get("pipeline_signature") != pipeline_signature:
                continue
            if status.get("status") in {"queued", "running", "completed"} and (
                status.get("status") != "completed" or (self.job_dir(status["id"]) / "result.json").exists()
            ):
                return status
        return None

    def recover_interrupted(self) -> int:
        recovered = 0
        for status in self.list(limit=10_000):
            if status.get("status") not in {"queued", "running", "cancelling"}:
                continue
            self.update(
                status["id"],
                status="interrupted",
                message="服务重启，原解析任务已中断",
                error="任务未自动续跑，请重新提交文件",
            )
            recovered += 1
        return recovered

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        statuses = []
        for path in self.root.glob("*/status.json"):
            try:
                statuses.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(statuses, key=lambda item: item.get("created_at", ""), reverse=True)[:limit]


class _BytesReader:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.offset = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.content) - self.offset
        result = self.content[self.offset : self.offset + size]
        self.offset += len(result)
        return result

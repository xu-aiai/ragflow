from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class OfficeConversionError(RuntimeError):
    pass


def _run_soffice(source: Path, target_dir: Path, target_format: str) -> Path:
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if not executable:
        raise OfficeConversionError("未找到 LibreOffice。请使用项目提供的 Docker 镜像运行 DOC/DOCX 解析。")
    profile = Path(tempfile.mkdtemp(prefix="manual-parser-lo-"))
    try:
        command = [
            executable,
            "--headless",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            f"-env:UserInstallation={profile.resolve().as_uri()}",
            "--convert-to",
            target_format,
            "--outdir",
            str(target_dir),
            str(source),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
        expected = target_dir / f"{source.stem}.{target_format.split(':', 1)[0]}"
        if completed.returncode != 0 or not expected.exists():
            details = (completed.stdout + "\n" + completed.stderr).strip()
            raise OfficeConversionError(f"LibreOffice 转换 {target_format} 失败：{details[-1200:]}")
        return expected
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def prepare_office_document(source: Path, work_dir: Path) -> tuple[Path, Path]:
    """Return an OOXML DOCX for native parsing and a PDF for visual parsing."""
    work_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()
    if suffix == ".doc":
        native_docx = _run_soffice(source, work_dir, "docx")
    elif suffix == ".docx":
        native_docx = work_dir / "native.docx"
        shutil.copy2(source, native_docx)
    else:
        raise OfficeConversionError(f"不支持的 Office 文件类型：{suffix}")
    visual_pdf = _run_soffice(native_docx, work_dir, "pdf")
    return native_docx, visual_pdf

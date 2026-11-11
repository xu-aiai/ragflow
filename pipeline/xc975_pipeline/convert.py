"""阶段 0 补充：.doc → .docx 自动转换。

优先 LibreOffice（读取不受亿赛通透明加密影响，写出是否为明文以文件头校验为准）；
Windows 上无 LibreOffice 时回退 Word COM——但亿赛通环境下 Word 另存产物是密文，
因此任何转换产物都必须通过 PK 文件头校验才被接受。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .preview import find_soffice


def convert_to_docx(source: str | Path, out_dir: Path) -> Path:
    """返回转换后的明文 .docx 路径；已转换过则复用。失败抛 RuntimeError。"""
    src = Path(source)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (src.stem + ".docx")
    if target.is_file():
        return target
    soffice = find_soffice()
    try:
        if soffice:
            subprocess.run(
                [soffice, "--headless", "--convert-to", "docx", "--outdir", str(out_dir), str(src)],
                check=True, capture_output=True, timeout=300,
            )
        elif sys.platform == "win32":
            _convert_via_word_com(src, target)
        else:
            raise RuntimeError("转换 .doc 需要 LibreOffice（或 Windows 本机的 Word）")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"转换失败：{e.stderr.decode(errors='replace')[:200]}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("转换超时（300 秒）") from e
    if not target.is_file():
        raise RuntimeError("转换器未产出 .docx 文件")
    if not target.open("rb").read(4).startswith(b"PK\x03\x04"):
        target.unlink()
        raise RuntimeError("转换产物是密文（本机 DRM 加密了写出文件），请改用未加密的转换环境")
    return target


def _convert_via_word_com(src: Path, target: Path) -> None:
    """Word COM 另存为 docx（wdFormatDocumentDefault=16），只读打开源文件。"""
    script = (
        "$word = New-Object -ComObject Word.Application; $word.Visible = $false;"
        "try { $doc = $word.Documents.Open($args[0], $false, $true);"
        " $doc.SaveAs2($args[1], 16); $doc.Close($false) } finally { $word.Quit() }"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script, str(src), str(target)],
        check=True, capture_output=True, timeout=300,
    )

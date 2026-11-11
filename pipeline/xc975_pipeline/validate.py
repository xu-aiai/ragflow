"""阶段 0：源文件校验（防亿赛通密文静默产出垃圾，规格附录 B.1）。"""
from __future__ import annotations

from pathlib import Path

_DOCX_MAGIC = b"PK\x03\x04"
_DOC_MAGIC = b"\xd0\xcf\x11\xe0"


class ValidationError(Exception):
    """源文件不可入管线。"""


def validate_source(path: str | Path) -> str:
    """校验文件头，返回 "docx" 或 "doc"（.doc 由阶段 0 自动转换）；密文抛 ValidationError。"""
    p = Path(path)
    head = p.open("rb").read(512)
    if b"E-SafeNet" in head or b"LOCK" in head:
        raise ValidationError(f"{p.name} 疑似亿赛通密文（文件头含 E-SafeNet/LOCK），拒收")
    if head.startswith(_DOCX_MAGIC):
        return "docx"
    if head.startswith(_DOC_MAGIC):
        return "doc"
    raise ValidationError(f"{p.name} 无法识别的文件头：{head[:8].hex()}")

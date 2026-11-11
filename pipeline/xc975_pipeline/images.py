"""阶段 4：图片提取与转码（规格 §6.2）。

- 段落锚点图 + 表格内嵌图统一落盘（后者是手册插图的大头，实测 268 张中占 216 张）
- 按锚点所属章节命名：{doc}_{章节号}_{序号:02d}.{ext}；同一部件多处引用只落盘一次
- EMF/WMF 需 LibreOffice（服务器）转 PNG；无 soffice 时保留原件并进审核清单
- 宽于目标宽度用 Pillow 缩放；Pillow 缺失保留原尺寸并进审核清单
"""
from __future__ import annotations

import subprocess
from io import BytesIO
from pathlib import Path

from .preview import find_soffice

_VECTOR_EXTS = {".emf", ".wmf"}


def extract_images(doc, elements, img_dir, doc_code: str, audit, target_width: int = 800) -> dict[str, str]:
    """遍历元素流，把图片部件落盘；返回 rId → 文件名。"""
    img_dir = Path(img_dir)
    img_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    by_part: dict[str, str] = {}
    section: str | None = None
    counter = 0

    def save(rid: str) -> None:
        nonlocal counter
        try:
            part = doc.part.related_parts[rid]
        except KeyError:
            audit.add("图片", f"rId={rid} 无对应媒体部件")
            return
        key = str(part.partname)
        if key in by_part:
            mapping[rid] = by_part[key]
            return
        counter += 1
        ext = Path(key).suffix.lower() or ".png"
        stem = f"{doc_code}_{(section or 'front').replace('.', '_')}_{counter:02d}"
        name = _save(img_dir, stem, ext, part.blob, target_width, audit)
        by_part[key] = name
        mapping[rid] = name

    for el in elements:
        if el.kind == "para" and el.heading_level is not None:
            section = el.编号
            counter = 0
            continue
        if el.kind == "table":
            if el.table is not None:
                for rids_row in el.table.cell_rids:
                    for rids in rids_row:
                        for rid in rids:
                            save(rid)
            continue
        if el.kind != "para" or not el.para:
            continue
        for rid in el.para.image_rids:
            save(rid)
    return mapping


def cell_image_files(table, image_files: dict[str, str]) -> list[list[list[str]]]:
    return [
        [
            [image_files[rid] for rid in cell_rids if rid in image_files]
            for cell_rids in row
        ]
        for row in table.cell_rids
    ]


def _save(img_dir: Path, stem: str, ext: str, blob: bytes, target_width: int, audit) -> str:
    if ext in _VECTOR_EXTS:
        png = _convert_vector(img_dir, stem, ext, blob)
        if png:
            return png
        audit.add("图片", f"{stem}{ext} 为矢量格式，需在服务器经 LibreOffice 转 PNG")
        (img_dir / f"{stem}{ext}").write_bytes(blob)
        return f"{stem}{ext}"
    try:
        from PIL import Image
    except ImportError:
        audit.add("图片", f"{stem}{ext} 未缩放（Pillow 缺失）")
        (img_dir / f"{stem}{ext}").write_bytes(blob)
        return f"{stem}{ext}"
    img = Image.open(BytesIO(blob))
    if img.width > target_width:
        ratio = target_width / img.width
        img = img.resize((target_width, max(1, round(img.height * ratio))))
    out = img_dir / f"{stem}{ext}"
    img.save(out)
    return out.name


def _convert_vector(img_dir: Path, stem: str, ext: str, blob: bytes) -> str | None:
    soffice = find_soffice()
    if not soffice:
        return None
    src = img_dir / f"_tmp{ext}"
    src.write_bytes(blob)
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "png", "--outdir", str(img_dir), str(src)],
            check=True, timeout=120, capture_output=True,
        )
        png = img_dir / "_tmp.png"
        if png.exists():
            out = img_dir / f"{stem}.png"
            png.rename(out)
            return out.name
    finally:
        src.unlink(missing_ok=True)
        (img_dir / "_tmp.png").unlink(missing_ok=True)
    return None

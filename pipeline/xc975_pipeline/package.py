"""阶段 6：打包——manifest + 逐文件 sha256（规格 §6.1）。"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from .schemas import Manifest


def write_json(path, data) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(pkg_dir, doc_code: str, variant: str, version: str, sections, fault_codes, rules) -> Path:
    out = Path(pkg_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / f"tree_{doc_code}.json", [s.model_dump() for s in sections])
    write_json(out / "fault_codes.json", [c.model_dump() for c in fault_codes])
    write_json(out / "maintenance_rules.json", [r.model_dump() for r in rules])
    files = [f"tree_{doc_code}.json", "fault_codes.json", "maintenance_rules.json"]
    files += [f"img/{p.name}" for p in sorted((out / "img").glob("*")) if p.is_file()]
    manifest = Manifest(
        数据包=out.name,
        文档=doc_code,
        适用变体=variant,
        手册版本=version,
        生成时间=dt.datetime.now().isoformat(timespec="seconds"),
        文件=[{"文件": f, "sha256": _sha256(out / f)} for f in files],
        规模={"章节": len(sections), "故障码": len(fault_codes), "保养规则": len(rules)},
    )
    write_json(out / "manifest.json", manifest.model_dump())
    return out

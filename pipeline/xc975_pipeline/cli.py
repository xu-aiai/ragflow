"""CLI 入口（规格 §6.2）：

    python pipeline.py --input 手册A.docx --doc A --variant 国内干桥 --version 202608 --out dist/
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .audit import AuditLog
from .docmodel import parse_docx
from .images import extract_images, image_dimensions
from .numbering import cross_check_toc, extract_toc, inject_numbers
from .package import package
from .products.fault_codes import extract_fault_codes
from .products.maintenance import extract_rules
from .products.tree import build_tree
from .validate import ValidationError, validate_source


def run(input_path: str, doc_code: str, variant: str, version: str, out_dir: str, img_width: int = 800) -> Path:
    audit = AuditLog()
    if validate_source(input_path) != "docx":
        raise ValidationError(f"{input_path} 不是 .docx")
    elements, doc = parse_docx(input_path)
    mode = "literal" if doc_code == "B" else "auto"
    for msg in inject_numbers(elements, mode):
        audit.add("编号", msg)
    for msg in cross_check_toc(elements, extract_toc(elements)):
        audit.add("目录交叉验证", msg)
    pkg_dir = Path(out_dir) / f"{doc_code}_{version}"
    image_files = extract_images(doc, elements, pkg_dir / "img", doc_code, audit, img_width)
    sections = build_tree(
        doc_code, elements, audit, image_files, literal=(mode == "literal"),
        image_sizes=image_dimensions(pkg_dir / "img", image_files),
    )
    fault_codes = extract_fault_codes(elements, doc_code, variant, audit)
    rules = extract_rules(elements, doc_code, variant, audit)
    package(pkg_dir, doc_code, variant, version, sections, fault_codes, rules)
    audit.save(pkg_dir / "audit.json")
    print(f"[{doc_code}] 章节 {len(sections)} · 故障码 {len(fault_codes)} · 保养规则 {len(rules)} · 审核项 {len(audit)}")
    print(f"数据包：{pkg_dir}")
    return pkg_dir


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pipeline", description="XC975-EV 手册抽取管线（第一批）")
    ap.add_argument("--input", required=True, help="源 .docx 路径")
    ap.add_argument("--doc", required=True, choices=["A", "B", "C"], help="文档代号")
    ap.add_argument("--variant", required=True, help="适用变体，如 国内干桥 / EU湿桥")
    ap.add_argument("--version", required=True, help="手册版本日期，如 202608")
    ap.add_argument("--out", default="dist", help="输出根目录")
    ap.add_argument("--img-width", type=int, default=800, help="图片转码目标宽度（默认屏宽 800）")
    args = ap.parse_args(argv)
    try:
        run(args.input, args.doc, args.variant, args.version, args.out, args.img_width)
    except ValidationError as e:
        print(f"拒收：{e}")
        return 2
    return 0

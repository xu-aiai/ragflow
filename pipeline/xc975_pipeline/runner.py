"""阶段化执行器：逐步执行管线，每阶段快照落盘（规格 §6.2"每阶段落盘中间产物"）。

run 目录结构：
    runs/<run_id>/run.json            运行元信息 + 各阶段状态（每阶段完成即增量写入）
    runs/<run_id>/stage_<N>.json      各阶段快照（工作台逐步展示的数据源）
    runs/<run_id>/events.jsonl        阶段事件流（工作台"流水"实时展示的数据源）
    runs/<run_id>/img/                阶段 1 提取的图片
    runs/<run_id>/package/            阶段 2 产出的数据包
"""
from __future__ import annotations

import datetime as dt
import json
import traceback
from pathlib import Path

from .audit import AuditLog
from .convert import convert_to_docx
from .docmodel import parse_docx
from .images import cell_image_files, extract_images, image_dimensions
from .numbering import cross_check_toc, extract_toc, inject_numbers
from .package import package, write_json
from .products.fault_codes import extract_fault_codes
from .products.maintenance import extract_rules
from .products.tree import build_tree
from .tables import classify_table_detailed
from .validate import ValidationError, validate_source

STAGES = ["校验", "解析", "DITA 生成"]


def _trunc(s, n=100):
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def run_stages(input_path, doc_code: str, variant: str, version: str, runs_root, img_width: int = 800,
               overrides: dict | None = None, run_id: str | None = None) -> dict:
    """执行三个阶段；返回 run.json 元信息（含各阶段状态与摘要）。

    overrides: {"表格分类": {元素ID: 分类}}，人工改标自阶段 1（解析）起生效；
    run_id 非空时复用同一 run 目录（改标后重跑）。
    """
    run_id = run_id or dt.datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{doc_code}"
    run_dir = Path(runs_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now().isoformat(timespec="seconds")
    audit = AuditLog()
    status: dict[str, dict] = {}
    mode = "literal" if doc_code == "B" else "auto"

    events_path = run_dir / "events.jsonl"
    # seq 在同一 run 目录内跨重跑连续：rerun 会清空事件文件，但 SSE/轮询
    # 靠 seq 判重，重置会导致重跑事件被误丢弃。
    seq = 0
    if events_path.is_file():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    seq = max(seq, json.loads(line).get("seq", 0))
                except json.JSONDecodeError:
                    pass
    events_path.write_text("", encoding="utf-8")  # 重跑时清空旧事件流

    def emit(类型: str, 阶段: int | None = None, 摘要: str | None = None, **kw) -> None:
        nonlocal seq
        seq += 1
        event = {"seq": seq, "时间": dt.datetime.now().isoformat(timespec="seconds"),
                 "类型": 类型, "阶段": 阶段, "摘要": 摘要, **kw}
        with events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    stage_clock: dict[int, dt.datetime] = {}

    def stage_start(n: int) -> None:
        stage_clock[n] = dt.datetime.now()
        status[str(n)] = {"名称": STAGES[n], "状态": "运行中"}
        emit("stage_start", n, STAGES[n])
        _save_meta()

    def done(n: int, summary: str, data) -> None:
        write_json(run_dir / f"stage_{n}.json", data)
        entry = {"名称": STAGES[n], "状态": "完成", "摘要": summary}
        if n in stage_clock:
            entry["耗时"] = round((dt.datetime.now() - stage_clock[n]).total_seconds(), 1)
        status[str(n)] = entry
        _save_meta()
        emit("stage_done", n, summary, 耗时=entry.get("耗时"))

    def fail(n: int, message: str) -> dict:
        status[str(n)] = {"名称": STAGES[n], "状态": "失败", "摘要": message}
        emit("stage_fail", n, message)
        traceback.print_exc()
        return _finish(message)

    def _save_meta(error_message: str | None = None, finished: bool = False) -> dict:
        meta = {
            "run_id": run_id,
            "输入": str(input_path),
            "文档": doc_code,
            "变体": variant,
            "版本": version,
            "开始": started,
            "阶段": status,
        }
        if finished:
            meta["结束"] = dt.datetime.now().isoformat(timespec="seconds")
        if error_message:
            meta["错误"] = error_message
        write_json(run_dir / "run.json", meta)
        return meta

    def _finish(error_message: str | None = None) -> dict:
        meta = _save_meta(error_message, finished=True)
        emit("run_done", None, error_message)
        return meta

    emit("run_start", None, f"{Path(input_path).name} · {doc_code} · {variant} · {version}")

    # ---- 阶段 0：校验 ----
    stage_start(0)
    src = Path(input_path)
    try:
        head = src.open("rb").read(16)
        emit("step", 0, "读取文件头", 结果=head.hex())
        size = src.stat().st_size
        emit("step", 0, "读取文件大小", 结果=f"{size / 1048576:.1f} MB")
        kind = validate_source(src)
        emit("step", 0, "格式识别与密文检查", 结果=f"识别为 {kind} 文档")
        snapshot = {"文件": src.name, "大小": size, "文件头": head.hex(), "结果": kind}
        if kind == "doc":
            src = convert_to_docx(src, run_dir / "converted")
            emit("step", 0, "转换 .doc → .docx", 结果=f"已生成 {src.name}")
            snapshot["转换"] = f"已自动转为明文 .docx：{src.name}"
        done(0, f"{Path(input_path).name} · {kind}" + ("（已自动转换）" if kind == "doc" else ""), snapshot)
    except (ValidationError, RuntimeError) as e:
        status["0"] = {"名称": STAGES[0], "状态": "失败", "摘要": str(e)}
        write_json(run_dir / "stage_0.json", {"文件": src.name, "错误": str(e)})
        emit("stage_fail", 0, str(e))
        return _finish(str(e))
    except OSError as e:
        status["0"] = {"名称": STAGES[0], "状态": "失败", "摘要": f"无法读取：{e}"}
        emit("stage_fail", 0, f"无法读取：{e}")
        return _finish(str(e))

    # ---- 阶段 1：解析 → 版面元素流（编号注入 + 表格分类 + 图片提取） ----
    stage_start(1)
    try:
        elements, doc = parse_docx(str(src))
        emit("step", 1, "解析文档结构", 结果=f"读取 {len(elements)} 个元素")
        forced = (overrides or {}).get("表格分类", {})
        for el in elements:
            if el.kind == "table" and str(el.index) in forced:
                el.forced_kind = forced[str(el.index)]
        num_audit = inject_numbers(elements, mode)
        emit("step", 1, "注入标题编号", 结果=f"生成 {sum(1 for el in elements if el.编号)} 个编号" if mode != "literal" else "保留原文编号")
        for m in num_audit:
            audit.add("编号", m)
        toc = extract_toc(elements)
        conflicts = cross_check_toc(elements, toc)
        emit("step", 1, "目录交叉验证", 结果=f"目录 {len(toc)} 条，冲突 {len(conflicts)} 个")
        for m in conflicts:
            audit.add("目录交叉验证", m)
        n_para = sum(1 for el in elements if el.kind == "para")
        n_tbl = sum(1 for el in elements if el.kind == "table")
        n_img = sum(1 for el in elements if el.kind == "para" and el.para and el.para.image_rids)
        n_box = sum(len(el.para.text_boxes) for el in elements if el.kind == "para" and el.para)
        n_head = sum(1 for el in elements if el.kind == "para" and el.heading_level is not None)
        # 完整版面元素流：每个元素带稳定 ID（文档流序号），分类标签与产品溯源
        # 都引用同一批 ID。编号、表格分类、图片提取随本阶段一并完成并呈现。
        layout = []
        section = None
        counts: dict[str, int] = {}
        for el in elements:
            if el.kind == "para":
                row = {"ID": el.index, "类型": "para", "样式": el.para.style,
                       "内容": _trunc(el.para.text, 200), "图片": len(el.para.image_rids)}
                if el.para.text_boxes:
                    row["文本框"] = el.para.text_boxes
                if el.heading_level is not None:
                    section = el.编号
                    row["编号"] = el.编号
                    row["层级"] = el.heading_level
                layout.append(row)
            else:
                g = el.table.grid
                cols = max((len(r) for r in g), default=0)
                kind, reason = classify_table_detailed(g, section)
                if el.forced_kind:
                    reason = f"人工指定（自动判定：{kind}，{reason}）"
                    kind = el.forced_kind
                counts[kind] = counts.get(kind, 0) + 1
                layout.append({"ID": el.index, "类型": "table", "样式": f"{len(g)}行×{cols}列",
                               "内容": _trunc(g[0][0] if g and g[0] else "", 200), "网格": g,
                               "图片": sum(len(r) for row in el.table.cell_rids for r in row),
                               "分类": kind, "依据": reason, "人工": bool(el.forced_kind)})
        emit("step", 1, "表格分类", 结果="、".join(f"{k} {v} 张" for k, v in sorted(counts.items())) or "未发现表格")
        image_files = extract_images(doc, elements, run_dir / "img", doc_code, audit, img_width)
        for el, row in zip(elements, layout, strict=True):
            rids = el.para.image_rids if el.kind == "para" else [rid for cells in el.table.cell_rids for cell in cells for rid in cell]
            row["图片文件"] = [image_files[rid] for rid in rids if rid in image_files]
            if el.kind == "table":
                row["cell_images"] = cell_image_files(el.table, image_files)
                row["col_spans"] = el.table.col_spans
                row["row_spans"] = el.table.row_spans
            elif any(part.kind == "image" for part in el.para.parts):
                row["parts"] = [
                    {"type": "text", "text": part.text} if part.kind == "text"
                    else {"type": "image", "file": image_files[part.rid]}
                    for part in el.para.parts
                    if part.kind == "text" or part.rid in image_files
                ]
        n_extracted = len(set(image_files.values()))
        emit("step", 1, "提取图片", 结果=f"提取 {n_extracted} 张图片")
        done(1, f"段落 {n_para} · 表格 {n_tbl} · 文本框 {n_box} · 图片锚点 {n_img} · 标题 {n_head} · 提取图片 {n_extracted}",
             {"元素总数": len(elements), "段落": n_para, "表格": n_tbl, "文本框": n_box, "图片锚点": n_img,
              "标题数": n_head, "目录条目数": len(toc), "冲突": conflicts,
              "分类统计": counts, "图片数": n_extracted, "元素": layout})
    except Exception as e:
        return fail(1, f"解析失败：{e}")

    # ---- 阶段 2：DITA 生成（产品切分 + 打包 + 审核清单） ----
    stage_start(2)
    try:
        sections = build_tree(
            doc_code, elements, audit, image_files, literal=(mode == "literal"),
            merge_pairs=(overrides or {}).get("段落合并", []),
            image_sizes=image_dimensions(run_dir / "img", image_files),
        )
        emit("step", 2, "切分章节树", 结果=f"生成 {len(sections)} 个章节")
        fault_codes = extract_fault_codes(elements, doc_code, variant, audit)
        emit("step", 2, "抽取故障码", 结果=f"提取 {len(fault_codes)} 条故障码")
        rules = extract_rules(elements, doc_code, variant, audit)
        emit("step", 2, "抽取保养规则", 结果=f"提取 {len(rules)} 条保养规则")
        pkg_dir = package(run_dir / "package", doc_code, variant, version, sections, fault_codes, rules)
        manifest = json.loads((pkg_dir / "manifest.json").read_text(encoding="utf-8"))
        emit("step", 2, "打包数据", 结果=f"写入 {pkg_dir.name} 数据包")
        audit.save(pkg_dir / "audit.json")
        emit("step", 2, "生成审核清单", 结果=f"生成 {len(audit)} 条审核项")
        done(2, f"章节 {len(sections)} · 故障码 {len(fault_codes)} · 保养规则 {len(rules)} · 审核 {len(audit)} 条",
             {"章节": [s.model_dump() for s in sections],
              "故障码": [c.model_dump() for c in fault_codes],
              "保养规则": [r.model_dump() for r in rules],
              "数据包": str(pkg_dir),
              "manifest": manifest,
              "条目": audit.entries})
    except Exception as e:
        return fail(2, f"DITA 生成失败：{e}")

    return _finish()

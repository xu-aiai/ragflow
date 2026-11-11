"""原文预览：按需用 LibreOffice 把 Word 转成 PDF（保留原始分页），按页渲染 PNG 供对照。

preview/ 目录产物：
    <手册名>.pdf     LibreOffice 转换的原文 PDF
    pages.json      页数 + 元素→页码映射 + 页面内区域坐标（悬浮热区）
    page_<N>.png    按页缓存的渲染图（110 dpi）

元素→页码用归一化文本包含匹配，按文档流顺序单调推进页指针；匹配不上的元素不映射。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

PREVIEW_MAP_VERSION = 15


def find_soffice() -> str | None:
    """在 PATH 或 Windows 默认安装目录中定位 LibreOffice。"""
    exe = shutil.which("soffice")
    if exe:
        return exe
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe",
              r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
        if Path(p).is_file():
            return p
    return None


def soffice_available() -> bool:
    return find_soffice() is not None


def find_preview_pdf(preview_dir: Path) -> str | None:
    for f in sorted(preview_dir.glob("*.pdf")):
        return f.name
    return None


def render_preview(source: str, out_dir: Path) -> str:
    """把 Word 转成 PDF，返回 PDF 文件名；失败抛 RuntimeError。"""
    if not soffice_available():
        raise RuntimeError("未检测到 LibreOffice（soffice），无法生成原文预览")
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [find_soffice(), "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(source)],
            check=True, capture_output=True, timeout=300,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"LibreOffice 转换失败：{e.stderr.decode(errors='replace')[:200]}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("LibreOffice 转换超时（300 秒）") from e
    name = find_preview_pdf(out_dir)
    if not name:
        raise RuntimeError("LibreOffice 未产出 PDF 文件")
    return name


def _norm(s: str) -> str:
    s = re.sub(r"[.…·]{2,}", "", s or "")  # 目录引导点不参与匹配
    return re.sub(r"\s+", "", s)


def build_page_map(pdf_path: Path, elements) -> dict:
    """返回 {"页数": N, "元素页": {元素ID: 1基页码}, "区域": {页码: [{ids, box}]}}。

    区域由 PDF 行级文本框按元素归并（段落级），box 为页面归一化百分比
    [left, top, width, height]，供前端悬浮热区使用。
    """
    import pymupdf

    pages = []
    with pymupdf.open(pdf_path) as pdf:
        for page in pdf:
            # 行级文本框（比块级更贴合文字，区域对齐更紧）
            lines = []
            image_blocks = []
            for b in page.get_text("dict")["blocks"]:
                if b.get("type") == 1:
                    image_blocks.append(list(b["bbox"]))
                    continue
                if b.get("type") != 0:
                    continue
                for ln in b["lines"]:
                    txt = "".join(s["text"] for s in ln["spans"])
                    if _norm(txt):
                        lines.append({"box": list(ln["bbox"]), "text": _norm(txt)})
            pages.append({"text": _norm(page.get_text()), "lines": lines, "images": image_blocks,
                          "leaders": len(re.findall(r"[.…·]{4,}", page.get_text())),
                          "w": page.rect.width, "h": page.rect.height})

    mapping: dict[str, int] = {}
    page_groups: dict[str, list[int]] = {}
    fulltexts: dict[int, str] = {}
    anchors: dict[int, str] = {}
    toc_pages: set[int] = set()

    # 先配目录条目（toc * 样式）：从含引导点的目录起始页开始，标题去掉页码匹配
    toc_start = next((i for i, p in enumerate(pages) if p["leaders"] >= 3), 0)
    for el in elements:
        if el.kind != "para" or not re.match(r"toc", getattr(el.para, "style", "") or "", re.IGNORECASE):
            continue
        title = re.sub(r"[\s.…·]*[IVXLC\d]+$", "", (el.para.text or "").strip())
        snippet = _norm(title)
        if len(snippet) < 2:
            continue
        for pn in range(toc_start, len(pages)):
            if snippet in pages[pn]["text"]:
                mapping[str(el.index)] = pn + 1
                # 保留页码后的完整目录文本用于区域定位；仅用标题片段做分页匹配。
                fulltexts[el.index] = _norm(el.para.text or "")
                toc_pages.add(pn + 1)
                toc_start = pn
                break

    # 正文元素：跳过目录页，避免标题被错配到同名目录条目上
    cur = 0
    short_match_counts: dict[str, int] = {}
    for el in elements:
        if el.kind == "para" and re.match(r"toc", getattr(el.para, "style", "") or "", re.IGNORECASE):
            continue
        if el.kind == "para":
            full = _norm(el.para.text)
            snippets = [full[:60]]
        else:
            full = _norm("".join("".join(row) for row in el.table.grid))
            snippets = [full[:60]]
            first_cell = _norm(el.table.grid[0][0] if el.table.grid and el.table.grid[0] else "")
            if first_cell:
                snippets.append(first_cell)  # 表头跨行/跨列时退化为首格匹配
        if not full:
            continue
        is_short_text = len(full) < 6
        if is_short_text:
            candidate_pages = [
                pn for pn in range(cur, len(pages))
                if pn + 1 not in toc_pages and any(line["text"] == full for line in pages[pn]["lines"])
            ]
            if not candidate_pages:
                continue
            occurrence = short_match_counts.get(full, 0)
            pn = candidate_pages[min(occurrence, len(candidate_pages) - 1)]
            mapping[str(el.index)] = pn + 1
            page_groups[str(el.index)] = [pn + 1]
            fulltexts[el.index] = full
            anchors[el.index] = full
            short_match_counts[full] = occurrence + 1
            cur = pn
            continue
        for pn in range(cur, len(pages)):
            if pn + 1 in toc_pages:
                continue  # 目录页不参与正文匹配
            end_pn = pn
            hit = next((s for s in snippets if (len(s) >= 6 and s in pages[pn]["text"]) or (len(s) < 6 and any(line["text"] == s for line in pages[pn]["lines"]))), None)
            if hit is None and pn + 1 < len(pages) and pn + 2 not in toc_pages:
                previous_text = re.sub(r"(?:\d+|[IVXLC]+)$", "", pages[pn]["text"])
                combined_text = previous_text + pages[pn + 1]["text"]
                hit = next((s for s in snippets if s in combined_text and s not in pages[pn + 1]["text"]), None)
                if hit is not None:
                    end_pn = pn + 1
            if hit is not None:
                mapping[str(el.index)] = pn + 1
                page_groups[str(el.index)] = list(range(pn + 1, end_pn + 2))
                fulltexts[el.index] = full
                anchors[el.index] = hit
                cur = end_pn
                break

    # 前向游标可能被长文本误配推进，未命中的元素再独立寻找全书唯一匹配页。
    matched_text_counts: dict[str, int] = {}
    for el in elements:
        if str(el.index) not in mapping:
            continue
        text = _norm(el.para.text) if el.kind == "para" else _norm("".join("".join(row) for row in el.table.grid))
        if text:
            matched_text_counts[text] = matched_text_counts.get(text, 0) + 1
    for el in elements:
        eid = str(el.index)
        if eid in mapping or (el.kind == "para" and re.match(r"toc", getattr(el.para, "style", "") or "", re.IGNORECASE)):
            continue
        if el.kind == "para":
            full = _norm(el.para.text)
            snippets = [full[:60]]
        else:
            full = _norm("".join("".join(row) for row in el.table.grid))
            snippets = [full[:60]]
            first_cell = _norm(el.table.grid[0][0] if el.table.grid and el.table.grid[0] else "")
            if first_cell:
                snippets.append(first_cell)
        if not full:
            continue
        candidates = []
        for pn, page in enumerate(pages):
            if pn + 1 in toc_pages:
                continue
            if len(full) < 6:
                hit = full if any(line["text"] == full for line in page["lines"]) else None
            else:
                hit = next((s for s in snippets if (len(s) >= 6 and s in page["text"]) or (len(s) < 6 and any(line["text"] == s for line in page["lines"]))), None)
            if hit is not None:
                candidates.append((pn, hit))
        if candidates:
            occurrence = matched_text_counts.get(full, 0)
            candidates = [candidates[min(occurrence, len(candidates) - 1)]]
            matched_text_counts[full] = occurrence + 1
        if len(candidates) == 1:
            pn, hit = candidates[0]
            mapping[eid] = pn + 1
            page_groups[eid] = [pn + 1]
            fulltexts[el.index] = full
            anchors[el.index] = hit

    # 纯图片段落没有文本可匹配，按文档顺序分配当前页尚未使用的 PDF 图片块。
    regions: dict[int, list] = {}
    used_image_blocks: dict[int, int] = {}
    last_page = 1
    for el in elements:
        eid = str(el.index)
        if el.kind == "para" and not _norm(el.para.text) and el.para.image_rids and eid not in mapping:
            available = pages[last_page - 1]["images"]
            start = used_image_blocks.get(last_page, 0)
            count = min(len(el.para.image_rids), len(available) - start)
            if count > 0:
                mapping[eid] = last_page
                page_groups[eid] = [last_page]
                fulltexts[el.index] = ""
                anchors[el.index] = ""
                for box in available[start:start + count]:
                    regions.setdefault(last_page, []).append({"ids": [el.index], "box": list(box), "bottom": box[3]})
                used_image_blocks[last_page] = start + count
        if eid in mapping:
            last_page = page_groups.get(eid, [mapping[eid]])[-1]

    # 区域归并：LibreOffice 的 PDF 基本是一行一个文本块，按"块文本是元素全文的
    # 子串"把同一元素的所有行合并为段落级区域；短结尾行按全文后缀并入上一区域。
    region_pages = sorted({pn for eid in mapping for pn in page_groups.get(eid, [mapping[eid]])} | set(regions))
    for pn1 in region_pages:
        page = pages[pn1 - 1]
        candidates = sorted(eid for eid in fulltexts if pn1 in page_groups.get(str(eid), [mapping[str(eid)]]))
        candidates = [(eid, fulltexts[eid]) for eid in candidates]
        table_ids = {el.index for el in elements if el.kind == "table"}
        used_table_anchors = set()
        used_short_texts = set()
        current = None
        for b in sorted(page["lines"], key=lambda b: (b["box"][1], b["box"][0])):
            # 优先要求完整元素文本命中；短文本是长文本的子串时不能反向归属，
            # 否则“目录”会错误匹配到“目录 II”，产生两个高亮区域。
            owner = next((eid for eid, full in candidates
                          if (full == b["text"] and (len(full) >= 6 or eid not in used_short_texts))
                          or (anchors.get(eid) == b["text"]
                              and (eid not in table_ids or eid not in used_table_anchors)
                              and (len(full) >= 6 or eid not in used_short_texts))
                          or (len(full) >= 6 and full in b["text"])), None)
            if owner is None and current is not None and len(b["text"]) >= 6 and b["text"] in fulltexts[current["ids"][0]]:
                owner = current["ids"][0]
            if owner is None:
                owner = next((eid for eid, full in candidates
                              if len(b["text"]) >= 6 and b["text"] in full), None)
            if owner is None and current is not None:
                gap = b["box"][1] - current["bottom"]
                current_full = fulltexts[current["ids"][0]]
                is_short_continuation = 0 < len(b["text"]) < 6 and current_full.endswith(b["text"]) and 0 <= gap < 60
                is_table_row = current["ids"][0] in table_ids and 0 <= gap < 60
                if gap < 8 or is_short_continuation or is_table_row:
                    owner = current["ids"][0]
            if owner is None:
                continue
            if len(fulltexts[owner]) < 6:
                used_short_texts.add(owner)
            if owner in table_ids and anchors.get(owner) == b["text"]:
                used_table_anchors.add(owner)
            if current is None or current["ids"][0] != owner:
                current = {"ids": [owner], "box": list(b["box"]), "bottom": b["box"][3]}
                regions.setdefault(pn1, []).append(current)
            else:
                box = current["box"]
                box[0] = min(box[0], b["box"][0])
                box[1] = min(box[1], b["box"][1])
                box[2] = max(box[2], b["box"][2])
                box[3] = max(box[3], b["box"][3])
            current["bottom"] = b["box"][3]

        # 目录标题可能在 PDF 中重复出现（例如页面大标题“目录”和目录行“目录 II”）。
        # 一个目录元素只保留页面中更靠后的目录行区域，避免一个右侧元素对应两个高亮框。
        toc_ids = {
            el.index for el in elements
            if el.kind == "para" and re.match(r"toc", getattr(el.para, "style", "") or "", re.IGNORECASE)
        }
        for eid in toc_ids:
            matches = [r for r in regions.get(pn1, []) if eid in r["ids"]]
            if len(matches) > 1:
                keep = max(matches, key=lambda r: r["box"][1])
                regions[pn1] = [r for r in regions[pn1] if eid not in r["ids"] or r is keep]

    for pn1, rs in regions.items():
        page = pages[pn1 - 1]
        for r in rs:
            x0, y0, x1, y1 = r.pop("box")
            r["box"] = [round(x0 / page["w"] * 100, 2), round(y0 / page["h"] * 100, 2),
                        round((x1 - x0) / page["w"] * 100, 2), round((y1 - y0) / page["h"] * 100, 2)]
            r.pop("bottom")
    info = {"映射版本": PREVIEW_MAP_VERSION, "页数": len(pages), "元素页": mapping, "元素页组": page_groups, "区域": regions}
    (pdf_path.parent / "pages.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return info


def render_page_png(pdf_path: Path, page_number: int, out_path: Path, dpi: int = 110) -> Path:
    """渲染指定页为 PNG（调用方负责缓存判断）。页码越界抛 ValueError。"""
    import pymupdf

    with pymupdf.open(pdf_path) as pdf:
        if not 1 <= page_number <= len(pdf):
            raise ValueError(f"页码 {page_number} 超出范围（共 {len(pdf)} 页）")
        pdf[page_number - 1].get_pixmap(dpi=dpi).save(out_path)
    return out_path

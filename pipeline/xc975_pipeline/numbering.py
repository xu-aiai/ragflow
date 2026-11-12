"""阶段 2：标题识别与编号注入。

A/C：标题样式大小写不敏感识别（三份手册样式名为小写 "heading n"）+ 位置推导编号，
     目录仅作交叉验证，冲突进审核清单（附录 A.1 已实测 0 冲突）。
B：编号为字面文本，四种格式（00 / 一、 / 1.2.4.1 / §1.1）归一为点分十进制。
"""
from __future__ import annotations

import re

from .docmodel import Element

_HEADING_STYLE = re.compile(r"^heading\s*(\d)?", re.IGNORECASE)
_TOC_STYLE = re.compile(r"^toc", re.IGNORECASE)
_TOC_ENTRY = re.compile(r"^\s*(\d+(?:\.\d+)*)\s+(.+?)[.\s…·]*\s*(\d+)?\s*$")

# B 手册字面编号 → 点分十进制（列表顺序即匹配优先级）
_B_LITERAL = [
    re.compile(r"^§(\d+(?:\.\d+)*)"),           # §1.1 → 1.1
    re.compile(r"^(\d{2})(?![\d.])"),           # 00/01 章号 → 去前导零
    re.compile(r"^([一二三四五六七八九十]+)、"),  # 一、 → 中文数字
    re.compile(r"^(\d+(?:\.\d+)+)"),            # 1.2.4.1 / 10.5.2 原样，避免匹配正文“1）”
    re.compile(r"^(\d+)(?=\s|$)"),               # 独立的数字章节号（如“1 电气系统”）
]
_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

_STRIP_PREFIX = re.compile(
    r"^(?:§\s*)?(?:\d+(?:\.\d+)*)\s*[、.．]?\s*|^[一二三四五六七八九十]+\s*、\s*"
)


def heading_level(style_name: str, outline_lvl: int | None = None) -> int | None:
    m = _HEADING_STYLE.match(style_name or "")
    if m:
        return int(m.group(1)) if m.group(1) else 1
    if outline_lvl is not None and 0 <= outline_lvl <= 8:
        return outline_lvl + 1
    return None


def _cn_to_int(s: str) -> int:
    if s == "十":
        return 10
    if "十" in s:
        left, _, right = s.partition("十")
        return _CN_DIGITS.get(left, 1) * 10 + (_CN_DIGITS[right] if right else 0)
    return _CN_DIGITS[s]


def literal_number(text: str) -> str | None:
    """B 手册：从标题文本抽取并归一编号。"""
    text = (text or "").strip()
    for i, pat in enumerate(_B_LITERAL):
        m = pat.match(text)
        if not m:
            continue
        raw = m.group(1)
        if i == 1:
            return str(int(raw))
        if i == 2:
            return str(_cn_to_int(raw))
        return raw
    return None


def strip_literal_prefix(text: str) -> str:
    """B 手册：标题文本去掉字面编号前缀。"""
    stripped = _STRIP_PREFIX.sub("", (text or "").strip()).strip()
    return stripped or (text or "").strip()


def inject_numbers(elements: list[Element], mode: str) -> list[str]:
    """填充 heading_level 与 编号；返回审核消息。

    mode: "auto"（A/C 位置推导）或 "literal"（B 字面归一）。
    """
    audit: list[str] = []
    if mode == "literal":
        body_started = False
        scope_level = None
        scope_number_depth = None
        previous_number = None
        previous_level = None
        for el in elements:
            if el.kind != "para" or el.para is None:
                continue
            if _TOC_STYLE.match(el.para.style or ""):
                continue  # 目录段落不是正文标题
            num = literal_number(el.para.text)
            lvl = heading_level(el.para.style)
            if lvl is None and not body_started:
                # 前言中的章节概述（如“00总则”“01电气系统”）是普通正文，
                # 在遇到真正的编号标题前不能据此创建章节。
                continue
            if num is None and lvl is None:
                continue
            if lvl is None:
                # 普通正文中的“1 xxx”“2 xxx”是条目，不是章节；只有多级编号
                # （1.7.3）、§ 编号或中文章节号才允许无标题样式推导层级。
                text = (el.para.text or "").strip()
                if "." not in num and not text.startswith(("§", "一、", "二、", "三、", "四、", "五、", "六、", "七、", "八、", "九、", "十、")):
                    continue
            # B 手册的点分编号本身就是可靠的结构层级；Word 样式经常只到
            # Heading 2，不能让样式层级覆盖 3.2.9 / 3.2.9.1 这类编号。
            if num and "." in num:
                lvl = len(num.split("."))
            elif lvl is None:
                lvl = len(num.split("."))
            if num is not None:
                absolute_level = len(num.split("."))
                is_extension = previous_number is not None and num.startswith(previous_number + ".")
                if absolute_level == 1 and not num.endswith(".0"):
                    scope_level = None
                    scope_number_depth = None
                    lvl = 1
                else:
                    if (
                        scope_level is not None
                        and not num.endswith(".0")
                        and not is_extension
                        and absolute_level <= scope_level
                        and num.split(".")[0] != previous_number.split(".")[0]
                    ):
                        scope_level = None
                        scope_number_depth = None
                        lvl = absolute_level
                    else:
                        if (
                            scope_level is None
                            and previous_number is not None
                            and len(previous_number.split(".")) > 1
                            and not is_extension
                            and absolute_level <= previous_level
                            and num.split(".")[0] != previous_number.split(".")[0]
                        ):
                            scope_level = previous_level
                            scope_number_depth = absolute_level
                        if scope_level is not None:
                            lvl = scope_level + 1 + absolute_level - scope_number_depth
                previous_number = num
                previous_level = lvl
            if num is not None and heading_level(el.para.style) is not None:
                body_started = True
            el.heading_level = lvl
            el.编号 = num
            if num is None:
                audit.append(f"B 手册标题无法归一编号：{el.para.text.strip()[:40]}")
        return audit
    counters: dict[int, int] = {}
    for el in elements:
        if el.kind != "para" or el.para is None:
            continue
        lvl = heading_level(el.para.style)
        if lvl is None:
            continue
        el.heading_level = lvl
        counters[lvl] = counters.get(lvl, 0) + 1
        for deeper in [k for k in counters if k > lvl]:
            counters[deeper] = 0
        missing = [k for k in range(1, lvl + 1) if k not in counters]
        if missing:
            audit.append(f"层级跳跃：'{el.para.text.strip()[:40]}' 层级 {lvl} 缺少上级 {missing}")
        el.编号 = ".".join(str(counters[k]) for k in sorted(counters) if k <= lvl)
    return audit


def extract_toc(elements: list[Element]) -> list[tuple[str, str, str | None]]:
    """从目录样式段落抽取 (编号, 标题, 页码)。"""
    out = []
    for el in elements:
        if el.kind == "para" and el.para and _TOC_STYLE.match(el.para.style or ""):
            entry = parse_toc_entry(el.para.text)
            if entry:
                out.append(entry)
    return out


def parse_toc_entry(text: str) -> tuple[str, str, str | None] | None:
    m = _TOC_ENTRY.match(text or "")
    if m:
        num = literal_number(m.group(1)) or m.group(1)
        return num, m.group(2).strip(), m.group(3)
    # B 手册字面编号目录（一、 / 00 / §1.1 等），编号归一规则与正文一致
    num = literal_number((text or "").strip())
    if num is None:
        return None
    page = re.search(r"(\d+)\s*$", text or "")
    title = re.sub(r"[\s.…·]*\d+\s*$", "", strip_literal_prefix(text)).strip()
    return num, title, page.group(1) if page else None


def cross_check_toc(elements: list[Element], toc_entries) -> list[str]:
    """目录编号 vs 推导编号，按标题出现顺序配对（同名标题各配各的）。"""
    from collections import defaultdict

    derived: dict[str, list[str]] = defaultdict(list)
    for el in elements:
        if el.kind == "para" and el.para and el.heading_level is not None:
            derived[strip_literal_prefix(el.para.text)].append(el.编号)
    used: dict[str, int] = defaultdict(int)
    conflicts = []
    for num, title, _page in toc_entries:
        lst = derived.get(title) or []
        i = used[title]
        if i >= len(lst):
            conflicts.append(f"目录条目在正文无对应标题（陈旧目录）：{num} {title}")
            continue
        used[title] = i + 1
        if lst[i] != num:
            conflicts.append(f"编号不一致：目录 {num} vs 正文推导 {lst[i]}（{title}）")
    return conflicts

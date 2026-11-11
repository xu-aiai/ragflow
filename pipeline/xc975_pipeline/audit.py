"""阶段 7：审核清单（规格 §3.E）——全阶段副产物汇总，人工质量门。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AuditLog:
    entries: list[dict] = field(default_factory=list)

    def add(self, 类别: str, 说明: str, 位置: str | None = None) -> None:
        entry = {"类别": 类别, "说明": 说明}
        if 位置:
            entry["位置"] = 位置
        self.entries.append(entry)

    def save(self, path) -> None:
        from .package import write_json
        write_json(path, self.entries)

    def __len__(self) -> int:
        return len(self.entries)

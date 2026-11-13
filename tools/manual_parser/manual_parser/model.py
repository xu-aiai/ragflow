from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float

    def as_list(self) -> list[float]:
        return [round(self.x0, 2), round(self.y0, 2), round(self.x1, 2), round(self.y1, 2)]


@dataclass
class Evidence:
    channel: str
    source_id: str
    confidence: float = 1.0
    detail: str = ""


@dataclass
class Block:
    id: str
    type: str
    text: str = ""
    page: int | None = None
    bbox: BBox | None = None
    html: str = ""
    level: int | None = None
    reading_order: int = 0
    confidence: float = 1.0
    region_image: str = ""
    parent_id: str | None = None
    continuation_of: str | None = None
    children: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    parts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["bbox"] = self.bbox.as_list() if self.bbox else None
        return result


@dataclass
class Page:
    number: int
    width: float
    height: float
    image: str
    block_ids: list[str] = field(default_factory=list)
    printed_page_label: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParseIssue:
    code: str
    message: str
    severity: str = "warning"
    block_id: str | None = None
    page: int | None = None


@dataclass
class DocumentResult:
    id: str
    filename: str
    source_type: str
    pages: list[Page]
    blocks: list[Block]
    tree: list[dict[str, Any]]
    markdown: str
    issues: list[ParseIssue]
    metrics: dict[str, Any]
    pipeline: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "manual-parser/2.0",
            "id": self.id,
            "filename": self.filename,
            "source_type": self.source_type,
            "pages": [page.to_dict() for page in self.pages],
            "blocks": [block.to_dict() for block in self.blocks],
            "tree": self.tree,
            "markdown": self.markdown,
            "issues": [asdict(issue) for issue in self.issues],
            "metrics": self.metrics,
            "pipeline": self.pipeline,
        }

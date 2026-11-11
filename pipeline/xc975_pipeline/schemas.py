"""通用数据规范 schema（规格 §3：脊柱 + 内容单元/实体/规则三子模型）。

字段名与规格文档的 JSON 示例保持一致（含中文字段名）。
块类型是封闭集：QML 端每种块一个 delegate，未知类型必须在抽取期进审核清单。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1"


# ---- 脊柱（规格 §3.1）：实体/规则类单元共享 ----


class AnchoredRecord(BaseModel):
    """脊柱基类：锚体系（来源=section_id 列表、src=版面流元素 ID）+ 变体元数据 + 质量标记。"""
    来源: list[str] = Field(default_factory=list)
    src: list[int] = Field(default_factory=list)
    适用变体: str | None = None
    审核标记: str | None = None


# ---- 内容单元（规格 §3.2）：封闭块集 ----


class ParaTextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ParaImagePart(BaseModel):
    type: Literal["image"] = "image"
    file: str


class ParaBlock(BaseModel):
    type: Literal["para"] = "para"
    text: str
    parts: list[ParaTextPart | ParaImagePart] = Field(default_factory=list)
    src: list[int] = Field(default_factory=list)  # 来源元素 ID（阶段 1 版面流）


class ImageBlock(BaseModel):
    type: Literal["image"] = "image"
    file: str
    图号: str | None = None
    题注: str | None = None
    src: list[int] = Field(default_factory=list)


class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    cell_images: list[list[list[str]]] = Field(default_factory=list)
    col_spans: list[list[int]] = Field(default_factory=list)
    row_spans: list[list[int]] = Field(default_factory=list)
    src: list[int] = Field(default_factory=list)


class WarningBlock(BaseModel):
    type: Literal["warning"] = "warning"
    level: Literal["注意", "警告", "危险"]
    text: str
    src: list[int] = Field(default_factory=list)


class StepsBlock(BaseModel):
    type: Literal["steps"] = "steps"
    items: list[str] = Field(default_factory=list)
    src: list[int] = Field(default_factory=list)


class ListBlock(BaseModel):
    type: Literal["list"] = "list"
    style: Literal["check", "plain"] = "plain"
    items: list[str] = Field(default_factory=list)
    src: list[int] = Field(default_factory=list)


Block = ParaBlock | ImageBlock | TableBlock | WarningBlock | StepsBlock | ListBlock


class Section(BaseModel):
    section_id: str
    seq: int
    章节号: str | None = None
    标题: str
    层级: int
    parent: str | None = None
    面包屑: str = ""
    src: list[int] = Field(default_factory=list)  # 标题元素 ID
    blocks: list[Block] = Field(default_factory=list)


# ---- 实体（规格 §3.3）----


class FaultCode(AnchoredRecord):
    code_id: str
    控制器: str
    代码: str
    故障名称: str
    触发条件: str | None = None
    故障等级: int | None = None
    解决措施: str | None = None


# ---- 规则（规格 §3.4）----


class MaintenanceRule(AnchoredRecord):
    rule_id: str
    触发: dict = Field(default_factory=dict)
    内容: str
    累积: list[str] = Field(default_factory=list)


# ---- 数据包 manifest（规格 §6.1）----


class Manifest(BaseModel):
    数据包: str
    文档: str
    适用变体: str
    手册版本: str
    schema_version: str = SCHEMA_VERSION
    生成时间: str
    文件: list[dict] = Field(default_factory=list)
    规模: dict = Field(default_factory=dict)

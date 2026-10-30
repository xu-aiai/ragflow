#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

"""Conservative document metadata extraction from the filename only."""

import re
import unicodedata
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path

from common.metadata_utils import update_metadata_to

_UNICODE_HYPHENS = str.maketrans({char: "-" for char in "‐‑‒–—―﹘﹣－"})

_BRAND_PATTERN = re.compile(r"徐工|XCMG", re.IGNORECASE)
_MANUAL_CODE_PATTERN = re.compile(r"(?<![A-Z0-9])PS\d{6,}(?![A-Z0-9])", re.IGNORECASE)

# Known XCMG product-family prefixes. Keeping an allow-list prevents internal BOM
# numbers, dates, battery capacities, engine models, and controller identifiers
# from being promoted to equipment models merely because they contain letters and
# digits. The captured token is preserved; no alias or sibling model is inferred.
_MODEL_PATTERN = re.compile(
    r"(?<![A-Z0-9])(?:XCA|XCT|XGC|XDR|XC|XE|LW|HB|GR|RP|XS|XZ)\d[A-Z0-9]*(?:-[A-Z0-9]+)*(?![A-Z0-9])",
    re.IGNORECASE,
)

_EQUIPMENT_TYPES = (
    (re.compile(r"液压挖掘机"), "液压挖掘机"),
    (re.compile(r"轮胎式装载机"), "轮胎式装载机"),
    (re.compile(r"车载式混凝土泵车"), "车载式混凝土泵车"),
    # Less specific names are accepted only when the more specific canonical
    # phrase above was not present.
    (re.compile(r"装载机"), "轮胎式装载机"),
    (re.compile(r"挖掘机"), "液压挖掘机"),
    (re.compile(r"混凝土泵车|泵车"), "车载式混凝土泵车"),
)

# Order expresses priority when a filename matches more than two categories.
_MANUAL_TYPES = (
    (re.compile(r"安全(?:规范|规定|手册)?"), "安全规范"),
    (re.compile(r"操作|使用说明|操保"), "操作方法"),
    (re.compile(r"保养周期|维护周期"), "保养周期"),
    (re.compile(r"保养|维护|操保"), "保养步骤"),
    (re.compile(r"故障|诊断|排查|维修"), "故障排查"),
    (re.compile(r"油液|润滑油|液压油|机油"), "油液规格"),
    (re.compile(r"技术参数|性能参数"), "技术参数"),
    (re.compile(r"部件说明|结构说明|系统原理|原理图"), "部件说明"),
)


def _append_unique(target: list[str], values: Iterable[str]) -> None:
    for value in values:
        if value and value not in target:
            target.append(value)


def _normalize_filename(filename: str) -> str:
    name = Path(str(filename or "")).name
    return unicodedata.normalize("NFKC", name).translate(_UNICODE_HYPHENS)


def _extract_equipment_types(filename: str) -> list[str]:
    for pattern, equipment_type in _EQUIPMENT_TYPES:
        if pattern.search(filename):
            return [equipment_type]
    return []


def _extract_manual_types(filename: str) -> list[str]:
    manual_types = []
    for pattern, manual_type in _MANUAL_TYPES:
        if pattern.search(filename):
            _append_unique(manual_types, (manual_type,))
        if len(manual_types) >= 2:
            break
    return manual_types


def extract_document_metadata(filename: str) -> dict[str, list[str]]:
    """Extract the five approved metadata fields from a filename.

    Every value has one stable type: ``list[str]``. A field is omitted when the
    filename does not provide reliable evidence. In particular, this function does
    not infer brand from a model prefix and does not expand model aliases/families.
    """
    normalized_name = _normalize_filename(filename)
    metadata: dict[str, list[str]] = {}

    if _BRAND_PATTERN.search(normalized_name):
        metadata["brand"] = ["徐工"]

    equipment_types = _extract_equipment_types(normalized_name)
    if equipment_types:
        metadata["equipment_type"] = equipment_types

    models = []
    _append_unique(models, (match.group(0).upper() for match in _MODEL_PATTERN.finditer(normalized_name)))
    if models:
        metadata["models"] = models

    manual_codes = []
    _append_unique(manual_codes, (match.group(0).upper() for match in _MANUAL_CODE_PATTERN.finditer(normalized_name)))
    if manual_codes:
        metadata["manual_code"] = manual_codes

    manual_types = _extract_manual_types(normalized_name)
    if manual_types:
        metadata["manual_type"] = manual_types

    return metadata


def attach_document_metadata(chunks: list[dict] | None, filename: str) -> list[dict]:
    """Attach one document metadata payload to the first chunk for persistence."""
    output = [dict(chunk) for chunk in (chunks or [])]
    if not output:
        return output

    metadata = extract_document_metadata(filename)
    existing = output[0].get("metadata")
    if isinstance(existing, dict):
        metadata = update_metadata_to(deepcopy(existing), metadata)
    output[0]["metadata"] = metadata
    return output

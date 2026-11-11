# 技术手册领域模型与数据格式规格（草案）

## 1. 目标与核心原则

本规格定义一套与行业结构化技术出版物思想对齐的数据契约，支撑：

- 多手册、完整目录和多终端阅读；
- 故障码等确定性查询与确定性答案；
- 保养周期和保养条件的确定性规则求值；
- 全文检索、精确技术数据查询和在线语义问答；
- Web、QML 车机、离线包及后续 DITA/EPUB 导出。

核心原则：

1. **规范内容与领域规则是唯一权威来源，搜索、RAG 和终端页面均为派生产物。**
2. **原件不可变，已发布 Edition 不可变。** 修改内容必须产生新版本。
3. **标识、显示文本和文件位置分离。** ID 不包含可能变化的章节号或标题。
4. **适用性、来源和审核是每类记录的一等契约。** 不允许只存在于页面或自由文本中。
5. **确定性功能不使用相似度猜测。** 无匹配、上下文不足或有歧义时必须明确返回状态。
6. **一套字段契约贯穿 API、存储和离线包。** 不维护中英文双字段映射。

## 2. 分层模型

```text
SourceDocument（不可变原件）
        │
        ▼
Manual → Edition → Section → Block → Asset
        │
        ├── FaultCode（故障注册记录）
        ├── MaintenanceRule（保养规则）
        ├── DiagnosticRule（后续独立诊断规则）
        └── CrossRef（章节/故障/保养/图片之间的引用）
        │
        ├── SearchRecord（派生索引）
        ├── RAGChunk（派生语料）
        └── OfflinePackage（终端发布产物）
```

边界说明：

- Fault Code 查询回答“这个控制器代码是什么意思、怎么处理”。
- Diagnostic Rule 回答“出现某现象后应做哪些检查、如何根据结果分支”。后者不得混入故障码表。
- Maintenance Rule 回答“何时做什么保养”。提醒计算由规则引擎执行，不由文档渲染器承担。

## 3. 通用约定

### 3.1 字段与枚举

- 数据字段使用 `snake_case`，与现有 `section_id`、`code_id` 保持一致。
- 枚举使用 `UPPER_SNAKE`。
- 中文是展示内容，不再作为机器字段名或唯一关联键。
- 日期时间使用带时区的 ISO 8601；数值与单位分离。
- 列表接口统一分页；空集合返回 `[]`，不省略必填字段。

### 3.2 标识与版本

| 字段 | 含义 |
|---|---|
| `manual_id` | 手册族的永久逻辑 ID，不随改版变化 |
| `edition_id` | 一个不可变内容版本的 ID |
| `section_id` | Edition 内唯一的章节 ID |
| `anchor_key` | 同一逻辑章节跨 Edition 的稳定锚点 |
| `fault_id` / `rule_id` | Edition 内唯一记录 ID |
| `logical_fault_id` / `logical_rule_id` | 同一故障/保养规则跨 Edition 的逻辑 ID |
| `block_id` | Section 内稳定内容块 ID |
| `asset_id` | 资源 ID；内容哈希用于跨文档去重，不替代业务 ID |

禁止把标题、章节号或显示名称直接作为主键。现有包含章节标题的 `code_id` 应迁移为稳定 ID，并保留旧 ID 仅用于迁移核对。

### 3.3 Edition 状态

```text
DRAFT → IN_REVIEW → APPROVED → PUBLISHED → SUPERSEDED
                                      └──────→ WITHDRAWN
```

只有 `PUBLISHED` 可进入默认搜索、RAG 和正式离线包。`SUPERSEDED` 用于历史追溯；`WITHDRAWN` 的离线策略需按安全规则执行。

## 4. 公共数据结构

### 4.1 适用性规则

```json
{
  "rule_id": "VAR-CN-DRY-OPERATOR",
  "mode": "ALL",
  "criteria": [
    {"axis": "market", "operator": "IN", "values": ["CN"]},
    {"axis": "axle", "operator": "IN", "values": ["DRY"]},
    {"axis": "audience", "operator": "IN", "values": ["OPERATOR"]},
    {"axis": "serial_number", "operator": "BETWEEN", "values": ["253913260", "253913261"]}
  ],
  "on_unknown": "REJECT"
}
```

约束：

- `mode` 为 `ALL` 或 `ANY`；复杂优先级由规则定义，不散落在客户端。
- 操作符使用受控集合，如 `IN`、`NOT_IN`、`EQUALS`、`BETWEEN`。
- 轴值来自受控词表，别名只在解析输入时使用。
- `on_unknown` 至少支持 `REJECT`、`REVIEW`；正式发布不得保留未处理的 `REVIEW`。
- Section、Block、FaultCode 和 MaintenanceRule 通过 `applicability_rule_ids` 引用规则。

### 4.2 来源引用

```json
{
  "source_document_id": "SRC-B-20260824",
  "edition_id": "B-20260824",
  "section_id": "B-1.8.2.1",
  "block_id": "B-1.8.2.1-T01",
  "source_element_ids": [1945],
  "page": null,
  "bbox": null,
  "excerpt_hash": "sha256:..."
}
```

- DOCX 无固定页码时，`page` 和 `bbox` 可为空。
- PDF 有可靠位置时填写页码和区域。
- `source_element_ids` 保留当前 `src` 的溯源能力。
- 不使用无版本的本地文件路径作为长期来源。

### 4.3 审核信息

对外发布记录至少携带：

```json
{
  "review_status": "APPROVED",
  "review_flags": []
}
```

审核人、内部备注和详细审计事件保存在平台内部，不默认下发车机。`review_flags` 非空时不得进入正式发布，除非相应质量门明确允许且已人工确认。

## 5. 手册内容格式

### 5.1 Manual 与 Edition

```json
{
  "manual_id": "XC975-EV-SERVICE",
  "title": "XC975-EV 维修保养手册",
  "manual_type": "SERVICE",
  "default_language": "zh-CN",
  "audience": "TECHNICIAN",
  "editions": [
    {
      "edition_id": "B-20260824",
      "version_label": "20260824",
      "status": "PUBLISHED",
      "published_at": "2026-08-24T00:00:00+08:00",
      "supersedes": null,
      "content_hash": "sha256:..."
    }
  ]
}
```

### 5.2 Section

```json
{
  "section_id": "B-1.8.2.1",
  "anchor_key": "electrical-motor-controller-diagnostics",
  "edition_id": "B-20260824",
  "parent_id": "B-1.8.2",
  "seq": 120,
  "display_number": "1.8.2.1",
  "title": "电机控制器故障诊断",
  "level": 4,
  "breadcrumbs": ["1 电气系统", "1.8 故障诊断", "1.8.2 故障代码"],
  "applicability_rule_ids": ["VAR-CN-DRY-TECHNICIAN"],
  "blocks": []
}
```

### 5.3 Block

首版保留现有封闭类型：`para`、`image`、`table`、`warning`、`steps`、`list`。每块增加 `block_id`、`applicability_rule_ids` 和 `source_refs`。

```json
{
  "block_id": "B-1.8.2.1-T01",
  "type": "table",
  "caption": "电机控制器故障代码",
  "header": ["代码", "故障名称", "触发条件", "故障等级", "解决措施"],
  "rows": [["8", "母线电流过流", "母线电流超过710A", "3", "联系厂家维修"]],
  "applicability_rule_ids": ["VAR-CN-DRY-TECHNICIAN"],
  "source_refs": [
    {
      "source_document_id": "SRC-B-20260824",
      "edition_id": "B-20260824",
      "section_id": "B-1.8.2.1",
      "block_id": "B-1.8.2.1-T01",
      "source_element_ids": [1945],
      "page": null,
      "bbox": null,
      "excerpt_hash": "sha256:..."
    }
  ]
}
```

表格网格、合并单元格展开和单元格图片来源必须在解析期确定。新块类型属于破坏性扩展，必须升级 schema 并同步所有终端；未知类型不能透传发布。

### 5.4 Asset

```json
{
  "asset_id": "ASSET-01...",
  "content_hash": "sha256:...",
  "media_type": "image/png",
  "path": "img/B_1_8_2_1_01.png",
  "bytes": 123456,
  "width": 800,
  "height": 600,
  "caption": "图1-1 电机控制器",
  "alt_text": null
}
```

## 6. FaultCode：确定性故障注册记录

### 6.1 数据格式

```json
{
  "schema_version": "1.0.0",
  "fault_id": "FC-01...",
  "logical_fault_id": "LF-01...",
  "edition_id": "B-20260824",
  "controller_id": "MOTOR_CONTROLLER",
  "code": "8",
  "name": "母线电流过流",
  "severity": {
    "level": "HIGH",
    "source_level": "3",
    "label": "联系厂家维修"
  },
  "trigger_text": "母线电流超过710A",
  "trigger_expression": null,
  "resolution": {
    "actions": [
      {
        "order": 1,
        "type": "CONTACT_SERVICE",
        "text": "联系厂家维修"
      }
    ]
  },
  "applicability_rule_ids": ["VAR-CN-DRY-TECHNICIAN"],
  "source_refs": [
    {
      "source_document_id": "SRC-B-20260824",
      "edition_id": "B-20260824",
      "section_id": "B-1.8.2.1",
      "block_id": "B-1.8.2.1-T01",
      "source_element_ids": [1945],
      "page": null,
      "bbox": null,
      "excerpt_hash": "sha256:..."
    }
  ],
  "review_status": "APPROVED",
  "review_flags": []
}
```

约束：

- 精确查询键为 `controller_id + code + 适用性 + Edition 解析结果`。
- `severity.level` 使用平台统一映射，`source_level` 保留原文值。
- `trigger_text` 是原文证据；只有经过审核的结构化条件才能写入 `trigger_expression`。
- 空解决措施、未知控制器、重复代码冲突和未知严重度必须阻断或进入审核，不能运行时猜测。
- 如果查询仍命中多条有效记录，返回 `AMBIGUOUS`，不得按相似度或最高等级自动选择。
- 症状、现象和检查分支应使用后续 DiagnosticRule，不塞进 `trigger_text` 进行模糊推理。

### 6.2 确定性故障响应

```json
{
  "status": "FOUND",
  "resolved_context": {
    "vehicle_profile_id": "SN-253913261",
    "edition_id": "B-20260824"
  },
  "answer": {
    "fault_id": "FC-01...",
    "controller_id": "MOTOR_CONTROLLER",
    "code": "8",
    "title": "母线电流过流",
    "severity": "HIGH",
    "actions": ["联系厂家维修"]
  },
  "source_refs": [
    {"edition_id": "B-20260824", "section_id": "B-1.8.2.1", "block_id": "B-1.8.2.1-T01"}
  ]
}
```

统一状态：

- `FOUND`：唯一且适用的记录。
- `NOT_FOUND`：在确定范围内不存在。
- `AMBIGUOUS`：存在多个候选，返回可供选择的控制器/版本，不自行选择。
- `NOT_APPLICABLE`：记录存在但不适用于当前车辆。
- `CONTENT_UNAVAILABLE`：内容未授权、已撤回或当前离线包不包含。
- `MISSING_CONTEXT`：缺少控制器、车辆配置等必要上下文。

## 7. MaintenanceRule：确定性保养规则

### 7.1 数据格式

```json
{
  "schema_version": "1.0.0",
  "rule_id": "MR-01...",
  "logical_rule_id": "LR-01...",
  "edition_id": "A-202608",
  "trigger": {
    "type": "INTERVAL",
    "terms": [
      {"metric": "ENGINE_HOURS", "every": 10, "unit": "HOUR"},
      {"metric": "CALENDAR_TIME", "every": 1, "unit": "DAY"}
    ],
    "relation": "EARLIEST"
  },
  "actions": [
    {
      "action_id": "MA-01...",
      "type": "CHECK",
      "item": "液压油油位",
      "instruction": "检查液压油油位，必要时补足。"
    }
  ],
  "includes_rule_ids": [],
  "applicability_rule_ids": ["VAR-CN-DRY-OPERATOR"],
  "source_refs": [
    {
      "source_document_id": "SRC-A-202608",
      "edition_id": "A-202608",
      "section_id": "A-3.3.2",
      "block_id": null,
      "source_element_ids": [807],
      "page": null,
      "bbox": null,
      "excerpt_hash": "sha256:..."
    }
  ],
  "review_status": "APPROVED",
  "review_flags": []
}
```

### 7.2 Trigger 类型

使用明确的分类型结构，不再使用自由 `dict`：

| `trigger.type` | 必要内容 | 示例 |
|---|---|---|
| `INTERVAL` | `terms[]`、`relation` | 每 10 小时或每天，先到为准 |
| `ONE_TIME` | `metric`、`at`、`unit`、`anchor` | 第一个 250 小时 |
| `CALENDAR` | 日期/周期间隔和锚点 | 每年 1 月或每 6 个月 |
| `CONDITION` | 已审核的表达式 ID 与版本 | 低温存放、SOC 条件 |
| `EVENT` | 受控事件类型 | 更换部件后、首次投入使用 |

`CONDITION` 的表达式使用独立、可测试的 AST 或规则引用，不把自然语言直接当可执行表达式。单位必须来自受控单位表；无法解析的周期、首保和累积关系进入审核，不猜测。

`includes_rule_ids` 表示累积包含的低周期规则，发布前检查目标存在和无循环。重复展示由规则引擎按 `action_id` 去重，不在文档解析时复制正文。

### 7.3 确定性保养响应

```json
{
  "status": "FOUND",
  "resolved_context": {
    "vehicle_profile_id": "SN-253913260",
    "edition_id": "A-202608",
    "engine_hours": 250,
    "as_of": "2026-11-07T10:00:00+08:00"
  },
  "due_rules": [
    {
      "rule_id": "MR-01...",
      "trigger_summary": "每10小时或每天，先到为准",
      "actions": ["检查液压油油位，必要时补足。"]
    }
  ],
  "source_refs": [
    {"edition_id": "A-202608", "section_id": "A-3.3.2", "block_id": null}
  ]
}
```

除故障响应的状态外，保养还支持 `NO_DUE_RULE`。缺少当前小时数、日期或配置时返回 `MISSING_CONTEXT`，不得用默认车辆数据补齐。

## 8. 搜索与 RAG 派生格式

### 8.1 SearchRecord

```json
{
  "record_id": "B-20260824:B-1.8.2.1:B-1.8.2.1-T01",
  "record_type": "TABLE",
  "manual_id": "XC975-EV-SERVICE",
  "edition_id": "B-20260824",
  "section_id": "B-1.8.2.1",
  "block_id": "B-1.8.2.1-T01",
  "title": "电机控制器故障诊断",
  "breadcrumbs_text": "1 电气系统 > 1.8 故障诊断 > 1.8.2 故障代码",
  "content_text": "代码 故障名称 触发条件 故障等级 解决措施 8 母线电流过流 ...",
  "exact_fields": {"controller_id": "MOTOR_CONTROLLER", "code": "8"},
  "applicability_rule_ids": ["VAR-CN-DRY-TECHNICIAN"],
  "permission_tags": ["TECHNICIAN"],
  "source_refs": []
}
```

### 8.2 RAGChunk

RAGChunk 至少携带 `manual_id`、`edition_id`、`section_id`、可选 `block_id`、面包屑、适用规则和权限标签。只能从已发布 Edition 派生，不允许直接编辑 RAG 文本以修正手册内容。

## 9. 标准阅读包与 OfflinePackage

### 9.1 标准阅读与交换产物

每个不可变 Edition 可导出一个 **EPUB 3.3 OCF + OPF** 阅读出版物。此时不使用自定义 JSON 冒充行业标准：

- `META-INF/container.xml` 指向 `package.opf`；
- OPF `metadata` 保存出版物标识、标题、语言和修改时间；
- OPF `manifest` 用 `id + href + media-type` 列出全部 publication resources；
- OPF `spine` 表达默认阅读顺序；
- EPUB Navigation Document 的 `toc nav` 表达完整章节目录。

EPUB 不提供本项目的故障精确查询、保养规则求值或 QML Block 语义，也没有 OPF 标准逐文件 SHA-256 字段。准确格式和官方规范链接见 `docs/project/manual-industry-package-standards.md`。

### 9.2 自定义车机数据包清单

以下 JSON 仅是本项目的应用数据包契约，不称作 EPUB/OPF、DITA map、S1000D DDN 或 TUF 标准格式：

```json
{
  "schema_version": "1.0.0",
  "package_id": "XC975-EV-CN-DRY-20260824",
  "package_kind": "FULL",
  "edition_ids": ["A-202608", "B-20260824"],
  "applicability_rule_ids": ["VAR-CN-DRY-OPERATOR", "VAR-CN-DRY-TECHNICIAN"],
  "minimum_reader_version": "1.0.0",
  "supersedes_package_id": null,
  "files": [
    {"path": "content/tree_A.json", "bytes": 123456, "sha256": "..."},
    {"path": "domain/fault_codes.json", "bytes": 23456, "sha256": "..."},
    {"path": "domain/maintenance_rules.json", "bytes": 34567, "sha256": "..."},
    {"path": "search/search_index.db", "bytes": 456789, "sha256": "..."}
  ],
  "signature": {"key_id": "release-key-1", "algorithm": "...", "value": "..."}
}
```

车机包内还必须包含适用规则、资源清单、交叉引用和版本信息。SHA-256 只证明字节完整性，发布者身份由签名证明。激活前校验签名、schema、最低阅读器版本、未知 Block、孤儿资源和失效引用。

安全分发时可将 EPUB、QML 数据包、故障和保养产物作为 TUF targets，以标准 `length` 和 `hashes` 保护下载字节；TUF 不负责手册目录、规则求值或应用激活。

## 10. 全局不变量

1. 每个已发布记录都能追溯到明确原件、Edition 和源元素。
2. 所有 ID 在各自作用域唯一；跨版本关联使用逻辑 ID 或 Anchor。
3. 目录、搜索、RAG、故障、保养和包签发使用同一适用性与权限语义。
4. 无匹配、歧义和上下文不足是明确结果，不进入生成式补全。
5. 已发布内容不可原地修改；搜索索引和终端包可以删除重建，但权威内容不能因此被改写。
6. 同一故障键的多个有效记录必须在审核时解决；运行时不做隐式折叠。
7. 保养周期单位、首保锚点、累积关系和条件表达式必须可执行且经过审核。
8. 新字段只做向后兼容的可选新增；改类型、删字段或新增未知 Block 需要主版本升级。
9. 车机包不包含可执行脚本或未审核内容；内容更新不能绕过 App 审核。

## 11. 现有字段迁移

| 当前字段 | 目标字段 |
|---|---|
| `章节号` | `display_number`，仅用于展示 |
| `标题` | `title` |
| `层级` | `level` |
| `parent` | `parent_id` |
| `面包屑` | `breadcrumbs` 数组，派生展示文本 |
| `src` | `source_refs[].source_element_ids` |
| `适用变体` 自由字符串 | `applicability_rule_ids` + 受控 VariantProfile |
| 故障 `code_id` 中的标题/章节 | 稳定 `fault_id` + `logical_fault_id`；原值仅用于迁移核对 |
| `触发` 自由字典 | 分类型 `trigger` |
| 保养 `内容` | `actions[].instruction` |
| 保养 `累积` | `includes_rule_ids` |
| `审核标记` | `review_status` + `review_flags` + 内部 AuditEvent |
| 当前 manifest 的文档/版本字符串 | `edition_ids`、结构化适用规则和不可变包 ID |

迁移必须提供双向核对报告：记录数、来源完整率、丢失字段、重复键、未知单位和未解析触发器。旧格式只作为迁移输入，不与新格式长期并行发布。

## 12. 推荐落地顺序

1. 评审本规格和 `CONTEXT.md` 术语，确认 ID、Edition、适用性和审核语义。
2. 用 JSON Schema/Pydantic 实现公共结构、Section/Block、FaultCode 和 MaintenanceRule。
3. 编写现有 A/B/C 数据迁移器和双向核对报告，不改变既有解析器行为。
4. 先实现故障精确查询与保养周期求值，验证所有非 `FOUND` 状态。
5. 再由同一 Edition 派生手册树、搜索记录、RAGChunk 和离线包。
6. 完成车机离线阅读和规则引擎后，再考虑 DiagnosticRule 和 DITA 创作适配。

## 13. 需要业务确认的点

- 各控制器代码的受控 ID 和跨手册同码归一规则。
- 原文故障等级到平台严重度的唯一映射。
- 保养小时、日历、里程、首保和事件的优先级及“先到为准”语义。
- 哪些条件规则允许自动执行，哪些只能展示原文。
- 安全相关故障和保养内容的审核级别。
- 历史版、撤回版在离线设备上的可见与停用策略。

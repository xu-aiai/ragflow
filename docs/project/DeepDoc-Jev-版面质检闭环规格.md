# DeepDoc + Jev 版面质检闭环规格

## 1. Objective

在现有工作台中增加“解析 → 质检 → 修复 → 复检”闭环。DeepDoc、PaddleOCR-VL 等解析器负责生成版面元素，Jev 负责封闭判断，程序负责确定性校验和动作路由，人工负责修改、合并及低置信度裁决。

目标不是让模型直接生成修正文本，而是让每个元素最终处于以下一种状态：

- `完整`：模型与规则均未发现阻断问题，或人工已确认。
- `待人工修正`：内容缺失、错识别或源图本身无法可靠自动恢复。
- `待换解析器`：当前解析结果不完整，备选解析器可能更好。
- `待合并`：当前元素与上一元素、下一元素或两者共同构成完整语义。
- `待人工判断`：模型置信度不足、判断冲突或模型不可用。

### 假设

1. 首版使用内网自部署的 `autotrust/JEV-27B-VL`，通过 `/v1/decide` 调用，不使用 TypeSafe 云端。
2. 首版落在 `pipeline/` 工作台，复用现有 DeepDoc、PaddleOCR-VL、原文对照和人工修正能力，不直接改写 RAGFlow 主切片流程。
3. Jev 只提供判断和概率，不自动修改原文，不直接生成修正内容。
4. 原始解析结果不可变；人工修正、解析器重试和合并均形成可追溯的新版本。
5. 未配置模型或模型调用失败时，人工修正流程仍可独立使用。
6. 多模态请求并发不得超过 8；全文质检按页落盘，支持断点续跑。

## 2. 质检数据流

```text
原始 PDF/图片
   ↓
DeepDoc / PaddleOCR-VL 原始解析结果（不可变）
   ↓
确定性规则预检
   ↓
Jev：内容完整性 + 语义边界 + 修复路径
   ↓
程序按置信度和约束路由
   ├─ 完整
   ├─ 人工修正 ───────┐
   ├─ 换解析器重解析 ─┤
   ├─ 合并相邻元素 ───┤→ 自动复检 → 完整或继续待处理
   └─ 人工判断 ───────┘
```

### 每个元素的输入

- 当前元素的类型、正文或表格 HTML、页码和坐标。
- 当前元素在原页中的裁剪图；判断缺字、缺行、截断时必需。
- 上一、当前、下一元素的文本和类型，用于语义边界判断。
- 确定性预检结果，例如空内容、无效区域、HTML 结构错误、表格行列异常、疑似乱码。
- 当前解析器、解析尝试编号和历史判断。

页面原文及解析文本只作为待判断数据，不作为操作指令。

### Jev 判断原语

每个元素一次请求并行询问三个问题：

| 问题 | 类型 | 选项 |
|---|---|---|
| `content_integrity` | Choice | `complete` / `recognition_error` / `missing_content` / `unreadable_source` / `uncertain` |
| `semantic_boundary` | Choice | `self_contained` / `needs_previous` / `needs_next` / `needs_both` / `uncertain` |
| `repair_path` | Choice | `not_needed` / `alternate_parser` / `manual_edit` / `human_review` |

不让 Jev 计算表格行列数、坐标重叠率或字符数；这些由代码完成后放入状态。程序根据三个判断、各项概率和置信度决定最终动作，避免模型同时给出互相矛盾的“问题”和“动作”。

### 置信度与动作约束

- 高置信度结果只自动给出动作建议；首版由用户点击后执行修复。
- 低置信度、选项概率接近或判断互相冲突时进入 `待人工判断`。
- 同一元素最多进行两轮备选解析；仍不完整则转人工，禁止无限重试。
- 模型不可用、超时或返回非法数据时保留原结果并标记 `待人工判断`。
- 首版自动合并仅建议相邻文本类元素；表格、图片与文本的跨类型合并必须人工执行。
- 人工可将任何状态确认为 `完整`，确认记录进入历史。

## 3. 元素身份、版本与合并

解析器块 ID 只在单次解析尝试内使用，不能作为永久身份。每个待审元素使用独立的 `review_id`，换解析器后仍沿用同一个 `review_id`。

```json
{
  "review_id": "p14_007",
  "页": 14,
  "来源区域": [14.28, 59.87, 71.39, 16.87],
  "当前尝试": {
    "解析器": "ragflow",
    "块ID": "314",
    "版本": 2,
    "内容哈希": "..."
  },
  "状态": "待人工修正",
  "判断": {},
  "历史": []
}
```

- 备选解析结果通过页码、区域重叠和元素类型映射回原 `review_id`，不能假设不同解析器生成相同块 ID。
- 人工修正创建新版本并自动复检，原始 `page_N.json` 不改写。
- 换解析器创建新尝试并自动复检，保留旧尝试供对照和回退。
- 合并生成一个新版本，记录全部来源 `review_id`、原始块 ID、阅读顺序和合并区域；被合并元素标记为已并入，不物理删除历史。
- 合并后复检新元素及其前后相邻元素，因为合并可能改变相邻语义边界。

建议持久化到 `runs/<run_id>/review/`，现有 `parse/` 继续保存原始解析与人工内容修正。

## 4. Tech Stack

- Python 3.10+、Flask、现有 `pipeline/xc975_pipeline/`。
- 原生 JavaScript、现有 `pipeline/web/`。
- Jev HTTP 接口 `POST ${JEV_URL}/v1/decide`，图文请求使用 `decide_mm` 的图文混排格式。
- 复用 `JEV-27B-DEMO/common/jev_client.py`，通过 `JEV_REPO` 定位，首版不新增 SDK 依赖。
- `JEV_URL`、`JEV_BACKEND=decide` 和可选 `JEV_API_KEY` 只从环境变量读取，不写入运行快照。

## 5. Commands

```bash
cd pipeline
python -m pytest tests/test_quality.py -q
python -m pytest tests -q
node --check web/app.js
JEV_URL=http://10.90.15.23:8004 JEV_BACKEND=decide python jev_full_quality.py --workers 8
python workbench.py --port 8765
```

真实 Jev 联调使用内网服务；单元测试默认使用本地假响应，不访问模型。

## 6. Project Structure

- `pipeline/xc975_pipeline/quality.py`：预检、Jev 请求、响应校验、动作路由和复检编排。
- `pipeline/xc975_pipeline/webapp.py`：质检、修复、换解析器、合并和复检接口。
- `pipeline/web/app.js`：元素质量状态、建议动作、版本对照和人工确认。
- `pipeline/web/style.css`：沿用现有状态色与按钮样式。
- `pipeline/tests/test_quality.py`：规则、路由、版本、合并和复检测试。
- `pipeline/tests/test_ocr.py`：现有解析及人工修正回归测试。
- `pipeline/runs/<run_id>/review/`：运行期质检和版本记录，不进入版本库。

`quality.py` 对调用方只暴露页级质检与单元素复检入口；Jev 请求格式、阈值和重试细节不扩散到 Web 层。

## 7. Code Style

```python
@dataclass(frozen=True)
class QualityVerdict:
    content: str
    boundary: str
    repair: str
    confidence: float


def route_action(verdict: QualityVerdict) -> str:
    if verdict.confidence < MIN_CONFIDENCE:
        return "human_review"
    if verdict.boundary != "self_contained":
        return "merge"
    return verdict.repair
```

- 解析器适配与质量判断分离，模型响应先校验再进入状态机。
- 文件读写沿用 `ensure_ascii=False` 和现有运行目录结构。
- 前端通过 DOM API 构造界面，不拼接未转义的解析内容。

## 8. Testing Strategy

- 单元测试：预检、置信度路由、非法模型响应、最大重试次数。
- 接口测试：质检落盘、人工修正后复检、换解析器后保持 `review_id`、合并及来源追踪。
- 浏览器测试：不完整表格 → 选择换解析器 → 新版本复检；断句 → 合并下一元素 → 复检。
- 故障测试：无 API Key、超时、非法响应时，原解析和人工修正仍可用。
- 回归命令：完整运行 `python -m pytest tests -q` 和 `node --check web/app.js`。
- 模型评测：建立人工标注元素集，分别报告内容错误召回率、误判完整率、动作建议准确率和合并准确率；阈值依据评测结果确定，不以单次示例调参。

## 9. Boundaries

- Always：原始结果不可变；所有修复可追溯；低置信度人工兜底；模型失败后人工流程可用；运行完整测试。
- Ask first：向外部模型发送真实手册；新增依赖；自动执行合并或自动无限重试；将质检结果接入正式知识库切片。
- Never：提交 API Key；让 Jev 直接生成修正文本；用解析器块 ID 充当跨版本身份；绕过复检直接标记完整。

## 10. Success Criteria

1. 每个解析元素都有内容完整性、语义边界、置信度和处理状态。
2. 缺行表格能被标记为待处理，并通过人工修正或备选解析产生新版本。
3. 每次人工修正、换解析器和合并后都会自动复检，不能只修改状态而不重新判断。
4. 换解析器后仍能找到同一 `review_id` 的历史和来源区域。
5. 断句可与上一或下一元素合并，合并后来源可追溯且新元素被复检。
6. 低置信度或模型故障不会触发自动修改，也不会阻断人工处理。
7. 原始解析结果始终保留，可对照、回退和审计。
8. 完整测试与真实浏览器闭环验证通过。

## 11. Open Questions

1. 全文质检完成后，首批人工标注集规模及可接受的“误判完整率”、合并准确率目标。
2. 低置信度标签的概率和首选差值阈值是否需要按手册类型分别校准。
3. 首版备选解析器是否只包含 DeepDoc 与 PaddleOCR-VL，其他解析器后续按同一映射机制加入。
4. 模型建议由用户点击执行是否满足预期，还是需要在评测达标后开放高置信度自动重解析。

## 12. 非首版范围

- 不让生成式模型自动补写缺失文字。
- 不直接修改原始 Word/PDF。
- 不做无限“换解析器—复检”循环。
- 不在未验证合并准确率前自动合并所有相邻元素。
- 不直接替换 RAGFlow 正式切片链路。

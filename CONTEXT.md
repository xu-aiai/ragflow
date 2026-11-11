# Technical Manual Platform

技术手册平台的统一领域语言，用于手册内容、确定性故障与保养服务，以及多终端发布。

## Language

**Manual**:
同一主题手册的逻辑系列，与具体改版无关。
_Avoid_: 文件、文档包

**Edition**:
某份 Manual 的一个不可变内容版本；已发布 Edition 的纠错或改版产生新 Edition。
_Avoid_: 文件版本、页面修订

**Section**:
Edition 内具有稳定标识和层级关系的逻辑内容单元。
_Avoid_: 页面、Chunk

**Block**:
Section 内具有明确类型的最小展示与引用单元。
_Avoid_: 任意 HTML、通用文本块

**Anchor**:
用于跨 Edition 定位同一逻辑内容的稳定锚点，不使用可能变化的章节号代替。
_Avoid_: 章节号主键、标题主键

**Applicability**:
内容适用于特定车辆、配置、市场、语言或受众的明确规则。
_Avoid_: 变体字符串、搜索偏好

**Source Reference**:
内容到原件 Edition、Section、Block 或源元素的证据关联。
_Avoid_: 无版本的文件路径引用

**Fault Code**:
由控制器标识和故障代码精确定位的一条故障注册记录。
_Avoid_: 症状诊断、语义答案

**Diagnostic Rule**:
依据症状、观测和检查步骤推进诊断的独立规则；不属于 Fault Code 查询。
_Avoid_: 故障码表、生成式诊断答案

**Maintenance Rule**:
把明确触发条件映射为一组保养操作的确定性规则。
_Avoid_: 自由文本提醒、无类型触发字典

**Deterministic Answer**:
由精确匹配或已审核规则直接产生并附来源的结果；上下文不足或结果歧义时明确拒绝推断。
_Avoid_: 最高相似度猜测、生成式答案

**Offline Package**:
针对明确 Edition、适用范围和授权签发的自包含只读内容产物。
_Avoid_: PDF 下载、临时缓存

**RAG Chunk**:
从已审核内容派生的语义检索输入，不是权威内容或规则来源。
_Avoid_: 权威 Section、规则记录

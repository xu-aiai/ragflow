# 技术手册平台开源组件选型调研

| | |
|---|---|
| 调研日期 | 2026-11-07 |
| 目标场景 | 几千到上万份 Word/PDF 技术手册：统一结构化、完整目录、全文检索、版本/变体/权限、Web 手册库、QML 车机离线包和更新 |
| 证据范围 | 项目官网、官方文档、官方源码仓库与标准规范；同时只读核对当前仓库已有实现与规划 |
| 结论性质 | 架构选型建议，不是对候选产品的性能实测；许可证信息用于风险提示，正式采用前仍应由法务按锁定版本复核 |

## 0. 核心结论

**没有发现一个单一、成熟的开源项目能够覆盖本场景的完整流程。** 候选项目分别解决文档解析、RAG、结构化发布、文档门户、内容管理、搜索、对象存储、身份认证或更新安全中的某一层；它们都不天然拥有本项目的 `Manual → Edition → Section/Block`、车型/SN 变体、内容授权、审核发布、车机离线包和设备激活状态等业务模型。

推荐采用**轻量组合**：

- 保留当前 `DocumentModel → Section/Block → 数据包 + manifest` 主链，以 MySQL 中的规范内容库作为权威来源。
- 保留现有 MinIO/S3 对象存储和 Elasticsearch；RAGFlow 只承担在线检索问答及引用，不作为技术手册内容治理底座。
- 现有 DOCX 确定性抽取继续优先；Docling、MinerU、PaddleOCR 只作为经过真实样本对比后选择的 PDF/OCR 适配器，不替换整个管线。
- Web 手册库、版本/变体/权限、审核发布、离线包构建、更新服务和 QML 阅读器属于必须自建或深度定制的业务层。
- 初期使用**全量、自包含、签名的数据包 + 暂存校验 + 原子激活 + 上一可用包回退**。TUF 是后续增强更新元数据安全的可选框架；Uptane 是更完整的汽车软件更新标准，不是可直接安装到 QML 的离线手册产品。

“文档门户简化路线”适合尽快上线公开或弱权限资料，但不能被误认为目标平台；“商业 CCMS/IETM”适合结构化创作、内容复用、翻译和合规治理已经成为主要成本的组织，即使采购商业产品，车辆配置、授权和 QML 交付仍需集成建设。

## 1. 判断口径与需求分层

### 1.1 不是“能打开 PDF”就等于覆盖手册平台

本报告将目标拆成五层：

1. **接入与理解**：DOC/DOCX/PDF 接入、版面/OCR、表格图片、阅读顺序、来源定位、质量诊断。
2. **规范内容与治理**：统一章节树和 Block、手册族、不可变版本、变体适用性、内容许可、审核、发布、撤回和审计。
3. **发现与交付**：目录、全文/精确检索、权限过滤、Web 阅读、深链、在线问答。
4. **离线分发**：自包含包、本地搜索、签名、更新发现、暂存、校验、激活、回滚和设备状态。
5. **基础设施**：数据库、对象存储、搜索引擎、身份认证、密钥和运维。

因此：

- **DITA Open Toolkit（DITA-OT）是发布工具，不是 CCMS。** 它不会自动提供创作库、评审流程、权限、版本基线或手册门户。
- **Sphinx/Read the Docs、BookStack 等文档门户不是完整技术手册平台。** 页面版本、文档站版本或页面修订记录，不等于不可变 Edition、车型/SN 适用性和离线权利。
- **搜索引擎和身份/权限组件不提供业务模型。** OpenSearch 能执行过滤，Keycloak 能认证和执行通用授权策略，但“哪个 Edition 适用于哪台车、谁有离线权、撤回后如何处理已安装包”必须由本项目定义。
- **TUF/Uptane 不是完整更新业务系统。** 安全元数据验证之外，仍需包构建、适用性、授权、活动、下载、安装、回滚和设备运营。

### 1.2 证据边界

- 下文“能覆盖”只表示官方资料明确支持相应基础能力，不表示开箱即满足全部业务验收。
- 未进行相同语料上的解析质量、搜索相关性或容量 benchmark，不用官网宣传数字代替本项目实测。
- 许可证以本次核实的当前官方资料为准；部署时必须锁定版本并保存相应许可证、NOTICE 和模型/插件许可证。

## 2. 总体对比：没有单一项目端到端覆盖

“部分”表示可以复用为该层组件，不表示直接满足业务语义。

| 项目 | 官方定位 | 主要覆盖层 | 本场景中明确不能替代的部分 | 许可证与部署要点 |
|---|---|---|---|---|
| **RAGFlow** | 带 Agent 能力的开源 RAG 引擎/上下文基础设施，含深度文档理解、分块、引用与 API | 文档接入、在线检索问答、引用；现有基础设施复用 | 规范章节树唯一权威、不可变 Edition、SN/配置规则、内容权利、QML 包和设备更新 | Apache-2.0；Docker/源码部署，依赖文档引擎、数据库、对象存储和模型服务。[官方仓库与部署](https://github.com/infiniflow/ragflow)、[许可证](https://raw.githubusercontent.com/infiniflow/ragflow/main/LICENSE) |
| **Docling** | 多格式文档解析与统一 `DoclingDocument`，强调 PDF 版面、阅读顺序、表格和 OCR | 解析适配器、中间表示、可本地/隔离运行 | 手册版本/变体/权限、审核、搜索业务、Web 库、离线和更新 | 代码 MIT，单个模型按其原包许可证；Python 库/CLI，另有 `docling-serve`。[官方文档](https://docling-project.github.io/docling/)、[官方仓库及许可证说明](https://github.com/docling-project/docling) |
| **MinerU** | 当前版本将文档解析、本地文档库、搜索和服务工具组合为文档转换/Agent 阅读工作流 | PDF/Office 解析、OCR、结构化结果、局部读取与引用定位 | 官方明确其不是 RAG 框架/向量库/聊天应用；本地库也不等于多用户手册治理、变体授权、Web/QML 发布和 OTA | **当前为 Apache-2.0 加附加条款**，并非纯粹 Apache-2.0；含商业门槛和在线服务标识义务。模型与运行资源需单独核查。[官方仓库](https://github.com/opendatalab/MinerU)、[当前许可证](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md) |
| **PaddleOCR** | OCR 与文档解析工具族，PP-StructureV3/PaddleOCR-VL 可把 PDF/图片转为 JSON/Markdown | 扫描件 OCR、版面、表格和复杂页面的可选解析后端 | DOCX 权威结构、Edition/变体/权限、审核发布、门户、包和更新 | 代码 Apache-2.0；按 CPU/GPU 与推理后端部署，锁定具体模型及其许可证。[官方仓库](https://github.com/PaddlePaddle/PaddleOCR) |
| **DITA Open Toolkit** | 将 DITA 内容处理并转换为 HTML、PDF、Markdown、规范化 DITA 等格式的发布工具 | 新创作内容的 topic/map 条件发布、多格式构建、规范化后适配 | **不是 CCMS**；不提供内容库、创作协作、审核治理、在线授权、搜索平台或车机更新 | Apache-2.0；作为构建工作器/CI 工具运行，PDF 还涉及 FO formatter。[官方首页](https://www.dita-ot.org/) |
| **Sphinx + Read the Docs** | Sphinx 从 reStructuredText/MyST 等生成 HTML/PDF/EPUB；Read the Docs 构建和托管多版本文档站 | 静态技术文档发布、目录/交叉引用、站级版本和翻译、托管与搜索 | Word/PDF 批量治理、运行时 SN/配置判定、细粒度内容授权、统一 Block API、受控 QML 包 | Sphinx BSD-2-Clause；Read the Docs 代码 MIT。Git/构建流水线导向；私有文档托管能力与所用服务套餐有关。[Sphinx](https://www.sphinx-doc.org/en/master/)、[RTD 功能](https://docs.readthedocs.com/platform/stable/features.html)、[Sphinx 许可证](https://github.com/sphinx-doc/sphinx/blob/master/LICENSE.rst)、[RTD 许可证](https://raw.githubusercontent.com/readthedocs/readthedocs.org/main/LICENSE) |
| **BookStack** | 以 Books/Chapters/Pages 组织的自托管文档/Wiki 应用 | 简化门户、编辑、全文搜索、页面修订、角色权限、OIDC/SAML/LDAP | 封闭 Block 协议、不可变手册 Edition、块级变体、内容许可、复杂检索治理、QML 离线更新 | MIT；PHP/Laravel + MySQL/MariaDB，自托管。[官方功能](https://www.bookstackapp.com/)、[安装要求](https://www.bookstackapp.com/docs/admin/installation/) |
| **Payload** | Next.js 原生的代码优先全栈/headless CMS，生成管理 UI、API、认证、访问控制和版本 | 可选内容中心/审核后台框架，可定制手册与发布实体 | 通用 versions/drafts 不等于不可变 Edition；没有车辆主数据、适用性、包构建、车机更新和领域搜索语义 | MIT；新增 Node.js/Next.js 服务。官方数据库适配器为 MongoDB、Postgres、SQLite，**不直接复用现有 MySQL**。[官方定位](https://payloadcms.com/docs/getting-started/what-is-payload)、[数据库](https://payloadcms.com/docs/database/overview)、[许可证](https://raw.githubusercontent.com/payloadcms/payload/main/LICENSE.md) |
| **OpenSearch** | Apache-2.0 搜索与分析引擎 | 全文、精确字段、聚合/facet、向量及索引集群；可选文档级安全 | 不定义手册/版本/变体/权利，不自动生成正确索引，不保证 facet/建议/下载的业务授权 | Apache-2.0；独立集群与资源/安全运维。当前已有 ES 时不应仅为选型整齐再引入。[官网](https://opensearch.org/)、[DLS](https://docs.opensearch.org/latest/security/access-control/document-level-security/)、[部署](https://docs.opensearch.org/latest/install-and-configure/install-opensearch/docker/) |
| **Readium** | EPUB/数字出版阅读技术；Swift/Kotlin/TypeScript 等工具包 | 可选 EPUB 导出后的移动端阅读、搜索、导航；部分工具包支持 PDF/LCP | 不是 Qt/QML 手册运行时，不提供规范内容库、车型变体、云端授权和更新业务 | 以 Swift Toolkit 为例为 BSD-3-Clause；iOS/Android 等按平台集成，LCP 还涉及 EDRLab 的额外组件。[官网](https://readium.org/)、[Swift Toolkit](https://github.com/readium/swift-toolkit)、[BSD-3-Clause](https://raw.githubusercontent.com/readium/swift-toolkit/main/LICENSE) |
| **MinIO** | S3 兼容对象存储 | 原件、图片、结构化产物、离线包的对象存储与分发 | 手册元数据、授权决策、版本状态、签名和更新状态机 | 当前社区源码 AGPLv3；官方仓库标记不再维护，社区版转为 source-only，历史二进制不再更新。现有部署需要单独制定升级/支持策略。[官方仓库](https://github.com/minio/minio) |
| **Keycloak** | 开源身份和访问管理，支持 OIDC/OAuth 2.0/SAML、SSO、用户联邦与授权服务 | 登录、SSO、组织/角色/客户端身份、令牌和通用策略 | 车辆/SN 权威数据、Edition 适用性、第三方离线许可、包签发和设备状态 | Apache-2.0；需独立高可用、数据库、密钥和升级运维。[官网](https://www.keycloak.org/)、[许可证](https://raw.githubusercontent.com/keycloak/keycloak/main/LICENSE.txt) |
| **TUF / python-tuf** | 安全更新框架、规范及 Python 参考实现 | 带角色/门限密钥、过期和版本检查的签名更新元数据，防回滚/冻结等供应链攻击 | 规范明确不定义通用更新系统、包格式或实际安装；不提供适用性、授权、活动、设备运营和 QML 安装器 | 规范可自由实现；python-tuf 双重 MIT/Apache-2.0。需要可信 root 引导、密钥/元数据仓库和客户端集成。[TUF 官网](https://theupdateframework.io/)、[规范及非目标](https://theupdateframework.github.io/specification/latest/)、[python-tuf](https://github.com/theupdateframework/python-tuf) |
| **Uptane** | 面向地面车辆软件更新安全的标准，基于并扩展 TUF 思路 | 汽车更新的 Image/Director 仓库、车辆/ECU 版本报告和安全设计参考 | **官方明确没有统一官方发行版或实现**；不是离线手册 CMS/阅读器/现成 OTA 服务 | 采用标准时仍须选择具体实现并分别核许可证；部署还涉及 ECU 密钥、可靠时间、车辆清单与运营流程。[标准](https://uptane.org/docs/latest/standard/uptane-standard)、[部署说明](https://uptane.org/docs/2.1.0/deployment/best-practices) |

## 3. 各层值得复用什么，边界在哪里

### 3.1 RAGFlow：保留在线问答，不扩大为内容治理平台

**官方定位与可复用能力。** RAGFlow 官方将其描述为融合 RAG 与 Agent 能力的开源引擎，支持 Word、PDF、扫描件等异构数据、深度文档理解、模板化分块、可追溯引用和集成 API；本地部署可使用 Elasticsearch 等文档引擎，并依赖 MySQL、MinIO 等基础设施。[RAGFlow 官方仓库](https://github.com/infiniflow/ragflow)

本项目可直接复用的是：

- 已审核 Edition 派生语料的在线语义检索、问答和引用展示。
- 现有 DeepDOC 文档理解、模型接入、检索编排和 RAG 运维经验。
- 将问答引用映射回 `manual_id + edition_id + section_id`，而不是另建不可追溯的答案库。

**不能覆盖或不应委托的职责。** RAGFlow 的知识库、文档和 chunk 不是本项目的 `Manual/Edition/Section/Block` 权威模型；不能依赖它表达车辆 SN/硬件配置、内容离线权、发布撤回、包签名和设备激活。RAG 检索结果也不能替代完整目录和确定性全文/故障码查询。

**建议。** 保持“规范内容库 → 搜索索引/RAG 派生”的单向关系。RAGFlow 不可用或 LLM 不可用时，目录、阅读、确定性搜索和车机离线功能仍须完整工作。

### 3.2 Docling、MinerU、PaddleOCR：只作为可替换解析适配器

#### Docling

Docling 官方支持 PDF、DOCX 等多格式输入，提供 PDF 版面、阅读顺序、表格结构、OCR 和统一 `DoclingDocument`，可导出无损 JSON、Markdown、HTML 等；支持本地和隔离环境，另有 API server。[Docling 官方功能](https://docling-project.github.io/docling/)

- **值得复用**：复杂 PDF 的结构化提取、统一中间表示和来源页/元素映射潜力。
- **必须自建**：`DoclingDocument → 当前 DocumentModel/Section/Block` 映射、标题树校验、六种封闭 Block、故障码/保养规则、质量门和人工审核。
- **注意**：官方多格式清单中的 Word 是 DOCX，不能据此假定旧二进制 DOC 无需转换；当前 LibreOffice/受控转换路线仍有价值。代码为 MIT，但所用模型许可证需逐项检查。[官方许可证说明](https://github.com/docling-project/docling)

#### MinerU

当前 MinerU 官方资料已包含本地文档库、搜索和文档/页/块定位，不应再简单描述成“只有 PDF 转 Markdown”；但其官方同时明确它不是 RAG 框架、向量数据库或聊天应用。[MinerU 官方仓库](https://github.com/opendatalab/MinerU)

- **值得复用**：复杂 PDF、扫描件、表格、公式、图片的解析对比样本，以及块级定位作为溯源参考。
- **不能覆盖**：本地文档库不是多租户、带审核发布和车辆变体的生产内容中心；没有 QML 包、离线权利和更新业务。
- **许可证是实际选型门槛**：当前许可证以 Apache-2.0 为基础并附加条件。合并口径 MAU 超过 1 亿或月总收入超过 2000 万美元需另获商业许可；基于 MinerU 向第三方提供在线服务还负有显著标识义务。不能只按历史印象写成“Apache-2.0 无附加限制”。[MinerU 当前许可证](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md)
- **建议**：只有在同一批真实手册上显著优于现有链路且收益覆盖资源、集成和许可成本时引入，不作为默认必装组件。

#### PaddleOCR

PaddleOCR 官方提供通用 OCR、PP-StructureV3 和 PaddleOCR-VL，可将复杂 PDF/图片转为 JSON/Markdown，支持多种硬件和服务化部署，代码采用 Apache-2.0。[PaddleOCR 官方仓库](https://github.com/PaddlePaddle/PaddleOCR)

- **值得复用**：扫描 PDF、图片文字、版面/表格识别以及现有规划中的 OCR/VLM 兜底。
- **边界**：OCR/VLM 输出不是已审核技术事实；不能直接绕过结构归一化和人工质量门。DOCX 有可靠结构时不应先渲染成图片再 OCR。
- **建议**：优先沿用 RAGFlow/DeepDOC 已有集成经验，以真实中文技术手册的表格、标题、图号和阅读顺序为验收依据，而非采用通用 benchmark 分数做决策。

**解析层共同原则：** 适配器输出只能是候选结构，权威产物始终是本项目规范模型。解析任务需记录源哈希、解析器/模型/配置版本和诊断，失败文档隔离，任何解析器都不负责版本发布与权限。

### 3.3 DITA Open Toolkit：可选的新内容生产与发布适配器

DITA-OT 官方定义就是“处理 DITA 内容并转换为其他格式的发布工具”，支持 HTML、PDF、Markdown 和规范化 DITA，采用 Apache-2.0。[DITA-OT 官方首页](https://www.dita-ot.org/) 规范化 DITA 会解析 map、key、content reference 等，可作为下游系统后处理的输入。[规范化 DITA 官方说明](https://www.dita-ot.org/dev/topics/dita2dita.html)

DITA 标准本身的 `@audience`、`@platform`、`@props` 等属性与 DITAVAL 可在发布处理时包含、排除或标记内容，适合按车型/市场/受众生成交付物。[OASIS 条件处理规范](https://docs.oasis-open.org/dita/dita/v1.3/os/part1-base/archSpec/base/condproc.html)

但以下等式都不成立：

- DITA-OT ≠ CCMS：没有现成组件内容库、协作创作、版本基线、审核流程和权限运营。
- DITAVAL ≠ 运行时授权：构建时过滤出一个包，不等于在线用户权限、内容许可或设备授权。
- DITA 发布输出 ≠ 当前车机协议：仍需映射到 Section/Block、资源清单、稳定深链和 manifest。

**建议：** 只在后续一个新手册系列试点 DITA topic/map/条件复用。存量 Word/PDF 先走现有迁移管线，不为使用 DITA-OT 而重写全部内容。若未来需要真正的 CCMS，应单独评估商业或专用 CCMS，而不是把 DITA-OT 扩展成伪 CCMS。

### 3.4 Sphinx / Read the Docs：适合静态文档站，不是受控手册业务库

Sphinx 官方支持 reStructuredText、MyST Markdown、交叉引用、国际化以及 HTML、LaTeX/PDF、EPUB 等构建。[Sphinx 官方文档](https://www.sphinx-doc.org/en/master/) Read the Docs 官方提供 Git 集成、多版本/翻译 URL、PR 预览、重定向、搜索分析和静态内容 CDN；私有/密码文档托管则明确列在 Read the Docs Business 能力中。[Read the Docs 功能](https://docs.readthedocs.com/platform/stable/features.html)

可复用的是文档构建、静态站托管、版本入口和公开知识库体验；不能直接复用的是：

- 几千份异构 Word/PDF 的自动质量治理；
- 同一内容按用户、车辆 SN、配置和离线权动态求值；
- `Section/Block` 级统一 API、故障码精确检索和 QML 包更新；
- 不可变 Edition、撤回和设备回滚业务。

Sphinx 代码为 BSD-2-Clause，Read the Docs 代码为 MIT；这不代表托管服务的所有商业功能都可免费获得。它们适合“文档门户简化路线”，不应成为目标平台的权威内容数据库。

### 3.5 BookStack：最相关的现成 Wiki/手册门户，但只覆盖简化场景

在 BookStack/Outline/Wiki.js 中，本报告只详评与“书—章—页”最贴近的 BookStack。官方明确提供 Books/Chapters/Pages、全库或书内搜索、页面修订、图片管理、角色权限以及 OIDC/SAML2/LDAP；采用 MIT，自托管依赖 PHP/Laravel 和 MySQL/MariaDB。[BookStack 官方功能](https://www.bookstackapp.com/)、[官方安装要求](https://www.bookstackapp.com/docs/admin/installation/)

它可快速提供内部手册门户、基础编辑、目录、搜索和访问控制，尤其适合权限较粗、以在线阅读为主的简化路线。但：

- 页面修订历史不是不可变、可替代的 `Edition` 发布模型；
- Books/Chapters/Pages 不是当前六种 Block 与故障/保养类型化数据协议；
- 角色权限不是 SN/VIN 适用性和第三方离线许可；
- 没有本场景所需的自包含 QML 包、签名更新和设备激活回滚。

因此可以把 BookStack 当临时门户或需求验证工具，不建议通过大量二次开发把它改造成车机技术内容权威库。Outline、Wiki.js 不再为凑数展开。

### 3.6 Payload：可选内容中心框架，不是开箱即用的 CCMS

在 Directus/Strapi/Payload 中，若确实需要代码优先的定制内容中心，**Payload 是更值得评估的一个**：官方提供 TypeScript 配置、React 管理 UI、REST/GraphQL/Local API、认证、文件、版本/草稿和文档/字段/操作级访问控制，核心为 MIT。[Payload 官方定位](https://payloadcms.com/docs/getting-started/what-is-payload)、[版本](https://payloadcms.com/docs/versions/overview)、[访问控制](https://payloadcms.com/docs/access-control/overview)

不过其官方 versions 支持恢复旧版本，draft/published 是通用 CMS 工作流；这并不自动满足“已发布 Edition 永不原地修改”的约束。车型/SN 规则、发布质量门、检索过滤、离线包和设备状态仍全部需要领域代码。

部署上还有一个明确成本：Payload 官方当前支持 MongoDB、Postgres、SQLite 适配器，没有 MySQL，因此不能无成本嵌入当前 MySQL 主库；引入它会增加 Node.js/Next.js 服务及数据库/同步治理。[Payload 数据库官方说明](https://payloadcms.com/docs/database/overview) 所以它不属于本项目最小组合，只适合团队决定用独立 TypeScript 内容中心替代大量自建后台时。

**Directus 不列入宽松开源最小基线。** 它连接数据库后可生成 REST/GraphQL API、管理应用、认证和细粒度访问控制，技术上适合快速搭建数据后台。[Directus 架构](https://directus.io/docs/getting-started/architecture)、[访问控制](https://directus.io/docs/guides/auth/access-control) 但最新 v12 官方说明采用 MSCL（source-available，源自 Fair Core License），附 Innovation Grant、Core 层级、软件 key 和四年后转 GPLv3 等安排，而非简单 MIT/Apache 开源。[Directus v12 许可证变更](https://directus.io/blog/directus-v12-license-change) 大型企业采用前必须按版本、营收/人数阈值和功能层级做法务及成本评估。Strapi 不再为凑数展开。

### 3.7 OpenSearch：可替代搜索基础设施，不提供领域授权模型

OpenSearch 官方定位为搜索与分析引擎，Apache-2.0，支持全文、聚合和相关扩展；Docker 可用于部署，生产仍需集群容量、安全、快照和升级管理。[OpenSearch 官网](https://opensearch.org/)、[官方 Docker 部署](https://docs.opensearch.org/latest/install-and-configure/install-opensearch/docker/)

其 Security 插件的 Document-Level Security 可用查询 DSL 限制角色能读取的文档，官方也提示复杂规则的性能影响及多角色组合语义。[OpenSearch DLS 官方文档](https://docs.opensearch.org/latest/security/access-control/document-level-security/) 这只是执行过滤的一种机制，并不会替平台定义：

- `current` 版本如何结合 SN、市场、语言、受众和发布通道求值；
- 搜索建议、摘要、facet 计数、RAG 召回和离线下载如何执行同一授权；
- 未知车辆配置时应该缩小、拒绝还是请求补选；
- 已撤回 Edition 和历史维修资料如何展示。

**当前建议是直接复用 Elasticsearch。** OpenSearch 是未来替换或许可证/运维策略变化时的候选，不是需要并行新增的第二套搜索。Solr、Meilisearch 不为凑数加入；它们同样不会消除上述业务自建工作。

### 3.8 Readium：只在未来需要通用 EPUB/移动阅读时引入

Readium 官方定位为 EPUB 3 和开放 Web 数字阅读技术，提供 Swift、Kotlin、TypeScript 等工具包。[Readium 官网](https://readium.org/)、[官方组织仓库](https://github.com/readium) 以 Swift Toolkit 为例，支持出版物模型、EPUB/PDF 导航、文本搜索等，代码为 BSD-3-Clause；LCP 支持还涉及 EDRLab 提供的额外二进制组件。[Swift Toolkit 功能与部署](https://github.com/readium/swift-toolkit)、[许可证](https://raw.githubusercontent.com/readium/swift-toolkit/main/LICENSE)

它适合可选的 EPUB 导出和 iOS/Android 阅读器，不是 Qt/QML 阅读组件，也不提供云端手册治理、车辆变体、内容授权或更新服务。当前 QML 已按六种 Block 设计 delegate，引入 EPUB/Readium 只会增加第二套交付语义，故不进入最小组合。

### 3.9 MinIO：继续承担对象存储，但需正视当前维护与分发变化

MinIO 官方仓库将其定义为高性能、S3 兼容对象存储，适合保存原件、图片、转换产物和离线包。[MinIO 官方仓库](https://github.com/minio/minio)

需要特别注意当前官方状态：社区仓库标记“不再维护”，社区版改为 source-only，历史预编译二进制不再获得更新；源码许可证为 AGPLv3，商业支持/发行路线转向 AIStor。这里不推导“调用 S3 API 就必然使业务代码被 AGPL 传染”之类法律结论，但要求项目组对现有镜像版本、安全更新、源码构建、再分发和支持策略做正式评审。

MinIO 只负责对象及 S3 访问机制。原件不可变规则、内容哈希、资产去重、授权下载 URL 有效期、包签名和留存删除策略仍是平台业务与安全工作。

### 3.10 Keycloak：复用身份，不把内容授权外包给 IdP

Keycloak 官方提供 SSO、OIDC/OAuth 2.0/SAML、身份代理、LDAP/AD 用户联邦和细粒度授权服务，采用 Apache-2.0。[Keycloak 官网](https://www.keycloak.org/)、[许可证](https://raw.githubusercontent.com/keycloak/keycloak/main/LICENSE.txt)

适合统一 Web、管理后台和更新服务的用户/客户端身份。仍需自建 `ContentLicense/Entitlement`、车辆与租户关系、Edition 可见性、离线权利和包签发。车机长期离线还不能假设每次请求都能 introspect token；令牌有效期、离线授权凭证、撤销提示和宽限期必须由产品与安全策略明确，而不是由“用了 Keycloak”自动解决。

### 3.11 TUF / Uptane：借鉴安全更新，而非寻找现成手册 OTA 产品

TUF 官方是安全软件更新框架，通过带角色的签名元数据、门限密钥、版本与过期机制增强更新安全。其规范明确写出非目标：**不创建通用更新系统，不定义包格式，也不实际执行应用文件更新**。[TUF 规范 §1.4](https://theupdateframework.github.io/specification/latest/) python-tuf 是 Python 参考实现，双重 MIT/Apache-2.0，可作为服务端工具或实现参考，并非现成 QML 客户端。[python-tuf 官方仓库](https://github.com/theupdateframework/python-tuf)

Uptane 则面向地面车辆，将 Image Repository、Director Repository、车辆/ECU 版本报告等纳入安全设计。[Uptane Standard](https://uptane.org/docs/latest/standard/uptane-standard) 官方部署文档明确：“Uptane 是标准，没有官方发行版或实现”，实际部署仍需密钥、可靠时间、ECU 预置和运营决策。[Uptane Deployment Best Practices](https://uptane.org/docs/2.1.0/deployment/best-practices)

本项目可分阶段采用：

1. MVP 对 manifest/包做发布签名，验证哈希、签名、schema、依赖和适用性，暂存后原子激活。
2. 当需要防止仓库被攻破后的元数据回滚/冻结、门限签名和系统化密钥轮换时，引入 TUF 元数据模型。
3. 只有当手册包需要与整车 OTA、Director/Image 仓库和 ECU 安全体系统一时，再评估 Uptane；不要为纯内容包直接复制整套汽车软件 OTA 复杂度。

还需区分两种“回滚”：更新安全机制拒绝攻击者把设备降级到旧包，与本项目在新包激活失败后自动恢复上一已知可用内容并不矛盾。若未来完整采用 Uptane，应由更新安全设计明确授权降级和业务恢复策略，不能简单关闭防回滚检查。

## 4. 无论选哪些组件，都必须自建的业务层

| 自建能力 | 最小职责 | 不能由候选组件自动替代的原因 |
|---|---|---|
| **规范内容模型** | `SourceDocument/Manual/Edition/Section/Block/Asset/CrossRef`，稳定 ID、schema 版本、来源定位 | 解析器、Wiki、RAG chunk 和搜索文档都不是该跨终端权威模型 |
| **不可变版本与差异** | 发布 Edition 不原地修改，替代/撤回、历史版、当前适用版、跨版本锚点和差异 | CMS revision、文档站 version、解析缓存与业务 Edition 语义不同 |
| **变体与适用性** | 受控轴、SN/VIN 范围、VariantProfile、包含/排除、未知值策略、矩阵测试 | DITAVAL 是构建过滤；搜索过滤和 IdP 属性都没有车辆权威规则 |
| **内容许可与授权** | 在线/离线/打印/导出/再分发权利，用户/角色/车辆/租户 Entitlement，有效期与审计 | Keycloak 提供身份，CMS 提供通用 ACL，但不掌握合同权利和车辆内容关系 |
| **质量门与审核发布** | 解析诊断、目录/图表/引用完整性、风险分级、人工/双人审核、状态机、发布审计 | 文档转换成功不代表技术内容正确；通用 draft/publish 不等于安全发布门 |
| **统一搜索语义** | Catalog/Section/TypedData 索引，精确故障码/章节号、中文词表、排序、深链、权限与 facet 一致性 | OpenSearch/ES 只执行查询，不知道业务字段、当前适用版或深链 |
| **Web 手册库与阅读 API** | 手册卡片、筛选、完整目录、六种 Block、历史版、搜索结果、无权限/不适用保护 | 现成门户的页面模型和展示语义不同，直接 URL/API 也必须执行授权 |
| **离线包构建器** | 自包含内容、资源、本地索引、适用性、许可、包依赖和增强 manifest，可复现构建 | PDF/EPUB 下载不是受管理离线包；CMS/搜索引擎不负责 QML 包 |
| **更新与设备状态** | 更新发现、包签发、断点续传、暂存、校验、原子激活、旧包恢复、撤回策略、状态回传 | TUF/Uptane 不提供完整业务运营，MinIO 只是下载存储 |
| **QML 本地运行时** | 库页、TreeView/ListView、块 delegate、图表、离线全文/精确搜索、版本提示和包管理 | Readium 不是 QML；RAGFlow 在线服务不能承担离线能力 |
| **批量运营与可观测性** | 幂等任务、失败隔离、重试/取消、审核队列、指标、审计、备份恢复和索引重建 | 各组件独立日志不等于端到端文档/批次/Edition/设备追踪 |

尤其需要保持一个**统一适用性与授权判定器**：目录、阅读 API、搜索结果/建议/facet、RAG 派生、包构建和更新签发必须调用同一语义。把不同规则分别写在 UI、搜索查询和 QML 中，会导致串配置或越权。

## 5. 三种建设选择

### 5.1 路线 A：轻量组合（推荐）

**组合：** 现有抽取管线 + 按需 PDF/OCR 适配器 + 自建 MySQL 规范内容库 + 现有 MinIO/S3 + 现有 ES + RAGFlow 在线问答 + 自建 Web/API/发布构建/更新服务 + QML 本地运行时。需要企业 SSO 时加入 Keycloak；需要更强更新元数据安全时引入 TUF。

**优势**

- 最大化复用当前确定性解析、六种 Block、图片表格、故障码/保养规则、manifest 和 QML 设计。
- 权威内容、搜索/RAG 和终端包职责清晰，不会被某个门户或 CMS 的通用模型绑住。
- 新增基础设施少，适合先完成单型号在线/离线纵向闭环，再批量扩到几千至上万文档。

**代价**

- 版本、变体、授权、审核、Web、包和更新都需要真实业务研发，不存在“装齐容器即完成”。
- 初期管理后台和审核工作台不如成熟 CCMS 完整，需要围绕实际运营逐步建设。

**适用条件：** 当前主要任务是存量 Word/PDF 迁移和多终端交付，而不是立即建设大规模多作者结构化创作体系。与本仓库现状最匹配。

### 5.2 路线 B：文档门户简化路线

**组合二选一：**

- 人工或脚本转换为 Sphinx 源，由 Sphinx + Read the Docs/静态托管发布公开文档站；或
- 将内容导入 BookStack，利用 Books/Chapters/Pages、搜索、页面修订和角色权限快速上线内部在线门户。

**优势：** 上线快，编辑和阅读现成，适合验证目录、分类、搜索词和用户任务，也适合权限简单、无需复杂车机交付的公开资料。

**明显缺口：** 无统一封闭 Block 协议、SN/配置动态适用性、不可变 Edition 治理、复杂内容权利、QML 自包含包与设备更新。即使按车型预生成多个静态站点，也只是构建时拆分，不能代替在线授权与车机状态管理。

**建议边界：** 可把它作为短期在线门户或原型，但应保留独立规范内容源和导出适配器；不要直接在门户数据库里累积不可迁移的权威业务数据。若目标始终包含当前全部需求，这条路线不能作为最终架构。

### 5.3 路线 C：商业 CCMS / IETM

**组合：** 采购结构化 CCMS，必要时选择支持 DITA/S1000D/IETM 的商业创作、CSDB、审核和发布套件；通过适配器输出到本项目 Section/Block、Web 和 QML。商业 CCMS 例如 RWS Tridion Docs 官方明确定位为覆盖创作、翻译、管理、交付和消费的端到端结构化内容方案，含组件复用、治理、工作流、权限和多渠道交付，并提供云/混合/本地选项。[Tridion Docs 官方产品页](https://www.rws.com/content-management/tridion/docs/)

**优势**

- 多作者创作、topic 复用、翻译、基线、评审、合规和复杂产品变体已有成熟工作流。
- 对需要供应链交换、S1000D CSDB/BREX/DMRL 或正式 IETM 交付的合同，比自行拼装通用组件更接近行业实践。
- 可降低长期内容生产和治理成本，而不只是降低服务器软件成本。

**代价与仍需自建/集成**

- 许可、实施、迁移、培训和供应商依赖成本最高；产品“支持变体”不等于已有本企业 SN/VIN 主数据和规则。
- 存量 Word/PDF 仍需清理、结构化和质量验收。
- 仍须确认开放 API/导出是否足以生成当前 Block、manifest、本地索引，避免只能进入厂商门户。
- 第三方内容离线权、现有 RAGFlow 集成、Web 个性化、QML 包更新和设备状态通常仍是项目集成范围。

**采用触发条件：** 内容复用/翻译/合规工作量已显著超过平台自建成本，或客户合同明确要求完整 DITA CCMS、S1000D/IETM。DITA-OT 本身不能替代这条路线中的 CCMS。

### 5.4 三路线决策表

| 维度 | 轻量组合（推荐） | 文档门户简化 | 商业 CCMS/IETM |
|---|---|---|---|
| 首要目标 | 存量手册统一结构化、多终端和受控离线 | 尽快上线在线阅读 | 结构化创作、复用、翻译、合规与行业交付 |
| 初始软件/采购成本 | 低至中，主要复用现有组件 | 最低 | 高 |
| 领域自建量 | 高，但集中在必要业务层 | 表面上低，目标需求仍需另建 | 中至高，主要是数据、规则与终端集成 |
| 完整目录/全文检索 | 可完全按 Section/Block 设计 | 可快速获得基础能力 | 通常成熟，但需核实导出与深链 |
| 版本/变体/内容权限 | 完全可控，需自建 | 通用能力明显不足 | 通常较强，车辆主数据和合同权利仍需集成 |
| QML 离线包/更新 | 沿用现有 manifest 最顺畅 | 基本需另建一套 | 需定制适配器和更新服务 |
| 供应商/迁移风险 | 低，模型自有 | 中，避免门户成为唯一权威源 | 高，必须合同化开放导出和退出机制 |
| 当前推荐度 | **最高** | 仅作原型或缩减范围 | 达到明确业务触发条件后评估 |

## 6. 结合当前仓库的最小技术组合

### 6.1 已核实可直接延续的资产

- `pipeline/xc975_pipeline/docmodel.py` 已将 DOCX 段落/表格按文档流保序读取，展开自动目录内容，保留图片关系并处理表格合并单元格。
- `pipeline/xc975_pipeline/schemas.py` 已定义 `Section` 的 `section_id/seq/parent/面包屑` 和六种封闭 Block：`para/image/table/warning/steps/list`，每块有 `src` 溯源。
- `pipeline/xc975_pipeline/package.py` 已生成 tree、故障码、保养规则、图片和 `manifest.json`，manifest 有文档、适用变体、手册版本、规模及逐文件 SHA-256。
- `docs/project/随车助手-数据抽取规格说明.md` 已确定 Qt 6 QML、TreeView/ListView、块 delegate、图片缩放/表格横滑和本地数据包，不要求车机连接 MySQL。
- `tasks/plan.md` 已规划 Manual/Edition、结构化适用规则、权限、不可变发布、本地索引、签名和更新回滚。这些是正确的平台增量，不需要因引入外部项目而改变方向。

### 6.2 最小组件清单

| 层 | 最小选择 | 现在不引入什么 |
|---|---|---|
| DOC/DOCX | 现有 LibreOffice/受控 DOC 转换 + DOCX `DocumentModel` 确定性读取 | 不对所有 Word 做 OCR，不换成 Docling/MinerU 主链 |
| PDF/扫描件 | 现有 DeepDOC/PaddleOCR 路线优先；用相同样本评估 Docling，必要时再评估 MinerU | 不并行长期维护多个等价 PDF 主解析器 |
| 权威内容库 | 当前 Python/Go 服务 + MySQL，自建 Manual/Edition/Section/Block 等实体 | 不把 RAGFlow、BookStack 或通用 CMS 当唯一权威源；不默认新增 Payload |
| 原件/资源/包 | 现有 MinIO/S3 接口，内容哈希、不可变 key、授权下载 | 不新增第二对象存储；但制定 MinIO 当前版本的维护/升级策略 |
| 在线确定性搜索 | 现有 Elasticsearch，从已发布 Edition 派生 Catalog/Section/TypedData 索引 | 不同时新增 OpenSearch/Solr/Meilisearch |
| 在线语义问答 | 现有 RAGFlow，只索引已审核内容并返回 Edition/Section 引用 | 不让 RAG 代替目录、全文和离线搜索 |
| 身份 | 初期沿用现有认证；有统一 SSO/LDAP/OIDC 需求时部署 Keycloak | 不用 IdP 角色表代替 Entitlement/ApplicabilityRule |
| Web | 当前 React/TypeScript 技术栈，自建手册库、目录、搜索、历史版和审核 UI | 不引入 BookStack/Sphinx/RTD 作为最终业务门户 |
| 车机 | 当前 Qt 6 QML + JSON/Block + 本地索引；发布时构建索引并打入包 | 不引入 Readium/EPUB 作为车机主协议 |
| 离线更新 | 全量包、增强 manifest、发布签名、暂存、原子激活、上一可用包恢复 | MVP 不做复杂增量，不直接上完整 Uptane；TUF 按威胁模型后增 |
| 新内容生产 | 后续单系列 DITA 试点，可用 DITA-OT 输出规范化 DITA 再适配 | 不在存量迁移期自建或采购完整 CCMS |

### 6.3 最小数据流

```text
DOC/DOCX/PDF
    │
    ▼
现有格式路由与 DocumentModel
    │  仅复杂 PDF/扫描件调用经 benchmark 选定的 OCR/解析适配器
    ▼
Section/Block + 资源 + 质量报告
    │
    ▼
MySQL 权威内容库：Manual / Edition / 变体 / 许可 / 审核 / 发布
    │
    ├──► MinIO：原件、Asset、可复现离线包
    ├──► ES：Catalog / Section / TypedData 派生索引
    ├──► RAGFlow：已审核内容的在线问答派生语料
    ├──► Web：手册库 / 完整目录 / 搜索 / 阅读 / 历史版
    └──► 发布构建器：JSON + 资源 + 本地索引 + 签名 manifest
                                  │
                                  ▼
                       更新服务 → QML 暂存/校验/激活/恢复
```

### 6.4 现有 manifest 的最小增强方向

现有逐文件 SHA-256 应保留，但它只证明字节完整性，不能证明发布者身份。至少补充：

- `schema_version`、`minimum_reader_version`、稳定 `package_id` 和 `edition_ids`；
- 结构化适用规则引用、许可/发布通道、包类型和依赖；
- 每个文件的字节数与哈希，本地索引也纳入文件清单；
- 内容/包哈希、签名算法、`key_id` 和签名值；
- 替代关系与激活所需信息；设备运行状态放服务端/设备状态模型，不回写不可变包。

MVP 仍坚持全量、自包含包。断网冷启动后，目录、全部 Block、图片表格、故障/保养数据和本地搜索不得依赖云端补齐。

## 7. 推荐决策与落地顺序

**最终推荐：路线 A，轻量组合。** 原因不是它功能名称最多，而是当前仓库已经拥有最关键且最难通用化的领域资产：保序 Word 中间模型、封闭 Block、章节树、类型化故障/保养数据和 QML 数据包。其他项目应围绕这些资产补位，而不是迫使平台接受另一套页面、chunk 或电子书模型。

建议按以下顺序做真实验证：

1. **先固定协议与业务规则**：Edition 不可变、稳定深链、VariantProfile、Entitlement、发布/撤回和 manifest 签名语义。
2. **用代表性真实手册做解析器对比**：标题树、阅读顺序、合并表格、图号/题注、跨页内容、扫描件、来源定位、耗时与资源；不凭官网准确率选型。
3. **先打通一份手册纵向闭环**：上传→审核→发布→Web 目录/搜索→全量包→QML 断网阅读/搜索→更新失败不破坏旧包。
4. **再批量化和运营化**：幂等、失败隔离、重试、审核台、索引蓝绿重建、设备状态、审计、备份恢复和规模压测。
5. **最后决定可选重组件**：结构化创作复用明显时试点 DITA；有 SSO 需求时加 Keycloak；威胁模型需要时加 TUF；创作治理规模或合同要求明确时采购 CCMS/IETM。

一句话概括：**开源项目足以搭好解析、存储、搜索、身份和安全更新的“零件”，但不能提供本项目的车辆技术内容业务操作系统；最小方案应复用现有 RAGFlow/MySQL/MinIO/ES 与 DocumentModel/Section/Block/manifest/QML 主链，集中自建规范内容治理、变体授权、Web 阅读和离线更新闭环。**

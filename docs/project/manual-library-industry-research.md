# 技术手册库工业案例与参考架构调研

| | |
|---|---|
| 调研日期 | 2026-11-07 |
| 调研目标 | 为“大量技术手册集中展示、完整章节目录、全文检索、按车型/配置/版本筛选、在线/离线阅读”的手册库选型与架构设计提供依据 |
| 案例范围 | 4 个汽车/装备服务信息案例、3 个工程/标准平台、1 个工程知识平台、1 个技术电子书平台，共 9 个 |
| 项目约束 | 复用现有 DocumentModel、Section/Block 章节树、变体元数据、图片/表格抽取、manifest 与 QML 车端方案；不要求重写现有抽取管线 |
| 交付性质 | 外部产品公开能力调研 + 本项目通用架构建议；不是对任何厂商内部实现的逆向或断言 |

## 0. 核心结论

1. **产品应同时有两种入口，而不是在“车机手册”和“小说商城”之间二选一。** 汽车平台普遍以“已选车辆/VIN/序列号”为任务上下文，O'Reilly 则证明了书库、分类、全文搜索、收藏/播放列表、离线下载和跨设备同步的价值。本项目宜采用“**本机手册优先 + 全部手册库可切换**”：车机默认只展示当前车辆适用的最新授权版本，用户进入手册库后才浏览其他车型、配置、语言和历史版本。
2. **全文检索不能替代结构化目录，也不能替代变体过滤。** ALLDATA 同时保留 Search Vehicle Information 与 Systems & Components；Accuris 同时提供文档目录、文内搜索和全库 facets；Knovel 把书、章节、表格层级元数据纳入相关性。本项目应以 Section 为基本命中和深链单元，目录、正文、表格、故障码、图题分别进入合适的索引字段。
3. **车型/配置适配必须是权限之外的一道硬约束。** 不能仅靠搜索排序“尽量把正确版本排在前面”。VIN/SN 或用户选择先解析为结构化 VariantProfile，再同时约束目录可见性、搜索结果、RAG 召回、阅读页面和离线包签发。
4. **“可下载 PDF”不等于“受管理的离线手册库”。** Knovel 支持章节 PDF 下载但交互工具必须在线；ASTM/SAE 支持文档下载；O'Reilly 支持 App 离线内容与进度同步；Accuris 则公开了更完整的受控离线模型：授权文档、加密存储、有效期、离线批注及恢复联网后的同步。车机需要最后一种，而不是简单保存若干 PDF。
5. **现有项目资产已经足够作为交付层核心。** 保留 `DocumentModel → Section/Block → tree_X.json/img/manifest.json` 主链，在其上增加手册目录、不可变版本、结构化适用规则、权限、发布与设备包状态即可。RAGFlow 继续承担在线检索问答，不作为章节树、版本或离线包的唯一存储底座。
6. **DITA 值得用于后续内容生产，S1000D 宜选择性借鉴而非立即全套落地。** DITA 的 topic/map/bookmap 与条件处理适合多车型、多语言、多配置复用；S1000D 的数据模块、适用性、质量状态和 CSDB 管理要求与工程机械很匹配，但全套业务规则、数据模块编码和交换体系的导入成本明显高于当前 MVP 所需。
7. **MVP 应先做“完整、正确、可离线、可更新”，再做商城式推荐和协作。** 第一阶段的验收重点不是封面和推荐算法，而是：不串配置、章节与图表完整、断网可搜索、包校验失败不启用、更新可回滚、每个答案和深链都能回到明确的版本与章节。

## 1. 方法、选例与证据边界

### 1.1 证据标签

- **[官证]**：厂商、标准组织或平台官方公开产品页、帮助文档、条款、API 文档或标准规范直接证实的外部功能。
- **[项目实证]**：本次只读核对当前仓库代码和既有规格得到的结论。
- **[推导/建议]**：由多个案例的共性及本项目约束推导的架构，不代表案例厂商内部如此实现。

### 1.2 必须保留的解释边界

- 本报告**不推断**任何案例内部使用 Elasticsearch、某种数据库、特定向量模型或私有搜索算法。只有 Knovel 官方明确公开了部分相关性因素，本报告才引用这些因素。
- “支持搜索”不自动等于“覆盖所有 PDF 和图片内文字的全文搜索”；“移动网页”不自动等于“离线 App”；“下载文档”不自动等于“有版本治理的离线包”。
- “未公开证实”表示本次公开资料不足以确认，**不表示产品一定没有该功能**。本次未登录付费账号，也未对受限内容进行实测。
- 功能、套餐、地区、语言和离线限制会随产品合同变化；采购或内容合作前需以目标地区、目标版本的合同与实测复核。
- Identifix Direct-Hit 与 Toyota TIS 的官方资料能证实维修资料、搜索或订阅，但本次可公开核验资料对“完整目录 + 检索 + 版本 + 离线”的整体覆盖不如入选案例，故不为凑数纳入主表。Techstreet 与 Accuris/标准平台能力重叠，也未另列弱证据案例。

## 2. 九个案例的官方公开能力

### 2.1 汽车维修与装备服务信息

| 案例 | 内容组织与目录 | 搜索与 facets | 车型/配置/版本适配 | 阅读器、图片与表格 | 在线/离线 | 权限与商业模式 |
|---|---|---|---|---|---|---|
| **ALLDATA Repair / Collision** | OEM 维修程序、TSB、DTC、规格、保养、图纸集中在一个车辆上下文；同时提供 Popular Information、Systems & Components 和搜索入口。[S-ALLDATA-SEARCH] | Search Vehicle Information 按类别返回维修程序、图纸、TSB 等；支持建议、拼写检查、DTC 图表搜索及系统/部件过滤。官方称其为标准化 OEM 分类并做术语映射，但未据此推断具体引擎。[S-ALLDATA-SEARCH][S-ALLDATA-RELEASE] | 可按 Year/Make/Model/Engine 或 VIN 缩小车辆范围；车辆选择贯穿资料访问。[S-ALLDATA-RELEASE] | OE 图与交互彩色电路图；支持缩放、平移、旋转、图内文字搜索、线路/部件高亮和多图查看；另有保养表与 OEM PDF 展示。[S-ALLDATA-DIAGRAM][S-ALLDATA-RELEASE] | **移动可用不等于维修资料离线可用。** 官方明确：Diagnostics 最近 72 小时内登录后可离线，但离线时 Repair/Collision 及其链接资料不可用。[S-ALLDATA-MOBILE] | Repair/Collision 与 Mobile/Diagnostics 等商业订阅组合；门户管理员可按店内角色分配 App 权限。[S-ALLDATA-MOBILE][S-ALLDATA-RELEASE] |
| **Mitchell 1 ProDemand** | OEM 维修、保养、估计信息与经验修复内容集中；以 1Search Plus 的结果卡片和维修工作流组织，而非只给一长串文档链接。[S-M1-PRODUCT][S-M1-SEARCH] | 选择车辆后一次查询汇聚 DTC、规格、维修程序、图纸、拆装、修后信息和工时等类别；公开资料证明聚合检索，不据此声称所有原文均为全文索引。[S-M1-SEARCH] | 提供车辆选择与 Plate-to-VIN，目的是得到精确车辆描述并减少错误选车。[S-M1-VIN] | OEM/交互彩色电路图、部件和连接器等视图；图纸导航、搜索和部件联动是重点。[S-M1-PRODUCT][S-M1-WIRING] | 本次官方公开资料未证实完整手册库离线包；应暂按在线服务理解，不能用平板优化推断离线。 | 面向维修企业的商业产品，官网提供产品和演示入口；具体用户/门店计费需按合同核验。[S-M1-PRODUCT] |
| **HaynesPro WorkshopData** | Tech / Electronics / Smart 三类能力；Tech 包含分步维修手册、OEM 保养、维修工时、技术图、调整数据、油液等，官方强调标准化数据结构和单一多品牌入口。[S-HP-PRODUCT] | 公开入口展示车辆筛选与导航；官方证明快速结构化检索，但本次未取得“全文覆盖范围”的充分公开说明。[S-HP-PRODUCT][S-HP-UI] | 公共界面直接显示 VIN、发动机代码、排量、功率、Model Year、Variant code、车桥类型等字段，说明其不止按车型名称筛选。[S-HP-UI] | 分步程序、技术插图、扭矩、保养工作表、电路与诊断数据；技术图可突出相关部件。[S-HP-PRODUCT] | 独立版官方定位为在线工具。本次查看到的 Red 合同条款还禁止未经授权的系统化下载和后续离线检索；这不是“技术上绝对不能离线”的证明，而是说明**离线再分发必须单独取得授权**。[S-HP-PRODUCT][S-HP-TERMS] | 独立许可、Portal-to-Portal/SSO、Web Services 数据集成三种交付；面向维修网络、零部件商、车队和设备厂商。[S-HP-PRODUCT] |
| **Cat SIS2GO / SIS Disconnected** | 操作保养手册、零件、拆装、原理图、测试调整、故障排查、系统原理和推荐工具集中；SIS 是这些信息的服务信息系统来源。[S-CAT-SIS2GO] | 官方明确称按拥有设备提供 portable、searchable 的信息；本次未据此推断完整目录或搜索技术。[S-CAT-SIS2GO] | **按每台设备序列号**提供手册与服务信息，比只按产品系列更贴近实际装配配置。[S-CAT-SIS2GO] | 操作保养、原理图、故障排查、测试调整与分步维修程序，适合任务导向阅读。[S-CAT-SIS2GO] | SIS2GO 页面称 always accessible，但这句话本身不足以证明离线实现；Cat Parts 官方 FAQ 另将 **SIS Disconnected** 明确称为访问技术零件和服务信息的 offline solution。两者不能混写成同一离线机制。[S-CAT-SIS2GO][S-CAT-OFFLINE] | SIS2GO 操作保养和零件信息免费；服务手册信息提供月/年订阅。[S-CAT-SIS2GO] |

### 2.2 工程、标准与技术电子书平台

| 案例 | 内容组织与目录 | 搜索与 facets | 车型/配置/版本适配 | 阅读器、图片与表格 | 在线/离线 | 权限与商业模式 |
|---|---|---|---|---|---|---|
| **Knovel** | 多学科工程参考书、材料/物质数据、公式、图表；Browse 按主题/子主题、Premium Offerings 组织；官方搜索说明还明确使用 book > chapter > table 层级元数据。[S-KNOVEL-WORKS][S-KNOVEL-BROWSE][S-KNOVEL-RANK] | 全文、数值/属性搜索；Content Type、Concept、Date facets，可多组、多值组合。官方公开相关性因素包括精确短语、词频/邻近度、字段权重、同义词和层级元数据，但没有公开内部引擎。[S-KNOVEL-WORKS][S-KNOVEL-FACET][S-KNOVEL-RANK][S-KNOVEL-SYNONYM] | 不是车型平台；其可借鉴点是“技术对象 + 属性 + 内容层级”检索，以及按订阅学科控制内容。 | Knovel Viewer 提供导航/高亮；交互表格、图、公式和单位工具把静态内容变成可计算数据。[S-KNOVEL-DOWNLOAD][S-KNOVEL-EQUATIONS] | 可下载/打印**书籍章节 PDF**，不可整书下载；交互表格、图和公式必须在线。移动浏览器可用不等于离线。[S-KNOVEL-DOWNLOAD][S-KNOVEL-MOBILE] | 机构按学科订阅，锁图标标识订阅外内容；My Knovel 保存常用内容、搜索和协作文件夹。[S-KNOVEL-EQUATIONS][S-KNOVEL-MY] |
| **Accuris / IHS Engineering Workbench** | 标准、法规、代码和技术资料统一库；官方白皮书证实文档内 Table of Contents 跳节、修订历史、引用/被引用文档、项目文件夹。[S-ACCURIS-WP] | 单框识别文档号/关键词、布尔高级检索、发布机构/年份等 facets、文档内短语搜索；新版还公开语义检索与条款定位。这里只引用外部能力，不推断底层引擎。[S-ACCURIS-WP][S-ACCURIS-PRODUCT] | 以 active/historical 文档、Smart Compare 版本差异、Watch Lists/Alerts 和持久深链管理版本变化。[S-ACCURIS-WP][S-ACCURIS-PRODUCT] | 在线 Document Viewer 逐页打开长文档、目录跳节、文内搜索、批注/书签；可获取完整 PDF。[S-ACCURIS-WP] | EWB Mobile 官方公开：iOS/Android，最多预下载 100 份授权文档，离线可读 30 天，设备端加密；离线批注在联网后同步并合并。[S-ACCURIS-MOBILE] | 授权内容、既有账号、项目集合随移动端下发；Mobile 包含在 EWB Base/Pro 套餐，体现“内容许可 + 受控离线”而非匿名文件分发。[S-ACCURIS-MOBILE] |
| **ASTM Compass** | ASTM 标准、图书、论文及第三方内容集中；支持加入企业自有内容和标准。Compass Points 可指向标准局部并保留元数据与长期链接。[S-ASTM-COMPASS] | 官方证实搜索与 refine、保存搜索、书签；按 active/historical/withdrawn 过滤。公开产品资料未足以让我对所有内容类型承诺同一全文深度。[S-ASTM-COMPASS][S-ASTM-VIRTUAL] | 标准版本模型清晰：active、historical、withdrawn、work item、redline；支持版本比较和更新提醒。[S-ASTM-VOLUME][S-ASTM-COMPASS] | 在线 HTML 阅读、PDF 打印/下载、章节/局部注释、附件与内部文档链接。[S-ASTM-VOLUME][S-ASTM-COMPASS] | 可下载 PDF 到工作站；本次公开资料未证实带同步/失效管理的完整离线库，应归为“文档级下载”。[S-ASTM-VOLUME][S-ASTM-VIRTUAL] | 单用户/多用户、按卷/节/全集等订阅；在线卷每周更新，年度续订。[S-ASTM-VOLUME] |
| **SAE Mobilus** | 技术论文、期刊、标准、图书、研究报告等统一内容库；My Library 承载个人收藏和注释。[S-SAE-SEARCH][S-SAE-ANNOTATE] | 搜索建议、短语、通配符、词干和邻近搜索；facets 包括 My Subscription、内容类型、出版日期、主题、作者、机构；另有字段化布尔高级搜索。[S-SAE-SEARCH][S-SAE-ADVANCED] | 订阅含历史标准时可做 redline 版本比较；可设置标准提醒。[S-SAE-REDLINE] | 文档页提供下载、收藏、提醒和在线文本批注；公开资料未足以概括所有图书/论文的目录与表格呈现。[S-SAE-DOWNLOAD][S-SAE-ANNOTATE] | 文档可下载；在线批注明确是 online。不能把文档下载写成带同步的离线阅读器。[S-SAE-DOWNLOAD][S-SAE-ANNOTATE] | 机构订阅支持 IP、用户名密码和 SSO；My Subscription 过滤授权内容，历史标准等能力取决于订阅。[S-SAE-LOGIN][S-SAE-SEARCH][S-SAE-REDLINE] |
| **O'Reilly Learning** | 图书、章节、课程、视频、音频、Playlist 等统一目录；阅读器有目录、高亮和笔记，Playlist 可跨内容组织学习路径。[S-OREILLY-FEATURES] | 标题/作者/出版商/关键词搜索，按格式、主题、出版商、评分过滤，支持字段、布尔和 `text:` 正文限定。官方 Search API 返回结果、facets、元数据，并明确书/章父子记录及近实时索引更新。[S-OREILLY-FEATURES][S-OREILLY-SEARCHAPI] | 重点是版本化的书目/章节和 Early Release，不是车型适配；可借鉴“目录记录 + 章节子记录 + 深链”。 | 在线书籍阅读、目录、高亮、笔记、选中内容链接；本次不额外推断其所有表格/插图的内部格式。[S-OREILLY-FEATURES] | 移动 App 可下载内容离线观看/阅读，设备自动同步阅读位置；Playlist 自动同步到移动端。[S-OREILLY-APPS][S-OREILLY-FEATURES] | Individual/Team/Enterprise；企业有用户/组管理、SSO、SCIM、Search/Insights API。SSO 深链先认证再跳到指定内容。[S-OREILLY-PRICING][S-OREILLY-SSO] |

## 3. 案例详细启示：应借鉴什么，不应误学什么

### 3.1 ALLDATA：车辆上下文与目录/搜索双入口

**[官证]** ALLDATA 的官方搜索指导没有让用户只依赖搜索框，而是同时保留 Popular Information、Systems & Components 与文档内 Ctrl+F；还提醒图片内嵌文字可能绕过搜索。它证明成熟平台也需要“分类导航、聚合搜索、文内定位”三层配合。[S-ALLDATA-SEARCH]

**[推导/建议]** 本项目不能把 RAG 问答当成唯一入口。车机至少要有：本车目录、手册内全文搜索、当前章节内查找；对尚未结构化的图片文字列入质检，而不是默认其可被搜索。另一个重要反证是 ALLDATA 的离线 Diagnostics 并不携带 Repair 内容，所以“诊断离线”和“手册离线”必须分别验收。

### 3.2 ProDemand：搜索结果应按维修任务组织

**[官证]** 1Search Plus 把同一车辆的一次查询分成 DTC、图纸、拆装、修后信息、工时等工作流类别，Plate-to-VIN 则用于精确选车。[S-M1-SEARCH][S-M1-VIN]

**[推导/建议]** 手册库搜索结果不必只有“书名 + 段落”。可以增加“操作程序 / 规格表 / 故障码 / 图片图纸 / 保养”结果类型，但每类仍应落到 `edition_id + section_id + block_id`，避免成为无法回到原文的孤立答案。

### 3.3 HaynesPro：数据产品、门户和授权应解耦

**[官证]** HaynesPro 同时提供独立门户、SSO 门户集成与 Web Services，且合同对离线保存和再分发有明确限制。[S-HP-PRODUCT][S-HP-TERMS]

**[推导/建议]** 本项目应把手册内容服务与 QML 展示分离，未来既可向车机发离线包，也可向 Web/售后系统提供同一目录和搜索 API。若未来引入第三方手册，不能因为技术上能打包就默认合同允许；授权模型需要记录离线、打印、导出和再分发权利。

### 3.4 Cat：序列号是最有价值的适配锚点

**[官证]** SIS2GO 按设备序列号组织“你拥有的每台设备”的资料，免费内容与付费服务信息分层。[S-CAT-SIS2GO]

**[推导/建议]** 当前 XC975-EV 已有适用 SN 元数据，应继续以 SN 为最终适配依据，车型/市场/干桥/湿桥只是可解释的筛选维度。无法由 SN 确定配置时，应要求用户补充选择并显示“适用性未完全确认”，不能静默回退到全部变体。

### 3.5 Knovel：表格不是图片，层级元数据直接影响检索

**[官证]** Knovel 把交互表格、图、公式作为独立技术工具；官方还公开了书 > 章 > 表层级元数据参与相关性，以及可开关的工程概念同义词扩展。[S-KNOVEL-WORKS][S-KNOVEL-RANK][S-KNOVEL-SYNONYM]

**[推导/建议]** 当前项目的 TableBlock、图号/题注、面包屑都应进入搜索，而不是只索引段落纯文本。故障码、扭矩、油液、SN、章节号需要精确字段；中文同义词宜使用经过审核的领域词表并保留开关/诊断信息，避免无边界扩展造成误召回。

### 3.6 Accuris：最接近“受治理的手册库 + 离线包”公开范例

**[官证]** Accuris 同时具备全库 facets、文档目录、文内搜索、修订历史、版本比较、深链，以及带数量/期限/加密/同步规则的移动离线能力。[S-ACCURIS-WP][S-ACCURIS-MOBILE]

**[推导/建议]** 本项目应复制其**能力边界**而非界面：云端确定授权和当前版本，车端持有明确版本的不可变包；离线阅读和批注可用，联网后检查更新并同步用户数据。其“100 份/30 天”是特定产品规则，不应原样搬为车机限制。

### 3.7 ASTM 与 SAE：版本状态必须是一等数据

**[官证]** ASTM 明确区分 active、historical、withdrawn、work item 和 redline；SAE 将历史标准比较与订阅权益关联。[S-ASTM-VOLUME][S-SAE-REDLINE]

**[推导/建议]** 手册版本不能只存一个日期字符串。至少需要 `current/superseded/withdrawn/draft` 状态、发布日期/生效日期、替代关系、变更摘要和适用性差异。默认搜索当前适用版，历史版用于维修旧车、审计和原文追溯，不应与现行版无标识混排。

### 3.8 O'Reilly：商城体验来自“个人空间 + 同步 + 开放集成”

**[官证]** O'Reilly 的价值不只是书多，而是搜索/facets、目录、高亮笔记、Playlist、离线下载、跨设备进度同步、企业 SSO 与 Search API 形成闭环。[S-OREILLY-FEATURES][S-OREILLY-APPS][S-OREILLY-SEARCHAPI]

**[推导/建议]** 手册库可增加最近阅读、收藏、下载管理、企业合集和“某车型维修包”等 Playlist 式集合，但推荐不能突破适用性和权限。商城式封面、评分、推荐属于后续体验层，不能优先于安全警告、版本和变体信息。

## 4. 内容生产与交换标准：DITA、S1000D、EPUB 的适用性

### 4.1 DITA：适合作为后续结构化创作与复用标准

**[官证]** OASIS DITA 1.3 将 topic 定义为创作和复用的基本单元，由 map 按层级组织发布；同一批 topics 可进入多个 maps。Bookmap 进一步提供 front matter、part、chapter、appendix、back matter 以及作者、所有者、版本和生产历史等元数据。[S-DITA-TOPIC][S-DITA-BOOKMAP]

**[官证]** DITA 的 `@audience`、`@deliveryTarget`、`@platform`、`@props`/`@otherprops` 等属性支持条件处理，DITAVAL 在发布时包含、排除或标记内容；topic 与 map 都可带元数据，map 可补充或覆盖 topic 元数据以支持不同上下文复用。[S-DITA-COND][S-DITA-FILTER][S-DITA-META]

**[推导/建议]**

- 适合：操作/保养/维修内容需要在多车型、市场、语言、受众之间复用；同一安全警告或通用工序需要在多个出版物中复用；需要由同一源生成 Web、PDF 和车机内容。
- 与当前模型的映射：DITA topic → 一个逻辑主题/章节单元；map/bookmap → 手册版本章节树；`xref/keyref/conref` → 内部引用与复用；DITAVAL → 按 VariantProfile 生成交付包；`fig/image/table/note/steps` → 归一化为现有封闭 Block 集。
- 不必做：为了使用 DITA 而推翻现有 Word 抽取，或把 DITA XML 直接交给 QML。现有 Section/Block 仍是稳定的车端交付协议。
- 标准边界：DITA 不替本项目规定全文索引、搜索排序、订阅收费、OTA 或离线权限，这些仍需单独设计。

### 4.2 S1000D：理念高度相关，全套采用应由业务规模决定

**[官证]** S1000D 官方将 Data Module 定义为可独立存在、可用 Data Module Code 从 Common Source Data Base 存取的描述/程序/操作信息单元。每个数据模块包含 identification and status 与 contents 两部分，前者用于 CSDB 管理、适用性、质量保证和检索控制。官方同时明确：CSDB 是存放和管理数据模块的“store”，S1000D **不定义其具体功能实现**。[S-S1000D-ABOUT]

**[官证]** S1000D 已从航空航天扩展到陆地、海洋和各种民用/军用设备，覆盖技术出版物的创建、管理和发布全生命周期；官方下载页还区分 major/minor/patch 及相应兼容含义。[S-S1000D-ABOUT][S-S1000D-DOWNLOAD]

**[推导/建议]**

- 对工程机械特别有价值的思想：模块级标识与状态、适用性、质量审核、出版物对数据模块的引用、插图/故障/保养/线路等信息类型，以及单一受控来源。
- 不宜在 MVP 直接承担的成本：完整 DMC/SNS 编码体系、BREX 业务规则验证、DMRL、CSDB 工作流和所有交换对象的全面改造。若没有航空航天/国防客户或跨企业 S1000D 交换要求，这些不会自动带来等额收益。
- 推荐采用“兼容概念而非宣称合规”：给 Section/内容模块增加状态、适用规则、审核和来源；用现有 manifest 表达发布包。只有合同或协作生态明确要求时，再建立真正的 S1000D 映射与一致性验证。

### 4.3 DITA 与 S1000D 的选择

| 维度 | DITA | S1000D | 本项目建议 |
|---|---|---|---|
| 核心抽象 | topic + map/bookmap | Data Module + CSDB + 出版物/业务规则体系 | 当前 Section/Block 可作为二者共同的下游交付模型 |
| 主要优势 | 技术写作、主题复用、条件发布、多格式输出 | 复杂装备全寿命、配置/适用性、质量与交换治理 | 新创作优先评估 DITA；S1000D 先吸收治理思想 |
| 变体支持 | 条件属性 + DITAVAL | 适用性是数据模块管理的重要部分 | 统一映射到 VariantProfile/ApplicabilityRule |
| 实施成本 | 中；可从一个手册系列试点 | 高；通常涉及编码、业务规则、工具和流程 | 不在 MVP 整体迁移 |
| 不解决的问题 | 搜索、权限、商城、离线更新需另建 | 官方明确不规定 CSDB 具体功能 | 搜索/OTA/权限仍是本项目自己的平台能力 |

### 4.4 EPUB：可选的通用阅读导出，不是车机主协议

**[官证]** W3C EPUB 3.3 是数字出版物分发和交换标准，可把 HTML、CSS、SVG 和资源打包成单文件容器；其规范包含 manifest、阅读顺序和导航等机制。[S-EPUB]

**[推导/建议]** 若未来需要把授权手册交给通用电子书阅读器，可由同一 Section/Block 模型导出 EPUB/PDF。车机仍使用现有 JSON + 图片 + manifest，因为 QML 需要表格横滑、警告块、故障/保养深链和受控更新；不应为了“像小说商城”而把 EPUB 阅读器变成唯一运行时。

## 5. 适合当前项目的参考架构

### 5.1 分层原则

**[推导/建议]** 将系统分为四层，避免源格式、内容治理和端侧展示相互绑定：

1. **源与抽取层**：Word/PDF，未来可接 DITA/S1000D；复用现有 DocumentModel、编号注入、表格分类、图片转码和审核清单。
2. **规范内容层**：手册族、不可变版本、章节树、封闭 Block、资源、交叉引用、适用规则、审核状态；这是唯一权威内容来源。
3. **发布与发现层**：目录 API、全文/精确搜索、facets、权限、版本解析、RAG 语料派生、全量/增量包构建、签名与分发。
4. **消费层**：Web 手册库、售后/门户集成、QML 车机、可选 EPUB/PDF 导出；均通过稳定 ID 回到同一章节。

```text
Word / PDF / 未来 DITA 或 S1000D
                 │
                 ▼
  现有 DocumentModel + 编号/表格/图片抽取 + audit
                 │
                 ▼
       规范内容库（手册族 / Edition / Section / Block）
       变体规则 / 版本状态 / 资源 / 引用 / 审核 / 权限
                 │
        ┌────────┴─────────┐
        ▼                  ▼
 云端目录与搜索/API      发布构建器
 RAG 派生语料           全量包/后续增量包/本地索引/签名
        │                  │
        ▼                  ▼
 Web 手册库/售后门户     云端更新服务 → QML 车机数据目录
                             ├─ 目录/阅读/图表/本地全文搜索
                             └─ 故障码/保养规则/深链（均离线）
```

### 5.2 对现有资产的复用与必要增量

| 现有资产 | 本次核对位置 | 保留方式 | 手册库所需增量 |
|---|---|---|---|
| 保序 DocumentModel、段落/表格/图片关系 | `pipeline/xc975_pipeline/docmodel.py` | 继续作为 Word 抽取中间模型，保留 `src` 溯源 | 在发布模型增加版本、稳定锚点和适用规则，不改解析语义 |
| Section 章节树与 `section_id/seq/parent/面包屑` | `pipeline/xc975_pipeline/schemas.py` | 继续作为目录、阅读和深链核心 | 增加 `edition_id` 作用域、跨版本锚点映射、可选 `block_id` |
| 六种 Block：para/image/table/warning/steps/list | 同上；`products/tree.py` | QML 每种块一个 delegate，未知块不发布 | 为块生成可搜索文本与资源依赖；后续新类型必须升 schema 并审阅 |
| 图片、题注、表格网格与单元格图片 | `docmodel.py`、`images.py`、`products/tree.py` | 继续生成 800px 车端资源和表格结构 | 可保留高分辨率放大版；manifest 记录全部资源和尺寸 |
| 市场/配置/受众/SN/版本元数据 | `docs/project/随车助手-数据抽取规格说明.md` 附录 B.3 | 保留中文展示标签和既有数据 | 增加机器可评估的结构化 VariantProfile，禁止只匹配“国内干桥”等自由字符串 |
| manifest + 逐文件 SHA-256 | `pipeline/xc975_pipeline/package.py`、`schemas.py` | 保留完整性校验和文件清单 | 增加 schema/阅读器兼容、包 ID、依赖、大小、适用规则、版本关系、签名和本地索引 |
| QML TreeView/ListView、图片缩放、横滑表格 | 上述规格 §3.A、§6.4 | 直接复用为离线阅读器 | 增加库首页、搜索结果、下载/更新状态、版本/适用性提示 |
| RAG 语料块含 `section_id`、面包屑、变体 | 上述规格 §3.D | 继续用于在线问答和引用深链 | 从已审核 Edition 派生；不取代确定性全文搜索和本地包 |

## 6. 关键数据模型

以下为**[推导/建议]**，是逻辑模型，不要求把所有 JSON 字段原样存入 MySQL。

### 6.1 内容、版本与变体

| 实体 | 关键字段 | 作用与约束 |
|---|---|---|
| `Manual` / 手册族 | `manual_id`、标题、手册类型、封面、品牌、默认语言、受众、简介 | 表示“这一系列手册”，不随每次改版改变；库首页和详情页使用 |
| `Edition` / 不可变版本 | `edition_id`、`manual_id`、`version_label`、状态、发布日期、生效/失效日期、`supersedes`、变更摘要、内容哈希 | 已发布版本不可原地改写；纠错产生新版本。状态至少含 draft/current/superseded/withdrawn |
| `VariantAxis` | 轴代码、名称、允许值、值别名 | 统一 market/model/axle/control/language/audience 等受控词表，避免自由文本漂移 |
| `VariantProfile` | `profile_id`、结构化轴值、SN 规则、硬件/软件配置、显示名称 | 由 SN/VIN 或用户选择解析；必须能解释“为何适用” |
| `ApplicabilityRule` | 规则 ID、各轴的包含/排除集合、SN 范围/列表、优先级、未知值策略 | 绑定到 Edition、Section 或 Block；复杂规则须可测试、可审核，不能散落在 QML |
| `Section` | 现有字段 + `edition_id`、可选稳定 `anchor_key`、适用规则、审核状态 | `section_id` 至少在 Edition 内唯一；章节号只用于展示和排序辅助，导航仍以 ID/seq |
| `Block` | 现有六种类型 + `block_id`、适用规则、来源 `src` | 封闭集不变；每块可派生搜索文本并定位到页面 |
| `Asset` | `asset_id`、路径、媒体类型、哈希、大小、宽高、题注、替代文本 | 图片/附件/高清图统一管理，被打包和索引引用 |
| `CrossRef` | 源锚点、目标 Edition/Section/Block、关系类型、显示文本 | 支撑相关程序、故障码到章节、保养到手册、版本差异和死链检查 |

**深链建议：** 对外使用包含版本的逻辑地址，例如 `manual/{manual_id}/edition/{edition_id}/section/{section_id}`。另提供“解析当前适用版”的入口，但解析结果必须显示实际版本。若章节改版后编号变化，用 `anchor_key` 或别名表迁移旧链接；不能仅因 `A-2.5.1` 字符相同就假定跨年份语义完全相同。

### 6.2 权限、商业与离线发布

| 实体 | 关键字段 | 作用与约束 |
|---|---|---|
| `ContentLicense` | 内容提供方、允许受众/地区、在线/离线/打印/导出/再分发权利、有效期 | 第三方内容必须显式记录离线权；自有内容也保留统一策略入口 |
| `Entitlement` | 租户/用户/角色/车辆/设备、内容范围、授权来源、起止时间 | 搜索、阅读、下载和包签发使用同一授权判定 |
| `ReleaseChannel` | stable/beta/internal、目标市场、最低阅读器版本、发布时间 | 控制内部审核与正式发布，防止草稿进入车机 |
| `OfflinePackage` | `package_id`、Edition 集合、VariantProfile、schema 版本、全量/增量、依赖、manifest、签名、大小 | 不可变、可校验、可按授权和适用性签发 |
| `DevicePackageState` | 设备、包版本、下载/校验/激活状态、安装时间、上一可用版本、错误码 | 支撑断点续传、失败回滚、更新审计；不把车机临时状态写回内容版本 |
| `UserReadingState`（后续） | 用户、Edition、Section、进度、收藏、批注、设备、同步版本 | 阅读进度与个人内容随版本定位；同步与内容包更新分离 |

### 6.3 manifest 的建议演进

现有字段 `数据包 / 文档 / 适用变体 / 手册版本 / 生成时间 / 文件+sha256 / 规模` 继续保留。建议新增：

```json
{
  "schema_version": "1.0",
  "package_id": "xc975-ev-cn-dry-operator-202608",
  "package_kind": "full",
  "文档": "A",
  "适用变体": "国内干桥",
  "手册版本": "202608",
  "生成时间": "2026-08-01T00:00:00+08:00",
  "edition_ids": ["A-202608"],
  "applicability_rule_ids": ["VAR-CN-DRY-OPERATOR"],
  "minimum_reader_version": "1.0.0",
  "supersedes_package_id": null,
  "文件": [
    {"文件": "tree_A.json", "sha256": "...", "bytes": 123456},
    {"文件": "search_index.db", "sha256": "...", "bytes": 456789},
    {"文件": "img/example.png", "sha256": "...", "bytes": 23456}
  ],
  "规模": {"章节": 159, "故障码": 205, "保养规则": 0},
  "signature": {"key_id": "release-key-1", "algorithm": "...", "value": "..."}
}
```

示例仅说明字段关系，具体文件名和签名算法在实现时确定。`search_index.db` 是可选的本地产物，不要求云端或厂商采用同一种数据库。**SHA-256 只能发现内容变化，不能证明发布者身份；公开分发必须有签名验证。** 签名、schema 兼容和交叉引用检查应在激活前完成。

## 7. 搜索与筛选设计

### 7.1 三类查询不要混成一个黑盒

1. **目录查询**：找手册、车型、语言、受众、版本、主题，返回 Edition/合集。
2. **确定性全文与精确查询**：找章节、故障码、章节号、扭矩、部件、图号/题注、表格单元格，返回可打开的 Section/Block。
3. **在线语义问答**：自然语言问题经 RAGFlow/Agent 检索，回答必须引用 Edition 和 `section_id`，可跳回前两类页面。

全文搜索是手册库的基础能力，RAG 是增量能力。即使 LLM 不可用，前两类与阅读仍应完整工作。

### 7.2 推荐索引单元与字段

| 索引记录 | 主要字段 | 结果展示 |
|---|---|---|
| `CatalogRecord` | 书名、简介、封面、手册类型、品牌、主题、语言、受众、适用变体、版本状态 | 手册卡片、库首页 facets |
| `SectionRecord` | `edition_id`、`section_id`、章节号、标题、面包屑、正文、steps/list/warning、图号/题注、表格文本、适用规则、权限标签 | 标题 + 面包屑 + 高亮摘要 + 版本/变体徽标 |
| `TypedDataRecord` | 故障码、控制器、故障名、保养周期、规格名/值/单位、来源章节 | 类型化结果卡片，点击回原文 |
| `AssetRecord`（可选） | 图号、题注、关联章节、媒体类型 | 图纸/插图结果；OCR 文本只有经过审核才进入 |

**排序原则：** 精确故障码/零件号/章节号优先；其后是标题、面包屑、正文、图题和表格字段的合理加权；再考虑受控同义词。Knovel 官方公开的层级元数据与同义词实践支持这一方向，但本项目权重必须通过自己的查询集调校，不能声称复制其算法。[S-KNOVEL-RANK][S-KNOVEL-SYNONYM]

### 7.3 过滤顺序与安全约束

- 默认上下文为 `当前车辆 + 当前用户权限 + current 版本`；无车辆上下文时才进入全库浏览。
- 权限和适用性应在返回结果及 facet 计数前生效，避免从无权文档的数量、标题或摘要泄露信息。
- `current` 不等于简单取最大日期：还要满足车辆 SN、市场、语言、受众、发布通道和授权。
- 历史版、其他车型和其他语言属于用户显式扩展；扩展后每个结果显示版本和适用范围。
- 变体未知时默认缩小或请求补充，不得为了提高召回率静默删除变体过滤。
- 云端和车端共享字段含义、精确匹配和过滤语义；排名实现可以不同，但同一安全适用性规则必须一致。

### 7.4 中文与技术词检索

**[推导/建议]**

- 建立经过审核的领域词典和同义词：部件全称/简称、故障现象、中英文术语、单位写法、常见错别字；保留原词命中优先级和“已扩展搜索”的可见状态。
- 故障码、SN、章节号、图号、零件号、数值单位走精确字段，不依赖普通中文分词。
- 中文分词或 n-gram 方案必须用真实 A/B/C 手册测试“两字术语、字母数字混合、连字符、上下标、全半角、单位”等，不因某个引擎默认支持中文就直接验收。
- 离线索引宜在发布构建时生成并纳入 manifest，避免每台车机重复构建和版本不一致。若采用 SQLite FTS 等具体方案，先验证目标 Qt/SQLite 驱动、中文 tokenizer、体积和只读部署，不把该选型当成既定前提。

### 7.5 建议搜索 API 语义

```json
{
  "query": "高压 无法上电",
  "vehicle_profile_id": "SN-253913260",
  "manual_types": ["operator", "service"],
  "languages": ["zh-CN"],
  "edition_status": ["current"],
  "content_types": ["section", "fault_code", "table"],
  "page_size": 20
}
```

结果至少返回 `manual_id/edition_id/section_id/block_id`、标题、面包屑、摘要、高亮范围、版本、适用性说明、内容类型和可离线状态。搜索 API 与车端本地结果使用同一深链语义。

## 8. 在线、离线包与云端更新边界

### 8.1 职责划分

| 云端负责 | QML 车机本地负责 |
|---|---|
| 源文档存档、抽取、审核、规范内容库、不可变 Edition | 已安装包的目录、完整章节树和六种 Block 渲染 |
| 全库目录、跨手册搜索、facets、版本与变体解析 | 当前车辆适用手册的本地全文/精确搜索和筛选 |
| 用户/角色/车辆/内容授权，第三方许可控制 | 只接收已授权且适用的包；本地不放宽权限 |
| RAGFlow 在线问答、语义诊断、云端分析 | 故障码、保养规则、手册深链等确定性功能离线运行 |
| 全量/后续增量包构建、签名、发布通道、更新清单 | 下载暂存、哈希/签名/schema/引用校验、原子激活、回滚 |
| 阅读进度/收藏/批注的云同步（后续） | 离线用户数据暂存和恢复联网后同步（后续） |
| 更新提醒、版本撤回、变更摘要和审计 | 显示当前包版本、离线时长、更新/撤回状态；旧包可追溯 |

### 8.2 离线包的内容边界

**必须完整自包含：** manifest、章节树、全部 Block、本地图片/表格资源、内部链接目标、故障码/保养规则、本地搜索索引、适用规则、版本与许可元数据。打开任一已安装章节不得依赖云端补图或补目录。

**默认不包含：** 在线 LLM 回答、实时车辆数据、用户私人云批注、未授权历史版、其他车型资料、可执行脚本或 QML 代码。内容包是数据，不应成为绕过 App 审核的代码更新通道。

### 8.3 更新流程

1. 车机提交设备、App/schema 版本、车辆 VariantProfile、当前包 ID 和授权凭据。
2. 云端返回该通道下“最新且适用且授权”的包描述；没有更新时返回明确的无更新结果。
3. 下载到独立暂存区；支持断点续传，暂存包不参与阅读。
4. 校验文件哈希、发布签名、包依赖、schema/最低阅读器版本、未知 Block、孤儿图片和内部引用。
5. 原子切换到新版本；保留上一个已知可用包，失败继续使用旧版并报告原因。
6. 激活后回传安装状态；用户仍看到实际 Edition 和发布时间，不把“下载成功”误当“内容已激活”。
7. 对安全召回或错误撤回，联网时显著提示；离线期间保留旧版可用性但显示版本信息，具体停用策略由安全与法务规则决定。

**MVP 只做全量包和原子替换。** 待真实包体、更新频率和网络数据明确后再做增量。增量包必须有基线版本、依赖链、最终内容哈希和“自动回退全量包”的路径，不能仅靠文件差分假设一定可拼接。

## 9. MVP 与后续阶段

### 9.1 MVP：可用的多手册库与受控车端离线阅读

**内容范围**

- 用现有 A/B/C 三份手册验证多手册、多受众、国内/EU、干/湿桥和不同版本；B 维修手册是否对普通车主可见由角色权限决定，不在 UI 中硬编码。
- 建立 Manual/Edition/VariantProfile/Entitlement/OfflinePackage 最小模型；现有 `适用变体` 保留显示，新增结构化规则。
- 每份已审核 Edition 产出 tree、图片、表格、故障/规则数据、本地索引和增强 manifest。

**云端与 Web**

- 库首页：手册卡片、车型/配置/语言/受众/版本筛选、手册详情和完整目录。
- Section 级全文搜索，故障码/章节号精确查询，结果高亮并深链到阅读页。
- 当前适用版默认、历史版显式选择；基础用户/角色/车辆授权。
- 全量离线包生成、签名、下载与安装状态接口。

**QML 车机**

- “本车手册”默认页 + “全部已安装手册”库页；目录抽屉、六种 Block、图片缩放、表格横滑。
- 断网冷启动后仍能浏览、搜索、打开图片/表格和跳转故障/保养来源章节。
- 下载/校验/激活/失败回滚；显示包版本与适用范围。

**MVP 明确不做**

- 不迁移全部内容到 DITA/S1000D；不做商城支付、评分推荐、社交批注、复杂增量 OTA；不把在线 RAG 问答作为离线搜索的依赖。

### 9.2 第二阶段：手册库体验与运营效率

- 最近阅读、收藏、下载管理、企业/车型合集、跨设备阅读位置同步。
- 版本变更摘要、Edition/Section 差异、更新提醒、历史版对照。
- 结果按操作程序/规格/故障/图纸/保养分类；受控同义词扩展与搜索分析。
- 真实包体验证后增加增量更新、差分资源复用和灰度发布。
- 用 DITA 试点一个新手册系列，验证 topic 复用、条件发布到相同 Section/Block 协议，而不是另建车端格式。

### 9.3 第三阶段：生态与高级治理

- 第三方内容许可、按车型/手册/订阅权益分发，必要时增加离线租期和设备解绑。
- 离线批注/检查单同步与冲突处理；企业 Playlist/维修合集和开放 Search API。
- 若客户或供应链有明确要求，再引入完整 S1000D CSDB、业务规则和交换流程。
- 对交互电路图、可计算规格表等新增能力，以新 Block 类型和 schema 版本发布，不在现有 JSON 中偷塞 QML 无法识别的数据。

## 10. 验收指标与优先风险

### 10.1 MVP 必须通过的端到端验收

- **完整性**：沿用黄金断言；未知 Block、编号冲突、孤儿图、失效内部引用均为 0；manifest 覆盖所有发布文件和本地索引。
- **适用性**：国内干桥、EU 湿桥、不同 SN 的矩阵测试；任何搜索、目录、RAG 引用和离线包都不得混入不适用内容。
- **搜索**：建立真实查询集，覆盖章节名、正文短语、故障码、图号、表格值、中文同义词、全半角和字母数字混合；每个结果可深链到正确版本和章节。
- **离线**：无网冷启动可读、可查、可看图表；不请求云端图片或目录；本地索引与内容包版本一致。
- **更新**：中断下载、哈希错误、签名错误、schema 不兼容、磁盘不足、激活失败均不破坏旧包；成功后深链和用户阅读位置有明确迁移行为。
- **权限**：无权手册不仅正文不可见，其标题、摘要、facet 计数、搜索建议和包下载也不泄露。
- **可追溯**：问答、故障码和保养规则均能定位到 `edition_id + section_id`；安全相关内容必须经过既定审核门。

### 10.2 需要尽早决定的事项

1. **B 维修手册的受众与车端可见性**：影响权限和包大小，不应等 UI 完成后再决定。
2. **SN 到配置的权威来源**：若 SN 本身不足以区分所有配置，需要车辆档案或用户补选流程。
3. **跨版本深链策略**：章节号变更时如何映射旧问答、收藏和保养引用。
4. **真实包体与高清图预算**：决定 800px/1600px 双资源、存储上限和未来增量策略。
5. **本地中文索引实测**：先验证目标 Qt 环境和真实查询，再锁定具体 FTS 技术。
6. **第三方内容的离线权利**：把许可条款纳入内容接入检查，避免技术先行后无法发布。
7. **撤回与安全更新策略**：旧版离线可用与安全纠错之间需要明确的产品/法务规则。

## 11. 一手来源索引

以下来源均为厂商、平台或标准组织官方页面/文档。链接用于支持对应外部能力，不用于推断其内部技术栈。

### ALLDATA

- [S-ALLDATA-SEARCH] [ALLDATA：Tackling Search Techniques](https://www.alldata.com/us/en/alldata-101)
- [S-ALLDATA-RELEASE] [ALLDATA Product Support：What's New - Repair/Collision](https://www.alldata.com/us/en/support/repair-collision/article/whats-new)
- [S-ALLDATA-DIAGRAM] [ALLDATA Product Support：Viewing Diagrams](https://www.alldata.com/us/en/support/repair-collision/article/viewing-diagrams)
- [S-ALLDATA-MOBILE] [ALLDATA Product Support：Mobile/Diagnostics FAQ（含离线边界）](https://www.alldata.com/us/en/support/diagnostics)

### Mitchell 1 ProDemand

- [S-M1-PRODUCT] [Mitchell 1：ProDemand 官方产品页](https://mitchell1.com/prodemand/)
- [S-M1-SEARCH] [Mitchell 1：ProDemand 1Search Plus 工作流与结果类别](https://mitchell1.com/shopconnection/prodemands-1search-plus-significantly-improves-efficiency-with-targeted-automotive-repair-information-at-your-fingertips/)
- [S-M1-VIN] [Mitchell 1：ProDemand Plate-to-VIN Vehicle Selector](https://mitchell1.com/press/mitchell-1-enhances-prodemand-new-vehicle-selector-feature/)
- [S-M1-WIRING] [Mitchell 1：Interactive Wiring Diagrams](https://mitchell1.com/press/mitchell-1-introduces-interactive-wiring-diagrams-in-latest-software-release/)

### HaynesPro

- [S-HP-PRODUCT] [HaynesPro / Infopro Digital Automotive 官方产品页](https://www.haynespro.com/)
- [S-HP-UI] [HaynesPro WorkshopData 官方入口（VIN/Variant/Engine 等字段）](https://www.workshopdata.com/touch/)
- [S-HP-TERMS] [HaynesPro Red：Technical Terms and Conditions](https://red.haynespro.com/terms.aspx)

### Caterpillar

- [S-CAT-SIS2GO] [Caterpillar：Cat SIS2GO App](https://www.cat.com/en_US/support/maintenance/sis2go-app.html)
- [S-CAT-OFFLINE] [Cat Parts 官方 FAQ（SIS Disconnected 离线说明）](https://parts.cat.com/en/carter/help/faq)

### Knovel / Elsevier

- [S-KNOVEL-WORKS] [Elsevier：How Knovel works](https://www.elsevier.com/en-gb/products/knovel/how-knovel-works)
- [S-KNOVEL-BROWSE] [Elsevier Support：How do I use Knovel Browse?](https://www.elsevier.support/knovel/answer/how-do-i-use-knovel-browse)
- [S-KNOVEL-FACET] [Elsevier Support：How can I refine my search results?](https://www.elsevier.support/knovel/answer/how-can-i-refine-my-search-results)
- [S-KNOVEL-RANK] [Elsevier Support：How does Knovel determine Search relevancy?](https://www.elsevier.support/knovel/answer/how-does-knovel-determine-search-relevancy)
- [S-KNOVEL-SYNONYM] [Elsevier Support：How does Knovel handle synonyms in Search?](https://www.elsevier.support/knovel/answer/how-does-knovel-handle-synonyms-in-search)
- [S-KNOVEL-DOWNLOAD] [Elsevier Support：Can I print or download content sections?](https://www.elsevier.support/knovel/answer/can-i-print-or-download-content-sections)
- [S-KNOVEL-EQUATIONS] [Elsevier Support：What is Knovel Interactive Equations?](https://www.elsevier.support/knovel/answer/what-is-knovel-interactive-equations)
- [S-KNOVEL-MOBILE] [Elsevier Support：Can I access Knovel on my smartphone or tablet?](https://www.elsevier.support/knovel/answer/can-i-access-knovel-on-my-smartphone-or-tablet)
- [S-KNOVEL-MY] [Elsevier Support：What is My Knovel?](https://www.elsevier.support/knovel/answer/what-is-my-knovel)

### Accuris Engineering Workbench

- [S-ACCURIS-PRODUCT] [Accuris：Engineering Workbench 官方产品页](https://accuristech.com/engineering-intelligence/engineering-workbench/)
- [S-ACCURIS-WP] [Accuris 官方白皮书：Engineering Workbench—Next Generation Standards Management](https://brand.accuristech.com/hubfs/Downloads/Engineering%20Workbench%20Overview%20-%20White%20Paper.pdf)
- [S-ACCURIS-MOBILE] [Accuris：EWB Mobile 离线文档、期限、加密与批注同步](https://accuristech.com/blog/the-research-stays-at-the-desk-the-decisions-get-made-in-the-field/)

### ASTM Compass

- [S-ASTM-COMPASS] [ASTM：ASTM Compass 官方产品页](https://www.astm.org/products-services/enterprise-solutions/astm-compass.html)
- [S-ASTM-VOLUME] [ASTM：Online Volume / Compass 格式、版本与订阅说明](https://www.astm.org/products-services/astm-bos-01.02.html)
- [S-ASTM-VIRTUAL] [ASTM：Virtual Volumes Available through Compass](https://www.astm.org/news/virtual-volumes-available-through-compass-so17)

### SAE Mobilus

- [S-SAE-SEARCH] [SAE Mobilus Help：Search and Filters](https://saemobilus.sae.org/help/search-filters)
- [S-SAE-ADVANCED] [SAE Mobilus Help：Advanced Search](https://saemobilus.sae.org/help/advanced-search)
- [S-SAE-DOWNLOAD] [SAE Mobilus Help：Download a Document](https://saemobilus.sae.org/help/download-documents)
- [S-SAE-REDLINE] [SAE Mobilus Help：Compare (Redline) Standards](https://saemobilus.sae.org/help/redline-compare-standards)
- [S-SAE-ANNOTATE] [SAE Mobilus Help：Annotate](https://saemobilus.sae.org/help/annotate-documents)
- [S-SAE-LOGIN] [SAE Mobilus Help：Login (subscription)](https://saemobilus.sae.org/help/login-subscription)

### O'Reilly Learning

- [S-OREILLY-FEATURES] [O'Reilly Support：Features（目录、高亮、Playlist、Search）](https://www.oreilly.com/online-learning/support/features.html)
- [S-OREILLY-APPS] [O'Reilly：Apps—离线下载与设备同步](https://www.oreilly.com/online-learning/apps.html)
- [S-OREILLY-PRICING] [O'Reilly：Online Learning Platform Pricing / 企业与 API 能力](https://www.oreilly.com/online-learning/pricing)
- [S-OREILLY-SSO] [O'Reilly Integration Docs：Single sign-on (SSO)](https://www.oreilly.com/online-learning/integration-docs/using-sso-saml.html)
- [S-OREILLY-SEARCHAPI] [O'Reilly Platform Search API 官方文档](https://www.oreilly.com/online-learning/integration-docs/search.html)

### DITA / OASIS

- [S-DITA-TOPIC] [OASIS DITA 1.3：The topic as the basic unit of information](https://docs.oasis-open.org/dita/dita/v1.3/os/part1-base/archSpec/base/topicdefined.html)
- [S-DITA-BOOKMAP] [OASIS DITA 1.3：Bookmap](https://docs.oasis-open.org/dita/dita/v1.3/os/part2-tech-content/archSpec/technicalContent/dita-spec-intro-bookmap.html)
- [S-DITA-COND] [OASIS DITA 1.3：Conditional processing (profiling)](https://docs.oasis-open.org/dita/dita/v1.3/os/part1-base/archSpec/base/condproc.html)
- [S-DITA-FILTER] [OASIS DITA 1.3：Filtering](https://docs.oasis-open.org/dita/dita/v1.3/os/part1-base/archSpec/base/filtering.html)
- [S-DITA-META] [OASIS DITA 1.3：DITA metadata](https://docs.oasis-open.org/dita/dita/v1.3/os/part1-base/archSpec/base/dita-metadata.html)
- [S-DITA-SPEC] [OASIS DITA 1.3 Technical Content Edition（完整规范入口）](https://docs.oasis-open.org/dita/dita/v1.3/os/part2-tech-content/dita-v1.3-os-part2-tech-content.html)

### S1000D 与 EPUB

- [S-S1000D-ABOUT] [S1000D 官方：About S1000D / Data Module / CSDB](https://s1000d.org/?page_id=101)
- [S-S1000D-DOWNLOAD] [S1000D 官方下载与 Issue 兼容说明](https://users.s1000d.org/)
- [S-EPUB] [W3C：EPUB 3.3](https://www.w3.org/TR/epub-33/)

## 12. 最终推荐一句话

**以现有 DocumentModel/Section/Block/manifest 为内容与车端交付底座，新增“手册族—不可变版本—结构化变体—权限—签名离线包”治理层；云端做全库发现、授权、更新与 RAG，QML 本地做完整目录、全文搜索和图表阅读。先保证正确适配与离线更新闭环，再叠加小说商城式收藏、推荐和跨设备同步。**

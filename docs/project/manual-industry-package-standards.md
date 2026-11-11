# 技术手册阅读包、Edition 与行业标准对照

| | |
|---|---|
| 核对日期 | 2026-11-07 |
| 问题 | 当前自定义 manifest/Edition 是否应改为行业通用规范，以及各规范实际覆盖什么 |
| 外部证据范围 | 仅使用 W3C、OASIS、S1000D 官方站点和 TUF 官方规范；不使用厂商博客或二手解释 |
| 项目证据范围 | 当前 `Manual/Edition/Section/Block/FaultCode/MaintenanceRule` 定义来自本仓库现有规格与代码 |
| 交付性质 | 规范事实核对与项目映射建议；不宣称当前实现已经符合任何外部标准 |

## 0. 结论

1. **应把“阅读出版物”“业务数据”“安全更新元数据”分开。** EPUB 3.3 的 OCF + Package Document（OPF）适合作为手册阅读包的标准交换格式；它不能替代故障注册、保养规则、QML 展示契约或完整的发布治理。
2. **OPF `manifest` 是出版物资源清单，不是逐文件 SHA-256 清单。** OPF `spine` 表达默认阅读顺序，EPUB Navigation Document 的 `toc nav` 表达目录，三者不能混用。OCF 允许通过可选的 `META-INF/signatures.xml` 使用 XML Signature 签署全部或部分容器内容，但这不是 OPF 中内建的逐文件哈希字段，也不是必验的包安全机制。[E1]
3. **DITA map/bookmap 是内容组织与发布引用结构。** `topicref`/`chapter` 组织主题引用，`bookmeta` 保存书籍元数据；它们不是 EPUB 式资源 manifest，也不提供本项目所需的确定性故障或保养执行语义。[D1][D2][D3][D4]
4. **S1000D 的核心是受控数据模块及其全生命周期管理。** 官方概览明确数据模块包含 identification and status 与 contents 两部分，前者覆盖 CSDB 管理、适用性、质量保证和检索控制；CSDB 是数据模块的存放与管理“store”，其具体功能实现并不由 S1000D 规定。[S1]
5. **TUF 是更新安全框架，不是手册目录或内容包格式。** 它用 root、timestamp、snapshot、targets 的分层签名元数据保护更新；targets 文件项具有 `length`、`hashes` 和可选 `custom`。TUF 官方还明确把“定义包格式”和“实际执行更新”列为非目标。[T1]
6. **W3C Web Application Manifest 与内容包无关。** 它是 Web 应用名称、图标、启动 URL、显示模式、导航范围等应用元数据，不应改名为本项目的手册包 manifest。[W1]
7. **没有任何一个上述标准能完整覆盖当前业务数据。** 正确方向不是寻找一个“大一统 Edition XML”，而是由同一权威 Edition 派生标准 EPUB 阅读产物、独立受控的 QML/故障/保养数据产物，再用 TUF 机制保护它们的获取与验证。

### 证据标签

- **[规范]**：后文由相应官方规范或标准组织页面直接支持的事实。
- **[项目]**：对当前仓库模型的只读核对结果。
- **[建议]**：基于规范边界作出的项目设计建议，不是标准强制要求。
- 示例用于准确展示结构。EPUB/DITA 示例依据官方内容模型编写；TUF 大写值为占位符，不是可验证的签名文件；S1000D 不提供未经选定 Issue 和官方 schema 证实的 XML 示例。

## 1. EPUB 3.3：标准阅读容器与出版物结构

官方主规范：[W3C EPUB 3.3 Recommendation](https://www.w3.org/TR/epub-33/)（下文各节号均指此文档）。[E1]

### 1.1 OCF 容器

**[规范]** OCF 是 EPUB 出版物的必需容器技术；交付给阅读系统的最终出版物使用 OCF ZIP 容器。规范区分抽象文件树和 ZIP 物理表示（§4）。[E1]

最小文件布局示例：

```text
manual.epub                         # ZIP 容器
├── mimetype                        # 内容固定为 application/epub+zip
├── META-INF/
│   └── container.xml               # 指向 Package Document
└── EPUB/
    ├── package.opf                 # metadata + manifest + spine
    ├── nav.xhtml                   # EPUB Navigation Document
    ├── text/
    │   ├── safety.xhtml
    │   └── diagnostics.xhtml
    └── images/
        └── controller.png
```

ZIP 的关键约束（§4.3.2）：[E1]

- `mimetype` 必须是 ZIP 中第一个文件；内容是 US-ASCII 的 `application/epub+zip`，不得有 BOM、首尾空白或填充。
- `mimetype` 不得压缩或加密，其 ZIP header 不得包含 extra field。
- `META-INF` 是根目录下的必需目录，`META-INF/container.xml` 必需；`signatures.xml`、`encryption.xml`、`metadata.xml`、`rights.xml` 和 `manifest.xml` 是可选的容器文件。
- `META-INF` 中文件和根目录 `mimetype` 不是 publication resources，不得列入 OPF `manifest`。可选的 `META-INF/manifest.xml` 也不能与 OPF `manifest` 混为一谈。

`META-INF/container.xml` 示例：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0"
           xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/package.opf"
              media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
```

**[规范]** `container` 的 `version="1.0"` 和 `rootfiles` 必需；至少一个 `rootfile`。每个 `rootfile` 的 `full-path` 与 `media-type` 必需，后者固定为 `application/oebps-package+xml`（§4.2.6.3.1）。[E1]

### 1.2 Package Document（OPF）

**[规范]** `package` 是 Package Document 的必需根元素。`version` 与 `unique-identifier` 必需；在 EPUB 3.3 中 `version` 仍为 **`3.0`**，因为 3.x 是同一 EPUB 3 格式的延续。`package` 按顺序恰含一个 `metadata`、一个 `manifest`、一个 `spine`（§5.4）。[E1]

完整最小关系示例：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         version="3.0"
         unique-identifier="pub-id"
         xml:lang="zh-CN">
  <metadata>
    <dc:identifier id="pub-id">urn:uuid:6f1a2f60-3f47-4dd3-a9a2-3ec3d62d1001</dc:identifier>
    <dc:title>XC975-EV 维修保养手册</dc:title>
    <dc:language>zh-CN</dc:language>
    <meta property="dcterms:modified">2026-11-07T00:00:00Z</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml"
          media-type="application/xhtml+xml" properties="nav"/>
    <item id="safety" href="text/safety.xhtml"
          media-type="application/xhtml+xml"/>
    <item id="diagnostics" href="text/diagnostics.xhtml"
          media-type="application/xhtml+xml"/>
    <item id="controller-img" href="images/controller.png"
          media-type="image/png"/>
  </manifest>
  <spine>
    <itemref idref="safety"/>
    <itemref idref="diagnostics"/>
  </spine>
</package>
```

#### metadata：必需字段

**[规范]** 最小必需元数据是（§5.5）：[E1]

- `dc:identifier`：出版物唯一标识；被选为主标识的元素 `id` 必须由 `package/@unique-identifier` 引用。
- `dc:title`：出版物标题。
- `dc:language`：语言。
- 恰好一个出版物级 `meta property="dcterms:modified"`：最后修改时间，格式为 `YYYY-MM-DDThh:mm:ssZ`，必须使用 UTC 和 `Z`。

其他 Dublin Core 和扩展元数据可按规范添加，但不能据此假定通用阅读器理解项目的 `edition_id`、适用性或审核状态。

#### manifest：资源项，不是阅读顺序

**[规范]** `manifest` 至少有一个 `item`。除 Package Document 自身外，它必须列出全部 publication resources，包括容器内和远程资源；Package Document 自身不得列入。每个 `item` 必需 `id`、`href`、`media-type`；`properties`、`media-overlay` 可选，`fallback` 在相应条件下必需（§5.6）。[E1]

- `item` 顺序没有意义；默认展示顺序由 `spine` 决定。
- 必须恰好有一个 `item` 以 `properties="nav"` 声明 EPUB Navigation Document。
- `properties` 还承担 `scripted`、`mathml`、`svg`、`remote-resources` 等资源语义声明；不是任意业务字段包。

#### spine：默认阅读顺序

**[规范]** `spine` 是引用 manifest `item` 的有序列表，至少一个 `itemref`；`itemref/@idref` 必需并指向 manifest 中的内容文档。`linear="yes|no"` 可区分主线内容和辅助内容。Navigation Document 可以但不必须列入 spine（§5.7）。[E1]

因此：

- `manifest` 回答“出版物有哪些资源”；
- `spine` 回答“默认依次阅读哪些内容文档”；
- Navigation Document 回答“目录如何导航到章节或片段”。

### 1.3 EPUB Navigation Document

`EPUB/nav.xhtml` 示例：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      lang="zh-CN" xml:lang="zh-CN">
  <head>
    <title>目录</title>
  </head>
  <body>
    <nav epub:type="toc" id="toc">
      <h1>目录</h1>
      <ol>
        <li><a href="text/safety.xhtml">安全注意事项</a></li>
        <li><a href="text/diagnostics.xhtml">故障诊断</a></li>
      </ol>
    </nav>
  </body>
</html>
```

**[规范]** Navigation Document 是必需的 XHTML Content Document，必须恰好包含一个 `epub:type="toc"` 的 `toc nav`。受约束的 `nav` 可有一个标题，必须有一个 `ol`；`li` 通过 `a` 或分组用的 `span` 以及可选嵌套 `ol` 构成目录层级。`page-list` 和 `landmarks` 可选（§7.1–7.4）。[E1]

### 1.4 是否有标准逐文件 SHA-256 与包签名

| 问题 | 规范结论 |
|---|---|
| OPF `item` 是否有标准 `sha256`/`length` 字段 | **没有。** §5.6 定义的核心字段是 `id`、`href`、`media-type` 及上述条件/可选属性；它不是逐文件完整性清单。 |
| OCF 是否支持数字签名 | **支持但可选。** 可选 `META-INF/signatures.xml` 包含一个或多个 XML Signature `Signature`，可对容器整体或其部分签名，并可签署非 XML 数据（§4.2.6.3.6）。 |
| 是否等于“OPF 自动为每个文件提供 SHA-256” | **不等于。** XML Signature 的 `Manifest`/`Reference` 可引用单独或成组文件并产生摘要；这是签名结构，不是 OPF `item` 的哈希清单。具体算法和信任策略还需另行确定。 |
| 是否保证阅读系统验证签名 | **不保证。** 规范明确提醒阅读系统不必检查签名。因此不能把“存在 signatures.xml”当作本项目激活前的充分安全控制。 |

**[建议]** 如果 EPUB 是正式受控更新对象，应把完整 `.epub` 作为一个 TUF target 验证；不要仅凭 OPF manifest 或 ZIP CRC 判断来源与完整性。若还需包内逐文件诊断/去重，可另设项目内部清单，但不要声称它是 EPUB 3.3 的强制结构。

## 2. DITA 1.3：主题组织、书籍结构与发布引用

官方依据：OASIS DITA 1.3 是 2015-12-17 的 OASIS Standard；Base Edition 定义基础 topic/map，Technical Content Edition 包含 bookmap。[D0]

### 2.1 map 与 topicref

**[规范]** topic 是创作和复用的基本单元；map 通过引用把 topics 组织成发布层级，同一批 topics 可用于多个 maps。`topicref` 可指向 topic 或其他资源，嵌套 `topicref` 可表达导航/目录层级及父子关系。[D1][D2]

```xml
<map id="xc975-service">
  <title>XC975-EV 维修保养手册</title>
  <topicref href="topics/safety.dita">
    <topicref href="topics/high-voltage.dita"/>
  </topicref>
  <topicref href="topics/diagnostics.dita"/>
</map>
```

### 2.2 bookmap、chapter 与 bookmeta

**[规范]** bookmap 是面向书籍发布流程的 map 特化，组织 front matter、parts、chapters、appendices、back matter 等，并提供作者、所有者、版本和生产历史等元数据。`chapter` 是 `map/topicref` 的 bookmap 特化，用于引用作为章的 topic 或 map。`bookmeta` 保存不被视为书籍正文的信息，例如版权、作者和分类。[D3][D4][D5]

```xml
<bookmap id="xc975-service-book">
  <booktitle>
    <mainbooktitle>XC975-EV 维修保养手册</mainbooktitle>
  </booktitle>
  <bookmeta>
    <prodinfo>
      <prodname>XC975-EV</prodname>
      <vrmlist>
        <vrm version="B" release="20260824"/>
      </vrmlist>
    </prodinfo>
  </bookmeta>
  <chapter href="topics/safety.dita"/>
  <chapter href="topics/diagnostics.dita">
    <topicref href="topics/controller-faults.dita"/>
  </chapter>
</bookmap>
```

### 2.3 它不是 EPUB 式资源 manifest

**[规范事实的直接边界]** DITA map/bookmap 的核心是内容引用、组织、导航与发布处理。它不会像 OPF 那样要求以 `id + href + media-type` 穷举出版物资源，也没有对应的 OPF `spine` 或强制 `toc nav` 容器契约。图片、topic、submap、key 等由各自引用机制进入处理流程，不能把一个 map 当成包含 `path/bytes/sha256/signature` 的通用包清单。

**[建议]** 若未来采用 DITA，把它放在创作、复用和条件发布层；由 map/topic 生成本项目 Section/Block 或 EPUB，而不是让 QML 直接解释 bookmap，也不要让 bookmap 承担更新安全元数据。

## 3. S1000D：数据模块、适用性、CSDB 与交换边界

官方概览：[S1000D — About / Principal Concepts](https://s1000d.org/?page_id=101)；官方下载与 Issue 说明：[S1000D Downloads](https://users.s1000d.org/)。[S1][S2]

### 3.1 数据模块的两段结构

**[规范]** Data Module 是可独立存在的信息单元，包含平台、系统或部件的描述、程序或操作数据；可通过 Data Module Code 作为标识从 Common Source Data Base 存取。每个数据模块由两部分组成：[S1]

```text
Data Module
├── identification and status section
└── contents section
```

在本项目讨论的 XML 术语中对应 `identAndStatusSection` 与 `content`。上面的树只表达官方公开概览证实的职责划分，**不是 XML 实例或 schema 断言**。

- identification and status：管理 CSDB 中的数据模块、管理适用性、管理质量保证过程、控制检索过程。
- contents：向用户提供执行任务或描述系统所需的实际信息。
- 官方概览列出的信息类型包括 Crew、Description、Procedural、Fault、Illustrated Parts Data、Schedules、Wiring、Process Module、Business Rules Exchange 等。[S1]

**重要边界：** “S1000D 有适用性管理”不等于本项目现有 `mode/ALL/criteria/on_unknown` JSON 规则就是 S1000D 格式。没有选定 Issue、官方 schema 和项目业务规则，不得宣称字段级兼容或合规。

### 3.2 CSDB 不是现成的阅读包或数据库产品

**[规范]** CSDB 是容纳和管理数据模块的“store”；S1000D 只提出存储与管理要求，**不定义其具体功能实现**。[S1]

因此不能推导出：

- CSDB 必然是某个数据库、Git 仓库或 QML 离线目录；
- 数据模块天然等于一个 Section 或一个 EPUB 文件；
- CSDB 自动提供本项目需要的全文索引、确定性规则引擎、包签名和 OTA 激活。

### 3.3 DDN 与包交换的证据边界

用户提出的 DDN（Data Dispatch Note）应与数据模块正文、CSDB 存储和阅读包目录分开考虑；但在本次可直接读取的 S1000D 官方公开概览中，**没有给出 DDN 的完整定义、XML 内容模型、必填字段、逐文件哈希或签名要求**。官方完整 Issue 套件通过下载页提供，且官方明确不同 major/minor Issue 的兼容和转换规则不同。[S1][S2]

因此本报告有意做到：

- 不编造 `<ddn>`、`identAndStatusSection` 子元素或 DDN XML 示例；
- 不声称 DDN 可替代 OPF manifest、本项目文件清单或 TUF；
- 若供应链要求 DDN 交换，先锁定 S1000D Issue，再依据该 Issue 官方规范正文、schema 和业务规则确认交换对象、状态与责任；
- 在取得这些证据前，只能把 DDN 列为待核实的 S1000D 交换机制，不能将现有 `manifest.json` 改名为 DDN 并宣称标准化。

## 4. TUF：分层签名更新元数据

官方依据：[The Update Framework Specification v1.0.37](https://theupdateframework.github.io/specification/v1.0.37/)（§1、§4）。[T1]

### 4.1 共同外层与公共字段

**[规范]** TUF 签名元数据的共同外层为：

```json
{
  "signed": "ROLE",
  "signatures": [
    {"keyid": "KEYID", "sig": "SIGNATURE"}
  ]
}
```

这里 `"ROLE"` 是结构占位；实际为相应角色的对象。各角色的 `signed` 对象具有 `_type`、`spec_version`、正整数 `version` 和 UTC 到期时间 `expires` 等字段。客户端不得接受过期元数据，也不得以较低版本替换当前已信任元数据。[T1]

### 4.2 root / timestamp / snapshot / targets

以下按官方 §4.3–4.6 展示 `signed` 部分骨架；大写值为占位符，省略号表示重复项，不是可直接发布的 JSON。

**root.json：顶级角色密钥与门限的信任根**

```text
{
  "_type": "root",
  "spec_version": SPEC_VERSION,
  "consistent_snapshot": CONSISTENT_SNAPSHOT,
  "version": VERSION,
  "expires": EXPIRES,
  "keys": { KEYID: KEY, ... },
  "roles": {
    ROLE: { "keyids": [KEYID, ...], "threshold": THRESHOLD },
    ...
  }
}
```

root 指定 root、snapshot、timestamp、targets 的授权密钥及签名门限，并支持顶级密钥更换。`consistent_snapshot` 为兼容旧元数据而可选，新实现应包含。[T1]

**timestamp.json：最新 snapshot 的频繁重签指示**

```text
{
  "_type": "timestamp",
  "spec_version": SPEC_VERSION,
  "version": VERSION,
  "expires": EXPIRES,
  "meta": METAFILES
}
```

timestamp 的 `meta` 必须只描述 `snapshot.json`，用于指示其最新版本；频繁重签缩短客户端无法发现更新干扰的时间窗口。[T1]

**snapshot.json：targets 元数据版本集合**

```text
{
  "_type": "snapshot",
  "spec_version": SPEC_VERSION,
  "version": VERSION,
  "expires": EXPIRES,
  "meta": METAFILES
}
```

snapshot 必须列出顶级 targets 和所有 delegated targets 元数据的版本；这些元数据项的 `length` 与 `hashes` 可选。不要把它与 targets 中实际文件项的必填 `length`/`hashes` 混淆。[T1]

**targets.json：实际目标文件及其校验信息**

```text
{
  "_type": "targets",
  "spec_version": SPEC_VERSION,
  "version": VERSION,
  "expires": EXPIRES,
  "targets": TARGETS,
  ("delegations": DELEGATIONS)
}

TARGETS = {
  TARGETPATH: {
    "length": LENGTH,
    "hashes": HASHES,
    ("custom": CUSTOM)
  },
  ...
}
```

- `TARGETPATH` 是相对于镜像 targets base URL 的文件路径。
- `length` 是目标文件字节数。
- `hashes` 是一个或多个加密哈希的映射，例如 `{"sha256": HASH, ...}`。
- `custom` 是可选对象，对 TUF 框架不透明，可携带应用用于下载决策的版本、依赖、要求等；这些字段的业务含义不是 TUF 标准化的。
- `delegations` 可选，用于把目标签名责任委派给其他角色。[T1]

### 4.3 它为什么不是手册目录

**[规范]** TUF 的范围是保护软件更新系统；其非目标明确包括“不定义 package formats”和“不执行实际应用文件更新”。[T1]

所以：

- `targets` 是受信目标文件集合，不是 Section 树；
- `custom` 是应用扩展点，不是放置整本目录、故障码和保养 AST 的替代数据库；
- TUF 的元数据 `version` 用于更新信任与防回滚，不自动等于内容的 `Edition.version_label`；
- 下载后如何解析 EPUB/JSON、检查引用、原子激活和保留可用旧包，仍是应用职责。

## 5. W3C Web Application Manifest：明确排除

官方依据：[W3C Web Application Manifest](https://www.w3.org/TR/appmanifest/)（当前页面状态为 Working Draft）。[W1]

**[规范]** 它定义 JSON 格式的 Web 应用元数据，例如 `name`、`short_name`、`icons`、`start_url`、`id`、`scope`、`display`、`orientation` 等，供用户代理提供接近原生应用的启动和安装体验；根成员均为可选。[W1]

```json
{
  "name": "Example Web App",
  "short_name": "Example",
  "start_url": "/start.html",
  "display": "standalone",
  "icons": [{"src": "icon.png", "sizes": "192x192", "type": "image/png"}]
}
```

它既不枚举内容包文件，也不表达 Edition、Section、阅读顺序、逐文件 SHA-256 或发布签名。**本项目不应采用 `.webmanifest` 或该 JSON 结构作为手册包 manifest。** 仅在开发可安装 Web 手册应用时，才可另行用它描述应用外壳。

## 6. 综合对比

| 标准 | 主要目的 | 核心结构 | 资源/文件清单 | 阅读顺序与目录 | 完整性/签名 | 不覆盖的关键业务 |
|---|---|---|---|---|---|---|
| **EPUB 3.3** | 数字出版物分发、交换与阅读 | OCF、OPF metadata/manifest/spine、Navigation Document | OPF 穷举 publication resources；无标准逐文件 SHA-256 字段 | spine = 默认顺序；`toc nav` = 目录 | 可选 OCF XML Signature；阅读器不必验证 | 故障精确查询、保养求值、QML delegate、适用规则引擎、更新工作流 |
| **DITA 1.3** | 主题创作、复用、组织和多格式发布 | topic、map/bookmap、topicref/chapter、bookmeta | 引用组织，不是穷举式包 manifest | map 层级用于导航/发布；不是 OPF spine | map/bookmap 不承担包哈希/签名 | 本项目的确定性 FaultCode/MaintenanceRule 执行契约、OTA 安全 |
| **S1000D** | 技术出版物全生命周期的模块化生产与管理 | Data Module、标识与状态、内容、CSDB；完整交换依 Issue | 不能据公开概览视为通用阅读包文件清单 | 数据模块不是 EPUB spine/nav | DDN 等细节须按选定 Issue 核实，本报告不作断言 | 不定义 CSDB 具体实现；不自动提供本项目 JSON 规则与 QML 协议 |
| **TUF v1.0.37** | 安全更新与可信文件获取 | root/timestamp/snapshot/targets、签名与门限 | targets 项含 length/hashes/custom | 无手册阅读顺序或目录 | 是其核心能力 | 不定义内容包格式、目录、规则语义或实际激活 |
| **Web App Manifest** | Web 应用安装/启动体验 | 应用名称、图标、启动与显示元数据 | 不是内容文件清单 | 无 | 不是内容包签名机制 | 与手册内容包无直接关系 |

## 7. 当前领域模型的正确映射

**[项目]** 当前定义中：Manual 是不随改版变化的逻辑手册族；Edition 是不可变内容版本；Section 是 Edition 内层级内容单元；Block 是 Section 内封闭类型的展示/引用单元；FaultCode 由控制器和代码精确定位；MaintenanceRule 把明确触发条件映射为保养操作。依据为 `CONTEXT.md`、`docs/project/manual-domain-data-spec.md` 和 `pipeline/xc975_pipeline/schemas.py`。

映射是**语义对应与导出关系**，不是宣布对象等同或自动合规：

| 当前对象 | EPUB 3.3 | DITA 1.3 | S1000D | TUF | 必须保留的自定义语义 |
|---|---|---|---|---|---|
| **Manual** | 无一对一标准对象；通常是一系列 EPUB 出版物的项目逻辑分组 | 可对应一组相关 maps/bookmaps 的项目集合，但 DITA 不强制该实体 | 不能简单等同于 CSDB 或单个数据模块 | 无对应；target 命名可关联手册族 | `manual_id`、手册类型、受众、跨 Edition 关系 |
| **Edition** | 推荐一个 Edition 导出一个 EPUB publication；OPF 必需标识/标题/语言/修改时间 | 一个具体 map/bookmap 及其 `bookmeta` 可承载版本/生产信息 | 可借数据模块标识、状态和审核思想；Edition 不必等于单个 DM | TUF 元数据 version 不是 Edition；可用 target/custom 辅助选择 | `edition_id`、不可变状态、supersedes、审核、来源、适用性、内容哈希 |
| **Section** | XHTML 内容文档或其片段；由 spine 排序并由 `toc nav` 深链 | topic 是内容单元，topicref/chapter 是发布组织引用 | 满足独立管理与信息类型规则时可映射为 DM；不是逐章节自动等同 | 无目录级对应 | `section_id`、`anchor_key`、层级、seq、适用性、来源 |
| **Block** | 映射为 XHTML 中的段落、表格、图、列表、警告等结构 | 可映射到 `p/table/fig/note/steps` 等内容元素 | 依 DM 信息类型和所选 schema 落到 content 内部 | 无 | 封闭 Block 类型、QML 渲染约束、`block_id`、表格网格、来源 |
| **FaultCode** | 可将人类可读说明发布为 XHTML；OPF 不提供故障注册语义 | 可用 reference/troubleshooting 等内容表达说明，但不等于确定性注册表 | Fault 是官方列出的信息类型；不因此获得当前 controller+code+适用性求值语义 | 可把故障数据文件作为 target，但不解释故障 | 控制器+代码精确键、严重度、动作、歧义/不适用状态、审核与来源 |
| **MaintenanceRule** | 可发布人类可读保养章节；不执行规则 | 可用 task 等内容表达操作；不提供当前 trigger AST 的标准执行语义 | Schedules 是官方列出的信息类型；具体字段仍须按 Issue 核实 | 可把保养数据文件作为 target，但不求值 | INTERVAL/ONE_TIME/CALENDAR/CONDITION/EVENT、单位、EARLIEST、includes、规则求值 |

**结论：** EPUB 覆盖阅读出版物，DITA 覆盖创作与组织，S1000D 覆盖复杂技术信息治理框架，TUF 覆盖更新安全。当前确定性业务数据只能有选择地映射或导出，无法被其中任何一个标准完全覆盖。

## 8. 具体落地建议

### 8.1 手册阅读包：采用 EPUB 3 OCF + OPF，但限定职责

**建议采用。** 对手工阅读和跨工具交换，以 EPUB 3.3 作为标准阅读产物，替代“用自定义 JSON manifest 同时冒充通用阅读包”的设计：

1. 每个不可变 Edition 构建一个 EPUB publication；若确需多 Edition 合集，应显式设计合集导出，不让 `edition_ids` 的含义含混。
2. 严格遵守 OCF ZIP/`mimetype`/`container.xml`、OPF 必需 metadata、完整 manifest、spine 和强制 `toc nav`。
3. Section 转为 XHTML 内容文档或可寻址片段，Block 转为受控 XHTML；保留稳定锚点，使 Web/QML/EPUB 能回到同一 `edition_id + section_id + block_id`。
4. 通用 EPUB 只承诺阅读，不承诺故障精确查询、保养提醒或 QML 原生交互。不要为了塞入业务数据而虚构 OPF 标准属性。
5. 安全更新时把完整 `.epub` 当 target；OCF 可选签名可按互操作需求补充，但不能代替本项目强制验证策略。

### 8.2 QML、故障与保养：独立受控产物，统一来源和发布关联

1. **QML 代码留在应用发布边界。** 内容包不携带可绕过应用审核的 QML/脚本代码。QML 消费的数据投影使用独立、版本化 schema；未知 Block 必须拒绝发布或激活。
2. **QML 阅读投影**可保留目录树、封闭 Block、资源和本地索引，但其 manifest 明确定位为应用数据包描述，不称作 OPF、DITA map、DDN 或 TUF targets。
3. **FaultCode 与 MaintenanceRule 分别成为独立受控产物**，各有 `schema_version`、不可变发布 ID、稳定逻辑 ID、适用性、审核状态、来源引用和确定性验证规则；不要仅作为 EPUB 中一张表或 TUF `custom` 的任意字段。
4. 三者均从同一权威 Edition 派生，并通过 `edition_id/section_id/block_id` 回到证据。可以随同一发布批次原子分发，但仍分别做 schema 与语义校验。
5. 若未来引入 DITA/S1000D，建立显式转换和一致性检查；只有经过所选标准/schema 验证的产物才声明对应标准符合性。

### 8.3 安全更新：参考并优先复用成熟 TUF 实现

1. 把 EPUB、QML 数据包、故障产物、保养产物列为 TUF targets，以 `length` 和 `hashes`（如 SHA-256）保护实际下载字节。
2. 用 root 管理角色密钥和门限；离线保护高价值密钥，按职责分离 targets/snapshot/timestamp，并执行到期、版本和签名验证。可信 root 的初始引导仍须由受控应用/设备 provisioning 完成。
3. `custom` 只放小型下载决策元数据，例如 `package_id`、`edition_id`、schema/最低阅读器版本和适用配置标识；这些字段由本项目自己定义，不冒充 TUF 标准字段，也不取代产物内部完整 schema。
4. 下载到暂存区后，再执行应用级 schema、适用性、引用与未知 Block 检查；随后原子激活并保留已知可用版本。TUF 保护更新元数据和目标文件，但不会替应用完成这些动作。
5. 若暂不引入完整 TUF，也应保留同样的职责分离；一个自签名的自定义 `signature` 字段不能自动获得 TUF 的密钥轮换、门限、过期和防回滚语义。

## 9. 官方来源与证据边界

### 官方 URL

- **[E1]** W3C, [EPUB 3.3](https://www.w3.org/TR/epub-33/)：§4 OCF；§4.2.6.3.1 `container.xml`；§4.2.6.3.6 `signatures.xml`；§4.3.2 ZIP；§5 Package Document；§5.5 metadata；§5.6 manifest；§5.7 spine；§7 Navigation Document。
- **[D0]** OASIS, [DITA 1.3 Part 1: Base Edition](https://docs.oasis-open.org/dita/dita/v1.3/os/part1-base/dita-v1.3-os-part1-base.html) 与 [Part 2: Technical Content Edition](https://docs.oasis-open.org/dita/dita/v1.3/os/part2-tech-content/dita-v1.3-os-part2-tech-content.html)：正式版本和范围。
- **[D1]** OASIS, [The topic as the basic unit of information](https://docs.oasis-open.org/dita/dita/v1.3/os/part1-base/archSpec/base/topicdefined.html)：topic、map 引用和复用。
- **[D2]** OASIS, [`topicref`](https://docs.oasis-open.org/dita/dita/v1.3/os/part1-base/langRef/base/topicref.html)：资源引用和嵌套导航层级。
- **[D3]** OASIS, [Bookmap](https://docs.oasis-open.org/dita/dita/v1.3/os/part2-tech-content/archSpec/technicalContent/dita-spec-intro-bookmap.html)：bookmap 结构和官方示例。
- **[D4]** OASIS, [`chapter`](https://docs.oasis-open.org/dita/dita/v1.3/os/part2-tech-content/langRef/technicalContent/chapter.html)：chapter 是 topicref 特化并引用章内容。
- **[D5]** OASIS, [`bookmeta`](https://docs.oasis-open.org/dita/dita/v1.3/os/part2-tech-content/langRef/technicalContent/bookmeta.html)：书籍非正文元数据。
- **[S1]** S1000D Council/Steering Committee, [About S1000D / Principal Concepts](https://s1000d.org/?page_id=101)：Data Module、两部分结构、适用性、信息类型和 CSDB 边界。
- **[S2]** S1000D 官方, [Downloads / Issue Numbers](https://users.s1000d.org/)：规范与 schema 套件入口、Issue 和兼容说明。
- **[T1]** The Update Framework, [TUF Specification v1.0.37](https://theupdateframework.github.io/specification/v1.0.37/)：§1 scope/non-goals；§4.2 通用格式；§4.3 root；§4.4 snapshot；§4.5 targets；§4.6 timestamp。
- **[W1]** W3C, [Web Application Manifest](https://www.w3.org/TR/appmanifest/)：应用元数据范围、成员和当前 Working Draft 状态。

### 不得越过的解释边界

1. 本报告只证明上述规范在其自身范围内的格式和职责；“映射”不表示当前项目已经通过 EPUBCheck、DITA 处理器、S1000D schema/BREX 或 TUF 客户端一致性测试。
2. EPUB 示例展示最小核心关系，不包含正文 XHTML、样式及所有可访问性/内容要求；实际发布仍需完整一致性验证。
3. S1000D 公开概览不足以支持 DDN XML 或数据模块完整必填字段示例；本报告因此明确留空，而不是从其他版本、第三方培训材料或记忆拼接。
4. TUF 骨架省略真实密钥和签名；不可把占位文本直接用于发布。采用时还应落实官方详细客户端工作流和具体实现的 POUF，而不只是生成四个 JSON 文件。
5. Web App Manifest 的排除仅针对“内容包格式”用途；它仍可独立用于可安装 Web 应用外壳。

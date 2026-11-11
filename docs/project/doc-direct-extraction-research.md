# Legacy Microsoft Word `.doc` 直接提取方案调研

| | |
|---|---|
| 调研日期 | 2026-11-07 |
| 目标 | 评估不生成中间 `.docx`、直接读取二进制 `.doc`，并转换为车载屏电子手册的可行性 |
| 范围 | Word COM/Interop、LibreOffice UNO、olefile + MS-DOC、antiword、catdoc、wvWare、Apache POI HWPF、Apache Tika；补充商业方案 Aspose.Words |
| 证据原则 | 采用标准规范、官方文档、官方 API 文档或上游源码所附文档；不以博客作为结论依据 |
| 本次交付 | 仅方案调研，不修改现有转换代码 |

## 1. 结论摘要

**直接读取 `.doc` 可行，但“提取文本”和“生成完整结构化手册”不是同一个问题。**

1. 只要目标是搜索或语料入库所需的纯文本，Tika/HWPF、antiword、catdoc、wvWare 都可承担一定工作；其中 catdoc 明确以纯文本为目标，Tika 的 `.doc` 支持则建立在 POI 之上。[S-CATDOC-MAN][S-TIKA-FORMATS]
2. 车载屏电子手册至少需要标题树、正文与表格/图片的混合顺序、图片文件、目录与内部链接、文本框内容以及可追溯页码。纯文本输出不能证明这些结构已被保留。CFB/MS-DOC 只规定二进制存储与语义结构，不会替应用完成分页、字体替换和绘图布局。[S-MSDOC][S-MSDOC-TEXT][S-MSODRAW]
3. **若坚持开源直读，LibreOffice UNO 是最值得验证的方案**：它可直接载入 `.doc`，并从同一个 Writer 文档模型取得段落样式、表格、图形、书签、目录和文本框；但它仍使用 LibreOffice 的 Word 导入过滤器，只是省略了 `.docx` 序列化文件，并不意味着换了一个更高保真的解析器。[S-UNO-FILTER][S-UNO-LOADER][S-UNO-DOC]
4. **Word COM/Interop 的对象模型最贴近 Word 原文，且能查询 Word 实际分页**，但仅限安装 Word 的 Windows 环境；微软明确不建议、也不支持无人值守/服务端 Office 自动化，存在对话框卡死、非重入、并发与安全问题。[S-WORD-INFO][S-WORD-SERVER]
5. **不建议自研 olefile + MS-DOC 全量解析器**。olefile 只解决 CFB 容器读写；仅取出正文就要实现 FIB、Table Stream、Clx/Pcdt/PlcPcd 和压缩/Unicode piece 解码，标题、表格、域、文本框和绘图还需更多 MS-DOC/MS-ODRAW 逻辑。[S-OLEFILE][S-MSDOC-TEXT][S-MSODRAW]
6. **不建议把 antiword、catdoc、wvWare 或 Tika 默认输出作为完整手册主链**。antiword 自身手册称功能不完整且图片位置可能错误；wvWare 官方明确废弃除 `wvSummary` 外的命令行工具，并称当前框架无法实现 TOC；Tika 继承 HWPF 的能力边界。[S-ANTIWORD-MAN][S-WV][S-TIKA-FORMATS]
7. **对本项目的默认建议是保留现有 `.doc → .docx` 主链和 Word → PDF 预览链**，把时间盒 PoC 用于验证 UNO 直读是否确实减少信息损失或运维问题。如果没有可量化收益，就停止直读改造，而不是长期维护两套语义抽取器。

## 2. 先定义交付层级：文本不等于结构化手册

### 2.1 L0：可检索文本

输出正文字符串、必要的字符集转换和基本段落边界即可。catdoc 的官方说明明确把目标限定为纯文本，并只保留非常有限的表格分隔信息；POI `WordExtractor` 和 Tika facade 也提供这一层的便捷入口。[S-CATDOC][S-POI-EXTRACTOR][S-TIKA-EXAMPLES]

这一层适合搜索索引、粗切片或交叉校验，**不足以直接驱动车载屏手册页面**。

### 2.2 L1：完整逻辑结构手册

本项目应把“完整结构化手册”定义为至少具备：

- 正文段落、标题样式和可靠的大纲层级；
- 表格行列、单元格内容及合并关系；
- 行内/浮动图片、图片字节、题注及其与章节的归属；
- 正文、表格、图片、列表、警告等块的确定顺序；
- 目录条目、书签、超链接或字段结果到正文目标的映射；
- 文本框、页眉页脚、脚注等非主文档流内容的显式归属；
- 源文件、源元素和原文页码的可追溯性；
- 对缺失、重复、乱码和无法识别对象的确定性质检。

UNO 和 Word 对象模型提供这些对象的多类访问入口，但“存在 API”不等于导入后每个复杂对象都自动形成正确的阅读顺序；例如 Word 的 `Document.Content` 只代表主文档流，`Shapes` 是另一集合，UNO 的文本框也由独立 supplier 暴露。[S-WORD-CONTENT][S-WORD-SHAPES][S-UNO-DOC]

### 2.3 L2：原始版面、页码与坐标

页码、换行、浮动对象位置和坐标是**排版结果**，不是纯文本的自然属性。Word 可通过 `Range.Information` 查询页码和页面相对位置；UNO 可用页游标查询页码；Aspose 则通过布局收集器把节点映射到页面。[S-WORD-INFO][S-UNO-PAGE][S-ASPOSE-LAYOUT]

对于会重排到车载屏的电子手册，建议将 **L1 作为内容主模型，L2 作为原文对照和质检证据**。不要为了追求原纸面绝对坐标而牺牲屏幕端的重排能力；现有 PDF 预览已经适合作为 L2 基准。

## 3. 本项目现状与“绕过转换”的实际含义

- `pipeline/xc975_pipeline/convert.py:16` 当前先定位 LibreOffice，执行 `.doc → .docx`；没有 LibreOffice 时才在 Windows 上回退 Word COM，并校验产物 ZIP/OOXML 文件头。
- `pipeline/xc975_pipeline/preview.py:41` 当前由 LibreOffice 将 Word 转为 PDF；`preview.py:66` 再把结构化元素映射到 PDF 页码与区域。
- 因此，现状的主要优点不是“.docx 这个后缀”，而是**复用 LibreOffice/Word 的完整导入器，再复用成熟的 OOXML 下游模型，并保留独立 PDF 版面证据**。

“直接读取”应进一步区分：

1. **不落地中间 `.docx`**：UNO、COM、HWPF、Aspose 都能做到；
2. **不做任何格式导入/内部模型转换**：UNO、COM 做不到，它们仍须把二进制格式导入各自的文档模型；LibreOffice 官方过滤器配置明确将 `MS Word 97` 映射为 `com.sun.star.text.TextDocument`。[S-UNO-FILTER]
3. **完全不依赖办公软件**：HWPF/Tika、antiword/catdoc/wvWare、自研解析器和 Aspose 可做到，但各自牺牲布局、保真度、维护性或成本。[S-POI][S-WV][S-ASPOSE-SYSTEM]

### 3.1 本次真实 `.doc` 样本实测

除官方资料外，本次还对项目现有 B 维修手册 `.doc` 做了本地只读验证；未修改或另存源文件：

- 源文件头为 `D0 CF 11 E0 A1 B1 1A E1`，符合普通 OLE/CFB 文件入口。
- 项目已有依赖 Tika 2.6.0 直接读取成功：默认文本输出约 100442 个字符、5218 个非空行；启用 `xmlContent=True` 后，XHTML 中含 70 个 `<table>`、366 个使用 `embedded:` 地址的 `<img>`，以及正文、题注、目录和标题等中文段落 class。
- Tika 结果只有 42 个 `<h1>`，其他标题仍主要以带样式的 `<p>` 表达；因此不能只用 HTML 标题标签建树，必须继续解析段落样式。XHTML 还包含嵌入式对象产生的附加内容，需要容错 HTML 解析和主文档范围控制。
- Windows Word COM 以 `ReadOnly=True` 直接打开成功，可访问 70 张表、325 个 InlineShape、374 个 Shape、1 个 TablesOfContents 对象；按 `OutlineLevel` 可取得 6 个一级、29 个二级、96 个三级、79 个四级段落，其中三级/四级还混有“副标题”和“无间隙1”等样式，不能仅按样式名过滤。
- 两类工具的对象计数口径不同，不能直接据数量判定完整性；对象可访问也不代表阅读顺序、图片字节导出、目录深链和原页码已经解决。

实测使 Tika XHTML 成为可继续验证的跨平台直读候选，但不改变后文对目录关联和 L2 版面能力的限制；Word COM 则证明当前 Windows/Word 环境可取得较完整的对象模型。

## 4. 方案逐项评估

### 4.1 Windows Word COM / Interop

**工作方式**：用 `Documents.Open(..., ReadOnly:=True)` 打开源 `.doc`，不调用 `SaveAs2`，通过 Word 对象模型读取 Range、Paragraph、Table、Shape、域和书签。

- **正文与标题**：`Document.Content` 返回主文档流 Range；`Paragraph.Style` 可读取样式，应结合内建样式/大纲级别而非只匹配本地化的“标题 1”名称。[S-WORD-CONTENT][S-WORD-STYLE]
- **表格、图片**：`Document.Tables`、`InlineShapes`、`Shapes` 分别覆盖表格、行内对象和浮动对象；`Shapes` 可包含图片、绘图、OLE、ActiveX 和文本对象。主文档的 `Shapes` 不包含页眉页脚中的 Shape，完整提取必须遍历相应 story。[S-WORD-TABLES][S-WORD-INLINE][S-WORD-SHAPES]
- **目录/书签**：`TablesOfContents` 和 `Bookmarks` 是直接对象入口；目录页码是否需要更新应由提取策略固定并记录，避免无意改写源文件。[S-WORD-TOC][S-WORD-BOOKMARKS]
- **文本框/浮动对象**：可经 `Shapes` 和 `StoryRanges` 取得，但对象枚举、锚点和视觉顺序需要本项目另行归一化；不能只读 `Content.Text`。[S-WORD-CONTENT][S-WORD-SHAPES]
- **版面/页码**：`Range.Information(wdActiveEndPageNumber)` 可返回页码，也有页面相对坐标；部分坐标在对象不可见时返回 `-1`，不能把它当成无条件的几何 API。[S-WORD-INFO]
- **图片工程风险**：对象可枚举不代表有统一的“原始图片字节”属性；图片导出、OLE 对象和组合图形需要单独设计与样本验证。

**运维结论**：适合 Windows 桌面、交互账户下的受控批处理，或作为疑难文档的权威对照。微软说明 Office 假定交互桌面和用户配置，且是非重入 STA 自动化服务器；无人值守场景可能死锁，故不应把它扩展成高并发生产服务。Office 许可也不能按普通免费解析库处理。[S-WORD-SERVER]

### 4.2 LibreOffice UNO 直接打开并读取 `.doc`

**工作方式**：通过 `XComponentLoader.loadComponentFromURL` 以 ReadOnly/Hidden 参数载入文档，取得 `TextDocument`，不调用 `storeToURL` 生成 `.docx`。[S-UNO-LOADER]

- **正文、标题**：`XTextDocument.getText()` 提供正文入口；段落属性含 `ParaStyleName` 和 `OutlineLevel`，后者可辅助避免依赖标题名称。[S-UNO-DOC][S-UNO-PARA]
- **表格、图片、目录/书签**：`TextDocument` 直接继承 `XTextTablesSupplier`、`XTextGraphicObjectsSupplier`、`XBookmarksSupplier`、`XDocumentIndexesSupplier`、`XTextFieldsSupplier` 等接口。[S-UNO-DOC]
- **文本框/浮动对象**：`XTextFramesSupplier` 暴露文本框；TextFrame 可读取内部 Text、锚点、尺寸与位置，TextGraphicObject 可取得 `XGraphic`、裁剪、环绕、锚点和几何属性。[S-UNO-FRAME][S-UNO-GRAPHIC]
- **版面/页码**：`XPageCursor.getPage()` 可返回页游标所在页；但将任意段落、表格和浮动对象映射到页码/坐标仍需控制视图游标、触发布局并处理跨页元素。现有 PDF 页映射应保留为对照，不宜在 PoC 前假定 UNO 游标能完全替代它。[S-UNO-PAGE]

**核心 tradeoff**：UNO 省略的是中间文件和 OOXML 二次解析，不是 LibreOffice 的 `.doc` 导入过程。因此它可能减少 `.docx` 写出时的信息损失，却不会自动改善 LibreOffice 对原文的导入保真度；相反，本项目需要新写一套 UNO → 规范块模型的适配器。[S-UNO-FILTER][S-UNO-DOC]

**部署与许可**：跨 Windows/Linux/macOS 的 LibreOffice 路线无需 Microsoft Word，但需管理 LibreOffice 进程、UNO 绑定、用户 profile、超时和资源回收。LibreOffice 主体按 MPL 2.0 发布，同时包含其他开源许可组件，分发时应保留安装包内完整许可信息。[S-LO-LICENSE]

### 4.3 纯 Python：olefile/CFB + 自研 MS-DOC 二进制解析

**实际边界**：CFB 是文件内部的类文件系统容器；MS-DOC 才定义 Word 文档语义。olefile 官方定位是解析、读写 OLE2/CFB，不是 Word 段落、样式或布局引擎。[S-MSCFB][S-OLEFILE]

仅正文提取的规范算法就包括：

1. 从 `WordDocument` Stream 偏移 0 读取 FIB；
2. 由 `fcClx/lcbClx` 在 Table Stream 找到 Clx；
3. 经 `Pcdt → PlcPcd → Pcd` 定位文本 piece；
4. 按 `FcCompressed.fCompressed` 分别解码 16-bit Unicode 或 8-bit ANSI。[S-MSDOC-TEXT]

达到 L1 还需继续实现段落/字符属性与样式表、表格标记、字段和书签、多个 story、Data Stream 图片以及 Office Drawing 对象；绘图还涉及独立的 MS-ODRAW 规范。[S-MSDOC][S-MSODRAW] L2 则还需字体度量、分行分页、环绕与浮动对象布局，远超“用 olefile 读几个 Stream”。

**维护与许可**：olefile 0.47 文档采用带署名/免责声明的 BSD 风格许可，并含 PIL 来源许可通知；这对本项目较友好，但只覆盖容器库，不降低自研 Word 语义层的成本。[S-OLEFILE-LICENSE]

**结论**：可以将 olefile 用于文件类型识别、Stream 检查、诊断或极小范围文本实验；不建议自行建设生产级完整 `.doc` 解析器。主要风险是规范覆盖不全、畸形/快速保存文档兼容、长期测试样本负担和静默丢内容。

### 4.4 antiword

上游 0.37 源码所附手册支持文本、带简单字符格式的文本、DocBook XML、PostScript/PDF，也提供图片输出等级；但同一手册明确写道“far from complete”、许多图片不能显示、部分图片位置错误。[S-ANTIWORD-MAN]

因此它可用于类 Unix 环境的应急文本抽取或独立对照，不能把 DocBook/PostScript 输出等同于完整标题树、表格、目录、浮动对象和 Word 页码。0.37 README 标注版本日期为 2005-10-21，手册为 2005-10-29，应按遗留 C 工具评估维护和安全隔离成本；许可为 GPL-2.0-or-later。[S-ANTIWORD-README][S-ANTIWORD-MAN]

### 4.5 catdoc

catdoc 作者文档明确说明：输出纯文本，只有初步表格处理，不保留 Word 字符格式；手册还列出快速保存处理不正确、脚注位置简化、无法区分空单元格与行尾等限制。[S-CATDOC][S-CATDOC-MAN]

作者站当前列出 0.95、源码和 Git 仓库，许可为 GNU GPL；同时明确“不支持 Windows”，主要平台为 Unix 和 MS-DOS。其字符集配置能力有价值，但不满足 L1/L2，且对本项目 Windows 现状还需额外移植/运行环境。[S-CATDOC]

### 4.6 wvWare / wv library

wv 项目站称库可解析 Word 2000/97/95/6，配套工具可输出 HTML、文本、LaTeX、PS、PDF 等；Windows 依赖外部移植，主体是跨平台 C 库及命令行工具。[S-WV]

最关键的一手限制是项目官方声明：

- 除 `wvSummary` 外，工具均应视为废弃并改用 AbiWord；
- 当前框架无法实现 TOC，且没有重新设计框架的计划；
- 不再接受这些工具的 bug 报告或功能请求；
- wv 库本身未被声明废弃，但若直接嵌入库，本项目仍需自行承担 C 集成和语义归一化。[S-WV]

项目站标明 GPL 许可。wvWare 比纯文本工具覆盖更多转换输出，但上述维护和 TOC 限制使其不适合新建完整手册主链。[S-WV]

### 4.7 Apache POI HWPF

HWPF 是纯 Java 的 `.doc` 解析器。官方把它描述为“moderately functional”：文本提取强，其他场景可能有限或不完整；组件总览仍称 HWPF 处于早期阶段，HWPF 页面还明确说缺少专门维护者。[S-POI][S-POI-COMPONENTS]

可用 API 覆盖比老式文本工具更广：

- `WordExtractor` 提供段落文本、主文本框文本等；`HWPFDocument` 可访问主文档、页眉页脚、文本框、Fields 和 Bookmarks；[S-POI-EXTRACTOR][S-POI-DOC]
- `Paragraph.getStyleIndex()`、`getLvl()` 等可恢复标题/大纲信息；[S-POI-PARAGRAPH]
- `TableIterator` 和 Table/Row/Cell 模型可提取表格；[S-POI-TABLE]
- `PicturesTable` 能从 Data Stream 提取图片，官方建议扫描 character runs，因为并非所有文档都把全部图片按理想方式连续存放。[S-POI-PICTURES]

**限制**：字段和书签存在 API 不等于已有完整 TOC 深链算法；主文本框 Range 独立存在也不等于自动恢复浮动阅读顺序。HWPF 没有 Word/Writer 那样的分页布局结果，不能单独满足 L2。[S-POI-DOC]

**适用判断**：若团队接受 JVM，且目标是 L0/L1 的有限直读，HWPF 是比自研 Python 解析器更合理的开源起点；但复杂表格、浮动对象、域和异常样本必须实测。POI 使用 Apache License 2.0，当前组件依赖包括 `poi-scratchpad` 和 Java 运行时。[S-APACHE-LICENSE][S-POI-COMPONENTS]

### 4.8 Apache Tika

Tika 官方格式页明确说明 `OfficeParser` 使用 Apache POI 处理 OLE2/OOXML；所以 **Tika 是统一提取接口，不是另一套独立 `.doc` 格式引擎**。[S-TIKA-FORMATS]

其优势是接入简单：`AutoDetectParser` 可输出纯文本，`ToXMLContentHandler` 可输出 XHTML；`OfficeParser` 另有 shape-based content 开关。[S-TIKA-EXAMPLES][S-TIKA-OFFICE] 但 XHTML 中有什么结构仍受 HWPF/OfficeParser 限制，不能据此承诺目录深链、图片空间关系或原页码。

Tika 适合作为文本/元数据基线、交叉校验器或已有 Java/Tika 设施中的统一入口，不适合作为完整结构化手册的唯一来源。它使用 Apache License 2.0，依赖 JVM/Tika 组件及其 POI 传递依赖。[S-APACHE-LICENSE][S-TIKA-FORMATS]

### 4.9 补充：Aspose.Words（商业直读对照）

Aspose.Words 官方格式表支持直接 Load DOC，并可导出 HTML、PDF、固定版面和图片；`LayoutCollector` 能把段落、Run、表格单元格等节点映射到起止页。[S-ASPOSE-FORMATS][S-ASPOSE-LAYOUT]

其 .NET 版本不要求安装 Microsoft Word，支持 Windows、Linux、macOS 和多个 .NET 运行时。[S-ASPOSE-SYSTEM] 这使其成为“单一商业 SDK 同时覆盖 DOM 与布局”的有效对照方案，但不应未经样本测试就假定与 Microsoft Word 完全一致。

主要 tradeoff 是商业许可、按开发者/部署位置/OEM/SDK 等模式核算的成本，以及供应商依赖；生产使用需购买相应许可。[S-ASPOSE-LICENSE]

## 5. 内容能力对比

符号含义：`●` 有较直接对象/API；`◐` 部分覆盖或需较多自定义/实测；`—` 无可靠支持或并非项目目标。表中“支持”均不表示对任意复杂 `.doc` 保证无损。

| 方案 | 正文 | 标题样式/层级 | 表格 | 图片 | 目录/书签 | 文本框/浮动对象 | 原版面/页码 | 主要证据 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Word COM/Interop | ● | ● | ● | ● 对象；导出需实现 | ● | ●，需遍历 story/锚点 | ●，Word 布局；部分坐标受可见性影响 | [S-WORD-CONTENT][S-WORD-INFO] |
| LibreOffice UNO | ● | ● | ● | ● `XGraphic` | ● | ●，Frame/Shape/Anchor | ◐，页游标可用；复杂映射需验证 | [S-UNO-DOC][S-UNO-PAGE] |
| olefile + 自研 MS-DOC | ◐ | ◐ 自研 | ◐ 自研 | ◐ 自研 | ◐ 自研 | ◐ 自研 | —，需另建布局引擎 | [S-OLEFILE][S-MSDOC-TEXT][S-MSODRAW] |
| antiword | ● | ◐，DocBook 不等于可靠大纲 | ◐ | ◐，官方称缺图/错位 | — | ◐，无完整性保证 | ◐，PS/PDF 是自身排版而非 Word 保真 | [S-ANTIWORD-MAN] |
| catdoc | ● | — | ◐，初步且有已知边界 | — | — | — | — | [S-CATDOC-MAN] |
| wvWare | ● | ◐ | ◐ | ◐，可产生图形输出 | —，官方称 TOC 无法实现 | ◐ | ◐，转换器布局 | [S-WV] |
| Apache POI HWPF | ● | ● | ● | ● | ◐，Fields/Bookmarks 需自行组合 | ◐，有独立 Textbox Range | — | [S-POI-DOC][S-POI-PICTURES] |
| Apache Tika | ● | ◐，经 XHTML/HWPF | ◐ | ◐，需配置嵌入式提取并验证关联 | ◐，不宜承诺深链 | ◐，可含 shape 文本但无完整几何 | — | [S-TIKA-FORMATS][S-TIKA-OFFICE] |
| Aspose.Words | ● | ● | ● | ● | ● | ● | ●，LayoutCollector/固定版面 | [S-ASPOSE-FORMATS][S-ASPOSE-LAYOUT] |

**对车载屏最重要的差异**是：UNO/COM/Aspose 同时提供内容对象和某种布局能力；HWPF/Tika 主要提供逻辑内容；catdoc 只提供文本。任何只有整段字符串的输出，都需要额外重建标题、表格、图片和链接，不能视为绕过转换后的等价替代。

## 6. 平台、维护、许可与工程风险对比

| 方案 | Windows / 跨平台 | 维护状态（截至调研日的一手证据） | 许可证 | 主要依赖与工程风险 |
|---|---|---|---|---|
| Word COM/Interop | 仅 Windows + 已安装 Word | Word 产品持续演进，但服务端自动化不受微软支持 | Microsoft Office 商业许可 | 交互桌面、STA、非重入；并发/死锁/宏安全；版本与字体环境 [S-WORD-SERVER] |
| LibreOffice UNO | Windows/Linux/macOS | 官方 API 与 core 源码持续演进 | MPL 2.0 为主，含其他开源组件 | LibreOffice + UNO/Python 绑定；进程生命周期、profile、导入保真 [S-LO-LICENSE][S-UNO-FILTER] |
| olefile + 自研 | 纯 Python，跨平台 | olefile 0.47 有正式文档；Word 语义层由本项目自行维护 | BSD 风格 + PIL 通知 | 规范实现量最大；兼容、畸形输入、静默丢内容、测试负担 [S-OLEFILE][S-OLEFILE-LICENSE] |
| antiword | 源码以 Unix 为主，有其他移植；Windows 需单独验证 | 上游 0.37/README/手册停留在 2005，按遗留工具管理 | GPL-2.0-or-later | C 构建、字符映射、可选 PS/Ghostscript；官方自述不完整 [S-ANTIWORD-MAN][S-ANTIWORD-README] |
| catdoc | 官方明确不支持 Windows；Unix/MS-DOS | 作者站列 0.95 和 Git，但功能目标仍是纯文本 | GNU GPL | C 构建、字符集文件；快速保存和表格已知缺陷 [S-CATDOC][S-CATDOC-MAN] |
| wvWare | 多种 Unix；Windows 依赖外部移植 | 库未被官方声明废弃；除 `wvSummary` 外工具已废弃且拒收工具 bug | GPL（项目站） | C 库及 libgsf/libxml2/glib 等历史依赖；TOC 框架限制 [S-WV] |
| Apache POI HWPF | JVM 跨平台 | POI 项目活跃，但官方称 HWPF 早期、缺专门维护者 | Apache-2.0 | Java 17（当前 POI 组件说明）、`poi-scratchpad` 及依赖；复杂结构需低层补丁 [S-POI][S-POI-COMPONENTS] |
| Apache Tika | JVM/Tika Server 跨平台 | 本次核验到官方 3.2.3 文档；底层继承 HWPF 状态 | Apache-2.0 | Java/Tika/POI 依赖；便利接口不改变底层结构缺口 [S-TIKA-FORMATS] |
| Aspose.Words | .NET 跨 Windows/Linux/macOS，无 Word 依赖 | 商业产品，官方系统要求覆盖到当前 .NET | 商业专有许可 | 采购/部署/OEM 许可、供应商锁定、字体与保真度基准测试 [S-ASPOSE-SYSTEM][S-ASPOSE-LICENSE] |

许可行只用于技术选型初筛，不替代法务对实际分发方式的审核。尤其 GPL 工具若以独立进程使用、修改后分发或链接成库，义务判断并不相同；应保留具体版本的许可证文本并让法务确认。

## 7. 推荐路线与不建议路线

### 7.1 推荐路线

**主推荐：保留现有转换链作为生产默认，UNO 直读作为有时间盒的候选优化。**

理由：现有链已经复用 LibreOffice 的 `.doc` 导入器，并有 OOXML 明文校验和 PDF 页码映射。UNO 虽能省略中间 `.docx`，但仍走同一个 `MS Word 97` 导入过滤器；只有实证证明它减少了写出损失、提升对象恢复率或降低故障，才值得替换现有下游。[S-UNO-FILTER]

建议优先级：

1. **默认生产**：LibreOffice `.doc → .docx` + 现有结构化抽取 + LibreOffice PDF 预览；Word COM 只作受控 Windows 回退。
2. **直读 PoC 首选**：UNO ReadOnly/Hidden 打开 `.doc`，直接生成与当前相同的规范 JSON 块和图片目录，不改车端数据协议。
3. **Word 保真对照**：若业务要求“页码必须与指定 Word 版本一致”，在交互式 Windows 工作站用 COM 产生对照数据，不将其扩展成无人值守服务。[S-WORD-SERVER]
4. **无办公套件的开源备选**：仅在 UNO 不可用且 JVM 可接受时评估 HWPF；Tika 用于文本基线，而非完整结构承诺。[S-POI][S-TIKA-FORMATS]
5. **商业备选**：若采购可接受，可用 Aspose.Words 与 UNO/现有链做同样基准，特别比较 DOM + 页码的一体化收益；不能仅凭功能表判定胜利。[S-ASPOSE-LAYOUT]

### 7.2 不建议路线

- **不建议 olefile + 自研 MS-DOC 作为生产主链**：投入和长期责任接近维护一个文件格式引擎，且仍需另做布局。[S-MSDOC-TEXT][S-MSODRAW]
- **不建议 antiword/catdoc/wvWare 作为完整手册主链**：分别存在官方自述的图片/完整性缺陷、纯文本边界、工具废弃和 TOC 限制。[S-ANTIWORD-MAN][S-CATDOC-MAN][S-WV]
- **不建议把 Tika 的 XHTML 当成完整结构保证**：它底层使用 POI，输出方便不等于对象关系完整。[S-TIKA-FORMATS]
- **不建议以服务池方式并发驱动 Word COM**：微软明确指出非重入、全局资源和死锁风险。[S-WORD-SERVER]
- **不建议为“直接读取”永久并行保留多套语义适配器**：这会扩大标题、表格、浮动对象和页码规则的回归范围。PoC 后应选择一条生产语义主链；PDF 原文对照不属于重复语义主链。

## 8. 适合本项目的分阶段落地建议

### 阶段 0：先建立可比较的验收基准

不修改生产代码，先固定同一批输入和基准输出：

- 从实际手册选取含多级标题、普通/合并单元格表格、行内与浮动图片、题注、目录域、书签、文本框、页眉页脚、分节/横竖页的样本；
- 加入中文、特殊符号、长段落跨页、异常/快速保存样本；加密或透明加密样本单独标记，不与普通解析失败混淆；
- 以当前 `.docx` 结构化结果和 PDF 预览为基线，保存源文件哈希、解析器版本、字体环境和运行耗时；
- 建立“不得静默丢内容”的清单：标题数、表格/单元格数、图片数、文本框数、目录/链接数、页数和异常项必须可审计。

### 阶段 1：时间盒 UNO 直读 PoC

仅在 PoC 分支/目录实现一个只读提取器：

1. UNO 以 ReadOnly/Hidden 加载 `.doc`，禁止宏执行，不写回源文档；
2. 输出当前车端已经消费的规范块模型，而不是另建一套 UNO 专用 JSON；
3. 主文档流中按锚点归并段落、表格、图片和文本框，另记页眉页脚/脚注等 story；
4. 标题优先使用 `OutlineLevel`，辅以 `ParaStyleName`；图片保存 `XGraphic` 并记录锚点、裁剪与题注候选；[S-UNO-PARA][S-UNO-GRAPHIC]
5. 页码先沿用 PDF 预览映射；另用 `XPageCursor` 抽样核对，不在第一阶段替换 PDF 区域映射；[S-UNO-PAGE]
6. 与基线逐项比较规范化文本、标题层级、表格网格、图片字节/关联、目录链接、文本框和页码，并记录所有差异由“导入”还是“`.docx` 写出”造成。

**通过门槛**：至少证明一个当前真实痛点得到修复，且没有正文/表格/图片静默丢失、安全内容回归或不可接受的进程稳定性问题。若仅得到“少一个中间文件”，而结果相同且 UNO 适配更复杂，应判定不值得替换。

### 阶段 2：单一路线决策，再做生产加固

- 若 UNO 明显胜出，再让规范模型消费 UNO 结果，并删除不再需要的 `.docx` 语义解析路径；不要长期双轨。
- 若现有链胜出，保留现状，只把 PoC 发现的缺失类型、质检规则和样本纳入现有链。
- 若只有 Word 能解决特定源文档，将其限定为人工触发、单并发、独立 Windows 工作进程；微软服务支持边界不变。[S-WORD-SERVER]
- 生产加固统一包括独立进程、超时、崩溃回收、临时目录清理、禁用宏/外部更新、固定 LibreOffice 与字体版本、资源上限和逐文档诊断日志。

### 阶段 3：保留明文与安全校验，完成车端回归

当前 COM 回退用 OOXML 的 `PK` 文件头识别加密写出；取消 `.docx` 后，这个检查自然失效，但透明加密风险并不会自动消失。直读路线必须改为验证实际产物：JSON 可解码且非密文、图片具有合法文件头且可打开、PDF/预览可读取，并保留失败即不发布策略。

最后用车端真实渲染做端到端回归：章节导航、图片与题注、表格横向浏览、警告块、目录深链、原文页对照和离线数据包均通过后再切换。安全相关手册内容仍需人工审核，不能仅因解析器返回成功就自动发布。

## 9. 最终建议一句话

**“直接读取 `.doc`”值得作为 UNO PoC 验证，不值得作为自研二进制解析项目；在完整结构化手册目标下，默认保留现有 `.docx` 主链与 PDF 版面证据，除非实测证明 UNO 直读显著减少信息损失或运维故障。**

## 10. 一手来源索引

以下来源均为本报告实际核验的标准、官方文档或上游源码所附文档；antiword 链接是上游 0.37 源码文档的镜像，文件内保留原作者、版本日期和许可声明。

### Microsoft 规范与 Word 对象模型

- [S-MSDOC] [Microsoft `[MS-DOC]`：Word (.doc) Binary File Format](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/ccd7b486-7881-484c-a137-51170af7cc22)
- [S-MSDOC-TEXT] [Microsoft `[MS-DOC]` 2.4.1：Retrieving Text](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/01d5d8c4-cf9c-4ef9-80fd-439e763cfe01)
- [S-MSCFB] [Microsoft `[MS-CFB]`：Compound File Binary File Format](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/53989ce4-7b05-4f8d-829b-d08d6148375b)
- [S-MSODRAW] [Microsoft `[MS-ODRAW]`：Office Drawing Binary File Format](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-odraw/8560795e-7759-4745-838f-f7f2ef2f1872)
- [S-WORD-CONTENT] [Microsoft Word VBA：`Document.Content`](https://learn.microsoft.com/en-us/office/vba/api/word.document.content)
- [S-WORD-STYLE] [Microsoft Word VBA：`Paragraph.Style`](https://learn.microsoft.com/en-us/office/vba/api/word.paragraph.style)
- [S-WORD-TABLES] [Microsoft Word VBA：`Document.Tables`](https://learn.microsoft.com/en-us/office/vba/api/word.document.tables)
- [S-WORD-INLINE] [Microsoft Word VBA：`Document.InlineShapes`](https://learn.microsoft.com/en-us/office/vba/api/word.document.inlineshapes)
- [S-WORD-SHAPES] [Microsoft Word VBA：`Document.Shapes`](https://learn.microsoft.com/en-us/office/vba/api/word.document.shapes)
- [S-WORD-TOC] [Microsoft Word VBA：`Document.TablesOfContents`](https://learn.microsoft.com/en-us/office/vba/api/word.document.tablesofcontents)
- [S-WORD-BOOKMARKS] [Microsoft Word VBA：`Document.Bookmarks`](https://learn.microsoft.com/en-us/office/vba/api/word.document.bookmarks)
- [S-WORD-INFO] [Microsoft Word VBA：`WdInformation`（页码与页面坐标）](https://learn.microsoft.com/en-us/office/vba/api/word.wdinformation)
- [S-WORD-SERVER] [Microsoft：Considerations for server-side Automation of Office](https://support.microsoft.com/en-us/topic/considerations-for-server-side-automation-of-office-48bcfe93-8a89-47f1-0bce-017433ad79e2)

### LibreOffice UNO

- [S-UNO-LOADER] [LibreOffice API：`XComponentLoader.loadComponentFromURL`](https://api.libreoffice.org/docs/idl/ref/interfacecom_1_1sun_1_1star_1_1frame_1_1XComponentLoader.html)
- [S-UNO-FILTER] [LibreOffice core 源码：`MS_Word_97.xcu` 导入过滤器配置](https://raw.githubusercontent.com/LibreOffice/core/master/filter/source/config/fragments/filters/MS_Word_97.xcu)
- [S-UNO-DOC] [LibreOffice API：`TextDocument`（表格、图形、书签、目录、字段、文本框 suppliers）](https://api.libreoffice.org/docs/idl/ref/servicecom_1_1sun_1_1star_1_1text_1_1TextDocument.html)
- [S-UNO-PARA] [LibreOffice API：`ParagraphProperties`（`ParaStyleName`、`OutlineLevel`）](https://api.libreoffice.org/docs/idl/ref/servicecom_1_1sun_1_1star_1_1style_1_1ParagraphProperties.html)
- [S-UNO-GRAPHIC] [LibreOffice API：`TextGraphicObject`](https://api.libreoffice.org/docs/idl/ref/servicecom_1_1sun_1_1star_1_1text_1_1TextGraphicObject.html)
- [S-UNO-FRAME] [LibreOffice API：`TextFrame`](https://api.libreoffice.org/docs/idl/ref/servicecom_1_1sun_1_1star_1_1text_1_1TextFrame.html)
- [S-UNO-PAGE] [LibreOffice API：`XPageCursor.getPage`](https://api.libreoffice.org/docs/idl/ref/interfacecom_1_1sun_1_1star_1_1text_1_1XPageCursor.html)
- [S-LO-LICENSE] [LibreOffice 官方许可说明](https://www.libreoffice.org/about-us/licenses/)

### Python、传统工具与 Apache

- [S-OLEFILE] [olefile 0.47 官方文档](https://olefile.readthedocs.io/en/latest/)
- [S-OLEFILE-LICENSE] [olefile 官方许可说明](https://olefile.readthedocs.io/en/latest/License.html)
- [S-ANTIWORD-MAN] [antiword 0.37 上游源码所附手册（镜像）：能力、缺陷与 GPL-2.0+](https://raw.githubusercontent.com/rsdoiel/antiword/master/Docs/antiword.1)
- [S-ANTIWORD-README] [antiword 0.37 上游源码所附 README（镜像）：2005 版本信息](https://raw.githubusercontent.com/rsdoiel/antiword/master/Docs/ReadMe)
- [S-CATDOC] [catdoc 作者官方项目页：目标、平台、0.95 与许可](https://www.wagner.pp.ru/~vitus/software/catdoc/)
- [S-CATDOC-MAN] [catdoc 作者官方手册：纯文本、表格与已知缺陷](https://www.wagner.pp.ru/~vitus/software/catdoc/catdoc.1.html)
- [S-WV] [wvWare/wv 官方项目站：格式、平台、工具废弃、TOC 限制与 GPL](https://wvware.sourceforge.net/)
- [S-POI] [Apache POI 官方 HWPF/XWPF 文档](https://poi.apache.org/components/document/)
- [S-POI-COMPONENTS] [Apache POI 官方组件、维护状态与依赖说明](https://poi.apache.org/components/)
- [S-POI-DOC] [Apache POI API：`HWPFDocument`](https://poi.apache.org/apidocs/dev/org/apache/poi/hwpf/HWPFDocument.html)
- [S-POI-EXTRACTOR] [Apache POI API：`WordExtractor`](https://poi.apache.org/apidocs/dev/org/apache/poi/hwpf/extractor/WordExtractor.html)
- [S-POI-PARAGRAPH] [Apache POI API：`Paragraph`（样式与标题级别）](https://poi.apache.org/apidocs/dev/org/apache/poi/hwpf/usermodel/Paragraph.html)
- [S-POI-TABLE] [Apache POI API：`TableIterator`](https://poi.apache.org/apidocs/dev/org/apache/poi/hwpf/usermodel/TableIterator.html)
- [S-POI-PICTURES] [Apache POI API：`PicturesTable`](https://poi.apache.org/apidocs/dev/org/apache/poi/hwpf/model/PicturesTable.html)
- [S-TIKA-FORMATS] [Apache Tika 3.2.3 官方格式说明（OfficeParser 使用 POI）](https://tika.apache.org/3.2.3/formats.html)
- [S-TIKA-EXAMPLES] [Apache Tika 3.2.3 官方 API 示例（文本与 XHTML）](https://tika.apache.org/3.2.3/examples.html)
- [S-TIKA-OFFICE] [Apache Tika 3.2.3 API：`OfficeParser`](https://tika.apache.org/3.2.3/api/org/apache/tika/parser/microsoft/OfficeParser.html)
- [S-APACHE-LICENSE] [Apache License 2.0 官方文本](https://www.apache.org/licenses/LICENSE-2.0)

### 商业对照

- [S-ASPOSE-FORMATS] [Aspose.Words for .NET 官方支持格式](https://docs.aspose.com/words/net/supported-document-formats/)
- [S-ASPOSE-LAYOUT] [Aspose.Words 官方 API：`LayoutCollector`](https://reference.aspose.com/words/net/aspose.words.layout/layoutcollector/)
- [S-ASPOSE-SYSTEM] [Aspose.Words for .NET 官方系统要求](https://docs.aspose.com/words/net/system-requirements/)
- [S-ASPOSE-LICENSE] [Aspose 官方许可类型与部署说明](https://purchase.aspose.com/policies/license-types)

[S-MSDOC]: https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/ccd7b486-7881-484c-a137-51170af7cc22
[S-MSDOC-TEXT]: https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/01d5d8c4-cf9c-4ef9-80fd-439e763cfe01
[S-MSCFB]: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/53989ce4-7b05-4f8d-829b-d08d6148375b
[S-MSODRAW]: https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-odraw/8560795e-7759-4745-838f-f7f2ef2f1872
[S-WORD-CONTENT]: https://learn.microsoft.com/en-us/office/vba/api/word.document.content
[S-WORD-STYLE]: https://learn.microsoft.com/en-us/office/vba/api/word.paragraph.style
[S-WORD-TABLES]: https://learn.microsoft.com/en-us/office/vba/api/word.document.tables
[S-WORD-INLINE]: https://learn.microsoft.com/en-us/office/vba/api/word.document.inlineshapes
[S-WORD-SHAPES]: https://learn.microsoft.com/en-us/office/vba/api/word.document.shapes
[S-WORD-TOC]: https://learn.microsoft.com/en-us/office/vba/api/word.document.tablesofcontents
[S-WORD-BOOKMARKS]: https://learn.microsoft.com/en-us/office/vba/api/word.document.bookmarks
[S-WORD-INFO]: https://learn.microsoft.com/en-us/office/vba/api/word.wdinformation
[S-WORD-SERVER]: https://support.microsoft.com/en-us/topic/considerations-for-server-side-automation-of-office-48bcfe93-8a89-47f1-0bce-017433ad79e2
[S-UNO-LOADER]: https://api.libreoffice.org/docs/idl/ref/interfacecom_1_1sun_1_1star_1_1frame_1_1XComponentLoader.html
[S-UNO-FILTER]: https://raw.githubusercontent.com/LibreOffice/core/master/filter/source/config/fragments/filters/MS_Word_97.xcu
[S-UNO-DOC]: https://api.libreoffice.org/docs/idl/ref/servicecom_1_1sun_1_1star_1_1text_1_1TextDocument.html
[S-UNO-PARA]: https://api.libreoffice.org/docs/idl/ref/servicecom_1_1sun_1_1star_1_1style_1_1ParagraphProperties.html
[S-UNO-GRAPHIC]: https://api.libreoffice.org/docs/idl/ref/servicecom_1_1sun_1_1star_1_1text_1_1TextGraphicObject.html
[S-UNO-FRAME]: https://api.libreoffice.org/docs/idl/ref/servicecom_1_1sun_1_1star_1_1text_1_1TextFrame.html
[S-UNO-PAGE]: https://api.libreoffice.org/docs/idl/ref/interfacecom_1_1sun_1_1star_1_1text_1_1XPageCursor.html
[S-LO-LICENSE]: https://www.libreoffice.org/about-us/licenses/
[S-OLEFILE]: https://olefile.readthedocs.io/en/latest/
[S-OLEFILE-LICENSE]: https://olefile.readthedocs.io/en/latest/License.html
[S-ANTIWORD-MAN]: https://raw.githubusercontent.com/rsdoiel/antiword/master/Docs/antiword.1
[S-ANTIWORD-README]: https://raw.githubusercontent.com/rsdoiel/antiword/master/Docs/ReadMe
[S-CATDOC]: https://www.wagner.pp.ru/~vitus/software/catdoc/
[S-CATDOC-MAN]: https://www.wagner.pp.ru/~vitus/software/catdoc/catdoc.1.html
[S-WV]: https://wvware.sourceforge.net/
[S-POI]: https://poi.apache.org/components/document/
[S-POI-COMPONENTS]: https://poi.apache.org/components/
[S-POI-DOC]: https://poi.apache.org/apidocs/dev/org/apache/poi/hwpf/HWPFDocument.html
[S-POI-EXTRACTOR]: https://poi.apache.org/apidocs/dev/org/apache/poi/hwpf/extractor/WordExtractor.html
[S-POI-PARAGRAPH]: https://poi.apache.org/apidocs/dev/org/apache/poi/hwpf/usermodel/Paragraph.html
[S-POI-TABLE]: https://poi.apache.org/apidocs/dev/org/apache/poi/hwpf/usermodel/TableIterator.html
[S-POI-PICTURES]: https://poi.apache.org/apidocs/dev/org/apache/poi/hwpf/model/PicturesTable.html
[S-TIKA-FORMATS]: https://tika.apache.org/3.2.3/formats.html
[S-TIKA-EXAMPLES]: https://tika.apache.org/3.2.3/examples.html
[S-TIKA-OFFICE]: https://tika.apache.org/3.2.3/api/org/apache/tika/parser/microsoft/OfficeParser.html
[S-APACHE-LICENSE]: https://www.apache.org/licenses/LICENSE-2.0
[S-ASPOSE-FORMATS]: https://docs.aspose.com/words/net/supported-document-formats/
[S-ASPOSE-LAYOUT]: https://reference.aspose.com/words/net/aspose.words.layout/layoutcollector/
[S-ASPOSE-SYSTEM]: https://docs.aspose.com/words/net/system-requirements/
[S-ASPOSE-LICENSE]: https://purchase.aspose.com/policies/license-types

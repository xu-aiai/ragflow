# python-docx 官方能力、边界与文档索引

## 1. 结论

- 当前自定义流水线的顶层 `Element.kind` 只有 `para` 和 `table`。`pipeline/xc975_pipeline/docmodel.py` 只把正文中的 `w:p`、`w:tbl` 转为顶层元素，并额外展开块级 `w:sdt`。
- 这是项目原始元素模型的限制，不是 DOCX 格式的限制，也不是 python-docx 的整体能力上限。
- python-docx 的 `Document.iter_inner_content()` 同样只保序产生 `Paragraph | Table`，但其他对象可以通过 `Document`、`Section`、样式、批注等专门接口访问。
- 项目声明的依赖为 `python-docx>=1.1`。批注 API 是 1.2.0 新增的，因此不能假设仅安装 1.1.x 的环境也具备批注接口。版本依据见[官方版本历史](https://github.com/python-openxml/python-docx/blob/master/HISTORY.rst)。
- 对浮动形状、文本框、公式、脚注、尾注、OLE 等内容，应表述为“没有完整高级 API，需要自行解析 XML 或包部件”，而不是“DOCX 加载后这些内容不存在”。

## 2. 当前项目实际使用的范围

当前项目已经读取：

- 正文段落、正文表格及其文档顺序。
- 段落文字和样式名。
- Word 自动编号标记 `w:numPr`。
- 图片关系 ID 和图片部件字节。
- DrawingML/VML 文本框文字、嵌套文本框和框内表格文字，并处理 AlternateContent 重复副本。
- 部分文本容器，如超链接、`smartTag`、插入修订、简单域、`customXml`、行内 `sdt`。
- 表格 `gridSpan`、`vMerge`、跨行和跨列信息。
- 块级 `w:sdt` 展开后的内容。

项目没有把这些能力全部建成独立原始元素。例如，图片是段落或单元格的关联数据，标题和列表是后续语义识别结果。

## 3. python-docx 公开读取能力

| 对象 | 可读取内容 | 官方依据 |
|---|---|---|
| 正文块 | `doc.paragraphs`、`doc.tables`、`doc.iter_inner_content()`；后者保序产生段落和表格 | [Document objects](https://python-docx.readthedocs.io/en/latest/api/document.html) |
| 段落 | 文本、样式、对齐、缩进、行距、分页属性、Run、超链接、已渲染分页符 | [Text-related objects](https://python-docx.readthedocs.io/en/latest/api/text.html) |
| Run | 文本、粗体、斜体、下划线、字体、字号、颜色、上下标、字符样式等 | [Text-related objects](https://python-docx.readthedocs.io/en/latest/api/text.html) |
| 超链接 | `address`、`fragment`、`url`、显示文本及其中 Runs | [Text-related objects](https://python-docx.readthedocs.io/en/latest/api/text.html) |
| Run 内内容 | `Run.iter_inner_content()` 可产生文本、`Drawing`、已渲染分页符；`Drawing` 目前主要只暴露底层 XML | [Text-related objects](https://python-docx.readthedocs.io/en/latest/api/text.html)、[Run 源码](https://github.com/python-openxml/python-docx/blob/master/src/docx/text/run.py) |
| 表格 | 行、列、单元格、文本、样式、宽度、合并与 `grid_span`；单元格可继续读取段落及嵌套表格 | [Table objects](https://python-docx.readthedocs.io/en/latest/api/table.html) |
| 节 | 页面尺寸、方向、页边距、装订线、节起始类型 | [Section objects](https://python-docx.readthedocs.io/en/latest/api/section.html) |
| 页眉页脚 | 默认、首页、奇偶页页眉页脚及其中的段落、表格，以及继承关系 | [Section objects](https://python-docx.readthedocs.io/en/latest/api/section.html)、[Header/Footer 指南](https://python-docx.readthedocs.io/en/latest/user/hdrftr.html) |
| 行内形状 | `doc.inline_shapes` 可枚举；`InlineShape` 提供类型和显示宽高；类型可区分图片、链接图片、图表和 SmartArt | [Shape API](https://python-docx.readthedocs.io/en/latest/api/shape.html)、[shape.py](https://github.com/python-openxml/python-docx/blob/master/src/docx/shape.py)、[类型枚举](https://github.com/python-openxml/python-docx/blob/master/src/docx/enum/shape.py) |
| 图片部件 | 可通过关系 ID 取得相关部件并读取 `blob`、`content_type`、`partname`；`ImagePart` 还可提供原生尺寸等信息 | [Part 源码](https://github.com/python-openxml/python-docx/blob/master/src/docx/opc/part.py)、[ImagePart 源码](https://github.com/python-openxml/python-docx/blob/master/src/docx/parts/image.py) |
| 样式 | 段落、字符、表格样式，默认样式、潜在样式、继承关系及相关格式 | [Style objects](https://python-docx.readthedocs.io/en/latest/api/style.html) |
| 核心属性 | 标题、主题、作者、关键词、创建/修改时间、修订号等 | [Document/CoreProperties](https://python-docx.readthedocs.io/en/latest/api/document.html) |
| 文档设置 | 公开高级属性目前包括奇偶页页眉页脚设置；其余可处理底层 XML | [Settings API](https://python-docx.readthedocs.io/en/latest/api/settings.html) |
| 批注 | python-docx 1.2.0 可枚举批注，读取作者、缩写、时间、正文及其中段落和表格 | [Comment objects](https://python-docx.readthedocs.io/en/latest/api/comments.html)、[版本历史](https://github.com/python-openxml/python-docx/blob/master/HISTORY.rst) |

图片部件访问属于包/部件层能力，不是 `InlineShape` 提供的高级图片内容 API。

## 4. 无完整高级 API 或读取有限的对象

### 4.1 浮动图片和浮动形状

`InlineShapes` 的官方实现只查询 `wp:inline`，不查询 `wp:anchor`。SDK 没有公开完整的浮动形状对象模型，也没有完整暴露浮动位置、文字环绕等属性。

依据：[官方 shape.py](https://github.com/python-openxml/python-docx/blob/master/src/docx/shape.py)。

### 4.2 图表和 SmartArt

行内时可以识别形状类型和显示尺寸，但没有公开高级 API 读取图表系列、图表数据或 SmartArt 结构。需要继续读取相应包部件和 XML。

### 4.3 普通 Drawing

`Run.iter_inner_content()` 虽可产生 `Drawing`，但目前主要提供底层 `CT_Drawing` XML，不等于已经提供完整的图片、形状和绘图语义模型。

### 4.4 修订内容

`doc.paragraphs`、`doc.tables` 不返回位于 `w:ins`、`w:del` 等修订包装中的内容；正文底层迭代也只选择直接子级 `w:p/w:tbl`。项目当前只额外遍历了段落内部的 `w:ins`，没有建立通用修订模型。

依据：[Document API](https://python-docx.readthedocs.io/en/latest/api/document.html)、[CT_Body 源码](https://github.com/python-openxml/python-docx/blob/master/src/docx/oxml/document.py)。

### 4.5 内容控件和 customXml

SDK 没有通用的高级块对象来自动展开所有此类包装节点。项目自行展开块级 `w:sdt`，正是在补这个限制。

### 4.6 域代码、目录域和书签

SDK 没有对应的公开高级对象模型。`Run.text` 只处理文本、制表符和换行等指定节点，不处理 `instrText`。但不能据此断言普通 Run 中缓存的目录可见文本也完全读取不到。

依据：[CT_R 源码](https://github.com/python-openxml/python-docx/blob/master/src/docx/oxml/text/run.py)。

### 4.7 公式、文本框、脚注、尾注和 OLE

当前 API 目录没有相应完整高级语义对象。需要自行解析 XML 和包部件，不能将“没有高级 API”误解为“文件加载后这些字节不存在”。

### 4.8 自动编号

可以读取段落样式，也可以从 XML 检查 `w:numPr`，但官方 `_NumberingStyle` 明确标为“Not yet implemented”，没有高级 API 自动计算最终可见编号。

依据：[Style API](https://python-docx.readthedocs.io/en/latest/api/style.html)、[style.py](https://github.com/python-openxml/python-docx/blob/master/src/docx/styles/style.py)。

### 4.9 真实分页和排版

SDK 不是 Word 排版渲染引擎，不能计算文档当前的准确页码。只能读取文件中已有的 `lastRenderedPageBreak` 等标记。

依据：[Text-related objects](https://python-docx.readthedocs.io/en/latest/api/text.html)。

## 5. 高层 API 与底层 XML 的边界

底层 `document.element`、XML 节点和包关系可用于补充解析，但应与稳定的高级公开 API 分开描述。

特别是 `_p`、`_tbl` 等带下划线的接口属于私有实现接口。当前项目已经使用这些接口，因此升级 python-docx 时应运行针对性测试，避免私有结构变化导致解析回归。

建议将能力分为三层：

1. **稳定高层 API**：段落、Run、表格、节、页眉页脚、样式、核心属性、批注等。
2. **包和关系层 API**：图片及其他媒体部件。
3. **项目自定义 OOXML 解析**：内容控件、文本框、公式、浮动形状、完整修订、自动编号等。

## 6. 对未知 DOCX 完整解析的启示

面对未知 DOCX，不能只用 `doc.iter_inner_content()` 或当前的 `para/table` 流判断文档内容是否完整。应先清点：

- ZIP 包中的部件。
- 正文及其他故事部件中的块级节点。
- 图片、图表、SmartArt 和嵌入对象关系。
- 每种 XML 标签的出现次数。
- 已识别、已转换、已忽略和未知节点的数量。

原始层应保留来源部件、文档顺序、父子层级、关系 ID 和必要的原始 XML。语义层再从完整原始层选择业务需要的内容。

核心原则是：原始层尽量无损，未知内容显式记录；语义层按需抽取，但始终可以追溯。

## 7. 官方文档索引

### python-docx

- [官方文档首页](https://python-docx.readthedocs.io/en/latest/)
- [Document objects](https://python-docx.readthedocs.io/en/latest/api/document.html)
- [Text-related objects](https://python-docx.readthedocs.io/en/latest/api/text.html)
- [Table objects](https://python-docx.readthedocs.io/en/latest/api/table.html)
- [Section objects](https://python-docx.readthedocs.io/en/latest/api/section.html)
- [Header/Footer 指南](https://python-docx.readthedocs.io/en/latest/user/hdrftr.html)
- [Shape objects](https://python-docx.readthedocs.io/en/latest/api/shape.html)
- [Style objects](https://python-docx.readthedocs.io/en/latest/api/style.html)
- [Settings objects](https://python-docx.readthedocs.io/en/latest/api/settings.html)
- [Comment objects](https://python-docx.readthedocs.io/en/latest/api/comments.html)
- [官方源码仓库](https://github.com/python-openxml/python-docx)
- [官方版本历史](https://github.com/python-openxml/python-docx/blob/master/HISTORY.rst)

### DOCX/OOXML 格式

- [ECMA-376：Office Open XML File Formats](https://ecma-international.org/publications-and-standards/standards/ecma-376/)
- [Microsoft Open XML 文档](https://learn.microsoft.com/en-us/office/open-xml/open-xml-sdk)

ECMA-376 是 DOCX 底层格式规范；Microsoft 文档可辅助理解 OOXML 结构，但本项目实际使用的 Python SDK 是 python-docx。

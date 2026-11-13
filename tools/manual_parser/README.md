# 徐工公司手册文档解析器

这是一个从 RAGFlow `v0.27.3` 源码树中单独运行的解析产品。它复用
DeepDOC 的 OCR、版面识别和表格结构模型，但**不启动** RAGFlow 网站、
MySQL、Redis、Elasticsearch/Infinity、MinIO 或知识库摄取服务。

支持的输入只有 `PDF`、`DOC`、`DOCX`。产品始终运行一条自动流水线，
不会让用户选择 Docling、PP-Structure、DeepDOC 等“解析器插件”。

## 当前流水线

1. **格式统一**：PDF 原样保留；DOC/DOCX 由容器内 LibreOffice 生成
   用于视觉解析的 PDF，DOC 另转为 DOCX。
2. **双通道取证**：
   - DeepDOC 从页面得到 OCR/原生文字、版面类型、坐标、表格和区域裁图；
   - 对有文字层的 PDF 逐页读取原生字符/文字坐标：目录页用于重建标题、
     点引导线和右侧页码，正文页用于保守补回 DeepDOC 明确遗漏的原生行；
   - DOCX 直接读取 OOXML 的标题级别、列表、DrawingML/VML 图片关系、
     段内图文顺序、表格网格、单元格图片和 `rowspan`/`colspan`。
3. **证据融合**：OOXML 负责语义结构；转换后 PDF 的原生文字行通过单调顺序
   对齐恢复页码和坐标；DeepDOC 负责视觉区域。无法被原生证据覆盖的视觉正文
   会作为兜底保留，不会在融合时直接删除。
4. **区域视觉理解**：对表格、图、公式、警示框和标题的裁图调用固定的
   PaddleOCR-VL 区域服务。它不是另一套并排解析结果；返回值直接进入融合。
   若模型遗漏/修改型号、故障码、针脚、数值或单位，结果会被拒绝。
5. **公司手册重建**：中文断行、目录项、标题树、列表组、警示框、图注归属、
   表格用途和跨页续表。目录按行融合，未覆盖的原始区域不会被整页替换删除；
   只有连续页面才能组成跨页表，远端页面上的重复文字不会误挂到表格。DOCX
   中未定位的对象按 OOXML 源顺序在相邻锚点之间插值，不会默认归入第一页；
   小图保留所在段落或表格单元格的位置及来源关系。
6. **可信输出**：页面预览、坐标层、文档视图、复核项、JSON 和 Markdown。
   `unsafe` 表格保留在 JSON/页面中供复核，但数值不会进入可信 Markdown。

## Docker 一键运行

前提：安装 Docker Desktop（Windows 建议启用 WSL2 backend），分配至少
`8 GB` 内存；处理 200 多页手册建议 `16 GB`。第一次构建会拉取 RAGFlow
镜像并安装无界面的 LibreOffice，耗时和镜像体积都明显大于普通 Web 应用。

在本目录执行：

```powershell
cd tools/manual_parser
docker compose up --build
```

打开 <http://localhost:9392>。停止服务：

```powershell
docker compose down
```

解析记录保存在 Docker volume `manual-parser-data`，`down` 不会删除；只有
显式执行 `docker compose down -v` 才会删除结果。

Word 的分页依赖字体。镜像已安装 Noto CJK、文泉驿、Carlito（Calibri
度量兼容）和 Caladea（Cambria 度量兼容）。若公司允许使用手册原始字体，
把 `.ttf`/`.otf`/`.ttc` 放进本目录的 `fonts/`，容器启动时会刷新字体缓存；
这通常比调整解析规则更能减少 DOC/DOCX 转 PDF 后的页码漂移。

### 为什么这个容器能独立运行

`Dockerfile` 以 `infiniflow/ragflow:v0.27.3` 为运行时，直接复用该版本已
安装的 Python 包和 DeepDOC 模型，再覆盖当前工作区中的 `deepdoc/`、
`rag/`、`common/` 源码。因此运行的是当前二次开发版本，而不是请求另一台
完整 RAGFlow 服务。容器只有一个 Python HTTP 进程和 LibreOffice 子进程。

## 区域 VLM

没有 GPU/VLM 地址时，系统仍会完整运行 DeepDOC + OOXML + 公司规则，健康
接口会显示 `vlm_enabled: false`。有 NVIDIA GPU（驱动支持 CUDA 12.6+）时，
可直接叠加官方 PaddleOCR-VL vLLM 容器，仍然是同一条解析流水线：

```powershell
docker compose -f compose.yaml -f compose.gpu.yaml up --build
```

该模式按 PaddleOCR 官方的分层方式启动 VLM 服务和 PaddleOCR-VL pipeline
服务；主解析器把 DeepDOC 切好的区域图发给 `/layout-parsing`，并关闭它自己的
Layout Detection，因此不会再对整页重复做另一套版面切分。第一次会拉取很大
的官方 GPU 镜像。也可以给主解析器提供一个已有的、支持图片消息的
OpenAI-compatible `/v1/chat/completions` 地址：

```powershell
$env:MANUAL_PARSER_VLM_ENDPOINT="http://host.docker.internal:8000/v1/chat/completions"
$env:MANUAL_PARSER_VLM_MODEL="PaddleOCR-VL-1.6-0.9B"
docker compose up --build
```

若服务需要密钥，再设置 `MANUAL_PARSER_VLM_API_KEY`。这是流水线内部固定的
区域识别阶段，不是用户可切换的产品适配器。之所以不把大模型强塞进同一个
CPU 容器，是因为 DeepDOC 和 0.9B/更大的视觉模型有不同的显存、驱动和扩缩
容要求；拆成两个部署单元才能保证没有 GPU 的机器也一定能启动主解析器。

## API

- `GET /health`：服务和 VLM 配置状态。
- `POST /api/jobs`：请求体直接传文件字节，`X-Filename` 传 URL 编码文件名。
- `GET /api/jobs`：最近任务。
- `GET /api/jobs/{id}`：进度。
- `POST /api/jobs/{id}/cancel`：安全取消排队或运行任务。
- `DELETE /api/jobs/{id}`：删除已停止任务及其结果。
- `GET /api/jobs/{id}/result`：统一 JSON。
- `GET /api/jobs/{id}/pages/{page}/image`：页面图。
- `GET /api/jobs/{id}/download/{json|markdown|package}`：下载结果；`package`
  包含可离线打开的 Markdown、完整 JSON 和引用的区域图片。

大文件使用后台任务解析。默认只有一个 worker，因为 DeepDOC 模型实例不是
线程安全的；可以横向启动多个容器，而不要在一个容器内盲目增加并发。
上传时会计算文件 SHA-256；内容和流水线版本都相同时直接复用已有任务。
服务重启后遗留的 `queued/running` 任务会被明确标记为“已中断”，不会再在
网页中显示为仍在运行。

## 开发验证

纯规则测试不依赖完整 RAGFlow 环境：

```powershell
cd <repository-root>
$env:PYTHONPATH=(Resolve-Path tools/manual_parser).Path
python -m unittest discover -s tools/manual_parser/tests -v
node --check tools/manual_parser/static/app.js
```

真正的 PDF/DOC/DOCX 端到端测试应在上述 Docker 容器中进行，因为宿主机不
需要也不应该重复安装 DeepDOC 的 ONNX 模型、Python 依赖和 LibreOffice。

## 目录

```text
tools/manual_parser/
├─ manual_parser/       # 单流水线实现
├─ static/              # 双栏解析 UI
├─ tests/               # 领域后处理单测
├─ server.py            # 后台任务与 HTTP API
├─ Dockerfile
├─ compose.yaml
└─ CONTEXT.md           # 领域词汇和不变量
```

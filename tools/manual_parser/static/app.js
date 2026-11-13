const $ = (id) => document.getElementById(id);
const state = { jobs: [], activeId: null, result: null, page: 1, zoom: 1, poll: null, jsonRendered: false };

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.classList.remove("hidden");
  clearTimeout(node._timer);
  node._timer = setTimeout(() => node.classList.add("hidden"), 3600);
}

function labelStatus(status) {
  return { queued: "排队中", running: "解析中", cancelling: "正在取消", cancelled: "已取消", interrupted: "已中断", completed: "已完成", failed: "失败" }[status] || status;
}

function formatDate(value) {
  if (!value) return "";
  return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

async function jsonFetch(url, options) {
  const response = await fetch(url, options);
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(value.error || `${response.status} ${response.statusText}`);
  return value;
}

async function refreshJobs() {
  try {
    const value = await jsonFetch("/api/jobs");
    state.jobs = value.items || [];
    renderJobs();
  } catch (error) { toast(error.message); }
}

function renderJobs() {
  const list = $("jobList");
  list.replaceChildren();
  if (!state.jobs.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "暂无文档";
    list.append(empty);
    return;
  }
  for (const job of state.jobs) {
    const item = document.createElement("div");
    item.className = `job-item ${job.id === state.activeId ? "active" : ""}`;
    const name = document.createElement("div");
    name.className = "job-name";
    name.textContent = job.filename;
    name.title = job.filename;
    const foot = document.createElement("div");
    foot.className = "job-foot";
    const time = document.createElement("span");
    time.textContent = formatDate(job.created_at);
    const status = document.createElement("span");
    status.className = `status-pill ${job.status}`;
    status.textContent = labelStatus(job.status);
    foot.append(time, status);
    item.append(name, foot);
    item.onclick = () => openJob(job.id);
    list.append(item);
  }
}

async function upload(file) {
  if (!file || !/\.(pdf|docx?|PDF|DOCX?)$/.test(file.name)) {
    toast("请选择 PDF、DOC 或 DOCX 文件");
    return;
  }
  $("pipelineState").lastElementChild.textContent = "正在上传";
  try {
    const job = await jsonFetch("/api/jobs", { method: "POST", headers: { "X-Filename": encodeURIComponent(file.name), "Content-Type": "application/octet-stream" }, body: file });
    if (job.cache_hit) toast("检测到相同文件和解析器版本，已直接复用原结果");
    state.jobs.unshift(job);
    renderJobs();
    await openJob(job.id);
  } catch (error) {
    toast(error.message);
    $("pipelineState").lastElementChild.textContent = "服务就绪";
  }
}

async function openJob(id) {
  state.activeId = id;
  state.result = null;
  state.page = 1;
  clearInterval(state.poll);
  renderJobs();
  $("emptyWorkspace").classList.add("hidden");
  $("workbench").classList.remove("hidden");
  try {
    const job = await jsonFetch(`/api/jobs/${id}`);
    showJob(job);
    if (job.status === "completed" && job.has_result) await loadResult(id);
    else if (["queued", "running", "cancelling"].includes(job.status)) {
      state.poll = setInterval(() => pollJob(id), 1200);
    }
  } catch (error) { toast(error.message); }
}

function showJob(job) {
  $("documentName").textContent = job.filename;
  $("documentMeta").textContent = `${labelStatus(job.status)} · ${Math.round((job.progress || 0) * 100)}%`;
  const working = job.status === "queued" || job.status === "running";
  const stopping = job.status === "cancelling";
  $("statusStrip").classList.toggle("hidden", !working && !stopping && job.status !== "failed" && job.status !== "interrupted");
  $("progressBar").style.width = `${Math.round((job.progress || 0) * 100)}%`;
  $("progressText").textContent = job.error || job.message || "";
  $("pipelineState").lastElementChild.textContent = working || stopping ? job.message : job.status === "failed" ? "解析失败" : "服务就绪";
  $("cancelJob").classList.toggle("hidden", !working && !stopping);
  $("deleteJob").classList.toggle("hidden", working || stopping);
  $("downloadMarkdown").classList.toggle("hidden", job.status !== "completed");
  $("downloadJson").classList.toggle("hidden", job.status !== "completed");
  $("downloadPackage").classList.toggle("hidden", job.status !== "completed");
}

async function pollJob(id) {
  if (state.activeId !== id) return clearInterval(state.poll);
  try {
    const job = await jsonFetch(`/api/jobs/${id}`);
    showJob(job);
    const index = state.jobs.findIndex((item) => item.id === id);
    if (index >= 0) state.jobs[index] = job;
    renderJobs();
    if (job.status === "completed") {
      clearInterval(state.poll);
      await loadResult(id);
      refreshJobs();
    } else if (["failed", "cancelled", "interrupted"].includes(job.status)) {
      clearInterval(state.poll);
      toast(job.error || job.message || "任务已停止");
      refreshJobs();
    }
  } catch (error) { clearInterval(state.poll); toast(error.message); }
}

async function loadResult(id) {
  state.result = await jsonFetch(`/api/jobs/${id}/result`);
  state.jsonRendered = false;
  $("statusStrip").classList.add("hidden");
  $("documentMeta").textContent = `${state.result.metrics.page_count} 页 · ${state.result.metrics.block_count} 个内容块 · ${state.result.metrics.elapsed_seconds}s`;
  $("pageCount").textContent = state.result.pages.length;
  $("resultPageCount").textContent = state.result.pages.length;
  $("pageNumber").value = "1";
  $("resultPageNumber").value = "1";
  $("issueCount").textContent = state.result.issues.length;
  $("downloadMarkdown").href = `/api/jobs/${id}/download/markdown`;
  $("downloadJson").href = `/api/jobs/${id}/download/json`;
  $("downloadPackage").href = `/api/jobs/${id}/download/package`;
  renderStructure();
  renderIssues();
  $("jsonResult").textContent = "切换到 JSON 标签后加载完整结果。";
  switchTab("document");
  showPage(1);
}

function safeTable(html) {
  const source = new DOMParser().parseFromString(html, "text/html");
  const allowed = new Set(["TABLE", "THEAD", "TBODY", "TFOOT", "TR", "TH", "TD", "CAPTION", "BR"]);
  for (const node of [...source.body.querySelectorAll("*")]) {
    if (!allowed.has(node.tagName)) node.replaceWith(document.createTextNode(node.textContent || ""));
    else for (const attr of [...node.attributes]) if (!new Set(["rowspan", "colspan"]).has(attr.name.toLowerCase())) node.removeAttribute(attr.name);
  }
  return source.body.innerHTML;
}

function inlineParts(block, blockMap) {
  const flow = document.createElement("span");
  flow.className = "inline-parts";
  for (const part of block.parts || []) {
    if (part.type === "text") {
      flow.append(document.createTextNode(part.text || ""));
      continue;
    }
    if (part.type !== "image") continue;
    const figure = blockMap.get(part.figure_id);
    const source = part.asset || figure?.region_image;
    if (!source) continue;
    const image = document.createElement("img");
    image.className = "inline-part-image";
    image.src = source;
    image.alt = figure?.attributes?.caption || "行内插图";
    image.loading = "lazy";
    image.dataset.figureId = part.figure_id || "";
    flow.append(image);
  }
  return flow;
}

function tableCellMap(table) {
  const cells = new Map();
  const occupiedUntil = new Map();
  [...table.rows].forEach((row, rowIndex) => {
    let column = 0;
    for (const cell of [...row.cells]) {
      while ((occupiedUntil.get(column) ?? -1) >= rowIndex) column += 1;
      cells.set(`${rowIndex}:${column}`, cell);
      const colspan = Math.max(1, Number(cell.colSpan || 1));
      const rowspan = Math.max(1, Number(cell.rowSpan || 1));
      if (rowspan > 1) {
        for (let offset = 0; offset < colspan; offset += 1) occupiedUntil.set(column + offset, rowIndex + rowspan - 1);
      }
      column += colspan;
    }
  });
  return cells;
}

function injectTableCellImages(container, block, blockMap) {
  const table = container.querySelector("table");
  if (!table) return;
  const cells = tableCellMap(table);
  for (const sourceCell of block.attributes?.cells || []) {
    const cell = cells.get(`${sourceCell.row}:${sourceCell.column}`);
    if (!cell) continue;
    for (const figureId of sourceCell.figure_ids || []) {
      const figure = blockMap.get(figureId);
      if (!figure?.region_image) continue;
      const image = document.createElement("img");
      image.className = "table-cell-image";
      image.src = figure.region_image;
      image.alt = figure.attributes?.caption || `表格单元格 R${Number(sourceCell.row) + 1}C${Number(sourceCell.column) + 1}`;
      image.loading = "lazy";
      image.dataset.figureId = figureId;
      cell.append(image);
    }
  }
}

function renderDocument() {
  const root = $("documentResult");
  root.replaceChildren();
  const fragment = document.createDocumentFragment();
  const blockMap = new Map(state.result.blocks.map((block) => [block.id, block]));
  const embeddedFigureIds = new Set();
  for (const block of state.result.blocks) {
    for (const part of block.parts || []) if (part.type === "image" && part.figure_id) embeddedFigureIds.add(part.figure_id);
    if (block.type === "table") {
      for (const cell of block.attributes?.cells || []) for (const figureId of cell.figure_ids || []) embeddedFigureIds.add(figureId);
    }
  }
  const pageBlocks = state.result.blocks.filter((block) => {
    if ((block.page || 1) === state.page) return true;
    return block.attributes?.position_slices?.some((slice) => slice.page === state.page);
  });
  for (const block of pageBlocks) {
    if (["page_header", "page_footer"].includes(block.type)) continue;
    if (block.type === "figure" && embeddedFigureIds.has(block.id)) continue;
    const wrapper = document.createElement("article");
    wrapper.className = `parsed-block ${block.type}`;
    wrapper.dataset.blockId = block.id;
    const tag = document.createElement("span");
    tag.className = "block-tag";
    const kind = block.type === "heading"
      ? `H${block.level || "?"}`
      : block.type === "toc_entry"
        ? `TOC L${block.attributes?.toc_level || block.level || "?"}`
        : block.type;
    tag.textContent = `${kind}${block.page ? ` · P${block.page}` : ""}`;
    if (block.type === "table" && block.attributes?.integrity_status) {
      const integrity = document.createElement("span");
      integrity.className = `integrity-badge ${block.attributes.integrity_status}`;
      integrity.textContent = { verified: "结构已验证", review_required: "表格需复核", unsafe: "数值关系不安全" }[block.attributes.integrity_status] || block.attributes.integrity_status;
      tag.append(integrity);
    }
    wrapper.append(tag);
    if (block.attributes?.section_path?.length) {
      const path = document.createElement("div");
      path.className = "section-path";
      path.textContent = block.attributes.section_path.join(" › ");
      wrapper.append(path);
    }
    if (block.type === "heading") {
      const heading = document.createElement(`h${Math.max(1, Math.min(6, block.level || 2))}`);
      heading.textContent = block.text;
      wrapper.append(heading);
    } else if (block.type === "table" && block.html) {
      if (["unsafe", "review_required"].includes(block.attributes?.integrity_status)) {
        const warning = document.createElement("div");
        warning.className = `table-trust-warning ${block.attributes.integrity_status}`;
        warning.textContent = block.attributes.integrity_status === "unsafe"
          ? "该表格的数值对应关系不安全，禁止直接作为技术参数依据。"
          : "该表格需要人工复核后才能作为技术参数依据。";
        wrapper.append(warning);
      }
      const table = document.createElement("div");
      table.innerHTML = safeTable(block.html);
      injectTableCellImages(table, block, blockMap);
      wrapper.append(table);
    } else if (block.type === "figure" && block.region_image) {
      const image = document.createElement("img");
      image.src = block.region_image;
      image.alt = block.attributes.caption || "文档插图";
      image.loading = "lazy";
      wrapper.append(image);
      if (block.attributes.visual_description) {
        const p = document.createElement("p"); p.textContent = block.attributes.visual_description; wrapper.append(p);
      }
      if (block.attributes.semantic_symbol) {
        const p = document.createElement("p"); p.textContent = `语义图标：${block.attributes.semantic_symbol}`; wrapper.append(p);
      }
      if (block.text) {
        const p = document.createElement("p"); p.className = "figure-search-text"; p.textContent = `图中可检索文字：${block.text}`; wrapper.append(p);
      }
    } else if (block.type === "list_item") {
      const item = document.createElement("div");
      const marker = document.createElement("span");
      marker.className = "list-marker";
      marker.textContent = block.attributes?.marker || (block.attributes?.ordered ? "1." : "•");
      item.style.marginLeft = `${Math.max(0, Number(block.attributes?.list_level || 0)) * 16}px`;
      if (block.attributes?.list_id) item.title = `列表组：${block.attributes.list_id}`;
      item.append(marker, block.parts?.length ? inlineParts(block, blockMap) : document.createTextNode(block.text || ""));
      wrapper.append(item);
    } else if (block.type === "safety_notice") {
      const title = document.createElement("strong");
      title.textContent = `${block.attributes?.warning_level || "警告"}！`;
      const body = document.createElement("div");
      body.textContent = block.attributes?.body || block.text;
      wrapper.append(title, body);
      if (block.region_image) {
        const image = document.createElement("img"); image.src = block.region_image; image.alt = `${block.attributes?.warning_level || "安全"}区域原图`; image.loading = "lazy"; wrapper.append(image);
      }
    } else {
      const p = document.createElement("div");
      if (block.parts?.length) p.append(inlineParts(block, blockMap));
      else p.textContent = block.text || block.attributes.visual_description || "";
      wrapper.append(p);
    }
    const details = document.createElement("details");
    details.className = "block-details";
    const summary = document.createElement("summary");
    summary.textContent = "结构与证据";
    details.append(summary);
    details.addEventListener("toggle", () => {
      if (!details.open || details.dataset.loaded) return;
      const metadata = document.createElement("pre");
      metadata.textContent = JSON.stringify({
        id: block.id,
        bbox: block.bbox,
        parent_id: block.parent_id,
        continuation_of: block.continuation_of,
        confidence: block.confidence,
        parts: block.parts,
        attributes: block.attributes,
        evidence: block.evidence,
      }, null, 2);
      details.append(metadata);
      details.dataset.loaded = "1";
    });
    wrapper.append(details);
    wrapper.onclick = () => selectBlock(block.id, true);
    fragment.append(wrapper);
  }
  if (!fragment.childNodes.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = `第 ${state.page} 页没有可展示的正文块`;
    fragment.append(empty);
  }
  root.append(fragment);
}

function renderStructure() {
  const root = $("structureResult");
  root.replaceChildren();
  if (!state.result?.tree?.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "没有识别到章节结构";
    root.append(empty);
    return;
  }
  const renderNodes = (nodes) => {
    const list = document.createElement("ul");
    for (const node of nodes) {
      const item = document.createElement("li");
      const button = document.createElement("button");
      const label = document.createElement("strong");
      const prefix = node.kind === "toc_root" ? "TOC" : node.kind === "toc_entry" ? `TOC L${node.level}` : `H${node.level}`;
      label.textContent = `${prefix} ${node.title}`;
      const page = document.createElement("small");
      const sourcePage = node.page ? `P${node.page}` : "未定位";
      const target = node.printed_page_label
        ? ` → 印刷页 ${node.printed_page_label}${node.target_pdf_page ? ` / P${node.target_pdf_page}` : ""}`
        : "";
      page.textContent = `${sourcePage}${target}`;
      if (node.resolution_status) page.title = `目录目标状态：${node.resolution_status}`;
      button.append(label, page);
      button.onclick = () => { switchTab("document"); selectBlock(node.id, true); };
      item.append(button);
      if (node.children?.length) item.append(renderNodes(node.children));
      list.append(item);
    }
    return list;
  };
  root.append(renderNodes(state.result.tree));
}

function renderIssues() {
  const root = $("issuesResult");
  root.replaceChildren();
  if (!state.result.issues.length) {
    const empty = document.createElement("div"); empty.className = "empty"; empty.textContent = "没有需要复核的问题"; root.append(empty); return;
  }
  for (const issue of state.result.issues) {
    const card = document.createElement("div"); card.className = `issue-card ${issue.severity}`;
    const title = document.createElement("strong"); title.textContent = issue.code;
    const message = document.createElement("div"); message.textContent = issue.message;
    const meta = document.createElement("span"); meta.textContent = [issue.page ? `第 ${issue.page} 页` : "", issue.block_id || ""].filter(Boolean).join(" · ");
    card.append(title, message, meta);
    if (issue.block_id) card.onclick = () => { switchTab("document"); selectBlock(issue.block_id, true); };
    root.append(card);
  }
}

function showPage(number) {
  if (!state.result) return;
  state.page = Math.max(1, Math.min(state.result.pages.length, Number(number) || 1));
  $("pageNumber").value = state.page;
  $("resultPageNumber").value = state.page;
  const page = state.result.pages[state.page - 1];
  $("printedPageLabel").textContent = page.printed_page_label ? `印刷页码 ${page.printed_page_label}` : "";
  const image = $("pageImage");
  image.onload = renderOverlay;
  image.src = `/api/jobs/${state.activeId}/pages/${state.page}/image`;
  renderDocument();
}

function renderOverlay() {
  const overlay = $("overlay");
  overlay.replaceChildren();
  if (!state.result || !$("overlayToggle").checked) return;
  const page = state.result.pages[state.page - 1];
  const sx = $("pageImage").naturalWidth / page.width;
  const sy = $("pageImage").naturalHeight / page.height;
  const visible = [];
  for (const block of state.result.blocks) {
    const slices = block.attributes?.position_slices?.length ? block.attributes.position_slices : (block.page && block.bbox ? [{ page: block.page, bbox: block.bbox }] : []);
    for (const slice of slices) if (slice.page === state.page && slice.bbox) visible.push({ block, bbox: slice.bbox });
  }
  for (const item of visible) {
    const block = item.block;
    const [x0, y0, x1, y1] = item.bbox;
    const box = document.createElement("div");
    box.className = `bbox ${block.type}`;
    box.dataset.blockId = block.id;
    box.title = `${block.type}: ${(block.text || "").slice(0, 90)}`;
    Object.assign(box.style, { left: `${x0 * sx}px`, top: `${y0 * sy}px`, width: `${Math.max(2, (x1 - x0) * sx)}px`, height: `${Math.max(2, (y1 - y0) * sy)}px` });
    box.onclick = (event) => { event.stopPropagation(); selectBlock(block.id, false); };
    overlay.append(box);
  }
}

function selectBlock(id, navigate) {
  const block = state.result?.blocks.find((item) => item.id === id);
  if (!block) return;
  if (navigate && block.page && block.page !== state.page) showPage(block.page);
  document.querySelectorAll(".selected").forEach((node) => node.classList.remove("selected"));
  const parsed = document.querySelector(`.parsed-block[data-block-id="${CSS.escape(id)}"]`);
  const bbox = document.querySelector(`.bbox[data-block-id="${CSS.escape(id)}"]`);
  if (parsed) { parsed.classList.add("selected"); parsed.scrollIntoView({ behavior: "smooth", block: "center" }); }
  if (bbox) bbox.classList.add("selected");
}

function setZoom(next) {
  state.zoom = Math.max(.5, Math.min(2.5, next));
  $("paper").style.transform = `scale(${state.zoom})`;
  $("zoomLabel").textContent = `${Math.round(state.zoom * 100)}%`;
}

$("uploadButton").onclick = () => $("fileInput").click();
$("fileInput").onchange = (event) => upload(event.target.files[0]);
$("refreshButton").onclick = refreshJobs;
$("cancelJob").onclick = async () => {
  if (!state.activeId || !confirm("确定停止当前解析任务吗？已经完成的中间步骤不会作为最终结果保留。")) return;
  try {
    const job = await jsonFetch(`/api/jobs/${state.activeId}/cancel`, { method: "POST" });
    showJob(job);
    toast(job.message || "正在取消任务");
    clearInterval(state.poll);
    state.poll = setInterval(() => pollJob(state.activeId), 800);
  } catch (error) { toast(error.message); }
};
$("deleteJob").onclick = async () => {
  if (!state.activeId || !confirm("确定删除这个任务及其解析结果吗？此操作无法恢复。")) return;
  try {
    await jsonFetch(`/api/jobs/${state.activeId}`, { method: "DELETE" });
    state.activeId = null; state.result = null;
    $("workbench").classList.add("hidden");
    $("emptyWorkspace").classList.remove("hidden");
    await refreshJobs();
    toast("任务已删除");
  } catch (error) { toast(error.message); }
};
for (const event of ["dragenter", "dragover"]) $("dropZone").addEventListener(event, (e) => { e.preventDefault(); $("dropZone").classList.add("drag"); });
for (const event of ["dragleave", "drop"]) $("dropZone").addEventListener(event, (e) => { e.preventDefault(); $("dropZone").classList.remove("drag"); });
$("dropZone").ondrop = (event) => upload(event.dataTransfer.files[0]);
$("prevPage").onclick = () => showPage(state.page - 1);
$("nextPage").onclick = () => showPage(state.page + 1);
$("pageNumber").onchange = (event) => showPage(event.target.value);
$("resultPrevPage").onclick = () => showPage(state.page - 1);
$("resultNextPage").onclick = () => showPage(state.page + 1);
$("resultPageNumber").onchange = (event) => showPage(event.target.value);
$("zoomIn").onclick = () => setZoom(state.zoom + .1);
$("zoomOut").onclick = () => setZoom(state.zoom - .1);
$("overlayToggle").onchange = renderOverlay;
function switchTab(name) {
  document.querySelectorAll(".tabs button").forEach((item) => item.classList.toggle("active", item.dataset.tab === name));
  $("documentResult").classList.toggle("hidden", name !== "document");
  $("structureResult").classList.toggle("hidden", name !== "structure");
  $("jsonResult").classList.toggle("hidden", name !== "json");
  $("issuesResult").classList.toggle("hidden", name !== "issues");
  $("resultPageControls").classList.toggle("hidden", name !== "document");
  if (name === "json" && state.result && !state.jsonRendered) {
    $("jsonResult").textContent = JSON.stringify(state.result, null, 2);
    state.jsonRendered = true;
  }
}

document.querySelectorAll(".tabs button").forEach((button) => button.onclick = () => switchTab(button.dataset.tab));

refreshJobs();

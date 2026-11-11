const STAGES = ["校验", "解析", "DITA 生成", "手册"];
const STAGE_STEPS = [
  ["读取文件头", "读取文件大小", "格式识别与密文检查"],
  ["解析文档结构", "注入标题编号", "目录交叉验证", "表格分类", "提取图片"],
  ["切分章节树", "抽取故障码", "抽取保养规则", "打包数据", "生成审核清单"],
  ["加载 DITA 标准数据", "生成手册阅读视图"],
];
const GOLDEN = { A: { 章节: 161, 故障码: 205 }, B: { 章节: 77 }, C: { 章节: 261 } };
const CLASS_BADGE = {
  warning: ["警告框", "b-warn"],
  fault_code: ["故障码表", "b-fault"],
  period: ["周期表", "b-period"],
  layout: ["排版表", "b-layout"],
  data: ["数据表", "b-data"],
};
// 解析界面的元素类型与 Word 样式显示字典；键统一使用小写。
const FIELD_LABELS = {
  p: "正文段落",
  para: "正文段落",
  toc: "目录",
  "toc 1": "一级目录",
  "toc 2": "二级目录",
  "toc 3": "三级目录",
  heading: "标题",
  "heading 1": "一级标题",
  "heading 2": "二级标题",
  "heading 3": "三级标题",
  "heading 4": "四级标题",
  "heading 5": "五级标题",
  "heading 6": "六级标题",
  subtitle: "副标题",
  normal: "普通正文",
  zw: "正文（ZW）",
  "body text": "正文文本",
  "body text indent": "缩进正文",
  caption: "图表题注",
  "列表段落": "列表段落",
  "批注文字": "批注文字",
  "正文文本缩进 2": "二级正文文本缩进",
  "无间隔1": "无间隔正文",
  diagram: "图示段落",
};
const CheckIcon = '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m3.5 8 3 3 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';

let currentRun = null;
let currentMeta = null;
let currentStage = null;
let compareMode = false;
let previewFile = null;
let previewPage = 1;
let previewPages = 0;
let previewPageMap = {};
let previewPageGroups = {};
let previewRegions = {};
let activeElementIds = new Set();
let hoveredElementIds = new Set();
let pageFilterOn = true;
let compareOffExplicit = false;
let stageRequest = 0;
let toastTimer = null;
/* 流水运行（live run）状态 */
let liveMode = false;
let followMode = true;
let eventSource = null;
let pollTimer = null;
let stageStatus = {};        // n -> {名称, 状态, 摘要, 耗时}（运行中由事件流增量维护）
let stageClock = {};         // n -> 该阶段开始时的 Date.now()
let runStartTime = null;
let elapsedTimer = null;
let stageSteps = {};         // n -> [步骤名]（运行中由 step 事件增量维护，视图内实时点亮）
let manualReaderTopics = [];
let manualReaderIndex = 0;
let sourceStyleById = new Map();
let sourceTextById = new Map();

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || r.statusText);
  }
  return r.json();
}

/* ---------- 初始化与运行记录 ---------- */

async function init() {
  renderStepper(null);
  try {
    await loadFiles();
    await refreshHistory(true);
  } catch (err) {
    showToast(`工作台加载失败：${err.message}`, true);
  }
}

async function loadFiles() {
  const data = await api("/api/manuals");
  const sel = document.getElementById("file");
  sel.innerHTML = "";
  if (!data.files.length) {
    sel.appendChild(new Option("未找到可解析的手册", ""));
    sel.disabled = true;
    return;
  }
  for (const f of data.files) {
    const opt = document.createElement("option");
    opt.value = f.path;
    opt.textContent = `${f.name}（${(f.size / 1048576).toFixed(1)} MB）`;
    sel.appendChild(opt);
  }
  sel.onchange = guessDoc;
  guessDoc();
}

function guessDoc() {
  const sel = document.getElementById("file");
  const name = sel.selectedOptions[0]?.textContent || "";
  const doc = document.getElementById("doc");
  const variant = document.getElementById("variant");
  if (name.includes("维修保养手册")) { doc.value = "B"; variant.value = "国内干桥"; }
  else if (name.includes("操保手册") || name.includes("253910058")) { doc.value = "C"; variant.value = "EU湿桥"; }
  else { doc.value = "A"; variant.value = "国内干桥"; }
}

async function refreshHistory(selectLatest = false) {
  const runs = await api("/api/runs");
  const sel = document.getElementById("history");
  sel.innerHTML = '<option value="">选择一次运行记录</option>';
  for (const r of runs) {
    const opt = document.createElement("option");
    opt.value = r.run_id;
    opt.textContent = `${r.错误 ? "失败" : "完成"} · ${r.文档} 手册 · ${formatTime(r.开始)}`;
    sel.appendChild(opt);
  }
  sel.onchange = handleHistoryChange;
  if (selectLatest && runs.length) await loadRun(runs[0].run_id);
}

async function handleHistoryChange(event) {
  const runId = event.currentTarget.value;
  if (!runId) return;
  try {
    await loadRun(runId);
  } catch (err) {
    showToast(`运行记录加载失败：${err.message}`, true);
  }
}

async function loadRun(runId) {
  stopLive();
  const meta = await api(`/api/runs/${runId}`);
  currentRun = meta.run_id;
  currentMeta = meta;
  compareMode = false;
  previewFile = null;
  previewPage = 1;
  previewPages = 0;
  previewPageMap = {};
  previewPageGroups = {};
  previewRegions = {};
  activeElementIds.clear();
  hoveredElementIds.clear();
  compareOffExplicit = false;
  document.getElementById("history").value = runId;
  renderStepper(meta);
  setRunStatus(meta.错误 ? "error" : "success", meta.错误 ? "运行失败" : "解析完成");
  const failed = Object.entries(meta.阶段 || {}).find(([, s]) => s.状态 === "失败");
  await selectStage(failed ? Number(failed[0]) : 2);
}

function formatTime(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

function setRunStatus(kind, text) {
  const badge = document.getElementById("run-status");
  badge.className = `status-badge ${kind}`;
  badge.textContent = text;
}

function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.className = `toast show${isError ? " error" : ""}`;
  toastTimer = setTimeout(() => { toast.className = "toast"; }, 3600);
}

/* ---------- 运行 ---------- */

document.getElementById("run-form").addEventListener("submit", handleRunSubmit);

async function handleRunSubmit(event) {
  event.preventDefault();
  const btn = document.getElementById("run-btn");
  if (!document.getElementById("file").value) {
    showToast("请先选择一份源手册", true);
    return;
  }
  btn.disabled = true;
  btn.classList.add("running");
  btn.querySelector("span").textContent = "正在启动…";
  setRunStatus("running", "正在启动");
  stageStatus = {};
  stageClock = {};
  stageSteps = {};
  renderStepper(null);
  showLiveStage(0);
  try {
    const r = await api("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path: document.getElementById("file").value,
        doc: document.getElementById("doc").value,
        variant: document.getElementById("variant").value,
        version: document.getElementById("version").value,
      }),
    });
    beginLiveRun(r.run_id);
  } catch (err) {
    setRunStatus("error", "启动失败");
    showToast(`运行启动失败：${err.message}`, true);
  } finally {
    btn.disabled = false;
    btn.classList.remove("running");
    btn.querySelector("span").textContent = "开始解析";
  }
}

/* ---------- 流水运行：事件流驱动的实时交互 ---------- */

function stopLive() {
  liveMode = false;
  followMode = true;
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  clearTimeout(pollTimer);
  pollTimer = null;
  clearInterval(elapsedTimer);
  elapsedTimer = null;
  const followBtn = document.getElementById("follow-btn");
  if (followBtn) followBtn.hidden = true;
}

function beginLiveRun(runId) {
  stopLive();
  currentRun = runId;
  currentMeta = null;
  currentStage = null;
  compareMode = false;
  previewFile = null;
  previewPage = 1;
  previewPages = 0;
  previewPageMap = {};
  previewPageGroups = {};
  previewRegions = {};
  activeElementIds.clear();
  hoveredElementIds.clear();
  compareOffExplicit = false;
  stageStatus = {};
  stageClock = {};
  stageSteps = {};
  runStartTime = Date.now();
  liveMode = true;
  followMode = true;

  renderStepper({ 阶段: stageStatus });
  setRunStatus("running", "正在初始化");
  showLiveStage(0);
  openEventStream(runId);
  elapsedTimer = setInterval(updateElapsed, 500);
}

function openEventStream(runId) {
  const es = new EventSource(`/api/runs/${encodeURIComponent(runId)}/stream`);
  eventSource = es;
  es.onmessage = e => handleRunEvent(JSON.parse(e.data));
  es.onerror = () => {
    if (eventSource !== es) return;
    es.close();
    eventSource = null;
    if (liveMode && currentRun === runId) {
      showToast("实时事件流断开，转为轮询运行状态…", true);
      pollUntilDone(runId);
    }
  };
}

/* SSE 断开后的兜底：轮询 run.json，把阶段状态补进界面 */
async function pollUntilDone(runId) {
  if (!liveMode || currentRun !== runId) return;
  try {
    const meta = await api(`/api/runs/${runId}`);
    for (const [k, s] of Object.entries(meta.阶段 || {})) {
      const n = Number(k);
      const known = stageStatus[n];
      if (!known || (known.状态 === "运行中" && s.状态 !== "运行中") || (known.状态 !== "失败" && s.状态 === "失败")) {
        stageStatus[n] = s;
      }
    }
    renderStepper({ 阶段: stageStatus });
    if (meta.结束) {
      finishLiveRun(meta.错误 || null);
      return;
    }
  } catch { /* run.json 尚未写入时忽略，继续等 */ }
  pollTimer = setTimeout(() => pollUntilDone(runId), 1500);
}

function handleRunEvent(ev) {
  const n = ev.阶段;
  switch (ev.类型) {
    case "stage_start": {
      stageStatus[n] = { 名称: STAGES[n], 状态: "运行中" };
      stageClock[n] = Date.now();
      renderStepper({ 阶段: stageStatus });
      setRunStatus("running", `阶段 ${n + 1}/${STAGES.length} · ${STAGES[n]}`);
      if (followMode) showLiveStage(n);
      break;
    }
    case "step": {
      stageSteps[n] = [...(stageSteps[n] || []), { name: ev.摘要, result: ev.结果 || "" }];
      if (liveMode && currentStage === n) showLiveStage(n);
      break;
    }
    case "stage_done": {
      stageStatus[n] = { 名称: STAGES[n], 状态: "完成", 摘要: ev.摘要, 耗时: ev.耗时 };
      renderStepper({ 阶段: stageStatus });
      if (followMode) showLiveStage(n, true);
      break;
    }
    case "stage_fail": {
      stageStatus[n] = { 名称: STAGES[n], 状态: "失败", 摘要: ev.摘要 };
      renderStepper({ 阶段: stageStatus });
      setRunStatus("error", `阶段 ${n + 1} 失败`);
      if (followMode) showFailedStage(n, ev.摘要);
      break;
    }
    case "run_done":
      finishLiveRun(ev.摘要 || null);
      break;
  }
  updateElapsed();
}

async function finishLiveRun(error) {
  const runId = currentRun;
  stopLive();
  let meta = null;
  try {
    meta = await api(`/api/runs/${runId}`);
  } catch { /* 保持现有界面 */ }
  if (meta && currentRun === runId) {
    currentMeta = meta;
    renderStepper(meta);
    setRunStatus(meta.错误 ? "error" : "success", meta.错误 ? "运行失败" : "解析完成");
    await refreshHistory();
    document.getElementById("history").value = runId;
  }
  showToast(
    error ? `解析已中止：${error}` : "解析完成，已生成结构化数据与审核清单",
    Boolean(error));
}

function runningStageIndex() {
  const hit = Object.entries(stageStatus).find(([, s]) => s.状态 === "运行中");
  return hit ? Number(hit[0]) : null;
}

function markActiveStep(n) {
  currentStage = n;
  document.querySelectorAll("#stepper .stage-step").forEach((c, i) => {
    c.classList.toggle("active", i === n);
    if (i === n) c.setAttribute("aria-current", "step");
    else c.removeAttribute("aria-current");
  });
}

function showLiveStage(n, completed = false) {
  markActiveStep(n);
  const received = stageSteps[n] || [];
  const steps = (STAGE_STEPS[n] || []).map(name => ({ name, result: "" }));
  for (const step of received) {
    const existing = steps.find(item => item.name === step.name);
    if (existing) existing.result = step.result;
    else steps.push(step);
  }
  const current = Math.max(0, received.length - 1);
  const items = steps.map((step, i) => {
    const status = completed || i < current ? "done" : i === current ? "running" : "pending";
    const marker = status === "done" ? CheckIcon
      : status === "running" ? '<span class="step-spinner" aria-hidden="true"></span>'
      : String(i + 1).padStart(2, "0");
    const statusText = { done: "已完成", running: "执行中", pending: "待执行" }[status];
    const result = step.result ? `<small class="live-step-result">${esc(step.result)}</small>` : "";
    return `<li class="${status}"><span class="live-step-marker">${marker}</span>` +
      `<span class="live-step-copy"><b>${esc(step.name)}</b>${result}</span>` +
      `<span class="live-step-status">${statusText}</span></li>`;
  }).join("");
  const elapsed = completed
    ? `本阶段用时 <b>${formatSeconds(Number(stageStatus[n]?.耗时 || 0))}</b>`
    : '本阶段已用时 <b id="live-elapsed">0 秒</b>';
  document.getElementById("stage-view").innerHTML = `
    <article class="stage-container">
      <header class="stage-heading">
        <div class="stage-heading-main">
          <span class="stage-number">${String(n + 1).padStart(2, "0")}</span>
          <div><h2>${STAGES[n]}</h2></div>
        </div>
        <span class="status-badge ${completed ? "success" : "running"}">${completed ? "阶段已完成" : "阶段执行中"}</span>
      </header>
      <div class="live-stage" aria-busy="${!completed}">
        <ol class="live-steps">${items}</ol>
        <p class="live-elapsed-line">${elapsed}</p>
        ${completed ? '<div class="live-stage-actions"><button id="view-stage-result" class="compare-button" type="button">查看阶段结果</button></div>' : ""}
      </div>
    </article>`;
  if (completed) {
    document.getElementById("view-stage-result").onclick = () => selectStage(n);
  }
  updateElapsed();
}

function showFailedStage(n, message) {
  markActiveStep(n);
  document.getElementById("stage-view").innerHTML = `
    <article class="stage-container">
      <header class="stage-heading">
        <div class="stage-heading-main">
          <span class="stage-number">${String(n + 1).padStart(2, "0")}</span>
          <div><h2>${STAGES[n]}</h2></div>
        </div>
      </header>
      <div class="error-state">
        <h1>阶段执行失败</h1>
        <p>${esc(message || "未知错误")}</p>
      </div>
    </article>`;
}

function updateElapsed() {
  if (runStartTime === null) return;
  document.querySelectorAll("#stepper .stage-step").forEach((chip, i) => {
    const badge = chip.querySelector(".step-elapsed");
    if (!badge) return;
    const start = stageClock[i];
    badge.textContent = start === undefined ? "" : formatSeconds(Math.floor((Date.now() - start) / 1000));
  });
  const liveEl = document.getElementById("live-elapsed");
  if (liveEl) {
    const n = runningStageIndex();
    const start = n === null ? undefined : stageClock[n];
    liveEl.textContent = start === undefined ? "—" : formatSeconds(Math.floor((Date.now() - start) / 1000));
  }
}

function formatSeconds(secs) {
  return secs < 60 ? `${secs} 秒` : `${Math.floor(secs / 60)} 分 ${secs % 60} 秒`;
}

document.getElementById("follow-btn").addEventListener("click", () => {
  followMode = true;
  document.getElementById("follow-btn").hidden = true;
  const running = runningStageIndex();
  if (running !== null) showLiveStage(running);
});

/* ---------- 步骤条与阶段详情 ---------- */

function renderStepper(meta) {
  const nav = document.getElementById("stepper");
  nav.innerHTML = "";
  STAGES.forEach((name, i) => {
    const st = meta ? (i === 3 && meta.阶段[2]?.状态 === "完成"
      ? { 状态: "完成", 摘要: "基于 DITA 标准数据生成手册展示" }
      : (meta.阶段[i] || { 状态: "跳过" })) : null;
    const statusClass = st ? ({ 完成: "done", 失败: "error", 跳过: "skip", 运行中: "running" }[st.状态] || "") : "";
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = `stage-step ${statusClass}`;
    chip.disabled = !meta;
    chip.setAttribute("aria-label", `阶段 ${i + 1}：${name}${st ? `，${st.状态}` : ""}`);
    const marker = st?.状态 === "完成" ? CheckIcon
      : st?.状态 === "运行中" ? '<span class="step-spinner" aria-hidden="true"></span>'
      : String(i + 1).padStart(2, "0");
    chip.innerHTML = `<span class="step-marker">${marker}</span><span class="step-label">${name}</span>` +
      (st?.状态 === "运行中" ? '<span class="step-elapsed"></span>' : "");
    if (st) chip.title = (st.摘要 || st.状态) + (st.耗时 !== undefined ? ` · 耗时 ${st.耗时} 秒` : "");
    chip.onclick = () => {
      if (liveMode) {
        const running = runningStageIndex();
        if (running === i) {
          followMode = true;
          document.getElementById("follow-btn").hidden = true;
          showLiveStage(i);
          return;
        }
        if (running !== null) {
          followMode = false;
          document.getElementById("follow-btn").hidden = false;
        }
      }
      selectStage(i);
    };
    nav.appendChild(chip);
  });
  updateElapsed();
}

async function selectStage(n) {
  if (!currentRun) return;
  const requestId = ++stageRequest;
  const runId = currentRun;
  markActiveStep(n);
  const view = document.getElementById("stage-view");
  view.innerHTML = '<div class="loading-state" aria-busy="true"><div class="spinner" aria-hidden="true"></div><p>正在读取阶段快照…</p></div>';
  let data;
  try {
    data = await api(`/api/runs/${runId}/stage/${n === 3 ? 2 : n}`);
    // 旧版运行记录把 DITA 产物拆在 stage_5/6/7；stage_2 仍是“编号”快照。
    // 发现旧格式时合并完整产品数据，保证历史记录与新运行使用同一展示路径。
    if ((n === 2 || n === 3) && !Array.isArray(data?.章节)) {
      const [products, packageData, audit] = await Promise.all([
        api(`/api/runs/${runId}/stage/5`),
        api(`/api/runs/${runId}/stage/6`).catch(() => ({})),
        api(`/api/runs/${runId}/stage/7`).catch(() => ({})),
      ]);
      data = { ...products, ...packageData, ...audit };
    }
  } catch (e) {
    if (requestId !== stageRequest) return;
    view.innerHTML = `<div class="error-state"><h1>暂无阶段快照</h1>${currentMeta?.错误 ? `<p>${esc(currentMeta.错误)}</p>` : ""}</div>`;
    return;
  }
  if (requestId !== stageRequest || runId !== currentRun) return;
  if (n === 3) {
    const source = await api(`/api/runs/${runId}/stage/1`).catch(() => null);
    const elements = Array.isArray(source?.元素) ? source.元素 : [];
    sourceStyleById = new Map(elements.map(item => [Number(item.ID), item.样式 || ""]));
    sourceTextById = new Map(elements.map(item => [Number(item.ID), item.段落 || ""]));
  }
  // 原文对照只属于解析阶段；DITA 阶段集中展示结构化结果和合并审核。
  if (n === 1 && !compareMode && !compareOffExplicit) compareMode = true;
  const compare = n === 1 && compareMode;
  view.innerHTML = `
    <article class="stage-container">
      <header class="stage-heading">
        <div class="stage-heading-main">
          <span class="stage-number">${String(n + 1).padStart(2, "0")}</span>
          <div><h2>${STAGES[n]}</h2></div>
        </div>
        <div id="stage-summary" class="stage-summary"></div>
      </header>
      <div class="stage-body${compare ? " compare" : ""}">
        ${compare ? compareToolbar() : ""}
        ${compare ? previewPane() : ""}
        <div id="stage-content" class="stage-content${n === 1 ? " layout-stage" : ""}"></div>
      </div>
    </article>`;
  const content = document.getElementById("stage-content");
  if (compare && previewPages) {
    document.getElementById("page-prev").onclick = () => setPreviewPage(previewPage - 1);
    document.getElementById("page-next").onclick = () => setPreviewPage(previewPage + 1);
  }
  await [render0, render1, render2, renderManualStage][n](content, data);
  const summary = content.querySelector(":scope > .stats-grid");
  if (summary) document.getElementById("stage-summary").appendChild(summary);
  if (compare && previewPages) setPreviewPage(previewPage);
  if (compare && !previewFile) loadPreviewForStage(n, requestId, runId);
}

function compareToolbar() {
  return `<div class="preview-bar compare-toolbar" aria-label="原文与解析结果分页控制">
    <button id="page-prev" class="compare-button" type="button">上一页</button>
    <span id="page-indicator" class="page-indicator"></span>
    <button id="page-next" class="compare-button" type="button">下一页</button>
  </div>`;
}

function previewPane() {
  if (!previewFile) {
    return `<div class="preview-pane preview-loading" aria-live="polite" aria-busy="true">
      <div class="spinner" aria-hidden="true"></div>
      <p>正在准备原文预览…</p>
      <span>Word 文档转换完成后将自动显示原文</span>
    </div>`;
  }
  if (!previewPages) {
    return '<div class="preview-pane"><p class="hint" style="padding:18px">原文 PDF 已生成，但无法读取分页信息。</p></div>';
  }
  return `<div class="preview-pane">
    <div class="preview-scroll"><div class="preview-page" id="preview-page"><img id="preview-img" alt="原文页面"></div></div>
  </div>`;
}

function setPreviewPage(n) {
  if (!previewPages) return;
  const nextPage = Math.min(Math.max(1, n), previewPages);
  const pageChanged = nextPage !== previewPage;
  previewPage = nextPage;
  const img = document.getElementById("preview-img");
  if (!img) return;
  img.src = `/runs/${encodeURIComponent(currentRun)}/preview/page/${previewPage}.png`;
  img.alt = `原文第 ${previewPage} 页`;
  document.getElementById("page-indicator").textContent = `第 ${previewPage} / ${previewPages} 页`;
  document.getElementById("page-prev").disabled = previewPage <= 1;
  document.getElementById("page-next").disabled = previewPage >= previewPages;
  renderRegions();
  syncPageToContent(pageChanged);
}

function renderRegions() {
  const wrap = document.getElementById("preview-page");
  if (!wrap) return;
  wrap.querySelectorAll(".region").forEach(x => x.remove());
  const regions = previewRegions[previewPage] || [];
  for (const r of regions) {
    const div = el("div", "region");
    div.style.left = r.box[0] + "%";
    div.style.top = r.box[1] + "%";
    div.style.width = r.box[2] + "%";
    div.style.height = r.box[3] + "%";
    const ids = r.ids.map(String);
    div.classList.toggle("is-active", ids.some(id => activeElementIds.has(id)));
    div.classList.toggle("is-hovered", ids.some(id => hoveredElementIds.has(id)));
    div.dataset.elements = ids.join(",");
    div.title = "点击定位对应解析结果";
    div.tabIndex = 0;
    div.setAttribute("role", "button");
    div.setAttribute("aria-label", `定位解析块 ${ids.join("、")}`);
    div.onmouseenter = () => hoverElements(ids);
    div.onmouseleave = clearHoveredElements;
    div.onfocus = () => hoverElements(ids);
    div.onblur = clearHoveredElements;
    div.onclick = () => scrollRightTo(ids);
    div.onkeydown = event => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      scrollRightTo(ids);
    };
    wrap.appendChild(div);
  }
}

function hoverElements(ids) {
  hoveredElementIds = new Set(ids.map(String));
  document.querySelectorAll("#preview-page .region").forEach(r => {
    r.classList.toggle("is-hovered", r.dataset.elements.split(",").some(id => hoveredElementIds.has(id)));
  });
  const content = document.getElementById("stage-content");
  if (!content) return;
  content.querySelectorAll(".is-hovered").forEach(x => x.classList.remove("is-hovered"));
  for (const id of hoveredElementIds) {
    content.querySelector(`[data-element-id="${id}"]`)?.classList.add("is-hovered");
    content.querySelectorAll("[data-src]").forEach(n => {
      if (n.dataset.src.split(",").includes(id)) n.classList.add("is-hovered");
    });
  }
}

function clearHoveredElements() {
  hoveredElementIds.clear();
  document.querySelectorAll(".is-hovered").forEach(x => x.classList.remove("is-hovered"));
}

function wireHover(content) {
  content.querySelectorAll("[data-element-id], [data-src]").forEach(n => {
    if (n.dataset.hoverWired) return;
    n.dataset.hoverWired = "1";
    const ids = () => n.dataset.elementId ? [n.dataset.elementId] : n.dataset.src.split(",");
    n.onmouseenter = () => hoverElements(ids());
    n.onmouseleave = clearHoveredElements;
  });
}

function selectElements(ids) {
  activeElementIds = new Set(ids.map(String));
  renderRegions();
  const content = document.getElementById("stage-content");
  if (!content) return;
  content.querySelectorAll(".is-active").forEach(x => x.classList.remove("is-active"));
  for (const id of activeElementIds) {
    content.querySelector(`[data-element-id="${id}"]`)?.classList.add("is-active");
    content.querySelectorAll("[data-src]").forEach(n => {
      if (n.dataset.src.split(",").includes(id)) n.classList.add("is-active");
    });
  }
}

function scrollRightTo(ids) {
  selectElements(ids);
  const content = document.getElementById("stage-content");
  if (!content) return;
  for (const id of ids) {
    const target = content.querySelector(`[data-element-id="${id}"]`) ||
      [...content.querySelectorAll("[data-src]")].find(n => n.dataset.src.split(",").includes(id));
    if (!target) continue;
    let p = target.parentElement;
    while (p) {
      if (p.tagName === "DETAILS") p.open = true;
      p = p.parentElement;
    }
    const panel = target.closest("[role='tabpanel']");
    if (panel && panel.hidden) {
      const panels = [...content.querySelectorAll("[role='tabpanel']")];
      const idx = panels.indexOf(panel);
      if (idx >= 0) content.querySelectorAll(".tab")[idx]?.click();
    }
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    return;
  }
}

function jumpPreviewFor(elementIds) {
  if (!compareMode) return;
  for (const id of elementIds) {
    const page = previewPageMap[id];
    if (page) {
      setPreviewPage(page);
      return;
    }
  }
}

function pageElementIds(page) {
  return new Set(
    Object.entries(previewPageMap)
      .filter(([id, firstPage]) => (previewPageGroups[id] || [firstPage]).includes(page))
      .map(([id]) => id),
  );
}

function syncPageToContent(scrollToHit = true) {
  if (!compareMode || !previewPages) return;
  const content = document.getElementById("stage-content");
  if (!content) return;
  const ids = pageElementIds(previewPage);
  content.querySelectorAll(".page-hit").forEach(x => x.classList.remove("page-hit"));
  content.querySelectorAll(".page-hidden").forEach(x => x.classList.remove("page-hidden"));

  if (![1, 2].includes(currentStage)) return;

  // 无文字的图片/表格可能没有文本页码映射，跟随前一个已映射元素显示。
  if (currentStage === 1) {
    let previousPage = null;
    for (const row of content.querySelectorAll(".layout-el")) {
      const mappedPage = previewPageMap[row.dataset.elementId];
      const mappedPages = previewPageGroups[row.dataset.elementId] || (mappedPage ? [mappedPage] : []);
      if (mappedPages.includes(previewPage)) previousPage = previewPage;
      else if (mappedPages.length) previousPage = mappedPages.at(-1);
      else if (row.classList.contains("has-inline-preview") && previousPage === previewPage) ids.add(row.dataset.elementId);
    }
  }

  let hits = [];
  if (currentStage === 1) {
    hits = [...content.querySelectorAll(".layout-el")].filter(r => ids.has(r.dataset.elementId));
  } else {
    hits = [...content.querySelectorAll("[data-src]")]
      .filter(n => n.dataset.src.split(",").some(id => ids.has(id)));
  }
  hits.forEach(n => n.classList.add("page-hit"));

  // 对照模式默认"仅看本页"：右栏只保留当前页的内容，左右一一对应
  if (pageFilterOn) {
    if (currentStage === 1) {
      content.querySelectorAll(".layout-el")
        .forEach(r => r.classList.toggle("page-hidden", !ids.has(r.dataset.elementId)));
    } else {
      content.querySelectorAll(".blk, tr[data-src]")
        .forEach(n => n.classList.toggle("page-hidden", !n.classList.contains("page-hit")));
      [...content.querySelectorAll("details.node")].reverse()
        .forEach(n => n.classList.toggle("page-hidden", !n.querySelector(".page-hit")));
      [...content.querySelectorAll(".manual-topic")].reverse()
        .forEach(n => n.classList.toggle("page-hidden", !n.querySelector(".page-hit")));
    }
  }

  if (hits.length && scrollToHit) {
    const target = currentStage === 2
      ? hits.find(h => !h.closest("[role='tabpanel']")?.hidden) || hits[0]
      : hits[0];
    if (currentStage === 2) {
      let p = target.parentElement;
      while (p) {
        if (p.tagName === "DETAILS") p.open = true;
        p = p.parentElement;
      }
    }
    target.scrollIntoView({ block: "center", behavior: "smooth" });
  }
  wireHover(content);
}

async function enableCompare() {
  if (!previewFile) {
    const r = await api(`/api/runs/${currentRun}/preview`, { method: "POST" });
    previewFile = r.文件;
    previewPages = r.页数 || 0;
    previewPageMap = r.元素页 || {};
    previewPageGroups = r.元素页组 || {};
    previewRegions = r.区域 || {};
    previewPage = 1;
  }
  compareMode = true;
}

async function loadPreviewForStage(n, requestId, runId) {
  try {
    await enableCompare();
    if (runId !== currentRun) return;
    if (currentStage === 1 && compareMode) {
      await selectStage(currentStage);
    }
  } catch (err) {
    if (requestId !== stageRequest || runId !== currentRun || currentStage !== n) return;
    compareMode = false;
    compareOffExplicit = true;
    showToast(`原文预览不可用：${err.message}`, true);
    await selectStage(n);
  }
}

/* ---------- 通用小件 ---------- */

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}

function esc(s) {
  return (s ?? "").toString()
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function fieldLabel(value, fallback = "未标注样式") {
  const raw = (value || "").trim();
  if (!raw) return fallback;
  const label = FIELD_LABELS[raw.toLowerCase()];
  return label ? `${label}（${raw}）` : raw;
}

function chips(view, pairs) {
  const row = el("div", "stats-grid");
  for (const [label, value, cls] of pairs) {
    const card = el("div", `stat-card ${cls || ""}`);
    card.appendChild(el("span", "stat-value", esc(value ?? 0)));
    card.appendChild(el("span", "stat-label", esc(label)));
    row.appendChild(card);
  }
  view.appendChild(row);
}

function tableScroll(tbl) {
  const wrap = el("div", "table-scroll");
  wrap.appendChild(tbl);
  return wrap;
}

/* ---------- 各阶段渲染 ---------- */

function render0(view, d) {
  const card = el("div", "card");
  card.appendChild(el("div", "alert " + (d.错误 ? "error" : "ok"), d.错误 ? `⛔ ${esc(d.错误)}` : `✓ 文件校验通过，识别为 ${esc(d.结果)} 文档`));
  const tbl = el("table", "kv");
  tbl.innerHTML = `
    <tr><td>文件</td><td>${esc(d.文件 || "")}</td></tr>
    <tr><td>大小</td><td>${d.大小 ? (d.大小 / 1048576).toFixed(1) + " MB" : "-"}</td></tr>
    <tr><td>文件头</td><td><code>${esc(d.文件头 || "")}</code></td></tr>
    ${d.转换 ? `<tr><td>转换</td><td>${esc(d.转换)}</td></tr>` : ""}`;
  card.appendChild(tbl);
  view.appendChild(card);
  if (d.错误) return;
  const work = el("div", "card");
  work.appendChild(el("h3", "", "校验做了哪些工作"));
  const list = el("ul", "check-list");
  const items = [
    `读取文件头 16 字节：<code>${esc(d.文件头 || "")}</code>`,
    `格式识别：${esc(d.结果)} 文档`,
    "亿赛通密文检查：未发现加密特征",
  ];
  if (d.转换) items.push(esc(d.转换));
  items.forEach(text => list.appendChild(el("li", "", `✓ ${text}`)));
  work.appendChild(list);
  view.appendChild(work);
}

function appendParaParts(parent, parts, fallback = "") {
  for (const part of parts?.length ? parts : [{ type: "text", text: fallback }]) {
    if (part.type === "image") {
      const image = el("img", "inline-img");
      image.src = `/runs/${currentRun}/img/${encodeURIComponent(part.file)}`;
      image.alt = "原文行内图片";
      image.loading = "lazy";
      parent.appendChild(image);
    } else {
      parent.appendChild(document.createTextNode(part.text || ""));
    }
  }
}

function layoutRow(e, editable = false, legacyBlocks = []) {
  const row = el("div", `layout-el ${e.类型}${e.层级 !== undefined ? " heading" : ""}`);
  row.dataset.elementId = e.ID;
  let badge;
  if (e.类型 === "table") {
    const [label, cls] = CLASS_BADGE[e.分类] || [e.分类 || "table", "b-layout"];
    badge = `<span class="badge ${cls}">${esc(label)}</span>`;
  } else {
    badge = `<span class="badge b-data">${esc(fieldLabel("p"))}</span>`;
  }
  row.innerHTML = `<span class="el-id">#${e.ID}</span>${badge}` +
    (e.编号 ? `<span class="el-num">${esc(e.编号)}</span>` : "") +
    `<span class="el-style" title="${esc(fieldLabel(e.样式))}">${esc(fieldLabel(e.样式))}</span>` +
    `<span class="el-text"></span>` +
    (e.图片 ? `<span class="el-imgs">图 ${e.图片}</span>` : "");
  appendParaParts(row.querySelector(".el-text"), e.parts, e.内容 || (e.图片 ? `［${e.图片} 张图］` : "（空）"));
  if (e.类型 === "table" && e.依据) row.title = `判定依据：${e.依据}`;
  if (e.类型 === "table" && editable) {
    const picker = el("select", "kind-picker");
    picker.title = "手工改标：修改分类后自动重跑，文档树 / 故障码 / 保养规则随之更新";
    picker.appendChild(new Option("自动判定", ""));
    for (const [key, [name]] of Object.entries(CLASS_BADGE)) picker.appendChild(new Option(name, key));
    picker.value = e.人工 ? e.分类 : "";
    picker.onchange = () => applyTableOverride(e.ID, picker.value);
    picker.onclick = event => event.stopPropagation();
    row.appendChild(picker);
  }

  const previews = [];
  if (Array.isArray(e.网格) && e.网格.length) {
    previews.push({
      type: "table", header: e.网格[0], rows: e.网格.slice(1),
      cell_images: e.cell_images, col_spans: e.col_spans, row_spans: e.row_spans,
    });
  }
  const hasInlineImages = e.parts?.some(part => part.type === "image") && e.parts.some(part => part.type === "text" && part.text.trim());
  const hasCellImages = e.cell_images?.some(row => row.some(cell => cell.length));
  if (!hasInlineImages && !hasCellImages) {
    for (const file of e.图片文件 || []) previews.push({ type: "image", file });
  }
  if (!previews.length) previews.push(...legacyBlocks);
  if (previews.length) row.classList.add("has-inline-preview");
  for (const block of previews) {
    const preview = blockView(block);
    preview.classList.add("source-block-preview");
    row.appendChild(preview);
  }
  return row;
}

async function legacySourceBlocks(elements) {
  const needed = elements.some(e => (e.类型 === "table" && !e.网格) || (e.图片 && !e.图片文件));
  if (!needed) return new Map();
  let products = await api(`/api/runs/${currentRun}/stage/2`).catch(() => null);
  if (!Array.isArray(products?.章节)) {
    products = await api(`/api/runs/${currentRun}/stage/5`).catch(() => null);
  }
  const result = new Map();
  for (const section of products?.章节 || []) {
    for (const block of section.blocks || []) {
      if (!["table", "warning", "image"].includes(block.type)) continue;
      for (const id of block.src || []) {
        if (!result.has(id)) result.set(id, []);
        result.get(id).push(block);
      }
    }
  }
  return result;
}

async function render1(view, d) {
  const conflicts = d.冲突 || [];
  chips(view, [
    ["元素", d.元素总数],
    ["段落", d.段落],
    ["表格", d.表格],
    ["标题", d.标题数],
    ["图片锚点", d.图片锚点],
    ["提取图片", d.图片数],
    ["目录冲突", conflicts.length, conflicts.length ? "bad" : "good"],
  ]);
  const legacy = await legacySourceBlocks(d.元素);
  const stream = el("div", "layout-stream");
  d.元素.forEach(e => stream.appendChild(layoutRow(e, true, legacy.get(e.ID) || [])));
  if (compareMode) {
    stream.querySelectorAll(".layout-el").forEach(row => {
      const id = row.dataset.elementId;
      if (previewPageMap[id]) {
        row.classList.add("traceable");
        const jump = `点击跳到原文第 ${previewPageMap[id]} 页`;
        row.title = row.title ? `${row.title}\n${jump}` : jump;
        row.onclick = () => {
          selectElements([id]);
          jumpPreviewFor([id]);
        };
      }
    });
  }
  view.appendChild(stream);
}

async function applyTableOverride(elementId, kind) {
  setRunStatus("running", "正在保存改标");
  try {
    await api(`/api/runs/${currentRun}/overrides`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ 元素: elementId, 分类: kind || null }),
    });
    const r = await api(`/api/runs/${currentRun}/rerun`, { method: "POST" });
    beginLiveRun(r.run_id);
    showToast(kind ? "已保存改标，正在带改标重跑…" : "已恢复自动判定，正在重跑…");
  } catch (err) {
    setRunStatus("error", "重跑失败");
    showToast(`改标失败：${err.message}`, true);
  }
}

async function render2(view, d) {
  const docCode = currentMeta?.文档;
  const golden = GOLDEN[docCode] || {};
  const topics = Array.isArray(d.章节) ? d.章节 : [];
  const faultCodes = Array.isArray(d.故障码) ? d.故障码 : [];
  const maintenanceRules = Array.isArray(d.保养规则) ? d.保养规则 : [];
  const literalTitles = Array.isArray(d.标题) ? d.标题 : [];
  const auditCount = (d.条目 || []).length;
  const topicCount = topics.length || literalTitles.length;
  chips(view, [
    ["Topic", topicCount, topicCount === golden.章节 ? "good" : (golden.章节 ? "bad" : "")],
    ["FaultCode", faultCodes.length, faultCodes.length === golden.故障码 ? "good" : (golden.故障码 ? "bad" : "")],
    ["MaintenanceRule", maintenanceRules.length],
    ["审核条目", auditCount, auditCount ? "bad" : "good"],
  ]);

  const lineage = el("section", "dita-lineage");
  lineage.innerHTML = `<div class="dita-lineage-heading">
      <h3>解析结果如何生成 DITA 标准数据</h3>
      <p>解析元素经规则转换为结构化产品；内容块仍在数据中保留来源元素 ID。</p>
    </div>
    <div class="dita-lineage-steps">
      <div class="dita-lineage-step"><b>1 · 解析元素</b><span>${layoutCountText(d)} 个段落、表格和图片元素</span></div>
      <div class="dita-lineage-step"><b>2 · 规则转换</b><span>标题建树，正文归块，故障表和周期内容分别抽取</span></div>
      <div class="dita-lineage-step"><b>3 · DITA 产品</b><span>${topicCount} Topic · ${faultCodes.length} FaultCode · ${maintenanceRules.length} MaintenanceRule</span></div>
    </div>
    <div class="dita-lineage-rules">
      <span>标题 → Topic</span><span>段落/列表/步骤/图片/表格 → Topic 内容块</span><span>故障码表 → FaultCode</span><span>周期规则 → MaintenanceRule</span><span>最终写入 manifest、审核清单和数据包</span>
    </div>`;
  view.appendChild(lineage);

  const right = el("div", "trace-products");
  view.appendChild(right);

  const tabs = el("div", "tabs");
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "DITA 标准数据");
  const pages = {};
  const counts = { 段落合并: undefined, Topics: topicCount, FaultCodes: faultCodes.length, MaintenanceRules: maintenanceRules.length,
                   数据包: undefined, 审核清单: auditCount };
  Object.keys(counts).forEach((name, i) => {
    const count = counts[name] !== undefined ? `<span class="tab-count">${counts[name]}</span>` : "";
    const btn = el("button", "tab" + (i === 0 ? " on" : ""), `${name}${count}`);
    btn.type = "button";
    btn.setAttribute("role", "tab");
    btn.setAttribute("aria-selected", String(i === 0));
    btn.onclick = () => {
      tabs.querySelectorAll(".tab").forEach(b => {
        b.classList.remove("on");
        b.setAttribute("aria-selected", "false");
      });
      btn.classList.add("on");
      btn.setAttribute("aria-selected", "true");
      Object.values(pages).forEach(p => { p.hidden = true; });
      pages[name].hidden = false;
    };
    tabs.appendChild(btn);
  });
  right.appendChild(tabs);

  Object.keys(counts).forEach((name, i) => {
    pages[name] = el("div");
    pages[name].hidden = i !== 0;
    pages[name].setAttribute("role", "tabpanel");
    right.appendChild(pages[name]);
  });

  if (topics.length) {
    renderTree(pages.Topics, topics);
  } else {
    renderLiteralTitles(pages.Topics, literalTitles);
  }
  await renderMergeReview(pages.段落合并);
  renderFaultCodes(pages.FaultCodes, faultCodes);
  renderRules(pages.MaintenanceRules, maintenanceRules);
  renderPackage(pages.数据包, d);
  renderAuditList(pages.审核清单, d.条目 || []);
}

function mergeTextPanel(title, text, cls = "") {
  const panel = el("div", `merge-text-panel ${cls}`);
  panel.appendChild(el("span", "merge-text-label", esc(title)));
  panel.appendChild(el("p", "", esc(text)));
  return panel;
}

async function renderMergeReview(root) {
  root.replaceChildren();
  const review = el("section", "merge-review");
  const heading = el("div", "merge-review-heading");
  const copy = el("div", "");
  copy.appendChild(el("h3", "", "段落合并审核"));
  copy.appendChild(el("p", "", "规则筛选可能的错误断段，再由 JEV 判断。只有确认后才会合并原文块并重新生成派生产物。"));
  heading.appendChild(copy);
  const generate = el("button", "compare-button", "生成 JEV 合并建议");
  generate.type = "button";
  heading.appendChild(generate);
  review.appendChild(heading);
  root.appendChild(review);

  let data;
  try {
    data = await api(`/api/runs/${currentRun}/merge-suggestions`);
  } catch (err) {
    review.appendChild(el("p", "alert error", `无法读取合并建议：${esc(err.message)}`));
    generate.disabled = true;
    return;
  }
  const suggestions = Array.isArray(data.建议) ? data.建议 : [];
  review.appendChild(el("p", "merge-model-note", `模型：${esc(data.模型 || "autotrust/JEV-27B-VL")} · 建议 ${suggestions.length} 条 · 不会自动修改解析结果`));
  generate.onclick = () => generateMergeSuggestions(root, generate);
  if (!suggestions.length) {
    review.appendChild(el("div", "merge-empty", "尚未生成建议。点击上方按钮后，JEV 会检查符合规则的相邻段落。"));
    return;
  }
  const list = el("div", "merge-suggestion-list");
  for (const suggestion of suggestions) {
    const status = suggestion.状态 || "pending";
    const card = el("article", `merge-suggestion ${status}`);
    const head = el("div", "merge-suggestion-heading");
    const title = `${suggestion.section_title || suggestion.section_id || "未命名章节"} · 元素 #${suggestion.previous.element_id} + #${suggestion.current.element_id}`;
    head.appendChild(el("h4", "", esc(title)));
    const statusText = { pending: "待确认", confirmed: "已确认", rejected: "已保留分段", error: "判断失败" }[status] || status;
    head.appendChild(el("span", `merge-status ${status}`, statusText));
    card.appendChild(head);
    const evidence = typeof suggestion.probability === "number"
      ? `JEV 接续概率 ${(suggestion.probability * 100).toFixed(1)}% · ${suggestion.rule}`
      : suggestion.错误 || "没有可用的 JEV 概率";
    card.appendChild(el("p", "merge-evidence", esc(evidence)));
    const preview = el("div", "merge-preview-grid");
    preview.appendChild(mergeTextPanel(`合并前 · 前段 #${suggestion.previous.element_id}`, suggestion.previous.text));
    preview.appendChild(mergeTextPanel(`合并前 · 后段 #${suggestion.current.element_id}`, suggestion.current.text));
    preview.appendChild(mergeTextPanel("用户确认后的合并结果", suggestion.merged_text, "merge-result"));
    card.appendChild(preview);
    if (status === "pending") {
      const actions = el("div", "merge-actions");
      const reject = el("button", "compare-button", "保留分段");
      reject.type = "button";
      reject.onclick = () => reviewMergeSuggestion(root, suggestion.id, false, card);
      const confirm = el("button", "compare-button on", "确认合并并重跑");
      confirm.type = "button";
      confirm.onclick = () => reviewMergeSuggestion(root, suggestion.id, true, card);
      actions.appendChild(reject);
      actions.appendChild(confirm);
      card.appendChild(actions);
    } else if (status === "confirmed") {
      card.appendChild(el("p", "hint", "已保存用户确认；合并通过人工规则重跑应用，合并前快照已保留。"));
    }
    list.appendChild(card);
  }
  review.appendChild(list);
}

async function generateMergeSuggestions(root, button) {
  button.disabled = true;
  button.textContent = "JEV 正在判断…";
  root.setAttribute("aria-busy", "true");
  try {
    await api(`/api/runs/${currentRun}/merge-suggestions`, { method: "POST" });
    await renderMergeReview(root);
    showToast("合并建议已生成，请逐项查看预览后确认");
  } catch (err) {
    showToast(`生成合并建议失败：${err.message}`, true);
    await renderMergeReview(root);
  } finally {
    root.removeAttribute("aria-busy");
  }
}

async function reviewMergeSuggestion(root, suggestionId, confirmed, card) {
  card.querySelectorAll("button").forEach(button => { button.disabled = true; });
  try {
    await api(`/api/runs/${currentRun}/merge-suggestions/${encodeURIComponent(suggestionId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ 确认: confirmed }),
    });
    if (!confirmed) {
      await renderMergeReview(root);
      showToast("已保留原来的分段");
      return;
    }
    setRunStatus("running", "正在应用确认的合并");
    const r = await api(`/api/runs/${currentRun}/rerun`, { method: "POST" });
    beginLiveRun(r.run_id);
    showToast("已确认合并，正在重新生成手册和数据包…");
  } catch (err) {
    showToast(`合并审核失败：${err.message}`, true);
    await renderMergeReview(root);
  }
}

function renderManualStage(view, d) {
  const topics = normalizeManualTopics(Array.isArray(d.章节) ? d.章节 : []);
  const reader = el("section", "manual-reader");
  if (!topics.length) {
    reader.appendChild(el("p", "hint", "当前 DITA 数据没有可展示的 Topic。"));
  } else {
    manualReaderTopics = topics;
    manualReaderIndex = 0;
    renderManualReader(reader);
  }
  view.appendChild(reader);
}

function renderManualReader(root) {
  root.innerHTML = "";
  const toc = el("aside", "manual-reader-toc");
  toc.appendChild(el("div", "manual-reader-toc-title", "手册目录"));
  const tocList = el("div", "manual-reader-toc-list");
  manualReaderTopics.forEach((topic, index) => {
    const shownNo = topic.显示章节号 || topic.章节号;
    const item = el("button", "manual-reader-toc-item", `${esc(shownNo ? `${shownNo} ` : "")}${esc(topic.标题)}`);
    item.type = "button";
    item.title = topic.面包屑 || topic.标题;
    item.style.paddingLeft = `${14 + Math.max(0, (topic.层级 || 1) - 1) * 14}px`;
    item.dataset.index = index;
    item.onclick = () => focusManualTopic(root, index);
    tocList.appendChild(item);
  });
  toc.appendChild(tocList);

  const main = el("main", "manual-reader-main");
  const toolbar = el("div", "manual-reader-toolbar");
  const prev = el("button", "compare-button", "上一页");
  const next = el("button", "compare-button", "下一页");
  const indicator = el("span", "page-indicator", `第 ${manualReaderIndex + 1} / ${manualReaderTopics.length} 节`);
  prev.type = next.type = "button";
  prev.disabled = manualReaderIndex <= 0;
  next.disabled = manualReaderIndex >= manualReaderTopics.length - 1;
  prev.onclick = () => focusManualTopic(root, manualReaderIndex - 1);
  next.onclick = () => focusManualTopic(root, manualReaderIndex + 1);
  toolbar.append(prev, indicator, next);
  main.appendChild(toolbar);

  const documentView = el("div", "manual-reading-document");
  manualReaderTopics.forEach((topic, index) => {
    const section = el("section", "manual-reading-section");
    section.dataset.topicIndex = index;
    const heading = el(`h${Math.min(4, Math.max(2, (topic.层级 || 1) + 1))}`, "manual-reading-title");
    const shownNo = topic.显示章节号 || topic.章节号;
    heading.innerHTML = `${esc(shownNo ? `${shownNo} ` : "")}${esc(topic.标题)}`;
    section.appendChild(heading);
    appendManualBlocks(section, topic.blocks || []);
    documentView.appendChild(section);
  });
  main.appendChild(documentView);
  root.append(toc, main);
  updateManualReaderControls(root);
}

function normalizeManualTopics(topics) {
  const tocIndex = topics.findIndex(topic => (topic.标题 || "").trim() === "目录");
  if (tocIndex > 0) {
    const preface = topics[0];
    if (preface && /前\s*言/.test(preface.标题 || "")) {
      topics.slice(1, tocIndex).forEach(topic => preface.blocks.push(...(topic.blocks || [])));
      topics = [preface, ...topics.slice(tocIndex + 1)];
    }
  }
  const normalized = [];
  topics.forEach(topic => {
    const title = (topic.标题 || "").trim();
    // 旧快照偶尔会额外生成一个无编号、无内容的重复 Topic（如再次出现“电气系统”）。
    // 这类节点不代表章节，直接丢弃，避免目录中出现孤立重复项。
    if (!topic.章节号 && !topic.blocks?.length && normalized.some(item => (item.标题 || "").trim() === title)) {
      return;
    }
    const chapterNo = String(topic.章节号 || "").trim();
    const numericLevel = /^\d+(?:\.\d+)*$/.test(chapterNo)
      ? chapterNo.split(".").length
      : null;
    if (numericLevel !== null && topic.层级 !== numericLevel) {
      topic = { ...topic, 层级: numericLevel };
    }
    const simpleNumber = topic.章节号 && !String(topic.章节号).includes(".");
    const sourceStyle = (topic.src || []).map(id => sourceStyleById.get(Number(id))).find(Boolean) || "";
    const sourceText = (topic.src || []).map(id => sourceTextById.get(Number(id))).find(Boolean) || "";
    const isHeadingStyle = /^(?:heading|subtitle)\b/i.test(sourceStyle.trim());
    if (chapterNo && /^\s*§/.test(sourceText) && !String(topic.章节号).startsWith("§")) {
      topic = { ...topic, 显示章节号: `§${chapterNo}` };
    }
    // 旧版 B 手册快照把正文步骤（“1 拧开…”，“2 用钢丝钳…”）
    // 误写成了一级 Topic。它们的编号在章节号字段，标题本身通常是
    // 18～30 字的动作句，不能只依赖 24 字阈值；多级编号仍是真正章节。
    const sentenceLike = /[，。；：:、（）()！？!?]/.test(title);
    const isBodyNumberedParagraph = /^[）)】〕]/.test(title)
      || (simpleNumber && sourceStyle && !isHeadingStyle)
      || (/^\d+\s+/.test(title) && (title.length >= 18 || sentenceLike));
    if (isBodyNumberedParagraph && normalized.length) {
      normalized[normalized.length - 1].blocks.push(...(topic.blocks || []));
      return;
    }
    normalized.push({ ...topic, blocks: [...(topic.blocks || [])] });
  });
  // 旧快照中的 parent/面包屑会因重复 section_id 指向前一个正文条目。
  // 目录展示按实际层级重新计算路径，避免出现“13）测量液压压力 > 2 如何阅读…”这类错链。
  const stack = [];
  return normalized.map(topic => {
    const level = Math.max(1, Number(topic.层级) || 1);
    stack.length = Math.min(stack.length, level - 1);
    stack.push(topic.标题 || "");
    return { ...topic, 面包屑: stack.filter(Boolean).join(" > ") };
  });
}

function updateManualReaderControls(root) {
  root.querySelectorAll(".manual-reader-toc-item").forEach((item, index) => {
    item.classList.toggle("on", index === manualReaderIndex);
  });
  const indicator = root.querySelector(".manual-reader-toolbar .page-indicator");
  const buttons = root.querySelectorAll(".manual-reader-toolbar .compare-button");
  if (indicator) indicator.textContent = `第 ${manualReaderIndex + 1} / ${manualReaderTopics.length} 节`;
  if (buttons[0]) buttons[0].disabled = manualReaderIndex <= 0;
  if (buttons[1]) buttons[1].disabled = manualReaderIndex >= manualReaderTopics.length - 1;
}

function focusManualTopic(root, index) {
  manualReaderIndex = Math.min(Math.max(0, index), manualReaderTopics.length - 1);
  updateManualReaderControls(root);
  root.querySelector(`.manual-reading-section[data-topic-index="${manualReaderIndex}"]`)
    ?.scrollIntoView({ block: "start", behavior: "smooth" });
}

function layoutCountText(data) {
  const count = data?.元素总数;
  return Number.isFinite(Number(count)) ? Number(count).toLocaleString("zh-CN") : "解析阶段";
}

function appendManualBlocks(parent, blocks) {
  for (const block of blocks) {
    const rendered = blockView(block);
    if (block.src?.length) rendered.dataset.src = block.src.join(",");
    // 技术元素标签（如 p、fig、table）用于解析/溯源视图，手册正文只呈现实际内容。
    rendered.querySelectorAll(".el-tag").forEach(tag => tag.remove());
    parent.appendChild(rendered);
  }
}

function renderTree(root, sections) {
  const byId = {};
  const seen = new Set();
  const nodes = [];
  for (const s of sections) {
    const node = { ...s, children: [] };
    // 重复 section_id 是数据缺陷（如 B 手册字面编号重复）：只登记首个，
    // 其余平铺展示，避免按 id 挂接成环把渲染递归打爆。
    if (!seen.has(s.section_id)) {
      byId[s.section_id] = node;
      seen.add(s.section_id);
    }
    nodes.push(node);
  }
  const tops = [];
  for (const node of nodes) {
    const parent = node.parent ? byId[node.parent] : null;
    if (parent && parent !== node) parent.children.push(node);
    else tops.push(node);
  }
  const frag = document.createDocumentFragment();
  tops.forEach(t => frag.appendChild(treeNode(t)));
  root.appendChild(frag);
}

function renderLiteralTitles(root, titles) {
  if (!titles.length) {
    root.appendChild(el("p", "hint", "该手册未生成可展示的章节树。"));
    return;
  }
  const stream = el("div", "layout-stream");
  titles.forEach((title, index) => {
    const row = el("div", "layout-el heading");
    row.innerHTML = `<span class="el-id">#${index + 1}</span><span class="el-style">${esc(title.样式 || "标题")}</span><span class="el-text">${esc(title.标题 || "")}</span>`;
    stream.appendChild(row);
  });
  root.appendChild(stream);
}

const BLOCK_EL = { para: "p", warning: "note", list: "ul", steps: "steps", image: "fig", table: "simpletable" };
const NOTE_TYPE = { 注意: "caution", 警告: "warning", 危险: "danger" };

/* 按手册 §2.2 的 JSON 绑定把产物块序列化为 DITA 元素对象 */
function blockToDitaJson(b) {
  switch (b.type) {
    case "para":
      return b.parts?.length ? {
        el: "p",
        parts: b.parts.map(part => part.type === "image"
          ? { el: "image", href: `img/${part.file}` }
          : { el: "text", text: part.text }),
      } : { el: "p", text: b.text };
    case "warning":
      return { el: "note", type: NOTE_TYPE[b.level] || "notice", text: b.text };
    case "list":
      return { el: "ul", items: (b.items || []).map(t => ({ el: "li", text: t })) };
    case "steps":
      return { el: "steps", items: (b.items || []).map(t => ({ el: "step", cmd: t })) };
    case "image":
      return {
        el: "fig",
        title: b.图号 || "",
        image: { href: `img/${b.file}`, alt: b.题注 || b.图号 || "" },
      };
    case "table":
      return {
        el: "simpletable", sthead: b.header || [], strow: b.rows || [],
        cell_images: b.cell_images || [], col_spans: b.col_spans || [], row_spans: b.row_spans || [],
      };
    default:
      return { el: b.type };
  }
}

/* 章节 → topic：根 el 由内容确定（含步骤序列为 task，否则 concept），
   id/props 取自产物的稳定锚（section_id / 章节号 / seq / 面包屑）。 */
function topicToDitaJson(node) {
  return {
    el: node.blocks.some(b => b.type === "steps") ? "task" : "concept",
    id: node.section_id,
    title: node.标题,
    props: {
      docCode: currentMeta?.文档,
      chapterNo: node.章节号,
      seq: node.seq,
      breadcrumb: node.面包屑,
    },
    body: node.blocks.map(blockToDitaJson),
  };
}

function treeNode(node) {
  const det = el("details", "node");
  const sum = el("summary", "",
    `<code>${esc(node.section_id)}</code> ` +
    (node.章节号 ? `<code>${esc(node.章节号)}</code> ` : "") +
    `${esc(node.标题)} <span class="count">${node.blocks.length} 块</span>`);
  if (node.src?.length) sum.dataset.src = node.src.join(",");
  const jsonBtn = el("button", "json-toggle", "JSON");
  jsonBtn.type = "button";
  jsonBtn.title = "查看该 topic 的规范 JSON";
  jsonBtn.onclick = event => {
    event.stopPropagation();
    pre.hidden = !pre.hidden;
    jsonBtn.classList.toggle("on", !pre.hidden);
  };
  sum.appendChild(jsonBtn);
  det.appendChild(sum);
  const pre = el("pre", "json-view", esc(JSON.stringify(topicToDitaJson(node), null, 2)));
  pre.hidden = true;
  det.appendChild(pre);
  const body = el("div", "nodebody");
  node.blocks.forEach(b => {
    const v = blockView(b);
    if (b.src?.length) v.dataset.src = b.src.join(",");
    body.appendChild(v);
  });
  det.appendChild(body);
  node.children.forEach(c => det.appendChild(treeNode(c)));
  return det;
}

function blockView(b) {
  const tag = `<span class="el-tag">${BLOCK_EL[b.type] || b.type}</span>`;
  switch (b.type) {
    case "para": {
      const view = el("p", "blk para", tag);
      appendParaParts(view, b.parts, b.text);
      return view;
    }
    case "warning": {
      const cls = { 注意: "w-note", 警告: "w-warn", 危险: "w-danger" }[b.level] || "w-note";
      return el("div", "blk warnbox " + cls, `${tag}<b>${esc(b.level)}</b>${esc(b.text)}`);
    }
    case "list":
      return el("ul", "blk list", b.items.map(i => `<li>${esc(i)}</li>`).join(""));
    case "steps":
      return el("ol", "blk steps", b.items.map(i => `<li>${esc(i)}</li>`).join(""));
    case "image": {
      const fig = el("figure", "blk imgblk");
      const img = el("img");
      img.src = `/runs/${currentRun}/img/${encodeURIComponent(b.file)}`;
      img.alt = b.题注 || b.图号 || "解析图片";
      img.loading = "lazy";
      fig.appendChild(img);
      fig.appendChild(el("figcaption", "", `${tag}${esc(b.图号 || "")} ${esc(b.题注 || "")}`));
      return fig;
    }
    case "table": {
      const wrap = el("div", "blk tblwrap");
      const tbl = el("table", "grid mini");
      const grid = [b.header || [], ...(b.rows || [])];
      grid.forEach((values, rowIndex) => {
        const tr = el("tr");
        let colIndex = 0;
        while (colIndex < values.length) {
          const rowSpan = b.row_spans?.[rowIndex]?.[colIndex] ?? 1;
          if (rowSpan === 0) {
            colIndex += 1;
            continue;
          }
          const colSpan = b.col_spans?.[rowIndex]?.[colIndex] ?? 1;
          const cell = el(rowIndex === 0 ? "th" : "td");
          cell.colSpan = colSpan;
          cell.rowSpan = rowSpan;
          cell.textContent = values[colIndex] || "";
          for (const file of b.cell_images?.[rowIndex]?.[colIndex] || []) {
            const image = el("img", "table-cell-img");
            image.src = `/runs/${currentRun}/img/${encodeURIComponent(file)}`;
            image.alt = "表格单元格图片";
            image.loading = "lazy";
            cell.appendChild(image);
          }
          tr.appendChild(cell);
          colIndex += colSpan;
        }
        tbl.appendChild(tr);
      });
      wrap.appendChild(tbl);
      const box = el("div", "blk");
      box.appendChild(el("div", "", tag));
      box.appendChild(wrap);
      return box;
    }
    default:
      return el("p", "blk unknown", `未知块类型：${esc(b.type)}`);
  }
}

function renderFaultCodes(root, codes) {
  if (!codes.length) {
    root.appendChild(el("p", "hint", "本文档未抽得故障码（或故障表分类未命中，可在解析界面手工改标后重跑）。"));
    return;
  }
  const tbl = el("table", "grid");
  tbl.innerHTML = "<thead><tr><th>id</th><th>controller</th><th>code</th><th>j1939.spn</th><th>j1939.fmi</th>" +
    "<th>name</th><th>triggerCondition</th><th>severity</th><th>remedy</th><th>auditFlag</th><th>source</th></tr></thead><tbody>" +
    codes.map(c => `<tr data-src="${(c.src || []).join(",")}">
      <td><code>${esc(c.code_id)}</code></td><td>${esc(c.控制器)}</td><td>${esc(c.代码)}</td>
      <td>–</td><td>–</td>
      <td>${esc(c.故障名称)}</td>
      <td>${esc(c.触发条件 ?? "")}</td><td>${c.故障等级 ?? "–"}</td>
      <td>${esc(c.解决措施 ?? "")}</td>
      <td>${c.审核标记 ? `<span class="badge b-fault">${esc(c.审核标记)}</span>` : ""}</td>
      <td>${(c.来源 || []).map(esc).join(", ")}</td></tr>`).join("") + "</tbody>";
  root.appendChild(tableScroll(tbl));
}

function renderRules(root, rules) {
  if (!rules.length) {
    root.appendChild(el("p", "hint", "本文档未抽得保养规则（周期表分类未命中，可在解析界面手工改标后重跑）。"));
    return;
  }
  const tbl = el("table", "grid");
  tbl.innerHTML = "<thead><tr><th>id</th><th>trigger.type</th><th>trigger.hours</th><th>trigger.calendar</th>" +
    "<th>trigger.duePolicy</th><th>content</th><th>accumulates</th><th>source</th></tr></thead><tbody>" +
    rules.map(r => {
      const t = r.触发 || {};
      return `<tr data-src="${(r.src || []).join(",")}">
        <td><code>${esc(r.rule_id)}</code></td>
        <td>${esc(t.类型 || "")}</td>
        <td>${t.小时 ?? "–"}</td>
        <td>${esc(t.日历 || "–")}</td>
        <td>${esc(t.关系 || "–")}</td>
        <td>${esc(r.内容)}</td>
        <td>${(r.累积 || []).map(a => `<code>${esc(a)}</code>`).join(" ")}</td>
        <td>${(r.来源 || []).map(esc).join("、")}</td></tr>`;
    }).join("") + "</tbody>";
  root.appendChild(tableScroll(tbl));
}

function renderPackage(root, d) {
  const m = d.manifest;
  const card = el("div", "card");
  card.appendChild(el("h3", "", `数据包：${esc(d.数据包)}`));
  if (!m || !Array.isArray(m.文件)) {
    card.appendChild(el("p", "hint", "该手册当前阶段未生成数据包 manifest。"));
    root.appendChild(card);
    return;
  }
  const pre = el("pre", "json-view", esc(JSON.stringify(m, null, 2)));
  pre.hidden = true;
  const jsonBtn = el("button", "json-toggle", "manifest.json");
  jsonBtn.type = "button";
  jsonBtn.onclick = () => {
    pre.hidden = !pre.hidden;
    jsonBtn.classList.toggle("on", !pre.hidden);
  };
  card.appendChild(jsonBtn);
  card.appendChild(pre);
  const tbl = el("table", "grid");
  tbl.innerHTML = "<thead><tr><th>文件</th><th>SHA-256（前 16 位）</th></tr></thead><tbody>" +
    m.文件.map(f => `<tr><td>${esc(f.文件)}</td><td><code>${esc(f.sha256.slice(0, 16))}…</code></td></tr>`).join("") + "</tbody>";
  card.appendChild(tableScroll(tbl));
  root.appendChild(card);
}

function renderAuditList(root, entries) {
  if (!entries.length) {
    root.appendChild(el("div", "alert ok", "✓ 零审核项——本轮抽取没有需要人工复核的内容。"));
    return;
  }
  const tbl = el("table", "grid");
  tbl.innerHTML = "<thead><tr><th>#</th><th>类别</th><th>说明</th><th>位置</th></tr></thead><tbody>" +
    entries.map((e, i) => `<tr><td>${i + 1}</td>
      <td><span class="badge b-layout">${esc(e.类别)}</span></td>
      <td>${esc(e.说明)}</td><td>${esc(e.位置 || "")}</td></tr>`).join("") + "</tbody>";
  root.appendChild(tableScroll(tbl));
}

init();

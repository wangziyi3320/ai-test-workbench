const $ = (id) => document.getElementById(id);
const state = { requirements: [], selectedId: null, selected: null, cases: [], defects: [] };
const categoryNames = { normal: "正常", boundary: "边界", exception: "异常", security: "安全" };
const statusNames = { draft: "待审核", approved: "已通过", rejected: "不采用" };
const severityNames = { critical: "严重", major: "主要", minor: "次要" };
const defectStatusNames = { open: "待修复", fixed: "已修复", verified: "已验证", closed: "已关闭" };

function el(tag, className = "", value = "") {
  const item = document.createElement(tag);
  if (className) item.className = className;
  item.textContent = value;
  return item;
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `请求失败（${response.status}）`);
  return data;
}

function toast(message) {
  const item = $("toast");
  item.textContent = message;
  item.classList.add("visible");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => item.classList.remove("visible"), 3800);
}

function formatDate(value) { return (value || "").replace("T", " ").slice(0, 16); }

async function refreshRequirements() {
  state.requirements = await api("/api/requirements");
  if (!state.requirements.some((item) => item.id === state.selectedId)) {
    state.selectedId = state.requirements.length ? state.requirements[0].id : null;
  }
  renderRequirementList();
  if (state.selectedId) await selectRequirement(state.selectedId);
  else { $("workspace").hidden = true; $("empty-state").hidden = false; }
}

function renderRequirementList() {
  $("requirement-count").textContent = state.requirements.length;
  const list = $("requirement-list");
  list.replaceChildren();
  for (const item of state.requirements) {
    const button = el("button", `req-link${item.id === state.selectedId ? " active" : ""}`);
    button.type = "button";
    button.append(el("strong", "", item.title), el("small", "", `${item.kind === "openapi" ? "API 文档" : "文字需求"} · ${item.case_count} 条用例`));
    button.addEventListener("click", () => selectRequirement(item.id));
    list.append(button);
  }
}

async function selectRequirement(id) {
  state.selectedId = id;
  [state.selected, state.cases, state.defects] = await Promise.all([
    api(`/api/requirements/${id}`), api(`/api/test-cases?requirement_id=${id}`), api(`/api/defects?requirement_id=${id}`),
  ]);
  $("empty-state").hidden = true;
  $("workspace").hidden = false;
  $("selected-title").textContent = state.selected.title;
  $("selected-meta").textContent = `${state.selected.kind === "openapi" ? "OpenAPI JSON" : "文字需求"} · ${state.selected.source_name || "手动输入"} · ${formatDate(state.selected.created_at)}`;
  $("source-content").textContent = state.selected.content;
  $("metric-cases").textContent = state.cases.length;
  $("metric-approved").textContent = state.cases.filter((item) => item.review_status === "approved").length;
  $("metric-defects").textContent = state.defects.length;
  renderRequirementList();
  renderCases();
  renderDefects();
}

function renderCases() {
  const list = $("case-list");
  list.replaceChildren();
  if (!state.cases.length) {
    list.append(el("div", "no-data", "还没有用例。选择生成模式，建立第一批待审核草稿。"));
  }
  for (const item of state.cases) {
    const card = el("article", "case");
    const top = el("div", "case-top");
    const heading = el("div");
    heading.append(el("h3", "", `#${item.id}  ${item.title}`));
    const meta = el("div", "case-meta");
    meta.append(el("span", `badge ${item.review_status}`, statusNames[item.review_status]),
                el("span", "badge", categoryNames[item.category]),
                el("span", "badge", item.priority),
                el("span", "badge", item.generator === "llm" ? "模型生成" : "离线草稿"));
    heading.append(meta);
    const actions = el("div", "case-actions");
    const edit = el("button", "small-button", "编辑 / 审核");
    edit.type = "button";
    edit.addEventListener("click", () => openEditor(item));
    actions.append(edit);
    top.append(heading, actions);
    card.append(top, el("p", "", `步骤：${item.steps}`), el("p", "", `预期：${item.expected}`),
                el("p", "source", `来源：${item.source_ref}`));
    list.append(card);
  }
  const caseSelect = $("defect-case");
  caseSelect.replaceChildren(el("option", "", "不关联具体用例"));
  caseSelect.firstChild.value = "";
  for (const item of state.cases) {
    const option = el("option", "", `#${item.id} ${item.title.slice(0, 46)}`);
    option.value = item.id;
    caseSelect.append(option);
  }
}

function openEditor(item) {
  $("edit-case-id").value = item.id;
  $("edit-title").value = item.title;
  $("edit-category").value = item.category;
  $("edit-priority").value = item.priority;
  $("edit-preconditions").value = item.preconditions;
  $("edit-steps").value = item.steps;
  $("edit-expected").value = item.expected;
  $("edit-source").value = item.source_ref;
  $("edit-method").value = item.method;
  $("edit-path").value = item.path;
  $("edit-status-code").value = item.expected_http_status || "";
  $("edit-review").value = item.review_status;
  $("case-dialog").showModal();
}

function renderDefects() {
  const list = $("defect-list");
  list.replaceChildren();
  if (!state.defects.length) list.append(el("div", "no-data", "目前还没有记录缺陷。"));
  for (const item of state.defects) {
    const row = el("div", "defect");
    const body = el("div");
    body.append(el("h3", "", `#${item.id} ${item.title}`),
                el("p", "", `${severityNames[item.severity]} · ${item.test_case_id ? `关联用例 #${item.test_case_id}` : "未关联用例"} · ${formatDate(item.created_at)}`),
                el("p", "", `实际：${item.actual}`));
    const select = el("select");
    select.setAttribute("aria-label", `缺陷 #${item.id} 状态`);
    for (const [value, label] of Object.entries(defectStatusNames)) {
      const option = el("option", "", label);
      option.value = value;
      select.append(option);
    }
    select.value = item.status;
    select.addEventListener("change", async () => {
      try {
        await api(`/api/defects/${item.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: select.value }) });
        item.status = select.value;
        toast("缺陷状态已更新");
      } catch (error) { select.value = item.status; toast(error.message); }
    });
    row.append(body, select);
    list.append(row);
  }
}

async function downloadFile(url, filename) {
  const response = await fetch(url);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `导出失败（${response.status}）`);
  }
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

$("requirement-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const saved = await api("/api/requirements", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: $("req-title").value, kind: $("req-kind").value, content: $("req-content").value }) });
    state.selectedId = saved.id;
    $("requirement-form").reset();
    await refreshRequirements();
    toast("需求已保存；现在可以生成用例草稿");
  } catch (error) { toast(error.message); }
});

$("file-input").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const form = new FormData();
    form.append("file", file);
    const saved = await api("/api/requirements/upload", { method: "POST", body: form });
    state.selectedId = saved.id;
    await refreshRequirements();
    toast("文档已导入");
  } catch (error) { toast(error.message); }
  event.target.value = "";
});

$("load-sample").addEventListener("click", async () => {
  try {
    $("req-title").value = "短链生成接口验收需求（虚构示例）";
    $("req-kind").value = "requirement";
    $("req-content").value = await (await fetch("/static/demo-requirement.md")).text();
    toast("示例已填入，点击保存需求");
  } catch (error) { toast("示例加载失败"); }
});

$("generate-button").addEventListener("click", async (event) => {
  if (!state.selectedId) return;
  event.target.disabled = true;
  try {
    const result = await api(`/api/requirements/${state.selectedId}/generate`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: $("generation-mode").value }) });
    await refreshRequirements();
    toast(`${result.generator === "llm" ? "模型" : "离线规则"}生成 ${result.generated} 条，新增 ${result.inserted} 条草稿`);
  } catch (error) { toast(error.message); }
  event.target.disabled = false;
});

$("csv-button").addEventListener("click", async () => {
  try { await downloadFile(`/api/requirements/${state.selectedId}/cases.csv`, `cases-${state.selectedId}.csv`); }
  catch (error) { toast(error.message); }
});
$("postman-button").addEventListener("click", async () => {
  try { await downloadFile(`/api/requirements/${state.selectedId}/postman.json`, `postman-${state.selectedId}.json`); }
  catch (error) { toast(error.message); }
});

$("case-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = $("edit-case-id").value;
  const payload = {
    title: $("edit-title").value, category: $("edit-category").value, priority: $("edit-priority").value,
    preconditions: $("edit-preconditions").value, steps: $("edit-steps").value, expected: $("edit-expected").value,
    source_ref: $("edit-source").value, method: $("edit-method").value, path: $("edit-path").value,
    review_status: $("edit-review").value,
  };
  if ($("edit-status-code").value) payload.expected_http_status = Number($("edit-status-code").value);
  try {
    await api(`/api/test-cases/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    $("case-dialog").close();
    await refreshRequirements();
    toast("用例修改和审核结果已保存");
  } catch (error) { toast(error.message); }
});
$("close-dialog").addEventListener("click", () => $("case-dialog").close());
$("cancel-dialog").addEventListener("click", () => $("case-dialog").close());

$("defect-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/defects", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requirement_id: state.selectedId,
        test_case_id: $("defect-case").value ? Number($("defect-case").value) : null,
        title: $("defect-title").value, severity: $("defect-severity").value, steps: $("defect-steps").value,
        expected: $("defect-expected").value, actual: $("defect-actual").value }) });
    $("defect-form").reset();
    await refreshRequirements();
    toast("缺陷已记录");
  } catch (error) { toast(error.message); }
});

(async () => {
  try {
    const health = await api("/api/health");
    $("mode-indicator").textContent = health.llm_configured ? "模型 API 已配置" : "离线规则模式可用";
    await refreshRequirements();
  } catch (error) { toast(`连接失败：${error.message}`); }
})();

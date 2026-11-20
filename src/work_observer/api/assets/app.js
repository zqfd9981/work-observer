"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const e = escapeHTML;
const token = $('meta[name="wo-token"]').content;
const state = {importAsset:null,csvRows:[],operations:null, filters:{}, offset:0, limit:20, jobs:new Map(), selected:new Map(), researchIds:null,
  activeRun:null, lastRun:null, lastResult:null, memories:new Map(), overview:null, page:"career", querySerial:0};
const statusLabels = {analysis_draft:"开发分析样稿（待核对）",completed:"回答已生成", partial:"已保留部分结果", evidence_only:"原文证据包", failed:"研究未完成", incomplete:"达到研究上限", insufficient_evidence:"正文不足"};
const originLabels = {website:"网站响应", unknown:"新鲜度未知", cache:"缓存资料", replay:"回放资料", manual:"人工资料", test:"测试资料", client_error:"获取失败"};
const requirementLabels = {required:"必备", preferred:"加分", unspecified:"未明确性质"};
const domainLabels = {business_application:"业务应用开发",agent_platform:"执行平台与 Harness",domain_decision:"领域决策系统",model_serving:"模型与推理部署",configuration_delivery:"平台配置与实施",other:"其他待定义领域"};
const materialRevisionDrafts = new Map();
const claimBasisLabels = {direct:"原文明示",synthesis:"研究归纳",inference:"研究推断"};
const claimBasisLabel = claim => claimBasisLabels[claim?.basis] || "性质未标注";
const categoryLabels = {business:"业务背景", deliverable:"交付物", task:"任务", responsibility:"责任", ability:"能力", tool:"工具"};
const reasonLabels = {VISION_NO_READABLE_TEXT:"未取得可核对的正文，未写入岗位。可对照原图人工填写。",VISION_MODEL_HTTP_ERROR:"当前模型服务未能处理图片，未写入岗位。",INVALID_VISION_DRAFT:"视觉响应不符合草稿格式，未写入岗位。",MODEL_CONFIG_MISSING:"尚未配置模型，可改用仅整理证据模式。",MODEL_AUTH_REQUIRED:"模型服务认证未通过。",MODEL_FORBIDDEN:"当前模型服务权限不足。",MODEL_RATE_LIMIT_OR_QUOTA:"模型服务限流或额度不足，可稍后再试。",MODEL_HTTP_ERROR:"模型服务暂时没有正常响应。",TIMEOUT:"已达到时间上限，研究停止。",model_call_limit:"已达到调用次数上限，研究停止。",no_available_details:"范围内没有可研究的完整正文。"};
const titles = {career:"求职成长",jobs:"岗位资料", companies:"公司档案", research:"研究工作台", projects:"持续研究项目", workflows:"日常研究流程", trials:"受限检索试用", knowledge:"领域与证据", quality:"研究质量核对", "profile-quality":"完整画像核对", "research-benchmarks":"研究方法核对", "data-quality":"资料核对",updates:"领域变化观察", reports:"已存研究", memory:"知识与偏好", matches:"个人匹配", retrieval:"检索与评测", operations:"观察与更新"};
let toastTimer, pollTimer;
const conversation = {id:null, timer:null, reports:new Map(), drafts:new Map(), sourceScopes:new Map(), notes:[], knowledge:[], notesFor:null, renderedId:null};
Object.assign(reasonLabels,{
  STEP_NOT_READY:"这一步目前不可执行。请刷新研究进度，核对是否仍在等待前置调查。",
  UPDATE_MEMORY_FORGOTTEN:"这份观察已随相关记忆或研究清除，不能从旧页面继续。请重新选择现有资料建立研究。",
  UPDATE_RECORD_NOT_FOUND:"未找到这份观察记录，请刷新列表后重新选择。",
  RESEARCH_HISTORY_TIME_OUT_OF_SCOPE:"历史读取时点必须明确，且不能晚于本轮研究开始。",
  INVALID_HISTORICAL_JOB_WINDOW:"历史正文读取位置无效，本次没有取得新证据。",
  EVIDENCE_DOCUMENT_INTEGRITY_FAILED:"该版本原始文档已缺失或改变，不能用现文替代历史依据。",
  MEMORY_VERSION_NOT_CURRENT:"这条记录已有更新，当前输入保留。请载入已保存的新版后再修改。",
  WORK_MATERIAL_CLOCK_CONFLICT:"本机保存时间未晚于上一版，请稍后重试并核对系统时间。",
  WORK_MATERIAL_REQUIRED:"只能修订自己保存的粘贴工作资料；网页归档保留原样。",
  WORK_MATERIAL_CHANGED_REFRESH:"这份资料已有新版本，请先打开新版再修订；当前输入仍保留。",
  WORK_MATERIAL_SOURCE_INTEGRITY_FAILED:"旧版归档完整性未通过，请先核对资料。",
  PUBLIC_DOCUMENT_INTEGRITY_FAILED:"归档完整性未通过，不能据此展示版本差异。",
  INVALID_DOCUMENT_COMPARISON:"请选择同一份资料中较早的归档版本进行对照。",
  INVALID_RESEARCH_DOCUMENT_SCOPE:"一次最多选择20份有效的归档资料，请重新选择。",
  PUBLIC_DOCUMENT_NOT_FOUND:"所选归档资料已不可用，请在资料库中重新选择。",
  RESEARCH_FEEDBACK_UNAVAILABLE:"原研究已不可用或已清除，请重新选择研究。",
  RESEARCH_FEEDBACK_FIXED_LOCAL_SCOPE_REQUIRED:"修正研究须使用原问题、原岗位与筛选；其他范围请另建研究。",
  RESEARCH_FEEDBACK_USE_PROJECT_BUDGET:"这是项目内的研究，请从原项目跟进，保留项目总预算。",
  RESEARCH_FEEDBACK_PROJECT_MISMATCH:"复核与当前项目不一致，请从原项目安排补查。",
  RESEARCH_FEEDBACK_PROJECT_CLAIM_REQUIRED:"本轮尚未由原项目领取，或范围与预算已变化；请从项目继续。",
  PROJECT_REPAIR_BUDGET_EXHAUSTED:"项目剩余额度不足以预留这一轮，请减少本轮额度或只整理原文。旧额度不会重置。",
  STEP_QUALITY_REJECTION_REPAIR_REQUIRED:"当前回答已有拒绝复核，请先补查或重新逐项核对后再接受。",
  STEP_REPAIR_ALREADY_PLANNED:"同一复核已有待执行或可续接的补查，请使用原轮进度。",
  RESEARCH_FEEDBACK_STANDARD_ONLY:"参考复核的新一轮使用现有方法和固定本地原文，请关闭公开补查。",
  RESEARCH_FEEDBACK_REJECTION_REQUIRED:"当前没有绑定本结果的未通过复核，请先逐项核对。",
  RESEARCH_FEEDBACK_SOURCES_CHANGED:"原研究的资料或记忆已变化，请先按当前资料建立新研究。",
  RESEARCH_FEEDBACK_CHANGED_NEW_RUN_REQUIRED:"所选复核或方法已变化，原进度保留；请查看最新复核后明确新建一轮。",
  RESEARCH_METHOD_CHANGED_NEW_RUN_REQUIRED:"这次试验使用的方法已更新，不能混用新旧方法继续原进度。已保留原记录，请开始一次新研究。",
  RESEARCH_VALIDATION_CHANGED_NEW_ROUND_REQUIRED:"本轮的要求性质检查已变化，原进度与预算保留。请明确安排新一轮，不会自动换规则续接。",
  SOURCE_FIRST_LOCAL_JD_ONLY:"分项核对试验只使用本地岗位正文。请关闭公开补查，或选择现有研究方法。"
});

function notify(message, error = false) {
  const toast = $("#toast");
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.className = "toast" + (error ? " error" : "");
  toast.hidden = false;
  toastTimer = setTimeout(() => { toast.hidden = true; }, 5000);
}

async function api(path, options = {}) {
  const response = await fetch("/api/" + path, {cache:"no-store", ...options,
    headers:{"X-WO-Token":token, ...(options.body ? {"Content-Type":"application/json"} : {}), ...options.headers}});
  let data;
  try { data = await response.json(); }
  catch { throw new Error("服务暂时没有返回可读取的数据，请确认本地服务仍在运行。"); }
  if (!response.ok) {
    const error = new Error(reasonLabels[data.error_code] || data.message || "操作未完成，请稍后再试。");
    error.code = data.error_code;
    throw error;
  }
  return data;
}

function when(value, compact = false) {
  if (!value) return "未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未知";
  return new Intl.DateTimeFormat("zh-CN", {timeZone:"Asia/Shanghai", month:"2-digit", day:"2-digit",
    ...(compact ? {} : {year:"numeric"}), hour:"2-digit", minute:"2-digit", hour12:false}).format(date);
}

function memoryText(item) {
  const content=typeof item === "string" ? item : item.content || "";
  try {
    if(content.startsWith(APPLICATION_PREFIX)) {
      const value=JSON.parse(content.slice(APPLICATION_PREFIX.length));
      if(typeof value.background==="string"&&typeof value.goal==="string"&&typeof value.constraints==="string")return `个人应用背景（用户自述）：\n已有经历或能力：${value.background}\n本次目标：${value.goal}\n投入与限制：${value.constraints||"未说明，不作假设"}`;
    }
    if (content.startsWith("结构化个人条件：")) {
      const p=JSON.parse(content.slice("结构化个人条件：".length));
      return [p.cities?.length ? "工作城市："+p.cities.join("、") : "工作城市不限",p.salary_min != null || p.salary_max != null ? "薪资区间："+(p.salary_min ?? "不限")+"～"+(p.salary_max ?? "不限")+"元 / "+({month:"月",year:"年",day:"日",hour:"小时"})[p.salary_unit] : "薪资不限",p.employment_types?.length ? "用工形式："+p.employment_types.join("、") : "",p.desired_tasks?.length ? "希望承担："+p.desired_tasks.join("、") : ""].filter(Boolean).join("；");
    }
    if (content.startsWith("画像领域纠正：")) {
      const value=JSON.parse(content.slice("画像领域纠正：".length));
      return "领域归类："+(value.domains.length ? value.domains.map(key=>value.domain_labels?.[key] || domainLabels[key] || key).join("、") : "暂不归类")+"。理由："+value.reason;
    }
  } catch {}
  return content;
}

function sourceLabel(item) { return item?.data_kind === "synthetic" ? "合成演示资料（非真实招聘）" : item?.input_kind === "ocr_manual_review" ? "OCR人工核对" : item?.input_kind === "image_manual_review" ? "截图人工核对" : originLabels[item?.response_origin] || "来源未知"; }

function badge(text, kind = "") { return `<span class="badge ${e(kind)}">${e(text)}</span>`; }
function empty(title, description = "") { return `<div class="panel empty"><h3>${e(title)}</h3><span>${e(description)}</span></div>`; }
function errorBox(error) { return `<div class="error-box" role="alert">${e(error.message || error)}</div>`; }
function detailData(label, value) { return `<div><dt>${e(label)}</dt><dd>${e(value || "未知")}</dd></div>`; }

async function loadOverview() {
  const data = await api("overview");
  state.overview = data;
  $("#nav-jobs").textContent = data.jobs;
  $("#stats").innerHTML = [["已存岗位",data.jobs,"当前资料范围内的去重记录","▦"],
    ["有完整正文",data.details,"可以查阅与研究原文","▤"],
    ["仅有摘要",data.jobs-data.details,"正文仍待补充","◷"],
    ["公司记录",data.companies,"保留未核实的公司关联","▧"]].map(([label,count,note,icon]) =>
      `<div class="stat"><span>${e(label)}</span><i aria-hidden="true">${icon}</i><strong>${e(count)}</strong><small>${e(note)}</small></div>`).join("");
  $("#sidebar-source").textContent = data.source.state === "paused" ? "招聘来源已暂停" : data.source.state === "unknown" ? "来源状态尚未确认" : "仅查看本地资料";
  $(".top-right .quiet-tag").textContent = data.source.state === "paused" ? "来源已暂停" : "本地资料";
  $("#model-status").textContent = data.model_configured ? "● 研究服务已配置" : "○ 可使用原文证据模式";
  if (!data.model_configured) {
    $("#offline").checked = true;
    $("#research-config-note").textContent = "尚未配置模型。可先使用原文证据模式；模型调用失败会明确显示，不会冒充已完成。";
  }
  return data;
}

function filterValues() {
  return Object.fromEntries([...new FormData($("#filter-form"))].filter(([key,value]) => String(value).trim() !== "")
    .map(([key,value]) => [key, String(value).trim()]));
}

async function loadJobs() {
  const serial = ++state.querySerial;
  const params = new URLSearchParams({...state.filters, limit:state.limit, offset:state.offset});
  try {
    const data = await api("jobs?" + params);
    if (serial !== state.querySerial) return;
    state.jobs = new Map(data.jobs.map(job => [job.id,job]));
    const counts = data.counts;
    $("#results-count").textContent = `${counts.matched} 个匹配 · ${counts.unknown} 个条件未知`;
    $("#filter-note").hidden = counts.unknown === 0;
    $("#filter-note").textContent = `有 ${counts.unknown} 个候选存在未知条件，已保留显示并单独标记。未知不等于符合。`;
    $("#jobs-body").innerHTML = data.jobs.length ? data.jobs.map(job => {
      const origin = job.detail_source || job.summary_source;
      const complete = job.has_detail;
      return `<tr class="${state.selected.has(job.id) ? "selected" : ""}">
        <td><input type="checkbox" data-select-job="${e(job.id)}" aria-label="选择 ${e(job.title)}" ${state.selected.has(job.id) ? "checked" : ""}></td>
        <td><button class="job-link" data-job="${e(job.id)}">${e(job.title || "未提供岗位名称")}</button><button class="company-link" data-company="${e(job.company_id || "")}">${e(job.company || "公司未知")}</button>${job.match_status === "unknown" ? `<br>${badge("条件未知","amber")}` : ""}</td>
        <td><span class="salary">${e(job.salary || "薪资未知")}</span><span class="subtext">${e(job.experience || "经验未知")} · ${e(job.education || "学历未知")}</span></td>
        <td>${e(job.city || "地点未知")}</td><td>${badge(complete ? "有完整正文" : "仅有摘要",complete ? "" : "muted")}<span class="subtext">${e(sourceLabel(origin))}</span></td>
        <td><span class="date">${e(when(job.last_observed_at,true))}</span><span class="subtext">发布时间${job.source_published_at ? "已记录" : "未知"}</span></td>
        <td><button class="chevron" data-job="${e(job.id)}" aria-label="查看 ${e(job.title)} 详情">›</button></td></tr>`;
    }).join("") : `<tr><td colspan="7" class="empty"><h3>没有找到符合范围的岗位</h3><span>试试减少筛选条件，或补充新的岗位资料。</span></td></tr>`;
    $("#page-number").textContent = Math.floor(state.offset / state.limit) + 1;
    $("#prev-page").disabled = state.offset === 0;
    $("#next-page").disabled = !data.truncated;
  } catch (error) {
    if (serial !== state.querySerial) return;
    $("#jobs-body").innerHTML = `<tr><td colspan="7">${errorBox(error)}</td></tr>`;
    $("#results-count").textContent = "读取未完成";
    notify(error.message,true);
  }
}

function updateSelection() {
  $("#selected-count").textContent = state.selected.size;
  $("#selection-bar").hidden = state.selected.size === 0;
  $("#compare-selected").disabled = state.selected.size < 2 || state.selected.size > 5;
  $("#compare-selected").title = "选择 2–5 个不同岗位后比较";
  $$("[data-select-job]").forEach(checkbox => {
    checkbox.checked = state.selected.has(checkbox.dataset.selectJob);
    checkbox.closest("tr").classList.toggle("selected",checkbox.checked);
  });
}

function openDialog(id) {
  const dialog = $("#" + id);
  if (!dialog.open) dialog.showModal();
}

async function showJob(id) {
  if (!id) return;
  $("#detail-label").textContent = "岗位详情";
  $("#detail-content").innerHTML = `<div class="empty">正在读取岗位…</div>`;
  openDialog("detail-dialog");
  try {
    const job = await api("jobs/" + encodeURIComponent(id));
    const c = job.current, company = job.company_profile;
    const source = job.provenance?.description_text || job.provenance?.title;
    $("#detail-content").innerHTML = `<div class="detail-head">${badge(c.description_text ? "有完整正文" : "仅有摘要",c.description_text ? "" : "muted")} ${badge(c.data_kind === "synthetic" || source?.data_kind === "synthetic" ? "合成演示资料（非真实招聘）" : job.source === "manual" ? "人工资料" : "BOSS 资料","muted")}<h2>${e(c.title || "未提供岗位名称")}</h2><p><button class="company-link" data-company="${e(c.company_id || "")}">${e(c.company_name_raw || "公司未知")}</button></p><div class="salary">${e(c.salary_raw || "薪资未知")}</div><span class="subtext">${e(c.city || "城市未知")} · ${e(c.experience_raw || "经验未知")} · ${e(c.education_raw || "学历未知")}</span></div>
      <div class="detail-actions"><button class="secondary" data-add-compare="${e(id)}">${state.selected.has(id) ? "已加入比较" : "加入比较"}</button><button class="secondary" data-supplement="${e(id)}">补充这份资料</button><button class="secondary" data-profile="${e(id)}">查看工作画像 ↗</button></div>
      <dl class="detail-grid">${detailData("来源记录的招聘状态",({active:"曾观察到招聘中",closed:"曾观察到关闭",unknown:"未知"})[c.status])}${detailData("状态确认时间",c.status_observed_at ? when(c.status_observed_at) : null)}${detailData("来源发布时间",c.source_published_at ? when(c.source_published_at) : c.source_published_raw)}${detailData("详情取得时间",c.detail_collected_at ? when(c.detail_collected_at) : null)}</dl>
      <section class="detail-section"><h3>职位描述</h3><div class="body-text">${c.description_text ? e(c.description_text) : "尚未取得完整 JD。这份资料只能用于摘要查看，不能据此推断任务、能力或工具要求。"}</div></section>
      <section class="detail-section"><h3>公司与工作地点</h3><div class="body-text">${e(c.address || c.district || "详细工作地址未知")}</div><p class="form-note">${e(company?.industry_raw || "行业未知")} · ${e(company?.scale_raw || "规模未知")} · ${e(company?.stage_raw || "发展阶段未知")}<br>${company?.identity_status === "source_id" ? "已有来源公司编号，不代表法定主体核验。" : "公司身份未核实，同名不代表同一主体。"}</p></section>
      <section class="detail-section"><h3>资料时间与依据</h3><div class="detail-time">首次发现：${e(when(c.first_observed_at))}<br>最近取得：${e(when(c.last_observed_at))}<br>来源类型：${e(sourceLabel(source))}<br>本地归档：${e(when(source?.archived_at))}<br>以上时间均为北京时间，取得时间不是发布时间。<br>内部岗位编号：${e(id)}</div>${source ? `<button class="secondary small" data-source="${e(source.document_id)}">核对来源文档 ↗</button>${source.import_asset_id ? `<button class="secondary small" data-import-image="${e(source.import_asset_id)}">核对截图原图 ↗</button>` : ""}` : ""}</section>
      ${job.manual_supplements?.length ? `<section class="detail-section"><h3>人工补充资料</h3>${job.manual_supplements.map(item=>`<button class="job-link" data-job="${e(item.job_id)}">${e(item.title)} ↗</button>`).join("")}</section>` : ""}
      <details class="detail-section" id="history-section"><summary>查看观察与版本记录</summary><button class="secondary small" data-compare-history="${e(id)}">比较最近正文版本 ↗</button><div id="history-comparison"></div><div id="job-history" class="detail-time">正在读取历史…</div></details>`;
    const history = await api("jobs/" + encodeURIComponent(id) + "/history");
    const historyRoot = $("#job-history");
    if (historyRoot) historyRoot.innerHTML = history.map(item=>`<div class="detail-history">${e(when(item.observed_at))} · ${item.kind === "detail" ? "详情" : "列表"} · ${e(sourceLabel(item))}<br>本地处理 ${e(when(item.processed_at))}<br><button data-source="${e(item.document_id)}">核对该次来源与内容版本 ↗</button></div>`).join("") || "暂无记录";
  } catch (error) { $("#detail-content").innerHTML = errorBox(error); }
}

async function compareJobHistory(id) {
  const root=$("#history-comparison");
  if (!root) return;
  root.innerHTML=`<p class="form-note">正在比较已保存的正文版本，不访问招聘来源…</p>`;
  try {
    const data=await api("jobs/"+encodeURIComponent(id)+"/compare-history");
    if (data.status !== "compared") {
      root.innerHTML=`<div class="research-context"><h3>尚无可比较的正文历史</h3>${data.gaps.map(gap=>`<p>${e(gap)}</p>`).join("")}<p>重复观察同一正文不会制造新版本。</p></div>`;return;
    }
    const fields={description:"JD正文",title:"岗位名称",company:"公司原文",city:"城市",salary:"薪资原文",education:"学历原文",experience:"经验原文",skills:"来源技能标签",status:"来源状态"};
    root.innerHTML=`<section class="research-context"><h3>最近两个不同正文版本</h3><p>较早取得 ${e(when(data.before.observed_at))} · ${e(sourceLabel(data.before))}<br>较晚取得 ${e(when(data.after.observed_at))} · ${e(sourceLabel(data.after))}</p><p>这是已保存来源内容的差异；采样范围变化与分析方法变化分别记录，不据此推断市场趋势或准确的网站更新时间。</p><h3>正文差异</h3><pre class="body-text history-diff">${e(data.description_diff || "正文相同，其他来源字段发生变化。")}</pre><p>“−”为较早正文，“＋”为较晚正文；发布时间未知时仍保持未知。</p>${data.changes.filter(item=>item.field !== "description").length ? `<details><summary>其他来源字段变化</summary>${data.changes.filter(item=>item.field !== "description").map(item=>`<p>${e(fields[item.field] || "来源字段")}：${e(typeof item.before === "object" ? JSON.stringify(item.before) : item.before ?? "未知")} → ${e(typeof item.after === "object" ? JSON.stringify(item.after) : item.after ?? "未知")}</p>`).join("")}</details>` : ""}${data.evidence.map((ev,index)=>`<details class="evidence-item"><summary>版本依据 ${index+1} · ${e(sourceLabel(ev))}</summary><blockquote>${e(ev.quote)}</blockquote><div class="evidence-meta">取得 ${e(when(ev.observed_at))} · 字符 ${ev.start}–${ev.end}<br><button data-source="${e(ev.document_id)}">核对该版本原始文档 ↗</button></div></details>`).join("")}</section>`;
  } catch (error) {root.innerHTML=errorBox(error);}
}

async function showCompany(id) {
  if (!id) return;
  $("#detail-label").textContent = "公司档案";
  $("#detail-content").innerHTML = `<div class="empty">正在读取公司…</div>`;
  openDialog("detail-dialog");
  try {
    const company = await api("companies/" + encodeURIComponent(id));
    $("#detail-content").innerHTML = `<div class="detail-head">${badge(company.identity_status === "source_id" ? "已有来源公司编号" : "身份未核实",company.identity_status === "source_id" ? "" : "amber")}<h2>${e(company.name)}</h2></div><dl class="detail-grid">${detailData("行业",company.industry_raw)}${detailData("规模",company.scale_raw)}${detailData("发展阶段",company.stage_raw)}${detailData("最近取得资料",when(company.last_observed_at))}</dl><section class="detail-section"><h3>公司介绍</h3><div class="body-text">${e(company.introduction || "来源尚未提供公司介绍。")}</div></section><section class="detail-section"><h3>关联岗位 · ${company.jobs.length}</h3>${company.jobs.map(job=>`<div class="detail-history"><button class="job-link" data-job="${e(job.id)}">${e(job.title)} ↗</button>${badge(job.detail_state === "detail" ? "有正文" : "仅摘要","muted")}</div>`).join("")}</section><p class="form-note">公司编号与名称是来源资料，不代表法定主体核验。同名记录不会自动归并。</p>`;
  } catch (error) { $("#detail-content").innerHTML = errorBox(error); }
}

async function showSource(id) {
  $("#source-content").innerHTML = `<div class="empty">正在核对资料…</div>`;
  openDialog("source-dialog");
  try {
    const data = await api("sources/" + encodeURIComponent(id));
    $("#source-content").innerHTML = `<h2>原始资料核对</h2>${data.import_asset_id ? `<button class="secondary" data-import-image="${e(data.import_asset_id)}">核对人工来源的截图原图 ↗</button>` : ""}<p class="form-note">通过文件指纹检查已存档资料；不重新访问招聘网站。</p>${badge(data.integrity === "verified" ? "原始文件完整性已核对" : "原始文件缺失或已改变",data.integrity === "verified" ? "" : "error")}<dl class="detail-grid">${detailData("来源类型",sourceLabel(data))}${detailData("资料取得",when(data.observed_at))}${detailData("本地归档",when(data.archived_at))}${detailData("来源首次获取",when(data.source_fetched_at))}</dl><div class="detail-time">文档编号：${e(data.document_id)}<br>文件指纹：${e(data.sha256)}</div>${data.related_job_id ? `<p class="form-note">这份人工资料关联了一个原岗位：<button class="text-button" data-job="${e(data.related_job_id)}">查看原岗位 ↗</button></p>` : ""}${data.versions.map(item=>`<section class="detail-section"><h3>${e(item.payload.title || "岗位内容版本")} · ${item.kind === "detail" ? "详情" : "摘要"}</h3><div class="detail-time">内容版本：${e(item.snapshot_id)}</div><div class="body-text">${e(item.payload.description || [item.payload.title,item.payload.company,item.payload.salary,item.payload.city].filter(Boolean).join(" · "))}</div></section>`).join("")}`;
  } catch (error) { $("#source-content").innerHTML = errorBox(error); }
}

async function showPublicSource(id) {
  const request=state.publicSourceRequest=(state.publicSourceRequest||0)+1;
  $("#source-content").innerHTML = `<div class="empty">正在核对公开资料归档…</div>`;
  openDialog("source-dialog");
  try {
    const data=await api("public-documents/"+encodeURIComponent(id));
    if(request!==state.publicSourceRequest)return;
    state.currentPublicDocument=data;
    $("#source-content").innerHTML=`<h2>${e(data.title)}</h2>${badge(data.integrity === "verified" ? "归档文件指纹已核对" : "归档文件缺失或已变化",data.integrity === "verified" ? "" : "amber")} ${badge(data.evidence_kind==="work_material"?"粘贴工作资料":"公开网页","muted")}<p class="form-note">${e(data.source_note || "已归档公开网页正文，不能直接证明岗位个人职责。")}</p><dl class="detail-grid">${detailData(data.evidence_kind==="work_material"?"来源说明":"出处",data.publisher)}${detailData(data.evidence_kind==="work_material"?"保存时间":"取得时间",when(data.observed_at))}${detailData("正文长度",data.full_text_length)}${detailData("来源发布时间",data.source_published_at ? when(data.source_published_at) : "未知")}</dl>${safeURL(data.final_url || data.url) ? `<a class="secondary button-link" href="${e(safeURL(data.final_url || data.url))}" target="_blank" rel="noopener noreferrer">打开公开出处 ↗</a>` : ""}${renderPublicVersionTools(data)}<section class="detail-section"><h3>归档全文（纯文本）</h3><div class="body-text">${e(data.text)}</div></section>`;
  } catch (error) {if(request===state.publicSourceRequest)$("#source-content").innerHTML=errorBox(error);}
}

function renderPublicVersionTools(data) {
  if(!data.latest_document_id)return "";
  const manual=data.evidence_kind==="work_material",latest=data.latest_document_id===data.id;
  const draft=materialRevisionDrafts.get(data.url);
  return `<section class="detail-section"><h3>资料版本</h3><p class="form-note">当前打开的是归档快照，旧引用仍指向各自版本。${latest?"这是目前最新归档。":"已有更新归档，当前仍显示旧版。"}</p><button type="button" class="secondary small" data-public-history="${e(data.id)}">查看历史版本</button>${!latest?`<button type="button" class="text-button" data-public-source="${e(data.latest_document_id)}">打开最新归档 ↗</button>`:""}${data.previous_document_id?`<button type="button" class="text-button" data-document-compare="${e(data.id)}" data-previous-document="${e(data.previous_document_id)}">与上一版对照</button>`:""}<div id="public-history-list"></div><div id="public-version-comparison"></div>${manual&&latest&&data.integrity==="verified"?`<details><summary>修订这份工作资料</summary><form id="work-material-revision" data-base-document="${e(data.id)}"><label>标题<input name="title" value="${e(draft?.title??data.title)}" maxlength="300" required></label><label>来源说明<input name="source_name" value="${e(draft?.source_name??data.publisher)}" maxlength="500"></label><label>新版原文<textarea name="text" rows="6" maxlength="100000" required>${e(draft?.text??data.text)}</textarea></label>${draft?'<p class="form-note">已保留未保存的修订草稿；请对照当前归档原文后再保存。</p>':""}<p class="form-note">保存新版本，保留旧原文和引用。来源说明仍未经独立核实；这次改稿不等于外部工作已经变化，保存不调用模型。</p><button class="secondary">保存新版本</button></form></details>`:""}<p id="public-version-status" class="form-note" role="status"></p>${manual?`<button type="button" class="text-button" data-version-question="${e(data.id)}">用这一版开始提问</button>${state.page==="research"&&conversation.id?`<button type="button" class="text-button" data-version-attach="${e(data.id)}" data-version-project="${e(conversation.id)}">加入当前研究的后续调查</button>`:""}`:""}</section>`;
}

async function loadPublicDocumentHistory(id,offset=0) {
  const data=await api("public-documents/"+encodeURIComponent(id)+"/history?"+new URLSearchParams({limit:10,offset}));
  const current=state.currentPublicDocument;
  if(current?.id!==id)return;
  const older=row=>row.observed_at<current.observed_at||(row.observed_at===current.observed_at&&row.id<current.id);
  $("#public-history-list").innerHTML=`<p class="form-note">共 ${e(data.total)} 个归档版本，显示 ${data.offset+1}–${data.offset+data.documents.length}。</p>${data.documents.map((row,i)=>`<div class="detail-history"><strong>第 ${e(data.total-data.offset-i)} 版 · ${e(row.title)}</strong><p class="form-note">本机保存：${e(when(row.observed_at))} · 来源发布：${row.source_published_at?e(when(row.source_published_at)):"未知"}</p><button type="button" class="text-button" data-public-source="${e(row.id)}">打开这一版 ↗</button><button type="button" class="text-button" data-history-select="${e(row.id)}" data-history-title="${e(row.title)}">加入新研究范围</button>${row.id!==id?`<button type="button" class="text-button" data-document-compare="${e(older(row)?id:row.id)}" data-previous-document="${e(older(row)?row.id:id)}">与当前打开版本对照</button>`:""}</div>`).join("")}${data.offset>0?`<button type="button" class="text-button" data-history-page="${Math.max(0,data.offset-data.limit)}" data-history-document="${e(id)}">上一页</button>`:""}${data.offset+data.documents.length<data.total?`<button type="button" class="text-button" data-history-page="${data.offset+data.limit}" data-history-document="${e(id)}">下一页</button>`:""}`;
}

function renderArchiveComparisons(result) {
  const labels={user_text_revision:"用户修订正文",archive_text_changed:"归档正文变化",extraction_changed:"同一原始文件的文本提取结果变化",metadata_only:"正文未变，说明变化",raw_archive_changed:"响应变化，提取正文未变",observed_again:"再次保存，正文未变",line_endings_changed:"行内容相同，换行形式变化"};
  if(!result.archive_comparisons?.length)return "";
  return `<section class="detail-section"><h3>所选归档版本对照</h3>${result.archive_comparisons.map(row=>`<div class="research-context"><strong>${e(labels[row.change_kind]||"变化类型待核对")}</strong><p class="form-note">${e(row.earlier.title)} · 较早保存 ${e(when(row.earlier.observed_at))}<br>${e(row.later.title)} · 较晚保存 ${e(when(row.later.observed_at))}<br>程序核对：原始文件指纹${row.raw_changed?"不同":"相同"}；提取正文 ${e(row.earlier.full_text_length)} → ${e(row.later.full_text_length)} 字符。<br>${e(row.notice)}<br>程序差异范围：${row.complete?"完整":"受展示上限限制"}；引用仅为局部原文。</p><button type="button" class="text-button" data-result-version-later="${e(row.later.id)}" data-result-version-earlier="${e(row.earlier.id)}">查看两版原文对照 ↗</button></div>`).join("")}</section>`;
}

document.addEventListener("click",async event=>{
  const button=event.target.closest("[data-result-version-later]");if(!button)return;
  try{await showPublicSource(button.dataset.resultVersionLater);await comparePublicDocuments(button.dataset.resultVersionLater,button.dataset.resultVersionEarlier);}
  catch(error){notify(error.message,true);}
});

function renderPublicDocumentComparison(data) {
  const labels={user_text_revision:"用户修订了粘贴正文",archive_text_changed:"归档正文发生变化",extraction_changed:"同一原始文件的文本提取结果变化",metadata_only:"正文未变，资料说明有变化",raw_archive_changed:"原始响应变化，提取正文未变",observed_again:"再次保存，正文未变",line_endings_changed:"行内容相同，换行形式有变化"};
  const fieldLabels={title:"标题",publisher:"来源说明",extractor_version:"文本处理版本"};
  const diffLines=(data.diff||"").split("\n"),groups=[];
  for(const line of (diffLines[0]?.startsWith("--- ")?diffLines.slice(2):diffLines)){
    if(!line||line.startsWith("@@"))continue;
    const kind=line.startsWith("+")?"added":line.startsWith("-")?"removed":"context";
    const last=groups.at(-1),text=["+","-"," "].includes(line[0])?line.slice(1):line;
    if(last?.kind===kind)last.lines.push(text);else groups.push({kind,lines:[text]});
  }
  const differences=data.change_kind==="line_endings_changed"?'<p class="form-note">行文本相同，差异来自换行形式；两版原文分别保留。</p>':groups.map(group=>`<div class="research-context"><strong>${({added:"新增内容",removed:"删除内容",context:"对照位置附近的原文"})[group.kind]}</strong><div class="body-text">${e(group.lines.join("\n"))}</div></div>`).join("");
  return `<h4>${e(labels[data.change_kind]||"版本差异待核对")}</h4><p class="form-note">${e(data.notice)}<br>较早保存：${e(when(data.earlier.observed_at))}；较晚保存：${e(when(data.later.observed_at))}</p>${!data.complete?'<p class="error-box">对照超过展示上限，以下不是完整差异；请分别打开归档全文核对剩余部分。</p>':""}${Object.entries(data.metadata_changes).map(([key,value])=>`<p class="form-note">${e(fieldLabels[key]||key)}：${e(value.earlier)} → ${e(value.later)}</p>`).join("")}${differences||'<p class="form-note">没有可展示的行内容差异。</p>'}`;
}

async function comparePublicDocuments(id,previous) {
  const selected=state.currentPublicDocument?.id;
  const data=await api("public-documents/"+encodeURIComponent(id)+"/compare?"+new URLSearchParams({previous_id:previous}));
  if(state.currentPublicDocument?.id===selected)$("#public-version-comparison").innerHTML=renderPublicDocumentComparison(data);
}

async function saveWorkMaterialRevision(id,title,text,source_name) {
  const result=await api("work-materials/"+encodeURIComponent(id)+"/revisions",{method:"POST",body:JSON.stringify({title,text,source_name})});
  if(state.currentPublicDocument?.id===id){
    materialRevisionDrafts.delete(state.currentPublicDocument.url);
    if(!result.unchanged)await showPublicSource(result.document.id);
    if(state.currentPublicDocument?.id===result.document.id)$("#public-version-status").textContent=result.unchanged?"原文和来源说明未变，没有创建新版本。":"新版本已保存，旧引用保留。可用新版提问，或明确加入当前研究后续调查。";
  }
  return result;
}

document.addEventListener("submit",async event=>{
  if(event.target.id!=="work-material-revision")return;
  event.preventDefault();const form=event.target,button=form.querySelector("button"),base=state.currentPublicDocument;
  const draft={title:form.elements.title.value,text:form.elements.text.value,source_name:form.elements.source_name.value};
  materialRevisionDrafts.set(base.url,draft);
  const fields=[...form.querySelectorAll("input,textarea,button")];fields.forEach(field=>field.disabled=true);
  try{await saveWorkMaterialRevision(form.dataset.baseDocument,draft.title,draft.text,draft.source_name);}
  catch(error){
    if(state.currentPublicDocument?.id===base.id){
      $("#public-version-status").textContent=error.message;
      if(error.code==="WORK_MATERIAL_CHANGED_REFRESH"){
        try{const fresh=await api("public-documents/"+base.id);$("#public-version-status").innerHTML+=` <button type="button" class="text-button" data-public-source="${e(fresh.latest_document_id)}">查看最新版（保留修订草稿）</button>`;}catch{}
      }
    }
  }
  finally{fields.forEach(field=>field.disabled=false);button.disabled=false;}
});

document.addEventListener("click",async event=>{
  const history=event.target.closest("[data-public-history]"),page=event.target.closest("[data-history-page]"),compare=event.target.closest("[data-document-compare]"),question=event.target.closest("[data-version-question]"),attach=event.target.closest("[data-version-attach]"),select=event.target.closest("[data-history-select]");
  try{
    if(history)await loadPublicDocumentHistory(history.dataset.publicHistory);
    else if(page)await loadPublicDocumentHistory(page.dataset.historyDocument,Number(page.dataset.historyPage));
    else if(compare)await comparePublicDocuments(compare.dataset.documentCompare,compare.dataset.previousDocument);
    else if(select){if(selectResearchDocument(select.dataset.historySelect,select.dataset.historyTitle))$("#public-version-status").textContent="这一版已选入新研究范围，可继续加入其他版本，再回研究台提问；未启动调查。";}
    else if(question){preparePublicDocumentQuestion(state.currentPublicDocument.title,question.dataset.versionQuestion);$("#source-dialog").close();location.hash="research";}
    else if(attach){
      const project=attach.dataset.versionProject;
      if(project!==conversation.id)throw new Error("请返回对应研究后，再加入这一版资料。");
      rememberConversationMaterial(project,state.currentPublicDocument);
      await retryConversationMaterial(project,attach.dataset.versionAttach);
      await openResearchConversation(project,false);
      $("#public-version-status").textContent="已加入后续调查；旧版仍保留，可以对照两版原文。";
    }
  }catch(error){const status=$("#public-version-status");if(status)status.textContent=error.message;else notify(error.message,true);}
});

async function loadCompanies() {
  const root = $("#companies-grid");
  root.innerHTML = empty("正在读取公司资料…");
  try {
    const companies = await api("companies?" + new URLSearchParams({name:$("#company-search").value.trim()}));
    root.innerHTML = companies.length ? companies.map(company=>`<button class="panel company-card" data-company="${e(company.id)}"><span class="company-monogram">${e(company.name.slice(0,1))}</span><h3>${e(company.name)}</h3><p>${e(company.industry_raw || "行业未知")} · ${e(company.scale_raw || "规模未知")}</p>${badge(company.identity_status === "source_id" ? "已有来源公司编号" : "身份未核实",company.identity_status === "source_id" ? "" : "muted")}<span class="subtext">最近取得 ${e(when(company.last_observed_at,true))}</span></button>`).join("") : empty("没有找到公司记录","换一个名称试试。");
  } catch (error) { root.innerHTML = errorBox(error); }
}

const selectedResearchDocuments = new Map();
const researchJobChoices=new Map();
let researchJobResults=[];

function renderResearchJobChoices() {
  const selected=new Set(state.researchIds||[]);
  $("#research-job-list").innerHTML=researchJobResults.length?'<p class="form-note">最多显示20项，可搜索缩小范围。勾选后会直接用于本次研究。</p>'+researchJobResults.map(job=>`<div class="research-job-choice"><label><input type="checkbox" data-research-job="${e(job.id)}" ${selected.has(job.id)?"checked":""}><span><strong>${e(job.title)}</strong><small>${e(job.company||"公司未说明")} · ${e(job.city||"地点未说明")} · ${job.has_detail?"有完整正文":"仅有摘要"}</small></span></label><button type="button" class="text-button" data-job="${e(job.id)}">查看资料</button></div>`).join(""):empty("没有找到岗位资料","可换个关键词，或直接上传工作资料。");
}

async function loadResearchJobChoices() {
  $("#research-job-list").innerHTML='<p class="form-note">正在查找岗位…</p>';
  try {
    const query=$("#research-job-query").value.trim();
    const result=await api("jobs?"+new URLSearchParams({keyword:query,limit:20}));
    researchJobResults=result.jobs;
    for(const job of researchJobResults)researchJobChoices.set(job.id,job);
    renderResearchJobChoices();
  }catch(error){$("#research-job-list").innerHTML=errorBox(error);}
}

$("#research-jobs-panel").addEventListener("toggle",event=>{if(event.target.open)loadResearchJobChoices();});
$("#research-job-search").addEventListener("click",loadResearchJobChoices);
$("#research-job-query").addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();loadResearchJobChoices();}});
document.addEventListener("change",event=>{
  const input=event.target.closest?.("[data-research-job]");if(!input)return;
  const ids=new Set(state.researchIds||[]);
  if(input.checked){if(ids.size>=20){input.checked=false;notify("一次最多选择20个岗位。",true);return;}ids.add(input.dataset.researchJob);}
  else ids.delete(input.dataset.researchJob);
  state.researchIds=ids.size?[...ids]:null;$("#research-source-mode").value="jobs";updateResearchScope();updateResearchApproach();
});
document.addEventListener("click",event=>{
  const remove=event.target.closest("[data-remove-research-job]"),all=event.target.closest("[data-use-all-research-jobs]");
  if(!remove&&!all)return;
  state.researchIds=remove?(state.researchIds||[]).filter(id=>id!==remove.dataset.removeResearchJob):null;
  if(!state.researchIds?.length)state.researchIds=null;
  if(all){$("#research-source-mode").value="jobs";updateResearchApproach();}
  updateResearchScope();renderResearchJobChoices();
});
try {
  const saved=JSON.parse(sessionStorage.getItem("wo-document-selection") || "[]");
  if(Array.isArray(saved)) for(const doc of saved.slice(0,20)) if(/^[a-f0-9]{32}$/.test(doc.id) && typeof doc.title==="string") selectedResearchDocuments.set(doc.id,doc.title.slice(0,300));
} catch {}

function renderSelectedResearchDocuments() {
  const root=$("#research-document-selection");if(!root)return;
  root.innerHTML=selectedResearchDocuments.size ? `<p class="form-note">已选 ${selectedResearchDocuments.size} 份资料，后续追问会沿用。</p><div class="research-sources">${[...selectedResearchDocuments].map(([id,title])=>`<div class="research-source"><strong>${e(title)}</strong><span><button type="button" class="text-button" data-public-source="${e(id)}">查看原文</button><button type="button" class="text-button" data-remove-research-document="${e(id)}">移出 ×</button></span></div>`).join("")}</div><button type="button" class="text-button" data-clear-research-documents>取消限定，从资料库查找</button>` : '<p class="form-note">还没有单独选择文档，可以先添加资料，或从资料库查找。</p>';
}

function selectResearchDocument(id,title) {
  if(!/^[a-f0-9]{32}$/.test(id))return false;
  if(selectedResearchDocuments.size>=20&&!selectedResearchDocuments.has(id)){notify("一次最多选择20份归档资料。",true);return false;}
  selectedResearchDocuments.set(id,title.slice(0,300));
  sessionStorage.setItem("wo-document-selection",JSON.stringify([...selectedResearchDocuments].map(([id,title])=>({id,title}))));
  renderSelectedResearchDocuments();return true;
}

function updateResearchScope() {
  renderSelectedResearchDocuments();
  const root = $("#research-scope");
  if ($("#research-source-mode")?.value === "public") {
    root.innerHTML="<strong>本机已归档资料</strong><br>不读取岗位。网页正文和粘贴工作资料分别标记；按下方归档原文范围查阅；所选资料保留归档版本，没有正文时会提示补充。";
    return;
  }
  if (state.researchIds?.length) {
    root.innerHTML = `<strong>所选 ${state.researchIds.length} 个岗位</strong><br>` + state.researchIds.map(id=>`<button type="button" class="secondary small" data-remove-research-job="${e(id)}">${e(researchJobChoices.get(id)?.title || state.selected.get(id)?.title || state.jobs.get(id)?.title || "指定岗位")} ×</button>`).join(" ");
  } else {
    const labels = {city:"城市",company:"公司",keyword:"关键词",education:"学历",experience:"经验",salary_min:"薪资下限",salary_max:"薪资上限",source:"来源"};
    const filters = Object.entries(state.filters).filter(([key,value])=>value && !["salary_unit","detail"].includes(key));
    root.innerHTML = `<strong>当前筛选范围</strong><br>` + (filters.length ? filters.map(([key,value])=>`${e(labels[key] || key)}：${e(value)}`).join(" · ") : "全部已存岗位") + (state.filters.detail === "detail" ? " · 仅有正文" : state.filters.detail === "list_only" ? " · 仅有摘要" : "") + "<br><small>最多研究 20 个候选，缺失正文会单独说明。</small>";
  }
}

async function loadResearchFormats() {
  try {
    const contract = await api("openapi.json");
    state.serviceContract=contract;
    $('#research-source-mode [value="public"]').disabled=contract.components?.schemas?.ProjectInput?.properties?.job_ids?.minItems!==0;
    const allowed = contract.components?.schemas?.ResearchInput?.properties?.approach?.enum || [];
    const select = $("#research-approach");
    const blueprint=$("[data-blueprint-map]");
    if(blueprint)blueprint.disabled=!(contract.components?.schemas?.StepInput?.properties?.approach?.enum||[]).includes("work_map");
    if (allowed.includes("work_map") && !select.querySelector('[value="work_map"]')) {
      const option = document.createElement("option");
      option.value = "work_map"; option.textContent = "工作地图与工作关系";
      select.append(option);
    }
  } catch (_) { /* The available service contract determines optional formats. */ }
}

function updateResearchApproach() {
  const publicOnly=$("#research-source-mode")?.value === "public";
  if(publicOnly&&$("#research-approach").value==="source_first")$("#research-approach").value="standard";
  $("#research-approach").disabled=false;
  const sourceOption=$("#research-approach").querySelector('option[value="source_first"]');if(sourceOption)sourceOption.disabled=publicOnly;
  const trial = $("#research-approach").value === "source_first";
  const publicSearch = $("#allow-public");
  if (trial) publicSearch.checked = false;
  publicSearch.disabled = trial;
  $("#research-approach-note").hidden = !trial;
}

const findingFacets = {work_task:"岗位建设与工作任务",deliverable:"工作产出",personal_coding_share:"个人编码分工",independent_delivery:"独立端到端负责程度",task_independence:"原文明示的独立子任务",team_collaboration:"团队协作",execution_safety:"执行安全与技术隔离",release_authority:"上线决策与责任",runtime_role:"平台运行中的角色",human_control:"人工控制与接管",qualification:"任职资格与强度",tool_usage:"工具使用",business_context:"岗位业务方向"};
const findingStates = {stated:"登记为原文明示（语义待核）",explicitly_denied:"登记为原文明示否定（语义待核）",not_disclosed:"已读归档正文中未披露（待核实）",unresolved:"尚不能判断（待核实）"};
const findingActors = {job_holder:"招聘岗位承担者",human_operator:"人工操作角色",team:"团队",system:"系统",agent:"Agent",unspecified:"主体未明确"};

function renderFindingActor(row) {
  return Object.prototype.hasOwnProperty.call(row,"actor") ? `<small> · 主体：${e(findingActors[row.actor] || row.actor || "主体未明确")}</small>` : "";
}

function findingQuoteStatus(row) {
  const cites=row.citations || [];
  if (!cites.length) return null;
  if (!cites.every(cite=>cite.unit_id)) {
    return ["covered","incomplete","unverified"].includes(row.source_quote_check?.status) ? row.source_quote_check.status : "unverified";
  }
  for (const cite of cites) {
    if (cite.unit_complete_read !== true || cite.unit_all_parts_shown !== true || !Number.isInteger(cite.unit_start) || !Number.isInteger(cite.unit_end) || cite.unit_start < 0 || cite.unit_end <= cite.unit_start) return "incomplete";
    const parts=cites.filter(part=>part.unit_id === cite.unit_id).sort((a,b)=>a.start-b.start || a.end-b.end);
    let cursor=cite.unit_start;
    for (const part of parts) {
      if (part.unit_start !== cite.unit_start || part.unit_end !== cite.unit_end || !Number.isInteger(part.start) || !Number.isInteger(part.end) || part.start < 0 || part.end <= part.start || part.start > cursor) return "incomplete";
      cursor=Math.max(cursor,part.end);
    }
    if (cursor !== cite.unit_end) return "incomplete";
  }
  return "covered";
}

function renderFindingQuoteWarning(row) {
  const status=findingQuoteStatus(row);
  if (!status || status === "covered") return "";
  const note=status === "incomplete" ? "部分原文单元未完整引用；后文可能含优先、否定或范围限定。请核对完整原文，不凭片段判定资格。" : "完整原文单元的定位信息不足，请核对全文中的条件与限定。";
  return `<p class="form-note" role="note"><strong>引用完整性待核：</strong>${note} 这不改变原登记或判断，也不表示语义通过。</p>`;
}

function renderFindingHistory(revisions, findings) {
  if (!revisions.length) return "";
  return `<details><summary>分项修订记录 · ${revisions.length} 条历史</summary><p class="form-note">历史保留，不作为活动结论。</p>${revisions.map(row=>{
    const replacement=findings.find(item=>item.id === row.superseded_by);
    const v2=Object.prototype.hasOwnProperty.call(row,"actor");
    return `<section class="detail-section"><p>${e(row.id)} → ${e(row.superseded_by || "后续记录")} · ${e(findingFacets[row.facet] || row.facet)}${renderFindingActor(row)} · 原状态：${e(findingStates[row.state] || "待核")}<br>修订说明（研究登记，待核）：${e(replacement?.reason || "请核对原始记录")}</p>${v2 ? `<p class="form-note">原登记理由（待核）：${e(row.reason || "未记录")}${replacement ? `<br>更正后维度：${e(findingFacets[replacement.facet] || replacement.facet)}${renderFindingActor(replacement)}` : ""}</p>${renderFindingQuoteWarning(row)}${(row.citations || []).map(cite=>`${(cite.context || []).length ? `<p class="form-note">原文上下文（定位信息，仍需核对）：${cite.context.map(item=>e(item.text || "")).join(" › ")}</p>` : ""}<blockquote class="body-text">${e(cite.text || "")}</blockquote><p class="form-note">原文字符 ${e(cite.start ?? "?")}–${e(cite.end ?? "?")} · 版本 ${e(cite.snapshot_id || "待核")}</p>`).join("")}` : ""}</section>`;
  }).join("")}</details>`;
}

function renderClaimSentenceSupport(claim, evidence = null) {
  if (!Object.prototype.hasOwnProperty.call(claim,"bindings") && !Object.prototype.hasOwnProperty.call(claim,"sentence_citations")) return "";
  return `<details class="detail-section" open><summary>已声明的支持子集 · 仍需语义核对</summary><p class="form-note">分句绑定不保证语义支持。请继续核对主体、范围、资格强度与遗漏；这些分句不是额外独立证据。</p>${(claim.bindings || []).map(binding=>`<p class="form-note">分项 ${e(binding.finding_id)} · 原文分句：${(binding.sentence_ids || []).map(id=>e(id)).join("、")}</p>`).join("")}${(claim.sentence_citations || []).map(cite=>{
    const ev=evidence?.get(cite.evidence_id);
    const canLocate=ev && ev.start <= cite.start && ev.end >= cite.end;
    return `<section class="detail-section"><p class="form-note">${e(cite.finding_id || "分项待核")} · ${e(findingFacets[cite.facet] || cite.facet || "维度待核")}${renderFindingActor(cite)}<br>岗位 ${e(cite.job_id || "待核")} · 版本 ${e(cite.snapshot_id || "待核")} · 原文字符 ${e(cite.start ?? "?")}–${e(cite.end ?? "?")}</p>${(cite.context || []).length ? `<p class="form-note">原文上下文（定位信息，仍需核对）：${cite.context.map(item=>e(item.text || "")).join(" › ")}</p>` : ""}<blockquote class="body-text">${e(cite.text || "")}</blockquote>${canLocate ? `<button class="cite" data-cite="${e(cite.evidence_id)}" data-cite-start="${e(cite.start)}" data-cite-end="${e(cite.end)}">${e(ev.label)} · 定位原文 ↗</button>` : ""}</section>`;
  }).join("")}</details>`;
}

function renderClaimAnalysisNotes(result, index) {
  const notes=[result.analysis_notes,result.source_binding_check?.analysis_notes].find(rows=>Array.isArray(rows) && rows.length) || [];
  const count=Array.isArray(result.claims) ? result.claims.length : 0;
  return notes.filter(note=>note && Number.isInteger(note.index) && note.index >= 0 && note.index < count && note.index === index).map(note=>`<section class="research-context"><strong>多维分析提示 · 仍须语义核对</strong><p class="form-note">多维分析不表示同口径单维可比，也不表示语义通过。${e(note.notice || "")}</p>${(note.sides || []).map(side=>`<p class="form-note">分项 ${e(side.finding_id || "待核")} · 岗位 ${e(side.job_id || "待核")} · ${e(findingFacets[side.facet] || side.facet || "维度待核")}${renderFindingActor(side)}</p>`).join("")}</section>`).join("");
}

function renderReviewScopeContext(packet) {
  const scope=packet.scope_context;
  if (!scope || !Array.isArray(scope.jobs)) return "";
  const jobs=scope.jobs.filter(job=>job.layer === "frozen_job_metadata");
  const identityStates={source_id:"有来源公司编号（身份仍待核）",unknown:"待核（未知）",unverified:"待核（未核实）",not_disclosed:"待核（未披露）",source_reported_unverified:"待核（来源标注，未独立核实）"};
  return `<section class="research-context"><h3>冻结岗位标识（不是JD逐字内容）</h3><p class="form-note">${e(scope.notice || "")} 这些标识不证明岗位隶属或当前招聘状态，公司身份仍待核。</p>${jobs.map(job=>`<section class="detail-section"><p class="body-text">岗位标题：${e(job.title || "标题待核")}<br>公司标注：${e(job.company_name_raw || "公司名称待核")}<br>身份状态：${e(identityStates[job.company_identity_status] || "待核")}</p><details><summary>查看冻结标识与版本</summary><p class="form-note">岗位标识：${e(job.job_id || "待核")}<br>版本：${e(job.snapshot_id || "待核")}<br>资料层：冻结岗位元数据</p></details></section>`).join("")}</section>`;
}

function renderReviewFindings(packet) {
  const scopeContext=renderReviewScopeContext(packet);
  const findings = (packet.source_findings || []).filter(row=>row.active !== false);
  const history = packet.source_finding_history || (packet.source_findings || []).filter(row=>row.active === false);
  const supportedClaims = (packet.claims || []).map((claim,index)=>{
    const support=renderClaimAnalysisNotes(packet,claim.index ?? index)+renderClaimSentenceSupport(claim);
    return support ? `<section class="detail-section"><h4>判断 ${(claim.index ?? index)+1} 的分句支持</h4><p class="body-text">${e(claim.text || "")}</p>${support}</section>` : "";
  }).join("");
  if (!findings.length && !history.length && !supportedClaims) return scopeContext;
  const titles = new Map();
  const addTitle = source=>{const id=source.job_id || source.id;if(id && source.title && !titles.has(id))titles.set(id,source.title);};
  (packet.scope?.jobs || []).forEach(addTitle);
  (packet.frozen_sources || []).forEach(addTitle);
  (packet.claims || []).forEach(claim=>(claim.citations || []).forEach(addTitle));
  return scopeContext+`<section class="research-context"><h3>原文分项记录 · 一并核对</h3><p class="form-note">以下是研究登记，明示与否定的解释仍需语义审核，不表示已经核对通过。岗位建设任务、个人分工、独立程度、上线责任与平台运行角色分别核对；流程中的人或Agent不自动等于应聘者。未知不能抹去已披露的原文动作。</p>${[...new Set(findings.map(row=>row.job_id))].map(id=>`<section class="detail-section"><h4>${e(titles.get(id) || "指定岗位 · "+id)}</h4>${[false,true].map(unknown=>{const selected=findings.filter(row=>row.job_id===id && ["not_disclosed","unresolved"].includes(row.state)===unknown);return selected.length?`<h5>${unknown?"待核实的维度（不等于没有该职责）":"有原文分句的登记"}</h5>${selected.map(row=>`<section class="detail-section"><strong>${e(findingFacets[row.facet] || row.facet_label || row.facet)}</strong>${renderFindingActor(row)} ${badge(findingStates[row.state] || "状态待核","muted")}<small> ${e(row.id)}</small>${renderFindingQuoteWarning(row)}${(row.citations || []).map(cite=>`${cite.context?.length?`<p class="form-note">原文上下文：${cite.context.map(item=>e(item.text || "")).join(" › ")}</p>`:""}<blockquote class="body-text">${e(cite.text || "")}</blockquote><p class="form-note">原文字符 ${e(cite.start ?? "?")}–${e(cite.end ?? "?")}</p>`).join("")}</section>`).join("")}`:"";}).join("")}</section>`).join("")}${renderFindingHistory(history,[...findings,...history])}${supportedClaims}</section>`;
}

function renderSourceFindings(result, evidence) {
  const all = result.source_findings || [];
  if (!all.length) return "";
  const jobs = new Map(result.scope.jobs.map(job=>[job.id,job]));
  const content = [...new Set(all.map(row=>row.job_id))].map(id=>{
    const job = jobs.get(id);
    const active = all.filter(row=>row.job_id === id && row.active);
    const groups = [false,true].map(unknown=>{
      const selected = active.filter(row=>["not_disclosed","unresolved"].includes(row.state) === unknown);
      if (!selected.length) return "";
      return `<h4>${unknown ? "待核实的维度" : "有原文分句的登记"}</h4>${selected.map(row=>`<section class="detail-section"><strong>${e(findingFacets[row.facet] || row.facet)}</strong>${renderFindingActor(row)} ${badge(findingStates[row.state] || "状态待核","muted")}<small> ${e(row.id)}</small>${renderFindingQuoteWarning(row)}${(row.citations || []).map(cite=>`<blockquote>${e(cite.text)}</blockquote><p class="form-note">原文字符 ${e(cite.start)}–${e(cite.end)} ${evidence.has(cite.evidence_id) ? `<button class="cite" data-cite="${e(cite.evidence_id)}" data-cite-start="${e(cite.start)}" data-cite-end="${e(cite.end)}">${e(evidence.get(cite.evidence_id).label)} · 定位原文 ↗</button>` : "来源待定位"}</p>`).join("")}</section>`).join("")}`;
    }).join("");
    return `<section class="detail-section"><h3>${e(job?.title || id)} · ${e(job?.company || "公司待核")}</h3>${groups}</section>`;
  }).join("");
  const revisions = all.filter(row=>!row.active);
  const history = renderFindingHistory(revisions,all);
  return `<section class="research-context"><h2>原文分项记录 <small>试验 · 语义待核</small></h2><p class="form-note">这是研究中的分项登记，不是人工审核通过。未知不等于没有职责；模型分析不能覆盖原文动作。</p>${content}${history}</section>`;
}

function highlightCitation(details, start, end) {
  const quote = $("blockquote",details);
  if (!quote) return;
  const text = quote.textContent;
  const characters = Array.from(text);
  const base = Number(details.dataset.evidenceStart);
  const from = Number(start) - base, to = Number(end) - base;
  quote.innerHTML = Number.isInteger(from) && Number.isInteger(to) && from >= 0 && to > from && to <= characters.length
    ? e(characters.slice(0,from).join("")) + "<mark>" + e(characters.slice(from,to).join("")) + "</mark>" + e(characters.slice(to).join(""))
    : e(text);
}

function renderRevisionScope(row) {
  return Number.isInteger(row.previous_scope_version)&&Number.isInteger(row.current_scope_version)&&row.previous_scope_version!==row.current_scope_version
    ? '<p class="form-note">研究范围或目标已经调整；本次是在新范围内重新核对旧判断，不表示外部工作发生变化。</p>' : "";
}
function renderCognitiveRevisions(result, evidence) {
  const revisions=result.cognition_revisions || [];
  if (!revisions.length) return "";
  const labels={retain:"保留",revise:"修订",withdraw:"撤回",unresolved:"仍待核实"};
  const reviewLabels={waiting_review:"待核对",completed:"项目内已接受（不等于独立质量审核）"};
  const priorState=row=>(reviewLabels[row.previous_review_state] || row.previous_review_state)+(row.previous_quality_review?.status==="rejected"?" · 原质量核对未通过（"+(row.previous_quality_review.reviewer_kind==="human"?"人工核对":"Agent辅助，非独立人审")+"）":"");
  return `<section class="detail-section"><h2>认识修正记录</h2><p class="form-note">记录认识为什么保留或改变；不等于外部工作需求变化，也不表示旧判断已获人审。</p>${revisions.map(row=>`<article class="panel"><h3>${e(labels[row.decision])}旧判断 ${e(row.previous_claim_index+1)}</h3><p><strong>原判断：</strong>${e(row.previous_statement)}</p>${row.new_statements.map(text=>`<p><strong>本轮判断：</strong>${e(text)}</p>`).join("")}<p>${e(row.reason)}</p>${renderRevisionAspects(row,evidence)}${renderRevisionScope(row)}<p class="form-note">原步骤状态 ${e(priorState(row))} · ${row.evidence_relation === "reread" ? "重读原材料" : "含旧轮未读的引用；不表示新发布资料"}</p>${row.evidence_ids.filter(id=>evidence.has(id)).map(id=>`<button class="cite" data-cite="${e(id)}">${e(evidence.get(id).label)} ↗</button>`).join(" ")}<button class="text-button" data-open-run="${e(row.previous_run_id)}">查看旧研究 ↗</button></article>`).join("")}</section>`;
}

const workDimensionLabels={business:"业务问题",task:"任务",deliverable:"交付物",responsibility:"责任",ability:"能力",tool:"工具"};
const workPredicateLabels={supports:"支撑",requires:"需要",produces:"产出",contradicts:"反驳"};
function renderKnowledgeSupport(rows) {
  if(!rows?.length)return "";
  return `<details class="research-context"><summary>原判断、要求性质与引用来源 · ${rows.length} 条</summary><p class="form-note">保留原研究的判断口径，仍须核对原文；关系中的“需要”不自动表示招聘必备资格。</p>${rows.map(row=>{
    const sources=[...new Map((row.source_references||[]).map(ref=>[ref.public_document_id||ref.job_id||ref.document_id||ref.id,ref])).values()];
    return `<section><p><strong>原判断 ${row.claim_index+1}</strong> · ${e(workDimensionLabels[row.category]||"维度待核")} · ${e(claimBasisLabels[row.basis]||"解释性质待核")} · ${e(requirementLabels[row.requirement]||"要求性质待核")}</p><p>${e(row.text)}</p>${sources.map(ref=>`<p class="form-note">引用来源：${e(ref.title||"归档资料")}${ref.company?" · "+e(ref.company):""} ${ref.public_document_id?`<button class="text-button" data-public-source="${e(ref.public_document_id)}">查看归档全文 ↗</button>`:ref.document_id?`<button class="text-button" data-source="${e(ref.document_id)}">查看原文版本 ↗</button>`:""}</p>`).join("")}</section>`;
  }).join("")}</details>`;
}

function renderMapRetention(data) {
  const states={candidate:"待核对",active:"已采纳",conflicted:"存在冲突",rejected:"已拒绝",withdrawn:"已撤回",superseded:"已有新版"};
  const domains='<option value="">选择工作类型</option>'+data.domains.map(row=>`<option value="${e(row.id)}" data-domain-key="${e(row.domain_key)}">${e(row.name)} · 第${row.version}版 · ${e(states[row.status]||row.status)}</option>`).join("");
  const relations=[...(data.ability_relations||[]).map(row=>({...row,kind:"ability_relation",source_text:row.task,target_text:row.ability,source_kind:"task",target_kind:"ability",predicate:"supports"})),...(data.work_relations||[]).map(row=>({...row,kind:"work_relation"}))];
  return `<p class="form-note">${e(data.notice)} 工作类型保留问题、任务、产出、边界及未知；关系保留解释性质和迁移限制；有关联比较时一并保留双方依据与比较条件。</p>${data.work_types.map(row=>`<section class="research-context"><h3>${e(row.name)}</h3>${renderKnowledgeSupport(row.supporting_claims)}${row.saved_id?`<p>${e(states[row.saved_status]||row.saved_status)} · <a href="#knowledge" data-knowledge-project="${e(data.project_id||'')}">查看领域定义与来源 ↗</a></p>`:`<form data-map-save="type-${row.index}" data-kind="work_type" data-index="${row.index}"><label>保存方式<select name="previous_domain_id"><option value="">建立新的工作类型候选</option>${domains.replace('<option value="">选择工作类型</option>',"")}</select></label><p class="form-note">选择已有定义时保存为新版本，保留原版本。</p><button class="secondary small">保留工作类型候选</button></form>`}</section>`).join("")}${relations.map(row=>`<form class="research-context" data-map-save="${row.kind}-${row.index}" data-kind="${row.kind}" data-index="${row.index}"><h3>${e(workDimensionLabels[row.source_kind])}：${e(row.source_text)} → ${e(workPredicateLabels[row.predicate])} → ${e(workDimensionLabels[row.target_kind])}：${e(row.target_text)}</h3>${renderKnowledgeSupport(row.supporting_claims)}<label>归入哪个工作类型<select name="domain_id" required>${domains}</select></label><label>是否更新已有关系<select name="previous_relation_id"><option value="">新建关系候选</option>${data.relations.map(old=>`<option value="${e(old.id)}" data-domain-id="${e(old.domain_id)}" data-domain-key="${e(old.domain_key)}">${e(old.source_text)} → ${e(workPredicateLabels[old.predicate]||"关系")} → ${e(old.target_text)}</option>`).join("")}</select></label>${row.saved_id?`<p class="form-note">这条关系已有保存记录；同一类型重复保存会复用原记录，也可明确选择其他类型。</p>`:""}${row.comparisons?.length?`<p class="form-note">同时保留 ${row.comparisons.length} 项关联比较及双方依据，比较解释仍需核对。</p>`:""}<button class="secondary small">保留这条工作关系</button></form>`).join("")}<p><a href="#knowledge" data-knowledge-project="${e(data.project_id||'')}">到领域与证据核对候选、原文及历史版本 ↗</a></p>`;
}

document.addEventListener("click",async event=>{
  const button=event.target.closest("[data-map-retention-open]");if(!button)return;
  const root=button.closest("[data-map-retention]"),body=root.querySelector("[data-map-retention-body]");
  button.disabled=true;
  try{body.innerHTML=renderMapRetention(await api("knowledge/research/"+encodeURIComponent(root.dataset.mapRetention)));}
  catch(error){body.innerHTML=errorBox(error);}finally{button.disabled=false;}
});

document.addEventListener("change",event=>{
  if(event.target.name!=="domain_id"||!event.target.closest("[data-map-save]"))return;
  const select=event.target.form.elements.previous_relation_id;
  for(const option of select.options)if(option.value)option.disabled=option.dataset.domainId!==event.target.value&&option.dataset.domainKey!==event.target.selectedOptions[0]?.dataset.domainKey;
  if(select.selectedOptions[0]?.disabled)select.value="";
});

document.addEventListener("submit",async event=>{
  const form=event.target;if(!form.matches("[data-map-save]"))return;event.preventDefault();
  const root=form.closest("[data-map-retention]"),body=root.querySelector("[data-map-retention-body]"),button=event.submitter||form.querySelector("button");
  const data=form.dataset.kind==="work_type"?{work_type_index:Number(form.dataset.index),previous_domain_id:form.elements.previous_domain_id.value||null}:{[form.dataset.kind==="work_relation"?"work_relation_index":"ability_relation_index"]:Number(form.dataset.index),domain_id:form.elements.domain_id.value,previous_relation_id:form.elements.previous_relation_id.value||null};
  const drafts=[...body.querySelectorAll("form")].filter(row=>row!==form).map(row=>({key:row.dataset.mapSave,values:[...row.querySelectorAll("select")].map(select=>[select.name,select.value])}));
  button.disabled=true;
  try{
    const path="knowledge/research/"+encodeURIComponent(root.dataset.mapRetention);
    await api(path,{method:"POST",body:JSON.stringify(data)});
    body.innerHTML=renderMapRetention(await api(path));
    for(const draft of drafts){const row=body.querySelector(`[data-map-save="${draft.key}"]`);if(row)for(const [name,value] of draft.values)row.elements[name].value=value;}
    notify("结构化候选已保存，来源和原报告保留。");
  }catch(error){notify(error.message,true);button.disabled=false;}
});

function mapInvestigationButton(result,section,index,label) {
  if(!result.project_id||!result.run_id)return "";
  return `<button type="button" class="text-button" data-map-investigation="${e(section)}" data-map-index="${index}" data-map-run="${e(result.run_id)}" data-map-project="${e(result.project_id)}">${e(label)} ↗</button>`;
}
function mapInvestigationPrompt(result,section,index) {
  const map=result.work_map;if(!map)throw new Error("原工作地图目前不可读取。");
  let title,details,kind="counterexample";
  if(section==="boundary"){
    const row=map.work_types[index];if(!row)throw new Error("原工作类型已无法定位。");
    title="核实工作类型边界："+row.name;
    details="原图待验证的边界："+row.boundary+"\n原图提出的核实方向："+row.next_check;
  }else if(section==="relation"){
    const row=map.work_relations?.[index];if(!row)throw new Error("原工作关系已无法定位。");
    title="核实关系："+row.source_text+" → "+row.target_text;
    details="原图解释："+row.rationale+"\n原图适用与迁移边界："+row.transfer_limit;
  }else if(section==="comparison"){
    const row=map.comparisons?.[index];if(!row)throw new Error("原比较已无法定位。");
    title="核实共用、差异与迁移比较";
    details="比较关系："+row.relation_indices.map(i=>{const r=map.work_relations[i];return r.source_text+" → "+r.target_text;}).join("；")+"\n共用点："+row.common_ground+"\n差异："+row.differences+"\n迁移条件："+row.transfer_conditions+"\n仍待核实："+row.unknowns.join("；");
  }else if(section==="ability"){
    const row=map.ability_relations?.[index];if(!row)throw new Error("原能力关系已无法定位。");
    title="核实任务与能力关系："+row.task+" → "+row.ability;
    details="原图解释："+row.rationale+"\n原图迁移边界："+row.transfer_limit;
  }else if(section==="unknown"){
    const row=map.unknowns[index];if(typeof row!=="string")throw new Error("原未知项已无法定位。");
    title="继续调查原图未知项";details=row;kind="investigate";
  }else throw new Error("无法识别这条地图核实入口。");
  const instruction=kind==="counterexample"?"请重读相关原文，查找不支持该解释的证据及其他合理解释；没有反例不等于解释已被证明。必要时保留、修订或撤回相关旧判断，区分认识变化与外部工作变化。":"请查现有范围内的证据，区分能回答的部分与仍然未知的部分，并说明下一步需要什么资料。";
  let question=title+"\n"+details+"\n"+instruction;
  if(question.length>4000)question=(title+"\n"+details).slice(0,3600)+"\n（这里只保留原图节选，请补齐要核实的条件。）\n"+instruction;
  return {question,kind};
}
async function prepareMapInvestigation(button) {
  const runId=button.dataset.mapRun,projectId=button.dataset.mapProject;
  const run=await api("research/"+encodeURIComponent(runId));
  if(run.state==="invalidated"||run.result?.status!=="completed"||run.result.project_id!==projectId)throw new Error("来源研究已不可用，未准备新的调查。");
  const project=await api("projects/"+encodeURIComponent(projectId));
  const step=project.steps?.find(row=>row.run_id===runId);
  if(!step||!["completed","waiting_review","superseded"].includes(step.state)||project.state==="invalidated")throw new Error("原调查暂时不能作为追问对象，请先查看原研究记录。");
  const prompt=mapInvestigationPrompt(run.result,button.dataset.mapInvestigation,Number(button.dataset.mapIndex));
  await openResearchConversation(projectId);
  if(conversation.id!==projectId||conversation.project?.state==="invalidated")throw new Error("研究已切换或不可用，未覆盖当前问题。");
  const input=$("#conversation-question");
  const combined=input.value.trim()?input.value+"\n\n"+prompt.question:prompt.question;
  if(combined.length>4000)throw new Error("当前草稿与地图问题合计过长，请先精简；原草稿已保留。");
  conversation.replyToStepId=step.id;renderConversationReply();
  input.value=combined;
  const select=$("#conversation-kind");if(select)select.value=prompt.kind;
  input.focus();input.scrollIntoView({block:"center",behavior:"smooth"});
  notify("已定位原轮并准备核实问题，可编辑后继续；尚未调用模型。");
}
document.addEventListener("click",async event=>{
  const button=event.target.closest("[data-map-investigation]");if(!button)return;
  button.disabled=true;try{await prepareMapInvestigation(button);}catch(error){notify(error.message,true);}finally{button.disabled=false;}
});
function renderWorkRelations(result,refs,claims,basis) {
  const rows=result.work_map.work_relations||[];if(!rows.length)return "";
  return `<h2>业务与工作关系</h2><p class="form-note">关系连接具体工作，不自动表示招聘必备资格；要求强度与主体仍须展开支撑判断核对。</p>${rows.map((row,index)=>{
    const ids=new Set(row.claim_indices.flatMap(index=>result.claims[index]?.evidence_ids||[]));
    const sources=(result.evidence||[]).filter(ev=>ids.has(ev.id));
    const scope=sources.some(ev=>ev.job_id)?"仅适用于引用的岗位及本条解释边界":sources.some(ev=>ev.evidence_kind==="work_material")?"用户补充资料所述工作，未独立核实，不证明招聘资格或已执行":"公开业务/技术背景，不证明岗位个人责任或必备资格";
    return `<article class="panel"><h3>${e(workDimensionLabels[row.source_kind])}：${e(row.source_text)} → ${e(workPredicateLabels[row.predicate])} → ${e(workDimensionLabels[row.target_kind])}：${e(row.target_text)}</h3><p>${basis(row)} ${e(row.rationale)}</p><p><strong>适用与迁移边界：</strong>${e(row.transfer_limit)}</p><p class="form-note">来源范围：${e(scope)}</p>${refs(row)}<details><summary>查看要求性质、主体与支撑判断</summary>${claims(row)}</details>${mapInvestigationButton(result,"relation",index,"查证这条关系与迁移条件")}</article>`;
  }).join("")}`;
}
function renderComparisonDetails(row) {
  return `<p><strong>共用点：</strong>${e(row.common_ground)}</p><p><strong>差异：</strong>${e(row.differences)}</p><p><strong>迁移条件：</strong>${e(row.transfer_conditions)}</p><p><strong>仍待核实：</strong>${(row.unknowns||[]).map(e).join("；")}</p>`;
}
function renderMapComparisons(result,refs,claims,basis) {
  const map=result.work_map;if(!map.comparisons?.length)return "";
  return `<h2>共用、差异与迁移比较</h2><p class="form-note">依据来自所连接关系的两端判断；这些引用帮助回查，比较解释仍需核对。</p>${map.comparisons.map((row,index)=>`<article class="panel"><h3>关系比较 ${index+1} ${basis(row)}</h3>${renderComparisonDetails(row)}${refs(row)}<details><summary>查看比较对象与双方判断</summary>${row.relation_indices.map(i=>{const r=map.work_relations[i];return `<p>关系 ${i+1}：${e(r.source_text)} → ${e(r.target_text)}</p>`;}).join("")}${claims(row)}</details>${mapInvestigationButton(result,"comparison",index,"查证这个比较与迁移条件")}</article>`).join("")}`;
}
let workGraphSerial=0;
function renderWorkRelationGraph(result,refs,claims,basis) {
  const map=result.work_map;if(!map)return "";
  const relations=[...(map.work_relations||[]).map((row,index)=>({...row,index,kind:"relation",label:workPredicateLabels[row.predicate]||row.predicate})),...(map.ability_relations||[]).map((row,index)=>({...row,index,kind:"ability",source_kind:"task",target_kind:"ability",source_text:row.task,target_text:row.ability,label:"关联能力"}))];
  if(!relations.length)return "";
  const nodes=new Map(),groups=new Map(),order=["business","task","deliverable","responsibility","ability","tool","unspecified"];
  const nodeFor=(kind,text)=>{
    kind=order.includes(kind)?kind:"unspecified";const key=kind+":"+text;
    if(!nodes.has(key)){
      const node={id:nodes.size,kind,text:String(text||"未命名内容")};nodes.set(key,node);
      if(!groups.has(kind))groups.set(kind,[]);groups.get(kind).push(node);
    }
    return nodes.get(key);
  };
  relations.forEach(row=>{row.source=nodeFor(row.source_kind,row.source_text);row.target=nodeFor(row.target_kind,row.target_text);});
  const columns=order.filter(kind=>groups.has(kind)),width=Math.max(460,columns.length*210+30),height=Math.max(...[...groups.values()].map(rows=>rows.length))*96+215;
  columns.forEach((kind,column)=>groups.get(kind).forEach((node,index)=>{node.x=column*210+25;node.y=index*96+180;}));
  const marker="work-arrow-"+(++workGraphSerial);
  const edges=relations.map((row,index)=>{
    const from=row.source,to=row.target,forward=to.x>from.x,same=to.x===from.x;
    const x1=from.x+(forward||same?170:0),y1=from.y+33,x2=to.x+(forward?0:170),y2=to.y+33;
    const bend=same?Math.max(x1,x2)+45:(x1+x2)/2;
    const direction=forward?1:-1,lane=Math.min(y1,y2)-95-(index%4)*18;
    const path=same?`M${x1},${y1} C${bend},${y1-28} ${bend},${y2+28} ${x2},${y2}`:Math.abs(to.x-from.x)>210?`M${x1},${y1} C${x1+direction*25},${lane} ${x2-direction*25},${lane} ${x2},${y2}`:`M${x1},${y1} C${bend},${y1} ${bend},${y2} ${x2},${y2}`;
    return `<path class="work-graph-edge" data-graph-edge="${index}" data-graph-pick="${index}" role="button" tabindex="0" aria-label="查看关系 ${index+1}：${e(row.source_text)} → ${e(row.label)} → ${e(row.target_text)}" d="${path}" marker-end="url(#${marker})"><title>${e(row.source_text)} → ${e(row.label)} → ${e(row.target_text)}</title></path>`;
  }).join("");
  const wrap=value=>{
    const lines=[];let line="",size=0;
    for(const char of Array.from(value)){
      const next=char.codePointAt(0)>255?13:7;
      if(size+next>148&&line){lines.push(line);line="";size=0;}
      line+=char;size+=next;
    }
    if(line)lines.push(line);
    return lines.length>3?[...lines.slice(0,2),lines[2].slice(0,-1)+"…"]:lines;
  };
  const boxes=[...nodes.values()].map(node=>`<g class="work-graph-node" data-graph-node="${node.id}" transform="translate(${node.x},${node.y})"><title>${e(workDimensionLabels[node.kind]||"维度未说明")}：${e(node.text)}</title><rect width="170" height="66" rx="9"/><text x="11" y="${wrap(node.text).length===1?38:22}">${wrap(node.text).map((line,index)=>`<tspan x="11" dy="${index?17:0}">${e(line)}</tspan>`).join("")}</text></g>`).join("");
  return `<details class="work-graph-panel" open data-work-graph><summary>本轮工作关系图 <span>${nodes.size} 个内容节点 · ${relations.length} 条关系</span></summary><p class="form-note">选择一条关系或点击连线，查看解释、边界和原文依据。连线只表示本轮研究的解释，仍需核对。</p><label>查看哪条关系<select data-graph-choice><option value="">显示全部关系</option>${relations.map((row,index)=>`<option value="${index}">${index+1}. ${e(row.source_text)} → ${e(row.label)} → ${e(row.target_text)}</option>`).join("")}</select></label><div class="work-graph-scroll"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" style="min-width:${Math.min(width,900)}px" role="group" aria-label="本轮工作关系图"><defs><marker id="${marker}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#869d86"/></marker></defs>${columns.map((kind,column)=>`<text class="work-graph-column" x="${column*210+110}" y="30" text-anchor="middle">${e(workDimensionLabels[kind]||"维度未说明")}</text>`).join("")}${edges}${boxes}</svg></div><div class="work-graph-explanations">${relations.map((row,index)=>`<section data-graph-detail="${index}" data-graph-from="${row.source.id}" data-graph-to="${row.target.id}" hidden><h3>${e(row.source_text)} → ${e(row.label)} → ${e(row.target_text)}</h3><p>${basis(row)} ${e(row.rationale)}</p><p><strong>适用与迁移边界：</strong>${e(row.transfer_limit)}</p>${refs(row)}${claims(row)}${mapInvestigationButton(result,row.kind,row.index,"继续查证这条关系")}</section>`).join("")}</div></details>`;
}
function selectWorkGraphRelation(select) {
  const root=select.closest("[data-work-graph]"),value=select.value;
  if(!root)return;
  const selected=$$("[data-graph-detail]",root).find(item=>item.dataset.graphDetail===value);
  for(const item of $$("[data-graph-detail]",root))item.hidden=item!==selected;
  for(const edge of $$("[data-graph-edge]",root)){
    edge.classList.toggle("is-dimmed",Boolean(selected)&&edge.dataset.graphEdge!==value);
    edge.classList.toggle("is-selected",Boolean(selected)&&edge.dataset.graphEdge===value);
  }
  for(const node of $$("[data-graph-node]",root))node.classList.toggle("is-dimmed",Boolean(selected)&&![selected.dataset.graphFrom,selected.dataset.graphTo].includes(node.dataset.graphNode));
}
document.addEventListener("change",event=>{if(event.target.matches?.("[data-graph-choice]"))selectWorkGraphRelation(event.target);});
function pickWorkGraphEdge(edge) {
  const root=edge.closest("[data-work-graph]"),select=root?.querySelector("[data-graph-choice]");
  if(select){select.value=edge.dataset.graphPick;selectWorkGraphRelation(select);}
}
document.addEventListener("click",event=>{const edge=event.target.closest("[data-graph-pick]");if(edge)pickWorkGraphEdge(edge);});
document.addEventListener("keydown",event=>{const edge=event.target.closest?.("[data-graph-pick]");if(edge&&["Enter"," "].includes(event.key)){event.preventDefault();pickWorkGraphEdge(edge);}});
function renderWorkMap(result, evidence) {
  const map = result.work_map;
  if (!map) return "";
  const refs = row => [...new Set(row.claim_indices.flatMap(index=>result.claims[index]?.evidence_ids || []))].filter(id=>evidence.has(id)).map(id=>`<button class="cite" data-cite="${e(id)}">${e(evidence.get(id).label)} ↗</button>`).join(" ");
  const claims = row => row.claim_indices.map(index=>`<p class="form-note">判断 ${index+1} · ${e(({direct:"原文明示",synthesis:"归纳",inference:"待验证解释"})[result.claims[index]?.basis] || "性质待核")} · ${e(requirementLabels[result.claims[index]?.requirement] || "性质待核")}：${e(result.claims[index]?.text || "引用失效，需核对")}</p>`).join("");
  const basis = row => badge(({direct:"原文明示",synthesis:"归纳",inference:"待验证解释"})[row.basis || "inference"],"muted");
  return `<section class="detail-section"><h2>工作类型地图</h2><p>${e(map.scope_note)}</p><p class="form-note">分析版本 ${e(map.version)} · 类型允许重叠；不是岗位互斥占比，也不是行业全景。原文可核对引用，解释仍需语义审核。</p>${renderWorkRelationGraph(result,refs,claims,basis)}${map.work_types.map((row,index)=>`<article class="panel"><h3>${e(row.name)} ${basis(row)}</h3><dl>${detailData("要解决的问题",row.problem)}${detailData("主要任务",row.tasks)}${detailData("交付物",row.deliverables)}${detailData("边界与反例",row.boundary)}${detailData("下一步验证",row.next_check)}</dl>${refs(row)}<details><summary>查看支撑判断</summary>${claims(row)}</details>${mapInvestigationButton(result,"boundary",index,"查证这一边界与其他解释")}</article>`).join("")}${map.ability_relations?.length?'<h2>任务与能力关系</h2>':""}${(map.ability_relations||[]).map((row,index)=>`<article class="panel"><h3>${e(row.task)} → ${e(row.ability)}</h3><p>${basis(row)} ${e(row.rationale)}</p><p><strong>迁移边界：</strong>${e(row.transfer_limit)}</p>${refs(row)}<details><summary>查看要求性质与支撑判断</summary>${claims(row)}</details>${mapInvestigationButton(result,"ability",index,"查证这条能力迁移关系")}</article>`).join("")}${renderWorkRelations(result,refs,claims,basis)}${renderMapComparisons(result,refs,claims,basis)}<h3>混合、未知与未分类</h3><ul>${map.unknowns.map((text,index)=>`<li>${e(text)} ${mapInvestigationButton(result,"unknown",index,"继续查这个未知项")}</li>`).join("")}</ul>${result.run_id&&result.status==="completed"&&state.serviceContract?.paths?.["/api/knowledge/research/{id}"]?`<div data-map-retention="${e(result.run_id)}"><button class="secondary" type="button" data-map-retention-open>保留工作类型与工作关系 ↗</button><div data-map-retention-body></div></div>`:""}</section>`;
}

function renderApplicationPlan(result,evidence,replyStepId=null) {
  const plan=result.application_plan;if(!plan?.actions?.length)return "";
  return `<section class="detail-section"><h2>应用行动 · 研究建议</h2><p class="form-note">目标：${e(plan.goal)} · 采用第 ${e(plan.background_version)} 版个人背景。${e(plan.constraints?"投入与限制："+plan.constraints:"投入限制未说明。")}</p><p class="form-note">${e(plan.notice)} 行动建议仍需结合实际核对，判断审核不代表行动效果已验证。</p><ol>${plan.actions.map((action,index)=>`<li class="detail-section"><h3>${e(action.title)}</h3><p>针对任务或能力：${e(action.task_or_ability)}</p><p><strong>交付物：</strong>${e(action.deliverable)}</p><p><strong>完成检查：</strong>${e(action.completion_check)}</p>${action.assumptions?.length?`<p class="form-note">需要确认的前提：${action.assumptions.map(e).join("；")}</p>`:""}${action.evidence_ids.map(id=>evidence.has(id)?`<button class="cite" data-cite="${e(id)}">${e(evidence.get(id).label)} ↗</button>`:"").join("")}${replyStepId?`<button type="button" class="secondary small" data-action-feedback-step="${e(replyStepId)}" data-action-feedback-index="${index}">回报尝试结果 ↗</button>`:""}</li>`).join("")}</ol>${plan.open_questions?.length?`<h3>行动前还需明确</h3><ul>${plan.open_questions.map(text=>`<li>${e(text)}</li>`).join("")}</ul>`:""}</section>`;
}

function resultSourceComparison(result,runId,replyStepId) {
  if(result.status!=="completed"||!runId||!state.serviceContract?.paths?.["/api/quality/runs/{id}"]?.get)return "";
  return `<section class="detail-section" data-result-sources="${e(runId)}" data-source-reply-step="${e(replyStepId||"")}"><button class="secondary" type="button" data-open-result-sources>展开原文逐段对照</button><p class="form-note">查看本轮原文与引用位置，检查重要条件是否遗漏。只读取归档，不提交审核或启动调查。</p><div data-result-sources-body hidden></div></section>`;
}
async function loadResultSources(button) {
  const panel=button.closest("[data-result-sources]"),body=panel?.querySelector("[data-result-sources-body]");
  if(!panel||!body)return;
  if(!body.hidden){body.replaceChildren();body.hidden=true;button.textContent="展开原文逐段对照";return;}
  body.hidden=false;body.innerHTML='<p class="form-note">正在读取本轮的原文版本…</p>';button.disabled=true;
  try {
    const packet=await api("quality/runs/"+encodeURIComponent(panel.dataset.resultSources));
    if(!panel.isConnected)return;
    body.innerHTML=renderQualitySources(packet,{replyStepId:panel.dataset.sourceReplyStep||null});
    button.textContent="收起原文逐段对照";
  } catch(error) {if(panel.isConnected){body.innerHTML=errorBox(error);button.textContent="收起原文逐段对照";}}
  finally{button.disabled=false;}
}
document.addEventListener("click",event=>{
  const button=event.target.closest("[data-open-result-sources]");if(button)loadResultSources(button);
});

function claimCorrectionButton(stepId,index) {
  return stepId ? `<button type="button" class="text-button" data-correct-step="${e(stepId)}" data-correct-claim="${index}">提出纠正意见</button>` : "";
}
function renderClaimCorrectionTarget(projectId) {
  const target=conversation.correctionTarget;
  if(!target||target.projectId!==projectId)return "";
  return `<div class="research-context"><p><strong>正在纠正这条判断：</strong>${e(target.statement)}</p><p class="form-note">原问题：${e(target.question)}。请在下方填写你的纠正和理由；保存不会直接改写旧判断或采纳知识。</p><button type="button" class="text-button" data-clear-claim-correction>取消针对这条判断，保留输入</button></div>`;
}
function prepareClaimCorrection(stepId,index) {
  const project=conversation.project;
  const step=project?.steps.find(row=>row.id===stepId),claim=step?.result?.claims?.[index];
  if(!project||project.id!==conversation.id||!Number.isInteger(index)||index<0||!claim||step.result.status!=="completed")throw new Error("无法定位原判断，请先重新打开这项研究。");
  const input=$("#conversation-context-content"),previous=conversation.correctionTarget;
  if(input.value.trim()&&(!previous||previous.stepId!==stepId||previous.index!==index))throw new Error("有尚未保存的补充内容，请先保存或清空，再选择要纠正的判断。");
  conversation.correctionTarget={projectId:project.id,stepId,runId:step.run_id,index,question:step.question,statement:claim.text};
  const kind=$("#conversation-context [name=kind]");if(kind)kind.value="correction";
  $("#conversation-correction-target").innerHTML=renderClaimCorrectionTarget(project.id);
  const form=$("#conversation-context"),details=form.closest?.("details");if(details)details.open=true;
  input.focus();input.scrollIntoView({block:"center",behavior:"smooth"});
}
document.addEventListener("click",event=>{
  const button=event.target.closest("[data-correct-claim]");
  if(button){try{prepareClaimCorrection(button.dataset.correctStep,Number(button.dataset.correctClaim));}catch(error){notify(error.message,true);}return;}
  if(event.target.closest("[data-clear-claim-correction]")){conversation.correctionTarget=null;$("#conversation-correction-target").replaceChildren();}
});
document.addEventListener("change",event=>{
  if(event.target.matches?.("#conversation-context [name=kind]")&&event.target.value!=="correction"){
    conversation.correctionTarget=null;$("#conversation-correction-target").replaceChildren();
  }
});

function renderResult(result, target, runId = null, replyStepId = null) {
  const evidence = new Map(result.evidence.map((ev,index)=>[ev.id,{...ev,label:`E${index+1}`}])) ;
  const counts = result.scope.counts;
  const completed = ["completed","evidence_only","analysis_draft"].includes(result.status);
  const reportId = result.report_id;
  const runIdentity = runId || result.run_id;
  target.innerHTML = `<article class="panel result-card"><div class="result-top"><h2>${e(result.mode === "offline" ? "原文证据" : "研究结果")}</h2>${badge(statusLabels[result.status] || result.status,completed ? "" : "amber")}</div><p class="result-question">${e(result.question)}</p><div class="scope-summary"><span>${counts.matched} 个匹配</span>·<span>${counts.unknown} 个条件未知</span>·<span>${counts.candidate_details} 份候选岗位正文</span>·<span>${e(result.scope.archived_public_total || 0)} 份可用归档资料</span>·<span>${e(when(result.created_at))}</span></div>
    ${result.scope.source_note ? `<p class="form-note">${e(result.scope.source_note)}</p>` : ""}
    ${result.question_scope && result.scope.jobs.length ? `<p class="form-note">本轮查阅了 ${e(result.question_scope.read_job_fragments)} 份岗位材料的片段，范围内有 ${e(result.question_scope.available_details)} 份可用正文。${e(result.question_scope.notice)}</p>` : ""}
    ${renderResearchContext({...result,run_id:runIdentity})}
    ${renderResearchCandidates(result)}
    ${result.analysis_origin === "developer_sample" ? `<div class="inline-note"><strong>开发分析样稿 · 非产品Agent输出</strong><p>用于核对方法和成果形式，未获独立人审；不计入Agent完成率或方法收益。</p></div>` : ""}
    ${renderArchiveComparisons(result)}
    ${renderWorkMap(result,evidence)}
    ${renderCognitiveRevisions(result,evidence)}
    ${renderUpstreamRevisionNotices(result)}
    ${renderSubmissionFeedback(result,evidence)}
    ${renderApplicationPlan(result,evidence,replyStepId)}
    ${renderSourceFindings(result,evidence)}
    ${result.source_findings?.length ? `<h2>判断（模型分析）</h2><p class="form-note">自由归纳与推断仍需语义审核，不能覆盖上述原文动作，也不能把个人分工未知改写为没有岗位任务。</p>` : ""}
    ${result.claims.length ? `<div class="claim-list">${result.claims.map((claim,index)=>`<section class="claim">${badge(categoryLabels[claim.category] || claim.category,"muted")} ${badge(requirementLabels[claim.requirement] || claim.requirement,claim.requirement === "preferred" ? "amber" : "")}<p>${e(claim.text)}</p>${replyStepId ? `<button class="text-button" data-conversation-claim="${e(claim.text)}" data-reply-step="${e(replyStepId)}">针对这条判断继续核实 ↗</button>` : ""}${badge(claimBasisLabel(claim),"muted")} ${renderClaimAnalysisNotes(result,index)}${renderClaimSentenceSupport(claim,evidence)}${claim.evidence_ids.map(id=>evidence.has(id) ? `<button class="cite" data-cite="${e(id)}">${e(evidence.get(id).label)} ↗</button>` : "").join("")}${result.status === "completed" ? claimCorrectionButton(replyStepId,index)+renderClaimKnowledge(runIdentity,claim,index,evidence,conversation.knowledge,result.project_id) : ""}</section>`).join("")}</div>` : `<p class="form-note">${result.status === "evidence_only" ? "这是原文证据包，未调用模型，也未进行自动比较或分类。" : "本次没有形成可接受的模型判断。可先查看已有证据，或缩小范围后再研究。"}</p>`}
    <div class="gaps"><strong>资料缺口与研究范围</strong><ul>${result.gaps.map(gap=>`<li>${e(gap)}</li>`).join("")}</ul>${!completed ? `<p>结束原因：${e(reasonLabels[result.stop_reason] || "本次未能完成研究，可核对范围后重试；已有资料仍可查看。")}</p>` : ""}</div>
    ${resultSourceComparison(result,runIdentity,replyStepId)}
    <details class="detail-section"><summary>本次候选与统计口径</summary><p class="form-note">统计在分页前计算。本次实际研究 ${result.scope.jobs.length} 个候选${result.scope.truncated ? "，候选较多，已截取前 20 个，请收窄范围" : ""}；未知条件不等于符合。</p>${result.scope.jobs.map(job=>`<div class="detail-history"><button class="job-link" data-job="${e(job.id)}">${e(job.title)} · ${e(job.company)}</button>${badge(job.has_detail ? "有正文" : "仅摘要","muted")} ${job.match_status === "unknown" ? badge("条件未知","amber") : ""}</div>`).join("")}</details>
    <div class="result-actions">${result.project_id?`<a class="secondary" href="#research/${e(result.project_id)}">返回这项持续研究 ↗</a>`:""}${reportId ? `${badge("已保存")}<a class="secondary" href="/api/reports/${e(reportId)}/download/md" download>下载 Markdown</a><a class="secondary" href="/api/reports/${e(reportId)}/download/json" download>下载 JSON</a>` : runId ? `<button class="primary" data-save-research="${e(runId)}">保存这次研究</button><small class="form-note">保存问题、范围、结果与原文依据。</small>` : ""}</div>
    <section class="detail-section"><h3>原文依据 · ${evidence.size} 个片段</h3><p class="form-note">点击结论后的引用可定位片段；也可核对对应原始文档。引用有效不代表模型解释必然正确。</p>${[...evidence.values()].map(ev=>`<details class="evidence-item" data-evidence="${e(ev.id)}" data-evidence-start="${e(ev.start)}"><summary>${e(ev.label)} · ${e(ev.title)} · ${e(ev.company || (ev.source === "public_web" ? "公开资料" : ""))}</summary>${historicalEvidenceNote(ev)}${ev.source_note ? `<p class="form-note evidence-source-note">${e(ev.source_note)}</p>` : ""}<blockquote>${e(ev.quote)}</blockquote><div class="evidence-meta">${e(sourceLabel(ev))} · 取得 ${e(when(ev.observed_at))}<br>字符 ${ev.start}–${ev.end}${ev.full_text_length ? ` / 原文 ${ev.full_text_length} 字符` : ""} · 发布时间 ${e(ev.source_published_at ? when(ev.source_published_at) : "未知")}<br>${ev.document_id ? `<button data-source="${e(ev.document_id)}">核对来源文档与内容版本 ↗</button>` : ""}${ev.public_document_id ? `<button data-public-source="${e(ev.public_document_id)}">核对归档全文 ↗</button><br>` : ""}${safeURL(ev.url) ? `<a href="${e(safeURL(ev.url))}" target="_blank" rel="noopener noreferrer">打开公开出处 ↗</a>` : ""}</div></details>`).join("")}</section></article>`;
}

function setBusy(busy) {
  $("#start-research").disabled = busy;
  $("#start-research").textContent = busy ? "调查进行中…" : "开始调查 ↗";
}

function renderResearchCandidates(result) {
  const knowledge=[...(result.knowledge_candidates || []),...(result.research_memory_candidates || [])],strategy=result.strategy_candidate;
  if (!knowledge.length && !strategy) return "";
  const evaluation=strategy?.evaluation;
  return `<section class="research-context"><h3>本次候选与固定评测</h3>${knowledge.length ? `<p>研究留下 ${knowledge.length} 条待核对的知识、假设或经验，尚未作为有效记忆使用。</p><ul>${knowledge.map(item=>`<li>${e(item.content)}</li>`).join("")}</ul><a class="secondary small" href="#memory">到知识与偏好核对采纳 ↗</a>` : ""}${strategy ? `<p>提出了一个本地别名候选，尚未自动启用。</p>${evaluation ? `<p>${evaluation.status === "accepted" ? "固定模拟开发集达到门槛，仍需显式审核启用。" : evaluation.status === "rejected" ? "固定模拟开发集未通过门槛，继续使用现有策略。" : "固定评测证据不足，继续使用现有策略。"} 这不是实际市场资料上的改进证据。</p>` : `<p>尚未完成固定评测，不作为有效检索方法使用。</p>`}<a class="secondary small" href="#retrieval">到检索与评测查看依据 ↗</a>` : ""}</section>`;
}

function safeURL(value) {
  try { const url = new URL(value); return ["https:","http:"].includes(url.protocol) ? url.href : ""; }
  catch { return ""; }
}

function renderReviewFeedback(result) {
  const item=result.review_feedback;
  if (!item) return "";
  return `<section class="research-context"><h3>本轮参照的复核诊断（不是新证据）</h3><p>${item.reviewer_kind === "human" ? "人类复核意见，仍须回查原文" : "Agent辅助复核，非人审"}。旧答案未放入本轮证据，旧结果与额度保留。</p><p class="body-text">${e(item.note)}</p><details><summary>查看反馈来源与具体缺口</summary><p>原运行 ${e(item.run_id)} · 复核 ${e(item.review_id)}</p>${Object.values(item.dimensions || {}).map(row=>`<p>${e(row.reason)}</p>`).join("")}${(item.claim_issues || []).map(row=>`<p>原判断 ${e(row.index+1)}：${e(row.note)}</p>`).join("")}${item.omitted_claim_reviews ? `<p>另有 ${e(item.omitted_claim_reviews)} 条复核未放入上下文，未展示不等于没有问题。</p>` : ""}</details></section>`;
}

function renderResearchContext(result) {
  const plan = result.plan;
  const business=result.business_review || {status:"pending"};
  const qualityNote=result.status === "completed" ? `<div class="research-context">${badge(business.status === "approved" && business.reviewer_kind === "human" ? "已人工核对业务质量" : business.status === "rejected" ? "业务质量核对未通过" : "业务质量待核对",business.status === "approved" && business.reviewer_kind === "human" ? "muted" : "amber")}<p>回答已生成表示执行结束；问题交付完整性和语义支持仍须逐项核对。</p><a class="secondary small" href="#quality">逐条核对判断与原文 ↗</a>${result.requirement_policy ? `<details><summary>本次要求性质口径</summary><p>${e(result.requirement_policy)}</p></details>` : ""}</div>` : "";
  const review = result.review;
  const validationNote=result.qualification_validation ? `<details class="research-context"><summary>本轮要求性质检查</summary><p>本轮使用更新后的局部否定识别，恢复时保留本轮检查口径。词面检查不能代替原文语义核对。</p></details>` : "";
  const memories = result.memories || result.memory_used || [];
  const audit=result.audit || {};
  const auditNote=audit.stale_memory || audit.stale_knowledge || audit.stale_dependencies || audit.changed_sources?.length || audit.affected_strategy?.length;
  return `${renderReviewFeedback(result)}${validationNote}${qualityNote}${auditNote ? `<div class="error-box"><strong>这是需要重新核对的历史结果</strong>${audit.stale_memory ? `<p>研究采用的偏好、知识或纠正已变化或撤回，后续研究会采用当前有效版本。</p>` : ""}${audit.stale_dependencies ? `<p>上游研究所用的偏好、纠正或知识已修订/撤回，这些派生认识需要重新核对。</p>` : ""}${audit.stale_knowledge ? `<p>参考的领域定义或关系已经换版、撤回或失效，需要按当前口径重新核对。</p>` : ""}${audit.changed_sources?.length ? `<p>部分来源已变化或原始文件完整性需要核对。历史引用保留当时版本，不能直接当作当前状态。</p>` : ""}${audit.affected_strategy?.length ? `<p>本次使用的检索方法已变化或回退；原始证据仍独立保留，可按当前策略重新研究。</p>` : ""}</div>` : ""}${plan ? `<details class="research-context" open><summary>研究计划与范围</summary><p>${e(plan.objective || "围绕问题查阅资料")}</p>${plan.steps?.length ? `<ol>${plan.steps.map(step=>`<li>${e(typeof step === "string" ? step : step.description || step.title || "查阅资料")}</li>`).join("")}</ol>` : ""}<p>${e(plan.scope_note || "")}</p></details>` : ""}
    ${memories.length ? `<details class="research-context"><summary>本次参考的知识与偏好 · ${memories.length} 条</summary>${memories.map(item=>`<p>${badge(({preference:"偏好",correction:"人工纠正",knowledge:"已采纳知识"})[item.kind] || "已有记录","muted")} ${e(memoryText(item))} <small>第 ${e(item.version || 1)} 版</small></p>`).join("")}<p>以上为研究背景，关键判断仍引用原始材料。</p></details>` : ""}
    ${review ? `<details class="research-context"><summary>程序合同检查与下一步</summary>${(review.checks || []).map(check=>`<p>${badge(check.passed ? "已通过" : "待核对",check.passed ? "" : "amber")} ${e(check.name)}：${e(check.detail || "")}</p>`).join("")}${(review.limitations || []).map(item=>`<p>${e(item)}</p>`).join("")}${review.next_questions?.length ? `<h3>值得继续查的问题</h3><ul>${review.next_questions.map(item=>`<li>${e(item)}${result.run_id ? `<button class="text-button" data-followup-question="${e(item)}" data-followup-run="${e(result.run_id)}">留作待研究问题 ＋</button>` : ""}</li>`).join("")}</ul>` : ""}</details>` : ""}`;
}

const runLabels = {running:"正在研究",finished:"已结束",interrupted:"已中断，可查看进度",failed:"执行失败",invalidated:"相关记忆已忘记，结果已清除"};

const researchHistory={query:"",offset:0,limit:20,request:0};
let researchProjects=[],researchProjectsExpanded=false;

function renderResearchProjects() {
  const root=$("#research-project-list"),query=($("#research-project-query").value||"").trim().toLocaleLowerCase();
  const matches=researchProjects.filter(project=>project.state==="active"&&[project.title,project.goal,project.last_question].some(text=>(text||"").toLocaleLowerCase().includes(query)));
  if(!matches.length){root.innerHTML=empty(query?"没有找到这项研究":"从一个具体问题开始",query?"换个关键词，或新建研究。":"上传资料并提问，之后可以在这里继续。");return;}
  const shown=researchProjectsExpanded||query?matches:matches.slice(0,6);
  root.innerHTML=`<div class="research-project-grid">${shown.map(project=>{
    const status=project.worker_running?"正在研究":project.last_state==="failed"?"本轮未完成":project.last_state==="interrupted"?"已暂停":project.step_count?"可继续":"还未开始";
    const sources=[project.job_count?project.job_count+" 个岗位":"",project.document_count==null?"资料库":project.document_count?project.document_count+" 份文档":""].filter(Boolean).join(" · ")||"待添加资料";
    return `<article class="research-project-card ${conversation.id===project.id?"is-current":""}"><div class="section-heading"><h3>${e(project.title)}</h3>${badge(status,project.worker_running?"":"muted")}</div><p>${e((project.last_question||project.goal||"").slice(0,140))}</p><small>${e(sources)} · ${project.step_count||0} 轮调查 · ${e(when(project.updated_at))}</small><button type="button" class="text-button" data-open-conversation="${e(project.id)}">${conversation.id===project.id?"查看当前研究":"打开并继续"} ↗</button></article>`;
  }).join("")}</div>${!query&&matches.length>6?`<button type="button" class="text-button" data-expand-research-projects>${researchProjectsExpanded?"收起":"查看全部 "+matches.length+" 项研究"}</button>`:""}`;
}

async function loadResearchProjects() {
  try {const items=await api("projects");researchProjects=Array.isArray(items)?items:[];renderResearchProjects();}
  catch(error){$("#research-project-list").innerHTML=errorBox(error);}
}

function prepareNewResearch(clearQuestion=true) {
  captureConversationDraft();clearTimeout(conversation.timer);
  conversation.id=null;conversation.project=null;conversation.renderedId=null;conversation.notesFor=null;
  conversation.notes=[];conversation.knowledge=[];conversation.replyToStepId=undefined;conversation.correctionTarget=null;
  sessionStorage.removeItem("wo-conversation");sessionStorage.removeItem("wo-pending-research");
  $("#research-output").innerHTML="";if(clearQuestion)$("#question").value="";
  $("#research-form").hidden=false;$(".research-layout")?.classList?.remove("research-focused");
  location.hash="research";setBusy(Boolean(state.activeRun));renderResearchProjects();
  $("#research-form").scrollIntoView({block:"start",behavior:"smooth"});$("#question").focus();
}

$("#research-project-query").addEventListener("input",renderResearchProjects);
$("#refresh-research-projects").addEventListener("click",loadResearchProjects);
document.addEventListener("click",event=>{
  const open=event.target.closest("[data-open-conversation]");
  if(open){const hash="#research/"+open.dataset.openConversation;if(location.hash===hash)openResearchConversation(open.dataset.openConversation);else location.hash=hash;return;}
  if(event.target.closest("[data-new-research]")){prepareNewResearch();return;}
  if(event.target.closest("[data-expand-research-projects]")){researchProjectsExpanded=!researchProjectsExpanded;renderResearchProjects();}
});

document.addEventListener("submit",async event=>{
  if(event.target.id!=="conversation-title-form")return;
  event.preventDefault();const id=event.target.dataset.projectId,button=event.target.querySelector("button"),title=event.target.elements.title.value.trim();
  if(!title||conversation.project?.id!==id)return;
  button.disabled=true;
  try {
    await api("projects/"+id+"/title",{method:"POST",body:JSON.stringify({revision:conversation.project.revision,title})});
    if(conversation.id===id)await openResearchConversation(id,false);
    await loadResearchProjects();notify("研究名称已更新。");
  }catch(error){notify(error.message,true);}
  finally{button.disabled=false;}
});

function clearForgottenConversation(projectIds) {
  for(const id of projectIds){conversation.drafts.delete(id);conversation.sourceScopes.delete(id);}
  researchProjects=researchProjects.filter(project=>!projectIds.includes(project.id));renderResearchProjects();
  if(!projectIds.includes(conversation.id))return;
  clearTimeout(conversation.timer);
  conversation.id=null;conversation.project=null;conversation.correctionTarget=null;
  conversation.notes=[];conversation.knowledge=[];conversation.notesFor=null;
  conversation.renderedId=null;conversation.replyToStepId=undefined;conversation.reports.clear();
  sessionStorage.removeItem("wo-conversation");
  $("#research-output").innerHTML=empty("这项研究已忘记","相关判断、纠正和背景已清除，原始岗位资料保留。");
}
window.clearForgottenConversation=clearForgottenConversation;

function resetResearchHistory() {
  researchHistory.request++;researchHistory.query="";researchHistory.offset=0;
  const input=$("#research-history-query");if(input)input.value="";
  $("#research-history-list").replaceChildren();
  $("#research-history-count").textContent="";
  $("#research-history-prev").disabled=true;$("#research-history-next").disabled=true;
}
window.resetResearchHistory=resetResearchHistory;

async function loadResearchHistory(offset=0) {
  const root=$("#research-history-list"),query=$("#research-history-query")?.value.trim()||"";
  const supported=Boolean(state.serviceContract?.paths?.["/api/research-history"]);
  const request=++researchHistory.request;
  if(query!==researchHistory.query)offset=0;
  $("#research-history-prev").disabled=true;$("#research-history-next").disabled=true;
  try {
    const data=await api(supported?"research-history?"+new URLSearchParams({q:query,offset,limit:20}):"research");
    if(request!==researchHistory.request)return;
    const runs=supported?data.items:data;
    researchHistory.query=query;researchHistory.offset=supported?data.offset:0;researchHistory.limit=supported?data.limit:100;
    $("#research-history-query").disabled=!supported;
    $("#research-history-count").textContent=supported?`共 ${data.total} 条研究${data.total?" · 显示 "+(data.offset+1)+"～"+Math.min(data.offset+data.limit,data.total):""}`:"当前服务仅能列出最近的研究，尚不支持历史搜索。";
    $("#research-history-prev").disabled=!supported||data.offset===0;
    $("#research-history-next").disabled=!supported||data.offset+data.limit>=data.total;
    const fields={question:"问题",claim:"回答判断",work_map:"工作地图（历史分析）",cognition_revision:"认识修订（仍须核对）",application_plan:"行动建议（不表示已执行）",gap:"资料缺口",read_source:"已读片段的资料标题",scope_source:"研究范围内的资料标题（不表示已读）"};
    root.innerHTML=runs.length?runs.map(run=>`<div class="panel report-row"><div><h3>${e(run.question.slice(0,160))}${run.question.length>160?"…":""}</h3><p>${e(when(run.created_at))} · ${e(runLabels[run.state]||run.state)}${run.status?" · "+e(statusLabels[run.status]||run.status):""}</p>${run.match?`<p class="form-note">匹配${e(fields[run.match.field]||"历史内容")}：${e(run.match.excerpt)}</p>`:""}</div><button class="secondary small" data-open-run="${e(run.id)}">${run.state==="running"?"查看进度":"打开研究"} ↗</button></div>`).join(""):empty(query?"没有找到匹配的研究":"还没有研究记录",query?"可以换个词，或清空条件查看全部保留记录。":"提交问题后，过程会自动留在这里。");
  }catch(error){if(request===researchHistory.request){root.innerHTML=errorBox(error);$("#research-history-count").textContent="";}}
}

function renderProgress(run) {
  const result = run.result || run.progress || {};
  const isRunning = run.state === "running";
  const friendlyFailure = reasonLabels[run.error_code] || reasonLabels[result.stop_reason];
  $("#research-output").innerHTML = `<article class="panel result-card" aria-live="polite"><div class="result-top">${isRunning ? `<div class="spinner small-spinner"></div>` : ""}<h2>${e(runLabels[run.state] || "研究记录")}</h2></div><p class="form-note">${isRunning ? "正在确认范围、查阅原文和核对依据。你可以继续查看其他资料。" : run.state === "invalidated" ? "相关个人记录已忘记，受影响的派生结果和检查点已清除。可依据当前记录重新研究。" : "已保留查过的证据与剩余预算。继续时沿用原范围和预算，不重复建立研究。"}</p>${friendlyFailure && !isRunning ? `<p class="form-note" role="status">${e(friendlyFailure)}</p>` : ""}${renderResearchContext(result)}<div class="scope-summary">已发起 ${e(result.model_calls || 0)} 次模型调用 · 研究进度自动留存</div><ol class="trace-list">${(result.trace || []).map(item=>`<li>${e(({query_jobs:"确认候选范围",plan_research:"制定研究计划",search_evidence:"检索本地原文",read_job:"查阅岗位正文",read_source_window:"补读岗位正文片段",record_source_findings:"登记原文分项与未知事项",search_public_web:"补查公开资料",read_public_document:"读取并归档公开全文",read_archived_document:"按编号补读归档原文",compare_history:"比较历史版本",compare_archived_versions:"对照所选归档版本",propose_knowledge:"提出待核对知识",propose_research_memory:"提出待核对假设或方法经验",browse_domain_knowledge:"查阅领域定义与关系线索",search_archived_sources:"统一检索已归档原文",propose_investigation:"提出有完成条件的补查",propose_retrieval_strategy:"提出本地别名候选",evaluate_retrieval_strategy:"运行固定模拟评测",finish_research:"提交结论与核对"})[item.tool] || "核对研究资料")}</li>`).join("")}</ol><div class="result-actions">${isRunning ? `<button class="secondary" data-cancel-run="${e(run.id)}">暂停并保留进度</button>` : run.resumable ? `<button class="primary" data-resume-run="${e(run.id)}">继续这次研究 ↗</button>` : `${run.project_id ? `<button class="primary" data-project-open="${e(run.project_id)}">从研究项目查看和继续 ↗</button>` : `<p class="form-note">没有可继续的检查点，可按原问题开始新研究。</p>`}`}</div></article>`;
}

async function openRun(id) {
  clearTimeout(pollTimer);
  const run = await api("research/" + encodeURIComponent(id));
  if (run.project_id || run.result?.project_id) {
    const projectId=run.project_id||run.result.project_id;
    await openResearchConversation(projectId);
    if(conversation.id===projectId)focusConversationRun(id);
    return;
  }
  state.lastRun = id;
  if (state.page !== "research") location.hash = "research";
  if (run.state === "running") { pendingResearch(id); return; }
  if (run.result && run.state === "finished") {
    state.lastResult = {...run.result, ...(run.saved || {})};
    renderResult(state.lastResult,$("#research-output"),id);
  } else renderProgress(run);
}

async function pollResearch(id) {
  clearTimeout(pollTimer);
  try {
    const run = await api("research/" + encodeURIComponent(id));
    if (run.state === "running") {
      renderProgress(run);
      pollTimer = setTimeout(()=>pollResearch(id),1500);
      return;
    }
    state.activeRun = null;
    state.lastRun = id;
    sessionStorage.removeItem("wo-research");
    setBusy(false);
    if (run.result && run.state === "finished") {
      state.lastResult = {...run.result, ...(run.saved || {})};
      renderResult(state.lastResult,$("#research-output"),id);
    } else renderProgress(run);
    loadResearchHistory();
    if (state.page !== "research") notify("研究已停止，可到研究工作台查看记录。");
  } catch (error) {
    state.activeRun = null;
    sessionStorage.removeItem("wo-research");
    setBusy(false);
    $("#research-output").innerHTML = errorBox(error);
  }
}

function pendingResearch(id) {
  state.activeRun = id;
  state.lastRun = id;
  sessionStorage.setItem("wo-research",id);
  setBusy(true);
  renderProgress({id,state:"running"});
  pollResearch(id);
  loadResearchHistory();
}

async function startResearch(event) {
  event.preventDefault();
  if (state.activeRun) return;
  if (materialImporting) { notify("资料正在保存，请稍等。",true); return; }
  const question = $("#question").value.trim();
  if (!question) { notify("请先写下研究问题。",true); return; }
  if ($("#work-material-text").value.trim() && !await saveWorkMaterial()) return;
  updateResearchApproach();
  if (["standard","work_map"].includes($("#research-approach").value)) {
    await startResearchConversation(question,{approach:$("#research-approach").value});return;
  }
  clearTimeout(conversation.timer);conversation.id=null;sessionStorage.removeItem("wo-conversation");
  setBusy(true);
  try {
    const run = await api("research",{method:"POST",body:JSON.stringify({question,
      job_ids:state.researchIds || null,filters:state.researchIds ? {} : state.filters,
      ...(selectedResearchDocuments.size?{public_document_ids:[...selectedResearchDocuments.keys()]}:{}),
      offline:$("#offline").checked,allow_public:$("#allow-public").checked,
      approach:$("#research-approach").value})});
    pendingResearch(run.id);
  } catch (error) { setBusy(false); notify(error.message,true); }
}

let conversationStarting=false;

function restorePendingResearch() {
  if(location.hash && location.hash!=="#research")return;
  let receipt=null;try{receipt=JSON.parse(sessionStorage.getItem("wo-pending-research")||"null");}catch{}
  if(!receipt)return;
  const intent=JSON.parse(receipt.intent);
  $("#question").value=intent.question;
  $("#offline").checked=intent.offline;$("#allow-public").checked=intent.allowPublic;
  $("#research-source-mode").value=intent.publicOnly?"public":"jobs";
  $("#research-approach").value=intent.approach||"standard";
  state.researchIds=intent.jobs;state.filters=intent.filters;
  const titles=new Map(selectedResearchDocuments);selectedResearchDocuments.clear();
  for(const id of intent.documents)selectedResearchDocuments.set(id,titles.get(id)||"所选归档资料");
  conversation.id=receipt.projectId||null;
  if(receipt.projectId)sessionStorage.setItem("wo-conversation",receipt.projectId);
  else sessionStorage.removeItem("wo-conversation");
  notify("已恢复上次未确认的问题和原资料范围。再次开始调查会复用原记录。");
}

async function startResearchConversation(question, options={}) {
  if(conversationStarting)return;
  conversationStarting=true;
  clearTimeout(conversation.timer);
  setBusy(true);
  try {
    const offline=$("#offline").checked,allowPublic=$("#allow-public").checked;
    const approach=options.approach||"standard";
    if(approach==="work_map"&&!(state.serviceContract?.components?.schemas?.StepInput?.properties?.approach?.enum||[]).includes("work_map"))throw new Error("当前服务尚未支持持续工作地图研究，请先安装已准备的更新包。");
    const intent=()=>JSON.stringify({question,publicOnly:$("#research-source-mode")?.value==="public",
      jobs:state.researchIds?.length?[...state.researchIds].sort():null,filters:state.researchIds?.length?{}:state.filters,
      documents:[...selectedResearchDocuments.keys()].sort(),offline,allowPublic,
      ...(approach!=="standard"?{approach}:{})});
    let receipt=null;
    try{receipt=JSON.parse(sessionStorage.getItem("wo-pending-research")||"null");}catch{}
    if(receipt?.intent!==intent()){
      const publicOnly=$("#research-source-mode")?.value === "public";
      const scope = publicOnly ? [] : state.researchIds?.length ? state.researchIds : (await api("jobs?"+new URLSearchParams({...state.filters,limit:20}))).jobs.map(job=>job.id);
      if(!scope.length){
        const hasArchived=selectedResearchDocuments.size>0||(await api("public-documents?limit=1")).total>0;
        if(!hasArchived)throw new Error("当前范围还没有原文，请先粘贴工作资料、归档网页或补充岗位原文。");
        if(!publicOnly){$("#research-source-mode").value="public";updateResearchScope();updateResearchApproach();}
      }
      receipt={intent:intent(),body:{title:question.slice(0,100),goal:question,job_ids:scope,...(selectedResearchDocuments.size?{public_document_ids:[...selectedResearchDocuments.keys()]}:{}),max_calls:24,max_seconds:720,max_rounds:6,max_public:allowPublic?4:0,source_key:"conversation:"+crypto.randomUUID()}};
      sessionStorage.setItem("wo-pending-research",JSON.stringify(receipt));
    }
    const project = await api("projects",{method:"POST",body:JSON.stringify(receipt.body)});
    receipt.projectId=project.id;sessionStorage.setItem("wo-pending-research",JSON.stringify(receipt));
    conversation.id=project.id;sessionStorage.setItem("wo-conversation",project.id);
    conversation.replyToStepId=null;
    await askResearchConversation(question,{offline,allowPublic,approach});
  } catch(error) {setBusy(false);notify(error.message,true);}
  finally{conversationStarting=false;}
}

function projectStepOriginLabel(step) {
  return step.origin==="agent"?"Agent提出的补查":step.origin==="user"?"你安排的调查":"历史调查 · 提问来源未记录";
}

function investigationDraft(proposal) {
  return proposal.question+"\n完成条件："+proposal.completion+"\n所需证据："+proposal.evidence_needed;
}

function proposalPlanningStatus(project,step,index) {
  const outcome=step?.proposal_outcomes?.find(row=>row.proposal_index===index);
  const planned=project?.steps?.find(row=>row.id===outcome?.step_id||row.key===step?.run_id+":proposal:"+index);
  const labels={queued:"已安排，等待调查",running:"已安排，正在调查",waiting_review:"本轮回答已生成，待核对",waiting_material:"已调查，仍待资料",completed:"项目内已接受，不等于独立质量审核",failed:"已安排的调查未完成",interrupted:"已安排的调查已暂停",superseded:"原安排已由补查接替"};
  if(step&&project&&step.scope_version!==project.scope_version)return {state:"historical",label:"原范围建议；使用前须按当前资料重新核实"};
  if(planned)return {state:planned.state,label:planned.result?.business_review?.status==="rejected"?"后续调查的质量核对未通过，原记录保留":labels[planned.state]||"已有调查安排",step:planned};
  const reasons={round_limit:"项目轮数已用完，尚未安排",call_budget:"剩余调用额度不足，尚未安排",time_budget:"剩余调查时间不足，尚未安排",scope_changed:"研究范围已调整，尚未安排",PROJECT_CHANGED_REFRESH:"项目同时发生变化，建议尚未安排",PROJECT_ROUND_LIMIT:"项目轮数已用完，尚未安排"};
  return {state:outcome?.state||"unrecorded",label:reasons[outcome?.reason]||(outcome?.reason?"安排未完成，原回答和建议保留":"尚无安排记录，请结合项目进度核对")};
}

function renderInvestigationProposals(result,project=null,step=null,allowDraft=false) {
  if(!result.investigation_proposals?.length)return "";
  return `<section class="detail-section"><h3>Agent提出的后续调查</h3><p class="form-note">建议说明待解决问题，不是已经取得的证据。安排与执行仍受当前资料范围和项目额度限制。</p>${result.investigation_proposals.map((proposal,index)=>{
    const status=proposalPlanningStatus(project,step,index);
    const draft=allowDraft?`<button class="text-button" data-conversation-followup="${e(investigationDraft(proposal))}" data-followup-kind="${e(proposal.kind)}" data-reply-step="${e(step?.id)}">准备这条追问（不开始调查） ↗</button>`:`<a class="text-button" href="#research/${e(project?.id)}">在研究对话准备追问 ↗</a>`;
    return `<section class="research-context"><h4>${e(proposal.question)}</h4><p><strong>完成条件：</strong>${e(proposal.completion)}</p><p><strong>所需证据：</strong>${e(proposal.evidence_needed)}</p><p class="form-note">${result.status==="completed"?e(status.label):"原调查尚未完成，建议仅供后续核实。"}</p>${status.step?.run_id?`<button class="text-button" data-open-run="${e(status.step.run_id)}">查看后续调查及原文 ↗</button>`:step&&project&&result.status==="completed"&&!status.step?draft:""}</section>`;
  }).join("")}</section>`;
}

function conversationAllocation(project, offline, allowPublic=false) {
  const budget=project.budget||{},usage=project.usage||{};
  const pending=(project.steps||[]).filter(step=>step.state==="queued"&&!step.run_id&&!step.offline);
  const calls=(budget.max_calls??10)-(usage.reserved_calls||0)-pending.reduce((n,s)=>n+s.max_calls,0);
  const seconds=(budget.max_seconds??720)-(usage.reserved_seconds||0)-pending.reduce((n,s)=>n+s.timeout,0);
  const publicLeft=(budget.max_public??4)-(usage.public||0)-pending.filter(s=>s.allow_public).length*4;
  const issue=!project.career&&(project.steps||[]).length>=(budget.max_rounds??6) ? "本研究已达轮数上限，记录已保留。可从左侧开始新研究。"
    : offline&&(project.steps||[]).some(step=>project.ready_step_ids?.includes(step.id)&&!step.offline) ? "当前有待执行的模型调查，请先处理已有进度，再仅整理原文。"
    : !offline&&calls<2 ? "剩余调用额度已分配，记录已保留。可只整理原文，或开始新研究。"
    : !offline&&seconds<1 ? "本研究可分配的调查时间已用完。可只整理原文，或开始新研究。"
    : !offline&&allowPublic&&publicLeft<4 ? "公开补查额度不足。可先归档网页，再关闭公开补查继续调查。" : "";
  return {maxCalls:Math.max(1,Math.min(10,calls)),timeout:offline?180:Math.max(1,Math.min(180,seconds)),allowPublic:allowPublic&&!offline,issue};
}

function updateConversationAllocation(project) {
  const offline=$("#conversation-offline").checked;
  const allocation=conversationAllocation(project,offline,$("#conversation-allow-public").checked);
  $("#conversation-submit").disabled=project.worker_running||Boolean(allocation.issue);
  $("#conversation-limit").textContent=allocation.issue||(offline?"本轮只整理原文，不调用模型。":`本轮最多使用 ${allocation.maxCalls} 次调用、${allocation.timeout} 秒。`)+"沿用本研究的资料范围；旧判断仍需核对，不会自动当成事实。";
}

const conversationSendKeys=new Map(),conversationSending=new Set();

function clearConversationReceipt(projectId) {
  conversationSendKeys.delete(projectId);sessionStorage.removeItem("wo-pending-question:"+projectId);
  let receipt=null;try{receipt=JSON.parse(sessionStorage.getItem("wo-pending-research")||"null");}catch{}
  if(receipt?.projectId===projectId)sessionStorage.removeItem("wo-pending-research");
}

async function askResearchConversation(question, options={}) {
  const id=conversation.id;
  if(conversationSending.has(id))throw new Error("这条问题正在发送，请稍候。");
  conversationSending.add(id);
  try{return await sendResearchConversation(question,options);}
  finally{conversationSending.delete(id);}
}

async function sendResearchConversation(question, options={}) {
  const project = await api("projects/"+encodeURIComponent(conversation.id));
  const offline=options.offline ?? $("#offline").checked;
  const allowPublic=(options.allowPublic??$("#allow-public").checked)&&!offline;
  const approach=options.approach||$("#conversation-approach")?.value||project.steps?.at(-1)?.approach||"standard";
  const receiptKey="wo-pending-question:"+project.id;
  const pending=conversationSendKeys.get(project.id)||sessionStorage.getItem(receiptKey);
  const saved=project.steps?.find(step=>step.key===pending);
  const kind=options.kind||$("#conversation-kind")?.value||saved?.kind||"investigate";
  if(saved){
    if(saved.question!==question.trim()||saved.offline!==offline||Boolean(saved.allow_public)!==allowPublic||(saved.approach||"standard")!==approach||(saved.kind||"investigate")!==kind)throw new Error("上一条问题已保存，请先查看或继续原调查，再发送其他问题。");
    if(saved.scope_version!=null&&project.scope_version!=null&&saved.scope_version!==project.scope_version)throw new Error("原问题已保存，但资料范围已变化，请先在项目记录中处理原步骤。");
    if(!project.worker_running&&["queued","interrupted"].includes(saved.state))await api("projects/"+project.id+"/run",{method:"POST",body:"{}"});
    conversation.replyToStepId=undefined;
    await openResearchConversation(project.id);
    clearConversationReceipt(project.id);
    return;
  }
  if(project.worker_running)throw new Error("正在调查，请等本轮结束后继续追问。");
  const allocation=conversationAllocation(project,offline,allowPublic);
  if(allocation.issue)throw new Error(allocation.issue);
  const supportsQuestionScope=(state.serviceContract?.components?.schemas?.StepInput?.properties?.coverage_mode?.enum || []).includes("question");
  const supportsReplies=Boolean(state.serviceContract?.components?.schemas?.StepInput?.properties?.reply_to_step_id);
  const replyTo=conversation.replyToStepId===undefined ? defaultConversationReply(project) : conversation.replyToStepId;
  const key=pending||crypto.randomUUID();
  conversationSendKeys.set(project.id,key);sessionStorage.setItem(receiptKey,key);
  const accepted=await api("projects/"+project.id+"/steps",{method:"POST",body:JSON.stringify({revision:project.revision,question,kind,...(supportsReplies ? {reply_to_step_id:replyTo}:{}),...(supportsQuestionScope ? {coverage_mode:project.steps?.at(-1)?.coverage_mode||(project.job_ids?.length===0?"question":state.researchIds?.length?"all":"question")}:{}),...(approach!=="standard"?{approach}:{}),completion:approach==="work_map"?"形成有引用、边界和未知的工作地图与业务/任务/交付物/责任/能力/工具关系；相关旧认识用修订记录说明。":"回答本次问题，查阅适用范围原文，说明解释、未知及后续核实方向。",offline,allow_public:allocation.allowPublic,max_calls:allocation.maxCalls,timeout:allocation.timeout,key})});
  const acceptedStep=accepted.steps?.find(step=>step.key===key);
  if(acceptedStep&&(acceptedStep.question!==question.trim()||acceptedStep.offline!==offline||Boolean(acceptedStep.allow_public)!==allocation.allowPublic||(acceptedStep.approach||"standard")!==approach||(acceptedStep.kind||"investigate")!==kind))throw new Error("原问题已经保存且设置不同，请先查看原调查，未自动开始新调用。");
  await api("projects/"+project.id+"/run",{method:"POST",body:"{}"});
  conversation.replyToStepId=undefined;
  await openResearchConversation(project.id);
  clearConversationReceipt(project.id);
}

function renderSubmissionFeedback(result,evidence) {
  const feedback=result.submission_feedback;
  if(result.status==="completed"||!feedback)return "";
  return `<section class="research-context"><h3>最近一次提交为何未通过</h3><p>${e(feedback.notice)}</p><ul>${feedback.reasons.map(row=>`<li>${e(row.message)}${row.claim_indices?.length?` 对应下方第 ${row.claim_indices.map(index=>index+1).join("、")} 条。`:""}</li>`).join("")}</ul><details><summary>查看未通过的提交 · ${feedback.draft_claims.length} 条（不作为当前认识）</summary>${feedback.draft_claims.map(row=>`<section class="claim"><strong>第 ${row.index+1} 条 · 未通过</strong><p>${e(row.text)}</p><p class="form-note">${e(categoryLabels[row.category]||"维度待核")} · ${e(claimBasisLabels[row.basis]||"性质待核")} · ${e(requirementLabels[row.requirement]||"要求性质待核")}</p>${row.evidence_ids.map(id=>evidence.has(id)?`<button class="cite" data-cite="${e(id)}">核对 ${e(evidence.get(id).label||"原文")} ↗</button>`:'<small class="form-note">引用无法定位</small>').join(" ")}</section>`).join("")}</details></section>`;
}

function renderUpstreamRevisionNotices(result) {
  const notices=result.upstream_revision_notices;
  if(!notices?.items?.length)return "";
  const decisions={retain:"重新保留",revise:"修订",withdraw:"撤回",unresolved:"仍有疑问"};
  return `<section class="research-context"><h3>沿用的旧研究后来出现不同判断</h3><p>${e(notices.notice)}</p>${notices.items.map(row=>`<section><p>${e(decisions[row.decision]||"后续意见")}：${e(row.reason)} <button class="text-button" data-open-run="${e(row.previous_run_id)}">查看原判断所在研究 ↗</button> <button class="text-button" data-open-run="${e(row.run_id)}">查看后续修正及原文 ↗</button></p>${renderRevisionAspects(row)}</section>`).join("")}${notices.omitted?`<p class="form-note">另有 ${e(notices.omitted)} 条相关意见，请在逐轮记录中核对。</p>`:""}</section>`;
}

function revisionComparisonNotice(row) {
  return row.comparison_notice || "这条历史记录未提供逐项对照，不能仅凭简写确认整条旧判断已保留。";
}

function renderRevisionAspects(row,evidence) {
  const labels={retain:"保留",revise:"修订",withdraw:"撤回",unresolved:"仍待核实"};
  return `<p class="form-note">${e(revisionComparisonNotice(row))}</p>${(row.aspects||[]).map(part=>`<section class="research-context"><strong>${e(labels[part.decision]||"待核对")}的具体内容</strong><p>旧内容：${e(part.previous_excerpt)}</p>${(part.new_statements||[]).map(text=>`<p>对应本轮判断：${e(text)}</p>`).join("")}<p>${e(part.reason)}</p>${(part.evidence_ids||[]).filter(id=>evidence?.has(id)).map(id=>`<button class="cite" data-cite="${e(id)}">核对 ${e(evidence.get(id).label||"原文")} ↗</button>`).join(" ")}</section>`).join("")}`;
}

function revisionAspectLines(row,line,refs=()=>"") {
  const labels={retain:"保留",revise:"修订",withdraw:"撤回",unresolved:"仍待核实"};
  return [line(revisionComparisonNotice(row)),...(row.aspects||[]).flatMap(part=>{
    const citations=refs(part.evidence_ids);
    return [
    "- "+labels[part.decision]+"的旧内容："+line(part.previous_excerpt),
    ...(part.new_statements||[]).map(text=>"  对应本轮判断："+line(text)),
    "  理由："+line(part.reason),...(citations?["  原文依据："+citations]:[])
  ];})];
}

function projectUnderstanding(project) {
  const included=[],excluded=[];
  for(const [position,step] of (project.steps||[]).entries()) {
    const result=step.result,audit=result?.audit;
    if(!result)continue;
    const reason=result.status!=="completed" ? "本轮未形成完整回答"
      : step.run_state==="invalidated" ? "相关记录已忘记"
      : result.business_review?.status==="rejected" ? "质量核对未通过"
      : step.scope_version!==project.scope_version ? "研究范围已调整"
      : !audit ? "尚未取得有效性信息"
      : audit.stale_memory||audit.stale_knowledge||audit.stale_dependencies||audit.changed_sources?.length||audit.affected_strategy?.length ? "所用资料或背景需要重新核对" : "";
    if(reason){excluded.push({step,reason,round:position+1});continue;}
    included.push({step,result,round:position+1});
  }
  const replaced=new Set(),unresolved=new Set(),changes=[],latestDecisions=new Map();
  for(const row of included)for(const revision of row.result.cognition_revisions||[]) {
    const key=revision.previous_run_id+":"+revision.previous_claim_index;
    const change={...row,revision};
    latestDecisions.set(key,change);
    changes.push(change);
  }
  for(const [key,{revision}] of latestDecisions) {
    if(["revise","withdraw"].includes(revision.decision))replaced.add(key);
    if(revision.decision==="unresolved")unresolved.add(key);
  }
  const claims=[];
  for(const row of included.slice().reverse())for(const [index,claim] of (row.result.claims||[]).entries()) {
    const key=row.step.run_id+":"+index;
    const evidence=(claim.evidence_ids||[]).map(id=>(row.result.evidence||[]).find(ev=>ev.id===id));
    if(replaced.has(key)||!evidence.length||evidence.some(ev=>!ev))continue;
    claims.push({...row,index,claim,evidence,unresolved:unresolved.has(key)});
  }
  const questions=[];
  for(const row of included.slice().reverse())for(const [index,proposal] of (row.result.investigation_proposals||[]).entries()) {
    if(proposalPlanningStatus(project,row.step,index).step)continue;
    if(!questions.some(q=>q.text===proposal.question))questions.push({...row,text:proposal.question,prompt:investigationDraft(proposal),kind:proposal.kind});
  }
  for(const row of latestDecisions.values())for(const part of row.revision.aspects||[]) {
    if(part.decision!=="unresolved")continue;
    const text="核实旧判断中的「"+part.previous_excerpt+"」："+part.reason;
    if(!questions.some(q=>q.text===text))questions.push({...row,text});
  }
  for(const row of included.slice(-1))for(const text of row.result.review?.next_questions||row.result.gaps||[]) {
    if(/[？?]|核实|补查/.test(text)&&!questions.some(q=>q.text===text))questions.push({...row,text});
  }
  const maps=included.slice().reverse().filter(row=>row.result.work_map).map(row=>{
    const map=row.result.work_map;
    const sections=["work_types","work_relations","ability_relations","comparisons"].map(key=>({key,items:(map[key]||[]).map((item,index)=>{
      const related=changes.filter(change=>change.revision.previous_run_id===row.step.run_id&&(item.claim_indices||[]).includes(change.revision.previous_claim_index));
      return {item,index,changes:related,currentChanges:related.filter(change=>latestDecisions.get(change.revision.previous_run_id+":"+change.revision.previous_claim_index)===change)};
    })}));
    return {...row,sections};
  });
  const scopeHistory=excluded.filter(row=>row.reason==="研究范围已调整"&&row.step.result.audit&&
    !["stale_memory","stale_knowledge","stale_dependencies","changed_sources","affected_strategy"].some(key=>{
      const value=row.step.result.audit[key];return Array.isArray(value)?value.length:Boolean(value);
    })).map(row=>({...row,result:row.step.result,claims:row.step.result.claims.map((claim,index)=>({claim,index,
      evidence:(claim.evidence_ids||[]).map(id=>(row.step.result.evidence||[]).find(ev=>ev.id===id)),
      changes:changes.filter(change=>change.revision.previous_run_id===row.step.run_id&&change.revision.previous_claim_index===index)
    })).filter(item=>item.evidence.length&&item.evidence.every(Boolean))})).filter(row=>row.claims.length);
  return {claims,changes:changes.reverse(),questions,excluded,maps,rounds:included,scopeHistory};
}

function renderScopeHistory(view) {
  if(!view.scopeHistory.length)return "";
  return `<details class="detail-section"><summary>范围调整前的认识 · ${view.scopeHistory.length} 轮（只供原范围对照）</summary><p class="form-note">以下保留原问题和原范围的判断，不能直接外推到当前范围或目标。需要使用时可沿原判断重新核实，不会自动成为当前认识或已采纳知识。</p>${view.scopeHistory.map(row=>`<section class="research-context"><h3>第 ${row.round} 轮 · 原范围 ${e(row.step.scope_version)}</h3><p>${e(row.step.question)}</p><p class="form-note">原岗位范围：${(row.result.scope?.jobs||[]).map(job=>e(job.title||job.id)).join("、")||"未记录岗位范围"}</p>${row.claims.map(({claim,index,changes})=>`<p><strong>原判断 ${index+1}：</strong>${e(claim.text)}</p>${changes.map(change=>`<p class="form-note">${e(({retain:"保留",revise:"修订",withdraw:"撤回",unresolved:"仍待核实"})[change.revision.decision])}（后续意见，待核对）：${e(change.revision.reason)} <button class="text-button" data-open-run="${e(change.step.run_id)}">查看后续处理 ↗</button></p>`).join("")}<button class="text-button" data-conversation-claim="${e(claim.text)}" data-reply-step="${e(row.step.id)}">沿这条旧认识重新核实 ↗</button>`).join("")}<p><button class="text-button" data-open-run="${e(row.step.run_id)}">打开这一轮原回答、地图与引用 ↗</button></p></section>`).join("")}</details>`;
}

function focusConversationRun(runId) {
  const root=$("#conversation-turns");if(!root)return false;
  const item=$$("[data-conversation-run]",root).find(row=>row.dataset.conversationRun===runId);
  if(!item)return false;
  item.open=true;item.scrollIntoView({block:"start",behavior:"smooth"});return true;
}

function projectDossierMarkdown(project,exportedAt=new Date().toISOString()) {
  if(project.state!=="active")throw new Error("这项研究已不可用，不能导出原内容。");
  if(project.worker_running)throw new Error("调查还在进行，请等本轮结束后导出。");
  const view=projectUnderstanding(project),sources=new Map();
  const text=value=>e(value).replace(/[\\`*_{}\[\]()#+!|]/g,char=>String.fromCharCode(92)+char);
  const line=value=>text(value).replace(/\r?\n/g,"\n\n");
  const origin=step=>projectStepOriginLabel(step);
  const labels={retain:"保留",revise:"修订",withdraw:"撤回",unresolved:"仍待核实"};
  const refs=(row,ids)=>[...new Set(ids||[])].map(id=>{
    const ev=row.result.evidence.find(item=>item.id===id);if(!ev)return "引用缺失，请回看原轮次";
    const key=row.step.run_id+":"+id;
    if(!sources.has(key))sources.set(key,{label:"E"+(sources.size+1),ev,row});
    return "["+sources.get(key).label+"]";
  }).join(" ");
  const claimRefs=(row,indices)=>refs(row,[...new Set((indices||[]).flatMap(index=>row.result.claims[index]?.evidence_ids||[]))]);
  const status=row=>row.unresolved?"后续仍有疑问":row.result.business_review?.status==="approved"&&row.result.business_review?.reviewer_kind==="human"?"人工核对通过":"待核对";
  const lines=["# "+line(project.title||"研究成果"),"",line(project.goal),"",
    "导出时间："+text(exportedAt),"",
    "按导出时仍有效的研究记录整理；判断和地图中的推断仍须核对。知识采纳以工作台记录为准。认识变化不等于外部工作变化。",
    "此文件包含本研究目标和所引用的原文；下载副本独立保留，不会随工作台遗忘自动删除。","",
    "## 研究范围与过程","",
    "当前范围："+(project.job_ids||[]).length+" 个岗位；归档资料："+(project.public_document_ids==null?"采用各轮实际冻结范围":project.public_document_ids.length+" 份明确所选资料")+"。",
    "已保存 "+project.steps.length+" 轮；已用模型调用 "+(project.usage?.calls??"未记录")+" 次。重复读取同一来源不构成独立证据。",
    "项目定位："+text(project.id),"",
    "## 当前认识",""];
  const workspace=safeURL(location.origin||"");
  if(workspace)lines.splice(lines.indexOf("## 当前认识"),0,"[返回原工作台研究]("+new URL("/#research/"+encodeURIComponent(project.id),workspace).href+")","");
  if(!view.claims.length)lines.push("暂无可纳入当前认识的判断；未完成或失效的轮次在下方说明。","");
  let claimRound=null;
  for(const row of view.claims){
    if(claimRound!==row.round){
      lines.push("### 第 "+row.round+" 轮","","原问题："+line(row.step.question),"提问来源："+text(origin(row.step)),"");
      claimRound=row.round;
    }
    lines.push("#### 判断 "+(row.index+1),"",
      "判断维度："+text(categoryLabels[row.claim.category]||row.claim.category)+"；状态："+status(row)+"；"+text(claimBasisLabel(row.claim))+"；"+text(requirementLabels[row.claim.requirement]||"性质待核"),"",
      line(row.claim.text),"","原文依据："+refs(row,row.claim.evidence_ids),"");
  }
  if(view.maps.length)lines.push("## 工作地图与关系解释","","逐轮保留原结构；受到后续修正影响的部分标明原因，不自动合并为新的事实。","");
  for(const row of view.maps){
    const map=row.result.work_map;
    lines.push("### 第 "+row.round+" 轮地图 · "+line(row.step.question),"",line(map.scope_note),"");
    for(const section of row.sections)for(const {item,index,changes,currentChanges} of section.items){
      const name=section.key==="work_types"?item.name:section.key==="ability_relations"?item.task+" → "+item.ability:section.key==="comparisons"?"关系比较 "+(index+1):item.source_text+" → "+(workPredicateLabels[item.predicate]||item.predicate)+" → "+item.target_text;
      const affected=currentChanges.some(change=>["revise","withdraw"].includes(change.revision.decision));
      lines.push("#### "+line(name),"",affected?"状态：受后续修订或撤回影响，保留供对照。":currentChanges.some(change=>change.revision.decision==="unresolved")?"状态：后续仍有疑问。":"状态：原研究解释，待核对。",
        "解释性质："+text(claimBasisLabels[item.basis]||"性质未标注"));
      const fields=section.key==="work_types"?[["要解决的问题",item.problem],["任务",item.tasks],["交付物",item.deliverables],["边界与反例",item.boundary],["下一步验证",item.next_check]]
        :section.key==="comparisons"?[["共用点",item.common_ground],["差异",item.differences],["迁移条件",item.transfer_conditions],["仍待核实",(item.unknowns||[]).join("；")]]
        :[["解释",item.rationale],["适用与迁移边界",item.transfer_limit]];
      for(const [label,value] of fields)lines.push(label+"："+line(value));
      if(section.key==="work_relations")lines.push("关系维度："+text(workDimensionLabels[item.source_kind]||"维度未标注")+" → "+text(workDimensionLabels[item.target_kind]||"维度未标注"));
      if(section.key==="comparisons")for(const i of item.relation_indices||[]){const relation=map.work_relations[i];if(relation)lines.push("比较对象："+line(relation.source_text+" → "+relation.target_text));}
      for(const i of item.claim_indices||[]){const claim=row.result.claims[i];if(claim)lines.push("支撑判断 "+(i+1)+"（"+text(requirementLabels[claim.requirement]||"性质待核")+"）："+line(claim.text));}
      lines.push("原文依据："+claimRefs(row,item.claim_indices));
      for(const change of changes)lines.push("后续第 "+change.round+" 轮"+labels[change.revision.decision]+"："+line(change.revision.reason));
      lines.push("");
    }
    for(const unknown of map.unknowns||[])lines.push("尚不明确："+line(unknown));
    lines.push("");
  }
  if(view.scopeHistory.length)lines.push("## 范围调整前的认识（仅供原范围对照）","",
    "原问题与范围已经调整；以下不是当前范围的结论，不自动采纳为知识。需使用时沿原判断重新核实。","");
  for(const row of view.scopeHistory){
    lines.push("### 第 "+row.round+" 轮 · 原范围 "+row.step.scope_version,"",line(row.step.question),"");
    for(const {claim,index,changes} of row.claims){
      lines.push("原判断 "+(index+1)+"："+line(claim.text),"原文依据："+refs(row,claim.evidence_ids));
      for(const change of changes)lines.push("后续第 "+change.round+" 轮意见（待核对）："+labels[change.revision.decision]+"；"+line(change.revision.reason));
      lines.push("");
    }
  }
  if(view.rounds.some(row=>row.result.gaps?.length))lines.push("## 各轮保留的资料缺口","","以下是原轮次记录；后续可能已进一步核实，请结合修正记录理解。","");
  for(const row of view.rounds)for(const gap of row.result.gaps||[])lines.push("- 第 "+row.round+" 轮："+line(gap));
  lines.push("");
  const plans=view.rounds.filter(row=>row.result.application_plan?.actions?.length);
  if(plans.length)lines.push("","## 个人应用建议（原研究建议，不表示已执行）","");
  for(const row of plans){const plan=row.result.application_plan;
    lines.push("### 第 "+row.round+" 轮建议","", "明确目标："+line(plan.goal),"投入与限制："+line(plan.constraints||"未说明"),line(plan.notice),"");
    for(const [index,action] of plan.actions.entries()){
      lines.push("#### 动作 "+(index+1)+" · "+line(action.title),"针对任务或能力："+line(action.task_or_ability),"交付物："+line(action.deliverable),"完成检查："+line(action.completion_check));
      for(const assumption of action.assumptions||[])lines.push("待确认前提："+line(assumption));
      lines.push("原文依据："+refs(row,action.evidence_ids),"");
    }
    for(const question of plan.open_questions||[])lines.push("行动前还需明确："+line(question));
    lines.push("");
  }
  if(view.changes.length)lines.push("## 认识为何保留或改变","");
  for(const row of view.changes){const revision=row.revision;
    lines.push("### 第 "+row.round+" 轮 · "+labels[revision.decision],"",
      "旧判断："+line(revision.previous_statement),...revision.new_statements.map(value=>"本轮判断："+line(value)),
      "理由："+line(revision.reason),...revisionAspectLines(revision,line,ids=>refs(row,ids)),revision.evidence_relation==="reread"?"材料关系：重读原材料。":"材料关系：包含旧轮未读的引用，不表示来源新发布。",
      ...(renderRevisionScope(revision)?["研究范围或目标已经调整；本次是新范围下的重新核对，不表示外部工作变化。"]:[]),
      "原研究定位："+text(revision.previous_run_id),"本轮依据："+refs(row,revision.evidence_ids),"");
  }
  const affectedRounds=view.rounds.filter(row=>row.result.upstream_revision_notices?.items?.length);
  if(affectedRounds.length)lines.push("## 沿用旧认识的下游研究", "");
  for(const row of affectedRounds){const notices=row.result.upstream_revision_notices;
    lines.push("### 第 "+row.round+" 轮 · "+line(row.step.question),"",line(notices.notice));
    for(const notice of notices.items)lines.push("- 后续"+labels[notice.decision]+"："+line(notice.reason)+"；原研究："+text(notice.previous_run_id)+"；修正研究："+text(notice.run_id),...revisionAspectLines(notice,line));
    if(notices.omitted)lines.push("另有 "+notices.omitted+" 条相关意见，须在原工作台逐轮核对。");
    lines.push("");
  }
  if(view.questions.length)lines.push("## 下一步需要核实","");
  for(const row of view.questions)lines.push("- "+line(row.text)+"（来自第 "+row.round+" 轮）");
  const proposed=view.rounds.filter(row=>row.result.investigation_proposals?.length);
  if(proposed.length)lines.push("","## Agent提出的后续调查","","建议与安排状态不表示已经获得证据或完成语义核对。","");
  for(const row of proposed)for(const [index,proposal] of row.result.investigation_proposals.entries()) {
    lines.push("### 第 "+row.round+" 轮建议 · "+line(proposal.question),
      "完成条件："+line(proposal.completion),"所需证据："+line(proposal.evidence_needed),
      "安排状态："+line(proposalPlanningStatus(project,row.step,index).label),"");
  }
  const pending=project.steps.filter(step=>!step.result),excluded=view.excluded.filter(row=>row.step.result?.status!=="evidence_only");
  if(excluded.length||pending.length)lines.push("","## 未纳入当前认识的历史轮次","");
  for(const {step,reason} of excluded){
    lines.push("- "+line(step.question)+"："+text(reason));
    const feedback=step.result?.submission_feedback;
    if(feedback){
      lines.push("  最近提交的程序检查提示（可能有误，不作为语义结论）：");
      for(const issue of feedback.reasons)lines.push("  - "+line(issue.message)+(issue.claim_indices?.length?"（条目 "+issue.claim_indices.map(index=>index+1).join("、")+"）":""));
      lines.push("  未通过的提交未纳入当前认识；详细文本与引用在原轮次中保留。");
    }
  }
  for(const step of pending)lines.push("- "+line(step.question)+"：尚未形成可整理的回答");
  const evidenceRounds=project.steps.map((step,index)=>({step,result:step.result,round:index+1})).filter(row=>row.result&&row.result.status!=="completed"&&row.step.run_state!=="invalidated"&&row.result.evidence?.length);
  if(evidenceRounds.length)lines.push("","## 已整理的原文与未完成调查","","这些轮次尚未形成可采用的研究判断；原文保留供继续分析。","");
  for(const row of evidenceRounds){
    const unusable=new Set((row.result.audit?.changed_sources||[]).filter(item=>item.retained_evidence_valid===false).map(item=>item.evidence_id));
    const ids=row.result.evidence.filter(ev=>!unusable.has(ev.id)).map(ev=>ev.id);
    lines.push("### 第 "+row.round+" 轮 · "+line(row.step.question),"",
      row.result.status==="evidence_only"?"本轮仅整理原文，未形成模型研究结论。":"本轮调查未完成，已有资料可继续核对。",
      row.step.scope_version===project.scope_version?"资料范围：当前研究范围。":"资料范围：调整前的范围，不能直接作为当前判断。",
      "原文依据："+refs(row,ids),"");
    for(const gap of row.result.gaps||[])lines.push("- "+line(gap));
    lines.push("");
  }
  lines.push("","## 原文依据","");
  for(const {label,ev,row} of sources.values()){
    lines.push("### "+label+" · "+line(ev.title||"原文资料"),"",
      "来自第 "+row.round+" 轮；来源："+text(sourceLabel(ev))+"；"+line(ev.company||ev.publisher||""),
      "取得时间："+text(ev.observed_at||"未知")+"；来源发布时间："+text(ev.source_published_at||"未知"),
      "原字符范围："+ev.start+"–"+ev.end+(ev.full_text_length!=null?" / 正文 "+ev.full_text_length+" 字符":""));
    if(ev.historical_cutoffs?.length)lines.push("历史读取截止："+ev.historical_cutoffs.map(text).join("；")+"。截止不是网站发布时间。");
    if(ev.publisher&&ev.publisher!==ev.company)lines.push("资料出处与导入说明："+line(ev.publisher));
    if(ev.source_note)lines.push("来源说明："+line(ev.source_note));
    lines.push("内容版本："+text(ev.snapshot_id||ev.public_document_id||"未归档搜索材料"),
      "原文文档定位："+text(ev.document_id||ev.public_document_id||"未知"),"",
      ...String(ev.quote||"").split(/\r?\n/).map(value=>"> "+text(value)),"");
    const url=safeURL(ev.url);if(url)lines.push("公开出处："+text(url),"");
  }
  return lines.join("\n")+"\n";
}
function dossierReadableText(value) {
  return String(value).replace(/\\([\\`*_{}\[\]()#+!|])/g,"$1").replace(/&(amp|lt|gt|quot|#39);/g,(_,name)=>({amp:"&",lt:"<",gt:">",quot:'"',"#39":"'"})[name]);
}

function projectDossierHTML(project,exportedAt=new Date().toISOString()) {
  const markdown=projectDossierMarkdown(project,exportedAt),blocks=[],toc=[];
  let paragraph=[],quotes=[],list=[],section=0;
  const inline=value=>String(value).split(/(?<!\\)\[(E\d+)\]/g).map((part,index)=>index%2?`<a class="citation" href="#source-${part}">[${part}]</a>`:e(dossierReadableText(part))).join("");
  const flush=()=>{
    if(paragraph.length){blocks.push('<p>'+paragraph.map(inline).join('<br>')+'</p>');paragraph=[];}
    if(quotes.length){blocks.push('<blockquote>'+quotes.map(inline).join('<br>')+'</blockquote>');quotes=[];}
    if(list.length){blocks.push('<ul>'+list.map(value=>'<li>'+inline(value)+'</li>').join('')+'</ul>');list=[];}
  };
  for(const line of markdown.split(/\r?\n/)){
    const heading=/^(#{1,4}) (.*)$/.exec(line);
    if(heading){flush();const level=heading[1].length,label=dossierReadableText(heading[2]),source=/^(E\d+) ·/.exec(label),id=source?'source-'+source[1]:'section-'+(++section);
      blocks.push(`<h${level} id="${id}">${e(label)}</h${level}>`);if(level===2)toc.push({id,label});
    }else if(line.startsWith('[返回原工作台研究](')){
      flush();const url=safeURL(line.slice('[返回原工作台研究]('.length,-1));
      if(url)blocks.push('<p><a href="'+e(url)+'">返回原工作台研究 ↗</a></p>');
    }else if(line.startsWith('> ')){if(paragraph.length||list.length)flush();quotes.push(line.slice(2));}
    else if(line.startsWith('- ')){if(paragraph.length||quotes.length)flush();list.push(line.slice(2));}
    else if(!line.trim())flush();
    else {if(quotes.length||list.length)flush();paragraph.push(line);}
  }
  flush();
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${e(project.title)} · 研究成果</title><style>
  :root{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#25372e;background:#f3f6f2;line-height:1.8}*{box-sizing:border-box}body{margin:0}main{max-width:1000px;margin:36px auto;padding:44px 52px;background:white;border:1px solid #e1e8df;border-radius:18px}header{display:flex;align-items:center;justify-content:space-between;gap:16px;border-bottom:1px solid #e1e8df;padding-bottom:18px;color:#41644b}header strong{letter-spacing:2px;font-size:12px}button{font:inherit;background:#315c46;color:white;border:0;padding:9px 16px;border-radius:8px;cursor:pointer}nav{background:#f3f7f1;padding:16px 20px;border-radius:10px;margin:24px 0}nav a{display:inline-block;margin-right:18px;color:#315c46;font-size:13px}h1{font-size:30px;line-height:1.4;margin:28px 0 18px}h2{font-size:21px;border-top:1px solid #e1e8df;padding-top:24px;margin-top:34px}h3{font-size:16px;margin-top:25px}p,li,blockquote{overflow-wrap:anywhere}blockquote{margin:14px 0;padding:15px 20px;background:#f6f8f4;border-left:3px solid #8fa788;font-size:14px}li{margin:7px 0}.citation{font-size:12px;color:#315c46;background:#edf3e9;border-radius:4px;padding:2px 5px;text-decoration:none}footer{border-top:1px solid #e1e8df;margin-top:30px;padding-top:16px;font-size:12px;color:#6f7e73}@media(max-width:650px){main{margin:0;padding:25px 20px;border-radius:0}h1{font-size:24px}header{align-items:flex-start;flex-direction:column}}@media print{:root{background:white}main{margin:0;border:0;padding:0;max-width:none}header button,nav{display:none}h2,h3{break-after:avoid}blockquote{break-inside:avoid}a{color:inherit}}
  </style></head><body><main><header><strong>WORK OBSERVER / 研究成果</strong><button type="button" onclick="window.print()">打印 / 保存为 PDF</button></header><nav aria-label="报告目录">${toc.map(item=>`<a href="#${item.id}">${e(item.label)}</a>`).join('')}</nav><article>${blocks.join('\n')}</article><footer>此文件由研究记录整理。判断、推断与来源仍需结合原文核对。</footer></main></body></html>`;
}

function projectSummaryText(project) {
  if(project.state!=="active")throw new Error("这项研究已不可用。");
  const view=projectUnderstanding(project),lines=[project.title,"研究目标："+project.goal,""];
  if(view.claims.length){
    lines.push("当前认识（最多摘录6条）：");
    for(const [index,row] of view.claims.slice(0,6).entries())lines.push((index+1)+". "+row.claim.text+"\n   性质："+claimBasisLabel(row.claim)+(row.claim.requirement&&row.claim.requirement!=="unspecified"?"；要求："+requirementLabels[row.claim.requirement]:"")+"；依据："+[...new Set(row.evidence.map(ev=>ev.title||"原文资料"))].join("、"));
  }else lines.push("当前尚未形成可整理的研究判断，已有原文和调查记录可继续查阅。");
  if(view.questions.length)lines.push("","仍需核实：",...view.questions.slice(0,5).map(row=>"- "+row.text));
  lines.push("","摘要是当前成果的摘录，完整原文、范围与修正记录见研究报告。");
  return lines.join("\n");
}

async function copyProjectSummary(id,button) {
  button.disabled=true;
  try{const project=await api("projects/"+encodeURIComponent(id));await navigator.clipboard.writeText(projectSummaryText(project));notify("研究摘要已复制。");}
  catch(error){notify(error.message||"复制未完成，可使用导出报告。",true);}
  finally{button.disabled=false;}
}

async function downloadProjectDossier(id,button,format="md") {
  button.disabled=true;
  try {
    const project=await api("projects/"+encodeURIComponent(id));
    if(!button.isConnected)return;
    const content=format==="html"?projectDossierHTML(project):projectDossierMarkdown(project);
    const url=URL.createObjectURL(new Blob([content],{type:(format==="html"?"text/html":"text/markdown")+";charset=utf-8"}));
    const link=document.createElement("a");link.href=url;link.download="研究成果-"+String(project.title||"研究").replace(/[<>:"/\\|?*\u0000-\u001f]/g,"_").slice(0,70)+"."+(format==="html"?"html":"md");
    document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  } catch(error){notify(error.message,true);}
  finally{button.disabled=false;}
}
document.addEventListener("click",event=>{
  const button=event.target.closest("[data-project-dossier]");if(button)downloadProjectDossier(button.dataset.projectDossier,button,button.dataset.exportFormat||"md");
  const copy=event.target.closest("[data-project-summary]");if(copy)copyProjectSummary(copy.dataset.projectSummary,copy);
});

function historicalEvidenceNote(ev) {
  return ev.historical_cutoffs?.length ? `<p class="form-note">历史原文读取截止：${ev.historical_cutoffs.map(value=>e(when(value))).join("；")}。按当时已入库资料读取，截止不是网站发布时间。</p>` : "";
}
function renderUnderstandingEvidence(result,indices) {
  const refs=[...new Set(indices.flatMap(index=>result.claims[index]?.evidence_ids||[]))];
  return `<details class="research-context"><summary>核对原判断与原文依据</summary>${indices.map(index=>{const claim=result.claims[index];return `<p>原判断 ${index+1} · ${e(claimBasisLabel(claim))} · ${e(requirementLabels[claim.requirement]||"性质待核")}：${e(claim.text)}</p>`;}).join("")}${refs.map(id=>{const ev=result.evidence.find(row=>row.id===id);if(!ev)return '<p>依据无法定位，请回看原研究。</p>';return `<p><strong>${e(ev.title||"原文资料")}</strong> · ${e(sourceLabel(ev))}</p>${historicalEvidenceNote(ev)}<blockquote>${e(ev.quote||"")}</blockquote>${ev.document_id?`<button class="text-button" data-source="${e(ev.document_id)}">核对来源版本 ↗</button>`:""}${ev.public_document_id?`<button class="text-button" data-public-source="${e(ev.public_document_id)}">查看归档全文 ↗</button>`:""}`;}).join("")}</details>`;
}
function renderProjectMaps(view) {
  if(!view.maps.length)return "";
  const decisions={retain:"保留",revise:"修订",withdraw:"撤回",unresolved:"仍待核实"};
  const labels={work_types:"工作类型",work_relations:"工作关系",ability_relations:"任务与能力关系",comparisons:"共用、差异与迁移比较"};
  const sectionNames={work_types:"boundary",work_relations:"relation",ability_relations:"ability",comparisons:"comparison"};
  return `<section class="detail-section"><h3>工作地图与后续修正</h3><p class="form-note">按原研究逐轮展示，不自动合并为新的结论。受后续修订或撤回影响的部分保留供对照；其余解释仍需核对，引用完整不表示已经成立。</p>${view.maps.map((row,position)=>{
    const map=row.result.work_map;
    return `<details class="detail-section" ${position===0?"open":""}><summary>第 ${row.round} 轮地图 · ${e(row.step.question)}</summary><p>${e(map.scope_note)}</p>${row.sections.filter(section=>section.items.length).map(section=>`<h4>${e(labels[section.key])}</h4>${section.items.map(({item,index,changes,currentChanges})=>{
      const affected=currentChanges.some(change=>["revise","withdraw"].includes(change.revision.decision));
      const uncertain=currentChanges.some(change=>change.revision.decision==="unresolved");
      let title,body;
      if(section.key==="work_types"){
        title=item.name;body=`<dl>${detailData("要解决的问题",item.problem)}${detailData("主要任务",item.tasks)}${detailData("交付物",item.deliverables)}${detailData("边界与反例",item.boundary)}${detailData("下一步验证",item.next_check)}</dl>`;
      }else if(section.key==="comparisons"){
        title="关系比较 "+(index+1);body=renderComparisonDetails(item)+`<p class="form-note">比较对象：${item.relation_indices.map(i=>{const r=map.work_relations[i];return e(r.source_text+" → "+r.target_text);}).join("；")}</p>`;
      }else{
        title=section.key==="ability_relations"?item.task+" → "+item.ability:workDimensionLabels[item.source_kind]+"："+item.source_text+" → "+workPredicateLabels[item.predicate]+" → "+workDimensionLabels[item.target_kind]+"："+item.target_text;
        body=`<p>${e(item.rationale)}</p><p><strong>适用与迁移边界：</strong>${e(item.transfer_limit)}</p>`;
      }
      return `<section class="research-context">${badge(affected?"受后续修正影响":uncertain?"后续仍有疑问":"原研究解释，待核对",affected||uncertain?"amber":"muted")} ${badge(({direct:"原文明示",synthesis:"归纳",inference:"待验证解释"})[item.basis||"inference"],"muted")}<h4>${e(title)}</h4>${body}${changes.length?`<div class="inline-note">${changes.map(change=>`<p>第 ${change.round} 轮${e(decisions[change.revision.decision]||"核实")}原判断 ${change.revision.previous_claim_index+1}：${e(change.revision.reason)} <button class="text-button" data-open-run="${e(change.step.run_id)}">查看修正及依据 ↗</button></p>`).join("")}</div>`:""}${renderUnderstandingEvidence(row.result,item.claim_indices)}${mapInvestigationButton(row.result,sectionNames[section.key],index,"针对原图这一部分继续查证")}</section>`;
    }).join("")}`).join("")}${map.unknowns?.length?`<h4>原图留下的未知项</h4><ul>${map.unknowns.map((text,index)=>`<li>${e(text)} ${mapInvestigationButton(row.result,"unknown",index,"继续查证")}</li>`).join("")}</ul>`:""}<button class="text-button" data-open-run="${e(row.step.run_id)}">查看完整原图与知识保留入口 ↗</button></details>`;
  }).join("")}</section>`;
}

function renderClaimKnowledge(runId,claim,index,evidence,records=conversation.knowledge,projectId=null) {
  const saved=records.filter(item=>item.source_run_id===runId&&item.content===claim.text);
  const item=saved.find(row=>row.status==="active"&&row.validity?.eligible===true)
    ||saved.find(row=>row.status==="active")||saved.find(row=>row.status==="candidate")||saved[0];
  if(item) {
    if(item.status==="candidate")return `<button class="text-button" data-knowledge-run="${e(runId)}" data-claim-index="${index}" data-knowledge-project="${e(projectId||"")}" data-knowledge-memory="${e(item.id)}">收藏这条认识 ☆</button>`;
    const label=item.status==="active" ? item.validity?.eligible===true
      ? `已采纳为${item.scope==="job"?"岗位":item.scope==="project"?"本研究":"研究"}知识`
      : "已采纳，需重新核对"
      : item.status==="candidate" ? "已留作知识候选"
      : item.status==="withdrawn" ? "知识已撤回" : "已有知识记录";
    return `<a class="text-button" href="#memory">${e(label)} · 查看记录 ↗</a>`;
  }
  return runId&&claim.evidence_ids?.length&&claim.evidence_ids.every(id=>{
    const ev=evidence.get(id);return ev?.public_document_id||(ev?.document_id&&ev?.snapshot_id);
  }) ? `<button class="text-button" data-knowledge-run="${e(runId)}" data-claim-index="${index}" data-knowledge-project="${e(projectId||"")}">收藏这条认识 ☆</button>` : "";
}

async function collectResearchClaim(button) {
  button.disabled=true;
  try {
    const projectId=button.dataset.knowledgeProject;
    const item=button.dataset.knowledgeMemory?{id:button.dataset.knowledgeMemory}:await api("memories",{method:"POST",body:JSON.stringify({kind:"knowledge",source_run_id:button.dataset.knowledgeRun,claim_index:Number(button.dataset.claimIndex),...(projectId?{scope:"project",project_id:projectId}:{})})});
    await api("memories/"+encodeURIComponent(item.id)+"/activate",{method:"POST"});
    button.textContent="已收藏 ✓";
    if(projectId&&conversation.id===projectId){conversation.notesFor=null;await openResearchConversation(projectId,false);}
    notify("已收藏。后续研究会按资料和适用范围参考，可在“知识与偏好”修改或撤回。");
  }catch(error){button.disabled=false;throw error;}
}

function renderProjectUnderstanding(project,knowledge=[]) {
  if(!(project.steps||[]).some(step=>step.result))return "";
  const view=projectUnderstanding(project);
  const claimCard=row=>`<section class="claim">${badge(row.unresolved?"后续仍有疑问":row.result.business_review?.status==="approved"&&row.result.business_review?.reviewer_kind==="human"?"人工核对通过":"待核对",row.unresolved?"amber":"muted")} ${badge(claimBasisLabel(row.claim),"muted")} ${badge(requirementLabels[row.claim.requirement]||"性质待核","muted")} ${row.evidence.some(ev=>ev.historical_cutoffs?.length)?badge("含历史时点依据","muted"):""}<p>${e(row.claim.text)}</p><p class="form-note">第 ${row.round} 轮 · ${e(row.step.question)}</p><details class="research-context"><summary>核对这一判断的原文依据 · ${row.evidence.length} 个片段</summary>${row.evidence.map(ev=>`<p><strong>${e(ev.title||"原文资料")}</strong> · ${e(sourceLabel(ev))}</p>${historicalEvidenceNote(ev)}<blockquote>${e(ev.quote||"")}</blockquote><p class="form-note">取得 ${e(when(ev.observed_at))} · 字符 ${e(ev.start)}–${e(ev.end)}</p>${ev.document_id?`<button class="text-button" data-source="${e(ev.document_id)}">核对来源版本 ↗</button>`:""}${ev.public_document_id?`<button class="text-button" data-public-source="${e(ev.public_document_id)}">查看归档全文 ↗</button>`:""}`).join("")}</details><button class="text-button" data-conversation-claim="${e(row.claim.text)}" data-reply-step="${e(row.step.id)}">针对这条认识继续核实 ↗</button><button class="text-button" data-open-run="${e(row.step.run_id)}">查看本轮完整回答 ↗</button>${claimCorrectionButton(row.step.id,row.index)}${renderClaimKnowledge(row.step.run_id,row.claim,row.index,new Map(row.evidence.map(ev=>[ev.id,ev])),knowledge,project.id)}</section>`;
  const questionLink=row=>`<p><button class="text-button" data-conversation-followup="${e(row.prompt||row.text)}" data-followup-kind="${e(row.kind||"investigate")}" data-reply-step="${e(row.step.id)}">${e(row.text)} ↗</button></p>`;
  const changeCard=({revision,step,round})=>`<section class="detail-section"><strong>第 ${round} 轮 · ${e(({retain:"保留",revise:"修订",withdraw:"撤回",unresolved:"仍待核实"})[revision.decision]||"后续判断")}</strong><p><strong>旧判断：</strong>${e(revision.previous_statement)}</p>${(revision.new_statements||[]).map(text=>`<p><strong>本轮判断：</strong>${e(text)}</p>`).join("")}<p>${e(revision.reason)}</p>${renderRevisionAspects(revision)}${renderRevisionScope(revision)}<p class="form-note">${revision.evidence_relation==="reread"?"重读原材料":"含旧轮未读的引用；不表示新发布资料"}</p><button class="text-button" data-open-run="${e(revision.previous_run_id)}">查看旧研究 ↗</button><button class="text-button" data-open-run="${e(step.run_id)}">查看这次修正及依据 ↗</button></section>`;
  return `<article class="panel result-card"><h2>本研究当前认识</h2><div class="result-actions"><button type="button" class="secondary small" data-project-dossier="${e(project.id)}" data-export-format="html" ${project.worker_running?"disabled":""}>导出可阅读报告 ↧</button><button type="button" class="text-button" data-project-summary="${e(project.id)}" ${project.worker_running?"disabled":""}>复制研究摘要</button><button type="button" class="text-button" data-project-dossier="${e(project.id)}" ${project.worker_running?"disabled":""}>Markdown</button></div><p class="form-note">导出包含研究目标与引用原文，下载副本独立保留。</p><p class="form-note">按仍有效的研究记录整理。明确被修订或撤回的旧判断放入修正记录；其余判断仍须核对，没有自动采纳为知识。认识变化不等于外部工作变化。</p>${view.rounds.filter(row=>row.result.upstream_revision_notices?.items?.length).map(row=>`<details class="detail-section" open><summary>第 ${row.round} 轮研究需要回看其沿用依据</summary>${renderUpstreamRevisionNotices(row.result)}</details>`).join("")}${renderProjectMaps(view)}${renderScopeHistory(view)}${view.claims.length?`<div class="claim-list">${view.claims.slice(0,6).map(claimCard).join("")}</div>${view.claims.length>6?`<details class="detail-section"><summary>其余 ${view.claims.length-6} 条认识</summary>${view.claims.slice(6).map(claimCard).join("")}</details>`:""}`:'<p>尚没有可整理的当前判断。已有原文、未完成回答和核对意见保留在下方逐轮记录中。</p>'}${view.changes.length?`<details class="detail-section" open><summary>认识为何保留或改变 · ${view.changes.length} 条</summary>${view.changes.map(changeCard).join("")}</details>`:""}${view.questions.length?`<div class="detail-section"><h3>仍需核实的问题</h3>${view.questions.slice(0,5).map(questionLink).join("")}${view.questions.length>5?`<details><summary>其余 ${view.questions.length-5} 个问题</summary>${view.questions.slice(5).map(questionLink).join("")}</details>`:""}</div>`:""}${view.excluded.length?`<details class="detail-section"><summary>另有 ${view.excluded.length} 轮保留在历史中</summary>${view.excluded.map(({step,reason})=>`<p>${e(reason)} · ${e(step.question)}${step.run_id?` <button class="text-button" data-open-run="${e(step.run_id)}">查看原记录 ↗</button>`:""}</p>`).join("")}</details>`:""}<p class="form-note"><a href="#memory">查看已保存的知识与偏好 ↗</a></p></article>`;
}

function captureConversationDraft() {
  const id=conversation.renderedId;
  if(!id||!$("#conversation-question")||conversation.project?.id!==id)return;
  const value=selector=>$(selector)?.value||"";
  const turns=$("#conversation-turns")?$$("[data-conversation-step]",$("#conversation-turns")):[];
  conversation.drafts.set(id,{
    openTurns:turns.filter(turn=>turn.open).map(turn=>turn.dataset.conversationStep),
    knownTurns:turns.map(turn=>turn.dataset.conversationStep),
    question:value("#conversation-question"),context:value("#conversation-context-content"),
    publicUrl:value("#conversation-public-url"),contextKind:value("#conversation-context [name=kind]")||"preference",
    contextOpen:$("#conversation-context")?.closest?.("details")?.open||false,
    publicOpen:$("#conversation-public-document")?.closest?.("details")?.open||false,
    replyTo:conversation.replyToStepId,correctionTarget:conversation.correctionTarget?{...conversation.correctionTarget}:null,
    offline:$("#conversation-offline")?.checked,allowPublic:$("#conversation-allow-public")?.checked,
    approach:value("#conversation-approach"),kind:value("#conversation-kind"),
    application:$("#application-background")?{memoryId:value("#application-memory-id"),background:value("#application-background"),
      goal:value("#application-goal"),constraints:value("#application-constraints"),open:$("#conversation-application-panel")?.open||false}:null,
    material:{title:value("#conversation-material-title"),source:value("#conversation-material-source"),
      text:value("#conversation-material-text"),open:$("#conversation-material-panel")?.open||false},
  });
  captureActionFeedback(id);
}

function conversationScopeDraft(project) {
  let draft=conversation.sourceScopes.get(project.id);
  if(!draft||(!draft.dirty&&draft.scopeVersion!==project.scope_version)){
    const jobNames=new Map(),documentNames=new Map();
    for(const step of project.steps||[]){
      for(const job of step.result?.scope?.jobs||[])jobNames.set(job.id,job);
      for(const item of step.result?.evidence||[])if(item.public_document_id)documentNames.set(item.public_document_id,{id:item.public_document_id,title:item.title,observed_at:item.observed_at});
    }
    for(const job of project.scope_materials?.jobs||[])jobNames.set(job.id,job);
    for(const item of project.scope_materials?.documents||[])documentNames.set(item.id,item);
    draft={id:project.id,scopeVersion:project.scope_version,jobIds:new Set(project.job_ids),documentIds:new Set(project.public_document_ids||[]),allDocuments:project.public_document_ids==null,
      jobNames,documentNames,jobs:[],documents:[],jobsQuery:"",documentsQuery:"",jobsOffset:0,documentsOffset:0,jobsTotal:0,documentsTotal:0,
      jobsLoaded:false,documentsLoaded:false,jobsLoading:false,documentsLoading:false,jobsRequest:0,documentsRequest:0,dirty:false,saving:false,open:draft?.open||false,message:""};
    conversation.sourceScopes.set(project.id,draft);
  }
  return draft;
}

function renderConversationScopeBody(project,draft) {
  const selected=(kind,ids,names)=>[...ids].map(id=>`<span class="scope-summary">${e(names.get(id)?.title||(kind==="jobs"?"已选岗位":"已选归档"))}${kind==="documents"&&names.get(id)?.observed_at?" · 归档 "+e(when(names.get(id).observed_at)):""} <button type="button" class="text-button" data-scope-remove="${e(id)}" data-scope-kind="${kind}" ${draft.saving?"disabled":""}>移出本研究</button> <button type="button" class="text-button" ${kind==="jobs"?'data-job':'data-public-source'}="${e(id)}">查看原文 ↗</button></span>`).join("");
  const library=(kind,title)=>`<section class="detail-section"><h3>${title}</h3><label>查找已保存资料<input id="conversation-scope-${kind}-query" value="${e(draft[kind+'Query'])}" maxlength="200" placeholder="输入关键词"></label><button type="button" class="secondary small" data-scope-search="${kind}">查找</button>${draft[kind+'Loading']?'<p class="form-note">正在读取本机资料…</p>':`<p class="form-note">匹配 ${draft[kind+'Total']} 份；仅展示本页，其他页的选择会保留。</p>`}${draft[kind].map(item=>{
    const ids=kind==="jobs"?draft.jobIds:draft.documentIds,unavailable=kind==="documents"&&item.integrity!=="verified",checked=kind==="documents"&&draft.allDocuments?!unavailable:ids.has(item.id);
    return `<label class="checkbox-line"><input type="checkbox" data-scope-select="${e(item.id)}" data-scope-kind="${kind}" ${checked?"checked":""} ${draft.saving||(kind==="documents"&&draft.allDocuments)||unavailable&&!checked?"disabled":""}>${e(item.title)} · ${e(item.company||item.publisher||item.source_name||"")} · ${kind==="jobs"?item.has_detail?"有正文":"仅摘要":unavailable?"原文需要核对":item.evidence_kind==="work_material"?"补充工作资料":"归档网页"}${kind==="documents"&&item.observed_at?" · 归档 "+e(when(item.observed_at))+"（非发布时间）":""}</label>`;
  }).join("")}<div class="result-actions">${draft[kind+'Offset']>0?`<button type="button" class="secondary small" data-scope-page="${kind}" data-offset="${Math.max(0,draft[kind+'Offset']-20)}">上一页</button>`:""}${draft[kind+'Offset']+draft[kind].length<draft[kind+'Total']?`<button type="button" class="secondary small" data-scope-page="${kind}" data-offset="${draft[kind+'Offset']+20}">下一页</button>`:""}</div></section>`;
  return `<p class="form-note">调整今后调查可使用的资料；原回答与原范围保留。保存只改范围，不启动模型。</p><h3>已选岗位 · ${draft.jobIds.size} / 20</h3>${selected("jobs",draft.jobIds,draft.jobNames)}<label class="checkbox-line"><input type="checkbox" data-scope-all-documents ${draft.allDocuments?"checked":""} ${draft.saving?"disabled":""}>使用全部可用归档，包括之后加入的资料</label><h3>${draft.allDocuments?"归档资料采用全部可用范围":"已选归档 · "+draft.documentIds.size+" / 20"}</h3>${draft.allDocuments?"":selected("documents",draft.documentIds,draft.documentNames)}${library("jobs","岗位资料")}${library("documents","已归档网页与工作资料")}<p id="conversation-scope-message" class="form-note">${e(draft.message)}</p><div class="result-actions"><button type="button" class="secondary" data-scope-save ${project.worker_running||draft.saving?"disabled":""}>保存本研究资料范围</button><button type="button" class="text-button" data-scope-reload ${draft.saving?"disabled":""}>重新载入已保存范围</button></div>${project.worker_running?'<p class="form-note">当前调查结束或暂停后可保存范围；现在的选择会保留。</p>':""}`;
}

function renderConversationScopePanel(project) {
  const draft=conversationScopeDraft(project);
  return `<details id="conversation-scope-panel" class="detail-section" ${draft.open?"open":""}><summary>选择或调整本研究的已存资料${draft.dirty?" · 尚未保存":""}</summary><div id="conversation-scope-body">${draft.open?renderConversationScopeBody(project,draft):""}</div></details>`;
}

function refreshConversationScope(draft) {
  if(conversation.id!==draft.id||conversation.sourceScopes.get(draft.id)!==draft)return;
  const body=$("#conversation-scope-body");if(!body)return;
  const active=document.activeElement,id=active?.id,choice=active?.dataset?.scopeSelect,kind=active?.dataset?.scopeKind;
  const editing=["conversation-scope-jobs-query","conversation-scope-documents-query"].includes(id);
  const selection=editing?[active.selectionStart,active.selectionEnd]:null;
  body.innerHTML=renderConversationScopeBody(conversation.project,draft);
  if(editing){const input=$("#"+id);input.focus();input.setSelectionRange(...selection);}
  else if(choice){const input=$$("[data-scope-select]",body).find(row=>row.dataset.scopeSelect===choice&&row.dataset.scopeKind===kind);input?.focus();}
}

async function loadConversationScopeSources(kind,offset=0) {
  const id=conversation.id,draft=conversation.sourceScopes.get(id);if(!draft)return;
  const request=++draft[kind+'Request'];draft[kind+'Loading']=true;draft.message="";
  refreshConversationScope(draft);
  try {
    const query=new URLSearchParams({limit:20,offset});
    if(draft[kind+'Query'].trim())query.set(kind==="jobs"?"keyword":"q",draft[kind+'Query'].trim());
    const data=await api((kind==="jobs"?"jobs?":"public-documents?")+query);
    if(conversation.sourceScopes.get(id)!==draft||request!==draft[kind+'Request'])return;
    draft[kind]=kind==="jobs"?data.jobs:data.documents;
    draft[kind+'Total']=kind==="jobs"?data.counts.matched+data.counts.unknown:data.total;
    draft[kind+'Offset']=offset;draft[kind+'Loaded']=true;
    const names=kind==="jobs"?draft.jobNames:draft.documentNames;
    for(const item of draft[kind])names.set(item.id,item);
  } catch(error){if(conversation.sourceScopes.get(id)===draft&&request===draft[kind+'Request']){draft.message=error.message;draft[kind+'Loaded']=true;}}
  finally{if(conversation.sourceScopes.get(id)===draft&&request===draft[kind+'Request']){draft[kind+'Loading']=false;refreshConversationScope(draft);}}
}

async function saveConversationScope() {
  const id=conversation.id,draft=conversation.sourceScopes.get(id);if(!draft||draft.saving)return;
  if(draft.jobIds.size>20||(!draft.allDocuments&&draft.documentIds.size>20))throw new Error("岗位和明确选择的归档各最多20份，请先调整选择。");
  draft.saving=true;refreshConversationScope(draft);
  try {
    const project=await api("projects/"+encodeURIComponent(id));
    if(conversation.id!==id||conversation.sourceScopes.get(id)!==draft)throw new Error("研究已切换，未保存原范围。");
    if(project.state!=="active"){clearForgottenConversation([id]);throw new Error("这项研究已不可用，未保存资料范围。");}
    if(project.worker_running)throw new Error("当前调查仍在执行，请结束或暂停后保存；选择已保留。");
    const jobs=[...draft.jobIds],documents=draft.allDocuments?null:[...draft.documentIds];
    const same=(left,right)=>JSON.stringify([...left].sort())===JSON.stringify([...right].sort());
    const unchanged=same(jobs,project.job_ids)&&(documents===null?project.public_document_ids==null:project.public_document_ids!=null&&same(documents,project.public_document_ids));
    if(!unchanged&&project.scope_version!==draft.scopeVersion)throw new Error("本研究范围已在其他地方改变。当前选择保留，请重新载入已保存范围后调整。");
    const saved=unchanged?project:await api("projects/"+id,{method:"PATCH",body:JSON.stringify({revision:project.revision,goal:project.goal,job_ids:jobs,public_document_ids:documents})});
    draft.scopeVersion=saved.scope_version;draft.dirty=false;
    draft.message=unchanged?"资料范围未改变，未重复保存或启动调查。":"已保存本研究资料范围。原回答保留，可在下方继续核实；没有调用模型。";
    if(conversation.id===id)await openResearchConversation(id,false);
    return {saved:!unchanged};
  } finally {draft.saving=false;refreshConversationScope(draft);}
}

document.addEventListener("input",event=>{
  const kind=event.target.id==="conversation-scope-jobs-query"?"jobs":event.target.id==="conversation-scope-documents-query"?"documents":null;
  const draft=conversation.sourceScopes.get(conversation.id);if(kind&&draft)draft[kind+'Query']=event.target.value;
});
document.addEventListener("change",event=>{
  const item=event.target.closest("[data-scope-select],[data-scope-all-documents]");if(!item)return;
  const draft=conversation.sourceScopes.get(conversation.id);if(!draft||draft.saving)return;
  if(item.matches("[data-scope-all-documents]"))draft.allDocuments=item.checked;
  else {
    const ids=item.dataset.scopeKind==="jobs"?draft.jobIds:draft.documentIds;
    if(item.checked&&ids.size>=20){item.checked=false;notify("同类资料最多20份，请先移出不需要的资料。",true);return;}
    if(item.checked)ids.add(item.dataset.scopeSelect);else ids.delete(item.dataset.scopeSelect);
  }
  draft.dirty=true;draft.message="选择尚未保存。";refreshConversationScope(draft);
});
document.addEventListener("click",async event=>{
  const button=event.target.closest("[data-scope-search],[data-scope-page],[data-scope-save],[data-scope-reload],[data-scope-remove]");if(!button||button.disabled)return;
  const id=conversation.id,draft=conversation.sourceScopes.get(id);if(!draft)return;
  try {
    if(button.hasAttribute("data-scope-save")){await saveConversationScope();return;}
    if(button.hasAttribute("data-scope-reload")){
      const project=await api("projects/"+id);if(conversation.id!==id)return;
      if(project.state!=="active"){clearForgottenConversation([id]);return;}
      conversation.sourceScopes.delete(id);const fresh=conversationScopeDraft(project);fresh.open=true;
      await openResearchConversation(id,false);return;
    }
    if(button.dataset.scopeRemove){if(draft.saving)return;(button.dataset.scopeKind==="jobs"?draft.jobIds:draft.documentIds).delete(button.dataset.scopeRemove);draft.dirty=true;refreshConversationScope(draft);return;}
    await loadConversationScopeSources(button.dataset.scopeSearch||button.dataset.scopePage,Number(button.dataset.offset||0));
  } catch(error){if(conversation.id===id){draft.message=error.message;refreshConversationScope(draft);}}
});

async function openResearchConversation(id, navigate=true) {
  if(!navigate && conversation.id!==id)return;
  captureConversationDraft();
  clearTimeout(conversation.timer);
  conversation.id=id;sessionStorage.setItem("wo-conversation",id);
  if (navigate && state.page!=="research") location.hash="research";
  const project=await api("projects/"+encodeURIComponent(id));
  if (conversation.id!==id) return;
  if(conversation.notesFor!==id){
    const notes=await api("memories?project_id="+encodeURIComponent(id));
    if(conversation.id!==id)return;
    conversation.notes=Array.isArray(notes)?notes.filter(note=>note.project_id===id && note.status==="active" && ["preference","correction"].includes(note.kind)):[];
    conversation.knowledge=Array.isArray(notes)?notes.filter(note=>note.kind==="knowledge"):[];
    conversation.notesFor=id;
  }
  const publicReadSupported=Boolean(state.serviceContract?.paths?.["/api/public-documents"]?.post);
  const materialWriteSupported=Boolean(state.serviceContract?.paths?.["/api/work-materials"]?.post);
  const root=$("#research-output");
  const same=conversation.renderedId===id;
  captureConversationDraft();
  if(project.state==="invalidated"){
    clearForgottenConversation([id]);setBusy(false);return;
  }
  $("#research-form").hidden=true;$(".research-layout")?.classList?.add("research-focused");
  const savedDraft=conversation.drafts.get(id)||{};
  conversation.project=project;
  conversation.replyToStepId=savedDraft.replyTo===undefined?defaultConversationReply(project):savedDraft.replyTo;
  conversation.correctionTarget=savedDraft.correctionTarget||null;
  if(conversation.correctionTarget){
    const target=conversation.correctionTarget,step=project.steps.find(row=>row.id===target.stepId);
    if(target.projectId!==id||step?.run_id!==target.runId||step?.run_state==="invalidated"||step?.result?.claims?.[target.index]?.text!==target.statement)conversation.correctionTarget=null;
  }
  const draft=savedDraft.question||"",contextDraft=savedDraft.context||"",publicDraft=savedDraft.publicUrl||"";
  const applicationDraft=savedDraft.application||null,materialDraft=savedDraft.material||{};
  const contextKind=savedDraft.contextKind||"preference";
  conversation.renderedId=id;
  const active=same && ["conversation-question","conversation-context-content","conversation-public-url","conversation-scope-jobs-query","conversation-scope-documents-query","conversation-material-title","conversation-material-source","conversation-material-text","application-background","application-goal","application-constraints","action-feedback-did","action-feedback-observed","action-feedback-artifact","action-feedback-criterion","action-feedback-reproduction"].includes(document.activeElement?.id) ? document.activeElement.id : null;
  const selection=active ? [$("#"+active).selectionStart,$("#"+active).selectionEnd] : null;
  const offline=savedDraft.offline ?? project.steps.at(-1)?.offline ?? $("#offline").checked;
  const allowPublic=savedDraft.allowPublic ?? project.steps.at(-1)?.allow_public ?? $("#allow-public").checked;
  const approach=savedDraft.approach||project.steps.at(-1)?.approach||"standard";
  const pendingKey=conversationSendKeys.get(id)||sessionStorage.getItem("wo-pending-question:"+id);
  const investigationKind=savedDraft.kind||project.steps.find(step=>step.key===pendingKey)?.kind||"investigate";
  const mapSupported=(state.serviceContract?.components?.schemas?.StepInput?.properties?.approach?.enum||[]).includes("work_map");
  const exhausted=Boolean(conversationAllocation(project,offline,allowPublic).issue);
  root.innerHTML=`<article class="panel"><div class="conversation-heading"><h2>${e(project.title)}</h2><button type="button" class="text-button" data-new-research>＋ 新建研究</button></div><details class="conversation-title-editor"><summary>修改研究名称</summary><form id="conversation-title-form" data-project-id="${e(project.id)}"><input name="title" value="${e(project.title)}" maxlength="150" required aria-label="研究名称" ${project.worker_running?"disabled":""}><button class="secondary small" ${project.worker_running?"disabled":""}>保存名称</button></form></details><p class="form-note">已保存 ${project.steps.length} 轮调查 · 已调用 ${e(project.usage.calls)} / ${e(project.budget.max_calls)} 次${project.public_document_ids!=null?" · 限定 "+e(project.public_document_ids.length)+" 份归档原文":""}${project.worker_running?" · 正在查阅资料…":""}</p><div class="result-actions">${project.worker_running?'<button class="secondary" data-conversation-pause>暂停并保留进度</button>':project.steps.some(step=>["queued","interrupted"].includes(step.state))?'<button class="secondary" data-conversation-resume>继续未完成的调查</button>':""}<button class="secondary" data-conversation-import ${project.worker_running?"disabled":""}>补充岗位原文</button><button class="text-button" data-project-open="${e(project.id)}">查看全部调查记录</button></div>${materialWriteSupported?renderConversationMaterialForm(project,materialDraft):""}${publicReadSupported?`<details class="detail-section"><summary>补充公开技术文档或企业页面</summary><form id="conversation-public-document"><label>公开网页网址<input id="conversation-public-url" name="url" type="url" value="${e(publicDraft)}" required maxlength="3000" placeholder="https://官方文档或企业页面"></label><button class="secondary" ${project.worker_running?"disabled":""}>读取并归档网页</button><p class="form-note">只读取公开网页，不登录、不调用模型。正文归档到本机公开资料库，后续调查可检索；企业介绍和技术说明不能直接证明岗位个人责任。</p><div id="conversation-public-status"></div></form></details>`:""}<details class="detail-section"><summary>补充背景或纠正理解${conversation.notes.length?" · "+conversation.notes.length+"条已保存":""}</summary>${conversation.notes.slice(0,5).map(note=>`<p class="form-note"><strong>${note.kind==="correction"?"我的纠正":"我的背景/目标"}：</strong>${e(memoryText(note))}</p>`).join("")}<form id="conversation-context"><label>这段信息的用途<select name="kind"><option value="preference" ${contextKind==="preference"?"selected":""}>我的背景、目标或关注重点</option><option value="correction" ${contextKind==="correction"?"selected":""}>纠正当前研究的理解</option></select></label><div id="conversation-correction-target">${renderClaimCorrectionTarget(project.id)}</div><label>补充内容<textarea id="conversation-context-content" name="content" rows="3" maxlength="4000" required placeholder="例如：我有后端经验，想了解转向Agent应用研发要补什么；或指出哪条判断理解错了。">${e(contextDraft)}</textarea></label><button class="secondary" ${project.worker_running?"disabled":""}>保存到本研究</button><p class="form-note">仅用于这项研究；你的说明与招聘原文分开保存，不会冒充新的来源证据。</p></form></details>${renderConversationApplication(project,applicationDraft)}${renderActionFeedback(project)}</article>${renderConversationScopePanel(project)}${renderProjectUnderstanding(project,conversation.knowledge)}<div id="conversation-turns"></div><form id="conversation-followup" class="panel"><h3>接着问</h3>${renderResearchNextActions(project)}<p id="conversation-reply" class="form-note"></p><label for="conversation-question">还有什么需要弄明白？</label><textarea id="conversation-question" rows="3" maxlength="4000" required placeholder="例如：这个判断在哪些情况下不成立？还有什么资料可以验证？">${e(draft)}</textarea><label>这轮重点<select id="conversation-kind"><option value="investigate" ${investigationKind==="investigate"?"selected":""}>继续查证</option><option value="counterexample" ${investigationKind==="counterexample"?"selected":""}>寻找反例与其他解释</option><option value="synthesis" ${investigationKind==="synthesis"?"selected":""}>整理阶段成果</option></select></label>${mapSupported?`<label>本轮成果<select id="conversation-approach"><option value="standard" ${approach==="standard"?"selected":""}>简明研究回答</option><option value="work_map" ${approach==="work_map"?"selected":""}>工作地图与工作关系</option></select></label>`:""}<label class="checkbox-line"><input id="conversation-offline" type="checkbox" ${offline?"checked":""}>只整理原文，不调用模型</label><label class="checkbox-line"><input id="conversation-allow-public" type="checkbox" ${allowPublic?"checked":""}>允许本轮补查公开资料</label><button id="conversation-submit" type="submit" class="primary" ${project.worker_running||exhausted?"disabled":""}>继续调查 ↗</button><p id="conversation-limit" class="form-note"></p></form>`;
  const contextPanel=$("#conversation-context")?.closest?.("details"),publicPanel=$("#conversation-public-document")?.closest?.("details");
  if(contextPanel)contextPanel.open=savedDraft.contextOpen||Boolean(conversation.correctionTarget);
  if(publicPanel)publicPanel.open=savedDraft.publicOpen||false;
  const scopePanel=$("#conversation-scope-panel"),scopeDraft=conversation.sourceScopes.get(id);
  const loadScope=()=>{
    if(conversation.id!==id||conversation.sourceScopes.get(id)!==scopeDraft||scopePanel.isConnected===false)return;
    scopeDraft.open=scopePanel.open;
    if(scopeDraft.open){
      refreshConversationScope(scopeDraft);
      for(const kind of ["jobs","documents"])if(!scopeDraft[kind+'Loaded']&&!scopeDraft[kind+'Loading'])loadConversationScopeSources(kind);
    }
  };
  scopePanel.addEventListener("toggle",loadScope);
  if(scopeDraft.open)loadScope();
  $("#conversation-offline").addEventListener("change",()=>updateConversationAllocation(project));
  $("#conversation-allow-public").addEventListener("change",()=>updateConversationAllocation(project));
  updateConversationAllocation(project);
  const turns=$("#conversation-turns");
  for(const step of project.steps){
    const item=document.createElement("details");item.className="detail-section";
    item.open=savedDraft.knownTurns?.includes(step.id)?savedDraft.openTurns.includes(step.id):step===project.steps.at(-1);
    item.dataset.conversationStep=step.id;
    item.dataset.conversationRun=step.run_id||"";
    item.innerHTML=`<summary>${e(step.question)} <small>${e(projectStepOriginLabel(step))}</small></summary><div></div>`;turns.append(item);
    const target=item.querySelector("div");
    if(step.result?.scope){
      renderResult({...step.result,...(conversation.reports.get(step.run_id)||{})},target,step.run_id,step.id);
      const questions=(step.result.review?.next_questions || step.result.gaps || []).filter(text=>/[？?]|核实|补查/.test(text)).slice(0,3);
      if(questions.length)target.insertAdjacentHTML("beforeend",`<div class="panel"><h4>沿着这些疑问继续查</h4>${questions.map(text=>`<button class="secondary small" data-conversation-followup="${e(text)}" data-reply-step="${e(step.id)}">${e(text)}</button>`).join(" ")}</div>`);
    }
    else target.innerHTML=`<p class="form-note">${({queued:"等待查阅资料",running:"正在调查…",interrupted:"已暂停，进度已保留",failed:"本轮未完成，可查看全部调查记录中的原因"})[step.state]||"资料与进度已保留"}</p>`;
    if(step.evidence_needed)target.insertAdjacentHTML("afterbegin",`<section class="research-context"><p><strong>本轮完成条件：</strong>${e(step.completion)}</p><p><strong>本轮所需证据：</strong>${e(step.evidence_needed)}</p></section>`);
    target.insertAdjacentHTML("beforeend",renderInvestigationProposals(step.result||{},project,step,true)+renderStepContinuation(project,step));
  }
  renderConversationReply();
  if(active){const input=$("#"+active);input.focus();input.setSelectionRange(...selection);}
  setBusy(project.worker_running);
  researchProjects=[{id:project.id,title:project.title,goal:project.goal,state:project.state,updated_at:project.updated_at,
    step_count:project.steps.length,
    job_count:project.job_ids?.length||0,document_count:project.public_document_ids?.length??null,
    last_question:project.steps.at(-1)?.question,last_state:project.steps.at(-1)?.state,worker_running:project.worker_running},...researchProjects.filter(row=>row.id!==project.id)];
  renderResearchProjects();
  if(project.worker_running)conversation.timer=setTimeout(()=>openResearchConversation(id,false).catch(error=>{setBusy(false);notify(error.message,true);}),2000);
}

document.addEventListener("submit",async event=>{
  if(event.target.id!=="conversation-followup")return;
  event.preventDefault();const input=$("#conversation-question"),question=input.value.trim();if(!question)return;
  const button=$("#conversation-submit");button.disabled=true;
  try{const offline=$("#conversation-offline").checked,allowPublic=$("#conversation-allow-public").checked;input.value="";await askResearchConversation(question,{offline,allowPublic});}catch(error){input.value=question;button.disabled=false;notify(error.message,true);}
});
function renderResearchNextActions(project) {
  const latest=project.steps.slice().reverse().find(step=>step.run_id&&step.result);
  if(!latest)return "";
  const actions=[
    ["解释得更具体","请结合本研究的原文和已有判断，用具体的任务与交付物解释核心区别。哪些是原文明示，哪些是推断？不要补造资料没有说明的内容。","investigate"],
    ["找反例与边界","针对本研究的关键判断，寻找反例、其他合理解释和适用边界。请核对原文；没有反证时说明仍待验证，不为反驳而编造。","counterexample"],
    ["整理阶段成果","围绕本研究目标整理一份简洁成果：核心认识、主要任务与交付物、依据、已发生的修正和仍未解决的问题。只复用当前适用的认识，未复查部分明确说明。","synthesis"],
  ];
  return `<div class="research-next-actions">${latest.result.status==="evidence_only"?'<button type="button" class="secondary" data-analyze-evidence>用 AI 分析这些原文</button>':""}${actions.map(([label,question,kind])=>`<button type="button" class="secondary small" data-conversation-followup="${e(question)}" data-followup-kind="${kind}" data-reply-step="${e(latest.id)}" ${project.worker_running?"disabled":""}>${label}</button>`).join("")}</div><p class="form-note">点选后先填写问题，可修改后再继续。</p>`;
}

function prepareEvidenceAnalysis() {
  const project=conversation.project;if(!project||project.worker_running)return;
  const input=$("#conversation-question");
  if(!input.value.trim())input.value="请根据本研究已有原文回答研究目标，解释业务问题、主要任务、交付物和责任分工，引用原文并明确哪些内容仍未知。";
  $("#conversation-offline").checked=false;$("#conversation-kind").value="investigate";
  conversation.replyToStepId=defaultConversationReply(project);renderConversationReply();updateConversationAllocation(project);
  input.focus();input.scrollIntoView({block:"center",behavior:"smooth"});
}

document.addEventListener("click",event=>{if(event.target.closest("[data-analyze-evidence]"))prepareEvidenceAnalysis();});

function defaultConversationReply(project) {
  return project.steps?.slice().reverse().find(step=>!["queued","running","interrupted"].includes(step.state))?.id || null;
}

const continuationReasons={calls_exhausted:"本轮调用次数已用完，保留原记录；继续按钮不会重新开放额度。",time_exhausted:"本轮调查时间已用完，原进度和消耗保留。",no_checkpoint:"没有可继续的检查点，已有原文和记录仍保留。",scope_changed:"范围或目标已调整，需在当前范围安排新一轮核实。",material_changed:"原资料或背景已改变，请按当前资料补查，不沿旧快照继续。",answer_completed:"本轮已有生成的回答，可直接查看。",unavailable:"相关记录已不可继续。"};
function renderStepContinuation(project,step) {
  const continuation=step.continuation;if(!continuation)return "";
  if(!continuation.available)return `<p class="form-note">${e(continuationReasons[continuation.reason]||"当前不能继续原检查点。")}</p>`;
  return `<section class="research-context"><p>本轮仍有至多 ${e(continuation.remaining_calls)} 次调用、${e(continuation.remaining_seconds)} 秒，可沿原检查点接着调查。保持原范围与总预算。</p><button type="button" class="secondary" data-continue-conversation-step="${e(step.id)}" ${project.worker_running||conversationSending.has(project.id)?"disabled":""}>继续本轮剩余调查 ↗</button></section>`;
}
async function continueConversationStep(stepId) {
  const id=conversation.id;
  if(conversationSending.has(id))throw new Error("本研究的请求正在处理，请稍候。");
  conversationSending.add(id);
  try {
    const project=await api("projects/"+encodeURIComponent(id));
    if(conversation.id!==id)throw new Error("研究已切换，未启动原调查。");
    const step=project.steps.find(row=>row.id===stepId);
    if(project.worker_running)throw new Error("本研究正在调查，请等待进度。");
    if(!step?.continuation?.available)throw new Error(continuationReasons[step?.continuation?.reason]||"本轮当前无法沿原检查点继续。");
    if(step.state==="failed")await api("projects/"+id+"/steps/"+stepId+"/review",{method:"POST",body:JSON.stringify({revision:project.revision,action:"retry",note:"在研究工作台明确继续原检查点；不改变原范围、原预算或质量状态。"})});
    await api("projects/"+id+"/run",{method:"POST",body:JSON.stringify({step_id:stepId})});
    if(conversation.id===id)await openResearchConversation(id,false);
  } finally {conversationSending.delete(id);}
}
document.addEventListener("click",async event=>{
  const button=event.target.closest("[data-continue-conversation-step]");if(!button||button.disabled)return;
  button.disabled=true;
  try{await continueConversationStep(button.dataset.continueConversationStep);}catch(error){notify(error.message,true);}
  finally{if(button.isConnected)button.disabled=false;}
});

const APPLICATION_PREFIX="个人应用背景（用户自述，结构化）：\n";
const APPLICATION_UNAVAILABLE="已保存背景目前不可用于研究。请在知识与偏好查看当前状态或有效期；当前输入保留。";

function applicationProfile(note,projectId) {
  if(note.project_id!==projectId||note.scope!=="project"||note.kind!=="preference"||note.origin!=="user"||note.status!=="active")return null;
  let data;
  if(note.content?.startsWith(APPLICATION_PREFIX)) {
    try{data=JSON.parse(note.content.slice(APPLICATION_PREFIX.length));}catch{return null;}
  } else {
    // Recognize the previous form only when each field boundary is unambiguous.
    const labels=["已有经历或能力：","\n本次目标：","\n投入与限制："];
    if(!note.content?.startsWith("个人应用背景（用户自述）：\n")||labels.some(label=>note.content.split(label).length!==2))return null;
    const match=note.content.match(/^个人应用背景（用户自述）：\n已有经历或能力：([\s\S]+)\n本次目标：([\s\S]+)\n投入与限制：([\s\S]*)$/);
    if(!match)return null;
    data={background:match[1],goal:match[2],constraints:match[3]==="未说明，不作假设"?"":match[3]};
  }
  if(!data||typeof data!=="object"||Array.isArray(data)||Object.keys(data).sort().join(",")!=="background,constraints,goal"||typeof data.background!=="string"||typeof data.goal!=="string"||typeof data.constraints!=="string"||!data.background.trim()||!data.goal.trim()||data.background.length>1500||data.goal.length>1000||data.constraints.length>500)return null;
  return {memoryId:note.id,version:note.version||1,...data};
}

function renderConversationApplication(project,draft=null) {
  const profiles=conversation.notes.filter(note=>note.validity?.eligible!==false).map(note=>applicationProfile(note,project.id)).filter(Boolean);
  const unavailable=conversation.notes.some(note=>note.validity?.eligible===false&&applicationProfile(note,project.id));
  const values=draft || (profiles.length===1?profiles[0]:{});
  const saved=profiles.find(row=>row.memoryId===values.memoryId);
  const notice=profiles.length>1?"有多份个人应用背景并存，请到知识与偏好选择当前背景后再修改。":!profiles.length&&unavailable?APPLICATION_UNAVAILABLE:values.memoryId&&!saved?"背景已在别处更新；当前输入仍保留，可载入已保存的新版。":saved?`已载入第 ${saved.version} 版背景；修改后新增版本，旧研究保留当时背景。`:"尚未保存这项研究的个人应用背景。";
  return `<details id="conversation-application-panel" class="detail-section" ${values.open?"open":""}><summary>把研究用于我的目标</summary><p class="form-note">${e(notice)} ${profiles.length>1?'<a href="#memory">查看知识与偏好</a>':""}</p><form id="conversation-application"><input type="hidden" id="application-memory-id" name="memory_id" value="${e(values.memoryId||"")}"><label>我已有的经历或能力<textarea id="application-background" name="background" rows="3" required maxlength="1500" placeholder="写你实际做过的工作或项目；没有相关经历也可以直接说明。">${e(values.background||"")}</textarea></label><label>这次想达到什么目标<textarea id="application-goal" name="goal" rows="2" required maxlength="1000" placeholder="例如：做一个可展示的项目，验证自己能否承担这类工作。">${e(values.goal||"")}</textarea></label><label>时间、资源或其他限制（可选）<textarea id="application-constraints" name="constraints" rows="2" maxlength="500" placeholder="例如：每周能投入的时间、可用资料、无法接触的系统。">${e(values.constraints||"")}</textarea></label><div class="result-actions"><button class="secondary" ${project.worker_running?"disabled":""}>保存背景并准备应用问题</button><button type="button" class="text-button" data-application-reload ${project.worker_running?"disabled":""}>载入已保存背景</button></div><p class="form-note">只用于这项研究。保存后可编辑下方追问，点击“继续调查”才调用模型；回答会区分原文要求与建议，给出可检查的产物和待核实信息。</p></form></details>`;
}

async function reloadResearchApplication() {
  const id=conversation.id;
  const notes=await api("memories?project_id="+encodeURIComponent(id));
  if(conversation.id!==id)return;
  const profiles=notes.filter(note=>note.validity?.eligible!==false).map(note=>applicationProfile(note,id)).filter(Boolean);
  if(profiles.length>1)throw new Error("有多份背景并存，请先到知识与偏好选择当前背景；当前输入保留。");
  if(!profiles.length&&notes.some(note=>note.validity?.eligible===false&&applicationProfile(note,id)))throw new Error(APPLICATION_UNAVAILABLE);
  const values=profiles[0]||{};
  conversation.notes=notes.filter(note=>note.project_id===id&&note.status==="active"&&["preference","correction"].includes(note.kind));
  conversation.knowledge=notes.filter(note=>note.kind==="knowledge");
  conversation.notesFor=id;
  for(const field of ["background","goal","constraints"])$("#application-"+field).value=values[field]||"";
  $("#application-memory-id").value=values.memoryId||"";
  await openResearchConversation(id,false);
}

document.addEventListener("click",async event=>{
  const button=event.target.closest("[data-application-reload]");if(!button)return;
  button.disabled=true;
  try{await reloadResearchApplication();notify("已载入保存的背景，追问保持不变。");}catch(error){notify(error.message,true);}
  finally{button.disabled=false;}
});

async function prepareResearchApplication(background,goal,constraints="",memoryId=$("#application-memory-id")?.value||"") {
  background=background.trim();goal=goal.trim();constraints=constraints.trim();
  if(!background||!goal)throw new Error("请填写实际经历和这次目标；没有相关经历也可以直接说明。");
  if(background.length>1500||goal.length>1000||constraints.length>500)throw new Error("内容超出长度，请精简经历、目标或限制。");
  const prompt="请结合本研究中我明确保存的个人应用背景，回答这些工作认识对我的目标有什么具体意义。先重新查阅适用原文，并核对是否存在互相冲突的背景或尚未说明的关键信息；若有，先列待确认项，不替我选择或补造经历。区分原文明示的工作要求、我自述的能力和你的应用推断，不把会用某工具等同于具备岗位能力，不据此认定已符合岗位或保证结果。最多建议3个按先后顺序可执行的学习或项目动作：每个说明它针对的任务或能力、可交付产物、怎样检查完成，以及对应原文引用。建议的产物和检查方式标明是推断，不冒充企业既定验收；资料或背景不足时说明还要补什么。";
  const question=$("#conversation-question");
  const combined=question.value.includes(prompt)?question.value:question.value+(question.value.trim()?"\n\n":"")+prompt;
  if(combined.length>4000)throw new Error("现有追问加上应用问题过长，请先精简下方追问；背景尚未保存。");
  const targetProject=conversation.id;
  const project=await api("projects/"+encodeURIComponent(targetProject));
  if(project.worker_running)throw new Error("请等当前调查结束后，再保存应用背景。");
  if(conversation.id!==targetProject)throw new Error("研究已切换，请在当前研究重新准备应用问题。");
  const allocation=conversationAllocation(project,$("#conversation-offline").checked,$("#conversation-allow-public").checked);
  if(allocation.issue)throw new Error(allocation.issue);
  const content=APPLICATION_PREFIX+JSON.stringify({background,goal,constraints});
  if(content.length>4000)throw new Error("背景包含较多换行或特殊字符，请精简后再保存；当前输入保留。");
  // Read current versions even when the form was restored from a cached conversation.
  const known=await api("memories?project_id="+encodeURIComponent(targetProject));
  if(conversation.id!==targetProject)throw new Error("研究已切换，请在当前研究重新准备应用问题。");
  const candidates=known.filter(note=>note.validity?.eligible!==false&&applicationProfile(note,targetProject));
  if(known.some(note=>note.status==="conflict"&&applicationProfile({...note,status:"active"},targetProject)))throw new Error("背景存在冲突，请到知识与偏好选择当前背景；当前输入保留。");
  if(known.some(note=>note.validity?.eligible===false&&applicationProfile(note,targetProject)&&(!candidates.length||note.id===memoryId)))throw new Error(APPLICATION_UNAVAILABLE);
  if(candidates.length>1)throw new Error("有多份背景并存，请先到知识与偏好选择当前背景；当前输入保留。");
  const old=candidates.find(note=>note.id===memoryId);
  const matching=candidates.find(note=>{const row=applicationProfile(note,targetProject);return row.background===background&&row.goal===goal&&row.constraints===constraints;});
  let saved=matching;
  if(memoryId&&!old&&!(matching?.previous_id===memoryId||matching?.id===memoryId))throw new Error("背景已有新版，请先载入已保存背景再修改；当前输入保留。");
  if(!saved) {
    if(old)saved=await api("memories/"+encodeURIComponent(old.id)+"/revise",{method:"POST",body:JSON.stringify({content})});
    else {
      if(candidates.length)throw new Error("已有保存的背景，请先载入后再修改；当前输入保留。");
      saved=await api("memories",{method:"POST",body:JSON.stringify({kind:"preference",content,subject:"个人应用背景",scope:"project",project_id:targetProject,origin:"user"})});
    }
  }
  if(saved.status!=="active")throw new Error("背景存在冲突，请到知识与偏好选择当前背景；当前输入保留。");
  conversation.notesFor=null;
  if(conversation.id!==targetProject)return;
  // The draft may have been edited while saving: append to its current value.
  const updated=question.value.includes(prompt)?question.value:question.value+(question.value.trim()?"\n\n":"")+prompt;
  if(updated.length>4000)throw new Error("背景已保存；当前追问过长，请精简后再准备应用问题。");
  question.value=updated;
  $("#application-memory-id").value=saved.id;
  await openResearchConversation(targetProject,false);
  $("#conversation-question").focus();
  $("#conversation-question").scrollIntoView({block:"center",behavior:"smooth"});
}

document.addEventListener("submit",async event=>{
  if(event.target.id!=="conversation-application")return;
  event.preventDefault();const form=event.target,button=event.submitter||form.querySelector("button");button.disabled=true;
  try{await prepareResearchApplication(form.elements.background.value,form.elements.goal.value,form.elements.constraints.value);notify("背景已保存，应用问题已放到下方。可编辑后继续调查。");}
  catch(error){notify(error.message,true);}
  finally{button.disabled=false;}
});

function renderConversationReply() {
  const target=$("#conversation-reply");if(!target)return;
  const step=conversation.project?.steps.find(step=>step.id===conversation.replyToStepId);
  target.innerHTML=step ? `正在追问：${e(step.question)} <button type="button" class="text-button" data-conversation-new-topic>改问新问题</button>` : "本次作为新问题调查，仍沿用当前研究的资料范围。";
}

function prefillConversationFollowup(button) {
  conversation.replyToStepId=button.dataset.replyStep;
  const kind=$("#conversation-kind");if(kind)kind.value=button.dataset.conversationClaim?"counterexample":["counterexample","synthesis"].includes(button.dataset.followupKind)?button.dataset.followupKind:"investigate";
  renderConversationReply();
  const input=$("#conversation-question");
  input.value=button.dataset.conversationClaim
    ? "请核实这条判断：「"+button.dataset.conversationClaim+"」\n原文依据是什么？有哪些反例或不成立的情况？请重新查证，必要时纠正。"
    : "继续核实上一轮留下的疑问："+button.dataset.conversationFollowup+"\n请先查现有资料，明确能解决什么、还缺哪些证据。";
  input.focus();input.scrollIntoView({block:"center",behavior:"smooth"});
}

document.addEventListener("click",event=>{
  if(event.target.closest("[data-conversation-new-topic]")){conversation.replyToStepId=null;if($("#conversation-kind"))$("#conversation-kind").value="investigate";renderConversationReply();return;}
  const button=event.target.closest("[data-conversation-followup], [data-conversation-claim]");if(!button)return;
  prefillConversationFollowup(button);
});

document.addEventListener("click",async event=>{
  const pause=event.target.closest("[data-conversation-pause]"),resume=event.target.closest("[data-conversation-resume]");
  if(!pause&&!resume)return;
  try{await api("projects/"+conversation.id+(pause?"/pause":"/run"),{method:"POST",body:"{}"});await openResearchConversation(conversation.id);}catch(error){notify(error.message,true);}
});

const conversationMaterialReceipts = new Map();
const actionFeedbackSelections = new Map(),actionFeedbackDrafts = new Map(),actionFeedbackSaving = new Set();
const attemptCheckLabels={unverified:"尚未核验",met:"按所填标准自查符合",not_met:"按所填标准自查不符",unclear:"尝试后仍无法判断"};

function currentActionFeedback(projectId) {
  if(!actionFeedbackSelections.has(projectId)){
    let saved=null;try{saved=JSON.parse(sessionStorage.getItem("wo-action-feedback:"+projectId)||"null");}catch{}
    if(saved&&/^[a-f0-9]{32}$/.test(saved.stepId)&&/^[a-f0-9]{32}$/.test(saved.runId)&&Number.isInteger(saved.index)&&saved.index>=0&&saved.index<3&&(!saved.documentId||/^[a-f0-9]{32}$/.test(saved.documentId)))actionFeedbackSelections.set(projectId,saved);
  }
  const selection=actionFeedbackSelections.get(projectId);if(!selection)return null;
  const key=projectId+":"+selection.stepId+":"+selection.index;
  if(!actionFeedbackDrafts.has(key))actionFeedbackDrafts.set(key,{...selection,did:"",observed:"",artifact:"",criterion:"",checkState:"unverified",reproduction:""});
  return actionFeedbackDrafts.get(key);
}

function rememberActionFeedback(projectId,draft) {
  const receipt={stepId:draft.stepId,runId:draft.runId,index:draft.index,documentId:draft.documentId||null,attached:Boolean(draft.attached)};
  actionFeedbackSelections.set(projectId,receipt);
  sessionStorage.setItem("wo-action-feedback:"+projectId,JSON.stringify(receipt));
}

function captureActionFeedback(projectId) {
  const draft=currentActionFeedback(projectId);
  if(!draft||draft.documentId)return;
  if($("#action-feedback-form")?.dataset?.actionFeedbackKey!==projectId+":"+draft.stepId+":"+draft.index)return;
  for(const key of ["did","observed","artifact","criterion","checkState","reproduction"]){const input=$("#action-feedback-"+key);if(input)draft[key]=input.value||(key==="checkState"?"unverified":"");}
}

function renderAttemptVerification(draft) {
  return `<label>本次核验标准及其来源（可选）<textarea id="action-feedback-criterion" name="criterion" rows="3" maxlength="2000" placeholder="什么结果算符合？标准来自哪份原文、原建议，还是自行约定？尚未明确可留空。">${e(draft.criterion||"")}</textarea></label><label>本次自查结果<select id="action-feedback-checkState" name="check_state">${Object.entries(attemptCheckLabels).map(([value,label])=>`<option value="${value}" ${value===(draft.checkState||"unverified")?"selected":""}>${e(label)}</option>`).join("")}</select></label><label>复现条件（可选）<textarea id="action-feedback-reproduction" name="reproduction" rows="3" maxlength="2000" placeholder="使用的资料或程序版本、输入/样本、运行环境等；不知道的项目留待核实。">${e(draft.reproduction||"")}</textarea></label><p class="form-note">有日志不等于通过验证。选择自查符合或不符须说明标准；自查结果仍是用户回报，未经独立验收。</p>`;
}

function renderActionFeedback(project) {
  const draft=currentActionFeedback(project.id);if(!draft)return "";
  const step=project.steps.find(step=>step.id===draft.stepId&&step.run_id===draft.runId);
  const action=step?.result?.application_plan?.actions?.[draft.index];
  if(!action)return '<p class="form-note">原行动建议当前无法读取，回报草稿保留；请从可查看的原建议继续。</p>';
  return `<details id="action-feedback-panel" class="detail-section" open><summary>回报尝试结果 · ${e(action.title)}</summary><form id="action-feedback-form" data-action-feedback-key="${e(project.id+':'+draft.stepId+':'+draft.index)}">${draft.documentId?`<p class="form-note">尝试记录已保存。${draft.attached?"已加入本研究，可继续核实。":"尚未加入本研究，可直接重试，无需再次保存。"}</p><button type="button" class="text-button" data-public-source="${e(draft.documentId)}">核对尝试记录原文 ↗</button>`:`<label>实际尝试了什么<textarea id="action-feedback-did" name="did" rows="3" maxlength="4000" required>${e(draft.did)}</textarea></label><label>观察结果或遇到的问题<textarea id="action-feedback-observed" name="observed" rows="3" maxlength="4000" required>${e(draft.observed)}</textarea></label>${renderAttemptVerification(draft)}<label>产出或核验原文（可选）<textarea id="action-feedback-artifact" name="artifact" rows="4" maxlength="50000" placeholder="粘贴实际取得的产出、测试记录或错误信息；没有就留空。">${e(draft.artifact)}</textarea></label>`}<button class="secondary" ${project.worker_running||actionFeedbackSaving.has(project.id)?"disabled":""}>${draft.documentId?"加入记录并准备追问":"保存尝试记录并准备追问"}</button><p class="form-note">记录为用户自述，未独立核实；建议不会自动标成完成或能力证明。保存不调用模型，也不自动执行外部动作。</p>${draft.documentId?`<button type="button" class="text-button" data-action-feedback-new ${actionFeedbackSaving.has(project.id)?'disabled':''}>记录另一次尝试</button>`:""}</form></details>`;
}

async function selectActionFeedback(stepId,index) {
  const project=conversation.project,step=project?.steps.find(step=>step.id===stepId);
  if(actionFeedbackSaving.has(project?.id))throw new Error("尝试记录正在保存，请稍候再切换。");
  if(!step?.result?.application_plan?.actions?.[index]||!Number.isInteger(index))throw new Error("无法读取这条原建议，请先刷新研究。");
  captureActionFeedback(project.id);
  actionFeedbackSelections.set(project.id,{stepId,index,runId:step.run_id});
  rememberActionFeedback(project.id,currentActionFeedback(project.id));
  await openResearchConversation(project.id,false);
  $("#action-feedback-panel").scrollIntoView({block:"center",behavior:"smooth"});
}

async function saveActionFeedback(did="",observed="",artifact="",verification={}) {
  const projectId=conversation.id;
  if(actionFeedbackSaving.has(projectId))throw new Error("尝试记录正在保存，请稍候。");
  actionFeedbackSaving.add(projectId);
  try{return await saveSelectedActionFeedback(did,observed,artifact,verification);}
  finally{
    actionFeedbackSaving.delete(projectId);
    if(conversation.id===projectId){
      const form=$("#action-feedback-form"),submit=form?.querySelector('button:not([type="button"])'),another=form?.querySelector("[data-action-feedback-new]");
      if(submit)submit.disabled=Boolean(conversation.project?.worker_running);
      if(another)another.disabled=Boolean(conversation.project?.worker_running);
    }
  }
}

async function saveSelectedActionFeedback(did="",observed="",artifact="",verification={}) {
  const projectId=conversation.id,draft=currentActionFeedback(projectId);
  if(!draft)throw new Error("请先选择要回报的行动建议。");
  if(!draft.documentId){
    draft.did=did;draft.observed=observed;draft.artifact=artifact;
    draft.criterion=verification.criterion??draft.criterion??"";
    draft.checkState=verification.checkState||draft.checkState||"unverified";
    draft.reproduction=verification.reproduction??draft.reproduction??"";
    if(!did.trim()||!observed.trim())throw new Error("请说明实际尝试和观察结果；尚未开始也请如实说明。");
    if(did.length>4000||observed.length>4000||artifact.length>50000)throw new Error("内容超出长度，请精简后再保存。");
    if(!Object.hasOwn(attemptCheckLabels,draft.checkState))throw new Error("请选择本次自查结果，不能把未知当成符合。");
    if(["met","not_met"].includes(draft.checkState)&&!draft.criterion.trim())throw new Error("选择自查符合或不符前，请说明核验标准及来源；没有标准时可保留尚未核验或无法判断。");
    if(draft.criterion.length>2000||draft.reproduction.length>2000)throw new Error("核验标准或复现条件过长，请精简后再保存。");
  }
  const project=await api("projects/"+encodeURIComponent(projectId));
  if(project.worker_running)throw new Error("请等当前调查结束后再保存回报；输入仍保留。");
  const step=project.steps.find(step=>step.id===draft.stepId&&step.run_id===draft.runId);
  if(!step?.result?.application_plan?.actions?.[draft.index])throw new Error("原建议已不可读取，当前回报保留，未自动另建资料。");
  if(conversation.id!==projectId)return;
  if(!draft.documentId){
    const text=`用户尝试记录（用户自述，未独立核实）\n回应研究：${draft.runId}\n回应建议序号：${draft.index+1}\n记录编号只用于关联，不是执行或能力证明。\n\n实际尝试（用户自述）：\n${draft.did}\n\n观察结果（用户自述）：\n${draft.observed}\n\n本次核验标准及来源（用户填写）：\n${draft.criterion||"未说明，不能据此判定符合或不符"}\n\n本次自查结果（用户回报，非独立验收）：\n${attemptCheckLabels[draft.checkState]}\n\n复现条件（用户填写）：\n${draft.reproduction||"未说明，留待核实"}\n\n产出或核验原文（用户粘贴，未独立核实）：\n${draft.artifact||"未提供"}`;
    const result=await api("work-materials",{method:"POST",body:JSON.stringify({title:"行动尝试记录 · 建议"+(draft.index+1),text,source_name:"用户自行回报的尝试与观察，未经独立核实"})});
    draft.documentId=result.document.id;rememberActionFeedback(projectId,draft);
    rememberConversationMaterial(projectId,result.document);
    if(conversation.id===projectId)await openResearchConversation(projectId,false);
  }
  await attachConversationArchivedMaterial(projectId,draft.documentId);
  draft.attached=true;rememberActionFeedback(projectId,draft);
  rememberConversationMaterial(projectId,{id:draft.documentId,title:"行动尝试记录 · 建议"+(draft.index+1),evidence_kind:"work_material"},true);
  if(conversation.id!==projectId)return;
  conversation.replyToStepId=draft.stepId;
  const input=$("#conversation-question"),prompt=`请重新核实上面第 ${draft.index+1} 条行动建议，并查阅刚加入的尝试记录（归档编号 ${draft.documentId}）。旧建议只是研究推断，用户尝试记录是自述；先区分实际提供的产出或核验原文与尚未验证的说法。核对用户填写的标准、标准来源、输入或版本等复现条件，标准或资料不足就保留未知；有日志、自查符合或单项指标达标不等于根因已定位或能力已证明。只在项目上下文确实带出原行动时回看它；未带出则说明缺口，不根据编号补造内容。原建议的动作、产物和完成检查哪些得到支持、遇到反例或需要调整？给出下一步最必要的验证，不把一次自述、工具使用或测试记录概括为已具备岗位能力。`;
  if(!input.value.includes(prompt)){
    if(input.value.length+prompt.length+2>4000)throw new Error("尝试记录已保存并加入；下方追问过长，请精简后再次准备。");
    input.value+=(input.value.trim()?"\n\n":"")+prompt;
  }
  await openResearchConversation(projectId,false);
  $("#conversation-question").focus();
}

document.addEventListener("click",async event=>{
  const selected=event.target.closest("[data-action-feedback-step]"),another=event.target.closest("[data-action-feedback-new]");
  try{
    if(selected)await selectActionFeedback(selected.dataset.actionFeedbackStep,Number(selected.dataset.actionFeedbackIndex));
    if(another){const draft=currentActionFeedback(conversation.id);if(!draft)return;draft.documentId=null;draft.attached=false;draft.did="";draft.observed="";draft.artifact="";draft.criterion="";draft.checkState="unverified";draft.reproduction="";rememberActionFeedback(conversation.id,draft);await openResearchConversation(conversation.id,false);}
  }catch(error){notify(error.message,true);}
});

document.addEventListener("submit",async event=>{
  if(event.target.id!=="action-feedback-form")return;
  event.preventDefault();const form=event.target,button=event.submitter||form.querySelector('button:not([type="button"])');button.disabled=true;
  try{await saveActionFeedback(form.elements.did?.value||"",form.elements.observed?.value||"",form.elements.artifact?.value||"",{criterion:form.elements.criterion?.value||"",checkState:form.elements.check_state?.value||"unverified",reproduction:form.elements.reproduction?.value||""});notify("尝试记录已保存，可以继续核实原建议。保存未调用模型。");}
  catch(error){notify(error.message,true);}
  finally{button.disabled=false;}
});

function materialReceipts(projectId) {
  if(!conversationMaterialReceipts.has(projectId)){
    let saved=[];
    try{saved=JSON.parse(sessionStorage.getItem("wo-material-receipts:"+projectId)||"[]");}catch{}
    conversationMaterialReceipts.set(projectId,Array.isArray(saved)?saved.filter(item=>item&&/^[a-f0-9]{32}$/.test(item.id)&&typeof item.title==="string").slice(-20):[]);
  }
  return conversationMaterialReceipts.get(projectId);
}

function rememberConversationMaterial(projectId,document,attached=false) {
  const rows=materialReceipts(projectId),previous=rows.find(item=>item.id===document.id);
  if(previous)previous.attached=attached;
  else rows.push({id:document.id,title:document.title,attached,evidence_kind:document.evidence_kind});
  sessionStorage.setItem("wo-material-receipts:"+projectId,JSON.stringify(rows.slice(-20)));
}

function renderConversationMaterialReceipts(projectId) {
  return materialReceipts(projectId).slice(-20).reverse().map(item=>`<div class="detail-history"><strong>${e(item.title)}</strong><p class="form-note">${item.attached?"已加入本研究，可在下一轮查阅。":"原文已保存，尚未加入本研究；可重试加入，无需再次保存。"}</p><button type="button" class="text-button" data-public-source="${e(item.id)}">核对归档原文 ↗</button>${item.attached?"":`<button type="button" class="secondary small" data-attach-conversation-document="${e(item.id)}">加入当前研究</button>`}</div>`).join("");
}

function renderConversationMaterialForm(project,draft={}) {
  return `<details id="conversation-material-panel" class="detail-section" ${draft.open?"open":""}><summary>补充工作资料</summary><label class="research-file-drop"><input type="file" id="conversation-material-files" data-conversation-files data-project-id="${e(project.id)}" multiple accept=".txt,.md,.markdown,.docx,.pdf,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" ${project.worker_running||conversation.materialSaving===project.id?"disabled":""}><strong>上传文件，加入这项研究</strong><span>TXT / Markdown / Word / PDF，可多选；已有回答会保留</span></label><div id="conversation-file-status" class="form-note" role="status"></div><form id="conversation-work-material"><label>资料标题<input id="conversation-material-title" name="title" value="${e(draft.title||"")}" required maxlength="300" placeholder="例如：项目说明、SOP、任务复盘"></label><label>来源说明<input id="conversation-material-source" name="source_name" value="${e(draft.source||"")}" maxlength="500" placeholder="保留资料出处；未知可留空"></label><label>原文内容<textarea id="conversation-material-text" name="text" rows="5" required maxlength="100000">${e(draft.text||"")}</textarea></label><button class="secondary" ${project.worker_running||conversation.materialSaving===project.id?"disabled":""}>保存并加入本研究</button><p class="form-note">粘贴资料与岗位、网页来源分别标记，来源说明未经独立核实。保存不调用模型，旧回答保留；下一轮再核对它支持或改变了什么。</p><p id="conversation-material-status" class="form-note" role="status"></p><div id="conversation-material-receipts">${renderConversationMaterialReceipts(project.id)}</div></form></details>`;
}

async function attachConversationArchivedMaterial(projectId,documentId) {
  const project=await api("projects/"+encodeURIComponent(projectId));
  if(project.worker_running)throw new Error("原文已保存。请先暂停当前调查，再加入本研究。");
  if(project.public_document_ids!=null&&!project.public_document_ids.includes(documentId)){
    if(project.public_document_ids.length>=20)throw new Error("原文已保存；本研究已选满20份归档资料，请调整范围或另建研究。");
    await api("projects/"+project.id,{method:"PATCH",body:JSON.stringify({revision:project.revision,goal:project.goal,job_ids:project.job_ids,public_document_ids:[...project.public_document_ids,documentId]})});
  }
}

function prefillMaterialFollowup(title) {
  const input=$("#conversation-question");if(!input||input.value.trim())return;
  input.value="结合刚补充的《"+title+"》继续核对：哪些旧判断得到支持，哪些需要修订？请区分原文、推断和未知。";
}

async function saveConversationWorkMaterial(title,text,source_name="") {
  if(!title.trim()||!text.trim())throw new Error("请填写资料标题和原文。");
  const projectId=conversation.id;
  const result=await api("work-materials",{method:"POST",body:JSON.stringify({title:title.trim(),text,source_name:source_name.trim()})});
  rememberConversationMaterial(projectId,result.document);
  if(conversation.id===projectId){
    for(const id of ["conversation-material-title","conversation-material-source","conversation-material-text"]){const input=$("#"+id);if(input)input.value="";}
    $("#conversation-material-receipts").innerHTML=renderConversationMaterialReceipts(projectId);
  }
  await retryConversationMaterial(projectId,result.document.id);
  return result;
}

document.addEventListener("submit",async event=>{
  if(event.target.id!=="conversation-work-material")return;
  event.preventDefault();
  const form=event.target,projectId=conversation.id,button=form.querySelector("button"),status=$("#conversation-material-status");
  if(conversation.materialSaving===projectId)return;
  conversation.materialSaving=projectId;button.disabled=true;status.textContent="正在保存并加入研究…";
  try{
    await saveConversationWorkMaterial(form.elements.title.value,form.elements.text.value,form.elements.source_name.value);
    if(conversation.id===projectId){status.textContent="已加入。下方可以继续追问，保存未调用模型。";await openResearchConversation(projectId,false);}
  }catch(error){if(conversation.id===projectId)status.textContent=error.message;}
  finally{
    if(conversation.materialSaving===projectId)conversation.materialSaving=null;
    button.disabled=false;
    const current=conversation.id===projectId?$("#conversation-work-material button"):null;
    if(current)current.disabled=Boolean(conversation.project?.worker_running);
  }
});

async function retryConversationMaterial(projectId,id) {
  await attachConversationArchivedMaterial(projectId,id);
  const item=materialReceipts(projectId).find(row=>row.id===id);
  if(item)rememberConversationMaterial(projectId,item,true);
  if(conversation.id===projectId){
    $("#conversation-material-receipts").innerHTML=renderConversationMaterialReceipts(projectId);
    prefillMaterialFollowup(item?.title||"补充资料");
  }
}

document.addEventListener("click",async event=>{
  const button=event.target.closest("[data-attach-conversation-document]");if(!button)return;
  const projectId=conversation.id,id=button.dataset.attachConversationDocument;
  button.disabled=true;
  try{
    await retryConversationMaterial(projectId,id);
    if(conversation.id===projectId)await openResearchConversation(projectId,false);
  }catch(error){if(conversation.id===projectId)notify(error.message,true);}
  finally{button.disabled=false;}
});

async function archiveConversationDocument(url) {
  const targetProject=conversation.id;
  const result=await api("public-documents",{method:"POST",body:JSON.stringify({url})});
  const document=result.document;
  if(conversation.id!==targetProject)return result;
  rememberConversationMaterial(targetProject,document);
  const receipts=$("#conversation-material-receipts");if(receipts)receipts.innerHTML=renderConversationMaterialReceipts(targetProject);
  await attachConversationArchivedMaterial(targetProject,document.id);
  rememberConversationMaterial(targetProject,document,true);
  if(receipts)receipts.innerHTML=renderConversationMaterialReceipts(targetProject);
  $("#conversation-public-status").innerHTML=`<p>已归档：<strong>${e(document.title)}</strong> · ${e(document.full_text_length)}字符</p><button type="button" class="text-button" data-public-source="${e(document.id)}">核对已归档全文 ↗</button><p class="form-note">来源 ${e(document.publisher)}；发布时间未知。${result.truncated?"归档保留全文，后续检索按片段读取。":""}</p>`;
  if(!$("#conversation-question").value.trim())$("#conversation-question").value="结合刚归档的《"+document.title+"》与岗位原文，当前解释有哪些得到支持，哪些仍缺证据？请分别说明来源和推断边界。";
  return result;
}

let materialImporting=false;

function useSelectedMaterials() {
  $("#research-source-mode").value="public";
  updateResearchScope();updateResearchApproach();
}

async function importResearchFiles(fileList,projectId=null) {
  if(materialImporting)return;
  const files=Array.from(fileList||[]),status=$(projectId?"#conversation-file-status":"#research-file-status"),fileInput=$(projectId?"#conversation-material-files":"#research-material-files");
  const emptyFollowup=projectId&&conversation.id===projectId&&!$("#conversation-question")?.value.trim();
  if(!files.length)return;
  if(files.length>10){status.textContent="一次最多上传10份资料，请分批选择。";return;}
  materialImporting=true;fileInput.disabled=true;$("#start-research").disabled=true;
  if(projectId)conversation.materialSaving=projectId;
  const messages=[],saved=[],failed=[];
  try {
    for(const file of files) {
      status.textContent=`正在保存 ${saved.length+failed.length+1}/${files.length}：${file.name}`;
      try {
        const richDocument=/\.(docx|pdf)$/i.test(file.name);
        if(!/\.(txt|md|markdown|docx|pdf)$/i.test(file.name))throw new Error("支持TXT、Markdown、DOCX和PDF；旧版DOC请先另存为DOCX");
        if(file.size>(richDocument?8*1024*1024:400000))throw new Error(richDocument?"文件超过8MB，请只保留相关内容":"文件过大，请保留10万字以内的相关内容");
        if(!projectId&&selectedResearchDocuments.size>=20)throw new Error("本次已选满20份资料，请先移出不需要的资料");
        if(projectId&&conversation.project?.id===projectId&&conversation.project.worker_running)throw new Error("请等本轮调查结束后再加入资料");
        let text,notice="",sourceName="用户上传文件："+file.name.slice(0,300);
        if(richDocument){
          status.textContent=`正在本地提取正文：${file.name}`;
          const extracted=await api("imports/documents/extract?filename="+encodeURIComponent(file.name),{method:"POST",headers:{"Content-Type":"application/octet-stream"},body:file});
          text=extracted.text;notice=extracted.notice;sourceName=extracted.source_name;
        }else text=(await file.text()).replace(/^\uFEFF/,"");
        if(!text.trim())throw new Error("文件没有正文");
        if(text.length>100000)throw new Error("正文超过10万字，请拆分文件");
        const result=await api("work-materials",{method:"POST",body:JSON.stringify({title:file.name.slice(0,300),text,source_name:sourceName})});
        if(projectId){rememberConversationMaterial(projectId,result.document);await retryConversationMaterial(projectId,result.document.id);}
        else selectResearchDocument(result.document.id,result.document.title);
        saved.push(result.document);
        messages.push(`<p>✓ ${e(file.name)} · ${e(result.document.full_text_length)}字符 <button type="button" class="text-button" data-public-source="${e(result.document.id)}">查看导入正文 ↗</button>${notice?'<br>'+e(notice):""}</p>`);
      } catch(error) {failed.push(file.name);messages.push(`<p>${projectId?"未完成":"未保存"} ${e(file.name)}：${e(error.message)}</p>`);}
    }
    if(projectId){
      if(conversation.id===projectId){
        await openResearchConversation(projectId,false);
        if(saved.length&&emptyFollowup)$("#conversation-question").value=`结合刚补充的 ${saved.length} 份资料继续核对：哪些旧判断得到支持，哪些需要修订？请区分原文、推断和未知。`;
      }
      await loadResearchProjects();
    }else if(saved.length){useSelectedMaterials();await loadPublicLibrary();$("#question").focus();}
    const target=projectId&&conversation.id===projectId?$("#conversation-file-status"):status;
    target.innerHTML=`<strong>${projectId?"已加入本研究":"已保存并选入"} ${saved.length} 份${failed.length?`，${failed.length} 份未完成`:""}。</strong>${messages.join("")}<p>可继续添加资料，或在下方提问。保存不调用模型。</p>`;
    return {saved,failed};
  } finally {
    materialImporting=false;fileInput.disabled=false;fileInput.value="";
    if(projectId&&conversation.materialSaving===projectId)conversation.materialSaving=null;
    if(projectId&&conversation.id===projectId)$("#conversation-material-files").disabled=Boolean(conversation.project?.worker_running);
    $("#start-research").disabled=Boolean(state.activeRun||conversationStarting||conversation.project?.worker_running);
  }
}

$("#research-material-files").addEventListener("change",event=>importResearchFiles(event.target.files));
document.addEventListener("change",event=>{
  if(event.target.matches?.("[data-conversation-files]"))importResearchFiles(event.target.files,event.target.dataset.projectId).catch(error=>notify(error.message,true));
});
const materialDrop=$("#research-file-drop");
materialDrop.addEventListener("dragover",event=>{event.preventDefault();materialDrop.classList.add("dragging");});
materialDrop.addEventListener("dragleave",()=>materialDrop.classList.remove("dragging"));
materialDrop.addEventListener("drop",event=>{event.preventDefault();materialDrop.classList.remove("dragging");importResearchFiles(event.dataTransfer.files);});

async function saveWorkMaterial() {
  if(materialImporting)return null;
  const text=$("#work-material-text").value,source_name=$("#work-material-source").value.trim();
  const title=$("#work-material-title").value.trim()||text.split(/\r?\n/).find(line=>line.trim())?.trim().slice(0,300);
  if(!text.trim()){notify("请粘贴资料原文。",true);return null;}
  if(selectedResearchDocuments.size>=20){notify("本次已选满20份资料，请先移出不需要的资料。",true);return null;}
  const button=$("#save-work-material"),status=$("#work-material-status");
  materialImporting=true;button.disabled=true;status.textContent="正在保存原文…";
  try{
    const result=await api("work-materials",{method:"POST",body:JSON.stringify({title,text,source_name})});
    const selected=selectResearchDocument(result.document.id,result.document.title);
    if(selected){useSelectedMaterials();$("#work-material-title").value="";$("#work-material-text").value="";$("#work-material-source").value="";}
    status.innerHTML=`已保存《${e(result.document.title)}》 · ${e(result.document.full_text_length)}字符。<button type="button" class="text-button" data-public-source="${e(result.document.id)}">查看原文 ↗</button> ${selected?"已选入研究，可直接提问。":"当前已选满20份，请先调整研究范围。"} 保存未调用模型。`;
    await loadPublicLibrary();
    return selected?result:null;
  }catch(error){status.textContent=error.message;return null;}
  finally{button.disabled=false;materialImporting=false;}
}
$("#save-work-material").addEventListener("click",saveWorkMaterial);

async function archiveResearchDocument() {
  const input=$("#research-document-url"),url=input.value.trim();
  if(!url){notify("请先填写公开网页网址。",true);return;}
  const button=$("#archive-research-document"),status=$("#research-document-status");
  button.disabled=true;status.textContent="正在读取并归档正文，最多等待40秒…";
  try{
    const result=await api("public-documents",{method:"POST",body:JSON.stringify({url})});
    const selected=selectResearchDocument(result.document.id,result.document.title);
    status.innerHTML=`已归档《${e(result.document.title)}》 · ${e(result.document.full_text_length)}字符。<button type="button" class="text-button" data-public-source="${e(result.document.id)}">查看全文 ↗</button> ${selected?"已选入下次研究，可以继续提问。":"当前已选满20份，请先调整研究范围。"} 保存未调用模型。`;
    await loadPublicLibrary();
  }catch(error){status.textContent=error.message;}
  finally{button.disabled=false;}
}

$("#archive-research-document").addEventListener("click",archiveResearchDocument);
$("#research-source-mode").addEventListener("change",()=>{updateResearchScope();updateResearchApproach();});

async function loadPublicLibrary(offset=0) {
  const root=$("#public-library-list"),q=$("#public-library-query").value.trim();
  if(q!==state.publicLibraryQuery)offset=0;
  state.publicLibraryQuery=q;
  const request=state.publicLibraryRequest=(state.publicLibraryRequest||0)+1;
  root.innerHTML='<p class="form-note">正在查找本机归档…</p>';
  try{
    const data=await api("public-documents?"+new URLSearchParams({q,limit:10,offset}));
    if(request!==state.publicLibraryRequest)return;
    root.innerHTML=data.documents.length ? `<p class="form-note">共 ${e(data.total)} 份归档资料，显示 ${data.offset+1}–${data.offset+data.documents.length}；同一资料显示最新归档，旧版可在全文页查看。</p>${data.documents.map(doc=>`<article class="detail-history"><h4>${e(doc.title)} ${badge(doc.evidence_kind==="work_material"?"粘贴工作资料":"公开网页","muted")}</h4><p class="form-note">${e(doc.publisher)} · ${e(doc.full_text_length)}字符<br>归档于 ${e(when(doc.observed_at))} · 发布 ${doc.source_published_at?e(when(doc.source_published_at)):"时间未知"}</p>${doc.evidence_kind==="work_material"?'<p class="form-note">来源说明由导入者填写，未经独立核实。</p>':""}${doc.integrity!=="verified"?'<p class="form-note">归档文件缺失或内容已变化，须重新核对。</p>':""}<button type="button" class="text-button" data-public-source="${e(doc.id)}">查看全文 ↗</button><button type="button" class="text-button" data-select-research-document="${e(doc.id)}" data-document-title="${e(doc.title)}" ${doc.integrity!=="verified"?"disabled":""}>加入研究范围</button><button type="button" class="text-button" data-public-document-id="${e(doc.id)}" data-public-question="${e(doc.title)}" ${doc.integrity!=="verified"?"disabled":""}>围绕这份资料提问</button></article>`).join("")}<div class="result-actions">${data.offset>0?`<button type="button" class="secondary small" data-public-library-page="${Math.max(0,data.offset-data.limit)}">上一页</button>`:""}${data.offset+data.documents.length<data.total?`<button type="button" class="secondary small" data-public-library-page="${data.offset+data.limit}">下一页</button>`:""}</div>` : '<p class="form-note">没有找到对应的归档。可调整关键词，或在上方补充公开网页。</p>';
  }catch(error){if(request===state.publicLibraryRequest)root.innerHTML=errorBox(error);}
}

function preparePublicDocumentQuestion(title,id) {
  if(conversation.id)prepareNewResearch(false);
  const input=$("#question"),previous=state.publicQuestionPrefix;
  const draft=previous&&input.value.startsWith(previous)?input.value.slice(previous.length):input.value;
  const prefix="围绕归档文档《"+title+"》：\n";
  if((prefix+draft).length>4000){notify("现有问题已保留，请先精简内容后再加入文档标题。",true);return;}
  if(id){selectedResearchDocuments.clear();selectResearchDocument(id,title);}
  state.publicQuestionPrefix=prefix;
  $("#research-source-mode").value="public";
  updateResearchScope();updateResearchApproach();
  input.value=prefix+draft;
  input.focus();input.scrollIntoView({block:"center",behavior:"smooth"});
}

$("#public-library").addEventListener("toggle",event=>{if(event.target.open)loadPublicLibrary();});
$("#refresh-public-library").addEventListener("click",()=>loadPublicLibrary());
$("#public-library-query").addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();loadPublicLibrary();}});
document.addEventListener("click",event=>{
  const add=event.target.closest("[data-select-research-document]");
  if(add&&!add.disabled){selectResearchDocument(add.dataset.selectResearchDocument,add.dataset.documentTitle);return;}
  const remove=event.target.closest("[data-remove-research-document]");
  if(remove || event.target.closest("[data-clear-research-documents]")){
    if(remove)selectedResearchDocuments.delete(remove.dataset.removeResearchDocument);else selectedResearchDocuments.clear();
    sessionStorage.setItem("wo-document-selection",JSON.stringify([...selectedResearchDocuments].map(([id,title])=>({id,title}))));
    renderSelectedResearchDocuments();return;
  }
  const page=event.target.closest("[data-public-library-page]");
  if(page){loadPublicLibrary(Number(page.dataset.publicLibraryPage));return;}
  const question=event.target.closest("[data-public-question]");
  if(question&&!question.disabled)preparePublicDocumentQuestion(question.dataset.publicQuestion,question.dataset.publicDocumentId);
});

document.addEventListener("submit",async event=>{
  if(event.target.id!=="conversation-public-document")return;
  event.preventDefault();const button=event.target.querySelector("button"),status=$("#conversation-public-status");
  button.disabled=true;status.textContent="正在读取并归档公开正文，最多等待40秒…";
  try{await archiveConversationDocument(event.target.elements.url.value.trim());notify("公开正文已归档，可以在下方继续核实。");}
  catch(error){status.textContent=({PUBLIC_DOCUMENT_RECRUITMENT_PAUSED:"招聘来源仍暂停，不能通过网页入口访问。",PUBLIC_DOCUMENT_URL_DENIED:"请填写公开HTTPS网页，不能包含登录凭据或私有地址。",PUBLIC_DOCUMENT_TIMEOUT:"网页读取超时，未取得正文。",PUBLIC_DOCUMENT_TOO_LARGE:"网页超过归档大小上限，未取得正文。"})[error.code] || error.message;}
  finally{button.disabled=false;}
});

async function attachConversationMaterial(projectId, jobId) {
  const project=await api("projects/"+encodeURIComponent(projectId));
  if(project.worker_running)throw new Error("原文已保存。请先暂停当前调查，再将资料加入研究。");
  if(!project.job_ids.includes(jobId)) {
    if(project.job_ids.length>=20)throw new Error("原文已保存；本研究已达20份资料上限，可从岗位页选择范围开始新研究。");
    await api("projects/"+project.id,{method:"PATCH",body:JSON.stringify({revision:project.revision,goal:project.goal,job_ids:[...project.job_ids,jobId]})});
  }
}

document.addEventListener("click",async event=>{
  if(!event.target.closest("[data-conversation-import]"))return;
  showImport();state.importConversationId=conversation.id;
  $("#import-submit").textContent="保存并加入当前研究";
  $("#import-feedback").textContent="保存你实际取得的完整岗位原文；加入本研究后再继续追问，不会自动调用模型。";
});
async function saveResearchContext(kind,content) {
  const targetProject=conversation.id;
  content=content.trim();
  if(!["preference","correction"].includes(kind)||!content)throw new Error("请填写要保存的背景或纠正意见。");
  const target=kind==="correction"&&conversation.correctionTarget?.projectId===targetProject?conversation.correctionTarget:null;
  const text=target?`针对本研究旧判断的纠正意见（用户提出，须按原文核实）\n原问题：${target.question.slice(0,300)}\n原判断：${target.statement}\n\n我的纠正和理由：\n${content}`:content;
  if(text.length>4000)throw new Error("补充内容与原判断合计过长，请精简纠正理由后保存。");
  const project=await api("projects/"+encodeURIComponent(targetProject));
  if(conversation.id!==targetProject)throw new Error("研究已切换，尚未保存这段内容。");
  if(project.worker_running)throw new Error("请等当前调查结束后保存纠正或背景，输入仍保留。");
  if(project.state==="invalidated")throw new Error("这项研究已不可用，未保存补充内容。");
  if(target){
    const step=project.steps?.find(row=>row.id===target.stepId&&row.run_id===target.runId);
    if(step?.result?.claims?.[target.index]?.text!==target.statement)throw new Error("原判断已不可读取，请重新选择；当前输入保留。");
  }
  const saved=await api("memories",{method:"POST",body:JSON.stringify({kind,content:text,scope:"project",project_id:targetProject,origin:"user"})});
  conversation.notesFor=null;
  if(conversation.id!==targetProject)return {saved,questionPrepared:false,switched:true};
  if(target&&conversation.correctionTarget!==target)return {saved,questionPrepared:false,selectionChanged:true};
  const input=$("#conversation-context-content");
  if(input?.value.trim()===content){input.value="";if(conversation.correctionTarget===target)conversation.correctionTarget=null;}
  const question=$("#conversation-question");
  const prompt=target?`请针对我保存的纠正意见重新核对旧判断「${target.statement}」。重新查阅原文，说明这条判断应保留、修订、撤回还是仍未知，以及理由；我的纠正意见不是独立来源证据。`:`请结合我补充的信息继续核对：${content}`;
  const updated=question.value.includes(prompt)?question.value:question.value+(question.value.trim()?"\n\n":"")+prompt;
  const questionPrepared=updated.length<=4000;
  if(questionPrepared){question.value=updated;if(target)conversation.replyToStepId=target.stepId;}
  try{await openResearchConversation(targetProject,false);}
  catch{return {saved,questionPrepared,refreshFailed:true};}
  return {saved,questionPrepared};
}

document.addEventListener("submit",async event=>{
  if(event.target.id!=="conversation-context")return;
  event.preventDefault();const form=event.target,content=form.elements.content.value.trim();if(!content)return;
  const button=form.querySelector("button");button.disabled=true;
  try{
    const result=await saveResearchContext(form.elements.kind.value,content);
    notify(result.switched?"补充内容已保存到原研究，当前研究未被切换。":result.selectionChanged?"纠正意见已保存，你正在编辑的新内容保持。":result.refreshFailed?"补充内容已保存，页面暂未刷新；可稍后重新打开本研究。":result.questionPrepared?"已保存到这项研究，并保留原追问草稿；明确提交后才继续调查。":"补充内容已保存；原追问草稿较长，未覆盖。请精简后继续核对。");
  }catch(error){notify(error.message,true);}
  finally{button.disabled=false;}
});

let reportQuerySerial=0;
async function loadReports() {
  const serial=++reportQuerySerial;
  $("#report-detail").hidden = true;
  $("#reports-search").hidden = false;
  $("#reports-list").hidden = false;
  $("#reports-list").innerHTML = empty("正在读取已存研究…");
  const query=$("#reports-query").value.trim(),status=$("#reports-status").value;
  const params=new URLSearchParams();if(query)params.set("q",query);if(status)params.set("status",status);
  try {
    const reports = await api("reports"+(params.size?"?"+params:""));
    if(serial!==reportQuerySerial)return;
    $("#reports-count").textContent=reports.length===100?"展示最近100份匹配研究，可增加关键词缩小范围。":"找到 "+reports.length+" 份"+(query||status?"匹配的":"已存")+"研究";
    $("#reports-list").innerHTML = reports.length ? reports.map(report=>`<button class="panel report-row" data-report="${e(report.report_id)}"><div><h3>${e(report.question)}</h3><p>${e(when(report.created_at))} · 依据和范围已随结果保存</p>${report.match_excerpt?`<p class="report-match">匹配内容：${e(report.match_excerpt)}</p>`:""}</div>${badge(statusLabels[report.status] || report.status,report.status === "completed" ? "" : "muted")}<span>↗</span></button>`).join("") : query||status?empty("没有找到匹配的研究","试试更短的关键词，或清空条件查看全部研究。"):empty("还没有保存的研究","完成一次研究后，点击“保存这次研究”，就能在这里再次查看。");
  } catch (error) { if(serial===reportQuerySerial){$("#reports-list").innerHTML=errorBox(error);$("#reports-count").textContent="";} }
}

async function showReport(id) {
  ++reportQuerySerial;
  $("#reports-search").hidden = true;
  $("#reports-list").hidden = true;
  const root = $("#report-detail");
  root.hidden = false;
  root.innerHTML = `<div class="empty">正在读取研究…</div>`;
  try {
    const result = await api("reports/" + encodeURIComponent(id));
    root.innerHTML = `<button class="secondary back-button" data-report-back>← 返回已存研究</button><div id="saved-result"></div>`;
    renderResult(result,$("#saved-result"));
  } catch (error) { root.innerHTML = '<button class="secondary back-button" data-report-back>← 返回已存研究</button>'+errorBox(error); }
}
$("#reports-search").addEventListener("submit",event=>{event.preventDefault();loadReports();});
$("#reports-status").addEventListener("change",()=>loadReports());
$("#reports-clear").addEventListener("click",()=>{$("#reports-query").value="";$("#reports-status").value="";loadReports();});

function showImport(relatedId = null) {
  state.importConversationId=null;$("#import-submit").textContent="保存人工资料";
  $("#import-form").reset();
  state.importAsset=null;state.csvRows=[];
  $("#csv-preview").replaceChildren();$("#commit-csv").disabled=true;
  $("#csv-feedback").textContent="";$("#import-image-preview").replaceChildren();
  $("#image-import-file").value="";$("#image-synthetic").checked=false;
  $("#image-model-consent").checked=false;$("#extract-import-image").disabled=true;
  $("#image-review-line").hidden=true;$("#ocr-reviewed").disabled=true;$("#ocr-reviewed").required=false;
  $("#import-file").value = "";
  $("#import-feedback").textContent = "";
  $("#import-form").elements.related_job_id.value = relatedId || "";
  if (relatedId) $("#import-form details").open = true;
  openDialog("import-dialog");
}

async function importFile(event) {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (file.size > 512000) throw new Error("请选择小于 500 KB 的文本、JSON或CSV文件。");
    let text;
    try {text=new TextDecoder("utf-8",{fatal:true}).decode(await file.arrayBuffer()).replace(/^\uFEFF/,"");}
    catch {throw new Error("文件不是有效的UTF-8文本，请转换编码后重试。");}
    if (file.name.toLowerCase().endsWith(".csv")) {
      const preview=await api("imports/csv/preview",{method:"POST",body:JSON.stringify({csv_text:text})});
      state.csvRows=preview.rows;renderCSVPreview();$("#csv-import-panel").open=true;
      $("#import-feedback").textContent="CSV已逐行预览，请核对后使用批量导入按钮。";return;
    }
    state.importAsset=null;$("#import-form").elements.import_asset_id.value="";
    $("#image-review-line").hidden=true;$("#ocr-reviewed").disabled=true;$("#ocr-reviewed").required=false;$("#ocr-reviewed").checked=false;
    $("#import-image-preview").replaceChildren();$("#extract-import-image").disabled=true;
    if (file.name.toLowerCase().endsWith(".json")) {
      const data = JSON.parse(text);
      if (!data || Array.isArray(data) || typeof data !== "object") throw new Error("JSON 文件需要包含一个岗位对象。");
      if (Object.keys(data).some(key=>!$("#import-form").elements.namedItem(key))) throw new Error("文件包含页面不支持的字段，请核对 JSON 格式；没有导入任何内容。");
      if (Object.entries(data).some(([key,value])=>value !== null && typeof value !== "string" && !(key === "ocr_reviewed" && typeof value === "boolean"))) throw new Error("JSON 中的原文字段需要是文本，未知字段可留空；截图核对字段使用布尔值。");
      if (data.ocr_reviewed && !data.import_asset_id) throw new Error("没有归档原图关联时，不能声明已核对OCR资料。");
      $("#import-form").reset();
      for (const [key,value] of Object.entries(data)) {
        const field = $("#import-form").elements.namedItem(key);
        if (field && typeof value === "string") field.value = value;
        else if (field && key === "ocr_reviewed" && typeof value === "boolean") field.checked=value;
      }
      if (data.import_asset_id) {
        const id=String(data.import_asset_id);
        state.importAsset={id,data_kind:data.data_kind || "user_provided",image_url:"/api/import-assets/"+encodeURIComponent(id)+"/image"};
        $("#import-image-preview").innerHTML=`<img class="import-image" src="${e(state.importAsset.image_url)}" alt="JSON所关联的本机归档原图，请重新核对">`;
        $("#image-import-panel").open=true;$("#image-review-line").hidden=false;$("#ocr-reviewed").disabled=false;$("#ocr-reviewed").required=true;$("#ocr-reviewed").checked=false;
        $("#extract-import-image").disabled=false;
      }
      $("#import-feedback").textContent = "文件已填入表单，请核对后保存；截图关联需重新对照原图并勾选核对。";
    } else {
      $("#import-form").elements.description.value = text;
      $("#import-feedback").textContent = "正文已读取，请填写岗位与公司名称后保存。";
    }
  } catch (error) { $("#import-feedback").textContent = error.message; }
}

async function importSubmit(event) {
  event.preventDefault();
  const values = Object.fromEntries([...new FormData(event.target)].filter(([,value])=>String(value).trim() !== ""));
  $("#import-submit").disabled = true;
  $("#import-feedback").textContent = "正在保存人工资料…";
  try {
    const result = await api("import",{method:"POST",body:JSON.stringify(values)});
    if(state.importConversationId){
      const targetProject=state.importConversationId;
      await attachConversationMaterial(targetProject,result.job_id);
      $("#import-dialog").close();state.importConversationId=null;
      await loadOverview();await loadJobs();await openResearchConversation(targetProject);
      $("#conversation-question").value="结合刚补充的岗位原文，哪些旧判断需要重新检查？请说明新资料支持什么、仍不能说明什么。";
      notify("原文已加入本研究。可以继续追问，旧回答与原文仍保留。");return;
    }
    $("#import-dialog").close();
    notify(result.stats.jobs_new ? "人工资料已保存，原有来源资料保持不变。" : result.stats.snapshots_new ? "新正文已保存为内容版本。" : "内容已存在，已保留本次导入记录，没有新增重复岗位。 ");
    await loadOverview();
    await loadJobs();
    showJob(result.job_id);
  } catch (error) { $("#import-feedback").textContent = error.message; }
  finally { $("#import-submit").disabled = false; }
}

async function showProfile(id) {
  $("#profile-content").innerHTML = `<div class="empty">正在读取岗位画像…</div>`;
  openDialog("profile-dialog");
  try { renderProfile(await api("profiles/"+encodeURIComponent(id)),id); }
  catch (error) {$("#profile-content").innerHTML=errorBox(error);}
}

function renderProfile(profile,id) {
  const result = profile.result;
  $("#profile-content").innerHTML = `<div class="detail-head"><h2>看清任务、能力与交付物</h2></div><p class="form-note">画像是对已存原文的分析，保留版本、人工纠正与引用。未知信息继续留空。</p>${profile.stale ? `<div class="error-box">此画像采用的原文或纠正已变化，请重新生成。${(profile.stale_reasons || []).map(item=>e(item)).join("；")}</div>` : ""}<div class="detail-actions"><button class="primary" data-analyze-profile="${e(id)}">${result ? "重新核对画像" : "生成工作画像"} ↗</button><button class="secondary" data-analyze-profile="${e(id)}" data-offline="true">仅整理原文</button></div>${profile.cached ? `<p class="form-note">已读取保存的画像，无需再次调用模型。</p>` : ""}<div id="profile-result"></div>`;
  if (!result) {$("#profile-result").innerHTML=empty("这份岗位还没有工作画像","可生成有引用的分析，或先整理原文。");return;}
  if (result.scope) renderResult(result,$("#profile-result"));
  else $("#profile-result").innerHTML=`<p class="form-note">${e(statusLabels[profile.status] || "画像已读取")}</p>`;
  const root=$("#profile-result");
  if(profile.id)root.insertAdjacentHTML("beforeend",`<p><button class="secondary" data-profile-quality-open="${e(profile.id)}">核对完整画像、领域与核实问题 ↗</button></p>`);
  root.insertAdjacentHTML("beforeend",`<details class="research-context"><summary>纠正这个岗位的领域归类</summary><form data-domain-form="${e(id)}"><div class="domain-options">${(profile.classification_options||[]).map(row=>`<label class="checkbox-line"><input type="checkbox" name="domain" value="${e(row.id)}">${e(row.name)} · 第${e(row.version)}版</label>`).join("")||'<p class="form-note">当前没有可用的已采纳工作类型，可到<a href="#knowledge">领域与证据</a>建立或核对定义。</p>'}</div><label>纠正理由<textarea name="reason" required maxlength="1200" rows="3" placeholder="说明原文为何支持这项纠正。仅影响这个岗位。"></textarea></label><p class="form-note">可不选任何领域以撤销已有归类。人工纠正会保留版本，并优先用于后续画像。</p><button class="secondary" type="submit">保存本岗位领域纠正</button><p class="form-note" data-domain-feedback></p></form></details>`);
  const domains=result.effective_domains || result.domains || [];
  const questions=result.interview_questions || [];
  const definitions=result.classification_definitions||[];
  root.insertAdjacentHTML("beforeend",definitions.length?`<details class="research-context"><summary>本次采用的工作类型定义与边界</summary>${definitions.map(row=>`<h4>${e(row.name)} · 第${row.version}版</h4><p>${e(row.definition)}</p><p class="form-note">包括：${e(row.inclusion||"未细分")}；排除或未知：${e(row.exclusion||"未细分")}</p>`).join("")}</details>`:'<p class="form-note">本次未采用可用的工作类型定义；未分类不表示岗位没有相关工作。历史标签保留在原画像中。</p>');
  const corrections=result.corrections || [];
  root.insertAdjacentHTML("beforeend",`${domains.length ? `<section class="research-context"><h3>工作类型归类</h3><p class="form-note">模型候选不等于已采纳分类；旧画像的历史标签不代表当前工作类型定义。</p>${domains.map(item=>`<p>${e(typeof item === "string" ? item : item.label || domainLabels[item.domain] || item.name || "待核实领域")}${item.rationale ? "："+e(item.rationale) : item.reason ? "："+e(item.reason) : ""}${item.definition_version?" · 第"+e(item.definition_version)+"版":""}${item.status === "user_corrected" ? "（人工纠正）" : ""}</p>`).join("")}</section>` : ""}${questions.length ? `<section class="research-context"><h3>适合继续核实的问题</h3><ul>${questions.map(item=>`<li>${e(typeof item === "string" ? item : item.question || "核对职责范围")}</li>`).join("")}</ul></section>` : ""}${corrections.length ? `<section class="research-context"><h3>本岗位的有效人工纠正</h3>${corrections.map(item=>`<p>${e(memoryText(item))}</p>`).join("")}</section>` : ""}`);
}

async function analyzeProfile(id,offline) {
  const root=$("#profile-content");
  $$("[data-analyze-profile]",root).forEach(button=>button.disabled=true);
  const status=document.createElement("p");status.className="form-note";status.textContent=offline ? "正在整理已存原文…" : "正在查阅原文、分析任务与能力，请稍候…";root.append(status);
  try {renderProfile(await api("profiles/"+encodeURIComponent(id),{method:"POST",body:JSON.stringify({offline})}),id);}
  catch (error) {status.textContent=error.message;$$("[data-analyze-profile]",root).forEach(button=>button.disabled=false);}
}

function matchPreferences() {
  const form=$("#match-form").elements;
  const split=value=>value.split(/[,，、;；]+/).map(item=>item.trim()).filter(Boolean);
  const preferences={cities:split(form.cities.value),employment_types:form.employment_type.value ? [form.employment_type.value] : [],desired_tasks:split(form.desired_tasks.value),salary_unit:form.salary_unit.value};
  if (form.salary_min.value !== "") preferences.salary_min=form.salary_min.value;
  if (form.salary_max.value !== "") preferences.salary_max=form.salary_max.value;
  return preferences;
}

async function runMatch(event) {
  event.preventDefault();
  const preferences=matchPreferences();
  $("#match-submit").disabled=true;
  $("#match-results").innerHTML=empty("正在按明确条件核对岗位…");
  try {
    const result=await api("matches",{method:"POST",body:JSON.stringify({filters:state.filters,preferences})});
    const counts=result.counts;
    $("#match-results").innerHTML=`<div class="scope-summary"><strong>${e(counts.matched)} 个符合 · ${e(counts.unknown)} 个待核实 · ${e(counts.excluded)} 个不符</strong></div><p class="form-note">${e(result.rules || "条件未知单列，薪资只比较相同周期。")}</p>`+(result.jobs.length ? result.jobs.map(row=>{const job=row.job || row;return `<article class="panel match-card"><div class="section-heading"><button class="job-link" data-job="${e(job.id)}">${e(job.title)} · ${e(job.company || job.company_name_raw || "")}</button>${badge(({matched:"符合明确条件",unknown:"信息待核实",excluded:"存在不符条件"})[row.match_status] || row.match_status,row.match_status === "unknown" ? "amber" : row.match_status === "excluded" ? "muted" : "")}</div><div class="detail-time">${e(job.salary || job.salary_raw || "薪资未知")} · ${e(job.city || "城市未知")}</div><ul class="match-reasons">${(row.reasons || []).map(reason=>`<li>${badge(({matched:"符合",unknown:"未知",excluded:"不符"})[reason.status] || reason.status,reason.status === "unknown" ? "amber" : "muted")} ${e(reason.detail || reason.condition)}</li>`).join("")}</ul><button class="text-button" data-profile="${e(job.id)}">核对岗位画像 ↗</button></article>`;}).join("") : empty("当前范围没有岗位","可返回岗位资料调整筛选条件。"));
  } catch (error) {$("#match-results").innerHTML=errorBox(error);}
  finally {$("#match-submit").disabled=false;}
}

async function loadMatchPreferences() {
  try {
    const saved=await api("preferences");
    const p=saved.preferences || {};
    const form=$("#match-form").elements;
    form.cities.value=(p.cities || []).join("、");
    form.employment_type.value=(p.employment_types || [])[0] || "";
    form.salary_min.value=p.salary_min ?? "";
    form.salary_max.value=p.salary_max ?? "";
    form.salary_unit.value=p.salary_unit || "month";
    form.desired_tasks.value=(p.desired_tasks || []).join("、");
    $("#match-preferences-status").textContent=saved.version ? `已载入第 ${saved.version} 版个人条件` : "尚未保存个人条件";
  } catch (error) {notify(error.message,true);}
}

async function saveMatchPreferences() {
  const button=$("#save-match-preferences");button.disabled=true;
  try {
    const saved=await api("preferences",{method:"POST",body:JSON.stringify(matchPreferences())});
    $("#match-preferences-status").textContent=`已保存第 ${saved.version} 版个人条件`;
    notify("个人条件已保存，下次匹配可继续使用；旧版停止默认召回。");
  } catch (error) {notify(error.message,true);}
  finally {button.disabled=false;}
}

const memoryKindLabels = {preference:"个人偏好",correction:"人工纠正",knowledge:"研究知识",hypothesis:"待验证解释",method:"研究方法经验"};
const memoryStatusLabels = {active:"已启用",candidate:"待核对采纳",conflict:"存在冲突，暂停召回",superseded:"已被新版替代",withdrawn:"已撤回",expired:"已过期",forgotten:"已忘记"};
const memoryValidityLabels = {outside_effective_time:"尚未生效或已过有效期",derived_dependency_stale:"上游研究采用的偏好、纠正或知识已变化",source_changed:"依据正文已变化",source_missing_or_invalid:"原文缺失或完整性异常"};

function renderMemoryRevisionNotices(notices) {
  const labels = {retain:"后续重新保留（仍待核对）",revise:"提出修订",withdraw:"建议撤回",unresolved:"尚未解决"};
  return (notices || []).map(item=>`<div class="research-context">${badge(item.scope_limited?"后续研究需补充资料核对":"后续研究 · " + (labels[item.decision] || "待核对"),"amber")}${item.previous_statement?`<p><strong>涉及原判断 ${e(item.previous_claim_index+1)}：</strong>${e(item.previous_statement)}</p>`:""}<p>${e(item.reason)}</p>${item.memory_match_note?`<p class="form-note">${e(item.memory_match_note)}</p>`:""}${item.decision==="retain"&&item.notice?`<p class="form-note">${e(item.notice)}</p>`:""}${item.recorded_at?`<p class="form-note">记录于 ${e(when(item.recorded_at))}</p>`:""}${renderRevisionAspects(item)}${(item.new_statements || []).map(text=>`<p>${e(text)}</p>`).join("")}<p class="form-note">后续判断待核对，已保存内容保留。请结合原文决定是否修订或撤回。</p><button class="text-button" data-open-run="${e(item.run_id)}">核对后续研究及原文 ↗</button></div>`).join("");
}

function renderRetrievedKnowledge(result,evidenceCard) {
  const records=result.knowledge||[],omitted=result.knowledge_omissions||[];
  return (records.length?'<h3>相关已采纳认识（派生，仍须核对原文）</h3>'+records.map(row=>`<article class="panel"><p>${e(row.content)}</p>${renderMemoryRevisionNotices(row.revision_notices)}<details><summary>核对原始依据</summary>${(row.evidence||[]).map(item=>evidenceCard(item,0,false)).join("")}</details></article>`).join(""):"")
    +(omitted.length?`<p class="research-context">本次召回中另有 ${omitted.length} 条认识因展示长度限制未展开${omitted.some(row=>row.has_revision_notices)?`，其中 ${omitted.filter(row=>row.has_revision_notices).length} 条含后续修正提醒`:""}。<a href="#memory">查看已保存知识和完整修正记录 ↗</a></p>`:"")
    +renderRetrievedDomainKnowledge(result.domain_knowledge);
}

function renderDomainSourceContexts(contexts) {
  if(!contexts?.length)return "";
  return `<p class="form-note">沿用合并或拆分前定义的来源；不表示原文直接支持当前全部表述，仍须核对。</p>${contexts.map(context=>`<p class="form-note">${e(context.scope_note||"")}</p>${context.run_id?`<button class="text-button" data-open-run="${e(context.run_id)}">核对沿用的来源研究及原文 ↗</button>`:""}`).join("")}`;
}

function renderRetrievedDomainKnowledge(data) {
  if(!data||(!data.domains?.length&&!data.relations?.length&&!data.omissions?.length&&!data.truncated))return "";
  const locate=(kind,id,label)=>`<button class="text-button" data-knowledge-locate="${e(id)}" data-knowledge-kind="${kind}">${label} ↗</button>`;
  const support=(run,indices)=>{
    const packet=(data.supporting_findings||[]).find(row=>row.run_id===run);
    return packet?renderKnowledgeSupport(packet.claims.filter(row=>(indices||[]).includes(row.claim_index)))+(packet.omitted_claims?'<p class="form-note">原研究另有未展开的判断，请打开来源研究完整核对。</p>':""):"";
  };
  const scope=context=>`<p class="form-note">${context?.job_ids?.length||context?.public_document_ids?.length?`来源范围：${context.job_ids?.length||0} 个岗位、${context.public_document_ids?.length||0} 份归档；不能外推到本次全部候选。`:"未绑定具体来源范围，适用边界以保存的定义文字为准。"}</p>`;
  return `<section class="detail-section"><h3>相关领域定义与工作关系</h3><p class="form-note">这些是已保存的派生认识，不计作新的原文来源或岗位样本；“需要”关系不自动等于招聘必备资格。</p>${(data.domains||[]).map(row=>`<article class="panel"><h4>${e(row.name)} · 第 ${row.version} 版</h4><p>${e(row.definition)}</p><dl>${detailData("包括",row.inclusion)}${detailData("边界与未知",row.exclusion)}</dl>${renderDomainSourceContexts(row.source_contexts)}${(row.source_contexts||[row.source_context||{}]).map(context=>`${scope(context)}${support(context.run_id,context.claim_indices)}${context.run_id?`<button class="text-button" data-open-run="${e(context.run_id)}">核对来源研究及原文 ↗</button>`:""}`).join("")}${renderMemoryRevisionNotices(row.revision_notices)}${locate("domains",row.id,"查看保存的定义")}</article>`).join("")}${(data.relations||[]).map(row=>{
    const map=row.scope?.research_map||{};
    return `<article class="panel"><h4>${e(row.domain_name||"已保存的工作关系")}</h4><p>${e(row.source_text)} → ${e(workPredicateLabels[row.predicate]||row.predicate)} → ${e(row.target_text)}</p>${map.rationale?`<p>${e(map.rationale)}</p>`:""}${map.transfer_limit?`<p><strong>适用与迁移边界：</strong>${e(map.transfer_limit)}</p>`:""}${scope(row.scope)}${renderMemoryRevisionNotices(row.revision_notices)}${support(row.source_run_id,map.claim_indices)}${row.source_run_id?`<button class="text-button" data-open-run="${e(row.source_run_id)}">核对来源研究及原文 ↗</button>`:""}${locate("relations",row.id,"查看保存的关系与反例")}</article>`;
  }).join("")}${(data.omissions||[]).map(row=>`<p class="form-note">因展示长度限制未展开：${row.kind==="research"?`<button class="text-button" data-open-run="${e(row.id)}">查看原研究及完整判断 ↗</button>`:locate(row.kind,row.id,row.kind==="domains"?"查看完整定义":"查看完整工作关系")}</p>`).join("")}${data.truncated?'<p class="form-note">当前仅展示部分相关认识，未展示不表示不存在；已保存记录保持完整。</p>':""}</section>`;
}

function renderMemory(item) {
  const validityReasons = (item.validity?.reasons || []).filter(reason=>memoryValidityLabels[reason]);
  const scope = item.scope === "project" ? "仅适用研究项目：" + item.project_id : item.job_id ? "仅适用岗位：" + item.job_id : "在相关研究中参考";
  const editable = ["active","candidate"].includes(item.status);
  const actions = editable ? `${item.status === "candidate" ? `<button class="primary small" data-memory-action="activate" data-memory-id="${e(item.id)}">核对后采纳</button>` : ""}${applicationProfile({...item,status:"active"},item.project_id) ? `<a class="secondary small" href="#research/${e(item.project_id)}">修改应用背景</a>` : item.content.startsWith("结构化个人条件：") ? `<a class="secondary small" href="#matches">修改个人条件</a>` : item.content.startsWith("画像领域纠正：") && item.job_id ? `<button class="secondary small" data-profile="${e(item.job_id)}">核对领域纠正</button>` : `<button class="secondary small" data-memory-edit="${e(item.id)}">修订</button>`}<button class="text-button" data-memory-action="withdraw" data-memory-id="${e(item.id)}">撤回并停止使用</button>` : item.status === "conflict" ? `<button class="primary small" data-memory-action="accept" data-memory-id="${e(item.id)}">选择此项，否决冲突值</button><button class="secondary small" data-memory-action="reject" data-memory-id="${e(item.id)}">否决此项</button>` : "";
  return `<article class="panel memory-card"><div class="result-top">${badge(memoryKindLabels[item.kind] || "记录","muted")}${badge(memoryStatusLabels[item.status] || item.status,["candidate","conflict"].includes(item.status) ? "amber" : "")}<small>第 ${e(item.version || 1)} 版</small></div><p class="body-text">${e(memoryText(item))}</p><p class="form-note">${e(scope)}${item.subject ? " · 主体：" + e(item.subject) : ""} · ${item.origin === "agent" ? "模型提出，经采纳后才可参考" : "用户明确输入"}<br>有效期：${item.valid_from ? e(when(item.valid_from)) : "未设起点"} 至 ${item.valid_until ? e(when(item.valid_until)) : "未设终点"}</p>${validityReasons.length ? `<p class="error-box">当前停止召回：${validityReasons.map(reason=>e(memoryValidityLabels[reason])).join("；")}。历史记录保留，需核对后建立新版本。</p>` : ""}${renderMemoryRevisionNotices(item.validity?.revision_notices)}${["hypothesis","method"].includes(item.kind) ? `<p class="form-note">这是${item.kind === "hypothesis" ? "待验证解释" : "研究经验"}，不能作为已核验事实或独立原文依据。</p>` : ""}${item.status === "conflict" ? `<p class="form-note">同一主体存在不同记录；当前不采用这些冲突值。明确选择后才恢复召回。</p>` : ""}${item.source_run_id ? `<button class="text-button" data-open-run="${e(item.source_run_id)}">核对来源研究 ↗</button>` : ""}${item.evidence?.length ? `<details class="research-context"><summary>原始依据 · ${item.evidence.length} 个片段</summary>${item.evidence.map(ev=>`<blockquote>${e(ev.quote || "")}</blockquote>${ev.document_id ? `<button class="text-button" data-source="${e(ev.document_id)}">核对原始文档 ↗</button>` : ""}${ev.public_document_id ? `<button class="text-button" data-public-source="${e(ev.public_document_id)}">核对归档全文 ↗</button>` : ""}`).join("")}</details>` : ""}<div class="result-actions">${actions}${["preference","correction"].includes(item.kind) && item.status !== "forgotten" ? `<button class="text-button" data-forget-memory="${e(item.id)}">忘记并清除相关结果</button>` : ""}</div></article>`;
}

async function loadMemories() {
  conversation.notesFor=null;
  const root = $("#memory-list");
  try {
    const items = await api("memories" + ($("#memory-history").checked ? "?history=1" : ""));
    state.memories = new Map(items.map(item=>[item.id,item]));
    root.innerHTML = items.length ? items.map(renderMemory).join("") : empty("还没有保存的知识或偏好","可以添加明确偏好、纠正、假设与方法，或从研究结论中留下知识候选。");
  } catch (error) {root.innerHTML = errorBox(error);}
}

function showMemory(id = null) {
  const form = $("#memory-form");
  form.reset();
  const item = id ? state.memories.get(id) : null;
  form.elements.id.value = id || "";
  form.elements.content.value = item?.content || "";
  form.elements.job_id.value = item?.job_id || "";
  form.elements.project_id.value = item?.project_id || "";
  form.elements.scope.value = item?.scope || "global";
  form.elements.subject.value = item?.subject || "";
  form.elements.valid_from.value = item?.valid_from ? new Date(new Date(item.valid_from).getTime()+8*3600000).toISOString().slice(0,16) : "";
  form.elements.valid_until.value = item?.valid_until ? new Date(new Date(item.valid_until).getTime()+8*3600000).toISOString().slice(0,16) : "";
  for (const field of ["job_id","project_id","scope","subject","valid_from","valid_until"]) form.elements[field].disabled = !!id;
  form.elements.kind.disabled = !!id;
  if (item) form.elements.kind.value = item.kind;
  $("#memory-dialog-title").textContent = id ? "修订记录，保留旧版本" : "添加明确记录";
  $("#memory-feedback").textContent = "";
  openDialog("memory-dialog");
}

async function saveMemory(event) {
  event.preventDefault();
  const form = event.target;
  const id = form.elements.id.value;
  const content = form.elements.content.value.trim();
  if (!content) return;
  $("#memory-submit").disabled = true;
  try {
    const scope=form.elements.scope.value;
    const input={content,kind:form.elements.kind.value,scope,origin:"user",subject:form.elements.subject.value.trim() || null,job_id:scope === "job" ? form.elements.job_id.value.trim() || null : null,project_id:scope === "project" ? form.elements.project_id.value.trim() || null : null,valid_from:form.elements.valid_from.value ? new Date(form.elements.valid_from.value+"+08:00").toISOString() : null,valid_until:form.elements.valid_until.value ? new Date(form.elements.valid_until.value+"+08:00").toISOString() : null};
    const saved=await api(id ? "memories/"+encodeURIComponent(id)+"/revise" : "memories", {method:"POST",body:JSON.stringify(id ? {content} : input)});
    $("#memory-dialog").close();
    await loadMemories();
    notify(saved.status === "conflict" ? "同一主体存在不同值，双方暂停召回，请明确选择。" : saved.status === "candidate" ? "已保存为待核对候选，采纳前不参与研究。" : id ? "新版本已保存，旧版停止默认使用。" : "记录已保存，后续研究会按范围参考。");
  } catch (error) {$("#memory-feedback").textContent = error.message;}
  finally {$("#memory-submit").disabled = false;}
}

async function searchRetrieval(event) {
  event.preventDefault();
  const form=event.target.elements;
  const terms=form.terms.value.split(/[,，、;；]+/).map(item=>item.trim()).filter(Boolean);
  const asOf=form.as_of.value ? new Date(form.as_of.value+"+08:00").toISOString() : null;
  $("#retrieval-submit").disabled=true;
  try {
    const data=await api("retrieval",{method:"POST",body:JSON.stringify({terms,filters:state.filters,as_of:asOf,aliases:form.aliases.checked})});
    const result=data.retrieval,statistics=data.statistics;
    $("#retrieval-results").innerHTML=`<article class="panel result-card"><h2>原文检索与样本口径</h2><p class="form-note">实际检索词：${result.expanded_terms.map(e).join("、")}<br>${e(result.sample.denominator_rule)}<br>${e(result.sample.time_rule)}</p><div class="scope-summary">明确符合 ${result.sample.matched} 个 · 条件未知 ${result.sample.unknown} 个 · 有正文分母 ${result.sample.denominator} 个 · 命中 ${result.matching_jobs} 个岗位</div><p class="form-note">${e(statistics.interpretation)}</p><div class="table-scroll"><table class="stats-table"><thead><tr><th>字面词</th><th>出现岗位 / 有正文分母</th><th>字面比例</th><th>条件未知中出现</th></tr></thead><tbody>${statistics.statistics.map(row=>`<tr><td>${e(row.term)}</td><td>${row.literal_jobs} / ${row.denominator}</td><td>${row.ratio === null ? "未知" : (row.ratio*100).toFixed(1)+"%"}</td><td>${row.unknown_scope_literal_jobs}</td></tr>`).join("")}</tbody></table></div><h3 class="retrieval-evidence-heading">原文证据 · ${result.evidence.length} 个片段</h3>${result.evidence.map((ev,index)=>`<details class="evidence-item"><summary>E${index+1} · ${e(ev.title)} · ${e(ev.company)} ${badge(ev.retrieval?.match_status === "unknown" ? "范围条件未知" : "范围明确",ev.retrieval?.match_status === "unknown" ? "amber" : "muted")}</summary><blockquote>${e(ev.quote)}</blockquote><div class="evidence-meta">${e(sourceLabel(ev))} · 取得 ${e(when(ev.observed_at))} · 字符 ${ev.start}–${ev.end}<br>命中：${(ev.retrieval?.matched_terms || []).map(e).join("、") || "来源标签"}<br><button data-source="${e(ev.document_id)}">核对来源文档与版本 ↗</button></div></details>`).join("") || `<p class="form-note">没有可引用的正文命中。换用其他表述或补充资料，不能据此判断市场无需求。</p>`}<p class="form-note">上下文 ${result.context_characters} / ${result.context_limit} 字符${result.truncated ? "，已按预算截取。统计仍来自完整范围。" : "。"}</p></article>`;
  } catch (error) {$("#retrieval-results").innerHTML=errorBox(error);}
  finally {$("#retrieval-submit").disabled=false;}
}

const strategyStatuses={candidate:"候选",active:"正在使用",superseded:"已被替代",rolled_back:"已回退",rejected:"已拒绝"};
const experimentStatuses={accepted:"通过固定门槛",rejected:"未通过，保持现策略",insufficient:"证据不足，保持现策略"};
async function loadStrategies() {
  try {
    const data=await api("strategies");
    if (!$("#strategy-form").elements.aliases.value) $("#strategy-form").elements.aliases.value=Object.entries(data.template).map(([term,aliases])=>term+"="+aliases.join("、")).join("\n");
    $("#strategy-list").innerHTML=data.strategies.length ? data.strategies.map(item=>{const evaluation=data.experiments.find(run=>run.strategy_id === item.id);return `<article class="panel strategy-card"><div class="section-heading"><h3>${e(item.name)}</h3>${badge(strategyStatuses[item.status] || item.status,item.status === "active" ? "" : "muted")}</div><p class="form-note">${Object.entries(item.config.aliases).map(([term,aliases])=>e(term)+" → "+aliases.map(e).join("、")).join("；") || "纯字面检索，无别名扩展。"}</p><div class="result-actions">${item.status === "candidate" ? `<button class="secondary small" data-strategy-action="evaluate" data-strategy-id="${e(item.id)}">运行完整固定评测</button>` : ""}${item.status === "candidate" && evaluation?.status === "accepted" ? `<button class="primary small" data-strategy-action="activate" data-strategy-id="${e(item.id)}">显式启用本地别名</button>` : ""}${evaluation ? badge(experimentStatuses[evaluation.status] || evaluation.status,evaluation.status === "accepted" ? "" : "amber") : ""}</div></article>`;}).join("") : empty("当前使用内置字面基线","可提出别名候选，验证它能否在固定预算内找到相同任务的不同表述。");
    $("#strategy-evaluations").innerHTML=data.experiments.length ? `<details class="research-context" open><summary>固定评测结果 · 模拟资料</summary>${data.experiments.slice(0,8).map(run=>`<section class="evaluation-result"><h3>${e(experimentStatuses[run.status] || run.status)} · ${e(when(run.created_at))}</h3><p>${e(run.metrics.reason)}<br>前 K 条已知支持命中率：基线 ${(run.metrics.baseline_recall*100).toFixed(1)}% → 候选 ${(run.metrics.candidate_recall*100).toFixed(1)}%；${run.metrics.case_count} 个固定问题；外部调用 ${run.metrics.external_calls} 次。</p><div class="table-scroll"><table class="stats-table"><thead><tr><th>问题</th><th>基线命中</th><th>候选命中</th><th>关键回归</th></tr></thead><tbody>${run.metrics.cases.map(row=>`<tr><td>${e(row.case_id)}</td><td>${row.baseline_recall ? "是" : "否"}</td><td>${row.candidate_recall ? "是" : "否"}</td><td>${row.regression ? "失败" : "无"}</td></tr>`).join("")}</tbody></table></div><p>原文版本护栏：${run.metrics.source_version_guard ? "通过" : "失败"}；预算护栏：${run.metrics.budget_guard ? "通过" : "失败"}。本次只验证模拟资料上的检索机制。</p></section>`).join("")}</details>` : "";
  } catch (error) {$("#strategy-list").innerHTML=errorBox(error);}
}

async function createStrategy(event) {
  event.preventDefault();
  const form=event.target.elements,aliases={};
  try {
    for (const line of form.aliases.value.split(/\r?\n/).map(item=>item.trim()).filter(Boolean)) {
      const match=line.match(/^([^=＝]+)[=＝](.*)$/);
      if (!match) throw new Error("请按每行“词=别名、别名”填写。");
      const key=match[1].trim();
      if (Object.hasOwn(aliases,key)) throw new Error("同一个词请合并为一行。");
      Object.defineProperty(aliases,key,{value:match[2].split(/[,，、;；]+/).map(item=>item.trim()).filter(Boolean),enumerable:true});
    }
    await api("strategies",{method:"POST",body:JSON.stringify({name:form.name.value.trim(),aliases})});
    notify("候选已保存，请运行完整固定评测。");
    await loadStrategies();
  } catch (error) {notify(error.message,true);}
}

async function rollbackStrategy(event) {
  event.preventDefault();
  try {
    await api("strategies/rollback",{method:"POST",body:JSON.stringify({reason:event.target.elements.reason.value.trim()})});
    notify("已回到上一稳定检索策略，并保留回退原因。");
    await loadStrategies();
  } catch (error) {notify(error.message,true);}
}

const taskStateLabels={queued:"等待执行",running:"执行中",completed:"已完成",success:"已完成",partial:"部分完成",failed:"失败",blocked:"来源暂停，未请求",interrupted:"执行中断",needs_auth:"需要来源认证"};
async function loadOperations() {
  try {
    if (!state.overview) await loadOverview();
    const data=await api("operations");state.operations=data;
    const sourceReady=state.overview?.source?.state === "no_local_pause";
    $("#operations-source-note").textContent=state.overview?.source?.state === "paused" ? "招聘来源仍处于本地暂停。可以查看资料、保存计划与研究问题；来源执行和启用时段入口保持停用。" : "当前只读取本地来源状态；未发现暂停不代表联网可用。没有在此恢复认证或变更权限。";
    $("#schedule-enabled").disabled=!sourceReady;
    const watchsetNames=new Map(data.watchsets.map(item=>[item.id,item.name+" · 第 "+item.version+" 版"]));
    const boss=data.watchsets.filter(item=>item.config.source === "boss");
    $("#schedule-watchset").innerHTML=boss.map(item=>`<option value="${e(item.id)}">${e(item.name)} · 第 ${item.version} 版</option>`).join("");
    $("#watchsets-list").innerHTML=boss.length ? boss.map(item=>`<article class="panel strategy-card"><div class="section-heading"><h3>${e(item.name)}</h3>${badge("第 "+item.version+" 版","muted")}</div><p class="form-note">${item.config.kind === "exploration" ? "独立探索组" : "固定观察组"} · ${e(item.config.city)} · ${e(item.config.query)}<br>最多 ${item.config.page_limit} 页 / ${item.config.detail_limit} 份详情 / ${item.config.request_limit} 次请求</p><button class="secondary small" data-create-task="${e(item.id)}">创建一次有限任务</button></article>`).join("") : empty("还没有可执行的观察规则","可先保存有限规则；现有人工导入记录不作为在线观察配置。");
    $("#schedule-list").innerHTML=data.schedules.map(item=>`<article class="panel report-row"><div><h3>${e(watchsetNames.get(item.watchset_id) || "历史规则")}</h3><p>每日北京时间 ${String(item.hour).padStart(2,"0")}:${String(item.minute).padStart(2,"0")} · ${item.enabled ? "已启用，需处理程序触发" : "已关闭"}</p></div><button class="secondary small" data-toggle-schedule="${e(item.id)}" ${!sourceReady && !item.enabled ? "disabled" : ""}>${item.enabled ? "关闭时段" : "启用时段"}</button></article>`).join("") || empty("还没有每日时段","保存时段不会自动创建系统任务。");
    $("#tasks-list").innerHTML=data.tasks.map(item=>`<article class="panel strategy-card"><div class="section-heading"><h3>${e(watchsetNames.get(item.watchset_id) || "历史观察规则")}</h3>${badge(taskStateLabels[item.state] || item.state,["failed","partial","blocked","interrupted","needs_auth"].includes(item.state) ? "amber" : "muted")}</div><p class="form-note">模式：${item.mode === "replay" ? "历史回放，非新市场观察" : "有限来源观察"} · 已尝试 ${item.attempts} 次 · ${e(when(item.created_at))}${item.error_code ? "<br>停止原因："+e(reasonLabels[item.error_code] || (item.error_code === "SOURCE_PAUSED_USE_LOCAL_DATA" ? "来源暂停；没有因此恢复或绕过停止条件。" : "本次执行失败，资料缺口保持未知。")) : ""}</p><div class="result-actions">${item.state === "queued" ? `<button class="secondary small" data-task-action="run" data-task-id="${e(item.id)}" ${sourceReady ? "" : "disabled"}>执行此任务</button>` : ""}${["failed","partial","blocked","interrupted","needs_auth"].includes(item.state) && item.attempts < 2 ? `<button class="text-button" data-task-action="retry" data-task-id="${e(item.id)}" ${sourceReady ? "" : "disabled"}>显式重试（总计至多两次）</button>` : ""}</div></article>`).join("") || empty("执行队列为空","创建一次任务后会保留进度，失败不会伪装成没有市场需求。");
    renderInbox();
  } catch (error) {$("#inbox-list").innerHTML=errorBox(error);}
}

function renderInbox() {
  const data=state.operations;if (!data) return;
  const items=data.inbox.filter(item=>!$("#inbox-unread").checked || item.state === "unread");
  $("#inbox-list").innerHTML=items.length ? items.map(item=>`<article class="panel strategy-card"><div class="section-heading"><h3>${e(item.title)}</h3>${badge(({unread:"未读",read:"已读",resolved:"已处理"})[item.state] || item.state,item.state === "unread" ? "amber" : "muted")}</div><p class="body-text">${e(item.body)}</p><p class="form-note">${e(when(item.created_at))} · ${({research:"研究更新",collection:"观察更新",followup:"待研究问题",hypothesis:"待验证假设",attention:"需要关注",system:"运行记录"})[item.kind] || "记录"}</p><div class="result-actions">${item.kind === "research" && item.related_id ? `<button class="secondary small" data-open-run="${e(item.related_id)}">查看研究</button>` : ""}${["followup","hypothesis"].includes(item.kind) && !item.details?.cleared ? `<button class="secondary small" data-inbox-research="${e(item.body)}">带入研究工作台 ↗</button>` : ""}${item.state === "unread" ? `<button class="text-button" data-notification-action="read" data-notification-id="${e(item.id)}">标为已读</button>` : ""}${item.state !== "resolved" ? `<button class="text-button" data-notification-action="resolve" data-notification-id="${e(item.id)}">标为已处理</button>` : ""}</div></article>`).join("") : empty("没有待看的更新","研究结果与待研究问题会留在这里，不发送外部消息。");
}

async function saveWatchset(event) {
  event.preventDefault();const form=event.target.elements;
  try {
    await api("watchsets",{method:"POST",body:JSON.stringify({name:form.name.value.trim(),spec:{source:"boss",kind:form.kind.value,query:form.query.value.trim(),city:form.city.value.trim(),page_limit:Number(form.page_limit.value),detail_limit:Number(form.detail_limit.value),request_limit:Number(form.request_limit.value)}})});
    notify("观察规则版本已保存，没有发起来源请求。");await loadOperations();
  } catch (error) {notify(error.message,true);}
}

async function saveSchedule(event) {
  event.preventDefault();const form=event.target.elements;
  const [hour,minute]=form.time.value.split(":").map(Number);
  try {
    await api("schedules",{method:"POST",body:JSON.stringify({watchset_id:form.watchset_id.value,hour,minute,enabled:form.enabled.checked})});
    notify("每日时段已保存；仍需运行任务处理程序，来源暂停继续生效。");await loadOperations();
  } catch (error) {notify(error.message,true);}
}

async function saveFollowup(event) {
  event.preventDefault();
  try {await api("inbox/followup",{method:"POST",body:JSON.stringify({question:event.target.elements.question.value.trim()})});event.target.reset();notify("待研究问题已保存。");await loadOperations();}
  catch (error) {notify(error.message,true);}
}

const importFieldLabels={title:"岗位名称",company:"公司名称",description:"JD正文",external_id:"稳定资料编号",city:"城市",salary:"薪资原文",education:"学历原文",experience:"经验原文",job_url:"原文链接",source_published_at:"明确发布时间（含时区）",source_published_raw:"来源时间原文",related_job_id:"关联岗位",note:"备注",data_kind:"资料性质"};
function renderCSVPreview() {
  $("#csv-preview").innerHTML=state.csvRows.map((row,index)=>`<details class="csv-row" open><summary><label class="checkbox-line"><input type="checkbox" data-csv-selected="${index}" ${row.valid ? "checked" : ""}>第 ${row.row_number} 行 · ${e(row.draft.title || "岗位名称未填")} ${badge(row.valid ? "格式有效，仍需核对" : "待修正",row.valid ? "muted" : "amber")}</label></summary>${row.errors.map(error=>`<p class="form-note">${e(error)}</p>`).join("")}<div class="form-grid">${["title","company","external_id"].map(key=>`<label>${importFieldLabels[key]}<input data-csv-index="${index}" data-csv-field="${key}" value="${e(row.draft[key] || "")}"></label>`).join("")}</div><label>完整JD正文<textarea rows="4" data-csv-index="${index}" data-csv-field="description">${e(row.draft.description || "")}</textarea></label><details><summary>核对其他原文字段</summary><div class="form-grid">${Object.entries(row.draft).filter(([key])=>!["title","company","external_id","description","ocr_reviewed"].includes(key)).map(([key,value])=>key === "data_kind" ? `<label>资料性质<select data-csv-index="${index}" data-csv-field="data_kind"><option value="user_provided" ${value === "user_provided" ? "selected" : ""}>用户提供</option><option value="synthetic" ${value === "synthetic" ? "selected" : ""}>合成演示（非真实招聘）</option></select></label>` : `<label>${e(importFieldLabels[key] || key)}<input data-csv-index="${index}" data-csv-field="${e(key)}" value="${e(value)}"></label>`).join("")}</div></details></details>`).join("");
  $("#commit-csv").disabled=!state.csvRows.length;
  $("#csv-feedback").textContent=`${state.csvRows.length} 行已预览。勾选表示已核对本行内容；失败行可编辑后单独重试。`;
}

async function commitCSV() {
  const button=$("#commit-csv");button.disabled=true;
  try {
    const rows=$$("[data-csv-selected]:checked").map(box=>{
      const index=Number(box.dataset.csvSelected),source=state.csvRows[index],jd={...source.draft};
      $$(`[data-csv-index="${index}"]`).forEach(field=>{if (field.value.trim()) jd[field.dataset.csvField]=field.value.trim();else delete jd[field.dataset.csvField];});
      return {row_number:source.row_number,jd};
    });
    if (!rows.length) throw new Error("请勾选已核对的行后再导入。");
    const result=await api("imports/csv/commit",{method:"POST",body:JSON.stringify({rows})});
    $("#csv-feedback").textContent=`已导入 ${result.imported} 行，失败 ${result.failed} 行。已完成行不受失败影响。`;
    for (const row of result.rows) {
      const index=state.csvRows.findIndex(item=>item.row_number === row.row_number);
      const box=$(`[data-csv-selected="${index}"]`);
      if (box && row.status === "imported") box.checked=false;
      const details=box?.closest("details.csv-row");
      if (details) {const note=document.createElement("p");note.className="form-note";note.textContent=row.status === "imported" ? "本行已保存；重复导入沿用既有去重规则。" : "本行未保存，请核对字段或资料编号，编辑后可再次勾选导入。";details.append(note);}
    }
    await loadOverview();await loadJobs();
  } catch (error) {$("#csv-feedback").textContent=error.message;}
  finally {button.disabled=false;}
}

async function uploadImportImage() {
  const file=$("#image-import-file").files[0];
  if (!file) {notify("请先选择要核对的截图。",true);return;}
  if (file.size > 5000000 || !["image/png","image/jpeg","image/webp"].includes(file.type)) {notify("请选择5MB以内的PNG、JPEG或WebP。",true);return;}
  const button=$("#upload-import-image");button.disabled=true;
  try {
    const kind=$("#image-synthetic").checked ? "synthetic" : "user_provided";
    const asset=await api("import-assets?"+new URLSearchParams({data_kind:kind}),{method:"POST",body:file,headers:{"Content-Type":file.type}});
    state.importAsset=asset;
    $("#import-image-preview").innerHTML=`<p class="form-note">${asset.data_kind === "synthetic" ? "合成演示原图（非真实招聘）" : "用户上传原图，待人工核对"} · 仅在本机归档</p><img class="import-image" src="${e(asset.image_url)}" alt="待人工核对的岗位截图原图">`;
    const form=$("#import-form");form.elements.import_asset_id.value=asset.id;form.elements.data_kind.value=asset.data_kind;
    $("#image-review-line").hidden=false;$("#ocr-reviewed").disabled=false;$("#ocr-reviewed").required=true;$("#ocr-reviewed").checked=false;
    $("#extract-import-image").disabled=false;
    $("#image-import-feedback").textContent="原图已归档。可对照图片人工填写；如需视觉抽取，请先明确同意发送，再点击抽取草稿。";
  } catch (error) {$("#image-import-feedback").textContent=error.message;}
  finally {button.disabled=false;}
}

async function extractImportImage() {
  if (!state.importAsset) return;
  if (!$("#image-model-consent").checked) {notify("请先明确勾选允许发送这张图片到已配置模型。",true);return;}
  const button=$("#extract-import-image");button.disabled=true;
  $("#image-import-feedback").textContent="正在进行一次视觉抽取；结果只是草稿，最多等待60秒…";
  try {
    const result=await api("import-assets/"+state.importAsset.id+"/extract",{method:"POST",body:JSON.stringify({allow_model:true})});
    state.importAsset=result.asset || state.importAsset;
    if (result.status !== "draft_ready" || !result.draft) throw new Error(reasonLabels[result.error_code] || "图片抽取失败，未写入岗位。可对照原图人工填写，或稍后显式重试。");
    const form=$("#import-form"),related=form.elements.related_job_id.value,externalId=form.elements.external_id.value;form.reset();form.elements.related_job_id.value=related;form.elements.external_id.value=externalId;
    for (const [key,value] of Object.entries(result.draft)) if (form.elements.namedItem(key)) form.elements.namedItem(key).value=value;
    form.elements.import_asset_id.value=state.importAsset.id;form.elements.data_kind.value=state.importAsset.data_kind;
    $("#image-review-line").hidden=false;$("#ocr-reviewed").disabled=false;$("#ocr-reviewed").required=true;$("#ocr-reviewed").checked=false;
    $("#image-import-feedback").textContent="视觉草稿已填入下方表单，尚未写入岗位。请逐项对照原图编辑，未知留空，勾选人工核对后再保存。";
    $("#import-feedback").textContent="待人工核对的OCR草稿，尚未保存。";
  } catch (error) {$("#image-import-feedback").textContent=error.message;}
  finally {button.disabled=false;}
}

function showArchivedImage(id) {
  $("#source-content").innerHTML=`<h2>人工核对的截图原图</h2><p class="form-note">这是用户上传并归档的原图，读取时核对文件指纹。模型抽取与人工转录均不代替原图核实。</p><img class="import-image" src="/api/import-assets/${e(id)}/image" alt="已归档的截图核对原图">`;
  openDialog("source-dialog");
}

async function route() {
  const page = location.hash.slice(1).split("/")[0] || "career";
  state.page = titles[page] ? page : "research";
  $$(".page").forEach(element=>{element.hidden = element.id !== "page-" + state.page;});
  $$("nav [data-page]").forEach(link=>{
    link.classList.toggle("active",link.dataset.page === state.page);
    if (link.dataset.page === state.page) link.setAttribute("aria-current","page");
    else link.removeAttribute("aria-current");
  });
  $("#breadcrumb").textContent = titles[state.page];
  document.title = `${titles[state.page]} · Work Observer`;
  if (state.page === "jobs") await loadJobs();
  if (state.page === "career") await window.loadCareer?.();
  if (state.page === "companies") await loadCompanies();
  if (state.page === "research") {
    updateResearchScope();await Promise.all([loadResearchProjects(),loadResearchHistory()]);
    const linked=location.hash.slice(1).split("/")[1];
    const saved=linked && /^[a-f0-9]{32}$/.test(linked) ? linked : conversation.id || sessionStorage.getItem("wo-conversation");
    if(saved && !state.activeRun && !sessionStorage.getItem("wo-research")) {
      conversation.id=saved;await openResearchConversation(saved,false);
    }
  }
  if (state.page === "memory") await loadMemories();
  if (state.page === "matches") await loadMatchPreferences();
  if (state.page === "retrieval") await loadStrategies();
  if (state.page === "operations") await loadOperations();
  if (state.page === "projects") await window.loadProjects?.();
  if (state.page === "workflows") await window.loadWorkflows?.();
  if (state.page === "trials") await window.loadTrials?.();
  if (state.page === "knowledge") await window.loadKnowledge?.();
  if (state.page === "quality") await window.loadQuality?.();
  if (state.page === "profile-quality") await window.loadProfileQuality?.();
  if (state.page === "research-benchmarks") await window.loadResearchBenchmarks?.();
  if (state.page === "data-quality") await window.loadDataQuality?.();
  if (state.page === "updates") await window.loadUpdates?.();
  if (state.page === "reports") {
    const reportId = location.hash.slice(1).split("/")[1];
    if (reportId && /^[a-f0-9]{32}$/.test(reportId)) await showReport(reportId);
    else await loadReports();
  }
}

$("#filter-form").addEventListener("submit",event=>{event.preventDefault();state.filters=filterValues();state.offset=0;loadJobs();});
$("#filter-form").addEventListener("reset",()=>{state.filters={};state.offset=0;setTimeout(loadJobs,0);});
$("#prev-page").addEventListener("click",()=>{state.offset=Math.max(0,state.offset-state.limit);loadJobs();});
$("#next-page").addEventListener("click",()=>{state.offset+=state.limit;loadJobs();});
$("#clear-selection").addEventListener("click",()=>{state.selected.clear();updateSelection();});
$("#compare-selected").addEventListener("click",()=>{
  if (state.selected.size < 2 || state.selected.size > 5) return;
  state.researchIds=[...state.selected.keys()];
  $("#research-source-mode").value="jobs";updateResearchApproach();
  $("#question").value="比较这些岗位的任务、责任、能力和工具，区分必备、加分和资料缺失。";
  location.hash="research";updateResearchScope();
});
$("#research-filtered").addEventListener("click",()=>{state.researchIds=null;$("#research-source-mode").value="jobs";updateResearchApproach();location.hash="research";updateResearchScope();});
$("#company-form").addEventListener("submit",event=>{event.preventDefault();loadCompanies();});
$("#research-form").addEventListener("submit",startResearch);
$("#research-approach").addEventListener("change",updateResearchApproach);
$("#refresh-research-history").addEventListener("click",()=>loadResearchHistory());
$("#research-history-search").addEventListener("submit",event=>{event.preventDefault();loadResearchHistory();});
$("#research-history-clear").addEventListener("click",()=>{$("#research-history-query").value="";loadResearchHistory();});
$("#research-history-prev").addEventListener("click",()=>loadResearchHistory(Math.max(0,researchHistory.offset-researchHistory.limit)));
$("#research-history-next").addEventListener("click",()=>loadResearchHistory(researchHistory.offset+researchHistory.limit));
$("#add-memory").addEventListener("click",()=>showMemory());
$("#memory-history").addEventListener("change",loadMemories);
$("#memory-form").addEventListener("submit",saveMemory);
$("#match-form").addEventListener("submit",runMatch);
$("#save-match-preferences").addEventListener("click",saveMatchPreferences);
$("#retrieval-form").addEventListener("submit",searchRetrieval);
$("#strategy-form").addEventListener("submit",createStrategy);
$("#refresh-strategies").addEventListener("click",loadStrategies);
$("#monitor-strategy").addEventListener("click",async ()=>{
  const button=$("#monitor-strategy");button.disabled=true;
  try {
    const result=await api("strategies/monitor",{method:"POST"});
    notify(result.status === "rolled_back" ? "当前策略护栏未通过，程序已回退并保留记录。" : result.status === "baseline" ? "当前使用稳定基线。" : "当前策略通过固定模拟护栏，真实资料效果仍需核对。");
    await loadStrategies();
  } catch (error) {notify(error.message,true);}
  finally {button.disabled=false;}
});
$("#strategy-rollback-form").addEventListener("submit",rollbackStrategy);
$("#refresh-operations").addEventListener("click",loadOperations);
$("#inbox-unread").addEventListener("change",renderInbox);
$("#watchset-form").addEventListener("submit",saveWatchset);
$("#schedule-form").addEventListener("submit",saveSchedule);
$("#followup-form").addEventListener("submit",saveFollowup);
$("#check-due-schedules").addEventListener("click",async ()=>{
  try {const result=await api("operations/tick",{method:"POST"});notify("到期检查完成，只处理本地入队，没有发出来源请求。");await loadOperations();}
  catch (error) {notify(error.message,true);}
});
$("#import-form").addEventListener("submit",importSubmit);
$("#import-file").addEventListener("change",importFile);
$("#upload-import-image").addEventListener("click",uploadImportImage);
$("#extract-import-image").addEventListener("click",extractImportImage);
$("#commit-csv").addEventListener("click",commitCSV);
window.addEventListener("hashchange",route);

document.addEventListener("submit",async event=>{
  const form=event.target.closest("[data-domain-form]");
  if (!form) return;
  event.preventDefault();
  const button=$("button[type=submit]",form);button.disabled=true;
  try {
    await api("knowledge/jobs/"+encodeURIComponent(form.dataset.domainForm)+"/domains",{method:"POST",body:JSON.stringify({domain_ids:[...new FormData(form).getAll("domain")],reason:form.elements.reason.value.trim()})});
    notify("已保存领域纠正；旧画像会标注变化，后续采用人工归类。");
    await showProfile(form.dataset.domainForm);
  } catch (error) {$("[data-domain-feedback]",form).textContent=error.message;button.disabled=false;}
});

document.addEventListener("change",event=>{
  const checkbox = event.target.closest("[data-select-job]");
  if (!checkbox) return;
  const id = checkbox.dataset.selectJob;
  if (checkbox.checked) state.selected.set(id,state.jobs.get(id));
  else state.selected.delete(id);
  updateSelection();
});

document.addEventListener("click",async event=>{
  const element = event.target.closest("button,[data-action]");
  if (!element) return;
  try {
  if (element.dataset.close) $("#"+element.dataset.close).close();
  if (element.dataset.action === "import") showImport();
  if (element.dataset.job) {
    if ($("#source-dialog").open) $("#source-dialog").close();
    await showJob(element.dataset.job);
  }
  if (element.dataset.company) await showCompany(element.dataset.company);
  if (element.dataset.compareHistory) await compareJobHistory(element.dataset.compareHistory);
  if (element.dataset.profile) await showProfile(element.dataset.profile);
  if (element.dataset.analyzeProfile) await analyzeProfile(element.dataset.analyzeProfile,element.dataset.offline === "true");
  if (element.dataset.source) await showSource(element.dataset.source);
  if (element.dataset.publicSource) await showPublicSource(element.dataset.publicSource);
  if (element.dataset.importImage) showArchivedImage(element.dataset.importImage);
  if (element.dataset.supplement) showImport(element.dataset.supplement);
  if (element.dataset.addCompare) {
    const id = element.dataset.addCompare;
    if (!state.selected.has(id)) {
      if (state.selected.size >= 5) { notify("一次比较最多选择 5 个岗位。",true); return; }
      const job = await api("jobs/"+encodeURIComponent(id));
      state.selected.set(id,{id,title:job.current.title});
    }
    element.textContent="已加入比较";updateSelection();notify("已加入比较，可在列表底部开始比较。");
  }
  if (element.dataset.openRun) await openRun(element.dataset.openRun);
  if (element.dataset.resumeRun) {
    element.disabled = true;
    try { const run = await api("research/"+element.dataset.resumeRun+"/resume",{method:"POST"});pendingResearch(run.id); }
    catch (error) { element.disabled=false;throw error; }
  }
  if (element.dataset.cancelRun) {
    element.disabled = true;
    await api("research/"+element.dataset.cancelRun+"/cancel",{method:"POST"});
    await pollResearch(element.dataset.cancelRun);
  }
  if (element.dataset.knowledgeRun) {
    await collectResearchClaim(element);
  }
  if (element.dataset.followupQuestion) {
    element.disabled=true;
    try {await api("inbox/followup",{method:"POST",body:JSON.stringify({question:element.dataset.followupQuestion,source_run_id:element.dataset.followupRun || null})});notify("问题已存入观察与更新收件箱。");}
    catch (error) {element.disabled=false;throw error;}
  }
  if (element.dataset.inboxResearch) {
    $("#question").value=element.dataset.inboxResearch;state.researchIds=null;location.hash="research";updateResearchScope();
  }
  if (element.dataset.notificationAction) {
    await api("inbox/"+encodeURIComponent(element.dataset.notificationId)+"/"+element.dataset.notificationAction,{method:"POST"});await loadOperations();
  }
  if (element.dataset.createTask) {await api("tasks",{method:"POST",body:JSON.stringify({watchset_id:element.dataset.createTask})});notify("已创建有限观察任务，尚未发起来源请求。");await loadOperations();}
  if (element.dataset.taskAction) {
    element.disabled=true;
    try {await api("tasks/"+encodeURIComponent(element.dataset.taskId)+"/"+element.dataset.taskAction,{method:"POST"});await loadOperations();if (element.dataset.taskAction === "run") setTimeout(loadOperations,1200);}
    catch (error) {element.disabled=false;throw error;}
  }
  if (element.dataset.toggleSchedule) {
    const item=state.operations.schedules.find(row=>row.id === element.dataset.toggleSchedule);
    await api("schedules",{method:"POST",body:JSON.stringify({watchset_id:item.watchset_id,hour:item.hour,minute:item.minute,enabled:!item.enabled,schedule_id:item.id})});await loadOperations();
  }
  if (element.dataset.strategyAction) {
    element.disabled=true;
    try {
      const result=await api("strategies/"+encodeURIComponent(element.dataset.strategyId)+"/"+element.dataset.strategyAction,{method:"POST"});
      notify(element.dataset.strategyAction === "evaluate" ? "固定模拟评测已结束，可查看逐项结果。" : "本地检索策略已启用，可用真实资料核对效果。");
      await loadStrategies();
    } catch (error) {element.disabled=false;throw error;}
  }
  if (element.dataset.forgetMemory) {
    if (!window.confirm("忘记这条个人偏好或纠正，并清除当前工作空间内相关研究检查点、画像与已存报告？原始岗位仍保留，独立下载副本与备份不会自动删除。此操作无法撤销。")) return;
    element.disabled=true;
    try {
      const forgotten=await api("memories/"+encodeURIComponent(element.dataset.forgetMemory),{method:"DELETE"});
      clearForgottenConversation(forgotten.affected_project_ids||[]);
      resetResearchHistory();
      if ((forgotten.affected_run_ids || []).includes(state.lastRun)) {
        state.lastResult=null;state.lastRun=null;
        $("#research-output").innerHTML=empty("相关个人记忆已忘记","受影响的研究结果已清除，可按当前记录重新研究。");
      }
      $("#report-detail").replaceChildren();$("#reports-list").replaceChildren();$("#profile-content").replaceChildren();$("#research-history-list").replaceChildren();
      state.operations=null;$("#inbox-list").replaceChildren();
      notify("已忘记记录，并清除相关派生结果。");await loadMemories();
    }
    catch (error) {element.disabled=false;throw error;}
  }
  if (element.dataset.memoryEdit) showMemory(element.dataset.memoryEdit);
  if (element.dataset.memoryAction) {
    element.disabled=true;
    try {
      await api("memories/"+encodeURIComponent(element.dataset.memoryId)+"/"+element.dataset.memoryAction,{method:"POST"});
      await loadMemories();
      notify(({activate:"记录已采纳，后续研究按类型与范围参考。",accept:"已选择此项，重叠有效期的冲突值已否决。",reject:"已否决此项，其他冲突仍需明确选择。",withdraw:"记录已撤回，后续研究停止默认召回。"})[element.dataset.memoryAction] || "记录已更新。");
    } catch (error) {element.disabled=false;throw error;}
  }
  if (element.dataset.prompt) {
    $("#question").value=element.dataset.prompt;
    if(element.dataset.promptApproach){
      if(element.dataset.promptApproach==="work_map"){$("#research-source-mode").value="jobs";updateResearchScope();}
      $("#research-approach").value=element.dataset.promptApproach;updateResearchApproach();
    }
  }
  if (element.dataset.report) await showReport(element.dataset.report);
  if (element.hasAttribute("data-report-back")) await loadReports();
  if (element.dataset.cite) {
    const root = element.closest(".result-card");
    const details = $$("[data-evidence]",root).find(item=>item.dataset.evidence === element.dataset.cite);
    if (details) {highlightCitation(details,element.dataset.citeStart,element.dataset.citeEnd);details.open=true;details.scrollIntoView({behavior:"smooth",block:"center"});}
  }
  if (element.dataset.saveResearch) {
    element.disabled=true;
    try {
      const saved = await api("research/"+element.dataset.saveResearch+"/save",{method:"POST"});
      if (element.closest("#conversation-turns")) {
        conversation.reports.set(element.dataset.saveResearch,saved);
        await openResearchConversation(conversation.id);
      } else if (element.closest("#project-detail") && typeof openProject === "function" && selectedProject) {
        await openProject(selectedProject.id);
      } else {
        state.lastResult={...state.lastResult,...saved};
        renderResult(state.lastResult,$("#research-output"),state.lastRun);
      }
      notify("研究已保存，可以在“已存研究”中查看。");
    } catch (error) {element.disabled=false;notify(error.message,true);}
  }
  } catch (error) { notify(error.message || "操作未完成，请稍后再试。",true); }
});

document.addEventListener("DOMContentLoaded",async function boot(){
  restorePendingResearch();
  updateResearchApproach();
  await loadResearchFormats();
  await route();
  try {
    const overview = await loadOverview();
    const current = overview.active_research || sessionStorage.getItem("wo-research");
    if (current) pendingResearch(current);
  } catch (error) {notify(error.message,true);$("#model-status").textContent="本地服务读取失败";}
});

// 从岗位详情进入整份画像审核，关闭上层对话框后再显示审核页。
document.addEventListener("click",async event=>{
  const button=event.target.closest("[data-profile-quality-open]");
  if(!button || button.closest("#page-profile-quality"))return;
  try {
    document.querySelectorAll("dialog[open]").forEach(dialog=>dialog.close());
    location.hash="profile-quality";
    await window.loadProfileQuality?.();
    await window.openProfileQuality?.(button.dataset.profileQualityOpen);
  } catch(error) {notify(error.message,true);}
});

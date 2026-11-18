"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const e = escapeHTML;
const token = $('meta[name="wo-token"]').content;
const state = {importAsset:null,csvRows:[],operations:null, filters:{}, offset:0, limit:20, jobs:new Map(), selected:new Map(), researchIds:null,
  activeRun:null, lastRun:null, lastResult:null, memories:new Map(), overview:null, page:"jobs", querySerial:0};
const statusLabels = {completed:"研究完成", partial:"已保留部分结果", evidence_only:"原文证据包", failed:"研究未完成", incomplete:"达到研究上限", insufficient_evidence:"正文不足"};
const originLabels = {website:"网站响应", unknown:"新鲜度未知", cache:"缓存资料", replay:"回放资料", manual:"人工资料", test:"测试资料", client_error:"获取失败"};
const requirementLabels = {required:"必备", preferred:"加分", unspecified:"未明确性质"};
const domainLabels = {business_application:"业务应用开发",agent_platform:"执行平台与 Harness",domain_decision:"领域决策系统",model_serving:"模型与推理部署",configuration_delivery:"平台配置与实施",other:"其他待定义领域"};
const categoryLabels = {business:"业务背景", deliverable:"交付物", task:"任务", responsibility:"责任", ability:"能力", tool:"工具"};
const reasonLabels = {VISION_NO_READABLE_TEXT:"未取得可核对的正文，未写入岗位。可对照原图人工填写。",VISION_MODEL_HTTP_ERROR:"当前模型服务未能处理图片，未写入岗位。",INVALID_VISION_DRAFT:"视觉响应不符合草稿格式，未写入岗位。",MODEL_CONFIG_MISSING:"尚未配置模型，可改用仅整理证据模式。",MODEL_AUTH_REQUIRED:"模型服务认证未通过。",MODEL_FORBIDDEN:"当前模型服务权限不足。",MODEL_RATE_LIMIT_OR_QUOTA:"模型服务限流或额度不足，可稍后再试。",MODEL_HTTP_ERROR:"模型服务暂时没有正常响应。",TIMEOUT:"已达到时间上限，研究停止。",model_call_limit:"已达到调用次数上限，研究停止。",no_available_details:"范围内没有可研究的完整正文。"};
const titles = {jobs:"岗位资料", companies:"公司档案", research:"研究工作台", reports:"已存研究", memory:"知识与偏好", matches:"个人匹配", retrieval:"检索与评测", operations:"观察与更新"};
let toastTimer, pollTimer;

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
    const error = new Error(data.message || "操作未完成，请稍后再试。");
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
    if (content.startsWith("结构化个人条件：")) {
      const p=JSON.parse(content.slice("结构化个人条件：".length));
      return [p.cities?.length ? "工作城市："+p.cities.join("、") : "工作城市不限",p.salary_min != null || p.salary_max != null ? "薪资区间："+(p.salary_min ?? "不限")+"～"+(p.salary_max ?? "不限")+"元 / "+({month:"月",year:"年",day:"日",hour:"小时"})[p.salary_unit] : "薪资不限",p.employment_types?.length ? "用工形式："+p.employment_types.join("、") : "",p.desired_tasks?.length ? "希望承担："+p.desired_tasks.join("、") : ""].filter(Boolean).join("；");
    }
    if (content.startsWith("画像领域纠正：")) {
      const value=JSON.parse(content.slice("画像领域纠正：".length));
      return "领域归类："+(value.domains.length ? value.domains.map(key=>domainLabels[key] || key).join("、") : "暂不归类")+"。理由："+value.reason;
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
  $("#source-content").innerHTML = `<div class="empty">正在核对公开资料归档…</div>`;
  openDialog("source-dialog");
  try {
    const data=await api("public-documents/"+encodeURIComponent(id));
    $("#source-content").innerHTML=`<h2>${e(data.title)}</h2>${badge(data.integrity === "verified" ? "公开归档文件指纹已核对" : "归档文件缺失或已变化",data.integrity === "verified" ? "" : "amber")}<p class="form-note">已归档的公开网页正文；作为业务背景，不能直接证明岗位职责。网页发布时间未知。</p><dl class="detail-grid">${detailData("出处",data.publisher)}${detailData("取得时间",when(data.observed_at))}${detailData("正文长度",data.full_text_length)}${detailData("来源发布时间",data.source_published_at ? when(data.source_published_at) : "未知")}</dl>${safeURL(data.final_url || data.url) ? `<a class="secondary button-link" href="${e(safeURL(data.final_url || data.url))}" target="_blank" rel="noopener noreferrer">打开公开出处 ↗</a>` : ""}<section class="detail-section"><h3>归档全文（纯文本）</h3><div class="body-text">${e(data.text)}</div></section>`;
  } catch (error) {$("#source-content").innerHTML=errorBox(error);}
}

async function loadCompanies() {
  const root = $("#companies-grid");
  root.innerHTML = empty("正在读取公司资料…");
  try {
    const companies = await api("companies?" + new URLSearchParams({name:$("#company-search").value.trim()}));
    root.innerHTML = companies.length ? companies.map(company=>`<button class="panel company-card" data-company="${e(company.id)}"><span class="company-monogram">${e(company.name.slice(0,1))}</span><h3>${e(company.name)}</h3><p>${e(company.industry_raw || "行业未知")} · ${e(company.scale_raw || "规模未知")}</p>${badge(company.identity_status === "source_id" ? "已有来源公司编号" : "身份未核实",company.identity_status === "source_id" ? "" : "muted")}<span class="subtext">最近取得 ${e(when(company.last_observed_at,true))}</span></button>`).join("") : empty("没有找到公司记录","换一个名称试试。");
  } catch (error) { root.innerHTML = errorBox(error); }
}

function updateResearchScope() {
  const root = $("#research-scope");
  if (state.researchIds?.length) {
    root.innerHTML = `<strong>所选 ${state.researchIds.length} 个岗位</strong><br>` + state.researchIds.map(id=>badge(state.selected.get(id)?.title || state.jobs.get(id)?.title || "指定岗位","muted")).join(" ");
  } else {
    const labels = {city:"城市",company:"公司",keyword:"关键词",education:"学历",experience:"经验",salary_min:"薪资下限",salary_max:"薪资上限",source:"来源"};
    const filters = Object.entries(state.filters).filter(([key,value])=>value && !["salary_unit","detail"].includes(key));
    root.innerHTML = `<strong>当前筛选范围</strong><br>` + (filters.length ? filters.map(([key,value])=>`${e(labels[key] || key)}：${e(value)}`).join(" · ") : "全部已存岗位") + (state.filters.detail === "detail" ? " · 仅有正文" : state.filters.detail === "list_only" ? " · 仅有摘要" : "") + "<br><small>最多研究 20 个候选，缺失正文会单独说明。</small>";
  }
}

function renderResult(result, target, runId = null) {
  const evidence = new Map(result.evidence.map((ev,index)=>[ev.id,{...ev,label:`E${index+1}`}])) ;
  const counts = result.scope.counts;
  const completed = ["completed","evidence_only"].includes(result.status);
  const reportId = result.report_id;
  const runIdentity = runId || result.run_id;
  target.innerHTML = `<article class="panel result-card"><div class="result-top"><h2>${e(result.mode === "offline" ? "原文证据" : "研究结果")}</h2>${badge(statusLabels[result.status] || result.status,completed ? "" : "amber")}</div><p class="result-question">${e(result.question)}</p><div class="scope-summary"><span>${counts.matched} 个匹配</span>·<span>${counts.unknown} 个条件未知</span>·<span>${counts.candidate_details} 份候选正文</span>·<span>${e(when(result.created_at))}</span></div>
    ${renderResearchContext({...result,run_id:runIdentity})}
    ${renderResearchCandidates(result)}
    ${result.claims.length ? `<div class="claim-list">${result.claims.map((claim,index)=>`<section class="claim">${badge(categoryLabels[claim.category] || claim.category,"muted")} ${badge(requirementLabels[claim.requirement] || claim.requirement,claim.requirement === "preferred" ? "amber" : "")}<p>${e(claim.text)}</p>${claim.basis ? badge(({direct:"原文明示",synthesis:"跨材料归纳",inference:"研究推断"})[claim.basis] || claim.basis,"muted") : ""} ${claim.evidence_ids.map(id=>evidence.has(id) ? `<button class="cite" data-cite="${e(id)}">${e(evidence.get(id).label)} ↗</button>` : "").join("")}${runIdentity && result.status === "completed" && claim.evidence_ids.every(id=>evidence.get(id)?.document_id && evidence.get(id)?.snapshot_id) ? `<button class="text-button" data-knowledge-run="${e(runIdentity)}" data-claim-index="${index}">留作知识候选 ＋</button>` : ""}</section>`).join("")}</div>` : `<p class="form-note">${result.status === "evidence_only" ? "这是原文证据包，未调用模型，也未进行自动比较或分类。" : "本次没有形成可接受的模型判断。可先查看已有证据，或缩小范围后再研究。"}</p>`}
    <div class="gaps"><strong>资料缺口与研究范围</strong><ul>${result.gaps.map(gap=>`<li>${e(gap)}</li>`).join("")}</ul>${!completed ? `<p>结束原因：${e(reasonLabels[result.stop_reason] || "本次未能完成研究，可核对范围后重试；已有资料仍可查看。")}</p>` : ""}</div>
    <details class="detail-section"><summary>本次候选与统计口径</summary><p class="form-note">统计在分页前计算。本次实际研究 ${result.scope.jobs.length} 个候选${result.scope.truncated ? "，候选较多，已截取前 20 个，请收窄范围" : ""}；未知条件不等于符合。</p>${result.scope.jobs.map(job=>`<div class="detail-history"><button class="job-link" data-job="${e(job.id)}">${e(job.title)} · ${e(job.company)}</button>${badge(job.has_detail ? "有正文" : "仅摘要","muted")} ${job.match_status === "unknown" ? badge("条件未知","amber") : ""}</div>`).join("")}</details>
    <div class="result-actions">${reportId ? `${badge("已保存")}<a class="secondary" href="/api/reports/${e(reportId)}/download/md" download>下载 Markdown</a><a class="secondary" href="/api/reports/${e(reportId)}/download/json" download>下载 JSON</a>` : runId ? `<button class="primary" data-save-research="${e(runId)}">保存这次研究</button><small class="form-note">保存问题、范围、结果与原文依据。</small>` : ""}</div>
    <section class="detail-section"><h3>原文依据 · ${evidence.size} 个片段</h3><p class="form-note">点击结论后的引用可定位片段；也可核对对应原始文档。引用有效不代表模型解释必然正确。</p>${[...evidence.values()].map(ev=>`<details class="evidence-item" data-evidence="${e(ev.id)}"><summary>${e(ev.label)} · ${e(ev.title)} · ${e(ev.company || (ev.source === "public_web" ? "公开资料" : ""))}</summary>${ev.source_note ? `<p class="form-note evidence-source-note">${e(ev.source_note)}</p>` : ""}<blockquote>${e(ev.quote)}</blockquote><div class="evidence-meta">${e(sourceLabel(ev))} · 取得 ${e(when(ev.observed_at))}<br>字符 ${ev.start}–${ev.end}${ev.full_text_length ? ` / 原文 ${ev.full_text_length} 字符` : ""} · 发布时间 ${e(ev.source_published_at ? when(ev.source_published_at) : "未知")}<br>${ev.document_id ? `<button data-source="${e(ev.document_id)}">核对来源文档与内容版本 ↗</button>` : ""}${ev.public_document_id ? `<button data-public-source="${e(ev.public_document_id)}">核对已归档的公开全文 ↗</button><br>` : ""}${safeURL(ev.url) ? `<a href="${e(safeURL(ev.url))}" target="_blank" rel="noopener noreferrer">打开公开出处 ↗</a>` : ""}</div></details>`).join("")}</section></article>`;
}

function setBusy(busy) {
  $("#start-research").disabled = busy;
  $("#start-research").textContent = busy ? "研究进行中…" : "开始研究 ↗";
}

function renderResearchCandidates(result) {
  const knowledge=result.knowledge_candidates || [],strategy=result.strategy_candidate;
  if (!knowledge.length && !strategy) return "";
  const evaluation=strategy?.evaluation;
  return `<section class="research-context"><h3>本次候选与固定评测</h3>${knowledge.length ? `<p>研究留下 ${knowledge.length} 条知识候选，尚未作为有效知识使用。</p><ul>${knowledge.map(item=>`<li>${e(item.content)}</li>`).join("")}</ul><a class="secondary small" href="#memory">到知识与偏好核对采纳 ↗</a>` : ""}${strategy ? `<p>提出了一个本地别名候选，尚未自动启用。</p>${evaluation ? `<p>${evaluation.status === "accepted" ? "固定模拟开发集达到门槛，仍需显式审核启用。" : evaluation.status === "rejected" ? "固定模拟开发集未通过门槛，继续使用现有策略。" : "固定评测证据不足，继续使用现有策略。"} 这不是实际市场资料上的改进证据。</p>` : `<p>尚未完成固定评测，不作为有效检索方法使用。</p>`}<a class="secondary small" href="#retrieval">到检索与评测查看依据 ↗</a>` : ""}</section>`;
}

function safeURL(value) {
  try { const url = new URL(value); return ["https:","http:"].includes(url.protocol) ? url.href : ""; }
  catch { return ""; }
}

function renderResearchContext(result) {
  const plan = result.plan;
  const review = result.review;
  const memories = result.memories || result.memory_used || [];
  const audit=result.audit || {};
  const auditNote=audit.stale_memory || audit.changed_sources?.length || audit.affected_strategy?.length;
  return `${auditNote ? `<div class="error-box"><strong>这是需要重新核对的历史结果</strong>${audit.stale_memory ? `<p>研究采用的偏好、知识或纠正已变化或撤回，后续研究会采用当前有效版本。</p>` : ""}${audit.changed_sources?.length ? `<p>部分来源已变化或原始文件完整性需要核对。历史引用保留当时版本，不能直接当作当前状态。</p>` : ""}${audit.affected_strategy?.length ? `<p>本次使用的检索方法已变化或回退；原始证据仍独立保留，可按当前策略重新研究。</p>` : ""}</div>` : ""}${plan ? `<details class="research-context" open><summary>研究计划与范围</summary><p>${e(plan.objective || "围绕问题查阅资料")}</p>${plan.steps?.length ? `<ol>${plan.steps.map(step=>`<li>${e(typeof step === "string" ? step : step.description || step.title || "查阅资料")}</li>`).join("")}</ol>` : ""}<p>${e(plan.scope_note || "")}</p></details>` : ""}
    ${memories.length ? `<details class="research-context"><summary>本次参考的知识与偏好 · ${memories.length} 条</summary>${memories.map(item=>`<p>${badge(({preference:"偏好",correction:"人工纠正",knowledge:"已采纳知识"})[item.kind] || "已有记录","muted")} ${e(memoryText(item))} <small>第 ${e(item.version || 1)} 版</small></p>`).join("")}<p>以上为研究背景，关键判断仍引用原始材料。</p></details>` : ""}
    ${review ? `<details class="research-context"><summary>研究复盘与下一步</summary>${(review.checks || []).map(check=>`<p>${badge(check.passed ? "已通过" : "待核对",check.passed ? "" : "amber")} ${e(check.name)}：${e(check.detail || "")}</p>`).join("")}${(review.limitations || []).map(item=>`<p>${e(item)}</p>`).join("")}${review.next_questions?.length ? `<h3>值得继续查的问题</h3><ul>${review.next_questions.map(item=>`<li>${e(item)}${result.run_id ? `<button class="text-button" data-followup-question="${e(item)}" data-followup-run="${e(result.run_id)}">留作待研究问题 ＋</button>` : ""}</li>`).join("")}</ul>` : ""}</details>` : ""}`;
}

const runLabels = {running:"正在研究",finished:"已结束",interrupted:"已中断，可查看进度",failed:"执行失败",invalidated:"相关记忆已忘记，结果已清除"};

async function loadResearchHistory() {
  const root = $("#research-history-list");
  try {
    const runs = await api("research");
    root.innerHTML = runs.length ? runs.map(run=>`<div class="panel report-row"><div><h3>${e(run.question)}</h3><p>${e(when(run.created_at))} · ${e(runLabels[run.state] || run.state)}${run.status ? " · " + e(statusLabels[run.status] || run.status) : ""}</p></div><button class="secondary small" data-open-run="${e(run.id)}">${run.state === "running" ? "查看进度" : "打开研究"} ↗</button></div>`).join("") : empty("还没有研究记录","提交问题后，过程会自动留在这里。");
  } catch (error) { root.innerHTML = errorBox(error); }
}

function renderProgress(run) {
  const result = run.result || run.progress || {};
  const isRunning = run.state === "running";
  $("#research-output").innerHTML = `<article class="panel result-card" aria-live="polite"><div class="result-top">${isRunning ? `<div class="spinner small-spinner"></div>` : ""}<h2>${e(runLabels[run.state] || "研究记录")}</h2></div><p class="form-note">${isRunning ? "正在确认范围、查阅原文和核对依据。你可以继续查看其他资料。" : run.state === "invalidated" ? "相关个人记录已忘记，受影响的派生结果和检查点已清除。可依据当前记录重新研究。" : "已保留查过的证据与剩余预算。继续时沿用原范围和预算，不重复建立研究。"}</p>${renderResearchContext(result)}<div class="scope-summary">已发起 ${e(result.model_calls || 0)} 次模型调用 · 研究进度自动留存</div><ol class="trace-list">${(result.trace || []).map(item=>`<li>${e(({query_jobs:"确认候选范围",plan_research:"制定研究计划",search_evidence:"检索本地原文",read_job:"查阅岗位正文",search_public_web:"补查公开资料",read_public_document:"读取并归档公开全文",compare_history:"比较历史版本",propose_knowledge:"提出待核对知识",propose_retrieval_strategy:"提出本地别名候选",evaluate_retrieval_strategy:"运行固定模拟评测",finish_research:"提交结论与核对"})[item.tool] || "核对研究资料")}</li>`).join("")}</ol><div class="result-actions">${isRunning ? `<button class="secondary" data-cancel-run="${e(run.id)}">暂停并保留进度</button>` : run.resumable ? `<button class="primary" data-resume-run="${e(run.id)}">继续这次研究 ↗</button>` : `<p class="form-note">没有可继续的检查点，可按原问题开始新研究。</p>`}</div></article>`;
}

async function openRun(id) {
  clearTimeout(pollTimer);
  const run = await api("research/" + encodeURIComponent(id));
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
  const question = $("#question").value.trim();
  if (!question) { notify("请先写下研究问题。",true); return; }
  setBusy(true);
  try {
    const run = await api("research",{method:"POST",body:JSON.stringify({question,
      job_ids:state.researchIds || null,filters:state.researchIds ? {} : state.filters,
      offline:$("#offline").checked,allow_public:$("#allow-public").checked})});
    pendingResearch(run.id);
  } catch (error) { setBusy(false); notify(error.message,true); }
}

async function loadReports() {
  $("#report-detail").hidden = true;
  $("#reports-list").hidden = false;
  $("#reports-list").innerHTML = empty("正在读取已存研究…");
  try {
    const reports = await api("reports");
    $("#reports-list").innerHTML = reports.length ? reports.map(report=>`<button class="panel report-row" data-report="${e(report.report_id)}"><div><h3>${e(report.question)}</h3><p>${e(when(report.created_at))} · 依据和范围已随结果保存</p></div>${badge(statusLabels[report.status] || report.status,report.status === "completed" ? "" : "muted")}<span>↗</span></button>`).join("") : empty("还没有保存的研究","完成一次研究后，点击“保存这次研究”，就能在这里再次查看。");
  } catch (error) { $("#reports-list").innerHTML = errorBox(error); }
}

async function showReport(id) {
  $("#reports-list").hidden = true;
  const root = $("#report-detail");
  root.hidden = false;
  root.innerHTML = `<div class="empty">正在读取研究…</div>`;
  try {
    const result = await api("reports/" + encodeURIComponent(id));
    root.innerHTML = `<button class="secondary back-button" data-report-back>← 返回已存研究</button><div id="saved-result"></div>`;
    renderResult(result,$("#saved-result"));
  } catch (error) { root.innerHTML = errorBox(error); }
}

function showImport(relatedId = null) {
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
  root.insertAdjacentHTML("beforeend",`<details class="research-context"><summary>纠正这个岗位的领域归类</summary><form data-domain-form="${e(id)}"><div class="domain-options">${Object.entries(domainLabels).map(([value,label])=>`<label class="checkbox-line"><input type="checkbox" name="domain" value="${e(value)}">${e(label)}</label>`).join("")}</div><label>纠正理由<textarea name="reason" required maxlength="1200" rows="3" placeholder="说明原文为何支持这项纠正。仅影响这个岗位。"></textarea></label><p class="form-note">可不选任何领域以撤销已有归类。人工纠正会保留版本，并优先用于后续画像。</p><button class="secondary" type="submit">保存本岗位领域纠正</button><p class="form-note" data-domain-feedback></p></form></details>`);
  const domains=result.effective_domains || result.domains || [];
  const questions=result.interview_questions || [];
  const corrections=result.corrections || [];
  root.insertAdjacentHTML("beforeend",`${domains.length ? `<section class="research-context"><h3>领域归类（模型判断）</h3>${domains.map(item=>`<p>${e(typeof item === "string" ? item : item.label || domainLabels[item.domain] || item.name || "待核实领域")}${item.rationale ? "："+e(item.rationale) : item.reason ? "："+e(item.reason) : ""}${item.status === "user_corrected" ? "（人工纠正）" : ""}</p>`).join("")}</section>` : ""}${questions.length ? `<section class="research-context"><h3>适合继续核实的问题</h3><ul>${questions.map(item=>`<li>${e(typeof item === "string" ? item : item.question || "核对职责范围")}</li>`).join("")}</ul></section>` : ""}${corrections.length ? `<section class="research-context"><h3>本岗位的有效人工纠正</h3>${corrections.map(item=>`<p>${e(memoryText(item))}</p>`).join("")}</section>` : ""}`);
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

const memoryKindLabels = {preference:"个人偏好",correction:"人工纠正",knowledge:"研究知识"};
const memoryStatusLabels = {active:"正在使用",candidate:"待核对采纳",superseded:"已被新版替代",withdrawn:"已撤回",expired:"已过期",forgotten:"已忘记"};

async function loadMemories() {
  const root = $("#memory-list");
  try {
    const items = await api("memories" + ($("#memory-history").checked ? "?history=1" : ""));
    state.memories = new Map(items.map(item=>[item.id,item]));
    root.innerHTML = items.length ? items.map(item=>`<article class="panel memory-card"><div class="result-top">${badge(memoryKindLabels[item.kind] || "记录","muted")}${badge(memoryStatusLabels[item.status] || item.status,item.status === "candidate" ? "amber" : "")}<small>第 ${e(item.version || 1)} 版</small></div><p class="body-text">${e(memoryText(item))}</p><p class="form-note">${item.job_id ? "仅适用岗位：" + e(item.job_id) : "在相关研究中参考"} · ${e(when(item.created_at))}</p>${item.source_run_id ? `<button class="text-button" data-open-run="${e(item.source_run_id)}">核对来源研究 ↗</button>` : ""}${item.evidence?.length ? `<details class="research-context"><summary>原始依据 · ${item.evidence.length} 个片段</summary>${item.evidence.map(ev=>`<blockquote>${e(ev.quote || "")}</blockquote>${ev.document_id ? `<button class="text-button" data-source="${e(ev.document_id)}">核对原始文档 ↗</button>` : ""}`).join("")}</details>` : ""}<div class="result-actions">${["active","candidate"].includes(item.status) ? `${item.status === "candidate" ? `<button class="primary small" data-memory-action="activate" data-memory-id="${e(item.id)}">核对后采纳</button>` : ""}${item.content.startsWith("结构化个人条件：") ? `<a class="secondary small" href="#matches">修改个人条件</a>` : item.content.startsWith("画像领域纠正：") && item.job_id ? `<button class="secondary small" data-profile="${e(item.job_id)}">核对领域纠正</button>` : `<button class="secondary small" data-memory-edit="${e(item.id)}">修订</button>`}<button class="text-button" data-memory-action="withdraw" data-memory-id="${e(item.id)}">撤回并停止使用</button>` : ""}${item.kind !== "knowledge" && item.status !== "forgotten" ? `<button class="text-button" data-forget-memory="${e(item.id)}">忘记并清除相关结果</button>` : ""}</div></article>`).join("") : empty("还没有保存的知识或偏好","可以添加明确偏好与纠正，或从研究结论中留下知识候选。");
  } catch (error) {root.innerHTML = errorBox(error);}
}

function showMemory(id = null) {
  const form = $("#memory-form");
  form.reset();
  const item = id ? state.memories.get(id) : null;
  form.elements.id.value = id || "";
  form.elements.content.value = item?.content || "";
  form.elements.job_id.value = item?.job_id || "";
  form.elements.job_id.disabled = !!id;
  form.elements.kind.disabled = !!id;
  if (item && item.kind !== "knowledge") form.elements.kind.value = item.kind;
  $("#memory-dialog-title").textContent = id ? "修订记录，保留旧版本" : "添加偏好或纠正";
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
    await api(id ? "memories/"+encodeURIComponent(id)+"/revise" : "memories", {method:"POST",body:JSON.stringify(id ? {content} : {content,kind:form.elements.kind.value,job_id:form.elements.job_id.value.trim() || null})});
    $("#memory-dialog").close();
    await loadMemories();
    notify(id ? "新版本已保存，旧版停止默认使用。" : "记录已保存，后续研究会按范围参考。");
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
  const page = location.hash.slice(1).split("/")[0] || "jobs";
  state.page = titles[page] ? page : "jobs";
  $$(".page").forEach(element=>{element.hidden = element.id !== "page-" + state.page;});
  $$("nav [data-page]").forEach(link=>{
    link.classList.toggle("active",link.dataset.page === state.page);
    if (link.dataset.page === state.page) link.setAttribute("aria-current","page");
    else link.removeAttribute("aria-current");
  });
  $("#breadcrumb").textContent = titles[state.page];
  document.title = `${titles[state.page]} · Work Observer`;
  if (state.page === "jobs") await loadJobs();
  if (state.page === "companies") await loadCompanies();
  if (state.page === "research") {updateResearchScope();await loadResearchHistory();}
  if (state.page === "memory") await loadMemories();
  if (state.page === "matches") await loadMatchPreferences();
  if (state.page === "retrieval") await loadStrategies();
  if (state.page === "operations") await loadOperations();
  if (state.page === "reports") await loadReports();
}

$("#filter-form").addEventListener("submit",event=>{event.preventDefault();state.filters=filterValues();state.offset=0;loadJobs();});
$("#filter-form").addEventListener("reset",()=>{state.filters={};state.offset=0;setTimeout(loadJobs,0);});
$("#prev-page").addEventListener("click",()=>{state.offset=Math.max(0,state.offset-state.limit);loadJobs();});
$("#next-page").addEventListener("click",()=>{state.offset+=state.limit;loadJobs();});
$("#clear-selection").addEventListener("click",()=>{state.selected.clear();updateSelection();});
$("#compare-selected").addEventListener("click",()=>{
  if (state.selected.size < 2 || state.selected.size > 5) return;
  state.researchIds=[...state.selected.keys()];
  $("#question").value="比较这些岗位的任务、责任、能力和工具，区分必备、加分和资料缺失。";
  location.hash="research";updateResearchScope();
});
$("#research-filtered").addEventListener("click",()=>{state.researchIds=null;location.hash="research";updateResearchScope();});
$("#company-form").addEventListener("submit",event=>{event.preventDefault();loadCompanies();});
$("#research-form").addEventListener("submit",startResearch);
$("#refresh-research-history").addEventListener("click",loadResearchHistory);
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
    await api("profiles/"+encodeURIComponent(form.dataset.domainForm)+"/correction",{method:"POST",body:JSON.stringify({domains:[...new FormData(form).getAll("domain")],reason:form.elements.reason.value.trim()})});
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
    element.disabled=true;
    try {
      await api("memories",{method:"POST",body:JSON.stringify({kind:"knowledge",source_run_id:element.dataset.knowledgeRun,claim_index:Number(element.dataset.claimIndex)})});
      element.textContent="已留作知识候选";
      notify("已保存为候选，可到“知识与偏好”核对并采纳。");
    } catch (error) {element.disabled=false;throw error;}
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
      notify(element.dataset.memoryAction === "activate" ? "知识已采纳，后续研究可参考原始依据。" : "记录已撤回，后续研究停止默认召回。");
    } catch (error) {element.disabled=false;throw error;}
  }
  if (element.dataset.prompt) $("#question").value=element.dataset.prompt;
  if (element.dataset.report) await showReport(element.dataset.report);
  if (element.hasAttribute("data-report-back")) await loadReports();
  if (element.dataset.cite) {
    const root = element.closest(".result-card");
    const details = $$("[data-evidence]",root).find(item=>item.dataset.evidence === element.dataset.cite);
    if (details) {details.open=true;details.scrollIntoView({behavior:"smooth",block:"center"});}
  }
  if (element.dataset.saveResearch) {
    element.disabled=true;
    try {
      const saved = await api("research/"+element.dataset.saveResearch+"/save",{method:"POST"});
      state.lastResult={...state.lastResult,...saved};
      renderResult(state.lastResult,$("#research-output"),state.lastRun);
      notify("研究已保存，可以在“已存研究”中查看。");
    } catch (error) {element.disabled=false;notify(error.message,true);}
  }
  } catch (error) { notify(error.message || "操作未完成，请稍后再试。",true); }
});

(async function boot(){
  await route();
  try {
    const overview = await loadOverview();
    const current = overview.active_research || sessionStorage.getItem("wo-research");
    if (current) pendingResearch(current);
  } catch (error) {notify(error.message,true);$("#model-status").textContent="本地服务读取失败";}
})();

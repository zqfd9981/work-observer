"use strict";
let currentIndustryReport=null;
const industryFacets={work:"工作结构",ability:"能力要求",threshold:"招聘门槛",change:"变化观察"};
function industryReportView(report){
  const sample=report.sample,byId=new Map(report.sources.map(row=>[row.job_id,row]));
  const basis={direct:"原文陈述，仍需核对解释",synthesis:"跨资料归纳",inference:"待验证解释"};
  const evidence=ev=>{const source=ev.source||byId.get(ev.job_id),ok=source?.availability==="verified";return `<article class="industry-evidence"><p><button type="button" class="text-button" data-job="${e(ev.job_id)}">${e(source?.title||"回查岗位")} ↗</button><span class="quiet-tag">${e(ev.role)}</span></p><blockquote>${e(ev.quote)}</blockquote><p class="form-note">原文字符 ${ev.start}–${ev.end} · 来源观察 ${e(when(source?.observed_at))} · ${ok?"归档正文与保存时内容一致":"原正文当前无法完整核验，以下保留历史引用"}</p>${ok?`<button type="button" class="text-button" data-source="${e(source.document_id)}">核对完整归档正文与版本 ↗</button>`:""}</article>`;};
  return `<article class="industry-observation"><header class="panel"><span class="eyebrow">SOURCE-BOUND INDUSTRY OBSERVATION</span><h2>${e(report.title)}</h2><p class="industry-summary">${e(report.summary)}</p><p class="form-note">${e(report.origin_label)} · 保存于 ${e(when(report.created_at))}</p>${report.source_note?`<p>${e(report.source_note)}</p>`:""}<div class="industry-sample"><div><strong>${sample.jobs}</strong><span>范围内岗位</span></div><div><strong>${sample.readable_details}</strong><span>保存时可核验正文</span></div><div><strong>${sample.missing_details}</strong><span>缺正文，保留未知</span></div><div><strong>${sample.cited_jobs}</strong><span>被引用的不同岗位</span></div></div><p class="form-note">${e(sample.notice)}<br>来源观察范围：${e(when(sample.observed_from))} 至 ${e(when(sample.observed_to))}。这是资料观察时间，不是职位发布时间或分析保存时间。</p></header>${industryEvolutionView(report)}<section class="panel"><h2>这轮要回答什么</h2><p>${e(report.question)}</p><nav class="industry-filters" aria-label="按观察维度查看"><button type="button" class="secondary small" data-industry-filter="all" aria-pressed="true">全部观察</button>${Object.entries(industryFacets).map(([key,label])=>`<button type="button" class="secondary small" data-industry-filter="${key}" aria-pressed="false">${label}</button>`).join("")}</nav><p class="form-note" id="industry-filter-note">当前展示全部观察；工作线可重叠，不把这些卡片当互斥分类占比。</p></section>${report.findings.map((row,index)=>`<section class="panel industry-finding" data-industry-facet="${e(row.facet)}" data-decision="${e(row.decision||"initial")}">${industryDecisionView(row)}<span class="quiet-tag">${e(industryFacets[row.facet])} · ${e(basis[row.basis])}</span><h2>${index+1}. ${e(row.title)}</h2><p class="industry-interpretation">${e(row.interpretation)}</p><aside class="industry-boundary"><strong>适用范围与其他解释</strong><p>${e(row.boundary)}</p></aside><details><summary>核对 ${new Set(row.evidence.map(ev=>ev.job_id)).size} 个岗位的 ${row.evidence.length} 处原文依据</summary>${row.evidence.map(evidence).join("")}</details>${industryReviewView(report,row,index)}<form data-industry-inquiry="${index}"><label>沿这条观察，继续想弄清楚什么<textarea name="question" rows="2" maxlength="1500" required>${e(row.next_question||"这条观察在所选岗位中是否成立？请回读原文，区分工作分工、要求强度及可能的反例。")}</textarea></label><button class="secondary small">带着这些岗位继续调查 ↗</button><p class="form-note">只准备所引用岗位的研究问题，不自动调用模型或扩大检索范围。</p></form></section>`).join("")}<section class="panel"><h2>现在仍不能判断什么</h2>${report.unknowns.map(text=>`<p>${e(text)}</p>`).join("")}<h3>下一轮最值得查什么</h3><ol>${report.next_questions.map(text=>`<li>${e(text)}</li>`).join("")}</ol></section><details class="panel"><summary>全部样本与资料完整性 · ${report.sources.length} 个岗位</summary><p class="form-note">来源、缺正文和无法核验的岗位仍列在这里。取得通道不是独立招聘来源，缺少原文不能当作没有要求。</p>${report.sources.map(source=>`<p><button type="button" class="text-button" data-job="${e(source.job_id)}">${e(source.title)} ↗</button> · ${source.availability==="verified"?"保存时正文可核验":source.availability==="missing_detail"?"缺正文，不能用于内容判断":"历史正文当前无法核验"} · ${e(source.source)}${source.transport?" / "+e(source.transport):""}</p>`).join("")}</details></article>`;
}
async function openIndustryReport(identity){
  const report=await api("industry/"+encodeURIComponent(identity));currentIndustryReport=report;
  $("#industry-report").innerHTML=industryReportView(report);
}
async function loadIndustry(){
  const reports=await api("industry");
  $("#industry-list").innerHTML=reports.length?`<label class="industry-picker">已保存的观察<select id="industry-report-select">${reports.map(row=>`<option value="${e(row.id)}">${e(row.title)} · ${e(when(row.created_at))}</option>`).join("")}</select></label>`:'<section class="panel"><h2>还没有已保存的行业观察</h2><p>已有岗位仍可研究。完成一轮带原文依据的跨岗位观察后，结果会出现在这里；不会用预置结论填充当前数据库。</p><a class="text-button" href="#jobs">查看已有岗位资料 ↗</a><a class="text-button" href="#research">从具体行业问题开始 ↗</a></section>';
  if(reports.length){const requested=location.hash.split("/")[1],selected=reports.find(row=>row.id===requested)?.id||reports.find(row=>row.id===currentIndustryReport?.id)?.id||reports[0].id;$("#industry-report-select").value=selected;await openIndustryReport(selected);}else{$("#industry-report").replaceChildren();currentIndustryReport=null;}
}
window.loadIndustry=loadIndustry;
$("#industry-refresh")?.addEventListener("click",()=>loadIndustry().catch(error=>notify(error.message,true)));
document.addEventListener("change",event=>{if(event.target.id==="industry-report-select")openIndustryReport(event.target.value).catch(error=>notify(error.message,true));});
document.addEventListener("click",event=>{const button=event.target.closest("[data-industry-filter]");if(!button)return;const facet=button.dataset.industryFilter;for(const row of $$("[data-industry-facet]"))row.hidden=facet!=="all"&&row.dataset.industryFacet!==facet;for(const row of $$("[data-industry-filter]"))row.setAttribute("aria-pressed",String(row===button));const count=$$("[data-industry-facet]").filter(row=>!row.hidden).length;$("#industry-filter-note").textContent=count?`当前展示 ${count} 条${facet==="all"?"观察":industryFacets[facet]}；观察不是互斥分类占比。`:`本报告没有形成${industryFacets[facet]}结论；不补造变化或趋势。`;});
document.addEventListener("submit",async event=>{if(!event.target.matches("[data-industry-inquiry]"))return;event.preventDefault();if(!currentIndustryReport)return;const button=event.submitter;button.disabled=true;try{const response=await api("industry/"+currentIndustryReport.id+"/inquiries",{method:"POST",body:JSON.stringify({finding_index:Number(event.target.dataset.industryInquiry),question:event.target.elements.question.value})});await openResearchConversation(response.project_id);notify("原岗位范围与待核问题已带入研究工作台，尚未调用模型。");}catch(error){notify(error.message,true);}finally{button.disabled=false;}});
if(location.hash.startsWith("#industry"))loadIndustry().catch(error=>notify(error.message,true));


const industryDecisions={initial:"首轮归纳",retain:"已回读，保留",revise:"已修正",withdraw:"已撤回",unresolved:"仍未知"};
function industryDecisionView(row){
  if(!row.decision)return "";
  return `<p class="industry-current"><strong>${e(industryDecisions[row.decision])}</strong>${row.needs_review?'<span class="badge">引用资料有变化，待重看</span>':""}${row.decision==="withdraw"?" · 以下判断已撤回，不再作为当前结论":row.decision==="unresolved"?" · 以下是待验证的判断，目前不能据此下结论":""}</p>`;
}
function industryEvolutionView(report){
  const evo=report.evolution;if(!evo)return "";
  return `<section class="panel industry-evolution"><span class="eyebrow">LEARN FROM NEW EVIDENCE</span><h2>持续演化：资料 → 补查 → 修订 → 再调查</h2><p>${e(evo.notice)}</p><div class="industry-evolution-stats"><strong>${evo.changes.length} 个岗位资料变化</strong><strong>${evo.pending_findings} 条观察待重看</strong><strong>${evo.revisions} 次有依据的修订</strong></div><p class="form-note">自动检查于 ${e(when(evo.checked_at))}；对比首轮保存的本地正文，无需重新抓取。</p>${evo.changes.length?evo.changes.map(row=>`<p><button class="text-button" data-job="${e(row.job_id)}">${e(row.title)} ↗</button> · ${e(row.kind)}</p>`).join(""):'<p>当前范围内未发现正文变化。也可以通过重新阅读原文、识别反例来修正认识。</p>'}<div class="result-actions"><button type="button" class="primary" data-industry-revisit>围绕变化与未知安排补查 ↗</button><button type="button" class="secondary" data-industry-check>重新检查资料</button></div><p class="form-note">补查使用本观察全部岗位，已知纠正会带入问题。不会在打开页面时自动消费模型额度。</p>${evo.inquiries.length?`<details><summary>回到已安排的补查 · ${evo.inquiries.length} 轮</summary>${evo.inquiries.slice().reverse().map(row=>`<p><a class="text-button" href="#research/${e(row.project_id)}">${e(row.question)} ↗</a><small> · ${e(when(row.created_at))}</small></p>`).join("")}<p>看完研究结果后，回到对应观察卡片，填写修订与原文依据。</p></details>`:""}</section>`;
}
function industryParagraphs(candidate){
  if(!candidate?.description)return [];
  const lines=candidate.description.split(/\r?\n/).map(text=>text.trim()).filter(text=>text.length>=8&&text.length<=1200);
  return lines.length?lines:[candidate.description.slice(0,1200)];
}
function industryQuoteOptions(candidate,selected){
  const lines=industryParagraphs(candidate);
  if(selected&&candidate?.description.includes(selected)&&!lines.includes(selected))lines.unshift(selected);
  return lines.map((text,i)=>`<option value="${i}" data-quote="${e(text)}" ${text===selected?"selected":""}>${e(text.slice(0,150))}${text.length>150?"…":""}</option>`).join("");
}
function industryReviewView(report,row,index){
  const candidates=report.evolution?.candidates.filter(item=>item.description)||[];
  if(!report.evolution)return "";
  const selected=candidates.find(item=>item.source.job_id===row.evidence[0]?.job_id)||candidates[0];
  const history=row.history||[];
  return `<details class="industry-review"><summary>回读后更新这条观察${history.length?` · 已有 ${history.length} 次修订`:""}</summary><p>核对原文，写明判断为什么改变。修订的是认识，不会自动记成行业趋势。</p>${history.length?`<h3>判断如何演化</h3>${history.slice().reverse().map(event=>`<article class="industry-history"><strong>${e(industryDecisions[event.decision])} · ${e(when(event.created_at))}</strong><p>之前：${e(event.previous_interpretation)}</p><p>这次：${e(event.interpretation)}</p><p><strong>理由：</strong>${e(event.reason)}</p><p><strong>适用范围：</strong>${e(event.boundary)}</p>${event.evidence.map(ev=>`<blockquote>${e(ev.quote)}</blockquote><button class="text-button" data-source="${e(ev.source.document_id)}">核对当时的完整原文 ↗</button>`).join("")}<p>下一轮：${e(event.next_question)}</p></article>`).join("")}`:""}${candidates.length?`<form data-industry-revision="${index}"><label>这次回读的结论<select name="decision"><option value="revise">修正判断或适用范围</option><option value="retain">证据支持，保留判断</option><option value="withdraw">撤回这条判断</option><option value="unresolved">有疑问，暂时保留未知</option></select></label><label>当前判断<textarea name="interpretation" maxlength="1200" required rows="4">${e(row.interpretation)}</textarea></label><label>适用范围与保留条件<textarea name="boundary" maxlength="600" required rows="3">${e(row.boundary)}</textarea></label><label>修订理由：新证据、反例或读法纠正<textarea name="reason" minlength="5" maxlength="800" required rows="2" placeholder="例如：原文写的是可选一个专攻方向，不能视为全部必备。"></textarea></label><label>核对哪个岗位<select name="evidence_job">${candidates.map(item=>`<option value="${e(item.source.job_id)}" ${item===selected?"selected":""}>${e(item.source.title)}</option>`).join("")}</select></label><label>点选一段当前原文作为依据<select name="evidence_quote">${industryQuoteOptions(selected,row.evidence[0]?.quote)}</select></label><details><summary>查看当前所选岗位的完整正文</summary><pre data-industry-current-body>${e(selected?.description)}</pre></details><label>根据这次认识，下一轮应查什么<textarea name="next_question" minlength="5" maxlength="600" required rows="2">${e(row.next_question||report.next_questions[0]||"继续核对交付标准与适用范围。")}</textarea></label><button class="primary">保存修订，更新当前观察</button></form>`:'<p>当前没有可核验正文，请先补齐或恢复资料。</p>'}</details>`;
}
document.addEventListener("change",event=>{
  if(event.target.name!=="evidence_job")return;
  const form=event.target.closest("[data-industry-revision]");if(!form)return;
  const candidate=currentIndustryReport.evolution.candidates.find(item=>item.source.job_id===event.target.value);
  form.elements.evidence_quote.innerHTML=industryQuoteOptions(candidate);
  form.querySelector("[data-industry-current-body]").textContent=candidate?.description||"当前正文不可读";
});
document.addEventListener("submit",async event=>{
  const form=event.target;if(!form.matches("[data-industry-revision]"))return;
  event.preventDefault();const button=event.submitter||form.querySelector('button[type="submit"],button.primary');button.disabled=true;
  const report=currentIndustryReport,index=Number(form.dataset.industryRevision),row=report.findings[index];
  try{
    const candidate=report.evolution.candidates.find(item=>item.source.job_id===form.elements.evidence_job.value);
    const quote=form.elements.evidence_quote.selectedOptions[0]?.dataset.quote;
    const selected={job_id:candidate.source.job_id,quote,role:"本轮回读的原文依据"};
    const evidence=[selected,...row.evidence.filter(ev=>report.evolution.candidates.some(item=>item.source.job_id===ev.job_id&&item.description.includes(ev.quote)))].filter((ev,i,all)=>all.findIndex(other=>other.job_id===ev.job_id&&other.quote===ev.quote)===i).slice(0,8).map(({job_id,quote,role})=>({job_id,quote,role}));
    const data={finding_index:index,decision:form.elements.decision.value,reason:form.elements.reason.value,interpretation:form.elements.interpretation.value,boundary:form.elements.boundary.value,next_question:form.elements.next_question.value,evidence};
    const revised=await api("industry/"+report.id+"/revisions",{method:"POST",body:JSON.stringify(data)});
    currentIndustryReport=revised;$("#industry-report").innerHTML=industryReportView(revised);notify("修订已保存；后续调查会沿用当前判断、纠正理由和下一轮问题。");
  }catch(error){notify(error.message,true);}finally{button.disabled=false;}
});
document.addEventListener("click",async event=>{
  const refresh=event.target.closest("[data-industry-check]"),revisit=event.target.closest("[data-industry-revisit]");
  if(!refresh&&!revisit)return;const button=refresh||revisit;button.disabled=true;
  try{
    if(refresh){await openIndustryReport(currentIndustryReport.id);notify("已检查当前本地归档。");return;}
    const question="回读本观察全部已有岗位，检查资料变化、已知纠正和未知问题，寻找支持与反例；分别说明哪些判断可保留、需修正、应撤回或仍未知。区分认识变化与行业变化，并给出精确原文依据。";
    const data=await api("industry/"+currentIndustryReport.id+"/inquiries",{method:"POST",body:JSON.stringify({question})});
    await openResearchConversation(data.project_id);notify("补查已安排，完成后可回到行业观察更新判断。");
  }catch(error){notify(error.message,true);}finally{button.disabled=false;}
});

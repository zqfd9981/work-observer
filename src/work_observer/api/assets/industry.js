"use strict";
let currentIndustryReport=null;
let industryRenderedRoute=null;
const industryFacets={work:"工作结构",ability:"能力要求",threshold:"招聘门槛",change:"变化观察"};
function industryExcerpt(text,limit=140){
  const value=String(text||"").replace(/\s+/g," ").trim();
  return value.length>limit?value.slice(0,limit)+"…":value;
}
function industryFindingLink(report,index){return `#industry/${report.id}/findings/${index}`;}
function industrySelectedFinding(report){
  const parts=location.hash.split("/");
  return parts[2]==="findings"&&/^\d+$/.test(parts[3]||"")&&Number(parts[3])<report.findings.length?Number(parts[3]):null;
}
function industryEvidenceView(ev,report){
  const source=ev.source||report.sources.find(row=>row.job_id===ev.job_id),ok=source?.availability==="verified";
  return `<details class="industry-citation"><summary><span><strong>${e(source?.title||"岗位原文")}</strong><small>${e(ev.role||"原文依据")}</small></span><span class="citation-toggle" aria-hidden="true">＋</span></summary><div class="industry-citation-body"><blockquote>${e(ev.quote)}</blockquote>${ok?`<button type="button" class="text-button" data-source="${e(source.document_id)}">阅读完整原文 ↗</button>`:'<p class="industry-unavailable">此处保留历史引用，原文当前无法核验。</p>'}<button type="button" class="text-button" data-job="${e(ev.job_id)}">查看岗位 ↗</button><details class="industry-provenance"><summary>归档信息</summary><p>资料观察于 ${e(when(source?.observed_at))} · 原文字符 ${ev.start}–${ev.end}</p><p>${ok?"归档正文与引用时的内容一致":"历史正文当前无法核验"}</p></details></div></details>`;
}
function industryScopeView(report){
  return `<details class="industry-scope"><summary>样本与观察范围 <span>${report.sample.jobs} 个岗位</span></summary><div><h3>这份观察能说明什么</h3><p>${e(report.sample.notice)}</p><p>${e(report.source_note||"")}</p><p>${e(report.origin_label)}。资料观察时间 ${e(when(report.sample.observed_from))} 至 ${e(when(report.sample.observed_to))}，不等于职位发布时间。</p><h3>目前还不能判断</h3><ul>${report.unknowns.map(text=>`<li>${e(text)}</li>`).join("")}</ul><details><summary>查看全部样本与资料完整性</summary>${report.sources.map(source=>`<p><button type="button" class="text-button" data-job="${e(source.job_id)}">${e(source.title)} ↗</button><small>${source.availability==="verified"?"归档正文可核验":source.availability==="missing_detail"?"缺正文，不能用于内容判断":"历史正文当前无法核验"}</small></p>`).join("")}</details><details><summary>首轮概述与保存信息</summary><p>${e(report.summary)}</p><p>保存于 ${e(when(report.created_at))}；保存时可核验正文 ${report.sample.readable_details} 份，缺正文 ${report.sample.missing_details} 份。</p></details></div></details>`;
}
function industryHistoryView(row){
  const history=row.history||[];
  if(!history.length)return "";
  return `<details class="industry-timeline"><summary>认识如何变化 <span>${history.length} 次修订</span></summary>${history.slice().reverse().map(event=>`<article class="industry-history"><div><strong>${e(industryDecisions[event.decision])}</strong><time>${e(when(event.created_at))}</time></div><h4>为什么更新</h4><p>${e(event.reason)}</p><details><summary>对比更新前后的判断</summary><p><strong>之前</strong><br>${e(event.previous_interpretation)}</p><p><strong>这次</strong><br>${e(event.interpretation)}</p><p><strong>适用范围</strong><br>${e(event.boundary)}</p></details><details><summary>这次修订的原文依据</summary>${event.evidence.map(ev=>`<blockquote>${e(ev.quote)}</blockquote><button type="button" class="text-button" data-source="${e(ev.source.document_id)}">阅读当时的完整原文 ↗</button>`).join("")}</details><p class="industry-next-question"><strong>下一轮问题</strong><br>${e(event.next_question)}</p></article>`).join("")}</details>`;
}
function industryOverviewView(report){
  const sample=report.sample,evo=report.evolution;
  const sourceNames=Object.keys(sample.sources||{}).map(key=>({boss:"BOSS直聘",manual:"补充资料"})[key]||key).join("、");
  return `<article class="industry-reader"><a class="industry-back" href="#industry">← 返回开始</a><header class="industry-hero"><span class="industry-kicker">本期观察${sourceNames?" · "+e(sourceNames):""}</span><h2>${e(report.title)}</h2><p>${e(report.question)}</p><div class="industry-scope-line"><span><strong>${sample.jobs}</strong> 个岗位</span><span><strong>${sample.readable_details}</strong> 份正文</span><span><strong>${sample.missing_details}</strong> 个待补全</span><span class="industry-scope-caution">样本观察，非全行业趋势</span></div></header><div class="industry-home-layout"><section class="industry-discoveries" aria-labelledby="industry-findings-title"><div class="industry-section-heading"><h2 id="industry-findings-title">本期发现 <span>${report.findings.length}</span></h2><span>选择一条，了解它的依据</span></div><div class="industry-filters" role="group" aria-label="按观察维度查看"><button type="button" data-industry-filter="all" aria-pressed="true">全部</button>${Object.entries(industryFacets).filter(([key])=>report.findings.some(row=>row.facet===key)).map(([key,label])=>`<button type="button" data-industry-filter="${key}" aria-pressed="false">${label}</button>`).join("")}</div><p class="sr-only" id="industry-filter-note" role="status">展示全部观察</p><div class="industry-card-list">${report.findings.map((row,index)=>`<a class="industry-card" href="${industryFindingLink(report,index)}" data-industry-facet="${e(row.facet)}" data-decision="${e(row.decision||"initial")}"><div class="industry-card-top"><span>${e(industryFacets[row.facet])}</span>${row.needs_review?'<span class="industry-state pending">资料有变化</span>':row.decision&&row.decision!=="initial"?`<span class="industry-state">${e(industryDecisions[row.decision])}</span>`:""}</div><h3>${e(row.title)}</h3><p>${row.decision==="withdraw"?"此判断已撤回，不再作为当前结论。 ":row.decision==="unresolved"?"尚未形成确定判断。 ":""}${e(industryExcerpt(row.interpretation))}</p><footer><span>${new Set(row.evidence.map(ev=>ev.job_id)).size} 个岗位提供依据${row.history?.length?` · ${row.history.length} 次修订`:""}</span><span class="industry-card-action">查看发现 <span aria-hidden="true">→</span></span></footer></a>`).join("")}</div><p class="industry-reading-note">这些发现来自对已读正文的归纳，工作线可以重叠。${sample.missing_details} 个缺正文岗位不参与内容判断。</p></section><aside class="industry-home-aside">${industryEvolutionView(report)}<section class="industry-aside-section"><h3>接下来值得了解</h3><ol class="industry-question-list">${report.next_questions.slice(0,3).map(text=>`<li>${e(industryExcerpt(text,100))}</li>`).join("")}</ol><button type="button" class="secondary full" data-industry-revisit>继续研究这个主题 ↗</button></section><a class="industry-library-link" href="#jobs">浏览岗位资料 <span aria-hidden="true">→</span><small>回到具体岗位，形成自己的判断</small></a></aside></div>${industryScopeView(report)}</article>`;
}
function industryDetailView(report,index){
  const row=report.findings[index],count=new Set(row.evidence.map(ev=>ev.job_id)).size;
  const basis={direct:"原文陈述",synthesis:"跨资料归纳",inference:"待验证解释"};
  return `<article class="industry-reader industry-detail"><a class="industry-back" href="#industry/${e(report.id)}">← 返回本期发现</a><header class="industry-detail-heading"><div><span class="industry-kicker">${e(industryFacets[row.facet])} · ${e(basis[row.basis]||"研究归纳")}</span><h2>${e(row.title)}</h2></div>${industryDecisionView(row)}</header><div class="industry-detail-layout"><div class="industry-detail-main"><section class="industry-current-reading" data-decision="${e(row.decision||"initial")}"><h3>当前判断</h3>${row.decision==="withdraw"?'<p class="industry-decision-notice">已撤回，不再作为当前结论。以下保留当时的判断供回看。</p>':row.decision==="unresolved"?'<p class="industry-decision-notice">这一判断仍有疑问，需要进一步核实。</p>':""}<p class="industry-interpretation">${e(row.interpretation)}</p><div class="industry-reading-boundary"><h4>适用范围</h4><p>${e(row.boundary)}</p></div></section><section class="industry-evidence-section"><div class="industry-section-heading"><h3>这条发现依据什么</h3><span>${count} 个岗位 · ${row.evidence.length} 段原文</span></div>${row.evidence.map(ev=>industryEvidenceView(ev,report)).join("")}</section>${industryHistoryView(row)}</div><aside class="industry-detail-aside"><section class="industry-ask"><span class="industry-kicker">沿着发现继续了解</span><h3>把问题带回岗位</h3><form data-industry-inquiry="${index}"><label>你想进一步弄清什么<textarea name="question" rows="4" maxlength="1500" required>${e(row.next_question||"这条观察在所选岗位中是否成立？请回读原文，寻找支持与反例。")}</textarea></label><button class="primary full">继续研究 ↗</button><p>使用这条发现引用的 ${count} 个岗位。</p></form></section>${industryReviewView(report,row,index)}<a class="industry-back subtle" href="#industry/${e(report.id)}">查看其他发现 →</a></aside></div></article>`;
}
const industryTaskExamples=[
  {label:"检验我的看法",question:"我以为Agent开发主要就是用框架和写提示词。基于已有招聘资料，这些岗位共同反映出怎样的工作与能力要求？岗位为什么分化，我的理解差在哪，对面试准备有什么影响？"},
  {label:"比较工作分工",question:"请基于已有招聘JD，对比Agent应用开发与平台开发的工作内容、交付物和能力要求，给出原文依据，并说明哪些仍不能确定。"},
  {label:"梳理招聘门槛",question:"请研究已有Agent岗位的经验与能力门槛，区分后端经验、AI经验、大模型应用经验，以及必备要求、可选方向和加分项，给出原文依据。"},
  {label:"检查资料变化",question:"请检查已有归档能否支持Agent岗位工作要求发生变化的判断，区分岗位原文变化、样本差异和认识修订；证据不足时明确保留未知。"}
];
function industryStartView(report){
  return `<section class="industry-start industry-agent"><header><h1>你对岗位的理解，和招聘要求一致吗？</h1><p>说说你的看法，或直接提问。对照多份招聘资料，发现共性、差异与认知偏差。</p></header><form data-industry-agent><label class="sr-only" for="industry-agent-question">你的看法或问题</label><textarea id="industry-agent-question" name="question" rows="4" maxlength="1500" required placeholder="例如：我以为 Agent 开发主要是用框架、写提示词。实际岗位还要求什么？"></textarea><div class="industry-agent-actions"><button type="button" class="text-button" data-action="import">＋ 补充 JD</button><button type="submit" class="primary">开始研究 <span aria-hidden="true">↑</span></button></div></form><div class="industry-agent-examples" aria-label="研究任务示例">${industryTaskExamples.map((row,index)=>`<button type="button" data-industry-example="${index}">${e(row.label)} <span aria-hidden="true">↗</span></button>`).join("")}</div><p class="industry-agent-scope">使用当前观察范围内的 ${report.sample.jobs} 个岗位 · ${report.sample.readable_details} 份正文 <a href="#jobs">查看资料</a></p><a class="industry-agent-result" href="#industry/${e(report.id)}">查看已完成的行业观察 →</a></section>`;
}
function industryReportView(report,selectedIndex=industrySelectedFinding(report)){
  if(!location.hash.split("/")[1])return industryStartView(report);
  return selectedIndex===null?industryOverviewView(report):industryDetailView(report,selectedIndex);
}
function renderIndustryReport(report){
  const input=$("#industry-agent-question"),draft=input?.value||"";
  const editing=input&&document.activeElement===input;
  const selection=editing?[input.selectionStart,input.selectionEnd]:null;
  $("#industry-report").innerHTML=industryReportView(report);
  const next=$("#industry-agent-question");
  if(next&&draft){next.value=draft;if(editing){next.focus();next.setSelectionRange(...selection);}}
  if(industryRenderedRoute!==location.hash){
    $("#page-industry")?.scrollIntoView?.({block:"start",behavior:"auto"});
    industryRenderedRoute=location.hash;
  }
}
async function openIndustryReport(identity){
  const report=await api("industry/"+encodeURIComponent(identity));currentIndustryReport=report;
  renderIndustryReport(report);
}
async function loadIndustry(){
  const reports=await api("industry");
  $("#industry-list").innerHTML=reports.length?`<label class="industry-picker" ${reports.length===1?"hidden":""}>选择观察<select id="industry-report-select">${reports.map(row=>`<option value="${e(row.id)}">${e(row.title)} · ${e(when(row.created_at))}</option>`).join("")}</select></label>`:'<section class="panel"><h2>还没有已保存的行业观察</h2><p>已有岗位仍可研究。完成一轮带原文依据的跨岗位观察后，结果会出现在这里；不会用预置结论填充当前数据库。</p><a class="text-button" href="#jobs">查看已有岗位资料 ↗</a><a class="text-button" href="#research">从具体行业问题开始 ↗</a></section>';
  if(reports.length){const requested=location.hash.split("/")[1],selected=reports.find(row=>row.id===requested)?.id||reports.find(row=>row.id===currentIndustryReport?.id)?.id||reports[0].id;$("#industry-report-select").value=selected;await openIndustryReport(selected);}else{$("#industry-report").replaceChildren();currentIndustryReport=null;}
}
window.loadIndustry=loadIndustry;
$("#industry-refresh")?.addEventListener("click",()=>loadIndustry().catch(error=>notify(error.message,true)));
document.addEventListener("change",event=>{if(event.target.id==="industry-report-select")openIndustryReport(event.target.value).catch(error=>notify(error.message,true));});
document.addEventListener("click",event=>{const button=event.target.closest("[data-industry-filter]");if(!button)return;const facet=button.dataset.industryFilter;for(const row of $$("[data-industry-facet]"))row.hidden=facet!=="all"&&row.dataset.industryFacet!==facet;for(const row of $$("[data-industry-filter]"))row.setAttribute("aria-pressed",String(row===button));const count=$$("[data-industry-facet]").filter(row=>!row.hidden).length;$("#industry-filter-note").textContent=count?`当前展示 ${count} 条${facet==="all"?"观察":industryFacets[facet]}；观察不是互斥分类占比。`:`本报告没有形成${industryFacets[facet]}结论；不补造变化或趋势。`;});
document.addEventListener("submit",async event=>{if(!event.target.matches("[data-industry-inquiry]"))return;event.preventDefault();if(!currentIndustryReport)return;const button=event.submitter;button.disabled=true;try{const response=await api("industry/"+currentIndustryReport.id+"/inquiries",{method:"POST",body:JSON.stringify({finding_index:Number(event.target.dataset.industryInquiry),question:event.target.elements.question.value})});await openResearchConversation(response.project_id);notify("已带上相关岗位和问题，可以继续研究。");}catch(error){notify(error.message,true);}finally{button.disabled=false;}});



const industryDecisions={initial:"首轮归纳",retain:"已回读，保留",revise:"已修正",withdraw:"已撤回",unresolved:"仍未知"};
function industryDecisionView(row){
  if(!row.decision)return "";
  return `<p class="industry-current"><strong>${e(industryDecisions[row.decision])}</strong>${row.needs_review?'<span class="badge">引用资料有变化，待重看</span>':""}${row.decision==="withdraw"?" · 以下判断已撤回，不再作为当前结论":row.decision==="unresolved"?" · 以下是待验证的判断，目前不能据此下结论":""}</p>`;
}
function industryEvolutionView(report){
  const evo=report.evolution;if(!evo)return "";
  const latest=report.findings.flatMap((row,index)=>(row.history||[]).map(event=>({...event,index}))).sort((a,b)=>b.created_at.localeCompare(a.created_at))[0];
  return `<section class="industry-aside-section industry-updates"><div class="industry-section-heading"><h3>观察动态</h3><button type="button" class="text-button" data-industry-check>检查更新</button></div>${evo.pending_findings?`<p class="industry-update-alert">${evo.pending_findings} 条发现的资料有变化，值得重新看看。</p>`:'<p class="industry-update-quiet">当前引用资料没有待复核的变化</p>'}${latest?`<a class="industry-latest-update" href="${industryFindingLink(report,latest.index)}"><span>最近修订 · ${e(when(latest.created_at))}</span><p>${e(industryExcerpt(latest.reason,90))}</p><strong>查看这次更新 →</strong></a>`:'<p class="industry-update-quiet">后续的修订会保留在这里。</p>'}<details class="industry-update-details"><summary>查看更新记录</summary><p>${evo.changes.length} 个岗位资料与首轮不同 · ${evo.revisions} 次认识修订</p><p>${e(evo.notice)}</p>${evo.changes.map(row=>`<p><button type="button" class="text-button" data-job="${e(row.job_id)}">${e(row.title)}</button> · ${e(row.kind)}</p>`).join("")}<p>本地归档检查于 ${e(when(evo.checked_at))}</p><a class="text-button" href="#updates">比较不同时点的资料 ↗</a>${evo.inquiries.length?`<h4>已安排的研究</h4>${evo.inquiries.slice().reverse().map(row=>`<p><a href="#research/${e(row.project_id)}">${e(industryExcerpt(row.question,90))} ↗</a></p>`).join("")}`:""}</details></section>`;
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
  return `<details class="industry-review"><summary>补充或修正这条观察</summary><p>回读原文后，说明你的判断和依据。</p>${candidates.length?`<form data-industry-revision="${index}"><label>这次回读的结论<select name="decision"><option value="revise">修正判断或适用范围</option><option value="retain">证据支持，保留判断</option><option value="withdraw">撤回这条判断</option><option value="unresolved">有疑问，暂时保留未知</option></select></label><label>当前判断<textarea name="interpretation" maxlength="1200" required rows="4">${e(row.interpretation)}</textarea></label><label>适用范围与保留条件<textarea name="boundary" maxlength="600" required rows="3">${e(row.boundary)}</textarea></label><label>修订理由：新证据、反例或读法纠正<textarea name="reason" minlength="5" maxlength="800" required rows="2" placeholder="例如：原文写的是可选一个专攻方向，不能视为全部必备。"></textarea></label><label>核对哪个岗位<select name="evidence_job">${candidates.map(item=>`<option value="${e(item.source.job_id)}" ${item===selected?"selected":""}>${e(item.source.title)}</option>`).join("")}</select></label><label>点选一段当前原文作为依据<select name="evidence_quote">${industryQuoteOptions(selected,row.evidence[0]?.quote)}</select></label><details><summary>查看当前所选岗位的完整正文</summary><pre data-industry-current-body>${e(selected?.description)}</pre></details><label>根据这次认识，下一轮应查什么<textarea name="next_question" minlength="5" maxlength="600" required rows="2">${e(row.next_question||report.next_questions[0]||"继续核对交付标准与适用范围。")}</textarea></label><button class="primary">保存修订，更新当前观察</button></form>`:'<p>当前没有可核验正文，请先补齐或恢复资料。</p>'}</details>`;
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
    currentIndustryReport=revised;renderIndustryReport(revised);notify("观察已更新，原判断与修订理由已保留。");
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

if(location.hash.startsWith("#industry"))loadIndustry().catch(error=>notify(error.message,true));

document.addEventListener("click",event=>{
  const button=event.target.closest("[data-industry-example]");if(!button)return;
  const example=industryTaskExamples[Number(button.dataset.industryExample)];if(!example)return;
  const input=$("#industry-agent-question");input.value=example.question;input.focus();
});
document.addEventListener("submit",async event=>{
  const form=event.target;if(!form.matches("[data-industry-agent]"))return;
  event.preventDefault();const question=form.elements.question.value.trim();if(!question||!currentIndustryReport)return;
  const button=event.submitter||form.querySelector('button[type="submit"]');button.disabled=true;button.textContent="正在开始…";
  try{await window.startIndustryResearchTask(question,currentIndustryReport.sources.map(row=>row.job_id));}
  catch(error){notify(error.message,true);}
  finally{if(button.isConnected){button.disabled=false;button.innerHTML='开始研究 <span aria-hidden="true">↑</span>';}}
});

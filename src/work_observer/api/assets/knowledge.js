"use strict";

(() => {
  const root = document.querySelector("#page-knowledge");
  if (!root) return;
  const find = selector => root.querySelector(selector);
  const knowledge = {domains:[], relations:[], evidence:[], collectionInput:null, collectionOffset:0};
  let requestedProject = null;
  const projectId = () => find("#knowledge-project").value || null;
  const labels = {candidate:"待审核", active:"已采纳", conflicted:"存在待审冲突", rejected:"已拒绝", withdrawn:"已撤回", superseded:"已有新版本", retired:"已合并或拆分", invalidated:"上游研究已失效"};
  const dimensions = {business:"业务背景",task:"任务",deliverable:"交付物",responsibility:"责任",ability:"能力",tool:"工具"};
  const parseTerms = value => value.split(/[,，、;；\n]/).map(item=>item.trim()).filter(Boolean);
  const dateValue = value => value ? new Date(value + "+08:00").toISOString() : null;
  const post = (path, data) => api(path, {method:"POST", body:JSON.stringify(data)});
  function feedback(target, error) { target.innerHTML = errorBox(error); notify(error.message,true); }
  function reviewControls(kind,row) {
    if (!["candidate","active","conflicted"].includes(row.status)) return "";
    const candidates=row.status!=="active";
    return `<div class="result-actions"><input data-review-reason="${e(row.id)}" maxlength="1200" aria-label="审核说明" placeholder="填写核对原文后的审核说明" required>${candidates?`<button class="secondary small" data-knowledge-review="${kind}" data-id="${e(row.id)}" data-decision="accept">采纳</button><button class="secondary small" data-knowledge-review="${kind}" data-id="${e(row.id)}" data-decision="reject">拒绝</button>`:""}<button class="secondary small" data-knowledge-review="${kind}" data-id="${e(row.id)}" data-decision="withdraw">撤回</button></div>`;
  }
  function evidenceCard(item,index,selection=true) {
    const origin=item.evidence_kind==="public_document"?"公开网页正文":sourceLabel(item);
    return `<article class="panel"><strong>${e(item.title||"来源原文")}</strong> ${badge(origin)}<p class="form-note">${e(item.company||item.publisher||"")} · 取得于 ${e(when(item.observed_at))} · 来源发布时间 ${e(when(item.source_published_at))}</p><blockquote>${e(item.quote)}</blockquote><p class="form-note">${e(item.scope_note||"引用保留原文位置与版本；请核对它是否真正支持你的表述。")}</p>${selection?`<label>该片段的用途<select data-evidence-index="${index}"><option value="">不用于关系候选</option><option value="support">支持证据</option><option value="counter">反例</option></select></label>`:""}</article>`;
  }
  function renderDomains() {
    find("#knowledge-domains").innerHTML=knowledge.domains.length?knowledge.domains.map(row=>`<article class="panel"><h3>${e(row.name)} ${badge("第 "+row.version+" 版")} ${badge(labels[row.status]||row.status)}</h3><p>${e(row.definition)}</p><dl>${detailData("包括",row.inclusion)}${detailData("排除或未知",row.exclusion)}</dl>${row.related_ids.length?`<p class="form-note">本版本保留 ${e(row.related_ids.length)} 个关联定义的合并或拆分关系。</p>`:""}${row.source_context?.run_id?`<p class="form-note">来源于研究地图 · ${e(({direct:"原文明示",synthesis:"研究归纳",inference:"研究推断"})[row.source_context.basis]||"性质待核")}<br>${e(row.source_context.scope_note||"")}</p><button class="text-button" data-open-run="${e(row.source_context.run_id)}">核对原地图、支撑判断与原文 ↗</button>${row.stale?`<p class="error-box">${(row.stale_reasons||[]).map(e).join("；")}</p>`:""}`:""}${row.review_reason?`<p class="form-note">审核：${e(row.review_reason)}</p>`:""}<button class="secondary small" data-domain-revise="${e(row.id)}">修订此定义</button>${reviewControls("domains",row)}</article>`).join(""):empty("还没有领域定义","可先创建具体业务边界，再核对并采纳；未知岗位不会强制归类。");
    const options=knowledge.domains.map(row=>`<option value="${e(row.id)}">${e(row.name)} · 第${row.version}版 · ${e(labels[row.status]||row.status)}</option>`).join("");
    find('[name="related_ids"]').innerHTML=options;
    find('#knowledge-relation-form [name="domain_id"]').innerHTML='<option value="">选择领域定义</option>'+options;
    find('#knowledge-collection-form [name="domain_id"]').innerHTML='<option value="">所有领域与未知</option>'+options;
    find('#knowledge-correction-form [name="domain_ids"]').innerHTML=knowledge.domains.filter(row=>row.status==="active").map(row=>`<option value="${e(row.id)}">${e(row.name)} · 第${row.version}版</option>`).join("");
  }
  function renderRelations() {
    find("#knowledge-relations").innerHTML=knowledge.relations.length?knowledge.relations.map(row=>`<article class="panel"><h3>${e(dimensions[row.source_kind])} → ${e(dimensions[row.target_kind])} ${badge(labels[row.status]||row.status)}${row.stale?badge("需要重新核对","amber"):""}</h3><p>${e(row.source_text)} → ${e(row.target_text)}</p>${row.scope.research_map?`<p><strong>解释性质：</strong>${e(({direct:"原文明示",synthesis:"研究归纳",inference:"研究推断"})[row.scope.research_map.basis]||"待核对")}</p><p>${e(row.scope.research_map.rationale)}</p><p><strong>迁移边界：</strong>${e(row.scope.research_map.transfer_limit)}</p>`:""}${row.source_run_id?`<button class="text-button" data-open-run="${e(row.source_run_id)}">核对来源研究 ↗</button>`:""}<p class="form-note">支持范围：${e(row.scope.job_ids?.length||0)} 个岗位、${e(row.scope.public_document_ids?.length||0)} 份公开材料；反例 ${e(row.counterevidence.length)} 条。</p>${row.stale_reasons.length?`<p class="form-note">${row.stale_reasons.map(e).join("；")}</p>`:""}<details><summary>核对支持原文与反例</summary>${row.evidence.map(item=>evidenceCard(item,0,false)).join("")}${row.counterevidence.length?"<h4>反例（不计为支持范围）</h4>":""}${row.counterevidence.map(item=>evidenceCard(item,0,false)).join("")}</details>${reviewControls("relations",row)}</article>`).join(""):empty("还没有关系候选","检索原文后选择支持证据和反例，明确两端表述，再保存候选审核。");
    find('[name="conflict_ids"]').innerHTML=knowledge.relations.filter(row=>["active","candidate","conflicted"].includes(row.status)).map(row=>`<option value="${e(row.id)}">${e(row.source_text)} → ${e(row.target_text)}</option>`).join("");
  }
  window.loadKnowledge = async () => {
    try {
      const history=find("#knowledge-history").checked;
      const selected=requestedProject ?? projectId(); requestedProject=null;
      const projects=await api("projects");
      find("#knowledge-project").innerHTML='<option value="">通用范围</option>'+projects.filter(row=>row.state==="active").map(row=>`<option value="${e(row.id)}">${e(row.title)}</option>`).join("");
      find("#knowledge-project").value=selected||"";
      const scope=projectId()?"&project_id="+encodeURIComponent(projectId()):"";
      const [domains,relations]=await Promise.all([api("knowledge/domains?include_history="+history),api("knowledge/relations?include_history="+history+scope)]);
      knowledge.domains=domains.domains.filter(row=>!row.source_context?.project_id||row.source_context.project_id===projectId()); knowledge.relations=relations.relations;
      renderDomains(); renderRelations();
      find('#knowledge-correction-form [name="job_id"]').innerHTML='<option value="">选择岗位</option>'+[...state.jobs.values()].map(row=>`<option value="${e(row.id)}">${e(row.title)} · ${e(row.company||"公司未知")}</option>`).join("");
    } catch(error) { feedback(find("#knowledge-domains"),error); }
  };
  document.addEventListener("click",event=>{
    const link=event.target.closest("[data-knowledge-project]");if(!link)return;
    requestedProject=link.dataset.knowledgeProject||"";
    if(state.page==="knowledge")window.loadKnowledge();
  });
  find("#knowledge-project").addEventListener("change",()=>{knowledge.evidence=[];find("#unified-results").innerHTML="";knowledge.collectionInput=null;find("#knowledge-collection").innerHTML="";window.loadKnowledge();});
  find("#knowledge-refresh").addEventListener("click",window.loadKnowledge);
  find("#knowledge-history").addEventListener("change",window.loadKnowledge);
  find("#unified-form").addEventListener("submit",async event=>{
    event.preventDefault(); const form=new FormData(event.target); const button=event.submitter; button.disabled=true;
    find("#unified-results").innerHTML='<p class="form-note" role="status">正在核对资料范围与来源完整性…</p>';
    try {
      const selected=form.has("selected_only");
      if(selected&&!state.selected.size) throw new Error("请先在岗位页面勾选岗位，或取消只查已勾选岗位。");
      const result=await post("retrieval/unified",{terms:parseTerms(form.get("terms")),filters:state.filters,job_ids:selected?[...state.selected.keys()]:null,as_of:dateValue(form.get("as_of")),aliases:form.has("aliases"),project_id:projectId()});
      knowledge.evidence=result.evidence;
      find("#unified-results").innerHTML=`<div class="panel"><h3>找到 ${e(result.matching_jobs)} 个岗位、${e(result.matching_public_documents)} 份公开材料</h3><p>完整岗位分母 ${e(result.sample.denominator)}；条件未知 ${e(result.sample.unknown)}；公开材料范围 ${e(result.public_scope_total)}。本次展示 ${e(result.evidence.length)} 个片段${result.truncated?"，受上下文上限限制":""}。</p>${result.excluded_integrity_ids.length?`<p class="form-note">${e(result.excluded_integrity_ids.length)} 份资料因缺失或完整性变化未用于原文引用。</p>`:""}</div>${result.evidence.length?result.evidence.map((item,index)=>evidenceCard(item,index)).join(""):empty("没有可展示的原文命中","可换一个词或补充资料；未命中不表示岗位没有该项要求。")}${result.knowledge.length?'<h3>相关已采纳认识（派生，仍须核对原文）</h3>'+result.knowledge.map(row=>`<article class="panel"><p>${e(row.content)}</p><details><summary>核对原始依据</summary>${row.evidence.map(item=>evidenceCard(item,0,false)).join("")}</details></article>`).join(""):""}`;
    } catch(error) { feedback(find("#unified-results"),error); }
    finally {button.disabled=false;}
  });
  find("#knowledge-domain-form").addEventListener("submit",async event=>{
    event.preventDefault(); const form=new FormData(event.target); const button=event.submitter; button.disabled=true;
    try {
      await post("knowledge/domains",{domain_key:form.get("domain_key")||("domain_"+crypto.randomUUID().replaceAll("-","")),name:form.get("name"),definition:form.get("definition"),inclusion:form.get("inclusion"),exclusion:form.get("exclusion"),previous_id:form.get("previous_id")||null,change_kind:form.get("change_kind"),related_ids:form.getAll("related_ids")});
      event.target.reset(); notify("领域候选已保存，核对定义后可明确采纳。"); await window.loadKnowledge();
    }catch(error){notify(error.message,true);}finally{button.disabled=false;}
  });
  find("#knowledge-relation-form").addEventListener("submit",async event=>{
    event.preventDefault(); const form=new FormData(event.target); const button=event.submitter; button.disabled=true;
    try {
      const selected=[...root.querySelectorAll("[data-evidence-index]")];
      const evidence=selected.filter(item=>item.value==="support").map(item=>knowledge.evidence[Number(item.dataset.evidenceIndex)]);
      const counterevidence=selected.filter(item=>item.value==="counter").map(item=>knowledge.evidence[Number(item.dataset.evidenceIndex)]);
      if(!evidence.length) throw new Error("请先检索并选择至少一条支持证据。");
      await post("knowledge/relations",{domain_id:form.get("domain_id"),source_kind:form.get("source_kind"),source_text:form.get("source_text"),target_kind:form.get("target_kind"),target_text:form.get("target_text"),predicate:form.get("predicate"),evidence,counterevidence,conflict_ids:form.getAll("conflict_ids"),project_id:projectId()});
      notify("关系候选已保存；核对支持范围和反例后再采纳。"); await window.loadKnowledge();
    }catch(error){notify(error.message,true);}finally{button.disabled=false;}
  });
  root.addEventListener("click",async event=>{
    const revision=event.target.closest("[data-domain-revise]");
    if(revision){const row=knowledge.domains.find(item=>item.id===revision.dataset.domainRevise);const form=find("#knowledge-domain-form");for(const key of ["domain_key","name","definition","inclusion","exclusion"])form.elements[key].value=row[key];form.elements.previous_id.value=row.id;form.elements.change_kind.value="revise";form.closest("details").open=true;form.scrollIntoView({block:"center",behavior:"smooth"});return;}
    const button=event.target.closest("[data-knowledge-review]"); if(!button)return;
    const reason=find(`[data-review-reason="${button.dataset.id}"]`).value.trim();
    if(!reason){notify("请先填写核对原文后的审核说明。",true);return;}
    button.disabled=true;
    try{await post(`knowledge/${button.dataset.knowledgeReview}/${button.dataset.id}/review`,{decision:button.dataset.decision,reason});notify("审核结果已保存，历史与来源仍可核对。");await window.loadKnowledge();}catch(error){notify(error.message,true);}finally{button.disabled=false;}
  });
  async function showCollection(){
    try{
      const result=await post("knowledge/collection",{...knowledge.collectionInput,offset:knowledge.collectionOffset,limit:50});
      find("#knowledge-collection").innerHTML=`<article class="panel"><h3>范围 ${e(result.counts.scope_total)} 个岗位 · 归入 ${e(result.counts.matched)} · 未知 ${e(result.counts.unknown)} · 不归入 ${e(result.counts.excluded)}</h3><p class="form-note">${e(result.rules)}</p>${result.jobs.map(row=>`<p><button class="job-link" data-job="${e(row.job_id)}">${e(row.title||"岗位")}</button> · ${e(row.company||"公司未知")} · ${badge(({matched:"归入",unknown:"未知",excluded:"不归入"})[row.state])}${row.classification==="user_corrected"?badge("人工纠正"):""}</p>`).join("")||"<p>当前范围没有岗位资料。</p>"}<div class="result-actions"><button class="secondary small" data-collection-page="-1" ${knowledge.collectionOffset===0?"disabled":""}>上一页</button><button class="secondary small" data-collection-page="1" ${result.truncated?"":"disabled"}>下一页</button></div></article>`;
    }catch(error){feedback(find("#knowledge-collection"),error);}
  }
  find("#knowledge-collection-form").addEventListener("submit",event=>{event.preventDefault();const form=new FormData(event.target);knowledge.collectionOffset=0;knowledge.collectionInput={project_id:projectId(),domain_id:form.get("domain_id")||null,filters:state.filters,as_of:dateValue(form.get("as_of"))};showCollection();});
  find("#knowledge-collection").addEventListener("click",event=>{const button=event.target.closest("[data-collection-page]");if(!button)return;knowledge.collectionOffset=Math.max(0,knowledge.collectionOffset+Number(button.dataset.collectionPage)*50);showCollection();});
  find("#knowledge-correction-form").addEventListener("submit",async event=>{event.preventDefault();const form=new FormData(event.target);const button=event.submitter;button.disabled=true;try{await post(`knowledge/jobs/${encodeURIComponent(form.get("job_id"))}/domains`,{domain_ids:form.getAll("domain_ids"),reason:form.get("reason")});notify("岗位领域纠正已保存，后续集合优先采用此记录。");if(knowledge.collectionInput)await showCollection();}catch(error){notify(error.message,true);}finally{button.disabled=false;}});
})();

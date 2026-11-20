"use strict";

(() => {
  const root = document.querySelector("#page-knowledge");
  if (!root) return;
  const find = selector => root.querySelector(selector);
  const knowledge = {domains:[], relations:[], domainHistory:[], relationHistory:[], evidence:[], collectionInput:null, collectionOffset:0};
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
  function definitionChanges(row) {
    if(!row.previous_id)return "";
    const old=knowledge.domainHistory.find(item=>item.id===row.previous_id);
    if(!old)return '<p class="form-note">前一版不在当前可查看范围，保留版本回链。</p>';
    const fields={name:"名称",definition:"工作问题、任务与交付物",inclusion:"包括的情形",exclusion:"边界与未知"};
    const changed=Object.entries(fields).filter(([key])=>old[key]!==row[key]);
    const sourceChanged=old.source_context?.run_id!==row.source_context?.run_id;
    return `<details class="research-context"><summary>与第 ${old.version} 版相比，哪些认识改变了</summary><p class="form-note">这是定义及研究认识的变化；不能据此认定外部工作需求已经变化。</p>${changed.length?changed.map(([key,label])=>`<section><h4>${e(label)}</h4><p><strong>之前：</strong>${e(old[key]||"未说明")}</p><p><strong>本版：</strong>${e(row[key]||"未说明")}</p></section>`).join(""):'<p>定义文字保持一致。</p>'}${sourceChanged?'<p>本版采用了不同的来源研究，请结合两次资料范围与原文核对。</p>':""}${old.source_context?.run_id?`<button class="text-button" data-open-run="${e(old.source_context.run_id)}">查看前一版来源研究 ↗</button>`:""}${row.review_reason?`<p><strong>本版核对说明：</strong>${e(row.review_reason)}</p>`:""}</details>`;
  }
  function relationChanges(row) {
    if(!row.conflict_ids?.length)return "";
    return `<details class="research-context" open><summary>本条要修正或反对的旧关系</summary>${row.conflict_ids.map(id=>{
      const old=knowledge.relationHistory.find(item=>item.id===id);
      return old?`<p>${e(old.source_text)} → ${e(old.target_text)} · ${e(labels[old.status]||old.status)}</p>${old.review_reason?`<p class="form-note">旧关系处理说明：${e(old.review_reason)}</p>`:""}${old.source_run_id?`<button class="text-button" data-open-run="${e(old.source_run_id)}">查看旧关系依据 ↗</button>`:""}`:'<p>旧关系不在当前可查看范围。</p>';
    }).join("")}<p class="form-note">候选不会静默覆盖旧认识；核对两侧依据后，再明确处理取舍。</p></details>`;
  }
  function renderDomains() {
    find("#knowledge-domains").innerHTML=knowledge.domains.length?knowledge.domains.map(row=>`<article class="panel" data-domain-record="${e(row.id)}"><h3>${e(row.name)} ${badge("第 "+row.version+" 版")} ${badge(labels[row.status]||row.status)}</h3><p>${e(row.definition)}</p><dl>${detailData("包括",row.inclusion)}${detailData("排除或未知",row.exclusion)}</dl>${row.related_ids.length?`<p class="form-note">本版本保留 ${e(row.related_ids.length)} 个关联定义的合并或拆分关系。</p>`:""}${row.source_context?.run_id?`<p class="form-note">来源于研究地图 · ${e(({direct:"原文明示",synthesis:"研究归纳",inference:"研究推断"})[row.source_context.basis]||"性质待核")}<br>${e(row.source_context.scope_note||"")}</p><button class="text-button" data-open-run="${e(row.source_context.run_id)}">核对原地图、支撑判断与原文 ↗</button>${row.stale?`<p class="error-box">${(row.stale_reasons||[]).map(e).join("；")}</p>`:""}`:""}${renderKnowledgeSupport(row.supporting_claims)}${row.review_reason?`<p class="form-note">审核：${e(row.review_reason)}</p>`:""}<button class="secondary small" data-domain-revise="${e(row.id)}">修订此定义</button>${definitionChanges(row)}${renderMemoryRevisionNotices(row.revision_notices)}${reviewControls("domains",row)}</article>`).join(""):empty("还没有领域定义","可先创建具体业务边界，再核对并采纳；未知岗位不会强制归类。");
    const options=knowledge.domains.map(row=>`<option value="${e(row.id)}">${e(row.name)} · 第${row.version}版 · ${e(labels[row.status]||row.status)}</option>`).join("");
    find('[name="related_ids"]').innerHTML=options;
    find('#knowledge-relation-form [name="domain_id"]').innerHTML='<option value="">选择领域定义</option>'+options;
    find('#knowledge-collection-form [name="domain_id"]').innerHTML='<option value="">所有领域与未知</option>'+options;
    find('#knowledge-correction-form [name="domain_ids"]').innerHTML=knowledge.domains.filter(row=>row.status==="active").map(row=>`<option value="${e(row.id)}">${e(row.name)} · 第${row.version}版</option>`).join("");
  }
  function renderRelations() {
    find("#knowledge-relations").innerHTML=knowledge.relations.length?knowledge.relations.map(row=>`<article class="panel" data-relation-record="${e(row.id)}"><h3>${e(dimensions[row.source_kind])} → ${e(dimensions[row.target_kind])} ${badge(labels[row.status]||row.status)}${row.stale?badge("需要重新核对","amber"):""}</h3><p>${e(row.source_text)} → ${e(({supports:"支撑",requires:"需要",produces:"产出",contradicts:"反驳"})[row.predicate]||row.predicate)} → ${e(row.target_text)}</p>${row.scope.research_map?`<p><strong>解释性质：</strong>${e(({direct:"原文明示",synthesis:"研究归纳",inference:"研究推断"})[row.scope.research_map.basis]||"待核对")}</p><p>${e(row.scope.research_map.rationale)}</p><p><strong>迁移边界：</strong>${e(row.scope.research_map.transfer_limit)}</p>${(row.scope.research_map.comparisons||[]).map(item=>`<details><summary>关联比较与双方依据</summary>${renderComparisonDetails(item)}<p class="form-note">依据包含比较双方；解释仍需核对，可在来源研究中查证比较对象。</p></details>`).join("")}`:""}${renderKnowledgeSupport(row.supporting_claims)}${row.source_run_id?`<button class="text-button" data-open-run="${e(row.source_run_id)}">核对来源研究 ↗</button>`:""}<p class="form-note">${e(({job:"引用岗位范围内的工作认识",work_material:"用户补充资料所述工作，未独立核实",public_context:"公开业务/技术背景，不证明岗位个人责任或必备资格"})[row.scope.evidence_scope]||"按所附原文范围核对")}。</p><p class="form-note">支持范围：${e(row.scope.job_ids?.length||0)} 个岗位、${e(row.scope.public_document_ids?.length||0)} 份公开材料；反例 ${e(row.counterevidence.length)} 条。</p>${row.stale_reasons.length?`<p class="form-note">${row.stale_reasons.map(e).join("；")}</p>`:""}<details><summary>核对支持原文与反例</summary>${row.evidence.map(item=>evidenceCard(item,0,false)).join("")}${row.counterevidence.length?"<h4>反例（不计为支持范围）</h4>":""}${row.counterevidence.map(item=>evidenceCard(item,0,false)).join("")}</details>${relationChanges(row)}${renderMemoryRevisionNotices(row.revision_notices)}${reviewControls("relations",row)}</article>`).join(""):empty("还没有关系候选","检索原文后选择支持证据和反例，明确两端表述，再保存候选审核。");
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
      const [domains,relations]=await Promise.all([api("knowledge/domains?include_history=true"),api("knowledge/relations?include_history=true"+scope)]);
      knowledge.domainHistory=domains.domains.filter(row=>!row.source_context?.project_id||row.source_context.project_id===projectId());
      knowledge.relationHistory=relations.relations;
      knowledge.domains=knowledge.domainHistory.filter(row=>history||["active","candidate"].includes(row.status));
      knowledge.relations=knowledge.relationHistory.filter(row=>history||["active","candidate","conflicted"].includes(row.status));
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
      find("#unified-results").innerHTML=`<div class="panel"><h3>找到 ${e(result.matching_jobs)} 个岗位、${e(result.matching_public_documents)} 份公开材料</h3><p>完整岗位分母 ${e(result.sample.denominator)}；条件未知 ${e(result.sample.unknown)}；公开材料范围 ${e(result.public_scope_total)}。本次展示 ${e(result.evidence.length)} 个片段${result.truncated?"，受上下文上限限制":""}。</p>${result.excluded_integrity_ids.length?`<p class="form-note">${e(result.excluded_integrity_ids.length)} 份资料因缺失或完整性变化未用于原文引用。</p>`:""}</div>${result.evidence.length?result.evidence.map((item,index)=>evidenceCard(item,index)).join(""):empty("没有可展示的原文命中","可换一个词或补充资料；未命中不表示岗位没有该项要求。")}${renderRetrievedKnowledge(result,evidenceCard)}`;
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
    const locate=event.target.closest("[data-knowledge-locate]");
    if(locate){
      const attribute=locate.dataset.knowledgeKind==="domains"?"data-domain-record":"data-relation-record";
      const selector="["+attribute+'="'+locate.dataset.knowledgeLocate+'"]';
      let target=root.querySelector(selector);
      if(!target){await window.loadKnowledge();target=root.querySelector(selector);}
      if(target)target.scrollIntoView({block:"center",behavior:"smooth"});
      else notify("该记录不在当前可查看范围，请核对研究选择或记录状态。",true);
      return;
    }
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

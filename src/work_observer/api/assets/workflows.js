"use strict";
(() => {
  const root=document.querySelector("#page-workflows");if(!root)return;
  const find=selector=>root.querySelector(selector);
  const labels={saved:"已保存，未执行",ready:"可继续有限批次",running:"正在执行",waiting_review:"等待人工核对",waiting_material:"等待资料",needs_scope_refinement:"请缩小范围",waiting_budget:"累计预算不足",interrupted:"已中断，可明确续接",completed:"本周期已核对"};
  const profileLabels={current:"复用有效画像",completed:"画像完成",evidence_only:"仅整理原文",pending:"本批预算未覆盖",running:"画像处理中",failed:"画像未完成",interrupted:"画像中断，须明确重试",waiting_material:"正文或来源待补充",budget_skipped:"累计预算不足"};
  const stopLabels={saved_no_execution:"只保存了目标，尚未执行",model_consent_required_to_continue:"这是模型研究周期，继续前请明确勾选允许模型",workflow_estimate_exceeds_remaining_budget:"完整处理超出剩余预算，请缩小范围",workflow_lifetime_budget_exhausted:"整个流程的累计预算已不足",bounded_batch_finished:"本批已按上限结束",review_or_material_required:"请核对研究结果或补充资料",scope_refined_budget_retained:"已缩小未来范围，历史和预算保留",workflow_inputs_changed_start_new_cycle:"资料或有效口径发生变化，需明确准备新周期",profiles_incomplete_research_not_started:"画像尚未完成，研究阶段没有启动",workflow_batch_budget_pending_profiles:"本批额度已用于画像，可明确继续下一批",explicit_or_process_interrupted:"本批已暂停或进程中断",workflow_batch_time_limit:"达到本批时间上限，进度已保留"};
  let selected=null,poll=null;
  stopLabels.project_model_budget_reserved="已按关联项目的明确模型补查补记累计预算";
  const post=(path,data)=>api(path,{method:"POST",body:JSON.stringify(data)});
  window.loadWorkflows=async()=>{
    try{
      const [items,domains]=await Promise.all([api("workflows"),api("knowledge/domains")]);
      const domainSelect=find('#workflow-create [name="domain_id"]'),previousDomain=domainSelect.value;
      domainSelect.innerHTML='<option value="">保持未知与多领域</option>'+domains.domains.filter(row=>row.status==="active").map(row=>`<option value="${e(row.id)}">${e(row.name)} · 第${row.version}版</option>`).join("");
      if([...domainSelect.options].some(option=>option.value===previousDomain))domainSelect.value=previousDomain;
      find("#workflows-list").innerHTML=items.length?items.map(row=>`<article class="panel strategy-editor"><div class="section-heading"><div><h3>${e(row.title)}</h3><p class="form-note">${e(labels[row.state]||row.state)} · ${e(when(row.updated_at))}</p></div><button class="secondary" data-workflow-open="${e(row.id)}">打开流程</button></div></article>`).join(""):empty("尚未建立日常流程","勾选资料并保存目标后，可以先整理原文，再明确启用模型研究。");
    }catch(error){find("#workflows-list").innerHTML=errorBox(error);}
  };
  async function openWorkflow(id){
    clearTimeout(poll);const record=await api("workflows/"+encodeURIComponent(id));selected=record;
    const cycle=record.cycles.at(-1),estimate=record.estimate,usage=record.usage;
    const listCard=find(`[data-workflow-open="${id}"]`)?.closest("article");
    if(listCard)listCard.querySelector(".form-note").textContent=(labels[record.state]||record.state)+" · "+when(record.updated_at);
    const offlineIncomplete=cycle?.mode==="offline"&&(record.dependency_issues||[]).every(item=>item.reason==="source_run_not_completed");
    const dependencyText=offlineIncomplete?"本周期只整理了原文材料，研究尚未完成、也未经过结论审核。材料面板可以核对，不能当作已经完成的研究。":"历史周期存在失效或未完成依赖。材料观察不等于研究结论已核实，请按原文、有效偏好和项目状态继续核对。";
    const tasks=cycle?Object.entries(cycle.profile_tasks):[];
    record.stop_reason=stopLabels[record.stop_reason]||"请核对资料、预算或关联项目的状态";
    const estimateText=estimate?`准备时估计：${estimate.profile_job_ids_needed.length}份画像待处理、${estimate.current_profile_ids.length}份可复用、${estimate.waiting_material_job_ids.length}份资料待补；新周期最坏${estimate.worst_new_cycle.calls}次调用/${estimate.worst_new_cycle.seconds}秒。${estimate.fits_remaining?"当时累计预算可覆盖。":"须缩小范围，不能直接执行完整链。"}`:"";
    find("#workflow-detail").innerHTML=`<article class="panel strategy-editor"><div class="section-heading"><h2>${e(record.title)}</h2>${badge(labels[record.state]||record.state,"amber")}</div><p class="body-text">${e(record.goal)}</p><p class="form-note">固定范围${record.job_ids.length}个岗位 · 周期${record.cycles.length}/${record.budget.max_cycles}<br>整个流程已预留${usage.reserved.calls}/${record.budget.max_calls}次调用、${Math.round(usage.reserved.seconds)}/${record.budget.max_seconds}秒；已记录实际${usage.actual.calls}次。${usage.unknown_actual_attempts?`另有${usage.unknown_actual_attempts}次尝试实际用量未知，原预留保留。`:""}费用未知。</p><p class="form-note">${e(estimateText)}</p>${record.stale_dependencies?'<div class="error-box">历史周期存在失效或未完成依赖。材料观察不等于研究结论已核实，请按原文、有效偏好和项目状态继续核对。</div>':""}<p class="form-note">停止原因：${e(record.stop_reason||"尚未执行")}。原文、样本与分析方法变化分别留存；没有可比时间序列就不作市场趋势。</p><div class="result-actions"><button class="secondary" data-workflow-open="${e(id)}">刷新状态</button><button class="secondary" data-workflow-refine="${e(id)}" ${record.worker_running?"disabled":""}>缩小到当前勾选岗位（保留预算）</button><button class="secondary" data-workflow-pause="${e(id)}" ${record.worker_running?"":"disabled"}>暂停本批</button>${cycle?.project_id?`<button class="secondary" data-workflow-project="${e(cycle.project_id)}">进入项目核对调查与反例</button>`:""}${cycle?.capture_id?`<button class="secondary" data-workflow-artifact="capture" data-id="${e(cycle.capture_id)}">当前材料面板</button>`:""}${cycle?.report_id?`<button class="secondary" data-workflow-artifact="report" data-id="${e(cycle.report_id)}">前后差异</button>`:""}</div>${tasks.length?'<h3>本周期画像状态</h3>'+tasks.map(([job,task])=>`<p><button class="job-link" data-job="${e(job)}">查看岗位</button> · ${e(profileLabels[task.state]||task.state)}</p>`).join(""):""}<form id="workflow-run"><h3>明确执行下一批</h3><label class="checkbox-line"><input name="allow_model" type="checkbox">允许把岗位原文、明确目标与有效偏好发送到已配置模型；未勾选仅整理原文</label><div class="form-grid"><label>本批调用上限<input name="max_calls" type="number" min="0" max="36" value="36" required></label><label>本批时限（秒）<input name="max_seconds" type="number" min="1" max="900" value="900" required></label></div><label class="checkbox-line"><input name="retry_failed" type="checkbox">明确重试失败/中断画像，额外预留计入原累计预算</label><label class="checkbox-line"><input name="new_cycle" type="checkbox">即使资料未变化也明确建立新周期，不重置预算</label><p class="form-note">同一周期复用成果；待核对或资料时直接释放。流程不请求招聘来源，也不解除来源暂停。</p><button class="primary" ${record.worker_running?"disabled":""}>按以上选择执行有限批次</button></form></article><div id="workflow-artifact"></div>`;
    const dependencyBox=find("#workflow-detail .error-box");if(dependencyBox)dependencyBox.textContent=dependencyText;
    if(record.worker_running)poll=setTimeout(()=>openWorkflow(id).catch(error=>notify(error.message,true)),2000);
  }
  find("#workflow-refresh").addEventListener("click",()=>{window.loadWorkflows();if(selected)openWorkflow(selected.id).catch(error=>notify(error.message,true));});
  find("#workflow-create").addEventListener("submit",async event=>{
    event.preventDefault();const form=new FormData(event.target),button=event.submitter;button.disabled=true;
    try{if(!state.selected.size)throw new Error("请先在岗位页勾选需要处理的1～20个岗位。");const record=await post("workflows",{title:form.get("title"),goal:form.get("goal"),job_ids:[...state.selected.keys()],domain_id:form.get("domain_id")||null,terms:form.get("terms").split(/[,，、;；\n]/).map(value=>value.trim()).filter(Boolean),include_personal:form.has("include_personal"),max_calls:Number(form.get("max_calls")),max_seconds:Number(form.get("max_seconds"))});notify("已保存流程与估算，尚未调用模型。");await window.loadWorkflows();await openWorkflow(record.id);}catch(error){notify(error.message,true);}finally{button.disabled=false;}
  });
  root.addEventListener("submit",async event=>{
    if(event.target.id!=="workflow-run")return;event.preventDefault();const form=new FormData(event.target),button=event.submitter;button.disabled=true;
    try{await post(`workflows/${selected.id}/run`,{allow_model:form.has("allow_model"),retry_failed:form.has("retry_failed"),new_cycle:form.has("new_cycle"),max_calls:Number(form.get("max_calls")),max_seconds:Number(form.get("max_seconds"))});await openWorkflow(selected.id);}catch(error){notify(error.message,true);button.disabled=false;}
  });
  function renderArtifact(data){
    const sample=data.sample?.after||data.sample||{};
    const changes=data.content_changes||[],methods=data.method_changes||{};
    const jobs=data.sample_changes||{};
    find("#workflow-artifact").innerHTML=`<article class="panel strategy-editor"><h3>${e(data.title||"观察记录")}</h3><p>岗位范围${e(sample.scope_total??"未知")}；有效正文分母${e(sample.eligible_detail_denominator??"未知")}；缺正文${e(sample.missing_details??"未知")}；未知条件${e(sample.filter_unknown??"未知")}。</p>${data.after_id?`<p>原文变化${changes.length}处；披露字段变化${(data.metadata_changes||[]).length}处。样本加入${(jobs.added_job_ids||[]).length}个、离开${(jobs.removed_job_ids||[]).length}个；不表示新招聘或关闭。</p><p>画像方法/结果变化${(methods.profiles||[]).length}项，分类变化${(methods.classifications||[]).length}项；领域定义${methods.domain_definitions_changed?"已变化":"未记录变化"}。</p>`:""}<p class="form-note">字面统计使用完整明确范围，不把片段数量当分母；只有两次观察不能证明趋势。</p>${(data.gaps||[]).map(gap=>`<p class="form-note">${e(gap)}</p>`).join("")}</article>`;
    const article=find("#workflow-artifact article");
    article.insertAdjacentHTML("beforeend",`<p class="form-note">当前画像输出${e(sample.current_profile_outputs??"未统计")}份，画像待补/核对${e(sample.missing_profiles??"未统计")}份；原文整理行不算完成模型画像。</p>`);
    const statistics=Array.isArray(data.statistics)?data.statistics:(data.statistics?.after||[]);
    if(statistics.length)article.insertAdjacentHTML("beforeend",'<h4>词项字面观察（不是必备要求比例）</h4>'+statistics.map(item=>`<p>${e(item.term)}：${item.literal_jobs==null?"未知":e(item.literal_jobs)} / ${e(item.denominator)}份有效正文。</p>`).join(""));
    const personal=data.personal_impact?.jobs||(data.jobs||[]).map(row=>({job_id:row.job_id,title:row.fields?.title,after:row.personal_impact}));
    const meanings={matched:"已披露条件字面符合",excluded:"存在明确不符",unknown:"仍需核实"};
    if(personal.some(row=>row.after)){article.insertAdjacentHTML("beforeend",'<h4>对明确个人条件的影响</h4>'+(data.personal_impact?.goal_changed?'<p class="form-note">个人条件口径已有变化，前后不能按同一条件直接比较。</p>':"")+personal.filter(row=>row.after).slice(0,20).map(row=>`<p>${e(row.title||state.jobs.get(row.job_id)?.title||"所选岗位")}：${e(meanings[row.after.state]||"待核对")}。${e((row.after.reasons||[]).map(reason=>reason.condition+"："+(meanings[reason.state]||"未知")).join("；")||row.after.note||"没有可自动采用的明确条件，不推测履历与能力。")}</p>`).join(""));}
  }
  root.addEventListener("click",async event=>{
    const button=event.target.closest("button");if(!button)return;
    try{
      if(button.dataset.workflowOpen)await openWorkflow(button.dataset.workflowOpen);
      else if(button.dataset.workflowPause){await post(`workflows/${button.dataset.workflowPause}/pause`,{});await openWorkflow(button.dataset.workflowPause);}
      else if(button.dataset.workflowRefine){if(!state.selected.size)throw new Error("请先勾选现有流程中更小的岗位集合。");await api(`workflows/${selected.id}`,{method:"PATCH",body:JSON.stringify({revision:selected.revision,job_ids:[...state.selected.keys()]})});await openWorkflow(selected.id);}
      else if(button.dataset.workflowProject){location.hash="#projects";await window.loadProjects?.();if(typeof openProject==="function")await openProject(button.dataset.workflowProject);}
      else if(button.dataset.workflowArtifact){renderArtifact(await api(`workflows/${selected.id}/artifacts/${button.dataset.workflowArtifact}`));}
    }catch(error){notify(error.message,true);}
  });
})();

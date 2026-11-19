"use strict";
let selectedProject = null, projectPoll = null, projectMapSupported = false;
const stepLabels = {queued:"待调查",running:"调查中",waiting_review:"等待核对",waiting_material:"等待资料",completed:"已核对",failed:"未完成",interrupted:"已中断",superseded:"已由补查接替"};

function renderProjectRepair(step) {
  const repair=step.repair;
  if (!repair?.available) return "";
  return `<details><summary>参考拒绝复核，安排项目内补查</summary><form data-step-repair="${e(step.id)}" data-review-id="${e(repair.review_id)}"><p class="form-note">${repair.reviewer_kind === "human" ? "人类复核意见，仍须回查原文" : "Agent辅助复核，非人审"}。只带诊断并重读原范围；旧回答与额度保留。本项目尚可预留 ${e(repair.remaining_calls)} 次调用、${e(repair.remaining_seconds)} 秒。保存后需点击项目的继续才执行。</p><label>本次补查说明<input name="note" required maxlength="1000" placeholder="说明本轮将核对哪些缺口"></label><div class="form-grid"><label>本轮最多调用<input name="max_calls" type="number" min="1" max="12" value="${Math.max(1,Math.min(8,repair.remaining_calls))}" required></label><label>本轮秒数上限<input name="timeout" type="number" min="1" max="300" value="${Math.max(1,Math.min(180,repair.remaining_seconds))}" required></label></div><label class="checkbox-line"><input name="offline" type="checkbox" ${repair.offline_preview_done ? "" : "checked"}>仅整理反馈与原文，不调用模型</label><button class="secondary">保存项目内补查</button></form></details>`;
}

window.loadProjects = async function () {
  try {
    const items = await api("projects");
    $("#projects-list").innerHTML = items.length ? items.map(p=>`<article class="panel report-row"><div><h3>${e(p.title)}</h3><p>${e(p.goal)}</p><small>${e(when(p.updated_at))} · ${p.state === "invalidated" ? "相关记忆已忘记，请新建" : "持久项目"}</small></div><button class="secondary" data-project-open="${e(p.id)}">打开</button></article>`).join("") : empty("尚未建立研究项目","先在岗位页选取资料，再保存目标。项目保存后重启仍可继续。");
  } catch (error) { $("#projects-list").innerHTML=errorBox(error); }
};

async function openProject(id) {
  clearTimeout(projectPoll);
  if(state.page !== "projects")location.hash="#projects";
  const project = await api("projects/" + encodeURIComponent(id));
  selectedProject=project;
  projectMapSupported=(state.serviceContract?.components?.schemas?.StepInput?.properties?.approach?.enum || []).includes("work_map");
  const root=$("#project-detail");
  if (project.state === "invalidated") { root.innerHTML=empty("相关记忆已忘记","项目对话、步骤和关联派生结果已清除，请建立新项目。");return; }
  root.innerHTML=`<article class="panel strategy-editor"><h2>${e(project.title)}</h2><p class="body-text">${e(project.goal)}</p><p class="form-note">范围版本 ${project.scope_version} · ${project.job_ids.length} 个岗位<br>模型调用 ${project.usage.calls} / ${project.budget.max_calls}（已预留 ${project.usage.reserved_calls}）；耗时 ${Math.round(project.usage.seconds)} 秒；公开请求 ${project.usage.public} / ${project.budget.max_public}。费用未知。${project.stop_reason ? "<br>停止原因："+e(project.stop_reason === "project_budget_exhausted" ? "已达到项目预留预算，请保留结果并明确安排新目标" : project.stop_reason) : ""}${project.worker_error ? "<br>执行未启动或已停止："+e(project.worker_error === "RESEARCH_BUSY" ? "其他入口正在执行，请等待后继续" : "请刷新进度并核对停止原因") : ""}</p><div class="result-actions"><button class="primary" data-project-run="${e(id)}" ${project.worker_running ? "disabled" : ""}>继续可执行步骤（至多3步）</button><button class="secondary" data-project-pause="${e(id)}" ${project.worker_running ? "" : "disabled"}>暂停调查</button><button class="text-button" data-project-open="${e(id)}">刷新进度</button><button class="text-button" data-project-forget="${e(id)}">忘记这个项目</button></div><details><summary>修订目标或范围</summary><form id="project-revise"><label>当前目标<textarea name="goal" required rows="3" maxlength="4000">${e(project.goal)}</textarea></label><label class="checkbox-line"><input name="replace_scope" type="checkbox">用岗位页当前勾选的岗位替换范围</label><p class="form-note">范围修订会保存版本；旧结论和未完成步骤不能外推到新范围，需重新安排追问。</p><button class="secondary">保存修订</button></form></details></article><div id="project-steps"></div><form id="project-ask" class="panel strategy-editor"><h3>继续追问或澄清</h3><label>问题<textarea name="question" rows="3" required maxlength="4000"></textarea></label><label>完成条件<input name="completion" required maxlength="1000" value="回答本问题，引用适用范围原文并明确未知项"></label><div class="form-grid">${projectMapSupported ? `<label>成果形式<select name="approach"><option value="standard">判断与缺口</option><option value="work_map">工作地图与认识修正</option></select></label>` : ""}<label>调查类型<select name="kind"><option value="investigate">补充调查 / 澄清</option><option value="counterexample">主动查反例</option><option value="synthesis">修订解释 / 汇总</option></select></label><label>前置步骤<select name="dependency"><option value="">独立追问</option>${project.steps.map(s=>`<option value="${e(s.id)}">${e(s.question.slice(0,50))} · ${e(stepLabels[s.state])}</option>`).join("")}</select></label></div><label class="checkbox-line"><input name="offline" type="checkbox" ${project.steps.at(-1)?.offline ? "checked" : ""}>仅整理证据</label><label class="checkbox-line"><input name="allow_public" type="checkbox">允许本轮有限公开补查（需剩余4次项目公开额度）</label><button class="primary">保存追问至项目</button></form>`;
  $("#project-steps").innerHTML=project.steps.map(s=>`<article class="panel strategy-editor"><div class="section-heading"><h3>${e(s.question)}</h3>${badge(stepLabels[s.state] || s.state,s.state === "completed" ? "muted" : "amber")}</div><p class="form-note">${e(projectStepOriginLabel(s))}<br>完成条件：${e(s.completion)}<br>范围版本 ${s.scope_version} · ${s.max_calls} 次调用 / ${s.timeout} 秒 · ${s.approach === "work_map" ? "工作地图与认识修正" : "判断与缺口"}${s.stop_reason ? " · "+e(s.stop_reason) : ""}</p>${s.review ? `<p class="body-text">核对记录：${e(s.review.note)}</p>` : ""}${s.replaces_step_id ? `<p class="form-note">这是显式安排的新轮调查，原步骤和消耗仍保留；前置事项将在补查核对后接续。</p>` : ""}${renderProjectRepair(s)}<div data-project-result="${e(s.id)}"></div>${["waiting_review","waiting_material","failed"].includes(s.state) ? `<form data-step-review="${e(s.id)}"><label>核对说明<input name="note" required maxlength="1000" placeholder="说明原文支持、反例或仍需补充的资料"></label><label>处理<select name="action"><option value="wait">等待资料 / 人工核对</option>${s.result?.status === "completed" ? '<option value="accept">已核对原文，接受本步</option>' : ""}<option value="retry">继续同一检查点和剩余预算</option></select></label><button class="secondary">保存核对结果</button></form><details><summary>更新材料或纠正口径后重查</summary><form data-step-refresh="${e(s.id)}"><label>补充说明<input name="note" required maxlength="1000" placeholder="说明补充了哪些正文、历史或已纠正的认识"></label><label class="checkbox-line"><input name="offline" type="checkbox" checked>仅整理原文，不调用模型</label><p class="form-note">保存一轮补查，原步骤、原预算仍保留。没有材料或口径变化会阻止重复调查；可明确从离线整理转为模型分析。开始模型调查仍需点击项目的继续。</p><button class="secondary">保存更新后的调查</button></form></details>` : ""}</article>`).join("");
  project.steps.forEach(s=>{if(s.result)renderResult(s.result,$(`[data-project-result="${s.id}"]`),s.run_id);});
  if(project.worker_running)projectPoll=setTimeout(()=>openProject(id).catch(error=>notify(error.message,true)),2000);
}

$("#refresh-projects").addEventListener("click",()=>{loadProjects();if(selectedProject)openProject(selectedProject.id).catch(error=>notify(error.message,true));});
$("#project-create").addEventListener("submit",async event=>{
  event.preventDefault();const f=event.target.elements;
  try {
    const ids=state.selected.size ? [...state.selected.keys()] : (await api("jobs?"+new URLSearchParams({...state.filters,limit:20}))).jobs.map(j=>j.id);
    if(!ids.length)throw new Error("当前范围没有岗位，请先补充或选择资料。");
    const project=await api("projects",{method:"POST",body:JSON.stringify({title:f.title.value.trim(),goal:f.goal.value.trim(),job_ids:ids,plan_steps:f.plan_steps.checked,offline:f.offline.checked})});
    event.target.reset();await loadProjects();await openProject(project.id);notify("项目与范围已保存；点击继续才执行调查。");
  } catch(error){notify(error.message,true);}
});

document.addEventListener("click",async event=>{
  const button=event.target.closest("button");if(!button)return;
  try {
    if(button.dataset.projectOpen)await openProject(button.dataset.projectOpen);
    if(button.dataset.projectForget){
      if(!window.confirm("忘记整个项目的目标、追问、全部项目记忆与关联派生结果？原始岗位和原图仍保留；独立下载副本与备份不自动删除。此操作无法撤销。"))return;
      await api("projects/"+button.dataset.projectForget,{method:"DELETE"});
      window.resetResearchHistory?.();
      selectedProject=null;clearTimeout(projectPoll);$("#project-detail").replaceChildren();
      state.memories=new Map();state.lastRun=null;state.lastResult=null;state.operations=null;
      for(const selector of ["#memory-list","#research-output","#research-history-list","#report-detail","#reports-list","#quality-detail","#update-report","#inbox-list","#knowledge-relations"]){$(selector)?.replaceChildren();}
      await loadProjects();notify("项目和关联派生上下文已忘记，原始岗位资料保留。");
    }
    if(button.dataset.projectRun){button.disabled=true;await api("projects/"+button.dataset.projectRun+"/run",{method:"POST"});await openProject(button.dataset.projectRun);}
    if(button.dataset.projectPause){await api("projects/"+button.dataset.projectPause+"/pause",{method:"POST"});await openProject(button.dataset.projectPause);}
    if(button.dataset.forgetMemory){selectedProject=null;clearTimeout(projectPoll);$("#project-detail").replaceChildren();$("#projects-list").replaceChildren();}
  }catch(error){button.disabled=false;notify(error.message,true);}
});

document.addEventListener("submit",async event=>{
  const form=event.target;
  if(!["project-ask","project-revise"].includes(form.id) && !form.dataset.stepReview && !form.dataset.stepRefresh && !form.dataset.stepRepair)return;
  event.preventDefault();if(!selectedProject)return;
  const id=selectedProject.id,f=form.elements;
  try {
    if(form.id === "project-ask")await api("projects/"+id+"/steps",{method:"POST",body:JSON.stringify({revision:selectedProject.revision,question:f.question.value.trim(),completion:f.completion.value.trim(),kind:f.kind.value,...(projectMapSupported ? {approach:f.approach.value} : {}),depends_on:f.dependency.value ? [f.dependency.value] : [],offline:f.offline.checked,allow_public:f.allow_public.checked,key:crypto.randomUUID()})});
    if(form.id === "project-revise"){
      const ids=f.replace_scope.checked ? [...state.selected.keys()] : selectedProject.job_ids;
      if(!ids.length)throw new Error("请先在岗位页勾选新的范围。");
      await api("projects/"+id,{method:"PATCH",body:JSON.stringify({revision:selectedProject.revision,goal:f.goal.value.trim(),job_ids:ids})});
    }
    if(form.dataset.stepReview)await api("projects/"+id+"/steps/"+form.dataset.stepReview+"/review",{method:"POST",body:JSON.stringify({revision:selectedProject.revision,action:f.action.value,note:f.note.value.trim()})});
    if(form.dataset.stepRefresh)await api("projects/"+id+"/steps/"+form.dataset.stepRefresh+"/refresh",{method:"POST",body:JSON.stringify({revision:selectedProject.revision,note:f.note.value.trim(),offline:f.offline.checked})});
    if(form.dataset.stepRepair)await api("projects/"+id+"/steps/"+form.dataset.stepRepair+"/repair",{method:"POST",body:JSON.stringify({revision:selectedProject.revision,review_id:form.dataset.reviewId,note:f.note.value.trim(),offline:f.offline.checked,max_calls:Number(f.max_calls.value),timeout:Number(f.timeout.value)})});
    await openProject(id);await loadProjects();
  }catch(error){notify(error.message,true);}
});
if(location.hash === "#projects")loadProjects();

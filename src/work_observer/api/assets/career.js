"use strict";
(()=>{
  const career={id:null,data:null,tab:"requirements",jobs:new Map(),selected:new Map(),timer:null,busy:false,drafts:new Map()};
  const labels={reflect:"根据练习结果调整下一步",role:"看清岗位",gaps:"对照经历与差距",plan:"设计工作样本实验",interview:"准备模拟面试",answer:"反馈我的回答"};
  const taskStates={planned:"待开始",doing:"进行中",done:"已记录结果"};
  const storyDraft=()=>career.drafts.get(career.id)||{};
  const storyFields=["title","situation","action","result","limits","requirement_key"];
  function resetStoryEditor(){
    const draft=storyDraft(),previous=draft.new_story_draft||{};
    for(const field of storyFields)delete draft[field];
    delete draft.story_id;delete draft.new_story_draft;Object.assign(draft,previous);
    career.drafts.set(career.id,draft);
  }
  function editStory(story){
    captureDrafts();const draft=storyDraft();
    if(!draft.story_id)draft.new_story_draft=Object.fromEntries(storyFields.map(field=>[field,draft[field]||""]));
    Object.assign(draft,Object.fromEntries(storyFields.map(field=>[field,story[field]||""])),{story_id:story.id});
    career.drafts.set(career.id,draft);career.tab="stories";renderDetail();$("#career-story").scrollIntoView({block:"center",behavior:"smooth"});
  }
  const button=(kind,text)=>`<button type="button" class="secondary" data-career-research="${kind}" ${career.data?.running||career.busy?"disabled":""}>${text||labels[kind]} ↗</button>`;
  const jobText=job=>{const row=job.current||job;return [row.title,row.company_name_raw||row.company||""].filter(Boolean).join(" · ");};
  const apiPath=()=>"career/"+encodeURIComponent(career.id);

  async function importResume(input){
    const file=input.files?.[0];if(!file)return;
    const form=input.closest("form"),status=form.querySelector("[data-resume-status]"),submit=form.querySelector('button[type="submit"],button.primary');
    input.disabled=true;if(submit)submit.disabled=true;status.textContent="正在本地读取简历正文…";
    try{
      if(!/\.(txt|md|markdown|docx|pdf)$/i.test(file.name))throw new Error("支持TXT、Markdown、DOCX和PDF；旧版DOC请先另存为DOCX。");
      if(file.size>8*1024*1024)throw new Error("请选择8MB以内的简历文件。");
      let text,notice="";
      if(/\.(pdf|docx)$/i.test(file.name)){
        const extracted=await api("imports/documents/extract?filename="+encodeURIComponent(file.name),{method:"POST",body:file,headers:{"Content-Type":"application/octet-stream"}});
        text=extracted.text;notice=extracted.notice;
      }else text=(await file.text()).replace(/^\uFEFF/,"");
      if(!text.trim())throw new Error("简历文件没有可读取的文字。");
      if(!form.isConnected)return;
      form.elements.resume_title.value=file.name.slice(0,150);form.elements.resume_text.value=text;
      status.textContent=`已读取 ${text.length} 字。${notice} ${text.length>20000?"请先精简到2万字以内再保存。":"请核对正文后保存；读取不调用模型。"}`;
      if(career.id&&form.id==="career-resume-form")captureDrafts();
    }catch(error){status.textContent=error.message;}finally{input.disabled=false;input.value="";if(submit)submit.disabled=form.id==="career-resume-form"&&Boolean(career.data?.running||career.busy);}
  }

  function resumePanel(data){
    const draft=storyDraft();
    return `<details class="panel career-resume-panel" ${draft.resume_open?"open":""}><summary>${data.resume?"已导入简历 · "+e(data.resume.title):"导入或粘贴我的简历"}</summary>${data.resume?`<button type="button" class="text-button" data-public-source="${e(data.resume.document_id)}">查看已保存的简历正文 ↗</button>`:""}<form id="career-resume-form"><label class="research-file-drop"><input type="file" data-career-resume-file accept=".txt,.md,.markdown,.docx,.pdf"><strong>${data.resume?"选择新的简历文件":"选择简历文件"}</strong><span>TXT / Markdown / Word / PDF，本地提取文字</span></label><label>简历标题<input name="resume_title" maxlength="150" required value="${e(draft.resume_title||data.resume?.title||"个人简历")}"></label><label>或直接粘贴简历原文<textarea name="resume_text" rows="5" maxlength="20000" required placeholder="保留真实经历、个人分工与结果。文件提取后请核对正文。">${e(draft.resume_text||"")}</textarea></label><p class="form-note" data-resume-status role="status"></p><button type="submit" class="primary" ${data.running?"disabled":""}>${data.resume?"更新这份简历":"保存简历到本目标"}</button><p class="form-note">保存不调用模型。后续分析会把简历视为用户自述，能力与效果仍需实际证据。</p></form></details>`;
  }

  function captureDrafts(){
    if(!career.id)return;
    const data={...storyDraft()},story=$("#career-story"),answer=$("#career-answer");
    if(story)for(const field of ["title","situation","action","result","limits","requirement_key"])data[field]=story.elements[field].value;
    if(answer){data.answer=answer.value;data.question_index=$("#career-interview-answer").elements.question_index.value;}
    const resume=$("#career-resume-form");if(resume){data.resume_title=resume.elements.resume_title.value;data.resume_text=resume.elements.resume_text.value;data.resume_open=resume.closest("details").open;}
    const insight=$("#career-insight");if(insight)data.insight=Object.fromEntries(new FormData(insight));
    const manual=$("#career-manual-experiment");if(manual){data.manual=Object.fromEntries(new FormData(manual));data.manual_open=manual.closest("details").open;}
    for(const form of $$("[data-career-task-form]"))data["task:"+form.dataset.careerTaskForm]=Object.fromEntries(new FormData(form));
    career.drafts.set(career.id,data);
  }

  async function loadGoals(){
    const items=await api("career");
    $("#career-goals").innerHTML=items.length?items.map(row=>`<a href="#career/${e(row.id)}" class="career-goal-card ${career.id===row.id?"is-current":""}"><strong>${e(row.title)}</strong><span>${row.job_count} 个目标岗位 · ${row.story_count} 份经历证据</span><small>${row.done_count} / ${row.task_count} 项练习已记录结果 · ${row.insight_count||0} 次复盘</small></a>`).join(""):"";
  }

  async function findJobs(){
    const query=$("#career-job-query").value.trim();
    $("#career-job-options").innerHTML='<p class="form-note">正在查找岗位…</p>';
    const result=await api("jobs?"+new URLSearchParams({keyword:query,limit:20}));
    career.jobs=new Map(result.jobs.map(row=>[row.id,row]));
    $("#career-job-options").innerHTML=result.jobs.length?result.jobs.map(job=>`<label class="career-job-option"><input type="checkbox" data-career-job="${e(job.id)}" ${career.selected.has(job.id)?"checked":""}><span><strong>${e(jobText(job))}</strong><small>${job.has_detail?"已有岗位正文":"当前正文可能不足，可先补充资料"}</small></span><button type="button" class="text-button" data-job="${e(job.id)}">查看</button></label>`).join(""):empty("还没有匹配的岗位","可以到岗位资料粘贴JD，再回到这里选择。");
  }

  function selectedJobs(){
    $("#career-selected-jobs").innerHTML=[...career.selected].map(([id,title])=>`<button type="button" class="scope-chip" data-career-remove-job="${e(id)}">${e(title)} ×</button>`).join("");
  }

  function requirements(data){
    const rows=data.requirements;
    return `<div class="section-heading"><div><h2>岗位要求 × 我的经历证据</h2><p class="form-note">经历由你自述；有材料可讨论，不等于已证明胜任。</p></div>${button("role",rows.length?"重新看清岗位":"从原文提炼关键要求")}</div>${rows.length?`<div class="career-requirements">${rows.map(row=>{
      const stories=data.stories.filter(story=>story.requirement_key===row.key);
      return `<article class="career-requirement"><div class="career-requirement-main"><div class="result-actions">${badge(categoryLabels[row.category]||row.category,"muted")}${badge(requirementLabels[row.requirement]||"未说明性质",row.requirement==="required"?"amber":"muted")}<span class="form-note">${e(claimBasisLabel(row))} · 待核对</span></div><h3>${e(row.text)}</h3><details><summary>查看招聘原文依据</summary>${row.evidence.map(ev=>`<p class="form-note">${e(ev.title)}</p><blockquote>${e(ev.quote)}</blockquote>`).join("")}</details></div><div class="career-requirement-proof"><span class="quiet-tag">${stories.length?"有自述经历，待核对":"还没有对应的经历证据"}</span>${stories.map(story=>`<p>${e(story.title)}</p>`).join("")}<button type="button" class="text-button" data-career-link-story="${e(row.key)}">${stories.length?"再补充一份证据":"我有哪些经历可以说明？"} ↗</button></div></article>`;
    }).join("")}</div>`:empty("先看清这份工作，再讨论自己差什么","分析会把具体要求与招聘原文放在一起；你可以逐项补充真实项目经历。")}`;
  }

  function stories(data){
    const draft=storyDraft();
    return `<div class="section-heading"><div><h2>我的经历证据库</h2><p class="form-note">写清亲自参与的部分、结果和边界，供研究与模拟面试使用。</p></div>${button("gaps")}</div>${resumePanel(data)}<div class="career-story-layout"><form id="career-story" class="panel">${draft.story_id?'<p class="career-editing-note">正在修改已保存的经历</p>':""}<label>对应哪项岗位要求<select name="requirement_key"><option value="">作为通用项目经历</option>${data.requirements.map(row=>`<option value="${e(row.key)}" ${draft.requirement_key===row.key?"selected":""}>${e(row.text)}</option>`).join("")}</select></label><label>项目或工作名称<input name="title" required maxlength="150" value="${e(draft.title||"")}" placeholder="例如：客服知识库检索项目"></label><label>要解决的问题<textarea name="situation" required rows="2" maxlength="1500">${e(draft.situation||"")}</textarea></label><label>我亲自做了什么<textarea name="action" required rows="3" maxlength="2000" placeholder="写你的具体行动、关键取舍，区分团队成果与个人参与。">${e(draft.action||"")}</textarea></label><label>实际结果与可查看的证据<textarea name="result" required rows="2" maxlength="1500" placeholder="可以写产物、测试方法、观察，也可以说明暂时没有效果数据。">${e(draft.result||"")}</textarea></label><label>局限、失败或未参与的部分<textarea name="limits" rows="2" maxlength="1000">${e(draft.limits||"")}</textarea></label><button class="primary" ${data.running?"disabled":""}>${draft.story_id?"保存修改":"保存这份经历"}</button>${draft.story_id?'<button type="button" class="text-button" data-career-cancel-story>取消修改</button>':""}</form><div>${data.stories.length?data.stories.map(story=>`<article class="panel career-story-card"><span class="quiet-tag">用户自述 · 待核对</span><h3>${e(story.title)}</h3><dl>${detailData("场景",story.situation)}${detailData("亲自负责",story.action)}${detailData("结果与证据",story.result)}${detailData("边界",story.limits||"未填写")}</dl><button type="button" class="text-button" data-public-source="${e(story.document_id)}">查看保存的经历原文 ↗</button><div class="result-actions"><button type="button" class="secondary small" data-career-edit-story="${e(story.id)}" ${data.running?"disabled":""}>修改经历 / 关联要求</button><button type="button" class="text-button" data-career-remove-story="${e(story.id)}" ${data.running?"disabled":""}>移出本目标</button></div></article>`).join(""):empty("真实经历比技能词更有用","从一件亲自做过的事开始，尚未成功的尝试也值得保存。")}</div></div>`;
  }

  function experiments(data){
    const plans=data.results.filter(row=>row.result?.status==="completed"&&row.result.application_plan?.actions?.length);
    return `<div class="section-heading"><div><h2>用工作样本验证能力</h2><p class="form-note">完成一次练习后，记录实际观察；结果可以成功，也可以推翻原先的判断。</p></div>${button("plan")}</div>${manualExperiment()}${plans.slice(0,2).map(row=>`<div class="career-plan-invite"><span>研究已给出 ${row.result.application_plan.actions.length} 项行动建议</span><button class="secondary small" data-career-import-tasks="${e(row.step_id)}">加入我的练习板</button></div>`).join("")}<div class="career-kanban">${Object.entries(taskStates).map(([state,label])=>`<section class="career-lane"><h3>${label} <span>${data.tasks.filter(task=>task.state===state).length}</span></h3>${data.tasks.filter(task=>task.state===state).map(task=>{
      const draft=storyDraft()["task:"+task.id]||task;
      return `<article class="panel career-task"><span class="quiet-tag">${task.origin==="user"?"我设计的练习":"研究建议"}</span><h3>${e(task.title)}</h3><p>${e(task.task_or_ability)}</p><dl>${detailData("要交付",task.deliverable)}${detailData("怎样检查",task.completion_check)}</dl>${task.assumptions?.length?`<p class="form-note">前提：${task.assumptions.map(e).join("；")}</p>`:""}<details><summary>记录进度与实际结果</summary><form data-career-task-form="${e(task.id)}"><label>练习状态<select name="state">${Object.entries(taskStates).map(([value,label])=>`<option value="${value}" ${draft.state===value?"selected":""}>${label}</option>`).join("")}</select></label><label>原先的预期或想验证的判断<textarea name="hypothesis" rows="2" maxlength="1500" placeholder="例如：加上重试就能解决请求失败；通过这个实验检查它是否成立。">${e(draft.hypothesis||"")}</textarea></label><label>实际做了什么、观察到什么<textarea name="outcome" rows="3" maxlength="4000">${e(draft.outcome||"")}</textarea></label><label>作品链接或产物位置<input name="artifact" maxlength="1000" value="${e(draft.artifact||"")}" placeholder="保存为文字，不会自动打开或上传"></label><button class="secondary small">保存进度</button></form></details>${task.hypothesis?`<p class="career-observation"><strong>原先预期：</strong>${e(task.hypothesis)}</p>`:""}${task.outcome?`<p class="career-observation"><strong>实际观察：</strong>${e(task.outcome)}</p>`:""}${task.artifact?`<p class="form-note">产物：${e(task.artifact)}</p>`:""}${task.outcome?`<button type="button" class="secondary" data-career-research="reflect" data-career-task-id="${e(task.id)}" ${data.running||career.busy?"disabled":""}>反思这次练习 ↗</button><button type="button" class="text-button" data-career-task-story="${e(task.id)}">把这次练习补成经历证据 ↗</button>`:""}</article>`;
    }).join("")||'<p class="form-note">还没有这一状态的练习</p>'}</section>`).join("")}</div>${!data.tasks.length?'<p class="form-note">先生成工作样本建议，再加入练习板。建议会结合岗位原文、你的背景与投入限制。</p>':""}${learningNotes(data)}`;
  }

  function manualExperiment(){
    const draft=storyDraft().manual||{};
    return `<details class="panel career-manual-experiment" ${storyDraft().manual_open?"open":""}><summary>自己设计一项工作样本实验</summary><form id="career-manual-experiment"><p class="form-note">把已有的验证想法放进练习板，保存不调用模型。</p><label>这项实验叫什么<input name="title" required maxlength="150" value="${e(draft.title||"")}" placeholder="例如：比较两种检索方案的失败案例"></label><label>针对什么任务或能力<input name="task_or_ability" required maxlength="500" value="${e(draft.task_or_ability||"")}"></label><label>原先的预期或想验证的判断<textarea name="hypothesis" maxlength="1500" rows="2">${e(draft.hypothesis||"")}</textarea></label><label>准备交付什么<textarea name="deliverable" required maxlength="700" rows="2" placeholder="例如：可运行的样例、测试集和观察记录">${e(draft.deliverable||"")}</textarea></label><label>怎样检查它是否完成<textarea name="completion_check" required maxlength="700" rows="2" placeholder="写可实际执行的检查；也可以记录哪些结果会推翻原来的预期。">${e(draft.completion_check||"")}</textarea></label><button class="primary">加入我的练习板</button></form></details>`;
  }

  function interview(data){
    const last=data.results.find(row=>row.kind==="interview"&&row.result?.status==="completed");
    const questions=(last?.result.gaps||[]).filter(text=>/[?？]/.test(text));
    return `<div class="section-heading"><div><h2>让真实经历经得住追问</h2><p class="form-note">围绕岗位和自己的项目展开，练习讲清任务、取舍、失败与责任边界。</p></div>${button("interview")}</div>${last?'<div id="career-interview-questions"></div>':empty("从你的材料出发的一次模拟面试","先补充一份经历，或直接准备面试问题；缺少的信息会明确指出。")}${questions.length?`<form id="career-interview-answer" class="panel career-answer-form"><label>选择本次回答的问题<select name="question_index">${questions.map((text,index)=>`<option value="${index}" ${String(storyDraft().question_index||"0")===String(index)?"selected":""}>${e(text)}</option>`).join("")}</select></label><label>写下你的真实回答<textarea id="career-answer" name="answer" rows="6" maxlength="2500" required placeholder="选择一个问题回答。写实际行动、当时的选择、验证方法，以及你还说不清的部分。">${e(storyDraft().answer||"")}</textarea></label><button class="primary" ${data.running?"disabled":""}>结合原文反馈我的回答 ↗</button></form>`:""}`;
  }

  function learningNotes(data){
    const draft=storyDraft().insight;
    return `<section class="career-learning-notes"><div class="section-heading"><div><h2>我改变了哪些认识</h2><p class="form-note">记录自己的理解与疑问，下一轮研究可以沿着这些问题继续。</p></div>${!draft?'<button type="button" class="secondary" data-career-new-insight>记录一次认识变化</button>':""}</div>${draft?`<form id="career-insight" class="panel"><p class="form-note">结合原文和实际观察编辑成自己的理解，保存不会调用模型。</p><label>来自哪次练习<select name="task_id"><option value="">不绑定某项练习</option>${data.tasks.map(task=>`<option value="${e(task.id)}" ${draft.task_id===task.id?"selected":""}>${e(task.title)}</option>`).join("")}</select></label><label>我原先怎么理解<textarea name="previous_view" rows="2" required maxlength="1500">${e(draft.previous_view||"")}</textarea></label><label>看到了什么证据或实际观察<textarea name="observation" rows="2" required maxlength="2000">${e(draft.observation||"")}</textarea></label><label>现在我怎么理解<textarea name="current_view" rows="3" required maxlength="1500">${e(draft.current_view||"")}</textarea></label><label>仍不确定什么、下一步要验证什么<textarea name="open_question" rows="2" maxlength="1000">${e(draft.open_question||"")}</textarea></label><div class="result-actions"><button class="primary">记入我的认知记录</button><button type="button" class="text-button" data-career-cancel-insight>取消</button></div></form>`:""}${(data.insights||[]).length?`<div class="career-learning-timeline">${[...data.insights].reverse().map(note=>`<article class="panel career-learning-note"><p class="form-note">${e(when(note.created_at))} · 我的复盘</p><div class="career-learning-change"><div><h3>原先的理解</h3><p>${e(note.previous_view)}</p></div><span aria-hidden="true">→</span><div><h3>现在的理解</h3><p>${e(note.current_view)}</p></div></div><details><summary>为什么改变、还有什么未知</summary><p><strong>观察：</strong>${e(note.observation)}</p>${note.open_question?`<p><strong>下一步：</strong>${e(note.open_question)}</p>`:""}</details></article>`).join("")}</div>`:!draft?'<p class="form-note">一次失败的实验、一次原文重读，或一个还没解决的问题，都可以成为新的起点。</p>':""}</section>`;
  }

  function startInsight(taskId=null){
    captureDrafts();const draft=storyDraft();
    if(!draft.insight){
      const task=career.data.tasks.find(row=>row.id===taskId);
      const reflection=career.data.results.find(row=>row.kind==="reflect"&&row.task_id===taskId&&row.result?.status==="completed");
      const proposed=reflection?.result.claims?.[0]?.text||"";
      const open=reflection?.result.gaps?.find(text=>!text.startsWith("静态有限样本"))||"";
      draft.insight={task_id:taskId||"",previous_view:task?.hypothesis||"",observation:task?.outcome?.length<=2000?task.outcome:"",current_view:proposed.length<=1500?proposed:"",open_question:open.length<=1000?open:""};
      career.drafts.set(career.id,draft);
    }
    career.tab="experiments";renderDetail();$("#career-insight").scrollIntoView({block:"center",behavior:"smooth"});
  }

  function coachingResult(row){
    const result=row.result;if(!result)return '<p class="form-note">这一轮还没有可展示的结果，可在完整研究记录中查看进度。</p>';
    const evidence=new Map((result.evidence||[]).map((ev,index)=>[ev.id,{...ev,label:"E"+(index+1)}]));
    const cites=ids=>(ids||[]).filter(id=>evidence.has(id)).map(id=>`<button type="button" class="cite" data-cite="${e(id)}">${e(evidence.get(id).label)} ↗</button>`).join(" ");
    const completed=result.status==="completed",plan=result.application_plan;
    const claims=completed?result.claims:result.submission_feedback?.draft_claims||[];
    const body=claims.map(claim=>`<article class="career-coaching-point"><div class="result-actions">${badge(categoryLabels[claim.category]||claim.category,"muted")}${claim.requirement!=="unspecified"?badge(requirementLabels[claim.requirement]||"性质待核","muted"):""}<span class="form-note">${e(claimBasisLabel(claim))}</span></div><p>${e(claim.text)}</p>${cites(claim.evidence_ids)}</article>`).join("");
    const gaps=(result.gaps||[]).filter(text=>!text.startsWith("静态有限样本")&&!text.startsWith("研究未完成，已有证据"));
    return `<article class="panel result-card career-coaching-result"><div class="section-heading"><h3>${e(labels[row.kind])}</h3>${badge(statusLabels[result.status]||result.status,completed?"":"amber")}</div>${result.audit?.stale_dependencies||result.audit?.stale_memory||result.audit?.changed_sources?.length?'<p class="career-result-notice">所用资料或背景已有变化，以下保留当时的分析，需重新核实。</p>':""}${result.business_review?.status==="rejected"?'<p class="career-result-notice">这份研究的质量核对未通过，请查看完整记录并修正。</p>':""}${row.kind==="answer"?`<section class="career-answer-record"><h4>我当时的回答</h4>${row.interview_question?`<p class="form-note">问题：${e(row.interview_question)}</p>`:""}<p>${e(row.answer)}</p></section>`:""}${completed?body:`<p class="career-result-notice">${result.status==="evidence_only"?"已整理原文，尚未分析。取消“只整理原文”后，可选择需要的研究步骤。":e(reasonLabels[result.stop_reason]||"这一轮没有形成完整回答，已读原文仍可查阅。")}</p>${body?'<details><summary>查看未完成草稿（尚未采用）</summary>'+body+'</details>':""}`}${completed&&plan?.actions?.length?`<section class="career-coaching-plan"><h3>可尝试的工作样本</h3>${plan.actions.map((action,index)=>`<article><h4>${index+1}. ${e(action.title)}</h4><p><strong>产物：</strong>${e(action.deliverable)}</p><p><strong>检查：</strong>${e(action.completion_check)}</p>${action.assumptions?.length?`<p class="form-note">前提：${action.assumptions.map(e).join("；")}</p>`:""}${cites(action.evidence_ids)}</article>`).join("")}<p class="form-note">这是基于资料与个人背景的练习建议，实际结果需要自己验证。</p></section>`:""}${gaps.length&&row.kind!=="interview"?`<section class="career-coaching-questions"><h3>还值得继续核实</h3><ul>${gaps.map(text=>'<li>'+e(text)+'</li>').join("")}</ul></section>`:""}<details class="career-coaching-sources"><summary>查看 ${evidence.size} 份引用原文</summary>${[...evidence.values()].map(ev=>`<details data-evidence="${e(ev.id)}"><summary>${e(ev.label)} · ${e(ev.title)}</summary><p class="form-note">${e(ev.company||ev.publisher||"")} · 原文字符 ${ev.start}–${ev.end}</p><blockquote>${e(ev.quote)}</blockquote>${ev.public_document_id?`<button class="text-button" data-public-source="${e(ev.public_document_id)}">查看完整归档 ↗</button>`:""}</details>`).join("")}</details>${row.kind==="reflect"&&row.task_id&&completed?`<button type="button" class="secondary" data-career-insight-task="${e(row.task_id)}">记下这次认识变化 ↗</button>`:""}<p class="form-note"><a href="#research/${e(career.id)}">查看完整研究与过程 ↗</a></p></article>`;
  }

  function preparationPackage(data){
    const paragraph=value=>`<p>${e(value||"未记录").replace(/\n/g,"<br>")}</p>`;
    const requirements=data.requirements.map(row=>`<article><h3>${e(row.text)}</h3><p class="meta">${e(categoryLabels[row.category]||row.category)} · ${e(requirementLabels[row.requirement]||"性质未说明")} · ${e(claimBasisLabel(row))}</p>${row.evidence.map(ev=>`<details open><summary>${e(ev.title)} · 引用原文</summary><blockquote>${e(ev.quote)}</blockquote></details>`).join("")}</article>`).join("");
    const stories=data.stories.map(row=>`<article><h3>${e(row.title)}</h3><h4>场景与目标</h4>${paragraph(row.situation)}<h4>亲自参与</h4>${paragraph(row.action)}<h4>结果与证据</h4>${paragraph(row.result)}<h4>局限与未参与部分</h4>${paragraph(row.limits)}</article>`).join("");
    const experiments=data.tasks.map(row=>`<article><h3>${e(row.title)} · ${e(taskStates[row.state])}</h3><p class="meta">${row.origin==="user"?"用户设计的练习":"研究提出的建议"}</p><h4>要交付什么</h4>${paragraph(row.deliverable)}<h4>怎样检查</h4>${paragraph(row.completion_check)}<h4>原先的预期</h4>${paragraph(row.hypothesis)}<h4>实际观察</h4>${paragraph(row.outcome)}<h4>产物位置</h4>${paragraph(row.artifact)}</article>`).join("");
    const interviews=data.results.filter(row=>row.kind==="answer").reverse().map(row=>`<article><h3>${e(row.interview_question||"模拟面试回答")}</h3><h4>我的回答</h4>${paragraph(row.answer)}<h4>研究反馈</h4>${row.result?.status==="completed"?row.result.claims.map(claim=>paragraph(claim.text)).join(""):'<p>本轮反馈尚未完整形成。</p>'}</article>`).join("");
    return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${e(data.title)} · 求职准备包</title><style>body{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:0;background:#f4f7f1;color:#25382c;line-height:1.9}main{max-width:940px;margin:30px auto;background:white;padding:40px;border-radius:16px}header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #dfe7da;padding-bottom:18px;font-size:12px;color:#55724d}button{border:0;background:#315c46;color:white;padding:10px 16px;border-radius:8px;cursor:pointer}h1{font-size:30px;line-height:1.5}h2{font-size:21px;margin-top:36px;border-top:1px solid #dfe7da;padding-top:22px}h3{font-size:16px}h4{font-size:12px;color:#71846b;margin:18px 0 3px}p{font-size:14px;margin:5px 0 14px;overflow-wrap:anywhere}article{padding:18px 22px;background:#f7f9f4;border-radius:10px;margin:14px 0}blockquote{white-space:pre-wrap;background:white;border-left:2px solid #8fa882;margin:10px 0;padding:12px;font-size:12px}.meta{font-size:12px;color:#74846c}summary{font-size:12px;cursor:pointer}@media(max-width:600px){main{margin:0;padding:23px;border-radius:0}h1{font-size:25px}}@media print{body{background:white}main{margin:0;padding:0}header button{display:none}h2,h3{break-after:avoid}article{break-inside:avoid}}</style></head><body><main><header><strong>WORK OBSERVER / 求职准备包</strong><button onclick="window.print()">打印 / 保存为 PDF</button></header><h1>${e(data.title)}</h1>${paragraph(data.goal)}<p class="meta">导出于 ${e(when(new Date().toISOString()))}。项目经历与实验观察由用户自述；研究结论、建议及个人能力仍需结合原文和实际产物核对。</p><h2>我的背景与投入</h2>${paragraph(data.profile?.background)}${paragraph(data.profile?.constraints)}<h2>目标岗位</h2>${data.jobs.map(job=>paragraph(jobText(job))).join("")}${data.resume_text?`<details open><summary>我提供的简历原文</summary><blockquote>${e(data.resume_text)}</blockquote></details>`:""}<h2>岗位要求与原文</h2>${requirements||'<p>尚未提炼岗位要求。</p>'}<h2>我的经历证据</h2>${stories||'<p>尚未保存经历。</p>'}<h2>工作样本：预期与观察</h2>${experiments||'<p>尚未保存练习。</p>'}<h2>我的认识如何变化</h2>${(data.insights||[]).map(note=>`<article><h3>${e(when(note.created_at))}</h3><h4>原先的理解</h4>${paragraph(note.previous_view)}<h4>实际观察</h4>${paragraph(note.observation)}<h4>现在的理解</h4>${paragraph(note.current_view)}<h4>仍待验证</h4>${paragraph(note.open_question)}</article>`).join("")||"<p>尚未记录认识变化。</p>"}<h2>模拟面试与反馈</h2>${interviews||'<p>尚未保存面试回答。</p>'}</main></body></html>`;
  }

  async function exportPreparation(button){
    button.disabled=true;
    try{
      const data=await api(apiPath());
      if(data.resume)data.resume_text=(await api("public-documents/"+encodeURIComponent(data.resume.document_id))).text;
      const html=preparationPackage(data);
      const url=URL.createObjectURL(new Blob([html],{type:"text/html;charset=utf-8"}));
      const link=document.createElement("a");link.href=url;link.download="求职准备包-"+data.title.replace(/[<>:"/\\|?*\u0000-\u001f]/g,"_").slice(0,70)+".html";
      document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(error){notify(error.message,true);}finally{button.disabled=false;}
  }

  function renderDetail(){
    const data=career.data;if(!data)return;
    $("#career-onboarding").hidden=true;const root=$("#career-detail");root.hidden=false;
    root.innerHTML=`<article class="career-target panel"><div><span class="eyebrow">MY NEXT CHAPTER</span><h2>${e(data.title)}</h2><p>${e(data.goal)}</p><div class="career-target-jobs">${data.jobs.map(job=>`<button class="quiet-tag" data-job="${e(job.id)}">${e(jobText(job))} ↗</button>`).join("")}</div></div><div class="career-target-aside"><button type="button" class="secondary" id="career-export">导出求职准备包 ↧</button><div class="career-progress"><strong>${data.stories.length}</strong><span>份经历证据</span><strong>${data.tasks.filter(task=>task.state==="done").length}</strong><span>项练习有结果</span><strong>${(data.insights||[]).length}</strong><span>次认识复盘</span></div></div></article><div class="career-research-bar"><p>${data.running?'正在查阅资料与研究…':`已用 ${data.usage.calls} / ${data.budget.max_calls} 次模型调用`} <a class="text-button" href="#research/${e(data.id)}">打开完整研究记录 ↗</a></p><label class="checkbox-line"><input id="career-offline" type="checkbox" ${career.offline?"checked":""}>只整理原文</label><small>分析会将所选资料、个人背景与经历发送至已配置模型；每轮最多6次调用、2分半。</small></div><nav class="career-tabs" aria-label="求职成长步骤">${[["requirements","01","看清工作"],["stories","02","经历与差距"],["experiments","03","工作样本"],["interview","04","模拟面试"]].map(([key,n,title])=>`<button type="button" data-career-tab="${key}" class="${career.tab===key?"active":""}" aria-pressed="${career.tab===key}"><span>${n}</span>${title}</button>`).join("")}</nav><div id="career-tab-content">${({requirements,stories,experiments,interview})[career.tab](data)}</div><section class="career-result-area"><div class="section-heading"><h2>研究与反馈</h2><button type="button" class="text-button" id="career-refresh">刷新</button></div><div id="career-results"></div></section>`;
    const shown=data.results.filter(row=>({requirements:["role"],stories:["gaps"],experiments:["plan","reflect"],interview:["interview","answer"]})[career.tab].includes(row.kind));
    $("#career-results").innerHTML=shown.length?shown.map(row=>`<details class="career-result" ${shown[0]===row?"open":""}><summary>${e(labels[row.kind])} · ${e(row.result?statusLabels[row.result.status]||row.result.status:({queued:"等待开始",running:"正在研究",failed:"未完成"})[row.state]||row.state)}</summary><div data-career-result="${e(row.step_id)}"></div></details>`).join(""):'<p class="form-note">这个步骤还没有研究记录。</p>';
    for(const row of shown)$(`[data-career-result="${row.step_id}"]`).innerHTML=coachingResult(row);
    if(career.tab==="interview"){
      const last=data.results.find(row=>row.kind==="interview"&&row.result?.status==="completed");
      if(last)$("#career-interview-questions").innerHTML=`<article class="panel career-interview-prompts">${(last.result.gaps||[]).filter(text=>/[?？]/.test(text)).map((text,index)=>`<p><strong>${index+1}.</strong> ${e(text)}</p>`).join("")}</article>`;
    }
  }

  async function openCareer(id){
    captureDrafts();clearTimeout(career.timer);career.id=id;
    const data=await api("career/"+encodeURIComponent(id));if(career.id!==id)return;
    career.data=data;renderDetail();
    if(data.running)career.timer=setTimeout(()=>{if(state.page==="career"&&career.id===id)openCareer(id).catch(error=>notify(error.message,true));},2000);
  }

  window.loadCareer=async()=>{
    clearTimeout(career.timer);$("#career-detail").hidden=true;await loadGoals();
    const id=location.hash.split("/")[1];
    if(id&&/^[a-f0-9]{32}$/.test(id))await openCareer(id);
    else{$("#career-onboarding").hidden=false;$("#career-detail").hidden=true;await findJobs();}
  };

  async function research(kind,answer="",questionIndex=0,taskId=null){
    if(career.busy)return;captureDrafts();career.busy=true;renderDetail();
    const id=career.id;
    try{
      const step=await api("career/"+id+"/prepare",{method:"POST",body:JSON.stringify({kind,answer,question_index:questionIndex,task_id:taskId,offline:Boolean(career.offline)})});
      await api("projects/"+id+"/run",{method:"POST",body:JSON.stringify({step_id:step.step_id})});
      await openCareer(id);
    }catch(error){notify(error.message,true);}
    finally{career.busy=false;if(career.id===id)renderDetail();}
  }

  $("#career-find-jobs").addEventListener("click",()=>findJobs().catch(error=>notify(error.message,true)));
  $("#career-job-query").addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();findJobs().catch(error=>notify(error.message,true));}});
  $("#career-new").addEventListener("click",()=>{captureDrafts();clearTimeout(career.timer);career.id=null;career.data=null;location.hash="career";$("#career-onboarding").hidden=false;$("#career-detail").hidden=true;findJobs().catch(error=>notify(error.message,true));});
  $("#career-create").addEventListener("submit",async event=>{
    event.preventDefault();const form=event.target,submit=$("#career-create-submit");
    if(!career.selected.size){notify("先选择至少一份目标岗位JD。",true);return;}
    submit.disabled=true;
    try{const data=Object.fromEntries(new FormData(form));data.resume_title=data.resume_title?.trim()||"个人简历";if(data.resume_text?.length>20000)throw new Error("请把简历正文精简到2万字以内。");if(!data.background.trim()){if(data.resume_text?.trim())data.background="已导入个人简历。具体经历见本目标附加的简历原文，经历与效果为用户自述，尚未独立验证。";else throw new Error("请填写已有经历，或导入一份简历。");}data.job_ids=[...career.selected.keys()];const created=await api("career",{method:"POST",body:JSON.stringify(data)});form.reset();career.selected.clear();selectedJobs();career.tab="requirements";location.hash="career/"+created.id;}
    catch(error){notify(error.message,true);}finally{submit.disabled=false;}
  });
  document.addEventListener("change",event=>{
    if(event.target.matches?.('#career-insight [name="task_id"]')){
      const task=career.data.tasks.find(row=>row.id===event.target.value),form=event.target.closest("form");
      if(task){if(!form.elements.previous_view.value)form.elements.previous_view.value=task.hypothesis||"";if(!form.elements.observation.value&&task.outcome.length<=2000)form.elements.observation.value=task.outcome;captureDrafts();}
    }
    if(event.target.matches?.("[data-career-resume-file]"))importResume(event.target);
    const choice=event.target.closest("[data-career-job]");
    if(choice){if(choice.checked&&career.selected.size>=6){choice.checked=false;notify("最多选择6个目标岗位。",true);return;}if(choice.checked)career.selected.set(choice.dataset.careerJob,jobText(career.jobs.get(choice.dataset.careerJob)));else career.selected.delete(choice.dataset.careerJob);selectedJobs();}
    if(event.target.id==="career-offline")career.offline=event.target.checked;
  });
  document.addEventListener("click",async event=>{
    const target=event.target.closest("[data-career-tab],[data-career-remove-job],[data-career-research],[data-career-link-story],[data-career-import-tasks],[data-career-task-story],[data-career-edit-story],[data-career-remove-story],[data-career-cancel-story],[data-career-new-insight],[data-career-insight-task],[data-career-cancel-insight],#career-refresh,#career-export");if(!target)return;
    try{
      if(target.dataset.careerRemoveJob){career.selected.delete(target.dataset.careerRemoveJob);selectedJobs();await findJobs();}
      if(target.dataset.careerTab){captureDrafts();career.tab=target.dataset.careerTab;renderDetail();}
      if(target.dataset.careerResearch)await research(target.dataset.careerResearch,"",0,target.dataset.careerTaskId||null);
      if(target.dataset.careerLinkStory){captureDrafts();career.drafts.set(career.id,{...storyDraft(),requirement_key:target.dataset.careerLinkStory});career.tab="stories";renderDetail();$("#career-story").scrollIntoView({block:"center",behavior:"smooth"});}
      if(target.dataset.careerImportTasks){captureDrafts();career.data=await api(apiPath()+"/tasks",{method:"POST",body:JSON.stringify({step_id:target.dataset.careerImportTasks})});renderDetail();await loadGoals();}
      if(target.dataset.careerTaskStory){captureDrafts();const task=career.data.tasks.find(row=>row.id===target.dataset.careerTaskStory);delete storyDraft().story_id;career.drafts.set(career.id,{...storyDraft(),title:task.title,situation:task.task_or_ability,action:task.outcome,result:task.artifact||task.outcome,limits:"这是个人练习，实际业务环境和职责仍需验证。"});career.tab="stories";renderDetail();}
      if(target.id==="career-refresh")await openCareer(career.id);
      if(target.id==="career-export")await exportPreparation(target);
      if(target.dataset.careerEditStory){const story=career.data.stories.find(row=>row.id===target.dataset.careerEditStory);if(story)editStory(story);}
      if(target.hasAttribute("data-career-cancel-story")){captureDrafts();resetStoryEditor();renderDetail();}
      if(target.dataset.careerRemoveStory){captureDrafts();target.disabled=true;career.data=await api(apiPath()+"/stories/"+encodeURIComponent(target.dataset.careerRemoveStory),{method:"DELETE"});if(storyDraft().story_id===target.dataset.careerRemoveStory)resetStoryEditor();renderDetail();await loadGoals();notify("经历已移出本目标，归档原文和历史研究保留。");}
      if(target.hasAttribute("data-career-new-insight")||target.dataset.careerInsightTask)startInsight(target.dataset.careerInsightTask||null);
      if(target.hasAttribute("data-career-cancel-insight")){captureDrafts();delete storyDraft().insight;renderDetail();}
    }catch(error){target.disabled=false;notify(error.message,true);}
  });
  document.addEventListener("submit",async event=>{
    const form=event.target;if(!["career-story","career-interview-answer","career-resume-form","career-insight","career-manual-experiment"].includes(form.id)&&!form.dataset.careerTaskForm)return;
    event.preventDefault();const submit=event.submitter||form.querySelector("button");submit.disabled=true;captureDrafts();
    try{
      if(form.id==="career-story"){const storyId=storyDraft().story_id;career.data=await api(apiPath()+"/stories"+(storyId?"/"+encodeURIComponent(storyId):""),{method:storyId?"PATCH":"POST",body:JSON.stringify(Object.fromEntries(new FormData(form)))});resetStoryEditor();renderDetail();await loadGoals();notify("经历已保存，后续分析和面试可引用。");}
      else if(form.id==="career-resume-form"){if(form.elements.resume_text.value.length>20000)throw new Error("请把简历正文精简到2万字以内。");career.data=await api(apiPath()+"/resume",{method:"PATCH",body:JSON.stringify({title:form.elements.resume_title.value,text:form.elements.resume_text.value})});delete storyDraft().resume_text;delete storyDraft().resume_title;renderDetail();notify("简历已保存，后续研究将参考这份正文。");}
      else if(form.id==="career-insight"){const data=Object.fromEntries(new FormData(form));data.task_id=data.task_id||null;career.data=await api(apiPath()+"/insights",{method:"POST",body:JSON.stringify(data)});delete storyDraft().insight;renderDetail();notify("这次认识变化已保存，后续研究会参考你的理解和疑问。");}
      else if(form.id==="career-manual-experiment"){career.data=await api(apiPath()+"/experiments",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(form)))});delete storyDraft().manual;delete storyDraft().manual_open;renderDetail();await loadGoals();notify("自己设计的实验已加入练习板。");}
      else if(form.id==="career-interview-answer")await research("answer",form.elements.answer.value,Number(form.elements.question_index.value));
      else{career.data=await api(apiPath()+"/tasks/"+encodeURIComponent(form.dataset.careerTaskForm),{method:"PATCH",body:JSON.stringify(Object.fromEntries(new FormData(form)))});delete storyDraft()["task:"+form.dataset.careerTaskForm];renderDetail();await loadGoals();notify("练习进度与实际观察已保存。");}
    }catch(error){notify(error.message,true);}finally{submit.disabled=false;}
  });
})();

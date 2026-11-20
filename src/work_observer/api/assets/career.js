"use strict";
(()=>{
  const career={id:null,data:null,tab:"requirements",jobs:new Map(),selected:new Map(),timer:null,busy:false,drafts:new Map(),searches:new Map()};
  const labels={reflect:"根据练习结果调整下一步",role:"看清岗位",map:"探索工作地图",gaps:"对照经历与差距",plan:"设计工作样本实验",interview:"准备模拟面试",answer:"反馈我的回答",followup:"沿着回答继续追问",ask:"我的问题",challenge:"两种解释的证据对照"};
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
  const researchUnavailable=data=>Boolean(data?.running||career.busy||data?.results?.some(row=>["queued","running","interrupted"].includes(row.state)));
  const button=(kind,text)=>`<button type="button" class="secondary" data-career-research="${kind}" ${researchUnavailable(career.data)?"disabled":""}>${text||labels[kind]} ↗</button>`;
  const jobText=job=>{const row=job.current||job;return [row.title,row.company_name_raw||row.company||""].filter(Boolean).join(" · ");};
  const apiPath=()=>"career/"+encodeURIComponent(career.id);

  async function importCareerFile(input){
    const file=input.files?.[0];if(!file)return;
    const material=input.hasAttribute("data-career-material-file"),artifact=input.hasAttribute("data-career-artifact-file"),label=material?"工作资料":artifact?"作品材料":"简历",prefix=material?"material":artifact?"artifact":"resume";
    const form=input.closest("form"),status=form.querySelector(material?"[data-material-status]":artifact?"[data-artifact-status]":"[data-resume-status]"),submit=form.querySelector('button[type="submit"],button.primary,button.secondary');
    input.disabled=true;if(submit)submit.disabled=true;status.textContent="正在本地读取"+label+"正文…";
    try{
      if(!/\.(txt|md|markdown|docx|pdf)$/i.test(file.name))throw new Error("支持TXT、Markdown、DOCX和PDF；旧版DOC请先另存为DOCX。");
      if(file.size>8*1024*1024)throw new Error("请选择8MB以内的"+label+"文件。");
      let text,notice="";
      if(/\.(pdf|docx)$/i.test(file.name)){
        const extracted=await api("imports/documents/extract?filename="+encodeURIComponent(file.name),{method:"POST",body:file,headers:{"Content-Type":"application/octet-stream"}});
        text=extracted.text;notice=extracted.notice;
      }else text=(await file.text()).replace(/^\uFEFF/,"");
      if(!text.trim())throw new Error(label+"文件没有可读取的文字。");
      if(!form.isConnected)return;
      form.elements[prefix+"_title"].value=file.name.slice(0,150);form.elements[prefix+"_text"].value=text;
      status.textContent=`已读取 ${text.length} 字。${notice} ${text.length>20000?"请先精简到2万字以内再保存。":"请核对正文后保存；读取不调用模型。"}`;
      if(career.id&&(artifact||material||form.id==="career-resume-form"))captureDrafts();
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
    if(answer){const form=answer.closest("form"),key=form.dataset.sourceStep+":"+form.dataset.questionIndex;data.interview_answers={...data.interview_answers,[key]:answer.value};data.source_step_id=form.dataset.sourceStep;data.question_index=form.dataset.questionIndex;data.answer=answer.value;}
    const resume=$("#career-resume-form");if(resume){data.resume_title=resume.elements.resume_title.value;data.resume_text=resume.elements.resume_text.value;data.resume_open=resume.closest("details").open;}
    const insight=$("#career-insight");if(insight)data.insight={...data.insight,...Object.fromEntries(new FormData(insight))};
    const inquiry=$("#career-inquiry");if(inquiry)data.inquiries={...data.inquiries,[career.tab]:Object.fromEntries(new FormData(inquiry))};
    const challenge=$("#career-challenge");if(challenge)data.challenge={...Object.fromEntries(new FormData(challenge)),open:challenge.closest("details").open};
    const manual=$("#career-manual-experiment");if(manual){data.manual=Object.fromEntries(new FormData(manual));data.manual_open=manual.closest("details").open;}
    const material=$("#career-material-form");if(material)data.material={...Object.fromEntries(new FormData(material)),open:material.closest("details").open};
    const library=$("#career-library-form");if(library)data.library={...Object.fromEntries(new FormData(library)),open:library.closest("details").open};
    const comparison=$(".career-comparison");if(comparison)data.compare_open=comparison.open;
    const intake=$('[data-career-jd="target"]');if(intake)data.target_jd={values:Object.fromEntries($$("[data-jd-field]",intake).map(field=>[field.dataset.jdField,field.value])),open:intake.open};
    const settings=$("#career-settings");if(settings){data.settings=Object.fromEntries(new FormData(settings));data.settings_open=settings.closest("details").open;data.settings_query=$("#career-target-query").value;}
    for(const form of $$("[data-career-task-form]"))data["task:"+form.dataset.careerTaskForm]=Object.fromEntries(new FormData(form));
    career.drafts.set(career.id,data);
  }

  async function loadGoals(){
    const items=await api("career");
    $("#career-goals").innerHTML=items.length?items.map(row=>`<a href="#career/${e(row.id)}" class="career-goal-card ${career.id===row.id?"is-current":""}"><strong>${e(row.title)}</strong><span>${row.job_count} 个目标岗位 · ${row.story_count} 份经历证据</span><small>${row.done_count} / ${row.task_count} 项练习已记录结果 · ${row.insight_count||0} 次复盘</small></a>`).join(""):"";
  }

  function jdIntake(target){
    const draft=target==="target"?storyDraft().target_jd:null,values=draft?.values||{};
    return `<details class="career-jd-intake" data-career-jd="${target}" ${draft?.open?"open":""}><summary>＋ 直接粘贴一份新的JD</summary><div class="form-grid"><label>岗位名称<input data-jd-field="title" maxlength="300" value="${e(values.title||"")}" placeholder="按招聘页面填写"></label><label>公司名称<input data-jd-field="company" maxlength="300" value="${e(values.company||"")}" placeholder="按招聘页面填写"></label></div><label>完整招聘正文<textarea data-jd-field="description" rows="6" maxlength="100000" placeholder="粘贴职责与任职要求，保留必备、加分和方向限定等原文。">${e(values.description||"")}</textarea></label><div class="form-grid"><label>原文链接（可选）<input type="url" data-jd-field="job_url" maxlength="2000" value="${e(values.job_url||"")}" placeholder="https://…"></label><label>资料性质<select data-jd-field="data_kind"><option value="user_provided">我提供的招聘资料</option><option value="synthetic" ${values.data_kind==="synthetic"?"selected":""}>演示用的虚构资料</option></select></label></div><button type="button" class="secondary" data-career-save-jd="${target}">保存JD并选为目标岗位</button><p class="form-note" data-jd-status role="status">只保存你粘贴的文字；不会自动打开链接或调用模型。</p></details>`;
  }
  async function saveInlineJD(button){
    const intake=button.closest("[data-career-jd]"),target=intake.dataset.careerJd,id=career.id;
    const selected=target==="target"?goalJobs():new Map(career.selected);
    if(selected.size>=6)throw new Error("最多选择6个岗位，请先移除一个再补充。");
    const values=Object.fromEntries($$("[data-jd-field]",intake).map(field=>[field.dataset.jdField,field.value.trim()]));
    if(!values.title||!values.company||!values.description)throw new Error("请填写岗位名称、公司和完整招聘正文。");
    if(!values.job_url)delete values.job_url;
    button.disabled=true;const status=intake.querySelector("[data-jd-status]");status.textContent="正在保存岗位原文…";
    try{
      const result=await api("import",{method:"POST",body:JSON.stringify(values)});
      const title=[values.title,values.company].join(" · ");selected.set(result.job_id,title);
      if(target==="target"){
        const draft=career.drafts.get(id)||{};draft.settings_jobs=[...selected];delete draft.target_jd;career.drafts.set(id,draft);
        if(career.id===id){captureDrafts();const updated=storyDraft();updated.settings_jobs=[...selected];delete updated.target_jd;career.drafts.set(id,updated);renderDetail();}
      }else{career.selected=selected;selectedJobs();await findJobs();intake.outerHTML=jdIntake("onboard");}
      await loadOverview();notify(target==="target"?"JD已保存并选中，点击保存调整后用于这个目标。":"JD已保存并选中，可以继续建立求职目标。");
    }catch(error){if(status.isConnected)status.textContent=error.message;throw error;}finally{button.disabled=false;}
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

  function goalJobs(){return new Map(storyDraft().settings_jobs||career.data.jobs.map(job=>[job.id,jobText(job)]));}
  function showGoalJobs(){
    const selected=goalJobs();
    $("#career-target-selection").innerHTML=[...selected].map(([id,title])=>`<button type="button" class="scope-chip" data-career-goal-remove-job="${e(id)}">${e(title)} ×</button>`).join("")||'<p class="form-note">请选择至少一份目标岗位。</p>';
    for(const choice of $$("[data-career-target-job]"))choice.checked=selected.has(choice.dataset.careerTargetJob);
  }
  async function findGoalJobs(){
    const id=career.id,root=$("#career-target-options"),query=$("#career-target-query").value.trim();
    root.innerHTML='<p class="form-note">正在查找岗位…</p>';
    const result=await api("jobs?"+new URLSearchParams({keyword:query,limit:20}));
    if(career.id!==id||!root.isConnected)return;
    career.targetOptions=new Map(result.jobs.map(job=>[job.id,job]));
    root.innerHTML=result.jobs.length?result.jobs.map(job=>`<label class="career-job-option"><input type="checkbox" data-career-target-job="${e(job.id)}" ${goalJobs().has(job.id)?"checked":""}><span><strong>${e(jobText(job))}</strong></span><button type="button" class="text-button" data-job="${e(job.id)}">查看</button></label>`).join(""):empty("没有找到匹配岗位","可以先到岗位资料补充新的JD。");
  }
  function goalSettings(data){
    const values=storyDraft().settings||{title:data.title,goal:data.goal,background:data.profile?.background||"",constraints:data.profile?.constraints||""};
    return `<details class="panel career-settings-panel" ${storyDraft().settings_open?"open":""}><summary>调整目标、个人背景与目标岗位</summary><form id="career-settings"><div class="form-grid"><label>目标名称<input name="title" maxlength="150" required value="${e(values.title)}"></label><label>投入与限制<input name="constraints" maxlength="500" value="${e(values.constraints)}"></label></div><label>我现在希望达到什么目标<textarea name="goal" maxlength="1000" rows="2" required>${e(values.goal)}</textarea></label><label>更新已有经历与能力<textarea name="background" maxlength="1500" rows="3" required>${e(values.background)}</textarea></label><label>目标岗位（最多6个）</label><div id="career-target-selection"></div><div class="research-hub-search"><input id="career-target-query" type="search" value="${e(storyDraft().settings_query||"")}" placeholder="查找想加入的岗位" aria-label="查找想加入目标的岗位"><button type="button" class="secondary" id="career-target-find">查找岗位</button></div><div id="career-target-options"></div>${jdIntake("target")}<div class="result-actions"><button class="primary" ${data.running?"disabled":""}>保存调整</button><button type="button" class="text-button" data-career-cancel-settings>取消修改</button></div><p class="form-note">保存不调用模型。已有经历、练习和认知记录继续保留，新的分析使用更新后的目标与背景。</p></form></details>`;
  }

  function compareJobs(data){
    const saved=(storyDraft().compare_jobs||[]).filter(id=>data.jobs.some(job=>job.id===id));
    return [...new Set([...saved,...data.jobs.map(job=>job.id)])].slice(0,2).map(id=>data.jobs.find(job=>job.id===id));
  }
  function jobComparison(data){
    if(data.jobs.length<2)return "";
    const jobs=compareJobs(data),categories=["business","task","deliverable","responsibility","ability","tool"];
    const jobIds=new Set(data.jobs.map(job=>job.id));
    const refs=row=>[...new Set(row.evidence.map(ev=>ev.job_id).filter(id=>jobIds.has(id)))];
    const shared=data.requirements.filter(row=>refs(row).length>1&&refs(row).some(id=>jobs.some(job=>job.id===id)));
    const proof=row=>`<p class="form-note">${e(requirementLabels[row.requirement]||"性质未说明")} · ${e(claimBasisLabel(row))}</p><p>${e(row.text)}</p><details><summary>看原文</summary>${row.evidence.map(ev=>`<p class="form-note">${e(ev.title)}</p><blockquote>${e(ev.quote)}</blockquote>`).join("")}</details>`;
    const rows=categories.map(category=>{
      const columns=jobs.map(job=>data.requirements.filter(row=>row.category===category&&refs(row).length===1&&refs(row)[0]===job.id));
      return `<tr><th scope="row">${e(workDimensionLabels[category]||category)}</th>${columns.map(items=>`<td>${items.length?items.map(row=>`<article>${proof(row)}</article>`).join(""):'<p class="form-note">当前分析尚未提炼这一项，可打开JD核对；不表示岗位没有这类工作或要求。</p>'}</td>`).join("")}</tr>`;
    }).join("");
    const question=`请比较我选中的两个岗位：${jobText(jobs[0])} 与 ${jobText(jobs[1])}。它们的实际任务、交付物和责任边界有何不同？哪些共用能力可以迁移、哪些尚无依据？请分别引用两侧原文，未写明不等于不需要。`;
    return `<details class="panel career-comparison" ${storyDraft().compare_open?"open":""}><summary>并排看清两个岗位：工作与要求有何不同</summary><p class="form-note">按原文来源展示已有分析，不计算虚假的匹配分。空白表示尚未提炼，跨岗位的综合判断单独列出。</p><div class="form-grid">${jobs.map((job,index)=>`<label>对照岗位 ${index+1}<select data-career-compare-job="${index}">${data.jobs.map(option=>`<option value="${e(option.id)}" ${option.id===job.id?"selected":""}>${e(jobText(option))}</option>`).join("")}</select></label>`).join("")}</div><div class="career-comparison-scroll" tabindex="0" aria-label="岗位工作对照表，可横向滚动"><table><thead><tr><th scope="col">工作维度</th>${jobs.map(job=>`<th scope="col"><strong>${e(jobText(job))}</strong><button type="button" class="text-button" data-job="${e(job.id)}">打开JD ↗</button><p class="form-note">${[job.current.city,job.current.salary_raw,job.current.experience_raw,job.current.education_raw].filter(Boolean).map(e).join(" · ")||"地点、薪资、经验或学历未完整披露"}</p></th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>${shared.length?`<details class="career-comparison-shared"><summary>涉及多个岗位的综合判断</summary>${shared.map(row=>`<article>${proof(row)}</article>`).join("")}</details>`:""}<button type="button" class="secondary" data-career-compare-question="${e(question.slice(0,1500))}">深入研究这两个岗位的差异 ↗</button></details>`;
  }
  function requirements(data){
    const rows=data.requirements;
    return `${jobComparison(data)}<div class="section-heading"><div><h2>岗位要求 × 我的经历证据</h2><p class="form-note">经历由你自述；有材料可讨论，不等于已证明胜任。</p></div><div class="result-actions">${button("role",rows.length?"重新看清岗位":"从原文提炼关键要求")}${button("map","把工作关系画出来")}</div></div>${rows.length?`<div class="career-requirements">${rows.map(row=>{
      const stories=data.stories.filter(story=>story.requirement_key===row.key);
      return `<article class="career-requirement"><div class="career-requirement-main"><div class="result-actions">${badge(categoryLabels[row.category]||row.category,"muted")}${badge(requirementLabels[row.requirement]||"未说明性质",row.requirement==="required"?"amber":"muted")}<span class="form-note">${e(claimBasisLabel(row))} · 待核对</span></div><h3>${e(row.text)}</h3><details><summary>查看原文与补充依据</summary>${row.evidence.map(ev=>`<p class="form-note">${e(ev.title)} · ${ev.job_id?"招聘原文":ev.public_document_id?"补充正文，不单独证明岗位要求":"搜索线索"}</p><blockquote>${e(ev.quote)}</blockquote>`).join("")}</details></div><div class="career-requirement-proof"><span class="quiet-tag">${stories.length?"有自述经历，待核对":"还没有对应的经历证据"}</span>${stories.map(story=>`<p>${e(story.title)}</p>`).join("")}<button type="button" class="text-button" data-career-link-story="${e(row.key)}">${stories.length?"再补充一份证据":"我有哪些经历可以说明？"} ↗</button></div></article>`;
    }).join("")}</div>`:empty("先看清这份工作，再讨论自己差什么","分析会把具体要求与招聘原文放在一起；你可以逐项补充真实项目经历。")}`;
  }

  function stories(data){
    const draft=storyDraft();
    return `<div class="section-heading"><div><h2>我的经历证据库</h2><p class="form-note">写清亲自参与的部分、结果和边界，供研究与模拟面试使用。</p></div><div class="result-actions"><button type="button" class="text-button" data-career-reuse-library>从已有经历与作品里选 ↗</button>${button("gaps")}</div></div>${resumePanel(data)}<div class="career-story-layout"><form id="career-story" class="panel">${draft.story_id?'<p class="career-editing-note">正在修改已保存的经历</p>':""}<label>对应哪项岗位要求<select name="requirement_key"><option value="">作为通用项目经历</option>${data.requirements.map(row=>`<option value="${e(row.key)}" ${draft.requirement_key===row.key?"selected":""}>${e(row.text)}</option>`).join("")}</select></label><label>项目或工作名称<input name="title" required maxlength="150" value="${e(draft.title||"")}" placeholder="例如：客服知识库检索项目"></label><label>要解决的问题<textarea name="situation" required rows="2" maxlength="1500">${e(draft.situation||"")}</textarea></label><label>我亲自做了什么<textarea name="action" required rows="3" maxlength="2000" placeholder="写你的具体行动、关键取舍，区分团队成果与个人参与。">${e(draft.action||"")}</textarea></label><label>实际结果与可查看的证据<textarea name="result" required rows="2" maxlength="1500" placeholder="可以写产物、测试方法、观察，也可以说明暂时没有效果数据。">${e(draft.result||"")}</textarea></label><label>局限、失败或未参与的部分<textarea name="limits" rows="2" maxlength="1000">${e(draft.limits||"")}</textarea></label><button class="primary" ${data.running?"disabled":""}>${draft.story_id?"保存修改":"保存这份经历"}</button>${draft.story_id?'<button type="button" class="text-button" data-career-cancel-story>取消修改</button>':""}</form><div>${data.stories.length?data.stories.map(story=>`<article class="panel career-story-card" data-career-record="story:${e(story.id)}"><span class="quiet-tag">用户自述 · 待核对</span><h3>${e(story.title)}</h3>${story.reused_from?`<p class="form-note">沿用自「${e(story.reused_from.project_title)}」，对新岗位的适用性仍需判断。</p>`:""}<dl>${detailData("场景",story.situation)}${detailData("亲自负责",story.action)}${detailData("结果与证据",story.result)}${detailData("边界",story.limits||"未填写")}</dl><button type="button" class="text-button" data-public-source="${e(story.document_id)}">查看保存的经历原文 ↗</button><div class="result-actions"><button type="button" class="secondary small" data-career-edit-story="${e(story.id)}" ${data.running?"disabled":""}>修改经历 / 关联要求</button><button type="button" class="text-button" data-career-remove-story="${e(story.id)}" ${data.running?"disabled":""}>移出本目标</button></div></article>`).join(""):empty("真实经历比技能词更有用","从一件亲自做过的事开始，尚未成功的尝试也值得保存。")}</div></div>`;
  }

  function challengePanel(data){
    const draft=storyDraft().challenge||{};
    return `<details class="panel career-challenge-panel" ${draft.open?"open":""}><summary>用两种解释，挑战一次认识</summary><form id="career-challenge"><p class="form-note">把尚未想清楚的原因写成两种假设，回查支持与反例。两种解释也可能同时成立，或都缺少依据。</p><label>对照哪次练习的观察<select name="task_id"><option value="">不绑定练习，从当前资料出发</option>${data.tasks.filter(task=>task.outcome).map(task=>`<option value="${e(task.id)}" ${draft.task_id===task.id?"selected":""}>${e(task.title)}</option>`).join("")}</select></label><div class="career-hypotheses"><label>解释 A<textarea name="hypothesis_a" rows="3" required maxlength="700" placeholder="例如：超时触发了重复提交，所以出现重复写入。">${e(draft.hypothesis_a||"")}</textarea></label><label>另一种解释 B<textarea name="hypothesis_b" rows="3" required maxlength="700" placeholder="例如：正常响应也有重复写入，原因可能在请求去重或并发处理。">${e(draft.hypothesis_b||"")}</textarea></label></div><button class="secondary" ${researchUnavailable(data)?"disabled":""}>查证依据、反例与区分方法 ↗</button></form></details>`;
  }
  function experiments(data){
    const plans=data.results.filter(row=>row.current!==false&&row.result?.status==="completed"&&row.result.application_plan?.actions?.length);
    return `<div class="section-heading"><div><h2>用工作样本验证能力</h2><p class="form-note">完成一次练习后，记录实际观察；结果可以成功，也可以推翻原先的判断。</p></div><div class="result-actions"><button type="button" class="text-button" data-career-reuse-library>复用已有作品与练习 ↗</button>${button("plan")}</div></div>${challengePanel(data)}${manualExperiment()}${plans.slice(0,2).map(row=>`<div class="career-plan-invite"><span>研究已给出 ${row.result.application_plan.actions.length} 项行动建议</span><button class="secondary small" data-career-import-tasks="${e(row.step_id)}">加入我的练习板</button></div>`).join("")}<div class="career-kanban">${Object.entries(taskStates).map(([state,label])=>`<section class="career-lane"><h3>${label} <span>${data.tasks.filter(task=>task.state===state).length}</span></h3>${data.tasks.filter(task=>task.state===state).map(task=>{
      const draft=storyDraft()["task:"+task.id]||task;
      return `<article class="panel career-task" data-career-record="task:${e(task.id)}"><span class="quiet-tag">${task.reused_from?"已有的个人练习":task.origin==="user"?"我设计的练习":"研究建议"}</span><h3>${e(task.title)}</h3>${task.reused_from?`<p class="form-note">沿用自「${e(task.reused_from.project_title)}」。这是当时的练习记录，迁移到新岗位仍需验证。</p>`:""}<p>${e(task.task_or_ability)}</p><dl>${detailData("要交付",task.deliverable)}${detailData("怎样检查",task.completion_check)}</dl>${task.assumptions?.length?`<p class="form-note">前提：${task.assumptions.map(e).join("；")}</p>`:""}<details><summary>记录进度与实际结果</summary><form data-career-task-form="${e(task.id)}"><label>练习状态<select name="state">${Object.entries(taskStates).map(([value,label])=>`<option value="${value}" ${draft.state===value?"selected":""}>${label}</option>`).join("")}</select></label><label>原先的预期或想验证的判断<textarea name="hypothesis" rows="2" maxlength="1500" placeholder="例如：加上重试就能解决请求失败；通过这个实验检查它是否成立。">${e(draft.hypothesis||"")}</textarea></label><label>实际做了什么、观察到什么<textarea name="outcome" rows="3" maxlength="4000">${e(draft.outcome||"")}</textarea></label><label>作品链接或产物位置<input name="artifact" maxlength="1000" value="${e(draft.artifact||"")}" placeholder="保存为文字，不会自动打开或上传"></label><details class="career-task-material"><summary>${task.artifact_document_id?"补充或替换作品材料":"附上作品说明、测试记录或日志"}</summary><label class="research-file-drop"><input type="file" data-career-artifact-file accept=".txt,.md,.markdown,.docx,.pdf"><strong>选择作品材料文件</strong><span>TXT / Markdown / Word / PDF，本地读取文字</span></label><label>材料名称<input name="artifact_title" maxlength="150" value="${e(draft.artifact_title||task.title+' · 作品材料')}"></label><label>或粘贴作品与运行记录<textarea name="artifact_text" rows="5" maxlength="20000" placeholder="例如：实验设置、输入、实际输出、错误日志和观察。保留限制，不填密钥等私密信息。">${e(draft.artifact_text||"")}</textarea></label><p class="form-note" data-artifact-status role="status">保存后可供反思与模拟面试回查；材料仍是你提供的记录，未由系统独立运行。</p></details><button class="secondary small">保存进度与材料</button></form></details>${task.hypothesis?`<p class="career-observation"><strong>原先预期：</strong>${e(task.hypothesis)}</p>`:""}${task.outcome?`<p class="career-observation"><strong>实际观察：</strong>${e(task.outcome)}</p>`:""}${task.artifact?`<p class="form-note">产物：${e(task.artifact)}</p>`:""}${task.artifact_document_id?`<button type="button" class="text-button" data-public-source="${e(task.artifact_document_id)}">查看作品材料：${e(task.artifact_title)} ↗</button>`:""}${task.outcome?`<button type="button" class="secondary" data-career-research="reflect" data-career-task-id="${e(task.id)}" ${researchUnavailable(data)?"disabled":""}>反思这次练习 ↗</button><button type="button" class="text-button" data-career-task-story="${e(task.id)}">把这次练习补成经历证据 ↗</button>`:""}</article>`;
    }).join("")||'<p class="form-note">还没有这一状态的练习</p>'}</section>`).join("")}</div>${!data.tasks.length?'<p class="form-note">先生成工作样本建议，再加入练习板。建议会结合岗位原文、你的背景与投入限制。</p>':""}${learningNotes(data)}`;
  }

  function manualExperiment(){
    const draft=storyDraft().manual||{};
    return `<details class="panel career-manual-experiment" ${storyDraft().manual_open?"open":""}><summary>自己设计一项工作样本实验</summary><form id="career-manual-experiment"><p class="form-note">把已有的验证想法放进练习板，保存不调用模型。</p><label>这项实验叫什么<input name="title" required maxlength="150" value="${e(draft.title||"")}" placeholder="例如：比较两种检索方案的失败案例"></label><label>针对什么任务或能力<input name="task_or_ability" required maxlength="500" value="${e(draft.task_or_ability||"")}"></label><label>原先的预期或想验证的判断<textarea name="hypothesis" maxlength="1500" rows="2">${e(draft.hypothesis||"")}</textarea></label><label>准备交付什么<textarea name="deliverable" required maxlength="700" rows="2" placeholder="例如：可运行的样例、测试集和观察记录">${e(draft.deliverable||"")}</textarea></label><label>怎样检查它是否完成<textarea name="completion_check" required maxlength="700" rows="2" placeholder="写可实际执行的检查；也可以记录哪些结果会推翻原来的预期。">${e(draft.completion_check||"")}</textarea></label><button class="primary">加入我的练习板</button></form></details>`;
  }

  const interviewSources=data=>data.results.filter(row=>["interview","followup"].includes(row.kind)&&row.current!==false&&row.result?.status==="completed"&&(row.result.gaps||[]).some(text=>/[?？]/.test(text)));
  const interviewQuestions=row=>(row?.result.gaps||[]).filter(text=>/[?？]/.test(text));
  function interview(data){
    const sources=interviewSources(data),draft=storyDraft();
    const selected=sources.find(row=>row.step_id===(draft.next_source_step_id||draft.source_step_id))||sources[0];
    const questions=interviewQuestions(selected),index=Math.min(Number(draft.question_index||0),Math.max(0,questions.length-1));
    const key=selected?.step_id+":"+index,answer=draft.interview_answers?.[key]??(!draft.source_step_id?draft.answer||"":"");
    const attempts=data.results.filter(row=>row.kind==="answer"&&row.interview_question===questions[index]).reverse();
    return `<div class="section-heading"><div><h2>让真实经历经得住追问</h2><p class="form-note">先回答，再根据真实回答追问；也可以重答同一道题，回看表达与证据的变化。</p></div>${button("interview")}</div>${selected?`<form id="career-interview-answer" class="panel career-answer-form" data-source-step="${e(selected.step_id)}" data-question-index="${index}"><div class="form-grid"><label>本次练习哪组问题<select name="source_step_id">${sources.map(row=>`<option value="${e(row.step_id)}" ${row===selected?"selected":""}>${row.kind==="followup"?"针对回答的追问":"岗位模拟面试"} · ${e(when(row.created_at))}</option>`).join("")}</select></label><label>选择本次回答的问题<select name="question_index">${questions.map((text,n)=>`<option value="${n}" ${index===n?"selected":""}>${n+1}. ${e(text)}</option>`).join("")}</select></label></div><blockquote class="career-active-question">${e(questions[index])}</blockquote><label>写下你的真实回答<textarea id="career-answer" name="answer" rows="6" maxlength="2500" required placeholder="写实际行动、当时的选择、验证方法，以及你还说不清的部分。">${e(answer)}</textarea></label><button class="primary" ${researchUnavailable(data)?"disabled":""}>结合原文反馈我的回答 ↗</button></form>${attempts.length?`<section class="career-interview-replay"><div class="section-heading"><div><h3>这道题，我回答过 ${attempts.length} 次</h3><p class="form-note">按时间对照自己的回答，结合实际材料判断哪些地方更清楚了。</p></div></div>${attempts.slice(-3).map((row,n)=>`<details class="panel career-attempt" ${n===Math.min(2,attempts.length-1)?"open":""}><summary>第 ${Math.max(0,attempts.length-3)+n+1} 次回答 · ${e(when(row.created_at))}</summary><p class="career-attempt-text">${e(row.answer)}</p>${row.answer_document_id?`<button type="button" class="text-button" data-public-source="${e(row.answer_document_id)}">查看本次回答全文 ↗</button>`:""}${row.result?.status==="completed"?`<p class="form-note">研究反馈，待结合原文核对</p>${row.result.claims.map(claim=>`<p>${e(claim.text)}</p>`).join("")}${(row.result.gaps||[]).filter(text=>!text.startsWith("静态有限样本")).map(text=>`<p class="form-note">${e(text)}</p>`).join("")}`:'<p class="form-note">这一轮反馈尚未完整形成。</p>'}${row.current===false?'<p class="form-note">来自调整前的目标，仅供回看。</p>':row.result?.status==="completed"?`<div class="result-actions"><button type="button" class="secondary" data-career-followup="${e(row.step_id)}" ${researchUnavailable(data)?"disabled":""}>针对这次回答继续追问 ↗</button></div>`:""}</details>`).join("")}</section>`:""}`:empty("从你的材料出发的一次模拟面试","先补充一份经历，或直接准备面试问题；缺少的信息会明确指出。")}`;
  }

  function learningNotes(data){
    const draft=storyDraft().insight;
    return `<section class="career-learning-notes"><div class="section-heading"><div><h2>我改变了哪些认识</h2><p class="form-note">记录自己的理解与疑问，下一轮研究可以沿着这些问题继续。</p></div>${!draft?'<button type="button" class="secondary" data-career-new-insight>记录一次认识变化</button>':""}</div>${draft?`<form id="career-insight" class="panel"><input type="hidden" name="source_step_id" value="${e(draft.source_step_id||"")}">${draft.id?'<p class="career-editing-note">修改已保存的认识记录</p>':""}<p class="form-note">结合原文和实际观察编辑成自己的理解，保存不会调用模型。</p><label>来自哪次练习<select name="task_id"><option value="">不绑定某项练习</option>${data.tasks.map(task=>`<option value="${e(task.id)}" ${draft.task_id===task.id?"selected":""}>${e(task.title)}</option>`).join("")}</select></label><label>我原先的理解，或最初的问题<textarea name="previous_view" rows="2" required maxlength="1500">${e(draft.previous_view||"")}</textarea></label><label>看到了什么证据或实际观察<textarea name="observation" rows="2" required maxlength="2000">${e(draft.observation||"")}</textarea></label><label>现在我怎么理解<textarea name="current_view" rows="3" required maxlength="1500">${e(draft.current_view||"")}</textarea></label><label>仍不确定什么、下一步要验证什么<textarea name="open_question" rows="2" maxlength="1000">${e(draft.open_question||"")}</textarea></label><div class="result-actions"><button class="primary">记入我的认知记录</button><button type="button" class="text-button" data-career-cancel-insight>取消</button></div></form>`:""}${(data.insights||[]).length?`<div class="career-learning-timeline">${[...data.insights].reverse().map(note=>`<article class="panel career-learning-note" data-career-record="insight:${e(note.id)}"><p class="form-note">${e(when(note.updated_at||note.created_at))} · 我的复盘${note.updated_at?" · 已修改":""}</p><div class="career-learning-change"><div><h3>原先的理解</h3><p>${e(note.previous_view)}</p></div><span aria-hidden="true">→</span><div><h3>现在的理解</h3><p>${e(note.current_view)}</p></div></div><details><summary>为什么改变、还有什么未知</summary><p><strong>观察：</strong>${e(note.observation)}</p>${note.open_question?`<p><strong>下一步：</strong>${e(note.open_question)}</p>`:""}</details><div class="result-actions"><button type="button" class="text-button" data-career-edit-insight="${e(note.id)}">修改这份认识</button><button type="button" class="text-button" data-career-challenge-insight="${e(note.id)}">用另一个解释挑战它 ↗</button>${note.source_step_id?`<button type="button" class="text-button" data-career-open-insight-source="${e(note.source_step_id)}">回看当时的讨论 ↗</button>`:""}${note.open_question?`<button type="button" class="secondary" data-career-insight-question="${e(note.id)}">沿着这个未知继续问 ↗</button>`:""}</div></article>`).join("")}</div>`:!draft?'<p class="form-note">一次失败的实验、一次原文重读，或一个还没解决的问题，都可以成为新的起点。</p>':""}</section>`;
  }

  function startInsight(taskId=null,resultId=null){
    captureDrafts();const draft=storyDraft();
    if(!draft.insight){
      const task=career.data.tasks.find(row=>row.id===taskId);
      const discussion=career.data.results.find(row=>row.step_id===resultId);
      const reflection=discussion||career.data.results.find(row=>row.kind==="reflect"&&row.task_id===taskId&&row.result?.status==="completed");
      const proposed=reflection?.result.claims?.[0]?.text||"";
      const open=reflection?.result.gaps?.find(text=>!text.startsWith("静态有限样本"))||"";
      draft.insight={task_id:taskId||discussion?.task_id||"",source_step_id:reflection?.step_id||"",previous_view:(discussion?.answer||discussion?.hypothesis_a||discussion?.user_question||task?.hypothesis||"").slice(0,1500),observation:discussion?(discussion.result.evidence||[]).map(ev=>ev.title+"："+ev.quote).join("\n").slice(0,2000):task?.outcome?.length<=2000?task.outcome:"",current_view:proposed.length<=1500?proposed:"",open_question:open.length<=1000?open:""};
      career.drafts.set(career.id,draft);
    }
    career.tab="experiments";renderDetail();$("#career-insight").scrollIntoView({block:"center",behavior:"smooth"});
  }

  function careerWorkMap(row,evidence){
    const result=row.result,map=result?.work_map;if(!map)return "";
    const refs=item=>[...new Set(item.claim_indices.flatMap(index=>result.claims[index]?.evidence_ids||[]))].filter(id=>evidence.has(id)).map(id=>`<button type="button" class="cite" data-cite="${e(id)}">${e(evidence.get(id).label)} ↗</button>`).join(" ");
    const claims=item=>item.claim_indices.map(index=>`<p class="form-note">${e(result.claims[index]?.text||"")}</p>`).join("");
    const basis=item=>badge(({direct:"原文明示",synthesis:"归纳",inference:"待验证解释"})[item.basis]||"待验证解释","muted");
    return `<section class="career-work-map"><h3>看懂工作如何产生结果</h3><p class="form-note">${e(map.scope_note)}</p>${renderWorkRelationGraph({...result,project_id:null},refs,claims,basis)}${(map.work_types||[]).map(work=>`<details class="career-work-type"><summary>${e(work.name)}</summary><p><strong>业务问题：</strong>${e(work.problem)}</p><p><strong>主要任务：</strong>${e(work.tasks)}</p><p><strong>交付物：</strong>${e(work.deliverables)}</p><p class="form-note">边界：${e(work.boundary)}</p>${refs(work)}</details>`).join("")}${(map.comparisons||[]).map(comparison=>`<details class="career-work-type"><summary>工作的共用点、差异与迁移条件</summary>${renderComparisonDetails(comparison)}${refs(comparison)}</details>`).join("")}${map.work_relations?.length?`<div class="career-map-explore"><p class="form-note">选一条关系继续讨论：</p>${map.work_relations.map(relation=>`<button type="button" class="text-button" data-career-ask-result="${e(row.step_id)}" data-career-map-question="${e('请解释这条工作关系为什么成立、对我的求职准备意味着什么，以及哪里还需要验证：'+relation.source_text.slice(0,350)+' → '+(workPredicateLabels[relation.predicate]||relation.predicate)+' → '+relation.target_text.slice(0,350))}">${e(relation.source_text.slice(0,36))} → ${e(workPredicateLabels[relation.predicate]||relation.predicate)} → ${e(relation.target_text.slice(0,36))} ↗</button>`).join("")}</div>`:""}<details><summary>仍不确定什么</summary><ul>${map.unknowns.map(text=>`<li>${e(text)}</li>`).join("")}</ul></details></section>`;
  }
  function coachingResult(row){
    const result=row.result;if(!result)return '<p class="form-note">这一轮还没有可展示的结果，可在完整研究记录中查看进度。</p>';
    const evidence=new Map((result.evidence||[]).map((ev,index)=>[ev.id,{...ev,label:"E"+(index+1)}]));
    const cites=ids=>(ids||[]).filter(id=>evidence.has(id)).map(id=>`<button type="button" class="cite" data-cite="${e(id)}">${e(evidence.get(id).label)} ↗</button>`).join(" ");
    const completed=result.status==="completed",plan=result.application_plan;
    const claims=completed?result.claims:result.submission_feedback?.draft_claims||[];
    const body=claims.map(claim=>`<article class="career-coaching-point"><div class="result-actions">${badge(categoryLabels[claim.category]||claim.category,"muted")}${claim.requirement!=="unspecified"?badge(requirementLabels[claim.requirement]||"性质待核","muted"):""}<span class="form-note">${e(claimBasisLabel(claim))}</span></div><p>${e(claim.text)}</p>${cites(claim.evidence_ids)}</article>`).join("");
    const gaps=(result.gaps||[]).filter(text=>!text.startsWith("静态有限样本")&&!text.startsWith("研究未完成，已有证据"));
    return `<article class="panel result-card career-coaching-result">${row.state==="abandoned"?'<p class="career-result-notice">这轮已由你结束，已读原文和未完成草稿仍可回看，不会自动续跑。</p>':""}<div class="section-heading"><h3>${e(labels[row.kind])}</h3>${badge(statusLabels[result.status]||result.status,completed?"":"amber")}</div>${result.audit?.stale_dependencies||result.audit?.stale_memory||result.audit?.changed_sources?.length?'<p class="career-result-notice">所用资料或背景已有变化，以下保留当时的分析，需重新核实。</p>':""}${row.current===false&&!result.audit?.stale_memory&&!result.audit?.stale_dependencies&&!result.audit?.changed_sources?.length&&result.business_review?.status!=="rejected"?'<p class="career-result-notice">这份分析来自调整前的目标，仅供回看。新的分析请按当前岗位和背景展开。</p>':""}${result.business_review?.status==="rejected"?'<p class="career-result-notice">这份研究的质量核对未通过，请查看完整记录并修正。</p>':""}${row.kind==="challenge"?`<section class="career-hypotheses"><div><span class="quiet-tag">待验证解释 A</span><p>${e(row.hypothesis_a)}</p></div><div><span class="quiet-tag">待验证解释 B</span><p>${e(row.hypothesis_b)}</p></div></section>`:""}${row.user_question&&row.kind!=="challenge"?`<blockquote class="career-user-question">${e(row.user_question)}</blockquote>`:""}${row.answer_document_id?`<button type="button" class="text-button" data-public-source="${e(row.answer_document_id)}">查看这次讨论涉及的回答原文 ↗</button>`:""}${result.public_searches||result.public_reads?`<p class="career-result-notice">本轮进行了 ${result.public_searches||0} 次公开搜索、${result.public_reads||0} 次正文读取。公开说明用于解释业务与技术，不单独证明岗位个人职责或任职要求。</p>`:""}${row.kind==="answer"?`<section class="career-answer-record"><h4>我当时的回答</h4>${row.interview_question?`<p class="form-note">问题：${e(row.interview_question)}</p>`:""}<p>${e(row.answer)}</p></section>`:""}${completed?careerWorkMap(row,evidence)+body:`<p class="career-result-notice">${result.status==="evidence_only"?"已整理原文，尚未分析。取消“只整理原文”后，可选择需要的研究步骤。":e(reasonLabels[result.stop_reason]||"这一轮没有形成完整回答，已读原文仍可查阅。")}</p>${body?'<details><summary>查看未完成草稿（尚未采用）</summary>'+body+'</details>':""}`}${completed&&plan?.actions?.length?`<section class="career-coaching-plan"><h3>可尝试的工作样本</h3>${plan.actions.map((action,index)=>`<article><h4>${index+1}. ${e(action.title)}</h4><p><strong>产物：</strong>${e(action.deliverable)}</p><p><strong>检查：</strong>${e(action.completion_check)}</p>${action.assumptions?.length?`<p class="form-note">前提：${action.assumptions.map(e).join("；")}</p>`:""}${cites(action.evidence_ids)}</article>`).join("")}<p class="form-note">这是基于资料与个人背景的练习建议，实际结果需要自己验证。</p></section>`:""}${gaps.length&&!["interview","followup"].includes(row.kind)?`<section class="career-coaching-questions"><h3>还值得继续核实</h3><ul>${gaps.map(text=>'<li>'+e(text)+'</li>').join("")}</ul></section>`:""}<details class="career-coaching-sources"><summary>查看 ${evidence.size} 份引用原文</summary>${[...evidence.values()].map(ev=>`<details data-evidence="${e(ev.id)}"><summary>${e(ev.label)} · ${e(ev.title)}${["search_answer","search_excerpt"].includes(ev.evidence_kind)?" · 搜索线索，未核正文":ev.evidence_kind==="public_document"?" · 已归档公开正文":""}</summary><p class="form-note">${e(ev.company||ev.publisher||"")} · 原文字符 ${ev.start}–${ev.end}</p><blockquote>${e(ev.quote)}</blockquote>${ev.public_document_id?`<button class="text-button" data-public-source="${e(ev.public_document_id)}">查看完整归档 ↗</button>`:""}</details>`).join("")}</details>${row.kind==="reflect"&&row.task_id&&completed?`<button type="button" class="secondary" data-career-insight-task="${e(row.task_id)}">记下这次认识变化 ↗</button>`:""}${completed&&row.current!==false&&row.kind==="answer"?`<button type="button" class="secondary" data-career-answer-plan="${e(row.step_id)}">针对这次回答，设计一次补证据练习 ↗</button>`:""}${completed&&row.current!==false&&["ask","answer","challenge"].includes(row.kind)?`<button type="button" class="secondary" data-career-insight-result="${e(row.step_id)}">把这次讨论记成我的认识 ↗</button>`:""}${completed&&row.current!==false?`<button type="button" class="text-button" data-career-ask-result="${e(row.step_id)}">接着这份分析继续问 ↗</button>`:""}<p class="form-note"><a href="#research/${e(career.id)}">查看完整研究与过程 ↗</a></p></article>`;
  }

  function preparationPackage(data){
    const paragraph=value=>`<p>${e(value||"未记录").replace(/\n/g,"<br>")}</p>`;
    const sourceQuotes=row=>(row.result?.evidence||[]).length?`<details><summary>本轮引用的原文</summary>${row.result.evidence.map(ev=>`<p class="meta">${e(ev.title)}${["search_answer","search_excerpt"].includes(ev.evidence_kind)?" · 搜索线索，未核正文":""}${safeURL(ev.url)?` · <a href="${e(safeURL(ev.url))}">公开出处</a>`:""}</p><blockquote>${e(ev.quote)}</blockquote>`).join("")}</details>`:"";
    const latestMap=data.results.find(row=>row.current!==false&&row.result?.status==="completed"&&row.result.work_map);
    const mapHtml=latestMap?`<h2>工作关系与迁移边界</h2>${(latestMap.result.work_map.work_relations||[]).map(relation=>`<article><h3>${e(relation.source_text)} → ${e(workPredicateLabels[relation.predicate]||relation.predicate)} → ${e(relation.target_text)}</h3>${paragraph(relation.rationale)}<h4>适用与迁移边界</h4>${paragraph(relation.transfer_limit)}</article>`).join("")}<h4>仍不确定什么</h4>${latestMap.result.work_map.unknowns.map(paragraph).join("")}`:"";
    const requirements=data.requirements.map(row=>`<article><h3>${e(row.text)}</h3><p class="meta">${e(categoryLabels[row.category]||row.category)} · ${e(requirementLabels[row.requirement]||"性质未说明")} · ${e(claimBasisLabel(row))}</p>${row.evidence.map(ev=>`<details open><summary>${e(ev.title)} · 引用原文</summary><blockquote>${e(ev.quote)}</blockquote></details>`).join("")}</article>`).join("");
    const stories=data.stories.map(row=>`<article><h3>${e(row.title)}</h3>${row.reused_from?`<p class="meta">沿用自 ${e(row.reused_from.project_title)}，新岗位的适用性尚未验证。</p>`:""}<h4>场景与目标</h4>${paragraph(row.situation)}<h4>亲自参与</h4>${paragraph(row.action)}<h4>结果与证据</h4>${paragraph(row.result)}<h4>局限与未参与部分</h4>${paragraph(row.limits)}</article>`).join("");
    const experiments=data.tasks.map(row=>`<article><h3>${e(row.title)} · ${e(taskStates[row.state])}</h3><p class="meta">${row.reused_from?"沿用自 "+e(row.reused_from.project_title)+" 的个人练习，迁移仍待验证":row.origin==="user"?"用户设计的练习":"研究提出的建议"}</p><h4>要交付什么</h4>${paragraph(row.deliverable)}<h4>怎样检查</h4>${paragraph(row.completion_check)}<h4>原先的预期</h4>${paragraph(row.hypothesis)}<h4>实际观察</h4>${paragraph(row.outcome)}<h4>产物位置</h4>${paragraph(row.artifact)}${row.artifact_text?`<details open><summary>${e(row.artifact_title)} · 用户提供的作品材料</summary><blockquote>${e(row.artifact_text)}</blockquote></details>`:""}</article>`).join("");
    const interviews=data.results.filter(row=>row.kind==="answer").reverse().map(row=>`<article><h3>${e(row.interview_question||"模拟面试回答")}</h3><h4>我的回答</h4>${paragraph(row.answer)}<h4>研究反馈</h4>${row.result?.status==="completed"?row.result.claims.map(claim=>paragraph(claim.text)).join("")+(row.result.gaps||[]).filter(text=>!text.startsWith("静态有限样本")).map(text=>paragraph(text)).join(""):'<p>本轮反馈尚未完整形成。</p>'}${sourceQuotes(row)}</article>`).join("");
    return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${e(data.title)} · 求职准备包</title><style>body{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:0;background:#f4f7f1;color:#25382c;line-height:1.9}main{max-width:940px;margin:30px auto;background:white;padding:40px;border-radius:16px}header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #dfe7da;padding-bottom:18px;font-size:12px;color:#55724d}button{border:0;background:#315c46;color:white;padding:10px 16px;border-radius:8px;cursor:pointer}h1{font-size:30px;line-height:1.5}h2{font-size:21px;margin-top:36px;border-top:1px solid #dfe7da;padding-top:22px}h3{font-size:16px}h4{font-size:12px;color:#71846b;margin:18px 0 3px}p{font-size:14px;margin:5px 0 14px;overflow-wrap:anywhere}article{padding:18px 22px;background:#f7f9f4;border-radius:10px;margin:14px 0}blockquote{white-space:pre-wrap;background:white;border-left:2px solid #8fa882;margin:10px 0;padding:12px;font-size:12px}.meta{font-size:12px;color:#74846c}summary{font-size:12px;cursor:pointer}@media(max-width:600px){main{margin:0;padding:23px;border-radius:0}h1{font-size:25px}}@media print{body{background:white}main{margin:0;padding:0}header button{display:none}h2,h3{break-after:avoid}article{break-inside:avoid}}</style></head><body><main><header><strong>WORK OBSERVER / 求职准备包</strong><button onclick="window.print()">打印 / 保存为 PDF</button></header><h1>${e(data.title)}</h1>${paragraph(data.goal)}<p class="meta">导出于 ${e(when(new Date().toISOString()))}。项目经历与实验观察由用户自述；研究结论、建议及个人能力仍需结合原文和实际产物核对。</p><h2>我的背景与投入</h2>${paragraph(data.profile?.background)}${paragraph(data.profile?.constraints)}<h2>目标岗位</h2>${data.jobs.map(job=>paragraph(jobText(job))).join("")}${data.resume_text?`<details open><summary>我提供的简历原文</summary><blockquote>${e(data.resume_text)}</blockquote></details>`:""}<h2>岗位要求与原文</h2>${requirements||'<p>尚未提炼岗位要求。</p>'}${mapHtml}${data.material_texts?.length?`<h2>补充工作资料</h2>${data.material_texts.map(row=>`<article><h3>${e(row.title)}</h3><p class="meta">${e(row.publisher)} · 来源说明尚需核对</p><blockquote>${e(row.text)}</blockquote></article>`).join("")}`:""}<h2>我的经历证据</h2>${stories||'<p>尚未保存经历。</p>'}<h2>工作样本：预期与观察</h2>${experiments||'<p>尚未保存练习。</p>'}<h2>我的认识如何变化</h2>${(data.insights||[]).map(note=>`<article><h3>${e(when(note.created_at))}</h3><h4>原先的理解</h4>${paragraph(note.previous_view)}<h4>实际观察</h4>${paragraph(note.observation)}<h4>现在的理解</h4>${paragraph(note.current_view)}<h4>仍待验证</h4>${paragraph(note.open_question)}</article>`).join("")||"<p>尚未记录认识变化。</p>"}<h2>模拟面试与反馈</h2>${interviews||'<p>尚未保存面试回答。</p>'}<h2>我的问题与探索</h2>${data.results.filter(row=>["ask","challenge"].includes(row.kind)).reverse().map(row=>`<article><h3>${e(row.user_question)}</h3>${row.current===false?'<p class="meta">当时目标下的讨论，仅供回看。</p>':""}${row.result?.status==="completed"?row.result.claims.map(claim=>paragraph(claim.text)).join("")+(row.result.gaps||[]).filter(text=>!text.startsWith("静态有限样本")).map(paragraph).join(""):'<p>尚未完整形成回答。</p>'}${sourceQuotes(row)}</article>`).join("")||'<p>尚未保存自选问题。</p>'}</main></body></html>`;
  }

  async function exportPreparation(button){
    button.disabled=true;
    try{
      const data=await api(apiPath());
      if(data.resume)data.resume_text=(await api("public-documents/"+encodeURIComponent(data.resume.document_id))).text;
      await Promise.all(data.tasks.filter(task=>task.artifact_document_id).map(async task=>{task.artifact_text=(await api("public-documents/"+encodeURIComponent(task.artifact_document_id))).text;}));
      data.material_texts=await Promise.all([...new Map([...(data.materials||[]),...(data.discovered_materials||[])].map(row=>[row.id,row])).values()].map(row=>api("public-documents/"+encodeURIComponent(row.id))));
      const html=preparationPackage(data);
      const url=URL.createObjectURL(new Blob([html],{type:"text/html;charset=utf-8"}));
      const link=document.createElement("a");link.href=url;link.download="求职准备包-"+data.title.replace(/[<>:"/\\|?*\u0000-\u001f]/g,"_").slice(0,70)+".html";
      document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(error){notify(error.message,true);}finally{button.disabled=false;}
  }

  const sectionKinds={requirements:["role","map"],stories:["gaps"],experiments:["plan","reflect","challenge"],interview:["interview","answer","followup"]};
  const inCareerSection=row=>row.kind==="ask"?row.section===career.tab:sectionKinds[career.tab].includes(row.kind);
  function inquiryPanel(data){
    const draft=storyDraft().inquiries?.[career.tab]||{},sources=data.results.filter(row=>inCareerSection(row)&&row.current!==false&&row.result?.status==="completed").slice(0,12);
    const prompts={requirements:"例如：这两个岗位都写Agent，实际交付和责任边界有什么不同？",stories:"例如：我的接口项目在哪些任务上能迁移，哪些地方还没有证据？",experiments:"例如：两组测试都失败了，是否说明我的原先解释不成立？",interview:"例如：我这次回答哪里混淆了亲自参与和团队结果？"};
    return `<section class="panel career-inquiry-panel"><div><span class="eyebrow">FOLLOW YOUR QUESTION</span><h3>把你真正想弄清楚的问题问下去</h3><p class="form-note">结合当前岗位和你的记录回答，可继续讨论已有分析。</p></div><form id="career-inquiry"><input type="hidden" name="material_id" value="${e(draft.material_id||"")}">${draft.material_id?`<p class="form-note">本次围绕：${e(data.materials?.find(row=>row.id===draft.material_id)?.title||"已选资料")} <button type="button" class="text-button" data-career-clear-material-focus>不限定这份资料</button></p>`:""}<label>这次想弄清楚什么<textarea name="question" rows="2" required maxlength="1500" placeholder="${e(prompts[career.tab])}">${e(draft.question||"")}</textarea></label><div class="career-inquiry-actions"><label>接着哪份分析讨论<select name="source_step_id"><option value="">直接从当前资料提问</option>${sources.map(row=>`<option value="${e(row.step_id)}" ${draft.source_step_id===row.step_id?"selected":""}>${e(row.user_question||labels[row.kind])} · ${e(when(row.created_at))}</option>`).join("")}</select></label><button class="primary" ${researchUnavailable(data)?"disabled":""}>研究我的问题 ↗</button></div></form></section>`;
  }
  function materialShelf(data){
    const draft=storyDraft().material||{};
    return `<div class="career-material-shelf"><h3>这次研究还参考哪些资料</h3>${(data.materials||[]).map(row=>`<article class="career-material-card"><div><strong>${e(row.title)}</strong><p class="form-note">${e(row.publisher)} · ${row.full_text_length} 字保存正文</p></div><div class="result-actions"><button type="button" class="text-button" data-public-source="${e(row.id)}">读原文 ↗</button><button type="button" class="secondary small" data-career-material-question="${e(row.id)}">围绕这份资料提问 ↗</button><button type="button" class="text-button" data-career-remove-material="${e(row.id)}" ${data.running?"disabled":""}>移出本目标</button></div></article>`).join("")||'<p class="form-note">可以补充业务说明、技术文档或自己的调查笔记；资料中的业务介绍不能直接证明某个岗位的个人职责。</p>'}${data.discovered_materials?.length?`<h3>研究中读到的公开正文</h3><p class="form-note">已保存供回查；用于业务和技术背景，不单独证明岗位职责或个人能力。</p>${data.discovered_materials.map(row=>`<article class="career-material-card career-discovered-material"><strong>${e(row.title)}</strong><p class="form-note">${e(row.publisher)} · ${row.full_text_length} 字保存正文</p><div class="result-actions"><button type="button" class="text-button" data-public-source="${e(row.id)}">读归档全文 ↗</button><button type="button" class="secondary small" data-career-attach-material="${e(row.id)}">用于后续研究</button></div></article>`).join("")}`:""}<details class="career-material-editor" ${draft.open?"open":""}><summary>＋ 补充一份工作资料</summary><form id="career-material-form"><label class="research-file-drop"><input type="file" data-career-material-file accept=".txt,.md,.markdown,.docx,.pdf"><strong>导入资料文件</strong><span>TXT / Markdown / Word / PDF，本地读取文字</span></label><label>资料名称<input name="material_title" required maxlength="150" value="${e(draft.material_title||"")}"></label><label>来源说明（可选）<input name="source_name" maxlength="500" value="${e(draft.source_name||"")}" placeholder="例如：我从公司介绍中复制；来源说明不会被视为独立核实"></label><label>原文或调查记录<textarea name="material_text" required rows="5" maxlength="20000" placeholder="可直接粘贴文字。保留出处、关键条件和不确定之处。">${e(draft.material_text||"")}</textarea></label><p class="form-note" data-material-status role="status">保存不调用模型，也不会自动访问外部网址。后续由你选择如何研究。</p><button class="secondary" ${data.running?"disabled":""}>保存并用于当前目标</button></form></details></div>`;
  }
  function evidenceLibrary(data){
    const draft=storyDraft().library||{},found=career.searches.get(data.id);
    const show=found&&found.query===draft.q&&found.scope===(draft.scope||"goal");
    const recordLabels={story:"我的经历自述",task:"实验预期与观察",insight:"我的认识与疑问",discussion:"当时的研究与回答"};
    const results=show?`<div class="career-library-results"><h3>原文材料</h3><p class="form-note">${found.originals.matching_jobs} 个岗位、${found.originals.matching_public_documents} 份归档材料命中；展示 ${found.originals.evidence.length} 个片段。${found.originals.truncated?"还有命中片段未展示，可以缩小关键词范围。":""}</p>${found.originals.evidence.map(ev=>`<article class="career-library-hit"><span class="quiet-tag">${ev.evidence_kind==="job_original"?"招聘原文":ev.evidence_kind==="work_material"?"用户提供材料":"归档资料"}</span><h4>${e(ev.title)}</h4><blockquote>${e(ev.quote)}</blockquote><p class="form-note">${e(ev.source_note||ev.scope_note||"")}</p>${ev.public_document_id?`<button type="button" class="text-button" data-public-source="${e(ev.public_document_id)}">打开归档全文 ↗</button>${!(data.document_ids||[]).includes(ev.public_document_id)?`<button type="button" class="secondary small" data-career-attach-material="${e(ev.public_document_id)}">用于当前目标</button>`:""}`:ev.job_id?`<button type="button" class="text-button" data-job="${e(ev.job_id)}">打开岗位与原文 ↗</button>`:""}</article>`).join("")||'<p class="form-note">没有找到原文片段，可换用JD中的具体词语。</p>'}<h3>经历、练习、认识与讨论</h3><p class="form-note">${found.record_count} 条记录命中${found.records_truncated?"，先展示最近24条":""}。以下是用户记录或当时分析，需要回查材料。</p>${found.records.map((row,index)=>`<article class="career-library-hit"><span class="quiet-tag">${recordLabels[row.kind]}</span><h4>${e(row.title)}</h4><p>${e(row.excerpt)}</p><p class="form-note">${e(row.project_title)} · ${e(when(row.recorded_at))}</p><div class="result-actions"><a class="text-button" href="#career/${e(row.project_id)}/${e(row.kind)}/${e(row.id)}">回到完整记录 ↗</a>${row.project_id===data.id?`<button type="button" class="text-button" data-career-library-ask="${index}">沿着这个线索继续问 ↗</button>`:["story","task"].includes(row.kind)?`<button type="button" class="secondary small" data-career-reuse-record="${index}">带入当前目标</button>`:""}</div></article>`).join("")||'<p class="form-note">没有找到个人记录或讨论。</p>'}</div>`:"";
    return `<details id="career-library" class="panel career-evidence-library" ${draft.open?"open":""}><summary>证据书架 · 找回资料与自己的认识</summary><form id="career-library-form"><div class="career-library-query"><label>关键词<input name="q" required maxlength="200" value="${e(draft.q||"")}" placeholder="例如：重复写入 或 接口 测试"></label><label>查找范围<select name="scope"><option value="goal">当前求职目标</option><option value="all" ${draft.scope==="all"?"selected":""}>全部保存的资料与求职目标</option></select></label><button class="secondary">查找已有记录</button></div><p class="form-note">本地关键词检索，不调用模型。原文命中与历史理解分开展示；没有命中不代表不存在。</p></form>${materialShelf(data)}${results}</details>`;
  }
  function focusCareerRecord(kind,id){
    if(!["story","task","insight","discussion"].includes(kind)||!/^[a-f0-9]{32}$/.test(id))return;
    const row=kind==="discussion"?career.data.results.find(item=>item.step_id===id):null;
    captureDrafts();career.tab=row?(row.section||Object.keys(sectionKinds).find(section=>sectionKinds[section].includes(row.kind))||"requirements"):kind==="story"?"stories":"experiments";renderDetail();
    const target=kind==="discussion"?$(`[data-career-result="${id}"]`):$(`[data-career-record="${kind}:${id}"]`);
    if(target){if(kind==="discussion")target.closest("details").open=true;target.scrollIntoView({block:"center",behavior:"smooth"});}
    else notify("这条记录已不在当前目标中，可以重新查找。");
  }
  function researchControls(data){
    const pending=data.results.find(row=>["queued","running","interrupted"].includes(row.state))||data.results.find(row=>row.state==="failed"&&row.continuation?.available);
    if(!data.running&&!pending)return "";
    const phase={read_job:"已读岗位，继续分析",read_archived_document:"已读归档，继续分析",query_jobs:"已定位岗位，继续研究",finish_research:"正在整理分析",search_public_web:"已尝试公开搜索，继续研究",read_public_document:"已尝试读取公开正文，继续研究"}[pending?.progress?.last_tool]||"正在研究资料";
    const reason={calls_exhausted:"本轮调用额度已用完，可保留记录后结束这轮。",time_exhausted:"本轮时间额度已用完，可保留记录后结束这轮。",scope_changed:"求职目标或资料范围已调整，请结束旧请求，再按当前目标提问。",material_changed:"所用资料或背景已有变化，请结束这轮后重新研究。",no_checkpoint:"这轮没有可继续的位置，可保留记录后重新提问。",unavailable:"这轮已不可继续，可查看完整记录。"}[pending?.continuation?.reason]||"";
    const canContinue=pending&&pending.scope_current&&(pending.state==="queued"||pending.continuation?.available);
    return `<section class="career-live-research panel" aria-live="polite"><div><span class="quiet-tag">${data.running?phase:pending?.state==="queued"?"等待开始":"本轮尚未完成"}</span><h3>${e(pending?.user_question?.slice(0,100)||labels[pending?.kind]||"当前研究")}</h3><p class="form-note">已发起 ${pending?.progress?.calls||0} 次调用 · 已读 ${pending?.progress?.read_fragments||0} 个原文片段，读到片段不代表核对了全文。</p>${pending&&typeof pending.allow_public==="boolean"?`<p class="form-note">本轮使用${pending.offline?"原文整理模式":pending.allow_public?"公开补查与已选资料":"已选的本地资料"}；续跑沿用此设置。</p>`:""}${!data.running&&reason?`<p class="form-note">${e(reason)}</p>`:""}${!data.running&&pending?.state==="queued"&&!pending.scope_current?'<p class="form-note">这轮仍使用调整前的资料，请撤销后重新提问。</p>':""}</div><div class="result-actions">${data.running?`<button type="button" class="secondary" data-career-control="pause" ${career.busy?"disabled":""}>暂停本轮</button>`:`${canContinue?`<button type="button" class="primary" data-career-control="continue" data-career-step="${e(pending.step_id)}" ${career.busy?"disabled":""}>${pending.state==="queued"?"开始这轮研究":"从已有进度继续"}</button>`:""}<button type="button" class="text-button" data-career-control="end" data-career-step="${e(pending.step_id)}" ${career.busy?"disabled":""}>${pending.run_id?"结束这轮，保留已有记录":"撤销未开始的请求"}</button>`}</div>${!data.running&&pending?.continuation?.available?`<p class="form-note">继续沿用本轮剩余的 ${pending.continuation.remaining_calls} 次调用和 ${pending.continuation.remaining_seconds} 秒，不新增一轮额度。</p>`:""}</section>`;
  }
  async function controlResearch(action,stepId){
    if(career.busy)return;captureDrafts();career.busy=true;renderDetail();const id=career.id;let ended=null;
    try{
      if(action==="pause")await api("projects/"+id+"/pause",{method:"POST",body:"{}"});
      else if(action==="end"){
        ended=career.data.results.find(item=>item.step_id===stepId);await api("career/"+id+"/steps/"+stepId,{method:"DELETE"});
      }else{
        const project=await api("projects/"+id),step=project.steps.find(row=>row.id===stepId);if(!step)throw new Error("这轮已不在当前记录中，请刷新。");
        if(step.state==="failed")await api("projects/"+id+"/steps/"+stepId+"/review",{method:"POST",body:JSON.stringify({revision:project.revision,action:"retry",note:"用户继续未完成的求职研究，沿用原调用与时间上限。"})});
        await api("projects/"+id+"/run",{method:"POST",body:JSON.stringify({step_id:stepId})});
      }
      if(career.id===id)await openCareer(id);
      if(ended&&!ended.run_id){
        const row=ended,draft=career.drafts.get(id)||{};
        if(row.kind==="ask"&&!draft.inquiries?.[row.section]?.question)draft.inquiries={...draft.inquiries,[row.section]:{question:row.user_question,source_step_id:row.source_step_id||"",material_id:row.material_id||""}};
        if(row.kind==="answer"){const key=row.source_step_id+":"+(row.question_index||0);if(!draft.interview_answers?.[key]){draft.source_step_id=row.source_step_id;draft.question_index=String(row.question_index||0);draft.interview_answers={...draft.interview_answers,[key]:row.answer};}}
        if(row.kind==="challenge"&&!draft.challenge?.hypothesis_a)draft.challenge={hypothesis_a:row.hypothesis_a,hypothesis_b:row.hypothesis_b,task_id:row.task_id||"",open:true};
        career.drafts.set(id,draft);if(career.id===id)renderDetail();
      }
      if(action==="end")notify("已结束这轮请求，可以继续当前目标的其他研究。");
    }catch(error){notify(error.message,true);}finally{career.busy=false;if(career.id===id){captureDrafts();renderDetail();}}
  }
  function renderDetail(){
    const data=career.data;if(!data)return;
    $("#career-onboarding").hidden=true;const root=$("#career-detail");root.hidden=false;
    root.innerHTML=`<article class="career-target panel"><div><span class="eyebrow">MY NEXT CHAPTER</span><h2>${e(data.title)}</h2><p>${e(data.goal)}</p><div class="career-target-jobs">${data.jobs.map(job=>`<button class="quiet-tag" data-job="${e(job.id)}">${e(jobText(job))} ↗</button>`).join("")}</div></div><div class="career-target-aside"><button type="button" class="text-button" id="career-open-library">找回资料与认识 ↗</button><button type="button" class="secondary" id="career-export">导出求职准备包 ↧</button><div class="career-progress"><strong>${data.stories.length}</strong><span>份经历证据</span><strong>${data.tasks.filter(task=>task.state==="done").length}</strong><span>项练习有结果</span><strong>${(data.insights||[]).length}</strong><span>次认识复盘</span></div></div></article>${evidenceLibrary(data)}${goalSettings(data)}<div class="career-research-bar"><p>${data.running?'正在查阅资料与研究…':`已用 ${data.usage.calls} / ${data.budget.max_calls} 次模型调用`} <a class="text-button" href="#research/${e(data.id)}">打开完整研究记录 ↗</a></p><label class="checkbox-line"><input id="career-offline" type="checkbox" ${career.offline?"checked":""}>只整理原文</label><label class="checkbox-line"><input id="career-public" type="checkbox" ${storyDraft().allow_public&&!career.offline?"checked":""} ${career.offline?"disabled":""}>补查公开业务与技术资料</label><small>以上选择用于新研究，续跑沿用原设置。研究会将所选资料与个人背景发送至已配置模型；每轮最多6次研究调用、2分半。公开补查使用已配置搜索服务，可能计费；本目标最多 ${data.budget.max_public||8} 次搜索或正文读取，已用 ${data.usage.public||0} 次。</small></div>${researchControls(data)}<nav class="career-tabs" aria-label="求职成长步骤">${[["requirements","01","看清工作"],["stories","02","经历与差距"],["experiments","03","工作样本"],["interview","04","模拟面试"]].map(([key,n,title])=>`<button type="button" data-career-tab="${key}" class="${career.tab===key?"active":""}" aria-pressed="${career.tab===key}"><span>${n}</span>${title}</button>`).join("")}</nav><div id="career-tab-content">${({requirements,stories,experiments,interview})[career.tab](data)}</div>${inquiryPanel(data)}<section class="career-result-area"><div class="section-heading"><h2>研究与反馈</h2><button type="button" class="text-button" id="career-refresh">刷新</button></div><div id="career-results"></div></section>`;
    showGoalJobs();
    const shown=data.results.filter(inCareerSection);
    $("#career-results").innerHTML=shown.length?shown.map(row=>`<details class="career-result" ${shown[0]===row?"open":""}><summary>${e(labels[row.kind])} · ${e(row.state==="abandoned"?"已结束，保留已有记录":row.result?statusLabels[row.result.status]||row.result.status:({queued:"等待开始",running:"正在研究",failed:"未完成",interrupted:"已暂停",abandoned:"已结束，保留已有记录"})[row.state]||row.state)}</summary><div data-career-result="${e(row.step_id)}"></div></details>`).join(""):'<p class="form-note">这个步骤还没有研究记录。</p>';
    for(const row of shown)$(`[data-career-result="${row.step_id}"]`).innerHTML=coachingResult(row);

  }

  async function openCareer(id){
    captureDrafts();clearTimeout(career.timer);career.id=id;
    const data=await api("career/"+encodeURIComponent(id));if(career.id!==id)return;
    career.data=data;renderDetail();
    if(data.running)career.timer=setTimeout(()=>{if(state.page==="career"&&career.id===id)openCareer(id).catch(error=>notify(error.message,true));},2000);
  }

  window.loadCareer=async()=>{
    clearTimeout(career.timer);$("#career-detail").hidden=true;await loadGoals();
    const id=location.hash.split("/")[1];$("#career-goal-switcher").open=!id;if(!$("#career-jd-intake").children.length)$("#career-jd-intake").innerHTML=jdIntake("onboard");
    if(id&&/^[a-f0-9]{32}$/.test(id)){await openCareer(id);const parts=location.hash.split("/");focusCareerRecord(parts[2],parts[3]);}
    else{$("#career-onboarding").hidden=false;$("#career-detail").hidden=true;await findJobs();}
  };

  async function research(kind,answer="",questionIndex=0,taskId=null,sourceStepId=null,question="",extras={}){
    if(career.busy)return;captureDrafts();career.busy=true;renderDetail();
    const id=career.id;
    try{
      const step=await api("career/"+id+"/prepare",{method:"POST",body:JSON.stringify({kind,answer,question_index:questionIndex,task_id:taskId,source_step_id:sourceStepId,question,section:career.tab,offline:Boolean(career.offline),allow_public:Boolean(storyDraft().allow_public)&&!career.offline,...extras})});
      if(["interview","followup"].includes(kind)){const draft=career.drafts.get(id)||{};draft.next_source_step_id=step.step_id;draft.question_index="0";career.drafts.set(id,draft);}
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
    if(event.target.matches?.('[data-career-compare-job]')){
      const select=event.target,side=Number(select.dataset.careerCompareJob);captureDrafts();const old=compareJobs(career.data).map(job=>job.id),pair=[...old];pair[side]=select.value;if(pair[0]===pair[1])pair[1-side]=old[side];const draft=storyDraft();draft.compare_jobs=pair;draft.compare_open=true;career.drafts.set(career.id,draft);renderDetail();return;
    }
    if(event.target.matches?.('#career-interview-answer [name="source_step_id"],#career-interview-answer [name="question_index"]')){
      const target=event.target;captureDrafts();const draft=storyDraft();delete draft.next_source_step_id;
      if(target.name==="source_step_id"){draft.source_step_id=target.value;draft.question_index="0";}else draft.question_index=target.value;
      career.drafts.set(career.id,draft);renderDetail();return;
    }
    const targetJob=event.target.closest("[data-career-target-job]");
    if(targetJob){
      captureDrafts();const selected=goalJobs();
      if(targetJob.checked){if(selected.size>=6){targetJob.checked=false;notify("最多选择6个目标岗位。",true);return;}selected.set(targetJob.dataset.careerTargetJob,jobText(career.targetOptions.get(targetJob.dataset.careerTargetJob)));}
      else selected.delete(targetJob.dataset.careerTargetJob);
      const draft=storyDraft();draft.settings_jobs=[...selected];career.drafts.set(career.id,draft);showGoalJobs();
    }
    if(event.target.matches?.('#career-insight [name="task_id"]')){
      const task=career.data.tasks.find(row=>row.id===event.target.value),form=event.target.closest("form");
      if(task){if(!form.elements.previous_view.value)form.elements.previous_view.value=task.hypothesis||"";if(!form.elements.observation.value&&task.outcome.length<=2000)form.elements.observation.value=task.outcome;captureDrafts();}
    }
    if(event.target.matches?.("[data-career-resume-file],[data-career-artifact-file],[data-career-material-file]"))importCareerFile(event.target);
    const choice=event.target.closest("[data-career-job]");
    if(choice){if(choice.checked&&career.selected.size>=6){choice.checked=false;notify("最多选择6个目标岗位。",true);return;}if(choice.checked)career.selected.set(choice.dataset.careerJob,jobText(career.jobs.get(choice.dataset.careerJob)));else career.selected.delete(choice.dataset.careerJob);selectedJobs();}
    if(event.target.id==="career-public"){const draft=storyDraft();draft.allow_public=event.target.checked;career.drafts.set(career.id,draft);}
    if(event.target.id==="career-offline"){captureDrafts();career.offline=event.target.checked;renderDetail();}
  });
  document.addEventListener("click",async event=>{
    const target=event.target.closest("[data-career-tab],[data-career-remove-job],[data-career-research],[data-career-link-story],[data-career-import-tasks],[data-career-task-story],[data-career-edit-story],[data-career-remove-story],[data-career-cancel-story],[data-career-new-insight],[data-career-insight-task],[data-career-cancel-insight],[data-career-cancel-settings],[data-career-goal-remove-job],[data-career-followup],[data-career-ask-result],[data-career-save-jd],[data-career-compare-question],[data-career-insight-result],[data-career-edit-insight],[data-career-open-insight-source],[data-career-insight-question],[data-career-library-ask],[data-career-challenge-insight],[data-career-reuse-library],[data-career-reuse-record],[data-career-attach-material],[data-career-remove-material],[data-career-material-question],[data-career-answer-plan],[data-career-control],[data-career-clear-material-focus],#career-open-library,#career-target-find,#career-refresh,#career-export");if(!target)return;
    try{
      if(target.dataset.careerControl)await controlResearch(target.dataset.careerControl,target.dataset.careerStep);
      if(target.dataset.careerAnswerPlan){captureDrafts();career.tab="experiments";renderDetail();await research("plan","",0,null,target.dataset.careerAnswerPlan);}
      if(target.hasAttribute("data-career-clear-material-focus")){captureDrafts();const draft=storyDraft();if(draft.inquiries?.[career.tab])draft.inquiries[career.tab].material_id="";renderDetail();}
      if(target.dataset.careerMaterialQuestion){captureDrafts();const material=career.data.materials.find(row=>row.id===target.dataset.careerMaterialQuestion);if(material){const draft=storyDraft();draft.inquiries={...draft.inquiries,[career.tab]:{question:('请先读这份资料「'+material.title+'」，它对理解当前岗位的实际工作有什么帮助？哪些内容还不能直接推成岗位个人责任或必备要求？').slice(0,1500),source_step_id:"",material_id:material.id}};career.drafts.set(career.id,draft);renderDetail();$("#career-inquiry").scrollIntoView({block:"center",behavior:"smooth"});}}
      if(target.dataset.careerAttachMaterial||target.dataset.careerRemoveMaterial){captureDrafts();target.disabled=true;const id=career.id,doc=target.dataset.careerAttachMaterial||target.dataset.careerRemoveMaterial,attach=Boolean(target.dataset.careerAttachMaterial);const updated=await api("career/"+id+"/materials/"+(attach?"attach":doc),{method:attach?"POST":"DELETE",...(attach?{body:JSON.stringify({document_id:doc})}:{})});if(career.id===id){captureDrafts();career.data=updated;if(!attach)for(const draft of Object.values(storyDraft().inquiries||{}))if(draft.material_id===doc)draft.material_id="";renderDetail();}notify(attach?"资料已加入当前目标，可以选择围绕原文提问。":"资料已移出本目标，原归档仍可在证据书架找回。");}
      if(target.hasAttribute("data-career-reuse-library")){captureDrafts();const draft=storyDraft();draft.library={...draft.library,scope:"all",open:true};career.drafts.set(career.id,draft);renderDetail();$("#career-library").scrollIntoView({block:"start",behavior:"smooth"});$("#career-library-form [name=q]").focus();}
      if(target.hasAttribute("data-career-reuse-record")){captureDrafts();const row=career.searches.get(career.id)?.records[Number(target.dataset.careerReuseRecord)];if(row){target.disabled=true;const id=career.id,updated=await api("career/"+id+"/reuse",{method:"POST",body:JSON.stringify({source_project_id:row.project_id,kind:row.kind,record_id:row.id})});if(career.id===id){captureDrafts();career.data=updated;career.tab=row.kind==="story"?"stories":"experiments";renderDetail();await loadGoals();}notify("已带入当前目标，不调用模型；对新岗位的适用性仍需重新判断。");}}
      if(target.dataset.careerChallengeInsight){captureDrafts();const note=career.data.insights.find(row=>row.id===target.dataset.careerChallengeInsight);if(note){const draft=storyDraft();draft.challenge={...draft.challenge,hypothesis_a:note.current_view.slice(0,700),task_id:note.task_id||"",open:true};career.drafts.set(career.id,draft);career.tab="experiments";renderDetail();$("#career-challenge").scrollIntoView({block:"center",behavior:"smooth"});$("#career-challenge [name=hypothesis_b]").focus();}}
      if(target.id==="career-open-library"){$("#career-library").open=true;$("#career-library").scrollIntoView({block:"start",behavior:"smooth"});$("#career-library-form [name=q]").focus();}
      if(target.hasAttribute("data-career-library-ask")){captureDrafts();const row=career.searches.get(career.id)?.records[Number(target.dataset.careerLibraryAsk)];if(row){career.tab=row.section;const draft=storyDraft(),source=career.data.results.find(item=>item.step_id===row.step_id&&item.current!==false&&item.result?.status==="completed");draft.inquiries={...draft.inquiries,[career.tab]:{question:("请回查当前原文，帮我核对这条旧记录，不把旧结论当成事实：\n"+row.title.slice(0,250)+"\n"+row.excerpt).slice(0,1500),source_step_id:source?.step_id||""}};career.drafts.set(career.id,draft);renderDetail();$("#career-inquiry").scrollIntoView({block:"center",behavior:"smooth"});}}
      if(target.dataset.careerInsightResult)startInsight(null,target.dataset.careerInsightResult);
      if(target.dataset.careerEditInsight){captureDrafts();const note=career.data.insights.find(row=>row.id===target.dataset.careerEditInsight);if(note&&!storyDraft().insight){storyDraft().insight={...note};renderDetail();$("#career-insight").scrollIntoView({block:"center",behavior:"smooth"});}else if(storyDraft().insight)notify("当前有未保存的认识记录，先保存或取消后再编辑另一份。");}
      if(target.dataset.careerOpenInsightSource){captureDrafts();const row=career.data.results.find(row=>row.step_id===target.dataset.careerOpenInsightSource);if(row){career.tab=row.section||Object.keys(sectionKinds).find(section=>sectionKinds[section].includes(row.kind))||"requirements";renderDetail();const panel=$(`[data-career-result="${row.step_id}"]`);if(panel){panel.closest("details").open=true;panel.scrollIntoView({block:"center",behavior:"smooth"});}}}
      if(target.dataset.careerInsightQuestion){captureDrafts();const note=career.data.insights.find(row=>row.id===target.dataset.careerInsightQuestion);if(note){career.tab="experiments";const draft=storyDraft();draft.inquiries={...draft.inquiries,experiments:{question:(note.open_question+"\n我的当前理解（个人认识，待验证）："+note.current_view.slice(0,220)+"\n我的观察记录："+note.observation.slice(0,180)).slice(0,1500),source_step_id:""}};career.drafts.set(career.id,draft);renderDetail();$("#career-inquiry").scrollIntoView({block:"center",behavior:"smooth"});}}
      if(target.dataset.careerCompareQuestion){captureDrafts();const draft=storyDraft();draft.inquiries={...draft.inquiries,requirements:{question:target.dataset.careerCompareQuestion,source_step_id:""}};career.drafts.set(career.id,draft);renderDetail();$("#career-inquiry").scrollIntoView({block:"center",behavior:"smooth"});$("#career-inquiry [name=question]").focus();}
      if(target.dataset.careerSaveJd)await saveInlineJD(target);
      if(target.dataset.careerRemoveJob){career.selected.delete(target.dataset.careerRemoveJob);selectedJobs();await findJobs();}
      if(target.dataset.careerTab){captureDrafts();career.tab=target.dataset.careerTab;renderDetail();}
      if(target.dataset.careerAskResult){captureDrafts();const draft=storyDraft();draft.inquiries={...draft.inquiries,[career.tab]:{...draft.inquiries?.[career.tab],source_step_id:target.dataset.careerAskResult,material_id:"",...(target.dataset.careerMapQuestion?{question:target.dataset.careerMapQuestion}:{})}};career.drafts.set(career.id,draft);renderDetail();$("#career-inquiry").scrollIntoView({block:"center",behavior:"smooth"});$("#career-inquiry [name=question]").focus();}
      if(target.dataset.careerFollowup)await research("followup","",0,null,target.dataset.careerFollowup);
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
      if(target.id==="career-target-find")await findGoalJobs();
      if(target.dataset.careerGoalRemoveJob){captureDrafts();const selected=goalJobs();selected.delete(target.dataset.careerGoalRemoveJob);const draft=storyDraft();draft.settings_jobs=[...selected];career.drafts.set(career.id,draft);showGoalJobs();}
      if(target.hasAttribute("data-career-cancel-settings")){captureDrafts();for(const key of ["settings","settings_jobs","settings_open","settings_query","target_jd"])delete storyDraft()[key];renderDetail();}
    }catch(error){target.disabled=false;notify(error.message,true);}
  });
  document.addEventListener("submit",async event=>{
    const form=event.target;if(!["career-story","career-interview-answer","career-resume-form","career-insight","career-manual-experiment","career-settings","career-inquiry","career-library-form","career-challenge","career-material-form"].includes(form.id)&&!form.dataset.careerTaskForm)return;
    event.preventDefault();const submit=event.submitter||form.querySelector("button");submit.disabled=true;captureDrafts();
    try{
      if(form.id==="career-library-form"){const id=career.id,values=Object.fromEntries(new FormData(form));const found=await api("career/"+id+"/search?"+new URLSearchParams(values));career.searches.set(id,found);if(career.id===id){captureDrafts();renderDetail();}}
      else if(form.id==="career-material-form"){const values=Object.fromEntries(new FormData(form));if(values.material_text.length>20000)throw new Error("请把工作资料精简到2万字以内再保存。");const id=career.id,updated=await api("career/"+id+"/materials",{method:"POST",body:JSON.stringify({title:values.material_title,text:values.material_text,source_name:values.source_name})});if(career.id===id){captureDrafts();career.data=updated;delete storyDraft().material;renderDetail();}notify("资料已保存并加入当前目标，保存没有调用模型。");}
      else if(form.id==="career-story"){const storyId=storyDraft().story_id;career.data=await api(apiPath()+"/stories"+(storyId?"/"+encodeURIComponent(storyId):""),{method:storyId?"PATCH":"POST",body:JSON.stringify(Object.fromEntries(new FormData(form)))});resetStoryEditor();renderDetail();await loadGoals();notify("经历已保存，后续分析和面试可引用。");}
      else if(form.id==="career-resume-form"){if(form.elements.resume_text.value.length>20000)throw new Error("请把简历正文精简到2万字以内。");career.data=await api(apiPath()+"/resume",{method:"PATCH",body:JSON.stringify({title:form.elements.resume_title.value,text:form.elements.resume_text.value})});delete storyDraft().resume_text;delete storyDraft().resume_title;renderDetail();notify("简历已保存，后续研究将参考这份正文。");}
      else if(form.id==="career-insight"){const data=Object.fromEntries(new FormData(form));data.task_id=data.task_id||null;data.source_step_id=data.source_step_id||null;const noteId=storyDraft().insight.id;career.data=await api(apiPath()+"/insights"+(noteId?"/"+encodeURIComponent(noteId):""),{method:noteId?"PATCH":"POST",body:JSON.stringify(data)});delete storyDraft().insight;renderDetail();notify("这次认识变化已保存，后续研究会参考你的理解和疑问。");}
      else if(form.id==="career-manual-experiment"){career.data=await api(apiPath()+"/experiments",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(form)))});delete storyDraft().manual;delete storyDraft().manual_open;renderDetail();await loadGoals();notify("自己设计的实验已加入练习板。");}
      else if(form.id==="career-settings"){const data=Object.fromEntries(new FormData(form));data.job_ids=[...goalJobs().keys()];if(!data.job_ids.length)throw new Error("请至少保留一个目标岗位。");const id=career.id,updated=await api(apiPath(),{method:"PATCH",body:JSON.stringify(data)});if(career.id===id){career.data=updated;for(const key of ["settings","settings_jobs","settings_open","settings_query","target_jd"])delete storyDraft()[key];renderDetail();await loadGoals();}notify("目标与背景已更新，经历、练习和认知记录继续保留。");}
      else if(form.id==="career-challenge")await research("challenge","",0,form.elements.task_id.value||null,null,"",{hypothesis_a:form.elements.hypothesis_a.value,hypothesis_b:form.elements.hypothesis_b.value});
      else if(form.id==="career-inquiry")await research("ask","",0,null,form.elements.source_step_id.value||null,form.elements.question.value,{material_id:form.elements.material_id.value||null});
      else if(form.id==="career-interview-answer")await research("answer",form.elements.answer.value,Number(form.elements.question_index.value),null,form.elements.source_step_id.value);
      else{if(form.elements.artifact_text.value.length>20000)throw new Error("请把作品材料精简到2万字以内再保存。");career.data=await api(apiPath()+"/tasks/"+encodeURIComponent(form.dataset.careerTaskForm),{method:"PATCH",body:JSON.stringify(Object.fromEntries(new FormData(form)))});delete storyDraft()["task:"+form.dataset.careerTaskForm];renderDetail();await loadGoals();notify("练习进度与实际观察已保存。");}
    }catch(error){notify(error.message,true);}finally{submit.disabled=false;}
  });
  document.addEventListener("keydown",event=>{if(event.target.id==="career-target-query"&&event.key==="Enter"){event.preventDefault();findGoalJobs().catch(error=>notify(error.message,true));}});
})();

// Verify the production start/follow-up sequence with isolated API and DOM doubles.
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const nodes=new Map(),storage=new Map();
const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{checked:false,value:"",disabled:false,dataset:{},children:[],focus(){},scrollIntoView(){},append(child){this.children.push(child);},insertAdjacentHTML(position,html){this.innerHTML=(this.innerHTML||"")+html;},querySelector:node,querySelectorAll:()=>[],addEventListener(){}});return nodes.get(selector);};
const context={document:{createElement:tag=>node("created-"+tag),querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:""},sessionStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k)||null,removeItem:k=>storage.delete(k)},crypto:{randomUUID:()=>"synthetic-request"},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2],"utf8"),context);
context.originalOpen=vm.runInContext("openResearchConversation",context);
context.calls=[];context.opened=[];
node("#offline").checked=true;
vm.runInContext('api=async(path,options)=>{calls.push({path,options});if(path.startsWith("jobs?"))return {jobs:[{id:"job-1"}]};if(path==="projects"&&options)return {id:"project-1"};if(path==="projects/project-1"&&!options)return {id:"project-1",revision:3,worker_running:false};return {};};openResearchConversation=async id=>opened.push(id);notify=()=>{}',context);
(async()=>{
 await vm.runInContext('startResearchConversation("合成输入问题")',context);
 assert.equal(context.calls[0].path,"jobs?limit=20");
 const project=JSON.parse(context.calls.find(c=>c.path==="projects").options.body);
 assert.deepEqual(project.job_ids,["job-1"]);assert.equal(project.goal,"合成输入问题");assert.equal(project.max_calls,72);assert.equal(project.max_seconds,1080);
 const initial=JSON.parse(context.calls.find(c=>c.path.endsWith("/steps")).options.body);
 assert.equal(initial.question,"合成输入问题");assert.equal(initial.revision,3);assert.equal(initial.offline,true);
 assert.equal(initial.allow_public,false);assert.equal(initial.max_calls,10);assert.equal("approach" in initial,false);
 assert.equal(context.calls.filter(c=>c.path.endsWith("/run")).length,1);
 assert.equal(storage.get("wo-conversation"),"project-1");
 await vm.runInContext('askResearchConversation("合成继续追问")',context);
 assert.equal(context.calls.filter(c=>c.path==="projects").length,1); // A follow-up uses the same project.
 assert.equal(context.calls.filter(c=>c.path.endsWith("/steps")).length,2);
 assert.equal(context.calls.filter(c=>c.path.endsWith("/run")).length,2);
 assert.equal(context.calls.filter(c=>c.path.includes("/review")).length,0); // Never impersonate acceptance.
 assert.deepEqual(Array.from(context.opened),["project-1","project-1"]);
 await vm.runInContext('saveResearchContext("correction","合成明确纠正")',context);
 const correction=JSON.parse(context.calls.find(c=>c.path==="memories").options.body);
 assert.equal(correction.scope,"project");assert.equal(correction.project_id,"project-1");assert.equal(correction.origin,"user");
 assert.equal(correction.kind,"correction");assert.equal("evidence" in correction,false);
 assert.ok(node("#conversation-question").value.includes("合成明确纠正"));
 vm.runInContext('api=async(path,options)=>{calls.push({path,options});return options?{}:{id:"project-1",revision:4,goal:"合成研究目标",job_ids:["job-1"],worker_running:false};}',context);
 await vm.runInContext('attachConversationMaterial("project-1","job-2")',context);
 const expanded=JSON.parse(context.calls.find(c=>c.options?.method==="PATCH").options.body);
 assert.deepEqual(expanded.job_ids,["job-1","job-2"]);assert.equal(expanded.goal,"合成研究目标");
 assert.equal(context.calls.filter(c=>c.path.endsWith("/run")).length,2); // Saving context/material never starts a model.
 vm.runInContext('api=async(path,options)=>{calls.push({path,options});return {document:{id:"d".repeat(32),title:"<script>合成文档</script>",full_text_length:120,publisher:"example.com"},truncated:false};}',context);
 await vm.runInContext('archiveConversationDocument("https://example.com/docs")',context);
 assert.ok(node("#conversation-public-status").innerHTML.includes("&lt;script&gt;合成文档"));
 assert.ok(!node("#conversation-public-status").innerHTML.includes("<script>"));
 assert.ok(node("#conversation-question").value.includes("合成明确纠正")); // Adding sources preserves an existing question.
 assert.equal(context.calls.filter(c=>c.path.endsWith("/run")).length,2);

 vm.runInContext('state.serviceContract={components:{schemas:{StepInput:{properties:{reply_to_step_id:{}}}}}};conversation.replyToStepId=undefined;api=async(path,options)=>{calls.push({path,options});return options?{}:{id:"project-1",revision:5,worker_running:false,steps:[{id:"a".repeat(32),state:"waiting_review"},{id:"b".repeat(32),state:"queued",offline:true}]};}',context);
 await vm.runInContext('askResearchConversation("为什么？")',context);
 let reply=JSON.parse(context.calls.filter(c=>c.path.endsWith("/steps")).at(-1).options.body);
 assert.equal(reply.reply_to_step_id,"a".repeat(32)); // Pending planned work is not the reply target.
 const runsBefore=context.calls.filter(c=>c.path.endsWith("/run")).length;
 vm.runInContext('prefillConversationFollowup({dataset:{replyStep:"c".repeat(32),conversationClaim:"合成待核实判断"}})',context);
 assert.ok(node("#conversation-question").value.includes("合成待核实判断"));
 assert.equal(context.calls.filter(c=>c.path.endsWith("/run")).length,runsBefore); // Selection only drafts a question.
 await vm.runInContext('askResearchConversation("针对更早的判断核实")',context);
 reply=JSON.parse(context.calls.filter(c=>c.path.endsWith("/steps")).at(-1).options.body);
 assert.equal(reply.reply_to_step_id,"c".repeat(32));
 assert.equal(context.calls.filter(c=>c.path.includes("/review")).length,0);

 context.capacityProject={id:"project-1",revision:7,worker_running:false,budget:{max_calls:10,max_seconds:300,max_rounds:2,max_public:0},usage:{reserved_calls:6,reserved_seconds:180,public:0},ready_step_ids:[],steps:[{id:"first",state:"waiting_review",run_id:"old-run",max_calls:6,timeout:180,offline:false}]};
 vm.runInContext('api=async(path,options)=>{calls.push({path,options});return options?{}:capacityProject;}',context);
 await vm.runInContext('askResearchConversation("按实际剩余额度继续",{offline:false,allowPublic:false})',context);
 const bounded=JSON.parse(context.calls.filter(c=>c.path.endsWith("/steps")).at(-1).options.body);
 assert.equal(bounded.max_calls,4);assert.equal(bounded.timeout,120);
 let stepWrites=context.calls.filter(c=>c.path.endsWith("/steps")).length;
 context.capacityProject.steps.push({id:"second",state:"failed",run_id:"second-run",offline:false});
 await assert.rejects(vm.runInContext('askResearchConversation("轮数已满",{offline:true})',context),/轮数/);
 assert.equal(context.calls.filter(c=>c.path.endsWith("/steps")).length,stepWrites);
 context.capacityProject.steps.pop();context.capacityProject.usage.reserved_seconds=300;
 await assert.rejects(vm.runInContext('askResearchConversation("时间已满",{offline:false})',context),/时间/);
 assert.equal(context.calls.filter(c=>c.path.endsWith("/steps")).length,stepWrites);
 await vm.runInContext('askResearchConversation("时间用完后只整理原文",{offline:true,allowPublic:true})',context);
 const offlineBounded=JSON.parse(context.calls.filter(c=>c.path.endsWith("/steps")).at(-1).options.body);
 assert.equal(offlineBounded.offline,true);assert.equal(offlineBounded.allow_public,false);
 context.capacityProject.usage.reserved_seconds=180;
 await assert.rejects(vm.runInContext('askResearchConversation("补查额度不足",{offline:false,allowPublic:true})',context),/公开补查/);
 context.capacityProject.budget.max_rounds=3;
 context.capacityProject.steps.push({id:"queued",state:"queued",max_calls:4,timeout:120,offline:false});
 context.capacityProject.ready_step_ids=["queued"];
 stepWrites=context.calls.filter(c=>c.path.endsWith("/steps")).length;
 await assert.rejects(vm.runInContext('askResearchConversation("已有计划占用额度",{offline:false})',context),/调用额度/);
 await assert.rejects(vm.runInContext('askResearchConversation("不得借离线启动待执行模型",{offline:true})',context),/待执行的模型/);
 assert.equal(context.calls.filter(c=>c.path.endsWith("/steps")).length,stepWrites);

 node("#research-source-mode").value="public";
 const queriesBefore=context.calls.filter(c=>c.path.startsWith("jobs?")).length;
 vm.runInContext('state.researchIds=["unrelated-job"];state.serviceContract.components.schemas.StepInput.properties.coverage_mode={enum:["all","question"]};api=async(path,options)=>{calls.push({path,options});if(path.startsWith("public-documents?"))return {documents:[],total:1};if(path.startsWith("jobs?"))throw Error("Public-only research must not query jobs");return options?{id:"public-project"}:{id:"public-project",revision:1,job_ids:[],steps:[],worker_running:false};}',context);
 await vm.runInContext('startResearchConversation("只研究公开文档")',context);
 const publicProject=JSON.parse(context.calls.filter(c=>c.path==="projects").at(-1).options.body);
 assert.deepEqual(publicProject.job_ids,[]);
 assert.equal(context.calls.filter(c=>c.path.startsWith("jobs?")).length,queriesBefore);
 const publicStep=JSON.parse(context.calls.filter(c=>c.path.endsWith("/steps")).at(-1).options.body);
 assert.equal(publicStep.coverage_mode,"question");
 node("#research-document-url").value="https://example.com/docs";
 const runsBeforeArchive=context.calls.filter(c=>c.path.endsWith("/run")).length;
 vm.runInContext('api=async(path,options)=>{calls.push({path,options});const document={id:"d".repeat(32),title:"<script>合成正文</script>",full_text_length:42,integrity:"verified",publisher:"example.com"};return path.startsWith("public-documents?")?{documents:[document],total:1,limit:10,offset:0}:{document};}',context);
 await vm.runInContext('archiveResearchDocument()',context);
 assert.ok(node("#research-document-status").innerHTML.includes("&lt;script&gt;合成正文"));
 assert.equal(context.calls.filter(c=>c.path.endsWith("/run")).length,runsBeforeArchive);
 assert.ok(node("#public-library-list").innerHTML.includes("&lt;script&gt;合成正文"));
 assert.ok(!node("#public-library-list").innerHTML.includes("<script>"));
 node("#question").value="我原有的问题";
 const callsBeforeQuestion=context.calls.length;
 await vm.runInContext('preparePublicDocumentQuestion("合成文档","d".repeat(32))',context);
 assert.ok(node("#question").value.includes("合成文档"));
 assert.ok(node("#question").value.includes("我原有的问题"));
 assert.equal(node("#research-source-mode").value,"public");
 assert.equal(context.calls.length,callsBeforeQuestion); // Selecting a document only drafts a question.
 assert.equal(JSON.parse(storage.get("wo-document-selection"))[0].id,"d".repeat(32));
 assert.ok(node("#research-document-selection").innerHTML.includes("已选 1 份资料"));
 vm.runInContext('selectResearchDocument("c".repeat(32),"<script>第二份</script>")',context);
 assert.ok(node("#research-document-selection").innerHTML.includes("&lt;script&gt;第二份"));
 vm.runInContext('api=async(path,options)=>{calls.push({path,options});return path==="projects"?{id:"project-1"}:{id:"project-1",revision:3,worker_running:false};}',context);
 await vm.runInContext('startResearchConversation("指定两份资料")',context);
 const selectedProject=JSON.parse(context.calls.filter(c=>c.path==="projects").at(-1).options.body);
 assert.deepEqual(selectedProject.public_document_ids,["d".repeat(32),"c".repeat(32)]);
 assert.deepEqual(selectedProject.job_ids,[]);

 vm.runInContext('api=async(path,options)=>{calls.push({path,options});return {documents:[],total:0,limit:10,offset:0};}',context);
 node("#public-library-query").value="Graph & API";
 await vm.runInContext('loadPublicLibrary(10)',context);
 const libraryQuery=new URLSearchParams(context.calls.at(-1).path.split("?")[1]);
 assert.equal(libraryQuery.get("q"),"Graph & API");assert.equal(libraryQuery.get("offset"),"0");

 node("#work-material-title").value="<script>合成SOP</script>";
 node("#work-material-text").value="\n保留的原文与空行。\n";
 node("#work-material-source").value="合成来源说明";
 node("#research-source-mode").value="jobs";
 const runsBeforeMaterial=context.calls.filter(c=>c.path.endsWith("/run")).length;
 vm.runInContext('api=async(path,options)=>{calls.push({path,options});const document={id:"e".repeat(32),title:"<script>合成SOP</script>",full_text_length:12,integrity:"verified",evidence_kind:"work_material",publisher:"合成来源说明"};return path.startsWith("public-documents?")?{documents:[document],total:1,limit:10,offset:0}:{document};}',context);
 await vm.runInContext('saveWorkMaterial()',context);
 const pasted=JSON.parse(context.calls.find(c=>c.path==="work-materials").options.body);
 assert.equal(pasted.text,"\n保留的原文与空行。\n");assert.equal(pasted.source_name,"合成来源说明");
 assert.ok(node("#work-material-status").innerHTML.includes("&lt;script&gt;合成SOP"));
 assert.ok(node("#public-library-list").innerHTML.includes("粘贴工作资料"));
 assert.equal(node("#research-source-mode").value,"public"); // Pasted material is ready for a focused question.
 assert.equal(context.calls.filter(c=>c.path.endsWith("/run")).length,runsBeforeMaterial);

 const runCountBeforePaste=context.calls.filter(c=>c.path.endsWith("/run")).length;
 node("#conversation-question").value="我正在写的追问";
 node("#conversation-material-title").value="<script>合成SOP</script>";
 node("#conversation-material-text").value="\n保留原文和空行。\n";
 node("#conversation-material-source").value="合成出处";
 vm.runInContext('conversation.id="project-1";globalThis.attachFails=true;api=async(path,options)=>{calls.push({path,options});if(path==="work-materials")return {document:{id:"f".repeat(32),title:"<script>合成SOP</script>",evidence_kind:"work_material"}};if(options?.method==="PATCH"&&attachFails)throw new Error("合成并发冲突");return {id:"project-1",revision:12,goal:"合成",job_ids:[],public_document_ids:["d".repeat(32)],worker_running:false};}',context);
 const savesBefore=context.calls.filter(c=>c.path==="work-materials").length;
 await assert.rejects(vm.runInContext('saveConversationWorkMaterial("<script>合成SOP</script>","\\n保留原文和空行。\\n","合成出处")',context),/并发冲突/);
 const savedRequest=JSON.parse(context.calls.filter(c=>c.path==="work-materials").at(-1).options.body);
 assert.equal(savedRequest.text,"\n保留原文和空行。\n");
 assert.ok(node("#conversation-material-receipts").innerHTML.includes("尚未加入本研究"));
 assert.ok(node("#conversation-material-receipts").innerHTML.includes("&lt;script&gt;合成SOP"));
 assert.equal(node("#conversation-material-text").value,""); // Raw text is already safely archived.
 assert.equal(node("#conversation-question").value,"我正在写的追问");
 vm.runInContext('attachFails=false',context);
 await vm.runInContext('retryConversationMaterial("project-1","f".repeat(32))',context);
 assert.equal(context.calls.filter(c=>c.path==="work-materials").length,savesBefore+1); // Retry only attaches.
 const attached=JSON.parse(context.calls.filter(c=>c.options?.method==="PATCH").at(-1).options.body);
 assert.deepEqual(attached.public_document_ids,["d".repeat(32),"f".repeat(32)]);
 assert.equal(node("#conversation-question").value,"我正在写的追问");
 assert.ok(node("#conversation-material-receipts").innerHTML.includes("已加入本研究"));
 assert.equal(context.calls.filter(c=>c.path.endsWith("/run")).length,runCountBeforePaste);
 assert.equal(JSON.parse(storage.get("wo-material-receipts:project-1")).at(-1).attached,true);
 vm.runInContext('globalThis.materialHtml=renderConversationMaterialForm({id:"project-1",worker_running:false},{title:"<script>草稿</script>",text:"</textarea><script>原文</script>",open:true})',context);
 assert.ok(context.materialHtml.includes("&lt;/textarea&gt;&lt;script&gt;原文"));
 assert.ok(context.materialHtml.includes('class="detail-section" open'));
 assert.ok(!context.materialHtml.includes("<script>"));

 vm.runInContext(fs.readFileSync(require("node:path").join(require("node:path").dirname(process.argv[2]),"quality.js"),"utf8"),context);
 context.revisionRows=[{previous_run_id:"a".repeat(32),previous_claim_index:0,decision:"revise",previous_statement:"<b>旧解释</b>",new_statements:["新的解释"],reason:"重读原文纠正",previous_review_state:"waiting_review",evidence_relation:"reread",evidence_ids:[]}];
 const correctionHtml=vm.runInContext('renderQualityMap({cognition_revisions:revisionRows})',context);
 assert.ok(correctionHtml.includes("认识修正记录"));assert.ok(correctionHtml.includes("待核对"));
 assert.ok(correctionHtml.includes("&lt;b&gt;旧解释&lt;/b&gt;"));
 assert.ok(!correctionHtml.includes("地图关系单独核对")); // Ordinary corrections do not require map review fields.
 context.revisionRows[0].previous_quality_review={status:"rejected",reviewer_kind:"agent_assisted"};
 assert.ok(vm.runInContext('renderQualityMap({cognition_revisions:revisionRows})',context).includes("原质量核对未通过（Agent辅助，非独立人审）"));

 context.project={id:"project-1",title:"合成持续调查",state:"active",usage:{calls:0,reserved_calls:0},budget:{max_calls:24},worker_running:false,steps:[{id:"step",question:"合成问题",state:"waiting_material",offline:true,result:{question:"合成问题",status:"evidence_only",scope:{counts:{matched:1,unknown:0,candidate_details:1},jobs:[]},evidence:[],claims:[],gaps:["哪些资料还需要核实？"],mode:"offline",created_at:"2026-11-19"}}]};
 vm.runInContext('openResearchConversation=originalOpen;api=async()=>project;state.page="jobs";location.hash="#jobs";conversation.id="project-1"',context);
 await vm.runInContext('openResearchConversation("project-1",false)',context);
 assert.equal(context.location.hash,"#jobs"); // Background refresh never forces navigation.
 assert.ok(node("#research-output").innerHTML.includes('id="conversation-followup"'));
 assert.ok(node("#research-output").innerHTML.includes("只整理原文，不调用模型"));
 assert.ok(!node("#research-output").innerHTML.includes("继续未完成的调查"));
 assert.ok(node("created-article").innerHTML.includes("可以继续问"));
 vm.runInContext('state.serviceContract={paths:{"/api/work-materials":{post:{}}}};conversationMaterialReceipts.delete("project-1")',context);
 node("#conversation-material-title").value="正在写的SOP标题";
 node("#conversation-material-source").value="明确出处";
 node("#conversation-material-text").value="</textarea>还没提交的原文";
 node("#conversation-material-panel").open=true;
 node("#application-background").value="</textarea>真实输入的合成经历";
 node("#application-goal").value="合成目标草稿";
 node("#application-constraints").value="合成投入限制";
 node("#conversation-application-panel").open=true;
 await vm.runInContext('openResearchConversation("project-1",false)',context);
 const refreshed=node("#research-output").innerHTML;
 assert.ok(refreshed.includes('id="conversation-work-material"'));
 assert.ok(refreshed.includes('value="正在写的SOP标题"'));
 assert.ok(refreshed.includes("&lt;/textarea&gt;还没提交的原文"));
 assert.ok(refreshed.includes("原文已保存" )===false); // Completed attachment is restored from session storage.
 assert.ok(refreshed.includes("已加入本研究，可在下一轮查阅"));
 assert.ok(refreshed.includes('id="conversation-material-panel" class="detail-section" open'));
 assert.ok(refreshed.includes("&lt;/textarea&gt;真实输入的合成经历"));
 assert.ok(refreshed.includes("合成目标草稿"));assert.ok(refreshed.includes("合成投入限制"));
 assert.ok(refreshed.includes('id="conversation-application-panel" class="detail-section" open'));

 // Returning from memory editing must show the new record, while preserving the question draft.
 context.memoNotes=[{id:"8".repeat(32),kind:"correction",scope:"project",project_id:"project-1",status:"active",origin:"user",version:1,content:"合成旧纠正：个人可以独立上线"}];
 vm.runInContext('conversation.notesFor=null;api=async path=>path.startsWith("memories")?memoNotes:project',context);
 await vm.runInContext('openResearchConversation("project-1",false)',context);
 assert.ok(node("#research-output").innerHTML.includes("合成旧纠正：个人可以独立上线"));
 context.memoNotes=[{...context.memoNotes[0],id:"9".repeat(32),version:2,content:"合成新版纠正：上线需平台团队确认"}];
 node("#conversation-question").value="保留我正在写的追问";
 await vm.runInContext('loadMemories();',context);
 await vm.runInContext('openResearchConversation("project-1",false)',context);
 assert.ok(node("#research-output").innerHTML.includes("合成新版纠正：上线需平台团队确认"));
 assert.ok(!node("#research-output").innerHTML.includes("合成旧纠正：个人可以独立上线"));
 assert.equal(node("#conversation-question").value,"保留我正在写的追问");
 context.memoNotes=[];
 await vm.runInContext('loadMemories();',context);
 await vm.runInContext('openResearchConversation("project-1",false)',context);
 assert.ok(!node("#research-output").innerHTML.includes("合成新版纠正：上线需平台团队确认"));

 const projectsBeforePastedOnly=context.calls.filter(c=>c.path==="projects").length;
 node("#research-source-mode").value="jobs";
 vm.runInContext('selectedResearchDocuments.clear();selectResearchDocument("f".repeat(32),"已有工作资料");state.researchIds=null;globalThis.messages=[];notify=message=>messages.push(message);openResearchConversation=async id=>opened.push(id);api=async(path,options)=>{calls.push({path,options});if(path.startsWith("jobs?"))return {jobs:[]};if(path.startsWith("public-documents?"))return {documents:[],total:0};return {id:"pasted-only",revision:1,job_ids:[],steps:[],ready_step_ids:[],budget:{max_calls:24,max_seconds:720,max_rounds:6,max_public:0},usage:{calls:0,reserved_calls:0,reserved_seconds:0,public:0},worker_running:false};}',context);
 await vm.runInContext('startResearchConversation("解释我保存的SOP")',context);
 assert.equal(context.calls.filter(c=>c.path==="projects").length,projectsBeforePastedOnly+1);
 const pastedOnly=JSON.parse(context.calls.filter(c=>c.path==="projects").at(-1).options.body);
 assert.deepEqual(pastedOnly.job_ids,[]);assert.deepEqual(pastedOnly.public_document_ids,["f".repeat(32)]);
 assert.equal(node("#research-source-mode").value,"public");
 const startsAfterSelection=context.calls.filter(c=>c.path==="projects").length;
 vm.runInContext('selectedResearchDocuments.clear();api=async(path,options)=>{calls.push({path,options});if(path.startsWith("jobs?"))return {jobs:[]};if(path.startsWith("public-documents?"))return {documents:[],total:1};return {id:"archive-only",revision:1,job_ids:[],steps:[],ready_step_ids:[],budget:{max_calls:24,max_seconds:720,max_rounds:6,max_public:0},usage:{calls:0,reserved_calls:0,reserved_seconds:0,public:0},worker_running:false};}',context);
 node("#research-source-mode").value="jobs";
 await vm.runInContext('startResearchConversation("解释库中已有工作资料")',context);
 assert.equal(context.calls.filter(c=>c.path==="projects").length,startsAfterSelection+1);
 const startsBeforeEmpty=context.calls.filter(c=>c.path==="projects").length;
 const runsBeforeEmpty=context.calls.filter(c=>c.path.endsWith("/run")).length;
 vm.runInContext('api=async(path,options)=>{calls.push({path,options});return path.startsWith("jobs?")?{jobs:[]}:{documents:[],total:0};}',context);
 for(const mode of ["jobs","public"]){
   node("#research-source-mode").value=mode;
   await vm.runInContext('startResearchConversation("没有原文时先补资料")',context);
 }
 assert.equal(context.calls.filter(c=>c.path==="projects").length,startsBeforeEmpty);
 assert.equal(context.calls.filter(c=>c.path.endsWith("/run")).length,runsBeforeEmpty);
 assert.ok(context.messages.at(-1).includes("粘贴工作资料"));

})().catch(error=>{console.error(error);process.exitCode=1;});

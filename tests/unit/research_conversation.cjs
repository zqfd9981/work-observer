// Verify the production start/follow-up sequence with isolated API and DOM doubles.
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const nodes=new Map(),storage=new Map();
const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{checked:false,value:"",disabled:false,children:[],append(child){this.children.push(child);},insertAdjacentHTML(position,html){this.innerHTML=(this.innerHTML||"")+html;},querySelector:node,querySelectorAll:()=>[],addEventListener(){}});return nodes.get(selector);};
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
 assert.deepEqual(project.job_ids,["job-1"]);assert.equal(project.goal,"合成输入问题");assert.equal(project.max_calls,24);
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

 context.project={id:"project-1",title:"合成持续调查",state:"active",usage:{calls:0,reserved_calls:0},budget:{max_calls:24},worker_running:false,steps:[{id:"step",question:"合成问题",state:"waiting_material",offline:true,result:{question:"合成问题",status:"evidence_only",scope:{counts:{matched:1,unknown:0,candidate_details:1},jobs:[]},evidence:[],claims:[],gaps:["哪些资料还需要核实？"],mode:"offline",created_at:"2026-11-19"}}]};
 vm.runInContext('openResearchConversation=originalOpen;api=async()=>project;state.page="jobs"',context);
 await vm.runInContext('openResearchConversation("project-1",false)',context);
 assert.equal(context.location.hash,""); // Background refresh never forces navigation.
 assert.ok(node("#research-output").innerHTML.includes('id="conversation-followup"'));
 assert.ok(node("#research-output").innerHTML.includes("只整理原文，不调用模型"));
 assert.ok(!node("#research-output").innerHTML.includes("继续未完成的调查"));
 assert.ok(node("div").innerHTML.includes("沿着这些疑问继续查"));

})().catch(error=>{console.error(error);process.exitCode=1;});

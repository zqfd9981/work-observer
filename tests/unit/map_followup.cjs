// A map opens an editable investigation in its source project; it never starts a model itself.
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const nodes=new Map(),storage=new Map();let serial=0;
const node=key=>{if(!nodes.has(key))nodes.set(key,{value:"",checked:false,disabled:false,innerHTML:"",querySelector:node,querySelectorAll:()=>[],addEventListener(){},focus(){},scrollIntoView(){}});return nodes.get(key);};
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){},createElement:node},window:{addEventListener(){}},location:{hash:"#research"},sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},crypto:{randomUUID:()=>"request"+(++serial)},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],"utf8"),ctx);
ctx.calls=[];ctx.messages=[];
ctx.result={project_id:"project",run_id:"run",status:"completed",claims:[{text:"原判断",evidence_ids:["one"]}],evidence:[],work_map:{version:"test",scope_note:"有限范围",work_types:[{name:"合成类型",problem:"问题",tasks:"任务",deliverables:"交付物",boundary:"尚未证明的边界",next_check:"核实个人分工",claim_indices:[0]}],work_relations:[{source_kind:"task",source_text:"合成任务",target_kind:"ability",target_text:"合成能力",predicate:"requires",rationale:"待核实关联",transfer_limit:"不能据同名工具证明迁移",claim_indices:[0]}],unknowns:["<script>原图未知项</script>"]}};
ctx.project={id:"project",state:"active",revision:1,scope_version:1,job_ids:["original-job"],steps:[{id:"source-step",run_id:"run",state:"waiting_review",question:"原问题",approach:"work_map",coverage_mode:"all"}],worker_running:false,budget:{max_calls:24,max_seconds:720,max_rounds:6,max_public:0},usage:{reserved_calls:4,reserved_seconds:120}};
vm.runInContext(`
state.serviceContract={components:{schemas:{StepInput:{properties:{approach:{enum:["standard","work_map"]},coverage_mode:{enum:["all","question"]},reply_to_step_id:{}}}}}};
notify=(text)=>messages.push(text);
openResearchConversation=async id=>{conversation.id=id;conversation.project=project;};
api=async(path,options)=>{
 calls.push({path,options});
 if(path==="research/run")return {state:"finished",result};
 if(path==="projects/project"&&!options)return project;
 if(path.endsWith("/steps")){const body=JSON.parse(options.body);project.steps.push({...body,id:"followup",state:"queued"});project.revision++;if(failSave){failSave=false;throw Error("lost save");}return project;}
 if(path.endsWith("/run")){project.steps.at(-1).state="waiting_review";return {};}
 throw Error(path);
};`,ctx);
ctx.button={dataset:{mapProject:"project",mapRun:"run",mapInvestigation:"boundary",mapIndex:"0"}};
(async()=>{
 const html=vm.runInContext('renderWorkMap(result,new Map())',ctx);
 assert.ok(html.includes('data-map-investigation="boundary"')&&html.includes('data-map-investigation="relation"')&&html.includes('data-map-investigation="unknown"'));
 assert.ok(html.includes("&lt;script&gt;原图未知项")&&!html.includes("<script>"));
 node("#conversation-question").value="保留已有草稿";
 await vm.runInContext('prepareMapInvestigation(button)',ctx);
 assert.equal(ctx.calls.length,2);assert.ok(ctx.calls.every(call=>!call.options));
 assert.ok(node("#conversation-question").value.startsWith("保留已有草稿"));
 assert.ok(node("#conversation-question").value.includes("核实个人分工"));
 assert.equal(node("#conversation-kind").value,"counterexample");
 assert.equal(vm.runInContext('conversation.replyToStepId',ctx),"source-step");
 ctx.question=node("#conversation-question").value;ctx.failSave=true;
 await assert.rejects(vm.runInContext('askResearchConversation(question)',ctx),/lost save/);
 assert.equal(ctx.project.steps.at(-1).kind,"counterexample");
 vm.runInContext('conversationSendKeys.clear()',ctx);node("#conversation-kind").value="";
 await vm.runInContext('askResearchConversation(question)',ctx);
 assert.equal(ctx.calls.filter(call=>call.path.endsWith("/steps")).length,1);
 assert.equal(ctx.calls.filter(call=>call.path.endsWith("/run")&&call.options?.method==="POST").length,1);
 assert.equal(ctx.project.steps.at(-1).reply_to_step_id,"source-step");
 assert.equal(ctx.project.steps.at(-1).coverage_mode,"all");
 assert.equal(ctx.project.steps.at(-1).approach,"work_map");
 ctx.button.dataset.mapInvestigation="unknown";
 const prompt=vm.runInContext('mapInvestigationPrompt(result,"unknown",0)',ctx);
 assert.equal(prompt.kind,"investigate");assert.ok(prompt.question.includes("未知"));
 node("#conversation-question").value="x".repeat(3999);
 await assert.rejects(vm.runInContext('prepareMapInvestigation(button)',ctx),/原草稿已保留/);
 assert.equal(node("#conversation-question").value.length,3999);
 ctx.result.status="failed";
 await assert.rejects(vm.runInContext('prepareMapInvestigation(button)',ctx),/来源研究已不可用/);
 console.log("Map boundaries, relationships and unknowns lead to source-bound editable followups; retries retain purpose and scope.");
})().catch(error=>{console.error(error);process.exitCode=1;});

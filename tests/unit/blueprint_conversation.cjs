// One main-entry flow: map creation, lost response, follow-up and ordinary explanation.
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const nodes=new Map(),storage=new Map();let sequence=0;
const node=key=>{if(!nodes.has(key))nodes.set(key,{value:"",checked:false,disabled:false,innerHTML:"",querySelector:node,querySelectorAll:()=>[],addEventListener(){},focus(){},scrollIntoView(){}});return nodes.get(key);};
const context={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){},createElement:node},window:{addEventListener(){}},location:{hash:"#research"},sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},crypto:{randomUUID:()=>"blueprint"+(++sequence)},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[2],"utf8"),context);
context.calls=[];context.failCreate=true;
context.project={id:"project",revision:1,scope_version:1,job_ids:["one","two"],steps:[],worker_running:false,budget:{max_calls:24,max_seconds:720,max_rounds:6,max_public:0},usage:{calls:0,reserved_calls:0,reserved_seconds:0}};
vm.runInContext(`
state.serviceContract={components:{schemas:{StepInput:{properties:{approach:{enum:["standard","work_map"]},coverage_mode:{enum:["all","question"]},reply_to_step_id:{}}}}}};
openResearchConversation=async id=>{};notify=()=>{};
api=async(path,options)=>{
 calls.push({path,options});
 if(path.startsWith("jobs?"))return {jobs:[{id:"one"},{id:"two"}]};
 if(path==="projects"){if(failCreate){failCreate=false;throw Error("lost create response");}return project;}
 if(path==="projects/project"&&!options)return project;
 if(path.endsWith("/steps")){const body=JSON.parse(options.body);project.steps.push({...body,id:"step"+project.steps.length,approach:body.approach||"standard",state:"queued"});project.revision++;return project;}
 if(path.endsWith("/run")){const step=project.steps.at(-1);step.state="waiting_review";project.usage.reserved_calls+=step.max_calls;return {};}
 throw Error("Unexpected path: "+path);
};`,context);
(async()=>{
 node("#research-source-mode").value="jobs";node("#research-approach").value="work_map";
 node("#question").value="按蓝图建立工作地图";
 await vm.runInContext('startResearch({preventDefault(){}})',context);
 assert.equal(JSON.parse(storage.get("wo-pending-research")).intent.includes('"approach":"work_map"'),true);
 node("#research-approach").value="standard";
 vm.runInContext('restorePendingResearch()',context);
 assert.equal(node("#research-approach").value,"work_map");
 await vm.runInContext('startResearch({preventDefault(){}})',context);
 assert.equal(context.project.steps[0].approach,"work_map");
 assert.equal(context.project.steps[0].coverage_mode,"question");
 const bodies=context.calls.filter(c=>c.path==="projects").map(c=>JSON.parse(c.options.body));
 assert.deepEqual(bodies[0],bodies[1]);
 vm.runInContext('state.researchIds=["unrelated-selection"]',context);
 await vm.runInContext('askResearchConversation("继续核实地图的边界")',context);
 assert.equal(context.project.steps[1].approach,"work_map");
 assert.equal(context.project.steps[1].reply_to_step_id,"step0");
 assert.equal(context.project.steps[1].coverage_mode,"question");
 await vm.runInContext('askResearchConversation("只解释这个边界",{approach:"standard"})',context);
 assert.equal(context.project.steps[2].approach,"standard");
 assert.equal(context.project.steps[2].reply_to_step_id,"step1");
 assert.equal(context.project.usage.reserved_calls,24);
 assert.equal(context.calls.some(c=>c.path==="research"),false);
 console.log("Blueprint entry stays in one persistent project through map and ordinary follow-ups.");
})().catch(error=>{console.error(error);process.exitCode=1;});

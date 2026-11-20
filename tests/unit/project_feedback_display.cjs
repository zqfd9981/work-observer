// Production project form/handler replay; synthetic DOM, no browser or provider.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const nodes=new Map(),handlers={};
const node=selector=>{
  if(!nodes.has(selector))nodes.set(selector,{innerHTML:"",value:"",listeners:{},querySelector:node,querySelectorAll:()=>[],addEventListener(name,fn){this.listeners[name]=fn;}});
  return nodes.get(selector);
};
const context={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(name,fn){(handlers[name]??=[]).push(fn);}},window:{addEventListener(){}},location:{hash:""},URL,console,setTimeout,clearTimeout,Intl,crypto:{randomUUID:()=>"synthetic-key"}};
vm.createContext(context);
const app=process.argv[2];
vm.runInContext(fs.readFileSync(app,"utf8"),context);
vm.runInContext(fs.readFileSync(path.join(path.dirname(app),"projects.js"),"utf8"),context);
context.project={id:"a".repeat(32),revision:4,title:"合成项目",goal:"合成目标",scope_version:1,job_ids:["b".repeat(32)],usage:{calls:3,reserved_calls:5,seconds:1,public:0},budget:{max_calls:10,max_public:0},state:"active",steps:[{id:"c".repeat(32),question:"合成核对",completion:"保留优先",scope_version:1,max_calls:5,timeout:60,state:"waiting_review",repair:{available:true,review_id:"d".repeat(32),reviewer_kind:"agent_assisted",remaining_calls:5,remaining_seconds:60}}]};
context.calls=[];
vm.runInContext('api=async(route,options)=>{calls.push({route,options});return route==="projects"?[]:project;};state.page="projects";notify=()=>{};renderResult=()=>{}',context);
(async()=>{
 await vm.runInContext('openProject(project.id)',context);
 assert.equal(context.calls.length,1);
 const html=node("#project-steps").innerHTML;
 assert.ok(html.includes('data-step-repair="'+"c".repeat(32)+'"'));
 assert.ok(html.includes('data-review-id="'+"d".repeat(32)+'"'));
 assert.ok(html.includes("Agent辅助复核，非人审")&&html.includes("保存后需点击项目的继续才执行"));
 assert.ok(html.includes("5 次调用、60 秒"));
 const event={target:{id:"",dataset:{stepRepair:"c".repeat(32),reviewId:"d".repeat(32)},matches:()=>false,closest:()=>null,elements:{note:{value:"  合成限定补查  "},max_calls:{value:"4"},timeout:{value:"55"},offline:{checked:false}}},preventDefault(){}};
 for(const handler of handlers.submit)await handler(event);
 const writes=context.calls.filter(row=>row.options?.method==="POST");
 assert.equal(writes.length,1);
 assert.equal(writes[0].route,"projects/"+context.project.id+"/steps/"+"c".repeat(32)+"/repair");
 const data=JSON.parse(writes[0].options.body);
 assert.equal(data.revision,4);assert.equal(data.review_id,"d".repeat(32));assert.equal(data.note,"合成限定补查");
 assert.equal(data.max_calls,4);assert.equal(data.timeout,55);assert.equal(data.offline,false);
 assert.ok(!context.calls.some(row=>row.route.endsWith("/run"))); // Saving is not execution.
 context.step={id:'<img src=x onerror=1>',repair:{...context.project.steps[0].repair,review_id:'<script>pin</script>'}};
 const escaped=vm.runInContext("renderProjectRepair(step)",context);
 assert.ok(escaped.includes("&lt;img")&&escaped.includes("&lt;script&gt;pin"));
 assert.ok(!escaped.includes("<img")&&!escaped.includes("<script>"));
})().catch(error=>{console.error(error);process.exitCode=1;});

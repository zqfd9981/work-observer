// A dropped response must not turn the same user message into another model investigation.
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const nodes=new Map(),storage=new Map();let sequence=0;
const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{checked:false,value:"",disabled:false,innerHTML:"",dataset:{},focus(){},scrollIntoView(){},querySelector:node,querySelectorAll:()=>[],addEventListener(){}});return nodes.get(selector);};
const context={document:{createElement:tag=>node("created-"+tag),querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:""},sessionStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k)||null,removeItem:k=>storage.delete(k)},crypto:{randomUUID:()=>"request-"+(++sequence)},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[2],"utf8"),context);
context.fresh=()=>({id:"a".repeat(32),scope_version:1,revision:1,worker_running:false,job_ids:[],budget:{max_calls:3,max_seconds:180,max_rounds:1,max_public:0},usage:{calls:0,reserved_calls:0},steps:[]});
vm.runInContext(`
globalThis.writes=0;globalThis.starts=0;globalThis.opens=0;
openResearchConversation=async()=>{opens++;if(failView){failView=false;throw new Error("view lost");}};
api=async(path,options)=>{
  if(!options)return project;
  if(path.endsWith("/steps")){
    const data=JSON.parse(options.body);
    if(!project.steps.some(step=>step.key===data.key)){writes++;project.steps.push({...data,id:"b".repeat(32),scope_version:1,state:"queued"});project.revision++;}
    if(failSave){failSave=false;throw new Error("save response lost");}
    return project;
  }
  if(path.endsWith("/run")){
    starts++;project.steps[0].state="waiting_review";project.usage={calls:3,reserved_calls:3};
    if(failRun){failRun=false;throw new Error("run response lost");}
    return {};
  }
};`,context);
(async()=>{
 for(const failure of ["failSave","failRun","failView"]){
  context.project=context.fresh();context.failSave=false;context.failRun=false;context.failView=false;context[failure]=true;
  vm.runInContext('writes=0;starts=0;opens=0;conversationSendKeys.clear();conversation.id=project.id;conversation.replyToStepId=undefined',context);storage.clear();
  await assert.rejects(vm.runInContext('askResearchConversation("合成同一问题")',context),/lost/);
  assert.ok(storage.has("wo-pending-question:"+context.project.id));
  vm.runInContext('conversationSendKeys.clear()',context); // A reload still has the safe request receipt.
  await vm.runInContext('askResearchConversation("合成同一问题")',context);
  assert.equal(context.writes,1,failure);assert.equal(context.starts,1,failure);
  assert.equal(context.project.steps.length,1);assert.equal(context.project.usage.calls,3);
  assert.equal(storage.has("wo-pending-question:"+context.project.id),false);
 }
 context.project=context.fresh();context.failSave=true;context.failRun=false;context.failView=false;
 vm.runInContext('writes=0;starts=0;conversation.id=project.id',context);
 await assert.rejects(vm.runInContext('askResearchConversation("已保存原问题")',context),/save response lost/);
 await assert.rejects(vm.runInContext('askResearchConversation("另一个问题")',context),/上一条问题已保存/);
 assert.equal(context.starts,0);assert.equal(context.writes,1);
 context.failSave=false;
 const pending=vm.runInContext('askResearchConversation("已保存原问题")',context);
 await assert.rejects(vm.runInContext('askResearchConversation("已保存原问题")',context),/正在发送/);
 await pending;
 assert.equal(context.writes,1);assert.equal(context.starts,1);
 console.log("Conversation retry: lost save/start/view responses, original budget and double-submit checks passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});

const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),values=new Map();
function node(key){if(!nodes.has(key))nodes.set(key,{value:'',checked:false,content:'test',addEventListener(){},querySelector:node,querySelectorAll:()=>[]});return nodes.get(key);}
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:''},URL,URLSearchParams,Intl,console,setTimeout,clearTimeout,sessionStorage:{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
ctx.started=[];ctx.opened=[];
vm.runInContext('startResearchConversation=async question=>started.push({question,jobs:[...state.researchIds],offline:$("#offline").checked,public:$("#allow-public").checked,documents:selectedResearchDocuments.size});openResearchConversation=async id=>opened.push(id);state.overview={model_configured:true};selectedResearchDocuments.set("old-document",{});',ctx);
(async()=>{
 await vm.runInContext('startIndustryResearchTask("研究实际工作",["job-a","job-b"])',ctx);
 const liveLimit=vm.runInContext('conversationAllocation({budget:{max_calls:24,max_seconds:720,max_rounds:6,max_public:0},steps:[],usage:{}},false,false)',ctx);assert.equal(liveLimit.maxCalls,12);
 assert.equal(ctx.started.length,1);assert.equal(ctx.started[0].offline,false);assert.equal(ctx.started[0].public,false);assert.equal(ctx.started[0].documents,0);assert.deepEqual(Array.from(ctx.started[0].jobs),['job-a','job-b']);
 vm.runInContext('state.overview={model_configured:false};',ctx);
 await assert.rejects(vm.runInContext('startIndustryResearchTask("另一个问题",["new-job"])',ctx),/模型尚未接通/);
 assert.equal(ctx.started.length,1);assert.deepEqual(Array.from(vm.runInContext('state.researchIds',ctx)),['job-a','job-b']);
 vm.runInContext('pendingResearch("project:live-project")',ctx);
 assert.deepEqual(Array.from(ctx.opened),['live-project']);
 console.log('Agent model mode: real analysis by default, fixed local source scope, no silent evidence-only fallback, preserved input on missing configuration and project progress restoration passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});

const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const node=()=>({querySelector:node,querySelectorAll:()=>[],addEventListener(){}});
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:""},URL,console,setTimeout,clearTimeout,Intl};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],"utf8"),ctx);
ctx.project={id:"project",revision:3,worker_running:false,steps:[{id:"selected",run_id:"same-run",state:"failed",continuation:{available:true,remaining_calls:2,remaining_seconds:50}}]};
ctx.calls=[];ctx.failReview=true;ctx.switchOnRead=false;ctx.opened=[];
vm.runInContext('conversation.id=project.id;api=async(path,options)=>{calls.push({path,options});if(!options){if(switchOnRead)conversation.id="other";return project;}if(path.endsWith("/review")){project.steps[0].state="interrupted";if(failReview)throw Error("response lost");}return {};};openResearchConversation=async id=>opened.push(id)',ctx);
(async()=>{
 await assert.rejects(vm.runInContext('continueConversationStep("selected")',ctx),/response lost/);
 assert.equal(ctx.calls.filter(x=>x.path.endsWith("/run")).length,0);
 ctx.failReview=false;
 await vm.runInContext('continueConversationStep("selected")',ctx);
 assert.equal(ctx.calls.filter(x=>x.path.endsWith("/review")).length,1); // Retry a lost reply without repeating review.
 const runs=ctx.calls.filter(x=>x.path.endsWith("/run"));assert.equal(runs.length,1);
 assert.deepEqual(JSON.parse(runs[0].options.body),{step_id:"selected"});
 assert.ok(ctx.calls.every(x=>!x.path.endsWith("/steps"))); // Same checkpoint; no new round/allocation.
 ctx.calls=[];ctx.project.steps[0].continuation={available:false,reason:"calls_exhausted"};
 await assert.rejects(vm.runInContext('continueConversationStep("selected")',ctx),/调用次数已用完/);
 assert.ok(ctx.calls.every(x=>!x.options));
 ctx.project.steps[0].continuation.available=true;ctx.switchOnRead=true;ctx.calls=[];
 await assert.rejects(vm.runInContext('continueConversationStep("selected")',ctx),/研究已切换/);
 assert.ok(ctx.calls.every(x=>!x.options));
 const html=vm.runInContext('renderStepContinuation(project,project.steps[0])',ctx);
 assert.ok(html.includes('data-continue-conversation-step="selected"'));
 console.log("Conversation continuation: same checkpoint, lost replies, scope switches and exhausted budgets passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});

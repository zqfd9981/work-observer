// Select already-stored sources without importing, starting research or losing questions.
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const nodes=new Map(),node=key=>{if(!nodes.has(key))nodes.set(key,{value:"",innerHTML:"",open:false,querySelector:node,querySelectorAll:()=>[],addEventListener(){},replaceChildren(){this.innerHTML="";}});return nodes.get(key);};
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:""},sessionStorage:{removeItem(){}},URL,URLSearchParams,console,Intl,setTimeout,clearTimeout};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],"utf8"),ctx);
ctx.project={id:"project",state:"active",revision:1,scope_version:1,goal:"原有研究目标",job_ids:["a"],public_document_ids:[],worker_running:false,steps:[]};
ctx.calls=[];ctx.opened=[];ctx.throwAfterPatch=false;ctx.switchOnRead=false;
vm.runInContext(`conversation.id=project.id;conversation.project=project;api=async(path,options)=>{
 calls.push({path,options});if(path.startsWith("jobs?"))return {jobs:[{id:"a",title:"<script>原岗位</script>",has_detail:true},{id:"b",title:"第二岗位",has_detail:false}],counts:{matched:2,unknown:0}};
 if(path.startsWith("public-documents?"))return {documents:[{id:"d",title:"归档资料",integrity:"verified",evidence_kind:"work_material",observed_at:"2026-11-19T12:00:00+00:00"}],total:1};
 if(!options){if(switchOnRead)conversation.id="other";return project;}
 const body=JSON.parse(options.body);project.job_ids=body.job_ids;project.public_document_ids=body.public_document_ids;project.revision++;project.scope_version++;
 if(throwAfterPatch){throwAfterPatch=false;throw Error("lost response");}return project;
};openResearchConversation=async(id,navigate)=>opened.push({id,navigate});`,ctx);
const patchCount=()=>ctx.calls.filter(row=>row.options?.method==="PATCH").length;
(async()=>{
 vm.runInContext('conversationScopeDraft(project)',ctx);
 await vm.runInContext('Promise.all([loadConversationScopeSources("jobs"),loadConversationScopeSources("documents")])',ctx);
 let html=vm.runInContext('renderConversationScopeBody(project,conversation.sourceScopes.get(project.id))',ctx);
 assert.ok(html.includes("&lt;script&gt;原岗位")&&!html.includes("<script>"));assert.ok(html.includes("仅摘要")&&html.includes("补充工作资料"));
 assert.ok(html.includes("归档")&&html.includes("非发布时间"));
 node("#conversation-question").value="尚未发出的追问";
 vm.runInContext('globalThis.draft=conversation.sourceScopes.get(project.id);draft.jobIds.add("b");draft.documentIds.add("d");draft.dirty=true;',ctx);
 await vm.runInContext('saveConversationScope()',ctx);
 const body=JSON.parse(ctx.calls.find(row=>row.options?.method==="PATCH").options.body);
 assert.deepEqual(body.job_ids,["a","b"]);assert.deepEqual(body.public_document_ids,["d"]);assert.equal(body.goal,"原有研究目标");
 assert.equal(node("#conversation-question").value,"尚未发出的追问");assert.equal(ctx.opened[0].navigate,false);
 assert.ok(ctx.calls.every(row=>!row.path.endsWith("/run")&&!row.path.endsWith("/import")&&(!row.options||row.options.method==="PATCH")));
 await vm.runInContext('saveConversationScope()',ctx);assert.equal(patchCount(),1);
 // A lost PATCH response must not create a second scope-history entry.
 vm.runInContext('draft.jobIds.delete("b");draft.jobIds.add("c");draft.dirty=true;',ctx);ctx.throwAfterPatch=true;
 await assert.rejects(vm.runInContext('saveConversationScope()',ctx),/lost response/);
 const version=ctx.project.scope_version;
 await vm.runInContext('saveConversationScope()',ctx);
 assert.equal(ctx.project.scope_version,version);assert.equal(patchCount(),2);
 // A different change from another window is preserved, not silently overwritten.
 vm.runInContext('draft.jobIds.add("b");draft.dirty=true;project.job_ids=["external"];project.scope_version++;',ctx);
 await assert.rejects(vm.runInContext('saveConversationScope()',ctx),/范围已在其他地方改变/);
 assert.deepEqual(Array.from(ctx.project.job_ids),["external"]);assert.equal(patchCount(),2);
 ctx.switchOnRead=true;
 await assert.rejects(vm.runInContext('saveConversationScope()',ctx),/研究已切换/);
 assert.equal(patchCount(),2);ctx.switchOnRead=false;
 // Preserve the API's distinct null/all-archive mode.
 vm.runInContext('conversation.id=project.id;draft.scopeVersion=project.scope_version;project.job_ids=[...draft.jobIds];draft.allDocuments=true;',ctx);
 await vm.runInContext('saveConversationScope()',ctx);
 assert.equal(ctx.project.public_document_ids,null);
 // Late catalog reads cannot restore an erased project's selection.
 vm.runInContext('api=()=>new Promise(resolve=>globalThis.deliver=resolve)',ctx);
 const pending=vm.runInContext('loadConversationScopeSources("jobs")',ctx);
 vm.runInContext('clearForgottenConversation([project.id])',ctx);
 ctx.deliver({jobs:[{id:"private",title:"不应恢复"}],counts:{matched:1,unknown:0}});await pending;
 assert.equal(vm.runInContext('conversation.sourceScopes.has(project.id)',ctx),false);
 console.log("Conversation scope: existing sources, exact selection, no model/import, lost responses, concurrent scope edits and forgetting passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});

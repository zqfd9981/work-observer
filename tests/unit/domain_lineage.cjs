// Execute the actual knowledge page's scope selection without a browser or network.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const nodes=new Map();
const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{value:"",checked:false,innerHTML:"",querySelector:node,querySelectorAll:()=>[],addEventListener(){}});return nodes.get(selector);};
const context={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:""},URL,console,setTimeout,clearTimeout,Intl};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[2],"utf8"),context);
context.domains=[{id:"merged",version:1,name:"合成项目内合并定义",definition:"任务定义",inclusion:"",exclusion:"",related_ids:["a","b"],source_context:{},source_contexts:[{project_id:"project-a",run_id:"original-a",scope_note:"<script>原范围</script>"},{project_id:"project-a",run_id:"original-b"}],supporting_claims:[],revision_notices:[],status:"active"}];
vm.runInContext('api=async p=>p==="projects"?[{id:"project-a",title:"合成项目",state:"active"}]:p.startsWith("knowledge/domains")?{domains}:{relations:[]};notify=message=>{throw new Error(message);}',context);
vm.runInContext(fs.readFileSync(path.join(path.dirname(process.argv[2]),"knowledge.js"),"utf8"),context);
(async()=>{
 await context.window.loadKnowledge();
 assert.ok(!node("#knowledge-domains").innerHTML.includes("合成项目内合并定义"));
 node("#knowledge-project").value="project-a";
 await context.window.loadKnowledge();
 const scoped=node("#knowledge-domains").innerHTML;
 assert.ok(scoped.includes("合成项目内合并定义")&&scoped.includes("沿用合并或拆分前定义的来源"));
 assert.ok(scoped.includes('data-open-run="original-a"')&&scoped.includes('data-open-run="original-b"'));
 assert.ok(scoped.includes("&lt;script&gt;原范围&lt;/script&gt;")&&!scoped.includes("<script>"));
 node("#knowledge-project").value="project-b";
 await context.window.loadKnowledge();
 assert.ok(!node("#knowledge-domains").innerHTML.includes("合成项目内合并定义"));
 console.log("Definition lineage UI: project scope, original research links and escaping passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});

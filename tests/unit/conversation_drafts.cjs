// Switch actual conversation views while preserving each project's unsent work.
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const nodes=new Map(),storage=new Map(),calls=[];
const node=key=>{if(!nodes.has(key))nodes.set(key,{value:"",checked:false,disabled:false,innerHTML:"",open:false,children:[],dataset:{},
  append(child){this.children.push(child);},focus(){},scrollIntoView(){},setSelectionRange(){},replaceChildren(){this.innerHTML="";},
  closest(){return node(key+"-panel");},querySelector:node,querySelectorAll:()=>[],addEventListener(){},classList:{toggle(){},add(){},remove(){}}});return nodes.get(key);};
const ctx={document:{querySelector:node,querySelectorAll:()=>[],createElement:node,addEventListener(){}},window:{addEventListener(){}},
  location:{hash:"#research"},sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
  console,URL,URLSearchParams,Intl,setTimeout,clearTimeout};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],"utf8"),ctx);
const project=id=>({id,title:id,state:"active",scope_version:1,worker_running:false,job_ids:[],steps:[],usage:{calls:0},budget:{max_calls:24,max_seconds:720,max_public:4,max_rounds:6}});
ctx.projects={a:project("a"),b:project("b")};ctx.calls=calls;
ctx.projects.a.steps=[{id:"step-a",run_id:"run-a",state:"waiting_review",question:"合成旧问题",result:{status:"completed",claims:[{text:"合成旧判断"}]}}];
vm.runInContext(`api=async(path,options)=>{calls.push({path,options});return path.startsWith("memories")?[]:projects[path.split("/")[1]];};
  state.page="research";state.serviceContract={paths:{"/api/work-materials":{post:{}},"/api/public-documents":{post:{}}},components:{schemas:{StepInput:{properties:{approach:{enum:["standard","work_map"]}}}}}};
  renderProjectUnderstanding=()=>"";`,ctx);
const textFields=["conversation-question","conversation-context-content","conversation-public-url","conversation-material-title","conversation-material-source","conversation-material-text","application-background","application-goal","application-constraints"];
const clearFields=()=>{for(const id of textFields)node("#"+id).value="";node("#conversation-context [name=kind]").value="preference";};
(async()=>{
 await vm.runInContext('openResearchConversation("a")',ctx);
 node("#conversation-question").value="A的未发问题<script>";
 node("#conversation-context-content").value="A的纠正理由";
 node("#conversation-context [name=kind]").value="correction";
 node("#conversation-material-title").value="A的材料标题";
 node("#conversation-material-source").value="A的出处";
 node("#conversation-material-text").value="A的原文草稿";
 node("#application-background").value="A的背景草稿";
 node("#application-goal").value="A的目标草稿";
 node("#application-constraints").value="A的限制草稿";
 node("#conversation-offline").checked=true;node("#conversation-allow-public").checked=false;
 node("#conversation-kind").value="counterexample";node("#conversation-approach").value="work_map";
 vm.runInContext('conversation.replyToStepId="step-a";conversation.correctionTarget={projectId:"a",stepId:"step-a",runId:"run-a",index:0,statement:"合成旧判断",question:"合成旧问题"}',ctx);
 await vm.runInContext('openResearchConversation("b")',ctx);
 assert.ok(!node("#research-output").innerHTML.includes("A的纠正理由"));
 clearFields();node("#conversation-question").value="B的未发问题";
 node("#conversation-offline").checked=false;node("#conversation-kind").value="investigate";
 await vm.runInContext('openResearchConversation("a")',ctx);
 const html=node("#research-output").innerHTML;
 for(const text of ["A的未发问题&lt;script&gt;","A的纠正理由","A的材料标题","A的出处","A的原文草稿","A的背景草稿","A的目标草稿","A的限制草稿"])assert.ok(html.includes(text),text);
 assert.ok(!html.includes("A的未发问题<script>"));
 assert.equal(vm.runInContext('conversation.replyToStepId',ctx),"step-a");
 assert.equal(vm.runInContext('conversation.correctionTarget.statement',ctx),"合成旧判断");
 assert.ok(html.includes('value="counterexample" selected')&&html.includes('value="work_map" selected'));
 assert.equal(vm.runInContext('conversation.drafts.get("b").question',ctx),"B的未发问题");
 assert.ok(calls.every(row=>!row.options)); // No saves, investigation, quota or provider calls.
 // Clear only the inactive forgotten project, then the active project.
 vm.runInContext('clearForgottenConversation(["b"])',ctx);
 assert.equal(vm.runInContext('conversation.drafts.has("b")',ctx),false);
 assert.equal(vm.runInContext('conversation.id',ctx),"a");
 vm.runInContext('clearForgottenConversation(["a"])',ctx);
 assert.equal(vm.runInContext('conversation.drafts.size',ctx),0);
 assert.equal(vm.runInContext('conversation.correctionTarget',ctx),null);
 console.log("Conversation drafts: project switching, correction binding, forms, choices, isolation and forgetting passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});

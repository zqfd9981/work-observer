// Replay document intake and the real start handler as one user flow.
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const nodes=new Map(),storage=new Map(),calls=[];
const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{value:"",checked:false,disabled:false,dataset:{},innerHTML:"",classList:{add(){},remove(){}},focus(){},scrollIntoView(){},querySelector:node,querySelectorAll:()=>[],addEventListener(){}});return nodes.get(selector);};
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:""},sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},URL,URLSearchParams,crypto:{randomUUID:()=>"intake-test"},console,setTimeout,clearTimeout,Intl};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],"utf8"),ctx);
ctx.calls=calls;ctx.saved=[];
vm.runInContext(`api=async(path,options)=>{
 calls.push({path,options});
 if(path==="work-materials"){
  const body=JSON.parse(options.body),document={...body,id:(saved.length+1).toString(16).padStart(32,"0"),full_text_length:body.text.length,integrity:"verified",evidence_kind:"work_material"};saved.push(document);return {document};
 }
 if(path.startsWith("public-documents?"))return {documents:saved,total:saved.length,offset:0,limit:10};
 if(path==="projects"&&options)return {id:"project-intake"};
 if(path==="projects/project-intake"&&!options)return {id:"project-intake",revision:1,worker_running:false};
 return {};
};notify=()=>{};openResearchConversation=async()=>{};`,ctx);
(async()=>{
 ctx.files=[{name:"工作说明.md",size:30,text:async()=>"\uFEFF合成资料：交付接口并与平台团队协作。"},{name:"失败记录.txt",size:16,text:async()=>"合成资料：恢复过程需要回放核对。"},{name:"暂不支持.pdf",size:20}];
 const imported=await vm.runInContext("importResearchFiles(files)",ctx);
 assert.equal(imported.saved.length,2);assert.equal(imported.failed.length,1);
 assert.equal(ctx.saved[0].text,"合成资料：交付接口并与平台团队协作。");
 assert.equal(node("#research-source-mode").value,"public");
 assert.ok(node("#research-file-status").innerHTML.includes("已保存并选入 2 份"));
 assert.ok(calls.every(call=>!call.path.endsWith("/run")));
 assert.equal(node("#start-research").disabled,false);
 node("#work-material-title").value="";
 node("#work-material-text").value="\n合成补充：团队负责验收\n保留原有换行。";
 node("#question").value="比较任务与责任，哪些仍待核实？";
 node("#research-approach").value="standard";node("#offline").checked=true;
 await vm.runInContext("startResearch({preventDefault(){}})",ctx);
 assert.equal(ctx.saved.length,3);assert.equal(ctx.saved[2].title,"合成补充：团队负责验收");
 assert.equal(node("#work-material-text").value,"");
 const project=JSON.parse(calls.find(call=>call.path==="projects").options.body);
 assert.deepEqual(project.job_ids,[]);assert.equal(project.public_document_ids.length,3);
 assert.equal(project.goal,"比较任务与责任，哪些仍待核实？");
 const step=JSON.parse(calls.find(call=>call.path.endsWith("/steps")).options.body);
 assert.equal(step.offline,true);assert.equal(calls.filter(call=>call.path.endsWith("/run")).length,1);
 assert.ok(!calls.some(call=>call.path.startsWith("jobs?")));
 // A save failure leaves the paste available and never launches an empty study.
 const writes=calls.filter(call=>call.path==="projects").length;
 node("#work-material-text").value="合成待保存资料";
 vm.runInContext('api=async()=>{throw new Error("保存暂时失败")}',ctx);
 await vm.runInContext("startResearch({preventDefault(){}})",ctx);
 assert.equal(node("#work-material-text").value,"合成待保存资料");
 assert.equal(calls.filter(call=>call.path==="projects").length,writes);
 console.log("Research intake: multiple files → automatic paste save → scoped project and first question passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});

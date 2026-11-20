// Replay history lookup and privacy resets without creating a research or calling a model.
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const nodes=new Map(),storage=new Map();
const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{checked:false,value:"",disabled:false,innerHTML:"",dataset:{},children:[],focus(){},scrollIntoView(){},replaceChildren(){this.innerHTML="";},append(child){this.children.push(child);},insertAdjacentHTML(position,html){this.innerHTML+=html;},querySelector:node,querySelectorAll:()=>[],addEventListener(){}});return nodes.get(selector);};
const context={document:{createElement:tag=>node("created-"+tag),querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:""},sessionStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k)||null,removeItem:k=>storage.delete(k)},crypto:{randomUUID:()=>"synthetic-request"},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[2],"utf8"),context);
context.calls=[];context.data={items:[{id:"a".repeat(32),state:"finished",status:"completed",question:"<script>合成问题</script>",created_at:"2026-11-19",match:{field:"scope_source",excerpt:"<b>合成未读资料</b>"}}],total:40,offset:0,limit:20};
vm.runInContext('state.serviceContract={paths:{"/api/research-history":{get:{}}}};api=async(path,options)=>{calls.push({path,options});return data;}',context);
(async()=>{
 node("#research-history-query").value="Agent & 召回";
 await vm.runInContext('loadResearchHistory()',context);
 const query=new URLSearchParams(context.calls[0].path.split("?")[1]);
 assert.equal(query.get("q"),"Agent & 召回");assert.equal(query.get("offset"),"0");
 const html=node("#research-history-list").innerHTML;
 assert.ok(html.includes("&lt;script&gt;合成问题"));assert.ok(!html.includes("<script>"));
 assert.ok(html.includes("研究范围内的资料标题（不表示已读）"));
 assert.ok(html.includes('data-open-run="'+"a".repeat(32)+'"'));
 assert.equal(node("#research-history-next").disabled,false);
 context.data.offset=20;await vm.runInContext('loadResearchHistory(20)',context);
 assert.equal(new URLSearchParams(context.calls.at(-1).path.split("?")[1]).get("offset"),"20");
 assert.equal(node("#research-history-prev").disabled,false);assert.equal(node("#research-history-next").disabled,true);
 node("#research-history-query").value="新查询";
 context.data.offset=0;await vm.runInContext('loadResearchHistory(20)',context);
 assert.equal(new URLSearchParams(context.calls.at(-1).path.split("?")[1]).get("offset"),"0");
 for(const [field,label] of [["work_map","工作地图（历史分析）"],["cognition_revision","认识修订（仍须核对）"],["application_plan","行动建议（不表示已执行）"]]){
  context.data.items[0].match={field,excerpt:"<b>仅为历史线索</b>"};
  await vm.runInContext('loadResearchHistory()',context);
  const content=node("#research-history-list").innerHTML;
  assert.ok(content.includes(label));assert.ok(content.includes("&lt;b&gt;仅为历史线索&lt;/b&gt;"));
 }
 vm.runInContext('globalThis.pending=[];api=path=>new Promise(resolve=>pending.push(resolve))',context);
 node("#research-history-query").value="旧的私密查询";const old=vm.runInContext('loadResearchHistory()',context);
 node("#research-history-query").value="新的公开查询";const current=vm.runInContext('loadResearchHistory()',context);
 context.pending[1]({...context.data,items:[],total:0});await current;
 context.pending[0](context.data);await old;
 assert.ok(node("#research-history-list").innerHTML.includes("没有找到匹配的研究"));
 const beforeForget=vm.runInContext('loadResearchHistory()',context);
 vm.runInContext('resetResearchHistory()',context);
 context.pending[2](context.data);await beforeForget;
 assert.equal(node("#research-history-list").innerHTML,"");assert.equal(node("#research-history-query").value,"");
 assert.ok(context.calls.every(call=>!call.options));
 console.log("History UI: search, pagination, safe excerpts, stale responses and forgetting reset passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});

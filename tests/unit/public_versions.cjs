// Exercise the production source viewer and revision workflow with isolated APIs.
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const nodes=new Map(),storage=new Map();
const node=selector=>{
  if(!nodes.has(selector))nodes.set(selector,{value:"",content:"synthetic-token",open:false,checked:false,
    showModal(){this.open=true;},close(){this.open=false;},focus(){},scrollIntoView(){},
    querySelector:node,querySelectorAll:()=>[],addEventListener(){}});
  return nodes.get(selector);
};
const context={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},
  window:{addEventListener(){}},location:{hash:""},sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2],"utf8"),context);
const first="1".repeat(32),second="2".repeat(32),third="3".repeat(32);
const base={id:first,title:"<script>合成旧稿</script>",publisher:"合成来源",url:"urn:work-observer:work-material:"+first,integrity:"verified",evidence_kind:"work_material",text:"</textarea><script>保留的原文</script>",source_published_at:null,observed_at:"2026-11-18T01:00:00+00:00",full_text_length:40,latest_document_id:second,previous_document_id:null};
context.docs={[first]:base,[second]:{...base,id:second,title:"合成新版",previous_document_id:first,observed_at:"2026-11-19T01:00:00+00:00"},[third]:{...base,id:third,title:"合成再修订",latest_document_id:third,previous_document_id:second,observed_at:"2026-11-19T02:00:00+00:00"}};
context.calls=[];
vm.runInContext(`state.page="research";conversation.id="synthetic-project";
  api=async(path,options)=>{calls.push({path,options});if(options)return {document:docs["${third}"]};
    if(path.includes("/history"))return {documents:[docs["${second}"],docs["${first}"]],total:2,offset:0,limit:10};
    return docs[path.split("/")[1]];};`,context);
(async()=>{
  await vm.runInContext(`showPublicSource("${first}")`,context);
  assert.ok(node("#source-content").innerHTML.includes("已有更新归档"));
  assert.ok(!node("#source-content").innerHTML.includes('id="work-material-revision"'));
  await vm.runInContext(`showPublicSource("${second}")`,context);
  assert.ok(node("#source-content").innerHTML.includes('id="work-material-revision"'));
  assert.ok(node("#source-content").innerHTML.includes("&lt;/textarea&gt;&lt;script&gt;保留的原文"));
  assert.ok(!node("#source-content").innerHTML.includes("<script>"));
  await vm.runInContext(`loadPublicDocumentHistory("${second}")`,context);
  assert.ok(node("#public-history-list").innerHTML.includes("第 1 版"));
  assert.ok(node("#public-history-list").innerHTML.includes("第 2 版"));
  assert.ok(node("#public-history-list").innerHTML.includes("加入新研究范围"));
  context.comparison={earlier:context.docs[first],later:context.docs[second],change_kind:"extraction_changed",notice:"不是外部业务变化",complete:false,metadata_changes:{title:{earlier:"<script>旧</script>",later:"新版"}},diff:"--- earlier\n+++ later\n@@ -1 +1 @@\n-<script>旧文本</script>\n+新文本\n"};
  const html=vm.runInContext("renderPublicDocumentComparison(comparison)",context);
  assert.ok(html.includes("同一原始文件的文本提取结果变化"));
  assert.ok(html.includes("不是完整差异"));
  assert.ok(html.includes("&lt;script&gt;旧文本&lt;/script&gt;"));
  assert.ok(html.includes("新增内容")&&html.includes("删除内容"));
  assert.ok(!html.includes("@@ -1")&&!html.includes("--- earlier"));
  vm.runInContext(`selectResearchDocument("${second}","合成新版")`,context);
  await vm.runInContext(`saveWorkMaterialRevision("${second}","合成再修订","\\n新版原文。\\n","明确出处")`,context);
  const request=JSON.parse(context.calls.find(row=>row.options).options.body);
  assert.equal(request.text,"\n新版原文。\n");
  assert.equal(request.source_name,"明确出处");
  assert.ok(node("#public-version-status").textContent.includes("新版本已保存"));
  const selected=vm.runInContext("[...selectedResearchDocuments.keys()]",context);
  assert.deepEqual(Array.from(selected),[second]); // Saving does not silently change research scope.
  assert.ok(context.calls.every(row=>!row.path.endsWith("/run")&&!row.path.startsWith("projects")));
  const displayed=node("#source-content").innerHTML;
  vm.runInContext('api=async()=>{throw new Error("已有新版本，请刷新");}',context);
  await assert.rejects(vm.runInContext(`saveWorkMaterialRevision("${third}","草稿","未保存内容","原出处")`,context),/已有新版本/);
  assert.equal(node("#source-content").innerHTML,displayed); // Failed submission leaves the editor untouched.
  vm.runInContext('materialRevisionDrafts.set(state.currentPublicDocument.url,{title:"保留的标题",source_name:"保留出处",text:"未保存的修订草稿<script>"});globalThis.retained=renderPublicVersionTools(state.currentPublicDocument)',context);
  assert.ok(context.retained.includes("未保存的修订草稿&lt;script&gt;"));
  assert.ok(context.retained.includes("已保留未保存的修订草稿"));
})().catch(error=>{console.error(error);process.exitCode=1;});

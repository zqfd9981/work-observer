// Execute production UI functions against a minimal DOM dependency, not a mirror renderer.
const fs = require("node:fs"), vm = require("node:vm"), assert = require("node:assert/strict");
const nodes = new Map();
const node = selector => {
  if (!nodes.has(selector)) nodes.set(selector,{value:"",checked:false,disabled:false,hidden:false,content:"synthetic-token",listeners:{},querySelector:node,querySelectorAll:()=>[],addEventListener(name,callback){this.listeners[name]=callback;}});
  return nodes.get(selector);
};
const context = {document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:""},URL,console,setTimeout,clearTimeout,Intl};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2],"utf8"),context);
context.fixture = JSON.parse(fs.readFileSync(process.argv[3],"utf8"));
vm.runInContext("globalThis.orphanNotes=renderClaimAnalysisNotes({claims:[],source_binding_check:{analysis_notes:[{index:0,notice:'draft'}]}},0);globalThis.invalidNotes=renderClaimAnalysisNotes({claims:[{}],analysis_notes:[true,false,'0',null,-1,1,0.5].map(index=>({index,notice:'invalid'}))},0)",context);
assert.equal(context.orphanNotes,"");
assert.equal(context.invalidNotes,"");
node("#research-approach").value="source_first";
node("#allow-public").checked=true;
vm.runInContext("updateResearchApproach()",context);
assert.equal(node("#allow-public").checked,false);
assert.equal(node("#allow-public").disabled,true);
assert.equal(node("#research-approach-note").hidden,false);
node("#research-approach").value="standard";
vm.runInContext("updateResearchApproach()",context);
assert.equal(node("#allow-public").disabled,false);
assert.equal(node("#research-approach-note").hidden,true);
context.target={innerHTML:""};
vm.runInContext("renderResult(fixture,target)",context);
assert.ok(context.target.innerHTML.indexOf("原文分项记录") < context.target.innerHTML.indexOf("判断（模型分析）"));
assert.ok(context.target.innerHTML.includes("搭建 &lt;script&gt;平台&lt;/script&gt;。"));
assert.ok(context.target.innerHTML.includes("已读归档正文中未披露（待核实）"));
assert.ok(context.target.innerHTML.includes("尚不能判断（待核实）"));
assert.ok(context.target.innerHTML.includes("data-cite-start="));
assert.ok(context.target.innerHTML.includes("F1 → F2"));
const isV2=Object.hasOwn(context.fixture.claims[0],"bindings");
const hasAnalysisNotes=(context.fixture.analysis_notes || context.fixture.source_binding_check?.analysis_notes || []).length > 0;
if(hasAnalysisNotes){
  assert.ok(context.target.innerHTML.includes("多维分析提示 · 仍须语义核对"));
  assert.ok(context.target.innerHTML.includes("不表示同口径单维可比，也不表示语义通过"));
  assert.ok(context.target.innerHTML.includes("synthetic-peer-job"));
  assert.ok(context.target.innerHTML.includes("团队协作"));
  vm.runInContext("globalThis.otherClaimNotes=renderClaimAnalysisNotes(fixture,1)",context);
  assert.equal(context.otherClaimNotes,"");
}
if(isV2){
  assert.ok(context.target.innerHTML.includes("主体：招聘岗位承担者"));
  assert.ok(context.target.innerHTML.includes("主体：团队"));
  assert.ok(context.target.innerHTML.includes("执行安全与技术隔离"));
  assert.ok(context.target.innerHTML.includes("原文明示的独立子任务"));
  assert.ok(context.target.innerHTML.includes("更正后维度：岗位建设与工作任务"));
  assert.ok(context.target.innerHTML.includes("已声明的支持子集"));
  assert.ok(context.target.innerHTML.includes("熟悉容器化、消息队列、任务调度系统者优先；"));
  assert.ok(context.target.innerHTML.includes("&lt;em&gt;完整上下文&lt;/em&gt;"));
  context.unsafeRow={actor:"<img src=x>",facet:"<script>维度</script>",state:"unresolved",id:"unsafe",job_id:context.fixture.scope.jobs[0].id};
  vm.runInContext("globalThis.unsafeHtml=renderReviewFindings({source_findings:[unsafeRow]})",context);
  assert.ok(context.unsafeHtml.includes("&lt;img src=x&gt;"));
  assert.ok(context.unsafeHtml.includes("&lt;script&gt;维度&lt;/script&gt;"));
  assert.ok(!context.unsafeHtml.includes("<img src=x>"));
  vm.runInContext("globalThis.operatorHtml=renderFindingActor({actor:'human_operator'});globalThis.agentHtml=renderFindingActor({actor:'agent'})",context);
  assert.ok(context.operatorHtml.includes("人工操作角色"));
  assert.ok(!context.operatorHtml.includes("招聘岗位承担者"));
  assert.ok(context.agentHtml.includes("Agent"));
} else assert.ok(!context.target.innerHTML.includes("主体："));
vm.runInContext("renderProgress({id:'synthetic',state:'failed',error_code:'RESEARCH_METHOD_CHANGED_NEW_RUN_REQUIRED'})",context);
assert.ok(node("#research-output").innerHTML.includes("不能混用新旧方法"));
vm.runInContext("renderProgress({id:'synthetic',state:'failed',error_code:'SOURCE_FIRST_LOCAL_JD_ONLY'})",context);
assert.ok(node("#research-output").innerHTML.includes("只使用本地岗位正文"));
const cite=context.fixture.source_findings[1].citations[0], ev=context.fixture.evidence[0];
const quote={textContent:ev.quote,innerHTML:""};
context.details={dataset:{evidenceStart:String(ev.start)},querySelector:()=>quote};
context.cite=cite;
vm.runInContext("highlightCitation(details,cite.start,cite.end)",context);
assert.ok(quote.innerHTML.includes("<mark>搭建 &lt;script&gt;平台&lt;/script&gt;。</mark>"));
// Backend review packets omit active; no method/old-score metadata is rendered by the shared view.
context.packet = {...context.fixture,source_findings:context.fixture.source_findings.filter(row=>row.active).map(({active,...row})=>row),
  ...(isV2?{source_finding_history:context.fixture.source_findings.filter(row=>!row.active)}:{}),
  approach:"DO_NOT_SHOW_APPROACH",method_sha256:"DO_NOT_SHOW_METHOD",reviews:[],notice:"Synthetic review packet",usage:{},approve_allowed:false,
  frozen_sources:[{job_id:context.fixture.scope.jobs[0].id,title:"合成冻结来源标题",text:"合成完整正文",data_kind:"synthetic"}],
  completion_criteria:[],claims:context.fixture.claims.map((claim,index)=>({...claim,index,citations:context.fixture.evidence}))};
vm.runInContext("globalThis.reviewHtml=renderReviewFindings(packet)",context);
assert.ok(context.reviewHtml.includes("合成建设岗位"));
assert.ok(context.reviewHtml.includes("搭建 &lt;script&gt;平台&lt;/script&gt;。"));
assert.ok(context.reviewHtml.includes("个人编码分工"));
assert.ok(context.reviewHtml.includes("流程中的人或Agent不自动等于应聘者"));
assert.ok(context.reviewHtml.includes("不等于没有该职责"));
assert.ok(!context.reviewHtml.includes("data-cite"));
assert.ok(!context.reviewHtml.includes("DO_NOT_SHOW"));
if(hasAnalysisNotes){
  assert.ok(context.reviewHtml.includes("多维分析提示 · 仍须语义核对"));
  assert.ok(context.reviewHtml.includes("synthetic-peer-job"));
}
if(isV2){
  assert.ok(context.reviewHtml.includes("主体：招聘岗位承担者"));
  assert.ok(context.reviewHtml.includes("F1 → F2"));
  assert.ok(context.reviewHtml.includes("原登记需纠正"));
  assert.ok(context.reviewHtml.includes("熟悉容器化、消息队列、任务调度系统者优先；"));
  assert.ok(context.reviewHtml.includes("原文明示的独立子任务"));
  assert.ok(context.reviewHtml.includes("执行安全与技术隔离"));
}
vm.runInContext("globalThis.fallbackHtml=renderReviewFindings({...packet,scope:undefined})",context);
assert.ok(context.fallbackHtml.includes("合成冻结来源标题"));
vm.runInContext("globalThis.citationTitleHtml=renderReviewFindings({...packet,scope:undefined,frozen_sources:[]})",context);
assert.ok(context.citationTitleHtml.includes("合成建设岗位"));
node("#research-approach").value="source_first";
node("#question").value="Synthetic submit";
node("#offline").checked=true;
vm.runInContext("api=async(path,options)=>{globalThis.sent=JSON.parse(options.body);return {id:'synthetic'};};pendingResearch=()=>{}",context);
(async()=>{
  await vm.runInContext("startResearch({preventDefault(){}})",context);
  assert.equal(context.sent.approach,"source_first");
  assert.equal(context.sent.allow_public,false);
  assert.equal(context.sent.offline,true);
  vm.runInContext("api=async()=>packet",context);
  const directory=require("node:path").dirname(process.argv[2]);
  vm.runInContext(fs.readFileSync(require("node:path").join(directory,"quality.js"),"utf8"),context);
  await vm.runInContext("openQuality('synthetic')",context);
  const quality=node("#quality-detail").innerHTML;
  assert.ok(quality.indexOf("原文分项记录") < quality.indexOf("逐条判断与原文"));
  assert.ok(quality.includes("个人编码分工"));
  if(isV2){assert.ok(quality.includes("已声明的支持子集"));assert.ok(quality.includes("主体：系统"));}
  if(hasAnalysisNotes){assert.ok(quality.includes("多维分析提示"));assert.ok(quality.includes("synthetic-peer-job"));}
  vm.runInContext(fs.readFileSync(require("node:path").join(directory,"research-benchmarks.js"),"utf8"),context);
  await node("#page-research-benchmarks").listeners.click({target:{closest:()=>({dataset:{benchPacket:"synthetic"}})}});
  const blind=node("#bench-packet").innerHTML;
  assert.ok(blind.indexOf("原文分项记录") < blind.indexOf("冻结原文全文"));
  assert.ok(blind.includes("个人编码分工"));
  assert.ok(!blind.includes("DO_NOT_SHOW"));
  if(isV2){assert.ok(blind.includes("已声明的支持子集"));assert.ok(blind.includes("系统者优先；"));assert.ok(blind.includes("主体：系统"));}
  if(hasAnalysisNotes){assert.ok(blind.includes("多维分析提示"));assert.ok(blind.includes("不表示语义通过"));}
})().catch(error=>{console.error(error);process.exitCode=1;});

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
  vm.runInContext(fs.readFileSync(require("node:path").join(directory,"research-benchmarks.js"),"utf8"),context);
  await node("#page-research-benchmarks").listeners.click({target:{closest:()=>({dataset:{benchPacket:"synthetic"}})}});
  const blind=node("#bench-packet").innerHTML;
  assert.ok(blind.indexOf("原文分项记录") < blind.indexOf("冻结原文全文"));
  assert.ok(blind.includes("个人编码分工"));
  assert.ok(!blind.includes("DO_NOT_SHOW"));
})().catch(error=>{console.error(error);process.exitCode=1;});

// Synthetic frozen metadata is identification context, not verified affiliation or JD text.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const nodes=new Map();
const node=selector=>{
  if(!nodes.has(selector))nodes.set(selector,{listeners:{},querySelector:node,querySelectorAll:()=>[],addEventListener(name,fn){this.listeners[name]=fn;}});
  return nodes.get(selector);
};
const context={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:""},URL,console,setTimeout,clearTimeout,Intl};
vm.createContext(context);
const app=process.argv[2],assets=path.dirname(app);
vm.runInContext(fs.readFileSync(app,"utf8"),context);
context.packet={question:"合成标准回答",notice:"合成匿名核对",claims:[{index:0,text:"合成判断",citations:[]}],gaps:[],reviews:[],usage:{},approve_allowed:false,completion_criteria:[],frozen_sources:[],
  method_sha256:"DO_NOT_SHOW_METHOD",arm:"DO_NOT_SHOW_ARM",old_score:"DO_NOT_SHOW_SCORE",
  scope_context:{notice:"不是JD逐字内容；不证明组织隶属、公司整体业务或当前招聘。<script>标识提示</script>",method_sha256:"DO_NOT_SHOW_SCOPE_METHOD",jobs:[
    {job_id:"job-1",title:"<b>合成标准岗位</b>",company_name_raw:"<img src=x onerror=alert(1)>",company_identity_status:"source_id",snapshot_id:"snapshot-1",layer:"frozen_job_metadata",unexpected:"DO_NOT_SHOW_EXTRA"},
    {job_id:"job-2",title:"未知公司岗位",company_name_raw:null,company_identity_status:"unknown",snapshot_id:"snapshot-2",layer:"frozen_job_metadata"},
    {job_id:"job-3",title:"未核实岗位",company_name_raw:"合成公司",company_identity_status:"unverified",snapshot_id:"snapshot-3",layer:"frozen_job_metadata"},
    {job_id:"job-other",title:"DO_NOT_SHOW_OTHER_LAYER",company_identity_status:"verified",layer:"unexpected_layer"},
  ]}};
vm.runInContext("globalThis.scopeHtml=renderReviewFindings(packet);globalThis.legacyHtml=renderReviewFindings({...packet,scope_context:undefined})",context);
function check(html){
  assert.ok(html.includes("冻结岗位标识（不是JD逐字内容）"));
  assert.ok(html.includes("&lt;b&gt;合成标准岗位&lt;/b&gt;"));
  assert.ok(html.includes("&lt;img src=x onerror=alert(1)&gt;"));
  assert.ok(html.includes("&lt;script&gt;标识提示&lt;/script&gt;"));
  assert.ok(!html.includes("<script>标识提示</script>"));
  assert.ok(html.includes("有来源公司编号（身份仍待核）"));
  assert.ok(html.includes("待核（未知）") && html.includes("待核（未核实）"));
  assert.ok(html.includes("公司名称待核"));
  assert.ok(html.includes("不证明岗位隶属或当前招聘状态"));
  assert.ok(html.includes("<details><summary>查看冻结标识与版本"));
  assert.ok(html.includes("snapshot-1"));
  assert.ok(!html.includes("DO_NOT_SHOW"));
  assert.ok(!html.includes("已验证"));
  assert.ok(!html.includes("原文分项记录"));
}
check(context.scopeHtml);
assert.equal(context.legacyHtml,"");
vm.runInContext("api=async()=>packet",context);
(async()=>{
  vm.runInContext(fs.readFileSync(path.join(assets,"quality.js"),"utf8"),context);
  await vm.runInContext("openQuality('synthetic-standard')",context);
  check(node("#quality-detail").innerHTML);
  vm.runInContext(fs.readFileSync(path.join(assets,"research-benchmarks.js"),"utf8"),context);
  await node("#page-research-benchmarks").listeners.click({target:{closest:()=>({dataset:{benchPacket:"opaque-standard"}})}});
  check(node("#bench-packet").innerHTML);
})().catch(error=>{console.error(error);process.exitCode=1;});

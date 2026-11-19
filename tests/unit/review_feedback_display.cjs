// Exercise the production submit handler with a synthetic DOM; no browser or network.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const nodes=new Map(),handlers={};
const node=selector=>{
  if(!nodes.has(selector)) nodes.set(selector,{listeners:{},querySelector:node,querySelectorAll:()=>[],addEventListener(name,fn){this.listeners[name]=fn;}});
  return nodes.get(selector);
};
const context={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(name,fn){(handlers[name]??=[]).push(fn);}},window:{addEventListener(){}},location:{hash:""},URL,console,setTimeout,clearTimeout,Intl};
vm.createContext(context);
const app=process.argv[2];
vm.runInContext(fs.readFileSync(app,"utf8"),context);
vm.runInContext(fs.readFileSync(path.join(path.dirname(app),"quality.js"),"utf8"),context);
context.packet={question:"合成问题",claims:[],gaps:[],reviews:[],usage:{},repair:{available:true,notice:"<script>合成提示</script>",question:"合成问题",job_ids:["a".repeat(32)],filters:{city:null},review_run_id:"b".repeat(32),review_id:"c".repeat(32),previous_model_calls:6}};
context.calls=[];context.opened=[];context.notices=[];
vm.runInContext('api=async(route,options)=>{calls.push({route,options});return options?{id:"new-run"}:packet;};openRun=async id=>opened.push(id);notify=(message,error)=>notices.push({message,error})',context);
(async()=>{
  await vm.runInContext('openQuality("original")',context);
  assert.equal(context.calls.length,1); // Reading review never starts research.
  const html=node("#quality-detail").innerHTML;
  assert.ok(html.includes("预算另计")&&html.includes("前次已调用 6 次"));
  assert.ok(html.includes("&lt;script&gt;合成提示&lt;/script&gt;")&&!html.includes("<script>合成提示</script>"));
  const button={disabled:false},event={target:{id:"quality-repair",closest:()=>null,elements:{max_calls:{value:"5"},timeout:{value:"120"},offline:{checked:true}},querySelector:()=>button},preventDefault(){}};
  for(const handler of handlers.submit) await handler(event);
  const sent=context.calls.find(row=>row.route==="research");
  const payload=JSON.parse(sent.options.body);
  assert.equal(payload.review_id,context.packet.repair.review_id);
  assert.equal(payload.review_run_id,context.packet.repair.review_run_id);
  assert.deepEqual(payload.job_ids,["a".repeat(32)]);
  assert.equal(payload.question,"合成问题");
  assert.equal(payload.allow_public,false);assert.equal(payload.approach,"standard");
  assert.equal(payload.max_calls,5);assert.equal(payload.timeout,120);assert.equal(payload.offline,true);
  assert.deepEqual(Array.from(context.opened),["new-run"]);
  assert.equal(context.location.hash,"#research");
  context.result={review_feedback:{reviewer_kind:"agent_assisted",run_id:"b".repeat(32),review_id:"c".repeat(32),note:"<img src=x onerror=alert(1)>",dimensions:{x:{reason:"<b>缺口</b>"}},claim_issues:[{index:0,note:"<script>范围</script>"}],omitted_claim_reviews:9}};
  const feedback=vm.runInContext("renderReviewFeedback(result)",context);
  assert.ok(feedback.includes("Agent辅助复核，非人审")&&feedback.includes("另有 9 条复核"));
  assert.ok(feedback.includes("&lt;img")&&feedback.includes("&lt;script&gt;范围"));
  assert.ok(!feedback.includes("<img")&&!feedback.includes("<script>"));
  assert.equal(vm.runInContext("renderReviewFeedback({})",context),"");
})().catch(error=>{console.error(error);process.exitCode=1;});

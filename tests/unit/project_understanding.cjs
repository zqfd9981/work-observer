// One reopened research flow: revision, evidence, follow-up and knowledge candidate.
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const node=()=>({querySelector:node,querySelectorAll:()=>[],addEventListener(){}});
const context={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:""},URL,console,setTimeout,clearTimeout,Intl};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[2],"utf8"),context);
const evidence={id:"e1",title:"合成原文",quote:"<script>接口开发，与平台协作</script>",document_id:"document",snapshot_id:"snapshot",start:0,end:16};
const claim=text=>({text,category:"responsibility",basis:"inference",requirement:"unspecified",evidence_ids:["e1"]});
const step=(id,text)=>({id,run_id:id,scope_version:1,state:"waiting_review",question:"合成"+id,result:{status:"completed",audit:{},claims:[claim(text)],evidence:[evidence],business_review:{status:"pending"},gaps:["如何核实实际上线权限？"]}});
const first=step("first","个人可能独立上线"),second=step("second","接口协作不能证明独立上线权限");
second.result.cognition_revisions=[{previous_run_id:"first",previous_claim_index:0,previous_statement:first.result.claims[0].text,decision:"revise",new_statements:[second.result.claims[0].text],new_claim_indices:[0],reason:"重读协作原文",evidence_relation:"reread"}];
const failed={id:"failed",run_id:"failed",scope_version:1,state:"failed",question:"未完成的补查",result:{status:"incomplete",audit:{},claims:[]}};
context.project={id:"project",state:"active",scope_version:1,steps:[first,second,failed]};
const original=JSON.stringify(context.project);
let view=vm.runInContext("projectUnderstanding(project)",context);
assert.deepEqual(Array.from(view.claims,x=>x.claim.text),[second.result.claims[0].text]);
assert.equal(view.changes[0].revision.previous_statement,first.result.claims[0].text);
assert.equal(view.excluded[0].step.id,"failed");
const html=vm.runInContext("renderProjectUnderstanding(project)",context);
assert.ok(html.includes("本研究当前认识")&&html.includes("没有自动采纳为知识"));
assert.ok(html.includes('data-open-run="first"')&&html.includes('data-open-run="second"'));
assert.ok(html.includes('data-reply-step="second"')&&html.includes('data-knowledge-run="second"'));
assert.ok(html.includes('data-source="document"')&&html.includes("如何核实实际上线权限"));
assert.ok(html.includes("&lt;script&gt;接口开发")&&!html.includes("<script>"));
assert.ok(!html.includes("人工核对通过"));
assert.equal(JSON.stringify(context.project),original); // Reopening never changes adoption or results.
context.knowledge=[{id:"saved",source_run_id:"second",content:second.result.claims[0].text,status:"active",scope:"job",validity:{eligible:true}}];
let savedHtml=vm.runInContext("renderProjectUnderstanding(project,knowledge)",context);
assert.ok(savedHtml.includes("已采纳为岗位知识"));
assert.ok(!savedHtml.includes('data-knowledge-run="second"'));
assert.ok(savedHtml.includes('href="#memory"'));
context.knowledge[0].status="withdrawn";
savedHtml=vm.runInContext("renderProjectUnderstanding(project,knowledge)",context);
assert.ok(savedHtml.includes("知识已撤回")&&!savedHtml.includes('data-knowledge-run="second"'));
second.result.business_review.status="rejected";
view=vm.runInContext("projectUnderstanding(project)",context);
assert.deepEqual(Array.from(view.claims,x=>x.claim.text),[first.result.claims[0].text]);
assert.equal(view.changes.length,0); // A rejected revision cannot hide the previous statement.
first.result.audit.stale_memory=true;
assert.equal(vm.runInContext("projectUnderstanding(project).claims.length",context),0);
first.result.audit={};second.result.business_review.status="pending";
context.project.scope_version=2;
assert.equal(vm.runInContext("projectUnderstanding(project).claims.length",context),0);
assert.ok(vm.runInContext("renderProjectUnderstanding(project)",context).includes("研究范围已调整"));
console.log("Reopened research: current understanding, revision, citations and reuse path passed.");

context.timeEvidence={historical_cutoffs:["2026-11-17T23:59:59+00:00","2026-11-19T16:36:05+00:00"]};
const historyNote=vm.runInContext("historicalEvidenceNote(timeEvidence)",context);
assert.ok(historyNote.includes("历史原文读取截止")&&historyNote.includes("不是网站发布时间"));
assert.ok(historyNote.includes("2026")&&historyNote.includes("；"));
assert.equal(vm.runInContext("historicalEvidenceNote({})",context),"");
context.timeEvidence.historical_cutoffs=["<script>unsafe</script>"];
assert.ok(!vm.runInContext("historicalEvidenceNote(timeEvidence)",context).includes("<script>"));

context.project.scope_version=1;
evidence.historical_cutoffs=["2026-11-17T23:59:59+00:00"];
const datedUnderstanding=vm.runInContext("renderProjectUnderstanding(project)",context);
assert.ok(datedUnderstanding.includes("含历史时点依据"));
assert.ok(datedUnderstanding.includes("历史原文读取截止"));
assert.ok(datedUnderstanding.includes('data-reply-step="second"'));
assert.ok(!datedUnderstanding.includes("人工核对通过"));

second.result.cognition_revisions[0].previous_scope_version=1;
second.result.cognition_revisions[0].current_scope_version=2;
assert.ok(vm.runInContext("renderProjectUnderstanding(project)",context).includes("研究范围或目标已经调整"));
assert.equal(vm.runInContext("renderRevisionScope({})",context),"");

second.result.upstream_revision_notices={items:[{previous_run_id:"ancestor",run_id:"correction",decision:"withdraw",reason:"<script>边界已改变</script>"}],omitted:1,notice:"依赖只记录到研究轮次，不能断定每条判断错误。"};
const affectedHtml=vm.runInContext("renderProjectUnderstanding(project)",context);
assert.ok(affectedHtml.includes("第 2 轮研究需要回看其沿用依据"));
assert.ok(affectedHtml.includes('data-open-run="ancestor"')&&affectedHtml.includes('data-open-run="correction"'));
assert.ok(affectedHtml.includes("&lt;script&gt;边界已改变&lt;/script&gt;")&&!affectedHtml.includes("<script>"));
assert.ok(affectedHtml.includes("不能断定每条判断错误")&&affectedHtml.includes("另有 1 条相关意见"));
second.result.upstream_revision_notices.items.push({previous_run_id:"ancestor",run_id:"retention",decision:"retain",reason:"重新确认任务，权限仍未知"});
const retainedHtml=vm.runInContext("renderProjectUnderstanding(project)",context);
assert.ok(retainedHtml.includes("重新保留：重新确认任务，权限仍未知"));
assert.ok(retainedHtml.includes('data-open-run="correction"')&&retainedHtml.includes('data-open-run="retention"'));

// Partial rechecks expose the exact unreviewed work, then a later full recheck clears it.
const partial=second.result.cognition_revisions[0];
partial.decision="unresolved";
partial.evidence_ids=["e1"];
partial.aspects=[{previous_excerpt:"个人",decision:"retain",new_claim_indices:[0],new_statements:[second.result.claims[0].text],evidence_ids:["e1"],reason:"仅确认任务主体"},
 {previous_excerpt:"独立上线",decision:"unresolved",new_claim_indices:[],new_statements:[],evidence_ids:["e1"],reason:"<script>尚缺权限依据</script>"}];
view=vm.runInContext("projectUnderstanding(project)",context);
assert.ok(view.claims.find(row=>row.step.id==="first").unresolved);
assert.ok(view.questions.some(row=>row.text.includes("独立上线")&&row.step.id==="second"));
const partialHtml=vm.runInContext("renderProjectUnderstanding(project)",context);
assert.ok(partialHtml.includes("仍待核实的具体内容")&&partialHtml.includes("旧内容：独立上线"));
assert.ok(partialHtml.includes("&lt;script&gt;尚缺权限依据&lt;/script&gt;")&&!partialHtml.includes("<script>"));
const exportPartial=vm.runInContext("projectDossierMarkdown(project)",context);
assert.ok(exportPartial.includes("仍待核实的旧内容：独立上线")&&exportPartial.includes("原文依据：[E"));
const latest=step("third","已按资料重新核对旧解释");
latest.result.cognition_revisions=[{...partial,decision:"revise",aspects:[{...partial.aspects[1],decision:"revise",new_claim_indices:[0],new_statements:[latest.result.claims[0].text],reason:"原文只能支持协作任务"}]}];
context.project.steps.push(latest);
view=vm.runInContext("projectUnderstanding(project)",context);
assert.ok(!view.claims.some(row=>row.step.id==="first"));
assert.ok(!view.questions.some(row=>row.text.includes("尚缺权限依据")));
assert.equal(view.changes.length,2); // Old uncertainty is still in the historical change log.

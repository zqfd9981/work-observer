// New investigation output remains readable, source-aware and escaped; old records still render.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const node=()=>({value:'',addEventListener(){},querySelector:node,querySelectorAll:()=>[]});
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:''},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('src/work_observer/api/assets/app.js','utf8'),ctx);
const source=fs.readFileSync('src/work_observer/api/assets/career.js','utf8').replace(/\}\)\(\);\s*$/,'window.adaptiveTest={investigationPanel,researchActivityItems,isInterviewSource,interviewQuestions};})();');
vm.runInContext(source,ctx);
const api=ctx.window.adaptiveTest;
assert.equal(api.investigationPanel({result:{claims:[]}}),'');
const row={result:{investigation:{original_question:'<script>这工作是啥</script>',tasks:[{
 intent:'compare',question:'两份工作差在哪',completion:'保留两侧限制',retried:true,
 retrieval_status:'comparison_needs_other_source',attempts:[{stage:'primary',channel:'work',terms:['工作任务'],candidates:0,reason:'换成资料表述'},{stage:'retry',channel:'personal',terms:['<img src=x>'],candidates:1,reason:'自述仅支持原话'}]
}],outcomes:[{task_index:0,status:'partial',answer:'资料只支持一侧\n仍需另一份依据',claim_indices:[0]}],missing_context:['另一份JD'],engine:'langgraph'},trace:[{tool:'plan_investigation',questions:['两份工作差在哪'],retrieval_attempts:[{},{}],replanned:true}]}};
const html=api.investigationPanel(row);
assert.match(html,/对照差异/);assert.match(html,/部分回答/);assert.match(html,/查看查询与补查/);
assert.match(html,/个人自述/);assert.match(html,/缺少另一份工作来源/);assert.match(html,/另一份JD/);
assert.match(html,/&lt;script&gt;/);assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<script>|<img/);
assert.match(api.researchActivityItems(row,{} )[0].detail,/调整调查.*2 组本地查询/);
console.log('Adaptive tasks, partial answers, retry queries, personal source labels and escaped text render; old results need no new fields.');
const interview={kind:'ask',result:{interview_questions:['具体做了什么？'],gaps:['其他未知？']}};
assert.equal(api.isInterviewSource(interview),true);
assert.deepEqual(Array.from(api.interviewQuestions(interview)),['具体做了什么？']);
row.result.investigation.constraints=[{field:'city',value:'上海',source_text:'只看上海'}];
row.result.investigation.effective_scope={job_ids:['first']};
row.result.investigation.scope_unknown_job_ids=['unknown'];
row.result.investigation.tasks[0].source_coverage=[{id:'second',label:'另一个选定岗位',included:false}];
row.result.investigation.tasks[0].attempts[0].required_terms=['记忆'];
const focused=api.investigationPanel(row);
assert.match(focused,/城市 · 上海/);assert.match(focused,/1 个岗位的相关条件未知/);
assert.match(focused,/另一个选定岗位：尚缺对应原文/);assert.match(focused,/须包含主题：记忆/);
row.result.project_id='goal';row.result.investigation.memory_recall={records:[{kind:'understanding',record_id:'old-note',query_terms:['idempotency_key'],preview:{current_view_preview:'<script>旧理解</script>',preview_is_partial:true}}],omitted_count:2};
const memory=api.investigationPanel(row);
assert.match(memory,/本次问题找回的旧线索/);assert.match(memory,/#career\/goal\/insight\/old-note/);
assert.match(memory,/&lt;script&gt;旧理解/);assert.doesNotMatch(memory,/<script>/);

const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const node=()=>({value:'',addEventListener(){},querySelector:node,querySelectorAll:()=>[]});
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:''},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('src/work_observer/api/assets/app.js','utf8'),ctx);
vm.runInContext(fs.readFileSync('src/work_observer/api/assets/career.js','utf8').replace(/\}\)\(\);\s*$/,
  'window.contextLabTest={contextProbeRecall,calculationRecords,sourceCalculationRecall,calculationInsightDraft,interviewFocusPanel,chooseInterviewFocus,contextReplayDraft,contextTaskRun,contextProbeDraft,contextSideInputs,contextLabValues,contextLabResult,contextLab,setup:(data,draft={})=>{career.id=data.id;career.data=data;career.drafts.set(data.id,draft);}};})();'),ctx);
const api=ctx.window.contextLabTest;
api.setup({id:'goal',questions:[],requirements:[],results:[]});
const fields={requirement_key:'run:3',question_id:'',source_step_id:'source',source_probe_index:'0',hypothesis:'只作为预期',data_kind:'synthetic'};
const elements=Object.fromEntries(Object.entries(fields).map(([key,value])=>[key,{value}]));
const record=(name,edge,cloud,include=true)=>({
  querySelector:selector=>selector.includes('include_case')?{checked:include}:{value:name},
  querySelectorAll:selector=>(selector.includes('edge')?edge:cloud).map(row=>({querySelector:key=>({value:key.includes('key')?row.key:row.value})})),
});
const values=api.contextLabValues({elements,querySelectorAll:()=>[
  record('纳入',[{key:'a|b\n第二行',value:'端侧\n内容 | 保留'}],[{key:'a',value:'云侧'}]),
  record('不纳入',[{key:'b',value:'不应出现'}],[],false),
]});
assert.equal(values.question_id,null);assert.equal(values.requirement_key,'run:3');assert.equal(values.cases.length,1);
assert.equal(values.source_step_id,'source');assert.equal(values.source_probe_index,0);
assert.equal(values.cases[0].edge[0].key,'a|b\n第二行');assert.equal(values.cases[0].edge[0].value,'端侧\n内容 | 保留');assert.equal(values.cases[0].cloud[0].value,'云侧');
const editor=api.contextSideInputs([{key:'a|b\n第二行',value:'<内容>\n保留'}],'edge',0);
assert.match(editor,/data-context-key/);assert.match(editor,/a\|b\n第二行/);assert.match(editor,/&lt;内容&gt;\n保留/);
assert.match(editor,/data-context-add-row="0:edge"/);assert.match(editor,/data-context-remove-row="0:edge:0"/);
const view=api.contextLab({id:'goal',questions:[],requirements:[],results:[]});
assert.match(view,/id="career-context-form"/);assert.match(view,/不调用模型或网络/);assert.match(view,/不推定缺失就是删除/);
const output=api.contextLabResult({outcome:'本机构造输入',conditions:'不判断新旧',cases:[{name:'合成冲突',appended:[{key:'<script>',value:'<img>',side:'edge',position:1}],folded_copies:0,conflicting_keys:['<script>'],one_sided_keys:['<script>'],merged:[{key:'<script>',status:'conflict',variants:[{value:'<img>',origins:[{side:'edge',position:1}]}]}]}]},'goal','saved');
assert.match(output,/冲突，未自动选择内容/);assert.match(output,/来源：端侧第1条/);assert.match(output,/#career\/goal\/task\/saved/);
assert.match(output,/&lt;script&gt;/);assert.match(output,/&lt;img&gt;/);assert.doesNotMatch(output,/<script>|<img>/);
console.log('Context inputs keep explicit identities, excluded cases stay excluded, and outputs preserve conflicts and origins safely.');

const oldRun={hypothesis:'保存时的原预期',data_kind:'synthetic',conditions:'原条件',outcome:'原计算输出',cases:[{name:'原输入组',input:{edge:[{key:'m1',value:'内容里有 | 分隔符'}],cloud:[]},appended:[{key:'m1',value:'内容里有 | 分隔符',side:'edge',position:1}],folded_copies:0,conflicting_keys:[],one_sided_keys:['m1'],merged:[{key:'m1',status:'one_side_only',variants:[{value:'内容里有 | 分隔符',origins:[{side:'edge',position:1}]}]}]}]};
const savedTask={id:'parent',local_experiment:'context_merge',question_id:'question',target_requirement:{key:'old-run:3'},hypothesis:'后来编辑的预期',context_run:oldRun};
const replay=api.contextReplayDraft(savedTask);
assert.equal(replay.previous_task_id,'parent');assert.equal(replay.question_id,'question');assert.equal(replay.requirement_key,'');
assert.equal(replay.target_requirement.key,'old-run:3');assert.equal(replay.hypothesis,'保存时的原预期');assert.equal(replay.result,null);
assert.equal(replay.cases[0].edge[0].value,'内容里有 | 分隔符');
replay.cases[0].edge[0].value='独立修改';assert.equal(oldRun.cases[0].input.edge[0].value,'内容里有 | 分隔符');
const savedView=api.contextTaskRun(savedTask,{id:'goal'});
assert.match(savedView,/保存时的本机计算/);assert.match(savedView,/data-context-load="parent"/);assert.doesNotMatch(savedView,/后来编辑的预期/);
const multiline=JSON.parse(JSON.stringify(savedTask));multiline.context_run.cases[0].input.edge[0].value='第一行\n第二行';
assert.equal(api.contextReplayDraft(multiline).cases[0].edge[0].value,'第一行\n第二行');

const notePracticeData={id:'context-note-goal',requirements:[],stories:[],results:[],tasks:[{...savedTask,title:'原冲突练习',artifact_document_id:'parent-log'},{...savedTask,id:'child',title:'后来改条件的练习',artifact_document_id:'child-log'}],insights:[{id:'note',task_id:'parent',current_view:'冲突还不能自动决定哪份更新。',observation:'原输入保留了不同内容。',open_question:'末尾未知：时序仍未验证。',use_for_research:false}]};
api.setup(notePracticeData);api.chooseInterviewFocus('insight:note');
const notePractice=api.interviewFocusPanel(notePracticeData);
assert.match(notePractice,/认识所据实验：原冲突练习/);assert.match(notePractice,/data-public-source="parent-log"/);assert.doesNotMatch(notePractice,/data-public-source="child-log"/);assert.match(notePractice,/末尾未知：时序仍未验证/);

const probeResult={model_calls:3,status:'completed',claims:[],gaps:[],career_learning_context:{context_experiments:[oldRun]}};
const probeRecall=api.contextProbeRecall(probeResult,'goal');
assert.match(probeRecall,/本轮实际运行的上下文对照 · 1 次/);assert.match(probeRecall,/保存时的原预期/);assert.match(probeRecall,/内容里有 \| 分隔符/);
const calculationRecord=api.calculationRecords(probeResult);assert.equal(calculationRecord.context_experiments.length,1);
const historicalProbe=api.sourceCalculationRecall(calculationRecord,'goal',true);
assert.match(historicalProbe,/原讨论 · 上下文合并/);assert.match(historicalProbe,/原讨论当时的本机计算/);assert.match(historicalProbe,/<details open><summary>核对每条输入/);assert.doesNotMatch(historicalProbe,/本轮实际运行的上下文对照/);

const source={step_id:'original',question_id:'original-question',state:'done',result:{...probeResult,career_learning_context:{context_experiments:[oldRun],requirement:{key:'frozen-work',text:'原岗位工作',evidence:[]}}}};
const probeDraft=api.contextProbeDraft(source,0);
assert.equal(probeDraft.source_step_id,'original');assert.equal(probeDraft.source_probe_index,0);
assert.equal(probeDraft.question_id,'original-question');assert.equal(probeDraft.target_requirement.key,'frozen-work');
assert.equal(probeDraft.previous_task_id,null);assert.equal(probeDraft.hypothesis,oldRun.hypothesis);
probeDraft.cases[0].edge[0].value='新值';assert.equal(oldRun.cases[0].input.edge[0].value,'内容里有 | 分隔符');
assert.match(api.contextProbeRecall(source.result,'goal',false,{results:[source]}),/data-context-probe="original:0"/);
assert.doesNotMatch(api.contextProbeRecall(source.result,'goal',true,{results:[source]}),/data-context-probe/);
const interrupted={...source,result:{...source.result,status:'incomplete'}};
assert.equal(api.contextProbeDraft(interrupted,0).source_status,'incomplete');
assert.throws(()=>api.contextProbeDraft({...source,state:'abandoned'},0),/重新选择/);
const originatingTask={...savedTask,context_run:{...oldRun,context_probe_origin:{step_id:'original',probe_index:0,hypothesis:'原讨论预期<保留>',research_status:'incomplete',notice:'本次另行计算，不是招聘原文。'},design_change:'改了冲突内容'}};
const originatingView=api.contextTaskRun(originatingTask,{id:'goal'});
assert.match(originatingView,/原讨论第 1 次实际计算/);assert.match(originatingView,/#career\/goal\/discussion\/original/);
assert.match(originatingView,/原讨论预期&lt;保留&gt;/);assert.match(originatingView,/改了冲突内容/);
console.log('Inline probes carry frozen work, inquiry and exact structured inputs into a new editable run; saved results retain the original probe link.');

api.setup({id:'goal',questions:[{id:'original-question',question:'原问题'}],requirements:[],results:[source]},{context_lab:{...probeDraft,source_probe_index:'0'}});
const linkedLab=api.contextLab({id:'goal',questions:[{id:'original-question',question:'原问题'}],requirements:[],results:[source]});
assert.match(linkedLab,/name="source_probe_index" value="0"/);assert.match(linkedLab,/原讨论第 1 次实际计算/);
assert.doesNotMatch(linkedLab,/原讨论第 01 次/);assert.match(linkedLab,/name="question_id" disabled/);

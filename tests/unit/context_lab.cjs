const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const node=()=>({value:'',addEventListener(){},querySelector:node,querySelectorAll:()=>[]});
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:''},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('src/work_observer/api/assets/app.js','utf8'),ctx);
vm.runInContext(fs.readFileSync('src/work_observer/api/assets/career.js','utf8').replace(/\}\)\(\);\s*$/,
  'window.contextLabTest={interviewFocusPanel,chooseInterviewFocus,contextReplayDraft,contextTaskRun,contextRecords,contextLabValues,contextLabResult,contextLab,setup:data=>{career.id=data.id;career.data=data;career.drafts.set(data.id,{});}};})();'),ctx);
const api=ctx.window.contextLabTest;
api.setup({id:'goal',questions:[],requirements:[],results:[]});
assert.equal(api.contextRecords('m1 | 内容中有 | 分隔符','端侧')[0].value,'内容中有 | 分隔符');
assert.throws(()=>api.contextRecords('没有分隔符','端侧'),/第 1 行/);
const fields={requirement_key:'run:3',question_id:'',hypothesis:'只作为预期',data_kind:'synthetic'};
const elements=Object.fromEntries(Object.entries(fields).map(([key,value])=>[key,{value}]));
const record=(name,edge,cloud,include=true)=>({querySelector:selector=>selector.includes('include_case')?{checked:include}:{value:selector.includes('case_name')?name:selector.includes('edge_text')?edge:cloud}});
const values=api.contextLabValues({elements,querySelectorAll:()=>[record('纳入','a | 端侧','a | 云侧'),record('不纳入','b | 不应出现','',false)]});
assert.equal(values.question_id,null);assert.equal(values.requirement_key,'run:3');assert.equal(values.cases.length,1);
assert.equal(values.cases[0].edge[0].value,'端侧');assert.equal(values.cases[0].cloud[0].value,'云侧');
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
assert.equal(api.contextRecords(replay.cases[0].edge_text,'端侧')[0].value,'内容里有 | 分隔符');
const savedView=api.contextTaskRun(savedTask,{id:'goal'});
assert.match(savedView,/保存时的本机计算/);assert.match(savedView,/data-context-load="parent"/);assert.doesNotMatch(savedView,/后来编辑的预期/);
const multiline=JSON.parse(JSON.stringify(savedTask));multiline.context_run.cases[0].input.edge[0].value='第一行\n第二行';
assert.throws(()=>api.contextReplayDraft(multiline),/不能自动改写/);

const notePracticeData={id:'context-note-goal',requirements:[],stories:[],results:[],tasks:[{...savedTask,title:'原冲突练习',artifact_document_id:'parent-log'},{...savedTask,id:'child',title:'后来改条件的练习',artifact_document_id:'child-log'}],insights:[{id:'note',task_id:'parent',current_view:'冲突还不能自动决定哪份更新。',observation:'原输入保留了不同内容。',open_question:'末尾未知：时序仍未验证。',use_for_research:false}]};
api.setup(notePracticeData);api.chooseInterviewFocus('insight:note');
const notePractice=api.interviewFocusPanel(notePracticeData);
assert.match(notePractice,/认识所据实验：原冲突练习/);assert.match(notePractice,/data-public-source="parent-log"/);assert.doesNotMatch(notePractice,/data-public-source="child-log"/);assert.match(notePractice,/末尾未知：时序仍未验证/);

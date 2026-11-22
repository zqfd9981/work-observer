const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const node=()=>({value:'',addEventListener(){},querySelector:node,querySelectorAll:()=>[]});
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){},inquiryCalls:[]},location:{hash:''},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
ctx.history={pushState(_state,_title,hash){ctx.location.hash=hash;}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('src/work_observer/api/assets/app.js','utf8'),ctx);
const source=fs.readFileSync('src/work_observer/api/assets/career.js','utf8').replace(/\}\)\(\);\s*$/,
  'window.requirementInquiryTest={panel:requirementInquiryPanel,origin:questionOrigin,submit:submitRequirementInquiry,setup:data=>{career.id=data.id;career.data=data;career.drafts.set(data.id,{allow_public:true,requirement_questions:{"run:3":"保留的未发送问题"}});},mockResearch:()=>{renderDetail=()=>{};selectInvestigation=()=>true;research=async(...args)=>{window.inquiryCalls.push(args);};}};})();');
vm.runInContext(source,ctx);
const api=ctx.window.requirementInquiryTest;
const point={key:'run:3',text:'合成评估集职责'},data={id:'goal',jobs:[],materials:[],stories:[],tasks:[],insights:[],requirements:[point],results:[],questions:[{id:'old-question',question:'已保存的交付物问题',state:'open',target_requirement:{key:'run:3'}},{id:'other-question',question:'其他工作的未知',state:'open',target_requirement:{key:'other:4'}}]};
api.setup(data);
const panel=api.panel(point,data);
assert.match(panel,/id="career-requirement-inquiry"/);assert.match(panel,/value="run:3"/);
assert.match(panel,/保留的未发送问题/);assert.match(panel,/#career\/goal\/investigate\/old-question/);
assert.doesNotMatch(panel,/其他工作的未知/);
assert.match(api.origin({...data.questions[0],target_requirement:point},data),/这条调查起点的岗位工作与原文/);
const exported=api.panel(point,data,true);
assert.match(exported,/已保存的交付物问题/);assert.doesNotMatch(exported,/<form|<textarea|href=/);

(async()=>{
  const calls=[];
  ctx.api=async(path,options)=>{
    calls.push({path,body:JSON.parse(options.body)});
    return {...data,questions:[...data.questions,{id:'new-question',question:'这项工作到底交付什么？',target_requirement:point}]};
  };
  api.mockResearch();
  await api.submit({elements:{requirement_key:{value:'run:3'},question:{value:'  这项工作到底交付什么？  '}}});
  assert.equal(calls.length,1);assert.equal(calls[0].path,'career/goal/questions');
  assert.deepEqual(calls[0].body,{requirement_key:'run:3',question:'这项工作到底交付什么？'});
  assert.equal(ctx.location.hash,'#career/goal/investigate/new-question');
  assert.equal(ctx.window.inquiryCalls.length,1);
  const research=ctx.window.inquiryCalls[0];
  assert.equal(research[0],'ask');assert.equal(research[5],'这项工作到底交付什么？');
  assert.equal(research[6].question_id,'new-question');assert.equal(research[6].allow_public,false);
  assert.doesNotMatch(api.panel(point,data),/保留的未发送问题/);
  console.log('A requirement question is saved before investigation, keeps its complete identity, and starts from existing sources.');
})().catch(error=>{console.error(error);process.exitCode=1;});

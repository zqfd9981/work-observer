// A question's readable journey follows saved links, not keyword guesses or new facts.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const node=()=>({value:'',addEventListener(){},querySelector:node,querySelectorAll:()=>[]});
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:''},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
const source=fs.readFileSync(process.argv[3],'utf8').replace(/\}\)\(\);\s*$/,'window.journeyTest={passageOrigin,passageReference,questionHypotheses,challengePanel,investigationPitchDraft,pitchQuestionLink,pitchLengthNotice,pitchCards,researchFocus,interview,interviewSources,interviewFocusLabel,questionInsightDraft,insightLengthNotice,insightSource,questionAnswer,conclusionDraft,researchLabel,requirements,autonomousState,mapQuestionDraft,questionOrigin,mapPair,mapComparison,comparisonWorkMap,questionJourneyRecords,questionJourney,questionJourneyPackage,sourceReading,readingStatus,libraryOriginal,learningRecall,learningFamily,understandingJourney,discussionFocus,libraryInquiry,inquiryPanel,setDraft:(data,draft)=>{career.id=data.id;career.data=data;career.tab="requirements";career.drafts.set(data.id,{inquiries:{requirements:draft},learning_journey:draft.learning_journey,map_comparison:draft.map_comparison,question_answers:draft.question_answers,next_source_step_id:draft.next_source_step_id})}};})();');
vm.runInContext(source,ctx);
const stamp=n=>`2026-11-21T00:00:0${n}Z`;
const question={id:'q',question:'Does retry prove recovery?',created_at:stamp(1),state:'open',conclusion:'',next_evidence:'Need a counterexample.'};
const task={id:'task',question_id:'q',title:'Negative experiment',created_at:stamp(3),updated_at:stamp(7),state:'done',hypothesis:'Retry should work.',deliverable:'Logs',completion_check:'Compare both inputs',outcome:'Both failed; no production result.',artifact_text:'<script>unsafe log</script>'};
const result=(step_id,created_at,extra={})=>({step_id,kind:'ask',created_at,state:'completed',current:true,result:{status:'completed',claims:[],evidence:[],gaps:[]},...extra});
const data={id:'goal',title:'Synthetic investigation',goal:'Understand conditions.',jobs:[],questions:[question],tasks:[task,{...task,id:'foreign-task',question_id:'other'}],results:[
  result('first',stamp(2),{question_id:'q'}),result('reply',stamp(4),{source_step_id:'first'}),
  result('interview',stamp(6),{kind:'interview',task_id:'task'}),
  result('pending',stamp(8),{source_step_id:'reply',state:'interrupted',result:{status:'incomplete',submission_feedback:{draft_claims:[{text:'UNFINISHED CLAIM MUST NOT APPEAR'}]}}}),
  result('other-study',stamp(4),{question_id:'other',source_step_id:'first'}),result('unrelated',stamp(2))
],insights:[
  {id:'old',created_at:stamp(0),current_view:'Original overconfident belief.',use_for_research:false},
  {id:'middle',created_at:stamp(5),task_id:'task',replaces_insight_id:'old',previous_view:'Original overconfident belief.',observation:'Negative run.',current_view:'Need evidence.',use_for_research:false},
  {id:'new',created_at:stamp(7),replaces_insight_id:'middle',previous_view:'Need evidence.',current_view:'Conditions remain unknown.',use_for_research:true},
  {id:'other-note',created_at:stamp(5),source_step_id:'other-study',replaces_insight_id:'new',current_view:'Another question.'},
  {id:'unrelated-note',created_at:stamp(1),current_view:'Unrelated general note.'}
]};
const original=JSON.stringify(data);
const records=ctx.window.journeyTest.questionJourneyRecords(question,data);
assert.deepEqual(Array.from(records.studies,row=>row.step_id).sort(),['first','interview','pending','reply']);
assert.deepEqual(Array.from(records.tasks,row=>row.id),['task']);
assert.deepEqual(Array.from(records.insights,row=>row.id).sort(),['middle','new','old']);
const html=ctx.window.journeyTest.questionJourney(question,data,true);
assert.ok(html.includes('Both failed; no production result.')&&html.includes('Conditions remain unknown.'));
assert.ok(html.includes('已搁置')&&html.includes('未完整形成回答'));
assert.ok(!html.includes('UNFINISHED CLAIM MUST NOT APPEAR')&&!html.includes('Another question.')&&!html.includes('Unrelated general note.'));
assert.ok(html.includes('&lt;script&gt;unsafe log&lt;/script&gt;')&&!html.includes('<script>unsafe log</script>'));
assert.ok(html.indexOf('data-journey-id="old"')<html.indexOf('data-journey-id="q"'));
assert.ok(html.includes('最近编辑')&&!html.includes('<button'));
const pack=ctx.window.journeyTest.questionJourneyPackage(question,data);
assert.ok(pack.startsWith('<!doctype html>')&&pack.includes('尚未记录结论，保留未知。'));
assert.ok(!pack.includes('foreign-task'));
assert.equal(JSON.stringify(data),original);
const old=result('older-source',stamp(1),{question_id:'q',task_id:'task',insight_id:'new',material_id:'removed',section:'requirements'});
const inquiryData={...data,stories:[{id:'story',title:'Exact saved story',document_id:'story-document'}],materials:[],document_ids:[],results:[...Array.from({length:20},(_,i)=>result('recent-'+i,stamp(2),{section:'requirements'})),old]};
const focus=ctx.window.journeyTest.discussionFocus(old,inquiryData);
assert.equal(focus.question_id,'q');assert.equal(focus.task_id,'task');assert.equal(focus.insight_id,'new');
assert.equal(focus.material_id,''); // Moving a material out of the goal must not restore it.
ctx.window.journeyTest.setDraft(inquiryData,focus);
const inquiry=ctx.window.journeyTest.inquiryPanel(inquiryData);
assert.ok(inquiry.includes('<option value="older-source" selected>'));
assert.ok(inquiry.includes('name="task_id" value="task"')&&inquiry.includes('name="insight_id" value="new"'));
const fromTask=ctx.window.journeyTest.libraryInquiry({kind:'task',id:'task',title:'Task lead',excerpt:'Only a short excerpt'},inquiryData);
assert.equal(fromTask.task_id,'task');assert.equal(fromTask.question_id,'q');
const fromStory=ctx.window.journeyTest.libraryInquiry({kind:'story',id:'story',title:'Story lead',excerpt:'Only a short excerpt'},inquiryData);
assert.equal(fromStory.story_id,'story');
const readings=[{job_id:'j',snapshot_id:'s',title:'JD',start:0,end:700,full_text_length:1600},{job_id:'j',snapshot_id:'s',title:'JD',start:500,end:1400,full_text_length:1600},{public_document_id:'p',title:'Log',start:0,end:4,full_text_length:4},{public_document_id:'lead',evidence_kind:'search_excerpt',title:'Search lead',start:0,end:10}];
const readingBefore=JSON.stringify(readings),coverage=ctx.window.journeyTest.sourceReading(readings);
assert.equal(coverage.sources.length,2);assert.equal(coverage.leads,1);
assert.equal(coverage.sources[0].read,1400);assert.equal(coverage.sources[0].complete,false);
assert.equal(coverage.sources[1].complete,true);
const readingHtml=ctx.window.journeyTest.readingStatus(coverage);
assert.ok(readingHtml.includes('1400 / 1600')&&readingHtml.includes('还有未读部分')&&readingHtml.includes('摘要不能当作已核正文'));
assert.equal(JSON.stringify(readings),readingBefore);
console.log('Question journey: explicit links, reply chain, belief replacement, negative observations, unfinished research and escaped standalone export passed.');

const named={public_document_id:'named-doc',title:'name-only.md',publisher:'<source>',quote:'Exact saved body.',start:0,end:17,retrieval:{match_location:'metadata',matched_terms:[]}};
const namedHtml=ctx.window.journeyTest.libraryOriginal(named,{document_ids:[]},'name-only.md');
assert.ok(namedHtml.includes('名称或来源信息命中')&&namedHtml.includes('打开完整原文')&&namedHtml.includes('&lt;source&gt;'));
const readerFocus=html=>JSON.parse(html.match(/data-reader-focus="([^"]+)"/)[1].replaceAll('&quot;','"'));
assert.equal(readerFocus(namedHtml).query,'');
assert.ok(namedHtml.includes('data-career-attach-material="named-doc"'));
const bodyHtml=ctx.window.journeyTest.libraryOriginal({...named,retrieval:{match_location:'body',matched_terms:['saved']}},{document_ids:['named-doc']},'missing saved');
assert.equal(readerFocus(bodyHtml).query,'saved');
assert.ok(bodyHtml.includes('正文命中')&&!bodyHtml.includes('data-career-attach-material'));
console.log('Library name previews and actual body-hit reader focus passed.');

const sentNote={id:'old-topic',previous_view:'Originally certain.',reported_observation:'Local failure only.',current_user_view:'<script>still unknown</script>',open_question:'Production unverified.',recorded_at:stamp(1),use_for_research:true};
const recalledResult={model_calls:3,career_learning_context:{notes:[sentNote],selected_note:null,selections:[{id:'old-topic',reason:'keyword'}],omitted_count:4}};
const recallHtml=ctx.window.journeyTest.learningRecall(recalledResult,'goal');
assert.ok(recallHtml.includes('本轮带入的个人认识 · 1 份')&&recallHtml.includes('字面关键词重合')&&recallHtml.includes('另有 4 份'));
assert.ok(recallHtml.includes('&lt;script&gt;still unknown&lt;/script&gt;')&&!recallHtml.includes('<script>still unknown</script>'));
assert.ok(recallHtml.includes('#career/goal/insight/old-topic'));
const recallExport=ctx.window.journeyTest.learningRecall(recalledResult,'goal',true);
assert.ok(recallExport.includes('Production unverified.')&&!recallExport.includes('href='));
assert.equal(ctx.window.journeyTest.learningRecall({...recalledResult,model_calls:0},'goal'),'');
assert.equal(ctx.window.journeyTest.learningRecall({model_calls:3},'goal'),'');
const explicitHtml=ctx.window.journeyTest.learningRecall({...recalledResult,career_learning_context:{...recalledResult.career_learning_context,selected_note:{...sentNote,use_for_research:false}}},'goal');
assert.ok(explicitHtml.includes('本次点选重查')&&explicitHtml.includes('当时已搁置')&&explicitHtml.includes('· 1 份'));
console.log('Learning recall: historical contents, selection reason, shelved explicit focus and standalone export passed.');

const noMatch=ctx.window.journeyTest.learningRecall({model_calls:3,career_learning_context:{notes:[],eligible_count:4,omitted_count:4}},'goal');
assert.ok(noMatch.includes('本轮带入的个人认识 · 0 份')&&noMatch.includes('没有自动找到相关的选用记录'));

const familyNotes=[
 {id:'first',created_at:stamp(1),previous_view:'Initial question.',observation:'No test.',current_view:'First view.',use_for_research:false},
 {id:'middle',created_at:stamp(2),replaces_insight_id:'first',previous_view:'First view.',observation:'Local negative observation.',current_view:'Middle view.',use_for_research:false},
 {id:'current',created_at:stamp(3),replaces_insight_id:'middle',previous_view:'Middle view.',observation:'Another counterexample.',current_view:'Current limited view.',open_question:'Production remains unverified.',use_for_research:true},
 {id:'parallel',created_at:stamp(4),replaces_insight_id:'first',previous_view:'First view.',observation:'Alternative explanation.',current_view:'Parallel <script>view</script>.',use_for_research:true},
 {id:'unrelated',created_at:stamp(5),current_view:'Unrelated record.'}
];
const familyBefore=JSON.stringify(familyNotes),family=ctx.window.journeyTest.learningFamily(familyNotes,'first');
assert.deepEqual(Array.from(family,row=>row.id),['first','middle','current','parallel']);
assert.deepEqual(Array.from(ctx.window.journeyTest.learningFamily(familyNotes,'current'),row=>row.id),['first','middle','current','parallel']);
const familyData={...data,insights:familyNotes};ctx.window.journeyTest.setDraft(familyData,{learning_journey:'first'});
const familyHtml=ctx.window.journeyTest.understandingJourney(familyData);
assert.ok(familyHtml.includes('4 份相关记录 · 2 份选用中')&&familyHtml.includes('Production remains unverified.'));
assert.ok(familyHtml.includes('#career/goal/understanding/middle')&&familyHtml.includes('data-career-insight-question="current"'));
assert.ok(!familyHtml.includes('Unrelated record.')&&!familyHtml.includes('<script>view</script>')&&familyHtml.includes('&lt;script&gt;view&lt;/script&gt;'));
assert.equal(JSON.stringify(familyNotes),familyBefore);
console.log('Understanding journey: continuous revisions, parallel views, selected record and retained limits passed.');

const activelyRead={...sentNote,id:'read-old',use_for_research:false,current_user_view:'Long remembered view; final limitation remains.',original_analysis:{text:'Old derived claim.'},source_locators:[{title:'Old source',quote:'<script>unsafe source</script>'}]};
const lookedUp={...recalledResult,career_learning_context:{...recalledResult.career_learning_context,searches:[{offset:0},{offset:6}],read_notes:[activelyRead]}};
const lookedUpHtml=ctx.window.journeyTest.learningRecall(lookedUp,'goal');
assert.ok(lookedUpHtml.includes('本轮带入的个人认识 · 2 份')&&lookedUpHtml.includes('Agent另检索 2 次，完整读取 1 次'));
assert.ok(lookedUpHtml.includes('data-learning-read="true"')&&lookedUpHtml.includes('Long remembered view; final limitation remains.'));
assert.ok(lookedUpHtml.includes('当时已搁置')&&lookedUpHtml.includes('Old derived claim.')&&lookedUpHtml.includes('&lt;script&gt;unsafe source&lt;/script&gt;'));
assert.ok(!ctx.window.journeyTest.learningRecall(lookedUp,'goal',true).includes('href='));
console.log('Notebook tool reads: complete historical text, separate initial context, old sources and escaped export passed.');

const pairedContext={model_calls:4,career_learning_context:{notes:[],selected_note:sentNote,counter_note:{...sentNote,id:'counter',use_for_research:false,current_user_view:'Counter view with its complete final limitation.'}}};
const pairedHtml=ctx.window.journeyTest.learningRecall(pairedContext,'goal');
assert.ok(pairedHtml.includes('本轮带入的个人认识 · 2 份')&&pairedHtml.includes('本次点选对照（B）')&&pairedHtml.includes('complete final limitation.'));
const pairedData={...inquiryData,insights:[...inquiryData.insights,{id:'counter',current_view:'Another complete view.'}]};
const pairedFocus=ctx.window.journeyTest.discussionFocus({...old,counter_insight_id:'counter'},pairedData);
assert.equal(pairedFocus.counter_insight_id,'counter');
ctx.window.journeyTest.setDraft(pairedData,pairedFocus);
assert.ok(ctx.window.journeyTest.inquiryPanel(pairedData).includes('name="counter_insight_id" value="counter"'));
console.log('Two-view comparison: both complete records and continued inquiry focus passed.');

const mapSource={id:'map-source',title:'<source title>',quote:'Original saved job text.',job_id:'job',snapshot_id:'snapshot',start:0,end:24};
const mapStudy=(id,n)=>result(id,stamp(n),{kind:'map',scope_current:n!==1,current:n!==1,result:{status:'completed',claims:[{category:'task',basis:'direct',requirement:'unspecified',text:'Complete task.',evidence_ids:['map-source']}],evidence:[mapSource],gaps:[],work_map:{scope_note:'Synthetic map '+id,work_types:[{name:'Work type '+id,problem:'A business problem.',tasks:'Concrete tasks.',deliverables:'An inspectable output.',boundary:'Only this setting.',next_check:'Check acceptance.',basis:'inference',claim_indices:[0]}],work_relations:[{source_text:'<script>full source</script>',predicate:'produces',target_text:'Complete output.',basis:'inference',rationale:'Reason remains an explanation.',transfer_limit:'Long boundary; '.repeat(100)+'FINAL LIMIT.',claim_indices:[0]}],comparisons:[],unknowns:['Actual responsibility remains unknown.']}}});
const maps=[mapStudy('third-map',3),mapStudy('second-map',2),mapStudy('first-map',1)];
const mapsData={...inquiryData,results:[...maps,result('unfinished-map',stamp(4),{result:{status:'incomplete',work_map:{scope_note:'UNFINISHED MAP'}}})]};
ctx.window.journeyTest.setDraft(mapsData,{map_comparison:{step_ids:['first-map','second-map'],open:true}});
assert.deepEqual(Array.from(ctx.window.journeyTest.mapPair(mapsData),row=>row.step_id),['first-map','second-map']);
const mapHtml=ctx.window.journeyTest.mapComparison(mapsData);
assert.ok(mapHtml.includes('Synthetic map first-map')&&mapHtml.includes('Synthetic map second-map'));
assert.ok(!mapHtml.includes('Synthetic map third-map')&&!mapHtml.includes('UNFINISHED MAP'));
assert.ok(mapHtml.includes('An inspectable output.')&&mapHtml.includes('FINAL LIMIT.')&&mapHtml.includes('Check acceptance.'));
assert.ok(mapHtml.includes('&lt;script&gt;full source&lt;/script&gt;')&&!mapHtml.includes('<script>full source</script>'));
const exportedMaps=ctx.window.journeyTest.mapComparison(mapsData,true);
assert.ok(exportedMaps.includes('Original saved job text.')&&exportedMaps.includes('FINAL LIMIT.'));
assert.ok(!exportedMaps.includes('<button')&&!exportedMaps.includes('<select'));
const mapFocus=ctx.window.journeyTest.discussionFocus(result('map-comparison',stamp(4),{comparison_step_ids:['first-map','second-map']}),mapsData);
assert.deepEqual(Array.from(mapFocus.comparison_step_ids),['first-map','second-map']);
console.log('Map comparison: selected history, complete work structure, source quotes, escaped export and continued focus passed.');

const originData={...mapsData,questions:[]};
ctx.window.journeyTest.setDraft(originData,{});
const inquirySeed=ctx.window.journeyTest.mapQuestionDraft(maps[0],'relation',0);
assert.ok(inquirySeed.question.length<=1500&&inquirySeed.question.includes('第 1 条工作关系'));
assert.ok(inquirySeed.question.includes('完整内容、理由、适用条件和未知'));
assert.ok(!inquirySeed.question.includes('Long boundary;'));
const typeSeed=ctx.window.journeyTest.mapQuestionDraft(maps[0],'boundary',0);
assert.equal(typeSeed.next_evidence,'Check acceptance.');
const originHtml=ctx.window.journeyTest.questionOrigin({source_step_id:maps[0].step_id},originData,true);
assert.ok(originHtml.includes('FINAL LIMIT.')&&originHtml.includes('Original saved job text.'));
assert.ok(!originHtml.includes('<button')&&!originHtml.includes('<script>full source</script>'));
const graphButton=vm.runInContext('mapInvestigationButton({career_step_id:"chosen-step"},"relation",0,"查证关系")',ctx);
assert.ok(graphButton.includes('data-career-map-step="chosen-step"')&&graphButton.includes('data-career-map-index="0"'));
console.log('Map inquiry: exact original item, bounded question, complete source context and saved-question entry passed.');

const autoRow=result('auto-third',stamp(4),{autonomous_rounds:1,autonomous_stop:'Reached the three-round limit.',investigation_reason:{evidence_needed:'<script>read original</script>',completion:'Keep unknown conditions.'}});
const autoHtml=ctx.window.journeyTest.autonomousState(autoRow);
assert.ok(autoHtml.includes('第 3 / 3 轮')&&autoHtml.includes('Reached the three-round limit.'));
assert.ok(autoHtml.includes('&lt;script&gt;read original&lt;/script&gt;')&&!autoHtml.includes('<script>read original</script>'));
assert.equal(ctx.window.journeyTest.autonomousState({}),'');
console.log('Autonomous inquiry: bounded round label, visible reason and escaped stop explanation passed.');

const materialGoal={...inquiryData,jobs:[],requirements:[],results:[]};
ctx.window.journeyTest.setDraft(materialGoal,{});
const materialIntro=ctx.window.journeyTest.requirements(materialGoal);
assert.ok(materialIntro.includes('当前未选目标JD')&&materialIntro.includes('理解这些工作资料'));
assert.ok(materialIntro.includes('data-career-open-material')&&!materialIntro.includes('岗位要求 × 我的经历证据'));
assert.equal(ctx.window.journeyTest.researchLabel({kind:'role',materials_only:true}),'理解工作资料');
assert.equal(ctx.window.journeyTest.researchLabel({kind:'role',materials_only:false}),'看清岗位');
console.log('Material-first research: source-aware entry, optional job link and historical labels passed.');

const longClaim='A limited interpretation; '.repeat(100)+'FINAL CONDITION MUST REMAIN.';
const answerRow=result('selected-answer',stamp(2),{question_id:'q',current:false,user_question:'Original inquiry.',result:{status:'completed',claims:[{text:longClaim,category:'task',basis:'inference',requirement:'unspecified',evidence_ids:['a']}],evidence:[{id:'a',title:'Original source',quote:'<script>saved original</script>',start:0,end:20}],gaps:['Still no independent observation.']}});
const otherAnswer=result('recent-answer',stamp(3),{question_id:'q',result:{status:'completed',claims:[{text:'Newer text is not automatically true.',category:'task',basis:'direct',requirement:'unspecified',evidence_ids:[]}],evidence:[],gaps:[]}});
const answersData={...inquiryData,results:[otherAnswer,answerRow]};
ctx.window.journeyTest.setDraft(answersData,{question_answers:{q:{step_id:'selected-answer',open:true}}});
const answerHtml=ctx.window.journeyTest.questionAnswer(question,answersData);
assert.ok(answerHtml.includes('FINAL CONDITION MUST REMAIN.')&&answerHtml.includes('Still no independent observation.'));
assert.ok(answerHtml.includes('data-career-conclusion-draft="q:selected-answer"')&&answerHtml.includes('value="selected-answer" selected'));
const answerDraft=ctx.window.journeyTest.conclusionDraft(answerRow);
assert.ok(answerDraft.length>2000&&answerDraft.includes(longClaim)&&answerDraft.includes('待验证解释')&&answerDraft.includes('Still no independent observation.'));
const answerExport=ctx.window.journeyTest.questionAnswer(question,answersData,true);
assert.ok(answerExport.includes('FINAL CONDITION MUST REMAIN.')&&answerExport.includes('&lt;script&gt;saved original&lt;/script&gt;'));
assert.ok(!answerExport.includes('<button')&&!answerExport.includes('<select'));
assert.equal(ctx.window.journeyTest.questionAnswer({id:'missing'},answersData),'');
console.log('Question answer: chosen completed response, full long conditions, uncertainty labels and standalone export passed.');

const reviewedQuestion={...question,conclusion:'My complete retained understanding. '.repeat(50)+'LAST LIMIT MUST REMAIN.',conclusion_step_id:'selected-answer',next_evidence:'Still unknown; '.repeat(90)};
const learningData={...answersData,questions:[reviewedQuestion]};
const noteDraft=ctx.window.journeyTest.questionInsightDraft(reviewedQuestion,learningData);
assert.equal(noteDraft.question_id,question.id);assert.equal(noteDraft.current_view,reviewedQuestion.conclusion);
assert.equal(noteDraft.source_claim_index,null);assert.equal(noteDraft.replaces_insight_id,'');
assert.ok(noteDraft.observation.includes('<script>saved original</script>'));
assert.ok(ctx.window.journeyTest.insightLengthNotice(noteDraft).includes('当前理解'));
assert.ok(ctx.window.journeyTest.insightLengthNotice(noteDraft).includes('仍待验证'));
const sourceDiscussion=ctx.window.journeyTest.insightSource(noteDraft,learningData,true);
assert.ok(sourceDiscussion.includes('关联整次讨论')&&sourceDiscussion.includes('&lt;script&gt;saved original&lt;/script&gt;'));
assert.ok(!sourceDiscussion.includes('<button'));
const relatedNotes={...data,insights:[...data.insights,{id:'question-linked',question_id:'q',current_view:'Explicit inquiry conclusion.'},{id:'another-inquiry',question_id:'other',source_step_id:'first',current_view:'Must stay in another inquiry.'}]};
const relatedRecords=ctx.window.journeyTest.questionJourneyRecords(question,relatedNotes);
assert.ok(relatedRecords.insights.some(row=>row.id==='question-linked'));
assert.ok(!relatedRecords.insights.some(row=>row.id==='another-inquiry'));
console.log('Inquiry conclusion to personal understanding: full draft, explicit question, whole-discussion origin and journey links passed.');

const quizRow=result('teachback-source',stamp(1),{kind:'teachback',question_id:'q',understanding_check:true,result:{status:'completed',claims:[],evidence:[],gaps:['Explain the boundary?']}});
const ownAttempt=result('own-attempt',stamp(2),{kind:'answer',question_id:'q',understanding_check:true,interview_question:'Explain the boundary?',answer:'Own explanation with unknowns.'});
const foreignAttempt={...ownAttempt,step_id:'other-attempt',question_id:'other',answer:'OTHER INQUIRY ANSWER MUST NOT MIX'};
const quizData={...inquiryData,questions:[question,{id:'other',question:'Another concept.'}],tasks:[],stories:[],results:[foreignAttempt,ownAttempt,quizRow]};
ctx.window.journeyTest.setDraft(quizData,{next_source_step_id:quizRow.step_id});
assert.equal(ctx.window.journeyTest.interviewSources(quizData)[0].step_id,quizRow.step_id);
assert.ok(ctx.window.journeyTest.interviewFocusLabel(quizRow,quizData).startsWith('理解自测：'));
const quizHtml=ctx.window.journeyTest.interview(quizData);
assert.ok(quizHtml.includes('把理解讲清楚，再检查边界')&&quizHtml.includes('检查我的理解与推理'));
assert.ok(quizHtml.includes('Own explanation with unknowns.')&&!quizHtml.includes('OTHER INQUIRY ANSWER MUST NOT MIX'));
assert.equal(ctx.window.journeyTest.researchLabel(ownAttempt),'理解自测反馈');
console.log('Understanding practice: clear mode, inquiry focus, answer grouping and feedback labels passed.');

const focusData={...data,focus_question_id:'q',questions:[{...question,conclusion:'User conclusion with remaining uncertainty.',next_evidence:'Need a real counterexample.'}],results:[...data.results].reverse()};
const focusBefore=JSON.stringify(focusData);
const focusHtml=ctx.window.journeyTest.researchFocus(focusData);
assert.ok(focusHtml.includes('data-career-focused-question="q"')&&focusHtml.includes('User conclusion with remaining uncertainty.'));
assert.ok(focusHtml.includes('Need a real counterexample.')&&focusHtml.includes('Negative experiment'));
assert.ok(focusHtml.includes('Conditions remain unknown.')&&!focusHtml.includes('Original overconfident belief.'));
assert.ok(focusHtml.includes('#career/goal/journey/q')&&focusHtml.includes('data-career-question-teachback="q"'));
assert.equal(JSON.stringify(focusData),focusBefore);
const noFocus=ctx.window.journeyTest.researchFocus({...focusData,focus_question_id:null});
assert.ok(noFocus.includes('留住一个值得继续的问题')&&!noFocus.includes('data-career-focused-question'));
console.log('Research focus: current question, linked work, selected understanding and unmodified records passed.');

const pitchBefore=JSON.stringify(data);
const researchPitch=ctx.window.journeyTest.investigationPitchDraft(question,data);
assert.equal(researchPitch.question_id,question.id);
assert.equal(researchPitch.story_id,'');assert.equal(researchPitch.source_step_id,'');
assert.ok(researchPitch.text.includes('Both failed; no production result.'));
assert.ok(researchPitch.text.includes('Conditions remain unknown.'));
assert.ok(!researchPitch.text.includes('UNFINISHED CLAIM MUST NOT APPEAR'));
assert.ok(!researchPitch.text.includes('Another question.')&&!researchPitch.text.includes('Unrelated general note.'));
const plannedPitch=ctx.window.journeyTest.investigationPitchDraft(question,{...data,tasks:[{...task,outcome:''}]});
assert.ok(plannedPitch.text.includes('目前只是验证计划')&&!plannedPitch.text.includes('Both failed'));
const emptyPitch=ctx.window.journeyTest.investigationPitchDraft(question,{...data,tasks:[],results:[],insights:[]});
assert.ok(emptyPitch.text.includes('尚未记录实际验证')&&emptyPitch.text.includes('尚未记录认识变化'));
const longPitch=ctx.window.journeyTest.investigationPitchDraft({...question,conclusion:'Very long qualification. '.repeat(150)+'FINAL LIMIT MUST STAY'},data);
assert.ok(longPitch.text.length>2500&&longPitch.text.includes('FINAL LIMIT MUST STAY'));
assert.ok(ctx.window.journeyTest.pitchLengthNotice(longPitch.text).includes('全文保留'));
const link=ctx.window.journeyTest.pitchQuestionLink(researchPitch,data);
assert.ok(link.includes('/journey/q')&&link.includes('后续更新不会改写'));
assert.equal(JSON.stringify(data),pitchBefore);
console.log('Research presentation: linked inquiry, actual negative observations, planned work, qualified understanding and full editable draft passed.');

const pairQuestion={...question,hypothesis_a:'A applies under timeout. <script>not executed</script>',hypothesis_b:'B depends on request identity. FINAL LIMIT'};
const pairData={...data,questions:[pairQuestion],tasks:[task,{...task,id:'foreign-task',title:'FOREIGN OBSERVATION',question_id:'other'}]};
const pairHtml=ctx.window.journeyTest.questionHypotheses(pairQuestion,true);
assert.ok(pairHtml.includes('FINAL LIMIT')&&pairHtml.includes('&lt;script&gt;'));
assert.ok(!pairHtml.includes('<button')&&!pairHtml.includes('<script>'));
const pairJourney=ctx.window.journeyTest.questionJourney(pairQuestion,{...pairData,results:[...data.results,result('pair',stamp(8),{kind:'challenge',question_id:'q',hypothesis_a:'Historical A',hypothesis_b:'Historical B'})]},true);
assert.ok(pairJourney.includes('Historical A')&&pairJourney.includes('Historical B'));
assert.ok(pairJourney.includes('FINAL LIMIT'));
const pairPitch=ctx.window.journeyTest.investigationPitchDraft(pairQuestion,pairData);
assert.ok(pairPitch.text.includes(pairQuestion.hypothesis_a)&&pairPitch.text.includes(pairQuestion.hypothesis_b));
assert.equal(ctx.window.journeyTest.questionHypotheses(question),'');
console.log('Competing inquiry explanations: full conditions, historical comparison, planned work and exported presentation passed.');

const originQuote='<source>Repeated passage with final qualification.</source>';
const passage={public_document_id:'origin-doc',start:51,end:51+Array.from(originQuote).length,title:'Exact saved material',quote:originQuote,evidence_kind:'work_material'};
const passageQuestion={...question,source_passage:passage};
const passageData={...data,document_ids:[]};
const originMarkup=ctx.window.journeyTest.passageOrigin(passageQuestion,passageData);
assert.ok(originMarkup.includes('&lt;source&gt;')&&!originMarkup.includes('<source>Repeated'));
assert.ok(originMarkup.includes('尚未选入')&&originMarkup.includes('data-career-attach-material="origin-doc"'));
assert.equal(readerFocus(originMarkup).start,51);
const passageExport=ctx.window.journeyTest.questionJourneyPackage(passageQuestion,passageData);
assert.ok(passageExport.includes('Exact saved material')&&passageExport.includes('&lt;source&gt;'));
assert.ok(!passageExport.includes('data-career-attach-material'));
assert.deepEqual(Object.keys(ctx.window.journeyTest.passageReference(passage)).sort(),['end','public_document_id','start']);
const crlf=String.fromCharCode(13,10),canonical='🙂'+crlf+'same'+crlf+'same';
const selected=ctx.sourceSelectionOffsets(canonical,7,11);
assert.equal(Array.from(canonical).slice(selected.start,selected.end).join(''),'same');
assert.equal(selected.start,9);
console.log('Original passage inquiry: exact repeated-text positions, Unicode and CRLF, readable origin and source-aware export passed.');

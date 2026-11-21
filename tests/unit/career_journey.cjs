// A question's readable journey follows saved links, not keyword guesses or new facts.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const node=()=>({value:'',addEventListener(){},querySelector:node,querySelectorAll:()=>[]});
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:''},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
const source=fs.readFileSync(process.argv[3],'utf8').replace(/\}\)\(\);\s*$/,'window.journeyTest={passageEvidenceSummary,contrastExperimentDraft,manualExperiment,carriedWorkRelations,relationComparisonRecall,relationInquiryForm,workRelationsValues,workRelationsLink,workRelationCard,workRelationsPackage,workRelationsPage,experimentInsightDraft,experimentInsightSource,insightQuestionDraft,insightQuestionOrigin,learningRecall,cohortDefaults,cohortPercent,cohortChange,cohortOutput,cohortLab,cohortRecall,cohortProbeDraft,readingCoverage,readerCoverage,sourceReaderText,readingReference,readingReferenceKey,jobReadingButton,comparisonStartDraft,comparisonStartPanel,jdFields,inquiryRecall,archiveSourceKey,investigationSourceRecords,archiveSourceLink,archiveSourceText,investigationArchive,interviewAttempts,answerReplaySelection,answerComparisonDraft,answerReplay,answerReplayPackage,answerComparisonRecall,selectInvestigation,renderInvestigation,storyDraft,questionCard,claimCorrectionDraft,learningNotes,localExperimentRecall,retryProbeDraft,retryObservationTables,retryLabDefaults,retryLabInputs,retryLabResult,retryLab,capturePassagePanel,careerSearchValues,careerSearchLink,careerSearchForm,careerSearchPage,libraryResults,evidenceLibrary,careerHome,researchActivityItems,researchActivity,researchControls,researchRecall,researchRows,researchViewControls,researchResultSummary,noteReview,libraryClaimMatches,materialReadingPair,materialReadingPanel,materialReadingPackage,practiceRevisionDraft,interviewFocusPanel,claimReferencePanel,claimCheckDraft,claimReviewFocus,coachingResult,insightGroupDraft,insightGroupFocus,noteSynthesisPanel,taskStoryDraft,storyLengthIssue,taskStorySource,comparisonColumn,experimentRecipeText,experimentComparisonTable,savedComparisonRows,experimentComparisonEditor,careerStartValues,questionInquiryDraft,mapRelationChanges,mapChanges,mapChangeInquiry,materialMapDraft,experimentRecall,inquiryNextAction,inquiryNextButton,inquiryNextStep,observationInquiryDraft,observationPreview,questionBoard,inquiryMapModel,inquiryMap,inquiryMapPackage,questionValues,questionMaterials,questionMaterialEditor,saveMaterialFocusButton,materialComparePanel,materialFocus,materialNames,materialBatchReady,materialBatchProblem,materialBatchPanel,passageGroups,passageEditor,materialQuestions,materialInquiryDraft,materialRevisionEditor,materialShelf,historySideEvidence,continuedDiscussion,compareJobs,comparisonJobIds,comparisonQuestionDraft,jobComparisonPackage,learningInquiryLinks,learningInquiryContext,synthesisPanel,synthesisSources,carriedDiscussion,returnInquiryDraft,returnedInquirySource,branchQuestionDraft,questionBranches,recentResearch,workspaceShortcuts,conversationNoteEditor,answerRevisionChoice,answerRevisionDraft,questionSourceChanges,questionSourceNotice,sourceFollowups,sourceReviewDraft,jobObservationEditor,careerWorkMap,taskRequirement,taskRequirementInquiry,requirementExperiments,jobChanges,jobChangeInquiry,jobComparison,comparisonFindings,selectedJobFocus,researchScope,learningInputs,learningChanges,learningChangeNotice,learningImpactRecords,learningImpact,learningImpactPackage,questionPassages,passageOrigin,passageReference,questionHypotheses,challengePanel,investigationPitchDraft,pitchQuestionLink,pitchLengthNotice,pitchCards,researchFocus,interview,interviewSources,interviewFocusLabel,questionInsightDraft,insightLengthNotice,insightSource,questionAnswer,conclusionDraft,researchLabel,requirements,autonomousState,mapQuestionDraft,questionOrigin,mapPair,mapComparison,comparisonWorkMap,questionJourneyRecords,questionJourney,questionJourneyPackage,sourceReading,readingStatus,libraryOriginal,learningRecall,learningFamily,understandingJourney,discussionFocus,libraryInquiry,inquiryPanel,setDraft:(data,draft)=>{career.id=data.id;career.data=data;career.tab="requirements";career.workspaceQuestion=null;career.workspaceExpanded=false;career.drafts.set(data.id,{insight:draft.insight,retry_lab:draft.retry_lab,cohort_lab:draft.cohort_lab,activity_open:draft.activity_open,interview_focus:draft.interview_focus,material_compare:draft.material_compare,material_batch:draft.material_batch,passage_filters:draft.passage_filters,manual:draft.manual,manual_open:draft.manual_open,passage_editor:draft.passage_editor,material_revision:draft.material_revision,synthesis:draft.synthesis,inquiries:{requirements:draft},answer_comparisons:draft.answer_comparisons,conversation_note:draft.conversation_note,jd_observations:draft.jd_observations,job_changes:draft.job_changes,compare_jobs:draft.compare_jobs,compare_step_id:draft.compare_step_id,compare_open:draft.compare_open,learning_journey:draft.learning_journey,map_comparison:draft.map_comparison,question_answers:draft.question_answers,next_source_step_id:draft.next_source_step_id})}};})();');
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

const counterPassage={...passage,id:'counter-passage',recorded_at:stamp(4),relation:'challenges',user_note:'Could be a counterexample <check conditions>.'};
const collectedQuestion={...passageQuestion,evidence_passages:[counterPassage]};
const collectedBefore=JSON.stringify(collectedQuestion);
const collectedMarkup=ctx.window.journeyTest.questionPassages(collectedQuestion,passageData);
assert.ok(collectedMarkup.includes('我的标注：可能挑战')&&collectedMarkup.includes('&lt;check conditions&gt;'));
assert.ok(collectedMarkup.includes('data-career-edit-passage="q:counter-passage"'));
assert.ok(collectedMarkup.includes('data-career-question-ask="q"'));
const collectedJourney=ctx.window.journeyTest.questionJourney(collectedQuestion,passageData,true);
assert.ok(collectedJourney.includes('data-journey-kind="passage"')&&collectedJourney.includes('&lt;check conditions&gt;'));
assert.ok(collectedJourney.includes('当时收集的原文与出处')&&!collectedJourney.includes('data-career-remove-passage'));
assert.equal(JSON.stringify(collectedQuestion),collectedBefore);
console.log('Collected inquiry passages: qualified labels, complete original text, chronology, continued inquiry and safe standalone export passed.');

{
const historicalView='Original interpretation. '.repeat(55)+'TAIL CONDITION: production remains unknown.';
const oldInput={id:'belief-a',current_user_view:historicalView,previous_view:'Initial question.',reported_observation:'Only a local record.',open_question:'Need a counterexample.',use_for_research:true};
const changedBeliefs=[{id:'belief-a',created_at:stamp(1),current_view:'Edited A, still uncertain.',previous_view:'Initial question.',observation:'Only a local record.',open_question:'Need a counterexample.',use_for_research:false},{id:'belief-b',created_at:stamp(5),replaces_insight_id:'belief-a',current_view:'B retains the limitation.',previous_view:historicalView,observation:'A negative observation.',open_question:'Still need external evidence.',use_for_research:true}];
const newInput={id:'belief-b',current_user_view:changedBeliefs[1].current_view,previous_view:historicalView,reported_observation:'A negative observation.',open_question:'Still need external evidence.',use_for_research:true};
const oldDiscussion=result('input-a',stamp(2),{run_id:'run-a',result:{status:'completed',model_calls:3,claims:[{text:'Historical qualified statement.',category:'task',basis:'inference',requirement:'unspecified',evidence_ids:['source-a']}],evidence:[{id:'source-a',title:'Original archive',quote:'<raw>Complete original source.</raw>',evidence_kind:'work_material',public_document_id:'doc-a',start:0,end:42}],gaps:['Unknown remains.'],career_learning_context:{notes:[oldInput]}}});
const activelyRead=result('input-b',stamp(6),{run_id:'run-b',result:{status:'completed',model_calls:3,claims:[],evidence:[],gaps:[],career_learning_context:{notes:[],read_notes:[newInput]}}});
const indirect=result('later',stamp(3),{run_id:'run-later',source_step_id:'input-a',result:{status:'completed',model_calls:3,claims:[],evidence:[],gaps:[]}});
const previewOnly=result('preview-only',stamp(4),{result:{status:'completed',model_calls:2,claims:[],evidence:[],gaps:[],career_learning_context:{notes:[],searches:[{notes:[{id:'belief-a',current_view_preview:'A preview only'}]}]}}});
const impactData={...data,insights:changedBeliefs,results:[activelyRead,indirect,oldDiscussion,previewOnly]};
const impactBefore=JSON.stringify(impactData);
const affected=ctx.window.journeyTest.learningImpactRecords('belief-b',impactData);
assert.deepEqual(Array.from(affected,item=>item.row.step_id),['input-b','later','input-a']);
assert.equal(affected.find(item=>item.row.step_id==='later').inputs.length,0);
assert.equal(affected.find(item=>item.row.step_id==='input-b').inputs[0].channel,'主动阅读全文');
const changes=ctx.window.journeyTest.learningChanges(oldDiscussion.result,impactData);
assert.equal(changes.length,1);assert.equal(changes[0].reasons.length,2);
assert.equal(ctx.window.journeyTest.learningChanges(activelyRead.result,impactData).length,0);
const alreadyShelved={...oldDiscussion.result,career_learning_context:{notes:[{...oldInput,current_user_view:changedBeliefs[0].current_view,use_for_research:false}]}};
assert.equal(ctx.window.journeyTest.learningChanges(alreadyShelved,impactData).length,0);
const impactMarkup=ctx.window.journeyTest.learningImpact('belief-a',impactData);
assert.ok(impactMarkup.includes('沿相关讨论继续或对照')&&impactMarkup.includes('原答复仍是当时结果'));
assert.ok(!impactMarkup.includes('data-learning-impact="preview-only"'));
const impactExport=ctx.window.journeyTest.learningImpactPackage('belief-b',impactData);
assert.ok(impactExport.includes('TAIL CONDITION: production remains unknown.'));
assert.ok(impactExport.includes('Historical qualified statement.')&&impactExport.includes('&lt;raw&gt;Complete original source.'));
assert.ok(!impactExport.includes('<raw>')&&!impactExport.includes('data-career-ask-result'));
assert.equal(JSON.stringify(impactData),impactBefore);
console.log('Understanding review: changed inputs, actual full-note reads, referenced followups, unchanged snapshots and complete safe export passed.');

}

{
const pairIds=['job-b','job-a'];
const scopedData={...inquiryData,jobs:[{id:'job-a',current:{title:'Job A <condition>',company_name_raw:'Team A'}},{id:'job-b',current:{title:'Job B',company_name_raw:'Team B'}},{id:'job-c',current:{title:'Unselected job'}}],questions:[{...question,selected_job_ids:pairIds}]};
const scopedRow={...old,selected_job_ids:pairIds};
const scopedFocus=ctx.window.journeyTest.discussionFocus(scopedRow,scopedData);
assert.deepEqual(Array.from(scopedFocus.selected_job_ids),pairIds);
ctx.window.journeyTest.setDraft(scopedData,{...scopedFocus,question:'Retain this question.'});
const scopedPanel=ctx.window.journeyTest.inquiryPanel(scopedData);
assert.ok(scopedPanel.includes('name="selected_job_ids"')&&scopedPanel.includes('data-career-clear-selected-jobs'));
assert.ok(scopedPanel.includes('Job A &lt;condition&gt;')&&scopedPanel.includes('Retain this question.'));
assert.ok(!scopedPanel.includes('Unselected job'));
const fromLibrary=ctx.window.journeyTest.libraryInquiry({kind:'question',id:'q',title:'Saved pair',excerpt:'Unknown remains.'},scopedData);
assert.deepEqual(Array.from(fromLibrary.selected_job_ids),pairIds);
const scopeHtml=ctx.window.journeyTest.researchScope({...scopedRow,result:{scope:{jobs:[{id:'job-b',title:'Original Job B'}]}}},scopedData,true);
assert.ok(scopeHtml.includes('Original Job B')&&!scopeHtml.includes('Job B · Team B'));
assert.ok(scopeHtml.indexOf('Original Job B')<scopeHtml.indexOf('Job A &lt;condition&gt;'));
assert.ok(!scopeHtml.includes('Unselected job'));
const scopedExport=ctx.window.journeyTest.questionJourneyPackage(scopedData.questions[0],{...scopedData,results:[]});
assert.ok(scopedExport.includes('Job A &lt;condition&gt;')&&scopedExport.includes('Job B'));
assert.ok(!scopedExport.includes('data-career-clear-selected-jobs'));
console.log('Selected job inquiry: exact pair, continued and library questions, historical names and standalone export passed.');
}

{
const pairEvidence=[{id:'ev-a',job_id:'job-a',quote:'Original A condition.',title:'Raw A'},{id:'ev-b',job_id:'job-b',quote:'Original B condition.',title:'Raw B'}];
const pairStudy=result('pair-study',stamp(2),{user_question:'Only this chosen study.',selected_job_ids:['job-b','job-a'],result:{status:'completed',claims:[{category:'task',basis:'direct',requirement:'unspecified',text:'Selected A task.',evidence_ids:['ev-a']},{category:'ability',basis:'direct',requirement:'preferred',text:'Selected B preferred condition.',evidence_ids:['ev-b']},{category:'task',basis:'inference',requirement:'unspecified',text:'A qualified comparison of both jobs.',evidence_ids:['ev-a','ev-b']}],evidence:pairEvidence,gaps:[]}});
const comparisonData={...data,jobs:[{id:'job-a',current:{title:'A'}},{id:'job-b',current:{title:'B'}}],requirements:[{category:'task',text:'Different recent map.',basis:'direct',requirement:'unspecified',evidence:[pairEvidence[0]]}],results:[pairStudy]};
ctx.window.journeyTest.setDraft(comparisonData,{compare_jobs:['job-b','job-a'],compare_step_id:'pair-study'});
const pairBefore=JSON.stringify(comparisonData),comparison=ctx.window.journeyTest.jobComparison(comparisonData);
assert.ok(comparison.includes('Only this chosen study.')&&comparison.includes('Selected B preferred condition.'));
assert.ok(comparison.includes('Original A condition.')&&comparison.includes('Original B condition.'));
assert.ok(comparison.includes('A qualified comparison of both jobs.')&&!comparison.includes('Different recent map.'));
assert.ok(comparison.includes('data-career-clear-comparison-study'));
const readOnlyScope=ctx.window.journeyTest.researchScope(pairStudy,comparisonData,true);
assert.ok(!readOnlyScope.includes('data-career-job-comparison'));
assert.ok(ctx.window.journeyTest.researchScope(pairStudy,comparisonData).includes('data-career-job-comparison'));
assert.equal(JSON.stringify(comparisonData),pairBefore);
console.log('Chosen study comparison: its own claims and complete evidence, preferred conditions, shared judgments and read-only export passed.');
}

{
const changeJob={id:'history-job',current:{title:'Changed role <condition>',company_name_raw:'Team'}};
const oldSource={snapshot_id:'old-snapshot',document_id:'old-document',job_id:'history-job',start:0,end:45,quote:'<original>Old qualification; boundary remains.</original>',title:'Old raw source'};
const newSource={...oldSource,snapshot_id:'new-snapshot',document_id:'new-document',quote:'New preferred condition, not mandatory.',title:'New raw source'};
const observed=(snapshot_id,minute)=>({snapshot_id,observed_at:`2026-11-21T01:${minute}:00+00:00`,processed_at:`2026-11-21T01:${minute}:01.123456+00:00`,read_as_of:`2026-11-21T01:${minute}:01.123456+00:00`,data_kind:'synthetic',mode:'manual'});
const changeComparison={status:'compared',job_id:changeJob.id,before:observed(oldSource.snapshot_id,'00'),after:observed(newSource.snapshot_id,'10'),description_diff:'-Old condition.\n+New condition <check>.',evidence:[oldSource,newSource],changes:[{field:'description',before:oldSource.quote,after:newSource.quote},{field:'education',before:null,after:'Preferred'}]};
const changeData={...data,jobs:[changeJob]};
ctx.window.journeyTest.setDraft(changeData,{job_changes:{job_id:changeJob.id,open:true,comparison:changeComparison}});
const changesHtml=ctx.window.journeyTest.jobChanges(changeData),changeDraft=ctx.window.journeyTest.jobChangeInquiry(changeJob,changeComparison);
assert.ok(changesHtml.includes('&lt;original&gt;')&&changesHtml.includes('&lt;check&gt;'));
assert.ok(changesHtml.includes('data-career-save-job-change="history-job"'));
assert.ok(!changesHtml.includes('<original>')&&!changesHtml.includes('undefined'));
assert.equal(changeDraft.source_passage.snapshot_id,'old-snapshot');
assert.equal(changeDraft.after_passage.snapshot_id,'new-snapshot');
assert.deepEqual(Array.from(changeDraft.selected_job_ids),['history-job']);
assert.ok(changeDraft.next_evidence.includes(changeComparison.before.read_as_of)&&changeDraft.next_evidence.includes(changeComparison.after.read_as_of));
assert.ok(changeDraft.hypothesis_a&&changeDraft.hypothesis_b);
ctx.window.journeyTest.setDraft(changeData,{job_changes:{job_id:changeJob.id,comparison:{status:'insufficient_history',gaps:['Need another source.']}}});
const insufficient=ctx.window.journeyTest.jobChanges(changeData);
assert.ok(insufficient.includes('Need another source.')&&!insufficient.includes('data-career-save-job-change'));
assert.equal(ctx.window.journeyTest.jobChanges({...data,jobs:[]}), '');
console.log('Source change inquiry: two raw sources, exact historical cutoffs, alternative explanations, escaped differences and insufficient history passed.');
}

{
const targetRequirement={key:'role-run:0',text:'Preferred qualification with final condition.',category:'ability',requirement:'preferred',missing:'Only one local observation; production unknown.',evidence:[{id:'target-ev',title:'Original target JD',quote:'<raw>Preferred condition; keep the exception.</raw>',job_id:'target-job'}]};
const targetedTask={...task,id:'target-task',source_step_id:'target-plan',target_requirement:targetRequirement};
const targetedData={...data,jobs:[{id:'target-job',current:{title:'Target'}}],tasks:[targetedTask,{...task,id:'foreign-task',title:'Other requirement task',target_requirement:{...targetRequirement,key:'other-run:0'}}],results:[result('target-plan',stamp(2))]};
const targetBefore=JSON.stringify(targetedData);
const renderedTarget=ctx.window.journeyTest.taskRequirement(targetedTask,targetedData);
assert.ok(renderedTarget.includes('Preferred qualification with final condition.')&&renderedTarget.includes('production unknown.'));
assert.ok(renderedTarget.includes('&lt;raw&gt;')&&!renderedTarget.includes('<raw>'));
assert.ok(renderedTarget.includes('data-career-task-requirement="target-task"'));
assert.ok(renderedTarget.includes('/discussion/target-plan'));
const exportedTarget=ctx.window.journeyTest.taskRequirement(targetedTask,targetedData,true);
assert.ok(exportedTarget.includes('keep the exception.')&&!exportedTarget.includes('data-career-task-requirement'));
assert.ok(!ctx.window.journeyTest.taskRequirement({...targetedTask,outcome:''},targetedData).includes('data-career-task-requirement'));
const candidates=ctx.window.journeyTest.requirementExperiments(targetRequirement,targetedData);
assert.ok(candidates.includes('/task/target-task')&&!candidates.includes('Other requirement task'));
const revisit=ctx.window.journeyTest.taskRequirementInquiry(targetedTask,targetedData);
assert.equal(revisit.task_id,'target-task');
assert.deepEqual(Array.from(revisit.selected_job_ids),['target-job']);
assert.equal(ctx.window.journeyTest.taskRequirement(task,targetedData),'');
assert.equal(JSON.stringify(targetedData),targetBefore);
console.log('Requirement experiment: original qualification and full raw source, planned versus observed work, exact task return and read-only export passed.');
}

{
const qualifiedMap=result('qualified-map',stamp(1),{kind:'map',result:{status:'completed',claims:[{text:'Carry out the task.',evidence_ids:['map-ev'],basis:'direct',category:'task',requirement:'unspecified'},{text:'Business background is preferred, with the final condition.',evidence_ids:['map-ev'],basis:'direct',category:'ability',requirement:'preferred'}],evidence:[{id:'map-ev',label:'E1',quote:'Original qualification.'}],work_map:{scope_note:'Selected source only.',work_types:[],work_relations:[{source_kind:'task',source_text:'Compare outputs',target_kind:'ability',target_text:'Business understanding',predicate:'requires',claim_indices:[0,1],basis:'inference',rationale:'A limited interpretation.',transfer_limit:'Not a mandatory recruitment condition.'}],comparisons:[],unknowns:[]}}});
const mapMarkup=ctx.window.journeyTest.careerWorkMap(qualifiedMap,new Map(qualifiedMap.result.evidence.map(row=>[row.id,row])));
assert.ok(mapMarkup.includes('加分')&&mapMarkup.includes('原文明示'));
assert.ok(mapMarkup.includes('Business background is preferred, with the final condition.'));
assert.ok(mapMarkup.includes('Not a mandatory recruitment condition.')&&mapMarkup.includes('data-graph-node-choice'));
console.log('Career relation evidence: preferred qualification, original statement type and complete final condition remain visible inside graph explanations.');
}

{
const observedJob={id:'observe-job',source:'manual',current:{title:'Manual role <check>',company_name_raw:'Team',description_text:'OLD BODY MUST NOT BE PREFILLED',salary_raw:'20-25K',source_published_at:'2026-11-18T09:00:00+08:00'},provenance:{description_text:{data_kind:'synthetic'}}};
ctx.window.journeyTest.setDraft(data,{});
const emptyObservation=ctx.window.journeyTest.jobObservationEditor(observedJob,data);
assert.ok(emptyObservation.includes('Manual role &lt;check&gt;')&&!emptyObservation.includes('20-25K'));
assert.ok(!emptyObservation.includes('OLD BODY MUST NOT BE PREFILLED')&&!emptyObservation.includes('2026-11-18T09:00:00+08:00'));
assert.ok(emptyObservation.includes('value="synthetic" selected')&&!emptyObservation.includes('name="external_id"'));
ctx.window.journeyTest.setDraft(data,{jd_observations:{'observe-job':{open:true,values:{description:'New body <keep final condition>',source_published_at:'',note:'A later supplied observation.'}}}});
const observedDraft=ctx.window.journeyTest.jobObservationEditor(observedJob,data);
assert.ok(observedDraft.includes('New body &lt;keep final condition&gt;')&&observedDraft.includes('A later supplied observation.'));
assert.ok(ctx.window.journeyTest.jobObservationEditor(observedJob,{...data,running:true}).includes('<fieldset disabled>'));
assert.equal(ctx.window.journeyTest.jobObservationEditor({...observedJob,source:'platform'},data),'');
console.log('JD observation entry: separate new body, original job identity, unknown publication date, retained per-job draft and manual source boundary passed.');
}

{
const oldRead=result('old-current',stamp(1),{question_id:'q',result:{status:'completed',claims:[],evidence:[{id:'ev-old',job_id:'updated-job',title:'Original raw source',quote:'<old>Complete old condition.</old>'}],audit:{changed_sources:[{evidence_id:'ev-old',reason:'job_current_version_changed',retained_evidence_valid:true}]}}});
const unrelatedRead=result('unrelated-read',stamp(4),{question_id:'another-q',result:{status:'completed',claims:[],evidence:[{id:'ev-new',job_id:'updated-job',quote:'Current raw.'}],audit:{changed_sources:[]}}});
const reviewQuestion={...question,state:'answered',conclusion:'Retain this old qualified conclusion.',conclusion_step_id:'old-current',selected_job_ids:['updated-job']};
const reviewData={...data,questions:[reviewQuestion],jobs:[{id:'updated-job',current:{title:'Updated role <check>'}}],results:[unrelatedRead,oldRead]};
const reviewBefore=JSON.stringify(reviewData);
const changes=ctx.window.journeyTest.questionSourceChanges(reviewQuestion,reviewData);
assert.equal(changes.length,1);assert.equal(changes[0].study.step_id,'old-current');
const markup=ctx.window.journeyTest.sourceFollowups(reviewData);
assert.ok(markup.includes('Updated role &lt;check&gt;')&&markup.includes('&lt;old&gt;Complete old condition.'));
assert.ok(markup.includes('data-career-review-sources="q"')&&markup.includes('Retain this old qualified conclusion.'));
const readOnly=ctx.window.journeyTest.sourceFollowups(reviewData,true);
assert.ok(!readOnly.includes('<button')&&!readOnly.includes('data-career-show-source-change'));
const historical=result('intentional-history',stamp(5),{question_id:'q',result:{status:'completed',claims:[],evidence:[{id:'ev-history',job_id:'updated-job',quote:'Selected old cutoff.'}],audit:{changed_sources:[],historical_sources:[{evidence_id:'ev-history',current_version_differs:true}]}}});
assert.equal(ctx.window.journeyTest.questionSourceChanges(reviewQuestion,{...reviewData,results:[historical,...reviewData.results]}).length,1);
const fresh=result('rechecked',stamp(6),{question_id:'q',result:{status:'completed',claims:[],evidence:[{id:'ev-current',job_id:'updated-job',quote:'Actually read current source.'}],audit:{changed_sources:[]}}});
assert.equal(ctx.window.journeyTest.questionSourceChanges(reviewQuestion,{...reviewData,results:[fresh,...reviewData.results]}).length,0);
assert.equal(ctx.window.journeyTest.sourceFollowups({...reviewData,questions:[{...reviewQuestion,state:'parked'}]}),'');
assert.equal(ctx.window.journeyTest.questionSourceChanges({...reviewQuestion,id:undefined},reviewData).length,0);
const invalid={...oldRead,result:{...oldRead.result,audit:{changed_sources:[{evidence_id:'ev-old',reason:'source_integrity_or_reference_changed',retained_evidence_valid:false}]}}};
assert.equal(ctx.window.journeyTest.questionSourceChanges(reviewQuestion,{...reviewData,results:[invalid]}).length,0);
const draft=ctx.window.journeyTest.sourceReviewDraft(reviewQuestion);
assert.equal(draft.question_id,'q');assert.deepEqual(Array.from(draft.selected_job_ids),['updated-job']);assert.equal(draft.source_step_id,'');
assert.equal(JSON.stringify(reviewData),reviewBefore);
console.log('Source followup: changed valid original citations, unrelated inquiries, intentional history, fresh source rereads, preserved conclusions and safe export passed.');
}

{
const previousUnderstanding={id:'rev-old',question_id:'q',current_view:'Original understanding. '.repeat(45)+'FINAL OLD CONDITION',previous_view:'Initial idea.',observation:'Old supplied observation.',open_question:'Old unknown.',use_for_research:true};
const quoteText='New cited source. '.repeat(130)+'FINAL SOURCE CONDITION';
const reviseStudy=result('rev-study',stamp(4),{question_id:'q',task_id:'current-task',result:{status:'completed',claims:[{text:'New qualified interpretation.',basis:'inference',category:'task',requirement:'unspecified',evidence_ids:['rev-ev']}],evidence:[{id:'rev-ev',title:'Original supplied source <check>',quote:quoteText},{id:'unused-ev',title:'Unused preview',quote:'UNUSED SOURCE MUST NOT BE DRAFTED'}],gaps:['Need a counterexample with a final condition.']}});
const revisionData={...data,insights:[previousUnderstanding,{...previousUnderstanding,id:'foreign-note',question_id:'other',current_view:'FOREIGN UNDERSTANDING'}],results:[reviseStudy]};
const revisionBefore=JSON.stringify(revisionData);
ctx.window.journeyTest.setDraft(revisionData,{question_answers:{q:{step_id:'rev-study'}}});
const unchosen=ctx.window.journeyTest.answerRevisionChoice(question,reviseStudy,revisionData);
assert.ok(unchosen.includes('disabled')&&!unchosen.includes('FOREIGN UNDERSTANDING'));
ctx.window.journeyTest.setDraft(revisionData,{question_answers:{q:{step_id:'rev-study',revision_note_id:'rev-old'}}});
const chosen=ctx.window.journeyTest.answerRevisionChoice(question,reviseStudy,revisionData);
assert.ok(chosen.includes('value="rev-old" selected')&&!chosen.includes(' disabled'));
const revision=ctx.window.journeyTest.answerRevisionDraft(question,reviseStudy,previousUnderstanding);
assert.equal(revision.replaces_insight_id,'rev-old');assert.equal(revision.source_step_id,'rev-study');assert.equal(revision.source_claim_index,null);
assert.equal(revision.previous_view,previousUnderstanding.current_view);assert.equal(revision.task_id,'current-task');assert.equal(revision.question_id,'q');
assert.ok(revision.observation.includes('FINAL SOURCE CONDITION')&&!revision.observation.includes('UNUSED SOURCE MUST NOT BE DRAFTED'));
assert.ok(revision.current_view.includes('New qualified interpretation.')&&revision.current_view.includes('Need a counterexample with a final condition.'));
assert.ok(ctx.window.journeyTest.insightLengthNotice(revision));
assert.equal(revision.open_question,'Need a counterexample with a final condition.');
const preferredSource={...reviseStudy,result:{...reviseStudy.result,claims:[{...reviseStudy.result.claims[0],basis:'direct',requirement:'preferred',text:'Business background, with the original condition.'}]}};
assert.ok(ctx.window.journeyTest.answerRevisionDraft(question,preferredSource,previousUnderstanding).current_view.includes('加分'));

assert.ok(!ctx.window.journeyTest.questionAnswer(question,revisionData,true).includes('data-career-revise-answer'));
assert.equal(JSON.stringify(revisionData),revisionBefore);
console.log('Answer to revised understanding: explicitly selected prior record, full old view and cited source, original limits, new discussion link and unchanged stored records passed.');
}

{
ctx.window.journeyTest.setDraft(data,{});
assert.equal(ctx.window.journeyTest.conversationNoteEditor(data),'');
const completeReply='Reported statement <source>. '.repeat(160)+'FINAL REPORTED QUALIFICATION';
const interviewDraft={question_id:'q',asked_question:'Who accepts the output?',answer:completeReply,wording:'paraphrased',speaker:'A reported role <check>',context:'Only one conversation.',said_when:'Exact date unknown.',limits:'Team work does not establish personal authority.'};
ctx.window.journeyTest.setDraft(data,{conversation_note:interviewDraft});
const interviewHtml=ctx.window.journeyTest.conversationNoteEditor(data);
assert.ok(interviewHtml.includes('FINAL REPORTED QUALIFICATION')&&interviewHtml.includes('Team work does not establish personal authority.'));
assert.ok(interviewHtml.includes('A reported role &lt;check&gt;')&&!interviewHtml.includes('<source>.'));
assert.ok(interviewHtml.includes('value="paraphrased" selected')&&interviewHtml.includes('Exact date unknown.'));
assert.ok(interviewHtml.includes('name="question_id" value="q"'));
assert.ok(!ctx.window.journeyTest.conversationNoteEditor(data).includes('name="state"'));
assert.ok(ctx.window.journeyTest.conversationNoteEditor({...data,running:true}).includes('disabled'));
console.log('Reported conversation entry: full reply and final qualification, explicit paraphrase, user supplied date, inquiry link and escaped source text passed.');
}

{
const recentData={...data,results:[result('ended',stamp(8),{state:'abandoned'}),result('last-complete',stamp(7)),result('unfinished',stamp(6),{state:'interrupted',result:{status:'incomplete'}})]};
assert.equal(ctx.window.journeyTest.recentResearch(recentData).step_id,'unfinished');
assert.equal(ctx.window.journeyTest.recentResearch({...recentData,results:recentData.results.slice(0,2)}).step_id,'last-complete');
assert.equal(ctx.window.journeyTest.recentResearch({...data,results:[]}),undefined);
const shortcuts=ctx.window.journeyTest.workspaceShortcuts({...data,results:[]});
assert.ok(shortcuts.includes('data-career-workspace-jump="recent" disabled'));
assert.ok(shortcuts.includes('data-career-workspace-jump="inquiry"')&&shortcuts.includes('data-career-workspace-jump="questions"'));
console.log('Workspace navigation: unfinished research stays reachable, abandoned rows do not become the latest result, and empty workspaces retain question entry.');
}

const branchParent={id:'parent-inquiry',question:'Who accepts this work?',state:'answered',conclusion:'Saved user view. '+('Only local observations. '.repeat(120))+'Final condition: cross-team production authority unknown.',next_evidence:'Ask the actual accepting party.',selected_job_ids:['second-job'],conclusion_step_id:'chosen-parent-answer',hypothesis_a:'Advice only.',hypothesis_b:'A limited acceptance role.'};
const branchChild={id:'child-inquiry',parent_question_id:branchParent.id,question:'<script>What would distinguish these roles?</script>',state:'open',conclusion:''};
const branchOther={id:'other-inquiry',parent_question_id:branchChild.id,question:'Grandchild should not be pulled into the parent list.',state:'parked'};
const branchData={...data,questions:[branchParent,branchChild,branchOther],results:[]};
const branchBefore=JSON.stringify(branchData);
const branchDraft=ctx.window.journeyTest.branchQuestionDraft(branchParent,branchData);
assert.equal(branchDraft.parent_question_id,branchParent.id);
assert.equal(branchDraft.source_step_id,'chosen-parent-answer');
assert.deepEqual(Array.from(branchDraft.selected_job_ids),['second-job']);
assert.equal(branchDraft.question,'');assert.equal(branchDraft.conclusion,'');assert.equal(branchDraft.state,'open');
assert.equal(branchDraft.conclusion_step_id,'');
const branchParentHtml=ctx.window.journeyTest.questionBranches(branchParent,branchData);
assert.ok(branchParentHtml.includes('从这里继续追问 · 1')&&branchParentHtml.includes('#career/goal/investigate/child-inquiry'));
assert.ok(!branchParentHtml.includes(branchOther.question));
assert.ok(branchParentHtml.includes('&lt;script&gt;What would distinguish')&&!branchParentHtml.includes('<script>'));
const branchChildExport=ctx.window.journeyTest.questionBranches(branchChild,branchData,true);
assert.ok(branchChildExport.includes(branchParent.conclusion)&&branchChildExport.includes(branchParent.next_evidence));
assert.ok(branchChildExport.includes('Advice only.')&&branchChildExport.includes('A limited acceptance role.'));
assert.ok(!branchChildExport.includes('<a ')&&!branchChildExport.includes('<button'));
assert.ok(ctx.window.journeyTest.questionJourneyPackage(branchChild,branchData).includes(branchParent.conclusion));
assert.equal(JSON.stringify(branchData),branchBefore);
console.log('Follow-up inquiries: explicit parent and scope, no adopted conclusion, full parent limits, direct navigation, escaped text and read-only export passed.');

const returnParent={...branchParent,selected_job_ids:[]},returnChild={...branchChild,selected_job_ids:['second-job']};
const returnChosen=result('chosen-child-answer',stamp(3),{question_id:returnChild.id,user_question:'Selected earlier <script>question</script>.',selected_job_ids:['second-job'],task_id:'child-task'});
const returnLater=result('later-child-answer',stamp(5),{question_id:returnChild.id,user_question:'Later answer is not selected.'});
const returnData={...branchData,questions:[returnParent,returnChild],results:[returnLater,returnChosen]};
const returnBefore=JSON.stringify(returnData);
const returnDraft=ctx.window.journeyTest.returnInquiryDraft(returnChild,returnChosen,returnData);
assert.equal(returnDraft.question_id,returnParent.id);assert.equal(returnDraft.source_step_id,returnChosen.step_id);
assert.deepEqual(Array.from(returnDraft.selected_job_ids),[]); // The parent covers all jobs; the chosen child covered one.
assert.equal(returnDraft.task_id,'');assert.equal(returnDraft.story_id,'');assert.equal(returnDraft.insight_id,'');
assert.ok(returnDraft.question.includes('原文')&&returnDraft.question.includes('不能确定'));
assert.equal(ctx.window.journeyTest.returnInquiryDraft(returnChild,{...returnChosen,current:false},returnData),null);
assert.equal(ctx.window.journeyTest.returnInquiryDraft(returnChild,{...returnChosen,state:'abandoned'},returnData),null);
assert.equal(ctx.window.journeyTest.returnInquiryDraft(returnParent,returnChosen,returnData),null);
const returnOrigin=ctx.window.journeyTest.returnedInquirySource(returnDraft,returnData);
assert.ok(returnOrigin.includes(returnParent.question)&&returnOrigin.includes('Selected earlier &lt;script&gt;question&lt;/script&gt;.'));
assert.ok(returnOrigin.includes('#career/goal/discussion/chosen-child-answer')&&!returnOrigin.includes(returnLater.user_question));
const returnExport=ctx.window.journeyTest.returnedInquirySource(returnDraft,returnData,true);
assert.ok(!returnExport.includes('<a ')&&!returnExport.includes('<button')&&!returnExport.includes('<script>'));
ctx.window.journeyTest.setDraft(returnData,{question_answers:{[returnChild.id]:{step_id:returnChosen.step_id,open:true}}});
const returnAnswer=ctx.window.journeyTest.questionAnswer(returnChild,returnData);
assert.ok(returnAnswer.includes('data-career-return-inquiry="child-inquiry:chosen-child-answer"'));
assert.ok(!returnAnswer.includes('data-career-return-inquiry="child-inquiry:later-child-answer"'));
assert.equal(JSON.stringify(returnData),returnBefore);
console.log('Return investigation: exact chosen answer, parent job scope, no inherited child task, escaped source link, stale history and read-only export passed.');

const carriedDiscussionQuestion={...question,reused_from:{project_id:'old-goal',project_title:'Old <goal>',kind:'discussion',record_id:'old-step'},carried_understanding:{recorded_at:stamp(1),notice:'Historical analysis, not current facts.',research_review_status:'rejected',source_jobs:[{id:'old-job',title:'Old role',company:'Old team'}],research_claims:[{category:'ability',basis:'inference',requirement:'preferred',text:'Only preferred. '+('Full old condition. '.repeat(90))+'FINAL LIMIT <script>not executed</script>'}],research_gaps:['Actual ownership unverified.'],source_references:[{title:'Old material',public_document_id:'old-doc',evidence_kind:'work_material'},{title:'Old JD',job_id:'old-job',document_id:'old-jd'}]}};
const carriedBefore=JSON.stringify(carriedDiscussionQuestion),carriedData={...data,jobs:[{id:'new-job'}],document_ids:[]};
const carriedHtml=ctx.window.journeyTest.carriedDiscussion(carriedDiscussionQuestion,carriedData);
assert.ok(carriedHtml.includes('历史Agent分析')&&carriedHtml.includes('原研究未通过质量核对'));
assert.ok(carriedHtml.includes('加分')&&carriedHtml.includes('研究推断')&&carriedHtml.includes('FINAL LIMIT &lt;script&gt;'));
assert.ok(carriedHtml.includes('未选入当前目标')&&carriedHtml.includes('未自动带入当前资料'));
assert.ok(carriedHtml.includes('data-career-attach-material="old-doc"')&&carriedHtml.includes('data-source="old-jd"'));
const carriedExport=ctx.window.journeyTest.carriedDiscussion(carriedDiscussionQuestion,carriedData,true);
assert.ok(carriedExport.includes('Actual ownership unverified.')&&!carriedExport.includes('<button')&&!carriedExport.includes('<a '));
assert.ok(!carriedExport.includes('<script>'));
const attachedCarried=ctx.window.journeyTest.carriedDiscussion(carriedDiscussionQuestion,{...carriedData,document_ids:['old-doc']});
assert.ok(attachedCarried.includes('已选入当前资料')&&!attachedCarried.includes('data-career-attach-material'));
assert.equal(JSON.stringify(carriedDiscussionQuestion),carriedBefore);
const historicalMap={scope_note:'Old map scope.',work_types:[{name:'Old work',problem:'Old problem',tasks:'Old tasks',deliverables:'Old deliverables',boundary:'Only a local exercise.',next_check:'Verify actual ownership.',basis:'inference',claim_indices:[0]}],work_relations:[{source_text:'Old task',predicate:'requires',target_text:'Old ability',rationale:'Old rationale.',transfer_limit:'Full boundary. '.repeat(95)+'FINAL MAP LIMIT <script>',basis:'inference',claim_indices:[0]}],ability_relations:[],comparisons:[],unknowns:['Production acceptance still unknown.']};
const mappedDiscussion={...carriedDiscussionQuestion,carried_understanding:{...carriedDiscussionQuestion.carried_understanding,work_map:historicalMap}};
const mappedBefore=JSON.stringify(mappedDiscussion);
for(const exporting of [false,true]){
  const mapped=ctx.window.journeyTest.carriedDiscussion(mappedDiscussion,carriedData,exporting);
  assert.ok(mapped.includes('Old map scope.')&&mapped.includes('Old rationale.')&&mapped.includes('Only a local exercise.'));
  assert.ok(mapped.includes('FINAL MAP LIMIT &lt;script&gt;')&&mapped.includes('Production acceptance still unknown.'));
  assert.ok(!mapped.includes('当时保存的引用')&&!mapped.includes('<script>'));
}
assert.equal(JSON.stringify(mappedDiscussion),mappedBefore);
console.log('Historical discussion transfer: original basis and preferred conditions, full final limits, separate scopes, explicit source attachment, rejected-review label and safe read-only export passed.');

const synthesisQuestionA={...question,id:'synthesis-q1',question:'Original <question A>'},synthesisQuestionB={...question,id:'synthesis-q2',question:'Original question B'};
const synthesisAnswerA={...old,step_id:'synthesis-answer-a',question_id:synthesisQuestionA.id,current:false},synthesisAnswerB={...old,created_at:stamp(3),step_id:'synthesis-answer-b',question_id:synthesisQuestionB.id};
const synthesisData={...data,questions:[synthesisQuestionA,synthesisQuestionB],results:[synthesisAnswerB,synthesisAnswerA]};
ctx.window.journeyTest.setDraft(synthesisData,{synthesis:{open:true,question:'Connect full conditions <script>.',question_ids:[synthesisQuestionA.id,synthesisQuestionB.id]}});
const synthesisBefore=JSON.stringify(synthesisData),synthesisPanel=ctx.window.journeyTest.synthesisPanel(synthesisData);
assert.ok(synthesisPanel.includes('career-synthesis')&&synthesisPanel.includes('目前选了 2 个'));
assert.ok(synthesisPanel.includes('Original &lt;question A&gt;')&&synthesisPanel.includes('Connect full conditions &lt;script&gt;.'));
assert.ok(synthesisPanel.includes('使用前需重核')&&synthesisPanel.includes('原问题的结论与状态由你决定'));
assert.ok(!ctx.window.journeyTest.synthesisPanel({...synthesisData,questions:[synthesisQuestionA]}));
const synthesized={...old,synthesis_sources:[{question_id:synthesisQuestionA.id,step_id:synthesisAnswerA.step_id},{question_id:synthesisQuestionB.id,step_id:synthesisAnswerB.step_id}]};
const synthesisSources=ctx.window.journeyTest.synthesisSources(synthesized,synthesisData);
assert.ok(synthesisSources.includes('本轮综合了 2 个')&&synthesisSources.includes('/discussion/synthesis-answer-a'));
assert.ok(synthesisSources.includes('Original &lt;question A&gt;')&&synthesisSources.includes('使用前需重核'));
const synthesisExport=ctx.window.journeyTest.synthesisSources(synthesized,synthesisData,true);
assert.ok(synthesisExport.includes('Original question B')&&!synthesisExport.includes('<a ')&&!synthesisExport.includes('<button'));
assert.equal(JSON.stringify(synthesisData),synthesisBefore);
console.log('Inquiry synthesis: editable multi-question selection, exact source discussion links, historical scope, escaped read-only export and unchanged original records passed.');

const jointQuote={id:'joint-quote',title:'Original <material>',quote:'Business background is preferred <script>.',evidence_kind:'work_material',public_document_id:'joint-doc',start:0,end:40};
const jointStudy={...result('joint-study',stamp(4)),synthesis_sources:synthesized.synthesis_sources,result:{status:'completed',claims:[{category:'task',basis:'synthesis',requirement:'unspecified',text:'First complete joint condition.',evidence_ids:['joint-quote']},{category:'ability',basis:'direct',requirement:'preferred',text:'SECOND JOINT CLAIM: preferred only.',evidence_ids:['joint-quote']}],evidence:[jointQuote],gaps:['Authority is still unknown.']}};
const wholeLearning={id:'whole-learning',source_step_id:jointStudy.step_id,source_claim_index:null,created_at:stamp(5),current_view:'Original whole understanding.',use_for_research:false};
const revisedWhole={id:'revised-whole',replaces_insight_id:wholeLearning.id,created_at:stamp(6),current_view:'A narrower condition, not a universal conclusion.',use_for_research:true};
const narrowedWhole={...revisedWhole,id:'narrowed-whole',question_id:synthesisQuestionA.id};
const wholeData={...synthesisData,results:[jointStudy,...synthesisData.results],insights:[wholeLearning,revisedWhole,narrowedWhole],tasks:[]},wholeBefore=JSON.stringify(wholeData);
const wholeLinks=ctx.window.journeyTest.learningInquiryLinks(wholeLearning,wholeData),revisedLinks=ctx.window.journeyTest.learningInquiryLinks(revisedWhole,wholeData);
assert.deepEqual(Array.from(wholeLinks,row=>row.question_id),[synthesisQuestionA.id,synthesisQuestionB.id]);
assert.ok(wholeLinks.every(row=>row.via==='synthesis'&&!row.inherited));
assert.deepEqual(Array.from(revisedLinks,row=>row.question_id),[synthesisQuestionA.id,synthesisQuestionB.id]);
assert.ok(revisedLinks.every(row=>row.inherited));
assert.deepEqual(Array.from(ctx.window.journeyTest.learningInquiryLinks(narrowedWhole,wholeData),row=>row.question_id),[synthesisQuestionA.id]);
const wholeScopeHtml=ctx.window.journeyTest.learningInquiryContext(revisedLinks,wholeData.id,true);
assert.ok(wholeScopeHtml.includes('Original &lt;question A&gt;')&&wholeScopeHtml.includes('从被接替认识保留')&&wholeScopeHtml.includes('不表示认识适用于每个问题'));
assert.ok(!wholeScopeHtml.includes('<a '));
const wholeSource=ctx.window.journeyTest.insightSource(wholeLearning,wholeData,true);
assert.ok(wholeSource.includes('First complete joint condition.')&&wholeSource.includes('SECOND JOINT CLAIM: preferred only.'));
assert.ok(wholeSource.includes('Business background is preferred &lt;script&gt;.')&&!wholeSource.includes('<button')&&!wholeSource.includes('<script>'));
const sharedJourney=ctx.window.journeyTest.questionJourneyRecords(synthesisQuestionB,wholeData);
assert.ok(sharedJourney.studies.some(row=>row.step_id===jointStudy.step_id));
assert.deepEqual(Array.from(sharedJourney.insights,row=>row.id),[wholeLearning.id,revisedWhole.id]);
assert.equal(JSON.stringify(wholeData),wholeBefore);
console.log('Synthesis learning: whole-source qualifiers, linked inquiries, inherited revision context, single-inquiry scope, shared journey, safe export and unchanged stored records passed.');

const groupJobs=Array.from({length:6},(_,i)=>({id:'group-job-'+i,current:{title:'Current <role '+i+'>',company_name_raw:'Team '+i}}));
const groupIds=groupJobs.map(row=>row.id),groupEvidence=groupJobs.map((job,i)=>({id:'group-ev-'+i,job_id:job.id,document_id:'group-doc-'+i,title:'Raw role '+i,quote:'Full raw condition '+i+' <script>.',start:0,end:35,evidence_kind:'job_document'}));
const publicGroupEvidence={id:'public-group-ev',public_document_id:'public-group-doc',title:'Company material',quote:'A platform feature, not an individual responsibility.',start:0,end:56,evidence_kind:'work_material'};
const groupClaims=[...groupJobs.map((job,i)=>({category:'task',basis:'direct',requirement:'unspecified',text:'SINGLE TASK '+i,evidence_ids:[groupEvidence[i].id]})),{category:'ability',basis:'direct',requirement:'preferred',text:'PREFERRED ONLY '+('Full condition. '.repeat(90))+'FINAL PREFERRED LIMIT',evidence_ids:[groupEvidence[1].id]},{category:'task',basis:'inference',requirement:'unspecified',text:'MIXED ROLE ZERO AND FIVE',evidence_ids:[groupEvidence[0].id,groupEvidence[5].id]},{category:'business',basis:'direct',requirement:'unspecified',text:'UNASSIGNED COMPANY FACT',evidence_ids:[publicGroupEvidence.id]}];
const groupStudy={...result('group-study',stamp(5)),kind:'role',selected_job_ids:[],user_question:'Chosen six-role study',result:{status:'completed',claims:groupClaims,evidence:[...groupEvidence,publicGroupEvidence],gaps:[],scope:{jobs:groupJobs.map((job,i)=>({id:job.id,title:'Original role '+i,company:'Original team '+i}))}}};
const groupData={...data,jobs:groupJobs,results:[groupStudy],requirements:[{category:'task',text:'Different recent study',evidence:[]}],insights:[]},groupBefore=JSON.stringify(groupData);
ctx.window.journeyTest.setDraft(groupData,{compare_jobs:groupIds,compare_step_id:groupStudy.step_id});
assert.deepEqual(Array.from(ctx.window.journeyTest.compareJobs(groupData),row=>row.id),groupIds);
assert.deepEqual(Array.from(ctx.window.journeyTest.comparisonJobIds(groupStudy)),groupIds);
const groupHtml=ctx.window.journeyTest.jobComparison(groupData);
assert.equal((groupHtml.match(/data-career-compare-job=/g)||[]).length,6);
assert.ok(groupHtml.includes('并排看清 6 个岗位')&&!groupHtml.includes('data-career-compare-add'));
assert.ok(groupHtml.includes('class="career-comparison-columns-6"')&&!groupHtml.includes('<table style='));
assert.ok(groupHtml.includes('Original role 0')&&groupHtml.includes('FINAL PREFERRED LIMIT')&&groupHtml.includes('加分'));
assert.ok(groupHtml.includes('MIXED ROLE ZERO AND FIVE')&&groupHtml.includes('UNASSIGNED COMPANY FACT')&&!groupHtml.includes('Different recent study'));
const groupQuestion=ctx.window.journeyTest.comparisonQuestionDraft(groupData);
assert.deepEqual(Array.from(groupQuestion.selected_job_ids),groupIds);
assert.equal(groupQuestion.source_step_id,groupStudy.step_id);
assert.equal(groupQuestion.parent_question_id,null);
assert.ok(groupQuestion.question.includes('6个岗位')&&groupQuestion.question.includes('加分')&&groupQuestion.question.length<1500);
const groupPackage=ctx.window.journeyTest.jobComparisonPackage(groupData);
assert.ok(groupPackage.startsWith('<!doctype html>')&&groupPackage.includes('FINAL PREFERRED LIMIT')&&groupPackage.includes('Full raw condition 5 &lt;script&gt;.'));
assert.ok(!groupPackage.includes('<button')&&!groupPackage.includes('<script>')&&!groupPackage.includes('data-career-compare-question'));
ctx.window.journeyTest.setDraft(groupData,{compare_jobs:groupIds.slice(0,2),compare_step_id:groupStudy.step_id});
const narrowedGroup=ctx.window.journeyTest.jobComparison(groupData);
assert.equal((narrowedGroup.match(/data-career-compare-job=/g)||[]).length,2);
assert.ok(narrowedGroup.includes('Original role 5')&&narrowedGroup.includes('（未列在本表中）')&&narrowedGroup.includes('MIXED ROLE ZERO AND FIVE'));
const withoutOldRole={...groupData,jobs:groupJobs.slice(0,2)};
const historicalMixed=ctx.window.journeyTest.jobComparison(withoutOldRole);
assert.ok(historicalMixed.includes('MIXED ROLE ZERO AND FIVE'));
const bodyCells=historicalMixed.slice(historicalMixed.indexOf('<tbody>'),historicalMixed.indexOf('</tbody>'));
assert.ok(!bodyCells.includes('MIXED ROLE ZERO AND FIVE')&&!bodyCells.includes('UNASSIGNED COMPANY FACT'));
assert.ok(ctx.window.journeyTest.researchScope(groupStudy,groupData).includes('范围中的 6 个岗位'));
assert.ok(!ctx.window.journeyTest.researchScope(groupStudy,withoutOldRole).includes('data-career-job-comparison'));
assert.equal(JSON.stringify(groupData),groupBefore);
console.log('Multi-role comparison: six columns, exact saved inquiry scope, historical source names, complete preferred limits, mixed and unassigned source boundaries, safe portable export and unchanged stored studies passed.');

const longSourceQuote={id:'long-source-ev',job_id:'original-role',document_id:'original-doc',title:'Original role source',quote:'Original preferred condition <script>.',start:0,end:38};
const longSource={...result('chosen-long-source',stamp(1)),kind:'map',selected_job_ids:['original-role'],user_question:'Chosen original discussion.',result:{status:'completed',claims:[{category:'business',basis:'inference',requirement:'unspecified',text:'Full old reasoning. '.repeat(70)+'FINAL OLD LIMIT <script>.',evidence_ids:['long-source-ev']},{category:'ability',basis:'direct',requirement:'preferred',text:'Original preferred qualification.',evidence_ids:['long-source-ev']}],gaps:['Original unresolved ownership.'],evidence:[longSourceQuote],scope:{jobs:[{id:'original-role',title:'Original <role>',company:'Original team'}]},work_map:historicalMap,application_plan:{actions:[{title:'Original proposal',task_or_ability:'Small sample check',deliverable:'Planned log',hypothesis:'Not yet performed.',completion_check:'Full check. '.repeat(50)+'FINAL PROPOSAL LIMIT <script>.',assumptions:['Local samples only.']}],open_questions:['What changes outside the sample?']}}};
const laterSource={...longSource,step_id:'later-long-source',created_at:stamp(3),user_question:'A newer discussion must not replace the chosen one.'};
const longFollowup={...result('long-followup',stamp(4)),source_step_id:longSource.step_id,selected_job_ids:['current-role']};
const continuationData={...data,jobs:[{id:'current-role',current:{title:'Current role'}}],results:[longFollowup,laterSource,longSource],questions:[]},continuationBefore=JSON.stringify(continuationData);
const continuationHtml=ctx.window.journeyTest.continuedDiscussion(longFollowup,continuationData);
assert.ok(continuationHtml.includes('Chosen original discussion.')&&!continuationHtml.includes(laterSource.user_question));
assert.ok(continuationHtml.includes('FINAL OLD LIMIT &lt;script&gt;.')&&continuationHtml.includes('FINAL MAP LIMIT &lt;script&gt;'));
assert.ok(continuationHtml.includes('Original &lt;role&gt;')&&!continuationHtml.includes('Current role'));
assert.ok(continuationHtml.includes('Original preferred qualification.')&&continuationHtml.includes('加分'));
assert.ok(continuationHtml.includes('FINAL PROPOSAL LIMIT &lt;script&gt;.')&&continuationHtml.includes('建议不能证明已经执行'));
assert.ok(continuationHtml.includes('/discussion/chosen-long-source')&&!continuationHtml.includes('/discussion/later-long-source'));
const continuationExport=ctx.window.journeyTest.continuedDiscussion(longFollowup,continuationData,true);
assert.ok(continuationExport.includes('Original unresolved ownership.')&&continuationExport.includes('What changes outside the sample?'));
assert.ok(!continuationExport.includes('<button')&&!continuationExport.includes('<a ')&&!continuationExport.includes('<script>'));
const clearedContinuation=ctx.window.journeyTest.continuedDiscussion(longFollowup,{...continuationData,results:[laterSource,{...longSource,result:null}]});
assert.ok(clearedContinuation.includes('原讨论已不可用')&&!clearedContinuation.includes('FINAL OLD LIMIT')&&!clearedContinuation.includes(laterSource.user_question));
assert.equal(JSON.stringify(continuationData),continuationBefore);
console.log('Discussion continuation: exact selected source, full old limits and map, distinct original scope, planned versus observed work, safe complete export and unavailable-source boundaries passed.');

const observationRows=Array.from({length:4},(_,i)=>({observation_id:'observation-'+i,snapshot_id:i===2?'snapshot-a':i===0?'snapshot-a':'snapshot-'+i,observed_at:stamp(i),processed_at:stamp(i),read_as_of:stamp(i),data_kind:'synthetic',mode:'manual'}));
const observationEvidence=observationRows.map((row,i)=>({...row,id:row.snapshot_id+':0:20',job_id:'observed-job',document_id:'observed-doc-'+i,title:'Saved original '+i,quote:i===2?'Original A <script>.':i===0?'Original A <script>.':'Original '+i+' condition.',start:0,end:20}));
const selectedObservationPair={status:'compared',before:observationRows[0],after:observationRows[1],observations:observationRows,evidence:observationEvidence.slice(0,2),changes:[{field:'description',before:'Old A',after:'Old B'}],description_diff:'-Old A\n+Old B'};
const observedJob={id:'observed-job',current:{title:'Observed role',company_name_raw:'Synthetic team'}},observationData={...data,jobs:[observedJob],results:[],questions:[]};
ctx.window.journeyTest.setDraft(observationData,{job_changes:{job_id:observedJob.id,open:true,observations:observationRows,comparison:selectedObservationPair,before_observation_id:observationRows[0].observation_id,after_observation_id:observationRows[1].observation_id}});
const observationHtml=ctx.window.journeyTest.jobChanges(observationData);
assert.ok(observationHtml.includes('data-career-change-before')&&observationHtml.includes('data-career-change-after')&&observationHtml.includes('data-career-compare-observations'));
assert.ok(observationHtml.includes('详情内容与记录 1 一致')&&observationHtml.includes('保存为变化调查'));
const observationQuestion=ctx.window.journeyTest.jobChangeInquiry(observedJob,selectedObservationPair);
assert.equal(observationQuestion.source_passage.document_id,'observed-doc-0');
assert.equal(observationQuestion.after_passage.document_id,'observed-doc-1');
assert.ok(observationQuestion.next_evidence.includes(observationRows[0].read_as_of)&&observationQuestion.next_evidence.includes(observationRows[1].read_as_of)&&!observationQuestion.next_evidence.includes(observationRows[2].read_as_of));
const identicalObservationPair={...selectedObservationPair,after:observationRows[2],evidence:[observationEvidence[0],observationEvidence[2]],changes:[],description_diff:''};
assert.deepEqual(Array.from(ctx.window.journeyTest.historySideEvidence(identicalObservationPair,observationRows[0]),row=>row.document_id),['observed-doc-0']);
assert.deepEqual(Array.from(ctx.window.journeyTest.historySideEvidence(identicalObservationPair,observationRows[2]),row=>row.document_id),['observed-doc-2']);
ctx.window.journeyTest.setDraft(observationData,{job_changes:{job_id:observedJob.id,open:true,observations:observationRows,comparison:identicalObservationPair}});
const unchangedObservationHtml=ctx.window.journeyTest.jobChanges(observationData);
assert.ok(unchangedObservationHtml.includes('选中的两次详情内容一致')&&!unchangedObservationHtml.includes('data-career-save-job-change'));
assert.ok(!unchangedObservationHtml.includes('其他来源字段存在差异')&&unchangedObservationHtml.includes('Original A &lt;script&gt;.'));
assert.throws(()=>ctx.window.journeyTest.jobChangeInquiry(observedJob,identicalObservationPair),/内容一致/);
console.log('Observation selection: exact earlier records, repeated-content labels, separate occurrences of the same original, fixed source cutoffs and honest no-change display passed.');

const updatedMaterial={id:'new-material',title:'<updated note>',publisher:'Synthetic',full_text_length:90,evidence_kind:'work_material',related_document_ids:['first-material','middle-material','new-material']};
const materialData={...data,questions:[{...question,id:'material-question',selected_job_ids:['chosen-job'],source_step_id:'cited-material'}, {...question,id:'passage-question',source_passage:{public_document_id:'middle-material'}}, {...question,id:'foreign-material-question'}],materials:[updatedMaterial],results:[result('cited-material',stamp(2),{result:{status:'completed',claims:[],evidence:[{public_document_id:'first-material'}],gaps:[]}}),result('unrelated-material',stamp(3),{question_id:'foreign-material-question',result:{status:'completed',claims:[],evidence:[{public_document_id:'other-material'}],gaps:[]}})],tasks:[],insights:[]};
const materialBefore=JSON.stringify(materialData);
assert.deepEqual(Array.from(ctx.window.journeyTest.materialQuestions(updatedMaterial,materialData),row=>row.id),['material-question','passage-question']);
const materialDraft=ctx.window.journeyTest.materialInquiryDraft(updatedMaterial,materialData.questions[0]);
assert.equal(materialDraft.material_id,'new-material');assert.equal(materialDraft.question_id,'material-question');assert.equal(materialDraft.selected_job_ids[0],'chosen-job');
assert.equal(materialDraft.source_step_id,'');assert.ok(materialDraft.question.includes('未回读的旧原文'));
assert.ok(ctx.window.journeyTest.materialInquiryDraft({...updatedMaterial,title:'x'.repeat(200)},{...question,question:'x'.repeat(1500)}).question.length<=1500);
ctx.window.journeyTest.setDraft(materialData,{material_revision:{document_id:'first-material',base_document_id:'new-material',material_title:'<title>',material_text:'<script>synthetic text</script>'}});
const materialHtml=ctx.window.journeyTest.materialShelf(materialData);
assert.ok(materialHtml.includes('引用过这份资料的 2 条调查')&&materialHtml.includes('data-career-material-review="new-material"'));
assert.ok(materialHtml.includes('data-career-edit-material="new-material"'));
assert.ok(materialHtml.includes('&lt;script&gt;synthetic text&lt;/script&gt;')&&!materialHtml.includes('<script>synthetic text'));
assert.ok(materialHtml.includes('其他目标由你分别决定是否更新'));
assert.ok(!ctx.window.journeyTest.materialShelf({...materialData,materials:[{...updatedMaterial,evidence_kind:'public_document'}]}).includes('data-career-edit-material="new-material"'));
assert.equal(JSON.stringify(materialData),materialBefore);
console.log('Corrected work material links saved source families to their actual inquiries and keeps editing drafts escaped.');

const viewA='Existing tools might only need configuration. '+('Limited to existing capabilities; '.repeat(12))+'Final qualifier: complex integration remains unknown.';
const viewB='Complex integration may require adapter development; authority remains unknown.';
const originalPassage={id:'pa',public_document_id:'source-a',title:'Configuration source',quote:'Only existing capabilities are described.',start:0,end:39,relation:'supports',target_view:viewA,user_note:'<check which conditions apply>'};
const alignedQuestion={...question,hypothesis_a:viewA,hypothesis_b:viewB,evidence_passages:[originalPassage,{...originalPassage,id:'pb',public_document_id:'source-b',relation:'conditions',target_view:viewB},{...originalPassage,id:'unknown',target_view:''}]};
const alignedData={...data,questions:[alignedQuestion]};
const alignedBefore=JSON.stringify(alignedQuestion);
let groups=ctx.window.journeyTest.passageGroups(alignedQuestion);
assert.deepEqual(Array.from(groups,row=>row.id),['a','b','other']);
assert.equal(groups[0].passages[0].id,'pa');assert.equal(groups[1].passages[0].id,'pb');assert.equal(groups[2].passages[0].id,'unknown');
ctx.window.journeyTest.setDraft(alignedData,{passage_editor:{id:'pa',question_id:'q',passage:originalPassage,relation:'supports',target_view:viewA,user_note:'<check which conditions apply>'}});
const alignmentEditor=ctx.window.journeyTest.passageEditor(alignedData);
assert.ok(alignmentEditor.includes('name="target_view"')&&alignmentEditor.includes('Final qualifier: complex integration remains unknown.'));
assert.ok(alignmentEditor.includes('data-career-passage-target="a"')&&alignmentEditor.includes('data-career-passage-target="b"'));
const alignmentMarkup=ctx.window.journeyTest.questionPassages(alignedQuestion,alignedData,true);
assert.ok(alignmentMarkup.includes('data-passage-group="a"')&&alignmentMarkup.includes('data-passage-group="b"'));
assert.ok(alignmentMarkup.includes('摘录条数不代表独立来源数量')&&alignmentMarkup.includes('&lt;check which conditions apply&gt;'));
assert.equal((alignmentMarkup.match(/data-question-passage="pa"/g)||[]).length,1);
const changedQuestion={...alignedQuestion,hypothesis_a:'A revised interpretation requiring fresh examination.'};
groups=ctx.window.journeyTest.passageGroups(changedQuestion);
assert.equal(groups[0].passages.length,0);assert.equal(groups[2].passages[0].target_view,viewA);
const changedMarkup=ctx.window.journeyTest.questionPassages(changedQuestion,alignedData,true);
assert.ok(changedMarkup.includes('原标注未自动转给新解释')&&changedMarkup.includes(viewA));
const alignmentPackage=ctx.window.journeyTest.questionJourneyPackage(changedQuestion,{...alignedData,questions:[changedQuestion]});
assert.ok(alignmentPackage.includes(viewA)&&alignmentPackage.includes('career-passage-hypotheses{display:grid'));
assert.ok(!alignmentPackage.includes('data-career-edit-passage')&&!alignmentPackage.includes('data-career-passage-target'));
const equalViews=ctx.window.journeyTest.passageGroups({...alignedQuestion,hypothesis_b:viewA});
assert.equal(equalViews[0].id,'ab');assert.equal(equalViews.filter(row=>row.view===viewA).length,1);
assert.equal(JSON.stringify(alignedQuestion),alignedBefore);
console.log('Evidence against concrete explanations: exact saved wording, separate A/B and unassigned groups, unchanged old targets, complete editor and safe portable export passed.');

const batchRow={id:'1',filename:'<source>.txt',title:'Synthetic source',text:'<script>bounded original</script>',source_name:'User supplied',read_state:'ready',include:true};
assert.equal(ctx.window.journeyTest.materialBatchReady(batchRow),true);
assert.equal(ctx.window.journeyTest.materialBatchReady({...batchRow,saved_document_id:'saved'}),false);
assert.equal(ctx.window.journeyTest.materialBatchReady({...batchRow,include:false}),false);
assert.equal(ctx.window.journeyTest.materialBatchReady({...batchRow,read_state:'error',read_error:'Cannot read'}),false);
const longBatchRow={...batchRow,id:'2',text:'x'.repeat(20001)};
assert.equal(ctx.window.journeyTest.materialBatchReady(longBatchRow),false);
assert.ok(ctx.window.journeyTest.materialBatchProblem(longBatchRow).includes('全文仍保留'));
ctx.window.journeyTest.setDraft(data,{material_batch:{open:true,rows:[batchRow,longBatchRow,{...batchRow,id:'3',saved_document_id:'saved',include:false}]}});
const batchMarkup=ctx.window.journeyTest.materialBatchPanel(data);
assert.ok(batchMarkup.includes('multiple data-career-material-files')&&batchMarkup.includes('保存所选可用资料（1份）'));
assert.ok(batchMarkup.includes('&lt;source&gt;.txt')&&batchMarkup.includes('&lt;script&gt;bounded original&lt;/script&gt;'));
assert.ok(batchMarkup.includes(longBatchRow.text));
assert.equal(longBatchRow.text.length,20001);
console.log('Multiple material intake: original previews stay complete and escaped; oversized, unselected, unread and already-saved files stay out of the pending save set.');

{
const comparisonMaterialA={id:'material-a',title:'<Configuration original>',publisher:'User note',full_text_length:90};
const comparisonMaterialB={id:'material-b',title:'Integration original',publisher:'User note',full_text_length:80};
const materialStudy={...result('material-study',stamp(4)),material_ids:['material-a','material-b'],result:{status:'completed',claims:[],evidence:[],gaps:[],scope:{public_document_titles:[comparisonMaterialA,comparisonMaterialB]}}};
const groupData={...data,stories:[],materials:[comparisonMaterialA,comparisonMaterialB],document_ids:['material-a','material-b'],results:[materialStudy]};
ctx.window.journeyTest.setDraft(groupData,{material_compare:{open:true,ids:['material-a','material-b']},material_ids:['material-a','material-b']});
const groupPanel=ctx.window.journeyTest.materialComparePanel(groupData);
assert.ok(groupPanel.includes('已选 2 份')&&groupPanel.includes('name="material_ids" value="material-a"'));
assert.ok(groupPanel.includes('&lt;Configuration original&gt;'));
const groupInquiry=ctx.window.journeyTest.inquiryPanel(groupData);
assert.ok(groupInquiry.includes('本轮重点对读 2 份资料')&&groupInquiry.includes('name="material_id" value=""'));
assert.ok(groupInquiry.includes('name="material_ids"')&&groupInquiry.includes('material-a'));
const groupFocus=ctx.window.journeyTest.discussionFocus(materialStudy,groupData);
assert.deepEqual(Array.from(groupFocus.material_ids),['material-a','material-b']);
const detachedGroup={...groupData,materials:[comparisonMaterialA],document_ids:['material-a']};
const sourceFocus=ctx.window.journeyTest.materialFocus(materialStudy,detachedGroup,true);
assert.ok(sourceFocus.includes('Integration original')&&sourceFocus.includes('本轮选定的 2 份重点资料'));
assert.ok(!sourceFocus.includes('data-public-source'));
ctx.window.journeyTest.setDraft(detachedGroup,{material_ids:['material-a','material-b']});
const detachedInquiry=ctx.window.journeyTest.inquiryPanel(detachedGroup);
assert.ok(detachedInquiry.includes('已移出本目标，本轮尚不可读')&&detachedInquiry.includes('data-career-attach-material="material-b"'));
assert.deepEqual(Array.from(ctx.window.journeyTest.discussionFocus(materialStudy,detachedGroup).material_ids),['material-a','material-b']);
console.log('Explicit material group research: selected sources, full historical names, editable inquiry focus and visible detached-source recovery passed.');
}

{
const archived=[{id:'saved-a',title:'<Original A>',full_text_length:40},{id:'saved-b',title:'Original B',full_text_length:30}];
const savedQuestion={...question,material_ids:['saved-a','saved-b']};
const savedData={...data,stories:[],questions:[savedQuestion],materials:archived,document_ids:['saved-a','saved-b']};
const savedBefore=JSON.stringify(savedQuestion);
ctx.window.journeyTest.setDraft(savedData,{question_id:'q'});
const defaultInquiry=ctx.window.journeyTest.inquiryPanel(savedData);
assert.ok(defaultInquiry.includes('本轮重点对读 2 份资料')&&defaultInquiry.includes('本调查已保存的默认重点资料'));
ctx.window.journeyTest.setDraft(savedData,{question_id:'q',material_ids:[]});
const clearedDefault=ctx.window.journeyTest.inquiryPanel(savedData);
assert.ok(!clearedDefault.includes('本轮重点对读')&&clearedDefault.includes('name="material_ids" value="[]"'));
assert.deepEqual(Array.from(ctx.window.journeyTest.questionValues(savedQuestion).material_ids),['saved-a','saved-b']);
const questionMaterialEditor=ctx.window.journeyTest.questionMaterialEditor(savedQuestion,savedData);
assert.ok(questionMaterialEditor.includes('name="question_material_ids" value="saved-a" checked')&&questionMaterialEditor.includes('&lt;Original A&gt;'));
const savedFocus=ctx.window.journeyTest.questionMaterials(savedQuestion,{...savedData,document_ids:['saved-a']},true);
assert.ok(savedFocus.includes('后续提问默认回查的 2 份资料')&&savedFocus.includes('已移出本目标'));
assert.ok(!savedFocus.includes('data-career-attach-material'));
const saveButton=ctx.window.journeyTest.saveMaterialFocusButton(savedData,{question_id:'q'},['saved-a']);
assert.ok(saveButton.includes('data-career-save-question-materials="q"'));
assert.deepEqual(Array.from(ctx.window.journeyTest.branchQuestionDraft(savedQuestion,savedData).material_ids),['saved-a','saved-b']);
const packageWithDefaults=ctx.window.journeyTest.questionJourneyPackage(savedQuestion,savedData);
assert.ok(packageWithDefaults.includes('后续提问默认回查的 2 份资料')&&packageWithDefaults.includes('&lt;Original A&gt;'));
assert.ok(!packageWithDefaults.includes('data-career-save-question-materials'));
assert.equal(JSON.stringify(savedQuestion),savedBefore);
console.log('Saved inquiry material defaults: reopening focus, explicit one-round clearing, editable full selection, missing sources, branch draft and read-only export passed.');
}

{
const earlier=result('earlier-material-study',stamp(1),{current:false});
const updatedStudyData={...data,stories:[],results:[earlier]};
const historicalFocus=ctx.window.journeyTest.discussionFocus(earlier,updatedStudyData);
assert.equal(historicalFocus.source_step_id,earlier.step_id);
ctx.window.journeyTest.setDraft(updatedStudyData,{source_step_id:earlier.step_id});
const continuedPanel=ctx.window.journeyTest.inquiryPanel(updatedStudyData);
assert.ok(continuedPanel.includes('<option value="earlier-material-study" selected>')&&continuedPanel.includes('当时资料，需重核'));
assert.equal(ctx.window.journeyTest.discussionFocus({...earlier,state:'abandoned'},updatedStudyData).source_step_id,'');
assert.equal(ctx.window.journeyTest.discussionFocus({...earlier,result:{...earlier.result,business_review:{status:'rejected'}}},updatedStudyData).source_step_id,'');
console.log('Rechecking old discussions: complete historical analysis stays explicitly selectable, while abandoned and rejected outputs stay out of continued research.');
}

{
const mapRoot={...question,question:'<Root inquiry> '+('preserve the original scope. '.repeat(12))+'FINAL QUESTION LIMIT'};
const child={...question,id:'map-child',parent_question_id:'q',question:'Does a failed local sample change the interpretation?'};
const other={...question,id:'map-other',question:'Which conditions are only preferred?',state:'answered',conclusion:'<User conclusion> still needs source checks.'};
const orphan={...question,id:'map-orphan',parent_question_id:'missing',question:'An earlier parent is unavailable.'};
const joint=result('map-joint',stamp(4),{synthesis_sources:[{question_id:'q'},{question_id:'map-other'}],result:{status:'completed',claims:[{text:'A shared synthetic finding.',category:'task',basis:'synthesis',requirement:'unspecified',evidence_ids:['map-ev']}],evidence:[{id:'map-ev',public_document_id:'map-doc',title:'<Saved original>',quote:'Original wording with final qualifier: production ownership unknown.',start:0,end:77}],gaps:['Still unknown.'],scope:{jobs:[]}}});
const shared={id:'map-note',source_step_id:'map-joint',created_at:stamp(5),previous_view:'Originally certain.',observation:'Local failure only.',current_view:'Shared view. '+('Conditions remain relevant. '.repeat(15))+'FINAL SHARED LIMIT',open_question:'Production unknown.',use_for_research:false};
const chartData={...data,stories:[],questions:[mapRoot,child,other,orphan],results:[joint],insights:[shared],tasks:[{...task,id:'map-failed',question_id:'map-child',outcome:'<NEGATIVE RESULT> Both inputs failed. FINAL OBSERVATION LIMIT',artifact_text:'Complete synthetic log. FINAL ARTIFACT LIMIT'},{...task,id:'map-planned',question_id:'q',outcome:'',state:'planned'}],focus_question_id:'map-child'};
const chartBefore=JSON.stringify(chartData),graph=ctx.window.journeyTest.inquiryMapModel(chartData);
assert.equal(graph.roots.length,3);assert.equal(graph.children.get('q')[0].id,'map-child');assert.equal(graph.syntheses.length,1);assert.equal(graph.shared.length,1);
const chart=ctx.window.journeyTest.inquiryMap(chartData);
assert.ok(chart.includes('data-inquiry-node="map-child"')&&chart.includes('当前主线'));
assert.ok(chart.includes('原问题不在本目标中')&&chart.includes('状态是用户记录'));
assert.ok(chart.includes('回看这次综合研究')&&chart.includes('1 条结果记录'));
assert.ok(chart.includes('拆出后续问题')&&chart.includes('data-career-pin-question="map-child"'));
assert.ok(chart.includes('&lt;Root inquiry&gt;')&&!chart.includes('<Root inquiry>'));
const chartPackage=ctx.window.journeyTest.inquiryMapPackage(chartData);
assert.ok(chartPackage.includes('href="#inquiry-map-child"')&&chartPackage.includes('id="inquiry-map-child"'));
assert.ok(chartPackage.includes('href="#inquiry-event-q-discussion-map-joint"')&&chartPackage.includes('id="inquiry-event-q-discussion-map-joint"'));
assert.ok(chartPackage.includes('href="#inquiry-event-q-insight-map-note"')&&chartPackage.includes('id="inquiry-event-q-insight-map-note"'));
assert.ok(chartPackage.includes('FINAL QUESTION LIMIT')&&chartPackage.includes('FINAL SHARED LIMIT'));
assert.ok(chartPackage.includes('FINAL OBSERVATION LIMIT')&&chartPackage.includes('FINAL ARTIFACT LIMIT'));
assert.ok(chartPackage.includes('production ownership unknown.')&&chartPackage.includes('&lt;User conclusion&gt;'));
assert.ok(!chartPackage.includes('data-career-branch-question')&&!chartPackage.includes('data-career-export-inquiry-map'));
assert.equal(JSON.stringify(chartData),chartBefore);
console.log('Investigation map: saved parent branches, historical synthesis, shared belief links, reported outcomes, direct navigation and complete escaped read-only export passed.');
}

{
const inquiry={...question,material_ids:['default-source'],selected_job_ids:['role-a']};
const observation={...task,id:'observed',question_id:'q',created_at:stamp(1),updated_at:stamp(3),state:'doing',hypothesis:'Expected recovery. FINAL HYPOTHESIS',deliverable:'Local records.',completion_check:'Compare both inputs. FINAL CHECK',outcome:'<FAILED> Both inputs failed. FINAL OBSERVATION',artifact_document_id:'observation-doc'};
const nextData={...data,stories:[],questions:[inquiry],tasks:[{...observation,outcome:''},{...observation,id:'other-task',question_id:'other'}],results:[]};
assert.equal(ctx.window.journeyTest.inquiryNextAction(inquiry,{...nextData,tasks:[]}).kind,'research');
assert.equal(ctx.window.journeyTest.inquiryNextAction(inquiry,nextData).kind,'task');
nextData.tasks=[observation,{...observation,id:'other-task',question_id:'other',updated_at:stamp(8)}];
assert.equal(ctx.window.journeyTest.inquiryNextAction(inquiry,nextData).id,'observed');
const preparedObservation=ctx.window.journeyTest.observationInquiryDraft(observation,inquiry);
assert.equal(preparedObservation.task_id,'observed');assert.equal(preparedObservation.question_id,'q');
assert.equal(preparedObservation.source_step_id,'');assert.equal(preparedObservation.material_ids[0],'default-source');assert.equal(preparedObservation.selected_job_ids[0],'role-a');
const preview=ctx.window.journeyTest.observationPreview(observation);
assert.ok(preview.includes('FINAL HYPOTHESIS')&&preview.includes('FINAL CHECK')&&preview.includes('FINAL OBSERVATION'));
assert.ok(preview.includes('&lt;FAILED&gt;')&&preview.includes('不是独立验证')&&!preview.includes('<FAILED>'));
const beforeNext=JSON.stringify(nextData);
ctx.window.journeyTest.setDraft(nextData,{});
const nextBoard=ctx.window.journeyTest.questionBoard(nextData);
assert.ok(nextBoard.includes('data-career-observation-inquiry="observed"')&&nextBoard.includes('class="career-question-tools"'));
assert.ok(nextBoard.includes('其他研究方式与记录')&&nextBoard.includes('data-career-question-auto="q"')&&nextBoard.includes('data-career-question-teachback="q"'));
assert.equal(JSON.stringify(nextData),beforeNext);
const reviewed=result('observed-review',stamp(4),{question_id:'q',task_id:'observed'});
assert.equal(ctx.window.journeyTest.inquiryNextAction(inquiry,{...nextData,results:[reviewed]}).kind,'conclusion');
assert.equal(ctx.window.journeyTest.inquiryNextAction({...inquiry,state:'answered',conclusion:'User still uncertain.'},{...nextData,results:[reviewed]}).kind,'research');
assert.equal(ctx.window.journeyTest.inquiryNextAction(inquiry,{...nextData,results:[{...reviewed,created_at:stamp(2)}]}).kind,'observation');
const waiting={...reviewed,step_id:'waiting',state:'queued',result:null};
const pendingAction=ctx.window.journeyTest.inquiryNextAction(inquiry,{...nextData,results:[waiting]});
assert.equal(pendingAction.kind,'pending');
const pendingButton=ctx.window.journeyTest.inquiryNextButton(pendingAction,inquiry,nextData);
assert.ok(pendingButton.includes('/discussion/waiting')&&!pendingButton.includes('data-career-control'));
console.log('Next inquiry step: only linked observations, full editable input context, preserved sources, explicit conclusion drafting, unchanged records and non-running pending navigation passed.');
}

const experimentSnapshot={model_calls:5,career_learning_context:{experiment_searches:[{terms:['幂等键'],matching_count:8,question_id:'q'}],read_experiments:[{id:'older',title:'<script>earlier</script>',state:'done',recorded_at:stamp(1),inquiry_question:'Earlier question',prior_expectation:'Hypothesis '.repeat(80)+'FINAL-EXPECTATION',task_or_ability:'Check local inputs',planned_deliverable:'Two raw logs',proposed_check:'Check '.repeat(100)+'FINAL-CHECK',reported_observation:'Failure '.repeat(200)+'FINAL-OBSERVATION',design_change:'Retain uncontrolled concurrency',artifact:'User log',artifact_document:{document_id:'raw',title:'Original log',in_current_scope:true},previous_task_id:'previous'}]}};
const experimentSnapshotBefore=JSON.stringify(experimentSnapshot);
const experimentHtml=ctx.window.journeyTest.experimentRecall(experimentSnapshot,'goal');
for(const text of ['FINAL-EXPECTATION','FINAL-CHECK','FINAL-OBSERVATION','完整设计与观察','不表示已核对日志','/task/previous','data-public-source="raw"'])assert.ok(experimentHtml.includes(text),text);
assert.ok(experimentHtml.includes('&lt;script&gt;earlier&lt;/script&gt;'));
assert.ok(!experimentHtml.includes('<script>earlier'));
const experimentExport=ctx.window.journeyTest.learningRecall(experimentSnapshot,'goal',true);
assert.ok(experimentExport.includes('FINAL-OBSERVATION'));
assert.ok(!/<button|<form|data-public-source/.test(experimentExport));
assert.equal(JSON.stringify(experimentSnapshot),experimentSnapshotBefore);
const unavailableExperiment=JSON.parse(experimentSnapshotBefore);
unavailableExperiment.career_learning_context.read_experiments[0].artifact_document.in_current_scope=false;
assert.ok(ctx.window.journeyTest.experimentRecall(unavailableExperiment,'goal').includes('不能据此声称已核对日志'));
assert.ok(!ctx.window.journeyTest.experimentRecall(unavailableExperiment,'goal').includes('data-public-source'));
console.log('Earlier experiment inputs: complete hypotheses, checks, negative observations, raw-source locators, escaped read-only exports and unchanged records passed.');

const recoveredExperiment=JSON.parse(experimentSnapshotBefore);
recoveredExperiment.career_learning_context.read_experiments[0].artifact_document.found_via_experiment=true;
const recoveredHtml=ctx.window.journeyTest.experimentRecall(recoveredExperiment,'goal');
assert.ok(recoveredHtml.includes('从本目标实验记录找回'));
assert.ok(recoveredHtml.includes('data-public-source="raw"'));
console.log('Older experiment logs retain their recovered-source label, raw reader and complete conditions.');

const materialMapInput={question:'Full chosen focus with final limit',question_id:'q',selected_job_ids:['job'],source_step_id:'old-step',task_id:'old-task',story_id:'old-story',insight_id:'old-note',comparison_step_ids:['x','y']};
const materialMapInputBefore=JSON.stringify(materialMapInput),mapSourceIds=['source-a','source-b'];
const mapDraft=ctx.window.journeyTest.materialMapDraft(mapSourceIds,materialMapInput);
assert.equal(mapDraft.kind,'map');assert.equal(mapDraft.question,materialMapInput.question);
assert.equal(mapDraft.question_id,'q');assert.deepEqual(Array.from(mapDraft.material_ids),mapSourceIds);
for(const key of ['source_step_id','task_id','story_id','insight_id','counter_insight_id'])assert.equal(mapDraft[key],'');
assert.equal(JSON.stringify(materialMapInput),materialMapInputBefore);
const mapDraftData={id:'mapgoal',jobs:[],tasks:[],stories:[],insights:[],questions:[],results:[],document_ids:mapSourceIds,materials:mapSourceIds.map(id=>({id,title:id,full_text_length:50}))};
ctx.window.journeyTest.setDraft(mapDraftData,ctx.window.journeyTest.materialMapDraft(mapSourceIds));
const materialMapForm=ctx.window.journeyTest.inquiryPanel(mapDraftData);
assert.ok(materialMapForm.includes('name="kind" value="map"'));
assert.ok(materialMapForm.includes('画所选资料的工作地图'));
assert.ok(materialMapForm.includes('data-career-inquiry-mode="ask"'));
assert.ok(!materialMapForm.includes('<select name="source_step_id">'));
assert.ok(ctx.window.journeyTest.materialComparePanel(mapDraftData).includes('value="map"'));
console.log('Selected-material work maps: editable focus, exact source group, cleared personal inputs, retained inquiry scope and explicit run form passed.');

assert.equal(ctx.window.journeyTest.discussionFocus({kind:'map',step_id:'map-step',state:'completed',result:{status:'completed'},material_ids:mapSourceIds},mapDraftData).kind,'ask');
console.log('Continuing a material map returns to inquiry mode while retaining its source group.');

const comparisonRelation={source_kind:'task',source_text:'<Task>',target_kind:'deliverable',target_text:'Report',predicate:'produces',basis:'inference',rationale:'Why '.repeat(160)+'FINAL-WHY',transfer_limit:'Limit '.repeat(200)+'FINAL-LIMIT',claim_indices:[0,1]};
const relationMap=(id,relations,extra={})=>({step_id:id,kind:'map',state:'completed',current:true,created_at:stamp(1),question_id:'q',result:{status:'completed',claims:[{text:'<Task>',category:'task',basis:'direct',requirement:'unspecified',evidence_ids:['ev']},{text:'Report',category:'deliverable',basis:'direct',requirement:'unspecified',evidence_ids:['ev']}],evidence:[{id:'ev',public_document_id:'raw',start:0,end:40,title:'Original',quote:'Complete quote with FINAL-QUOTE'}],gaps:[],work_map:{scope_note:'Synthetic scope',work_types:[],work_relations:relations,comparisons:[],unknowns:['Still unknown']}},...extra});
const relationLeft=relationMap('left',[comparisonRelation,{...comparisonRelation,source_text:'Unique left'}]);
const relationRight=relationMap('right',[{...comparisonRelation,transfer_limit:'Changed limit with FINAL-RIGHT-LIMIT'},{...comparisonRelation,source_text:'Unique right'}]);
const relationPair=[relationLeft,relationRight],pairBefore=JSON.stringify(relationPair);
const changes=ctx.window.journeyTest.mapRelationChanges(relationPair);
assert.deepEqual(Array.from(changes,row=>row.state),['details','left','right']);
const changeHtml=ctx.window.journeyTest.mapChanges(relationPair);
for(const value of ['FINAL-WHY','FINAL-LIMIT','FINAL-RIGHT-LIMIT','FINAL-QUOTE','不能据此认定已经撤回','data-career-map-change="0"','&lt;Task&gt;'])assert.ok(changeHtml.includes(value),value);
const changeDraft=ctx.window.journeyTest.mapChangeInquiry(relationPair,0);
assert.equal(changeDraft.kind,'ask');assert.equal(changeDraft.question_id,'q');
assert.deepEqual(Array.from(changeDraft.comparison_step_ids),['left','right']);
assert.ok(changeDraft.question.includes('左图第1条工作关系'));
assert.ok(changeDraft.question.includes('右图第1条工作关系'));
assert.ok(changeDraft.question.length<=1500);
const changeExport=ctx.window.journeyTest.mapChanges(relationPair,true);
assert.ok(changeExport.includes('FINAL-RIGHT-LIMIT'));
assert.ok(!/<button|<form|<script>/.test(changeExport));
assert.equal(JSON.stringify(relationPair),pairBefore);
const repeatedLeft=relationMap('duplicates-left',[comparisonRelation,{...comparisonRelation,transfer_limit:'A second full condition'}]);
const repeatedRight=relationMap('duplicates-right',[{...comparisonRelation,transfer_limit:'A second full condition'},comparisonRelation]);
const sameGroups=ctx.window.journeyTest.mapRelationChanges([repeatedLeft,repeatedRight]);
assert.equal(sameGroups.length,1);assert.equal(sameGroups[0].state,'same');assert.equal(sameGroups[0].left.length,2);
assert.ok(ctx.window.journeyTest.mapChangeInquiry([repeatedLeft,repeatedRight],0).question.includes('左图第1、2条'));
const movedEvidence=JSON.parse(JSON.stringify(relationLeft));movedEvidence.result.evidence[0].public_document_id='different-original';
assert.equal(ctx.window.journeyTest.mapRelationChanges([relationLeft,movedEvidence])[0].state,'details');
console.log('Map relation comparison: literal groups, complete conditions and citations, duplicate edges, selected-pair inquiry, unchanged maps and escaped read-only export passed.');

assert.ok(changeDraft.question.includes('selected_inquiry.earlier_discussions'));
const independentChangeDraft=ctx.window.journeyTest.mapChangeInquiry([relationLeft,{...relationRight,question_id:'different'}],0);
assert.equal(independentChangeDraft.question_id,'');
assert.ok(independentChangeDraft.question.includes('selected_map_comparison'));
console.log('Map-change inquiry targets the actual history context for linked and independent maps.');

const emptyMapChanges=ctx.window.journeyTest.mapChanges([relationMap('empty-a',[]),relationMap('empty-b',[])]);
assert.ok(emptyMapChanges.includes('尚无可对照的工作关系'));
assert.ok(!emptyMapChanges.includes('均同文'));

const longLibraryIds=Array.from({length:25},(_,index)=>'library-'+index);
const longLibraryData={id:'library',jobs:[],materials:longLibraryIds.map(id=>({id,title:id})),stories:[],tasks:[],results:[]};
const longLibraryScope=ctx.window.journeyTest.researchScope({kind:'map',document_ids:longLibraryIds.slice(0,20),omitted_documents:5,result:{status:'completed',scope:{archived_public_ids:longLibraryIds,public_document_titles:[]},evidence:[]}},longLibraryData);
assert.ok(longLibraryScope.includes('本轮可查阅 25 份'));
assert.ok(longLibraryScope.includes('开头优先 20 份'));
assert.ok(longLibraryScope.includes('library-24'));
assert.ok(!longLibraryScope.includes('份未带入'));
console.log('Research source scope displays the saved readable library separately from its opening selection.');

const startQuestion='📚理解原文与任务边界'.repeat(60)+'FINAL-START-QUESTION';
const startPayload=ctx.window.journeyTest.careerStartValues({first_question:'  '+startQuestion+'  ',title:'',goal:'',background:'',material_title:'Original',material_text:'Full original'},['job']);
assert.equal(startPayload.first_question,startQuestion);assert.equal(startPayload.goal,startQuestion);
assert.equal(Array.from(startPayload.title).length,51);assert.ok(startPayload.title.endsWith('…'));
assert.equal(startPayload.material_text,'Full original');assert.equal(startPayload.background,'');
assert.deepEqual(Array.from(startPayload.job_ids),['job']);
assert.throws(()=>ctx.window.journeyTest.careerStartValues({first_question:'   '}));
const startCustom=ctx.window.journeyTest.careerStartValues({first_question:'Question',title:'Broader title',goal:'Broader goal',resume_text:'User resume'});
assert.equal(startCustom.title,'Broader title');assert.equal(startCustom.goal,'Broader goal');assert.ok(startCustom.background.includes('用户自述'));
const firstInquiry=ctx.window.journeyTest.questionInquiryDraft({id:'first',question:startQuestion,material_ids:['raw'],selected_job_ids:['job']});
assert.equal(firstInquiry.kind,'ask');assert.equal(firstInquiry.question,startQuestion);
assert.equal(firstInquiry.question_id,'first');assert.deepEqual(Array.from(firstInquiry.material_ids),['raw']);
assert.equal(firstInquiry.source_step_id,'');assert.equal(firstInquiry.insight_id,'');
console.log('Question-first intake: complete saved question, readable title, optional background, selected jobs and source-bound inquiry passed.');

const comparisonTask={...task,comparison_conditions:"Same input; <uncontrolled> concurrency.",comparison_rows:[{condition:"A <script>",input:"One request",expected:"No second row",observed:"Second row appeared; final limit."},{condition:"B",input:"Two requests",expected:"New row",observed:""}]};
const comparisonBefore=JSON.stringify(comparisonTask);
const worksheetHtml=ctx.window.journeyTest.experimentComparisonTable(comparisonTask);
assert.ok(worksheetHtml.includes("Second row appeared; final limit.")&&worksheetHtml.includes("尚无实际观察，不能用预期代替"));
assert.ok(worksheetHtml.includes("&lt;script&gt;")&&!worksheetHtml.includes("<script>"));
assert.equal(JSON.stringify(comparisonTask),comparisonBefore);
const cleaned=ctx.window.journeyTest.savedComparisonRows([{condition:" A ",observed:" Result "},{}]);
assert.equal(cleaned.length,1);assert.equal(cleaned[0].condition,"A");assert.equal(cleaned[0].observed,"Result");
assert.throws(()=>ctx.window.journeyTest.savedComparisonRows([{condition:"",observed:"Actual result"}]),/分组名称/);
const comparisonExport=ctx.window.journeyTest.questionJourney(question,{...data,tasks:[comparisonTask]},true);
assert.ok(comparisonExport.includes("Second row appeared; final limit.")&&comparisonExport.includes("尚无实际观察"));
const savedInputs={model_calls:3,career_learning_context:{comparison_inputs:[{...comparisonTask,id:"worksheet"}]}};
const inputsHtml=ctx.window.journeyTest.experimentRecall(savedInputs,"goal",true);
assert.ok(inputsHtml.includes("当轮带入的条件对照")&&inputsHtml.includes("Second row appeared; final limit."));
assert.ok(!inputsHtml.includes("次完整读取"));
console.log("Experiment worksheets: expected versus observed, blank unrun groups, full conditions, saved research inputs and escaped exports passed.");

const recipe={title:"合成对照设计",task_or_ability:"理解条件",deliverable:"输入输出记录",completion_check:"逐组比较",hypothesis:"编号可能影响结果",comparison_conditions:"同一初始表格，未控制并发",comparison_rows:[{condition:"重复编号",input:"request_id=A\nrequest_id=A <原样>",expected:"第二次可能不新增"}],assumptions:["仅用合成数据"],evidence_ids:["ev"]};
const recipeBefore=JSON.stringify(recipe);
const recipeText=ctx.window.journeyTest.experimentRecipeText(recipe);
assert.ok(recipeText.includes("尚未执行")&&recipeText.includes("request_id=A\nrequest_id=A <原样>"));
assert.ok(recipeText.includes("第二次可能不新增")&&recipeText.includes("未控制并发"));
assert.ok(!recipeText.includes("实际观察（用户记录）"));
const observedRecipe=ctx.window.journeyTest.experimentRecipeText({...recipe,comparison_rows:[{...recipe.comparison_rows[0],observed:"第二次仍新增，预期未支持"}],outcome:"只做了合成表格"},true);
assert.ok(observedRecipe.includes("第二次仍新增，预期未支持")&&observedRecipe.includes("系统未独立执行或核验"));
const proposedHtml=ctx.window.journeyTest.experimentComparisonTable(recipe,true);
assert.ok(proposedHtml.includes("建议的条件对照 · 尚未执行")&&proposedHtml.includes("&lt;原样&gt;"));
assert.ok(!proposedHtml.includes("条件对照 · 用户记录"));
assert.equal(JSON.stringify(recipe),recipeBefore);
const proposalStudy={...data.results[0],kind:"plan",result:{status:"completed",claims:[],evidence:[],gaps:[],application_plan:{actions:[recipe],open_questions:["真实规则未知"],notice:"建议，尚未运行"}}};
const exportedPlan=ctx.window.journeyTest.comparisonColumn(proposalStudy,false);
assert.ok(exportedPlan.includes("request_id=A")&&exportedPlan.includes("第二次可能不新增")&&exportedPlan.includes("真实规则未知"));
assert.ok(!exportedPlan.includes("<button"));
console.log("Agent experiment recipes: proposed cases, editable import fields, complete copy text, current observations and read-only proposal export passed.");

const storyTask={...comparisonTask,comparison_rows:[...comparisonTask.comparison_rows.map(row=>({...row})),{condition:"UNRUN GROUP",input:"UNRUN INPUT MUST NOT BECOME ACTION",expected:"UNRUN EXPECTATION",observed:""}]};
const storyOriginal=JSON.stringify(storyTask);
const practiceDraft=ctx.window.journeyTest.taskStoryDraft(storyTask,data,[0]);
assert.equal(practiceDraft.source_task_id,storyTask.id);
assert.ok(practiceDraft.action.includes("One request")&&practiceDraft.action.includes("No second row"));
assert.ok(practiceDraft.result.includes("Second row appeared; final limit."));
assert.ok(!practiceDraft.action.includes("UNRUN INPUT")&&!practiceDraft.result.includes("UNRUN EXPECTATION"));
assert.ok(practiceDraft.limits.includes("UNRUN GROUP")&&practiceDraft.limits.includes("<uncontrolled>"));
assert.ok(practiceDraft.limits.includes("不代表企业工作经历"));
assert.equal(JSON.stringify(storyTask),storyOriginal);
assert.throws(()=>ctx.window.journeyTest.taskStoryDraft({...storyTask,outcome:""},data),/实际观察/);
assert.throws(()=>ctx.window.journeyTest.taskStoryDraft(storyTask,data,[]),/选一组/);
const longStory=ctx.window.journeyTest.taskStoryDraft({...storyTask,comparison_rows:[{condition:"long",input:"操作".repeat(1100)+"FINAL INPUT",expected:"仍未知",observed:"观察".repeat(800)+"FINAL RESULT"}]},data);
assert.ok(longStory.action.endsWith("仍未知")&&longStory.result.includes("FINAL RESULT"));
assert.ok(longStory.action.includes("FINAL INPUT")&&ctx.window.journeyTest.storyLengthIssue(longStory).includes("亲自操作"));
const sourceHtml=ctx.window.journeyTest.taskStorySource(practiceDraft,{...data,tasks:[storyTask]});
assert.ok(sourceHtml.includes("回看原练习与产物")&&!sourceHtml.includes("<uncontrolled>"));
console.log("Practice-to-story drafts: chosen actual observations, planned versus executed inputs, complete limits, untruncated long fields and original record links passed.");

{
const groupIds=[data.insights[0].id,data.insights[1].id,data.insights[2].id],groupBefore=JSON.stringify(data);
const groupDraft=ctx.window.journeyTest.insightGroupDraft(data,groupIds,"  连起任务、交付与条件；末尾仍未知。  ");
assert.deepEqual(Array.from(groupDraft.insight_ids),groupIds);
assert.equal(groupDraft.question,"连起任务、交付与条件；末尾仍未知。");
assert.equal(groupDraft.question_id,"");assert.equal(groupDraft.insight_id,"");assert.equal(groupDraft.source_step_id,"");
assert.throws(()=>ctx.window.journeyTest.insightGroupDraft(data,[groupIds[0]]),/2–4/);
assert.throws(()=>ctx.window.journeyTest.insightGroupDraft(data,[groupIds[0],"foreign"]),/2–4/);
const groupFocus=ctx.window.journeyTest.insightGroupFocus(data,groupDraft);
assert.ok(groupFocus.includes('name="insight_ids"')&&groupFocus.includes("本次综合 3 条个人认识"));
assert.ok(groupFocus.includes("Original overconfident belief.")&&groupFocus.includes("已搁置，仅本次点选"));
const savedGroup={model_calls:3,career_learning_context:{selected_notes:groupIds.map(id=>{const note=data.insights.find(row=>row.id===id);return {id,current_user_view:note.current_view,previous_view:note.previous_view,reported_observation:note.observation,open_question:note.open_question,use_for_research:note.use_for_research}})}};
const groupRecall=ctx.window.journeyTest.learningRecall(savedGroup,data.id,true,data);
assert.ok(groupRecall.includes("本次点选综合")&&groupRecall.includes("Original overconfident belief."));
const groupRow=result("note-group",stamp(9),{insight_ids:groupIds,result:{...savedGroup,status:"completed",claims:[],evidence:[],gaps:[]}});
assert.deepEqual(Array.from(ctx.window.journeyTest.discussionFocus(groupRow,data).insight_ids),groupIds);
assert.ok(ctx.window.journeyTest.learningImpactRecords(groupIds[0],{...data,results:[groupRow]}).some(item=>item.row.step_id==="note-group"));
assert.equal(JSON.stringify(data),groupBefore);
console.log("Personal-view synthesis: exact chosen group, independent query focus, full parked inputs, historical recall and continued research passed.");

}

{
 const historicalInput={id:"original-view",current_user_view:"Old view <boundary> with final condition",previous_view:"Earlier uncertainty",reported_observation:"Reported failure",open_question:"Still unknown",use_for_research:false};
 const derivedNote={id:"derived",current_user_view:"Conditional synthesis",source_personal_inputs:[historicalInput],source_personal_inputs_notice:"Historical user inputs, not new evidence."};
 const derivedHtml=ctx.window.journeyTest.learningRecall({model_calls:2,career_learning_context:{selected_note:derivedNote}},"goal",true);
 assert.ok(derivedHtml.includes("原综合讨论中的个人观点")&&derivedHtml.includes("Old view &lt;boundary&gt; with final condition"));
 assert.ok(derivedHtml.includes("当时已搁置")&&!derivedHtml.includes("<boundary>"));
 console.log("Derived synthesis recall keeps complete historical personal inputs without adopting them as facts.");
}


{
  const api=ctx.window.journeyTest,qualifier='末尾限定：仅适用于局部样例，生产验收权仍未知。';
  const full='🧪'.repeat(1100)+qualifier;
  const selected=result('exact-old-study',stamp(1),{question_id:'q',material_ids:['raw'],selected_job_ids:['job'],insight_ids:['old','new'],result:{status:'completed',claims:Array.from({length:24},(_,index)=>({category:'task',basis:'inference',requirement:'unspecified',text:index===23?full:'Other claim '+index,evidence_ids:index===23?['exact','lead']:['unrelated']})),evidence:[{id:'exact',title:'<source>',public_document_id:'raw',quote:'<script>literal quoted input</script>'+qualifier,start:0,end:100},{id:'lead',title:'Search lead',evidence_kind:'search_excerpt',quote:'Not yet read in full.'},{id:'unrelated',title:'Other source',quote:'UNRELATED QUOTE'}],gaps:[]}});
  const local={...inquiryData,document_ids:['raw'],materials:[{id:'raw',title:'Raw'}],results:[selected]};
  const before=JSON.stringify(local),refs=api.claimReferencePanel(selected,23);
  assert.ok(refs.includes('&lt;source&gt;')&&refs.includes('&lt;script&gt;literal quoted input&lt;/script&gt;'+qualifier));
  assert.ok(!refs.includes('<script>')&&!refs.includes('UNRELATED QUOTE'));
  assert.ok(refs.includes('搜索线索，尚未核对正文')&&refs.includes('data-public-source="raw"'));
  const draft=api.claimCheckDraft(selected,23,local);
  assert.equal(draft.source_step_id,'exact-old-study');assert.equal(draft.claim_review_index,23);
  assert.equal(draft.question_id,'q');assert.ok(draft.question.includes('第 24 条判断'));
  assert.ok(draft.question.length<1500&&!draft.question.includes(full));
  assert.deepEqual(Array.from(draft.selected_job_ids),['job']);assert.deepEqual(Array.from(draft.material_ids),['raw']);
  assert.deepEqual(Array.from(draft.insight_ids),['old','new']);
  const focus=api.claimReviewFocus(local,draft);
  assert.ok(focus.includes(full)&&focus.includes('从原研究第 24 条判断发起查证'));
  assert.ok(!focus.includes('Other claim 22'));
  api.setDraft(local,draft);
  const panel=api.inquiryPanel(local),card=api.coachingResult(selected);
  assert.ok(panel.includes(full)&&panel.includes('name="claim_review_index" value="23"'));
  assert.ok(card.includes('data-career-check-claim="exact-old-study:23"'));
  assert.equal(api.discussionFocus(selected,local).claim_review_index,null);
  assert.ok(!api.claimReviewFocus(local,{...draft,source_step_id:''}).includes(full));
  assert.throws(()=>api.claimCheckDraft({...selected,state:'abandoned'},23,local));
  assert.equal(JSON.stringify(local),before);
  console.log('Per-claim source inspection and editable numbered recheck preserve full long claims and existing scope without running research.');
}


{
 const api=ctx.window.journeyTest,oldQuote='<old>Complete condition; authority unknown.</old>';
 const question={id:'material-q',question:'Who reviews the failure record?',state:'answered',conclusion:'Keep the original qualified conclusion.',conclusion_step_id:'old-material-read'};
 const material={id:'current-raw',title:'Corrected work note <check>',related_document_ids:['old-raw','current-raw']};
 const old=result('old-material-read',stamp(1),{question_id:question.id,result:{status:'completed',claims:[{text:'Old explanation.'}],evidence:[{id:'old-fragment',public_document_id:'old-raw',quote:oldQuote,start:0,end:oldQuote.length}],audit:{}}});
 const local={...data,questions:[question],materials:[material],document_ids:['current-raw'],results:[old]};
 const before=JSON.stringify(local),changes=api.questionSourceChanges(question,local);
 assert.equal(changes.length,1);assert.equal(changes[0].kind,'material');assert.equal(changes[0].material.id,'current-raw');
 const panel=api.sourceFollowups(local),notice=api.questionSourceNotice(question,local);
 assert.ok(panel.includes('Corrected work note &lt;check&gt;')&&panel.includes('&lt;old&gt;Complete condition; authority unknown.&lt;/old&gt;'));
 assert.ok(panel.includes('Keep the original qualified conclusion.')&&notice.includes('data-public-source="current-raw"'));
 assert.ok(notice.includes('data-career-material-review="current-raw"')&&notice.includes('data-public-source="old-raw"'));
 const draft=api.sourceReviewDraft(question,local);
 assert.equal(draft.material_id,'current-raw');assert.equal(draft.source_step_id,'old-material-read');
 assert.equal(draft.question_id,question.id);assert.deepEqual(Array.from(draft.material_ids),[]);
 assert.ok(draft.question.length<1500&&draft.question.includes('未回读的原文保留未知'));
 const fresh=result('fresh-material-read',stamp(3),{question_id:question.id,result:{status:'completed',claims:[],evidence:[{id:'new-fragment',public_document_id:'current-raw',quote:'Read current material.'}]}});
 assert.equal(api.questionSourceChanges(question,{...local,results:[fresh,old]}).length,0);
 // A different inquiry reading the update does not silently settle this one.
 assert.equal(api.questionSourceChanges(question,{...local,results:[{...fresh,question_id:'different-question'},old]}).length,1);
 assert.equal(api.questionSourceChanges(question,{...local,results:[{...fresh,state:'abandoned'},old]}).length,1);
 assert.equal(api.questionSourceChanges(question,{...local,results:[{...fresh,result:{...fresh.result,status:'incomplete'}},old]}).length,1);
 // Another goal retaining its original material should not adopt a correction on its own.
 assert.equal(api.questionSourceChanges(question,{...local,materials:[{...material,id:'old-raw'}],document_ids:['old-raw']}).length,0);
 // Deliberately attaching both originals keeps the old one in the current readable choice.
 assert.equal(api.questionSourceChanges(question,{...local,materials:[material,{...material,id:'old-raw'}],document_ids:['current-raw','old-raw']}).length,0);
 const retainedPassage={...question,conclusion_step_id:'',source_passage:{public_document_id:'old-raw',quote:oldQuote,start:0,end:oldQuote.length}};
 assert.equal(api.questionSourceChanges(retainedPassage,{...local,questions:[retainedPassage],results:[]}).length,1);
 assert.equal(api.sourceReviewDraft(retainedPassage,{...local,results:[]}).source_step_id,'');
 const secondMaterial={id:'second-current',title:'Second correction',related_document_ids:['second-old','second-current']};
 const bothOld={...old,result:{...old.result,evidence:[...old.result.evidence,{id:'second-fragment',public_document_id:'second-old',quote:'Another old condition.'}]}};
 const together={...local,materials:[material,secondMaterial],document_ids:['current-raw','second-current'],results:[bothOld]};
 const group=api.sourceReviewDraft(question,together);
 assert.deepEqual(Array.from(group.material_ids),['current-raw','second-current']);assert.equal(group.material_id,'');
 const single=api.sourceReviewDraft(question,together,'second-current');
 assert.equal(single.material_id,'second-current');assert.equal(single.source_step_id,'old-material-read');
 const exported=api.sourceFollowups(local,true);
 assert.ok(exported.includes('Corrected work note &lt;check&gt;')&&exported.includes(oldQuote.replace('<old>','&lt;old&gt;').replace('</old>','&lt;/old&gt;')));
 assert.ok(!exported.includes('<button')&&!exported.includes('data-public-source'));
 assert.equal(JSON.stringify(local),before);
 console.log('Corrected work material followups: linked current versus old sources, exact old discussion, one/group drafts, fresh-read dismissal, explicit old-source retention and safe export passed.');
}


{
 const api=ctx.window.journeyTest,full='A conditional understanding. '.repeat(50)+'<FINAL UNKNOWN: not run>';
 const note={id:'practice-note',current_view:full,previous_view:'Old broad idea.',observation:'Only a local observation.',open_question:'Which counterexample matters?',use_for_research:false};
 const quiz=result('practice-quiz',stamp(2),{kind:'teachback',insight_id:note.id,understanding_check:true,result:{status:'completed',claims:[],evidence:[],gaps:['Same question?'],career_learning_context:{selected_note:{id:note.id,current_user_view:'Historical selected wording.'}}}});
 const feedback=result('practice-feedback',stamp(3),{kind:'answer',source_step_id:quiz.step_id,insight_id:note.id,understanding_check:true,answer:'My actual own explanation.',interview_question:'Same question?',result:{status:'completed',claims:[{category:'task',basis:'synthesis',requirement:'unspecified',text:'Need to distinguish the conditions.',evidence_ids:['feedback-quote']}],gaps:['Which case would refute it?'],evidence:[{id:'feedback-quote',title:'Raw <feedback>',public_document_id:'raw',quote:'Full raw observation. '.repeat(115)+'FINAL NOT RUN'}]}});
 const other={...feedback,step_id:'other-feedback',insight_id:'other-note',answer:'UNRELATED NOTE ANSWER'};
 const local={...inquiryData,insights:[note,{...note,id:'other-note',current_view:'A different view.'}],results:[quiz,feedback,other],running:false};
 const before=JSON.stringify(local);
 api.setDraft(local,{interview_focus:'insight:'+note.id,next_source_step_id:quiz.step_id});
 const focus=api.interviewFocusPanel(local);
 assert.ok(focus.includes(full.replace('<FINAL UNKNOWN: not run>','&lt;FINAL UNKNOWN: not run&gt;'))&&focus.includes('生成这条认识的自测问题'));
 assert.ok(focus.includes('（已搁置）')&&focus.includes('Which counterexample matters?'));
 assert.equal(api.interviewFocusLabel(quiz,local),'认识自测：Historical selected wording.');
 const replay=api.interview(local);
 assert.ok(replay.includes('My actual own explanation.')&&!replay.includes('UNRELATED NOTE ANSWER'));
 const revision=api.practiceRevisionDraft(feedback,local);
 assert.equal(revision.replaces_insight_id,note.id);assert.equal(revision.previous_view,full);
 assert.equal(revision.source_step_id,feedback.step_id);assert.equal(revision.question_id,'');
 assert.ok(revision.observation.endsWith('FINAL NOT RUN')&&api.insightLengthNotice(revision));
 const card=api.coachingResult(feedback);assert.ok(card.includes('data-career-revise-practice="practice-feedback"'));
 assert.throws(()=>api.practiceRevisionDraft({...feedback,insight_id:'missing'},local));
 assert.throws(()=>api.practiceRevisionDraft({...feedback,state:'abandoned'},local));
 assert.equal(JSON.stringify(local),before);
 console.log('Saved-understanding practice: full parked focus, historical label, separate answer replays, editable full correction and no automatic note change passed.');
}


{
 const api=ctx.window.journeyTest,ending='FINAL CONDITION: no production authority <keep>';
 const sources=[{id:'left',title:'Old <text>',text:'🧪开头\r\n'+'Complete original text. '.repeat(700)+ending,publisher:'Supplied <source>',integrity:'verified',evidence_kind:'work_material'}, {id:'right',title:'Current correction',text:'New full body. '+ending,publisher:'User supplied',integrity:'verified',evidence_kind:'work_material'}, {id:'third',title:'Saved search lead',text:'<script>literal search text</script>',integrity:'verified',evidence_kind:'search_excerpt'}];
 const reading={goal_id:data.id,documents:sources,left:'left',right:'right',focus:{}},local={...data,document_ids:['right','third']};
 const before=JSON.stringify(reading),page=api.materialReadingPanel(local,reading);
 assert.ok(page.includes('Old &lt;text&gt;')&&page.includes('Supplied &lt;source&gt;'));
 assert.ok(page.includes(ending.replace('<keep>','&lt;keep&gt;'))&&page.includes('未选用于本目标')&&page.includes('本目标选用中'));
 assert.ok(page.includes('Complete original text. '.repeat(700))&&page.includes('data-reader-query'));
 const swapped=api.materialReadingPair(reading,'left','right');
 assert.equal(swapped.left,'right');assert.equal(swapped.right,'left');
 const third=api.materialReadingPair(reading,'right','third');assert.equal(third.left,'left');assert.equal(third.right,'third');
 assert.equal(api.materialReadingPair(reading,'left','unknown').left,'left');
 const lead=api.materialReadingPanel(local,third);assert.ok(lead.includes('尚未核对网页正文')&&lead.includes('&lt;script&gt;literal search text&lt;/script&gt;')&&!lead.includes('<script>'));
 const exported=api.materialReadingPackage(local,reading);
 assert.ok(exported.startsWith('<!doctype html>')&&exported.includes('Complete original text. '.repeat(700))&&exported.includes(ending.replace('<keep>','&lt;keep&gt;')));
 assert.ok(!exported.includes('literal search text')&&!exported.includes('<button')&&!exported.includes('<script')&&!exported.includes('<form'));
 assert.equal(JSON.stringify(reading),before);
 console.log('Side-by-side original reading: complete long sources, explicit scope labels, independent source selection, safe search-lead display and full static export passed.');
}

{
 const api=ctx.window.journeyTest,row={result:{claims:[{evidence_ids:['a','b','c']}],evidence:[{id:'a',public_document_id:'first-doc',quote:'First original.'},{id:'b',public_document_id:'second-doc',quote:'Second original.'},{id:'c',public_document_id:'first-doc',quote:'Another range of the first original.'}]}};
 const panel=api.claimReferencePanel(row,0);assert.ok(panel.includes('data-career-read-materials="first-doc:second-doc"'));
 console.log('A claim with multiple archived sources opens the exact distinct originals for side-by-side inspection.');
}

{
 const api=ctx.window.journeyTest,full='🧪'.repeat(1100)+'FINAL CONDITION <not production>';
 const source=result('matched-study',stamp(1),{result:{status:'completed',claims:[],evidence:[],gaps:[]}});
 const local={...inquiryData,results:[source]};
 const row={kind:'discussion',project_id:local.id,step_id:source.step_id,claim_match_count:5,claim_matches:[{index:23,text:full,category:'ability',basis:'direct',requirement:'preferred',source_titles:['Original <raw>']}]};
 const before=JSON.stringify(row),html=api.libraryClaimMatches(row,local);
 assert.ok(html.includes(full.replace('<not production>','&lt;not production&gt;'))&&html.includes('Original &lt;raw&gt;'));
 assert.ok(html.includes('/discussion/matched-study/23')&&html.includes('data-career-check-claim="matched-study:23"'));
 assert.ok(html.includes('加分')&&html.includes('其余 4 条'));
 const foreign=api.libraryClaimMatches({...row,project_id:'other-goal'},local);
 assert.ok(foreign.includes('#career/other-goal/discussion/matched-study/23')&&!foreign.includes('data-career-check-claim'));
 assert.ok(!api.libraryClaimMatches(row,{...local,results:[{...source,state:'abandoned'}]}).includes('data-career-check-claim'));
 assert.equal(api.libraryClaimMatches({...row,claim_matches:[]},local),'');
 assert.equal(api.libraryClaimMatches({...row,kind:'insight'},local),'');
 assert.equal(JSON.stringify(row),before);
 console.log('Library judgment matches preserve full conditions and requirement type, target exact historical positions and prepare only available local studies.');
}

{
 const api=ctx.window.journeyTest,full='A conditional view. '.repeat(65)+'<FINAL LIMIT: not run>';
 const note={id:'note',project_id:'owner',project_title:'Work <topic>',current_view:full,previous_view:'Full old view.',observation:'<script>literal user observation</script>',open_question:'Which condition remains unknown?',use_for_research:false,replaces_insight_id:'old',source_step_id:'source-step',source_claim_index:0,successor_ids:['child'],inquiry_links:[{question_id:'related',question:'A linked question?'}],created_at:stamp(1)};
 const data={goals:[{id:'owner',title:'Work <topic>'}],notes:[note],total_count:13,offset:0,next_offset:12};
 const before=JSON.stringify(data),html=api.noteReview(data,{q:'<query>',goal_id:'owner',state:'parked',unknown:true});
 assert.ok(html.includes(full.replace('<FINAL LIMIT: not run>','&lt;FINAL LIMIT: not run&gt;'))&&html.includes('&lt;script&gt;literal user observation&lt;/script&gt;')&&!html.includes('<script>'));
 assert.ok(html.includes('value="&lt;query&gt;"')&&html.includes('Work &lt;topic&gt;')&&html.includes('已搁置'));
 assert.ok(html.includes('#career/owner/discussion/source-step/0')&&html.includes('#career/owner/understanding/note')&&html.includes('#career/owner/practice/note'));
 assert.ok(html.includes('#career/owner/question/related')&&html.includes('data-career-review-page="12"'));
 assert.ok(html.includes('Which condition remains unknown?')&&html.includes('1 条接替记录'));
 assert.equal(JSON.stringify(data),before);
 const empty=api.noteReview({goals:[],notes:[],total_count:0,offset:0,next_offset:null},{q:'',goal_id:'',state:'selected',unknown:false});
 assert.ok(empty.includes('还没有符合选择的认识')&&empty.includes('0 份认识'));
 console.log('Cross-goal understanding review: full current and old views, unknowns, exact source-zero links, parked status, prepared-practice navigation, safe filters and empty state passed.');
}

{
 const api=ctx.window.journeyTest,q={...question,source_step_id:'explicit-origin',conclusion_step_id:'reply',question:'A working question <keep its scope>?'},local={...data,questions:[q,{id:'other',question:'Another inquiry?'}],results:[...data.results,
 result('explicit-origin',stamp(0),{kind:'map',question_id:'other'}),
 result('origin-other-reply',stamp(1),{kind:'ask',section:'requirements',question_id:'other',source_step_id:'explicit-origin'}),
 result('quiz',stamp(5),{kind:'teachback',question_id:'q',understanding_check:true}),
 result('feedback',stamp(6),{kind:'answer',question_id:'q',source_step_id:'quiz',understanding_check:true}),
 result('shared-synthesis',stamp(7),{kind:'ask',section:'requirements',question_id:'other',synthesis_sources:[{question_id:'q'}]}),
 ]};
 const before=JSON.stringify(local),rows=api.researchRows(local,'question:q','requirements');
 assert.deepEqual(Array.from(rows,row=>row.step_id).sort(),['explicit-origin','feedback','first','interview','pending','quiz','reply','shared-synthesis']);
 assert.ok(!rows.some(row=>row.step_id==='origin-other-reply'||row.step_id==='other-study'||row.step_id==='unrelated'));
 assert.equal(api.researchRows(local,'all','stories').length,local.results.length);
 assert.ok(!api.researchRows(local,'section','requirements').some(row=>row.kind==='answer'||row.kind==='teachback'));
 assert.equal(api.researchRows(local,'question:missing','requirements').length,0);
 const controls=api.researchViewControls(local,'question:q',rows.length);
 assert.ok(controls.includes('value="question:q" selected')&&controls.includes('A working question &lt;keep its scope&gt;?'));
 assert.ok(controls.includes('#career/goal/inquiry/q')&&controls.includes('data-career-export-journey="q"'));
 assert.ok(!api.researchViewControls(local,'all',local.results.length).includes('data-career-export-journey'));
 const whole='🧪'.repeat(130)+'FULL FINAL QUESTION';
 const header=api.researchResultSummary({...local.results[0],user_question:whole});
 assert.ok(header.includes('🧪'.repeat(120)+'…')&&!header.includes('FULL FINAL QUESTION')&&!header.includes('�'));
 assert.ok(header.includes('<time datetime=')&&header.includes('career-result-heading'));
 assert.equal(JSON.stringify(local),before);
 console.log('Research history views collect exact inquiry links, explicit origins and shared studies across stages, retain unfinished work and preserve canonical scope.');
}

{
 const api=ctx.window.journeyTest,full='Complete old claim. '.repeat(60)+'<FINAL OLD LIMIT>',old={step_id:'remembered',recorded_at:stamp(1),question:'An old question <keep>',claim_details_to_recheck:[{position:24,text:full,basis:'inference',requirement:'preferred'}],unknowns_then:['Unverified production ownership.'],source_references_to_reread:[{title:'Old <raw>',in_current_scope:false}]};
 const result={model_calls:4,career_learning_context:{history_searches:[{matching_count:1}],read_history:[old]}};
 const before=JSON.stringify(result),html=api.learningRecall(result,'goal');
 assert.ok(html.includes('Agent 回查的旧研究')&&html.includes(full.replace('<FINAL OLD LIMIT>','&lt;FINAL OLD LIMIT&gt;')));
 assert.ok(html.includes('原研究第 24 条')&&html.includes('加分')&&html.includes('Unverified production ownership.')&&html.includes('这次回查时不在研究范围内'));
 assert.ok(html.includes('#career/goal/discussion/remembered/23')&&html.includes('Old &lt;raw&gt;'));
 const exported=api.learningRecall(result,'goal',true);assert.ok(exported.includes('FINAL OLD LIMIT')&&!/<a[\s>]/.test(exported)&&!exported.includes('<button'));
 assert.equal(api.researchRecall({...result,model_calls:0},'goal'),'');assert.equal(JSON.stringify(result),before);
 console.log('Agent research recall displays complete historical claims, qualifications and unknowns separately from new evidence, with safe read-only export.');
}

{
 const api=ctx.window.journeyTest,local={...inquiryData,materials:[{id:'raw',title:'Renamed current material'}],tasks:[{id:'task',title:'A failed local experiment'}],results:[result('prior',stamp(1),{user_question:'Old source question <conditions>'})],insights:[{id:'note',current_view:'A later edited view.'}]};
 const row={step_id:'active',kind:'ask',state:'running',user_question:'Current research question',result:{status:'running',model_calls:6,evidence:[{public_document_id:'raw',title:'Historical raw <title>'}],career_learning_context:{read_notes:[{id:'note',current_user_view:'The full view actually read.'}]},trace:[{tool:'search_research_history',terms:['<needle>'],matched:0,private_reasoning:'PRIVATE THOUGHT MUST NOT APPEAR'},{tool:'read_research_history',step_id:'prior'},{tool:'read_archived_documents',windows:[{document_id:'raw',start:0,end:700,has_more:true}]},{tool:'read_learning_note',note_id:'note'},{tool:'read_experiments',experiment_ids:['task']},{tool:'finish_research',validation:'citation_or_coverage_rejected'}]}};
 const before=JSON.stringify(row),items=api.researchActivityItems(row,local);
 assert.equal(items.length,6);assert.ok(items[0].detail.includes('命中 0 条记录'));
 assert.ok(items[2].detail.includes('Historical raw <title>')&&items[2].detail.includes('未读内容'));
 assert.equal(items[3].detail,'The full view actually read.');assert.ok(items[4].label.includes('已记录观察'));
 api.setDraft(local,{activity_open:{'live:active':false,'result:active':true}});
 const live=api.researchActivity(row,local,true),stored=api.researchActivity(row,local);
 assert.ok(live.includes('data-career-activity="live:active"')&&!live.includes('aria-live="off" open'));
 assert.ok(stored.includes('aria-live="off" open')&&stored.includes('本次提交需调整'));
 assert.ok(stored.includes('Historical raw &lt;title&gt;')&&stored.includes('#career/'+local.id+'/discussion/prior'));
 assert.ok(!stored.includes('PRIVATE THOUGHT MUST NOT APPEAR')&&!stored.includes('A later edited view.'));
 const exported=api.researchActivity(row,local,false,true);assert.ok(!/<a[\s>]/.test(exported)&&!exported.includes('<button'));
 assert.ok(api.researchActivity({step_id:'pending'},local,true).includes('尚未收到'));
 assert.equal(api.researchActivity({step_id:'pending'},local),'');assert.equal(JSON.stringify(row),before);
 console.log('Research activity uses actual tool records, retains zero hits and unread limits, separates disclosure states, avoids hidden reasoning and exports safely.');
}

{
 const api=ctx.window.journeyTest,paused={step_id:'paused',kind:'ask',state:'interrupted',scope_current:true,progress:{calls:2,read_fragments:1},continuation:{available:true,remaining_calls:4,remaining_seconds:140},result:{status:'interrupted',claims:[],evidence:[],gaps:[],trace:[{tool:'read_archived_document',public_document_id:'raw',start:0,end:100}]}};
 const local={...inquiryData,running:false,results:[paused],materials:[]};api.setDraft(local,{});
 assert.ok(api.researchControls(local).includes('已暂停'));
 assert.ok(api.coachingResult(paused).includes('已暂停')&&!api.coachingResult(paused).includes('>interrupted<'));
 console.log('Paused research uses readable status labels in the live controls and result card.');
}

{
 const api=ctx.window.journeyTest;
 const long='🧪'.repeat(210)+'末尾条件不得被首页预览覆盖', row={id:'goal',title:'<合成目标>',updated_at:'2026-11-22T10:00:00Z',focus_question_id:'focus',focus_question:long,latest_research:{step_id:'paused',kind:'ask',state:'interrupted',question:'<旧问题>'}};
 const before=JSON.stringify(row), html=api.careerHome([row,{id:'new',title:'无记录目标',goal:'<先理解工作>',updated_at:'invalid'}]);
 assert.ok(html.includes('已暂停')&&html.includes('#career/goal/discussion/paused'));
 assert.ok(html.includes('#career/goal/investigate/focus')&&html.includes('#career/goal/history/focus'));
 assert.ok(html.includes('&lt;合成目标&gt;')&&html.includes('&lt;旧问题&gt;'));
 assert.ok(!html.includes('末尾条件不得被首页预览覆盖')&&!html.includes('Invalid Date'));
 assert.ok(!html.includes('data-career-research')&&!html.includes('/run')&&!html.includes('已验证'));
 assert.equal(JSON.stringify(row),before);
 assert.equal((api.careerHome([row,row,row,row]).match(/data-career-home-goal=/g)||[]).length,3);
 for(const state of ['queued','running','failed','completed','abandoned'])assert.ok(api.careerHome([{...row,latest_research:{...row.latest_research,state}}]).includes('#career/goal/discussion/paused'));
 console.log('Returning home links to saved focus and exact study without research actions or source mutation.');
}

{
 const api=ctx.window.journeyTest,query='失败重试 / 🧪 & <原句>?',values={q:query,record_kind:'discussion',records_offset:'24',sources_offset:'12'},link=api.careerSearchLink(values);
 assert.deepEqual(JSON.parse(JSON.stringify(api.careerSearchValues(link))),values);
 const found={query,scope:'all',record_kind:'discussion',record_count:26,records_offset:24,next_records_offset:null,originals:{evidence:[{id:'ev',public_document_id:'raw',title:'<原文>',quote:'完整末尾条件。',retrieval:{match_location:'body',matched_terms:['条件']}}],offset:12,evidence_count:14,next_offset:null,matching_jobs:0,matching_public_documents:1},records:[{id:'study',step_id:'study',project_id:'other',project_title:'<旧目标>',kind:'discussion',title:'当时的判断',excerpt:'过去的解释。',claim_match_count:1,claim_matches:[{index:0,text:'<旧观点>不能证明实际权限。',basis:'direct',requirement:'unspecified'}]},{id:'note',project_id:'other',kind:'insight',project_title:'旧目标',title:'旧认识',excerpt:'完整记录可回看',use_for_research:false}]};
 const before=JSON.stringify(found),html=api.libraryResults(found);
 assert.ok(html.includes('#career/other/discussion/study/0')&&html.includes('#career/other/insight/note'));
 assert.ok(html.includes('已搁置')&&html.includes('&lt;旧观点&gt;')&&html.includes('data-public-source="raw"'));
 assert.ok(html.includes('data-career-search-page="sources"')&&html.includes('data-career-search-page="records"'));
 for(const action of ['data-career-attach-material','data-career-reuse-record','data-career-library-ask','data-career-check-claim'])assert.ok(!html.includes(action));
 assert.equal(JSON.stringify(found),before);
 const goal={id:'other',document_ids:[],results:[{step_id:'study',state:'completed',current:true,result:{status:'completed'}}]};
 const local=api.libraryResults(found,goal);assert.ok(local.includes('data-career-library-page=')&&local.includes('data-career-attach-material="raw"')&&local.includes('data-career-library-ask="0"'));
 api.setDraft({...inquiryData,...goal},{});assert.ok(api.evidenceLibrary({...inquiryData,...goal}).includes('全部保存的资料与求职目标'));
 assert.ok(api.careerSearchPage(values,found).includes('&lt;原句&gt;')&&!api.careerSearchPage({q:''}).includes('data-career-library-sources'));
 console.log('Goal-independent search preserves query and both page positions, links exact historical claims, and keeps reading separate from goal changes.');
}

{
 const api=ctx.window.journeyTest,quote='🧪'.repeat(210)+'<末尾条件>实际权限未知。',passage={title:'<原文标题>',start:50,end:280,quote,evidence_kind:'search_excerpt'};
 const before=JSON.stringify(passage),html=api.capturePassagePanel(passage,[{id:'goal',title:'<旧目标>'}]);
 assert.ok(html.includes('&lt;末尾条件&gt;实际权限未知。')&&html.includes('&lt;原文标题&gt;'));
 assert.ok(html.includes('搜索线索，尚未核网页正文')&&html.includes('value="goal">&lt;旧目标&gt;'));
 assert.ok(html.includes('name="include_source" checked')&&html.includes('name="question_id"')&&html.includes('保存不调用模型'));
 assert.ok(!html.includes('data-career-research')&&!html.includes('<末尾条件>'));
 assert.equal(JSON.stringify(passage),before);
 console.log('Cross-goal passage capture preserves the full selection, labels search leads, and requires an explicit destination and save.');
}

{
 const api=ctx.window.journeyTest,initial=api.retryLabDefaults();assert.equal(initial.length,4);assert.equal(initial[2].requests[0].request_id,'请求1');assert.equal(initial[2].requests[1].request_id,'请求2');assert.equal(initial[3].requests[1].action,'取消');
 const result={conditions:'本机顺序模拟，没有网络。',outcome:'不能证明真实系统安全。',cases:[{name:'<条件>',requests:[{request_id:'r1',business_id:'<业务>',action:'确认'}],runs:[{label:'按业务与动作',accepted:[1],skipped:[]}]}]};
 const before=JSON.stringify(result),html=api.retryLabResult(result,'goal','task');assert.ok(html.includes('&lt;条件&gt;')&&html.includes('&lt;业务&gt;')&&html.includes('#career/goal/task/task'));
 assert.ok(html.includes('本次实际运行的完整输入')&&html.includes('不能证明真实系统安全。')&&html.includes('下载完整运行记录'));
 assert.ok(!html.includes('成功率')&&!html.includes('已验证岗位能力'));assert.equal(JSON.stringify(result),before);
 const data={...inquiryData,focus_question_id:'q',running:false};api.setDraft(data,{retry_lab:{open:true,cases:initial,question_id:'q',hypothesis:'<运行前的猜想>',result}});
 const panel=api.retryLab(data);assert.ok(panel.includes('value="preview"')&&panel.includes('value="save"')&&panel.includes('&lt;运行前的猜想&gt;'));
 assert.ok(panel.includes('本地顺序模拟')&&panel.includes('不调用模型')&&!panel.includes('data-career-research'));
 const busy=api.retryLab({...data,running:true});assert.ok(/value="save" disabled/.test(busy)&&!/value="preview" disabled/.test(busy));
 console.log('Local retry lab keeps editable conditions, before-run expectations and actual outputs separate, preserves full inputs, and saves only on the explicit run-and-save action.');
}

{
 const api=ctx.window.journeyTest,prediction='完整运行前预期。'.repeat(100)+'末尾限定：不推断真实协议。',probe={kind:'local_sequential_simulation',hypothesis:prediction,conditions:'仅本机顺序计算，没有网络。',outcome:'不是原文证据，实际并发未知。',cases:[{name:'<两种动作>',requests:[{request_id:'r1',business_id:'<业务>',action:'确认'},{request_id:'r2',business_id:'<业务>',action:'取消<条件>'}],runs:[{label:'只按业务编号',accepted:[1],skipped:[2]}]}],private_reasoning:'DO_NOT_RENDER'};
 const result={run_id:'run',model_calls:3,career_learning_context:{local_experiments:[probe]},trace:[{tool:'run_retry_experiment',case_count:1,request_count:2}]},row={step_id:'study',question_id:'q',result},data={...inquiryData,results:[row]};
 result.status='completed';result.claims=[];result.evidence=[];result.gaps=[];row.state='completed';
 const before=JSON.stringify(row),html=api.localExperimentRecall(result,'goal',false,data),archive=api.localExperimentRecall(result,'goal',true,data);
 assert.ok(html.includes(prediction)&&html.includes('&lt;业务&gt;')&&html.includes('&lt;条件&gt;')&&html.includes('data-career-use-retry-probe="study:0"'));
 assert.ok(!html.includes('DO_NOT_RENDER')&&!html.includes('data-career-research'));
 assert.ok(!archive.includes('<button')&&!archive.includes('<form')&&archive.includes('<details open>'));
 assert.ok(api.learningRecall(result,'goal',true,data).includes('Agent本轮运行的本地模拟'));
 const draft=api.retryProbeDraft(row,0);assert.equal(draft.question_id,'q');assert.equal(draft.hypothesis,prediction);assert.ok(!('runs' in draft.cases[0])&&!draft.result&&!draft.saved_task_id);
 draft.cases[0].requests[0].action='不同的输入';assert.equal(JSON.stringify(row),before);
 assert.equal(api.retryProbeDraft({...row,question_id:null},0).question_id,'');
 api.setDraft(data,{});assert.ok(api.coachingResult(row).includes('data-career-use-retry-probe="study:0"'));
 const actions=api.researchActivityItems(row,data);assert.equal(actions[0].label,'运行本地重试与去重模拟');assert.ok(actions[0].detail.includes('1 组、2 条输入'));
 console.log('Agent local probes preserve full predictions and computed inputs, stay separate from source claims, export read-only, and prepare an independent rerun draft.');
}

{
 const api=ctx.window.journeyTest,claim='🧪'.repeat(1100)+'末尾限定：不能推出生产权限。',row={step_id:'source',question_id:null,task_id:null,state:'completed',result:{status:'completed',claims:[{text:claim,evidence_ids:['ev']}],evidence:[{id:'ev',title:'<原文>',quote:'观察条件。'.repeat(500)+'末尾条件必须保留。'}]}};
 const before=JSON.stringify(row),draft=api.claimCorrectionDraft(row,0);
 assert.equal(draft.current_view,'');assert.equal(draft.replaces_insight_id,'');assert.equal(draft.source_claim_index,0);assert.equal(draft.source_step_id,'source');
 assert.equal(draft.observation,'');assert.ok(draft.source_length_notice.includes('完整文字保留'));
 assert.ok(draft.previous_view.includes('Agent原判断')&&!draft.previous_view.includes('🧪'));
 const short=api.claimCorrectionDraft({...row,result:{...row.result,claims:[{text:'局部解释。',evidence_ids:[]}] }},0);assert.equal(short.previous_view,'Agent原判断：\n局部解释。');
 const data={...inquiryData,id:'goal',results:[row],insights:[],questions:[],tasks:[]};api.setDraft(data,{insight:draft});
 const form=api.learningNotes(data);assert.ok(form.includes('留下我的修正与依据')&&form.includes('保存我的修正')&&form.includes('末尾限定：不能推出生产权限。'));
 assert.ok(form.includes('source_claim_index" value="0"')&&!form.includes('data-career-research'));
 assert.ok(form.includes('data-career-open-insight-source="source:0"'));
 assert.equal(JSON.stringify(row),before);
 console.log('Claim correction keeps the full original in its source, leaves the user revision blank, avoids silently replacing beliefs, and preserves long qualifiers.');
}

{
 const data={id:'focused-goal',questions:[{id:'first',question:'First <question>',material_ids:['source-a']},{id:'second',question:'Second question',selected_job_ids:['job-b']}]};
 const before=JSON.stringify(data),t=ctx.window.journeyTest;
 t.setDraft(data,{question:'Unsent whole-goal question',material_ids:['whole-source']});
 assert.equal(t.selectInvestigation('first'),true);
 assert.equal(t.storyDraft().inquiries.requirements.question_id,'first');
 assert.deepEqual(Array.from(t.storyDraft().inquiries.requirements.material_ids),['source-a']);
 t.storyDraft().inquiries.requirements.question='Unsent first-question draft';
 t.selectInvestigation('second');
 assert.equal(t.storyDraft().inquiries.requirements.question_id,'second');
 assert.deepEqual(Array.from(t.storyDraft().inquiries.requirements.selected_job_ids),['job-b']);
 t.storyDraft().inquiries.requirements.question='Unsent second-question draft';
 t.selectInvestigation('first');assert.equal(t.storyDraft().inquiries.requirements.question,'Unsent first-question draft');
 assert.equal(t.selectInvestigation('missing'),false);
 assert.equal(t.storyDraft().inquiries.requirements.question_id,'first');
 t.selectInvestigation(null);assert.equal(t.storyDraft().inquiries.requirements.question,'Unsent whole-goal question');
 t.selectInvestigation('second');assert.equal(t.storyDraft().inquiries.requirements.question,'Unsent second-question draft');
 assert.equal(JSON.stringify(data),before);
 console.log('Single-question workspace keeps separate unsent drafts, exact saved source scope and whole-goal drafts without changing records.');
}

{
 const t=ctx.window.journeyTest,question='What changes when the input changes?',source={step_id:'quiz',kind:'teachback',understanding_check:true,insight_id:'note',result:{status:'completed',gaps:[question]}},long='🧪'.repeat(1100)+'Final condition: no production experience <script>unsafe</script>';
 const answer=(id,n,extra={})=>({step_id:id,kind:'answer',state:'completed',created_at:stamp(n),current:true,understanding_check:true,insight_id:'note',interview_question:question,answer:id==='old'?long:'Full response '+id,result:{status:'completed',claims:[{text:'Feedback '+id,category:'task',basis:'synthesis',requirement:'unspecified',evidence_ids:[]}],evidence:[],gaps:['Still unknown?']},...extra});
 const old=answer('old',1),latest=answer('latest',6),data={id:'answer-goal',title:'Answer comparison',jobs:[],questions:[],tasks:[],stories:[],insights:[],results:[source,old,...[2,3,4,5].map(n=>answer('attempt-'+n,n)),latest,answer('foreign-note',7,{insight_id:'other'}),answer('different-question',8,{interview_question:'Another question?'})]};
 const before=JSON.stringify(data);t.setDraft(data,{});
 const attempts=t.interviewAttempts(source,question,data);assert.equal(attempts.length,6);assert.equal(attempts[0],old);assert.equal(attempts.at(-1),latest);
 const html=t.answerReplay(source,0,data);assert.ok(html.includes('回答过 6 次')&&html.includes('第 6 次回答')&&html.includes('Final condition: no production experience &lt;script&gt;unsafe&lt;/script&gt;'));assert.ok(!html.includes('foreign-note')&&!html.includes('different-question')&&!html.includes('<script>unsafe</script>'));
 const draft=t.answerComparisonDraft([old,latest]);assert.equal(draft.insight_id,'note');assert.equal(draft.question_id,'');assert.deepEqual(Array.from(draft.comparison_step_ids),['old','latest']);assert.equal(draft.source_step_id,'');
 assert.throws(()=>t.answerComparisonDraft([old,old]));assert.throws(()=>t.answerComparisonDraft([old,answer('unfinished',9,{result:null})]));assert.throws(()=>t.answerComparisonDraft([old,answer('wrong-note',9,{insight_id:'other'})]));
 t.setDraft(data,{answer_comparisons:{'quiz:0':{ids:['attempt-3','attempt-5']}}});assert.deepEqual(Array.from(t.answerReplaySelection(source,0,data).pair,row=>row.step_id),['attempt-3','attempt-5']);
 t.setDraft(data,{});const pack=t.answerReplayPackage(source,0,data);assert.ok(pack.startsWith('<!doctype html>')&&pack.includes('Feedback old')&&pack.includes('Feedback latest'));assert.ok(!pack.includes('<button')&&!pack.includes('data-career-')&&!pack.includes('<script>unsafe</script>'));
 const saved={career_learning_context:{answer_comparison:[{step_id:'old',recorded_at:stamp(1),interview_question:question,user_answer:long,claim_details_to_recheck:old.result.claims,unresolved_then:['Original unknown.'],source_references_to_reread:[{title:'Original source',public_document_id:'raw',start:0,end:33,evidence_kind:'work_material'}]}]}};
 const recalled=t.answerComparisonRecall(saved,data.id,true);assert.ok(recalled.includes('Final condition: no production experience')&&recalled.includes('Original unknown.')&&recalled.includes('字符 0–33'));assert.ok(!recalled.includes('<button')&&!recalled.includes('data-career-'));
 assert.equal(JSON.stringify(data),before);
 console.log('Answer practice comparisons retain every attempt, complete long answers and qualifiers, exact practice groups, chosen pairs and read-only historical exports.');
}

{
 const t=ctx.window.journeyTest,quote='Repeated condition.',text='🙂\r\n'+quote+'\r\nLater context: '+quote+'\r\nFinal restriction </script><script>alert(1)</script>',start=Array.from(text.slice(0,text.lastIndexOf(quote))).length;
 const question={id:'portable',question:'How does this condition limit the claim?',state:'open',created_at:stamp(1),source_passage:{public_document_id:'old-public',title:'Original raw',quote,start,end:start+quote.length}};
 const source=(snapshot)=>({document_id:'same-raw-document',job_id:'same-job',snapshot_id:snapshot,title:'JD '+snapshot,quote:'Saved JD quote',start:0,end:14});
 const study=result('portable-study',stamp(2),{question_id:question.id});study.result.evidence=[source('snapshot-a'),source('snapshot-b'),question.source_passage];
 const foreign=result('foreign-study',stamp(3),{question_id:'unrelated'});foreign.result.evidence=[{public_document_id:'unrelated-public'}];
 const data={id:'portable-goal',title:'Portable <investigation>',goal:'Read full conditions',jobs:[],tasks:[{id:'artifact-task',title:'Recorded experiment',state:'done',question_id:question.id,artifact_document_id:'artifact'}],insights:[],questions:[question],results:[study,foreign],materials:[{id:'unread-public',title:'Unused source'}]};
 const before=JSON.stringify(data),records=t.investigationSourceRecords(question,data);
 assert.equal(records.length,4);assert.ok(records.some(row=>row.snapshot_id==='snapshot-a')&&records.some(row=>row.snapshot_id==='snapshot-b'));assert.ok(!records.some(row=>['unrelated-public','unread-public'].includes(row.public_document_id)));
 const original=records.find(row=>row.public_document_id==='old-public');Object.assign(original,{text,integrity:'verified'});
 const rendered=t.archiveSourceText(original),link=t.archiveSourceLink(question.source_passage,records);
 assert.ok(link.includes(original.references[0].anchor));assert.ok(rendered.includes('class="archive-highlight"')&&rendered.includes('Final restriction &lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;'));assert.ok(!rendered.includes('<script>'));
 assert.ok(rendered.indexOf('Repeated condition.')<rendered.indexOf('id="'+original.references[0].anchor+'"'));
 const mismatch=t.archiveSourceText({...original,integrity:'changed'});assert.ok(!mismatch.includes('class="archive-highlight"')&&mismatch.includes('引用位置尚未与附入正文确认'));
 const bad=t.archiveSourceText({...original,references:[{...original.references[0],start:0,end:999999}]});assert.ok(!bad.includes('class="archive-highlight"'));
 const missing=records.find(row=>row.public_document_id==='artifact');Object.assign(missing,{unavailable:'Raw unavailable <unsafe>'});
 const archive=t.investigationArchive(records);assert.ok(archive.includes('未附入正文')&&archive.includes('Raw unavailable &lt;unsafe&gt;'));
 const pack=t.questionJourneyPackage(question,{...data,offline_sources:records});assert.ok(pack.includes('原文档案 · 4 份')&&pack.includes('archive-find')&&pack.includes('Final restriction'));assert.equal((pack.match(/<script>/g)||[]).length,1);assert.ok(!pack.includes('alert(1)</script>')&&!pack.includes('src="http')&&!pack.includes('fetch('));
 assert.equal(JSON.stringify(data),before);
 console.log('Portable investigations collect only linked sources, keep exact JD snapshots and repeated Unicode/CRLF positions, preserve missing-source explanations, and escape raw text in a self-contained reader.');
}

{
 const t=ctx.window.journeyTest,annotation='Full condition '.repeat(70)+'Final user annotation <script>unsafe</script>',question={id:'old-inquiry',question:'Original question with final qualifier',state:'parked',created_at:stamp(1),hypothesis_a:'A is only a working explanation.',hypothesis_b:'B depends on different conditions.',next_evidence:'Still need the responsibility boundary.',evidence_passages:[{public_document_id:'removed',title:'Old raw',start:0,end:9,quote:'Raw quote',relation:'challenges',target_view:'A is only a working explanation.',user_note:annotation,in_current_scope:false}]},saved={model_calls:1,career_learning_context:{inquiry_searches:[{terms:['condition'],matching_count:8}],read_inquiries:[question]}};
 const before=JSON.stringify(saved),html=t.inquiryRecall(saved,'goal');assert.ok(html.includes('Original question with final qualifier')&&html.includes('Full condition ')&&html.includes('Final user annotation &lt;script&gt;unsafe&lt;/script&gt;'));assert.ok(html.includes('本轮回查时不在研究范围内')&&html.includes('暂不研究')&&html.includes('当时用户的标注')&&html.includes('#career/goal/investigate/old-inquiry'));
 const exported=t.inquiryRecall(saved,'goal',true);assert.ok(exported.includes('Final user annotation')&&!exported.includes('<button')&&!exported.includes('data-career-')&&!exported.includes('<script>unsafe</script>'));
 const action=t.researchActivityItems({result:{...saved,trace:[{tool:'read_inquiry',question_id:question.id}]}},{id:'goal',questions:[]});assert.equal(action[0].label,'读取完整调查笔记与反例');assert.equal(action[0].detail,question.question);assert.equal(action[0].href,'#career/goal/investigate/old-inquiry');assert.equal(JSON.stringify(saved),before);
 console.log('Inquiry recall keeps complete question hypotheses, user annotations, old scope and parked status separate from fresh evidence, with safe exports and direct navigation.');
}

{
 const t=ctx.window.journeyTest,rows=[{title:' A ',company:' Team ',description:'Must keep Python. Business preferred. Final qualifier.',data_kind:'synthetic',job_url:'https://example.com/a?track=1'},{title:'B',company:'Other',description:'Responsibility is not stated. <script>unsafe</script>',data_kind:'user_provided',job_url:''}];
 const before=JSON.stringify(rows),values=t.comparisonStartDraft(rows);assert.equal(values[0].title,'A');assert.equal(values[0].description,rows[0].description);assert.equal(values[0].data_kind,'synthetic');assert.ok(!('job_url' in values[1]));assert.equal(JSON.stringify(rows),before);
 assert.throws(()=>t.comparisonStartDraft([rows[0],{...rows[1],description:''}]));assert.throws(()=>t.comparisonStartDraft([rows[0],{...rows[1],description:'https://example.com/jd'}]));assert.throws(()=>t.comparisonStartDraft([rows[0],{...rows[1],job_url:'https://person:password@example.com'}]));
 const fields=t.jdFields({title:'<unsafe>',description:rows[1].description,data_kind:'synthetic'});assert.ok(fields.includes('&lt;unsafe&gt;')&&fields.includes('&lt;script&gt;unsafe&lt;/script&gt;'));assert.ok(!fields.includes('<script>'));
 const panel=t.comparisonStartPanel();assert.equal((panel.match(/data-comparison-start-row=/g)||[]).length,2);assert.ok(panel.includes('不调用模型')&&panel.includes('career-create-comparison'));
 console.log('Two-JD intake validates both originals before saving, preserves wording and source type, shares existing JD fields, and clearly starts a bounded comparison without research calls.');
}

{
 const t=ctx.window.journeyTest,left={id:'job:j1:s1',job_id:'j1',document_id:'d1',snapshot_id:'s1',title:'JD <A>',text:'Full JD A. Final condition: preferred only <script>unsafe</script>',integrity:'verified',evidence_kind:'job_description',data_kind:'synthetic'},right={...left,id:'job:j2:s2',job_id:'j2',document_id:'d2',snapshot_id:'s2',title:'JD B',text:'Full JD B. Ownership unknown.'},data={id:'job-reader-goal',title:'Pair reading',jobs:[{id:'j1',title:'A'},{id:'j2',title:'B'}],document_ids:[]},reading={documents:[left,right],left:left.id,right:right.id,focus:{}};
 const before=JSON.stringify(reading),reference=t.readingReference(left);assert.equal(reference.document_id,'d1');assert.equal(reference.snapshot_id,'s1');assert.equal(reference.job_id,'j1');assert.ok(!('public_document_id' in reference));assert.equal(t.readingReferenceKey(reference),left.id);assert.equal(t.readingReferenceKey(t.readingReference({id:'public-a',title:'Source',evidence_kind:'work_material'})),'public-a');
 const html=t.materialReadingPanel(data,reading);assert.ok(html.includes('本目标选用中')&&html.includes('虚构岗位资料')&&html.includes('Full JD B. Ownership unknown.')&&html.includes('&lt;script&gt;unsafe&lt;/script&gt;'));assert.ok(!html.includes('<script>unsafe</script>'));
 const swapped=t.materialReadingPair(reading,'left',right.id);assert.equal(swapped.left,right.id);assert.equal(swapped.right,left.id);
 const partial=t.materialReadingPanel(data,{...reading,documents:[left,{...right,text:'',integrity:'unavailable',unavailable:'Only an archived summary.'}]});assert.ok(partial.includes('Full JD A.')&&partial.includes('Only an archived summary.'));assert.equal((partial.match(/class="detail-section source-reader"/g)||[]).length,1);
 const pack=t.materialReadingPackage(data,reading);assert.ok(pack.includes('Final condition: preferred only')&&pack.includes('虚构岗位资料')&&pack.includes('&lt;script&gt;unsafe&lt;/script&gt;'));assert.ok(!pack.includes('<button')&&!pack.includes('data-career-'));
 assert.ok(t.jobReadingButton(['j1','j2'],data).includes('data-career-read-jobs="j1:j2"'));assert.equal(t.jobReadingButton(['j1','foreign'],data),'');assert.equal(JSON.stringify(reading),before);
 console.log('JD pair reading keeps exact job/document/snapshot references, separates source types, preserves full text and source labels, swaps distinct columns and keeps one readable side when the other lacks a body.');
}

{
 const t=ctx.window.journeyTest,source={id:'public',public_document_id:'public',title:'Full text',text:'🙂0123456789abcdefghij',integrity:'verified'},length=Array.from(source.text).length;
 const evidence=(start,end,extra={})=>({public_document_id:'public',start,end,title:'Full text',...extra});
 const studies=[{step_id:'first',created_at:stamp(1),kind:'ask',user_question:'First read',result:{evidence:[evidence(0,8)]}},{step_id:'overlap',created_at:stamp(2),kind:'ask',user_question:'Overlapping read',result:{evidence:[evidence(4,12),evidence(4,12)]}},{step_id:'lead',created_at:stamp(3),kind:'ask',result:{evidence:[evidence(0,length,{evidence_kind:'search_excerpt'})]}},{step_id:'other',created_at:stamp(4),kind:'ask',result:{evidence:[evidence(0,length,{public_document_id:'another'})]}}],data={id:'coverage-goal',results:studies};
 const before=JSON.stringify(data),coverage=t.readingCoverage(source,data);assert.equal(coverage.read,12);assert.deepEqual(Array.from(coverage.gaps,row=>Array.from(row)),[[12,length]]);assert.equal(coverage.studies.length,2);assert.deepEqual(Array.from(coverage.ranges,row=>Array.from(row)),[[0,12]]);
 const html=t.readerCoverage(source,data);assert.ok(html.includes('12 / '+length)&&html.includes('12:'+length)&&html.includes('字符覆盖不表示理解或判断正确')&&html.includes('data-career-reading-origin'));const pack=t.readerCoverage(source,data,true);assert.ok(!pack.includes('<button')&&!pack.includes('data-career-')&&pack.includes('Overlapping read'));
 const full=t.readingCoverage(source,{results:[...studies,{step_id:'tail',result:{evidence:[evidence(12,length)]}}]});assert.equal(full.read,length);assert.equal(full.gaps.length,0);assert.equal(t.readingCoverage({...source,id:'new-public',public_document_id:'new-public'},data).read,0);assert.equal(t.readingCoverage({...source,integrity:'changed'},data),null);
 const jd={...source,id:'job:j:s2',job_id:'j',document_id:'d',snapshot_id:'s2'};assert.equal(t.readingCoverage(jd,{results:[{result:{evidence:[{job_id:'j',document_id:'d',snapshot_id:'s1',start:0,end:length}]}}]}).read,0);
 const raw='🙂\r\nRepeated <condition>',chars=Array.from(raw),selected={start:3,end:chars.length},marked=t.sourceReaderText({chars,matches:[],index:0,selected});assert.ok(marked.includes('source-selection-hit')&&marked.includes('data-reader-selected-anchor')&&marked.includes('&lt;condition&gt;'));
 assert.equal(JSON.stringify(data),before);
 console.log('Reader gaps merge exact-source tool ranges once, exclude search leads and other snapshots, preserve interval gaps and research links, and select code-point ranges without claiming comprehension.');
}

{
 const t=ctx.window.journeyTest,groups=t.cohortDefaults().map((row,index)=>({...row,before_rate:index?.1:.9,after_rate:index?.05:.8,change:index?-.05:-.1,before_share:index?.8:.2,after_share:index?.2:.8})),probe={hypothesis:'Prediction '.repeat(100)+'Final prediction qualifier',kind:'local_cohort_comparison',metric:'Registration / visits <scope>',conditions:'Same definition; constructed sample. Final limit.',data_kind:'synthetic',data_origin:'构造的虚构数据',groups,overall:{before_total:500,before_converted:130,after_total:500,after_converted:325,before_rate:.26,after_rate:.65,after_with_before_mix:.2,change:.39,change_with_before_mix:-.06,composition_reversal:true},outcome:'Given inputs only.',notice:'No causal claim.'},row={step_id:'cohort-study',question_id:'q',result:{career_learning_context:{cohort_experiments:[probe]}}},data={id:'cohort-goal',questions:[{id:'q',question:'Check the metric.'}],results:[row]};
 const before=JSON.stringify(row),draft=t.cohortProbeDraft(row,0);assert.equal(draft.question_id,'q');assert.equal(draft.hypothesis,probe.hypothesis);assert.equal(draft.conditions,probe.conditions);assert.equal(draft.groups[0].after_converted,320);assert.ok(!('after_rate' in draft.groups[0]));
 const output=t.cohortOutput(probe);assert.ok(output.includes('65%')&&output.includes('20%')&&output.includes('Final prediction qualifier')&&output.includes('&lt;scope&gt;')&&output.includes('人群占比'));
 const recalled=t.cohortRecall(row.result,data.id,false,data);assert.ok(recalled.includes('data-career-use-cohort-probe="cohort-study:0"'));const exported=t.cohortRecall(row.result,data.id,true,data);assert.ok(exported.includes('Final limit.')&&!exported.includes('<button')&&!exported.includes('data-career-'));
 assert.equal(t.cohortPercent(null),'无法计算（无样本）');assert.ok(t.cohortPercent(0).includes('0%'));assert.ok(t.cohortChange(-.06).includes('-6'));
 t.setDraft(data,{cohort_lab:draft});const panel=t.cohortLab(data);assert.ok(panel.includes('320')&&panel.includes('分群 1 A总数')&&panel.includes('Final prediction qualifier'));assert.equal(JSON.stringify(row),before);
 console.log('Cohort lab preserves complete counts, predictions, conditions and source nature, labels zero samples honestly, shows fixed-mixture results and prepares exact read-only handoffs.');
}

{
 const j=ctx.window.journeyTest;
 const task={id:'exp-origin',question_id:'origin-q',title:'完整<实验>',hypothesis:'原先判断'+ '🤔'.repeat(90),outcome:'本机观察末尾：不能证明真实改进',deliverable:'原始计数',completion_check:'检查口径',comparison_conditions:'限制条件'.repeat(60)+'末尾完整',comparison_rows:[{condition:'群体<甲>',input:'A90/100；B320/400',expected:'待核',observed:'90% → 80%'}],artifact_document_id:'raw-exp'};
 const note={id:'source-note',task_id:task.id,question_id:'origin-q',previous_view:'原认识',current_view:'缩窄后的理解'+ '🤔'.repeat(110),observation:'实际观察',open_question:'需要什么新证据？',use_for_research:false};
 const data={id:'origin-goal',tasks:[task],insights:[note],questions:[{id:'origin-q',question:'原调查',material_ids:['business-raw'],selected_job_ids:['job-a']}],results:[],document_ids:['business-raw','raw-exp']};
 const before=JSON.stringify(data),draft=j.experimentInsightDraft(task);
 assert.strictEqual(draft.previous_view,task.hypothesis);assert.strictEqual(draft.observation,task.outcome);assert.strictEqual(draft.current_view,'');assert.strictEqual(draft.source_step_id,'');
 assert.strictEqual(j.experimentInsightDraft({...task,outcome:'长观察'.repeat(1000)}).observation,'');assert.throws(()=>j.experimentInsightDraft({...task,outcome:''}));
 const question=j.insightQuestionDraft(note,data);assert.strictEqual(question.source_insight_id,note.id);assert.strictEqual(question.parent_question_id,'origin-q');assert.strictEqual(question.question,note.open_question);assert.deepStrictEqual(Array.from(question.material_ids),['business-raw','raw-exp']);assert.deepStrictEqual(Array.from(question.selected_job_ids),['job-a']);assert.strictEqual(question.conclusion,'');assert.strictEqual(question.source_step_id,'');
 const panel=j.insightQuestionOrigin(question,data);assert(panel.includes('完整&lt;实验&gt;')&&panel.includes(task.comparison_conditions)&&panel.includes(note.current_view)&&panel.includes('已搁置'));assert(panel.includes('data-public-source="raw-exp"'));
 const exported=j.insightQuestionOrigin(question,data,true);assert(!exported.includes('data-public-source=')&&!exported.includes('<button'));assert(exported.includes('A90/100；B320/400'));const archived=j.questionJourneyPackage({...question,id:'follow-up',state:'open',created_at:stamp(8),evidence_passages:[]},{...data,title:'调查',goal:'核对解释',jobs:[],materials:[]});assert(archived.includes(note.current_view)&&archived.includes('A90/100；B320/400'));
 const recalled={...note,current_user_view:note.current_view,reported_observation:note.observation,linked_experiment:task};const record=j.learningRecall({model_calls:2,career_learning_context:{origin_learning_note:recalled,notes:[],selections:[]}},data.id,true,data);assert(record.includes('本次问题明确承接')&&record.includes(note.current_view)&&record.includes(task.comparison_conditions)&&record.includes('当时已搁置'));
 assert.strictEqual(JSON.stringify(data),before);
 console.log('Experiment observations become editable personal revisions and source-linked inquiry drafts; complete conditions, parked origins and raw artifact pointers survive read-only recall.');
}

{
 const j=ctx.window.journeyTest,limit='保留限定🤔'.repeat(150)+'末尾迁移条件';
 const row={key:'g:s:0',project_id:'g',project_title:'目标<甲>',step_id:'s',relation_index:0,recorded_at:stamp(2),current:false,question:'完整问题',scope_note:'仅两份资料',scope:{jobs:[]},relation:{source_kind:'task',source_text:'核对<账本>完整任务',source_claim_index:0,target_kind:'deliverable',target_text:'差异清单',target_claim_index:1,predicate:'produces',basis:'inference',rationale:'连接理由'+limit,transfer_limit:limit},claims:[{index:0,basis:'direct',requirement:'unspecified'},{index:1,basis:'direct',requirement:'preferred'}],evidence:[{id:'e0',public_document_id:'raw',title:'合成<原文>',start:0,end:20,evidence_kind:'work_material',quote:'核对账本并交付差异清单。末尾条件保留。'}],unknowns:['验收权未知']};
 const before=JSON.stringify(row),card=j.workRelationCard(row,false,true);assert(card.includes('目标&lt;甲&gt;')&&card.includes('核对&lt;账本&gt;')&&card.includes(limit)&&card.includes('历史记录')&&card.includes('data-work-rel-select'));assert(card.includes('末尾条件保留。')&&card.includes('#career/g/relation/s/0'));
 const html=j.workRelationsPackage([row,{...row,key:'other:s:0',project_title:'另一目标'}]);assert(html.includes(limit)&&html.includes('另一目标')&&html.includes('合成&lt;原文&gt;'));assert(!html.includes('data-work-rel-select')&&!html.includes('<button')&&!html.includes('data-public-source'));
 const values=j.workRelationsValues('#career/work?q=%E9%AA%8C%E6%94%B6&node_kind=task&state=historical&offset=12');assert.strictEqual(values.q,'验收');assert.strictEqual(values.offset,'12');assert.strictEqual(values.state,'historical');const link=j.workRelationsLink(values);assert(link.startsWith('#career/work?')&&link.includes('offset=12'));
 const page=j.workRelationsPage({notice:'记录解释并非事实',goals:[],relations:[row],total_count:13,offset:12,next_offset:null},{q:'验收',goal_id:'',node_kind:'task',predicate:'all',state:'all'});assert(page.includes('匹配 13 条')&&page.includes('data-work-rel-page="0"')&&!page.includes('data-work-rel-page="24"'));assert.strictEqual(JSON.stringify(row),before);
 const second={...row,key:'other:s:0',project_id:'other',evidence:[{...row.evidence[0],public_document_id:'other-raw'}]},carried={work_relations:[row,second],include_sources:false,skipped_sources:[{title:'合成缺失原文',reason:'原文暂不可读'}]};
 const origin=j.carriedWorkRelations(carried,true);assert(origin.includes(limit)&&origin.includes('建立时未带入原文')&&origin.includes('合成缺失原文')&&!origin.includes('<button'));
 const recalled=j.relationComparisonRecall({career_learning_context:{relation_comparison:[row,second]}},true);assert(recalled.includes('本轮带入的两条关系原记录')&&recalled.includes(limit)&&!recalled.includes('data-work-rel-select'));
 const sources=j.investigationSourceRecords({id:'new',carried_understanding:carried},{tasks:[],results:[],insights:[],questions:[]});assert.strictEqual(sources.length,2);assert.deepStrictEqual(Array.from(sources,row=>row.public_document_id),['raw','other-raw']);
 console.log('Work relationship browsing preserves full scoped nodes, reasons, limits, cited source zero and historical labels; selection exports stay read-only and pagination retains filters.');
}

{
 const j=ctx.window.journeyTest,a='解释 A：'+ '同一工具未必对应同一工作。🤔'.repeat(25),b='解释 B：'+ '交付对象和验收边界决定迁移条件。'.repeat(25);
 const q={id:'desk-q',question:'共用工具意味着工作可以迁移吗？',hypothesis_a:a,hypothesis_b:b,evidence_passages:[{id:'support',public_document_id:'same-raw',title:'同一<原文>',start:0,end:6,quote:'支持标注原句',target_view:a,relation:'supports',user_note:'先核对范围'},{id:'challenge',public_document_id:'same-raw',title:'同一<原文>',start:8,end:14,quote:'反例标注原句',target_view:a,relation:'challenges',user_note:'同一正文的另一条标注'},{id:'condition',public_document_id:'second-raw',title:'另一原文',start:0,end:6,quote:'适用条件原句',target_view:b,relation:'conditions',user_note:'条件待核实'},{id:'old',public_document_id:'third-raw',title:'旧解释原文',start:0,end:6,quote:'旧标注原句',target_view:'已改写的旧解释',relation:'supports'}]};
 const data={id:'desk-goal',questions:[q],jobs:[],tasks:[],results:[],insights:[]};const before=JSON.stringify(data);
 const summary=j.passageEvidenceSummary(j.passageGroups(q)[0]);assert(summary.includes('来自 1 份不同归档正文')&&summary.includes('适用条件标注')&&summary.includes('不等于独立事实来源'));
 j.setDraft(data,{passage_filters:{'desk-q':'challenges'}});const filtered=j.questionPassages(q,data);assert(filtered.includes('反例标注原句')&&!filtered.includes('支持标注原句')&&!filtered.includes('旧标注原句'));const exported=j.questionPassages(q,data,true);assert(exported.includes('支持标注原句')&&exported.includes('旧标注原句')&&exported.includes('已改写的旧解释')&&!exported.includes('data-career-passage-filter'));
 const experiment=j.contrastExperimentDraft(q);assert(experiment.hypothesis.includes(a)&&experiment.hypothesis.includes(b));assert.strictEqual(experiment.question_id,q.id);assert.strictEqual(experiment.comparison_rows.length,2);assert(experiment.comparison_rows.every(row=>row.expected===''&&row.observed===''));assert(experiment.completion_check.includes('同时符合或都不符合'));
 assert.throws(()=>j.contrastExperimentDraft({...q,hypothesis_b:a}));assert.throws(()=>j.contrastExperimentDraft({...q,hypothesis_b:''}));
 j.setDraft(data,{manual:experiment,manual_open:true});const form=j.manualExperiment();assert(form.includes('data-career-add-case="manual"')&&form.includes('data-comparison-row="1"')&&form.includes('name="comparison_conditions"'));
 assert.strictEqual(JSON.stringify(data),before);
 console.log('Evidence desk counts exact archived originals rather than votes, filters live annotations without hiding export records and drafts complete competing predictions without inventing observations.');
}

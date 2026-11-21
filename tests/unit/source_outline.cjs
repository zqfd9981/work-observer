// Literal source sections preserve Python-style positions, source text and citation anchors.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const node=()=>({value:'',addEventListener(){},querySelector:node,querySelectorAll:()=>[]});
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:''},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
const text='😀原文前言\r\n岗位职责\r\n1. 内部工具建设\r\n输出内部知识库；不负责外部产品验收。\r\n2. 产品孵化\r\n交付MVP；只在种子用户范围验证。\r\n任职资格\r\n1. 商科背景更佳\r\n条件只作加分，不表示拥有投资决定权。\r\n加分项\r\n- 有用户研究经验\r\n';
ctx.text=text;
const sections=vm.runInContext('sourceOutline(text)',ctx),chars=Array.from(text);
assert.deepEqual(Array.from(sections,row=>row.label),['岗位职责','1. 内部工具建设','2. 产品孵化','任职资格','1. 商科背景更佳','加分项']);
assert.equal(sections[0].start,Array.from('😀原文前言\r\n').length);
const raw=row=>chars.slice(row.start,row.end).join('');
assert.ok(raw(sections[0]).includes('1. 内部工具建设')&&raw(sections[0]).includes('2. 产品孵化'));
assert.ok(!raw(sections[0]).includes('任职资格'));
assert.ok(raw(sections[1]).includes('不负责外部产品验收')&&!raw(sections[1]).includes('产品孵化'));
assert.ok(raw(sections[2]).includes('只在种子用户范围验证')&&!raw(sections[2]).includes('商科背景'));
assert.ok(raw(sections[4]).includes('不表示拥有投资决定权')&&!raw(sections[4]).includes('加分项'));
assert.equal(raw(sections[5]),'加分项\r\n- 有用户研究经验\r\n');
for(const row of sections){assert.ok(row.start<row.heading_end&&row.heading_end<=row.end);assert.equal(chars.slice(row.start,row.heading_end).join('').trim(),row.label);}
ctx.parts=sections;ctx.section=sections[2];
const sourceText=vm.runInContext('sourceReaderText({chars:Array.from(text),matches:[],index:0,citation:{start:parts[4].start,end:parts[4].heading_end},section:{start:section.start,end:section.heading_end}})',ctx);
assert.ok(sourceText.includes('data-reader-section-anchor')&&sourceText.includes('data-reader-anchor'));
assert.ok(sourceText.includes('source-citation-hit')&&sourceText.includes('source-section-hit'));
assert.equal(sourceText.replace(/<[^>]*>/g,''),text);
ctx.unsafe='# <script>alert(1)</script>\n原文限定。\n## 下一节\n只有已读原文。';
const unsafe=vm.runInContext('renderSourceOutline({sections:sourceOutline(unsafe)},true)',ctx);
assert.ok(unsafe.includes('&lt;script&gt;')&&!unsafe.includes('<script>'));
assert.ok(unsafe.includes('data-reader-section-question disabled'));
assert.ok(!vm.runInContext('renderSourceOutline({sections:sourceOutline(unsafe)},false)',ctx).includes('data-reader-section-question'));
assert.equal(vm.runInContext('renderSourceOutline({sections:sourceOutline("普通正文没有标题。")},false)',ctx),'');
ctx.repeated='工作内容\n1. 相同标题\n第一段限定。\n2. 别的部分\n中间文字。\n1. 相同标题\n第二段的不同限定。';
const repeated=vm.runInContext('sourceOutline(repeated)',ctx);
assert.notEqual(repeated[1].start,repeated[3].start);
assert.ok(Array.from(ctx.repeated).slice(repeated[3].start,repeated[3].end).join('').includes('第二段的不同限定'));
ctx.large=Array.from({length:205},(_,i)=>'# 标题'+i+'\n正文\n').join('');
const limited=vm.runInContext('renderSourceOutline({sections:sourceOutline(large)},false)',ctx);
assert.ok(limited.includes('205 项')&&limited.includes('目录仅列出前200项'));
assert.equal((limited.match(/<option value="\d+"/g)||[]).length,200);
console.log('Source outline: literal task lines, complete qualifications, distinct repeated headings, CRLF/Unicode positions, preserved citation marks, escaped text and bounded directory passed.');

{
 ctx.location.hash='#career/search?q=conditions';vm.runInContext('state.page="career"',ctx);
 const global=vm.runInContext('renderSourceReader(text,"原文",{query:"条件"},{public_document_id:"raw"})',ctx);
 assert.ok(global.includes('source-reader-question')&&global.includes('data-reader-section-question')&&!global.includes('data-reader-question-target'));
 assert.ok(global.includes('下一步可选择调查目标'));
 ctx.location.hash='#career/review';assert.ok(!vm.runInContext('renderSourceReader(text,"原文",null,{public_document_id:"raw"})',ctx).includes('source-reader-question'));
 ctx.location.hash='#career/'+'a'.repeat(32);const goal=vm.runInContext('renderSourceReader(text,"原文",null,{public_document_id:"raw"})',ctx);assert.ok(goal.includes('data-reader-question-target'));
 console.log('Reader selections can enter a chosen inquiry from global search while existing goal readers keep their direct question selection.');
}

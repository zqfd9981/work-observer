// Exercise the shipped answer renderer, including its detailed report, against real UI helpers.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map();
function node(key){if(!nodes.has(key))nodes.set(key,{value:'',checked:false,content:'test',addEventListener(){},querySelector:node,querySelectorAll:()=>[]});return nodes.get(key);}
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:''},URL,URLSearchParams,Intl,console,setTimeout,clearTimeout};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
ctx.result={status:'completed',mode:'model',question:'合成研究问题',created_at:'2026-11-24T00:00:00Z',scope:{counts:{matched:1,unknown:0,candidate_details:1},jobs:[{id:'job',title:'合成岗位',company:'合成公司',has_detail:true}]},evidence:[{id:'ev1',job_id:'job',title:'合成岗位',quote:'原文<script>引用',document_id:'doc1',source:'boss',start:0,end:14,observed_at:'2026-11-24T00:00:00Z'}],claims:[{text:'研究回答<script>文本',category:'task',basis:'direct',requirement:'unspecified',evidence_ids:['ev1']}],gaps:['INTERNAL GAP TEXT']};
ctx.target={innerHTML:''};vm.runInContext('renderResult(result,target,"run","step")',ctx);
const answer=ctx.target.innerHTML.split('<details class="conversation-answer-record">')[0];
assert.ok(answer.includes('研究回答&lt;script&gt;文本')&&!answer.includes('<script>'));
assert.ok(answer.includes('data-source="doc1"'));
assert.ok(!answer.includes('研究计划与范围')&&!answer.includes('INTERNAL GAP TEXT')&&!answer.includes('<form'));
assert.ok(ctx.target.innerHTML.includes('执行记录与更多操作')&&ctx.target.innerHTML.includes('INTERNAL GAP TEXT'));
ctx.result={...ctx.result,status:'evidence_only',mode:'offline',claims:[]};
vm.runInContext('renderResult(result,target,"run","step")',ctx);
const packet=ctx.target.innerHTML.split('<details class="conversation-answer-record">')[0];
assert.ok(packet.includes('原文已整理，分析回答尚未生成')&&packet.includes('没有回答你的研究问题'));
assert.ok(!packet.includes('研究计划与范围')&&!packet.includes('INTERNAL GAP TEXT'));
assert.ok(packet.includes('查看原文依据')&&!packet.includes('已生成回答'));
console.log('Conversation reading: answers first, exact source links, honest evidence-only state, escaped text and collapsed execution records passed.');

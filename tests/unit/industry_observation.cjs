const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),handlers={};
function node(key){if(!nodes.has(key))nodes.set(key,{innerHTML:'',textContent:'',value:'',addEventListener(){},replaceChildren(){this.innerHTML='';}});return nodes.get(key);}
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ctx={window:{},document:{addEventListener:(key,handler)=>handlers[key]=handler},location:{hash:''},$:node,$$:()=>[],e:escape,when:v=>v||'未知',console};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
const report={id:'a'.repeat(32),title:'观察<script>',summary:'原文归纳',origin_label:'辅助研究',created_at:'2026-11-23',sample:{jobs:2,readable_details:1,missing_details:1,cited_jobs:1,notice:'非市场占比',observed_from:'2026-11-17',observed_to:'2026-11-18'},sources:[{job_id:'a',title:'岗位甲',source:'boss',transport:'mcp',availability:'verified',document_id:'doc',observed_at:'2026-11-17'},{job_id:'b',title:'岗位乙',source:'boss',availability:'missing_detail'}],findings:[{title:'工作分工',facet:'work',basis:'synthesis',interpretation:'跨资料归纳',boundary:'样本有限',evidence:[{job_id:'a',quote:'业务接口<script>原文',start:0,end:15,role:'职责'}]}],unknowns:['缺正文不能推断'],next_questions:['验收标准？']};
ctx.input=report;const html=vm.runInContext('industryReportView(input)',ctx);
assert.ok(html.includes('观察&lt;script&gt;')&&!html.includes('<script>'));
assert.ok(html.includes('缺正文，不能用于内容判断'));
assert.ok(html.includes('data-source="doc"')&&html.includes('data-job="a"'));
assert.ok(html.includes('data-industry-inquiry="0"'));
assert.ok(html.includes('跨资料归纳')&&html.includes('保存时可核验正文'));
ctx.api=async p=>p==='industry'?[report]:report;
(async()=>{await ctx.window.loadIndustry();assert.ok(node('#industry-report').innerHTML.includes('工作分工'));console.log('Industry observation: evidence links, missing text, scope forms, escaping and report loading passed.');})().catch(error=>{console.error(error);process.exitCode=1;});

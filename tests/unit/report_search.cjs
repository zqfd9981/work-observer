// Search and reopen saved work through the real report library handlers.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),calls=[];
const node=key=>{if(!nodes.has(key))nodes.set(key,{value:'',innerHTML:'',hidden:false,addEventListener(){},querySelector:node,querySelectorAll:()=>[]});return nodes.get(key);};
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:''},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
ctx.calls=calls;ctx.reports=[{report_id:'a',question:'接口责任',status:'evidence_only',created_at:'2026-11-20',match_excerpt:'<script>原文匹配</script>'}];
vm.runInContext('api=async path=>{calls.push(path);return reports;}',ctx);
(async()=>{
 node('#reports-query').value='接口 Python';node('#reports-status').value='evidence_only';
 await vm.runInContext('loadReports()',ctx);
 const url=new URL(calls[0],'http://localhost/');
 assert.equal(url.searchParams.get('q'),'接口 Python');assert.equal(url.searchParams.get('status'),'evidence_only');
 assert.ok(node('#reports-list').innerHTML.includes('&lt;script&gt;原文匹配&lt;/script&gt;'));
 assert.ok(node('#reports-count').textContent.includes('1 份匹配'));
 vm.runInContext('api=async()=>[]',ctx);await vm.runInContext('loadReports()',ctx);
 assert.ok(node('#reports-list').innerHTML.includes('没有找到匹配'));
 vm.runInContext('api=async()=>{throw new Error("旧报告已删除")}',ctx);
 await vm.runInContext('showReport("gone")',ctx);
 assert.equal(node('#reports-search').hidden,true);assert.ok(node('#report-detail').innerHTML.includes('data-report-back'));
 // A slow prior search must not overwrite newer results.
 vm.runInContext('api=()=>new Promise(resolve=>globalThis.deliverReport=resolve)',ctx);
 const pending=vm.runInContext('loadReports()',ctx);
 vm.runInContext('api=async()=>[]',ctx);await vm.runInContext('loadReports()',ctx);
 ctx.deliverReport(ctx.reports);await pending;
 assert.ok(node('#reports-list').innerHTML.includes('没有找到匹配'));
 console.log('Report library: query, type filter, matching excerpt, empty state and reopening passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});

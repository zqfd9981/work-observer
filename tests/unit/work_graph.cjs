// Relationship diagram uses only the supplied map and preserves claim/source distinctions.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const node=()=>({value:'',addEventListener(){},querySelector:node,querySelectorAll:()=>[]});
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:''},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
ctx.result={claims:[{text:'合成交付任务',evidence_ids:['a'],basis:'direct',requirement:'required'}],evidence:[{id:'a',quote:'合成原文'}],work_map:{work_relations:[{source_kind:'task',source_text:'接口开发',target_kind:'deliverable',target_text:'<script>接口产物</script>',predicate:'produces',claim_indices:[0],basis:'inference',rationale:'合成关系解释',transfer_limit:'不能证明个人上线权限'}],ability_relations:[{task:'接口开发',ability:'Python',claim_indices:[0],basis:'direct',rationale:'用于实现接口',transfer_limit:'只限本份资料'}]}};
const original=JSON.stringify(ctx.result);
const render='renderWorkRelationGraph(result,row=>`<button data-cite="a">E1</button>`,row=>"必备：合成交付任务",row=>claimBasisLabel(row))';
const html=vm.runInContext(render,ctx);
assert.ok(html.includes('3 个内容节点 · 2 条关系')); // Shared task is a single node.
assert.ok(html.includes('&lt;script&gt;接口产物&lt;/script&gt;')&&!html.includes('<script>'));
assert.ok(html.includes('不能证明个人上线权限')&&html.includes('必备：合成交付任务'));
assert.ok(html.includes('data-cite="a"')&&html.includes('data-graph-pick="1"'));
assert.ok(html.includes('关联能力')&&!html.includes('NaN'));
assert.equal(JSON.stringify(ctx.result),original);
assert.equal(vm.runInContext('renderWorkRelationGraph({},()=>"",()=>"",()=>"")',ctx),'');
const makeItem=dataset=>({dataset,hidden:true,classes:new Set(),classList:{toggle(name,on){on?this.owner.classes.add(name):this.owner.classes.delete(name);}}});
const detail=[makeItem({graphDetail:'0',graphFrom:'0',graphTo:'1'}),makeItem({graphDetail:'1',graphFrom:'0',graphTo:'2'})];
const edges=[makeItem({graphEdge:'0'}),makeItem({graphEdge:'1'})],nodes=[0,1,2].map(id=>makeItem({graphNode:String(id)}));
for(const item of [...detail,...edges,...nodes])item.classList.owner=item;
ctx.root={querySelectorAll:selector=>({'[data-graph-detail]':detail,'[data-graph-edge]':edges,'[data-graph-node]':nodes})[selector]};
ctx.select={value:'1',closest:()=>ctx.root};
vm.runInContext('selectWorkGraphRelation(select)',ctx);
assert.equal(detail[0].hidden,true);assert.equal(detail[1].hidden,false);
assert.ok(edges[0].classes.has('is-dimmed')&&edges[1].classes.has('is-selected'));
assert.ok(nodes[1].classes.has('is-dimmed')&&!nodes[0].classes.has('is-dimmed'));
ctx.select.value='';vm.runInContext('selectWorkGraphRelation(select)',ctx);
assert.ok(edges.every(edge=>!edge.classes.has('is-dimmed')));
console.log('Work relation graph: shared nodes, original qualifiers, source links, selection and reset passed.');

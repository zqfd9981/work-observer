// Starting a research step follows its record without taking over another page.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const node=()=>({value:'',addEventListener(){},querySelector:node,querySelectorAll:()=>[]});
const ctx={document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},location:{hash:''},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
let events=[];
ctx.history={pushState(_state,_title,hash){events.push(['history',hash]);ctx.location.hash=hash;}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
const source=fs.readFileSync(process.argv[3],'utf8').replace(/\}\)\(\);\s*$/,'window.navigationTest={run:runPreparedResearch,context:(id,hash)=>{career.id=id;career.data={id};location.hash=hash;},adapters:value=>{captureDrafts=value.capture;openCareer=value.open;focusCareerRecord=value.focus;}};})();');
vm.runInContext(source,ctx);
const api=ctx.window.navigationTest,goal='a'.repeat(32),step='b'.repeat(32),other='c'.repeat(32),origin='#career/'+goal+'/investigate/question',reading='#career/'+goal+'/discussion/'+step,otherRoute='#career/'+other+'/investigate/other-question';
function deferred(){let resolve,reject;const promise=new Promise((ok,no)=>{resolve=ok;reject=no;});return {promise,resolve,reject};}
function reset({route=origin,id=goal,run=async()=>({state:'running'}),open=async()=>{}}={}){
 events=[];api.context(id,route);
 ctx.api=async(path,options)=>{events.push(['run',path,options.method,JSON.parse(options.body).step_id]);return run();};
 api.adapters({capture:()=>events.push(['capture']),open:async(id,workspace)=>{events.push(['open',id,workspace]);await open();},focus:(kind,id)=>events.push(['focus',kind,id])});
}
(async()=>{
 const started=deferred();reset({run:()=>started.promise});const work=api.run(goal,step,origin);
 assert.equal(ctx.location.hash,reading);assert.equal(events.filter(e=>e[0]==='open').length,0);
 started.resolve({state:'running'});await work;
 assert.deepEqual(events.filter(e=>e[0]==='run'),[['run','projects/'+goal+'/run','POST',step]]);
 assert.deepEqual(events.filter(e=>e[0]==='open'),[['open',goal,null]]);
 assert.deepEqual(events.filter(e=>e[0]==='focus'),[['focus','discussion',step]]);
 reset({run:async()=>{throw new Error('RESEARCH_BUSY');}});await assert.rejects(()=>api.run(goal,step,origin),/RESEARCH_BUSY/);
 assert.equal(ctx.location.hash,reading);assert.equal(events.filter(e=>e[0]==='run').length,1);assert.equal(events.filter(e=>e[0]==='open').length,1);assert.equal(events.filter(e=>e[0]==='focus').length,1);
 reset({id:other,route:otherRoute});await api.run(goal,step,origin);
 assert.equal(ctx.location.hash,otherRoute);assert.equal(events.filter(e=>e[0]==='run').length,1);assert.equal(events.filter(e=>['history','open','focus'].includes(e[0])).length,0);
 const pending=deferred();reset({run:()=>pending.promise});const away=api.run(goal,step,origin);api.context(other,otherRoute);pending.resolve({state:'running'});await away;
 assert.equal(ctx.location.hash,otherRoute);assert.equal(events.filter(e=>['open','focus'].includes(e[0])).length,0);
 const loaded=deferred(),loading=deferred();reset({open:()=>{loading.resolve();return loaded.promise;}});const moveWhileLoading=api.run(goal,step,origin);await loading.promise;api.context(other,otherRoute);loaded.resolve();await moveWhileLoading;
 assert.equal(ctx.location.hash,otherRoute);assert.equal(events.filter(e=>e[0]==='focus').length,0);
 reset({route:reading});await api.run(goal,step,reading);
 assert.equal(events.filter(e=>e[0]==='history').length,0);assert.equal(events.filter(e=>e[0]==='run').length,1);assert.equal(events.filter(e=>e[0]==='focus').length,1);
 console.log('Research starts and resumes on its reading page, exposes queued state after a start failure, sends only one run request, and preserves navigation made before or during the response without adding duplicate history entries.');
})().catch(error=>{console.error(error);process.exitCode=1;});

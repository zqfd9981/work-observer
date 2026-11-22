// Exploration keeps the tour position without claiming that another record is a tour step.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const leaf=()=>({value:'',dataset:{},textContent:'',disabled:false,open:false,addEventListener(){},querySelector:leaf,querySelectorAll:()=>[],getAttribute(){return null;},setAttribute(){},removeAttribute(){}});
const fields=new Map(),bar=leaf();bar.querySelector=key=>{if(!fields.has(key))fields.set(key,leaf());return fields.get(key);};
const links=Array.from({length:8},(_,i)=>{const attrs={href:'#career/demo/stage-'+i};return {textContent:'① 步骤 '+i,dataset:{demoQuestion:'问题 '+i,demoNote:'说明 '+i},getAttribute:key=>attrs[key]??null,setAttribute:(key,value)=>{attrs[key]=value;},removeAttribute:key=>{delete attrs[key];}};});
const events=[],ctx={document:{querySelector:key=>key==='[data-demo-tourbar]'?bar:leaf(),querySelectorAll:key=>key==='.career-demo-banner [data-demo-step]'?links:[],addEventListener:(kind,fn)=>events.push({kind,fn})},window:{addEventListener(){}},location:{hash:''},history:{state:null,replaceState(value){this.state=value;}},URL,URLSearchParams,console,setTimeout,clearTimeout,Intl};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
const field=selector=>bar.querySelector(selector),navigate=(hash,state=null)=>{ctx.location.hash=hash;ctx.history.state=state;ctx.updateDemoGuide();};
const click=events.find(e=>e.kind==='click'&&e.fn.toString().includes('data-demo-direction')).fn;
const direction=n=>{const button={dataset:{demoDirection:String(n)},closest:key=>key==='[data-demo-tourbar]'?bar:null};click({target:{closest:key=>key==='[data-demo-direction]'?button:null}});ctx.history.state=null;ctx.updateDemoGuide();};
navigate('#career');assert.equal(bar.dataset.demoActiveStep,'-1');assert.equal(field('[data-demo-direction="1"]').textContent,'开始导览 ↗');
navigate(links[3].getAttribute('href'),{otherViewState:'retained'});assert.equal(bar.dataset.demoActiveStep,'3');assert.equal(ctx.history.state.otherViewState,'retained');field('.career-demo-points').open=true;
const drill='#career/demo/discussion/followup';navigate(drill);const drillState={...ctx.history.state};assert.equal(bar.dataset.demoActiveStep,'3');assert(field('[data-demo-position]').textContent.includes('正在浏览其他记录'));assert.equal(field('.career-demo-points').open,true);direction(1);assert.equal(ctx.location.hash,links[4].getAttribute('href'));
navigate(drill,drillState);assert.equal(bar.dataset.demoActiveStep,'3');direction(1);assert.equal(ctx.location.hash,links[4].getAttribute('href'));direction(-1);assert.equal(ctx.location.hash,links[3].getAttribute('href'));
bar.dataset={};navigate(drill,drillState);assert.equal(bar.dataset.demoActiveStep,'3');bar.dataset={};navigate(drill);assert.equal(bar.dataset.demoActiveStep,'-1');direction(1);assert.equal(ctx.location.hash,links[0].getAttribute('href'));assert.equal(field('[data-demo-direction="-1"]').disabled,true);
navigate(links[7].getAttribute('href'));direction(1);assert.equal(ctx.location.hash,links[0].getAttribute('href'));
console.log('The eight-step guide resumes after viewing another record, restores the correct position through history or reload, preserves other history state, and keeps fresh-entry, manual jump and restart behavior.');

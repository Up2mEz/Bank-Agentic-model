const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const vm = require('vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/merchant_sandbox/static/lending.js'), 'utf8');
const elements = new Map();
function setup(values = new Map(), transport) {
  elements.clear();
  const el = id => {
    if (!elements.has(id)) elements.set(id, {value:'human reason', html:'', children:[], insertAdjacentHTML(_, html){this.html += html;}, append(child){this.children.push(child);}});
    return elements.get(id);
  };
  const sent = [];
  const s = {current:{id:'CASE-111111111111'}, busy:false, config:{capabilities:{bank_review:true}},
    crypto:{randomUUID:()=> 'pending-key-123'},
    localStorage:{getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)},
    $:el, document:{createElement:()=>({})}, esc:v=>String(v).replaceAll('<','&lt;'), pair:(k,v)=>`${k}:${v}`, render(){}, async loadQueue(){}, showError(){},
    api:async (path, body)=>{if (!body) return {version:7}; sent.push(JSON.parse(JSON.stringify(body)));return transport(path,body,sent.length);}
  };
  vm.createContext(s); vm.runInContext(source, s);
  vm.runInContext("bankCards.set('CASE-111111111111',{bank:{version:7,kyc:{status:'REVIEW'},business:{},kyb:{status:'PENDING_REVIEW'}}})",s);
  return {s,sent,values,el};
}
const c = {id:'CASE-111111111111',version:3,active:false,state:'REVIEW_READY',packet:{financial:{}}};
for (const [kind, pending, other] of [['loan','APPROVED','DECLINED'],['loan','APPROVED','NEEDS_INFORMATION'],['kyc','APPROVED','DECLINED'],['kyb','VERIFIED','NEEDS_INFORMATION']]) {
  test(`${kind}: pending ${pending} blocks ${other}; reload offers explicit exact recovery`,async()=>{
    const first=setup(new Map(),async()=>{throw Error('lost before delivery');});
    await assert.rejects(first.s.reviewAction(c,kind,pending));
    const saved=[...first.values.values()][0];
    await assert.rejects(first.s.reviewAction(c,kind,other));
    assert.equal(first.sent.length,1,'different decision must never dispatch pending approval');
    assert.equal([...first.values.values()][0],saved);
    const reloaded=setup(first.values,async(_,body)=>({...c,state:body.decision,decision:{status:body.decision}}));
    reloaded.s.renderHumanReview(c);
    for (const id of ['loan-actions','bank-actions']) assert.ok(reloaded.el(id).children.every(b=>b.disabled));
    const recovery=reloaded.el(`recover-${kind}`);
    assert.match(reloaded.el(kind==='loan'?'assessment':'application').html,new RegExp({loan:'อนุมัติ',kyc:'ผ่าน KYC',kyb:'ยืนยันธุรกิจ'}[kind]));
    assert.match(reloaded.el(kind==='loan'?'assessment':'application').html,/human reason/);
    assert.equal(typeof recovery.onclick,'function');
    await recovery.onclick();
    assert.deepEqual(reloaded.sent,[first.sent[0]],'key, version, decision and reason must survive reload');
    assert.equal(first.values.size,0);
  });
}
test('ordinary decision uses selected decision/reason; pending recovery error keeps exact record',async()=>{
  const normal=setup(new Map(),async(_,body)=>({...c,state:body.decision}));
  await normal.s.reviewAction(c,'loan','DECLINED');
  assert.equal(normal.sent[0].decision,'DECLINED');assert.equal(normal.sent[0].reason,'human reason');assert.equal(normal.values.size,0);
  const unknown=setup(new Map(),async()=>{throw Error('lost reply');});
  await assert.rejects(unknown.s.reviewAction(c,'loan','APPROVED'));
  const saved=[...unknown.values.values()][0];
  const restored=setup(unknown.values,async()=>{throw Object.assign(Error('auth interrupted'),{status:403});});
  await assert.rejects(restored.s.reviewAction(c,'loan'));
  assert.equal([...restored.values.values()][0],saved);
});
for(const status of [400,409,422])test(`fresh approval rejection ${status} permits KYB and information actions`,async()=>{
  const initial=setup(new Map(),async(_,body,count)=>{
    if(count===1)throw Object.assign(Error('approval not eligible'),{status});
    return {...c,state:body.decision};
  });
  await assert.rejects(initial.s.reviewAction(c,'loan','APPROVED'));
  assert.equal(initial.values.size,0);
  initial.s.renderHumanReview(c);
  assert.ok(initial.el('bank-actions').children.every(b=>!b.disabled));
  assert.ok(initial.el('loan-actions').children.every(b=>!b.disabled));
  await initial.s.reviewAction(c,'kyb','VERIFIED');
  await initial.s.reviewAction(c,'loan','NEEDS_INFORMATION');
  assert.deepEqual(initial.sent.map(body=>body.decision),['APPROVED','VERIFIED','NEEDS_INFORMATION']);
});
for(const status of [400,401,403,409,422])test(`recovered pending approval error ${status} retains key/body and blocks new choices`,async()=>{
  const first=setup(new Map(),async()=>{throw Error('lost reply');});
  await assert.rejects(first.s.reviewAction(c,'loan','APPROVED'));
  const saved=[...first.values.values()][0];
  const restored=setup(first.values,async()=>{throw Object.assign(Error('recovery rejected'),{status});});
  await assert.rejects(restored.s.reviewAction(c,'loan'));
  await assert.rejects(restored.s.reviewAction(c,'kyb','VERIFIED'));
  assert.deepEqual(restored.sent,[first.sent[0]]);
  assert.equal([...restored.values.values()][0],saved);
});
test('full staff render labels original analysis versions and shows one persisted human result',()=>{
  const nodes=new Map();
  const node=id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',value:'',children:[],querySelectorAll:()=>[],insertAdjacentHTML(_,v){this.innerHTML+=v;},append(v){this.children.push(v);}});return nodes.get(id);};
  const s={document:{getElementById:node,querySelectorAll:()=>[],createElement:()=>({})},localStorage:{getItem:()=>null},setInterval(){}};
  vm.createContext(s);
  const html=fs.readFileSync(path.join(__dirname, '../src/merchant_sandbox/static/index.html'),'utf8');
  const inline=html.match(/<script>([\s\S]*?)<\/script>/)[1].split('(async()=>{try{config=')[0];
  vm.runInContext(inline,s);vm.runInContext(source,s);
  const record={...c,source:'merchant_app',version:4,input:{},results:{onboarding_read:{onboarding_version:7}},policy_snapshot:{assessment:{}},feedback:[],trace:[],state:'APPROVED',decision:{status:'APPROVED',reason:'persisted human result',decided_at:'now',reviewer:'local-reviewer'},packet:{case_version:3,onboarding:{onboarding_version:7},recommendation:'EXCEPTION_REVIEW',financial:{schedule:[],assumptions:[]}}};
  s.record=record;
  vm.runInContext("config={provider:{configured:true},capabilities:{bank_review:true},scenarios:{}};bankCards.set(record.id,{bank:{version:9,kyc:{status:'APPROVED'}}});current=record;render();",s);
  const assessment=node('assessment').innerHTML;
  assert.match(assessment,/ผลวิเคราะห์เดิมของ Agent/);
  assert.match(assessment,/คำขอรุ่นที่วิเคราะห์<\/span><strong>3/);
  assert.match(assessment,/ข้อมูลธนาคารรุ่นที่วิเคราะห์<\/span><strong>7/);
  assert.equal((assessment.match(/<h2>(คำตัดสินโดยเจ้าหน้าที่|การพิจารณาโดยเจ้าหน้าที่)<\/h2>/g)||[]).length,1);
  assert.match(assessment,/persisted human result/);
  assert.match(assessment,/ตารางชำระตามข้อเสนอ/);
  assert.match(node('trace').innerHTML,/ประวัติการทำงาน/);
});

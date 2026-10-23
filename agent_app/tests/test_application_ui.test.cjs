const test=require('node:test');
const assert=require('node:assert/strict');
const {harness}=require('./ui_harness.cjs');
const defaults={scenario:'complete',applicant_name:'Default',email:'mali@example.test',phone:'0800000000',shop_name:'Sample',business_type:'food',business_location:'test',consent:true,requested_thb:'30000.00',purpose:'stock',living_cost_thb:'15000.00',debt_thb:'10000.00',message:'default message'};
const created={id:'CASE-lab1',version:1,state:'DRAFT',input:defaults,documents:[]};
function setup(options={}){
  const h=harness({...options,manual:true});h.context.defaults=defaults;
  h.run("config={defaults:{complete:defaults},capabilities:{agent_review:{configured:true,available:true,modes:['offline','typhoon'],typhoon_configured:true}}};fillManual(defaults);renderManual();");return h;
}
test('manual create merges complete defaults with user values without inventing input keys',async()=>{
  const h=setup({transport:async()=>created});h.node('applicant_name').value='User entered';h.node('debt_thb').value='';
  await h.context.createManualCase();
  assert.equal(h.requests[0].url,'/api/cases');assert.equal(h.requests[0].body.input.applicant_name,'User entered');
  assert.equal(h.requests[0].body.input.debt_thb,null);assert.equal(h.requests[0].body.input.scenario,'complete');
  assert.equal(h.requests[0].body.input.message,'default message');
  assert.deepEqual(Object.keys(h.requests[0].body.input).sort(),Object.keys(defaults).sort());
  assert.equal(h.requests.length,1,'create must not upload or run automatically');
});
for(const kind of ['create','upload','sample','review'])test(`${kind} uncertain result survives reload and retries original path/version/bytes/key`,async()=>{
  const first=setup({transport:async()=>{throw Error('lost response');}});
  if(kind!=='create') { first.context.c=structuredClone(created);first.run("manualState.case=c;"); }
  if(kind==='review')first.run("manualState.case.documents=[{id:'doc',ocr_pages:[{page:1,text:'recorded synthetic'}]}];");
  const actions={create:()=>first.context.createManualCase(),upload:()=>first.context.uploadManualDocument({name:'original.pdf',type:'application/pdf',size:3,arrayBuffer:async()=>Uint8Array.from([65,66,67]).buffer},'statement'),sample:()=>first.context.addSampleDocuments(),review:()=>first.context.startManualReview('offline')};
  await assert.rejects(actions[kind]());const saved=[...first.storage.values()][0];
  first.node('applicant_name').value='changed';await assert.rejects(first.context.createManualCase());
  assert.equal(first.requests.length,1,'pending command blocks incompatible commands');
  const second=setup({storage:first.storage,transport:async()=>kind==='review'?{id:'job-1',status:'QUEUED',stage:'queued'}:{...created,version:2}});
  await second.context.retryManualCommand();
  assert.deepEqual(second.requests.map(x=>({url:x.url,body:x.body})),first.requests.map(x=>({url:x.url,body:x.body})));
  assert.ok(saved.includes('ui-test-key'));
  assert.equal(second.run('manualState.pending'),null);
  if(kind==='upload')assert.deepEqual(second.requests[0].body.document,{kind:'statement',filename:'original.pdf',mime_type:'application/pdf',content_base64:'QUJD'});
});
test('uploaded PDF without recorded OCR cannot silently run offline or replace it with sample',async()=>{
  const h=setup();h.context.c={...created,documents:[{id:'upload',filename:'own.pdf',ocr_pages:[]}]};h.run('manualState.case=c;renderManual();');
  await assert.rejects(h.context.startManualReview('offline'),/OCR/);
  assert.equal(h.requests.length,0);
});
test('explicit sample receipt permits offline for its exact document hash; changed hash is blocked',async()=>{
  const sample={id:'sample-1',kind:'statement',filename:'synthetic-statement.pdf',sha256:'sample-sha',ocr_pages:[]};
  const h=setup({transport:async(url)=>url.endsWith('/sample-documents')?{...created,version:2,documents:[sample]}:{id:'job-sample',status:'QUEUED'}});
  h.context.c=structuredClone(created);h.run('manualState.case=c;');
  await h.context.addSampleDocuments();
  const reloaded=setup({storage:h.storage,transport:async()=>({id:'job-sample',status:'QUEUED'})});
  await reloaded.context.startManualReview('offline');
  assert.equal(reloaded.requests[0].url,'/api/cases/CASE-lab1/evidence-review');
  assert.equal(reloaded.requests[0].body.mode,'offline');
  reloaded.run("manualState.job=null;manualState.case.documents[0].sha256='changed';");
  await assert.rejects(reloaded.context.startManualReview('offline'),/OCR/);
  assert.equal(reloaded.requests.length,1);
});
test('sample endpoint acknowledging an already uploaded sole sample still permits offline',async()=>{
  const sample={id:'existing-sample',kind:'statement',filename:'own-name.pdf',sha256:'sample-sha',ocr_pages:[]};
  const c={...created,documents:[sample]};
  const h=setup({transport:async url=>url.endsWith('/sample-documents')?c:{id:'job-sole-sample',status:'QUEUED'}});
  h.context.c=c;h.run('manualState.case=c;');
  await h.context.addSampleDocuments();await h.context.startManualReview('offline');
  assert.equal(h.requests.length,2);assert.equal(h.requests[1].body.mode,'offline');
});
test('recovered definitive rejection retains pending; fresh validation rejection permits correction',async()=>{
  const h=setup({transport:async()=>{throw Object.assign(Error('invalid'),{status:422});}});
  await assert.rejects(h.context.createManualCase());assert.equal(h.run('manualState.pending'),null);
  const lost=setup({transport:async()=>{throw Error('lost');}});await assert.rejects(lost.context.createManualCase());
  const retry=setup({storage:lost.storage,transport:async()=>{throw Object.assign(Error('conflict'),{status:409});}});
  await assert.rejects(retry.context.retryManualCommand());assert.ok(retry.run('manualState.pending'));
});
test('storage quota failure stops upload before network dispatch and does not discard prior case',async()=>{
  const h=setup();h.context.c=created;h.run('manualState.case=c;');
  h.context.localStorage.setItem=()=>{throw Error('quota exceeded');};
  await assert.rejects(h.context.addSampleDocuments(),/quota/);assert.equal(h.requests.length,0);
  assert.equal(h.run('manualState.case.id'),'CASE-lab1');
});
test('officer pending review blocks a second command from manual page',async()=>{
  const storage=new Map([['merchant-evidence-review-pending:CASE-lab1',JSON.stringify({path:'/api/cases/CASE-lab1/evidence-review',body:{version:1,mode:'offline',idempotency_key:'staff-pending-key'}})]]);
  const h=setup({storage});h.context.c=created;h.run('manualState.case=c;renderManual();');
  assert.equal(h.node('sample-documents').disabled,true);
  await assert.rejects(h.context.addSampleDocuments(),/เจ้าหน้าที่|คำสั่ง/);assert.equal(h.requests.length,0);
});

test('new manual form requires fresh affirmative consent; saved consent is preserved',async()=>{
  const h=setup({transport:async()=>({defaults:{complete:defaults},capabilities:{}})});
  await h.context.initManual();
  assert.equal(h.node('consent').checked,false);
  h.run('manualState.draft={...defaults,consent:true};');
  await h.context.initManual();
  assert.equal(h.node('consent').checked,true);
});

test('manual status distinguishes completed transport from incomplete native review',()=>{
  const h=setup();h.context.c=created;
  h.run("manualState.case=c;manualState.job={id:'technical',status:'COMPLETED',mode:'typhoon',result:{review_state:'TECHNICAL_REVIEW'}};renderManual();");
  assert.match(h.node('manual-review-status').textContent,/ตรวจไม่ครบ.*เทคนิค/);
});

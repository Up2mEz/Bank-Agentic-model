const test = require('node:test');
const assert = require('node:assert/strict');
const {harness} = require('./ui_harness.cjs');
const record = {id:'CASE-111111111111',source:'merchant_app',version:3,state:'REVIEW_READY',input:{shop_name:'ร้านทดสอบ',consent:true},results:{},policy_snapshot:{assessment:{}},feedback:[],trace:[],packet:{financial:{assumptions:[],schedule:[]}},documents:[{id:'doc-1',filename:'test.pdf',kind:'statement',ocr_pages:[]}]};
function selected(options) {
  const h=harness(options);h.context.record=structuredClone(record);
  h.run("config={provider:{configured:true},scenarios:{},capabilities:{bank_review:true,agent_review:{configured:true,modes:['offline','typhoon']}}};current=record;bankCards.set(record.id,{bank:{version:7,kyc:{status:'REVIEW'},business:{}}});render();");return h;
}
test('bank refresh preserves typed reasons including blank edits and renders one human panel',async()=>{
  const h=selected({transport:async()=>({version:8,kyc:{status:'REVIEW'},business:{}})});
  h.node('loan-review-reason').value='เหตุผลที่กำลังเขียน';h.node('bank-review-reason').value='';
  await h.context.loadBankCard(record.id);
  assert.equal(h.node('loan-review-reason').value,'เหตุผลที่กำลังเขียน');
  assert.equal(h.node('bank-review-reason').value,'');
  assert.equal((h.node('assessment').innerHTML.match(/<h2>คำตัดสินโดยเจ้าหน้าที่<\/h2>/g)||[]).length,1);
});
test('legacy nullable case and documents without OCR render without invented OCR results',()=>{
  const h=harness();h.context.record={...record,input:null,results:null,policy_snapshot:null,feedback:null,trace:null,documents:[{id:'old',kind:'statement',filename:'old.pdf',ocr_pages:null}]};
  assert.doesNotThrow(()=>h.run("config={capabilities:{}};current=record;render();"));
  assert.match(h.node('evidence').innerHTML,/ยังไม่มีผล OCR/);
  assert.doesNotMatch(h.node('evidence').innerHTML,/undefined|null/);
});
test('async report shows four sections, escaped questions and references; stale blocks approval',()=>{
  const h=selected();h.context.job={id:'job-1',case_id:record.id,case_version:2,status:'COMPLETED',stage:'report',stale:true,mode:'offline',result:{report:{sections:{supported_sales:{items:[{description:'<script>bad</script>',refs:['doc:p1:r2']}]},follow_up:{items:[{question:'ขอหลักฐานยอดโอน',refs:['doc:p2:r1']}]}}}}};
  h.run('reviewJobs.set(record.id,{job});render();');
  assert.match(h.node('review-status').textContent,/ล้าสมัย/);
  const output=h.node('review-report').innerHTML;
  for(const label of ['รายรับจากการขาย','เงินเข้าที่ไม่ใช่ยอดขาย','ภาระจ่ายที่ระบุได้','ประเด็นค้างและคำถาม','doc:p1:r2','ขอหลักฐานยอดโอน'])assert.ok(output.includes(label),label);
  assert.ok(output.includes('&lt;script&gt;'));assert.ok(!output.includes('<script>'));
  assert.equal(h.node('loan-actions').children[0].disabled,true);
});
test('evidence-review uncertain dispatch survives reload, blocks other mode, replays exact command',async()=>{
  const first=selected({transport:async()=>{throw Error('lost reply');}});
  await assert.rejects(first.context.runEvidenceReview('offline'));
  const saved=[...first.storage.entries()];
  await assert.rejects(first.context.runEvidenceReview('typhoon'));
  assert.equal(first.requests.length,1);
  const second=selected({storage:first.storage,transport:async()=>({id:'job-2',status:'QUEUED',stage:'queued',case_version:3,case_id:record.id})});
  await second.context.runEvidenceReview();
  assert.deepEqual(second.requests.map(x=>({url:x.url,body:x.body})),first.requests.map(x=>({url:x.url,body:x.body})));
  assert.ok(saved.length);assert.equal(second.storage.size,0);
});
test('NOT_STARTED and unavailable capability are visible and never enable an approval',async()=>{
  const h=selected({transport:async()=>({status:'NOT_STARTED',case_id:record.id,case_version:3,stale:false,result:null})});
  await h.context.loadEvidenceReview(record.id);
  assert.match(h.node('review-status').textContent,/ยังไม่มีงาน/);
  assert.equal(h.node('loan-actions').children[0].disabled,true);
  h.run("config.capabilities.agent_review={configured:true,available:false,modes:[],typhoon_configured:false};render();");
  assert.equal(h.node('run-agent').disabled,true);assert.match(h.node('review-status').textContent,/บริการ|ตั้งค่า/);
});
test('poll renders async stage then a failed job with the actual error and keeps typed reason',async()=>{
  const h=selected({transport:async url=>url.endsWith('/evidence-review')?{id:'job-poll',case_id:record.id,case_version:3,status:'FAILED',stage:'ocr',mode:'offline',error:{code:'OCR_REQUIRED',message:'recorded OCR missing'}}:record});
  h.run("reviewJobs.set(record.id,{job:{id:'job-poll',status:'RUNNING',stage:'ocr',mode:'offline',case_version:3}});render();");
  assert.match(h.node('review-status').textContent,/กำลังตรวจ/);assert.match(h.node('review-stage').textContent,/ocr/);
  h.node('loan-review-reason').value='keep during poll';await h.context.pollStaff();
  assert.match(h.node('review-status').textContent,/ไม่สำเร็จ/);assert.match(h.node('review-error').textContent,/OCR_REQUIRED/);
  assert.equal(h.node('loan-review-reason').value,'keep during poll');assert.equal(h.node('loan-actions').children[0].disabled,true);
});
test('a current human-only completed report permits original approval payload; malformed autonomous result does not',async()=>{
  const h=selected({transport:async (url,body)=>body?{...record,decision:{status:body.decision,reason:body.reason},state:body.decision}:url.endsWith('/onboarding')?{version:7}:[]});
  h.context.job={id:'job-ready',case_id:record.id,case_version:3,status:'COMPLETED',mode:'offline',result:{report:{sections:{}},decision:null,human_final_decision_required:true}};
  h.run('reviewJobs.set(record.id,{job});render();');
  assert.equal(h.node('loan-actions').children[0].disabled,false);
  h.node('loan-review-reason').value='verified by human';await h.context.reviewAction(record,'loan','APPROVED');
  const body=h.requests.find(x=>x.body).body;
  assert.deepEqual(body,{version:3,idempotency_key:'ui-test-key-1',decision:'APPROVED',reason:'verified by human',onboarding_version:7});
  const blocked=selected();blocked.context.job={...h.context.job,result:{report:{sections:{}},decision:'APPROVED',human_final_decision_required:false}};
  blocked.run('reviewJobs.set(record.id,{job});render();');
  assert.equal(blocked.node('loan-actions').children[0].disabled,true);
});
test('a delayed GET cannot overwrite the newly accepted review job',async()=>{
  let release;const gate=new Promise(resolve=>release=resolve);
  const h=selected({transport:async (url,body)=>body?{id:'new-job',case_id:record.id,case_version:3,status:'QUEUED'}:gate});
  const older=h.context.loadEvidenceReview(record.id);
  await h.context.runEvidenceReview('offline');
  release({status:'NOT_STARTED'});await older;
  assert.match(h.node('review-stage').textContent,/new-job/);
});
test('recovered evidence command rejection keeps original storage and blocks other mode',async()=>{
  const lost=selected({transport:async()=>{throw Error('lost');}});await assert.rejects(lost.context.runEvidenceReview('offline'));
  const saved=[...lost.storage.entries()];
  const recovered=selected({storage:lost.storage,transport:async()=>{throw Object.assign(Error('stale'),{status:409});}});
  await assert.rejects(recovered.context.runEvidenceReview());await assert.rejects(recovered.context.runEvidenceReview('typhoon'));
  assert.deepEqual([...recovered.storage.entries()],saved);assert.equal(recovered.requests.length,1);
});
test('pending review in manual form blocks a second job from officer page',async()=>{
  const storage=new Map([['merchant-test-application-v1',JSON.stringify({case:{id:record.id},pending:{kind:'review',path:'/api/cases/'+record.id+'/evidence-review',body:{version:3,mode:'offline',idempotency_key:'manual-pending-key'}}})]]);
  const h=selected({storage});
  assert.equal(h.node('run-agent').disabled,true);
  await assert.rejects(h.context.runEvidenceReview('offline'),/แบบฟอร์ม|คำสั่ง/);
  assert.equal(h.requests.length,0);
});

test('native technical review is visibly incomplete and never enables approval',()=>{
  const h=selected();h.context.job={id:'job-technical',case_id:record.id,case_version:3,status:'COMPLETED',mode:'typhoon',result:{report:{sections:{}},review_state:'TECHNICAL_REVIEW',decision:null,human_final_decision_required:true}};
  h.run('reviewJobs.set(record.id,{job});render();');
  assert.match(h.node('review-status').textContent,/ไม่ครบ|เทคนิค/);
  assert.match(h.node('review-status').className,/warning/);
  assert.equal(h.node('loan-actions').children[0].disabled,true);
});

test('follow-up preserves the original question and refs from existing issues, safely escaped',()=>{
  const h=selected();h.context.job={id:'job-question',case_id:record.id,case_version:3,status:'COMPLETED',mode:'offline',result:{decision:null,human_final_decision_required:true,report:{sections:{},existing_issues:[{code:'UNVERIFIED',question:'ขอใบเสร็จ <script> ไม่ใช่เดาว่ายอดขาย',refs:['input:message','DOC-1:p1:r2']}]}}};
  h.run('reviewJobs.set(record.id,{job});render();');
  assert.match(h.node('review-report').innerHTML,/ขอใบเสร็จ &lt;script&gt;/);
  assert.match(h.node('review-report').innerHTML,/DOC-1:p1:r2/);
  assert.doesNotMatch(h.node('review-report').innerHTML,/<script>/);
});

test('Android unresolved dispatch blocks fresh jobs and recovery retains the original binding through reload',async()=>{
  const h=selected({transport:async()=>{throw Error('lost recovery reply');}});
  h.run("current={...record,revision:11,state:'TECHNICAL_REVIEW',results:{evidence_review:{case_version:3,status:'SUBMITTING',mode:'typhoon',idempotency_key:'original-android-key',job_id:null}}};render();");
  assert.equal(h.node('run-agent').disabled,true);
  assert.equal(h.node('recover-dispatch').hidden,false);
  await assert.rejects(h.context.runEvidenceReview('offline'));
  assert.equal(h.requests.length,0);
  await assert.rejects(h.context.recoverEvidenceDispatch());
  const original=h.requests[0];
  assert.deepEqual(original.body,{version:3,revision:11,mode:'typhoon',idempotency_key:'original-android-key'});
  assert.equal(original.url,'/api/cases/'+record.id+'/evidence-review/recover');
  const reload=selected({storage:h.storage,transport:async()=>({...record,revision:12,active:true,state:'PROCESSING',results:{evidence_review:{idempotency_key:'original-android-key'}}})});
  await reload.context.runEvidenceReview();
  assert.deepEqual(reload.requests[0].body,original.body);
  assert.equal(reload.requests[0].url,original.url);
  assert.equal(reload.storage.size,0);
});

test('staff trace exposes the terminal safe attempt receipt and usage even when the job failed',()=>{
  const h=selected();
  h.context.job={id:'failed-paid-job',status:'FAILED',case_version:3,error:{code:'REVIEW_EXECUTION_FAILED',usage:{ocr_calls:1,total_tokens:11},trace:[{kind:'llm_attempt',attempt:2,status:'REJECTED',rejection:{stage:'finish_reason',tool_count:0}}]}};
  h.run('reviewJobs.set(record.id,{job});render();');
  assert.match(h.node('trace').innerHTML,/finish_reason/);
  assert.match(h.node('trace').innerHTML,/ocr_calls/);
});

test('unresolved Android command disables only the new loan information request while keeping reason and pending recovery',async()=>{
  const h=selected({transport:async()=>{throw Error('synthetic lost decision reply');}});
  h.run("current={...record,state:'TECHNICAL_REVIEW',packet:null,results:{evidence_review:{status:'SUBMITTING',case_version:3,idempotency_key:'retained-android-key'}}};render();");
  h.node('loan-review-reason').value='Keep this human reason';
  h.run('render();');
  assert.equal(h.node('loan-actions').children[2].disabled,true);
  assert.equal(h.node('loan-actions').children[1].disabled,false);
  assert.equal(h.node('loan-review-reason').value,'Keep this human reason');
  assert.equal(h.requests.length,0);
  const pending={path:'/api/cases/'+record.id+'/decision',body:{version:3,idempotency_key:'original-human-key',decision:'NEEDS_INFORMATION',reason:'Previously accepted or uncertain reason'}};
  h.storage.set('merchant-review-pending:'+record.id+':loan',JSON.stringify(pending));
  h.run('render();');
  assert.equal(Boolean(h.node('recover-loan').disabled),false);
  await assert.rejects(h.context.reviewAction(h.run('current'),'loan'));
  assert.deepEqual(h.requests[0].body,pending.body);
  assert.equal(h.storage.get('merchant-review-pending:'+record.id+':loan'),JSON.stringify(pending));
  assert.equal(h.node('loan-review-reason').value,'Keep this human reason');
});

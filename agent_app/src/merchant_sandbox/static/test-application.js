'use strict';

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const manualFields = ['applicant_name','shop_name','email','phone','business_type','business_location','purpose','requested_thb','living_cost_thb','debt_thb','message'];
const manualSlot = 'merchant-test-application-v1';
let config = {}, manualBusy = false, manualPolling = false, storageError = null;
let manualState = {case:null, pending:null, draft:null, job:null, samples:[]};
try {
  const saved = localStorage.getItem(manualSlot);
  if (saved) {
    const value = JSON.parse(saved);
    if (!value || typeof value !== 'object' || Array.isArray(value) || (value.pending && (!value.pending.path || !value.pending.body?.idempotency_key))) throw Error('รูปแบบข้อมูลไม่ถูกต้อง');
    manualState = {...manualState, ...value};
  }
} catch { storageError = 'อ่านข้อมูลคำสั่งเดิมไม่ได้ กรุณาเก็บข้อมูลใน browser นี้ไว้เพื่อตรวจสอบ ยังเริ่มคำสั่งใหม่ไม่ได้'; }

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Review-Nonce':config.review_nonce || ''},body:JSON.stringify(body)});
  let data;
  try { data = await response.json(); } catch { throw Object.assign(Error('อ่านคำตอบจากบริการไม่ได้ ยังเก็บคำสั่งเดิมไว้'),{status:response.status}); }
  if (!response.ok) throw Object.assign(Error(data?.error || 'คำสั่งไม่สำเร็จ'),{status:response.status,code:data?.code});
  return data;
}
function manualError(error) { $('error').textContent = error.message; $('error').hidden = false; }
function persistManual(next) {
  // Save before dispatch, and atomically save the receipt before releasing pending.
  // Quota/private-mode errors must stop dispatch, never switch to memory-only keys.
  localStorage.setItem(manualSlot, JSON.stringify(next));
  manualState = next;
}
function fillManual(data) {
  for (const name of manualFields) $(name).value = data[name] ?? '';
  $('consent').checked = data.consent === true;
}
function manualInput() {
  const defaults = config.defaults?.complete;
  if (!defaults || typeof defaults !== 'object') throw Error('ยังไม่มีค่าเริ่มต้น complete จาก config');
  const data = structuredClone(defaults);
  for (const name of manualFields) data[name] = $(name).value.trim();
  for (const name of ['living_cost_thb','debt_thb']) if (!data[name]) data[name] = null;
  data.consent = $('consent').checked;
  return data;
}
function manualCapability() {
  const cap = config.capabilities?.agent_review;
  return {configured:cap?.configured === true && cap.available === true, modes:Array.isArray(cap?.modes) ? cap.modes.filter(m=>m==='offline'||(m==='typhoon' && cap.typhoon_configured === true)) : []};
}
function ensureManualNewCommand() {
  if (storageError) throw Error(storageError);
  if (manualBusy) throw Error('กำลังส่งคำสั่ง กรุณารอผล');
  if (manualState.pending) throw Error('มีคำสั่งรอตรวจผล กรุณาลองคำสั่งเดิมก่อน');
  if (officerPending()) throw Error('มีคำสั่งตรวจหลักฐานค้างที่พื้นที่เจ้าหน้าที่ กรุณาตรวจผลคำสั่งเดิมที่หน้านั้น');
}
function officerPending() { return Boolean(manualState.case?.id && localStorage.getItem('merchant-evidence-review-pending:'+manualState.case.id)); }
function manualCasePath(action) {
  if (!manualState.case?.id) throw Error('กรุณาสร้างเคสก่อน');
  return '/api/cases/' + encodeURIComponent(manualState.case.id) + '/' + action;
}
async function sendManualCommand(kind, path, body, recovering = false) {
  if (storageError) throw Error(storageError);
  if (manualBusy) throw Error('กำลังส่งคำสั่ง กรุณารอผล');
  if (!recovering) {
    ensureManualNewCommand();
    persistManual({...manualState, pending:{kind,path,body}});
  }
  const pending = manualState.pending;
  if (!pending) throw Error('ไม่มีคำสั่งเดิมที่ค้าง');
  manualBusy = true; $('error').hidden = true; renderManual();
  try {
    const result = await api(pending.path, pending.body);
    let next;
    if (pending.kind === 'review') {
      const job = result?.job || result;
      if (!job?.id) throw Error('ยังไม่มีหมายเลขงานตอบกลับ กรุณาลองคำสั่งเดิม');
      next = {...manualState,job:{...job,stale:Boolean(result.stale || job.stale)},pending:null};
    } else {
      if (!result?.id || !Number.isInteger(result.version)) throw Error('คำตอบไม่มีเคสหรือรุ่นข้อมูล กรุณาลองคำสั่งเดิม');
      const previousIds = new Set((manualState.case?.documents || []).map(doc=>doc.id));
      const samples = pending.kind === 'sample' ? [
        ...(manualState.samples || []),
        // A successful exact-sample command with one existing statement also
        // proves byte deduplication. With mixed existing documents, stay conservative.
        ...(result.documents || []).filter(doc=>doc?.kind==='statement' && doc.sha256 && (!previousIds.has(doc.id) || result.documents.length === 1)).map(doc=>({id:doc.id,sha256:doc.sha256}))
      ] : manualState.samples;
      next = {...manualState,case:result,samples,pending:null};
    }
    persistManual(next);
  } catch (error) {
    if (!recovering && [400,409,422].includes(error.status)) persistManual({...manualState,pending:null});
    else error.message += ' · ยังเก็บคำสั่งเดิมพร้อม key และข้อมูลเดิมไว้';
    throw error;
  } finally { manualBusy = false; renderManual(); }
}
async function createManualCase() {
  ensureManualNewCommand();
  if (manualState.case) throw Error('มีเคสทดสอบแล้ว หากต้องการเริ่มใหม่ให้ใช้ปุ่มเริ่มเคสใหม่');
  const input = manualInput();
  persistManual({...manualState,draft:input});
  await sendManualCommand('create','/api/cases',{input,idempotency_key:crypto.randomUUID()});
}
async function uploadManualDocument(file, kind) {
  ensureManualNewCommand();
  const path = manualCasePath('documents'), version = manualState.case.version;
  if (!file || !['identity','business','statement'].includes(kind)) throw Error('กรุณาเลือกไฟล์และประเภทเอกสาร');
  if (!file.size || file.size > 3 * 1024 * 1024) throw Error('เลือกไฟล์ขนาดไม่เกิน 3 MiB เพื่อเก็บคำสั่งกู้คืนใน browser ได้');
  manualBusy = true; renderManual();
  let document;
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = '';
    for (let offset=0;offset<bytes.length;offset+=8192) binary += String.fromCharCode(...bytes.subarray(offset,offset+8192));
    document = {kind,filename:file.name,mime_type:file.type || (file.name.toLowerCase().endsWith('.pdf') ? 'application/pdf' : 'application/octet-stream'),content_base64:btoa(binary)};
  } finally { manualBusy = false; renderManual(); }
  await sendManualCommand('upload',path,{version,document,idempotency_key:crypto.randomUUID()});
}
async function addSampleDocuments() {
  ensureManualNewCommand();
  await sendManualCommand('sample',manualCasePath('sample-documents'),{version:manualState.case.version,idempotency_key:crypto.randomUUID()});
}
async function startManualReview(mode) {
  ensureManualNewCommand();
  const path = manualCasePath('evidence-review'), cap = manualCapability();
  if (!cap.configured || !cap.modes.includes(mode)) throw Error('บริการหรือโหมดตรวจหลักฐานนี้ยังไม่พร้อม');
  const docs = Array.isArray(manualState.case.documents) ? manualState.case.documents : [];
  if (!manualState.case.input?.consent || !docs.length) throw Error('ต้องยืนยันความยินยอมและแนบเอกสารก่อน');
  if (['QUEUED','RUNNING'].includes(manualState.job?.status)) throw Error('มีงานตรวจที่ยังไม่เสร็จ');
  if (mode === 'offline' && docs.some(doc=>!hasRecordedOCR(doc))) throw Error('Offline ต้องมี recorded OCR ของทุกเอกสาร กรุณาใช้ bundled sample อย่างชัดเจน หรือเลือก Typhoon เพื่อ OCR ไฟล์ที่อัปโหลด');
  await sendManualCommand('review',path,{version:manualState.case.version,mode,idempotency_key:crypto.randomUUID()});
}
async function retryManualCommand() { await sendManualCommand(null,null,null,true); }
function hasSampleReceipt(doc) { return Boolean(doc?.sha256 && (manualState.samples || []).some(sample=>sample.id===doc.id && sample.sha256===doc.sha256)); }
function hasRecordedOCR(doc) { return Boolean(doc && ((Array.isArray(doc.ocr_pages) && doc.ocr_pages.length) || hasSampleReceipt(doc))); }
function renderManual() {
  const c = manualState.case, pending = manualState.pending, externalPending = officerPending(), locked = manualBusy || Boolean(pending) || Boolean(storageError) || externalPending;
  const active = ['QUEUED','RUNNING'].includes(manualState.job?.status), cap = manualCapability();
  $('intake-fields').disabled = locked || Boolean(c); $('create-case').disabled = locked || Boolean(c) || !config.defaults?.complete;
  for (const id of ['upload-document','sample-documents','document-file','document-kind']) $(id).disabled = locked || !c || active;
  $('new-case').disabled = locked || active; $('refresh-case').disabled = locked || !c;
  const previous = $('manual-review-mode').value;
  $('manual-review-mode').innerHTML = '<option value="">เลือกโหมดตรวจหลักฐาน</option>' + cap.modes.map(m=>`<option value="${m}">${m==='offline'?'Offline · recorded OCR / ไม่เรียก LLM':'Typhoon · OCR/โมเดลจริง'}</option>`).join('');
  $('manual-review-mode').value = cap.modes.includes(previous) ? previous : cap.modes.includes('offline') ? 'offline' : '';
  $('manual-review-mode').disabled = locked || !cap.configured || active;
  $('start-review').disabled = locked || !c || active || !cap.configured || !$('manual-review-mode').value;
  $('retry-command').hidden = !pending; $('retry-command').disabled = manualBusy || Boolean(storageError);
  $('pending-command').hidden = !pending && !externalPending;
  $('pending-command').textContent = pending ? `ยังไม่ทราบผลคำสั่ง ${pending.kind} · เก็บ version, key และข้อมูลเดิมไว้แล้ว ปุ่มลองคำสั่งเดิมจะส่งข้อมูลเดิมทุกครั้ง` : externalPending ? 'มีคำสั่งค้างในพื้นที่เจ้าหน้าที่ กรุณาเปิดพื้นที่เจ้าหน้าที่จากลิงก์ด้านบนเพื่อตรวจผลเดิมก่อน' : '';
  $('manual-case').innerHTML = c ? `<strong>${esc(c.id)} · ข้อมูลรุ่น ${esc(c.version)}</strong> · <a href="/?case=${encodeURIComponent(c.id)}">เปิดในพื้นที่เจ้าหน้าที่ →</a>` : 'ยังไม่ได้สร้างเคส';
  const docs = Array.isArray(c?.documents) ? c.documents : [];
  $('manual-documents').innerHTML = docs.length ? '<ul>'+docs.filter(Boolean).map(doc=>`<li>${esc(doc.filename || doc.id)} · ${esc(doc.kind)} · ${hasSampleReceipt(doc) ? 'Bundled sample สังเคราะห์ · บริการจะใช้ recorded OCR ที่ผูก hash · ไม่เรียก LLM ใน Offline' : hasRecordedOCR(doc) ? 'มีข้อความ OCR ที่บันทึกไว้ โปรดตรวจแหล่งที่มา' : 'ยังไม่มีผล OCR หรือการแยกประเภทรายการ'}</li>`).join('')+'</ul>' : '<p class="notice">ยังไม่มีเอกสาร</p>';
  const job = manualState.job;
  const stale = job && (job.stale || (job.case_version != null && job.case_version !== c?.version));
  const incomplete = job?.result?.review_state === 'TECHNICAL_REVIEW';
  $('manual-review-status').textContent = !cap.configured ? 'ยังไม่ได้ตั้งค่าหรือติดต่อบริการตรวจหลักฐานไม่ได้' : job ? `${incomplete ? 'ตรวจไม่ครบ / ปัญหาเทคนิค · ' : ''}${job.status} · ขั้นตอน ${job.stage || 'ยังไม่ทราบ'} · ${job.mode || 'ไม่ทราบโหมด'}${stale ? ' · ผลล้าสมัย ต้องตรวจใหม่' : ''}` : 'ยังไม่มีงานตรวจหลักฐาน';
  $('manual-review-error').textContent = job?.error ? (typeof job.error === 'string' ? job.error : JSON.stringify(job.error)) : '';
  $('manual-review-error').hidden = !job?.error;
  if (storageError) manualError(Error(storageError));
}
async function refreshManualCase() {
  if (manualBusy || manualState.pending || storageError || !manualState.case) return;
  manualBusy = true; renderManual();
  try {
    config = await api('/api/config');
    const id = manualState.case.id, c = await api('/api/cases/'+encodeURIComponent(id));
    persistManual({...manualState,case:c});
    const response = await api('/api/cases/'+encodeURIComponent(id)+'/evidence-review');
    const job = response?.job || response;
    persistManual({...manualState,job:job?.id ? {...job,stale:Boolean(response.stale || job.stale)} : null});
  } finally { manualBusy = false; renderManual(); }
}
async function initManual() {
  $('manual-form').onsubmit = event=>{event.preventDefault();createManualCase().catch(manualError);};
  $('upload-document').onclick = ()=>uploadManualDocument($('document-file').files[0],$('document-kind').value).catch(manualError);
  $('sample-documents').onclick = ()=>addSampleDocuments().catch(manualError);
  $('start-review').onclick = ()=>startManualReview($('manual-review-mode').value).catch(manualError);
  $('manual-review-mode').onchange = renderManual;
  $('retry-command').onclick = ()=>retryManualCommand().catch(manualError);
  $('refresh-case').onclick = ()=>refreshManualCase().catch(manualError);
  $('new-case').onclick = ()=>{
    try {
      ensureManualNewCommand();
      if (['QUEUED','RUNNING'].includes(manualState.job?.status)) throw Error('กรุณารอให้งานเดิมเสร็จก่อน');
      persistManual({case:null,pending:null,draft:null,job:null,samples:[]});fillManual({...config.defaults.complete,consent:false});$('error').hidden=true;renderManual();
    } catch(e) {manualError(e);}
  };
  for (const name of [...manualFields,'consent']) $(name).oninput = ()=>{
    if (manualState.case || manualState.pending || storageError) return;
    try { persistManual({...manualState,draft:manualInput()}); } catch(e) {manualError(e);}
  };
  renderManual();
  try {
    config = await api('/api/config');
    if (!config.defaults?.complete) throw Error('ไม่มี complete defaults จากบริการ');
    fillManual(manualState.draft || manualState.case?.input || {...config.defaults.complete,consent:false});
    renderManual();
    if (manualState.case && !manualState.pending) await refreshManualCase();
  } catch(e) { manualError(e); }
  setInterval(async()=>{
    if (manualPolling || manualBusy || manualState.pending || !['QUEUED','RUNNING'].includes(manualState.job?.status)) return;
    manualPolling = true;
    try { await refreshManualCase(); } catch(e) {manualError(e);} finally {manualPolling=false;}
  },1500);
}
document.addEventListener('DOMContentLoaded',initManual);

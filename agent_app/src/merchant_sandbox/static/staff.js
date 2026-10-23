'use strict';

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const list = value => Array.isArray(value) ? value.filter(x => x != null) : [];
const number = value => value == null || !Number.isFinite(Number(value)) ? 'ยังไม่ทราบ' : Number(value).toLocaleString('th-TH', {minimumFractionDigits:2, maximumFractionDigits:2});
const pair = (label, value) => `<div class="pair"><span>${esc(label)}</span><strong>${esc(value ?? 'ยังไม่ทราบ')}</strong></div>`;
const raw = value => '<pre>' + esc(JSON.stringify(value ?? {}, null, 2)) + '</pre>';
const statusText = {DRAFT:'รอตรวจหลักฐาน', REVIEW_READY:'พร้อมพิจารณา', WAIT_CUSTOMER:'รอข้อมูลเพิ่ม', EXCEPTION_REVIEW:'รอตรวจเพิ่มเติม', APPROVED:'อนุมัติแล้ว', DECLINED:'ไม่อนุมัติ', TECHNICAL_REVIEW:'รอแก้ปัญหาเทคนิค'};
let config = {}, current = null, cases = [], busy = false, selection = 0, activeTab = 'application', polling = false;
let renderedCaseId = null;
const reasonDrafts = new Map(), reviewJobs = new Map(), reviewLoads = new Map();
const reviewPendingSlot = id => 'merchant-evidence-review-pending:' + id;
function retainedDispatch(c) {
  const record = c.results?.evidence_review;
  return record && !['COMPLETED','FAILED'].includes(record.status) ? record : null;
}

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method:'POST', headers:{'Content-Type':'application/json', 'X-Review-Nonce':config?.review_nonce || ''}, body:JSON.stringify(body)
  });
  let data;
  try { data = await response.json(); } catch { throw Object.assign(Error('ไม่สามารถอ่านคำตอบจากบริการได้'), {status:response.status}); }
  if (!response.ok) throw Object.assign(Error(data?.error || 'โหลดข้อมูลไม่สำเร็จ'), {status:response.status, code:data?.code});
  return data;
}
function showError(error) { $('error').textContent = error.message; $('error').hidden = false; }
function statusBadge(c) { return `<span class="badge">${esc(c.active ? 'กำลังประมวลผล' : statusText[c.state] || c.state || 'ยังไม่ทราบ')}</span>`; }
function tab(id) {
  activeTab = id;
  document.querySelectorAll('[data-tab]').forEach(b => { const on = b.dataset.tab === id; b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; });
  document.querySelectorAll('[role="tabpanel"]').forEach(p => { p.hidden = p.id !== id; });
}
function captureReasons() {
  if (!renderedCaseId) return;
  const values = reasonDrafts.get(renderedCaseId) || {};
  for (const id of ['loan-review-reason','bank-review-reason']) if ($(id)) values[id] = $(id).value;
  reasonDrafts.set(renderedCaseId, values);
}
function restoreReasons(c) {
  const values = reasonDrafts.get(c.id) || {};
  for (const id of ['loan-review-reason','bank-review-reason']) if ($(id)) {
    if (Object.hasOwn(values, id)) $(id).value = values[id];
    $(id).oninput = captureReasons;
  }
}
function renderQueue() {
  const q = $('search').value.trim().toLowerCase(), state = $('filter').value;
  const visible = cases.filter(c => (!state || c.state === state) && (!q || [c.id,c.applicant_name,c.shop_name].join(' ').toLowerCase().includes(q)));
  $('queue-count').textContent = `${visible.length} จาก ${cases.length} คำขอที่โหลด`;
  $('queue').innerHTML = visible.map(c => `<button class="case ${current?.id === c.id ? 'selected' : ''}" data-case="${esc(c.id)}" aria-pressed="${current?.id === c.id}" ${busy ? 'disabled' : ''}><strong>${esc(c.shop_name || c.applicant_name || c.id)}</strong><span class="mono">${esc(c.id)} · v${esc(c.version)}</span><div>${statusBadge(c)}</div></button>`).join('') || '<p class="empty">ไม่พบคำขอตามเงื่อนไข</p>';
  $('queue').querySelectorAll('[data-case]').forEach(b => { b.onclick = () => selectCase(b.dataset.case).catch(showError); });
}
async function loadQueue() { cases = list(await api('/api/cases')); renderQueue(); }
async function selectCase(id) {
  if (busy) return;
  const ticket = ++selection, data = await api('/api/cases/' + encodeURIComponent(id));
  if (ticket !== selection || busy) return;
  captureReasons(); current = data;
  localStorage.setItem('merchant-review-case', id); $('error').hidden = true;
  render(); renderQueue();
  await Promise.allSettled([loadEvidenceReview(id), ...(data.source === 'merchant_app' ? [loadBankCard(id)] : [])]);
}
function agentReviewCapability() {
  const cap = config?.capabilities?.agent_review;
  if (!cap || typeof cap !== 'object') return {configured:false, modes:[]};
  const configured = cap.configured === true && cap.available !== false;
  let modes = Array.isArray(cap.modes) ? cap.modes : Object.keys(cap.modes || {}).filter(k => cap.modes[k] === true);
  if (!modes.length) modes = ['offline','typhoon'].filter(k => cap[k] === true);
  return {configured, modes:configured ? modes.filter(m => ['offline','typhoon'].includes(m) && (m !== 'typhoon' || cap.typhoon_configured !== false)) : []};
}
function pendingEvidenceReview(id) {
  const saved = localStorage.getItem(reviewPendingSlot(id));
  if (!saved) return null;
  try {
    const value = JSON.parse(saved);
    if (!value?.path || !value.body?.idempotency_key) throw Error();
    return value;
  } catch { throw Error('อ่านคำสั่งตรวจหลักฐานที่ค้างไม่ได้ กรุณาเก็บข้อมูลเดิมไว้เพื่อตรวจสอบ'); }
}
function pendingManualCase(id) {
  try {
    const saved = JSON.parse(localStorage.getItem('merchant-test-application-v1') || 'null');
    return saved?.case?.id === id && Boolean(saved.pending);
  } catch { return false; }
}
function jobIsStale(c, job) { return Boolean(job?.stale || (job?.case_version != null && job.case_version !== c.version)); }
function evidenceDecisionBlocked(c) {
  // Legacy installations retain their original human workflow. Once configured,
  // incomplete, unavailable or stale review output must never enable approval.
  if (!config?.capabilities?.agent_review) return false;
  const entry = reviewJobs.get(c.id), job = entry?.job;
  return !agentReviewCapability().configured || Boolean(entry?.error) || !job || jobIsStale(c, job) || job.status !== 'COMPLETED' || job.result?.review_state === 'TECHNICAL_REVIEW' || !job.result?.report || job.result.decision !== null || job.result.human_final_decision_required !== true || Boolean(localStorage.getItem(reviewPendingSlot(c.id))) || pendingManualCase(c.id);
}
function reviewEntry(data) {
  const job = data?.job || data;
  return job?.id ? {job:{...job, stale:Boolean(data?.stale || job.stale)}} : {job:null};
}
async function loadEvidenceReview(id) {
  const ticket = (reviewLoads.get(id) || 0) + 1; reviewLoads.set(id, ticket);
  try {
    const entry = reviewEntry(await api('/api/cases/' + encodeURIComponent(id) + '/evidence-review'));
    if (ticket === reviewLoads.get(id)) reviewJobs.set(id, entry);
  } catch (error) {
    if (ticket === reviewLoads.get(id)) reviewJobs.set(id, error.status === 404 ? {job:null} : {...reviewJobs.get(id), error:error.message});
  }
  if (current?.id === id) render();
}
async function runEvidenceReview(mode = null) {
  if (busy || !current) return;
  const c = current, slot = reviewPendingSlot(c.id);
  if (pendingManualCase(c.id)) throw Error('มีคำสั่งรอตรวจผลในแบบฟอร์มทดสอบ กรุณากลับไปลองคำสั่งเดิมที่หน้านั้น');
  let pending = pendingEvidenceReview(c.id);
  const recovering = mode === null;
  if (!recovering && retainedDispatch(c)) throw Error('งาน Android เดิมยังไม่ทราบผล กรุณากู้คืนคำสั่งเดิมก่อน');
  if (pending && !recovering) throw Error('มีคำสั่งตรวจหลักฐานรอตรวจผล กรุณาลองคำสั่งเดิม');
  if (!pending && recovering) throw Error('ไม่มีคำสั่งตรวจหลักฐานที่ค้าง');
  if (!pending) {
    const cap = agentReviewCapability(), job = reviewJobs.get(c.id)?.job;
    if (!cap.configured || !cap.modes.includes(mode)) throw Error('ยังไม่ได้ตั้งค่าโหมดตรวจหลักฐานนี้');
    if (c.active || ['APPROVED','DECLINED'].includes(c.state) || hasPendingReview(c) || ['QUEUED','RUNNING'].includes(job?.status)) throw Error('คำขอนี้ยังเริ่มงานตรวจใหม่ไม่ได้');
    if (!c.input?.consent || !list(c.documents).length) throw Error('ต้องมีความยินยอมและเอกสารก่อนตรวจหลักฐาน');
    pending = {path:'/api/cases/' + encodeURIComponent(c.id) + '/evidence-review', body:{version:c.version, mode, idempotency_key:crypto.randomUUID()}};
    localStorage.setItem(slot, JSON.stringify(pending));
  }
  busy = true; render(); renderQueue();
  // Fence any older GET that could otherwise overwrite the newly accepted job.
  reviewLoads.set(c.id, (reviewLoads.get(c.id) || 0) + 1);
  try {
    const data = await api(pending.path, pending.body);
    if (pending.path.endsWith('/evidence-review/recover')) {
      if (data?.id !== c.id || data.version !== pending.body.version || data.results?.evidence_review?.idempotency_key !== pending.body.idempotency_key) throw Error('คำตอบกู้คืนไม่ตรงกับคำสั่งเดิม เก็บคำสั่งไว้ตรวจสอบ');
      if (current?.id === c.id && (current.revision == null || data.revision >= current.revision)) current = data;
      localStorage.removeItem(slot);
      return;
    }
    const entry = reviewEntry(data);
    if (!entry.job) throw Error('บริการไม่ส่งหมายเลขงานกลับมา ยังเก็บคำสั่งเดิมไว้');
    reviewJobs.set(c.id, entry); localStorage.removeItem(slot);
  } catch (error) {
    if (!recovering && [400,409,422].includes(error.status)) localStorage.removeItem(slot);
    throw error;
  } finally { busy = false; if (current?.id === c.id) render(); renderQueue(); }
}
async function recoverEvidenceDispatch() {
  if (busy || !current) return;
  const record = retainedDispatch(current);
  if (!record || current.active || current.state !== 'TECHNICAL_REVIEW') throw Error('ยังไม่สามารถกู้คืนงานเดิมได้ กรุณาโหลดสถานะล่าสุด');
  if (pendingEvidenceReview(current.id)) return runEvidenceReview();
  if (record.case_version !== current.version || !Number.isInteger(current.revision)) throw Error('รุ่นคำขอไม่ตรงกับคำสั่งเดิม หยุดการกู้คืน');
  const pending = {path:'/api/cases/' + encodeURIComponent(current.id) + '/evidence-review/recover',body:{version:current.version,revision:current.revision,mode:record.mode,idempotency_key:record.idempotency_key}};
  localStorage.setItem(reviewPendingSlot(current.id),JSON.stringify(pending));
  return runEvidenceReview();
}
function reportHTML(report) {
  if (!report || typeof report !== 'object') return '<p>ยังไม่มีรายงานที่อ่านได้</p>';
  return [
    ['supported_sales','รายรับจากการขายที่มีหลักฐานรองรับ'],
    ['non_sales_inflows','เงินเข้าที่ไม่ใช่ยอดขาย'],
    ['identifiable_obligations','ภาระจ่ายที่ระบุได้'],
    ['follow_up','ประเด็นค้างและคำถาม']
  ].map(([key,label], index) => {
    const section = report.sections?.[key] || {};
    const items = [...list(section.items), ...(key === 'follow_up' ? list(report.existing_issues).filter(issue => issue.question && !list(section.items).some(item => item.question === issue.question)) : [])];
    return `<section class="report-section"><h3>${index + 1}. ${label}</h3>${section.credit_total_thb != null ? pair('ยอดรับที่รวม (บาท)',number(section.credit_total_thb)) : ''}${section.debit_total_thb != null ? pair('ยอดจ่ายที่รวม (บาท)',number(section.debit_total_thb)) : ''}<ul>${items.map(item => `<li><p>${esc(item.description || item.question || item.code || 'รายการรอตรวจ')}</p>${item.question && item.description ? '<p class="question">'+esc(item.question)+'</p>' : ''}${item.amount_thb != null ? '<p>'+number(item.amount_thb)+' บาท · '+esc(item.support_level || 'UNVERIFIED')+'</p>' : ''}${item.exclusion_reason ? '<p>ไม่รวมยอด: '+esc(item.exclusion_reason)+'</p>' : ''}<p class="refs">อ้างอิง: ${esc(list(item.refs).join(', ') || 'ยังไม่มีอ้างอิง')}</p></li>`).join('') || '<li class="notice">ยังไม่มีรายการที่มีหลักฐานรองรับในส่วนนี้</li>'}</ul></section>`;
  }).join('') + `<details><summary>การตรวจเอกสารและข้อมูลรายเดือน</summary>${raw({document_checks:report.document_checks, monthly_cashflow_summary:report.monthly_cashflow_summary})}</details>`;
}
function renderEvidenceReview(c) {
  const cap = agentReviewCapability(), entry = reviewJobs.get(c.id), job = entry?.job;
  const active = ['QUEUED','RUNNING'].includes(job?.status), stale = jobIsStale(c, job);
  const ownPending = Boolean(localStorage.getItem(reviewPendingSlot(c.id))), manualPending = pendingManualCase(c.id);
  const pending = ownPending || manualPending;
  const labels = {QUEUED:'รอคิว',RUNNING:'กำลังตรวจหลักฐาน',COMPLETED:'ตรวจเสร็จ รอเจ้าหน้าที่พิจารณา',FAILED:'ตรวจไม่สำเร็จ',INTERRUPTED:'งานถูกขัดจังหวะ ต้องตรวจผลก่อนเริ่มใหม่'};
  const technical = job?.status === 'COMPLETED' && job.result?.review_state === 'TECHNICAL_REVIEW';
  if (technical) labels.COMPLETED = 'ตรวจไม่ครบ — Agent มีปัญหาเทคนิค รายงานนี้เป็นหลักฐานบางส่วน';
  $('review-status').textContent = !cap.configured ? 'ยังไม่ได้ตั้งค่าบริการ Agent ตรวจหลักฐาน' : entry?.error ? 'ติดต่อบริการตรวจหลักฐานไม่ได้: '+entry.error : stale ? 'ผลล้าสมัย — ข้อมูลเคสหรือเอกสารเปลี่ยนแล้ว ต้องตรวจใหม่' : labels[job?.status] || 'ยังไม่มีงานตรวจหลักฐาน';
  $('review-status').className = 'review-status ' + (technical || stale || entry?.error || ['FAILED','INTERRUPTED'].includes(job?.status) || !cap.configured ? 'warning' : '');
  $('review-stage').textContent = job ? `งาน ${job.id} · ${job.mode === 'offline' ? 'Offline · OCR ที่บันทึกไว้ ไม่เรียกโมเดล' : job.mode === 'typhoon' ? 'Typhoon · เรียก OCR/โมเดลจริง' : 'ไม่ทราบโหมด'} · ขั้นตอน: ${job.stage || job.status} · ข้อมูลรุ่น ${job.case_version ?? 'ไม่ทราบ'}` : '';
  $('review-error').textContent = job?.error ? (typeof job.error === 'string' ? job.error : JSON.stringify(job.error)) : '';
  $('review-error').hidden = !job?.error;
  const selectedMode = $('review-mode').value;
  $('review-mode').innerHTML = '<option value="">เลือกโหมดตรวจหลักฐาน</option>' + cap.modes.map(m => `<option value="${m}">${m === 'offline' ? 'Offline · ใช้ OCR ที่บันทึกไว้' : 'Typhoon · OCR/โมเดลจริง'}</option>`).join('');
  $('review-mode').value = cap.modes.includes(selectedMode) ? selectedMode : cap.modes.includes('offline') ? 'offline' : '';
  $('review-mode').disabled = busy || active || pending || !cap.configured;
  $('run-agent').disabled = busy || c.active || active || pending || Boolean(retainedDispatch(c)) || !cap.configured || !$('review-mode').value || ['APPROVED','DECLINED'].includes(c.state) || !c.input?.consent || !list(c.documents).length || hasPendingReview(c);
  $('recover-dispatch').hidden = !retainedDispatch(c) || ownPending;
  $('recover-dispatch').disabled = busy || c.active || c.state !== 'TECHNICAL_REVIEW' || !cap.configured;
  $('recover-review').hidden = !ownPending; $('recover-review').disabled = busy || c.active;
  $('review-pending').hidden = !pending;
  $('review-pending').textContent = manualPending ? 'มีคำสั่งค้างในแบบฟอร์มทดสอบ กรุณาเปิดแบบฟอร์มทดสอบจากลิงก์ด้านบนแล้วลองคำสั่งเดิมก่อนเริ่มงานอื่น' : 'ยังไม่ทราบผลคำสั่งเดิม ระบบเก็บ mode, version และ key เดิมไว้ กรุณาตรวจผลเดิมก่อนเริ่มงานอื่น';
  $('review-report').innerHTML = job?.result?.report ? reportHTML(job.result.report) : '<p class="empty">เมื่อประมวลผลสำเร็จ รายงาน 4 ส่วนพร้อมอ้างอิงและคำถามจะแสดงที่นี่</p>';
  $('review-report').className = stale ? 'stale-report' : '';
  $('review-report-label').textContent = stale ? 'รายงานเดิม · ใช้ดูประวัติเท่านั้น' : 'รายงานตรวจหลักฐาน';
}
function renderLegacyAssessment(c) {
  const r = c.results || {}, f = c.packet?.financial || r.financial_calculate;
  return `<details><summary>ผลวิเคราะห์เดิมของ Agent · ข้อเสนอและสูตรสาธิต</summary>${pair('คำขอรุ่นที่วิเคราะห์',c.packet?.case_version ?? r.onboarding_read?.case_version ?? 'ยังไม่มีผล')}${pair('ข้อมูลธนาคารรุ่นที่วิเคราะห์',c.packet?.onboarding?.onboarding_version ?? r.onboarding_read?.onboarding_version ?? 'ยังไม่มีผล')}${pair('วงเงินเสนอจากกฎสาธิต',number(f?.proposed_limit_thb))}<p class="notice">เป็นผลตามข้อมูลรุ่นเดิม ไม่ใช่คำตัดสินสินเชื่อหรือโมเดล PD ที่ผ่าน validation</p>${f ? `<h2>ตารางชำระตามข้อเสนอ</h2><div class="tablewrap"><table><thead><tr><th>งวด</th><th>เงินต้น</th><th>ดอกเบี้ย</th><th>ชำระรวม</th></tr></thead><tbody>${list(f.schedule).map(x=>`<tr><td>${esc(x.installment)}</td><td>${number(x.principal_thb)}</td><td>${number(x.interest_thb)}</td><td>${number(x.payment_thb)}</td></tr>`).join('')}</tbody></table></div>${raw(f)}` : '<p>ยังไม่มีผลคำนวณ</p>'}${raw(c.policy_snapshot)}</details>`;
}
function render() {
  if (!current) return;
  if (renderedCaseId === current.id) captureReasons();
  const focus = document.activeElement, focusedId = focus?.id, caret = focus?.selectionStart;
  const c = current;
  $('empty-workspace').hidden = true; $('workspace').hidden = false;
  $('shop-title').textContent = c.input?.shop_name || c.input?.applicant_name || c.id;
  $('case-meta').innerHTML = esc(c.id) + ' · ข้อมูลรุ่น '+esc(c.version)+' · '+statusBadge(c);
  $('requested').textContent = number(c.input?.requested_thb) + ' บาท';
  $('feedback').innerHTML = list(c.feedback).length ? '<div class="callout">'+list(c.feedback).map(x=>'<p>'+esc(x)+'</p>').join('')+'</div>' : '';
  renderUploaded(c);
  $('assessment').innerHTML = renderLegacyAssessment(c);
  if (c.source === 'merchant_app') renderHumanReview(c);
  else $('assessment').insertAdjacentHTML('beforeend', `<article><h2>คำตัดสินโดยเจ้าหน้าที่</h2>${pair('ผลปัจจุบัน',c.decision?.status || 'ยังไม่มีคำตัดสิน')}<p class="notice">แบบฟอร์มนี้เป็นเคสทดสอบ การตัดสินคำขอลูกค้าจริงอยู่ในขั้นตอนเจ้าหน้าที่ของ Android intake</p></article>`);
  const job = reviewJobs.get(c.id)?.job;
  $('trace').innerHTML = `<h2>ประวัติการทำงาน</h2><details><summary>ขั้นตอน Agent และการใช้โมเดล</summary>${raw({job:job && {id:job.id,status:job.status,stage:job.stage,mode:job.mode,usage:job.result?.usage || job.error?.usage,trace:job.result?.trace || job.error?.trace},legacy_trace:list(c.trace)})}</details><details><summary>ข้อมูลเคส JSON</summary>${raw(c)}</details>`;
  renderEvidenceReview(c);
  renderedCaseId = c.id; restoreReasons(c); tab(activeTab);
  if (focusedId && $(focusedId)) { $(focusedId).focus(); if (caret != null && $(focusedId).setSelectionRange) $(focusedId).setSelectionRange(caret,caret); }
}
async function pollStaff() {
  if (polling || !current || busy) return;
  const id = current.id, job = reviewJobs.get(id)?.job;
  if (!current.active && !['QUEUED','RUNNING'].includes(job?.status)) return;
  polling = true;
  try {
    const data = await api('/api/cases/'+encodeURIComponent(id));
    if (current?.id === id && (data.revision == null || current.revision == null || data.revision >= current.revision)) { current = data; render(); }
    await loadEvidenceReview(id);
  } catch (error) { if (current?.id === id) { reviewJobs.set(id,{...reviewJobs.get(id),error:error.message});render(); } }
  finally { polling = false; }
}
async function initStaff() {
  document.querySelectorAll('[data-tab]').forEach((button,index,buttons) => {
    button.onclick = () => tab(button.dataset.tab);
    button.onkeydown = event => {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      const n = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length-1 : (index+(event.key === 'ArrowRight' ? 1 : -1)+buttons.length)%buttons.length;
      buttons[n].focus(); tab(buttons[n].dataset.tab);
    };
  });
  $('search').oninput = renderQueue; $('filter').onchange = renderQueue;
  $('refresh').onclick = async () => { if (busy) return; try { config = await api('/api/config'); await loadQueue(); if (current) await selectCase(current.id); } catch(e) {showError(e);} };
  $('run-agent').onclick = () => runEvidenceReview($('review-mode').value).catch(showError);
  $('review-mode').onchange = render;
  $('recover-review').onclick = () => runEvidenceReview().catch(showError);
  $('recover-dispatch').onclick = () => recoverEvidenceDispatch().catch(showError);
  $('download').onclick = () => {
    if (!current) return;
    const a = document.createElement('a'), url = URL.createObjectURL(new Blob([JSON.stringify({case:current,evidence_review:reviewJobs.get(current.id)?.job},null,2)],{type:'application/json'}));
    a.href=url; a.download=current.id+'-review.json'; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  setInterval(pollStaff,1500);
  try {
    config = await api('/api/config');
    $('capability-banner').textContent = 'พื้นที่ตรวจในเครื่อง · คำขอลูกค้าจริงรับผ่าน Android · การตรวจหลักฐานไม่ใช่การอนุมัติสินเชื่อ';
    await loadQueue();
    const preferred = new URL(location.href).searchParams.get('case') || localStorage.getItem('merchant-review-case');
    const id = cases.find(c=>c.id===preferred)?.id || cases[0]?.id;
    if (id) await selectCase(id);
  } catch (error) { showError(error); }
}
document.addEventListener('DOMContentLoaded', initStaff);

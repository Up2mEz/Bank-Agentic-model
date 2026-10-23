/* Uploaded applications: all OCR text is escaped, never interpreted as HTML. */
const bankCards=new Map();
const reviewKinds=['loan','kyc','kyb'];
const reviewSlot=(c,kind)=>'merchant-review-pending:'+c.id+':'+kind;
const pendingReview=(c,kind)=>{
  const saved=localStorage.getItem(reviewSlot(c,kind));
  if(!saved)return null;
  try{const pending=JSON.parse(saved);if(!pending?.body||!pending.path)throw Error();return pending;}
  catch{throw Error('อ่านคำสั่งพิจารณาที่ค้างไม่ได้ กรุณาเก็บข้อมูลเดิมไว้เพื่อตรวจสอบ');}
};
const hasPendingReview=c=>reviewKinds.some(kind=>pendingReview(c,kind));
const reviewChoiceLabel=(kind,choice)=>({loan:{APPROVED:'อนุมัติ',DECLINED:'ไม่อนุมัติ',NEEDS_INFORMATION:'ขอข้อมูลเพิ่ม'},kyc:{APPROVED:'ผ่าน KYC',DECLINED:'ไม่ผ่าน KYC',RESUBMISSION_REQUESTED:'ขอข้อมูลตัวตนเพิ่ม'},kyb:{VERIFIED:'ยืนยันธุรกิจ',NEEDS_INFORMATION:'ขอข้อมูลธุรกิจเพิ่ม'}}[kind]?.[choice]||choice);
function renderReviewRecovery(c,kind,target){
  const pending=pendingReview(c,kind);
  if(!pending)return;
  const label=reviewChoiceLabel(kind,pending.body.decision);
  $(target).insertAdjacentHTML('beforeend',`<article class="card" role="alert"><h2>รอตรวจผลคำสั่งเดิม: ${esc(label)}</h2>${pair('เหตุผลเดิม',pending.body.reason)}<p>ยังไม่ทราบผลคำสั่งนี้ กรุณาตรวจผลเดิมก่อนเลือกคำตัดสินใหม่</p><button id="recover-${kind}">ตรวจผลคำสั่งเดิม: ${esc(label)}</button></article>`);
  const button=$('recover-'+kind);button.disabled=busy||c.active;
  button.onclick=()=>reviewAction(c,kind).catch(showError);
}
async function loadBankCard(id){
  try{const bank=await api('/api/cases/'+encodeURIComponent(id)+'/onboarding');bankCards.set(id,{bank});}
  catch(e){bankCards.set(id,{error:e.message});}
  if(current?.id===id)render();
}
function renderHumanReview(c){
  const entry=bankCards.get(c.id),b=entry?.bank,final=['APPROVED','DECLINED'].includes(c.state),blocked=busy||c.active||final||hasPendingReview(c);
  const labels={APPROVED:'ผ่าน KYC',REVIEW:'รอเจ้าหน้าที่ตรวจ',RESUBMISSION_REQUESTED:'ขอข้อมูลตัวตนเพิ่ม',DECLINED:'ไม่ผ่าน KYC',NOT_STARTED:'ยังไม่เริ่ม',VERIFIED:'ตรวจธุรกิจแล้ว',PENDING_REVIEW:'รอตรวจธุรกิจ',NEEDS_INFORMATION:'ขอข้อมูลธุรกิจเพิ่ม',ACTIVE:'ใช้งานได้',NOT_OPEN:'ยังไม่เปิด',BLOCKED:'ระงับใช้งาน'};
  const bankStatus=v=>labels[v]||v||'ยังไม่ทราบ';
  $('application').insertAdjacentHTML('beforeend',`<article class="card"><h2>สถานะ KYC / กระเป๋า / ธุรกิจจากธนาคาร</h2><button id="reload-bank">โหลดสถานะล่าสุด</button>${entry?.error?'<p role="alert">'+esc(entry.error)+'</p>':''}${b?pair('ข้อมูลธนาคารรุ่น',b.version)+pair('KYC',bankStatus(b.kyc?.status))+pair('กระเป๋า',bankStatus(b.wallet?.status))+pair('KYB',bankStatus(b.kyb?.status))+pair('หมายเหตุ KYC',b.kyc?.reason||'—')+pair('หมายเหตุธุรกิจ',b.kyb?.reason||'—')+pair('การยืนยันตัวตน',b.is_mock?'ผู้ให้บริการจำลอง':'ตามผลจากธนาคาร'):'<p>ยังไม่มีสถานะปัจจุบันสำหรับตัดสิน กรุณาโหลดข้อมูล</p>'}<p class="notice">OCR ช่วยอ่านเอกสาร ไม่ใช่การพิสูจน์ตัวตน ผลเดิมที่ Agent อ่านยังเก็บในประวัติและแฟ้ม</p>${!final&&b?'<label for="bank-review-reason">เหตุผลการตรวจ KYC / ธุรกิจ</label><input id="bank-review-reason" maxlength="1200" placeholder="ระบุสิ่งที่ตรวจหรือข้อมูลที่ต้องขอเพิ่ม"><div class="actions" id="bank-actions"></div>':''}</article>`);
  $('reload-bank').onclick=()=>loadBankCard(c.id);
  if($('bank-actions')){
    const actions=[];
    if(b?.kyc?.status==='REVIEW')actions.push(['kyc','APPROVED','ผ่าน KYC'],['kyc','DECLINED','ไม่ผ่าน KYC'],['kyc','RESUBMISSION_REQUESTED','ขอข้อมูลตัวตนเพิ่ม']);
    if(b?.business)actions.push(['kyb','VERIFIED','ยืนยันธุรกิจ'],['kyb','NEEDS_INFORMATION','ขอข้อมูลธุรกิจเพิ่ม']);
    for(const [kind,choice,label] of actions){const button=document.createElement('button');button.textContent=label;button.disabled=blocked||!config?.capabilities?.bank_review;button.onclick=()=>reviewAction(c,kind,choice).catch(showError);$('bank-actions').append(button);}
  }
  const decision=c.decision;
  $('assessment').insertAdjacentHTML('beforeend',`<article class="card"><h2>คำตัดสินโดยเจ้าหน้าที่</h2>${pair('ผลปัจจุบัน',decision?({APPROVED:'อนุมัติ',DECLINED:'ไม่อนุมัติ',NEEDS_INFORMATION:'ขอข้อมูลเพิ่ม'}[decision.status]):'ยังไม่มีคำตัดสิน')}${decision?pair('เหตุผลที่แสดงในแอป',decision.reason)+pair('เวลาตัดสิน',decision.decided_at)+pair('ผู้ตรวจในเครื่อง',decision.reviewer):''}${!final?'<label for="loan-review-reason">เหตุผลที่แสดงให้ผู้สมัคร</label><input id="loan-review-reason" maxlength="1200" placeholder="ระบุเหตุผลหรือรายการข้อมูลที่ต้องขอเพิ่ม"><div class="actions" id="loan-actions"></div>':''}<p class="notice">local-reviewer เป็นผู้ใช้เครื่องนี้ ยังไม่มี staff SSO / production role การอนุมัติเป็นผลพิจารณา ไม่มีสัญญาหรือการจ่ายเงิน</p></article>`);
  if($('loan-actions'))for(const [choice,label] of [['APPROVED','อนุมัติตามวงเงินเสนอ'],['DECLINED','ไม่อนุมัติ'],['NEEDS_INFORMATION','ขอข้อมูลเพิ่ม']]){
    const button=document.createElement('button');button.textContent=label;button.disabled=blocked||(choice==='NEEDS_INFORMATION'&&typeof retainedDispatch==='function'&&Boolean(retainedDispatch(c)))||(choice==='APPROVED'&&(!b||!c.packet?.financial||Boolean(decision)||(typeof evidenceDecisionBlocked==='function'&&evidenceDecisionBlocked(c))));button.onclick=()=>reviewAction(c,'loan',choice).catch(showError);$('loan-actions').append(button);
  }
  for(const kind of reviewKinds)renderReviewRecovery(c,kind,kind==='loan'?'assessment':'application');
}
async function reviewAction(c,kind,choice=null){
  if(busy||c.active)return;
  const b=bankCards.get(c.id)?.bank,reason=$(kind==='loan'?'loan-review-reason':'bank-review-reason')?.value.trim();
  if(!reviewKinds.includes(kind))throw Error('ประเภทคำสั่งไม่ถูกต้อง');
  const slot=reviewSlot(c,kind);
  let pending=pendingReview(c,kind);
  if(choice!==null&&hasPendingReview(c))throw Error('มีคำสั่งรอตรวจผล กรุณาใช้ปุ่มตรวจผลคำสั่งเดิม');
  if(choice===null&&!pending)throw Error('ไม่มีคำสั่งเดิมที่รอตรวจผล');
  if(!pending){
    if(['APPROVED','DECLINED'].includes(c.state))throw Error('เคสมีคำตัดสินสุดท้ายแล้ว');
    if(kind!=='loan'&&!b)throw Error('กรุณาโหลดสถานะธนาคารก่อน');
    if(!reason)throw Error('กรุณาระบุเหตุผลก่อนบันทึก');
    if(kind==='loan'&&choice==='APPROVED'&&typeof evidenceDecisionBlocked==='function'&&evidenceDecisionBlocked(c))throw Error('ต้องมีผลตรวจหลักฐานปัจจุบันที่สมบูรณ์ก่อนอนุมัติ');
    const body={version:kind==='loan'?c.version:b.version,idempotency_key:crypto.randomUUID(),decision:choice,reason};
    if(kind==='loan'&&b)body.onboarding_version=b.version;
    pending={path:'/api/cases/'+encodeURIComponent(c.id)+(kind==='loan'?'/decision':'/onboarding/'+kind+'-decision'),body};
    localStorage.setItem(slot,JSON.stringify(pending));
  }
  busy=true;render();
  try{const result=await api(pending.path,pending.body);localStorage.removeItem(slot);if(current?.id===c.id)current=result;await loadBankCard(c.id);await loadQueue();}
  catch(e){
    // Only a newly dispatched, definitively rejected command is safe to release.
    // Recovery errors cannot prove the earlier uncertain command was not accepted.
    if(choice!==null&&[400,409,422].includes(e.status))localStorage.removeItem(slot);
    else e.message+=' · ยังเก็บคำสั่งและเหตุผลเดิมไว้ ใช้ปุ่มตรวจผลคำสั่งเดิม';
    throw e;
  }
  finally{busy=false;if(current?.id===c.id)render();}
}
function renderUploaded(c) {
  const d=c.input||{},r=c.results||{},docs=Array.isArray(c.documents)?c.documents.filter(Boolean):[];
  const app=c.source==='merchant_app';
  $('application').innerHTML=`<article><h2>ข้อมูลผู้สมัครและร้านค้า</h2><p class="notice">${app?'คำขอจาก Android · ข้อมูลเป็นคำแจ้งของผู้สมัคร':'เคสทดสอบในเครื่อง · ไม่ใช่ช่องทางรับสมัครจริง'}</p>${pair('ผู้สมัคร',d.applicant_name)}${pair('ร้าน',d.shop_name)}${pair('อีเมล',d.email)}${pair('โทรศัพท์',d.phone)}${pair('ประเภทธุรกิจ',d.business_type)}${pair('ช่องทาง / สถานที่ขาย',d.business_location)}${pair('วัตถุประสงค์',d.purpose)}${pair('ค่าครองชีพ / เดือน',number(d.living_cost_thb))}${pair('ภาระหนี้ / เดือน',number(d.debt_thb))}${pair('ยินยอมให้ตรวจเอกสาร',d.consent?'ยืนยันแล้ว':'ยังไม่ยืนยัน')}<details><summary>ข้อมูลที่ Agent อ่านก่อนหน้า</summary>${raw(r.identity_verify||{})}${raw(r.onboarding_read||{})}</details></article>`;
  $('evidence').innerHTML=`<h2>เอกสารและผลอ่านที่มีอยู่</h2><p class="notice">การอัปโหลดไฟล์ไม่ได้หมายความว่า OCR อ่านหรือแยกประเภทรายการแล้ว ผล OCR ไม่ยืนยันว่าเอกสารแท้</p>${docs.map(doc=>{
    const pages=Array.isArray(doc.ocr_pages)?doc.ocr_pages.filter(Boolean):[];
    return `<article class="document"><h3>${esc(doc.filename||'เอกสารเดิม')}</h3>${pair('ประเภท',doc.kind||'ยังไม่ทราบ')}${doc.id?'<a href="/api/documents/'+encodeURIComponent(doc.id)+'" target="_blank" rel="noopener">เปิดไฟล์ต้นฉบับ ↗</a>':''}<p>${pages.length?esc(pages.length)+' หน้าที่มีข้อความ OCR · ตรวจแหล่งที่มาในแต่ละหน้า':'ยังไม่มีผล OCR สำหรับไฟล์นี้'}</p>${pages.map(p=>`<details><summary>หน้า ${esc(p.page??'ไม่ทราบ')} · ${esc(p.model||p.source||'ไม่ทราบแหล่ง OCR')}</summary><pre>${esc(p.text)}</pre></details>`).join('')}<details><summary>ข้อมูลเอกสารและ SHA-256</summary>${raw({id:doc.id,sha256:doc.sha256,pages:doc.pages,ocr_source:doc.ocr_source,synthetic:doc.synthetic})}</details></article>`;
  }).join('')||'<p class="empty">ยังไม่มีเอกสารในเคสนี้</p>'}<details><summary>ผลอ่านจาก workflow เดิม</summary>${raw(r.evidence||{})}</details>`;
}

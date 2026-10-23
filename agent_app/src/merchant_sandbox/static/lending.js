/* Uploaded applications: all OCR text is escaped, never interpreted as HTML. */
const bankCards=new Map();
const reviewKinds=['loan','kyc','kyb'];
const reviewSlot=(c,kind)=>'merchant-review-pending:'+c.id+':'+kind;
const pendingReview=(c,kind)=>JSON.parse(localStorage.getItem(reviewSlot(c,kind))||'null');
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
    if(b.kyc?.status==='REVIEW')actions.push(['kyc','APPROVED','ผ่าน KYC'],['kyc','DECLINED','ไม่ผ่าน KYC'],['kyc','RESUBMISSION_REQUESTED','ขอข้อมูลตัวตนเพิ่ม']);
    if(b.business)actions.push(['kyb','VERIFIED','ยืนยันธุรกิจ'],['kyb','NEEDS_INFORMATION','ขอข้อมูลธุรกิจเพิ่ม']);
    for(const [kind,choice,label] of actions){const button=document.createElement('button');button.textContent=label;button.disabled=blocked||!config.capabilities.bank_review;button.onclick=()=>reviewAction(c,kind,choice).catch(showError);$('bank-actions').append(button);}
  }
  const decision=c.decision;
  $('assessment').insertAdjacentHTML('beforeend',`<article class="card"><h2>คำตัดสินโดยเจ้าหน้าที่</h2>${pair('ผลปัจจุบัน',decision?({APPROVED:'อนุมัติ',DECLINED:'ไม่อนุมัติ',NEEDS_INFORMATION:'ขอข้อมูลเพิ่ม'}[decision.status]):'ยังไม่มีคำตัดสิน')}${decision?pair('เหตุผลที่แสดงในแอป',decision.reason)+pair('เวลาตัดสิน',decision.decided_at)+pair('ผู้ตรวจในเครื่อง',decision.reviewer):''}${!final?'<label for="loan-review-reason">เหตุผลที่แสดงให้ผู้สมัคร</label><input id="loan-review-reason" maxlength="1200" placeholder="ระบุเหตุผลหรือรายการข้อมูลที่ต้องขอเพิ่ม"><div class="actions" id="loan-actions"></div>':''}<p class="notice">local-reviewer เป็นผู้ใช้เครื่องนี้ ยังไม่มี staff SSO / production role การอนุมัติเป็นผลพิจารณา ไม่มีสัญญาหรือการจ่ายเงิน</p></article>`);
  if($('loan-actions'))for(const [choice,label] of [['APPROVED','อนุมัติตามวงเงินเสนอ'],['DECLINED','ไม่อนุมัติ'],['NEEDS_INFORMATION','ขอข้อมูลเพิ่ม']]){
    const button=document.createElement('button');button.textContent=label;button.disabled=blocked||(choice==='APPROVED'&&(!b||!c.packet?.financial||Boolean(decision)));button.onclick=()=>reviewAction(c,'loan',choice).catch(showError);$('loan-actions').append(button);
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
  const d=c.input,r=c.results,e=r.evidence,k=r.identity_verify,docs=c.documents||[];
  const docCards=docs.map(doc=>`<article class="card"><h2>${esc(doc.kind==='identity'?'เอกสาร KYC':doc.kind==='business'?'หลักฐานธุรกิจ':'Statement')}</h2><p><a href="/api/documents/${encodeURIComponent(doc.id)}" target="_blank" rel="noopener">${esc(doc.filename)} ↗</a></p>${pair('อ่านเอกสารแล้ว',doc.ocr_pages.length+' / '+doc.pages+' หน้า')}${pair('SHA-256',doc.sha256)}${doc.ocr_pages.map(p=>`<details><summary>หน้า ${p.page} · ${esc(p.model)}</summary><pre>${esc(p.text)}</pre></details>`).join('')}<p class="notice">ผล OCR เป็นข้อความที่อ่านได้ ยังไม่ยืนยันเอกสารแท้ ไม่มีพิกัดกรอบข้อความหรือคะแนนความมั่นใจรายช่องจาก API นี้</p></article>`).join('');
  $('application').innerHTML=`<div class="grid"><div><article class="card"><h2>ข้อมูลสมัครจากแอป</h2>${pair('ผู้สมัคร',d.applicant_name)}${pair('อีเมล',d.email)}${pair('โทรศัพท์',d.phone)}${pair('ร้าน',d.shop_name)}${pair('ประเภทธุรกิจ',d.business_type)}${pair('สถานที่ / ช่องทางขาย',d.business_location)}${pair('วัตถุประสงค์',d.purpose)}${pair('ค่าครองชีพ / เดือน',number(d.living_cost_thb)+' บาท')}${pair('ภาระหนี้ / เดือน',number(d.debt_thb)+' บาท')}${pair('ยินยอมส่งเอกสารให้ OCR',d.consent?'ยืนยันแล้ว':'ยังไม่ยืนยัน')}<p class="notice">ชื่อและข้อมูลการเงินเป็นคำแจ้งจากผู้สมัคร ยังต้องตรวจหลักฐานประกอบ</p></article></div><div><article class="card"><h2>การสมัครและ KYC</h2>${pair('บัญชีผู้ส่ง','ตรวจ login โดย Merchant backend')}${pair('รหัสเจ้าของคำขอ',c.owner_id)}${pair('ผล OCR เทียบชื่อ',k?.status==='CONFLICT'?'ชื่อไม่ตรง ต้องตรวจความสัมพันธ์':k?.extracted_names?.length?'พบชื่อที่อ่านได้ รอตรวจโดยเจ้าหน้าที่':'รอเจ้าหน้าที่ตรวจเอกสาร')}${pair('สถานะ KYC จากธนาคาร',r.onboarding_read?.snapshot?.kyc?.status||'ยังอ่านสถานะไม่ได้')}${pair('วิธีอ่านเอกสาร',k?.method||'รอ OCR')}<p class="notice">OCR ช่วยอ่านเอกสารเท่านั้น ผู้สมัครติดตามสถานะและรายการขอเพิ่มได้ใน Android app</p>${k?raw(k):''}</article>${docs.filter(x=>x.kind==='identity').length?'':'<article class="card">ยังไม่มีเอกสาร KYC</article>'}</div></div>`;
  const rows=e?.months||[];
  $('evidence').innerHTML=`<div class="grid"><div><article class="card"><h2>Statement ที่อ่านด้วย Typhoon OCR</h2>${pair('แหล่งข้อมูล','เอกสารที่ผู้สมัครแนบผ่าน Merchant backend')}${pair('ผลตรวจตาราง',e?.status||'ยังไม่ได้ตรวจ')}${pair('ช่วงที่ตรวจ',e?.expected_months?.join(', ')||'6 เดือนที่ปิดครบก่อนวันที่ยื่นคำขอ')}${pair('เดือนที่ขาด',e?.missing_months?.join(', ')|| (e?'ไม่มี':'ยังไม่ทราบ'))}${pair('รายการที่อ่านได้',e?.rows?.length??'ยังไม่มีผล')}${pair('รายการแยกออก',e?.excluded?.length??'ยังไม่มีผล')}<p class="notice">ตรวจยอดยกมา + รับ − จ่าย = คงเหลือทุกแถว แยกรายการตามคำบรรยายที่รองรับ รายการคลุมเครือพักให้เจ้าหน้าที่ตรวจ ยอดโอนเข้าไม่ได้ถูกนับเป็นยอดขายทั้งหมด</p>${e?.issues?.length?'<div class="callout">'+e.issues.map(x=>'<p>'+esc(x.reason)+'</p>').join('')+'</div>':''}</article><article class="card"><h2>ยอดรายเดือนที่แยกประเภทได้</h2>${rows.length?`<div class="tablewrap"><table><thead><tr><th>เดือน</th><th>ยอดขาย</th><th>ต้นทุนผันแปร</th><th>ต้นทุนคงที่</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${esc(x.month)}</td><td>${number(x.R)}</td><td>${number(x.V)}</td><td>${number(x.F)}</td></tr>`).join('')}</tbody></table></div>`:'<p>ยังไม่มีผล</p>'}${e?'<details><summary>รายการและหน้า/แถวอ้างอิง</summary>'+raw(e.rows)+'</details><details><summary>รายการที่แยกออก</summary>'+raw(e.excluded)+'</details>':''}</article></div><div>${docCards||'<article class="card">ยังไม่มีเอกสาร</article>'}</div></div>`;
  if(c.state==='WAIT_CUSTOMER') $('feedback').innerHTML='<div class="callout">'+c.feedback.map(x=>'<p>'+esc(x)+'</p>').join('')+'<p class="notice">รายการนี้แสดงให้เจ้าของคำขอใน Android app แล้ว</p></div>';
}

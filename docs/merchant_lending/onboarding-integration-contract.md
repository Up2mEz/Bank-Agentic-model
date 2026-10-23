# Wallet onboarding, lending and reviewer contract v1
23 October 2026. Implements the approved UX in repos/ntt_data_2026-merchant-ui/docs/wallet-loan-ux.md and kyc-credit-mock.md, with latest user correction: no provenance/debug-policy panels in the customer app.

## Ownership and source of truth
- Go owns persisted onboarding (phone/KYC/wallet/business/KYB); Python `merchant_sandbox` under `agent_app/` owns loan cases, uploaded evidence, OCR, computations, traces and final human decisions. Flutter uses customer JWT through Go.
- Go/Flutter belong to the related Merchant repository and are not bundled into this Python package. This document preserves the 23 October integration contract; see [current team status](TEAM_AGENTIC_STATUS_20261024_TH.md) for the native-agent experiment boundary.
- Local acceptance used separate Go/Python ports 18082/8768 and isolated synthetic databases. These are example development settings, not deployed service addresses; use separate state/ports for each run.
- No new lender/financial engine or AWS service. Preserve existing Python Decimal policy and evidence parser, not a second Go score. KYC mock != actual identity proof, OCR != KYC. No contract or disbursement.
- Agent reads applicant/evidence/calculation snapshots; human decides every loan case. No decision tool for LLM.
- Keep backend is_mock/provider/policy metadata and source documentation. Customer screens have concise task/status text, no "เกณฑ์นี้มาจากไหน", "ค่าทดลองที่ยังไม่ใช่นโยบายจริง", policy constants, trace or test scenario chooser. A small environment label may distinguish demo; actual terms shown where necessary, not hidden.

## Go onboarding API
All paths start /v1. Customer routes use existing JWT (derive owner, never accept customer_id in body). Reserved named API keys: lending-agent is READ ONLY on /agent/*; lending-reviewer only /review/onboarding/* plus explicit GET /agent/customers/{id}/onboarding; other legacy services keep existing permissions. Enforce reserved roles globally, not only new handlers.
ONBOARDING_MODE=mock enables deterministic provider; omitted/disabled fails closed for new onboarding endpoints. No real-provider integration implied. ONBOARDING_MOCK_OUTCOME default approved; supported approved, resubmission_requested, review, declined, expired, unavailable. Externally editable scenario UI is absent. Use provider interface to test other outcomes.

GET /onboarding -> OnboardingSnapshot:
{
  "customer_id": UUID, "version": integer,
  "phone": {"value": string, "verified": bool},
  "profile": null or {
    "first_name":string,"last_name":string,"date_of_birth":"YYYY-MM-DD","nationality":"TH",
    "document_number_masked":string,"document_expiry":"YYYY-MM-DD",
    "current_address":string,"occupation":string,"source_of_funds":string,"wallet_purpose":string,
    "privacy_accepted":bool
  },
  "kyc":{"session_id":string|null,"status":"NOT_STARTED|APPROVED|RESUBMISSION_REQUESTED|REVIEW|DECLINED|EXPIRED","attempt":int,"is_mock":bool,"reason":string},
  "wallet":{"status":"NOT_OPEN|ACTIVE|BLOCKED|CLOSED","account_id":UUID|null},
  "business":null or {"name":string,"category":string,"location":string,"started_on":"YYYY-MM-DD","ownership_confirmed":bool,"evidence_note":string},
  "kyb":{"status":"NOT_SUBMITTED|PENDING_REVIEW|VERIFIED|NEEDS_INFORMATION","reason":string},
  "is_mock":bool
}
Optional additional timestamps and top-level first_name/last_name for initial prefill are safe. Mobile tolerates omitted optional strings but uses these exact names/statuses. Profile remains null until saved complete.
- GET returns prefilled names/phone from customer where possible; profile can be null until complete. Existing wallet does not make KYC verified. Wallet status reflects live bank account.
- Every mutation accepts version + idempotency_key (8-100 chars) in JSON. Replay matching key/action/body BEFORE version validation; changed body/key -> 422 idempotency_key_reused. Stale version ->409 stale_version. Successful reply returns current snapshot except phone challenge which also returns challenge_id and expires_at. Under row lock/transaction, one key and one mutation.
- PUT /onboarding/profile: {version,idempotency_key,profile:{first_name,last_name,date_of_birth,nationality,document_number,document_expiry,current_address,occupation,source_of_funds,wallet_purpose,privacy_accepted}}. Validate required fields, real dates, 13-digit Thai document format (format is not authenticity), expiry, input sizes. Changing verified identity invalidates KYC; cannot silently retain APPROVED. Raw document number must not appear in logs or Agent snapshots.
- POST /onboarding/phone/challenge: {version,idempotency_key,phone}. Mock code 123456, expiry 5 minutes, bounded attempts 5, replacement challenge invalidates old one; phone changes clear prior verification. Output snapshot + challenge_id/expires_at. Mock hint only after request, no SMS assertion.
- POST /onboarding/phone/verify: {version,idempotency_key,challenge_id,code}. Bound to owner/phone/challenge; failed attempts persist, stale/expired errors safe.
- POST /onboarding/kyc: {version,idempotency_key}. Requires verified phone and completed profile/privacy acknowledgement. Provider session/attempt tracked, resubmission same session new attempt, declined/expired fresh session on new action. Unavailable is retryable and does not set DECLINED or APPROVED. No caller-supplied outcome accepted.
- POST /onboarding/wallet: {version,idempotency_key,terms_accepted:true}. Requires approved KYC and verified phone. Uses existing bank AccountService in SAME database transaction and onboarding row lock. Replay/lost response or concurrent taps cannot create another wallet. Existing active THB wallet may be linked after KYC; account existence alone never grants KYC. While module enabled, legacy customer POST /customers/{id}/accounts is blocked with onboarding_required (service seed remains allowed).
- PUT /onboarding/business: {version,idempotency_key,business:{name,category,location,started_on,ownership_confirmed,evidence_note}}. Requires KYC/wallet ready. Save declared business profile and mark PENDING_REVIEW, never auto-verify, no need merchant_id/app sales. Editing verified business resets KYB. Does NOT approve merchant ordering feature.
- GET /agent/customers/{customerID}/onboarding: lending-agent or lending-reviewer read safe snapshot. No OTP/raw document number/provider secret. Existing bank customer exists check; not-found stays404.
- GET /review/onboarding/{customerID}: lending-reviewer only snapshot for staff.
- POST /review/onboarding/{customerID}/kyc-decision: {version,idempotency_key,decision:"APPROVED|DECLINED|RESUBMISSION_REQUESTED",reason}. Only pending REVIEW; records staff identity from authenticated key name, timestamp, reason, original provider/mock metadata.
- POST /review/onboarding/{customerID}/kyb-decision: {version,idempotency_key,decision:"VERIFIED|NEEDS_INFORMATION",reason}. Only submitted business, version checked, reason required.
- Snapshot should expose audit summaries needed for review, no hidden model chain-of-thought.
Persist row + idempotency records in PostgreSQL migration 000008 (verify existing numbering), source disabled config does not auto-migrate or approve old records.

## Existing lending routes to reuse and extend
Customer /lending/cases: existing list/create/get/revise/document/remove/submit, existing payloads with optional idempotency_key now also supported on revise/upload/remove/submit. New Flutter always sends durable exact key/body. Same-key replay checked before version/state guards and returns safe case projection; changed-payload same key returns422 {error:string,code:"idempotency_key_reused"}. Old clients without keys remain compatible but do not gain replay guarantees. Async submit acceptance is idempotent and cannot start a second run; deliberate technical retry is a new key only after a definite result. Go bridge LENDING_SERVICE_URL/TOKEN, timeout and owner binding retained. Larger 6 MiB body limit only on lending document routes as in original integration.
- Backend checks KYC approved, phone verified, linked active wallet and submitted business before create/submit; pending KYB may submit but cannot be approved. Fetch/edit existing own cases remains possible for information recovery.
- kind of uploaded document: identity | statement | business. Business evidence is for staff KYB, not statement income, and must not satisfy required statement/identity evidence counts.
- Input continues existing fields. Flutter prefills onboarding business/name/phone, user can review. No source/scenario/owner/provider fields from APK.
- Customer projection returns decision null or {status:"APPROVED|DECLINED|NEEDS_INFORMATION",reason,decided_at,reviewer,case_version,amount_thb:null|string,onboarding_version:int}. Status state values APPROVED/DECLINED become final, NEEDS_INFORMATION maps WAIT_CUSTOMER. No token/secrets/officer traces.
- A request for more info resumes same case; revise/doc changes invalidate previous analysis/packet/decision and increment version, preserve prior snapshots/audit. Final approved/declined cases cannot be rewritten by stale revise/run/doc actions.
- Add Go READ ONLY service endpoints GET /agent/lending/cases and GET /agent/lending/cases/{caseID}. They forward through existing server-only bridge credential to Python GET /internal/agent/cases and /internal/agent/cases/{id}; return staff dossier/metadata/evidence refs/calculations/trace (no raw upload bytes, secrets). Customer JWT and agent mutation attempts refused. These are for the other team's Agent/tool adapter.

## Python integration
- Internal receipt resolution (bridge Bearer token + authenticated `X-Customer-ID` owner, never customer supplied): `POST /internal/lending/cases/replay` takes the original `{input,idempotency_key}`; `POST /internal/lending/cases/{caseID}/submit/replay` takes the original `{version,idempotency_key}`. These routes ONLY read existing owner/action/key/payload-bound receipts and return 200 with the current customer projection. Create resolves the original case ID from the stored receipt; submit also binds the case ID. Missing receipt or different owner returns404; changed payload for an existing receipt returns422 `idempotency_key_reused`. No case allocation, receipt insertion, state mutation or worker dispatch is permitted. Body comparison uses the same normalized input/version hash as original acceptance. Go uses these dedicated routes only when current create/submit readiness fails and a valid key is present: no receipt/404 (including an older Python lacking these routes) returns the original readiness rejection, 422 is preserved, and transport failure remains retryable503. NEVER fall back to the mutating keyed POST when unready. Deploy the matching Python/Go pair for recovery support; old clients without keys keep normal ready operations and the readiness rejection when unready.
- New BankOnboardingClient (stdlib urllib or existing deps), server-side --bank-url, --bank-agent-key-file, --bank-reviewer-key-file. HTTP loopback/HTTPS only, finite timeout/no redirects, bounded JSON and owner validation. Agent uses GET /v1/agent/customers/{owner}/onboarding with X-API-Key. Never accept URL/key/owner from LLM.
- New tool onboarding_read for merchant_app cases uses stored owner UUID and stores read snapshot/version/provenance in results. Legacy lab cases continue unchanged. Missing configuration/provider outage is explicit technical/needs-review state, never fabricated verified.
- review_build_packet incorporates onboarding read result, KYC/KYB, existing calculation, evidence ownership/coverage and loan recommendation. Must not claim OCR proves KYC. Existing financial score remains demonstration policy, metadata retained staff-side.
- Staff GET /api/cases/{id}/onboarding obtains current bank snapshot via reviewer credential. POST /api/cases/{id}/onboarding/kyc-decision or kyb-decision uses stored owner (not posted customer_id), forwards above contract; case cannot be active during staff mutation.
- Staff POST /api/cases/{id}/decision {version,idempotency_key,decision,reason,onboarding_version}; onboarding_version is required for APPROVED and comes from the displayed current bank snapshot, checked again against a fresh read. Final approval uses existing computed proposed amount only. Require complete/current evidence/calculation, KYC approved, wallet ACTIVE, KYB VERIFIED and matching current identity. Unknown debt/unsupported evidence/outside demo profile cannot be approved. Human action with reason; no LLM tool/bridge Agent route may call.
- Preserve auth model of local reviewer sandbox, add review_nonce from /api/config and X-Review-Nonce on reviewer mutations; no production SSO claim. Named reviewer attribution local, explicit in docs. Decision write is atomic CAS/idempotent; stale case/version or changed same-key payload fails, and no running agent may overwrite a human result. Refresh onboarding card/version after KYB review; cached pre-review metadata stays auditable.
- Add reviewer controls in existing UI, simple Thai copy; show persisted decisions and customer-facing reason. Finish flow at result, no pay-out.
- Existing Python financial policy remains source of computation; enforce supplemental demo eligibility age20-60 only if using profile, recorded as benchmark-adapted (not credit score). Don't silently invent new financial thresholds.
- No live LLM cost required for validation; integration may use bounded offline planner + mocked OCR responses with real HTTP/auth/persistence. Report distinction honestly.

## Required checks / boundaries
- Phone retry/expiry/attempts, KYC retry/statuses, no wallet before verification, concurrent wallet single account; restart storage.
- Customer isolation, reserved Agent read cannot mutate legacy bank endpoints or review, no APK secret.
- Exact normal existing financial oracle capacity5000/proposed28400; unknown debt !=0, more files !=score.
- Staff more-info keeps case; approval/decline reason and version; stale agent/result cannot overwrite.
- Flutter simple forms at320, validation/unknown money, operation replay across lost reply/restart, no auto-wallet on registration, final human result displayed.
- Real HTTP Go→Python→Go data fetch and customer status round trip against isolated stores.
- Build Android debug; emulator test coordinated only, no stop/reinstall of other thread's app.

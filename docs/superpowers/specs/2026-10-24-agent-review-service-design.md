# Agent review service and staff usability

The user requests fixing the failing PR, a usable officer web application, manual
data-entry testing, and an agent service that is easier to maintain and deploy.
Existing loan decisions remain human actions. Customer production intake remains
Android through Go; the browser entry is a clearly marked local test form.

## Approach

Keep the existing Case API as owner of case/document versions and human decisions.
Run evidence review in a separate authenticated HTTP service with a persisted job
queue. Reuse native agent/OCR/report modules behind a narrow pipeline. The staff
browser talks only to the Case API. This creates a concrete service boundary while
keeping the Go contract stable. A single worker is sufficient for the local demo;
multi-worker/PostgreSQL/SQS execution is later work. Merely wrapping the legacy
planner would leave the native/report gap unresolved; migrating to LangGraph now
would add a framework without addressing the observed contract/report bugs.

## Agent service contract

Default port 8781; configurable host, SQLite path, provider env file. Bearer token
`AGENT_SERVICE_TOKEN` (at least 32 characters) is required for review endpoints.
`GET /healthz` exposes liveness only. `GET /readyz` reports safe capability flags.

- `POST /v1/reviews`: `{case, documents, mode, idempotency_key}`. Case is the
  trusted Case API snapshot. Documents belong to this case, have bounded content,
  hashes and either recorded OCR pages or `content_base64` for OCR. Modes are
  `offline` (no network, supplied OCR only) and `typhoon` (real OCR if necessary,
  then bounded native agent). Unknown OCR must fail explicitly, never fabricate.
- `GET /v1/reviews/{job_id}` returns the persisted job.
- `GET /v1/cases/{case_id}/review` returns latest job for the case, or 404.
- Job schema: `id, case_id, case_version, snapshot_hash, mode, status, stage,
  created_at, updated_at, result, error`. Status is QUEUED/RUNNING/COMPLETED/
  FAILED/INTERRUPTED. `result` contains `report, trace, usage, review_state,
  decision:null, human_final_decision_required:true`. No autonomous decision or
  money movement endpoint. Native financial recommendations are not exposed as
  authoritative credit approval in this new API.
- Same key/body returns original job; different body/key reuse is rejected.
  Accepted jobs survive process restart; RUNNING jobs become INTERRUPTED and are
  not automatically retried with paid provider calls. Worker and queue are bounded.
- Provider settings and all current financial formulas/oracles remain unchanged.
  Existing unresolved model-semantic issues are documented, not called fixed by
  deploying the service. Offline mode is visibly distinct from model execution.

## Case API integration owned by parent

Configure `--agent-service-url` and `--agent-service-token-file` (or env token).
Expose safe capability flags under `config.capabilities.agent_review`.

- `POST /api/cases/{id}/evidence-review`: `{version,mode,idempotency_key}`;
  verify current version, consent, nonfinal/nonactive case and documents. Build
  service input from stored snapshots/bytes only, never caller-supplied case data.
- `GET /api/cases/{id}/evidence-review`: latest service job with `stale` computed
  against current case/document snapshot. Stale output must not masquerade as a
  current result or enable a decision. Service unavailable is a visible status.
- Local test form creates ordinary lab cases with `POST /api/cases`, uploads via
  `POST /api/cases/{id}/documents` using `{version,document,idempotency_key}` (local
  mock/lab cases only), and can request bundled example documents through
  `POST /api/cases/{id}/sample-documents` with `{version,idempotency_key}`.
  Sample OCR is bound to exact bundled file hashes and labelled replayed synthetic.
- Staff UI at `/`, test form at `/test-application`, existing `/lab` retained.

The user subsequently selected both browser and Android testing. When the service
is configured, the existing authenticated Go → Case API submit contract must
dispatch to that same service. Keep operational processing state separate from
the immutable analysis snapshot, bind completion to the accepted version/claim,
and preserve submit receipts. Evidence-only jobs must not supply financial approval
packets. Retain legacy controller only for explicitly unconfigured installations.

## Staff UI contract owned by UI implementer

Retain ids/application/evidence/assessment/trace and pending reviewer key/body
recovery semantics. Simplify queue/search, selected-case summary and four tabs;
show the four-part evidence report prominently and errors/status in plain Thai.
Keep developer JSON, long trace and formulas collapsed. Avoid rendering the legacy
mock panels and then replacing/appending duplicate panels. Loading bank state
must not erase an entered reason or interrupt a pending decision.

Separate staff CSS/JS from the compressed inline document. Parent adds generic
safe static routes for packaged local assets. New assets and tests stay under
agent_app. Manual test form owns exact pending create/upload/review receipts and
never silently switches to fixtures or paid model execution.

## Verification

Reproduce observed UI/persistence failures before edits; use focused HTTP/job
tests for auth, scope, idempotency, restart, stale output and failures. Preserve
existing human-decision tests. Exercise manual entry, sample upload, offline review,
staff four-part view and reload in browser. Real provider verification, if run,
must be synthetic, bounded and record usage; no claim it proves underwriting
readiness. Run complete Python/JS/lint checks and hosted PR checks. Provide a
container recipe and separate state volumes; no AWS deployment or shared-runtime
restart is part of this local work.

# Agent review service implementation plan

> Implement within the user's request for a maintainable agent service and usable
> manual/staff flow. Parent integrates; separately owned backend and UI tasks use
> focused tests and a final independent review. No financial policy promotion.

**Goal:** Manual synthetic entry and a statement reach a separate persisted agent
service, then a clear four-part report in the staff browser.

**Spec:** `docs/superpowers/specs/2026-10-24-agent-review-service-design.md`.

## Tasks

- [x] Inspect actual CI/reviews. Both push and PR runs at a6ff93c are successful;
  no comments/review failures exist. Keep links instead of fabricating a CI fix.
- [x] Reproduce lab document KeyError and missing service routes with failing tests.
- [x] Add Case API gateway, exact bundled recorded-OCR mapping, nonce-protected
  manual upload/sample/review routes, capability flags and stale-snapshot checks.
- [x] Backend owner implements persisted bounded jobs, authenticated review HTTP
  endpoints, offline/native pipelines, startup interruption, and focused tests.
- [x] UI owner extracts compressed scripts/styles, reduces clutter/duplicate
  rendering, preserves draft reasons/pending decisions, and adds manual form with
  exact recovery and async four-part report rendering.
- [x] Parent supplies local launcher, container recipe, separate volumes/config,
  operator guide and contract tests. Verify end-to-end without live provider first.
- [x] Test manual submit/reload/errors in browser and run all relevant regressions.
  Save receipts; if a bounded synthetic live run is performed, account for calls
  and distinguish recorded OCR from live model/OCR.
- [x] Independent review of the final integrated source and scoped guard closure.
  All findings resolved with focused tests; PR/hosted status is tracked on PR #1.
- [x] User selected both channels: connect authenticated Android/Go submit to the
  same service, preserve existing submit recovery, bind immutable evidence versions,
  and test evidence-only handoff without financial approval promotion.

## Review ledger

- First integrated review found encoded-route auth bypass, retained Android command
  overwrite, post-OCR failure usage loss and omitted terminal attempt diagnostics.
  One bounded fix wave addressed all four; scoped re-review closed three and the
  duplicate-job path, with one remaining NEEDS_INFORMATION recovery deadlock.
- Ruling: complete the retained-command boundary with a narrow guard that rejects
  a new NEEDS_INFORMATION action until exact-command reconciliation. Do not widen
  recovery to overwrite a human request. Cost if overly strict: staff must resolve
  the old job before sending a new information request. Existing decision receipts
  replay first; final human decisions and financial policy stay unchanged.
- Real Typhoon retry remains TECHNICAL_REVIEW, 4 calls / 12,243 tokens, two terminal
  unknown-tool responses. This is retained as failed model acceptance, separately
  from 674 passing integration tests and 41 UI checks before the final guard.
- Final guard review closed the residual with no direct regression. Final combined
  verification: 677 Python passed, 15 historical skips, 1 known strict XFAIL;
  42 Node tests passed, Ruff and wheel build passed. Existing runtime was reloaded
  only after all review jobs were terminal. No additional model calls followed.

## Review focus

1. Accepted request with an uncertain response: exact key/body replay survives
   reload, never creates another case/job silently.
2. A result for another case/version or modified document must be rejected/stale.
3. Service unavailable/restart/provider failure must remain visible with no credit
   decision or invented evidence, and no automatic paid retry of interrupted jobs.
4. Refreshing bank/job state must preserve typed human reasons and unresolved
   decision receipts; one human result panel and one evidence report remain.
5. Offline sample text must bind exact synthetic bytes, contain no evaluation
   labels, and remain distinguishable from uploaded files and real model execution.

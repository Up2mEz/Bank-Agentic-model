# Evidence and execution status

Research date: 2026-10-04, Asia/Bangkok.

This file records the initial research turn before training/network access. The subsequent authorized experiment completed data downloads, raw audit and training. Current measured results are in [REPORT_TH.md](../reports/v1/REPORT_TH.md); current direct-agent execution evidence is in [EXECUTION_AND_AGENT_REVIEW_TH.md](EXECUTION_AND_AGENT_REVIEW_TH.md). The pending statuses below are historical.

## Local workspace

- Inspected `D:\Project\NTT-Bank-Agentic` directly. It was empty at the start; no project AGENTS.md, existing model, dataset or training results were found in that directory.
- No training, installation, deployment, account registration, competition entry or acceptance of external agreements was performed.
- These Markdown files are research deliverables, not model artifacts.

## Herdr delegation

- Read the requested installed skills at `D:\skill ai\skills\herdr\SKILL.md`, `herdr-orchestrator\SKILL.md`, and `herdr-a2a\SKILL.md`.
- Verified `HERDR_ENV=1` before issuing Herdr commands.
- Read current CLI help; `agy` and `gemini` are supported kinds.
- `herdr-a2a discover --json` reported both available. Availability was not treated as proof that task execution worked.
- Attempted one read-only task to each runtime: agy for independent dataset due diligence; gemini for independent literature/BOT/model comparison. Neither delegation produced a task ID or research result. Both returned:

```text
HERDR_PROTOCOL_UNSUPPORTED: herdr protocol 22 != required 20
```

- `herdr-a2a doctor` returned `ok: true` and showed Herdr `0.9.1-preview.2026-09-21-0ff0f27e2226`, protocol 22, with all required methods present. This diagnostic does not erase the delegation errors. The precise component producing the stricter protocol-20 requirement has not been identified.
- Direct `herdr status`, `herdr agent list`, and `herdr pane layout --current` returned `PermissionDenied / Access is denied`.
- No server stop, upgrade, permission weakening, profile change, alternate-agent substitution or repeated blind submission was performed.
- **No claim in these deliverables is attributed to agy or Gemini.** Research was performed by the primary agent.

## Data access

- Kaggle CLI is installed. Attempted `kaggle competitions files -c home-credit-credit-risk-model-stability --page-size 100`; request failed with Windows socket error 10013 / network access permissions.
- Official Home Credit Model Stability Data and Rules pages were read through Chrome UI. The data explorer required sign-in and acceptance of competition rules; neither was performed. Rules explicitly contained Competition Use Only and the B.7.A access restriction.
- Kaggle UCI page title/URL were reached, but subsequent browser inspection timed out, including one recovery attempt. Mirror license and CSV preview were not verified from that page.
- UCI official dataset documentation was read with the web research tool. Source metadata is distinguished from raw measurements.
- No raw dataset file was obtained. Hash, duplicate counts, class counts, missing-value counts and model metrics are **unknown**, rather than filled from familiar benchmark values.
- Also attempted the public original UCI ZIP download. The web tool rejected the binary response as exceeding its content limit; a direct `Invoke-WebRequest` in the default sandbox returned `Unable to connect to the remote server`. No elevated network request or permission bypass was attempted.

## Literature verification

- Used primary papers, proceedings, an author PDF, official repository documentation and official vendor documentation as specified in the reference audit.
- DOI pages for Lessmann (2015) and the ICML calibration paper returned access/tool errors. This is not evidence of an invalid DOI; metadata was obtained from accessible records and content from indexed author/manuscript sources. The DOI-resolution step remains incomplete.
- Searched for retraction notices for central cited papers and inspected accessible source pages. No matching notice appeared in those returned results. This is a limited search, not a complete Retraction Watch/Crossref certification.
- BOT PDF text was read at the relevant credit-model/rating/scoring sections. Screenshot requests were made but did not return a viewable image in this tool surface; no claim of complete visual review or full legal compliance is made.
- Review is targeted and bounded. It does not claim exhaustive PRISMA screening, a systematic-review search count, independent benchmark replication, or bank deployment certification.

## Current package status

| Item | Status |
|---|---|
| Research synthesis and stack proposal | Written, with source links and scope limitations |
| Kaggle candidate selection | Conditional; UCI for behavioral benchmark |
| Raw dataset audit | Pending, no raw file access |
| Independent agy/Gemini review | Not executed successfully |
| Training / measured winner | Not performed |
| Thai bank validation / regulatory readiness | Not established |

Existing local packages were inspected, not installed: pandas 2.3.3, numpy 2.3.5, scikit-learn 1.8.0, LightGBM 4.6.0, CatBoost 1.2.10, Kaggle CLI 2.2.4. These versions are environment evidence, not a tested compatibility lock.

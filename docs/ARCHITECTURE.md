# Code and experiment boundaries

The maintained implementation is `src/creditrisk`. It separates:

- `schema`: the 23-column input and binary-target contracts;
- `features`: pure within-row historical summaries, with exact V2 migration parity;
- `splits`: group identity and disjoint-fold checks;
- `nested`: depth and early-stopping selection inside training data only;
- `models`: category adapters and the versioned inference pipeline;
- `calibration` and `metrics`: probability transforms and diagnostics;
- `experiment`: immutable protocol, outer-CV evaluation, promotion gate and final fitting;
- `exploration`: additional EDA restricted to the original fit partition;
- `cli`: commands for research and scoring.

The original `scripts/` are historical V1/V2 experiment sources. Their bytes remain
unchanged because frozen run manifests cite their SHA-256 hashes and saved artifacts
depend on their import paths. They are retained for audit and reproducibility; new
development uses the formatted and tested package. `tools/` contains review, export,
migration-verification and reporting utilities.

`outputs/` contains local predictions, models, logs and reviewer output. It is ignored.
`reports/` contains curated, public evidence with source hashes. Raw data and model
weights are not included in the Git repository. `.env` is excluded, and no API key is
needed for the main CatBoost/LightGBM experiment.

## What agents do

The authorized native agy CLI reviews supplied protocol/code extracts in plan mode.
The primary researcher verifies its suggestions against actual code and measurements.
The LLM is not part of numerical feature calculation, prediction or the promotion gate.
There is no automated lending action. A supplied-material agent review is not an
independent dataset audit or regulatory model validation.

## Validation limits

Exact-vector groups remain together at both inner and outer boundaries. Each outer
fit selects depth and iteration count using only its inner validation labels, then
refits all outer-training rows without an evaluation set. The refit iteration count
is the median of the chosen candidate's inner best tree counts; this is a predefined
heuristic. The fixed blend weights and reused V2 features/comparator have prior
selection history. Nested fitting does not erase that history or restore an
independent holdout.

For scoring, only load a locally created or otherwise trusted joblib artifact:
joblib uses pickle and can execute code while loading. The CLI validates input schema,
finite values, integer category codes, row order and final probabilities. Scoring is
development research and does not approve or decline credit.

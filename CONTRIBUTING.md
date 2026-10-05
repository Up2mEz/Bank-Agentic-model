# Development checks

Use Python 3.12 and install the package with development tools:

```powershell
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
.venv\Scripts\ruff.exe check src tests tools
.venv\Scripts\ruff.exe format --check src tests tools
.venv\Scripts\python.exe -m pytest -q
```

Tests protect row/index order, single-row inference, unknown category handling,
zero denominators, target/ID exclusion, conflicting-label groups, invalid probabilities,
and inner-only selection/refitting. They include a real small CatBoost model with
save/reload prediction parity. They do not train on downloaded data or require tokens.

Create a new output directory and protocol for a new experiment. Do not rewrite
completed predictions, source manifests or selection decisions, or tune on the old
reference test. Historical scripts remain immutable; add changes to the maintained
package with a new protocol. Keep hypotheses, outcomes, failed gates and unknown
dataset semantics explicit. Review agent suggestions against primary evidence.

Never commit `.env`, raw data, model checkpoints or local agent logs. Public evidence
is exported through `tools/export_reports.py`. Retain UCI attribution for derived data.

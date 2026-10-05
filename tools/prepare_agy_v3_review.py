"""Build a code-only bounded review prompt from actual source; no environment reads."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def excerpt(path: Path, names: set[str]) -> str:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    pieces = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            pieces.append(
                f"{path.relative_to(ROOT).as_posix()}:{node.lineno}\n"
                + "\n".join(lines[node.lineno - 1 : node.end_lineno])
            )
    return "\n\n".join(pieces)


def main():
    sections = [
        """Review supplied code only. NO TOOLS: no workspace reads, shell, network, edits or other actions. Do not claim tests or dataset audits. Find concrete correctness bugs, leakage, schema/scoring/order errors and reproducibility failures, prioritize by severity, cite supplied file/line. Distinguish untested suggestions from demonstrated bugs. Explain in Thai. Do not invent columns or category meanings.

Context: development research only, all original partitions exposed. Current protocol froze before fitting. 3 outer group folds, 3 inner group folds select 2 CatBoost configs by mean inner Logloss with early stopping max2000/patience100; median chosen best tree counts refit outer training, NO outer eval_set. Fixed blend .75/.25 with SHA-verified saved V2 LightGBM OOF from identical folds/features. Gate gain>=.001/allfolds improve/Brier no worse/quietLLdelta<=.001; if fail, keep V2. Final fit repeats same inner algorithm on original fit with predefined seed, calibration only on originalcal4500, references oldval/test descriptive only. Historical adaptivity remains; no unbiased generalization or production claim.
All23 raw predictors finite, categorical integer; retain unknown codes. make_features constructs only PREDICTORS and matched legacy68 columns exactly all30k cells, target/ID excluded. Nested fitter receives outer-training features/targets/groups only. Existing immutable V1/V2 scripts retained; maintained package new. Files/predictions exported as byte-preserved snapshots. Review below independent of outcome, do not add candidates based on scores.
"""
    ]
    for name in ("nested.py", "models.py", "schema.py"):
        path = ROOT / "src/creditrisk" / name
        sections.append(
            f"FILE {path.relative_to(ROOT).as_posix()}\n{path.read_text(encoding='utf-8')}"
        )
    sections.append(
        excerpt(ROOT / "src/creditrisk/experiment.py", {"load_inputs", "run_outer_fold", "select"})
    )
    sections.append(
        excerpt(ROOT / "src/creditrisk/calibration.py", {"select_calibrator", "fit_calibrator"})
    )
    prompt = "\n\n".join(sections)
    if len(prompt) > 24000:
        raise ValueError(f"Prompt too long: {len(prompt)}")
    path = ROOT / "research/AGY_V3_CODE_PROMPT.txt"
    path.write_text(prompt, encoding="utf-8")
    print({"prompt_chars": len(prompt), "path": path.relative_to(ROOT).as_posix()})


if __name__ == "__main__":
    main()

"""Portable command-line entry points for research and development scoring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd

from . import experiment
from .exploration import explore
from .models import CreditPipeline


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("outputs/experiment_v3"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    for stage in ("prepare", "cv", "select", "finalize", "explore"):
        stage_parser = subparsers.add_parser(stage)
        if stage in {"prepare", "explore"}:
            stage_parser.add_argument(
                "--data", type=Path, default=Path("data/raw/kaggle_credit_card/UCI_Credit_Card.csv")
            )
            stage_parser.add_argument("--reference", type=Path, default=Path("reports/v2"))
    score_parser = subparsers.add_parser("score")
    score_parser.add_argument("input_csv", type=Path)
    score_parser.add_argument(
        "--model", type=Path, default=Path("outputs/experiment_v3/models/selected.joblib")
    )
    score_parser.add_argument("--scores", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = root / args.output
    result = None
    if args.command == "prepare":
        result = experiment.prepare(
            root, output, data_path=root / args.data, reference=root / args.reference
        )
    elif args.command == "explore":
        result = explore(root / args.data, root / args.reference / "folds.csv", output)
    elif args.command == "score":
        # Only load locally created/trusted model files: joblib can execute pickle code.
        pipeline = joblib.load(root / args.model)
        if not isinstance(pipeline, CreditPipeline):
            raise ValueError("Model artifact is not a versioned CreditPipeline.")
        scores = pipeline.predict(pd.read_csv(root / args.input_csv))
        destination = root / args.scores
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError("Scores output already exists; select a new filename.")
        scores.to_csv(destination, index=False)
        print(scores.to_string(index=False))
    elif args.command == "cv":
        experiment.run_cv(root, output)
    else:
        result = getattr(experiment, args.command)(root, output)
    if result is not None:
        compact = {
            key: value
            for key, value in result.items()
            if key not in {"hashes", "feature_quality", "outer_search", "final_search"}
        }
        print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

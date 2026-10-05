from creditrisk.cli import main


def test_cv_command_dispatches_to_outer_cv_runner(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        "creditrisk.experiment.run_cv", lambda root, output: calls.append((root, output))
    )
    main(["--root", str(tmp_path), "cv"])
    assert calls == [(tmp_path, tmp_path / "outputs/experiment_v3")]

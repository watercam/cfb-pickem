import shutil
from pathlib import Path

from src.backtest.run import main
from src.features.market_movement import no_vig_probability
from tests.helpers import write_mini_raw_cache


def _prep_root(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    (tmp_path / "config").mkdir()
    shutil.copy(repo / "config" / "backtest.yaml", tmp_path / "config" / "backtest.yaml")
    shutil.copy(repo / "config" / "experiment_late_line.yaml", tmp_path / "config" / "experiment_late_line.yaml")
    shutil.copy(repo / "config" / "team_aliases.yaml", tmp_path / "config" / "team_aliases.yaml")
    write_mini_raw_cache(tmp_path)


def test_cache_only_run_writes_four_artifacts(tmp_path, monkeypatch) -> None:
    _prep_root(tmp_path)
    monkeypatch.setenv("CFB_PICKEM_ROOT", str(tmp_path))
    assert main(["--mode", "cache_only", "--bootstrap-iterations", "30"]) == 0
    processed = tmp_path / "data" / "processed"
    outputs = tmp_path / "data" / "outputs"
    assert (processed / "backtest_dataset.parquet").exists()
    assert (outputs / "line_movement_matrix.csv").exists()
    assert (outputs / "model_metrics.csv").exists()
    assert (outputs / "backtest_report.md").exists()
    report = (outputs / "backtest_report.md").read_text()
    assert any(v in report for v in ["**Verdict: A.", "**Verdict: B.", "**Verdict: C.", "**Verdict: D."])
    assert "movement_adjustment" not in report or "all zero" in report.lower() or "Verdict: C" in report or "Verdict: D" in report or "Verdict: B" in report


def test_joined_cache_has_no_lookahead_and_valid_signs(tmp_path, monkeypatch) -> None:
    import pandas as pd

    _prep_root(tmp_path)
    monkeypatch.setenv("CFB_PICKEM_ROOT", str(tmp_path))
    assert main(["--mode", "cache_only", "--bootstrap-iterations", "20"]) == 0
    dataset = pd.read_parquet(tmp_path / "data" / "processed" / "backtest_dataset.parquet")
    modeled = dataset.loc[dataset["include_in_model"]]
    assert not modeled.empty
    kickoff = pd.to_datetime(modeled["kickoff_timestamp"], utc=True)
    current = pd.to_datetime(modeled["current_timestamp"], utc=True)
    reference = pd.to_datetime(modeled["reference_timestamp"], utc=True)
    assert (current <= kickoff - pd.Timedelta(hours=24)).all()
    assert (reference <= kickoff - pd.Timedelta(hours=72)).all()
    # T-1h steam to -20 must not appear.
    assert (modeled["current_spread"] != -20).all()
    for _, row in modeled.iterrows():
        if row["spread_move"] > 0:
            assert row["reference_spread"] > row["current_spread"]
    matrix = pd.read_csv(tmp_path / "data" / "outputs" / "line_movement_matrix.csv")
    assert len(matrix) == 42
    assert (matrix["shrunk_adjustment"].abs() <= 0.03 + 1e-12).all()
    metrics = pd.read_csv(tmp_path / "data" / "outputs" / "model_metrics.csv")
    assert {"A", "B"}.issubset(set(metrics["model"]))
    assert "pooled_oos" in set(metrics["fold_id"])


def test_late_line_experiment_does_not_overwrite_v1(tmp_path, monkeypatch) -> None:
    _prep_root(tmp_path)
    monkeypatch.setenv("CFB_PICKEM_ROOT", str(tmp_path))
    assert main(["--mode", "cache_only", "--bootstrap-iterations", "20"]) == 0
    v1_report = (tmp_path / "data" / "outputs" / "backtest_report.md").read_text()
    v1_dataset = tmp_path / "data" / "processed" / "backtest_dataset.parquet"
    assert v1_dataset.exists()
    stamp = v1_dataset.stat().st_mtime
    assert main(
        ["--mode", "cache_only", "--experiment", "late_line", "--bootstrap-iterations", "20"]
    ) == 0
    assert (tmp_path / "data" / "outputs" / "backtest_report.md").read_text() == v1_report
    assert v1_dataset.stat().st_mtime == stamp
    exp_dir = tmp_path / "data" / "outputs" / "experiment_late_line"
    assert (exp_dir / "experiment_report.md").exists()
    assert (tmp_path / "data" / "processed" / "experiment_horizon_dataset.parquet").exists()
    report = (exp_dir / "experiment_report.md").read_text()
    assert "Experiment L" in report
    assert "Experiment S" in report
    assert "Oracle" in report


def test_late_line_dry_run_lists_only_missing(tmp_path, monkeypatch, capsys) -> None:
    from datetime import timedelta

    from src.data.fetch_odds_history import floor_to_grid, snapshot_filename
    from tests.helpers import KICKOFFS

    _prep_root(tmp_path)
    monkeypatch.setenv("CFB_PICKEM_ROOT", str(tmp_path))
    missing_ts = floor_to_grid(KICKOFFS[2021] - timedelta(hours=1), 5)
    path = tmp_path / "data" / "raw" / "odds_api" / "snapshots" / snapshot_filename(missing_ts)
    path.unlink()
    assert main(["--experiment", "late_line", "--dry-run-fetch", "--mode", "cache_only"]) == 0
    captured = capsys.readouterr().out
    assert missing_ts.strftime("%Y-%m-%dT%H:%M:%SZ") in captured
    assert "n_requests (new GETs):" in captured
    assert "No HTTP was made" in captured


def test_no_vig_pair_still_sums_to_one() -> None:
    p = no_vig_probability(-150, 130)
    q = no_vig_probability(130, -150)
    assert abs(p + q - 1.0) < 1e-9

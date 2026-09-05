"""Pipeline entry point.

python -m src.backtest.run

Regenerates backtest_dataset.parquet, line_movement_matrix.csv,
model_metrics.csv, and backtest_report.md from cached raw data.
"""

from __future__ import annotations

import argparse
import json
from typing import Optional

from src.backtest.late_line import walk_forward_L, walk_forward_S
from src.backtest.walk_forward import walk_forward
from src.data.build_dataset import build_dataset, build_horizon_dataset
from src.data.fetch_odds_history import fetch_odds_history, plan_fetch
from src.data.fetch_results import fetch_results
from src.models.matrix_builder import apply_production_inclusion, build_matrix
from src.reporting.generate_experiment_report import generate_experiment_report
from src.reporting.generate_report import generate_report
from src.settings import get_api_keys, load_backtest_config, load_experiment_config, resolve_paths


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="V1 Pinnacle line-movement backtest")
    parser.add_argument(
        "--mode",
        choices=["cache_only", "fetch_missing"],
        default=None,
        help="cache_only never makes HTTP calls. Default comes from config/run.default_mode.",
    )
    parser.add_argument(
        "--dry-run-fetch",
        action="store_true",
        help="Print unique snapshot timestamps and estimated Odds API credits, then exit 0.",
    )
    parser.add_argument(
        "--confirm-fetch",
        action="store_true",
        help="Required with allow_historical_fetch to perform Odds API historical GETs.",
    )
    parser.add_argument(
        "--experiment",
        choices=["late_line"],
        default=None,
        help="Run a side experiment. late_line writes data/outputs/experiment_late_line/ and does not overwrite V1 artifacts.",
    )
    parser.add_argument(
        "--bootstrap-iterations",
        type=int,
        default=None,
        help="Override bootstrap iterations (tests may use a smaller value).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if args.experiment == "late_line":
        config = load_experiment_config("late_line")
    else:
        config = load_backtest_config()
    keys = get_api_keys()
    mode = args.mode or config.get("run", {}).get("default_mode", "cache_only")
    paths = resolve_paths(config)
    mvp = config["mvp"]

    print("Line-movement backtest environment")
    print(f"  mode: {mode}")
    print(f"  experiment: {args.experiment or 'v1'}")
    print(f"  seasons: {mvp['seasons']}")
    print(f"  decision_horizon_hours: {mvp['decision_horizon_hours']}")
    print(f"  reference_horizon_hours: {mvp['reference_horizon_hours']}")
    if config.get("snapshot_horizons_hours"):
        print(f"  snapshot_horizons_hours: {config['snapshot_horizons_hours']}")
    print(f"  sharp_source: {mvp['sharp_source']}")
    print(f"  CFBD_API_KEY: {'set' if keys.cfbd else 'MISSING'}")
    print(f"  ODDS_API_KEY: {'set' if keys.odds else 'MISSING'}")
    if keys.missing and mode == "cache_only":
        print("Missing keys are allowed in cache_only if raw caches exist.")
    elif keys.missing and mode == "fetch_missing":
        print(
            "Some keys are missing; fetch_missing will use cache for those sources "
            "and skip live HTTP for them."
        )

    try:
        games = fetch_results(mode=mode, config=config)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1

    plan = plan_fetch(games, config)
    print(f"  planned unique snapshots: {plan.get('n_planned', plan['n_requests'])}")
    print(f"  already cached: {plan.get('n_cached', 'n/a')}")
    print(f"  missing timestamps: {plan.get('n_missing', plan['n_requests'])}")
    print(f"  estimated Odds API credits (missing): {plan['est_credits']}")

    if args.dry_run_fetch:
        missing = plan.get("missing_timestamps") or plan["timestamps"]
        print("Dry-run missing snapshot timestamps (UTC, 5-minute floor):")
        if not missing:
            print("  (none — cache already has every planned timestamp)")
        for ts in missing:
            print(f"  {ts.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        print(f"n_requests (new GETs): {len(missing)}")
        print(f"est_credits: {plan['est_credits']}")
        print("No HTTP was made for Odds API.")
        if plan["n_requests"] > plan["max_historical_requests"]:
            print(
                f"ERROR: planned new requests {plan['n_requests']} exceed "
                f"max_historical_requests={plan['max_historical_requests']}."
            )
            return 1
        return 0

    if plan["n_requests"] > plan["max_historical_requests"]:
        print(
            f"ERROR: planned new requests {plan['n_requests']} exceed "
            f"max_historical_requests={plan['max_historical_requests']}."
        )
        return 1

    try:
        snapshots = fetch_odds_history(
            games,
            mode=mode,
            dry_run=False,
            confirm_fetch=args.confirm_fetch,
            config=config,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"BLOCKER: Pinnacle snapshots cannot be reconstructed. {exc}")
        print("Never substituting another sportsbook.")
        return 1

    if args.experiment == "late_line" and int(plan.get("n_missing") or 0) > 0:
        fetch_dir = paths["outputs"]
        fetch_dir.mkdir(parents=True, exist_ok=True)
        (fetch_dir / "fetch_summary.json").write_text(
            json.dumps(
                {
                    "n_planned": plan.get("n_planned"),
                    "n_cached_before": plan.get("n_cached"),
                    "n_missing_fetched": plan.get("n_missing"),
                    "est_credits": plan.get("est_credits"),
                    "book": "pinnacle",
                },
                indent=2,
            )
            + "\n"
        )

    if args.experiment == "late_line":
        return _run_late_line(args, config, games, snapshots, plan, paths)

    dataset = build_dataset(games, snapshots, config=config)
    lookahead = dataset["exclusion_reasons"].fillna("").str.contains("LOOKAHEAD_GUARD", regex=False)
    if lookahead.any():
        print("BLOCKER: look-ahead guard fired on joined rows. Modeling aborted.")
        return 1

    n_modeled = int(dataset["include_in_model"].sum()) if not dataset.empty else 0
    pinnacle_reconstructed = not snapshots.empty
    if not pinnacle_reconstructed:
        print("BLOCKER: odds_snapshots.parquet is empty. Modeling aborted.")
        return 1

    iterations = args.bootstrap_iterations
    if iterations is None:
        iterations = int(config["bootstrap"]["iterations"])

    wf = walk_forward(dataset, config, bootstrap_iterations=iterations)
    full_matrix = build_matrix(dataset, config, bootstrap_iterations=iterations)
    matrix = apply_production_inclusion(
        full_matrix,
        cell_oos=wf["cell_oos"],
        model_b_beats_a=wf["model_b_beats_a"],
        config=config,
    )
    outputs = paths["outputs"]
    outputs.mkdir(parents=True, exist_ok=True)
    processed = paths["processed"]
    processed.mkdir(parents=True, exist_ok=True)
    dataset.to_parquet(processed / "backtest_dataset.parquet", index=False)
    matrix.to_csv(outputs / "line_movement_matrix.csv", index=False)
    wf["metrics"].to_csv(outputs / "model_metrics.csv", index=False)

    data_note = (
        f"Rebuilt from cache under `{paths['raw_cfbd']}` and `{paths['snapshots']}` "
        f"with {n_modeled} modeled favorite rows."
    )
    generate_report(
        dataset,
        games,
        matrix,
        wf["metrics"],
        config=config,
        pinnacle_reconstructed=pinnacle_reconstructed,
        data_note=data_note,
    )
    print(f"Wrote {processed / 'backtest_dataset.parquet'}")
    print(f"Wrote {outputs / 'line_movement_matrix.csv'}")
    print(f"Wrote {outputs / 'model_metrics.csv'}")
    print(f"Wrote {outputs / 'backtest_report.md'}")
    return 0


def _run_late_line(args, config, games, snapshots, plan, paths) -> int:
    dataset = build_horizon_dataset(games, snapshots, config=config)
    lookahead = dataset["exclusion_reasons"].fillna("").str.contains("LOOKAHEAD_GUARD", regex=False)
    if lookahead.any():
        print("BLOCKER: look-ahead guard fired on joined rows. Modeling aborted.")
        return 1

    pinnacle_reconstructed = not snapshots.empty
    if not pinnacle_reconstructed:
        print("BLOCKER: odds_snapshots.parquet is empty. Modeling aborted.")
        return 1

    iterations = args.bootstrap_iterations
    if iterations is None:
        iterations = int(config["bootstrap"]["iterations"])

    result_l = walk_forward_L(dataset, config, bootstrap_iterations=iterations)
    result_s = walk_forward_S(dataset, config)
    clock1 = dataset.loc[
        (dataset["decision_horizon_hours"] == 1) & (dataset["include_in_model"])
    ]
    full_matrix = build_matrix(
        clock1.assign(include_in_model=True),
        config,
        bootstrap_iterations=iterations,
    )
    matrix_l = apply_production_inclusion(
        full_matrix,
        cell_oos=result_l.get("cell_oos"),
        model_b_beats_a=result_l.get("model_b_beats_a", False),
        config=config,
    )

    outputs = paths["outputs"]
    outputs.mkdir(parents=True, exist_ok=True)
    processed = paths["processed"]
    processed.mkdir(parents=True, exist_ok=True)
    dataset.to_parquet(processed / "experiment_horizon_dataset.parquet", index=False)
    matrix_l.to_csv(outputs / "l_line_movement_matrix.csv", index=False)
    result_l["metrics"].to_csv(outputs / "l_model_metrics.csv", index=False)
    result_s["metrics"].to_csv(outputs / "s_model_metrics.csv", index=False)
    if result_s.get("close_forecast_error") is not None:
        result_s["close_forecast_error"].to_csv(outputs / "s_close_forecast_error.csv", index=False)

    data_note = (
        f"Late-line experiment from `{paths['snapshots']}`. "
        f"L modeled n={result_l.get('n_modeled', 0)}; "
        f"S modeled n={result_s.get('n_s_modeled', 0)}. "
        "V1 backtest_dataset.parquet and backtest_report.md were not overwritten."
    )
    generate_experiment_report(
        dataset,
        config=config,
        plan=plan,
        result_l=result_l,
        result_s=result_s,
        matrix_l=matrix_l,
        pinnacle_reconstructed=pinnacle_reconstructed,
        data_note=data_note,
    )
    print(f"Wrote {processed / 'experiment_horizon_dataset.parquet'}")
    print(f"Wrote {outputs / 'experiment_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

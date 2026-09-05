"""Season-based walk-forward validation. Never randomly split games."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pandas as pd

from src.models.baseline_market import model_a_probs
from src.models.calibration import classification_metrics
from src.models.matrix_builder import build_matrix
from src.models.movement_model import model_b_probs

EPS = 1e-6


def walk_forward(
    dataset: pd.DataFrame,
    config: Dict[str, Any],
    *,
    bootstrap_iterations: int | None = None,
) -> Dict[str, Any]:
    modeled = dataset.loc[dataset["include_in_model"]].copy()
    folds = config["walk_forward"]["folds"]
    metric_rows: List[Dict[str, Any]] = []
    pred_parts: List[pd.DataFrame] = []
    oos_cells: List[pd.DataFrame] = []
    train_matrices = {}

    for fold_i, fold in enumerate(folds, start=1):
        train_seasons = set(fold["train"])
        test_seasons = set(fold["test"])
        train = modeled.loc[modeled["season"].isin(train_seasons)]
        test = modeled.loc[modeled["season"].isin(test_seasons)]
        fold_id = f"fold_{fold_i}"
        test_season = int(list(fold["test"])[0])
        matrix = build_matrix(
            train.assign(include_in_model=True),
            config,
            bootstrap_iterations=bootstrap_iterations,
        )
        train_matrices[fold_id] = matrix
        if test.empty:
            metric_rows.extend(
                [
                    _empty_metrics(fold_id, test_season, "A"),
                    _empty_metrics(fold_id, test_season, "B"),
                ]
            )
            continue
        p_a = model_a_probs(test, config)
        p_b = model_b_probs(test, matrix, config)
        y = test["win"].to_numpy(dtype=int)
        metrics_a = classification_metrics(y, p_a, config)
        metrics_b = classification_metrics(y, p_b, config)
        metric_rows.append(_metric_row(fold_id, test_season, "A", metrics_a))
        metric_rows.append(_metric_row(fold_id, test_season, "B", metrics_b))
        part = test.copy()
        part["fold_id"] = fold_id
        part["p_model_a"] = p_a
        part["p_model_b"] = p_b
        pred_parts.append(part)
        oos_cells.append(_oos_cell_residuals(test, fold_id, test_season))

    oos = pd.concat(pred_parts, ignore_index=True) if pred_parts else modeled.iloc[0:0]
    if not oos.empty:
        y = oos["win"].to_numpy(dtype=int)
        pooled_a = classification_metrics(y, oos["p_model_a"].to_numpy(), config)
        pooled_b = classification_metrics(y, oos["p_model_b"].to_numpy(), config)
        metric_rows.append(_metric_row("pooled_oos", "2023-2025", "A", pooled_a))
        metric_rows.append(_metric_row("pooled_oos", "2023-2025", "B", pooled_b))
    metrics = pd.DataFrame(metric_rows)
    cell_oos = pd.concat(oos_cells, ignore_index=True) if oos_cells else pd.DataFrame()
    beats = model_b_beats_a(metrics)
    return {
        "metrics": metrics,
        "oos_predictions": oos,
        "cell_oos": cell_oos,
        "train_matrices": train_matrices,
        "model_b_beats_a": beats,
    }


def model_b_beats_a(metrics: pd.DataFrame) -> bool:
    pooled = metrics.loc[metrics["fold_id"] == "pooled_oos"]
    if pooled.empty:
        return False
    a = pooled.loc[pooled["model"] == "A"].iloc[0]
    b = pooled.loc[pooled["model"] == "B"].iloc[0]
    ll_ok = b["log_loss"] <= a["log_loss"] + EPS
    br_ok = b["brier"] <= a["brier"] + EPS
    strict = (b["log_loss"] < a["log_loss"] - EPS) or (b["brier"] < a["brier"] - EPS)
    return bool(ll_ok and br_ok and strict)


def model_b_worse_than_a(metrics: pd.DataFrame) -> bool:
    pooled = metrics.loc[metrics["fold_id"] == "pooled_oos"]
    if pooled.empty:
        return False
    a = pooled.loc[pooled["model"] == "A"].iloc[0]
    b = pooled.loc[pooled["model"] == "B"].iloc[0]
    return bool(b["log_loss"] > a["log_loss"] + EPS or b["brier"] > a["brier"] + EPS)


def _oos_cell_residuals(test: pd.DataFrame, fold_id: str, test_season: int) -> pd.DataFrame:
    rows = []
    for (band, bucket), cell in test.groupby(["probability_band", "movement_bucket"]):
        n = len(cell)
        raw = float(cell["win"].mean() - cell["current_probability"].mean()) if n else 0.0
        rows.append(
            {
                "fold_id": fold_id,
                "test_season": test_season,
                "probability_band": band,
                "movement_bucket": bucket,
                "n": n,
                "raw_adjustment": raw,
            }
        )
    return pd.DataFrame(rows)


def _metric_row(fold_id: str, test_season: Any, model: str, metrics: Dict[str, float]) -> Dict[str, Any]:
    return {
        "fold_id": fold_id,
        "test_season": test_season,
        "model": model,
        "n": int(metrics["n"]),
        "log_loss": metrics["log_loss"],
        "brier": metrics["brier"],
        "ece": metrics["ece"],
        "accuracy": metrics["accuracy"],
    }


def _empty_metrics(fold_id: str, test_season: Any, model: str) -> Dict[str, Any]:
    return {
        "fold_id": fold_id,
        "test_season": test_season,
        "model": model,
        "n": 0,
        "log_loss": float("nan"),
        "brier": float("nan"),
        "ece": float("nan"),
        "accuracy": float("nan"),
    }

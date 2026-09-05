"""Walk-forward for Experiment L (1h clock) and Experiment S (forecast the close)."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from src.backtest.walk_forward import (
    _empty_metrics,
    _metric_row,
    _oos_cell_residuals,
    model_b_beats_a,
)
from src.models.baseline_market import model_a_probs
from src.models.calibration import classification_metrics, clamp_probabilities
from src.models.close_forecast import close_forecast_error, fit_close_forecast, predict_p_1h
from src.models.matrix_builder import build_matrix
from src.models.movement_model import model_b_probs

MIN_WALKFORWARD_N = 50


def clock_frame(dataset: pd.DataFrame, decision_hours: int) -> pd.DataFrame:
    return dataset.loc[dataset["decision_horizon_hours"] == decision_hours].copy()


def walk_forward_L(
    dataset: pd.DataFrame,
    config: Dict[str, Any],
    *,
    bootstrap_iterations: int | None = None,
) -> Dict[str, Any]:
    modeled = clock_frame(dataset, 1)
    modeled = modeled.loc[modeled["include_in_model"]].copy()
    return _walk_ab(modeled, config, bootstrap_iterations=bootstrap_iterations)


def walk_forward_S(
    dataset: pd.DataFrame,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    clock24 = clock_frame(dataset, 24)
    modeled = clock24.loc[clock24["include_in_model"]].copy()
    folds = config["walk_forward"]["folds"]
    metric_rows: List[Dict[str, Any]] = []
    pred_parts: List[pd.DataFrame] = []
    close_rows: List[Dict[str, Any]] = []

    for fold_i, fold in enumerate(folds, start=1):
        train_seasons = set(fold["train"])
        test_seasons = set(fold["test"])
        train = modeled.loc[modeled["season"].isin(train_seasons)]
        test = modeled.loc[modeled["season"].isin(test_seasons)]
        fold_id = f"fold_{fold_i}"
        test_season = int(list(fold["test"])[0])
        forecast_model = fit_close_forecast(train)
        if test.empty:
            for name in ("A24", "Forecast", "Oracle"):
                metric_rows.append(_empty_metrics(fold_id, test_season, name))
            continue
        cal = config["calibration"]
        p_a24 = clamp_probabilities(
            test["p_24"].to_numpy(dtype=float),
            cal["clamp_min"],
            cal["clamp_max"],
        )
        p_forecast = predict_p_1h(test, forecast_model, config)
        has_1h = test["p_1h"].notna()
        y_all = test["win"].to_numpy(dtype=int)
        metrics_a_all = classification_metrics(y_all, p_a24, config)
        metric_rows.append(_metric_row(fold_id, test_season, "A24_all", metrics_a_all))

        inter = test.loc[has_1h]
        if inter.empty:
            for name in ("A24", "Forecast", "Oracle"):
                metric_rows.append(_empty_metrics(fold_id, test_season, name))
            continue
        y = inter["win"].to_numpy(dtype=int)
        p_a = clamp_probabilities(
            inter["p_24"].to_numpy(dtype=float),
            cal["clamp_min"],
            cal["clamp_max"],
        )
        p_fc = predict_p_1h(inter, forecast_model, config)
        p_ora = clamp_probabilities(
            inter["p_1h"].to_numpy(dtype=float),
            cal["clamp_min"],
            cal["clamp_max"],
        )
        metric_rows.append(_metric_row(fold_id, test_season, "A24", classification_metrics(y, p_a, config)))
        metric_rows.append(
            _metric_row(fold_id, test_season, "Forecast", classification_metrics(y, p_fc, config))
        )
        metric_rows.append(
            _metric_row(fold_id, test_season, "Oracle", classification_metrics(y, p_ora, config))
        )
        err = close_forecast_error(p_fc, inter["p_1h"].to_numpy(dtype=float))
        close_rows.append({"fold_id": fold_id, "test_season": test_season, **err})
        part = inter.copy()
        part["fold_id"] = fold_id
        part["p_a24"] = p_a
        part["p_forecast"] = p_fc
        part["p_oracle"] = p_ora
        pred_parts.append(part)

    oos = pd.concat(pred_parts, ignore_index=True) if pred_parts else modeled.iloc[0:0]
    if not oos.empty:
        y = oos["win"].to_numpy(dtype=int)
        metric_rows.append(
            _metric_row("pooled_oos", "2023-2025", "A24", classification_metrics(y, oos["p_a24"], config))
        )
        metric_rows.append(
            _metric_row(
                "pooled_oos",
                "2023-2025",
                "Forecast",
                classification_metrics(y, oos["p_forecast"], config),
            )
        )
        metric_rows.append(
            _metric_row(
                "pooled_oos",
                "2023-2025",
                "Oracle",
                classification_metrics(y, oos["p_oracle"], config),
            )
        )
        pooled_err = close_forecast_error(
            oos["p_forecast"].to_numpy(dtype=float),
            oos["p_1h"].to_numpy(dtype=float),
        )
        close_rows.append({"fold_id": "pooled_oos", "test_season": "2023-2025", **pooled_err})
    return {
        "metrics": pd.DataFrame(metric_rows),
        "oos_predictions": oos,
        "close_forecast_error": pd.DataFrame(close_rows),
        "n_s_modeled": int(len(modeled)),
        "n_s_with_1h": int(modeled["p_1h"].notna().sum()) if not modeled.empty else 0,
    }


def forecast_beats_a24(metrics: pd.DataFrame) -> bool:
    pooled = metrics.loc[metrics["fold_id"] == "pooled_oos"]
    if pooled.empty:
        return False
    a = pooled.loc[pooled["model"] == "A24"]
    fc = pooled.loc[pooled["model"] == "Forecast"]
    if a.empty or fc.empty:
        return False
    a_row, fc_row = a.iloc[0], fc.iloc[0]
    eps = 1e-6
    ll_ok = fc_row["log_loss"] <= a_row["log_loss"] + eps
    br_ok = fc_row["brier"] <= a_row["brier"] + eps
    strict = (fc_row["log_loss"] < a_row["log_loss"] - eps) or (
        fc_row["brier"] < a_row["brier"] - eps
    )
    return bool(ll_ok and br_ok and strict)


def sample_too_small(n: int) -> bool:
    return n < MIN_WALKFORWARD_N


def _walk_ab(
    modeled: pd.DataFrame,
    config: Dict[str, Any],
    *,
    bootstrap_iterations: int | None = None,
) -> Dict[str, Any]:
    folds = config["walk_forward"]["folds"]
    metric_rows: List[Dict[str, Any]] = []
    pred_parts: List[pd.DataFrame] = []
    oos_cells: List[pd.DataFrame] = []
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
        if test.empty:
            metric_rows.extend(
                [
                    _empty_metrics(fold_id, test_season, "A1"),
                    _empty_metrics(fold_id, test_season, "B1"),
                ]
            )
            continue
        p_a = model_a_probs(test, config)
        p_b = model_b_probs(test, matrix, config)
        y = test["win"].to_numpy(dtype=int)
        metric_rows.append(_metric_row(fold_id, test_season, "A1", classification_metrics(y, p_a, config)))
        metric_rows.append(_metric_row(fold_id, test_season, "B1", classification_metrics(y, p_b, config)))
        part = test.copy()
        part["fold_id"] = fold_id
        part["p_model_a"] = p_a
        part["p_model_b"] = p_b
        pred_parts.append(part)
        oos_cells.append(_oos_cell_residuals(test, fold_id, test_season))

    oos = pd.concat(pred_parts, ignore_index=True) if pred_parts else modeled.iloc[0:0]
    if not oos.empty:
        y = oos["win"].to_numpy(dtype=int)
        metric_rows.append(
            _metric_row("pooled_oos", "2023-2025", "A1", classification_metrics(y, oos["p_model_a"], config))
        )
        metric_rows.append(
            _metric_row("pooled_oos", "2023-2025", "B1", classification_metrics(y, oos["p_model_b"], config))
        )
    metrics = pd.DataFrame(metric_rows)
    renamed = metrics.copy()
    renamed["model"] = renamed["model"].replace({"A1": "A", "B1": "B"})
    beats = model_b_beats_a(renamed)
    return {
        "metrics": metrics,
        "oos_predictions": oos,
        "cell_oos": pd.concat(oos_cells, ignore_index=True) if oos_cells else pd.DataFrame(),
        "model_b_beats_a": beats,
        "n_modeled": int(len(modeled)),
    }

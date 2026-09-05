"""Build the shrunk 7×6 production matrix and write line_movement_matrix.csv."""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from src.backtest.bootstrap import bootstrap_residual_ci
from src.features.market_movement import assign_interval_label


def shrinkage_weight(n: int, config: Dict[str, Any]) -> float:
    thresholds = config["shrinkage"]["n_thresholds"]
    weights = config["shrinkage"]["weights"]
    if n < int(thresholds["very_heavy"]):
        return float(weights["very_heavy"])
    if n < int(thresholds["heavy"]):
        return float(weights["heavy"])
    if n < int(thresholds["moderate"]):
        return float(weights["moderate"])
    if n < int(thresholds["light"]):
        return float(weights["light"])
    return float(weights["minimal"])


def empty_matrix_template(config: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for band in config["probability_bands"]:
        for bucket in config["movement_buckets"]:
            rows.append(
                {
                    "probability_band": band["label"],
                    "probability_min": float(band["min"]),
                    "probability_max": float(band["max"]),
                    "movement_bucket": bucket["label"],
                    "movement_min": float(bucket["min"]),
                    "movement_max": float(bucket["max"]),
                    "sample_size": 0,
                    "raw_adjustment": 0.0,
                    "shrunk_adjustment": 0.0,
                    "ci_lower": np.nan,
                    "ci_upper": np.nan,
                    "production_adjustment": 0.0,
                }
            )
    return pd.DataFrame(rows)


def build_matrix(
    frame: pd.DataFrame,
    config: Dict[str, Any],
    *,
    bootstrap_iterations: Optional[int] = None,
) -> pd.DataFrame:
    template = empty_matrix_template(config)
    if frame is None or frame.empty:
        return template
    modeled = frame.loc[frame["include_in_model"]].copy()
    if modeled.empty:
        return template
    iterations = bootstrap_iterations
    if iterations is None:
        iterations = int(config["bootstrap"]["iterations"])
    cap = float(config["shrinkage"]["max_adjustment"])
    rows = []
    for _, spec in template.iterrows():
        cell = modeled.loc[
            (modeled["probability_band"] == spec["probability_band"])
            & (modeled["movement_bucket"] == spec["movement_bucket"])
        ]
        n = int(len(cell))
        if n == 0:
            rows.append(
                {
                    **spec.to_dict(),
                    "sample_size": 0,
                    "raw_adjustment": 0.0,
                    "shrunk_adjustment": 0.0,
                    "ci_lower": np.nan,
                    "ci_upper": np.nan,
                    "production_adjustment": 0.0,
                }
            )
            continue
        raw, lo, hi = bootstrap_residual_ci(cell, iterations=iterations, seed=42)
        weight = shrinkage_weight(n, config)
        shrunk = float(np.clip(raw * weight, -cap, cap))
        rows.append(
            {
                **spec.to_dict(),
                "sample_size": n,
                "raw_adjustment": raw,
                "shrunk_adjustment": shrunk,
                "ci_lower": lo,
                "ci_upper": hi,
                "production_adjustment": 0.0,
            }
        )
    return pd.DataFrame(rows)


def ci_crosses_zero(lo: float, hi: float) -> bool:
    if lo is None or hi is None or pd.isna(lo) or pd.isna(hi):
        return True
    return (lo <= 0 <= hi)


def apply_production_inclusion(
    full_matrix: pd.DataFrame,
    *,
    cell_oos: pd.DataFrame,
    model_b_beats_a: bool,
    config: Dict[str, Any],
) -> pd.DataFrame:
    """V1 inclusion without Pick'em simulation."""
    out = full_matrix.copy()
    cap = float(config["shrinkage"]["max_adjustment"])
    if not model_b_beats_a:
        out["production_adjustment"] = 0.0
        return out

    for idx, cell in out.iterrows():
        n = int(cell["sample_size"])
        shrunk = float(cell["shrunk_adjustment"])
        production = 0.0
        eligible = (
            n >= 50
            and shrunk != 0.0
            and not ci_crosses_zero(cell["ci_lower"], cell["ci_upper"])
        )
        if eligible:
            oos = _cell_oos_rows(cell_oos, cell)
            if _sign_stable(cell["raw_adjustment"], oos):
                production = float(np.clip(shrunk, -cap, cap))
        if config["shrinkage"].get("uncertain_to_zero") and (
            n < 50 or ci_crosses_zero(cell["ci_lower"], cell["ci_upper"])
        ):
            production = 0.0
        out.at[idx, "production_adjustment"] = production
    return out


def _cell_oos_rows(cell_oos: pd.DataFrame, cell: pd.Series) -> pd.DataFrame:
    if cell_oos is None or cell_oos.empty:
        return pd.DataFrame()
    return cell_oos.loc[
        (cell_oos["probability_band"] == cell["probability_band"])
        & (cell_oos["movement_bucket"] == cell["movement_bucket"])
    ]


def _sign_stable(train_raw: float, oos: pd.DataFrame) -> bool:
    if train_raw == 0 or pd.isna(train_raw):
        return False
    if oos is None or oos.empty:
        return False
    usable = oos.loc[oos["n"] >= 20]
    if usable.empty:
        return False
    signs = np.sign(usable["raw_adjustment"].to_numpy(dtype=float))
    train_sign = np.sign(train_raw)
    if len(usable) == 1:
        return bool(signs[0] == train_sign)
    agree = int((signs == train_sign).sum())
    return agree >= 2


def label_cells(frame: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    out = frame.copy()
    out["probability_band"] = [
        assign_interval_label(v, config["probability_bands"])
        for v in out["current_probability"]
    ]
    out["movement_bucket"] = [
        assign_interval_label(v, config["movement_buckets"]) for v in out["spread_move"]
    ]
    return out

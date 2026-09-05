"""Model B: market probability plus train-fold shrunk matrix lookup."""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from src.features.market_movement import assign_interval_label
from src.models.calibration import clamp_probabilities


def lookup_shrunk_adjustment(
    current_probability: float,
    spread_move: float,
    matrix: pd.DataFrame,
    config: Dict[str, Any],
) -> float:
    band = assign_interval_label(current_probability, config["probability_bands"])
    bucket = assign_interval_label(spread_move, config["movement_buckets"])
    if matrix is None or matrix.empty:
        return 0.0
    matched = matrix.loc[
        (matrix["probability_band"] == band) & (matrix["movement_bucket"] == bucket)
    ]
    if matched.empty:
        return 0.0
    value = matched.iloc[0]["shrunk_adjustment"]
    if value is None or pd.isna(value):
        return 0.0
    return float(value)


def model_b_probs(
    frame: pd.DataFrame,
    matrix: pd.DataFrame,
    config: Dict[str, Any],
) -> np.ndarray:
    cal = config["calibration"]
    base = frame["current_probability"].to_numpy(dtype=float)
    adj = np.array(
        [
            lookup_shrunk_adjustment(p, m, matrix, config)
            for p, m in zip(frame["current_probability"], frame["spread_move"])
        ],
        dtype=float,
    )
    return clamp_probabilities(base + adj, cal["clamp_min"], cal["clamp_max"])

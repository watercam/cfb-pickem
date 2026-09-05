"""Calibration error and probability clamping for production lookup."""

from __future__ import annotations

from typing import Any, Dict, Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss


def clamp_probabilities(p: np.ndarray, clamp_min: float, clamp_max: float) -> np.ndarray:
    return np.clip(np.asarray(p, dtype=float), clamp_min, clamp_max)


def log_loss_score(y: np.ndarray, p: np.ndarray) -> float:
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    if len(y) == 0:
        return float("nan")
    return float(log_loss(y, np.column_stack([1 - p, p]), labels=[0, 1]))


def brier_score(y: np.ndarray, p: np.ndarray) -> float:
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    if len(y) == 0:
        return float("nan")
    return float(brier_score_loss(y, p))


def expected_calibration_error(
    y: np.ndarray,
    p: np.ndarray,
    bands: Sequence[Dict[str, Any]],
) -> float:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    if len(y) == 0:
        return float("nan")
    total = len(y)
    ece = 0.0
    assigned = np.zeros(len(y), dtype=bool)
    for spec in bands:
        lo = float(spec["min"])
        hi = float(spec["max"])
        if spec.get("right_closed"):
            mask = (p >= lo) & (p <= hi)
        else:
            mask = (p >= lo) & (p < hi)
        assigned |= mask
        n = int(mask.sum())
        if n == 0:
            continue
        acc = float(y[mask].mean())
        conf = float(p[mask].mean())
        ece += (n / total) * abs(acc - conf)
    leftover = ~assigned
    n_left = int(leftover.sum())
    if n_left:
        acc = float(y[leftover].mean())
        conf = float(p[leftover].mean())
        ece += (n_left / total) * abs(acc - conf)
    return float(ece)


def classification_metrics(
    y: np.ndarray,
    p: np.ndarray,
    config: Dict[str, Any],
) -> Dict[str, float]:
    cal = config["calibration"]
    p_hat = clamp_probabilities(p, cal["clamp_min"], cal["clamp_max"])
    y_arr = np.asarray(y, dtype=int)
    return {
        "n": float(len(y_arr)),
        "log_loss": log_loss_score(y_arr, p_hat),
        "brier": brier_score(y_arr, p_hat),
        "ece": expected_calibration_error(y_arr, p_hat, config["probability_bands"]),
        "accuracy": float(((p_hat >= 0.5) == y_arr).mean()) if len(y_arr) else float("nan"),
    }

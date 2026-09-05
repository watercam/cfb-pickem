"""Cluster bootstrap by week-season, 1000+ iterations."""

from __future__ import annotations

from typing import Dict, Iterable, Tuple

import numpy as np
import pandas as pd


def week_season_key(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["season"].astype(int).astype(str)
        + "-"
        + frame["week"].astype(int).astype(str)
    )


def bootstrap_residual_ci(
    frame: pd.DataFrame,
    *,
    iterations: int = 1000,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """Percentile 95% CI on mean(win) - mean(current_probability)."""
    if frame is None or frame.empty:
        return float("nan"), float("nan"), float("nan")
    y = frame["win"].to_numpy(dtype=float)
    p = frame["current_probability"].to_numpy(dtype=float)
    raw = float(y.mean() - p.mean())
    clusters = week_season_key(frame).to_numpy()
    unique = np.unique(clusters)
    rng = np.random.default_rng(seed)
    stats = np.empty(iterations, dtype=float)
    grouped: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
    for key in unique:
        mask = clusters == key
        grouped[str(key)] = (y[mask], p[mask])
    keys = np.array(list(grouped.keys()))
    for i in range(iterations):
        draw = rng.choice(keys, size=len(keys), replace=True)
        ys = []
        ps = []
        for key in draw:
            gy, gp = grouped[str(key)]
            ys.append(gy)
            ps.append(gp)
        yb = np.concatenate(ys)
        pb = np.concatenate(ps)
        stats[i] = yb.mean() - pb.mean()
    lo, hi = np.quantile(stats, [0.025, 0.975])
    return raw, float(lo), float(hi)

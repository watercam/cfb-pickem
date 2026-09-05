"""Forecast the 1-hour Pinnacle probability from 24h-known features only.

Target is p_1h. Inputs are p_24 and spread_move_72_24. Never uses 1h prices
as features (those are train labels / oracle only).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from src.models.calibration import clamp_probabilities

FEATURE_COLUMNS = ("p_24", "spread_move_72_24")
EPS = 1e-4


def logit(p: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(p, dtype=float), EPS, 1.0 - EPS)
    return np.log(clipped / (1.0 - clipped))


def sigmoid(z: np.ndarray) -> np.ndarray:
    z = np.asarray(z, dtype=float)
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))


def fit_close_forecast(train: pd.DataFrame) -> Optional[LinearRegression]:
    """Fit logit(p_1h) ~ logit(p_24) + spread_move_72_24 on train rows."""
    usable = _labeled_rows(train)
    if len(usable) < 8:
        return None
    x = _design_matrix(usable)
    y = logit(usable["p_1h"].to_numpy(dtype=float))
    finite = np.isfinite(x).all(axis=1) & np.isfinite(y)
    if int(finite.sum()) < 8:
        return None
    model = LinearRegression()
    model.fit(x[finite], y[finite])
    return model


def predict_p_1h(
    frame: pd.DataFrame,
    model: Optional[LinearRegression],
    config: Dict[str, Any],
) -> np.ndarray:
    cal = config["calibration"]
    fallback = clamp_probabilities(
        np.nan_to_num(frame["p_24"].to_numpy(dtype=float), nan=0.5),
        cal["clamp_min"],
        cal["clamp_max"],
    )
    if model is None or frame.empty:
        return fallback
    x = _design_matrix(frame)
    finite = np.isfinite(x).all(axis=1)
    pred = np.array(fallback, copy=True)
    if finite.any():
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            raw = model.predict(x[finite])
        pred[finite] = sigmoid(raw)
        pred = np.where(np.isfinite(pred), pred, fallback)
    return clamp_probabilities(pred, cal["clamp_min"], cal["clamp_max"])


def close_forecast_error(p_hat: np.ndarray, p_1h: np.ndarray) -> Dict[str, float]:
    hat = np.asarray(p_hat, dtype=float)
    actual = np.asarray(p_1h, dtype=float)
    mask = np.isfinite(hat) & np.isfinite(actual)
    if not mask.any():
        return {"n": 0.0, "mae": float("nan"), "brier": float("nan")}
    hat = hat[mask]
    actual = actual[mask]
    return {
        "n": float(len(hat)),
        "mae": float(np.mean(np.abs(hat - actual))),
        "brier": float(np.mean((hat - actual) ** 2)),
    }


def _labeled_rows(frame: pd.DataFrame) -> pd.DataFrame:
    p24 = pd.to_numeric(frame["p_24"], errors="coerce")
    p1h = pd.to_numeric(frame["p_1h"], errors="coerce")
    move = pd.to_numeric(frame["spread_move_72_24"], errors="coerce")
    mask = p24.notna() & p1h.notna() & move.notna()
    mask &= np.isfinite(p24.to_numpy(dtype=float))
    mask &= np.isfinite(p1h.to_numpy(dtype=float))
    mask &= np.isfinite(move.to_numpy(dtype=float))
    return frame.loc[mask]


def _design_matrix(frame: pd.DataFrame) -> np.ndarray:
    if any(col not in frame.columns for col in FEATURE_COLUMNS):
        raise ValueError(f"Close forecast features must be {FEATURE_COLUMNS}")
    p24 = pd.to_numeric(frame["p_24"], errors="coerce").to_numpy(dtype=float)
    move = pd.to_numeric(frame["spread_move_72_24"], errors="coerce").to_numpy(dtype=float)
    p24 = np.where(np.isfinite(p24), p24, 0.5)
    move = np.where(np.isfinite(move), np.clip(move, -50.0, 50.0), 0.0)
    return np.column_stack([logit(p24), move])

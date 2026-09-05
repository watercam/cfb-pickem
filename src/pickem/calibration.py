"""Movement adjustment adapter: handwritten, matrix_csv, or none.

Does not import src.models or src.backtest. Ranking stays identical across sources.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd

from src.features.market_movement import assign_interval_label
from src.settings import project_root

LOGGER = logging.getLogger(__name__)

HANDWRITTEN_CAP = 0.03


def handwritten_adjustment(delta_spread: float) -> float:
    """Pick'em spec §4B. Gaps between 0.5 and 1.0 points are 0."""
    move = float(delta_spread)
    if move > 2.5:
        adj = 0.03
    elif 1.0 <= move <= 2.5:
        adj = 0.015
    elif -0.5 <= move <= 0.5:
        adj = 0.0
    elif -2.5 <= move <= -1.0:
        adj = -0.015
    elif move < -2.5:
        adj = -0.03
    else:
        adj = 0.0
    return max(-HANDWRITTEN_CAP, min(HANDWRITTEN_CAP, adj))


class MovementCalibrator:
    def __init__(
        self,
        source: str,
        *,
        matrix_path: Optional[Path] = None,
        clamp_min: float = 0.01,
        clamp_max: float = 0.99,
        max_adjustment: float = 0.03,
        matrix: Optional[pd.DataFrame] = None,
    ) -> None:
        self.source = source
        self.matrix_path = matrix_path
        self.clamp_min = float(clamp_min)
        self.clamp_max = float(clamp_max)
        self.max_adjustment = float(max_adjustment)
        self._matrix = matrix
        self._matrix_loaded = matrix is not None
        self._warned_missing = False
        if source not in {"handwritten", "matrix_csv", "none"}:
            raise ValueError(f"Unknown calibration source: {source}")

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        *,
        matrix: Optional[pd.DataFrame] = None,
    ) -> "MovementCalibrator":
        cal = config["calibration"]
        path_value = cal.get("matrix_csv")
        matrix_path = None
        if path_value:
            matrix_path = Path(path_value)
            if not matrix_path.is_absolute():
                matrix_path = project_root() / matrix_path
        return cls(
            str(cal["source"]),
            matrix_path=matrix_path,
            clamp_min=float(cal.get("clamp_min", 0.01)),
            clamp_max=float(cal.get("clamp_max", 0.99)),
            max_adjustment=float(cal.get("max_adjustment", 0.03)),
            matrix=matrix,
        )

    def movement_adjustment(
        self,
        current_probability: float,
        delta_spread: float,
    ) -> float:
        if self.source == "none":
            adj = 0.0
        elif self.source == "handwritten":
            adj = handwritten_adjustment(delta_spread)
        else:
            adj = self._matrix_adjustment(current_probability, delta_spread)
        cap = self.max_adjustment
        return max(-cap, min(cap, float(adj)))

    def clamp(self, probability: float) -> float:
        return max(self.clamp_min, min(self.clamp_max, float(probability)))

    def _matrix_adjustment(self, current_probability: float, delta_spread: float) -> float:
        frame = self._load_matrix()
        if frame is None or frame.empty:
            return 0.0
        if "production_adjustment" not in frame.columns:
            if not self._warned_missing:
                LOGGER.warning("matrix_csv has no production_adjustment column; using 0")
                self._warned_missing = True
            return 0.0
        p_specs = _interval_specs(frame, "probability_min", "probability_max")
        m_specs = _interval_specs(frame, "movement_min", "movement_max")
        p_key = assign_interval_label(float(current_probability), p_specs)
        m_key = assign_interval_label(float(delta_spread), m_specs)
        if not p_key or not m_key:
            return 0.0
        p_lo, p_hi = (float(x) for x in p_key.split(":"))
        m_lo, m_hi = (float(x) for x in m_key.split(":"))
        matched = frame.loc[
            (frame["probability_min"].astype(float) == p_lo)
            & (frame["probability_max"].astype(float) == p_hi)
            & (frame["movement_min"].astype(float) == m_lo)
            & (frame["movement_max"].astype(float) == m_hi)
        ]
        if matched.empty:
            return 0.0
        value = matched.iloc[0]["production_adjustment"]
        if pd.isna(value):
            return 0.0
        return float(value)

    def _load_matrix(self) -> Optional[pd.DataFrame]:
        if self._matrix_loaded:
            return self._matrix
        self._matrix_loaded = True
        if self.matrix_path is None or not self.matrix_path.exists():
            LOGGER.warning(
                "matrix_csv source selected but %s is missing; using 0",
                self.matrix_path,
            )
            self._matrix = None
            return None
        self._matrix = pd.read_csv(self.matrix_path)
        return self._matrix


def movement_adjustment(
    current_probability: float,
    delta_spread: float,
    *,
    calibrator: Optional[MovementCalibrator] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> float:
    adapter = calibrator
    if adapter is None:
        if config is None:
            raise ValueError("calibrator or config is required")
        adapter = MovementCalibrator.from_config(config)
    return adapter.movement_adjustment(current_probability, delta_spread)


def _interval_specs(
    frame: pd.DataFrame,
    min_col: str,
    max_col: str,
) -> List[Dict[str, Any]]:
    pairs = sorted(
        {(float(row[min_col]), float(row[max_col])) for _, row in frame.iterrows()},
        key=lambda pair: (pair[0], pair[1]),
    )
    specs: List[Dict[str, Any]] = []
    for index, (lo, hi) in enumerate(pairs):
        specs.append(
            {
                "label": f"{lo}:{hi}",
                "min": lo,
                "max": hi,
                "right_closed": index == len(pairs) - 1,
            }
        )
    return specs

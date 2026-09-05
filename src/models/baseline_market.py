"""Model A: current Pinnacle no-vig probability only."""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from src.models.calibration import clamp_probabilities


def model_a_probs(frame: pd.DataFrame, config: Dict[str, Any]) -> np.ndarray:
    cal = config["calibration"]
    return clamp_probabilities(
        frame["current_probability"].to_numpy(dtype=float),
        cal["clamp_min"],
        cal["clamp_max"],
    )

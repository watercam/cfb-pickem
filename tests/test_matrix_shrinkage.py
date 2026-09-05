import pandas as pd

from src.models.matrix_builder import (
    apply_production_inclusion,
    build_matrix,
    shrinkage_weight,
)
from src.settings import load_backtest_config


def test_shrinkage_weight_steps() -> None:
    config = load_backtest_config()
    assert shrinkage_weight(49, config) == 0.0
    assert shrinkage_weight(50, config) == 0.25
    assert shrinkage_weight(100, config) == 0.50
    assert shrinkage_weight(250, config) == 0.75
    assert shrinkage_weight(500, config) == 0.90


def test_cells_shrink_toward_zero_and_cap() -> None:
    config = load_backtest_config()
    rows = []
    for i in range(80):
        rows.append(
            {
                "season": 2021,
                "week": (i % 10) + 1,
                "include_in_model": True,
                "win": 1,
                "current_probability": 0.62,
                "spread_move": 2.0,
                "probability_band": "60-70%",
                "movement_bucket": "+1.5 to +3.0",
            }
        )
    frame = pd.DataFrame(rows)
    matrix = build_matrix(frame, config, bootstrap_iterations=50)
    cell = matrix.loc[
        (matrix["probability_band"] == "60-70%")
        & (matrix["movement_bucket"] == "+1.5 to +3.0")
    ].iloc[0]
    assert cell["sample_size"] == 80
    assert abs(cell["raw_adjustment"]) > abs(cell["shrunk_adjustment"])
    assert cell["shrunk_adjustment"] <= 0.03
    assert cell["shrunk_adjustment"] >= -0.03
    assert cell["raw_adjustment"] > 0
    assert cell["shrunk_adjustment"] == min(cell["raw_adjustment"] * 0.25, 0.03)


def test_uncertain_or_small_n_production_is_zero() -> None:
    config = load_backtest_config()
    rows = [
        {
            "season": 2021,
            "week": 1,
            "include_in_model": True,
            "win": 1,
            "current_probability": 0.62,
            "spread_move": 2.0,
            "probability_band": "60-70%",
            "movement_bucket": "+1.5 to +3.0",
        }
        for _ in range(10)
    ]
    matrix = build_matrix(pd.DataFrame(rows), config, bootstrap_iterations=20)
    matrix = apply_production_inclusion(
        matrix,
        cell_oos=pd.DataFrame(),
        model_b_beats_a=True,
        config=config,
    )
    cell = matrix.loc[
        (matrix["probability_band"] == "60-70%")
        & (matrix["movement_bucket"] == "+1.5 to +3.0")
    ].iloc[0]
    assert cell["sample_size"] == 10
    assert cell["shrunk_adjustment"] == 0.0
    assert cell["production_adjustment"] == 0.0

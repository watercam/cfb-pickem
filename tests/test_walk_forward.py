import pandas as pd

from src.backtest.walk_forward import walk_forward
from src.settings import load_backtest_config


def _row(season, game_id, p, move, win, week=1):
    return {
        "game_id": str(game_id),
        "season": season,
        "week": week,
        "include_in_model": True,
        "current_probability": p,
        "spread_move": move,
        "win": win,
        "probability_band": "60-70%",
        "movement_bucket": "+1.5 to +3.0",
    }


def test_walk_forward_uses_configured_seasons_not_random_split() -> None:
    rows = []
    game_id = 1
    for season in [2021, 2022, 2023, 2024, 2025]:
        for i in range(6):
            rows.append(_row(season, game_id, 0.62, 2.0, 1 if i % 3 else 0, week=i + 1))
            game_id += 1
    dataset = pd.DataFrame(rows)
    config = load_backtest_config()
    result = walk_forward(dataset, config, bootstrap_iterations=25)
    metrics = result["metrics"]
    assert set(metrics["fold_id"]) >= {"fold_1", "fold_2", "fold_3", "pooled_oos"}
    assert set(metrics["model"]) == {"A", "B"}
    fold1 = metrics.loc[metrics["fold_id"] == "fold_1"]
    assert (fold1["test_season"] == 2023).all()
    pooled = metrics.loc[metrics["fold_id"] == "pooled_oos"]
    assert len(pooled) == 2
    assert result["oos_predictions"]["season"].isin([2023, 2024, 2025]).all()
    assert not result["oos_predictions"]["season"].isin([2021, 2022]).any()

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from src.data.build_dataset import build_horizon_dataset
from src.features.market_movement import team_features_from_snapshots
from src.models.close_forecast import FEATURE_COLUMNS, fit_close_forecast
from src.settings import load_experiment_config


KICKOFF = datetime(2021, 9, 11, 19, 0, tzinfo=timezone.utc)


def _snap(hours_before: float, home_spread: float, home_ml: int, away_ml: int) -> dict:
    ts = KICKOFF - timedelta(hours=hours_before)
    return {
        "snapshot_request_ts": ts,
        "snapshot_ts": ts,
        "odds_event_id": "evt-1",
        "commence_time": KICKOFF,
        "home_team_odds": "Alpha State",
        "away_team_odds": "Beta Tech",
        "bookmaker": "pinnacle",
        "home_spread": home_spread,
        "away_spread": -home_spread,
        "home_spread_price": -110,
        "away_spread_price": -110,
        "home_moneyline": home_ml,
        "away_moneyline": away_ml,
        "sharp_available": True,
        "last_update": ts,
    }


def test_24h_features_ignore_injected_1h_prices() -> None:
    base = [_snap(72, -3.0, -140, 120), _snap(24, -5.0, -150, 130)]
    injected = base + [_snap(1, -20.0, -900, 600)]
    kwargs = dict(
        decision_ts=KICKOFF - timedelta(hours=24),
        reference_ts=KICKOFF - timedelta(hours=72),
        team="Alpha State",
        opponent="Beta Tech",
        home_team="Alpha State",
        away_team="Beta Tech",
    )
    a = team_features_from_snapshots(pd.DataFrame(base), **kwargs)
    b = team_features_from_snapshots(pd.DataFrame(injected), **kwargs)
    assert a["current_spread"] == b["current_spread"] == -5.0
    assert a["current_probability"] == b["current_probability"]
    assert a["spread_move"] == b["spread_move"]


def test_horizon_dataset_24h_clock_does_not_use_1h_line(tmp_path, monkeypatch) -> None:
    repo = __import__("pathlib").Path(__file__).resolve().parents[1]
    (tmp_path / "config").mkdir()
    import shutil

    shutil.copy(repo / "config" / "backtest.yaml", tmp_path / "config" / "backtest.yaml")
    shutil.copy(
        repo / "config" / "experiment_late_line.yaml",
        tmp_path / "config" / "experiment_late_line.yaml",
    )
    shutil.copy(repo / "config" / "team_aliases.yaml", tmp_path / "config" / "team_aliases.yaml")
    (tmp_path / "data" / "processed").mkdir(parents=True)
    (tmp_path / "data" / "outputs").mkdir(parents=True)
    monkeypatch.setenv("CFB_PICKEM_ROOT", str(tmp_path))

    games = pd.DataFrame(
        [
            {
                "game_id": "1",
                "season": 2021,
                "week": 1,
                "season_type": "regular",
                "game_date": KICKOFF.date(),
                "kickoff_timestamp": KICKOFF,
                "home_team_cfbd": "Alpha State",
                "away_team_cfbd": "Beta Tech",
                "home_team": None,
                "away_team": None,
                "home_classification": "fbs",
                "away_classification": "fbs",
                "neutral_site": False,
                "home_score": 31,
                "away_score": 17,
                "cancelled": False,
                "completed": True,
                "sharp_source": "pinnacle",
                "sharp_available": True,
                "exclude_from_model": False,
                "exclusion_reasons": "",
            }
        ]
    )
    snapshots = pd.DataFrame(
        [_snap(72, -3.0, -140, 120), _snap(24, -5.0, -150, 130), _snap(1, -20.0, -900, 600)]
    )
    dataset = build_horizon_dataset(games, snapshots, config=load_experiment_config("late_line"))
    clock24 = dataset.loc[dataset["decision_horizon_hours"] == 24]
    clock1 = dataset.loc[dataset["decision_horizon_hours"] == 1]
    home24 = clock24.loc[clock24["team"] == "Alpha State"].iloc[0]
    home1 = clock1.loc[clock1["team"] == "Alpha State"].iloc[0]
    assert home24["current_spread"] == -5.0
    assert home24["p_24"] == home24["current_probability"]
    assert home1["current_spread"] == -20.0
    assert home1["p_1h"] == home1["current_probability"]
    assert home24["p_1h"] == home1["current_probability"]
    assert pd.to_datetime(home24["current_timestamp"], utc=True) <= KICKOFF - timedelta(hours=24)


def test_close_forecast_features_are_24h_only() -> None:
    assert FEATURE_COLUMNS == ("p_24", "spread_move_72_24")
    assert "p_1h" not in FEATURE_COLUMNS
    assert "spread_move_24_1h" not in FEATURE_COLUMNS
    train = pd.DataFrame(
        {
            "p_24": [0.62] * 10,
            "spread_move_72_24": [1.5] * 10,
            "p_1h": [0.70] * 10,
        }
    )
    model = fit_close_forecast(train)
    assert model is not None
    # p_1h is the label only; design matrix is two columns.
    assert model.n_features_in_ == 2


def test_close_forecast_predict_handles_nonfinite_inputs() -> None:
    from src.models.close_forecast import predict_p_1h

    train = pd.DataFrame(
        {
            "p_24": [0.62] * 10,
            "spread_move_72_24": [1.5] * 10,
            "p_1h": [0.70] * 10,
        }
    )
    model = fit_close_forecast(train)
    frame = pd.DataFrame(
        {
            "p_24": [0.62, float("nan"), 0.55],
            "spread_move_72_24": [1.5, 0.0, float("inf")],
        }
    )
    config = {"calibration": {"clamp_min": 0.01, "clamp_max": 0.99}}
    pred = predict_p_1h(frame, model, config)
    assert len(pred) == 3
    assert np.isfinite(pred).all()
    assert ((pred >= 0.01) & (pred <= 0.99)).all()

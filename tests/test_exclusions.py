import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.data.build_dataset import build_dataset
from src.settings import load_backtest_config


def test_exclusion_codes_are_stored(tmp_path, monkeypatch) -> None:
    repo = Path(__file__).resolve().parents[1]
    (tmp_path / "config").mkdir()
    shutil.copy(repo / "config" / "backtest.yaml", tmp_path / "config" / "backtest.yaml")
    shutil.copy(repo / "config" / "team_aliases.yaml", tmp_path / "config" / "team_aliases.yaml")
    (tmp_path / "data" / "processed").mkdir(parents=True)
    (tmp_path / "data" / "outputs").mkdir(parents=True)
    monkeypatch.setenv("CFB_PICKEM_ROOT", str(tmp_path))

    kickoff = datetime(2021, 9, 11, 19, 0, tzinfo=timezone.utc)
    games = pd.DataFrame(
        [
            {
                "game_id": "1",
                "season": 2021,
                "week": 1,
                "season_type": "regular",
                "game_date": kickoff.date(),
                "kickoff_timestamp": kickoff,
                "home_team_cfbd": "Alpha State",
                "away_team_cfbd": "Beta Tech",
                "home_team": None,
                "away_team": None,
                "home_classification": "fbs",
                "away_classification": "fcs",
                "neutral_site": False,
                "home_score": 10,
                "away_score": 7,
                "cancelled": False,
                "completed": True,
                "sharp_source": "pinnacle",
                "sharp_available": False,
                "exclude_from_model": True,
                "exclusion_reasons": "NOT_FBS_VS_FBS",
            }
        ]
    )
    snapshots = pd.DataFrame(
        columns=[
            "snapshot_request_ts",
            "snapshot_ts",
            "odds_event_id",
            "commence_time",
            "home_team_odds",
            "away_team_odds",
            "bookmaker",
            "sharp_available",
            "home_moneyline",
            "away_moneyline",
            "home_spread",
            "away_spread",
            "home_spread_price",
            "away_spread_price",
            "last_update",
        ]
    )
    dataset = build_dataset(games, snapshots, config=load_backtest_config())
    assert len(dataset) == 2
    assert dataset["include_in_model"].sum() == 0
    assert dataset["exclusion_reasons"].str.contains("NOT_FBS_VS_FBS").all()

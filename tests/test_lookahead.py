from datetime import datetime, timedelta, timezone

import pandas as pd

from src.features.market_movement import (
    pick_snapshot_at_or_before,
    team_features_from_snapshots,
)


KICKOFF = datetime(2021, 9, 11, 19, 0, tzinfo=timezone.utc)
DECISION = KICKOFF - timedelta(hours=24)
REFERENCE = KICKOFF - timedelta(hours=72)


def _snap(hours_before: float, home_spread: float, home_ml: int, away_ml: int) -> dict:
    ts = KICKOFF - timedelta(hours=hours_before)
    return {
        "snapshot_ts": ts,
        "home_team_odds": "Alpha State",
        "away_team_odds": "Beta Tech",
        "home_spread": home_spread,
        "away_spread": -home_spread,
        "home_spread_price": -110,
        "away_spread_price": -110,
        "home_moneyline": home_ml,
        "away_moneyline": away_ml,
        "sharp_available": True,
    }


def _frame(rows):
    return pd.DataFrame(rows)


def test_selected_timestamps_are_not_after_targets() -> None:
    snaps = _frame(
        [
            _snap(80, -3.0, -140, 120),
            _snap(24, -5.0, -150, 130),
            _snap(1, -8.0, -180, 150),
        ]
    )
    features = team_features_from_snapshots(
        snaps,
        decision_ts=DECISION,
        reference_ts=REFERENCE,
        team="Alpha State",
        opponent="Beta Tech",
        home_team="Alpha State",
        away_team="Beta Tech",
    )
    assert features["current_timestamp"] <= DECISION
    assert features["reference_timestamp"] <= REFERENCE
    assert features["current_spread"] == -5.0
    assert features["spread_move"] == 2.0


def test_late_pinnacle_move_does_not_change_features() -> None:
    base = [
        _snap(80, -3.0, -140, 120),
        _snap(24, -5.0, -150, 130),
    ]
    injected = base + [_snap(1, -20.0, -900, 600)]
    kwargs = dict(
        decision_ts=DECISION,
        reference_ts=REFERENCE,
        team="Alpha State",
        opponent="Beta Tech",
        home_team="Alpha State",
        away_team="Beta Tech",
    )
    a = team_features_from_snapshots(_frame(base), **kwargs)
    b = team_features_from_snapshots(_frame(injected), **kwargs)
    assert a["current_spread"] == b["current_spread"]
    assert a["current_probability"] == b["current_probability"]
    assert a["spread_move"] == b["spread_move"]


def test_feature_builder_ignores_rows_after_decision() -> None:
    snaps = _frame(
        [
            _snap(24, -5.0, -150, 130),
            _snap(1, -9.0, -200, 170),
        ]
    )
    features = team_features_from_snapshots(
        snaps,
        decision_ts=DECISION,
        reference_ts=REFERENCE,
        team="Alpha State",
        opponent="Beta Tech",
        home_team="Alpha State",
        away_team="Beta Tech",
    )
    assert features["current_spread"] == -5.0
    assert features["current_timestamp"] <= DECISION


def test_feature_builder_does_not_accept_results() -> None:
    import inspect

    params = inspect.signature(team_features_from_snapshots).parameters
    assert "win" not in params
    assert "final_team_score" not in params


def test_one_hour_clock_ignores_post_kickoff() -> None:
    snaps = _frame(
        [
            _snap(24, -5.0, -150, 130),
            _snap(1, -7.0, -170, 140),
            {
                **_snap(0, -20.0, -900, 600),
                "snapshot_ts": KICKOFF + timedelta(minutes=5),
            },
        ]
    )
    decision_1h = KICKOFF - timedelta(hours=1)
    features = team_features_from_snapshots(
        snaps,
        decision_ts=decision_1h,
        reference_ts=DECISION,
        team="Alpha State",
        opponent="Beta Tech",
        home_team="Alpha State",
        away_team="Beta Tech",
        current_earliest_ts=DECISION,
    )
    assert features["current_timestamp"] <= decision_1h
    assert features["current_spread"] == -7.0
    assert features["current_spread"] != -20.0


def test_one_hour_clock_does_not_substitute_24h_line() -> None:
    snaps = _frame([_snap(24, -5.0, -150, 130)])
    features = team_features_from_snapshots(
        snaps,
        decision_ts=KICKOFF - timedelta(hours=1),
        reference_ts=DECISION,
        team="Alpha State",
        opponent="Beta Tech",
        home_team="Alpha State",
        away_team="Beta Tech",
        current_earliest_ts=DECISION,
    )
    assert features["current_timestamp"] is None
    assert features["current_spread"] is None


def test_snapshot_picker_never_takes_later_candidate() -> None:
    target = DECISION
    earlier = target - timedelta(minutes=10)
    later = target + timedelta(minutes=1)
    chosen = pick_snapshot_at_or_before([earlier, later], target)
    assert chosen == earlier
    assert chosen != later

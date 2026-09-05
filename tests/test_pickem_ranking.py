from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.features.market_movement import spread_move
from src.pickem.calibration import MovementCalibrator
from src.pickem.odds import snapshots_from_payloads
from src.pickem.ranking import recommend_slate, score_game
from src.pickem.slate import load_fixture
from src.pickem.types import UNMAPPED_TEAM, SlateGame
from src.settings import project_root

FIXTURE = project_root() / "tests" / "fixtures" / "pickem_week.json"
NOW = datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc)


def _slate():
    games, payloads, now, week = load_fixture(FIXTURE)
    snaps = snapshots_from_payloads(payloads)
    return games, snaps, now, week


def test_spread_move_sign_favorite_lengthens() -> None:
    assert spread_move(-3, -5) == 2
    games, snaps, now, _week = _slate()
    game = next(g for g in games if g.game_id == "game-05")
    rec = score_game(
        game,
        snaps,
        now=now,
        calibrator=MovementCalibrator("none"),
        reference_hours=72,
    )
    # Beta Tech home, -3 -> -5 is +2 for the home favorite.
    assert rec.pick == "Beta Tech"
    assert rec.spread_move == 2.0


def test_confidence_is_permutation_of_ten_to_one() -> None:
    games, snaps, now, week = _slate()
    result = recommend_slate(
        games,
        snaps,
        now=now,
        calibrator=MovementCalibrator("handwritten"),
        reference_hours=72,
        week=week,
    )
    confs = [g.confidence for g in result.games]
    assert sorted(confs) == list(range(1, 11))
    picks = [g.pick for g in result.games]
    assert None not in picks
    assert len(picks) == 10
    assert all(g.pick != g.opponent for g in result.games)


def test_none_ranks_by_p_current_only() -> None:
    games, snaps, now, week = _slate()
    none = recommend_slate(
        games,
        snaps,
        now=now,
        calibrator=MovementCalibrator("none"),
        reference_hours=72,
        week=week,
    )
    assert all(g.adj == 0.0 for g in none.games)
    ordered = sorted(none.games, key=lambda g: g.confidence or 0, reverse=True)
    p_values = [g.p_current for g in ordered]
    assert p_values == sorted(p_values, reverse=True)


def test_matrix_zero_adj_keeps_none_order(tmp_path: Path) -> None:
    games, snaps, now, week = _slate()
    csv_path = tmp_path / "zeros.csv"
    pd.DataFrame(
        [
            {
                "probability_min": 0.50,
                "probability_max": 1.00,
                "movement_min": -999.0,
                "movement_max": 999.0,
                "production_adjustment": 0.0,
            }
        ]
    ).to_csv(csv_path, index=False)
    none = recommend_slate(
        games,
        snaps,
        now=now,
        calibrator=MovementCalibrator("none"),
        reference_hours=72,
        week=week,
    )
    csv = recommend_slate(
        games,
        snaps,
        now=now,
        calibrator=MovementCalibrator("matrix_csv", matrix_path=csv_path),
        reference_hours=72,
        week=week,
    )
    assert [g.pick for g in none.games] == [g.pick for g in csv.games]
    assert [g.confidence for g in none.games] == [g.confidence for g in csv.games]


def test_unmapped_espn_name_is_not_fuzzy() -> None:
    games, snaps, now, _week = _slate()
    game = SlateGame(
        game_id="unmapped",
        away_espn="Miam",
        home_espn="USC",
        kickoff=games[0].kickoff,
    )
    rec = score_game(
        game,
        snaps,
        now=now,
        calibrator=MovementCalibrator("none"),
        reference_hours=72,
    )
    assert rec.pick is None
    assert UNMAPPED_TEAM in rec.flags


def test_lookahead_snapshot_ignored() -> None:
    games, snaps, now, _week = _slate()
    rec = score_game(
        games[0],
        snaps,
        now=now,
        calibrator=MovementCalibrator("none"),
        reference_hours=72,
    )
    assert rec.p_current is not None
    assert rec.p_current < 0.9


def test_missing_reference_uses_zero_move() -> None:
    games, snaps, now, week = _slate()
    t72 = snaps["snapshot_ts"].min()
    current_only = snaps.loc[snaps["snapshot_ts"] > t72].copy()
    recs = recommend_slate(
        games,
        current_only,
        now=now,
        calibrator=MovementCalibrator("handwritten"),
        reference_hours=72,
        week=week,
    )
    assert all("REFERENCE_MISSING" in g.flags for g in recs.games)
    assert all(g.spread_move == 0.0 for g in recs.games)
    assert sorted(g.confidence for g in recs.games) == list(range(1, 11))

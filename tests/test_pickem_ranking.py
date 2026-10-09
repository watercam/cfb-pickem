from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src.features.market_movement import no_vig_probability, spread_move
from src.pickem.calibration import MovementCalibrator
from src.pickem.odds import snapshots_from_payloads
from src.pickem.ranking import recommend_slate, score_game
from src.pickem.slate import load_fixture
from src.pickem.types import ODDS_SIDE_UNMATCHED, PINNACLE_MISSING, UNMAPPED_TEAM, SlateGame
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


def _neutral_snapshots(
    *,
    event_id: str,
    kickoff: datetime,
    book_home: str,
    book_away: str,
    home_ml: int,
    away_ml: int,
    spread: float,
) -> pd.DataFrame:
    t72 = kickoff - timedelta(hours=72)
    current = kickoff - timedelta(hours=24)

    def payload(ts: datetime, ml_home: int, ml_away: int, line: float) -> dict:
        return {
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "_meta": {"requested_date": ts.strftime("%Y-%m-%dT%H:%M:%SZ")},
            "data": [
                {
                    "id": event_id,
                    "sport_key": "americanfootball_ncaaf",
                    "commence_time": kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "home_team": book_home,
                    "away_team": book_away,
                    "bookmakers": [
                        {
                            "key": "pinnacle",
                            "title": "Pinnacle",
                            "last_update": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "markets": [
                                {
                                    "key": "h2h",
                                    "outcomes": [
                                        {"name": book_home, "price": ml_home},
                                        {"name": book_away, "price": ml_away},
                                    ],
                                },
                                {
                                    "key": "spreads",
                                    "outcomes": [
                                        {"name": book_home, "price": -110, "point": line},
                                        {"name": book_away, "price": -110, "point": -line},
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
        }

    return snapshots_from_payloads(
        [
            payload(t72, home_ml + 15, away_ml - 10, spread + 1.0),
            payload(current, home_ml, away_ml, spread),
        ]
    )


def test_neutral_site_reversed_book_keeps_favorite_probability() -> None:
    """ASU @ Kansas in London: ESPN lists Kansas as home; Pinnacle lists ASU as home favorite."""
    kickoff = datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)
    asu_ml = -250
    kansas_ml = 210
    snaps = _neutral_snapshots(
        event_id="asu-kansas-london",
        kickoff=kickoff,
        book_home="Arizona State Sun Devils",
        book_away="Kansas Jayhawks",
        home_ml=asu_ml,
        away_ml=kansas_ml,
        spread=-6.5,
    )
    game = SlateGame(
        game_id="asu-at-kansas",
        away_espn="ASU",
        home_espn="Kansas",
        kickoff=kickoff,
        public_away_pct=28.0,
        public_home_pct=72.0,
        week=3,
    )
    rec = score_game(
        game,
        snaps,
        now=now,
        calibrator=MovementCalibrator("none"),
        reference_hours=72,
    )
    asu_p = no_vig_probability(asu_ml, kansas_ml)
    kansas_p = no_vig_probability(kansas_ml, asu_ml)
    assert rec.pick == "ASU"
    assert rec.opponent == "Kansas"
    assert rec.is_home_pick is False
    assert rec.p_current == asu_p
    assert rec.p_current > kansas_p
    assert rec.public_pick_pct == 28.0
    assert rec.pinnacle_spread == -6.5
    assert ODDS_SIDE_UNMATCHED not in rec.flags


def test_cotton_bowl_reversed_book_keeps_texas_favorite() -> None:
    kickoff = datetime(2026, 10, 10, 19, 0, tzinfo=timezone.utc)
    now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    texas_ml = -185
    oklahoma_ml = 160
    snaps = _neutral_snapshots(
        event_id="texas-oklahoma-cotton",
        kickoff=kickoff,
        book_home="Oklahoma Sooners",
        book_away="Texas Longhorns",
        home_ml=oklahoma_ml,
        away_ml=texas_ml,
        spread=4.0,
    )
    game = SlateGame(
        game_id="red-river",
        away_espn="Oklahoma",
        home_espn="Texas",
        kickoff=kickoff,
        public_away_pct=41.0,
        public_home_pct=59.0,
        week=7,
    )
    rec = score_game(
        game,
        snaps,
        now=now,
        calibrator=MovementCalibrator("none"),
        reference_hours=72,
    )
    assert rec.pick == "Texas"
    assert rec.is_home_pick is True
    assert rec.p_current == no_vig_probability(texas_ml, oklahoma_ml)
    assert rec.p_current > no_vig_probability(oklahoma_ml, texas_ml)
    assert rec.public_pick_pct == 59.0
    assert rec.pinnacle_spread == -4.0


def test_ndsu_at_unlv_matches_both_book_slot_orders() -> None:
    kickoff = datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)
    now = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)
    ndsu_ml = 150
    unlv_ml = -170
    game = SlateGame(
        game_id="NDSU @ UNLV",
        away_espn="North Dakota State",
        home_espn="UNLV",
        kickoff=kickoff,
        public_away_pct=34.0,
        public_home_pct=66.0,
        week=6,
    )
    for book_home, book_away, home_ml, away_ml, spread in (
        ("UNLV Rebels", "North Dakota State Bison", unlv_ml, ndsu_ml, -3.5),
        ("North Dakota State Bison", "UNLV Rebels", ndsu_ml, unlv_ml, 3.5),
    ):
        snaps = _neutral_snapshots(
            event_id="ndsu-at-unlv",
            kickoff=kickoff,
            book_home=book_home,
            book_away=book_away,
            home_ml=home_ml,
            away_ml=away_ml,
            spread=spread,
        )
        rec = score_game(
            game,
            snaps,
            now=now,
            calibrator=MovementCalibrator("none"),
            reference_hours=72,
        )
        assert rec.pick is not None
        assert UNMAPPED_TEAM not in rec.flags
        assert ODDS_SIDE_UNMATCHED not in rec.flags
        assert PINNACLE_MISSING not in rec.flags
        assert rec.p_current == no_vig_probability(unlv_ml, ndsu_ml)


def test_unmatched_odds_side_is_flagged_not_guessed() -> None:
    kickoff = datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)
    snaps = _neutral_snapshots(
        event_id="wrong-kansas",
        kickoff=kickoff,
        book_home="Kansas State Wildcats",
        book_away="Arizona State Sun Devils",
        home_ml=-150,
        away_ml=130,
        spread=-3.0,
    )
    game = SlateGame(
        game_id="kansas-vs-asu",
        away_espn="Arizona State",
        home_espn="Kansas",
        kickoff=kickoff,
        public_away_pct=55.0,
        public_home_pct=45.0,
    )
    rec = score_game(
        game,
        snaps,
        now=now,
        calibrator=MovementCalibrator("none"),
        reference_hours=72,
    )
    assert rec.pick is None
    assert rec.p_final is None
    assert rec.public_pick_pct is None
    assert PINNACLE_MISSING in rec.flags or ODDS_SIDE_UNMATCHED in rec.flags
    assert rec.p_current is None

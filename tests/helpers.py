"""Synthetic CFBD + Pinnacle cache used by unit tests and cache_only acceptance."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.data.fetch_odds_history import floor_to_grid, snapshot_filename

SEASONS = [2021, 2022, 2023, 2024, 2025]
KICKOFFS = {
    2021: datetime(2021, 9, 11, 19, 0, tzinfo=timezone.utc),
    2022: datetime(2022, 9, 10, 19, 0, tzinfo=timezone.utc),
    2023: datetime(2023, 9, 9, 19, 0, tzinfo=timezone.utc),
    2024: datetime(2024, 9, 7, 19, 0, tzinfo=timezone.utc),
    2025: datetime(2025, 9, 6, 19, 0, tzinfo=timezone.utc),
}


def write_mini_raw_cache(root: Path) -> None:
    cfbd = root / "data" / "raw" / "cfbd"
    snaps = root / "data" / "raw" / "odds_api" / "snapshots"
    cfbd.mkdir(parents=True, exist_ok=True)
    snaps.mkdir(parents=True, exist_ok=True)
    games_by_season: Dict[int, List[Dict[str, Any]]] = {s: [] for s in SEASONS}
    snapshot_events: Dict[datetime, List[Dict[str, Any]]] = {}
    fbs_teams = ["Alpha State", "Beta Tech", "Gamma U", "Delta College", "FCS Place"]

    game_id = 900000
    for season in SEASONS:
        kickoff = KICKOFFS[season]
        games_by_season[season].extend(
            [
                _cfbd_game(game_id, season, 1, "Alpha State", "Beta Tech", kickoff, 31, 17),
                _cfbd_game(game_id + 1, season, 1, "Gamma U", "Delta College", kickoff, 24, 21),
                _cfbd_game(
                    game_id + 2,
                    season,
                    2,
                    "Alpha State",
                    "FCS Place",
                    kickoff + timedelta(days=7),
                    42,
                    10,
                    away_class="fcs",
                ),
            ]
        )
        _add_pinnacle_event(
            snapshot_events,
            kickoff,
            event_id=f"evt-{season}-1",
            home="Alpha State",
            away="Beta Tech",
            ref_spread=-3.0,
            cur_spread=-5.0,
            home_ml=-150,
            away_ml=130,
            late_spread=-20.0,
            late_home_ml=-500,
            late_away_ml=350,
        )
        _add_pinnacle_event(
            snapshot_events,
            kickoff,
            event_id=f"evt-{season}-2",
            home="Gamma U",
            away="Delta College",
            ref_spread=-7.0,
            cur_spread=-4.0,
            home_ml=-200,
            away_ml=170,
            late_spread=-6.0,
            late_home_ml=-220,
            late_away_ml=180,
        )
        game_id += 10

    for season, games in games_by_season.items():
        (cfbd / f"games_{season}_regular.json").write_text(json.dumps(games, indent=2, default=str))
        (cfbd / f"games_{season}_postseason.json").write_text("[]")
        (cfbd / f"teams_fbs_{season}.json").write_text(
            json.dumps([{"school": name} for name in fbs_teams if name != "FCS Place"])
        )

    cancelled = _cfbd_game(
        800001,
        2021,
        3,
        "Alpha State",
        "Beta Tech",
        KICKOFFS[2021] + timedelta(days=14),
        None,
        None,
        cancelled=True,
        completed=False,
    )
    games_2021 = json.loads((cfbd / "games_2021_regular.json").read_text())
    games_2021.append(cancelled)
    (cfbd / "games_2021_regular.json").write_text(json.dumps(games_2021, indent=2, default=str))

    for ts, events in snapshot_events.items():
        payload = {
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "previous_timestamp": None,
            "next_timestamp": None,
            "_meta": {"requested_date": ts.strftime("%Y-%m-%dT%H:%M:%SZ")},
            "data": events,
        }
        (snaps / snapshot_filename(ts)).write_text(json.dumps(payload))


def _cfbd_game(
    game_id: int,
    season: int,
    week: int,
    home: str,
    away: str,
    kickoff: datetime,
    home_points: Optional[int],
    away_points: Optional[int],
    *,
    away_class: str = "fbs",
    cancelled: bool = False,
    completed: bool = True,
) -> Dict[str, Any]:
    return {
        "id": game_id,
        "season": season,
        "week": week,
        "seasonType": "regular",
        "startDate": kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "completed": completed and home_points is not None,
        "cancelled": cancelled,
        "neutralSite": False,
        "homeTeam": home,
        "awayTeam": away,
        "homeClassification": "fbs",
        "awayClassification": away_class,
        "homePoints": home_points,
        "awayPoints": away_points,
    }


def _add_pinnacle_event(
    snapshot_events: Dict[datetime, List[Dict[str, Any]]],
    kickoff: datetime,
    *,
    event_id: str,
    home: str,
    away: str,
    ref_spread: float,
    cur_spread: float,
    home_ml: int,
    away_ml: int,
    late_spread: Optional[float] = None,
    late_home_ml: Optional[int] = None,
    late_away_ml: Optional[int] = None,
) -> None:
    t72 = floor_to_grid(kickoff - timedelta(hours=72), 5)
    t24 = floor_to_grid(kickoff - timedelta(hours=24), 5)
    t1 = floor_to_grid(kickoff - timedelta(hours=1), 5)
    snapshot_events.setdefault(t72, []).append(
        _odds_event(event_id, kickoff, home, away, ref_spread, home_ml + 20, away_ml - 10)
    )
    snapshot_events.setdefault(t24, []).append(
        _odds_event(event_id, kickoff, home, away, cur_spread, home_ml, away_ml)
    )
    snapshot_events.setdefault(t1, []).append(
        _odds_event(
            event_id,
            kickoff,
            home,
            away,
            cur_spread if late_spread is None else late_spread,
            home_ml if late_home_ml is None else late_home_ml,
            away_ml if late_away_ml is None else late_away_ml,
        )
    )


def _odds_event(
    event_id: str,
    kickoff: datetime,
    home: str,
    away: str,
    spread: float,
    home_ml: int,
    away_ml: int,
) -> Dict[str, Any]:
    return {
        "id": event_id,
        "sport_key": "americanfootball_ncaaf",
        "commence_time": kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "home_team": home,
        "away_team": away,
        "bookmakers": [
            {
                "key": "pinnacle",
                "title": "Pinnacle",
                "last_update": (kickoff - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": home, "price": home_ml},
                            {"name": away, "price": away_ml},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": home, "price": -110, "point": spread},
                            {"name": away, "price": -110, "point": -spread},
                        ],
                    },
                ],
            }
        ],
    }

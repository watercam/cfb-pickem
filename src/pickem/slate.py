"""Load the weekly ESPN slate, or a local fixture."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd
import requests

from src.pickem.types import SlateGame

CONFIDENCE_SCORING_FORMAT_ID = 1
PICKEM_USER_AGENT = "cfb-pickem-refresh/1.0"


def load_fixture(path: Path) -> Tuple[List[SlateGame], List[Dict[str, Any]], datetime, Optional[int]]:
    payload = json.loads(Path(path).read_text())
    now = _parse_ts(payload.get("now")) or datetime.now(timezone.utc)
    week = payload.get("week")
    games = [_fixture_game(item, week) for item in payload.get("games") or []]
    odds_payloads = list(payload.get("odds_payloads") or [])
    return games, odds_payloads, now, week


def fetch_espn_slate(url: str, *, timeout: int = 30) -> List[SlateGame]:
    response = requests.get(
        url,
        headers={
            "Accept": "application/json, text/plain, */*",
            "User-Agent": PICKEM_USER_AGENT,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "ESPN slate URL did not return JSON. Pass --fixture PATH."
        ) from exc
    games = parse_espn_payload(payload)
    if not games:
        raise RuntimeError("ESPN slate JSON contained no games. Pass --fixture PATH.")
    return games


def parse_espn_payload(payload: Any) -> List[SlateGame]:
    gambit = parse_gambit_payload(payload)
    if gambit:
        return gambit
    if isinstance(payload, Mapping) and payload.get("games"):
        week = payload.get("week")
        return [_flexible_game(item, week, index) for index, item in enumerate(payload["games"])]
    candidates = _find_game_list(payload)
    games = []
    for index, item in enumerate(candidates):
        parsed = _flexible_game(item, None, index)
        games.append(parsed)
    return games


def parse_gambit_payload(payload: Any) -> List[SlateGame]:
    if isinstance(payload, list):
        propositions = [item for item in payload if isinstance(item, Mapping)]
        period_id = None
        format_id = CONFIDENCE_SCORING_FORMAT_ID
    elif isinstance(payload, Mapping) and isinstance(payload.get("propositions"), list):
        propositions = [item for item in payload["propositions"] if isinstance(item, Mapping)]
        period = payload.get("currentScoringPeriod") or {}
        period_id = period.get("id") if isinstance(period, Mapping) else None
        defaults = payload.get("defaultGroupSettings") or {}
        format_id = (
            defaults.get("scoringFormatId")
            if isinstance(defaults, Mapping)
            else CONFIDENCE_SCORING_FORMAT_ID
        ) or CONFIDENCE_SCORING_FORMAT_ID
    else:
        return []
    games: List[SlateGame] = []
    for index, item in enumerate(propositions):
        parsed = _gambit_game(item, period_id=period_id, format_id=int(format_id), index=index)
        if parsed is not None:
            games.append(parsed)
    return games


def _gambit_game(
    item: Mapping[str, Any],
    *,
    period_id: Optional[int],
    format_id: int,
    index: int,
) -> Optional[SlateGame]:
    formats = item.get("scoringFormatIds") or []
    if formats and format_id not in formats:
        return None
    away = _gambit_outcome(item, "AWAY")
    home = _gambit_outcome(item, "HOME")
    if away is None or home is None:
        return None
    kickoff = _parse_ts(item.get("date") or item.get("lockDate"))
    if kickoff is None:
        kickoff = datetime.now(timezone.utc)
    week = item.get("scoringPeriodId", period_id)
    name = item.get("name")
    game_id = str(name or item.get("id") or f"espn-{index}")
    return SlateGame(
        game_id=game_id,
        away_espn=str(away["name"]),
        home_espn=str(home["name"]),
        kickoff=kickoff,
        public_away_pct=_gambit_public_pct(away, format_id),
        public_home_pct=_gambit_public_pct(home, format_id),
        week=week,
    )


def _gambit_outcome(item: Mapping[str, Any], side: str) -> Optional[Mapping[str, Any]]:
    for outcome in item.get("possibleOutcomes") or []:
        if isinstance(outcome, Mapping) and str(outcome.get("subType") or "").upper() == side:
            return outcome
    return None


def _gambit_public_pct(outcome: Mapping[str, Any], format_id: int) -> Optional[float]:
    for counter in outcome.get("choiceCounters") or []:
        if not isinstance(counter, Mapping):
            continue
        if counter.get("scoringFormatId") != format_id:
            continue
        raw = counter.get("percentage")
        if raw is None:
            return None
        value = float(raw)
        if 0.0 <= value <= 1.0:
            return value * 100.0
        return value
    return None


def _fixture_game(item: Mapping[str, Any], week: Optional[int]) -> SlateGame:
    public = item.get("public_pct") or {}
    kickoff = _parse_ts(item["kickoff"])
    if kickoff is None:
        raise ValueError(f"Game {item.get('game_id')} is missing kickoff")
    return SlateGame(
        game_id=str(item["game_id"]),
        away_espn=str(item["away_team"]),
        home_espn=str(item["home_team"]),
        kickoff=kickoff,
        public_away_pct=_opt_float(public.get("away")),
        public_home_pct=_opt_float(public.get("home")),
        week=item.get("week", week),
    )


def _flexible_game(item: Mapping[str, Any], week: Optional[int], index: int) -> SlateGame:
    away = _team_name(item, "away")
    home = _team_name(item, "home")
    kickoff = _parse_ts(
        item.get("kickoff")
        or item.get("startDate")
        or item.get("start_date")
        or item.get("commence_time")
    )
    if kickoff is None:
        kickoff = datetime.now(timezone.utc)
    game_id = str(item.get("game_id") or item.get("id") or f"espn-{index}")
    return SlateGame(
        game_id=game_id,
        away_espn=away,
        home_espn=home,
        kickoff=kickoff,
        public_away_pct=_opt_float(
            item.get("awayPercent") or item.get("away_public_pct") or (item.get("public_pct") or {}).get("away")
        ),
        public_home_pct=_opt_float(
            item.get("homePercent") or item.get("home_public_pct") or (item.get("public_pct") or {}).get("home")
        ),
        week=item.get("week", week),
    )


def _team_name(item: Mapping[str, Any], side: str) -> str:
    key = f"{side}_team"
    if key in item and not isinstance(item[key], Mapping):
        return str(item[key])
    nested = item.get(f"{side}Team") or item.get(key) or {}
    if isinstance(nested, Mapping):
        return str(nested.get("name") or nested.get("abbreviation") or nested.get("displayName") or "")
    espn_key = f"{side}_espn"
    if espn_key in item:
        return str(item[espn_key])
    return str(nested) if nested else ""


def _find_game_list(payload: Any) -> Sequence[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("matchups", "picks", "events", "schedule"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    kwargs: Dict[str, Any] = {"utc": True}
    if isinstance(value, (int, float)):
        if value > 10**11:
            value = value / 1000.0
        kwargs["unit"] = "s"
    ts = pd.to_datetime(value, **kwargs)
    if pd.isna(ts):
        return None
    return ts.to_pydatetime().astimezone(timezone.utc)


def _opt_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)

"""Pinnacle current and T-72 snapshots for weekly Pick'em."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd
import requests

from src.data.fetch_odds_history import (
    BOOKMAKER,
    ODDS_HOST,
    _strip_api_key,
    floor_to_grid,
    parse_snapshot_payload,
)
from src.data.team_mapping import canonicalize, load_aliases
from src.features.market_movement import team_features_from_snapshots
from src.pickem.types import (
    NO_CURRENT_ML,
    PINNACLE_MISSING,
    REFERENCE_MISSING,
    UNMAPPED_TEAM,
    SlateGame,
)

LIVE_ODDS_PATH = "/v4/sports/{sport}/odds"
HISTORICAL_PATH = "/v4/historical/sports/{sport}/odds"


def snapshots_from_payloads(payloads: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for payload in payloads:
        rows.extend(parse_snapshot_payload(dict(payload)))
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    for col in ("snapshot_request_ts", "snapshot_ts", "commence_time", "last_update"):
        if col in frame.columns:
            frame[col] = pd.to_datetime(frame[col], utc=True)
    return frame


def fetch_pinnacle_snapshots(
    games: Sequence[SlateGame],
    *,
    now: datetime,
    config: Mapping[str, Any],
    api_key: str,
) -> pd.DataFrame:
    if config["odds_api"].get("allow_book_fallback"):
        raise ValueError("allow_book_fallback must be false; Pinnacle only")
    payloads = [fetch_current_payload(config, api_key, now)]
    for ts in unique_reference_timestamps(games, config):
        payloads.append(fetch_historical_payload(ts, config, api_key))
    return snapshots_from_payloads(payloads)


def fetch_current_payload(
    config: Mapping[str, Any],
    api_key: str,
    now: datetime,
) -> Dict[str, Any]:
    odds_cfg = config["odds_api"]
    params = _odds_params(odds_cfg, api_key)
    url = ODDS_HOST + LIVE_ODDS_PATH.format(sport=odds_cfg["sport"])
    events = _odds_get_json(url, params)
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"timestamp": stamp, "data": events, "_meta": {"requested_date": stamp}}


def fetch_historical_payload(
    request_ts: datetime,
    config: Mapping[str, Any],
    api_key: str,
) -> Dict[str, Any]:
    odds_cfg = config["odds_api"]
    date_iso = request_ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = _odds_params(odds_cfg, api_key)
    params["date"] = date_iso
    url = ODDS_HOST + HISTORICAL_PATH.format(sport=odds_cfg["sport"])
    payload = _odds_get_json(url, params)
    if isinstance(payload, list):
        payload = {"timestamp": date_iso, "data": payload}
    payload["_meta"] = {"requested_date": date_iso}
    return payload


def unique_reference_timestamps(
    games: Sequence[SlateGame],
    config: Mapping[str, Any],
) -> List[datetime]:
    hours = int(config["horizons"]["reference_hours"])
    grid = int(config["odds_api"]["snapshot_grid_minutes"])
    unique = {
        floor_to_grid(game.kickoff - timedelta(hours=hours), grid)
        for game in games
    }
    return sorted(unique)


def _odds_get_json(url: str, params: Mapping[str, str]) -> Any:
    try:
        response = requests.get(url, params=dict(params), timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        shown = url
        response = getattr(exc, "response", None)
        if response is not None and getattr(response, "url", None):
            shown = _strip_api_key(response.url)
        status = getattr(response, "status_code", None)
        raise RuntimeError(f"Odds API request failed ({status}) {shown}") from None


def _odds_params(odds_cfg: Mapping[str, Any], api_key: str) -> Dict[str, str]:
    book = odds_cfg["preferred_bookmaker"]
    if str(book).lower() != BOOKMAKER:
        raise ValueError("preferred_bookmaker must be pinnacle")
    return {
        "apiKey": api_key,
        "regions": ",".join(odds_cfg["regions"]),
        "markets": ",".join(odds_cfg["markets"]),
        "oddsFormat": odds_cfg.get("odds_format", "american"),
        "bookmakers": book,
    }


def resolve_espn_pair(
    game: SlateGame,
    aliases=None,
) -> Tuple[Optional[str], Optional[str], List[str]]:
    alias_rows = aliases if aliases is not None else load_aliases()
    home = canonicalize(game.home_espn, "espn", aliases=alias_rows)
    away = canonicalize(game.away_espn, "espn", aliases=alias_rows)
    flags: List[str] = []
    if home is None or away is None:
        flags.append(UNMAPPED_TEAM)
    return home, away, flags


def match_event_snapshots(
    snapshots: pd.DataFrame,
    game: SlateGame,
    *,
    home_canonical: Optional[str],
    away_canonical: Optional[str],
    aliases=None,
) -> pd.DataFrame:
    if snapshots is None or snapshots.empty:
        return pd.DataFrame()
    alias_rows = aliases if aliases is not None else load_aliases()
    wanted = None
    if home_canonical and away_canonical:
        wanted = {home_canonical, away_canonical}
    matched_idx = []
    for idx, row in snapshots.iterrows():
        odds_home = canonicalize(row.get("home_team_odds"), "odds", aliases=alias_rows)
        odds_away = canonicalize(row.get("away_team_odds"), "odds", aliases=alias_rows)
        if wanted and odds_home and odds_away and {odds_home, odds_away} == wanted:
            matched_idx.append(idx)
            continue
        raw_home = str(row.get("home_team_odds") or "")
        raw_away = str(row.get("away_team_odds") or "")
        espn_pair = {game.home_espn, game.away_espn}
        if espn_pair == {raw_home, raw_away}:
            matched_idx.append(idx)
    if not matched_idx:
        return pd.DataFrame()
    return snapshots.loc[matched_idx].copy()


def features_for_side(
    event_snaps: pd.DataFrame,
    *,
    team: str,
    opponent: str,
    home_team: str,
    away_team: str,
    now: datetime,
    kickoff: datetime,
    reference_hours: int,
) -> Dict[str, Any]:
    decision = min(now, kickoff)
    reference = kickoff - timedelta(hours=reference_hours)
    if reference > decision:
        reference = decision
    return team_features_from_snapshots(
        event_snaps,
        decision_ts=decision,
        reference_ts=reference,
        team=team,
        opponent=opponent,
        home_team=home_team,
        away_team=away_team,
    )


def current_event_home_away(event_snaps: pd.DataFrame, now: datetime, kickoff: datetime) -> Tuple[str, str]:
    decision = min(now, kickoff)
    usable = event_snaps.loc[pd.to_datetime(event_snaps["snapshot_ts"], utc=True) <= pd.Timestamp(decision)]
    if usable.empty:
        row = event_snaps.iloc[-1]
    else:
        row = usable.sort_values("snapshot_ts").iloc[-1]
    return str(row["home_team_odds"]), str(row["away_team_odds"])


def missing_current_flags(features: Mapping[str, Any], event_snaps: pd.DataFrame) -> List[str]:
    flags: List[str] = []
    if event_snaps.empty:
        flags.append(PINNACLE_MISSING)
        return flags
    if not bool(event_snaps["sharp_available"].fillna(False).any()) and features.get("current_probability") is None:
        flags.append(PINNACLE_MISSING)
        return flags
    if features.get("current_probability") is None:
        flags.append(NO_CURRENT_ML)
    if features.get("reference_timestamp") is None or features.get("spread_move") is None:
        if NO_CURRENT_ML not in flags and PINNACLE_MISSING not in flags:
            flags.append(REFERENCE_MISSING)
    return flags

"""Fetch final scores and game metadata from CollegeFootballData."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import pandas as pd
import requests

from src.data.team_mapping import build_alias_indexes, load_aliases
from src.settings import get_api_keys, load_backtest_config, resolve_paths

EXCL_NOT_FBS = "NOT_FBS_VS_FBS"
EXCL_CANCELLED = "CANCELLED"
EXCL_NO_FINAL = "NO_FINAL_RESULT"
EXCL_TEAM_UNMAPPED = "TEAM_UNMAPPED"


def fetch_results(
    *,
    mode: str = "cache_only",
    config: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    cfg = config or load_backtest_config()
    paths = resolve_paths(cfg)
    raw_dir = paths["raw_cfbd"]
    raw_dir.mkdir(parents=True, exist_ok=True)
    seasons = list(cfg["mvp"]["seasons"])
    if cfg["mvp"].get("include_2020"):
        if 2020 not in seasons:
            seasons = [2020, *seasons]
    else:
        seasons = [s for s in seasons if s != 2020]

    season_types = list(cfg["cfbd"]["season_types"])
    payload_by_file: Dict[Path, Any] = {}
    missing: List[Path] = []
    for season in seasons:
        teams_path = raw_dir / f"teams_fbs_{season}.json"
        if teams_path.exists():
            payload_by_file[teams_path] = _read_json(teams_path)
        else:
            missing.append(teams_path)
        for season_type in season_types:
            games_path = raw_dir / f"games_{season}_{season_type}.json"
            if games_path.exists():
                payload_by_file[games_path] = _read_json(games_path)
            else:
                missing.append(games_path)

    if missing:
        if mode == "cache_only":
            names = ", ".join(path.name for path in missing[:8])
            extra = "" if len(missing) <= 8 else f" (+{len(missing) - 8} more)"
            raise FileNotFoundError(
                f"CFBD cache missing {len(missing)} file(s) in {raw_dir}: {names}{extra}. "
                "Re-run with --mode fetch_missing if CFBD_API_KEY is set."
            )
        keys = get_api_keys()
        if not keys.cfbd:
            raise FileNotFoundError(
                "CFBD cache is incomplete and CFBD_API_KEY is missing. "
                "Add the key or provide cached JSON under data/raw/cfbd."
            )
        _download_missing(missing, cfg, keys.cfbd, raw_dir)
        for path in missing:
            payload_by_file[path] = _read_json(path)

    games = _build_games_frame(payload_by_file, cfg, seasons, season_types)
    processed = paths["processed"]
    processed.mkdir(parents=True, exist_ok=True)
    games.to_parquet(processed / "games.parquet", index=False)
    return games


def _download_missing(
    missing: List[Path],
    cfg: Dict[str, Any],
    api_key: str,
    raw_dir: Path,
) -> None:
    base = cfg["cfbd"]["base_url"].rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    for path in missing:
        name = path.name
        if name.startswith("teams_fbs_"):
            season = int(name.replace("teams_fbs_", "").replace(".json", ""))
            url = f"{base}/teams/fbs"
            params = {"year": season}
        else:
            rest = name.replace("games_", "").replace(".json", "")
            season_str, season_type = rest.split("_", 1)
            url = f"{base}/games"
            params = {
                "year": int(season_str),
                "seasonType": season_type,
                "division": cfg["cfbd"].get("classification", "fbs"),
            }
        response = requests.get(url, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        path.write_text(json.dumps(response.json(), indent=2))


def _build_games_frame(
    payload_by_file: Dict[Path, Any],
    cfg: Dict[str, Any],
    seasons: Iterable[int],
    season_types: Iterable[str],
    *,
    aliases=None,
) -> pd.DataFrame:
    season_set = set(seasons)
    type_set = set(season_types)
    fbs_by_season: Dict[int, Set[str]] = {}
    game_rows: List[Dict[str, Any]] = []
    alias_rows = aliases if aliases is not None else load_aliases()
    cfbd_map, _odds_map = build_alias_indexes(alias_rows)

    for path, payload in payload_by_file.items():
        name = path.name
        if name.startswith("teams_fbs_"):
            season = int(name.replace("teams_fbs_", "").replace(".json", ""))
            fbs_by_season[season] = {
                str(item.get("school") or item.get("team") or "")
                for item in payload
                if item.get("school") or item.get("team")
            }

    for path, payload in payload_by_file.items():
        name = path.name
        if not name.startswith("games_"):
            continue
        rest = name.replace("games_", "").replace(".json", "")
        season_str, season_type = rest.split("_", 1)
        season = int(season_str)
        if season not in season_set or season_type not in type_set:
            continue
        fbs_names = fbs_by_season.get(season, set())
        for item in payload:
            game_rows.append(
                _game_row(item, season, season_type, fbs_names, cfg, cfbd_map)
            )

    if not game_rows:
        return pd.DataFrame(columns=_games_columns())
    frame = pd.DataFrame(game_rows)
    frame["kickoff_timestamp"] = pd.to_datetime(frame["kickoff_timestamp"], utc=True)
    frame["game_date"] = pd.to_datetime(frame["game_date"]).dt.date
    return frame[_games_columns()]


def _game_row(
    item: Dict[str, Any],
    season: int,
    season_type: str,
    fbs_names: Set[str],
    cfg: Dict[str, Any],
    cfbd_map: Dict[str, str],
) -> Dict[str, Any]:
    home_cfbd = str(item.get("homeTeam") or item.get("home_team") or "")
    away_cfbd = str(item.get("awayTeam") or item.get("away_team") or "")
    home_class = _classification(item, "home", fbs_names, home_cfbd)
    away_class = _classification(item, "away", fbs_names, away_cfbd)
    start = item.get("startDate") or item.get("start_date") or item.get("start_date_iso")
    kickoff = _parse_ts(start)
    home_score = _nullable_int(item.get("homePoints", item.get("home_points")))
    away_score = _nullable_int(item.get("awayPoints", item.get("away_points")))
    cancelled = bool(item.get("cancelled") or item.get("noContest") or item.get("no_contest"))
    completed = bool(item.get("completed", home_score is not None and away_score is not None))
    if item.get("completed") is False:
        completed = False
    reasons: List[str] = []
    if home_class != "fbs" or away_class != "fbs":
        reasons.append(EXCL_NOT_FBS)
    if cancelled:
        reasons.append(EXCL_CANCELLED)
    if not completed or home_score is None or away_score is None:
        reasons.append(EXCL_NO_FINAL)
    home_team = cfbd_map.get(home_cfbd)
    away_team = cfbd_map.get(away_cfbd)
    if home_team is None and home_cfbd:
        # Identity is allowed only as a pending exact match vs Odds API.
        home_team = None
    if away_team is None and away_cfbd:
        away_team = None
    if home_team is None or away_team is None:
        reasons.append(EXCL_TEAM_UNMAPPED)
    exclude = bool(reasons)
    return {
        "game_id": str(item.get("id")),
        "season": int(item.get("season") or season),
        "week": int(item.get("week") or 0),
        "season_type": str(item.get("seasonType") or item.get("season_type") or season_type),
        "game_date": kickoff.date() if kickoff is not None else None,
        "kickoff_timestamp": kickoff,
        "home_team_cfbd": home_cfbd,
        "away_team_cfbd": away_cfbd,
        "home_team": home_team,
        "away_team": away_team,
        "home_classification": home_class,
        "away_classification": away_class,
        "neutral_site": bool(item.get("neutralSite") or item.get("neutral_site")),
        "home_score": home_score,
        "away_score": away_score,
        "cancelled": cancelled,
        "completed": completed,
        "sharp_source": cfg["mvp"]["sharp_source"],
        "sharp_available": False,
        "exclude_from_model": exclude,
        "exclusion_reasons": ";".join(reasons),
    }


def _classification(item: Dict[str, Any], side: str, fbs_names: Set[str], name: str) -> str:
    key = f"{side}Classification" if side in {"home", "away"} else ""
    alt = f"{side}_classification"
    value = item.get(key) or item.get(alt)
    if value:
        return str(value).lower()
    return "fbs" if name in fbs_names else "unknown"


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    ts = pd.to_datetime(value, utc=True)
    if pd.isna(ts):
        return None
    return ts.to_pydatetime().astimezone(timezone.utc)


def _nullable_int(value: Any) -> Optional[int]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _games_columns() -> List[str]:
    return [
        "game_id",
        "season",
        "week",
        "season_type",
        "game_date",
        "kickoff_timestamp",
        "home_team_cfbd",
        "away_team_cfbd",
        "home_team",
        "away_team",
        "home_classification",
        "away_classification",
        "neutral_site",
        "home_score",
        "away_score",
        "cancelled",
        "completed",
        "sharp_source",
        "sharp_available",
        "exclude_from_model",
        "exclusion_reasons",
    ]

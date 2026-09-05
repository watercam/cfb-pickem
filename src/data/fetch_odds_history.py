"""Fetch historical NCAAF odds from The Odds API.

MVP: sport=americanfootball_ncaaf, markets=h2h+spreads, bookmaker=pinnacle.
If Pinnacle is missing, persist sharp_available=false. Do not substitute another book.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import pandas as pd
import requests

from src.settings import get_api_keys, load_backtest_config, resolve_paths

BOOKMAKER = "pinnacle"
HISTORICAL_PATH = "/v4/historical/sports/{sport}/odds"
ODDS_HOST = "https://api.the-odds-api.com"


def floor_to_grid(ts: datetime, minutes: int = 5) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    epoch = int(ts.timestamp())
    grid = minutes * 60
    floored = epoch - (epoch % grid)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def snapshot_horizons_hours(config: Dict[str, Any]) -> List[int]:
    listed = config.get("snapshot_horizons_hours")
    if listed:
        return [int(h) for h in listed]
    mvp = config["mvp"]
    return [int(mvp["decision_horizon_hours"]), int(mvp["reference_horizon_hours"])]


def planned_snapshot_timestamps(
    kickoffs: Iterable[datetime],
    *,
    grid_minutes: int,
    horizons: Optional[Sequence[int]] = None,
    decision_horizon_hours: Optional[int] = None,
    reference_horizon_hours: Optional[int] = None,
) -> List[datetime]:
    if horizons is None:
        if decision_horizon_hours is None or reference_horizon_hours is None:
            raise ValueError("Provide horizons or both decision and reference hours")
        horizons = [int(decision_horizon_hours), int(reference_horizon_hours)]
    unique = set()
    for kickoff in kickoffs:
        if kickoff is None or pd.isna(kickoff):
            continue
        ko = pd.to_datetime(kickoff, utc=True).to_pydatetime()
        for hours in horizons:
            target = ko - timedelta(hours=int(hours))
            unique.add(floor_to_grid(target, grid_minutes))
    return sorted(unique)


def estimate_credits(n_requests: int, config: Dict[str, Any]) -> int:
    odds = config["odds_api"]
    per = int(odds["credits_per_market_per_region"])
    return n_requests * per * len(odds["markets"]) * len(odds["regions"])


def plan_fetch(
    games: pd.DataFrame,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cfg = config or load_backtest_config()
    usable = games.copy()
    if "exclusion_reasons" in usable.columns:
        reasons = usable["exclusion_reasons"].fillna("")
        usable = usable.loc[~reasons.str.contains("NOT_FBS_VS_FBS", regex=False)]
    if "cancelled" in usable.columns:
        usable = usable.loc[~usable["cancelled"].fillna(False).astype(bool)]
    if "completed" in usable.columns:
        usable = usable.loc[usable["completed"].fillna(False).astype(bool)]
    horizons = snapshot_horizons_hours(cfg)
    timestamps = planned_snapshot_timestamps(
        usable["kickoff_timestamp"],
        horizons=horizons,
        grid_minutes=int(cfg["odds_api"]["snapshot_grid_minutes"]),
    )
    paths = resolve_paths(cfg)
    snap_dir = paths["snapshots"]
    missing = [
        ts
        for ts in timestamps
        if not _snapshot_file_ready(snap_dir / snapshot_filename(ts))
    ]
    n_missing = len(missing)
    return {
        "timestamps": timestamps,
        "missing_timestamps": missing,
        "horizons_hours": horizons,
        "n_planned": len(timestamps),
        "n_cached": len(timestamps) - n_missing,
        "n_missing": n_missing,
        "n_requests": n_missing,
        "est_credits": estimate_credits(n_missing, cfg),
        "est_credits_all_planned": estimate_credits(len(timestamps), cfg),
        "markets": list(cfg["odds_api"]["markets"]),
        "regions": list(cfg["odds_api"]["regions"]),
        "max_historical_requests": int(cfg["odds_api"]["max_historical_requests"]),
    }


def _snapshot_file_ready(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def snapshot_filename(ts: datetime) -> str:
    iso = ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"{iso}.json"


def fetch_odds_history(
    games: pd.DataFrame,
    *,
    mode: str = "cache_only",
    dry_run: bool = False,
    confirm_fetch: bool = False,
    config: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    cfg = config or load_backtest_config()
    paths = resolve_paths(cfg)
    plan = plan_fetch(games, cfg)
    if plan["n_requests"] > plan["max_historical_requests"]:
        raise RuntimeError(
            f"Planned Odds API requests {plan['n_requests']} exceed "
            f"max_historical_requests={plan['max_historical_requests']}."
        )
    if dry_run:
        return pd.DataFrame()

    snap_dir = paths["snapshots"]
    snap_dir.mkdir(parents=True, exist_ok=True)
    missing = list(plan.get("missing_timestamps") or [
        ts
        for ts in plan["timestamps"]
        if not _snapshot_file_ready(snap_dir / snapshot_filename(ts))
    ])
    if missing and mode == "cache_only":
        raise FileNotFoundError(
            f"Odds snapshot cache missing {len(missing)} of {plan.get('n_planned', plan['n_requests'])} "
            f"Pinnacle timestamps under {snap_dir}. "
            "This pipeline never substitutes another sportsbook. "
            "Re-run with --mode fetch_missing --confirm-fetch after setting "
            "allow_historical_fetch: true if you intend to spend Odds API credits."
        )
    if missing:
        _maybe_fetch_missing(missing, cfg, paths, confirm_fetch)

    frame = snapshots_from_cache(snap_dir)
    processed = paths["processed"]
    processed.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(processed / "odds_snapshots.parquet", index=False)
    return frame


def _maybe_fetch_missing(
    missing: Sequence[datetime],
    cfg: Dict[str, Any],
    paths: Dict[str, Path],
    confirm_fetch: bool,
) -> None:
    odds_cfg = cfg["odds_api"]
    if not odds_cfg.get("allow_historical_fetch"):
        raise RuntimeError(
            "Odds snapshots are missing and allow_historical_fetch is false. "
            "Run --dry-run-fetch, then set allow_historical_fetch: true and pass "
            "--confirm-fetch. Never substitute another sportsbook."
        )
    if not confirm_fetch:
        raise RuntimeError(
            "Odds snapshots are missing. Pass --confirm-fetch after reviewing "
            "--dry-run-fetch credits. No historical GET was made."
        )
    keys = get_api_keys()
    if not keys.odds:
        raise FileNotFoundError(
            "Odds snapshot cache is incomplete and ODDS_API_KEY is missing."
        )
    log_path = paths["request_log"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    total = len(missing)
    failures = []
    for i, ts in enumerate(missing, start=1):
        dest = paths["snapshots"] / snapshot_filename(ts)
        if dest.exists() and dest.stat().st_size > 0:
            continue
        try:
            remaining = _fetch_one_snapshot(ts, cfg, keys.odds, paths["snapshots"], log_path)
        except Exception as exc:  # noqa: BLE001 — keep going; resume later
            failures.append((ts.isoformat(), str(exc)))
            print(f"  fetch fail {i}/{total} {ts.isoformat()}: {exc}")
            continue
        if i == 1 or i % 25 == 0 or i == total:
            print(f"  fetched {i}/{total} remaining_credits={remaining}")
    if failures:
        fail_path = paths["raw_odds"] / "fetch_failures.jsonl"
        with fail_path.open("a") as handle:
            for ts, err in failures:
                handle.write(json.dumps({"timestamp": ts, "error": err}) + "\n")
        print(f"WARNING: {len(failures)} snapshot fetches failed; see {fail_path}")
        raise RuntimeError(
            f"{len(failures)} Pinnacle snapshot fetches failed. Re-run to resume; "
            "already-written JSON will not be re-downloaded."
        )


def _fetch_one_snapshot(
    request_ts: datetime,
    cfg: Dict[str, Any],
    api_key: str,
    snap_dir: Path,
    log_path: Path,
) -> Optional[str]:
    odds_cfg = cfg["odds_api"]
    date_iso = request_ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "apiKey": api_key,
        "regions": ",".join(odds_cfg["regions"]),
        "markets": ",".join(odds_cfg["markets"]),
        "oddsFormat": odds_cfg.get("odds_format", "american"),
        "date": date_iso,
        "bookmakers": odds_cfg["preferred_bookmaker"],
    }
    url = ODDS_HOST + HISTORICAL_PATH.format(sport=odds_cfg["sport"])
    last_error: Optional[Exception] = None
    for attempt in range(1, 6):
        try:
            response = requests.get(url, params=params, timeout=60)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(min(2 ** attempt, 20))
            continue
        remaining = response.headers.get("x-requests-remaining")
        logged = {
            "requested_date": date_iso,
            "url": _strip_api_key(response.url),
            "status": response.status_code,
            "x-requests-remaining": remaining,
            "x-requests-used": response.headers.get("x-requests-used"),
            "cached": False,
            "attempt": attempt,
        }
        with log_path.open("a") as handle:
            handle.write(json.dumps(logged) + "\n")
        if response.status_code == 429:
            time.sleep(min(5 * attempt, 30))
            last_error = RuntimeError("HTTP 429")
            continue
        if response.status_code >= 500:
            time.sleep(min(2 ** attempt, 20))
            last_error = RuntimeError(f"HTTP {response.status_code}")
            continue
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
        payload = response.json()
        payload["_meta"] = {
            "requested_date": date_iso,
            "url": _strip_api_key(response.url),
        }
        dest = snap_dir / snapshot_filename(request_ts)
        dest.write_text(json.dumps(payload))
        return remaining
    raise RuntimeError(f"failed after retries: {last_error}")


def _strip_api_key(url: str) -> str:
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() != "apikey"]
    return urlunparse(parsed._replace(query=urlencode(query)))


def snapshots_from_cache(snap_dir: Path) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for path in sorted(snap_dir.glob("*.json")):
        payload = json.loads(path.read_text())
        rows.extend(parse_snapshot_payload(payload, path))
    if not rows:
        return pd.DataFrame(columns=_snapshot_columns())
    frame = pd.DataFrame(rows)
    for col in (
        "snapshot_request_ts",
        "snapshot_ts",
        "commence_time",
        "last_update",
    ):
        frame[col] = pd.to_datetime(frame[col], utc=True)
    return frame[_snapshot_columns()]


def parse_snapshot_payload(payload: Dict[str, Any], path: Optional[Path] = None) -> List[Dict[str, Any]]:
    meta = payload.get("_meta") or {}
    request_ts = _parse_ts(meta.get("requested_date")) or _request_ts_from_name(path)
    snapshot_ts = _parse_ts(payload.get("timestamp")) or request_ts
    events = payload.get("data") or []
    rows = []
    for event in events:
        rows.append(_event_row(event, request_ts, snapshot_ts))
    return rows


def _event_row(
    event: Dict[str, Any],
    request_ts: Optional[datetime],
    snapshot_ts: Optional[datetime],
) -> Dict[str, Any]:
    books = event.get("bookmakers") or []
    pinnacle = next((b for b in books if str(b.get("key", "")).lower() == BOOKMAKER), None)
    home = event.get("home_team")
    away = event.get("away_team")
    h2h = _market_outcomes(pinnacle, "h2h") if pinnacle else {}
    spreads = _market_outcomes(pinnacle, "spreads") if pinnacle else {}
    home_ml = _price(h2h.get(home))
    away_ml = _price(h2h.get(away))
    home_spread = _point(spreads.get(home))
    away_spread = _point(spreads.get(away))
    if home_spread is None and away_spread is not None:
        home_spread = -away_spread
    if away_spread is None and home_spread is not None:
        away_spread = -home_spread
    sharp_available = pinnacle is not None and home_ml is not None and away_ml is not None
    last_update = None
    if pinnacle:
        last_update = _parse_ts(pinnacle.get("last_update"))
    return {
        "snapshot_request_ts": request_ts,
        "snapshot_ts": snapshot_ts,
        "odds_event_id": str(event.get("id") or ""),
        "commence_time": _parse_ts(event.get("commence_time")),
        "home_team_odds": home,
        "away_team_odds": away,
        "bookmaker": BOOKMAKER,
        "sharp_available": sharp_available,
        "home_moneyline": home_ml,
        "away_moneyline": away_ml,
        "home_spread": home_spread,
        "away_spread": away_spread,
        "home_spread_price": _price(spreads.get(home)),
        "away_spread_price": _price(spreads.get(away)),
        "last_update": last_update,
    }


def _market_outcomes(book: Dict[str, Any], market_key: str) -> Dict[str, Dict[str, Any]]:
    markets = book.get("markets") or []
    market = next((m for m in markets if m.get("key") == market_key), None)
    if not market:
        return {}
    return {str(o.get("name")): o for o in market.get("outcomes") or []}


def _price(outcome: Optional[Dict[str, Any]]) -> Optional[int]:
    if not outcome or outcome.get("price") is None:
        return None
    return int(outcome["price"])


def _point(outcome: Optional[Dict[str, Any]]) -> Optional[float]:
    if not outcome or outcome.get("point") is None:
        return None
    return float(outcome["point"])


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    ts = pd.to_datetime(value, utc=True)
    if pd.isna(ts):
        return None
    return ts.to_pydatetime().astimezone(timezone.utc)


def _request_ts_from_name(path: Optional[Path]) -> Optional[datetime]:
    if path is None:
        return None
    if "T" not in path.stem:
        return None
    date_part, time_part = path.stem.split("T", 1)
    time_part = time_part.replace("-", ":")
    return _parse_ts(f"{date_part}T{time_part}")


def _snapshot_columns() -> List[str]:
    return [
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

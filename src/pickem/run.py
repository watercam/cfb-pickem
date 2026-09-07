"""python -m src.pickem.run --fixture tests/fixtures/pickem_week.json"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from src.pickem.alerts import projection_alerts
from src.pickem.calibration import MovementCalibrator
from src.pickem.odds import fetch_pinnacle_snapshots, snapshots_from_payloads
from src.pickem.ranking import recommend_slate
from src.pickem.slate import PICKEM_USER_AGENT, fetch_espn_slate, load_fixture
from src.pickem.slack import post_pickem_update
from src.pickem.types import GameRecommendation, PickemResult
from src.settings import get_api_keys, load_pickem_config, project_root

DASHBOARD_ROOT_KEYS = ("week", "calibration", "generated_at", "games")
DASHBOARD_GAME_KEYS = (
    "game_id",
    "pick",
    "opponent",
    "confidence",
    "p_current",
    "spread_move",
    "adj",
    "p_final",
    "flags",
    "public_pick_pct",
    "kickoff",
    "away",
    "home",
    "espn_p",
    "note",
    "pinnacle_spread",
)
WEB_RECOMMENDATIONS = Path("web") / "recommendations.json"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Weekly ESPN CFB Pick'em (confidence mode)")
    parser.add_argument("--fixture", type=Path, help="Local slate + Pinnacle snapshots JSON")
    parser.add_argument("--json", action="store_true", help="Write JSON to stdout")
    parser.add_argument("--out", type=Path, help="Write dashboard JSON to this file")
    parser.add_argument(
        "--web",
        action="store_true",
        help=f"Write dashboard JSON to {WEB_RECOMMENDATIONS}",
    )
    parser.add_argument("--config", type=Path, default=None, help="Override config/pickem.yaml")
    parser.add_argument("--no-slack", action="store_true", help="Do not POST to SLACK_WEBHOOK_URL")
    args = parser.parse_args(argv)

    config = load_pickem_config(args.config)
    calibrator = MovementCalibrator.from_config(config)
    if args.fixture:
        games, odds_payloads, now, week = load_fixture(args.fixture)
        snapshots = snapshots_from_payloads(odds_payloads)
    else:
        games = fetch_espn_slate(config["slate"]["espn_challenge_url"])
        keys = get_api_keys()
        if not keys.odds:
            raise SystemExit("ODDS_API_KEY is required unless --fixture is set")
        now = datetime.now(timezone.utc)
        week = None
        snapshots = fetch_pinnacle_snapshots(games, now=now, config=config, api_key=keys.odds)

    result = recommend_slate(
        games,
        snapshots,
        now=now,
        calibrator=calibrator,
        reference_hours=int(config["horizons"]["reference_hours"]),
        confidence_points=int(config["slate"]["confidence_points"]),
        week=week,
    )
    payload = _result_to_json(result)
    out_path = _resolve_out_path(args.out, args.web)
    if args.fixture:
        previous = _load_previous(out_path)
    else:
        previous = fetch_deployed_recommendations(
            str((config.get("slate") or {}).get("dashboard_url") or "")
        ) or _load_previous(out_path)
    payload = _attach_previous_dashboard(previous, payload)
    payload["alerts"] = projection_alerts(previous, payload)
    if not args.no_slack:
        slate = config.get("slate") or {}
        post_pickem_update(
            payload,
            previous=previous,
            dashboard_url=str(slate.get("dashboard_url") or ""),
            refresh_url=str(slate.get("refresh_url") or ""),
        )
    if out_path is not None:
        _write_json(out_path, payload)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(format_table(result))
        if out_path is not None:
            print(f"\nwrote {out_path}")
    return 0


def _resolve_out_path(out: Optional[Path], web: bool) -> Optional[Path]:
    if out is not None:
        path = out
    elif web:
        path = WEB_RECOMMENDATIONS
    else:
        return None
    if not path.is_absolute():
        path = project_root() / path
    return path


def fetch_deployed_recommendations(dashboard_url: str, *, timeout: int = 30) -> Optional[Dict[str, Any]]:
    """GET the live site snapshot so insights/notes/alerts survive a refresh."""
    base = (dashboard_url or "").rstrip("/")
    if not base:
        return None
    try:
        response = requests.get(
            f"{base}/recommendations.json",
            timeout=timeout,
            headers={"User-Agent": PICKEM_USER_AGENT, "Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_previous(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _attach_previous_dashboard(
    previous: Optional[Dict[str, Any]],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    if not previous or previous.get("week") != payload.get("week"):
        payload.setdefault("alerts", [])
        return payload
    for key in ("insights", "tiebreak", "ranking"):
        if key in previous and key not in payload:
            payload[key] = previous[key]
    prev_games = {str(game.get("game_id")): game for game in previous.get("games") or []}
    for game in payload.get("games") or []:
        old = prev_games.get(str(game.get("game_id")))
        if old is None:
            continue
        for field in ("espn_p", "note"):
            if game.get(field) is None and old.get(field) is not None:
                game[field] = old[field]
    return payload


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def format_table(result: PickemResult) -> str:
    lines = [
        f"week: {result.week if result.week is not None else '-'}",
        f"calibration: {result.calibration_source}",
        "",
        f"{'conf':<5} {'pick':<18} {'opponent':<18} {'p_current':>10} {'spread_move':>12} {'adj':>8} {'p_final':>8} {'flags':<24}",
    ]
    for game in result.games:
        conf = "" if game.confidence is None else str(game.confidence)
        pick = game.pick or "-"
        opp = game.opponent or "-"
        p_cur = _fmt(game.p_current)
        move = _fmt(game.spread_move)
        adj = _fmt(game.adj)
        p_fin = _fmt(game.p_final)
        flags = ",".join(game.flags) if game.flags else "-"
        lines.append(
            f"{conf:<5} {pick:<18} {opp:<18} {p_cur:>10} {move:>12} {adj:>8} {p_fin:>8} {flags:<24}"
        )
    return "\n".join(lines)


def _fmt(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:.4f}"


def _result_to_json(result: PickemResult) -> Dict[str, Any]:
    return {
        "week": result.week,
        "calibration": result.calibration_source,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "games": [_game_to_json(game) for game in result.games],
    }


def _game_to_json(game: GameRecommendation) -> Dict[str, Any]:
    kickoff = None
    if game.kickoff is not None:
        kickoff = game.kickoff.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "game_id": game.game_id,
        "pick": game.pick,
        "opponent": game.opponent,
        "confidence": game.confidence,
        "p_current": game.p_current,
        "spread_move": game.spread_move,
        "pinnacle_spread": game.pinnacle_spread,
        "adj": game.adj,
        "p_final": game.p_final,
        "flags": game.flags,
        "public_pick_pct": game.public_pick_pct,
        "kickoff": kickoff,
        "away": game.away_espn,
        "home": game.home_espn,
        "espn_p": None,
        "note": None,
    }


if __name__ == "__main__":
    sys.exit(main())

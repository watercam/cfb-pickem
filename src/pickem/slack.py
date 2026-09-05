"""Post Pick'em summaries to a Slack Incoming Webhook. Skip if unset."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, List, Mapping, Optional

import requests

from src.settings import load_env

WEBHOOK_ENV = "SLACK_WEBHOOK_URL"


def post_pickem_update(
    payload: Mapping[str, Any],
    *,
    previous: Optional[Mapping[str, Any]] = None,
    dashboard_url: str = "",
    webhook_url: Optional[str] = None,
) -> bool:
    url = _webhook(webhook_url)
    if not url:
        return False
    text = format_success_message(payload, previous=previous, dashboard_url=dashboard_url)
    _post_text(url, text)
    return True


def post_failure(message: str, *, webhook_url: Optional[str] = None) -> bool:
    url = _webhook(webhook_url)
    if not url:
        return False
    _post_text(url, message)
    return True


def format_success_message(
    payload: Mapping[str, Any],
    *,
    previous: Optional[Mapping[str, Any]] = None,
    dashboard_url: str = "",
) -> str:
    week = payload.get("week")
    week_label = "-" if week is None else str(week)
    lines = [
        f"Pick'em week {week_label} · calibration {payload.get('calibration') or '-'}",
        f"generated_at: {payload.get('generated_at') or '-'}",
    ]
    if dashboard_url:
        lines.append(f"dashboard: {dashboard_url}")
    if _is_new_week(previous, payload):
        lines.append("new week slate")
    lines.append("")
    lines.append(format_confidence_table(payload.get("games") or []))
    alerts = list(payload.get("alerts") or [])
    if alerts:
        lines.append("")
        lines.append("Alerts:")
        for alert in alerts:
            if isinstance(alert, Mapping):
                lines.append(f"- {alert.get('message') or alert.get('kind')}")
            else:
                lines.append(f"- {alert}")
    return "\n".join(lines).rstrip() + "\n"


def format_confidence_table(games: List[Any]) -> str:
    ranked = [
        game
        for game in games
        if isinstance(game, Mapping) and game.get("confidence") is not None
    ]
    ranked.sort(key=lambda game: int(game["confidence"]), reverse=True)
    header = f"{'conf':<5} {'pick':<18} {'opponent':<18}"
    rows = [header]
    for game in ranked:
        conf = str(game.get("confidence"))
        pick = str(game.get("pick") or "-")
        opp = str(game.get("opponent") or "-")
        rows.append(f"{conf:<5} {pick:<18} {opp:<18}")
    return "\n".join(rows)


def _is_new_week(previous: Optional[Mapping[str, Any]], current: Mapping[str, Any]) -> bool:
    if not previous:
        return True
    return previous.get("week") != current.get("week")


def _webhook(explicit: Optional[str]) -> Optional[str]:
    load_env()
    value = explicit if explicit is not None else os.getenv(WEBHOOK_ENV)
    if not value:
        return None
    return value.strip() or None


def _post_text(url: str, text: str) -> None:
    response = requests.post(url, json={"text": text}, timeout=30)
    response.raise_for_status()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Slack Incoming Webhook helpers")
    parser.add_argument("--failure", metavar="MESSAGE", help="Post a short failure ping")
    args = parser.parse_args(argv)
    if args.failure:
        posted = post_failure(args.failure)
        return 0 if posted or not _webhook(None) else 1
    parser.error("pass --failure MESSAGE")
    return 2


if __name__ == "__main__":
    sys.exit(main())

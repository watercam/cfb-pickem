"""Post Pick'em summaries to a Slack Incoming Webhook. Skip if unset."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Mapping, Optional

import requests

from src.settings import load_env

WEBHOOK_ENV = "SLACK_WEBHOOK_URL"
# Slack's table UI fades after ~8 body rows; 5 keeps a 10-game slate fully visible.
TABLE_BODY_ROW_LIMIT = 5
_MRKDWN_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))


def post_pickem_update(
    payload: Mapping[str, Any],
    *,
    previous: Optional[Mapping[str, Any]] = None,
    dashboard_url: str = "",
    refresh_url: str = "",
    webhook_url: Optional[str] = None,
) -> bool:
    url = _webhook(webhook_url)
    if not url:
        return False
    _post_json(
        url,
        {
            "text": format_success_message(payload, previous=previous),
            "unfurl_links": False,
            "blocks": format_success_blocks(
                payload,
                previous=previous,
                dashboard_url=dashboard_url,
                refresh_url=refresh_url,
            ),
        },
    )
    return True


def post_failure(message: str, *, webhook_url: Optional[str] = None) -> bool:
    url = _webhook(webhook_url)
    if not url:
        return False
    _post_json(
        url,
        {
            "text": message,
            "unfurl_links": False,
            "blocks": format_failure_blocks(message),
        },
    )
    return True


def format_success_message(
    payload: Mapping[str, Any],
    *,
    previous: Optional[Mapping[str, Any]] = None,
    dashboard_url: str = "",
    refresh_url: str = "",
) -> str:
    del dashboard_url, refresh_url
    week = payload.get("week")
    week_label = "-" if week is None else str(week)
    top = _ranked_games(payload.get("games") or [])
    if not top:
        summary = f"Pick'em week {week_label}"
    else:
        game = top[0]
        pick = game.get("pick") or "-"
        opp = game.get("opponent") or "-"
        summary = f"Pick'em week {week_label} · {game.get('confidence')} {pick} vs {opp}"
    if _is_new_week(previous, payload):
        summary += " · new week slate"
    return summary


def format_success_blocks(
    payload: Mapping[str, Any],
    *,
    previous: Optional[Mapping[str, Any]] = None,
    dashboard_url: str = "",
    refresh_url: str = "",
) -> List[Dict[str, Any]]:
    week = payload.get("week")
    week_label = "-" if week is None else str(week)
    blocks: List[Dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Pick'em · Week {week_label}"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": _context_text(payload, previous)}],
        },
    ]
    blocks.extend(format_confidence_table_blocks(payload.get("games") or []))
    alerts = _alert_lines(payload.get("alerts") or [])
    if alerts:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Alerts*\n" + "\n".join(alerts)},
            }
        )
    actions = _action_elements(dashboard_url, refresh_url)
    if actions:
        blocks.append({"type": "actions", "elements": actions})
    return blocks


def format_failure_blocks(message: str) -> List[Dict[str, Any]]:
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Pick'em refresh failed"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": _escape_mrkdwn(message)},
        },
    ]


def format_confidence_list(games: List[Any]) -> str:
    ranked = _ranked_games(games)
    if not ranked:
        return "_No ranked picks._"
    return "\n".join(_confidence_line(game) for game in ranked)


def format_confidence_table_blocks(games: List[Any]) -> List[Dict[str, Any]]:
    ranked = _ranked_games(games)
    if not ranked:
        return [_confidence_table([])]
    return [
        _confidence_table(ranked[index : index + TABLE_BODY_ROW_LIMIT])
        for index in range(0, len(ranked), TABLE_BODY_ROW_LIMIT)
    ]


def format_confidence_table_block(games: List[Any]) -> Dict[str, Any]:
    return format_confidence_table_blocks(games)[0]


def _confidence_table(ranked: List[Mapping[str, Any]]) -> Dict[str, Any]:
    header = [
        _raw_text("Conf"),
        _raw_text("Pick"),
        _raw_text("Opp"),
        _raw_text("Win"),
        _raw_text("Pin"),
        _raw_text("Pub"),
    ]
    rows: List[List[Dict[str, Any]]] = [header]
    if not ranked:
        rows.append(
            [
                _raw_text(""),
                _raw_text("No ranked picks"),
                _raw_text(""),
                _raw_text(""),
                _raw_text(""),
                _raw_text(""),
            ]
        )
    else:
        for game in ranked:
            rows.append(_confidence_row(game))
    return {
        "type": "table",
        "column_settings": [
            {"align": "right"},
            {"is_wrapped": True},
            {"is_wrapped": True},
            {"align": "right"},
            {"align": "right"},
            {"align": "right"},
        ],
        "rows": rows,
    }


def _confidence_row(game: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [
        _raw_text(str(game.get("confidence"))),
        _rich_text(str(game.get("pick") or "-"), bold=True),
        _raw_text(str(game.get("opponent") or "-")),
        _raw_text(_fmt_pct(game.get("p_final")) or ""),
        _raw_text(_fmt_spread(game.get("pinnacle_spread")) or ""),
        _raw_text(_fmt_pct(game.get("public_pick_pct"), already_percent=True) or ""),
    ]


def format_confidence_table(games: List[Any]) -> str:
    ranked = _ranked_games(games)
    header = f"{'conf':<5} {'pick':<18} {'opponent':<18}"
    rows = [header]
    for game in ranked:
        conf = str(game.get("confidence"))
        pick = str(game.get("pick") or "-")
        opp = str(game.get("opponent") or "-")
        rows.append(f"{conf:<5} {pick:<18} {opp:<18}")
    return "\n".join(rows)


def _ranked_games(games: List[Any]) -> List[Mapping[str, Any]]:
    ranked = [
        game
        for game in games
        if isinstance(game, Mapping) and game.get("confidence") is not None
    ]
    ranked.sort(key=lambda game: int(game["confidence"]), reverse=True)
    return ranked


def _confidence_line(game: Mapping[str, Any]) -> str:
    pick = _escape_mrkdwn(str(game.get("pick") or "-"))
    opp = _escape_mrkdwn(str(game.get("opponent") or "-"))
    parts = [f"*{game.get('confidence')}*  *{pick}* vs {opp}"]
    p_final = _fmt_pct(game.get("p_final"))
    if p_final:
        parts.append(p_final)
    pin = _fmt_spread(game.get("pinnacle_spread"))
    if pin:
        parts.append(f"Pin {pin}")
    pub = _fmt_pct(game.get("public_pick_pct"), already_percent=True)
    if pub:
        parts.append(f"pub {pub}")
    return "  ·  ".join(parts)


def _fmt_pct(value: Any, *, already_percent: bool = False) -> Optional[str]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not already_percent:
        number *= 100
    return f"{number:.0f}%"


def _fmt_spread(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        formatted = f"{int(number)}"
    else:
        formatted = f"{number:g}"
    if number > 0:
        return f"+{formatted}"
    return formatted


def _context_text(payload: Mapping[str, Any], previous: Optional[Mapping[str, Any]]) -> str:
    bits = [
        f"calibration `{_escape_mrkdwn(str(payload.get('calibration') or '-'))}`",
        f"generated_at `{_escape_mrkdwn(str(payload.get('generated_at') or '-'))}`",
    ]
    if _is_new_week(previous, payload):
        bits.append("*New week slate*")
    return "  ·  ".join(bits)


def _alert_lines(alerts: List[Any]) -> List[str]:
    lines: List[str] = []
    for alert in alerts:
        if isinstance(alert, Mapping):
            text = alert.get("message") or alert.get("kind")
        else:
            text = alert
        if not text:
            continue
        lines.append(f":warning: {_escape_mrkdwn(str(text))}")
    return lines


def _action_elements(dashboard_url: str, refresh_url: str) -> List[Dict[str, Any]]:
    elements: List[Dict[str, Any]] = []
    if dashboard_url:
        elements.append(_url_button("Dashboard", dashboard_url, "dashboard"))
    if refresh_url:
        elements.append(_url_button("Run refresh", refresh_url, "refresh"))
    return elements


def _raw_text(text: str) -> Dict[str, str]:
    return {"type": "raw_text", "text": text}


def _rich_text(text: str, *, bold: bool = False) -> Dict[str, Any]:
    element: Dict[str, Any] = {"type": "text", "text": text}
    if bold:
        element["style"] = {"bold": True}
    return {
        "type": "rich_text",
        "elements": [{"type": "rich_text_section", "elements": [element]}],
    }


def _url_button(label: str, url: str, action_id: str) -> Dict[str, Any]:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": label},
        "url": url,
        "action_id": action_id,
    }


def _escape_mrkdwn(value: str) -> str:
    for src, dst in _MRKDWN_ESCAPES:
        value = value.replace(src, dst)
    return value


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


def _post_json(url: str, body: Mapping[str, Any]) -> None:
    response = requests.post(url, json=body, timeout=30)
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

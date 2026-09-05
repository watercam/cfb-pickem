"""Compare two dashboard payloads and emit projection-change alerts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def projection_alerts(previous: Optional[Dict[str, Any]], current: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not previous:
        return []
    if previous.get("week") != current.get("week"):
        return []
    prev_by_id = {str(game.get("game_id")): game for game in previous.get("games") or []}
    prev_by_matchup = {}
    for game in previous.get("games") or []:
        key = _matchup_key(game)
        if key:
            prev_by_matchup[key] = game
    alerts: List[Dict[str, Any]] = []
    for game in current.get("games") or []:
        old = prev_by_id.get(str(game.get("game_id")))
        if old is None:
            key = _matchup_key(game)
            old = prev_by_matchup.get(key) if key else None
        if old is None:
            continue
        alert = _game_alert(old, game)
        if alert is not None:
            alerts.append(alert)
    return alerts


def _matchup_key(game: Dict[str, Any]) -> Optional[str]:
    pick = game.get("pick")
    opponent = game.get("opponent")
    if pick and opponent:
        return "|".join(sorted((str(pick), str(opponent))))
    home = game.get("home")
    away = game.get("away")
    if home and away:
        return "|".join(sorted((str(home), str(away))))
    return None


def _game_alert(old: Dict[str, Any], new: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    old_pick = old.get("pick")
    new_pick = new.get("pick")
    old_conf = old.get("confidence")
    new_conf = new.get("confidence")
    game_id = new.get("game_id")
    if new_pick and old_pick and new_pick != old_pick:
        message = f"Projection update: {new_pick} replaces {old_pick}"
        if old_conf is not None and new_conf is not None:
            message += f" and is now {new_conf} (was {old_conf})"
        message += " after the Pinnacle line changed."
        return {
            "kind": "pick_change",
            "game_id": game_id,
            "pick": new_pick,
            "from_pick": old_pick,
            "from_confidence": old_conf,
            "to_confidence": new_conf,
            "message": message,
        }
    if (
        new_pick
        and old_conf is not None
        and new_conf is not None
        and old_conf != new_conf
    ):
        return {
            "kind": "rank_change",
            "game_id": game_id,
            "pick": new_pick,
            "from_confidence": old_conf,
            "to_confidence": new_conf,
            "message": (
                f"Projection update: {new_pick} moved from {old_conf} to {new_conf} "
                "after the Pinnacle line changed."
            ),
        }
    return None

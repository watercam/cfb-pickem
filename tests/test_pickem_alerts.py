from src.pickem.alerts import projection_alerts


def _game(**overrides):
    base = {
        "game_id": "TULN @ DUKE",
        "pick": "Duke",
        "opponent": "Tulane",
        "confidence": 9,
        "home": "Duke",
        "away": "Tulane",
    }
    base.update(overrides)
    return base


def test_rank_change_emits_alert() -> None:
    previous = {"week": 1, "games": [_game(confidence=9)]}
    current = {"week": 1, "games": [_game(confidence=10)]}
    alerts = projection_alerts(previous, current)
    assert len(alerts) == 1
    assert alerts[0]["kind"] == "rank_change"
    assert alerts[0]["from_confidence"] == 9
    assert alerts[0]["to_confidence"] == 10
    assert "Duke moved from 9 to 10" in alerts[0]["message"]


def test_pick_change_emits_alert() -> None:
    previous = {"week": 1, "games": [_game(pick="Duke", confidence=9)]}
    current = {"week": 1, "games": [_game(pick="Tulane", confidence=8)]}
    alerts = projection_alerts(previous, current)
    assert len(alerts) == 1
    assert alerts[0]["kind"] == "pick_change"
    assert alerts[0]["from_pick"] == "Duke"
    assert alerts[0]["pick"] == "Tulane"


def test_new_week_has_no_alerts() -> None:
    previous = {"week": 1, "games": [_game(confidence=9)]}
    current = {"week": 2, "games": [_game(confidence=10)]}
    assert projection_alerts(previous, current) == []


def test_probability_wiggle_without_rank_change_is_silent() -> None:
    previous = {"week": 1, "games": [_game(confidence=9, p_current=0.75)]}
    current = {"week": 1, "games": [_game(confidence=9, p_current=0.76)]}
    assert projection_alerts(previous, current) == []


def test_matchup_fallback_when_game_id_changes() -> None:
    previous = {"week": 1, "games": [_game(game_id="old-id", confidence=2)]}
    current = {"week": 1, "games": [_game(game_id="new-id", confidence=1)]}
    alerts = projection_alerts(previous, current)
    assert len(alerts) == 1
    assert alerts[0]["kind"] == "rank_change"

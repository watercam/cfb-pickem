from src.pickem.slack import format_success_message, post_failure, post_pickem_update


def _payload(**overrides):
    base = {
        "week": 1,
        "calibration": "none",
        "generated_at": "2026-09-05T19:03:06Z",
        "alerts": [],
        "games": [
            {
                "game_id": "CLEM @ LSU",
                "pick": "LSU",
                "opponent": "Clemson",
                "confidence": 10,
            },
            {
                "game_id": "TULN @ DUKE",
                "pick": "Duke",
                "opponent": "Tulane",
                "confidence": 9,
            },
        ],
    }
    base.update(overrides)
    return base


def test_success_message_includes_table_and_dashboard() -> None:
    text = format_success_message(
        _payload(),
        previous={"week": 1, "games": []},
        dashboard_url="https://example.netlify.app",
        refresh_url="https://github.com/example/cfb-pickem/actions/workflows/pickem-refresh.yml",
    )
    assert "Pick'em week 1 · calibration none" in text
    assert "generated_at: 2026-09-05T19:03:06Z" in text
    assert "dashboard: https://example.netlify.app" in text
    assert "new week slate" not in text
    assert "10    LSU                Clemson" in text
    assert "9     Duke               Tulane" in text
    assert "Alerts:" not in text
    assert text.endswith(
        "Run refresh: https://github.com/example/cfb-pickem/actions/workflows/pickem-refresh.yml\n"
    )


def test_new_week_and_alerts_are_appended() -> None:
    payload = _payload(
        week=2,
        alerts=[{"kind": "rank_change", "message": "Duke moved from 9 to 10"}],
    )
    text = format_success_message(payload, previous={"week": 1})
    assert "new week slate" in text
    assert "Alerts:" in text
    assert "Duke moved from 9 to 10" in text


def test_missing_previous_is_new_week() -> None:
    text = format_success_message(_payload(), previous=None)
    assert "new week slate" in text
    assert "Run refresh:" not in text


def test_post_skips_without_webhook(monkeypatch) -> None:
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

    def boom(*_args, **_kwargs):
        raise AssertionError("must not POST")

    monkeypatch.setattr("src.pickem.slack.requests.post", boom)
    assert post_pickem_update(_payload(), webhook_url="") is False
    assert post_failure("failed", webhook_url=None) is False

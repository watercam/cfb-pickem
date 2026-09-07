from src.pickem.slack import (
    format_failure_blocks,
    format_success_blocks,
    format_success_message,
    post_failure,
    post_pickem_update,
)


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
                "p_final": 0.7602,
                "pinnacle_spread": -10.0,
                "public_pick_pct": 89.97,
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


def test_success_fallback_text_is_short_summary() -> None:
    text = format_success_message(
        _payload(),
        previous={"week": 1, "games": []},
        dashboard_url="https://example.netlify.app",
        refresh_url="https://github.com/example/cfb-pickem/actions/workflows/pickem-refresh.yml",
    )
    assert text == "Pick'em week 1 · 10 LSU vs Clemson"
    assert "dashboard:" not in text
    assert "Run refresh:" not in text


def test_success_blocks_include_header_stats_and_buttons() -> None:
    blocks = format_success_blocks(
        _payload(),
        previous={"week": 1, "games": []},
        dashboard_url="https://example.netlify.app",
        refresh_url="https://github.com/example/cfb-pickem/actions/workflows/pickem-refresh.yml",
    )
    assert [block["type"] for block in blocks] == ["header", "context", "table", "actions"]
    assert blocks[0]["text"]["text"] == "Pick'em · Week 1"
    context = blocks[1]["elements"][0]["text"]
    assert "calibration `none`" in context
    assert "generated_at `2026-09-05T19:03:06Z`" in context
    assert "New week slate" not in context
    table = blocks[2]
    assert [cell["text"] for cell in table["rows"][0]] == ["Conf", "Pick", "Opp", "Win", "Pin", "Pub"]
    lsu, duke = table["rows"][1], table["rows"][2]
    assert lsu[0]["text"] == "10"
    assert lsu[1]["elements"][0]["elements"][0]["text"] == "LSU"
    assert lsu[1]["elements"][0]["elements"][0]["style"]["bold"] is True
    assert lsu[2]["text"] == "Clemson"
    assert lsu[3]["text"] == "76%"
    assert lsu[4]["text"] == "-10"
    assert lsu[5]["text"] == "90%"
    assert duke[0]["text"] == "9"
    assert duke[1]["elements"][0]["elements"][0]["text"] == "Duke"
    assert duke[2]["text"] == "Tulane"
    assert duke[3]["text"] == ""
    assert duke[4]["text"] == ""
    assert duke[5]["text"] == ""
    buttons = {el["action_id"]: el["url"] for el in blocks[3]["elements"]}
    assert buttons["dashboard"] == "https://example.netlify.app"
    assert (
        buttons["refresh"]
        == "https://github.com/example/cfb-pickem/actions/workflows/pickem-refresh.yml"
    )
    assert blocks[3]["elements"][0]["text"]["text"] == "Dashboard"
    assert blocks[3]["elements"][1]["text"]["text"] == "Run refresh"


def test_new_week_and_alerts_are_in_blocks() -> None:
    payload = _payload(
        week=2,
        alerts=[{"kind": "rank_change", "message": "Duke moved from 9 to 10"}],
    )
    text = format_success_message(payload, previous={"week": 1})
    assert "new week slate" in text
    blocks = format_success_blocks(payload, previous={"week": 1})
    assert [block["type"] for block in blocks] == ["header", "context", "table", "section"]
    assert "*New week slate*" in blocks[1]["elements"][0]["text"]
    assert ":warning: Duke moved from 9 to 10" in blocks[3]["text"]["text"]
    assert blocks[3]["text"]["text"].startswith("*Alerts*")


def test_missing_previous_is_new_week_without_actions() -> None:
    text = format_success_message(_payload(), previous=None)
    assert "new week slate" in text
    blocks = format_success_blocks(_payload(), previous=None)
    assert [block["type"] for block in blocks] == ["header", "context", "table"]
    assert "*New week slate*" in blocks[1]["elements"][0]["text"]


def test_table_keeps_team_name_characters() -> None:
    payload = _payload(
        games=[
            {
                "game_id": "A & B @ C",
                "pick": "Texas A&M",
                "opponent": "SMU <FBS>",
                "confidence": 8,
            }
        ]
    )
    row = format_success_blocks(payload, previous={"week": 1})[2]["rows"][1]
    assert row[1]["elements"][0]["elements"][0]["text"] == "Texas A&M"
    assert row[2]["text"] == "SMU <FBS>"


def test_six_picks_split_into_two_tables() -> None:
    games = [
        {"pick": f"Team{n}", "opponent": f"Opp{n}", "confidence": n}
        for n in range(10, 4, -1)
    ]
    blocks = format_success_blocks(_payload(games=games), previous={"week": 1})
    tables = [block for block in blocks if block["type"] == "table"]
    assert len(tables) == 2
    assert [row[0]["text"] for row in tables[0]["rows"][1:]] == ["10", "9", "8", "7", "6"]
    assert [row[0]["text"] for row in tables[1]["rows"][1:]] == ["5"]
    assert [cell["text"] for cell in tables[1]["rows"][0]] == [
        "Conf",
        "Pick",
        "Opp",
        "Win",
        "Pin",
        "Pub",
    ]


def test_failure_blocks() -> None:
    blocks = format_failure_blocks("https://github.com/example/cfb-pickem/actions/runs/1")
    assert blocks[0]["text"]["text"] == "Pick'em refresh failed"
    assert "https://github.com/example/cfb-pickem/actions/runs/1" in blocks[1]["text"]["text"]


def test_post_skips_without_webhook(monkeypatch) -> None:
    monkeypatch.setattr("src.pickem.slack.load_env", lambda: None)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

    def boom(*_args, **_kwargs):
        raise AssertionError("must not POST")

    monkeypatch.setattr("src.pickem.slack.requests.post", boom)
    assert post_pickem_update(_payload(), webhook_url="") is False
    assert post_failure("failed", webhook_url=None) is False


def test_post_sends_blocks_payload(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("src.pickem.slack.requests.post", fake_post)
    assert post_pickem_update(
        _payload(),
        previous={"week": 1},
        dashboard_url="https://example.netlify.app",
        webhook_url="https://hooks.slack.com/services/T/B/X",
    )
    body = captured["json"]
    assert captured["url"] == "https://hooks.slack.com/services/T/B/X"
    assert captured["timeout"] == 30
    assert body["text"] == "Pick'em week 1 · 10 LSU vs Clemson"
    assert body["unfurl_links"] is False
    assert [block["type"] for block in body["blocks"]] == ["header", "context", "table", "actions"]
    assert post_failure("boom", webhook_url="https://hooks.slack.com/services/T/B/X")
    fail = captured["json"]
    assert fail["text"] == "boom"
    assert fail["blocks"][0]["text"]["text"] == "Pick'em refresh failed"

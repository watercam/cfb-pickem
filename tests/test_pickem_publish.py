import json
import os
from pathlib import Path

from src.pickem.publish import publish_payload, resolve_refresh_url
from src.pickem.stamp import format_updated_stamp, stamp_payload
from src.settings import project_root


def _payload(**overrides):
    base = {
        "week": 1,
        "calibration": "none",
        "generated_at": "2026-10-12T21:31:00Z",
        "alerts": [],
        "games": [
            {
                "game_id": "CLEM @ LSU",
                "pick": "LSU",
                "opponent": "Clemson",
                "confidence": 10,
            }
        ],
    }
    base.update(overrides)
    return base


def test_format_updated_stamp_matches_example() -> None:
    assert format_updated_stamp("2026-10-12T21:31:00Z", "123") == "Updated 5:31 PM ET, run 123"


def test_stamp_payload_is_shared_by_dashboard_and_slack() -> None:
    stamped = stamp_payload(_payload(), run_id="123")
    assert stamped["run_id"] == "123"
    assert stamped["updated_stamp"] == "Updated 5:31 PM ET, run 123"
    from src.pickem.slack import format_success_blocks

    context = format_success_blocks(stamped, previous={"week": 1, "games": []})[1]["elements"][0]["text"]
    assert "`Updated 5:31 PM ET, run 123`" in context


def test_stamp_reuses_same_week_slack_pointer_only() -> None:
    previous = {"week": 1, "slack": {"channel": "C1", "ts": "111.222"}}
    same = stamp_payload(_payload(), run_id="9", previous=previous)
    assert same["slack"] == {"channel": "C1", "ts": "111.222"}
    nxt = stamp_payload(_payload(week=2), run_id="9", previous=previous)
    assert nxt["slack"] is None


def test_publish_dry_run_uses_same_payload_without_posting(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_CHANNEL_ID", raising=False)

    def boom(*_args, **_kwargs):
        raise AssertionError("dry-run must not POST")

    monkeypatch.setattr("src.pickem.slack.requests.post", boom)
    dest = tmp_path / "recommendations.json"
    dest.write_text(json.dumps(_payload()) + "\n")
    result = publish_payload(
        stamp_payload(_payload(), run_id="123", previous={"week": 1, "games": []}),
        path=dest,
        dry_run=True,
        previous={"week": 1, "games": []},
        dashboard_url="https://example.netlify.app",
        refresh_url="https://github.com/example/cfb-pickem/actions/workflows/pickem-refresh.yml",
    )
    assert result["updated_stamp"] == "Updated 5:31 PM ET, run 123"
    assert result["slack_mode"] == "dry_run_webhook"
    body = result["slack_body"]
    assert body["text"] == "Pick'em week 1 · 10 LSU vs Clemson"
    assert "`Updated 5:31 PM ET, run 123`" in body["blocks"][1]["elements"][0]["text"]
    assert json.loads(dest.read_text())["generated_at"] == "2026-10-12T21:31:00Z"


def test_publish_dry_run_prefers_editing_existing_message(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_CHANNEL_ID", "C123")

    def boom(*_args, **_kwargs):
        raise AssertionError("dry-run must not POST")

    monkeypatch.setattr("src.pickem.slack.requests.post", boom)
    payload = stamp_payload(
        _payload(),
        run_id="123",
        previous={"week": 1, "slack": {"channel": "C123", "ts": "1.2"}},
    )
    result = publish_payload(payload, dry_run=True, slack=True)
    assert result["slack_mode"] == "dry_run_update"
    assert "`Updated 5:31 PM ET, run 123`" in result["slack_body"]["blocks"][1]["elements"][0]["text"]


def test_publish_chat_update_then_persists_pointer(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"ok": True, "channel": "C123", "ts": "1.2"}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers")
        return FakeResponse()

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr("src.pickem.slack.requests.post", fake_post)
    dest = tmp_path / "recommendations.json"
    payload = stamp_payload(
        _payload(),
        run_id="123",
        previous={"week": 1, "slack": {"channel": "C123", "ts": "1.2"}},
    )
    result = publish_payload(payload, path=dest, dashboard_url="https://example.netlify.app")
    assert captured["url"] == "https://slack.com/api/chat.update"
    assert captured["json"]["ts"] == "1.2"
    assert captured["json"]["channel"] == "C123"
    assert "`Updated 5:31 PM ET, run 123`" in captured["json"]["blocks"][1]["elements"][0]["text"]
    saved = json.loads(dest.read_text())
    assert saved["run_id"] == "123"
    assert saved["updated_stamp"] == "Updated 5:31 PM ET, run 123"
    assert saved["slack"] == {"channel": "C123", "ts": "1.2"}
    assert result["pointer_updated"] is True


def test_resolve_refresh_url_uses_secret_when_set(monkeypatch) -> None:
    monkeypatch.delenv("PICKEM_REFRESH_SECRET", raising=False)
    fallback = "https://github.com/watercam/cfb-pickem/actions/workflows/pickem-refresh.yml"
    assert resolve_refresh_url(fallback, "https://cfb-pickem-845.netlify.app") == fallback
    monkeypatch.setenv("PICKEM_REFRESH_SECRET", "shh")
    assert (
        resolve_refresh_url(fallback, "https://cfb-pickem-845.netlify.app/")
        == "https://cfb-pickem-845.netlify.app/.netlify/functions/refresh?token=shh"
    )


def test_refresh_function_dispatches_same_workflow() -> None:
    source = (project_root() / "netlify" / "functions" / "refresh.js").read_text()
    assert "pickem-refresh.yml" in source
    assert "/dispatches" in source
    assert "PICKEM_REFRESH_SECRET" in source
    assert "GITHUB_DISPATCH_TOKEN" in source


def test_workflow_ranks_once_then_deploys_then_publishes() -> None:
    text = (project_root() / ".github" / "workflows" / "pickem-refresh.yml").read_text()
    rank = text.index("python -m src.pickem.run --web --no-slack")
    deploy = text.index("netlify-cli deploy --dir=web --functions=netlify/functions --prod")
    publish = text.index("python -m src.pickem.publish --from-web")
    persist = text.rindex("netlify-cli deploy --dir=web --functions=netlify/functions --prod")
    assert rank < deploy < publish < persist
    assert "PICKEM_RUN_ID: ${{ github.run_id }}" in text
    assert "SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}" in text


def test_cli_dry_run(tmp_path: Path, monkeypatch) -> None:
    import subprocess
    import sys

    dest = tmp_path / "recs.json"
    dest.write_text(json.dumps(stamp_payload(_payload(), run_id="123")) + "\n")
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"ODDS_API_KEY", "CFBD_API_KEY", "SLACK_WEBHOOK_URL", "SLACK_BOT_TOKEN"}
    }
    completed = subprocess.run(
        [sys.executable, "-m", "src.pickem.publish", "--from", str(dest), "--dry-run"],
        cwd=project_root(),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Updated 5:31 PM ET, run 123" in completed.stdout
    assert "dry_run_" in completed.stdout

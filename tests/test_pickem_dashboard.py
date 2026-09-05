import json
import os
import subprocess
import sys
from pathlib import Path

from src.pickem.run import DASHBOARD_GAME_KEYS, DASHBOARD_ROOT_KEYS
from src.settings import project_root


def _env() -> dict:
    return {
        k: v
        for k, v in os.environ.items()
        if k not in {"ODDS_API_KEY", "CFBD_API_KEY", "SLACK_WEBHOOK_URL"}
    }


def assert_dashboard_payload(payload: dict) -> None:
    for key in DASHBOARD_ROOT_KEYS:
        assert key in payload, f"missing {key}"
    assert payload["generated_at"]
    assert isinstance(payload["games"], list)
    assert len(payload["games"]) == 10
    for game in payload["games"]:
        for key in DASHBOARD_GAME_KEYS:
            assert key in game, f"missing game field {key}"


def test_out_writes_dashboard_json(tmp_path: Path) -> None:
    dest = tmp_path / "recs.json"
    fixture = project_root() / "tests" / "fixtures" / "pickem_week.json"
    completed = subprocess.run(
        [sys.executable, "-m", "src.pickem.run", "--fixture", str(fixture), "--out", str(dest)],
        cwd=project_root(),
        capture_output=True,
        text=True,
        env=_env(),
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert dest.is_file()
    payload = json.loads(dest.read_text())
    assert_dashboard_payload(payload)
    assert payload["week"] == 2
    assert payload["calibration"] == "none"


def test_web_flag_writes_dashboard_json(tmp_path: Path) -> None:
    dest = tmp_path / "recommendations.json"
    fixture = project_root() / "tests" / "fixtures" / "pickem_week.json"
    completed = subprocess.run(
        [sys.executable, "-m", "src.pickem.run", "--fixture", str(fixture), "--out", str(dest)],
        cwd=project_root(),
        capture_output=True,
        text=True,
        env=_env(),
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert dest.is_file()
    assert_dashboard_payload(json.loads(dest.read_text()))


def test_committed_sample_match_contract() -> None:
    sample = project_root() / "web" / "recommendations.json"
    assert_dashboard_payload(json.loads(sample.read_text()))


def test_out_emits_alerts_when_overwriting_same_week(tmp_path: Path) -> None:
    dest = tmp_path / "recs.json"
    fixture = project_root() / "tests" / "fixtures" / "pickem_week.json"
    first = subprocess.run(
        [sys.executable, "-m", "src.pickem.run", "--fixture", str(fixture), "--out", str(dest), "--json"],
        cwd=project_root(),
        capture_output=True,
        text=True,
        env=_env(),
        check=False,
    )
    assert first.returncode == 0, first.stderr
    payload = json.loads(dest.read_text())
    assert payload["alerts"] == []
    assert "pinnacle_spread" in payload["games"][0]
    ranked = sorted(
        [g for g in payload["games"] if g.get("confidence") is not None],
        key=lambda g: g["confidence"],
    )
    if len(ranked) >= 2:
        ranked[0]["confidence"], ranked[1]["confidence"] = (
            ranked[1]["confidence"],
            ranked[0]["confidence"],
        )
        dest.write_text(json.dumps(payload, indent=2) + "\n")
        second = subprocess.run(
            [sys.executable, "-m", "src.pickem.run", "--fixture", str(fixture), "--out", str(dest), "--json"],
            cwd=project_root(),
            capture_output=True,
            text=True,
            env=_env(),
            check=False,
        )
        assert second.returncode == 0, second.stderr
        again = json.loads(dest.read_text())
        assert any(alert.get("kind") == "rank_change" for alert in again.get("alerts") or [])

    html = (project_root() / "web" / "index.html").read_text()
    for key in DASHBOARD_ROOT_KEYS:
        assert key in html
    for key in DASHBOARD_GAME_KEYS:
        assert key in html


def test_fetch_deployed_recommendations_skips_empty_url() -> None:
    from src.pickem.run import fetch_deployed_recommendations

    assert fetch_deployed_recommendations("") is None
    assert fetch_deployed_recommendations("   ") is None


def test_fetch_deployed_recommendations_returns_json(monkeypatch) -> None:
    from src.pickem.run import fetch_deployed_recommendations

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"week": 1, "calibration": "none", "games": []}

    def fake_get(url, timeout, headers):
        assert url.endswith("/recommendations.json")
        assert "User-Agent" in headers
        return Resp()

    monkeypatch.setattr("src.pickem.run.requests.get", fake_get)
    payload = fetch_deployed_recommendations("https://example.netlify.app/")
    assert payload["week"] == 1


def test_fetch_deployed_recommendations_failure_returns_none(monkeypatch) -> None:
    import requests
    from src.pickem.run import fetch_deployed_recommendations

    def boom(*_args, **_kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("src.pickem.run.requests.get", boom)
    assert fetch_deployed_recommendations("https://example.netlify.app") is None


def test_refresh_workflow_is_cron_and_dispatch_only() -> None:
    text = (project_root() / ".github" / "workflows" / "pickem-refresh.yml").read_text()
    assert "workflow_dispatch" in text
    assert "schedule:" in text
    assert "pull_request" not in text
    assert "pull_request_target" not in text
    assert "python -m src.pickem.run --web" in text
    assert "--fixture" not in text
    assert "netlify-cli deploy --dir=web --prod" in text

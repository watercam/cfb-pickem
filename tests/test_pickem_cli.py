import json
import os
import subprocess
import sys

from src.settings import project_root


def test_fixture_cli_without_api_keys() -> None:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"ODDS_API_KEY", "CFBD_API_KEY", "SLACK_WEBHOOK_URL"}
    }
    fixture = project_root() / "tests" / "fixtures" / "pickem_week.json"
    completed = subprocess.run(
        [sys.executable, "-m", "src.pickem.run", "--fixture", str(fixture)],
        cwd=project_root(),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "calibration: none" in completed.stdout
    assert "week: 2" in completed.stdout
    json_run = subprocess.run(
        [sys.executable, "-m", "src.pickem.run", "--fixture", str(fixture), "--json"],
        cwd=project_root(),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert json_run.returncode == 0, json_run.stderr
    payload = json.loads(json_run.stdout)
    assert payload["week"] == 2
    assert payload["calibration"] == "none"
    assert len(payload["games"]) == 10
    confs = sorted(g["confidence"] for g in payload["games"])
    assert confs == list(range(1, 11))

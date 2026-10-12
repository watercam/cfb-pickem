"""Publish one ranked payload to Slack (and keep the Slack pointer on disk).

Ranking writes `web/recommendations.json`. The GitHub Action deploys that file
to Netlify first, then this module posts or updates Slack from the same JSON so
both surfaces show the same `updated_stamp`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from src.pickem.slack import SlackPublishResult, publish_pickem_message
from src.pickem.stamp import stamp_payload
from src.settings import load_env, load_pickem_config, project_root

WEB_RECOMMENDATIONS = Path("web") / "recommendations.json"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Publish a ranked Pick'em JSON to Slack")
    parser.add_argument(
        "--from-web",
        action="store_true",
        help=f"Read {WEB_RECOMMENDATIONS}",
    )
    parser.add_argument("--from", dest="source", type=Path, help="Read this dashboard JSON file")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the Slack body from the JSON; do not POST",
    )
    parser.add_argument("--no-slack", action="store_true", help="Skip Slack (still stamps/writes pointer)")
    args = parser.parse_args(argv)

    path = _resolve_source(args.source, args.from_web)
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise SystemExit(f"{path} is not a JSON object")
    payload = stamp_payload(payload)
    result = publish_payload(
        payload,
        path=path,
        dry_run=args.dry_run,
        slack=not args.no_slack,
    )
    print(result["updated_stamp"])
    if args.dry_run:
        print(json.dumps(result, indent=2))
    _write_github_output("pointer_updated", "true" if result.get("pointer_updated") else "false")
    _write_github_output("updated_stamp", result["updated_stamp"])
    _write_github_output("run_id", str(result.get("run_id") or ""))
    return 0


def publish_payload(
    payload: Mapping[str, Any],
    *,
    path: Optional[Path] = None,
    dry_run: bool = False,
    slack: bool = True,
    previous: Optional[Mapping[str, Any]] = None,
    dashboard_url: Optional[str] = None,
    refresh_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Publish one payload to Slack and persist any new message pointer."""
    load_env()
    config = load_pickem_config()
    slate = config.get("slate") or {}
    dashboard = dashboard_url if dashboard_url is not None else str(slate.get("dashboard_url") or "")
    configured_refresh = refresh_url if refresh_url is not None else str(slate.get("refresh_url") or "")
    stamped = stamp_payload(payload, previous=previous if previous is not None else payload)
    slack_result: Optional[SlackPublishResult] = None
    if slack:
        slack_result = publish_pickem_message(
            stamped,
            previous=previous,
            dashboard_url=dashboard,
            refresh_url=resolve_refresh_url(configured_refresh, dashboard),
            dry_run=dry_run,
        )
        if slack_result.channel or slack_result.ts:
            stamped = dict(stamped)
            pointer = {}
            if slack_result.channel:
                pointer["channel"] = slack_result.channel
            if slack_result.ts:
                pointer["ts"] = slack_result.ts
            stamped["slack"] = pointer or None
    pointer_updated = False
    if path is not None and not dry_run:
        pointer_updated = _write_if_changed(path, stamped)
    return {
        "updated_stamp": stamped["updated_stamp"],
        "run_id": stamped["run_id"],
        "generated_at": stamped["generated_at"],
        "pointer_updated": pointer_updated,
        "slack_mode": None if slack_result is None else slack_result.mode,
        "slack_body": None if slack_result is None else slack_result.body,
        "payload": stamped,
    }


def resolve_refresh_url(configured: str, dashboard_url: str) -> str:
    """Point Slack at the Netlify dispatcher when a shared secret is set."""
    secret = (os.getenv("PICKEM_REFRESH_SECRET") or "").strip()
    base = (dashboard_url or "").rstrip("/")
    if secret and base:
        return f"{base}/.netlify/functions/refresh?token={secret}"
    return configured


def _resolve_source(source: Optional[Path], from_web: bool) -> Path:
    if source is not None:
        path = source
    elif from_web:
        path = WEB_RECOMMENDATIONS
    else:
        raise SystemExit("pass --from-web or --from PATH")
    if not path.is_absolute():
        path = project_root() / path
    if not path.is_file():
        raise SystemExit(f"missing {path}")
    return path


def _write_if_changed(path: Path, payload: Mapping[str, Any]) -> bool:
    text = json.dumps(payload, indent=2) + "\n"
    existing = path.read_text() if path.exists() else None
    if existing == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return True


def _write_github_output(name: str, value: str) -> None:
    dest = os.getenv("GITHUB_OUTPUT")
    if not dest:
        return
    with open(dest, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


if __name__ == "__main__":
    sys.exit(main())

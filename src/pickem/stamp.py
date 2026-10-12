"""Single display stamp shared by the dashboard JSON and Slack."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
RUN_ID_ENV = "PICKEM_RUN_ID"
GITHUB_RUN_ID_ENV = "GITHUB_RUN_ID"


def resolve_run_id(explicit: Optional[str] = None) -> str:
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    for key in (RUN_ID_ENV, GITHUB_RUN_ID_ENV):
        value = (os.getenv(key) or "").strip()
        if value:
            return value
    return "local"


def format_updated_stamp(generated_at: str, run_id: str) -> str:
    """Return 'Updated 5:31 PM ET, run 123' from a UTC ISO timestamp."""
    local = _parse_utc(generated_at).astimezone(ET)
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"Updated {hour}:{local.strftime('%M')} {local.strftime('%p')} ET, run {run_id}"


def stamp_payload(
    payload: Mapping[str, Any],
    *,
    run_id: Optional[str] = None,
    generated_at: Optional[str] = None,
    previous: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    out = dict(payload)
    out["run_id"] = resolve_run_id(run_id if run_id is not None else out.get("run_id"))
    if generated_at:
        out["generated_at"] = generated_at
    elif not out.get("generated_at"):
        out["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out["updated_stamp"] = format_updated_stamp(str(out["generated_at"]), str(out["run_id"]))
    if "new_week" not in out:
        out["new_week"] = (not previous) or previous.get("week") != out.get("week")
    pointer = _slack_pointer(previous) if previous and previous.get("week") == out.get("week") else None
    if pointer:
        out["slack"] = pointer
    elif "slack" not in out:
        out["slack"] = None
    return out


def _slack_pointer(previous: Mapping[str, Any]) -> Optional[Dict[str, str]]:
    meta = previous.get("slack")
    if not isinstance(meta, Mapping):
        return None
    ts = str(meta.get("ts") or "").strip()
    if not ts:
        return None
    channel = str(meta.get("channel") or "").strip()
    pointer = {"ts": ts}
    if channel:
        pointer["channel"] = channel
    return pointer


def _parse_utc(value: str) -> datetime:
    text = (value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

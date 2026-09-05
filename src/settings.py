from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "backtest.yaml"


def project_root() -> Path:
    override = os.environ.get("CFB_PICKEM_ROOT")
    if override:
        return Path(override)
    return ROOT


@dataclass(frozen=True)
class ApiKeys:
    cfbd: Optional[str]
    odds: Optional[str]

    @property
    def missing(self) -> List[str]:
        missing: List[str] = []
        if not self.cfbd:
            missing.append("CFBD_API_KEY")
        if not self.odds:
            missing.append("ODDS_API_KEY")
        return missing


def load_env() -> None:
    load_dotenv(project_root() / ".env")
    load_dotenv(ROOT / ".env")


def get_api_keys() -> ApiKeys:
    load_env()
    return ApiKeys(
        cfbd=os.getenv("CFBD_API_KEY") or None,
        odds=os.getenv("ODDS_API_KEY") or None,
    )


def load_backtest_config() -> Dict[str, Any]:
    config_path = project_root() / "config" / "backtest.yaml"
    if not config_path.exists():
        config_path = CONFIG_PATH
    with config_path.open() as handle:
        return yaml.safe_load(handle)


def load_experiment_config(name: str = "late_line") -> Dict[str, Any]:
    """V1 backtest.yaml plus experiment overlay. Overlay lists replace, dicts merge."""
    base = load_backtest_config()
    filename = {
        "late_line": "experiment_late_line.yaml",
    }.get(name)
    if filename is None:
        raise ValueError(f"Unknown experiment {name!r}")
    overlay_path = project_root() / "config" / filename
    if not overlay_path.exists():
        overlay_path = ROOT / "config" / filename
    with overlay_path.open() as handle:
        overlay = yaml.safe_load(handle) or {}
    return _deep_merge(base, overlay)


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(base)
    for key, value in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_pickem_config(path: Optional[Path] = None) -> Dict[str, Any]:
    config_path = path or (project_root() / "config" / "pickem.yaml")
    with config_path.open() as handle:
        return yaml.safe_load(handle)


def resolve_paths(config: Optional[Dict[str, Any]] = None) -> Dict[str, Path]:
    cfg = config or load_backtest_config()
    root = project_root()
    paths = cfg["paths"]
    return {
        "root": root,
        "raw_odds": root / paths["raw_odds"],
        "raw_cfbd": root / paths["raw_cfbd"],
        "processed": root / paths["processed"],
        "outputs": root / paths["outputs"],
        "snapshots": root / paths["raw_odds"] / "snapshots",
        "request_log": root / paths["raw_odds"] / "request_log.jsonl",
    }

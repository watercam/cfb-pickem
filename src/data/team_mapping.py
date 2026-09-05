"""Resolve Odds API and CFBD team names onto a canonical join key.

Never auto-fuzzy-match below the configured confidence threshold.
Fuzzy matching is disabled for V1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

from src.settings import load_backtest_config, project_root


@dataclass(frozen=True)
class TeamAlias:
    canonical_team: str
    odds_api_team: str
    cfbd_team: str
    espn_team: str


def load_aliases(path: Optional[Path] = None) -> List[TeamAlias]:
    config = load_backtest_config()
    aliases_file = path or project_root() / config["team_mapping"]["aliases_file"]
    with aliases_file.open() as handle:
        payload = yaml.safe_load(handle) or {}
    rows = []
    for item in payload.get("aliases", []):
        canonical = str(item["canonical_team"])
        rows.append(
            TeamAlias(
                canonical_team=canonical,
                odds_api_team=str(item["odds_api_team"]),
                cfbd_team=str(item["cfbd_team"]),
                espn_team=str(item["espn_team"]) if item.get("espn_team") else canonical,
            )
        )
    return rows


def build_alias_indexes(
    aliases: Optional[Iterable[TeamAlias]] = None,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    rows = list(aliases) if aliases is not None else load_aliases()
    cfbd_to_canonical = {}
    odds_to_canonical = {}
    for row in rows:
        cfbd_to_canonical[row.cfbd_team] = row.canonical_team
        odds_to_canonical[row.odds_api_team] = row.canonical_team
        cfbd_to_canonical[row.canonical_team] = row.canonical_team
        odds_to_canonical[row.canonical_team] = row.canonical_team
    return cfbd_to_canonical, odds_to_canonical


def build_espn_index(
    aliases: Optional[Iterable[TeamAlias]] = None,
) -> Dict[str, str]:
    rows = list(aliases) if aliases is not None else load_aliases()
    espn_to_canonical: Dict[str, str] = {}
    for row in rows:
        espn_to_canonical[row.espn_team] = row.canonical_team
        espn_to_canonical[row.canonical_team] = row.canonical_team
    return espn_to_canonical


def canonicalize(
    name: Optional[str],
    source: str,
    *,
    aliases: Optional[Iterable[TeamAlias]] = None,
    enable_fuzzy: bool = False,
) -> Optional[str]:
    if not name:
        return None
    cfbd_map, odds_map = build_alias_indexes(aliases)
    if source == "espn":
        table = build_espn_index(aliases)
    elif source == "cfbd":
        table = cfbd_map
    else:
        table = odds_map
    if name in table:
        return table[name]
    if enable_fuzzy:
        raise NotImplementedError("Fuzzy team matching is disabled for V1")
    return None


def map_or_none(name: Optional[str], source: str, **kwargs: Any) -> Optional[str]:
    mapped = canonicalize(name, source, **kwargs)
    if mapped:
        return mapped
    if name:
        # Exact string equality across sources is an allowed join key.
        return None
    return None


def exact_or_alias(
    name: Optional[str],
    source: str,
    *,
    aliases: Optional[Iterable[TeamAlias]] = None,
    enable_fuzzy: bool = False,
) -> Optional[str]:
    if not name:
        return None
    mapped = canonicalize(name, source, aliases=aliases, enable_fuzzy=enable_fuzzy)
    if mapped:
        return mapped
    cfbd_map, odds_map = build_alias_indexes(aliases)
    espn_map = build_espn_index(aliases)
    if source == "espn":
        other_values = list(espn_map.values())
        if name in other_values or name in espn_map:
            return name
    else:
        other = odds_map if source == "cfbd" else cfbd_map
        if name in other.values() or name in cfbd_map or name in odds_map:
            return name
    return name if _is_self_canonical(name, aliases) else None


def _is_self_canonical(name: str, aliases: Optional[Iterable[TeamAlias]]) -> bool:
    rows = list(aliases) if aliases is not None else load_aliases()
    known = {row.canonical_team for row in rows}
    known.update(row.cfbd_team for row in rows)
    known.update(row.odds_api_team for row in rows)
    known.update(row.espn_team for row in rows)
    if name in known:
        return True
    # Unlisted names may still match if both sources use the identical string.
    return False


def resolve_pair(
    cfbd_name: Optional[str],
    odds_name: Optional[str],
    *,
    aliases: Optional[Iterable[TeamAlias]] = None,
) -> Optional[str]:
    cfbd_map, odds_map = build_alias_indexes(aliases)
    if cfbd_name and cfbd_name in cfbd_map:
        return cfbd_map[cfbd_name]
    if odds_name and odds_name in odds_map:
        return odds_map[odds_name]
    if cfbd_name and odds_name and cfbd_name == odds_name:
        return cfbd_name
    if cfbd_name and cfbd_name in odds_map:
        return odds_map[cfbd_name]
    if odds_name and odds_name in cfbd_map:
        return cfbd_map[odds_name]
    return None

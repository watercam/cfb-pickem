"""Resolve Odds API and CFBD team names onto a canonical join key.

Never auto-fuzzy-match below the configured confidence threshold.
Fuzzy matching is disabled for V1.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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


# Tokens that distinguish two schools that share a prefix (Kansas vs Kansas State).
_SCHOOL_QUALIFIERS = frozenset(
    {
        "state",
        "tech",
        "a&m",
        "am",
        "and",
        "international",
        "college",
        "university",
        "univ",
        "martin",
        "oh",
        "ohio",
        "fl",
        "a",
        "m",
    }
)

# Unique, commonly scraped abbreviations. Ambiguous ones (OSU, MSU, UT) are omitted.
_EXPLICIT_ABBREVS = {
    "asu": "Arizona State",
    "fsu": "Florida State",
    "ou": "Oklahoma",
    "tamu": "Texas A&M",
    "pitt": "Pittsburgh",
    "cal": "California",
    "bama": "Alabama",
    "olemiss": "Ole Miss",
    "missst": "Mississippi State",
    "msst": "Mississippi State",
    "kstate": "Kansas State",
    "k-state": "Kansas State",
    "okst": "Oklahoma State",
    "okstate": "Oklahoma State",
    "appst": "App State",
    "appstate": "App State",
    "nd": "Notre Dame",
    "psu": "Penn State",
    "wazzou": "Washington State",
    "wazu": "Washington State",
}

_TOKEN_SYNONYMS = {
    "app": "appalachian",
    "appalachian": "app",
    "miss": "mississippi",
    "oh": "ohio",
}


def normalize_team_key(name: Optional[str]) -> str:
    """Deterministic school-name key: St./State, punctuation, case. Not fuzzy."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[/'’]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [tok for tok in text.split() if tok]
    out: List[str] = []
    last = len(tokens) - 1
    for index, token in enumerate(tokens):
        if token in {"st", "saint"}:
            out.append("saint" if index == 0 else "state")
            continue
        if token in {"mt", "mount"}:
            out.append("mount")
            continue
        if token in {"the", "univ", "university"} and 0 < index < last:
            continue
        out.append(token)
    return " ".join(out)


def compact_team_key(name: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_team_key(name))


def pair_odds_sides_for_espn(
    espn_home: Optional[str],
    espn_away: Optional[str],
    odds_home: Optional[str],
    odds_away: Optional[str],
    *,
    aliases: Optional[Iterable[TeamAlias]] = None,
) -> Optional[Tuple[str, str]]:
    """Map ESPN home/away onto the book's team strings by name.

    Returns (odds_name_for_espn_home, odds_name_for_espn_away). None if either
    side is missing, ambiguous, or both ESPN names collapse onto one book team.
    Never infers a swap from home/away slots.
    """
    if not espn_home or not espn_away or not odds_home or not odds_away:
        return None
    if espn_home == espn_away or odds_home == odds_away:
        return None
    index = TeamNameIndex(aliases)
    home_odds = index.match_unique(espn_home, (odds_home, odds_away))
    away_odds = index.match_unique(espn_away, (odds_home, odds_away))
    if home_odds is None or away_odds is None or home_odds == away_odds:
        return None
    return home_odds, away_odds


class TeamNameIndex:
    """Resolve team strings using aliases plus conservative normalization."""

    def __init__(self, aliases: Optional[Iterable[TeamAlias]] = None) -> None:
        self.rows = list(aliases) if aliases is not None else load_aliases()
        self._canonical_by_key: Dict[str, str] = {}
        self._mascots: List[str] = []
        self._build()

    def resolve(self, name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        for source in ("espn", "odds", "cfbd"):
            mapped = canonicalize(name, source, aliases=self.rows)
            if mapped:
                return mapped
        compact = compact_team_key(name)
        if compact in _EXPLICIT_ABBREVS:
            return _EXPLICIT_ABBREVS[compact]
        key = normalize_team_key(name)
        if key in self._canonical_by_key:
            return self._canonical_by_key[key]
        core = self.core_key(name)
        if core in self._canonical_by_key:
            return self._canonical_by_key[core]
        if compact in self._canonical_by_key:
            return self._canonical_by_key[compact]
        return None

    def same_team(self, left: Optional[str], right: Optional[str]) -> bool:
        if not left or not right:
            return False
        if left == right:
            return True
        resolved_left = self.resolve(left)
        resolved_right = self.resolve(right)
        if resolved_left and resolved_right:
            return resolved_left == resolved_right
        return bool(self.core_key(left) and self.core_key(left) == self.core_key(right))

    def match_unique(self, query: str, candidates: Sequence[str]) -> Optional[str]:
        hits = [candidate for candidate in candidates if self.same_team(query, candidate)]
        if len(hits) > 1:
            return None
        if len(hits) == 1:
            return hits[0]
        compact = compact_team_key(query)
        if not compact:
            return None
        abbrev_hits = [
            candidate
            for candidate in candidates
            if compact in self._abbreviation_keys(candidate)
        ]
        if len(abbrev_hits) == 1:
            return abbrev_hits[0]
        return None

    def core_key(self, name: Optional[str]) -> str:
        key = normalize_team_key(name)
        for mascot in self._mascots:
            suffix = f" {mascot}"
            if key.endswith(suffix):
                return key[: -len(suffix)]
        return key

    def _abbreviation_keys(self, name: str) -> set[str]:
        keys = {compact_team_key(name)}
        resolved = self.resolve(name)
        if resolved:
            keys.add(compact_team_key(resolved))
            for abbrev, canonical in _EXPLICIT_ABBREVS.items():
                if canonical == resolved:
                    keys.add(abbrev)
        core = self.core_key(name)
        tokens = [tok for tok in core.split() if tok not in {"and", "the"}]
        if tokens:
            initials = "".join(tok[0] for tok in tokens)
            keys.add(initials)
            if len(tokens) >= 2:
                keys.add(initials + "u")
        return {key for key in keys if key}

    def _build(self) -> None:
        buckets: Dict[str, set[str]] = {}
        mascots: set[str] = set()

        def add_key(key: str, canonical: str) -> None:
            if not key:
                return
            buckets.setdefault(key, set()).add(canonical)

        for row in self.rows:
            names = (
                row.canonical_team,
                row.odds_api_team,
                row.cfbd_team,
                row.espn_team,
            )
            for raw in names:
                for variant in _name_variants(raw):
                    add_key(variant, row.canonical_team)
                    add_key(compact_team_key(variant), row.canonical_team)
            for mascot in _mascot_from_row(row):
                mascots.add(mascot)
        self._mascots = sorted(mascots, key=len, reverse=True)
        for row in self.rows:
            for raw in (row.odds_api_team, row.cfbd_team, row.espn_team, row.canonical_team):
                core = self.core_key(raw)
                add_key(core, row.canonical_team)
                for variant in _name_variants(core):
                    add_key(variant, row.canonical_team)
        unique: Dict[str, str] = {}
        for key, canonicals in buckets.items():
            if len(canonicals) == 1:
                unique[key] = next(iter(canonicals))
        self._canonical_by_key = unique


def _name_variants(name: Optional[str]) -> set[str]:
    key = normalize_team_key(name)
    if not key:
        return set()
    variants = {key}
    tokens = key.split()
    swapped = [_TOKEN_SYNONYMS.get(tok, tok) for tok in tokens]
    variants.add(" ".join(swapped))
    return {item for item in variants if item}


def _mascot_from_row(row: TeamAlias) -> List[str]:
    odds_key = normalize_team_key(row.odds_api_team)
    mascots: List[str] = []
    for base in _name_variants(row.canonical_team) | _name_variants(row.cfbd_team) | _name_variants(row.espn_team):
        prefix = f"{base} "
        if odds_key.startswith(prefix):
            extra = odds_key[len(prefix) :]
            extra_tokens = extra.split()
            if extra and not any(tok in _SCHOOL_QUALIFIERS for tok in extra_tokens):
                mascots.append(extra)
    return mascots

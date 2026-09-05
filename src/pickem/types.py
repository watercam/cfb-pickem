"""Weekly Pick'em value types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


UNMAPPED_TEAM = "UNMAPPED_TEAM"
PINNACLE_MISSING = "PINNACLE_MISSING"
NO_CURRENT_ML = "NO_CURRENT_ML"
REFERENCE_MISSING = "REFERENCE_MISSING"


@dataclass(frozen=True)
class SlateGame:
    game_id: str
    away_espn: str
    home_espn: str
    kickoff: datetime
    public_away_pct: Optional[float] = None
    public_home_pct: Optional[float] = None
    week: Optional[int] = None


@dataclass
class SideScore:
    espn_name: str
    canonical: str
    is_home: bool
    p_current: float
    spread_move: float
    pinnacle_spread: Optional[float]
    adj: float
    p_final: float


@dataclass
class GameRecommendation:
    game_id: str
    week: Optional[int]
    home_espn: str
    away_espn: str
    pick: Optional[str]
    opponent: Optional[str]
    is_home_pick: bool
    confidence: Optional[int]
    p_current: Optional[float]
    spread_move: Optional[float]
    pinnacle_spread: Optional[float]
    adj: Optional[float]
    p_final: Optional[float]
    flags: List[str] = field(default_factory=list)
    public_pick_pct: Optional[float] = None
    kickoff: Optional[datetime] = None


@dataclass
class PickemResult:
    week: Optional[int]
    calibration_source: str
    games: List[GameRecommendation]

"""Pick the favorite by clamped p_final and assign unique confidence 10..1."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional, Sequence

import pandas as pd

from src.data.team_mapping import load_aliases
from src.pickem.calibration import MovementCalibrator
from src.pickem.odds import (
    current_event_home_away,
    features_for_side,
    match_event_snapshots,
    missing_current_flags,
    resolve_espn_pair,
)
from src.pickem.types import (
    NO_CURRENT_ML,
    PINNACLE_MISSING,
    UNMAPPED_TEAM,
    GameRecommendation,
    PickemResult,
    SideScore,
    SlateGame,
)


def recommend_slate(
    games: Sequence[SlateGame],
    snapshots: pd.DataFrame,
    *,
    now: datetime,
    calibrator: MovementCalibrator,
    reference_hours: int,
    confidence_points: int = 10,
    week: Optional[int] = None,
) -> PickemResult:
    aliases = load_aliases()
    scored = [
        score_game(
            game,
            snapshots,
            now=now,
            calibrator=calibrator,
            reference_hours=reference_hours,
            aliases=aliases,
        )
        for game in games
    ]
    ranked = assign_confidence(scored, confidence_points=confidence_points)
    return PickemResult(
        week=week if week is not None else _first_week(games),
        calibration_source=calibrator.source,
        games=ranked,
    )


def score_game(
    game: SlateGame,
    snapshots: pd.DataFrame,
    *,
    now: datetime,
    calibrator: MovementCalibrator,
    reference_hours: int,
    aliases=None,
) -> GameRecommendation:
    alias_rows = aliases if aliases is not None else load_aliases()
    home_c, away_c, flags = resolve_espn_pair(game, alias_rows)
    event_snaps = match_event_snapshots(
        snapshots,
        game,
        home_canonical=home_c,
        away_canonical=away_c,
        aliases=alias_rows,
    )
    if (home_c is None or away_c is None) and not event_snaps.empty:
        # Exact ESPN string match against Pinnacle names (not fuzzy).
        flags = [flag for flag in flags if flag != UNMAPPED_TEAM]
    elif home_c is None or away_c is None:
        return _failed(game, flags or [UNMAPPED_TEAM])
    if event_snaps.empty:
        if UNMAPPED_TEAM in flags:
            return _failed(game, flags)
        return _failed(game, flags + [PINNACLE_MISSING])

    odds_home, odds_away = current_event_home_away(event_snaps, now, game.kickoff)
    home_features = features_for_side(
        event_snaps,
        team=odds_home,
        opponent=odds_away,
        home_team=odds_home,
        away_team=odds_away,
        now=now,
        kickoff=game.kickoff,
        reference_hours=reference_hours,
    )
    away_features = features_for_side(
        event_snaps,
        team=odds_away,
        opponent=odds_home,
        home_team=odds_home,
        away_team=odds_away,
        now=now,
        kickoff=game.kickoff,
        reference_hours=reference_hours,
    )
    data_flags = missing_current_flags(home_features, event_snaps)
    if NO_CURRENT_ML in data_flags or PINNACLE_MISSING in data_flags:
        return _failed(game, flags + data_flags)

    home_score = _side_score(
        espn_name=game.home_espn,
        canonical=home_c or game.home_espn,
        is_home=True,
        features=home_features,
        calibrator=calibrator,
    )
    away_score = _side_score(
        espn_name=game.away_espn,
        canonical=away_c or game.away_espn,
        is_home=False,
        features=away_features,
        calibrator=calibrator,
    )
    chosen = _argmax_side(home_score, away_score, game.game_id)
    other = away_score if chosen is home_score else home_score
    public = game.public_home_pct if chosen.is_home else game.public_away_pct
    return GameRecommendation(
        game_id=game.game_id,
        week=game.week,
        home_espn=game.home_espn,
        away_espn=game.away_espn,
        pick=chosen.espn_name,
        opponent=other.espn_name,
        is_home_pick=chosen.is_home,
        confidence=None,
        p_current=chosen.p_current,
        spread_move=chosen.spread_move,
        pinnacle_spread=chosen.pinnacle_spread,
        adj=chosen.adj,
        p_final=chosen.p_final,
        flags=flags + data_flags,
        public_pick_pct=public,
        kickoff=game.kickoff,
    )


def _side_score(*, espn_name, canonical, is_home, features, calibrator: MovementCalibrator) -> SideScore:
    p_current = float(features["current_probability"])
    move = features.get("spread_move")
    spread_move = 0.0 if move is None or pd.isna(move) else float(move)
    raw_spread = features.get("current_spread")
    pinnacle_spread = None if raw_spread is None or pd.isna(raw_spread) else float(raw_spread)
    adj = calibrator.movement_adjustment(p_current, spread_move)
    p_final = calibrator.clamp(p_current + adj)
    return SideScore(
        espn_name=espn_name,
        canonical=canonical,
        is_home=is_home,
        p_current=p_current,
        spread_move=spread_move,
        pinnacle_spread=pinnacle_spread,
        adj=adj,
        p_final=p_final,
    )


def _argmax_side(home: SideScore, away: SideScore, game_id: str) -> SideScore:
    def key(side: SideScore) -> tuple:
        return (side.p_final, side.p_current, side.is_home, game_id)

    return home if key(home) >= key(away) else away


def assign_confidence(
    games: Sequence[GameRecommendation],
    *,
    confidence_points: int = 10,
) -> List[GameRecommendation]:
    playable = [game for game in games if game.p_final is not None and game.pick]
    failed = [game for game in games if game.p_final is None or not game.pick]
    ordered = sorted(
        playable,
        key=lambda game: (
            -(game.p_final or 0.0),
            -(game.p_current or 0.0),
            not game.is_home_pick,
            game.game_id,
        ),
    )
    top = min(confidence_points, len(ordered))
    for index, game in enumerate(ordered):
        if index < top:
            game.confidence = confidence_points - index
        else:
            game.confidence = None
    by_id = {game.game_id: game for game in ordered + failed}
    return [by_id[game.game_id] for game in games]


def _failed(game: SlateGame, flags: Iterable[str]) -> GameRecommendation:
    return GameRecommendation(
        game_id=game.game_id,
        week=game.week,
        home_espn=game.home_espn,
        away_espn=game.away_espn,
        pick=None,
        opponent=None,
        is_home_pick=False,
        confidence=None,
        p_current=None,
        spread_move=None,
        pinnacle_spread=None,
        adj=None,
        p_final=None,
        flags=list(dict.fromkeys(flags)),
        public_pick_pct=None,
        kickoff=game.kickoff,
    )


def _first_week(games: Sequence[SlateGame]) -> Optional[int]:
    for game in games:
        if game.week is not None:
            return game.week
    return None

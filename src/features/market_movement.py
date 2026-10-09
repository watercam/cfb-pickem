"""Spread, moneyline, and snapshot-as-of features for V1.

Positive spread_move is always favorable to the selected team:
spread_move = spread_reference - spread_current
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import pandas as pd


def american_to_implied(odds: float) -> float:
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


def no_vig_probability(team_odds: float, opponent_odds: float) -> float:
    p_team = american_to_implied(team_odds)
    p_opp = american_to_implied(opponent_odds)
    return p_team / (p_team + p_opp)


def spread_move(spread_reference: float, spread_current: float) -> float:
    return float(spread_reference) - float(spread_current)


def team_spread_from_home(home_spread: float, *, is_home: bool) -> float:
    return float(home_spread) if is_home else -float(home_spread)


def pick_snapshot_at_or_before(
    timestamps: Iterable[datetime],
    target: datetime,
    *,
    earliest: Optional[datetime] = None,
) -> Optional[datetime]:
    """Latest timestamp that is still <= target. Never returns a later stamp.

    If earliest is set, timestamps at or before that bound are ignored. Used so
    a 1-hour clock cannot silently substitute the 24-hour Pinnacle line.
    """
    target_utc = _as_utc(target)
    eligible = [ts for ts in timestamps if _as_utc(ts) <= target_utc]
    if earliest is not None:
        earliest_utc = _as_utc(earliest)
        eligible = [ts for ts in eligible if _as_utc(ts) > earliest_utc]
    if not eligible:
        return None
    return max(eligible, key=_as_utc)


def assign_interval_label(value: float, specs: Sequence[Mapping[str, Any]]) -> str:
    for spec in specs:
        lo = float(spec["min"])
        hi = float(spec["max"])
        if spec.get("right_closed"):
            if lo <= value <= hi:
                return str(spec["label"])
        elif lo <= value < hi:
            return str(spec["label"])
    return ""


def _as_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def team_features_from_snapshots(
    snapshots: pd.DataFrame,
    *,
    decision_ts: datetime,
    reference_ts: datetime,
    team: str,
    opponent: str,
    home_team: str,
    away_team: str,
    current_earliest_ts: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build V1 market features from snapshots at or before the decision time.

    Later-than-decision rows are ignored. Game results are not accepted.
    current_earliest_ts, if set, blocks substituting an older horizon's price.
    """
    if snapshots is None or snapshots.empty:
        return _empty_features()

    frame = snapshots.copy()
    frame["snapshot_ts"] = pd.to_datetime(frame["snapshot_ts"], utc=True)
    decision = _as_utc(decision_ts)
    reference = _as_utc(reference_ts)
    usable = frame.loc[frame["snapshot_ts"] <= pd.Timestamp(decision)].copy()
    if usable.empty:
        return _empty_features()

    current_ts = pick_snapshot_at_or_before(
        usable["snapshot_ts"].tolist(),
        decision,
        earliest=current_earliest_ts,
    )
    reference_pool = usable.loc[usable["snapshot_ts"] <= pd.Timestamp(reference)]
    reference_chosen = pick_snapshot_at_or_before(
        reference_pool["snapshot_ts"].tolist(),
        reference,
    )
    if team == home_team:
        is_home: Optional[bool] = True
    elif team == away_team:
        is_home = False
    else:
        is_home = None
    current_row = _row_at(usable, current_ts)
    reference_row = _row_at(reference_pool, reference_chosen)
    if is_home is None:
        current_spread, current_spread_price = None, None
        reference_spread, reference_spread_price = None, None
    else:
        current_spread, current_spread_price = _team_spread(current_row, team, is_home)
        reference_spread, reference_spread_price = _team_spread(reference_row, team, is_home)
    current_ml, opp_ml = _team_moneylines(current_row, team, opponent)
    reference_ml, reference_opp_ml = _team_moneylines(reference_row, team, opponent)
    current_p = (
        no_vig_probability(current_ml, opp_ml)
        if current_ml is not None and opp_ml is not None
        else None
    )
    reference_p = (
        no_vig_probability(reference_ml, reference_opp_ml)
        if reference_ml is not None and reference_opp_ml is not None
        else None
    )
    move = (
        spread_move(reference_spread, current_spread)
        if reference_spread is not None and current_spread is not None
        else None
    )
    return {
        "current_timestamp": current_ts,
        "reference_timestamp": reference_chosen,
        "current_spread": current_spread,
        "reference_spread": reference_spread,
        "current_spread_price": current_spread_price,
        "reference_spread_price": reference_spread_price,
        "current_moneyline": current_ml,
        "reference_moneyline": reference_ml,
        "current_probability": current_p,
        "reference_probability": reference_p,
        "spread_move": move,
        "home_team": home_team,
        "away_team": away_team,
    }


def _empty_features() -> Dict[str, Any]:
    return {
        "current_timestamp": None,
        "reference_timestamp": None,
        "current_spread": None,
        "reference_spread": None,
        "current_spread_price": None,
        "reference_spread_price": None,
        "current_moneyline": None,
        "reference_moneyline": None,
        "current_probability": None,
        "reference_probability": None,
        "spread_move": None,
        "home_team": None,
        "away_team": None,
    }


def _row_at(frame: pd.DataFrame, ts: Optional[datetime]) -> Optional[pd.Series]:
    if ts is None or frame.empty:
        return None
    matched = frame.loc[frame["snapshot_ts"] == pd.Timestamp(_as_utc(ts))]
    if matched.empty:
        return None
    return matched.iloc[-1]


def _team_spread(
    row: Optional[pd.Series],
    team: str,
    is_home: bool,
) -> tuple[Optional[float], Optional[int]]:
    if row is None:
        return None, None
    if "home_spread" in row.index and pd.notna(row.get("home_spread")):
        spread = team_spread_from_home(float(row["home_spread"]), is_home=is_home)
        price_key = "home_spread_price" if is_home else "away_spread_price"
        price = row.get(price_key)
        return spread, int(price) if pd.notna(price) else None
    return None, None


def _team_moneylines(
    row: Optional[pd.Series],
    team: str,
    opponent: str,
) -> tuple[Optional[int], Optional[int]]:
    if row is None:
        return None, None
    home_ml = row.get("home_moneyline")
    away_ml = row.get("away_moneyline")
    home_team = row.get("home_team_odds") or row.get("home_team")
    away_team = row.get("away_team_odds") or row.get("away_team")
    if pd.isna(home_ml) or pd.isna(away_ml):
        return None, None
    if team == home_team:
        return int(home_ml), int(away_ml)
    if team == away_team:
        return int(away_ml), int(home_ml)
    return None, None


def assert_no_lookahead(
    current_timestamp: datetime,
    reference_timestamp: datetime,
    decision_target: datetime,
    reference_target: datetime,
) -> None:
    if _as_utc(current_timestamp) > _as_utc(decision_target):
        raise AssertionError("current_timestamp is after the decision target")
    if _as_utc(reference_timestamp) > _as_utc(reference_target):
        raise AssertionError("reference_timestamp is after the reference target")

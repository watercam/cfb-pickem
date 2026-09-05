"""Join odds snapshots to CFBD results into one row per game × team.

Must not include post-decision odds in model features.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pandas as pd

from src.data.team_mapping import build_alias_indexes, load_aliases
from src.features.market_movement import (
    assign_interval_label,
    pick_snapshot_at_or_before,
    team_features_from_snapshots,
)
from src.settings import load_backtest_config, resolve_paths

EXCL_NOT_FBS = "NOT_FBS_VS_FBS"
EXCL_CANCELLED = "CANCELLED"
EXCL_NO_FINAL = "NO_FINAL_RESULT"
EXCL_TEAM_UNMAPPED = "TEAM_UNMAPPED"
EXCL_ALREADY_STARTED = "ALREADY_STARTED"
EXCL_MISSING_DECISION = "MISSING_DECISION_SNAPSHOT"
EXCL_MISSING_REFERENCE = "MISSING_REFERENCE_SNAPSHOT"
EXCL_PINNACLE_MISSING = "PINNACLE_MISSING"
EXCL_MISSING_ML = "MISSING_CURRENT_MONEYLINE"
EXCL_MISSING_SPREAD = "MISSING_SPREAD"
EXCL_LOOKAHEAD = "LOOKAHEAD_GUARD"
EXCL_MISSING_1H_SNAPSHOT = "MISSING_1H_SNAPSHOT"
EXCL_MISSING_1H_ML = "MISSING_1H_MONEYLINE"

KICKOFF_MATCH_HOURS = 18


def build_dataset(
    games: Optional[pd.DataFrame] = None,
    snapshots: Optional[pd.DataFrame] = None,
    *,
    config: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    cfg = config or load_backtest_config()
    paths = resolve_paths(cfg)
    processed = paths["processed"]
    if games is None:
        games = pd.read_parquet(processed / "games.parquet")
    if snapshots is None:
        snapshots = pd.read_parquet(processed / "odds_snapshots.parquet")

    aliases = load_aliases()
    cfbd_map, odds_map = build_alias_indexes(aliases)
    unmatched: List[Dict[str, str]] = []
    snapshot_index = _index_snapshots(snapshots, odds_map)

    rows: List[Dict[str, Any]] = []
    updated_games = []
    for game in games.itertuples(index=False):
        game_dict = game._asdict() if hasattr(game, "_asdict") else dict(game._asdict())
        row_pair, unmatched_names, game_update = _rows_for_game(
            game_dict, snapshot_index, cfg, cfbd_map, odds_map
        )
        rows.extend(row_pair)
        unmatched.extend(unmatched_names)
        updated_games.append(game_update)

    dataset = pd.DataFrame(rows)
    if dataset.empty:
        dataset = pd.DataFrame(columns=_dataset_columns())
    else:
        dataset = dataset[_dataset_columns()]

    outputs = paths["outputs"]
    outputs.mkdir(parents=True, exist_ok=True)
    if unmatched:
        pd.DataFrame(unmatched).drop_duplicates().to_csv(
            outputs / "unmatched_teams.csv", index=False
        )

    games_out = pd.DataFrame(updated_games)
    if not games_out.empty:
        games_out.to_parquet(processed / "games.parquet", index=False)
    processed.mkdir(parents=True, exist_ok=True)
    dataset.to_parquet(processed / "backtest_dataset.parquet", index=False)
    return dataset


def build_horizon_dataset(
    games: Optional[pd.DataFrame] = None,
    snapshots: Optional[pd.DataFrame] = None,
    *,
    config: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """One row per game × team × decision clock (24h and 1h). Does not write V1 parquet."""
    cfg = config or load_backtest_config()
    paths = resolve_paths(cfg)
    processed = paths["processed"]
    if games is None:
        games = pd.read_parquet(processed / "games.parquet")
    if snapshots is None:
        snapshots = pd.read_parquet(processed / "odds_snapshots.parquet")

    aliases = load_aliases()
    cfbd_map, odds_map = build_alias_indexes(aliases)
    snapshot_index = _index_snapshots(snapshots, odds_map)
    clocks = cfg.get("clocks") or {
        "S": {"decision_horizon_hours": 24, "reference_horizon_hours": 72},
        "L": {"decision_horizon_hours": 1, "reference_horizon_hours": 24},
    }
    clock_specs = [
        {
            "decision_h": int(clocks["S"]["decision_horizon_hours"]),
            "reference_h": int(clocks["S"]["reference_horizon_hours"]),
            "current_earliest_hours": None,
            "missing_current_code": EXCL_MISSING_DECISION,
            "missing_ml_code": EXCL_MISSING_ML,
        },
        {
            "decision_h": int(clocks["L"]["decision_horizon_hours"]),
            "reference_h": int(clocks["L"]["reference_horizon_hours"]),
            "current_earliest_hours": int(clocks["S"]["decision_horizon_hours"]),
            "missing_current_code": EXCL_MISSING_1H_SNAPSHOT,
            "missing_ml_code": EXCL_MISSING_1H_ML,
        },
    ]

    rows: List[Dict[str, Any]] = []
    unmatched: List[Dict[str, str]] = []
    for game in games.itertuples(index=False):
        game_dict = game._asdict() if hasattr(game, "_asdict") else dict(game)
        for clock in clock_specs:
            row_pair, unmatched_names, _game_update = _rows_for_game(
                game_dict,
                snapshot_index,
                cfg,
                cfbd_map,
                odds_map,
                decision_h=clock["decision_h"],
                reference_h=clock["reference_h"],
                current_earliest_hours=clock["current_earliest_hours"],
                missing_current_code=clock["missing_current_code"],
                missing_ml_code=clock["missing_ml_code"],
            )
            rows.extend(row_pair)
            unmatched.extend(unmatched_names)

    dataset = pd.DataFrame(rows)
    if dataset.empty:
        dataset = pd.DataFrame(columns=_horizon_dataset_columns())
    else:
        dataset = _attach_cross_horizon_fields(dataset)
        extra = [c for c in _horizon_dataset_columns() if c not in dataset.columns]
        for col in extra:
            dataset[col] = None
        dataset = dataset[_horizon_dataset_columns()]

    outputs = paths["outputs"]
    outputs.mkdir(parents=True, exist_ok=True)
    if unmatched:
        pd.DataFrame(unmatched).drop_duplicates().to_csv(
            outputs / "unmatched_teams.csv", index=False
        )
    return dataset


def _attach_cross_horizon_fields(dataset: pd.DataFrame) -> pd.DataFrame:
    out = dataset.copy()
    key = ["game_id", "team"]
    clock24 = out.loc[out["decision_horizon_hours"] == 24, key + [
        "current_probability",
        "current_spread",
        "current_timestamp",
        "spread_move",
    ]].rename(
        columns={
            "current_probability": "p_24",
            "current_spread": "spread_24",
            "current_timestamp": "ts_24",
            "spread_move": "spread_move_72_24",
        }
    )
    clock1 = out.loc[out["decision_horizon_hours"] == 1, key + [
        "current_probability",
        "current_spread",
        "current_timestamp",
        "spread_move",
    ]].rename(
        columns={
            "current_probability": "p_1h",
            "current_spread": "spread_1h",
            "current_timestamp": "ts_1h",
            "spread_move": "spread_move_24_1h",
        }
    )
    out = out.merge(clock24, on=key, how="left")
    out = out.merge(clock1, on=key, how="left")
    missing_1h = out["decision_horizon_hours"].eq(24) & out["p_1h"].isna()
    extra = EXCL_MISSING_1H_SNAPSHOT
    flag = out["data_quality_flag"].fillna("").astype(str)
    out.loc[missing_1h & (flag == ""), "data_quality_flag"] = extra
    out.loc[missing_1h & (flag != ""), "data_quality_flag"] = flag[missing_1h & (flag != "")] + ";" + extra
    return out


def _rows_for_game(
    game: Dict[str, Any],
    snapshot_index: List[Dict[str, Any]],
    cfg: Dict[str, Any],
    cfbd_map: Dict[str, str],
    odds_map: Dict[str, str],
    *,
    decision_h: Optional[int] = None,
    reference_h: Optional[int] = None,
    current_earliest_hours: Optional[int] = None,
    missing_current_code: str = EXCL_MISSING_DECISION,
    missing_ml_code: str = EXCL_MISSING_ML,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]], Dict[str, Any]]:
    mvp = cfg["mvp"]
    decision_h = int(mvp["decision_horizon_hours"] if decision_h is None else decision_h)
    reference_h = int(mvp["reference_horizon_hours"] if reference_h is None else reference_h)
    kickoff = pd.to_datetime(game["kickoff_timestamp"], utc=True)
    reasons = _split_reasons(game.get("exclusion_reasons"))
    unmatched: List[Dict[str, str]] = []

    home_cfbd = game.get("home_team_cfbd")
    away_cfbd = game.get("away_team_cfbd")
    event, home_canonical, away_canonical = _match_event(
        game, snapshot_index, cfbd_map, odds_map
    )
    if home_canonical and away_canonical:
        reasons = [r for r in reasons if r != EXCL_TEAM_UNMAPPED]
    if home_canonical is None and home_cfbd:
        unmatched.append({"raw_name": str(home_cfbd), "source": "cfbd"})
    if away_canonical is None and away_cfbd:
        unmatched.append({"raw_name": str(away_cfbd), "source": "cfbd"})
    if event is None:
        if EXCL_TEAM_UNMAPPED not in reasons and (home_canonical is None or away_canonical is None):
            reasons.append(EXCL_TEAM_UNMAPPED)
        if home_canonical and away_canonical:
            reasons.append(missing_current_code)
            reasons.append(EXCL_MISSING_REFERENCE)
        rows = [
            _blank_team_row(
                game,
                home_canonical or home_cfbd,
                away_canonical or away_cfbd,
                "home",
                reasons,
                cfg,
                decision_h=decision_h,
                reference_h=reference_h,
            ),
            _blank_team_row(
                game,
                away_canonical or away_cfbd,
                home_canonical or home_cfbd,
                "away",
                reasons,
                cfg,
                decision_h=decision_h,
                reference_h=reference_h,
            ),
        ]
        game_out = dict(game)
        game_out["home_team"] = home_canonical
        game_out["away_team"] = away_canonical
        game_out["sharp_available"] = False
        game_out["exclusion_reasons"] = ";".join(_unique(reasons))
        game_out["exclude_from_model"] = True
        return rows, unmatched, game_out

    for raw in (event["home_team_odds"], event["away_team_odds"]):
        if raw and _canonical_odds(raw, odds_map) is None and raw not in {home_cfbd, away_cfbd}:
            unmatched.append({"raw_name": str(raw), "source": "odds_api"})

    decision_target = kickoff - timedelta(hours=decision_h)
    reference_target = kickoff - timedelta(hours=reference_h)
    event_snaps = event["frame"].copy()
    event_snaps["snapshot_ts"] = pd.to_datetime(event_snaps["snapshot_ts"], utc=True)

    if kickoff <= decision_target:
        reasons.append(EXCL_ALREADY_STARTED)

    current_earliest = None
    if current_earliest_hours is not None:
        current_earliest = (kickoff - timedelta(hours=int(current_earliest_hours))).to_pydatetime()
    current_ts = pick_snapshot_at_or_before(
        event_snaps["snapshot_ts"],
        decision_target.to_pydatetime(),
        earliest=current_earliest,
    )
    reference_ts = pick_snapshot_at_or_before(event_snaps["snapshot_ts"], reference_target.to_pydatetime())
    if current_ts is None:
        reasons.append(missing_current_code)
    if reference_ts is None:
        reasons.append(EXCL_MISSING_REFERENCE)
    if current_ts is not None and pd.Timestamp(current_ts) > decision_target:
        reasons.append(EXCL_LOOKAHEAD)
    if reference_ts is not None and pd.Timestamp(reference_ts) > reference_target:
        reasons.append(EXCL_LOOKAHEAD)

    current_row = _row_at(event_snaps, current_ts)
    reference_row = _row_at(event_snaps, reference_ts)
    home_ml = _get(current_row, "home_moneyline")
    away_ml = _get(current_row, "away_moneyline")
    has_pinnacle_book = current_row is not None and (
        _get(current_row, "last_update") is not None
        or home_ml is not None
        or away_ml is not None
        or _get(current_row, "home_spread") is not None
    )
    if current_ts is not None and not has_pinnacle_book:
        reasons.append(EXCL_PINNACLE_MISSING)
    sharp_ok = bool(current_row is not None and current_row.get("sharp_available"))
    if current_ts is not None and (home_ml is None or away_ml is None):
        reasons.append(missing_ml_code)

    if current_ts is not None and reference_ts is not None:
        for snap_row in (current_row, reference_row):
            if snap_row is None or _get(snap_row, "home_spread") is None or _get(snap_row, "away_spread") is None:
                reasons.append(EXCL_MISSING_SPREAD)
                break

    reasons = _unique(reasons)
    home_row = _team_row(
        game,
        cfg,
        side="home",
        team=home_canonical or home_cfbd,
        opponent=away_canonical or away_cfbd,
        current_row=current_row,
        reference_row=reference_row,
        current_ts=current_ts,
        reference_ts=reference_ts,
        decision_h=decision_h,
        reference_h=reference_h,
        reasons=reasons,
        sharp_ok=sharp_ok,
        home_ml=home_ml,
        away_ml=away_ml,
        event_snaps=event_snaps,
        decision_target=decision_target,
        reference_target=reference_target,
        home_canonical=home_canonical,
        away_canonical=away_canonical,
        current_earliest_ts=current_earliest,
    )
    away_row = _team_row(
        game,
        cfg,
        side="away",
        team=away_canonical or away_cfbd,
        opponent=home_canonical or home_cfbd,
        current_row=current_row,
        reference_row=reference_row,
        current_ts=current_ts,
        reference_ts=reference_ts,
        decision_h=decision_h,
        reference_h=reference_h,
        reasons=reasons,
        sharp_ok=sharp_ok,
        home_ml=home_ml,
        away_ml=away_ml,
        event_snaps=event_snaps,
        decision_target=decision_target,
        reference_target=reference_target,
        home_canonical=home_canonical,
        away_canonical=away_canonical,
        current_earliest_ts=current_earliest,
    )
    _apply_favorite_filter(home_row, away_row, game)
    game_out = dict(game)
    game_out["home_team"] = home_canonical
    game_out["away_team"] = away_canonical
    game_out["sharp_available"] = bool(home_row["sharp_available"])
    game_reasons = _unique(
        list(reasons)
        + _split_reasons(home_row["exclusion_reasons"])
        + _split_reasons(away_row["exclusion_reasons"])
    )
    # Keep game-level exclusions; favorite filter does not exclude the game.
    game_out["exclusion_reasons"] = ";".join(
        [r for r in game_reasons if r != "NOT_FAVORITE"]
    )
    game_out["exclude_from_model"] = not (home_row["include_in_model"] or away_row["include_in_model"])
    return [home_row, away_row], unmatched, game_out


def _apply_favorite_filter(home_row: Dict[str, Any], away_row: Dict[str, Any], game: Dict[str, Any]) -> None:
    hp = home_row.get("current_probability")
    ap = away_row.get("current_probability")
    for row, is_home in ((home_row, True), (away_row, False)):
        p = row.get("current_probability")
        favorite = p is not None and p >= 0.50
        if hp == 0.50 and ap == 0.50:
            favorite = is_home
        if not favorite and row["include_in_model"]:
            row["include_in_model"] = False


def _team_row(
    game: Dict[str, Any],
    cfg: Dict[str, Any],
    *,
    side: str,
    team: Optional[str],
    opponent: Optional[str],
    current_row: Optional[pd.Series],
    reference_row: Optional[pd.Series],
    current_ts: Any,
    reference_ts: Any,
    decision_h: int,
    reference_h: int,
    reasons: Sequence[str],
    sharp_ok: bool,
    home_ml: Any,
    away_ml: Any,
    event_snaps: pd.DataFrame,
    decision_target: Any,
    reference_target: Any,
    home_canonical: Optional[str],
    away_canonical: Optional[str],
    current_earliest_ts: Optional[Any] = None,
) -> Dict[str, Any]:
    is_home = side == "home"
    home_away = "neutral" if game.get("neutral_site") else side
    features = team_features_from_snapshots(
        event_snaps,
        decision_ts=pd.Timestamp(decision_target).to_pydatetime(),
        reference_ts=pd.Timestamp(reference_target).to_pydatetime(),
        team=event_snaps.iloc[0]["home_team_odds"] if is_home else event_snaps.iloc[0]["away_team_odds"],
        opponent=event_snaps.iloc[0]["away_team_odds"] if is_home else event_snaps.iloc[0]["home_team_odds"],
        home_team=event_snaps.iloc[0]["home_team_odds"],
        away_team=event_snaps.iloc[0]["away_team_odds"],
        current_earliest_ts=current_earliest_ts,
    )
    current_spread = features["current_spread"]
    reference_spread = features["reference_spread"]
    current_ml = features["current_moneyline"]
    current_p = features["current_probability"]
    move = features["spread_move"]
    home_score = game.get("home_score")
    away_score = game.get("away_score")
    team_score = home_score if is_home else away_score
    opp_score = away_score if is_home else home_score
    win = None
    if team_score is not None and opp_score is not None and not pd.isna(team_score) and not pd.isna(opp_score):
        if team_score != opp_score:
            win = int(float(team_score) > float(opp_score))

    local_reasons = list(reasons)
    include = (
        not local_reasons
        and current_p is not None
        and current_p >= 0.50
        and current_spread is not None
        and reference_spread is not None
        and current_ml is not None
        and features["current_timestamp"] is not None
        and features["reference_timestamp"] is not None
        and bool(game.get("completed"))
        and not bool(game.get("cancelled"))
        and sharp_ok
        and win is not None
    )
    bucket = (
        assign_interval_label(move, cfg["movement_buckets"]) if move is not None else ""
    )
    band = (
        assign_interval_label(current_p, cfg["probability_bands"]) if current_p is not None else ""
    )
    return {
        "game_id": str(game["game_id"]),
        "season": int(game["season"]),
        "week": int(game["week"]),
        "game_date": game["game_date"],
        "kickoff_timestamp": pd.to_datetime(game["kickoff_timestamp"], utc=True),
        "team": team,
        "opponent": opponent,
        "home_away": home_away,
        "neutral_site": bool(game.get("neutral_site")),
        "decision_horizon_hours": decision_h,
        "reference_horizon_hours": reference_h,
        "reference_timestamp": features["reference_timestamp"],
        "current_timestamp": features["current_timestamp"],
        "reference_spread": reference_spread,
        "current_spread": current_spread,
        "reference_spread_price": features["reference_spread_price"],
        "current_spread_price": features["current_spread_price"],
        "reference_moneyline": features["reference_moneyline"],
        "current_moneyline": current_ml,
        "reference_probability": features["reference_probability"],
        "current_probability": current_p,
        "spread_move": move,
        "final_team_score": team_score,
        "final_opponent_score": opp_score,
        "win": win,
        "sharp_source": "pinnacle",
        "sharp_available": bool(sharp_ok),
        "include_in_model": bool(include),
        "exclusion_reasons": ";".join(_unique(local_reasons)),
        "movement_bucket": bucket,
        "probability_band": band,
        "data_quality_flag": "",
    }


def _blank_team_row(
    game: Dict[str, Any],
    team: Optional[str],
    opponent: Optional[str],
    side: str,
    reasons: Sequence[str],
    cfg: Dict[str, Any],
    *,
    decision_h: Optional[int] = None,
    reference_h: Optional[int] = None,
) -> Dict[str, Any]:
    home_away = "neutral" if game.get("neutral_site") else side
    is_home = side == "home"
    home_score = game.get("home_score")
    away_score = game.get("away_score")
    team_score = home_score if is_home else away_score
    opp_score = away_score if is_home else home_score
    win = None
    if team_score is not None and opp_score is not None and not pd.isna(team_score) and not pd.isna(opp_score):
        if float(team_score) != float(opp_score):
            win = int(float(team_score) > float(opp_score))
    return {
        "game_id": str(game["game_id"]),
        "season": int(game["season"]),
        "week": int(game["week"]),
        "game_date": game["game_date"],
        "kickoff_timestamp": pd.to_datetime(game["kickoff_timestamp"], utc=True),
        "team": team,
        "opponent": opponent,
        "home_away": home_away,
        "neutral_site": bool(game.get("neutral_site")),
        "decision_horizon_hours": int(
            cfg["mvp"]["decision_horizon_hours"] if decision_h is None else decision_h
        ),
        "reference_horizon_hours": int(
            cfg["mvp"]["reference_horizon_hours"] if reference_h is None else reference_h
        ),
        "reference_timestamp": pd.NaT,
        "current_timestamp": pd.NaT,
        "reference_spread": None,
        "current_spread": None,
        "reference_spread_price": None,
        "current_spread_price": None,
        "reference_moneyline": None,
        "current_moneyline": None,
        "reference_probability": None,
        "current_probability": None,
        "spread_move": None,
        "final_team_score": team_score,
        "final_opponent_score": opp_score,
        "win": win,
        "sharp_source": "pinnacle",
        "sharp_available": False,
        "include_in_model": False,
        "exclusion_reasons": ";".join(_unique(reasons)),
        "movement_bucket": "",
        "probability_band": "",
        "data_quality_flag": "",
    }


def _index_snapshots(snapshots: pd.DataFrame, odds_map: Dict[str, str]) -> List[Dict[str, Any]]:
    if snapshots is None or snapshots.empty:
        return []
    frame = snapshots.copy()
    frame["snapshot_ts"] = pd.to_datetime(frame["snapshot_ts"], utc=True)
    frame["commence_time"] = pd.to_datetime(frame["commence_time"], utc=True)
    indexed = []
    for (event_id, home, away), group in frame.groupby(
        ["odds_event_id", "home_team_odds", "away_team_odds"], dropna=False
    ):
        indexed.append(
            {
                "odds_event_id": event_id,
                "home_team_odds": home,
                "away_team_odds": away,
                "home_canonical": _canonical_odds(home, odds_map),
                "away_canonical": _canonical_odds(away, odds_map),
                "commence_time": group["commence_time"].dropna().iloc[0]
                if group["commence_time"].notna().any()
                else None,
                "frame": group,
            }
        )
    return indexed


def _match_event(
    game: Dict[str, Any],
    snapshot_index: List[Dict[str, Any]],
    cfbd_map: Dict[str, str],
    odds_map: Dict[str, str],
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    home_cfbd = game.get("home_team_cfbd")
    away_cfbd = game.get("away_team_cfbd")
    kickoff = pd.to_datetime(game["kickoff_timestamp"], utc=True)
    best = None
    best_home = None
    best_away = None
    best_delta = None
    for event in snapshot_index:
        home_c, away_c = _pair_canonicals(
            home_cfbd, away_cfbd, event, cfbd_map, odds_map
        )
        if home_c is None or away_c is None:
            continue
        commence = event.get("commence_time")
        if commence is None or pd.isna(commence):
            continue
        delta = abs((pd.to_datetime(commence, utc=True) - kickoff).total_seconds())
        if delta > KICKOFF_MATCH_HOURS * 3600:
            continue
        if best_delta is None or delta < best_delta:
            best = event
            best_home, best_away = home_c, away_c
            best_delta = delta
    if best is None:
        home_c = cfbd_map.get(home_cfbd) or None
        away_c = cfbd_map.get(away_cfbd) or None
        return None, home_c, away_c
    return best, best_home, best_away


def _pair_canonicals(
    home_cfbd: Optional[str],
    away_cfbd: Optional[str],
    event: Dict[str, Any],
    cfbd_map: Dict[str, str],
    odds_map: Dict[str, str],
) -> Tuple[Optional[str], Optional[str]]:
    home_odds = event.get("home_team_odds")
    away_odds = event.get("away_team_odds")
    home = _canonical_pair(home_cfbd, home_odds, cfbd_map, odds_map)
    away = _canonical_pair(away_cfbd, away_odds, cfbd_map, odds_map)
    if home and away:
        return home, away
    # Allow swapped home/away vs Odds API only if names match as a set.
    home_swapped = _canonical_pair(home_cfbd, away_odds, cfbd_map, odds_map)
    away_swapped = _canonical_pair(away_cfbd, home_odds, cfbd_map, odds_map)
    if home_swapped and away_swapped:
        return home_swapped, away_swapped
    return home, away


def _canonical_pair(
    cfbd_name: Optional[str],
    odds_name: Optional[str],
    cfbd_map: Dict[str, str],
    odds_map: Dict[str, str],
) -> Optional[str]:
    if cfbd_name and cfbd_name in cfbd_map:
        mapped = cfbd_map[cfbd_name]
        odds_c = _canonical_odds(odds_name, odds_map)
        if odds_c is None and odds_name == cfbd_name:
            return mapped
        if odds_c is None:
            return None
        return mapped if mapped == odds_c else None
    if cfbd_name and odds_name and cfbd_name == odds_name:
        return cfbd_name
    odds_c = _canonical_odds(odds_name, odds_map)
    if cfbd_name and odds_c and cfbd_name == odds_c:
        return odds_c
    return None


def _canonical_odds(name: Optional[str], odds_map: Dict[str, str]) -> Optional[str]:
    if not name:
        return None
    if name in odds_map:
        return odds_map[name]
    return None


def _row_at(frame: pd.DataFrame, ts: Any) -> Optional[pd.Series]:
    if ts is None or frame.empty:
        return None
    matched = frame.loc[frame["snapshot_ts"] == pd.Timestamp(ts)]
    if matched.empty:
        return None
    return matched.iloc[-1]


def _get(row: Optional[pd.Series], key: str) -> Any:
    if row is None:
        return None
    value = row.get(key)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def _split_reasons(value: Any) -> List[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
        return []
    return [part for part in str(value).split(";") if part]


def _unique(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _dataset_columns() -> List[str]:
    return [
        "game_id",
        "season",
        "week",
        "game_date",
        "kickoff_timestamp",
        "team",
        "opponent",
        "home_away",
        "neutral_site",
        "decision_horizon_hours",
        "reference_horizon_hours",
        "reference_timestamp",
        "current_timestamp",
        "reference_spread",
        "current_spread",
        "reference_spread_price",
        "current_spread_price",
        "reference_moneyline",
        "current_moneyline",
        "reference_probability",
        "current_probability",
        "spread_move",
        "final_team_score",
        "final_opponent_score",
        "win",
        "sharp_source",
        "sharp_available",
        "include_in_model",
        "exclusion_reasons",
        "movement_bucket",
        "probability_band",
        "data_quality_flag",
    ]


def _horizon_dataset_columns() -> List[str]:
    return _dataset_columns() + [
        "p_24",
        "spread_24",
        "ts_24",
        "p_1h",
        "spread_1h",
        "ts_1h",
        "spread_move_72_24",
        "spread_move_24_1h",
    ]

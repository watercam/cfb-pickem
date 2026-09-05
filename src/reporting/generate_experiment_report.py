"""Write experiment_late_line/experiment_report.md. Does not touch V1 backtest_report.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from src.backtest.late_line import forecast_beats_a24, sample_too_small
from src.reporting.generate_report import VERDICTS, _effect_table, _md_table, choose_verdict
from src.settings import resolve_paths


def generate_experiment_report(
    dataset: pd.DataFrame,
    *,
    config: Dict[str, Any],
    plan: Dict[str, Any],
    result_l: Dict[str, Any],
    result_s: Dict[str, Any],
    matrix_l: pd.DataFrame,
    pinnacle_reconstructed: bool,
    data_note: str = "",
) -> Path:
    paths = resolve_paths(config)
    outputs = paths["outputs"]
    outputs.mkdir(parents=True, exist_ok=True)
    fetch_summary = _load_fetch_summary(outputs)

    clock1 = dataset.loc[dataset["decision_horizon_hours"] == 1] if not dataset.empty else dataset
    clock24 = dataset.loc[dataset["decision_horizon_hours"] == 24] if not dataset.empty else dataset
    n_l = int(result_l.get("n_modeled") or 0)
    n_s = int(result_s.get("n_s_modeled") or 0)
    n_s_1h = int(result_s.get("n_s_with_1h") or 0)
    n_1h_ml = int(clock1["p_1h"].notna().sum()) if not clock1.empty else 0
    n_24 = int(clock24["p_24"].notna().sum()) if not clock24.empty else 0

    l_blocker = (not pinnacle_reconstructed) or sample_too_small(n_l)
    metrics_l = result_l["metrics"]
    metrics_s = result_s["metrics"]
    if l_blocker:
        verdict_l = None
        matrix_l = matrix_l.copy()
        matrix_l["production_adjustment"] = 0.0
    else:
        renamed = metrics_l.copy()
        renamed["model"] = renamed["model"].replace({"A1": "A", "B1": "B"})
        verdict_l = choose_verdict(
            renamed,
            matrix_l,
            n_modeled=n_l,
            pinnacle_reconstructed=pinnacle_reconstructed,
        )
        if verdict_l != "A":
            matrix_l = matrix_l.copy()
            matrix_l["production_adjustment"] = 0.0

    verdict_s_forecast_beats = forecast_beats_a24(metrics_s)
    oracle_gap = _oracle_gap(metrics_s)
    go_4h = _go_4h(verdict_l, verdict_s_forecast_beats, oracle_gap)

    by_move_l = _effect_table(
        clock1.loc[clock1["include_in_model"]] if not clock1.empty else clock1,
        "movement_bucket",
        config["movement_buckets"],
    )

    lines = [
        "# Late line vs close forecast",
        "",
        "## 1. Executive summary",
        "",
    ]
    lines += _exec_summary(
        verdict_l=verdict_l,
        l_blocker=l_blocker,
        n_l=n_l,
        n_s=n_s,
        n_s_1h=n_s_1h,
        metrics_l=metrics_l,
        metrics_s=metrics_s,
        forecast_beats=verdict_s_forecast_beats,
        oracle_gap=oracle_gap,
        data_note=data_note,
    )
    lines += [
        "## 2. Credits / new timestamps",
        "",
        f"- Snapshot horizons (hours): {plan.get('horizons_hours')}",
        f"- Unique planned timestamps: {plan.get('n_planned')}",
        *_credit_lines(plan, fetch_summary),
        "- Book: Pinnacle only. No substitute sportsbook.",
        "",
        "## 3. Coverage",
        "",
        f"- Clock-24 rows with `p_24`: {n_24}",
        f"- Clock-1 rows with `p_1h`: {n_1h_ml}",
        f"- Experiment L modeled favorites (1h ML + 24h spread): {n_l}",
        f"- Experiment S modeled favorites (24h ML): {n_s}",
        f"- S favorites that also have `p_1h` (forecast/oracle sample): {n_s_1h}",
        "",
        _md_table(_horizon_exclusion_counts(dataset)),
        "",
        "## 4. Experiment L (decide at 1h)",
        "",
    ]
    if l_blocker:
        lines += [
            f"**Blocker:** n with 1h moneyline in the L sample is {n_l}, which is too "
            "small to claim a walk-forward A/B/C/D verdict. No production 1h matrix.",
            "",
        ]
    else:
        lines += [
            f"**Verdict L: {VERDICTS[verdict_l]}**",
            "",
            "A1 is clamp(p at 1h). B1 adds a train-only 7×6 lookup on 24h→1h spread move.",
            "",
            _md_table(_pooled(metrics_l)),
            "",
            "### 24h→1h movement buckets (L modeled rows)",
            "",
            _md_table(by_move_l),
            "",
        ]
    lines += [
        "## 5. Experiment S (decide at 24h)",
        "",
        "A24 is clamp(p at 24h) vs the game winner. Forecast-close predicts p_1h from "
        "`p_24` and `spread_move_72_24` only, then scores clamp(p_hat_1h) vs the winner. "
        "Oracle is clamp(actual p_1h) vs the winner — not available at a 24h deadline.",
        "",
        (
            "**Forecast-close vs A24:** Forecast **beats** A24 out of sample."
            if verdict_s_forecast_beats
            else "**Forecast-close vs A24:** Forecast does **not** beat A24. Early spread "
            "move does not forecast a more useful 1h number for winners."
        ),
        "",
        _md_table(_pooled(metrics_s)),
        "",
        "### Close-forecast error (p_hat_1h vs actual p_1h)",
        "",
        _md_table(result_s.get("close_forecast_error")),
        "",
        "## 6. Limitations",
        "",
        "- 1 hour before kickoff is not the close; some games may already be underway "
        "relative to a 1h target if kickoff timestamps are noisy.",
        "- Missing 1h Pinnacle moneylines drop out of L and of S forecast/oracle.",
        "- A24 can still score games that lack a 1h snapshot.",
        "- Oracle beating A24 is not evidence to ship a 24h→1h movement feature.",
        "- No 4h snapshot, public %, contest sim, or optimizer wiring.",
        "",
        "## 7. Go / no-go for a 4h fetch",
        "",
        go_4h,
        "",
        "## 8. L train matrix (not a production ship unless verdict L is A)",
        "",
        _md_table(matrix_l),
        "",
    ]
    path = outputs / "experiment_report.md"
    path.write_text("\n".join(line for line in lines if line is not None).replace("\n\n\n", "\n\n"))
    matrix_l.to_csv(outputs / "l_line_movement_matrix.csv", index=False)
    return path


def _exec_summary(
    *,
    verdict_l: Optional[str],
    l_blocker: bool,
    n_l: int,
    n_s: int,
    n_s_1h: int,
    metrics_l: pd.DataFrame,
    metrics_s: pd.DataFrame,
    forecast_beats: bool,
    oracle_gap: Optional[Dict[str, float]],
    data_note: str,
) -> list[str]:
    lines = []
    if l_blocker:
        lines += [
            f"**Experiment L:** no A/B/C/D claim (n={n_l} modeled 1h favorites).",
            "",
        ]
    else:
        lines += [f"**Experiment L:** {VERDICTS[verdict_l]}.", ""]
        pooled_l = _pooled(metrics_l)
        a1, b1 = _pair(pooled_l, "A1", "B1")
        if a1 is not None and b1 is not None:
            lines += [
                f"On {int(a1['n'])} OOS 1h favorites, A1 log loss {float(a1['log_loss']):.4f} "
                f"vs B1 {float(b1['log_loss']):.4f}; Brier {float(a1['brier']):.4f} vs "
                f"{float(b1['brier']):.4f}.",
                "",
            ]
    lines += [
        (
            "**Experiment S:** Forecast-close beats A24 — 72h→24h movement helps a 24h deadline."
            if forecast_beats
            else "**Experiment S:** Forecast-close does not beat A24 — 72h→24h movement does "
            "not produce a more useful 1h probability for winners."
        ),
        "",
    ]
    pooled_s = _pooled(metrics_s)
    a24, fc, ora = _triple(pooled_s)
    if a24 is not None and fc is not None:
        lines += [
            f"On {int(a24['n'])} OOS games with both p_24 and p_1h (S sample n={n_s}, "
            f"with 1h n={n_s_1h}): A24 log loss {float(a24['log_loss']):.4f}, "
            f"Forecast {float(fc['log_loss']):.4f}"
            + (
                f", Oracle {float(ora['log_loss']):.4f}."
                if ora is not None
                else "."
            ),
            "",
        ]
    if oracle_gap and oracle_gap.get("large"):
        lines += [
            "The **oracle gap** (actual 1h line vs Thursday's line) is large: waiting "
            "until 1h would have helped, but that is not a 24h feature.",
            "",
        ]
    elif oracle_gap:
        lines += [
            "The oracle gap is small: the 1h line is not much more informative about "
            "winners than the 24h line in this sample.",
            "",
        ]
    if verdict_l in {"C", "D"} and not forecast_beats and oracle_gap and oracle_gap.get("large"):
        lines += [
            "Reading: the late line is better than Thursday's line, but you cannot steal "
            "that with 72h→24h movement. Operational takeaway: pick later or poll a fresh "
            "Pinnacle moneyline, not a movement matrix.",
            "",
        ]
    if data_note:
        lines += [data_note, ""]
    return lines


def _go_4h(verdict_l: Optional[str], forecast_beats: bool, oracle_gap: Optional[Dict[str, float]]) -> str:
    if verdict_l is None:
        return (
            "**No-go for 4h until L has enough 1h moneylines to score.** 4h is the same "
            "design as L with a different clock."
        )
    l_movement = verdict_l in {"A", "B"}
    if l_movement != forecast_beats:
        return (
            "**Go (optional):** L and S disagree across clocks. A 4h fetch is the in-between "
            "submit time if you still need one."
        )
    return (
        "**No-go for 4h.** L and S do not disagree in a way that needs an in-between "
        "clock. Skip 4h until a later question requires it."
    )


def _load_fetch_summary(outputs: Path) -> Dict[str, Any]:
    path = outputs / "fetch_summary.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _credit_lines(plan: Dict[str, Any], summary: Dict[str, Any]) -> list[str]:
    if summary.get("n_missing_fetched"):
        return [
            f"- Already in cache before this fetch: {summary.get('n_cached_before')}",
            f"- New T-1h GETs this session: {summary.get('n_missing_fetched')}",
            f"- Estimated credits spent on those GETs: {summary.get('est_credits')}",
            f"- Cache at report time: {plan.get('n_cached')} / {plan.get('n_planned')} "
            f"(missing now {plan.get('n_missing')})",
        ]
    return [
        f"- Already in cache: {plan.get('n_cached')}",
        f"- Missing at plan time (new GETs): {plan.get('n_missing')}",
        f"- Estimated credits for missing timestamps: {plan.get('est_credits')}",
    ]


def _oracle_gap(metrics: pd.DataFrame) -> Optional[Dict[str, float]]:
    pooled = _pooled(metrics)
    a24, _fc, ora = _triple(pooled)
    if a24 is None or ora is None:
        return None
    ll_gap = float(a24["log_loss"] - ora["log_loss"])
    br_gap = float(a24["brier"] - ora["brier"])
    return {"log_loss_gap": ll_gap, "brier_gap": br_gap, "large": ll_gap > 0.005 or br_gap > 0.002}


def _pooled(metrics: pd.DataFrame) -> pd.DataFrame:
    if metrics is None or metrics.empty:
        return metrics
    return metrics.loc[metrics["fold_id"] == "pooled_oos"]


def _pair(pooled: pd.DataFrame, a: str, b: str):
    if pooled is None or pooled.empty:
        return None, None
    left = pooled.loc[pooled["model"] == a]
    right = pooled.loc[pooled["model"] == b]
    if left.empty or right.empty:
        return None, None
    return left.iloc[0], right.iloc[0]


def _triple(pooled: pd.DataFrame):
    if pooled is None or pooled.empty:
        return None, None, None
    def _one(name: str):
        hit = pooled.loc[pooled["model"] == name]
        return None if hit.empty else hit.iloc[0]
    return _one("A24"), _one("Forecast"), _one("Oracle")


def _horizon_exclusion_counts(dataset: pd.DataFrame) -> pd.DataFrame:
    codes = [
        "NOT_FBS_VS_FBS",
        "CANCELLED",
        "NO_FINAL_RESULT",
        "TEAM_UNMAPPED",
        "MISSING_DECISION_SNAPSHOT",
        "MISSING_REFERENCE_SNAPSHOT",
        "MISSING_1H_SNAPSHOT",
        "MISSING_1H_MONEYLINE",
        "PINNACLE_MISSING",
        "MISSING_CURRENT_MONEYLINE",
        "MISSING_SPREAD",
        "LOOKAHEAD_GUARD",
    ]
    if dataset.empty:
        return pd.DataFrame({"exclusion_code": codes, "row_count": [0] * len(codes)})
    reasons = dataset["exclusion_reasons"].fillna("")
    rows = []
    for code in codes:
        rows.append({"exclusion_code": code, "row_count": int(reasons.str.contains(code, regex=False).sum())})
    return pd.DataFrame(rows)

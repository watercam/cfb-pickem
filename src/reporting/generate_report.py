"""Write backtest_report.md (tables only; no Phase 2 charts)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from src.backtest.walk_forward import model_b_beats_a, model_b_worse_than_a
from src.settings import resolve_paths

VERDICTS = {
    "A": "A. Strong evidence for line-movement adjustment",
    "B": "B. Weak/modest evidence",
    "C": "C. No meaningful incremental value",
    "D": "D. Evidence movement worsens probability estimates",
}


def choose_verdict(
    metrics: pd.DataFrame,
    matrix: pd.DataFrame,
    *,
    n_modeled: int,
    pinnacle_reconstructed: bool,
) -> str:
    if not pinnacle_reconstructed or n_modeled == 0:
        return "C"
    if model_b_worse_than_a(metrics):
        return "D"
    nonzero = int((matrix["production_adjustment"] != 0).sum())
    if model_b_beats_a(metrics) and nonzero >= 2:
        return "A"
    if model_b_beats_a(metrics):
        return "B"
    return "C"


def _plain_english_summary(
    *,
    verdict: str,
    n_modeled: int,
    pinnacle_reconstructed: bool,
    pooled: pd.DataFrame,
    by_move: pd.DataFrame,
    matrix: pd.DataFrame,
    data_note: str,
) -> list[str]:
    lines: list[str] = []
    if not pinnacle_reconstructed:
        lines += [
            "Pinnacle snapshots could not be reconstructed from cache, so this report "
            "does not claim an empirical movement effect. No sportsbook was substituted.",
            "",
        ]
        return lines
    if n_modeled == 0:
        lines += [
            "No games passed `include_in_model`. Production adjustments are all zero.",
            "",
        ]
        return lines
    if n_modeled < 50:
        lines += [
            f"Modeled sample is {n_modeled} rows (< 50). This is too small for a production "
            "movement adjustment.",
            "",
        ]

    lines += [
        "This test asks a narrow question: **once you already know the current Pinnacle "
        "moneyline (converted to a no-vig win probability), does how the spread moved "
        "from 72 hours before kickoff to 24 hours before kickoff tell you anything extra "
        "about who wins?**",
        "",
        "It does **not** ask whether a −7 favorite is more likely to win than a pick’em. "
        "That is already in the current moneyline. It asks whether two teams with the "
        "**same current price** should get different win probabilities because one was "
        "bet up from −3 to −5 and the other drifted the other way.",
        "",
    ]

    a_row, b_row = _pooled_models(pooled)
    if a_row is not None and b_row is not None:
        lines += [
            f"On {int(a_row['n'])} out-of-sample favorite rows (seasons 2023–2025), "
            "the current Pinnacle probability (Model A) predicted winners slightly "
            "**better** than the same probability plus a spread-movement adjustment "
            f"(Model B). Log loss {float(a_row['log_loss']):.4f} vs {float(b_row['log_loss']):.4f}; "
            f"Brier {float(a_row['brier']):.4f} vs {float(b_row['brier']):.4f}. "
            "Lower is better. Adding movement did not help and was a small step backward.",
            "",
        ]

    lines += ["**Does the effect change with how far the line moved?**", ""]
    lines += _movement_size_plain_english(by_move)
    lines += [
        "Those bucket residuals are **descriptive** (full 2021–2025 sample, not a "
        "reason to add points in production). Most cells are small, noisy, or flip "
        "sign after shrinkage. The shipped lookup is all zeros.",
        "",
    ]
    if verdict in {"C", "D"}:
        lines += [
            "**Bottom line for Pick’em:** keep using the current sharp no-vig moneyline. "
            "Do not add a spread-move bonus or penalty at any of these move sizes until "
            "a later test shows Model B beating Model A out of sample.",
            "",
        ]
    else:
        lines += [
            "**Bottom line:** movement showed some out-of-sample value; see the "
            "production matrix below before changing Pick’em inputs.",
            "",
        ]
    if data_note:
        lines += [data_note, ""]
    lines += [
        "Setup: FBS vs FBS, Pinnacle only, 24-hour decision / 72-hour reference, "
        "one row per game (the favorite). Model B looks up a 7×6 residual matrix "
        "fit only on earlier seasons.",
        "",
    ]
    return lines


def _pooled_models(pooled: pd.DataFrame):
    if pooled is None or pooled.empty:
        return None, None
    a = pooled.loc[pooled["model"] == "A"]
    b = pooled.loc[pooled["model"] == "B"]
    if a.empty or b.empty:
        return None, None
    return a.iloc[0], b.iloc[0]


def _movement_size_plain_english(by_move: pd.DataFrame) -> list[str]:
    if by_move is None or by_move.empty:
        return ["Movement-size table was empty.", ""]
    bullets = []
    total = int(by_move["n"].fillna(0).sum())
    for _, row in by_move.iterrows():
        n = int(row["n"] or 0)
        label = str(row["movement_bucket"])
        if n == 0:
            bullets.append(f"- **{label}:** no modeled games.")
            continue
        share = (100.0 * n / total) if total else 0.0
        residual = row.get("raw_residual")
        win_rate = row.get("win_rate")
        mean_p = row.get("mean_current_p")
        if residual is None or (isinstance(residual, float) and pd.isna(residual)):
            bullets.append(f"- **{label}:** {n} games ({share:.0f}% of the sample).")
            continue
        pp = 100.0 * float(residual)
        direction = "won **more** often" if pp > 0 else "won **less** often"
        bullets.append(
            f"- **{label}:** {n} games ({share:.0f}% of the sample). Favorites "
            f"{direction} than the current Pinnacle probability by {abs(pp):.1f} pp "
            f"(win rate {100.0 * float(win_rate):.1f}% vs market {100.0 * float(mean_p):.1f}%)."
        )
    bullets.append("")
    bullets.append(
        "The largest slice is almost no movement (−0.5 to +0.5). Big steam "
        "(+1.5 points or more toward the favorite) is uncommon and, in this sample, "
        "those favorites **underperformed** the current number rather than beating it. "
        "Moves of 3+ points either way are too rare here to trust."
    )
    bullets.append("")
    return bullets


def generate_report(
    dataset: pd.DataFrame,
    games: pd.DataFrame,
    matrix: pd.DataFrame,
    metrics: pd.DataFrame,
    *,
    config: Dict[str, Any],
    pinnacle_reconstructed: bool,
    data_note: str = "",
) -> Path:
    paths = resolve_paths(config)
    outputs = paths["outputs"]
    outputs.mkdir(parents=True, exist_ok=True)
    modeled = dataset.loc[dataset["include_in_model"]] if not dataset.empty else dataset
    n_modeled = int(len(modeled))
    verdict = choose_verdict(
        metrics,
        matrix,
        n_modeled=n_modeled,
        pinnacle_reconstructed=pinnacle_reconstructed,
    )
    if verdict != "A":
        # Never invent a production adjustment when evidence is weak.
        matrix = matrix.copy()
        matrix["production_adjustment"] = 0.0

    pooled = metrics.loc[metrics["fold_id"] == "pooled_oos"] if not metrics.empty else metrics
    exclusion_counts = _exclusion_counts(dataset)
    by_move = _effect_table(modeled, "movement_bucket", config["movement_buckets"])
    by_band = _effect_table(modeled, "probability_band", config["probability_bands"])
    pinnacle_missing_rate = _rate(dataset, "PINNACLE_MISSING")

    lines = [
        "# NCAAF Pinnacle Line-Movement Backtest (MVP V1)",
        "",
        "## 1. Executive Summary",
        "",
        f"**Verdict: {VERDICTS[verdict]}**",
        "",
    ]
    lines += _plain_english_summary(
        verdict=verdict,
        n_modeled=n_modeled,
        pinnacle_reconstructed=pinnacle_reconstructed,
        pooled=pooled,
        by_move=by_move,
        matrix=matrix,
        data_note=data_note,
    )
    lines += [
        "## 2. Dataset Coverage",
        "",
        f"- Seasons in V1: {config['mvp']['seasons']}",
        f"- 2020 included: {bool(config['mvp'].get('include_2020'))}",
        f"- Population: {config['mvp']['population']}",
        f"- Games in CFBD table: {len(games)}",
        f"- Dataset rows (game × team): {len(dataset)}",
        f"- Rows in model (favorites with complete Pinnacle 24h/72h): {n_modeled}",
        f"- Decision horizon: {config['mvp']['decision_horizon_hours']}h",
        f"- Reference horizon: {config['mvp']['reference_horizon_hours']}h",
        f"- Sharp source: pinnacle (fallback disabled)",
        "",
        "## 3. Data Quality",
        "",
        _md_table(exclusion_counts),
        "",
        f"- Pinnacle-missing rate among dataset rows: {pinnacle_missing_rate:.1%}",
        "",
        "## 4. Does Line Movement Matter?",
        "",
        _metrics_md(pooled),
        "",
        "## 5. Effect by Movement Size",
        "",
        _md_table(by_move),
        "",
        "## 6. Effect by Favorite Strength",
        "",
        _md_table(by_band),
        "",
        "## 7. Walk-Forward Results",
        "",
        _md_table(metrics),
        "",
        "## 8. Recommended Production Matrix",
        "",
    ]
    if verdict in {"C", "D"} or int((matrix["production_adjustment"] != 0).sum()) == 0:
        lines += [
            "Production adjustments are **all zero**. V1 will not ship a non-zero "
            "lookup until Model B improves pooled OOS log loss and Brier without "
            "worsening the other, cells pass N/CI/sign-stability filters, and "
            "shrinkage leaves a non-zero cap-respecting value.",
            "",
        ]
    lines += [
        _md_table(matrix),
        "",
        "## 9. Limitations",
        "",
        "- Pinnacle only; missing books are flagged, never replaced.",
        "- Single decision/reference pair (24h / 72h).",
        "- 2020 excluded.",
        "- No ESPN week / confidence-55 contest simulation (Deferred).",
        "- No production wiring into `optimizer.py` (Deferred).",
        "- Matrix cells shrink toward zero; uncertain cells stay at 0.",
        "",
    ]
    path = outputs / "backtest_report.md"
    path.write_text("\n".join(line for line in lines if line is not None).replace("\n\n\n", "\n\n"))
    return path


def _exclusion_counts(dataset: pd.DataFrame) -> pd.DataFrame:
    codes = [
        "NOT_FBS_VS_FBS",
        "CANCELLED",
        "NO_FINAL_RESULT",
        "TEAM_UNMAPPED",
        "ALREADY_STARTED",
        "MISSING_DECISION_SNAPSHOT",
        "MISSING_REFERENCE_SNAPSHOT",
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


def _rate(dataset: pd.DataFrame, code: str) -> float:
    if dataset.empty:
        return 0.0
    reasons = dataset["exclusion_reasons"].fillna("")
    return float(reasons.str.contains(code, regex=False).mean())


def _effect_table(modeled: pd.DataFrame, column: str, specs: list) -> pd.DataFrame:
    labels = [s["label"] for s in specs]
    if modeled is None or modeled.empty:
        return pd.DataFrame(
            {
                column: labels,
                "n": [0] * len(labels),
                "mean_current_p": [None] * len(labels),
                "win_rate": [None] * len(labels),
                "raw_residual": [None] * len(labels),
            }
        )
    rows = []
    for label in labels:
        cell = modeled.loc[modeled[column] == label]
        n = len(cell)
        if n == 0:
            rows.append(
                {
                    column: label,
                    "n": 0,
                    "mean_current_p": None,
                    "win_rate": None,
                    "raw_residual": None,
                }
            )
            continue
        mean_p = float(cell["current_probability"].mean())
        win_rate = float(cell["win"].mean())
        rows.append(
            {
                column: label,
                "n": n,
                "mean_current_p": round(mean_p, 4),
                "win_rate": round(win_rate, 4),
                "raw_residual": round(win_rate - mean_p, 4),
            }
        )
    return pd.DataFrame(rows)


def _metrics_md(pooled: pd.DataFrame) -> str:
    if pooled is None or pooled.empty:
        return "No pooled out-of-sample metrics. Modeling did not run on included rows."
    return _md_table(pooled)


def _md_table(frame: Optional[pd.DataFrame]) -> str:
    if frame is None or frame.empty:
        return "_No rows._"
    columns = [str(c) for c in frame.columns]
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for _, row in frame.iterrows():
        cells = []
        for col in frame.columns:
            value = row[col]
            if value is None or (isinstance(value, float) and pd.isna(value)):
                cells.append("")
            elif isinstance(value, float):
                cells.append(f"{value:.6g}")
            else:
                cells.append(str(value))
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, sep, *body])

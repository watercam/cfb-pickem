1. Objective

Build a historical backtesting system that determines whether sportsbook line movement contains incremental predictive information for ESPN College Football Pick’em winner selections.

The output of the project will replace the manually defined line-movement adjustment matrix:

Spread Movement	Current Adjustment
> +2.5	+3.0%
+1.0 to +2.5	+1.5%
-0.5 to +0.5	0.0%
-1.0 to -2.5	-1.5%
< -2.5	-3.0%

with a matrix derived from historical NCAAF sportsbook data.

The system must explicitly test the null hypothesis:

Once the current sharp sportsbook moneyline is known, historical movement leading to that price may contain little or no additional predictive information.

If the data shows no statistically meaningful incremental value, the correct output should be a matrix containing adjustments near 0%.

⸻

2. Core Modeling Principle

The model must distinguish between:

1. Current market strength
    * Example: Team A is currently -300.
    * This directly implies a high win probability.
2. Line movement
    * Example: Team A moved from -4.0 to -6.0.

Simply calculating the historical winning percentage of teams that moved from -4 to -6 is invalid because those teams are usually strong favorites anyway.

Instead, the backtest must measure:

Actual Win Probability
vs.
Probability Expected From Current Sharp Moneyline

and determine whether line movement systematically explains the residual.

Conceptually:

Incremental Movement Value
=
Observed Win Rate
-
Expected Win Rate From Current Market

Example:

Current no-vig probability:      65.0%
Historical win rate for similar
65% teams with +2 spread move:   66.1%
Estimated movement uplift:       +1.1 percentage points

The proposed matrix adjustment would therefore be approximately +1.1%, not an arbitrarily selected +1.5%.

⸻

3. Recommended Data Sources

Primary Odds Source: The Odds API

Use:

sport = americanfootball_ncaaf
markets = h2h,spreads
bookmaker = pinnacle

Historical data is available from approximately mid-2020 onward.

Required historical snapshots:

* Moneyline
* Spread
* Odds attached to spread
* Timestamp
* Bookmaker
* Home team
* Away team
* Game start time

Pinnacle should be the preferred book.

If Pinnacle is unavailable for a game/snapshot, do not silently substitute another sportsbook.

Instead save:

sharp_source = pinnacle
sharp_available = false

A separate fallback model may later use a multi-book consensus.

⸻

Secondary Results / Metadata Source: CollegeFootballData

Use CollegeFootballData for:

* Final scores
* Winner
* Game ID
* Week
* Season
* Home/away designation
* Neutral-site status
* FBS/FCS classification
* Game start time

Maintain a team-name resolution table between sources.

Example:

canonical_team	odds_api_team	cfbd_team
Ole Miss	Mississippi Rebels	Ole Miss
Miami FL	Miami Hurricanes	Miami
USC	USC Trojans	USC

Never fuzzy-match automatically below a configurable confidence threshold.

⸻

4. Historical Period

Use all usable seasons beginning with:

2020 season
through
latest completed week

However:

* treat 2020 as potentially structurally unusual because of COVID scheduling
* report results both including and excluding 2020
* season-based out-of-sample testing is mandatory

Expected usable sample should contain thousands of FBS games rather than only ESPN Pick’em games.

⸻

5. Game Population

Primary analysis population:

FBS vs. FBS games

Exclude:

* FBS vs FCS
* FCS vs FCS
* cancelled games
* games without final results
* games without a usable current Pinnacle moneyline
* games where historical timestamps cannot be reconstructed
* games that already started at the simulated decision timestamp

Store excluded games with an exclusion reason.

Do not simply delete them.

⸻

6. Avoiding Look-Ahead Bias

This is the most important engineering requirement.

The historical model must simulate the information that would have been available when the Pick’em recommendation was generated.

The backtest may never use:

* closing odds occurring after the simulated decision time
* sportsbook updates after the decision timestamp
* final injury/status information not yet known
* game results
* later market movement

Configurable Decision Time

Create:

DECISION_HOURS_BEFORE_KICKOFF

Default:

12 hours

But run separate backtests for:

72 hours
24 hours
12 hours
6 hours
1 hour

This determines whether line movement is more useful close to kickoff.

The production optimizer should ultimately use the calibration corresponding most closely to when the user normally submits picks.

⸻

7. Defining the Historical Reference Line

Do not rely exclusively on a vague concept of “opening line.”

Early college-football lines sometimes appear weeks or months ahead of kickoff and can behave differently from the mature weekly betting market.

Create multiple reference horizons.

Reference Snapshots

For each game capture Pinnacle prices closest to but not later than:

T-7 days
T-72 hours
T-24 hours
T-12 hours
T-6 hours
T-1 hour

Also capture:

FIRST_AVAILABLE_PINNACLE_LINE

The model can then evaluate:

open_to_current
72h_to_current
24h_to_current
12h_to_current
6h_to_current

This makes the definition reproducible.

⸻

8. Canonical Team Perspective

All spread calculations must be stored from the perspective of one specific team.

Recommended schema:

game_id
team
opponent
is_home
spread_reference
spread_current
moneyline_reference
moneyline_current

Define favorable spread movement as:

spread_move = spread_reference - spread_current

Examples:

-3 -> -5
-3 - (-5) = +2
Favorable = +2
+7 -> +4
+7 - (+4) = +3
Favorable = +3
-7 -> -4
-7 - (-4) = -3
Unfavorable = -3

Positive values must always represent movement toward the selected team.

⸻

9. No-Vig Moneyline Probability

Convert both sides’ sharp moneylines into implied probabilities.

For American odds:

if odds < 0:
    implied = abs(odds) / (abs(odds) + 100)
else:
    implied = 100 / (odds + 100)

Then remove vig:

p_team_no_vig =
    p_team_raw /
    (p_team_raw + p_opponent_raw)

Save:

p_current
p_reference

The current no-vig probability is the primary baseline predictor.

⸻

10. Additional Market Movement Features

Create the following variables.

Spread Movement

spread_move

Moneyline Probability Movement

prob_move =
p_current - p_reference

Example:

Opening probability = 61%
Current probability = 66%
prob_move = +5 percentage points

Log-Odds Movement

Preferred statistically:

logit_move =
logit(p_current) - logit(p_reference)

Movement Velocity

spread_move / hours_elapsed

Recent Movement

Examples:

spread_move_last_24h
spread_move_last_6h
prob_move_last_24h
prob_move_last_6h

These allow the backtest to distinguish between:

slow drift

and:

late sharp movement

⸻

11. Initial Line Movement Buckets

Do not begin by optimizing arbitrary bucket boundaries.

Start with predetermined 0.5/1.0-point-oriented bins:

<= -3.0
-3.0 to -1.5
-1.5 to -0.5
-0.5 to +0.5
+0.5 to +1.5
+1.5 to +3.0
>= +3.0

These provide enough granularity to observe the shape of the relationship without creating dozens of low-sample cells.

For every bucket calculate:

Games
Wins
Actual Win %
Average Current No-Vig Win %
Raw Residual
Brier Score
Log Loss

Where:

Raw Residual =
Actual Win %
-
Average Current No-Vig Win %

⸻

12. Probability-Stratified Matrix

A single movement adjustment across all favorites is likely too simplistic.

A +2-point move should not automatically have the same probability impact for:

52% favorite

and:

90% favorite

Therefore construct a two-dimensional matrix.

Dimension 1 — Current No-Vig Probability

Suggested bands:

50%-55%
55%-60%
60%-70%
70%-80%
80%-90%
90%+

Dimension 2 — Spread Movement

<= -3.0
-3.0 to -1.5
-1.5 to -0.5
-0.5 to +0.5
+0.5 to +1.5
+1.5 to +3.0
>= +3.0

Each cell should output:

N
Expected Win %
Actual Win %
Raw Residual
Shrunk Residual
95% CI

Example final structure:

Current P	<-3	-3:-1.5	-1.5:-0.5	Neutral	+0.5:+1.5	+1.5:+3	>+3
50-55%	?	?	?	0	?	?	?
55-60%	?	?	?	0	?	?	?
60-70%	?	?	?	0	?	?	?
70-80%	?	?	?	0	?	?	?
80-90%	?	?	?	0	?	?	?
90%+	?	?	?	0	?	?	?

This becomes the candidate production matrix.

⸻

13. Statistical Model

Do not rely only on raw bucket win rates.

Fit a probabilistic model.

Baseline:

logit(P(win)) =
α
+ β1 × logit(current_no_vig_probability)

Movement model:

logit(P(win)) =
α
+ β1 × logit(current_no_vig_probability)
+ f(spread_move)

where:

f(spread_move)

is initially modeled using either:

1. restricted cubic spline, or
2. piecewise linear spline

Preferred implementation:

sklearn
statsmodels

Do not start with XGBoost/random forest.

The objective is inference and calibration, not maximum model complexity.

⸻

14. Critical Model Comparison

Compare:

Model A — Sharp Market Only

P(win) = current Pinnacle no-vig probability

Model B — Sharp Market + Spread Movement

current probability
+
spread movement

Model C — Sharp Market + Full Movement Features

current probability
spread movement
moneyline movement
recent movement
movement velocity

The movement concept only survives if Model B/C outperform Model A out-of-sample.

⸻

15. Evaluation Metrics

Primary metrics:

Log Loss
Brier Score
Calibration Error

Secondary:

Accuracy
Pick'em Expected Confidence Points

Do not optimize primarily on straight accuracy.

A model that changes:

70% -> 73%

without changing the predicted winner can materially improve confidence ranking even though classification accuracy remains unchanged.

⸻

16. Walk-Forward Validation

Never randomly split individual games across train/test datasets.

Use season-based walk-forward validation.

Example:

Train: 2020-2022
Test:  2023
Train: 2020-2023
Test:  2024
Train: 2020-2024
Test:  2025

For the current 2026 season:

Train: 2020-2025
Validate historically
Deploy: 2026

This more closely approximates the real production workflow.

⸻

17. Bootstrap Confidence Intervals

For each movement bucket/matrix cell, estimate uncertainty using bootstrap resampling.

Use:

1,000+ bootstrap iterations

Prefer resampling by:

week

or:

week-season cluster

rather than individual games.

This protects against correlated market conditions within the same week.

Output:

estimated uplift
lower 95% CI
upper 95% CI

Example:

+1.2%
CI: -0.4% to +2.7%

This should NOT automatically become a +1.2% production adjustment because the estimate is weak.

⸻

18. Shrinkage

Raw cell-level residuals will be noisy.

Apply shrinkage toward zero.

At minimum:

adjustment =
raw_adjustment × reliability_weight

Example reliability structure:

N < 50       -> very heavy shrinkage
50-100       -> heavy shrinkage
100-250      -> moderate shrinkage
250-500      -> light shrinkage
500+         -> minimal shrinkage

Preferred implementation:

Empirical Bayes / hierarchical model

where movement buckets are partially pooled.

The goal is to prevent:

N = 23
Observed uplift = +7%

from becoming a production rule.

⸻

19. Key-Number Analysis

As a secondary analysis, create flags for lines crossing common football spread numbers.

Examples:

cross_3
cross_7
cross_10
cross_14

Example:

-2.5 -> -3.5

may convey more market information than:

-4.0 -> -5.0

even though both are 1-point moves.

Test interaction:

spread_move × crossed_key_number

Do not add this to production unless out-of-sample performance supports it.

⸻

20. Sharp Consensus Extension

Pinnacle movement alone should be Model V1.

Model V2 may construct a broader market indicator.

For every snapshot calculate:

median_market_spread
number_of_books
pct_books_moving_toward_team
dispersion_of_spreads
pinnacle_vs_market_difference

Potential signal:

Pinnacle moves first
+
majority of books subsequently follow

This is more consistent with the concept of “steam” than merely observing one sportsbook moving.

Call this:

movement_breadth

and test it separately.

⸻

21. Late Movement Test

Line movement may be more predictive when it happens close to kickoff.

Create:

move_72h_to_24h
move_24h_to_6h
move_6h_to_1h

Then determine whether:

+2 points over 72 hours

behaves differently from:

+2 points during the final 6 hours

Again, condition everything on the final/current no-vig probability.

⸻

22. Backtesting the Current Hand-Written Matrix

Explicitly test the existing rules as a benchmark.

Current rules:

if movement > 2.5:
    adjustment = +0.030
elif movement >= 1.0:
    adjustment = +0.015
elif -0.5 <= movement <= 0.5:
    adjustment = 0
elif movement <= -2.5:
    adjustment = -0.030
elif movement <= -1.0:
    adjustment = -0.015

Run historical ESPN-style confidence simulations using:

Strategy 1

Current Pinnacle probability only

Strategy 2

Current Pinnacle probability
+
existing manual matrix

Strategy 3

Current Pinnacle probability
+
data-derived matrix

Strategy 4

calibrated continuous movement model

Compare all four.

⸻

23. Simulated ESPN Pick’em Confidence Score

For every historical week:

1. Select a set of 10 games.
2. Predict each winner.
3. Rank predicted winners by probability.
4. Assign confidence:

10
9
8
...
1

5. Score actual outcomes.

Weekly score:

score =
sum(confidence_points for correctly predicted games)

Maximum:

55

Calculate:

Mean weekly score
Median weekly score
Standard deviation
10th percentile
25th percentile
75th percentile
90th percentile
Maximum

Most importantly:

Incremental expected points vs market-only baseline

⸻

24. Creating ESPN-Like Historical Weeks

Historical sportsbook data contains far more than 10 games per week.

The backtest must avoid choosing an artificially favorable test set.

Support three game-selection modes.

Mode A — All Games

Evaluate underlying probability calibration across every eligible FBS game.

Mode B — Random 10

For each historical week:

randomly sample 10 eligible FBS games

Repeat:

1,000 simulations

Mode C — ESPN-Like

Approximate ESPN Pick’em selection based on games more likely to appear in the contest.

Potential filters:

Power-conference games
ranked teams
nationally relevant games
moderate spreads
Saturday games

Do not tune these criteria based on results.

If actual historical ESPN Pick’em matchup lists can later be collected, replace this approximation with the real lists.

⸻

25. Public Pick Percentage

Do NOT mix public pick percentage into the line-movement calibration.

Treat it as a separate optimization layer.

The base model should answer:

What is the probability Team A wins?

Public percentage answers a different question:

How valuable is Team A relative to the pool?

Those must remain separate.

Pipeline:

Sharp Probability
    ↓
Line Movement Calibration
    ↓
Final Win Probability
    ↓
Pick Selection
    ↓
Public / Tournament Strategy
    ↓
Confidence Optimization

Historical ESPN public percentages should only be incorporated if reliable historical data becomes available.

⸻

26. Production Matrix Construction

After walk-forward validation, generate:

line_movement_matrix.csv

Suggested schema:

probability_min
probability_max
movement_min
movement_max
sample_size
raw_adjustment
shrunk_adjustment
ci_lower
ci_upper
production_adjustment

Example:

probability_min,probability_max,movement_min,movement_max,sample_size,raw_adjustment,shrunk_adjustment,ci_lower,ci_upper,production_adjustment
0.60,0.70,1.5,3.0,512,0.012,0.009,0.002,0.017,0.009

⸻

27. Production Inclusion Rule

A cell should only receive a non-zero adjustment when:

1. Sample size is sufficient
2. Direction is reasonably stable across seasons
3. Adjustment survives shrinkage
4. Out-of-sample Brier/log-loss improves
5. Pick'em simulation does not deteriorate

Do not require conventional p < 0.05 mechanically.

But uncertain or unstable effects should be aggressively shrunk toward zero.

Suggested cap:

maximum movement adjustment = ±3 percentage points

until substantial evidence supports a larger value.

⸻

28. Continuous Model vs Matrix

The backtest should output both.

Matrix Model

Advantages:

* easy to inspect
* easy to explain
* easy to integrate
* stable

Continuous Model

Example:

adjustment = f(
    current_probability,
    spread_move
)

Advantages:

* avoids artificial thresholds
* more statistically efficient
* handles nonlinear relationships

Use the continuous model as the analytical benchmark.

If the matrix performs nearly as well, use the matrix in production for simplicity.

⸻

29. Recommended Repository Structure

cfb-pickem/
│
├── data/
│   ├── raw/
│   │   ├── odds_api/
│   │   └── cfbd/
│   │
│   ├── processed/
│   │   ├── games.parquet
│   │   ├── odds_snapshots.parquet
│   │   └── backtest_dataset.parquet
│   │
│   └── outputs/
│       ├── line_movement_matrix.csv
│       └── model_metrics.csv
│
├── src/
│   ├── data/
│   │   ├── fetch_odds_history.py
│   │   ├── fetch_results.py
│   │   ├── team_mapping.py
│   │   └── build_dataset.py
│   │
│   ├── features/
│   │   └── market_movement.py
│   │
│   ├── models/
│   │   ├── baseline_market.py
│   │   ├── movement_model.py
│   │   ├── calibration.py
│   │   └── matrix_builder.py
│   │
│   ├── backtest/
│   │   ├── walk_forward.py
│   │   ├── pickem_simulator.py
│   │   └── bootstrap.py
│   │
│   └── reporting/
│       └── generate_report.py
│
├── config/
│   ├── backtest.yaml
│   └── team_aliases.yaml
│
├── notebooks/
│   └── movement_analysis.ipynb
│
└── tests/

⸻

30. Data Model

Primary backtest dataset should contain one row per:

game × team × decision horizon

Required columns:

game_id
season
week
game_date
kickoff_timestamp
team
opponent
home_away
neutral_site
decision_horizon_hours
reference_timestamp
reference_spread
reference_spread_price
reference_moneyline
reference_probability
current_timestamp
current_spread
current_spread_price
current_moneyline
current_probability
spread_move
moneyline_probability_move
logit_move
spread_move_24h
spread_move_6h
cross_3
cross_7
cross_10
cross_14
final_team_score
final_opponent_score
win
sharp_source
data_quality_flag

⸻

31. Required Diagnostic Charts

Generate the following automatically.

Chart 1

Movement bucket
vs
Observed - Expected win probability

with confidence intervals.

Chart 2

Spread movement
vs
calibrated probability adjustment

using the continuous model.

Chart 3

Calibration curves:

Pinnacle Only
Pinnacle + Movement

Chart 4

Historical ESPN-style weekly confidence scores:

Baseline
Manual Matrix
Data-Derived Matrix
Continuous Model

Chart 5

Movement adjustment by current probability band.

⸻

32. Automated Research Report

The pipeline should produce:

backtest_report.md

with the following sections:

1. Executive Summary
2. Dataset Coverage
3. Data Quality
4. Does Line Movement Matter?
5. Effect by Movement Size
6. Effect by Favorite Strength
7. Effect by Time Horizon
8. Walk-Forward Results
9. ESPN Confidence Simulation
10. Recommended Production Matrix
11. Comparison vs Existing Matrix
12. Limitations

The executive summary must explicitly state one of:

A. Strong evidence for line-movement adjustment
B. Weak/modest evidence
C. No meaningful incremental value
D. Evidence movement worsens probability estimates

⸻

33. Acceptance Tests

The implementation is complete when all of the following are true.

Data integrity

* No post-decision odds appear in model features.
* Home/away orientation is validated.
* Positive spread movement always means favorable movement.
* No-vig probabilities for both teams sum to ~1.
* Game results reconcile to CollegeFootballData.

Modeling

* Market-only baseline exists.
* Movement model exists.
* Season walk-forward validation exists.
* Brier and log-loss comparison exists.
* Bootstrap confidence intervals exist.
* Matrix adjustments are shrunk toward zero.

Pick’em simulation

* Picks select the higher calibrated probability.
* Confidence 10 is assigned to the highest probability game.
* Confidence 1 is assigned to the lowest.
* Maximum weekly score is 55.
* Baseline and movement strategies use identical historical game sets.

Reproducibility

Running:

python -m src.backtest.run

should regenerate:

backtest_dataset.parquet
line_movement_matrix.csv
model_metrics.csv
backtest_report.md

from cached raw data.

⸻

34. Recommended MVP

Do not build every advanced feature initially.

MVP V1

Use:

2021-2025 NCAAF
Pinnacle
FBS vs FBS
24-hour decision point
72-hour reference point
Current no-vig moneyline
Spread movement

Estimate:

Baseline = current Pinnacle probability
Candidate = current Pinnacle probability + movement

Produce:

7 movement buckets
×
6 probability bands

and run walk-forward validation.

This answers the most important question with minimal complexity.

⸻

35. Phase 2

Only after V1 proves that movement adds value, add:

multiple decision horizons
opening-line movement
late steam
moneyline movement
key-number crossings
market breadth
Pinnacle-vs-consensus movement
ESPN public percentage
historical contest simulations

Do not build these before establishing that basic movement contains incremental signal.

⸻

36. Production Integration

Replace the existing hard-coded function:

def movement_adjustment(delta_spread):
    ...

with:

def movement_adjustment(
    current_probability,
    delta_spread
):
    return lookup_calibrated_adjustment(
        current_probability,
        delta_spread
    )

Then:

base_probability = current_pinnacle_no_vig
movement_adj = movement_adjustment(
    current_probability=base_probability,
    delta_spread=spread_move
)
final_probability = base_probability + movement_adj

Clamp:

final_probability = min(
    max(final_probability, 0.01),
    0.99
)

Confidence rankings are then based on:

final_probability

rather than arbitrary movement points.

⸻

37. Primary Research Question

The entire project should ultimately answer:

If Pinnacle currently says a team has a 65% chance of winning, should we assign a different probability depending on whether that team moved from -3 to -6, stayed at -6, or moved from -8 to -6?

That is the economically and statistically correct test of the line-movement hypothesis.

The final matrix must be a consequence of the answer to that question—not an assumption built into the model.
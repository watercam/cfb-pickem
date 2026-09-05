# ESPN College Football Pick'em 2026 - Rules & Optimization Model

## Overview
ESPN College Football Pick'em is a weekly prediction game where players pick the winners of selected US college football games over a 14-week season (Sept 5, 2026 - Dec 5, 2026).

## Game Modes
Players can create up to 5 entries and play in three different game modes:

### 1. Standard Scoring System
- **Objective:** Pick the outright winner of the game (the team that scores more points).
- **Scoring:** Each correct pick is worth 10 points.
- **Strategy:** Focus purely on win probabilities (moneyline odds).

### 2. Spread Scoring System
- **Objective:** Pick the team that covers the point spread.
- **Scoring:** Each correct pick is worth 10 points.
- **How it works:** 
  - If you pick the FAVORITE: They must win by more than the spread.
  - If you pick the UNDERDOG: They must win outright OR lose by less than the spread.
- **Strategy:** Focus on spread betting models, finding value where the ESPN spread differs from sharp sportsbooks or predictive models.

### 3. Confidence Scoring System
- **Objective:** Pick the outright winner AND assign a confidence value to each pick.
- **Scoring:** You assign a unique point value (from 1 up to 10, depending on the number of games) to each pick. A correct pick earns that number of points.
- **Strategy:** Rank games by win probability. Assign the highest points to the biggest favorites, and the lowest points to toss-up games.

## Tiebreakers
In the event of a tie for weekly or overall prizes:
1. Higher number of points scored in the most recent week (e.g., Week 14, then Week 13, etc.)
2. For weekly prizes: A predicted score for a designated Tiebreaker Game is used. The entrant whose predicted total score is closest to the actual total score wins.

## Optimization Strategy

To optimize the likelihood of winning, we need a model that handles all three game modes:

### Data Sources Needed
1. **Win Probabilities (Moneyline):** To optimize Standard and Confidence modes.
2. **Point Spreads & Expected Margins:** To optimize Spread mode.
3. **Public Pick Percentages:** To find contrarian value (crucial for large-field tournaments).

### Mode-Specific Optimization

#### Standard Mode Optimization
- **Goal:** Maximize expected points.
- **Approach:** Always pick the team with the highest win probability ($P(Win) > 0.5$).
- **Tournament Adjustment:** If trying to win a large pool, we may need to pick slight underdogs if the public is heavily over-picking the favorite (Game Theory).

#### Spread Mode Optimization
- **Goal:** Maximize expected points against the spread.
- **Approach:** Compare ESPN's spread to a sharp consensus spread (e.g., Pinnacle, Circa) or a predictive model (e.g., SP+, FPI).
- **Selection:** Pick the team where the expected margin of victory provides the most value against the ESPN spread.

#### Confidence Mode Optimization
- **Goal:** Maximize expected points by optimally assigning confidence weights.
- **Approach:** 
  1. Sort all games by Win Probability (highest to lowest).
  2. Assign the highest confidence points to the highest win probabilities.
  3. **Tournament Adjustment:** In large pools, we can optimize by looking at Expected Value (EV) relative to public pick percentages. If a heavy favorite is being picked by 99% of the public, we still pick them with high confidence. But if a 60% favorite is being picked by 90% of the public, we might lower their confidence or pick the underdog to gain an edge on the field.

### Mathematical Model for Confidence Mode
Let $N$ be the number of games (e.g., 10).
Let $p_i$ be the probability of our selected team winning game $i$.
Let $c_i \in \{1, 2, ..., N\}$ be the confidence points assigned to game $i$.

We want to maximize Expected Points:
$E[Points] = \sum_{i=1}^{N} p_i \cdot c_i$

To maximize this, we simply sort the games such that:
$p_1 \le p_2 \le ... \le p_N$
And assign confidence points:
$c_1 = 1, c_2 = 2, ..., c_N = N$

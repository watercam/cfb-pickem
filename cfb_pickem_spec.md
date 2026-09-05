# ESPN College Football Pick'em - Automation & Optimization Tool Spec

## 1. Overview
This specification outlines a tool designed to automate and optimize picks for the ESPN College Football Pick'em game (Confidence Mode). The tool will read the weekly matchups directly from the user's active ESPN session, fetch sharp sportsbook odds and line movement data, calculate the optimal picks and confidence points (1-10), and provide the recommended entries.

## 2. System Architecture

### Components
1. **Scraper / Browser Automation (Playwright)**
   - Connects to the user's active browser session (or runs a standalone authenticated session) to scrape the weekly matchups, team names, and current public pick percentages from ESPN.
2. **Odds Integration Module**
   - Connects to a sharp sports betting data provider (e.g., The Odds API, Pinnacle, or Circa Sports) to fetch current moneylines, point spreads, and historical line movement (opening lines vs. current lines).
3. **Optimization Engine (Backend)**
   - A Python-based modeling engine that calculates true win probabilities, adjusts them based on line movement, and ranks the 10 games to assign confidence points (1 through 10).
4. **Output / Auto-fill (Playwright)**
   - Outputs the optimal picks to the user and (optionally) uses Playwright to automatically click the UI elements on ESPN to save the picks.

## 3. Data Flow

1. **Extract Matchups:** Playwright navigates to `https://fantasy.espn.com/games/college-football-pickem-2026/picks`. It parses the DOM to extract the 10 games for the current week, including Away Team, Home Team, and Public Pick %.
2. **Fetch Sharp Odds:** The backend queries an odds API for the extracted matchups to get the Current Moneyline, Current Spread, and Opening Spread from a sharp book (e.g., Pinnacle).
3. **Calculate Base Win Probability:** Convert the sharp moneyline into an implied win probability, removing the vig (sportsbook juice).
4. **Apply Line Movement Matrix:** Adjust the base probability using a scoring matrix based on how the spread has moved since opening.
5. **Rank and Assign Confidence:** Sort the 10 games by their adjusted win probabilities. Assign 10 points to the highest probability, down to 1 point for the lowest.
6. **Execute Picks:** Display the results and/or push them back to the ESPN UI.

## 4. Modeling & Scoring Matrix

### A. Base Win Probability
The most accurate predictor of a college football game is a sharp sportsbook's moneyline.
1. Convert American Odds to Implied Probability:
   - Positive Odds (e.g., +150): `100 / (Odds + 100)`
   - Negative Odds (e.g., -170): `|Odds| / (|Odds| + 100)`
2. Remove the Vig (Juice) to get the "True" Base Probability.

### B. Line Movement Adjustment (The Scoring Matrix)
Sharp money moves lines. If a team opens at -3 and moves to -4.5, sharp bettors are backing them. We want to slightly overweight teams that have seen favorable line movement.

Let $\Delta S$ be the Spread Movement = (Opening Spread - Current Spread).
*(Note: Spreads are negative for favorites. If a team goes from -3 to -5, $\Delta S = -3 - (-5) = +2$ points of favorable movement).*

**Adjustment Matrix:**
- **Favorable Movement > 2.5 points:** +3.0% to Base Probability
- **Favorable Movement 1.0 to 2.5 points:** +1.5% to Base Probability
- **Neutral Movement (-0.5 to +0.5 points):** 0.0% adjustment
- **Unfavorable Movement -1.0 to -2.5 points:** -1.5% to Base Probability
- **Unfavorable Movement < -2.5 points:** -3.0% to Base Probability

*Example:* Team A has a true win probability of 65.0%. Their spread opened at -4.0 and moved to -6.0 (Favorable movement of +2.0). 
Adjusted Probability = 65.0% + 1.5% = 66.5%.

### C. Public Pick Percentage (Tournament Adjustment)
For large pools, picking what everyone else picks limits your ability to gain ground. 
- If Adjusted Probability > 50% AND Public Pick % is extremely high (> 90%), slightly lower the confidence score to differentiate your entry.
- If Adjusted Probability > 50% AND Public Pick % is low (< 40%), this is a "Value Play". Increase confidence points.

### D. Confidence Assignment
1. Calculate the **Final Score** for all 20 teams (10 matchups).
2. For each of the 10 matchups, select the team with the higher Final Score.
3. Sort the 10 selected teams descending by their Final Score.
4. Assign 10 points to the top team, 9 to the second, ..., 1 to the bottom team.

## 5. Implementation Roadmap

### Phase 1: Data Extraction
- Build a Playwright script that logs into ESPN (or uses an existing user data directory to bypass login).
- Scrape the 10 matchups and public percentages.

### Phase 2: Odds Integration
- Integrate `The-Odds-API` (or similar) to fetch NCAAF odds.
- Write a fuzzy-matching algorithm to match ESPN team names (e.g., "Tulane") with Sportsbook team names (e.g., "Tulane Green Wave").

### Phase 3: Optimization Engine
- Implement the math model in Python.
- Take the scraped games + fetched odds and output the 1-10 confidence rankings.

### Phase 4: Automation
- Extend the Playwright script to take the output from Phase 3 and automatically click the corresponding "Select Winner" and "Points for Win" dropdowns on the ESPN page.
- Click "Save Picks".
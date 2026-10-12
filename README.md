# CFB Pick’em

Weekly ESPN College Football Pick’em (confidence mode): rank the 10-game slate from **current Pinnacle no-vig moneyline** plus T-72 spread move, with production calibration set to **none**. A phone dashboard is a static snapshot of `web/recommendations.json` on Netlify. Every refresh path ranks **once**, deploys that JSON, then publishes the **same** payload to Slack with a shared stamp (`Updated 5:31 PM ET, run 123`).

## Weekly live run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Put secrets in `.env` (never commit that file):

- `ODDS_API_KEY` — The Odds API (Pinnacle current + historical T-72)
- `SLACK_WEBHOOK_URL` — Incoming Webhook for the channel you want pings in
- `SLACK_BOT_TOKEN` / `SLACK_CHANNEL_ID` — optional; edit the same Slack message on every refresh
- `CFBD_API_KEY` — only needed for the research backtest

Offline (no keys):

```bash
python -m src.pickem.run --fixture tests/fixtures/pickem_week.json --web
cd web && python3 -m http.server 8765
# open http://127.0.0.1:8765
```

Live ESPN Gambit JSON + Pinnacle (needs `ODDS_API_KEY`):

```bash
python -m src.pickem.run --web --no-slack
# Slack is published from the JSON after a Netlify deploy:
python -m src.pickem.publish --from-web
# inspect the Slack body without posting:
python -m src.pickem.publish --from-web --dry-run
```

Laptop Netlify deploy (same shared publish path):

```bash
chmod +x scripts/publish_pickem.sh   # once
./scripts/publish_pickem.sh --live
```

`--live` runs `python -m src.pickem.run --web --no-slack`, `npx netlify-cli deploy --dir=web --functions=netlify/functions --prod`, then `python -m src.pickem.publish --from-web`.

One-time Netlify: `npx --yes netlify-cli login` then `npx --yes netlify-cli init` with publish directory `web`. Dashboard URL lives in `config/pickem.yaml` as `slate.dashboard_url`.

### Slack (one-time, in the browser)

While signed into Slack: Incoming Webhooks → choose a channel → copy the URL into GitHub Actions secrets and local `.env`. Do not scrape Slack’s UI. Posts are skipped when the webhook is unset so tests stay key-free.

**Preferred behavior:** edit the original Pick’em message in place. Incoming webhooks cannot do that. Add a Slack app bot token (`chat:write`) and the channel id as `SLACK_BOT_TOKEN` and `SLACK_CHANNEL_ID` in GitHub Actions (and locally). The first run posts once and stores `slack.ts` on the live `recommendations.json`; later runs call `chat.update` on that message. Without the bot token, the job still posts a **new** webhook message after the dashboard deploy (same stamp, but the message you clicked will not change).

Success messages include week, `calibration none`, the shared `Updated … ET, run <id>` stamp, the dashboard URL, a compact 10-row confidence table, plus `pick_change` / `rank_change` lines. A new week still pings with `new week slate`. Workflow failures send a short error post via the webhook.

### Refresh paths

All three of these compute the ranking in `.github/workflows/pickem-refresh.yml` and publish that JSON to Netlify **before** Slack:

1. Scheduled cron (Thu–Sat Eastern windows)
2. **Actions → Pick'em refresh → Run workflow** (`workflow_dispatch`)
3. **Run refresh** in Slack — either the GitHub Actions workflow page (`slate.refresh_url`) or, if configured, `/.netlify/functions/refresh`, which dispatches that same workflow

The dashboard fetches `recommendations.json` with a cache-buster and the file is deployed with `Cache-Control: no-store`. Compare the stamp on Slack and the dashboard lede; they must match.

Optional one-click Slack link (Netlify → GitHub `workflow_dispatch`):

1. Create a GitHub PAT with `actions:write` on this repo. Store it as Netlify env `GITHUB_DISPATCH_TOKEN`.
2. Pick a random string. Store it as GitHub Actions secret **and** Netlify env `PICKEM_REFRESH_SECRET`.
3. Redeploy once so `netlify/functions/refresh.js` is live.
4. Later Slack messages will use `https://cfb-pickem-845.netlify.app/.netlify/functions/refresh?token=…` as the button URL. Do not commit that token.

### GitHub Actions

[`.github/workflows/pickem-refresh.yml`](.github/workflows/pickem-refresh.yml) runs on `workflow_dispatch` and Thu–Sat cron (UTC covering Thu evening / Fri midday+evening / Sat morning+midday Eastern). It does **not** run on `pull_request`.

Each run (`PICKEM_RUN_ID` = `github.run_id`):

1. `python -m src.pickem.run --web --no-slack` — GETs the live `recommendations.json` (notes / insights / tiebreak / alerts / Slack message pointer), then ranks ESPN Gambit + Pinnacle. No `--fixture` fallback. Writes `run_id` and `updated_stamp`.
2. `npx netlify-cli deploy --dir=web --functions=netlify/functions --prod`
3. `python -m src.pickem.publish --from-web` — Slack from that same JSON
4. Redeploy only if a new Slack message pointer was stored

Repo **Settings → Secrets and variables → Actions**:

- `ODDS_API_KEY` — same value as local `.env`
- `SLACK_WEBHOOK_URL` — Incoming Webhook URL (optional; success/failure posts skip if empty)
- `SLACK_BOT_TOKEN` — optional bot token so refreshes **edit** the existing Slack message
- `SLACK_CHANNEL_ID` — optional; required with the bot token (`C…`)
- `PICKEM_REFRESH_SECRET` — optional; enables the Netlify one-click refresh button
- `NETLIFY_AUTH_TOKEN` — Netlify personal access token (User settings → Applications → New access token), not the browser login cookie
- `NETLIFY_SITE_ID` — Project Id from `npx netlify-cli status` (this site: `a16d0891-5afa-4733-9fd6-4e065357f0b5`)

Dashboard: https://cfb-pickem-845.netlify.app (`slate.dashboard_url`).

This repo must be on GitHub with that workflow file before cron or **Run workflow** can fire. `gh` is not required on the laptop; Actions runs on GitHub after the first push.

Never put those in git or in `web/`. Do not upload `data/raw/` or `.env` as artifacts. Odds `apiKey` query strings are stripped from logged URLs. Snapshot JSON is not committed each run; previous state comes from the live site.

After secrets are set, run **Actions → Pick'em refresh → Run workflow** once and confirm Netlify and Slack show the same `Updated …, run <id>` line.

## Research backtest

Primary research spec: `NCAAF Line Movement Backtesting & Calibration Specification.md`.

```bash
python -m src.backtest.run --mode cache_only
```

That writes `data/processed/backtest_dataset.parquet`, `data/outputs/line_movement_matrix.csv`, `data/outputs/model_metrics.csv`, and `data/outputs/backtest_report.md`.

Odds API historical pulls are extra:

```bash
python -m src.backtest.run --mode fetch_missing --dry-run-fetch
# review credit estimate, set allow_historical_fetch: true in config/backtest.yaml
python -m src.backtest.run --mode fetch_missing --confirm-fetch
```

`cache_only` does not require API keys if `data/raw/cfbd` and `data/raw/odds_api/snapshots` already exist. Missing Pinnacle books are never replaced with another sportsbook.

V1 scope: seasons 2021–2025, FBS vs FBS, Pinnacle only, 24-hour decision time, 72-hour reference line, current no-vig moneyline vs spread movement residual, season walk-forward, shrunk 7×6 matrix.

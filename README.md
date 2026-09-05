# CFB Pick’em

Weekly ESPN College Football Pick’em (confidence mode): rank the 10-game slate from **current Pinnacle no-vig moneyline** plus T-72 spread move, with production calibration set to **none**. A phone dashboard is a static snapshot of `web/recommendations.json` on Netlify. GitHub Actions refreshes ESPN + Odds and posts Slack Incoming Webhooks.

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
- `CFBD_API_KEY` — only needed for the research backtest

Offline (no keys):

```bash
python -m src.pickem.run --fixture tests/fixtures/pickem_week.json --web
cd web && python3 -m http.server 8765
# open http://127.0.0.1:8765
```

Live ESPN Gambit JSON + Pinnacle (needs `ODDS_API_KEY`):

```bash
python -m src.pickem.run --web
# skip Slack even if SLACK_WEBHOOK_URL is set:
python -m src.pickem.run --web --no-slack
```

Laptop Netlify deploy (same Slack path if `.env` has the webhook):

```bash
chmod +x scripts/publish_pickem.sh   # once
./scripts/publish_pickem.sh --live
```

`--live` runs `python -m src.pickem.run --web` then `npx netlify-cli deploy --dir=web --prod`.

One-time Netlify: `npx --yes netlify-cli login` then `npx --yes netlify-cli init` with publish directory `web`. Dashboard URL lives in `config/pickem.yaml` as `slate.dashboard_url`.

### Slack (one-time, in the browser)

While signed into Slack: Incoming Webhooks → choose a channel → copy the URL into GitHub Actions secrets and local `.env`. Do not scrape Slack’s UI. The job POSTs JSON (`text`). Posts are skipped when the webhook is unset so tests stay key-free.

Success messages include week, `calibration none`, `generated_at`, the dashboard URL, a compact 10-row confidence table, plus `pick_change` / `rank_change` lines. A new week (no same-week previous JSON) still pings with `new week slate`. Workflow failures send a short error post.

### GitHub Actions

[`.github/workflows/pickem-refresh.yml`](.github/workflows/pickem-refresh.yml) runs on `workflow_dispatch` and Thu–Sat cron (UTC covering Thu evening / Fri midday+evening / Sat morning+midday Eastern). It does **not** run on `pull_request`.

Each run:

1. `python -m src.pickem.run --web` — GETs the live `recommendations.json` (notes / insights / tiebreak / alerts), then ranks ESPN Gambit + Pinnacle. No `--fixture` fallback.
2. `npx netlify-cli deploy --dir=web --prod`

Repo **Settings → Secrets and variables → Actions**:

- `ODDS_API_KEY` — same value as local `.env`
- `SLACK_WEBHOOK_URL` — Incoming Webhook URL (optional; success/failure posts skip if empty)
- `NETLIFY_AUTH_TOKEN` — Netlify personal access token (User settings → Applications → New access token), not the browser login cookie
- `NETLIFY_SITE_ID` — Project Id from `npx netlify-cli status` (this site: `a16d0891-5afa-4733-9fd6-4e065357f0b5`)

Dashboard: https://cfb-pickem-845.netlify.app (`slate.dashboard_url`).

This repo must be on GitHub with that workflow file before cron or **Run workflow** can fire. `gh` is not required on the laptop; Actions runs on GitHub after the first push.

Never put those in git or in `web/`. Do not upload `data/raw/` or `.env` as artifacts. Odds `apiKey` query strings are stripped from logged URLs. Snapshot JSON is not committed each run; previous state comes from the live site.

After secrets are set, run **Actions → Pick'em refresh → Run workflow** once and confirm Netlify updates and a Slack message arrives.

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

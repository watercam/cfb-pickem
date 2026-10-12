#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

if [[ "${1:-}" == "--live" ]]; then
  "$PYTHON" -m src.pickem.run --web --no-slack
else
  FIXTURE="${1:-tests/fixtures/pickem_week.json}"
  "$PYTHON" -m src.pickem.run --fixture "$FIXTURE" --web --no-slack
fi

npx --yes netlify-cli deploy --dir=web --functions=netlify/functions --prod
"$PYTHON" -m src.pickem.publish --from-web

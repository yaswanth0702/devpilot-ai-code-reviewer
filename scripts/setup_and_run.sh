#!/usr/bin/env bash
# One-step setup for macOS/Linux: installs DevPilot, asks for your API key (hidden, never saved),
# runs the tests and the benchmark, and prints the results.
#
#   bash scripts/setup_and_run.sh              # Anthropic (default)
#   bash scripts/setup_and_run.sh openai       # OpenAI
#   bash scripts/setup_and_run.sh gemini       # Google Gemini
set -euo pipefail

PROVIDER="${1:-anthropic}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/agent"

say() { printf "\n\033[1;34m==> %s\033[0m\n" "$*"; }

command -v python3 >/dev/null || { echo "python3 not found. Install it with: brew install python"; exit 1; }
PYV=$(python3 -c 'import sys; print(sys.version_info >= (3, 10))')
[[ "$PYV" == "True" ]] || { echo "Python 3.10+ needed (found $(python3 --version)). Run: brew install python"; exit 1; }

say "Creating virtual environment (agent/.venv)"
[[ -d .venv ]] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

say "Installing DevPilot"
pip install -q --upgrade pip
pip install -q -e ".[dev]"

say "Running tests"
pytest -q

case "$PROVIDER" in
  anthropic) KEYVAR=ANTHROPIC_API_KEY ;;
  openai)    KEYVAR=OPENAI_API_KEY ;;
  gemini)    KEYVAR=GEMINI_API_KEY ;;
  *) echo "provider must be anthropic, openai or gemini"; exit 1 ;;
esac

if [[ -z "${!KEYVAR:-}" ]]; then
  say "Paste your $KEYVAR (input is hidden, it is NOT saved anywhere) and press Enter"
  read -r -s KEY
  echo
  [[ -n "$KEY" ]] || { echo "No key entered."; exit 1; }
  export "$KEYVAR=$KEY"
fi

say "Running the seeded-bug benchmark with $PROVIDER (14 reviews, takes a few minutes)"
python -m evals.run_eval --provider "$PROVIDER"

say "Done"
echo "Full report: $ROOT/agent/evals/results/$PROVIDER.md"
echo
echo "To review your own code later:"
echo "  source $ROOT/agent/.venv/bin/activate"
echo "  export $KEYVAR=...   # your key"
echo "  cd /path/to/any/git/project && devpilot review --provider $PROVIDER"

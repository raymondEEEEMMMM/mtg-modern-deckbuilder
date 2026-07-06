#!/usr/bin/env bash
# scripts/run_meta_snapshot.sh
#
# One-shot meta snapshot driver. Runs the full data acquisition layer
# (Top8 + Goldfish decklists + Topdeck round-level matchup data), then
# prints instructions for triggering the analysis workflow in a Claude
# session (the analysis itself is JS/Workflow-based, not shellable).
#
# Usage:
#   ./scripts/run_meta_snapshot.sh                      # current period, full pipeline
#   ./scripts/run_meta_snapshot.sh --start 2026-05-18   # explicit period start
#   ./scripts/run_meta_snapshot.sh --end 2026-06-10     # explicit period end
#   ./scripts/run_meta_snapshot.sh --smoke              # 5 events / 3 tournaments (fast)
#   ./scripts/run_meta_snapshot.sh --skip-topdeck       # decklist only, no matchup pass
#   ./scripts/run_meta_snapshot.sh --dry-run            # print commands, run nothing
#
# Required env:
#   TOPDECK_API_KEY    Topdeck.gg API key (for round-level matchup data)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Defaults
PERIOD_START=""
PERIOD_END=""
SMOKE=0
SKIP_TOPDECK=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --start)         PERIOD_START="$2"; shift 2;;
    --end)           PERIOD_END="$2"; shift 2;;
    --smoke)         SMOKE=1; shift;;
    --skip-topdeck)  SKIP_TOPDECK=1; shift;;
    --dry-run)       DRY_RUN=1; shift;;
    -h|--help)
      sed -n '2,21p' "$0"; exit 0;;
    *)
      echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

# Resolve period bounds
if [[ -z "$PERIOD_START" || -z "$PERIOD_END" ]]; then
  META_FILE="mtg_modern_data/ban_list/meta.json"
  if [[ ! -f "$META_FILE" ]]; then
    echo "ERROR: $META_FILE not found" >&2; exit 1
  fi
  if [[ -z "$PERIOD_START" ]]; then
    PERIOD_START=$(python3 -c "import json; print(json.load(open('$META_FILE'))['changes_history'][-1]['effective_date'])")
  fi
  if [[ -z "$PERIOD_END" ]]; then
    PERIOD_END=$(date +%Y-%m-%d)
  fi
fi

# Caps
if [[ $SMOKE -eq 1 ]]; then
  MAX_EVENTS=5
  MAX_TOURNAMENTS=3
else
  MAX_EVENTS=999
  MAX_TOURNAMENTS=999
fi

PY="${PYTHON:-python3}"
TOPDECK_FLAG=()
if [[ $SKIP_TOPDECK -eq 1 ]]; then
  TOPDECK_FLAG=(--skip-topdeck)
fi

step() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
run()  {
  if [[ $DRY_RUN -eq 1 ]]; then
    printf "  [dry-run] %s\n" "$*"
  else
    printf "  $ %s\n" "$*"
    eval "$@"
  fi
}

step "Period: $PERIOD_START ~ $PERIOD_END  (smoke=$SMOKE, skip_topdeck=$SKIP_TOPDECK, dry_run=$DRY_RUN)"

# 1. Top8 + Goldfish decklists
step "[1/4] Decklist fetch (Top8 + Goldfish)"
run "$PY scripts/fetch_period_data.py --start $PERIOD_START --end $PERIOD_END --max-events $MAX_EVENTS --max-tournaments $MAX_TOURNAMENTS"

# 2. Topdeck round-level matchup data
if [[ $SKIP_TOPDECK -eq 0 ]]; then
  step "[2/4] Topdeck round-level matchup data"
  if [[ -z "${TOPDECK_API_KEY:-}" ]]; then
    echo "  WARN: TOPDECK_API_KEY not set — skipping Topdeck pass."
    echo "       export TOPDECK_API_KEY=... and re-run to enable matchup data."
  else
    run "$PY scripts/topdeck_poc.py"
  fi
else
  step "[2/4] Topdeck pass skipped (--skip-topdeck)"
fi

# 3. Aggregate sideboard frequency + winrate from existing decklists
step "[3/4] Aggregate sideboard frequency + per-archetype winrate"
run "$PY scripts/aggregate_sideboard_winrate.py"

# 4. Prompt for analysis
step "[4/4] Data acquisition done. To run the meta analysis workflow:"
cat <<EOF

  Option A — interactively in this Claude Code session:
      Run the workflow script (Run ID wf_38933e14-5b4 cached, all 5 agents hit cache).
      Or simply say: "run the meta snapshot workflow".

  Option B — headless, using the analysis prompt:
      claude -p "
        Run the meta snapshot workflow. Period: $PERIOD_START ~ $PERIOD_END.
        Read mtg_modern_data/decks/raw/decklists/ for the latest decklists and
        mtg_modern_data/sources/topdeck/ for matchup data. Use the
        meta-snapshot-report skill to render the HTML.
      "

  Output artifacts to look for:
    - mtg_modern_data/decks/raw/decklists/${PERIOD_END}_top8_decklists.json
    - mtg_modern_data/decks/raw/decklists/${PERIOD_END}_goldfish_decklists.json
    - mtg_modern_data/sources/topdeck/matchup_matrix_<fetch_start>_<fetch_end>.json  (60-day window)
    - mtg_modern_data/sources/topdeck/topdeck_quality_report.json  (check coverage gate)
    - mtg_modern_data/sources/goldfish/sideboard_frequency_*.json
    - mtg_modern_data/sources/goldfish/winrate_*.json
    - mtg_modern_data/decks/reports/${PERIOD_END}_meta_snapshot.html

EOF

step "Done."

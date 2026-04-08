#!/bin/bash
#
# Presentation Generator Regression Suite
#
# Sequential pyramid orchestrator — runs tiers cheapest-first with continue-on-failure.
# Designed for after-hours scheduling via the test-suite endpoint with monopolize=true.
#
# Usage:
#   ./src/tests/run-presentation-regression.sh                # Default: render-only + Sonnet
#   ./src/tests/run-presentation-regression.sh --include-opus  # + Opus full pipeline
#   ./src/tests/run-presentation-regression.sh --include-r2p   # + Research-to-Presentation chain
#   ./src/tests/run-presentation-regression.sh --all           # Everything
#   ./src/tests/run-presentation-regression.sh --bg            # Background mode (stripped by test-suite)
#
# Scheduling via test-suite endpoint:
#   POST /api/test-suite/submit
#   {"test_types": "presentation", "scheduled_at": "2026-04-07T22:00:00-04:00"}
#
# Cost estimates per tier:
#   Tier 2 (render-only):  ~$0.00  (~60s)
#   Tier 3 (Sonnet full):  ~$0.46  (~8min)
#   Tier 4 (Opus full):    ~$2.43  (~8min)
#   Tier 5 (R2P chain):    ~$5-10  (~30min)
#
# Created: 2026-04-07 (Session 5946362f — E2E testing strategy)

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../.."  # Project root

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

INCLUDE_OPUS=false
INCLUDE_R2P=false
LOG_FILE="/tmp/presentation-regression-latest.log"
VENV_ACTIVATE="src/cosa/.venv/bin/activate"
PYTEST="python3 -m pytest"  # System python3 has pytest in Docker; matches unit/smoke runners

TOTAL=0
PASSED=0
FAILED=0
FAILED_TIERS=""

# ═══════════════════════════════════════════════════════════════════════════════
# Argument Parsing
# ═══════════════════════════════════════════════════════════════════════════════

for arg in "$@"; do
    case "$arg" in
        --include-opus) INCLUDE_OPUS=true ;;
        --include-r2p)  INCLUDE_R2P=true ;;
        --all)          INCLUDE_OPUS=true; INCLUDE_R2P=true ;;
        --bg)           ;; # Stripped by test-suite job — no action needed
        -v|--verbose)   ;; # Passed through to pytest via environment
    esac
done

# ═══════════════════════════════════════════════════════════════════════════════
# Environment Setup
# ═══════════════════════════════════════════════════════════════════════════════

# Source virtualenv if available
if [ -f "$VENV_ACTIVATE" ]; then
    source "$VENV_ACTIVATE"
fi

# Ensure PYTHONPATH includes src/
export PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"

# Source test credentials if available
HOME_DIR="${HOME:-$(getent passwd $(id -un) | cut -d: -f6)}"
if [ -f "$HOME_DIR/.lupin/test-env.sh" ]; then
    source "$HOME_DIR/.lupin/test-env.sh"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Runner Function
# ═══════════════════════════════════════════════════════════════════════════════

run_tier() {
    local name="$1"
    local cmd="$2"
    local timeout_secs="$3"
    local cost_est="$4"

    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  TIER: $name  (timeout: ${timeout_secs}s, est. cost: $cost_est)"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""

    TOTAL=$((TOTAL + 1))

    local start_time=$(date +%s)

    if timeout "$timeout_secs" bash -c "$cmd" 2>&1 | tee -a "$LOG_FILE"; then
        local end_time=$(date +%s)
        local elapsed=$((end_time - start_time))
        echo ""
        echo "  ✓ PASS: $name (${elapsed}s)"
        PASSED=$((PASSED + 1))
    else
        local exit_code=$?
        local end_time=$(date +%s)
        local elapsed=$((end_time - start_time))
        echo ""
        echo "  ✗ FAIL: $name (exit code $exit_code, ${elapsed}s)"
        FAILED=$((FAILED + 1))
        FAILED_TIERS="$FAILED_TIERS $name"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Main Execution
# ═══════════════════════════════════════════════════════════════════════════════

echo "═══════════════════════════════════════════════════════════════" | tee "$LOG_FILE"
echo "  Presentation Generator Regression Suite" | tee -a "$LOG_FILE"
echo "  Started: $(date)" | tee -a "$LOG_FILE"
echo "  Tiers: render-only + sonnet${INCLUDE_OPUS:+ + opus}${INCLUDE_R2P:+ + r2p}" | tee -a "$LOG_FILE"
echo "═══════════════════════════════════════════════════════════════" | tee -a "$LOG_FILE"

# Tier 2: Render-only (~60s, $0)
run_tier "render-only" \
    "$PYTEST src/tests/smoke/test_presentation_render_only_smoke.py --auto-proxy -v" \
    120 \
    "\$0.00"

# Tier 3: Sonnet full pipeline (~8min, $0.46)
run_tier "sonnet-full" \
    "$PYTEST src/tests/smoke/test_presentation_live_smoke.py --auto-proxy --content-model claude-sonnet-4-6 --cost-cap-usd 2.00 -v" \
    900 \
    "~\$0.46"

# Tier 4: Opus full pipeline (optional, ~8min, $2.43)
if [ "$INCLUDE_OPUS" = "true" ]; then
    run_tier "opus-full" \
        "$PYTEST src/tests/smoke/test_presentation_live_smoke.py --auto-proxy --cost-cap-usd 5.00 -v" \
        900 \
        "~\$2.43"
fi

# Tier 5: Research-to-Presentation chain (optional, ~30min, $5-10)
if [ "$INCLUDE_R2P" = "true" ]; then
    run_tier "r2p-chain" \
        "$PYTEST src/tests/smoke/test_research_to_presentation_live_smoke.py --auto-proxy --lead-model claude-haiku-4-5 --cost-cap-usd 10.00 -v" \
        2400 \
        "~\$1-3 (Haiku)"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  PRESENTATION REGRESSION RESULTS"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  Total:  $TOTAL tiers"
echo "  Passed: $PASSED"
echo "  Failed: $FAILED"
if [ -n "$FAILED_TIERS" ]; then
    echo "  Failed tiers:$FAILED_TIERS"
fi
echo ""
echo "  Log: $LOG_FILE"
echo "  Completed: $(date)"
echo ""
echo "═══════════════════════════════════════════════════════════════"

[ "$FAILED" -eq 0 ] && exit 0 || exit 1

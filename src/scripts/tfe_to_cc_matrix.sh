#!/usr/bin/env bash
# TFE-to-CC model × thinking-effort matrix runner.
#
# Kicks off the four arms defined in
# src/rnd/v0.1.6/2026.04.10-test-fix-expediter/22-model-effort-matrix-plan.md
# back-to-back against the same 11-fix cluster set, preserves each arm's
# artifacts in /tmp, and prints a summary table with paths you can diff later.
#
# Usage:
#   src/scripts/tfe_to_cc_matrix.sh              # run all four arms (A,B,C,D)
#   src/scripts/tfe_to_cc_matrix.sh --arms A,C   # subset
#   src/scripts/tfe_to_cc_matrix.sh --dry-run    # print commands only
#   src/scripts/tfe_to_cc_matrix.sh --strict     # abort on first arm failure
#
# Notes:
#   - Requires the `lupin-rest-test` Docker container to be running.
#   - Each arm takes ~8–30 min depending on model + effort; full sweep ~1–2 hrs.
#   - The harness fires a high-priority cosa-voice notification on every arm
#     finish, so you'll be pinged even if you wander off.

set -uo pipefail

# ─── Arms ───────────────────────────────────────────────────────────────
# Edit here if you want to tweak the matrix — keep keys single-letter.
declare -A ARMS
ARMS[A]="--model claude-sonnet-4-6 --effort high"
ARMS[B]="--model claude-opus-4-7   --effort low"
ARMS[C]="--model claude-opus-4-7   --effort high"
ARMS[D]="--model claude-opus-4-7   --effort xhigh"

ARM_ORDER=( A B C D )

# ─── Arg parsing ────────────────────────────────────────────────────────
SELECTED=""
DRY_RUN=0
STRICT=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --arms)   SELECTED="$2"; shift 2 ;;
        --arms=*) SELECTED="${1#*=}"; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --strict)  STRICT=1;  shift ;;
        -h|--help)
            sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "unknown arg: $1" >&2
            exit 2
            ;;
    esac
done

if [[ -n "$SELECTED" ]]; then
    IFS=',' read -r -a ARM_ORDER <<< "$SELECTED"
fi

# Validate arm names
for arm in "${ARM_ORDER[@]}"; do
    if [[ -z "${ARMS[$arm]:-}" ]]; then
        echo "unknown arm: $arm (valid: ${!ARMS[*]})" >&2
        exit 2
    fi
done

# ─── Locate repo root ───────────────────────────────────────────────────
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
HARNESS="$REPO_ROOT/src/scripts/tfe_to_cc_phase3_live.py"

if [[ ! -f "$HARNESS" ]]; then
    echo "[ERROR] harness not found at $HARNESS" >&2
    exit 1
fi

# ─── Pre-flight ─────────────────────────────────────────────────────────
if (( DRY_RUN == 0 )); then
    if ! docker ps --format '{{.Names}}' | grep -qx lupin-rest-test; then
        echo "[ERROR] lupin-rest-test container is not running." >&2
        echo "        Start it (per CLAUDE.md 'RUNNING/TESTING FASTAPI APPLICATIONS')" >&2
        echo "        and re-run this script." >&2
        exit 1
    fi
fi

RUN_TS="$( date -u +%Y%m%dT%H%M%SZ )"
MATRIX_LOG="/tmp/tfe-to-cc-matrix-$RUN_TS.log"
MATRIX_SUMMARY="/tmp/tfe-to-cc-matrix-$RUN_TS-summary.md"

banner() {
    echo
    echo "════════════════════════════════════════════════════════════════════"
    echo "   $*"
    echo "════════════════════════════════════════════════════════════════════"
}

banner "TFE-to-CC Matrix — arms: ${ARM_ORDER[*]}  |  started: $( date -Iseconds )"
echo "Matrix log: $MATRIX_LOG"
echo "Summary:    $MATRIX_SUMMARY"
echo "Harness:    $HARNESS"
echo "Dry run:    $DRY_RUN"
echo "Strict:     $STRICT"
{
    echo "# TFE-to-CC matrix run $RUN_TS"
    echo
    echo "| Arm | Flags | Exit | Duration | Changes JSON | Changes MD |"
    echo "|---|---|---|---|---|---|"
} > "$MATRIX_SUMMARY"

# ─── Arm loop ───────────────────────────────────────────────────────────
OVERALL_STATUS=0

for arm in "${ARM_ORDER[@]}"; do
    flags="${ARMS[$arm]}"
    arm_log="/tmp/tfe-to-cc-matrix-$RUN_TS-arm-$arm.log"
    banner "Arm $arm  |  $flags"
    echo "Per-arm log: $arm_log"

    if (( DRY_RUN == 1 )); then
        echo "[DRY RUN] would run: python3 $HARNESS $flags"
        echo "| $arm | \`$flags\` | (dry-run) | — | — | — |" >> "$MATRIX_SUMMARY"
        continue
    fi

    start_epoch=$( date +%s )

    # shellcheck disable=SC2086
    # Intentional word-splitting on $flags so the CLI sees separate args.
    PYTHONPATH="$REPO_ROOT/src:${PYTHONPATH:-}" \
        python3 "$HARNESS" $flags 2>&1 | tee "$arm_log"
    exit_code="${PIPESTATUS[0]}"

    end_epoch=$( date +%s )
    duration=$(( end_epoch - start_epoch ))

    # Extract artifact paths from the harness stdout
    json_path=$( grep -oE 'Changes \(JSON\):[[:space:]]*/tmp/[^ ]+\.json' "$arm_log" | awk '{print $NF}' | tail -n1 )
    md_path=$(   grep -oE 'Changes  \(MD\):[[:space:]]*/tmp/[^ ]+\.md'    "$arm_log" | awk '{print $NF}' | tail -n1 )

    json_path="${json_path:-(missing)}"
    md_path="${md_path:-(missing)}"

    mins=$(( duration / 60 ))
    secs=$(( duration % 60 ))
    echo "| $arm | \`$flags\` | $exit_code | ${mins}m${secs}s | \`$json_path\` | \`$md_path\` |" >> "$MATRIX_SUMMARY"

    echo
    echo "[MATRIX] Arm $arm finished: exit=$exit_code  duration=${mins}m${secs}s"
    echo "[MATRIX] JSON: $json_path"
    echo "[MATRIX]  MD:  $md_path"

    if (( exit_code != 0 )); then
        OVERALL_STATUS=$exit_code
        if (( STRICT == 1 )); then
            echo "[MATRIX] --strict set; aborting remaining arms."
            break
        fi
        echo "[MATRIX] Arm $arm failed but continuing (pass --strict to abort on first failure)."
    fi
done

# ─── Summary ────────────────────────────────────────────────────────────
banner "Matrix complete"
echo "Summary:"
cat "$MATRIX_SUMMARY"
echo
echo "Overall status: $OVERALL_STATUS"
echo
echo "Tip: diff the four changes artifacts side-by-side, e.g.:"
echo "     jq '.overall' /tmp/tfe-to-cc-changes-*.json"

exit "$OVERALL_STATUS"

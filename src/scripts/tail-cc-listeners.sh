#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# tail-cc-listeners.sh — Live aggregated output from all CC Notification Listeners
#
# Discovers active listeners via bridge files, then tails their log files
# with color-coded session hash prefixes into a single unified stream.
#
# Usage:
#   src/scripts/tail-cc-listeners.sh                          # active listeners only
#   src/scripts/tail-cc-listeners.sh --all                    # include stale logs too
#   src/scripts/tail-cc-listeners.sh --no-color               # disable ANSI colors
#   src/scripts/tail-cc-listeners.sh --filter 7211,a3f8       # show only these sessions
#   src/scripts/tail-cc-listeners.sh --filter 7211 --all      # filter + stale logs
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail

SESSION_DIR="$HOME/.claude/sessions"

# Extended 256-color palette — visually distinct, avoids near-duplicates
# Format: "38;5;N" for 256-color foreground
COLORS=(
    "38;5;196"   # bright red
    "38;5;46"    # bright green
    "38;5;226"   # bright yellow
    "38;5;33"    # bright blue
    "38;5;201"   # bright magenta
    "38;5;51"    # bright cyan
    "38;5;208"   # orange
    "38;5;129"   # purple
    "38;5;118"   # lime
    "38;5;197"   # hot pink
    "38;5;45"    # sky blue
    "38;5;220"   # gold
)

# ── Parse arguments ───────────────────────────────────────────────────
SHOW_ALL=false
USE_COLOR=true
FILTER_IDS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)      SHOW_ALL=true; shift ;;
        --no-color) USE_COLOR=false; shift ;;
        --filter)
            shift
            if [[ $# -eq 0 ]]; then
                echo "Error: --filter requires a comma-separated list of session IDs" >&2
                exit 1
            fi
            IFS=',' read -ra FILTER_IDS <<< "$1"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--all] [--no-color] [--filter ID[,ID,...]]"
            echo ""
            echo "  --all              Include stale log files (listener no longer running)"
            echo "  --no-color         Disable ANSI color codes (for piping to files)"
            echo "  --filter ID[,...]  Show only sessions matching these IDs (prefix match)"
            echo ""
            echo "Examples:"
            echo "  $0                           # all active listeners"
            echo "  $0 --filter 7211,a3f8        # only these two sessions"
            echo "  $0 --filter 7211 --all       # single session, include stale"
            echo ""
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--all] [--no-color] [--filter ID[,ID,...]]" >&2
            exit 1
            ;;
    esac
done

# ── Hash-based color assignment ───────────────────────────────────────
# Deterministic: same session hash always gets the same color across runs.
# Uses a simple checksum of the hash string to pick from the palette.
pick_color() {
    local hash="$1"
    local sum=0
    local i
    for (( i = 0; i < ${#hash}; i++ )); do
        sum=$(( sum + $( printf '%d' "'${hash:$i:1}" ) ))
    done
    echo "${COLORS[$sum % ${#COLORS[@]}]}"
}

# ── Filter check ──────────────────────────────────────────────────────
matches_filter() {
    local hash="$1"
    if [[ ${#FILTER_IDS[@]} -eq 0 ]]; then
        return 0  # no filter — match everything
    fi
    for fid in "${FILTER_IDS[@]}"; do
        if [[ "$hash" == "$fid"* ]]; then
            return 0  # prefix match
        fi
    done
    return 1
}

# ── Discover active listener log files ────────────────────────────────
discover_active_logs() {
    for bridge in "$SESSION_DIR"/cc-*.json; do
        [ -f "$bridge" ] || continue

        lpid=$( python3 -c "import json; print( json.load( open( '$bridge' ) ).get( 'listener_pid', '' ) )" 2>/dev/null )
        sid=$( python3 -c "import json; print( json.load( open( '$bridge' ) ).get( 'session_id', '' )[:8] )" 2>/dev/null )

        [ -z "$lpid" ] && continue
        kill -0 "$lpid" 2>/dev/null || continue

        logfile="$SESSION_DIR/cc-listener-${sid}.log"
        [ -f "$logfile" ] && echo "$logfile"
    done
}

# ── Discover all log files (including stale) ──────────────────────────
discover_all_logs() {
    for logfile in "$SESSION_DIR"/cc-listener-*.log; do
        [ -f "$logfile" ] && echo "$logfile"
    done
}

# ── Tail a single log with color-coded prefix ────────────────────────
tail_with_prefix() {
    local logfile="$1" color="$2"
    local hash
    hash=$( basename "$logfile" | sed 's/cc-listener-//;s/\.log//' )

    if [[ "$USE_COLOR" == true ]]; then
        tail -F "$logfile" 2>/dev/null | while IFS= read -r line; do
            # Strip existing [CC-Listener] prefix, replace with colored [hash]
            clean=$( echo "$line" | sed 's/\[CC-Listener\] //' )
            printf "\033[%sm[%s]\033[0m %s\n" "$color" "$hash" "$clean"
        done
    else
        tail -F "$logfile" 2>/dev/null | while IFS= read -r line; do
            clean=$( echo "$line" | sed 's/\[CC-Listener\] //' )
            printf "[%s] %s\n" "$hash" "$clean"
        done
    fi
}

# ── Main ──────────────────────────────────────────────────────────────
echo ""
echo "═══ CC Listener Aggregator ═══"
echo ""

# Collect log files
if [[ "$SHOW_ALL" == true ]]; then
    mapfile -t LOGFILES < <( discover_all_logs )
else
    mapfile -t LOGFILES < <( discover_active_logs )
fi

# Apply filter
FILTERED=()
for logfile in "${LOGFILES[@]}"; do
    hash=$( basename "$logfile" | sed 's/cc-listener-//;s/\.log//' )
    if matches_filter "$hash"; then
        FILTERED+=( "$logfile" )
    fi
done
LOGFILES=( "${FILTERED[@]+"${FILTERED[@]}"}" )

if [[ ${#LOGFILES[@]} -eq 0 ]]; then
    echo "  (no matching listeners found)"
    echo ""
    echo "  Listeners are spawned by CC SessionStart hooks."
    echo "  Log files are written to: $SESSION_DIR/cc-listener-*.log"
    if [[ "$SHOW_ALL" == false ]]; then
        echo "  Try --all to include stale log files."
    fi
    if [[ ${#FILTER_IDS[@]} -gt 0 ]]; then
        echo "  Filter: ${FILTER_IDS[*]} (no matches)"
    fi
    echo ""
    exit 0
fi

# Launch tails
PIDS=()

for logfile in "${LOGFILES[@]}"; do
    hash=$( basename "$logfile" | sed 's/cc-listener-//;s/\.log//' )
    color=$( pick_color "$hash" )
    tail_with_prefix "$logfile" "$color" &
    PIDS+=( $! )

    if [[ "$USE_COLOR" == true ]]; then
        printf "  Watching: \033[%sm[%s]\033[0m %s\n" "$color" "$hash" "$logfile"
    else
        printf "  Watching: [%s] %s\n" "$hash" "$logfile"
    fi
done

echo ""
echo "  ${#PIDS[@]} listener(s) — Ctrl+C to stop"
echo ""

# Wait for Ctrl+C, then clean up all background tails
cleanup() {
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    echo ""
    echo "Stopped."
    exit 0
}
trap cleanup INT TERM

wait

#!/usr/bin/env bash
#
# Wedge watchdog for the pinned v1 baseline arm on :7997 (row d8d019f6).
#
# WHY THIS EXISTS: on 2026-08-19 the arm pegged its CPU with 32 RUNNABLE threads and a
# 391-byte request sitting UNREAD in its socket, then died before anyone captured a stack.
# The evidence went with it, so a silent repeat would teach us nothing. This samples the
# same instruments continuously and writes them to a file that OUTLIVES the process.
#
# 🔴 WHAT IT CANNOT DO, stated rather than discovered later: it cannot take a Python stack.
# py-spy is installed but /proc/sys/kernel/yama/ptrace_scope = 1 permits tracing only a
# DESCENDANT, and the arm is detached (nohup, reparented to init). A sibling watchdog is
# not an ancestor, so the attach is refused. When this trips, a human with sudo runs:
#     sudo env "PATH=$PATH" py-spy dump --pid <PID>
# Everything below is readable WITHOUT root, which is why it is what gets collected.
#
#   bash src/scripts/watch-v1-arm-wedge.sh <PID> [stall_minutes]
#
set -uo pipefail
PID="${1:?usage: watch-v1-arm-wedge.sh <PID> [stall_minutes]}"
STALL_MIN="${2:-4}"
LOG="/tmp/v1-baseline-7997.log"
OUT="/tmp/v1-arm-wedge-watch-${PID}.log"
INTERVAL=30
stalled=0
need=$(( STALL_MIN * 60 / INTERVAL ))

say() { echo "[$(date '+%H:%M:%S')] $*" >> "$OUT"; }

say "watchdog armed on pid $PID — stall threshold ${STALL_MIN}m, sampling ${INTERVAL}s"
last_size=$(stat -c%s "$LOG" 2>/dev/null || echo 0)
last_utime=$(awk '{print $14+$15}' /proc/$PID/stat 2>/dev/null || echo 0)

while kill -0 "$PID" 2>/dev/null; do
    sleep "$INTERVAL"
    size=$(stat -c%s "$LOG" 2>/dev/null || echo 0)
    utime=$(awk '{print $14+$15}' /proc/$PID/stat 2>/dev/null || echo 0)
    cpu_ticks=$(( utime - last_utime ))
    if [[ "$size" == "$last_size" ]]; then stalled=$(( stalled + 1 )); else stalled=0; fi
    last_size=$size; last_utime=$utime

    if (( stalled >= need )); then
        say "🔴 WEDGE SUSPECTED — log unchanged for ${STALL_MIN}m while burning ${cpu_ticks} CPU ticks in the last ${INTERVAL}s"
        say "--- threads: $(awk '/^Threads:/{print $2}' /proc/$PID/status 2>/dev/null) ---"
        say "--- per-thread state (R=runnable is the signature) ---"
        for t in /proc/$PID/task/*; do
            [[ -r "$t/stat" ]] || continue
            awk -v tid="$(basename "$t")" '{print "  tid " tid " state " $3 " utime " $14 " stime " $15}' "$t/stat" >> "$OUT" 2>/dev/null
        done
        say "--- socket queues (an UNREAD Recv-Q is a server not servicing its listener) ---"
        ss -tnp 2>/dev/null | grep -E ":7997|State" >> "$OUT"
        say "--- open fd count: $(ls /proc/$PID/fd 2>/dev/null | wc -l) ---"
        say "--- wchan: $(cat /proc/$PID/wchan 2>/dev/null) ---"
        say "⚠️ NO PYTHON STACK — ptrace_scope=1 and this watchdog is not the arm's ancestor."
        say "   A human with sudo gets one now with: sudo env \"PATH=\$PATH\" py-spy dump --pid $PID"
        stalled=0   # re-arm so a long wedge produces a SERIES of samples, not one
    fi
done
say "arm pid $PID exited — watchdog done"

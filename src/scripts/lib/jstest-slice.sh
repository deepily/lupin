#!/bin/bash
# The capped JS-test lane — run node's test runner inside its OWN cgroup so a
# runaway dies against its own ceiling instead of becoming fleet pressure.
#
# WHY THIS EXISTS, stated as the mechanism rather than as a list of doors.
# On 2026-08-24 the allocator was named (row 32c58572): node:assert builds its
# failure-diff by deep-inspecting the actual value, and when that value is a
# happy-dom element the walk reaches ownerDocument -> defaultView -> the whole
# Window graph and does not terminate. It needs THREE things at once:
#     happy-dom registered  ×  a DOM node as an assertion operand  ×  the
#     assertion FAILS
# Remove any one and it is harmless — measured, 3 runs per cell: DOM node +
# failing assert died 3/3; the same node with a PASSING assert, a plain object
# with a failing assert, and a failing assert with happy-dom not registered all
# survived at ~86 MB.
#
# ⇒ THE HAZARD IS A FAILING ASSERTION HOLDING A DOM NODE, NOT "the TypeScript
# tier". That distinction is the whole point: the tier is dangerous exactly when
# tests FAIL, which is the state a fix cycle is in, and safe when they pass —
# which is why green runs never showed it. Naming the doors instead of the
# mechanism is how the rule got attached to the wrong noun for three days.
# Evidence: src/rnd/v0.2.0/2026.08.24-oom-allocator-named-happy-dom-assertion-diff.md
#
# WHY MemoryMax AND NOT MemoryHigh — this is load-bearing, not a preference.
# MemoryHigh THROTTLES: the cgroup is pushed into reclaim and stalls rather than
# dying. A runaway under MemoryHigh therefore drives slice PSI up and keeps
# living, which is precisely the 2026-08-23 mechanism — systemd-oomd killed on
# slice PSI 74.8% across 30-52 processes and took seats that were not the
# offender. MemoryMax kills the offender, locally, at once. Do NOT add
# MemoryHigh to this lane.
#
# WHY MemorySwapMax=0 — with swap available the runaway swaps instead of dying,
# which converts a fast local kill into a slow global stall.
#
# ⚠️ WHY THE WALL CLOCK IS NOT 300s. A single-file probe dies in ~5 seconds, so
# 300 looks generous; the FULL suite is 119 files, observed at 8m19s (499s)
# WITHOUT c8, and TestSuiteJob budgets it 1500s WITH c8 instrumentation. A 300s
# ceiling would kill the full suite mid-run every time and report it as a cap
# hit. The default below tracks the suite's own budget; override per-call for a
# single-file probe.
#
# ⚠️ AND WHY THE SCOPE REPLACES `timeout` RATHER THAN JOINING IT. timeout(1)
# signals its DIRECT CHILD only, never the process group, and node blocked in a
# synchronous C++/GC frame never services SIGTERM. Receipt (row 32c58572): a run
# under `timeout 300` burned 6m28s of CPU — 388 seconds against a 300-second
# ceiling. The cap never fired. systemd-run caps wall time AND memory in one
# primitive that does not depend on the target cooperating.

# Our own path, so the in-scope re-entry can source this same file rather than
# carrying a second copy of the watchdog that can drift.
JSTEST_LIB_PATH="${BASH_SOURCE[0]}"
JSTEST_SLICE="${JSTEST_SLICE:-jstest.slice}"
JSTEST_MEM_MAX="${JSTEST_MEM_MAX:-8G}"
JSTEST_RUNTIME_MAX="${JSTEST_RUNTIME_MAX:-1500}"

# Run "$@" inside the capped scope. FAILS LOUD when it cannot cap — an uncapped
# fallback would be a run that LOOKS lane-protected and is not, which is the
# false-green shape this lane exists to prevent. Set JSTEST_ALLOW_UNCAPPED=1 to
# opt out deliberately; it prints what it is giving up.
# INSIDE A CONTAINER THERE IS NO systemd-run, AND THERE CANNOT BE A SUB-SCOPE.
# Measured on lupin-rest-test 2026-08-24: `command -v systemd-run` is ABSENT, the
# container runs as 1001:1001, and /sys/fs/cgroup/memory.max is root-owned 0644 —
# so the process can READ its ceiling and cannot create or write one. The lever
# therefore lives in docker-compose.yml (deploy.resources.limits.memory), not here.
#
# ⇒ In a container the lane DEFERS to that ceiling when one exists, and REFUSES
# when it does not. Refusing is the whole point: `memory.max` reading `max` means
# UNCAPPED, and a door that runs the suite uncapped while reporting itself as the
# capped lane is worse than a door that will not open. This is what makes the
# compose limit load-bearing rather than decorative.
_jstest_in_container() { [ -f /.dockerenv ]; }

_jstest_container_ceiling() {
    # Echoes the byte ceiling, or "max"/"" when there is none to find.
    cat /sys/fs/cgroup/memory.max 2>/dev/null || echo ""
}


# ── THE PER-PROCESS WATCHDOG ─────────────────────────────────────────────────
# 🔴 WHY NOT NODE_OPTIONS --max-old-space-size, which is the obvious answer and
# is WRONG here. This allocator is OFF-HEAP, so the V8 heap ceiling is not in its
# path. Measured twice: the original kill ran with --max-old-space-size=2048 and
# reached 6 GB with no "JavaScript heap out of memory" abort and no heapsnapshot
# despite --heapsnapshot-near-heap-limit=1; re-run at 512 it still reached the
# 4 GB cgroup limit and was SIGKILLed in 3.4 seconds. A heap cap cannot bound
# memory that is not on the heap.
#
# So the ceiling has to be enforced from OUTSIDE the process, and the enforcer
# must work where systemd-run does not exist and the process cannot write its
# own cgroup — i.e. inside the container. Polling RSS and sending SIGKILL needs
# no privileges at all and works identically in both places.
#
# ⇒ IT KILLS THE NODE PROCESS, NOT THE CONTAINER. That is the whole design goal:
# a runaway takes the tier red and leaves uvicorn serving. A container-wide
# mem_limit would have taken :8000 down with it, which is worse than the failure
# being fixed.
#
# THE CEILING, and its provenance — do not quote the number without this.
#   · a PASSING single-file run peaks at 199 MB RSS (measured 2026-08-24)
#   · the runaway climbs ~640 MB per 250 ms, about 2.5 GB/s (measured)
#   · overshoot = growth-rate x poll-interval, so a 100 ms poll costs ~250 MB
# 2 GB is ~10x the measured working set, which is generous for the 119-file
# suite at concurrency 4. ⚠️ It is ONE FILE'S peak, not the suite's — nobody has
# measured the full suite because the tier is banned. Re-derive when it runs.
JSTEST_RSS_MAX_MB="${JSTEST_RSS_MAX_MB:-2048}"
JSTEST_POLL_SECS="${JSTEST_POLL_SECS:-0.1}"

# Total RSS in MB of a pid and EVERY DESCENDANT, at any depth.
#
# 🔴 TWO LEVELS OF THIS WERE WRONG IN A ROW, so the comment records both.
#   1. Reading only the PARENT: node --test spawns a worker per file, so the
#      memory is the worker's while the parent sits near 10 MB. A parent-only
#      watchdog polls ~10 MB forever and never fires.
#   2. Reading parent + DIRECT children (`ps --ppid`): still one level. Measured
#      2026-08-24 with a parent → child → hog tree, the watchdog reported a
#      28 MB peak while the grandchild allocated past 2 GB, and never fired.
#      `node --import tsx --test` is exactly this shape when a loader or shell
#      sits between the runner and the worker.
# ⇒ Walk the whole descendant set. Both failure modes are SILENT — the watchdog
#   reports a comfortable peak and the runaway proceeds — which is why each was
#   found by a mutation and a probe rather than by anything going red.
_jstest_descendants() {
    local root="$1" frontier="$1" next=""
    echo "$root"
    while [ -n "$frontier" ]; do
        next="$( pgrep -P "$( echo $frontier | tr ' ' ',' )" 2>/dev/null | tr '\n' ' ' )"
        [ -z "$next" ] && break
        echo "$next" | tr ' ' '\n' | grep -v '^$'
        frontier="$next"
    done
}

_jstest_tree_rss_mb() {
    local root="$1" pids
    pids="$( _jstest_descendants "$root" | tr '\n' ',' | sed 's/,$//' )"
    [ -z "$pids" ] && { echo 0; return; }
    ps -o rss= -p "$pids" 2>/dev/null | awk '{ s += $1 } END { print int( s / 1024 ) }'
}

jstest_watchdog_exec() {
    "$@" &
    local target=$!
    local peak=0 rss=0

    while kill -0 "$target" 2>/dev/null; do
        rss="$( _jstest_tree_rss_mb "$target" )"
        [ -z "$rss" ] && rss=0
        [ "$rss" -gt "$peak" ] && peak="$rss"
        if [ "$rss" -gt "$JSTEST_RSS_MAX_MB" ]; then
            echo "🔴 [jstest-lane] RSS ${rss}MB exceeded the ${JSTEST_RSS_MAX_MB}MB ceiling — killing node." >&2
            echo "    The tier goes RED and the server keeps serving; that is the intended outcome." >&2
            echo "    Most likely a FAILING assertion holding a DOM node (rows f5768ee4 / 32c58572)." >&2
            # KILL THE WHOLE DESCENDANT SET, DEEPEST FIRST — a THIRD level of the
            # same one-level bug. Detection was fixed to walk every depth while the
            # KILL was still `kill $target` plus `pkill -P $target`: the root and its
            # direct children. Measured 2026-08-24 on a depth-4 chain, the watchdog
            # fired, ANNOUNCED the kill, and three processes were still alive
            # afterwards — including the one actually allocating. A watchdog that
            # detects and half-kills is worse than one that never fires, because it
            # reports the runaway as handled.
            #
            # Deepest-first, so a dying parent cannot re-parent a live child away
            # before we reach it. Explicit pids only — never a pattern match; a
            # hand-rolled pattern kill is what took three seats on 2026-08-21
            # (row cd332d2b).
            local victims v
            victims="$( _jstest_descendants "$target" | tac )"
            for v in $victims; do kill -9 "$v" 2>/dev/null; done
            wait "$target" 2>/dev/null
            return 137
        fi
        sleep "$JSTEST_POLL_SECS"
    done

    wait "$target"
    local rc=$?
    # A process that finishes inside one poll interval is never sampled. Reporting
    # "peak 0MB" there would be a fabricated measurement, and a number printed by a
    # tool is a number someone will later quote — so say there was no sample.
    if [ "$peak" -eq 0 ]; then
        echo "[jstest-lane] finished within one poll (${JSTEST_POLL_SECS}s) — no RSS sample taken" >&2
    else
        echo "[jstest-lane] peak RSS ${peak}MB of ${JSTEST_RSS_MAX_MB}MB ceiling" >&2
    fi
    return $rc
}

jstest_slice_exec() {
    if _jstest_in_container; then
        local ceiling
        ceiling="$( _jstest_container_ceiling )"
        if [ -z "$ceiling" ] || [ "$ceiling" = "max" ]; then
            if [ "${JSTEST_ALLOW_UNCAPPED:-}" = "1" ]; then
                echo "⚠️  [jstest-lane] container has NO memory ceiling and JSTEST_ALLOW_UNCAPPED=1 — running UNCAPPED." >&2
                exec "$@"
            fi
            echo "🔴 [jstest-lane] IN A CONTAINER WITH NO MEMORY CEILING — refusing." >&2
            echo "    /sys/fs/cgroup/memory.max reads '${ceiling:-<unreadable>}', which means UNCAPPED." >&2
            echo "    systemd-run does not exist in a container and this process cannot write its own" >&2
            echo "    cgroup, so the ceiling must come from docker-compose.yml:" >&2
            echo "        deploy: { resources: { limits: { memory: 12G } } }   on this service" >&2
            echo "    Add it and recreate the container (a plain restart does NOT apply it)." >&2
            return 70
        fi
        echo "[jstest-lane] in-container; container ceiling memory.max=$ceiling bytes" >&2
        jstest_watchdog_exec "$@"
        return $?
    fi

    if ! command -v systemd-run >/dev/null 2>&1; then
        if [ "${JSTEST_ALLOW_UNCAPPED:-}" = "1" ]; then
            echo "⚠️  [jstest-lane] systemd-run NOT FOUND and JSTEST_ALLOW_UNCAPPED=1 — running UNCAPPED." >&2
            echo "    A runaway here is a whole-host event, not a local one. You own the blast radius." >&2
            exec "$@"
        fi
        echo "🔴 [jstest-lane] systemd-run NOT FOUND — refusing to run the JS test suite uncapped." >&2
        echo "    The suite's failure mode is unbounded off-heap growth (row 32c58572); without a" >&2
        echo "    cgroup ceiling one runaway becomes fleet pressure and systemd-oomd picks a victim" >&2
        echo "    that need not be the offender. Set JSTEST_ALLOW_UNCAPPED=1 to override knowingly." >&2
        return 70
    fi

    echo "[jstest-lane] slice=$JSTEST_SLICE MemoryMax=$JSTEST_MEM_MAX MemorySwapMax=0 RuntimeMaxSec=$JSTEST_RUNTIME_MAX rss_ceiling=${JSTEST_RSS_MAX_MB}MB" >&2
    # 🔴 THE WATCHDOG RUNS INSIDE THE SCOPE, NOT INSTEAD OF IT — and this line
    # used to be a lie. The host path exec'd systemd-run directly while the
    # message above already announced `rss_ceiling=...MB`, so the host ANNOUNCED
    # a per-process ceiling it never enforced; only the container path ran the
    # watchdog. The scope alone kills the whole scope (every worker) on the
    # container's terms; the watchdog kills the one process that grew and says
    # why. Both are wanted: the watchdog is the surgical cut, the scope is the
    # backstop if the watchdog is outrun between polls.
    #
    # Re-entering through `bash -c 'source "$0"; ...'` keeps ONE implementation
    # of the watchdog rather than a second copy that can drift from the first.
    exec systemd-run --user --scope --quiet \
        --slice="$JSTEST_SLICE" \
        -p MemoryMax="$JSTEST_MEM_MAX" \
        -p MemorySwapMax=0 \
        -p RuntimeMaxSec="$JSTEST_RUNTIME_MAX" \
        -- bash -c 'source "$0"; jstest_watchdog_exec "$@"' "$JSTEST_LIB_PATH" "$@"
}

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

JSTEST_SLICE="${JSTEST_SLICE:-jstest.slice}"
JSTEST_MEM_MAX="${JSTEST_MEM_MAX:-8G}"
JSTEST_RUNTIME_MAX="${JSTEST_RUNTIME_MAX:-1500}"

# Run "$@" inside the capped scope. FAILS LOUD when it cannot cap — an uncapped
# fallback would be a run that LOOKS lane-protected and is not, which is the
# false-green shape this lane exists to prevent. Set JSTEST_ALLOW_UNCAPPED=1 to
# opt out deliberately; it prints what it is giving up.
jstest_slice_exec() {
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

    echo "[jstest-lane] slice=$JSTEST_SLICE MemoryMax=$JSTEST_MEM_MAX MemorySwapMax=0 RuntimeMaxSec=$JSTEST_RUNTIME_MAX" >&2
    exec systemd-run --user --scope --quiet \
        --slice="$JSTEST_SLICE" \
        -p MemoryMax="$JSTEST_MEM_MAX" \
        -p MemorySwapMax=0 \
        -p RuntimeMaxSec="$JSTEST_RUNTIME_MAX" \
        -- "$@"
}

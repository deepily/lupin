#!/bin/bash
# vertex-launcher-review-rig.sh — manual review harness for start-cc-with-tmux.sh's
# vertex/MAX pane-scrub seam (Arnold P0 F1, review_request 57124681).
#
# Authored by Rio ⚡ (session 8d8c5e07, 2026-07-15) as the execution rig behind the
# APPROVE verdict that cleared Arnold's NOT-APPROVE on commit 7eef87ce. Banked here
# on Mr. Radio's ruling (utilities/ = manual harness, OUTSIDE pytest collection —
# the killtrace_probe.py precedent). It is NOT a suite member: run it by hand when
# reviewing a launcher diff that touches the scrub/forward seam.
#
# WHAT IT PROVES (18 checks, PASS/FAIL to stdout):
#   RUN B   --vertex: the PANE PROCESS sees all 3 toggle vars (env-dump oracle, not
#           the session table); agreeing GOOGLE_CLOUD_PROJECT still scrubbed; model
#           pins survive; banner printed.
#   RUN B2  --vertex from a toggle-TAINTED shell: server born clean (SERVER_SCRUB
#           rides new-session even under --vertex) while the pane keeps the toggle.
#   RUN C   MAX path from a shell tainted with ALL MAX_PANE_UNSET_KEYS: pane carries
#           none of them; server born clean.
#   RUN D   MUTANT reconstructing the P0 (pane scrub forced to the MAX set on
#           --vertex): the pane-process oracle goes RED while the session-table
#           oracle (`show-environment -t`) stays GREEN — the R1 blindness finding.
#           An observation is evidence only if it could have come out otherwise.
#   RUN E   F4 disposition: a failing pane-scrub derivation is fail-CLOSED (set -e
#           on the assignment aborts BEFORE new-session) but SILENT (2>/dev/null).
#           No pytest covers this path.
#
# ⚠️ LESSON, LEARNED THE HARD WAY (Rio, v1 of this rig, 2026-07-15): unix socket
# paths cap at ~107 bytes. v1 put TMUX_TMPDIR under a deep scratchpad path; every
# tmux server silently failed to start ("File name too long") and SEVERAL CHECKS
# PASSED AS ARTIFACTS — greps against missing files, show-environment against dead
# servers. A null is not evidence until the instrument is proven. Hence: sockets
# live under a SHORT mktemp -d /tmp dir (socket files only — no process is cwd'd
# there), and every run passes a HARD instrument gate (launcher rc=0 + live session
# + dump captured) before any oracle is read.
#
# ISOLATION (fleet-killer plan §2.5): $TMUX BEATS TMUX_TMPDIR, so every tmux and
# launcher invocation strips TMUX/TMUX_PANE and pins a private TMUX_TMPDIR. The
# fleet socket is never addressed. Zero GCP/network: dummy project id, fake
# `claude` that only dumps its env — nothing ever phones out.
#
# Usage:
#   LUPIN_ROOT=/path/to/lupin bash src/tests/smoke/utilities/vertex-launcher-review-rig.sh
set -uo pipefail

REPO="${LUPIN_ROOT:?LUPIN_ROOT must be set — the rig drives \$LUPIN_ROOT/src/scripts/start-cc-with-tmux.sh}"
LAUNCHER_NEW="$REPO/src/scripts/start-cc-with-tmux.sh"
WORK="$( mktemp -d /tmp/rio-rig-XXXX )"   # SHORT path — unix socket 107-byte limit (see header)
DUMPS="$WORK/dumps"; mkdir -p "$DUMPS" "$WORK/bin"
SOCKROOT="$WORK/sock"; mkdir -p "$SOCKROOT"
trap 'for s in "$SOCKROOT"/*; do env -u TMUX -u TMUX_PANE TMUX_TMPDIR="$s" tmux kill-server 2>/dev/null; done; rm -rf "$WORK"' EXIT
PASS=0; FAIL=0

cat > "$WORK/bin/claude" <<'EOF'
#!/usr/bin/env bash
env | sort > "${RIO_ENV_DUMP:-/dev/null}"
sleep 15
EOF
chmod +x "$WORK/bin/claude"

check() { local label=$1; shift; if "$@" >/dev/null 2>&1; then echo "PASS  $label"; PASS=$((PASS+1)); else echo "FAIL  $label"; FAIL=$((FAIL+1)); fi }
check_not() { local label=$1; shift; if "$@" >/dev/null 2>&1; then echo "FAIL  $label"; FAIL=$((FAIL+1)); else echo "PASS  $label"; PASS=$((PASS+1)); fi }
tmx() { local sock=$1; shift; env -u TMUX -u TMUX_PANE TMUX_TMPDIR="$sock" tmux "$@"; }
gate() {  # gate <tag> <rc> <sock> <sess> <dump|-> — instrument proof before any oracle is read
    local tag=$1 rc=$2 sock=$3 sess=$4 dump=$5
    [[ $rc -eq 0 ]] || { echo "GATE-FAIL $tag: launcher rc=$rc"; FAIL=$((FAIL+1)); return 1; }
    tmx "$sock" has-session -t "$sess" 2>/dev/null || { echo "GATE-FAIL $tag: session not live"; FAIL=$((FAIL+1)); return 1; }
    if [[ "$dump" != "-" ]]; then
        for _ in $( seq 1 24 ); do [[ -s "$dump" ]] && break; sleep 0.5; done
        [[ -s "$dump" ]] || { echo "GATE-FAIL $tag: pane env dump never appeared"; FAIL=$((FAIL+1)); return 1; }
    fi
    echo "GATE-OK   $tag: launcher rc=0, session live, dump captured"
    return 0
}
launch() {  # launch <sock> <dump> <extra KEY=VAL...> -- <launcher> <args...>
    local sock=$1 dump=$2; shift 2
    local extra=()
    while [[ "$1" != "--" ]]; do extra+=( "$1" ); shift; done
    shift
    env -u TMUX -u TMUX_PANE \
        TMUX_TMPDIR="$sock" RIO_ENV_DUMP="$dump" PATH="$WORK/bin:$PATH" \
        LUPIN_ROOT="$REPO" "${extra[@]}" bash "$@"
}
# Guard-compliant (test_no_hardcoded_gcp_identifiers): reference LUPIN_GCP_PROJECT_ID through the
# fail-loud `:?` form the doctrine mandates. Seed a DUMMY default first via the `+x` SET-test — NOT
# the guard-forbidden silent-default expansions — so the rig stays zero-config and never phones out
# (see header). The launcher's compose_vertex_env() _require()s this key; a dummy id satisfies it.
[[ -n "${LUPIN_GCP_PROJECT_ID+x}" ]] || LUPIN_GCP_PROJECT_ID="rio-review-dummy-project"
VERTEX_ENV=( "LUPIN_GCP_PROJECT_ID=${LUPIN_GCP_PROJECT_ID:?rig seeds a dummy default just above}" LUPIN_VERTEX_REGION=global )

echo "═══ RUN B — launcher, --vertex: pane must SEE the 3 toggle vars ═══"
mkdir -p "$SOCKROOT/B"
launch "$SOCKROOT/B" "$DUMPS/B.txt" "${VERTEX_ENV[@]}" GOOGLE_CLOUD_PROJECT=rio-review-dummy-project \
    -- "$LAUNCHER_NEW" --headless --vertex rio-b-vertex 2> "$DUMPS/B.stderr"
if gate B $? "$SOCKROOT/B" rio-b-vertex "$DUMPS/B.txt"; then
  check     "B1 pane sees CLAUDE_CODE_USE_VERTEX=1"                    grep -qx 'CLAUDE_CODE_USE_VERTEX=1' "$DUMPS/B.txt"
  check     "B2 pane sees CLOUD_ML_REGION=global"                      grep -qx 'CLOUD_ML_REGION=global' "$DUMPS/B.txt"
  check     "B3 pane sees ANTHROPIC_VERTEX_PROJECT_ID=dummy"           grep -qx 'ANTHROPIC_VERTEX_PROJECT_ID=rio-review-dummy-project' "$DUMPS/B.txt"
  check_not "B4 vertex scrub removed agreeing GOOGLE_CLOUD_PROJECT from pane" grep -q '^GOOGLE_CLOUD_PROJECT=' "$DUMPS/B.txt"
  check     "B5 pane sees model pin ANTHROPIC_DEFAULT_OPUS_MODEL (forwarded, not scrubbed)" grep -qx 'ANTHROPIC_DEFAULT_OPUS_MODEL=claude-opus-4-8' "$DUMPS/B.txt"
  check     "B6 SESSION table carries toggle (the weaker oracle, for contrast with D2)" bash -c "env -u TMUX -u TMUX_PANE TMUX_TMPDIR='$SOCKROOT/B' tmux show-environment -t rio-b-vertex | grep -qx 'CLAUDE_CODE_USE_VERTEX=1'"
  check     "B7 metered banner printed on stderr"                      grep -q 'GCP VERTEX' "$DUMPS/B.stderr"
fi

echo "═══ RUN B2 — --vertex FROM A TOGGLE-TAINTED SHELL: server born clean, pane still on Vertex ═══"
mkdir -p "$SOCKROOT/B2"
launch "$SOCKROOT/B2" "$DUMPS/B2.txt" "${VERTEX_ENV[@]}" \
    CLAUDE_CODE_USE_VERTEX=1 CLOUD_ML_REGION=global ANTHROPIC_VERTEX_PROJECT_ID=rio-review-dummy-project \
    -- "$LAUNCHER_NEW" --headless --vertex rio-b2-vertex 2> "$DUMPS/B2.stderr"
if gate B2 $? "$SOCKROOT/B2" rio-b2-vertex "$DUMPS/B2.txt"; then
  check     "B2a pane STILL sees CLAUDE_CODE_USE_VERTEX=1 (feature alive)" grep -qx 'CLAUDE_CODE_USE_VERTEX=1' "$DUMPS/B2.txt"
  check_not "B2b SERVER global table NOT frozen with the toggle (SERVER_SCRUB rides new-session even under --vertex)" \
      bash -c "env -u TMUX -u TMUX_PANE TMUX_TMPDIR='$SOCKROOT/B2' tmux show-environment -g CLAUDE_CODE_USE_VERTEX | grep -qx 'CLAUDE_CODE_USE_VERTEX=1'"
fi

echo "═══ RUN C — MAX path, shell tainted with ALL MAX_PANE_UNSET_KEYS ═══"
MAX_KEYS="$( PYTHONPATH="$REPO/src" python3 -c 'from cosa.utils.vertex_env import MAX_PANE_UNSET_KEYS; print( " ".join( MAX_PANE_UNSET_KEYS ) )' )"
TAINT_ARGS=(); for k in $MAX_KEYS; do TAINT_ARGS+=( "$k=RIO_TAINT" ); done
mkdir -p "$SOCKROOT/C"
launch "$SOCKROOT/C" "$DUMPS/C.txt" "${TAINT_ARGS[@]}" -- "$LAUNCHER_NEW" --headless rio-c-max 2> "$DUMPS/C.stderr"
if gate C $? "$SOCKROOT/C" rio-c-max "$DUMPS/C.txt"; then
  C_LEAKS=0
  for k in $MAX_KEYS; do grep -q "^$k=" "$DUMPS/C.txt" && { echo "  LEAK: $( grep "^$k=" "$DUMPS/C.txt" )"; C_LEAKS=$((C_LEAKS+1)); }; done
  if [[ $C_LEAKS -eq 0 ]]; then echo "PASS  C1 MAX pane carries NONE of the $( echo "$MAX_KEYS" | wc -w ) MAX_PANE_UNSET_KEYS"; PASS=$((PASS+1)); else echo "FAIL  C1 $C_LEAKS key(s) leaked"; FAIL=$((FAIL+1)); fi
  C_FROZEN=0
  for k in CLAUDE_CODE_USE_VERTEX CLOUD_ML_REGION ANTHROPIC_VERTEX_PROJECT_ID; do
      tmx "$SOCKROOT/C" show-environment -g "$k" 2>/dev/null | grep -qx "$k=RIO_TAINT" && { echo "  FROZEN: $k"; C_FROZEN=$((C_FROZEN+1)); }
  done
  if [[ $C_FROZEN -eq 0 ]]; then echo "PASS  C2 server NOT born tainted (SERVER_SCRUB, MAX path)"; PASS=$((PASS+1)); else echo "FAIL  C2 $C_FROZEN toggle(s) frozen"; FAIL=$((FAIL+1)); fi
fi

echo "═══ RUN D — MUTANT reconstructing the P0 (pane scrub forced to MAX set on --vertex) ═══"
# ORACLE UPDATED 2026-07-15 (Rio, authorized by Mr. Radio 38a0bb8c): OLD RUN D expected the
# mutant's fake claude to RUN and dump an env LACKING the toggle, and read the session table
# as the blind-oracle contrast (finding R1). Cheech's pane_guard (wired in INNER, post-unset
# pre-claude) changed the mutant's fate: the pane now DIES AT pane_guard before claude ever
# runs — no dump, and the SESSION dies with the pane, so the old dump-gate and the D2
# session-table contrast reading are both unobtainable BY DESIGN. The runtime guard catches
# pre-token what this rig could only observe post-hoc; the R1 contrast lesson lives on in the
# header prose and in the taint suite's negative control.
# NEW oracle (granted verbatim): no-dump (pane_guard refused) OR dump-lacking-toggle = the
# defect was CAUGHT → PASS; dump WITH the toggle = the mutant failed to reproduce → FAIL.
# Gate reduces to launcher rc=0 (headless returns before the pane's fate resolves).
sed 's/VERTEX_PATH="\$VERTEX"/VERTEX_PATH="0"/' "$LAUNCHER_NEW" > "$WORK/mutant-p0-launcher.sh"
grep -q 'VERTEX_PATH="0"' "$WORK/mutant-p0-launcher.sh" || echo "MUTANT ANCHOR MISSING — launcher no longer injects VERTEX_PATH=\"\$VERTEX\"; adapt the sed before trusting RUN D"
mkdir -p "$SOCKROOT/D"
launch "$SOCKROOT/D" "$DUMPS/D.txt" "${VERTEX_ENV[@]}" -- "$WORK/mutant-p0-launcher.sh" --headless --vertex rio-d-mutant 2> "$DUMPS/D.stderr"
D_RC=$?
if [[ $D_RC -ne 0 ]]; then
    echo "GATE-FAIL D: mutant launcher rc=$D_RC"; FAIL=$((FAIL+1))
else
    echo "GATE-OK   D: mutant launcher rc=0 (pane fate is the oracle, not the gate)"
    for _ in $( seq 1 12 ); do [[ -s "$DUMPS/D.txt" ]] && break; sleep 0.5; done
    if [[ ! -s "$DUMPS/D.txt" ]]; then
        echo "PASS  D1 DEFECT CAUGHT PRE-TOKEN: no dump — pane_guard killed the mutant pane before claude ran"; PASS=$((PASS+1))
    elif ! grep -qx 'CLAUDE_CODE_USE_VERTEX=1' "$DUMPS/D.txt"; then
        echo "PASS  D1 DEFECT CAUGHT POST-HOC: claude ran but the pane-process dump lacks the toggle (banner lies, oracle sees it)"; PASS=$((PASS+1))
    else
        echo "FAIL  D1 mutant pane SAW the toggle — the P0 mutant failed to reproduce the defect (anchor drift?)"; FAIL=$((FAIL+1))
    fi
    check "D3 mutant banner still printed METERED (the lie the P0 shipped)" grep -q 'GCP VERTEX' "$DUMPS/D.stderr"
fi

echo "═══ RUN E — F4: pane-scrub derivation failure — fail-closed AND LOUD (R3) ═══"
# ORACLE UPDATED 2026-07-15 (Rio, pre-authorized by Mr. Radio c60f4312): E3 originally
# asserted the OLD behavior — fail-closed but SILENT (the derivation ran under
# 2>/dev/null; the operator saw a wordless death). Cheech's R3 fix REMOVED the
# silencer, so a broken derivation now SAYS what broke (Python traceback on stderr)
# while still failing closed before any tmux call. E3 now asserts the NEW loud
# behavior; E1/E2/E4 (fail-closed, pre-new-session, no session) are unchanged.
# Attribution receipt: against the R3'd launcher the captured output began
# "Traceback (most recent call last):" — the exact words 2>/dev/null used to eat.
mkdir -p "$SOCKROOT/E"
OUT="$( env -u TMUX -u TMUX_PANE -u PYTHONPATH TMUX_TMPDIR="$SOCKROOT/E" PATH="$WORK/bin:$PATH" \
        LUPIN_ROOT=/nonexistent-rio-probe bash "$LAUNCHER_NEW" --headless rio-e-f4 2>&1 )"; RC=$?
check     "E1 launcher ABORTS (rc=$RC) when the derivation cannot import (fail closed via set -e on the assignment)" test $RC -ne 0
check_not "E2 abort happened BEFORE new-session (no 'Creating tmux session' printed)" grep -q 'Creating tmux session' <<< "$OUT"
check     "E3 the cause is SAID, not swallowed (R3: silencer removed — traceback reaches the operator)" grep -qE 'Traceback|ModuleNotFoundError' <<< "$OUT"
check_not "E4 no session created" bash -c "env -u TMUX -u TMUX_PANE TMUX_TMPDIR='$SOCKROOT/E' tmux has-session -t rio-e-f4"
echo "E combined output was: [${OUT}]"

echo ""
echo "══════════ RIG SUMMARY: PASS=$PASS FAIL=$FAIL ══════════"
[[ $FAIL -eq 0 ]]

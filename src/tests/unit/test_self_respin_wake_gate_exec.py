"""
EXECUTION test for the self-re-spin wake readiness gate (row 275cb0b9, GAP 1).

The other suites only STRING-MATCH build_guarded_clear_argv's bash script for its
flags — they never RUN it, so a broken gate (wrong mtime compare, wrong exit, a
send before the gate) would pass them all. Mr Radio's blocker: spawn the REAL argv
and prove the two behaviors that matter —

  (a) the wake FIRES once the bridge file's mtime CHANGES (SessionStart's rehydrate
      write), and
  (b) the wake TIMES OUT loudly (exit 3, wake NOT typed) when the mtime never moves.

Mechanism (deterministic, no timing race): a FAKE `tmux` on PATH logs every
invocation and, on the FIRST `Enter` (the /clear submit), touches the bridge file —
exactly what the real SessionStart hook does after /clear. `m0` is captured BEFORE
that Enter, so the touch always lands strictly after m0 and the gate breaks on the
next poll. For the timeout case the shim is told NOT to touch, so the mtime never
moves and the bounded loop exits 3.

Venue: self-contained subprocess + temp files only (no server, no persistent state,
sub-second) → :7999-eligible. `date -r` / `bash` are GNU-coreutils/Linux givens here.
"""

import os
import subprocess

import pytest

import lupin_mcp.self_respin_core as sr


def _fake_tmux_dir( tmp_path, *, bridge_to_rewrite, mtime_only=False ):
    """Create a dir holding a fake `tmux` that logs args and (optionally) simulates the
    bridge changing on the first Enter. Returns ( dir, tmux_log_path ).

    `mtime_only=True` reproduces the DEFECT condition (bug e88ebfae): the bridge's mtime
    moves but its content does not — exactly what `touch_bridge_mtime()` does from the
    PostToolUse hook on every tool call. The gate must NOT open on that."""
    d       = tmp_path / "bin"
    d.mkdir()
    log     = tmp_path / "tmux.log"
    flag    = "1" if bridge_to_rewrite else ""
    # A rehydrate mints a NEW transient session_id; a bare touch leaves it alone.
    change  = ( f'    touch "{bridge_to_rewrite}"\n' if mtime_only
                else f'    printf \'{{\\n  "session_id": "NEW-AFTER-CLEAR",\\n  "stable_session_id": "SEAT-1"\\n}}\\n\' > "{bridge_to_rewrite}"\n' )
    shim = (
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> "{log}"\n'
        # On the FIRST Enter (the /clear submit), simulate SessionStart rewriting the
        # bridge — a one-shot sentinel so the wake's own Enter does not re-fire it.
        f'if [ -n "{flag}" ] && printf "%s" "$*" | grep -q "Enter"; then\n'
        f'  if [ ! -f "{log}.touched" ]; then\n'
        f'    : > "{log}.touched"\n'
        f'{change}'
        "  fi\n"
        "fi\n"
        "exit 0\n"
    )
    p = d / "tmux"
    p.write_text( shim )
    p.chmod( 0o755 )
    return str( d ), str( log )


def _run_gate( tmp_path, *, touch_bridge, ready_timeout_polls, poll_interval_seconds=0.05,
               mtime_only=False ):
    """Build the REAL wake argv and execute it with a fake tmux on PATH. Returns
    ( returncode, tmux_log_text, stderr ).

    NOTE: the injector writes NO receipt — a receipt written here would only prove the
    injector reached the line, never that the pane ingested the keystrokes (send-keys has
    no ingestion feedback). This test proves the gate TYPES the wake (or doesn't); proof of
    a REAL wake is consumer-side (the rehydrated seat writes a nonce-echoing artifact), which
    the observer suite covers."""
    bridge      = tmp_path / "cc-4242.json"
    # A pre-existing bridge carrying the seat's CURRENT transient id — what the gate
    # samples as s0 right before the /clear.
    bridge.write_text( '{\n  "session_id": "OLD-BEFORE-CLEAR",\n  "stable_session_id": "SEAT-1"\n}\n' )
    fire_token  = tmp_path / ".self-respin-fire-sid.token"
    fire_token.write_text( "{}" )                             # rm "$4" must succeed
    bin_dir, log = _fake_tmux_dir( tmp_path, bridge_to_rewrite=str( bridge ) if touch_bridge else None,
                                   mtime_only=mtime_only )

    argv = sr.build_guarded_clear_argv(
        "sess", str( fire_token ), 0,                         # delay 0 — no real wait
        wake_text="READ YOUR MEMENTO AND RESUME",
        bridge_path=str( bridge ),
        ready_timeout_polls=ready_timeout_polls,
        poll_interval_seconds=poll_interval_seconds,
    )
    env = dict( os.environ, PATH=f"{bin_dir}:{os.environ.get( 'PATH', '' )}" )
    proc = subprocess.run( argv, env=env, capture_output=True, text=True, timeout=30 )
    log_text = ""
    if os.path.exists( log ):
        with open( log ) as f:
            log_text = f.read()
    return proc.returncode, log_text, proc.stderr


def test_wake_fires_when_bridge_reports_a_new_session( tmp_path ):
    """(a) The rehydrate write mints a new transient session_id → gate breaks → wake typed, exit 0."""
    rc, log, _ = _run_gate( tmp_path, touch_bridge=True, ready_timeout_polls=100 )
    assert rc == 0
    assert "/clear" in log                                    # the clear was typed
    assert "READ YOUR MEMENTO AND RESUME" in log              # the wake fired AFTER the gate
    # the fire token was consumed (one-shot guard ran)
    assert not ( tmp_path / ".self-respin-fire-sid.token" ).exists()


def test_wake_times_out_loudly_when_bridge_never_changes( tmp_path ):
    """(b) session_id never changes → bounded loop gives up: exit 3, wake NEVER typed."""
    rc, log, stderr = _run_gate( tmp_path, touch_bridge=False, ready_timeout_polls=3, poll_interval_seconds=0.02 )
    assert rc == 3                                            # loud, bounded give-up
    assert "/clear" in log                                    # the clear WAS still typed
    assert "READ YOUR MEMENTO AND RESUME" not in log         # the wake was NOT typed into the old context
    assert "not proven" in stderr                            # the loud stderr witness


def test_wake_gate_no_ops_when_fire_token_already_gone( tmp_path ):
    """The one-shot guard: a second fire finds the token gone → rm fails → exit 0,
    NOTHING typed (not the clear, not the wake) — the double-fire this row guards."""
    bridge     = tmp_path / "cc-4242.json"
    bridge.write_text( "{}" )
    missing    = tmp_path / ".gone.token"                     # never created
    bin_dir, log = _fake_tmux_dir( tmp_path, bridge_to_rewrite=str( bridge ) )
    argv = sr.build_guarded_clear_argv(
        "sess", str( missing ), 0, wake_text="WAKE", bridge_path=str( bridge ),
        ready_timeout_polls=3, poll_interval_seconds=0.02,
    )
    env  = dict( os.environ, PATH=f"{bin_dir}:{os.environ.get( 'PATH', '' )}" )
    proc = subprocess.run( argv, env=env, capture_output=True, text=True, timeout=30 )
    assert proc.returncode == 0                               # rm "$4" || exit 0
    assert not os.path.exists( log )                          # tmux never invoked → nothing typed


def test_wake_does_NOT_fire_on_a_bare_mtime_touch( tmp_path ):
    """
    (c) THE REGRESSION THAT MATTERS — bug e88ebfae, reproduced end-to-end.

    The bridge's mtime moves but its content does not. That is precisely what
    `touch_bridge_mtime()` does on every tool call (session_bridge.py REDLINE C1: a
    bare os.utime, no content write), so it is what a seat still finishing its turn
    does to its own bridge milliseconds after the /clear is queued.

    Under the old mtime gate this opened the gate and typed the wake into the
    UN-CLEARED pane, which is how a seat at 519,378 tokens was told it had rehydrated
    at low context. The gate must now time out loudly instead.
    """
    rc, log, stderr = _run_gate( tmp_path, touch_bridge=True, mtime_only=True,
                                 ready_timeout_polls=3, poll_interval_seconds=0.02 )
    assert rc == 3                                            # timed out — correct
    assert "/clear" in log                                    # the clear WAS typed
    assert "READ YOUR MEMENTO AND RESUME" not in log          # the wake was NOT typed
    assert "not proven" in stderr


# ---------------------------------------------------------------------------
# The pre-clear session id is SUBSTITUTED INTO the wake at fire time
# ---------------------------------------------------------------------------
#
# 🔴 WHY THIS MUST BE AN EXECUTION TEST. The substitution is a bash parameter
# expansion inside the detached chain. A string-match on the script proves the
# expansion was WRITTEN, never that it RUNS — and it did not, on the first cut: an
# escaped `\"` inside `${s0%\"}` reads as an opening quote to bash and the whole
# script died with `unexpected EOF while looking for matching '"'`. The chain exited
# 2, no wake was typed, and every string-match assertion in the sibling suite would
# have passed. Only running it found that.

def _sub_probe_tmux_dir( tmp_path, bridge, post_id ):
    """A fake `tmux` that logs its args and, on the FIRST Enter, rewrites the bridge
    with `post_id` — what SessionStart does after a real /clear."""
    d   = tmp_path / "subbin"
    d.mkdir()
    log = tmp_path / "sub-tmux.log"
    ( d / "tmux" ).write_text(
        "#!/bin/bash\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        f'if [[ "$*" == *Enter* ]] && [ ! -f "{tmp_path}/.did" ]; then\n'
        f'  : > "{tmp_path}/.did"\n'
        f'  printf \'{{\\n  "session_id": "{post_id}",\\n  "stable_session_id": "stable-1"\\n}}\\n\' > "{bridge}"\n'
        "fi\n"
        "exit 0\n"
    )
    ( d / "tmux" ).chmod( 0o755 )
    return d, log


def test_the_typed_wake_carries_the_PRE_clear_session_id( tmp_path ):
    """
    Run the REAL chain and read what the pane was actually handed.

    Requires:
        - bash and a writable tmp dir

    Ensures:
        - the sentinel does NOT survive into the typed wake (it was substituted)
        - the typed wake quotes the id the bridge held BEFORE the clear
        - it does NOT quote the post-clear id — quoting that would make the seat's
          comparison trivially equal and the instrument would always say "no clear"
    """
    pre    = "00249b1e-25c1-478a-8579-b134fb77e354"
    post   = "4bc5167d-7f02-456c-b66c-c6d868a9b2f0"
    bridge = tmp_path / "bridge.json"
    bridge.write_text( f'{{\n  "session_id": "{pre}",\n  "stable_session_id": "stable-1"\n}}\n' )
    token  = tmp_path / "fire.token"
    token.write_text( "x" )

    bindir, log = _sub_probe_tmux_dir( tmp_path, bridge, post )
    wake = sr.build_wake_text( "/m/memento.md", "NONCE-123", "/m/proof.marker" )
    argv = sr.build_guarded_clear_argv(
        "seat-pane", str( token ), 0, wake_text=wake, bridge_path=str( bridge ),
        poll_interval_seconds=0.05, ready_timeout_polls=40, settle_seconds=0.05 )

    env = dict( os.environ, PATH=f"{bindir}{os.pathsep}{os.environ[ 'PATH' ]}" )
    run = subprocess.run( argv, env=env, capture_output=True, text=True, timeout=60 )
    assert run.returncode == 0, f"chain failed rc={run.returncode}: {run.stderr[ :400 ]}"

    typed = [ l for l in log.read_text().splitlines() if "-l --" in l ]
    wakes = [ l for l in typed if "SELF-RESPIN-WAKE-PROOF" in l ]
    assert wakes, f"no wake was typed; tmux saw: {typed}"
    got = wakes[ 0 ]

    assert sr._PRE_CLEAR_SID_SENTINEL not in got, \
        "the sentinel survived into the typed wake — the substitution did not run"
    assert pre  in got, "the typed wake does not quote the PRE-clear session id"
    assert post not in got, \
        "the typed wake quotes the POST-clear id; the seat's comparison would always say 'same'"


def test_an_unreadable_bridge_still_sends_a_wake_that_says_so( tmp_path ):
    """
    When the bridge cannot be read at fire time there is no id to quote. The chain must
    substitute the explicit UNAVAILABLE marker rather than an empty string.

    Ensures:
        - an empty id never reaches the seat as if it were an answer

    An empty substitution would render as `this pane was session .` — which reads like a
    real, if odd, statement, and a seat comparing against it concludes "differs" every
    time. A named unavailable value is the difference between a missing reading and a
    confident wrong one.
    """
    bridge = tmp_path / "absent.json"          # deliberately never created
    token  = tmp_path / "fire2.token"
    token.write_text( "x" )
    post   = "4bc5167d-7f02-456c-b66c-c6d868a9b2f0"

    bindir, log = _sub_probe_tmux_dir( tmp_path, bridge, post )
    wake = sr.build_wake_text( "/m/memento.md", "NONCE-9", "/m/proof.marker" )
    argv = sr.build_guarded_clear_argv(
        "seat-pane", str( token ), 0, wake_text=wake, bridge_path=str( bridge ),
        poll_interval_seconds=0.05, ready_timeout_polls=40, settle_seconds=0.05 )

    env = dict( os.environ, PATH=f"{bindir}{os.pathsep}{os.environ[ 'PATH' ]}" )
    subprocess.run( argv, env=env, capture_output=True, text=True, timeout=60 )

    typed = [ l for l in log.read_text().splitlines() if "-l --" in l ]
    wakes = [ l for l in typed if "SELF-RESPIN-WAKE-PROOF" in l ]
    assert wakes, f"no wake was typed; tmux saw: {typed}"
    # 🔴 ASSERT THE SUBSTITUTION SITE, NOT THE STRING. The first cut of this test was
    # `sr._PRE_CLEAR_SID_UNAVAILABLE in wakes[0]`, and it was BLIND: the wake TEMPLATE
    # already contains that literal in its closing sentence ("if the id above reads
    # (unavailable) …"), so the assertion held whatever the chain substituted. Deleting
    # the fallback entirely left it GREEN. Expected and actual met inside the template —
    # a tautology wearing an assertion's clothes. The contiguous phrase below occurs
    # ONLY where the substitution lands.
    assert f"was session {sr._PRE_CLEAR_SID_UNAVAILABLE}" in wakes[ 0 ], \
        "an unreadable bridge must yield the named UNAVAILABLE value AT THE SUBSTITUTION " \
        "SITE, never an empty id that renders as 'was session .'"
    assert sr._PRE_CLEAR_SID_SENTINEL not in wakes[ 0 ]

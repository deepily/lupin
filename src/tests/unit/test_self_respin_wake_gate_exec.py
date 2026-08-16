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


def _fake_tmux_dir( tmp_path, *, bridge_to_touch ):
    """Create a dir holding a fake `tmux` that logs args and (optionally) touches the
    bridge on the first Enter. Returns ( dir, tmux_log_path )."""
    d       = tmp_path / "bin"
    d.mkdir()
    log     = tmp_path / "tmux.log"
    touchfl = "1" if bridge_to_touch else ""
    shim = (
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> "{log}"\n'
        # On the FIRST Enter (the /clear submit), simulate SessionStart rewriting the
        # bridge — a one-shot sentinel so the wake's own Enter does not re-touch.
        f'if [ -n "{touchfl}" ] && printf "%s" "$*" | grep -q "Enter"; then\n'
        f'  if [ ! -f "{log}.touched" ]; then\n'
        f'    : > "{log}.touched"\n'
        f'    touch "{bridge_to_touch}"\n'
        "  fi\n"
        "fi\n"
        "exit 0\n"
    )
    p = d / "tmux"
    p.write_text( shim )
    p.chmod( 0o755 )
    return str( d ), str( log )


def _run_gate( tmp_path, *, touch_bridge, ready_timeout_polls, poll_interval_seconds=0.05 ):
    """Build the REAL wake argv and execute it with a fake tmux on PATH. Returns
    ( returncode, tmux_log_text )."""
    bridge      = tmp_path / "cc-4242.json"
    bridge.write_text( "{}" )                                  # pre-existing bridge (mtime = now)
    fire_token  = tmp_path / ".self-respin-fire-sid.token"
    fire_token.write_text( "{}" )                             # rm "$4" must succeed
    bin_dir, log = _fake_tmux_dir( tmp_path, bridge_to_touch=str( bridge ) if touch_bridge else None )

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


def test_wake_fires_when_bridge_mtime_changes( tmp_path ):
    """(a) The rehydrate write moves the mtime → gate breaks → wake is typed, exit 0."""
    rc, log, _ = _run_gate( tmp_path, touch_bridge=True, ready_timeout_polls=100 )
    assert rc == 0
    assert "/clear" in log                                    # the clear was typed
    assert "READ YOUR MEMENTO AND RESUME" in log              # the wake fired AFTER the gate
    # the fire token was consumed (one-shot guard ran)
    assert not ( tmp_path / ".self-respin-fire-sid.token" ).exists()


def test_wake_times_out_loudly_when_bridge_never_changes( tmp_path ):
    """(b) mtime never moves → bounded loop gives up: exit 3, wake NEVER typed."""
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
    bin_dir, log = _fake_tmux_dir( tmp_path, bridge_to_touch=str( bridge ) )
    argv = sr.build_guarded_clear_argv(
        "sess", str( missing ), 0, wake_text="WAKE", bridge_path=str( bridge ),
        ready_timeout_polls=3, poll_interval_seconds=0.02,
    )
    env  = dict( os.environ, PATH=f"{bin_dir}:{os.environ.get( 'PATH', '' )}" )
    proc = subprocess.run( argv, env=env, capture_output=True, text=True, timeout=30 )
    assert proc.returncode == 0                               # rm "$4" || exit 0
    assert not os.path.exists( log )                          # tmux never invoked → nothing typed

"""
EXECUTION test for the self-re-spin idle gate (row 698a5aaf).

Measured failures (09-09 twice, 09-10): /clear typed into a pane that was mid-turn
consumed the fire token and cleared nothing. The fix waits for an idle prompt first.
This RUNS the real built script against a fake `tmux` on PATH whose capture-pane
replays a scripted sequence of screens, and whose send-keys is logged, so the test
sees exactly when — and whether — /clear was typed.

Venue: subprocess + temp files only, sub-second, no server → :7999-eligible.
"""

import os
import subprocess

import pytest

import lupin_mcp.self_respin_core as sr


_BUSY   = "✻ Working… (12s · esc to interrupt)\n"
_IDLE   = "─" * 80 + "\n❯ \n" + "─" * 80 + "\n"
_DIALOG = "─" * 80 + "\nDo you want to proceed?\n❯ 1. Yes\n" + "─" * 80 + "\n"


def _fake_tmux( tmp_path, screens ):
    """A fake tmux: capture-pane prints the next screen from `screens` (the last one
    repeats), send-keys appends its args to a log. Returns ( bin_dir, log_path )."""
    d = tmp_path / "bin"
    d.mkdir()
    for i, screen in enumerate( screens ):
        ( tmp_path / f"screen-{i}.txt" ).write_text( screen )
    log     = tmp_path / "send.log"
    counter = tmp_path / "capture.count"
    last    = len( screens ) - 1
    shim = (
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "capture-pane" ]; then\n'
        f'  n=$(cat "{counter}" 2>/dev/null || echo 0)\n'
        f'  echo $((n + 1)) > "{counter}"\n'
        f'  [ "$n" -gt {last} ] && n={last}\n'
        f'  cat "{tmp_path}/screen-$n.txt"\n'
        "  exit 0\n"
        "fi\n"
        f'echo "$*" >> "{log}"\n'
        "exit 0\n"
    )
    p = d / "tmux"
    p.write_text( shim )
    p.chmod( 0o755 )
    return str( d ), log, counter


def _run( tmp_path, screens, *, max_seconds=0.5, poll=0.05 ):
    token = tmp_path / ".self-respin-fire-sid.token"
    token.write_text( "{}" )
    stamp = tmp_path / ".self-respin-keys-sent-sid.marker"
    bin_dir, log, counter = _fake_tmux( tmp_path, screens )
    argv = sr.build_guarded_clear_argv(
        "sess", str( token ), 0, keys_sent_path=str( stamp ),
        idle_wait_max_seconds=max_seconds, idle_poll_seconds=poll,
    )
    env  = dict( os.environ, PATH=f"{bin_dir}:{os.environ.get( 'PATH', '' )}" )
    proc = subprocess.run( argv, env=env, capture_output=True, text=True, timeout=30 )
    sent = log.read_text() if log.exists() else ""
    return proc, sent, token, stamp, int( counter.read_text() ) if counter.exists() else 0


def test_clear_is_typed_only_after_the_pane_goes_idle( tmp_path ):
    """Busy for three captures, then idle: /clear is typed, the token consumed, the send stamped."""
    proc, sent, token, stamp, captures = _run( tmp_path, [ _BUSY, _BUSY, _BUSY, _IDLE ] )
    assert proc.returncode == 0, proc.stderr
    assert "/clear" in sent
    assert not token.exists()
    assert stamp.exists()
    assert captures >= 5, "idle must be seen on two captures, after the three busy ones"


def test_a_pane_that_never_goes_idle_gets_no_clear_and_keeps_its_token( tmp_path ):
    """Mr. Radio's ordering: the wait runs before rm, so a timeout leaves the token as
    evidence the clear never fired — and the send is never stamped."""
    proc, sent, token, stamp, _ = _run( tmp_path, [ _BUSY ], max_seconds=0.2, poll=0.05 )
    assert proc.returncode == 4
    assert sent == ""
    assert token.exists()
    assert not stamp.exists()
    assert "never showed an idle prompt" in proc.stderr


def test_a_permission_dialog_is_never_mistaken_for_an_idle_prompt( tmp_path ):
    """A dialog paints the divider but is not a prompt — typing /clear into it could pick an option."""
    proc, sent, token, _, _ = _run( tmp_path, [ _DIALOG ], max_seconds=0.2, poll=0.05 )
    assert proc.returncode == 4
    assert sent == ""
    assert token.exists()


def test_one_idle_frame_between_busy_frames_is_not_enough( tmp_path ):
    """The recheck: a turn that is STARTING may not have painted its busy line yet."""
    proc, sent, _, _, _ = _run( tmp_path, [ _IDLE, _BUSY, _BUSY, _BUSY ], max_seconds=0.2, poll=0.05 )
    assert proc.returncode == 4
    assert sent == ""


def test_the_wake_chain_waits_for_idle_before_its_clear_too( tmp_path ):
    """The wake path carries the same gate: never idle → no /clear, no wake, token kept."""
    token  = tmp_path / ".self-respin-fire-sid.token"
    token.write_text( "{}" )
    bridge = tmp_path / "cc-1.json"
    bridge.write_text( '{\n  "session_id": "OLD"\n}\n' )
    bin_dir, log, _ = _fake_tmux( tmp_path, [ _BUSY ] )
    argv = sr.build_guarded_clear_argv(
        "sess", str( token ), 0, wake_text="WAKE", bridge_path=str( bridge ),
        ready_timeout_polls=2, poll_interval_seconds=0.01,
        idle_wait_max_seconds=0.2, idle_poll_seconds=0.05,
    )
    env  = dict( os.environ, PATH=f"{bin_dir}:{os.environ.get( 'PATH', '' )}" )
    proc = subprocess.run( argv, env=env, capture_output=True, text=True, timeout=30 )
    assert proc.returncode == 4
    assert not log.exists()
    assert token.exists()


def test_without_the_gate_the_script_is_unchanged():
    """None ⇒ no gate: existing callers and their tests see the original chain."""
    plain = sr.build_guarded_clear_argv( "sess", "/t", 20 )
    assert "_idle" not in plain[ 2 ]
    assert len( plain ) == 9

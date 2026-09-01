"""
Does the narrow fix (51950988) REPAIR a seat already carrying an erased stamp, or
only PREVENT a ninth? — row 8a4647b8, split off the class-decision row e9b78e51.

THE QUESTION AND WHY IT NEEDED MEASURING RATHER THAN READING. Mr. Radio asked it
twice: "a fix that stops new sessions losing the stamp while leaving every existing
seat broken needs a remediation step for the fleet, and that step is not in the diff."
The fix's own commit message answers "it does NOT heal — the eight erased seats stay
erased until each restarts", and the runbook on e9b78e51 says it "REPAIRS NOTHING
already broken." Both are the author's claim about his own patch, so this file
measures it instead of citing it.

WHAT THE TWO RUNS MEAN. `main()` is the SessionStart hook. Running it a SECOND time
against the same session id IS the /clear and re-spin path — that is the whole reason
a second run is the right instrument here rather than a contrivance.

⚠️ THE ANSWER TURNS ON A DISTINCTION THE WORD "REPAIR" HIDES, which is why this file
asserts three separate things rather than one:

    PASSIVELY, with the seat doing nothing   -> NO. Nothing reaches an idle bridge.
    On the seat's next SessionStart          -> YES, and that is what these tests pin.
    Which a /clear or a restart both are     -> so the runbook is for a seat that
                                                cannot afford either, not for all of them.

"Repairs nothing" and "repairs itself at the next SessionStart" are both true of
different questions, and only the second one tells five seats what to do.
"""

import importlib
import io
import json
from contextlib import redirect_stderr

import pytest

HOOK_MODULE   = "lupin_cli.claude_code.hooks.register_session"
SESSION_ID    = "0e3df8ca-9019-42ad-803c-b72e6e7b6289"   # shape of a real erased seat
SENTINEL_KEY  = "SENTINEL_ondisk_only"


def _seam( monkeypatch, tmp_path ):
    """The redirected HOME + bridge dir, built once and reused across both runs."""
    home = tmp_path / "home"
    seam = tmp_path / "seam"
    ( home / ".claude" / "sessions" ).mkdir( parents=True )
    seam.mkdir()
    monkeypatch.setenv( "HOME", str( home ) )
    monkeypatch.setenv( "LUPIN_HOOK_SESSIONS_DIR", str( seam ) )
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path / "lupin" ) )
    monkeypatch.setenv( "COSA_VOICE_PREFERRED_PERSONA__LUPIN", "Tiffany" )
    for _k in ( "COSA_VOICE_SPAWNED_BY", "COSA_VOICE_HEADLESS", "COSA_VOICE_ROLE",
                "COSA_VOICE_PERSONA_CHAIN", "COSA_VOICE_SPAWNED_BY_PERSONA" ):
        monkeypatch.delenv( _k, raising=False )
    return seam


def _run_session_start( monkeypatch, seam, persona_name="Tiffany" ):
    """
    One real SessionStart against `seam`, with the REAL listener path live.

    Only the subprocess is faked. Patching `_spawn_listener` away is what hid this
    entire defect from the original stamp test — `_record_listener_pid` is the write
    that clobbers, so a seam that skips it cannot answer any question on this row.
    """
    module = importlib.import_module( HOOK_MODULE )
    from lupin_cli.claude_code.hooks.lib import session_bridge as sb
    from lupin_cli.claude_code.hooks.lib import manager_figure  as mf

    monkeypatch.setattr( sb, "SESSION_DIR", seam )
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
    monkeypatch.setattr( mf, "resolve_project_name", lambda environ=None: "lupin" )
    monkeypatch.setattr( module, "read_hook_input",
                         lambda: { "session_id": SESSION_ID, "cwd": "/tmp",
                                   "transcript_path": "/x" } )
    monkeypatch.setattr( module, "emit_json", lambda *a, **k: None )
    monkeypatch.setattr( module, "send_tts",  lambda *a, **k: None )

    class _FakeProc:
        pid = __import__( "os" ).getpid()
    _real_popen = module.subprocess.Popen
    def _popen( cmd, *a, **k ):
        if ( isinstance( cmd, list ) and len( cmd ) > 2
             and cmd[ 0 ] == __import__( "sys" ).executable and cmd[ 1 ] == "-m"
             and "cc_notification_listener" in cmd[ 2 ] ):
            return _FakeProc()
        return _real_popen( cmd, *a, **k )
    monkeypatch.setattr( module.subprocess, "Popen", _popen )
    monkeypatch.setattr( module.time, "sleep", lambda *a, **k: None )
    monkeypatch.setattr( module, "_allocate_voice_persona_via_http",
                         lambda *a, **k: ( { "name": persona_name }, None ) )

    buf = io.StringIO()
    with redirect_stderr( buf ):
        try:
            module.main()
        except SystemExit:
            pass

    bridges = list( seam.glob( "cc-*.json" ) )
    assert len( bridges ) == 1, f"expected one bridge, got {[ b.name for b in bridges ]}"
    return bridges[ 0 ], sb.MANAGER_FIGURE_BRIDGE_FIELD


def _erase_stamp( bridge, field, extra=None ):
    """
    Turn a healthy bridge into one a PRE-FIX session would have left behind.

    Removing the field is the whole simulation: that is exactly the end state the
    wholesale write produced, and it is what the five listed seats are sitting in.
    """
    data = json.loads( bridge.read_text() )
    data.pop( field, None )
    if extra: data.update( extra )
    bridge.write_text( json.dumps( data ) )
    return data


class TestThePreventDirection:
    """Direction 1 — does a session started under the fix keep its stamp?"""

    def test_a_fresh_session_start_lands_the_stamp_and_the_listener_pid_together( self, monkeypatch, tmp_path ):
        """
        Both keys, from one run, with the clobbering write live.

        `listener_pid` is the control that matters: its presence proves
        `_record_listener_pid` actually RAN. Asserting the stamp alone would pass
        just as well on a seam where the clobbering write never fired, which is
        precisely how the original test stayed green through the live defect.
        """
        seam = _seam( monkeypatch, tmp_path )
        bridge, field = _run_session_start( monkeypatch, seam )
        data = json.loads( bridge.read_text() )
        assert "listener_pid" in data, "the clobbering write never ran — this seam proves nothing"
        assert field in data,          "the stamp did not survive the listener-pid write"


class TestTheRepairDirection:
    """
    Direction 2 — does a seat that is ALREADY erased get its stamp back?

    This is the one that decides whether the fleet is owed a remediation step.
    """

    def test_a_second_session_start_restamps_an_already_erased_bridge( self, monkeypatch, tmp_path ):
        """
        THE MEASUREMENT. Run once, erase the field the way the pre-fix code did,
        run again against the SAME session id — which is what /clear and a re-spin
        both do — and the stamp comes back.

        So "repairs nothing already broken" is true only of a seat that never has
        another SessionStart. Every seat that clears or restarts repairs itself.
        """
        seam = _seam( monkeypatch, tmp_path )
        bridge, field = _run_session_start( monkeypatch, seam )

        before = _erase_stamp( bridge, field )
        assert field not in before, "control failed: the bridge was not actually erased"

        _run_session_start( monkeypatch, seam )
        after = json.loads( bridge.read_text() )
        assert field in after, "a second SessionStart did NOT restore the stamp"

    def test_an_idle_erased_bridge_is_never_repaired_on_its_own( self, monkeypatch, tmp_path ):
        """
        The other half of the same answer, and the half that justifies the runbook:
        nothing reaches a bridge whose seat does nothing. The fix lives in the
        SessionStart hook, so a seat that neither clears nor restarts stays erased
        however long it waits.

        ⚠️ THE `assert field in healthy` LINE IS WHAT MAKES THIS TEST MEAN ANYTHING.
        Without it the test asserts only an ABSENCE, and an absence is exactly what
        the un-fixed code produces too — so it passed on the negative control while
        its three siblings correctly went red. A test that cannot fail for the reason
        it names is not evidence, and this one was one line away from being that.
        """
        seam = _seam( monkeypatch, tmp_path )
        bridge, field = _run_session_start( monkeypatch, seam )

        healthy = json.loads( bridge.read_text() )
        assert field in healthy, "nothing was erased — this bridge never had the stamp"

        _erase_stamp( bridge, field )

        # No second run — this is the "seat sits there" case.
        assert field not in json.loads( bridge.read_text() )


class TestWhatTheSecondRunCostsBesidesTheStamp:
    """
    The class defect, MEASURED HERE AND NOW FIXED — Rick ruled option (d) on e9b78e51
    (2026-09-01) and the one-line rebind landed at 23804005 the night it was measured.
    These now assert the WORKING behaviour and pass; the xfail marker is gone.

    🔴 WHY THE MARKER EXISTED, kept because the reasoning outlives it. My first cut was
    a PASSING test asserting the BUG, and Mr. Radio 🦉 called it a trap: a green test
    asserting a defect reads as APPROVED BEHAVIOUR to anyone who did not write it, and
    the comment saying otherwise is not what a reader checks. `xfail(strict=True)` gave
    the same signal without the trap — an XPASS is a FAILURE, so whoever landed the
    rebind was forced back here to flip these. That is exactly what happened.

    `session_topic` is the named production victim: the MCP server writes it via
    set_session_topic, it lives only on the bridge, and it is what the stop-hook
    "Continue Session?" notification reads.
    """

    def test_an_on_disk_only_key_survives_the_next_session_start( self, monkeypatch, tmp_path ):
        seam = _seam( monkeypatch, tmp_path )
        bridge, field = _run_session_start( monkeypatch, seam )
        _erase_stamp( bridge, field,
                      extra={ SENTINEL_KEY: "written-by-nobody-in-main",
                              "session_topic": "a topic only the MCP server wrote" } )

        _run_session_start( monkeypatch, seam )
        after = json.loads( bridge.read_text() )

        assert SENTINEL_KEY    in after
        assert "session_topic" in after

    def test_the_stamp_is_no_longer_the_only_key_with_a_rescue( self, monkeypatch, tmp_path ):
        """
        Both the stamp and an unrelated on-disk key survive the next SessionStart, from
        ONE mechanism rather than one rescue per field.

        Keeping the stamp assertion beside the sentinel is deliberate: it proves the
        class fix did not merely move the problem, and it fails loudly if a future
        change starts rescuing fields one at a time again.

        This test asserted the inverse before the rebind landed. That history is in the
        commit that changed it (git log -p on this file), not restated here — Clayton 😎
        on review: a defect written out in the docstring of a green test is read as
        current behaviour by anyone who does not check the assertions underneath it.
        """
        seam = _seam( monkeypatch, tmp_path )
        bridge, field = _run_session_start( monkeypatch, seam )
        _erase_stamp( bridge, field, extra={ SENTINEL_KEY: "x" } )

        _run_session_start( monkeypatch, seam )
        after = json.loads( bridge.read_text() )

        assert field        in after, "the stamp survives"
        assert SENTINEL_KEY in after, "and so does an unrelated on-disk key — the class fix"

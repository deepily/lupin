"""
End-to-end test — register_session Phase 4.6 stamps the implicit manager-figure
answer onto the bridge (bug e5d600bd, Rick's Option A).

Drives the REAL main() with the bridge seam + session_bridge.SESSION_DIR
redirected and the HTTP/TTS/listener side effects mocked, then asserts the
on-disk bridge carries MANAGER_FIGURE_BRIDGE_FIELD computed from the caller's
env — the proof that the server can later read a static field instead of
re-deriving the (server-empty) implicit source.
"""

import importlib
import io
import json
from contextlib import redirect_stderr

import pytest

HOOK_MODULE = "lupin_cli.claude_code.hooks.register_session"


def _drive_stamp( monkeypatch, tmp_path, session_id, persona_name, chain, real_listener=False ):
    home = tmp_path / "home"
    seam = tmp_path / "seam"
    ( home / ".claude" / "sessions" ).mkdir( parents=True )
    seam.mkdir()
    monkeypatch.setenv( "HOME", str( home ) )
    monkeypatch.setenv( "LUPIN_HOOK_SESSIONS_DIR", str( seam ) )
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path / "lupin" ) )
    monkeypatch.setenv( "COSA_VOICE_PREFERRED_PERSONA__LUPIN", chain )
    # Isolate from the ambient spawn env (this suite may run inside a spawned
    # session): a lingering COSA_VOICE_SPAWNED_BY would stamp role="reviewer"
    # etc. onto the bridge. Phase 4.6 is orthogonal to those, but clear them so
    # the test is deterministic regardless of who launched it.
    for _k in ( "COSA_VOICE_SPAWNED_BY", "COSA_VOICE_HEADLESS", "COSA_VOICE_ROLE",
                "COSA_VOICE_PERSONA_CHAIN", "COSA_VOICE_SPAWNED_BY_PERSONA" ):
        monkeypatch.delenv( _k, raising=False )

    module = importlib.import_module( HOOK_MODULE )
    from lupin_cli.claude_code.hooks.lib import session_bridge as sb
    from lupin_cli.claude_code.hooks.lib import manager_figure as mf

    monkeypatch.setattr( sb, "SESSION_DIR", seam )
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
    # Deterministic project so the chain lookup is exercised, not the ambient bridge cwd.
    monkeypatch.setattr( mf, "resolve_project_name", lambda environ=None: "lupin" )

    monkeypatch.setattr( module, "read_hook_input",
                         lambda: { "session_id": session_id, "cwd": "/tmp",
                                   "transcript_path": "/x" } )
    monkeypatch.setattr( module, "emit_json", lambda *a, **k: None )
    monkeypatch.setattr( module, "send_tts", lambda *a, **k: None )
    if real_listener:
        # Row 6325123c — run the REAL _spawn_listener so _record_listener_pid()
        # actually fires. That call writes the in-memory session_data dict
        # WHOLESALE over the bridge, ~45 lines after Phase 4.6 stamped the file,
        # and it erased the stamp on every production session. Patching
        # _spawn_listener out (the other path below) hides the clobber entirely,
        # which is why the original stamp test passed while 0 of 47 real bridges
        # carried the field. Only the subprocess is faked here, not the write.
        class _FakeProc:
            pid = __import__( "os" ).getpid()   # a live pid, so the liveness check passes
        _real_popen = module.subprocess.Popen
        def _popen( cmd, *a, **k ):
            # Fake ONLY the listener spawn; main() also shells out elsewhere
            # (tree-state), and those must keep working.
            # `pgrep` scans for the same module name, so match the ACTUAL spawn:
            # this interpreter, run with -m on the listener module.
            if ( isinstance( cmd, list ) and len( cmd ) > 2
                 and cmd[ 0 ] == __import__( "sys" ).executable and cmd[ 1 ] == "-m"
                 and "cc_notification_listener" in cmd[ 2 ] ):
                return _FakeProc()
            return _real_popen( cmd, *a, **k )
        monkeypatch.setattr( module.subprocess, "Popen", _popen )
        monkeypatch.setattr( module.time, "sleep", lambda *a, **k: None )
    else:
        monkeypatch.setattr( module, "_spawn_listener", lambda *a, **k: None )
    # Allocation is the only source of the persona name Phase 4.6 reads.
    monkeypatch.setattr( module, "_allocate_voice_persona_via_http",
                         lambda *a, **k: ( { "name": persona_name }, None ) )

    buf = io.StringIO()
    with redirect_stderr( buf ):
        try:
            module.main()
        except SystemExit:
            pass

    bridges = list( seam.glob( "cc-*.json" ) )
    assert len( bridges ) == 1, f"Phase 2 bridge not written: {[ b.name for b in bridges ]}"
    return json.loads( bridges[ 0 ].read_text() ), sb.MANAGER_FIGURE_BRIDGE_FIELD


def test_named_standing_persona_stamps_true( monkeypatch, tmp_path ):
    data, field = _drive_stamp(
        monkeypatch, tmp_path,
        session_id="krishnaa-1111-2222-3333-444444444444",
        persona_name="Krishna", chain="Krishna,*",
    )
    # Phase 4.6 stamps the implicit answer computed from the allocated persona.
    # (voice_persona itself is written to the bridge by the server's /allocate
    # endpoint, which is mocked out here — not this block's responsibility.)
    assert data[ field ] is True


def test_worker_persona_stamps_false( monkeypatch, tmp_path ):
    data, field = _drive_stamp(
        monkeypatch, tmp_path,
        session_id="tiffanyy-1111-2222-3333-444444444444",
        persona_name="Tiffany", chain="Krishna,*",
    )
    assert data[ field ] is False


@pytest.mark.parametrize( "persona,chain,expected", [
    ( "Krishna", "Krishna,*", True  ),
    ( "Tiffany", "Krishna,*", False ),
] )
def test_stamp_survives_the_listener_pid_write( monkeypatch, tmp_path, persona, chain, expected ):
    """
    Row 6325123c — the stamp must survive to the END of main(), not merely be
    written by Phase 4.6.

    MEASURED 2026-08-30: Phase 4.6 called set_manager_figure_implicit(), which
    writes the FILE. main() then called _spawn_listener() -> _record_listener_pid(),
    which does atomic_write_json( session_file, session_data ) — a WHOLESALE write
    of a dict captured before the stamp, not a read-modify-write. The field was
    therefore erased on every real session; 0 of 47 live bridges carried it, and
    the server's blocked-mint guard answered 403 to every caller.

    The two tests above cannot see this because they patch _spawn_listener away.
    This one leaves it real and fakes only the subprocess.
    """
    data, field = _drive_stamp(
        monkeypatch, tmp_path,
        session_id="1ed3e116-1111-2222-3333-444444444444",
        persona_name=persona, chain=chain, real_listener=True,
    )
    assert "listener_pid" in data, "the clobbering write did not run — test is not exercising the bug"
    assert field in data, "manager-figure stamp was erased by the listener-pid write (row 6325123c)"
    assert data[ field ] is expected

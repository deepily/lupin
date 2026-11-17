"""
register_session turns the spawn voice-mode word into the bridge's speakerphone_on.

The tests drive the actual main(), as test_register_session_manager_figure_stamp.py does. They cover the
three words, an absent word, and solo and chorus for `inherit`. They also cover Tiberius's second
amendment. A spawned session whose persona is a standing manager gets the mode-aware default, never the
worker's quiet start. Cheech was spawned as role "author" and Maria as "manager".
"""
import importlib
import io
import json
from contextlib import redirect_stderr

import pytest

HOOK_MODULE = "lupin_cli.claude_code.hooks.register_session"


def _drive( monkeypatch, tmp_path, *, persona, chain, role, voice_word, chorus, flip_to=None ):
    home = tmp_path / "home"
    seam = tmp_path / "seam"
    ( home / ".claude" / "sessions" ).mkdir( parents=True )
    seam.mkdir()
    monkeypatch.setenv( "HOME", str( home ) )
    monkeypatch.setenv( "LUPIN_HOOK_SESSIONS_DIR", str( seam ) )
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path / "lupin" ) )
    monkeypatch.setenv( "COSA_VOICE_PREFERRED_PERSONA__LUPIN", chain )
    monkeypatch.setenv( "COSA_VOICE_SPAWNED_BY", "mgr-session" )
    monkeypatch.setenv( "COSA_VOICE_ROLE", role )
    for k in ( "COSA_VOICE_HEADLESS", "COSA_VOICE_PERSONA_CHAIN", "COSA_VOICE_SPAWNED_BY_PERSONA",
               "COSA_VOICE_WORKER_VOICE_MODE" ):
        monkeypatch.delenv( k, raising=False )
    if voice_word is not None:
        monkeypatch.setenv( "COSA_VOICE_WORKER_VOICE_MODE", voice_word )

    module = importlib.import_module( HOOK_MODULE )
    from lupin_cli.claude_code.hooks.lib import session_bridge as sb
    from lupin_cli.claude_code.hooks.lib import manager_figure as mf
    from cosa.utils import util as cu

    monkeypatch.setattr( sb, "SESSION_DIR", seam )
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
    monkeypatch.setattr( mf, "resolve_project_name", lambda environ=None: "lupin" )
    monkeypatch.setattr( cu, "get_tts_interaction_mode", lambda: "chorus" if chorus else "solo" )
    monkeypatch.setattr( module, "read_hook_input",
                         lambda: { "session_id": f"{persona.lower()[:8]:<8}-1111-2222-3333-444444444444".replace( " ", "x" ),
                                   "cwd": "/tmp", "transcript_path": "/x" } )
    monkeypatch.setattr( module, "emit_json", lambda *a, **k: None )
    monkeypatch.setattr( module, "send_tts", lambda *a, **k: None )
    monkeypatch.setattr( module, "_spawn_listener", lambda *a, **k: None )
    monkeypatch.setattr( module, "_allocate_voice_persona_via_http",
                         lambda *a, **k: ( { "name": persona }, None ) )
    def _run():
        with redirect_stderr( io.StringIO() ):
            try: module.main()
            except SystemExit: pass
    _run()
    bridges = list( seam.glob( "cc-*.json" ) )
    assert len( bridges ) == 1
    if flip_to is not None:
        # Row 4d811743: Rick flips the voice mode mid-session, then the context resets (a second
        # SessionStart for the same session reads the flipped bridge as old_data).
        flipped = json.loads( bridges[ 0 ].read_text() )
        flipped[ "speakerphone_on" ] = flip_to
        bridges[ 0 ].write_text( json.dumps( flipped ) )
        _run()
        bridges = list( seam.glob( "cc-*.json" ) )
        assert len( bridges ) == 1
    return json.loads( bridges[ 0 ].read_text() )


@pytest.mark.parametrize( "word,chorus,expected", [
    ( "quiet",        True,  False ),
    ( "quiet",        False, False ),
    ( "speakerphone", False, True  ),
    ( "inherit",      False, False ),
    ( "inherit",      True,  True  ),
    ( None,           True,  False ),   # a child spawned by an older server keeps today's False
] )
def test_a_worker_persona_follows_the_word( monkeypatch, tmp_path, word, chorus, expected ):
    data = _drive( monkeypatch, tmp_path, persona="Tiffany", chain="Cheech,maria,*",
                   role="author", voice_word=word, chorus=chorus )
    assert data[ "speakerphone_on" ] is expected
    assert data[ "manager_figure_implicit" ] is False


@pytest.mark.parametrize( "persona,role", [ ( "Cheech", "author" ), ( "maria", "manager" ), ( "maria", "reviewer" ) ] )
@pytest.mark.parametrize( "chorus,expected", [ ( False, False ), ( True, True ) ] )
def test_a_standing_manager_gets_inherit_whatever_role_and_whatever_word( monkeypatch, tmp_path, persona, role, chorus, expected ):
    data = _drive( monkeypatch, tmp_path, persona=persona, chain="Cheech,maria,*",
                   role=role, voice_word="quiet", chorus=chorus )
    assert data[ "manager_figure_implicit" ] is True
    assert data[ "speakerphone_on" ] is expected, "a manager must get the mode-aware default, solo off and chorus on"


@pytest.mark.parametrize( "role,persona,expected", [
    ( "author",  "Tiffany", False ),   # a worker starts quiet under the INI key
    ( "manager", "maria",   True  ),   # a spawned manager inherits, and chorus is on
] )
def test_the_real_spawn_env_feeds_the_real_hook( monkeypatch, tmp_path, role, persona, expected ):
    """spawn_sessions builds the child's env, and the hook turns that env into the bridge flag."""
    from test_spawn_sessions import FakeRunner, _stated_fleet
    from lupin_mcp.session_spawner import spawn_sessions
    runner = FakeRunner()
    spawn_sessions( 1, "t", "mgr-sid", script_path="/s.sh", role=role, runner=runner, session_dir=tmp_path / "sessions",
                    voice_config_fn=lambda: type( "C", ( ), { "get": lambda self, key, default=None, **kw: "quiet" } )(),
                    **_stated_fleet() )
    env  = runner.calls[ 0 ][ 1 ]
    data = _drive( monkeypatch, tmp_path, persona=persona, chain="Cheech,maria,*", role=env[ "COSA_VOICE_ROLE" ],
                   voice_word=env[ "COSA_VOICE_WORKER_VOICE_MODE" ], chorus=True )
    assert data[ "speakerphone_on" ] is expected


@pytest.mark.parametrize( "word,flip", [ ( "quiet", True ), ( "speakerphone", False ) ] )
def test_a_worker_flip_survives_a_context_reset( monkeypatch, tmp_path, word, flip ):
    """A flip made after the start mode wins over the word at the next SessionStart."""
    data = _drive( monkeypatch, tmp_path, persona="Tiffany", chain="Cheech,maria,*",
                   role="author", voice_word=word, chorus=True, flip_to=flip )
    assert data[ "speakerphone_on" ] is flip


@pytest.mark.parametrize( "chorus,flip", [ ( True, False ), ( False, True ) ] )
def test_a_spawned_manager_flip_survives_a_context_reset( monkeypatch, tmp_path, chorus, flip ):
    data = _drive( monkeypatch, tmp_path, persona="maria", chain="Cheech,maria,*",
                   role="manager", voice_word="inherit", chorus=chorus, flip_to=flip )
    assert data[ "speakerphone_on" ] is flip

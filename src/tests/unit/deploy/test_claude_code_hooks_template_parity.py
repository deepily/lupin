"""
The hooks template carries every hook the fleet runs, and the merge refuses to lose one.

The installer replaced the whole `hooks` key of ~/.claude/settings.json with the repo template.
The template was behind a dev box, so a run deleted three live guard hooks and left only a backup.
These tests drive the helper on fixture files in a tmp folder. Nothing here reads or writes a real
settings file, and nothing runs the installer.
"""
import copy
import importlib.util
import json
import os
import re
import subprocess
import sys

import pytest

import cosa.utils.util as cu

ROOT      = cu.get_project_root()
TEMPLATE  = f"{ROOT}/src/conf/claude-code-hooks.json"
FLEET     = f"{ROOT}/src/tests/unit/deploy/fixtures/fleet_settings_hooks.json"
HELPER    = f"{ROOT}/src/scripts/lib/merge_cc_hooks.py"
INSTALLER = f"{ROOT}/src/scripts/install-cosa-voice.sh"

_spec  = importlib.util.spec_from_file_location( "merge_cc_hooks", HELPER )
helper = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( helper )


def _load( path ):
    with open( path, encoding="utf-8" ) as handle:
        return json.load( handle )


def _write( path, body ):
    path.write_text( json.dumps( body, indent=2 ) )
    return str( path )


@pytest.fixture
def fleet():
    return _load( FLEET )[ "hooks" ]


@pytest.fixture
def template():
    return _load( TEMPLATE )[ "hooks" ]


# ── parity: the template carries every hook the fleet runs ──────────────────

def test_every_fleet_hook_command_is_in_the_template( fleet, template ):
    """Kills the mutant that drops a guard from the template: the three that were missing."""
    assert helper.unknown_commands( fleet, template ) == { }


def test_the_three_guards_that_were_missing_are_in_the_template( template ):
    commands = helper.commands_by_event( template )
    joined   = "\n".join( c for cs in commands.values() for c in cs )
    for script in ( "worktree_creation_guard.py", "rnd_write_guard.py", "install_context_pressure_tick.py" ):
        assert script in joined, script
    assert any( "worktree_creation_guard.py" in c for c in commands[ "PreToolUse" ] )
    assert any( "rnd_write_guard.py" in c and "--mode pretooluse" in c for c in commands[ "PreToolUse" ] )
    assert any( "install_context_pressure_tick.py" in c for c in commands[ "SessionStart" ] )


def test_the_fleet_fixture_is_not_empty_and_covers_the_events_the_template_has( fleet, template ):
    """The comparison above means nothing over an empty fixture."""
    assert sum( len( v ) for v in helper.commands_by_event( fleet ).values() ) >= 10
    assert set( helper.commands_by_event( template ) ) <= set( helper.commands_by_event( fleet ) ) | { "SessionStart", "PreToolUse" }


def test_the_template_keeps_the_portable_interpreter_form_for_the_lupin_hooks( template ):
    lupin = [ c for cs in helper.commands_by_event( template ).values() for c in cs if "/src/lupin_cli/claude_code/hooks/" in c ]
    assert len( lupin ) >= 8 and all( c.startswith( '"${LUPIN_CC_VENV:-$LUPIN_ROOT/.venv}/bin/python3"' ) for c in lupin )


def test_the_host_only_allow_list_starts_empty():
    assert helper.HOST_ONLY_HOOKS == frozenset()


# ── normalising the interpreter prefix ──────────────────────────────────────

@pytest.mark.parametrize( "command", [
    '"$LUPIN_ROOT/.venv/bin/python3" "$LUPIN_ROOT/x.py"',
    '"${LUPIN_CC_VENV:-$LUPIN_ROOT/.venv}/bin/python3" "$LUPIN_ROOT/x.py"',
    'python3 "$LUPIN_ROOT/x.py"',
    '/usr/bin/python3 "$LUPIN_ROOT/x.py"',
] )
def test_interpreter_prefixes_normalise_to_one_command( command ):
    assert helper.normalise_command( command ) == '"$LUPIN_ROOT/x.py"'


def test_a_defaulted_variable_normalises_to_the_bare_variable():
    left  = helper.normalise_command( 'python3 "${PLANNING_IS_PROMPTING_ROOT:-/abs/path}/w/t.py"' )
    right = helper.normalise_command( '/usr/bin/python3 "$PLANNING_IS_PROMPTING_ROOT/w/t.py"' )
    assert left == right


def test_arguments_still_tell_two_commands_apart():
    assert helper.normalise_command( 'python3 "$R/g.py" --mode a' ) != helper.normalise_command( 'python3 "$R/g.py" --mode b' )


# ── the merge ───────────────────────────────────────────────────────────────

def test_an_unknown_command_refuses_and_leaves_the_file_byte_identical( tmp_path, template ):
    """Kills the mutant that overwrites in the refuse branch."""
    settings = { "model": "keep-me", "hooks": copy.deepcopy( template ) }
    settings[ "hooks" ][ "Stop" ].append( { "hooks": [ { "type": "command", "command": "python3 /opt/host-only-guard.py" } ] } )
    path   = _write( tmp_path / "settings.json", settings )
    before = open( path, "rb" ).read()
    code, message = helper.merge( path, TEMPLATE )
    assert code == helper.EXIT_REFUSED
    assert "Stop: python3 /opt/host-only-guard.py" in message
    assert open( path, "rb" ).read() == before
    assert not [ n for n in os.listdir( tmp_path ) if ".bak-" in n ], "a refusal must not leave a backup"


def test_every_unknown_command_is_named_under_its_event( tmp_path, template ):
    settings = { "hooks": copy.deepcopy( template ) }
    settings[ "hooks" ][ "Stop" ].append( { "hooks": [ { "type": "command", "command": "stop-extra" } ] } )
    settings[ "hooks" ][ "PreToolUse" ].append( { "hooks": [ { "type": "command", "command": "pre-extra" } ] } )
    code, message = helper.merge( _write( tmp_path / "s.json", settings ), TEMPLATE )
    assert code == helper.EXIT_REFUSED and "Stop: stop-extra" in message and "PreToolUse: pre-extra" in message


def test_a_known_command_moved_to_another_event_counts_as_unknown( tmp_path, template ):
    """Commands are compared per event, so a guard filed under the wrong event is not "known"."""
    stray = template[ "PreToolUse" ][ 0 ][ "hooks" ][ 0 ][ "command" ]
    settings = { "hooks": { "Stop": [ { "hooks": [ { "type": "command", "command": stray } ] } ] } }
    assert helper.unknown_commands( settings[ "hooks" ], template ) == { "Stop": [ stray ] }


def test_template_only_commands_merge_cleanly_and_keep_other_settings( tmp_path, template ):
    path = _write( tmp_path / "settings.json", { "model": "keep-me", "permissions": { "allow": [ "x" ] }, "hooks": { } } )
    code, message = helper.merge( path, TEMPLATE, now=lambda: 1234 )
    written = _load( path )
    assert code == helper.EXIT_WRITTEN and "installed" in message
    assert written[ "hooks" ] == template and written[ "model" ] == "keep-me" and written[ "permissions" ] == { "allow": [ "x" ] }
    assert os.path.exists( f"{path}.bak-1234" ), "the backup is made before the write"


def test_matching_sets_with_a_different_interpreter_prefix_pass_and_take_the_template_form( tmp_path, fleet, template ):
    path = _write( tmp_path / "settings.json", { "hooks": fleet } )
    code, _ = helper.merge( path, TEMPLATE )
    assert code == helper.EXIT_WRITTEN
    assert _load( path )[ "hooks" ] == template


def test_force_overwrites_after_the_backup_copy( tmp_path, template ):
    settings = { "hooks": { "Stop": [ { "hooks": [ { "type": "command", "command": "python3 /opt/host-only-guard.py" } ] } ] } }
    path   = _write( tmp_path / "settings.json", settings )
    before = open( path, "rb" ).read()
    code, _ = helper.merge( path, TEMPLATE, force=True, now=lambda: 77 )
    assert code == helper.EXIT_WRITTEN and _load( path )[ "hooks" ] == template
    assert open( f"{path}.bak-77", "rb" ).read() == before


def test_an_allow_listed_command_is_not_lost( tmp_path, template ):
    settings = { "hooks": copy.deepcopy( template ) }
    settings[ "hooks" ][ "Stop" ].append( { "hooks": [ { "type": "command", "command": "python3 /opt/host-only-guard.py" } ] } )
    path = _write( tmp_path / "settings.json", settings )
    code, _ = helper.merge( path, TEMPLATE, allow=frozenset( { "/opt/host-only-guard.py" } ) )
    assert code == helper.EXIT_WRITTEN


def test_a_missing_settings_file_is_written_fresh_with_no_backup( tmp_path, template ):
    path = str( tmp_path / "settings.json" )
    code, _ = helper.merge( path, TEMPLATE )
    assert code == helper.EXIT_WRITTEN and _load( path )[ "hooks" ] == template
    assert os.listdir( tmp_path ) == [ "settings.json" ]


@pytest.mark.parametrize( "body", [ "{not json", "[1, 2]", "" ] )
def test_unreadable_settings_are_left_alone_unless_forced( tmp_path, template, body ):
    path = tmp_path / "settings.json"
    path.write_text( body )
    code, message = helper.merge( str( path ), TEMPLATE )
    assert code == helper.EXIT_UNREADABLE and "--force" in message and path.read_text() == body
    code, _ = helper.merge( str( path ), TEMPLATE, force=True, now=lambda: 5 )
    assert code == helper.EXIT_WRITTEN and _load( str( path ) )[ "hooks" ] == template
    assert ( tmp_path / "settings.json.bak-5" ).read_text() == body


def test_a_hooks_key_that_is_not_a_dict_counts_as_nothing_to_lose( tmp_path, template ):
    path = _write( tmp_path / "settings.json", { "hooks": [ "stale" ] } )
    assert helper.merge( path, TEMPLATE )[ 0 ] == helper.EXIT_WRITTEN


def test_entries_that_are_not_hook_dicts_are_ignored():
    odd = { "Stop": [ "text", { "hooks": [ "text", { "type": "command" }, { "command": "ok" } ] }, { "no": "hooks" } ], "X": "not a list" }
    assert helper.commands_by_event( odd ) == { "Stop": [ "ok" ] }


# ── the command line ────────────────────────────────────────────────────────

def _cli( *args ):
    return subprocess.run( [ sys.executable, HELPER, *args ], capture_output=True, text=True, timeout=30 )


def test_cli_exit_codes_and_streams( tmp_path, template ):
    ok = _cli( _write( tmp_path / "a.json", { } ), TEMPLATE )
    assert ok.returncode == 0 and "installed" in ok.stdout and ok.stderr == ""
    refused_path = _write( tmp_path / "b.json", { "hooks": { "Stop": [ { "hooks": [ { "command": "extra" } ] } ] } } )
    refused = _cli( refused_path, TEMPLATE )
    assert refused.returncode == 3 and "Stop: extra" in refused.stderr and refused.stdout == ""
    forced = _cli( refused_path, TEMPLATE, "--force" )
    assert forced.returncode == 0
    assert _cli().returncode == 2 and _cli( "a", "b", "--nope" ).returncode == 2 and "usage" in _cli( "a" ).stderr


def test_main_in_process_returns_the_exit_codes_and_prints_to_the_right_stream( tmp_path, capsys ):
    assert helper.main( [ _write( tmp_path / "a.json", { } ), TEMPLATE ] ) == 0
    captured = capsys.readouterr()
    assert "installed" in captured.out and captured.err == ""
    refused = _write( tmp_path / "b.json", { "hooks": { "Stop": [ { "hooks": [ { "command": "extra" } ] } ] } } )
    assert helper.main( [ refused, TEMPLATE ] ) == 3
    captured = capsys.readouterr()
    assert "Stop: extra" in captured.err and captured.out == ""
    assert helper.main( [ refused, TEMPLATE, "--force" ] ) == 0
    capsys.readouterr()
    assert helper.main( [ "only-one" ] ) == 2 and helper.main( [ "a", "b", "--nope" ] ) == 2
    assert "usage" in capsys.readouterr().err


# ── the installer asks the helper instead of replacing the key ──────────────

def test_the_installer_no_longer_replaces_the_hooks_key_itself():
    text = open( INSTALLER, encoding="utf-8" ).read()
    assert "existing[ 'hooks' ] = tmpl" not in text
    assert "merge_cc_hooks.py" in text and "LUPIN_INSTALL_FORCE_HOOKS" in text


def test_the_installer_captures_the_helpers_exit_code_in_a_way_that_survives_set_e():
    text = open( INSTALLER, encoding="utf-8" ).read()
    assert re.search( r"^set -e", text, re.M )
    assert '"$HOOKS_MERGER" "$SETTINGS_FILE" "$HOOKS_TEMPLATE" $FORCE_HOOKS_ARG || HOOKS_RC=$?' in text


def test_the_installer_turns_a_refusal_into_a_warning_not_a_silent_pass():
    text = open( INSTALLER, encoding="utf-8" ).read()
    refusal = text[ text.index( 'elif [ "$HOOKS_RC" -eq 3 ]' ): ]
    assert refusal.split( "else", 1 )[ 0 ].count( "warn_check" ) == 1 and "REFUSED" in refusal.split( "else", 1 )[ 0 ]


def test_the_installer_still_parses():
    assert subprocess.run( [ "bash", "-n", INSTALLER ], capture_output=True ).returncode == 0

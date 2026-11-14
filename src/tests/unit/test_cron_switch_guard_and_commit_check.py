"""
Tests for the two controls on a hand edit of a scheduled-job switch.

The PreToolUse guard denies the tool call. The pre-commit check refuses the commit.
The guard is driven through the real hook `main()` with only I/O stubbed.
The commit check runs against a real temporary git repository with a staged file.
So the diff it reads is the one git produces.
"""
import contextlib
import json
import os
import subprocess

from unittest.mock import MagicMock, patch

import pytest

from lupin_cli.claude_code.hooks import pre_tool_use as ptu
from lupin_cli.claude_code.hooks.lib import cron_switch_commit_check as cc
from lupin_cli.claude_code.hooks.lib import cron_switch_guard as cg


MODULE = "lupin_cli.claude_code.hooks.pre_tool_use"
INI    = (
    "[main]\n"
    "some other key = 1\n"
    "cron job alpha enabled = true\n"
    "cron job beta enabled = false\n"
)


# ---------------------------------------------------------------- the guard, file tools

def _ini( tmp_path, text=INI ):
    """Write a lupin-app.ini and return its path."""
    path = tmp_path / "lupin-app.ini"
    path.write_text( text )
    ( tmp_path / "job-registry.json" ).write_text( json.dumps( { "jobs": [ { "job": j } for j in ( "alpha", "beta", "gamma" ) ] } ) )
    return str( path )


def test_edit_that_flips_a_switch_is_denied( tmp_path ):
    path   = _ini( tmp_path )
    reason = cg.cron_switch_deny_reason( "Edit", {
        "file_path": path, "old_string": "cron job alpha enabled = true", "new_string": "cron job alpha enabled = false" } )
    assert reason is not None and "alpha" in reason


def test_edit_of_another_key_is_allowed( tmp_path ):
    path = _ini( tmp_path )
    assert cg.cron_switch_deny_reason( "Edit", {
        "file_path": path, "old_string": "some other key = 1", "new_string": "some other key = 2" } ) is None


def test_edit_carrying_a_switch_line_as_context_is_allowed( tmp_path ):
    path = _ini( tmp_path )
    assert cg.cron_switch_deny_reason( "Edit", {
        "file_path": path,
        "old_string": "some other key = 1\ncron job alpha enabled = true",
        "new_string": "some other key = 2\ncron job alpha enabled = true" } ) is None


def test_multiedit_and_write_that_change_a_switch_are_denied( tmp_path ):
    path = _ini( tmp_path )
    multi = cg.cron_switch_deny_reason( "MultiEdit", { "file_path": path, "edits": [
        { "old_string": "some other key = 1", "new_string": "some other key = 3" },
        { "old_string": "cron job beta enabled = false", "new_string": "cron job beta enabled = true" } ] } )
    write = cg.cron_switch_deny_reason( "Write", { "file_path": path, "content": INI.replace( "alpha enabled = true", "alpha enabled = false" ) } )
    added = cg.cron_switch_deny_reason( "Write", { "file_path": path, "content": INI + "cron job zeta enabled = true\n" } )
    assert "beta" in multi and "alpha" in write and "zeta" in added


def test_edit_that_cannot_apply_or_file_that_cannot_be_read_is_judged_safely( tmp_path ):
    path = _ini( tmp_path )
    assert cg.cron_switch_deny_reason( "Edit", { "file_path": path, "old_string": "absent", "new_string": "x" } ) is None
    assert cg.cron_switch_deny_reason( "MultiEdit", { "file_path": path, "edits": "no" } ) is None
    assert cg.cron_switch_deny_reason( "MultiEdit", { "file_path": path, "edits": [ "no" ] } ) is None
    assert cg.cron_switch_deny_reason( "Write", { "file_path": path, "content": 5 } ) is None
    unreadable = str( tmp_path / "sub" / "lupin-app.ini" )
    os.makedirs( unreadable )                                   # a directory: open() raises OSError
    assert cg.cron_switch_deny_reason( "Edit", {
        "file_path": unreadable, "old_string": "cron job a enabled = true", "new_string": "cron job a enabled = false" } ) is not None
    assert cg.cron_switch_deny_reason( "MultiEdit", { "file_path": unreadable, "edits": [ "no", { "old_string": "x", "new_string": "y" } ] } ) is None
    assert cg.cron_switch_deny_reason( "Write", { "file_path": str( tmp_path / "new" / "lupin-app.ini" ), "content": "cron job a enabled = true\n" } ) is not None


def test_other_files_and_other_tools_are_ignored( tmp_path ):
    other = tmp_path / "notes.ini"
    other.write_text( INI )
    assert cg.cron_switch_deny_reason( "Edit", { "file_path": str( other ), "old_string": "true", "new_string": "false" } ) is None
    assert cg.cron_switch_deny_reason( "Read", { "file_path": _ini( tmp_path ) } ) is None
    assert cg.cron_switch_deny_reason( "Edit", "not a dict" ) is None
    assert cg.cron_switch_deny_reason( "Bash", { "command": "" } ) is None
    assert cg.cron_switch_deny_reason( "Bash", { "command": 5 } ) is None


def test_an_environment_flag_no_longer_allows_anything( tmp_path ):
    edit = { "file_path": _ini( tmp_path ), "old_string": "cron job alpha enabled = true", "new_string": "cron job alpha enabled = false" }
    with patch.dict( os.environ, { "LUPIN_ALLOW_CRON_SWITCH_EDIT": "1" } ):
        assert cg.cron_switch_deny_reason( "Edit", edit ) is not None
    assert not hasattr( cg, "DENY_HATCH" ) and not hasattr( cc, "HATCH_ENV" )


def test_a_call_that_touches_the_ini_fails_closed_and_any_other_call_fails_open( tmp_path ):
    edit = { "file_path": _ini( tmp_path ), "old_string": "some other key = 1", "new_string": "some other key = 2" }
    with patch.object( cg, "_file_tool_jobs", side_effect=RuntimeError( "boom" ) ):
        assert cg.DENY_UNJUDGED in cg.cron_switch_deny_reason( "Edit", edit )
        assert cg.cron_switch_deny_reason( "Edit", { **edit, "file_path": str( tmp_path / "notes.txt" ) } ) is None
    with patch.object( cg, "_bash_reason", side_effect=RuntimeError( "boom" ) ):
        assert cg.DENY_UNJUDGED in cg.cron_switch_deny_reason( "Bash", { "command": "cat src/conf/lupin-app.ini" } )
        assert cg.cron_switch_deny_reason( "Bash", { "command": "ls" } ) is None


def test_what_the_guard_touches_is_judged_without_raising():
    assert cg._touches_ini( "Edit", { "file_path": "/x/lupin-app.ini" } ) is True
    assert cg._touches_ini( "Bash", { "command": "cat lupin-app.ini" } ) is True
    assert cg._touches_ini( "Bash", { "command": "ls" } ) is False
    assert cg._touches_ini( "Read", { "file_path": "/x/lupin-app.ini" } ) is False
    assert cg._touches_ini( "Bash", "not a dict" ) is False
    assert cg._touches_ini( "Bash", { "command": 5 } ) is False


# ---------------------------------------------------------------- the guard, Bash

@pytest.mark.parametrize( "command", [
    "sed -i 's/true/false/' src/conf/lupin-app.ini",
    "echo 'cron job alpha enabled = false' >> src/conf/lupin-app.ini",
    "printf x | tee src/conf/lupin-app.ini",
    "cp /tmp/x src/conf/lupin-app.ini",
    "git checkout HEAD -- src/conf/lupin-app.ini",
    "rm src/conf/lupin-app.ini",
    "dd if=/tmp/x of=src/conf/lupin-app.ini",
    "awk -i inplace '{print}' src/conf/lupin-app.ini",
    "vim src/conf/lupin-app.ini",
    "bash -c \"sed -i s/a/b/ src/conf/lupin-app.ini\"",
] )
def test_a_shell_write_to_the_ini_is_denied( command ):
    assert cg.cron_switch_deny_reason( "Bash", { "command": command } ) is not None


@pytest.mark.parametrize( "command", [
    "python3 -c \"open('src/conf/lupin-app.ini','w').write('x')\"",
    "python3 -c \"from lupin_mcp.fleet_cap_ini_io import write_bool_to_disk; write_bool_to_disk('cron job a enabled', True)\"",
] )
def test_a_python_write_to_the_ini_or_a_switch_writer_is_denied( command ):
    assert cg.cron_switch_deny_reason( "Bash", { "command": command } ) is not None


@pytest.mark.parametrize( "command", [
    "cat src/conf/lupin-app.ini",
    "grep 'cron job' src/conf/lupin-app.ini",
    "git diff -- src/conf/lupin-app.ini",
    "git commit -m 'flip a line in lupin-app.ini'",
    "echo lupin-app.ini",
    "ls src/conf",
] )
def test_reading_or_naming_the_ini_is_allowed( command ):
    assert cg.cron_switch_deny_reason( "Bash", { "command": command } ) is None


def test_the_deny_envelope_has_the_hook_shape():
    out = cg.build_cron_switch_deny_response( "why" )
    assert out == { "hookSpecificOutput": { "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "why" } }


# ---------------------------------------------------------------- the guard, through the real hook

def _hook( payload ):
    """Drive the real main() with only I/O stubbed; return what was emitted."""
    emit = MagicMock()
    with contextlib.ExitStack() as stack:
        for name, kw in ( ( "read_hook_input", { "return_value": payload } ), ( "log_payload", {} ), ( "touch_bridge_mtime", {} ),
                          ( "resolve_stable_session_id", { "return_value": "s1" } ), ( "get_claude_session_id", { "return_value": "s1" } ),
                          ( "drain_and_acknowledge", { "return_value": [] } ), ( "format_voice_context", { "return_value": None } ) ):
            stack.enter_context( patch( f"{MODULE}.{name}", **kw ) )
        stack.enter_context( patch( f"{MODULE}.emit_json", emit ) )
        try:
            ptu.main()
        except SystemExit as exit_:
            assert exit_.code == 0
    return emit.call_args.args[ 0 ]


def test_the_real_hook_denies_a_planted_switch_edit( tmp_path ):
    path = _ini( tmp_path )
    out  = _hook( { "session_id": "s1", "tool_name": "Edit", "tool_input": {
        "file_path": path, "old_string": "cron job alpha enabled = true", "new_string": "cron job alpha enabled = false" } } )
    assert out[ "hookSpecificOutput" ][ "permissionDecision" ] == "deny"
    assert "alpha" in out[ "hookSpecificOutput" ][ "permissionDecisionReason" ]


def test_the_real_hook_does_not_deny_an_unrelated_edit( tmp_path ):
    path = _ini( tmp_path )
    out  = _hook( { "session_id": "s1", "tool_name": "Edit", "tool_input": {
        "file_path": path, "old_string": "some other key = 1", "new_string": "some other key = 2" } } )
    assert out.get( "hookSpecificOutput", {} ).get( "permissionDecision" ) != "deny"


# ---------------------------------------------------------------- the commit check, real git

def _git( root, *args ):
    subprocess.run( [ "git", "-C", str( root ), *args ], check=True, capture_output=True )


def _repo( tmp_path, ini=INI, registry=( "alpha", "beta", "gamma" ) ):
    """A repository with one commit holding the ini and the registry."""
    root = tmp_path / "repo"
    ( root / "src" / "conf" ).mkdir( parents=True )
    _git( root, "init", "-q" )
    _git( root, "config", "user.email", "t@example.invalid" )
    _git( root, "config", "user.name", "t" )
    ( root / "src" / "conf" / "lupin-app.ini" ).write_text( ini )
    ( root / "src" / "conf" / "job-registry.json" ).write_text( json.dumps( { "jobs": [ { "job": j } for j in registry ] } ) )
    _git( root, "add", "." )
    _git( root, "commit", "-q", "-m", "base" )
    return root


def _stage( root, text, registry=None ):
    ( root / "src" / "conf" / "lupin-app.ini" ).write_text( text )
    _git( root, "add", "src/conf/lupin-app.ini" )
    if registry is not None:
        ( root / "src" / "conf" / "job-registry.json" ).write_text( json.dumps( { "jobs": [ { "job": j } for j in registry ] } ) )
        _git( root, "add", "src/conf/job-registry.json" )


def _record( tmp_path, **jobs ):
    path = tmp_path / "state.json"
    path.write_text( json.dumps( { job: { "on": on, "at": "t", "by": "rick" } for job, on in jobs.items() } ) )
    return { cc.STATE_ENV: str( path ) }


def test_a_planted_hand_edit_is_refused_at_commit( tmp_path ):
    root = _repo( tmp_path )
    _stage( root, INI.replace( "alpha enabled = true", "alpha enabled = false" ) )
    code, message = cc.check( str( root ), env=_record( tmp_path ) )
    assert code == cc.EXIT_REFUSE and "alpha" in message and "no record" in message


def test_a_flip_the_endpoint_recorded_is_allowed( tmp_path ):
    root = _repo( tmp_path )
    _stage( root, INI.replace( "alpha enabled = true", "alpha enabled = false" ) )
    assert cc.check( str( root ), env=_record( tmp_path, alpha=False ) ) == ( cc.EXIT_ALLOW, "" )


def test_a_value_that_differs_from_the_record_is_refused( tmp_path ):
    root = _repo( tmp_path )
    _stage( root, INI.replace( "alpha enabled = true", "alpha enabled = false" ) )
    code, message = cc.check( str( root ), env=_record( tmp_path, alpha=True ) )
    assert code == cc.EXIT_REFUSE and "last flip" in message and "rick" in message


def test_removed_duplicated_and_junk_switches_are_refused( tmp_path ):
    root = _repo( tmp_path )
    for text, word in ( ( INI.replace( "cron job beta enabled = false\n", "" ), "removed" ),
                        ( INI + "cron job alpha enabled = true\n", "2 times" ),
                        ( INI.replace( "beta enabled = false", "beta enabled = maybe" ), "neither" ) ):
        _stage( root, text )
        code, message = cc.check( str( root ), env=_record( tmp_path ) )
        assert code == cc.EXIT_REFUSE and word in message


def test_a_commit_that_changes_no_switch_is_allowed( tmp_path ):
    root = _repo( tmp_path )
    _stage( root, INI.replace( "some other key = 1", "some other key = 2" ) )
    assert cc.check( str( root ), env=_record( tmp_path ) ) == ( cc.EXIT_ALLOW, "" )
    _git( root, "reset", "-q" )
    assert cc.check( str( root ), env=_record( tmp_path ) ) == ( cc.EXIT_ALLOW, "" )


def test_a_new_line_for_a_registry_job_is_allowed_once_and_an_unlisted_one_is_refused( tmp_path ):
    root = _repo( tmp_path )
    _stage( root, INI + "cron job gamma enabled = true\n" )
    assert cc.check( str( root ), env=_record( tmp_path ) ) == ( cc.EXIT_ALLOW, "" )
    _stage( root, INI + "cron job zeta enabled = true\n" )
    code, message = cc.check( str( root ), env=_record( tmp_path ) )
    assert code == cc.EXIT_REFUSE and "zeta" in message and "does not list" in message


def test_a_new_line_that_contradicts_the_record_or_has_no_registry_is_refused( tmp_path ):
    root = _repo( tmp_path )
    _stage( root, INI + "cron job gamma enabled = true\n" )
    code, message = cc.check( str( root ), env=_record( tmp_path, gamma=False ) )
    assert code == cc.EXIT_REFUSE and "record says" in message
    ( root / "src" / "conf" / "job-registry.json" ).write_text( "not json" )
    _git( root, "add", "src/conf/job-registry.json" )
    assert cc.registry_job_ids( str( root ) ) == { "alpha", "beta", "gamma" }      # unreadable as staged: HEAD's is used
    ( root / "src" / "conf" / "job-registry.json" ).write_text( "{}" )
    _git( root, "add", "src/conf/job-registry.json" )
    _git( root, "commit", "-q", "-m", "break the registry", "--", "src/conf/job-registry.json" )
    assert cc.registry_job_ids( str( root ) ) is None
    _stage( root, INI + "cron job gamma enabled = true\n" )
    code, message = cc.check( str( root ), env=_record( tmp_path ) )
    assert code == cc.EXIT_REFUSE and "does not list" in message


def test_no_flag_in_the_environment_lets_a_refused_change_through( tmp_path ):
    root = _repo( tmp_path )
    _stage( root, INI.replace( "alpha enabled = true", "alpha enabled = false" ) )
    env = { **_record( tmp_path ), "LUPIN_ALLOW_CRON_SWITCH_EDIT": "1" }
    code, message = cc.check( str( root ), env=env )
    assert code == cc.EXIT_REFUSE and "REFUSED" in message


def test_a_missing_or_broken_record_counts_as_empty( tmp_path ):
    assert cc.read_state( str( tmp_path / "nope.json" ) ) == {}
    bad = tmp_path / "bad.json"
    bad.write_text( "[1]" )
    assert cc.read_state( str( bad ) ) == {}
    bad.write_text( "{" )
    assert cc.read_state( str( bad ) ) == {}


def test_state_path_uses_the_override_else_the_config_lock_folder( tmp_path ):
    assert cc.state_path( { cc.STATE_ENV: "/x/y.json" } ) == "/x/y.json"
    assert cc.state_path( {} ).endswith( cc.STATE_FILENAME )


def test_main_exit_codes_and_the_loud_error_path( tmp_path, capsys ):
    root = _repo( tmp_path )
    _stage( root, INI.replace( "alpha enabled = true", "alpha enabled = false" ) )
    with patch.dict( os.environ, _record( tmp_path ) ):
        assert cc.main( [ "--repo-root", str( root ) ] ) == cc.EXIT_REFUSE
    assert "REFUSED" in capsys.readouterr().err
    assert cc.main( [ "--repo-root", str( tmp_path / "not-a-repo" ) ] ) == cc.EXIT_ALLOW
    assert "NOT enforced" in capsys.readouterr().err
    _git( root, "reset", "-q" )
    with patch.dict( os.environ, _record( tmp_path ) ):
        assert cc.main( [ "--repo-root", str( root ) ] ) == cc.EXIT_ALLOW


def test_the_pre_commit_chain_runs_the_gate_and_stops_on_a_refusal( tmp_path ):
    """The shipped chain script, in a real repo, with a planted hand edit staged."""
    root   = _repo( tmp_path )
    script = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts", "pre-commit-chain.sh" )
    for package in ( "lupin_cli", "lupin_mcp", "cosa" ):     # the chain runs python from the repo's own src
        os.symlink( os.path.join( os.environ[ "LUPIN_ROOT" ], "src", package ), str( root / "src" / package ) )
    _stage( root, INI.replace( "alpha enabled = true", "alpha enabled = false" ) )
    env = { **os.environ, **_record( tmp_path ), "LUPIN_ROOT": os.environ[ "LUPIN_ROOT" ] }
    env.pop( "PLANNING_IS_PROMPTING_ROOT", None )
    done = subprocess.run( [ "bash", script ], cwd=str( root ), env=env, capture_output=True, text=True )
    assert done.returncode == 1 and "[cron-switch-check] REFUSED" in done.stderr


# ---------------------------------------------------------------- the remaining branches

def test_a_python_heredoc_that_writes_the_ini_is_denied_and_a_harmless_one_is_not():
    write = "python3 <<'PY'\nopen( 'src/conf/lupin-app.ini', 'w' ).write( 'x' )\nPY"
    quiet = "python3 <<'PY'\nprint( 1 )\nPY"
    assert cg.DENY_PYTHON_WRITE in cg.cron_switch_deny_reason( "Bash", { "command": write } )
    assert cg.cron_switch_deny_reason( "Bash", { "command": quiet } ) is None


def test_nested_shells_are_scanned_to_a_depth_and_a_clean_one_passes():
    nested = "bash -c \"sed -i s/a/b/ src/conf/lupin-app.ini\""
    assert cg._bash_reason( "bash -c \"echo hi\"", 0 ) is None
    assert cg._bash_reason( nested, 0 ) == cg.DENY_BASH_WRITE
    assert cg._bash_reason( "bash -c \"echo hi\"", cg._MAX_DEPTH ) is None       # the depth cap: no further descent


def test_a_segment_with_no_program_has_nothing_to_judge():
    assert cg._segment_program( "" ) is None
    assert cg._segment_writes_ini( "lupin-app.ini", "" ) is False


def test_a_repo_without_a_registry_gives_none( tmp_path ):
    root = tmp_path / "bare"
    root.mkdir()
    _git( root, "init", "-q" )
    assert cc.registry_job_ids( str( root ) ) is None


# ---------------------------------------------------------------- adding a registry job's key

def _add( path, line ):
    return { "file_path": path, "old_string": "some other key = 1", "new_string": "some other key = 1\n" + line }


def test_adding_a_line_for_a_registry_job_is_allowed_through_every_tool( tmp_path ):
    path = _ini( tmp_path )
    assert cg.cron_switch_deny_reason( "Edit", _add( path, "cron job gamma enabled = true" ) ) is None
    assert cg.cron_switch_deny_reason( "MultiEdit", { "file_path": path, "edits": [ _add( path, "cron job gamma enabled = false" ) ] } ) is None
    assert cg.cron_switch_deny_reason( "Write", { "file_path": path, "content": INI + "cron job gamma enabled = true\n" } ) is None
    unreadable_dir = tmp_path / "x" / "lupin-app.ini"
    os.makedirs( unreadable_dir )                      # unreadable as a file: the call's own old and new text are compared
    ( tmp_path / "x" / "job-registry.json" ).write_text( json.dumps( { "jobs": [ { "job": "gamma" } ] } ) )
    assert cg.cron_switch_deny_reason( "Edit", _add( str( unreadable_dir ), "cron job gamma enabled = true" ) ) is None


def test_adding_an_unlisted_duplicate_or_junk_line_is_still_denied( tmp_path ):
    path = _ini( tmp_path )
    for line in ( "cron job zeta enabled = true", "cron job alpha enabled = true", "cron job gamma enabled = maybe",
                  "cron job gamma enabled = true\ncron job gamma enabled = false" ):
        assert cg.cron_switch_deny_reason( "Edit", _add( path, line ) ) is not None
    os.remove( tmp_path / "job-registry.json" )          # no registry beside the file: nothing may be added
    assert cg.cron_switch_deny_reason( "Edit", _add( path, "cron job gamma enabled = true" ) ) is not None
    ( tmp_path / "job-registry.json" ).write_text( "{" )
    assert cg.registry_jobs_beside( path ) is None


def test_changing_a_value_stays_denied_when_a_line_is_added_in_the_same_edit( tmp_path ):
    path = _ini( tmp_path )
    both = { "file_path": path, "old_string": "cron job alpha enabled = true", "new_string": "cron job alpha enabled = false\ncron job gamma enabled = true" }
    reason = cg.cron_switch_deny_reason( "Edit", both )
    assert reason is not None and "alpha" in reason and "gamma" not in reason.split( "\n" )[ 0 ]


def test_a_bash_append_of_one_registry_line_is_allowed_and_every_other_form_is_denied( tmp_path ):
    path = _ini( tmp_path )
    ok   = f"echo 'cron job gamma enabled = true' >> {path}"
    assert cg.cron_switch_deny_reason( "Bash", { "command": ok } ) is None
    assert cg.cron_switch_deny_reason( "Bash", { "command": f"printf \"cron job gamma enabled = false\" >> {path}" } ) is None
    for command in ( f"echo 'cron job zeta enabled = true' >> {path}",                       # not in the registry
                     f"echo 'cron job alpha enabled = false' >> {path}",                    # the job already has a line
                     f"echo 'cron job gamma enabled = maybe' >> {path}",                    # junk value
                     f"echo 'cron job gamma enabled = true' > {path}",                      # overwrite, not append
                     f"echo 'x = 1' >> {path}",                                             # not a switch line
                     f"echo 'cron job gamma enabled = true' >> {path} && sed -i s/a/b/ {path}",
                     f"echo 'cron job gamma enabled = true' >> {tmp_path}/nope/lupin-app.ini" ):
        assert cg.cron_switch_deny_reason( "Bash", { "command": command } ) is not None, command
    os.remove( tmp_path / "job-registry.json" )
    assert cg.cron_switch_deny_reason( "Bash", { "command": ok } ) is not None

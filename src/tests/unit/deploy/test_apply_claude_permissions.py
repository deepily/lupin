"""
Unit tests for src/scripts/apply_claude_permissions.py — the dev -> VM Claude permission merge.

Every behaviour that MATTERS here is one whose absence would be silent:
  - a non-portable rule shipping anyway ( the 96-dead-rules failure, 2026-08-04 )
  - the merge clobbering the VM's own hooks / env / model keys
  - --verify reporting green on a target that is actually missing rules

So each of those gets a CONTROL that must FAIL. A test that can only pass is decoration.
"""

import importlib.util
import json
import os

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
SCRIPT_PATH  = os.path.join( PROJECT_ROOT, "src/scripts/apply_claude_permissions.py" )


def _load_module():
    """
    Ensures:
        - returns the script imported as a module ( it lives outside any package )
    """
    spec = importlib.util.spec_from_file_location( "apply_claude_permissions", SCRIPT_PATH )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


acp = _load_module()


PORTABLE_STANZA = {
    "permissions": {
        "allow"       : [ "Bash", "Read", "Write" ],
        "deny"        : [ "Bash(rm -rf /)" ],
        "defaultMode" : "auto",
    }
}


def _write( path, doc ):
    with open( path, "w" ) as fh:
        json.dump( doc, fh, indent=2 )
    return str( path )


# ---------------------------------------------------------------- portability guard

def test_find_non_portable_flags_absolute_paths():
    rules = [ "Bash", "Read(/mnt/DATA01/x/**)", "Write(/home/rruiz/y)", "Grep" ]
    assert acp.find_non_portable( rules ) == [ "Read(/mnt/DATA01/x/**)", "Write(/home/rruiz/y)" ]


def test_find_non_portable_passes_a_clean_set():
    assert acp.find_non_portable( [ "Bash", "Read", "Bash(pytest:*)" ] ) == []


def test_load_stanza_accepts_a_portable_source( tmp_path ):
    src    = _write( tmp_path / "perms.json", PORTABLE_STANZA )
    stanza = acp.load_stanza( src )
    assert stanza[ "allow" ]       == [ "Bash", "Read", "Write" ]
    assert stanza[ "defaultMode" ] == "auto"


def test_load_stanza_REFUSES_a_non_portable_rule( tmp_path ):
    """CONTROL — this is the failure the guard exists for. It MUST raise."""
    doc = { "permissions": { "allow": [ "Bash", "Read(/mnt/DATA01/include/**)" ] } }
    src = _write( tmp_path / "bad.json", doc )

    with pytest.raises( ValueError ) as exc:
        acp.load_stanza( src )

    assert "/mnt/DATA01/include/**" in str( exc.value )   # names the OFFENDER, not just the count
    assert "cannot travel" in str( exc.value )


def test_load_stanza_refuses_a_source_with_no_permissions_object( tmp_path ):
    src = _write( tmp_path / "empty.json", { "model": "opus" } )
    with pytest.raises( ValueError, match="no 'permissions' object" ):
        acp.load_stanza( src )


def test_load_stanza_checks_deny_and_ask_too( tmp_path ):
    doc = { "permissions": { "allow": [ "Bash" ], "ask": [ "Read(/var/log/**)" ] } }
    src = _write( tmp_path / "bad-ask.json", doc )
    with pytest.raises( ValueError, match=r"/var/log" ):
        acp.load_stanza( src )


# ---------------------------------------------------------------- merge semantics

def test_merge_preserves_the_targets_own_rules():
    target = { "permissions": { "allow": [ "Bash(alembic upgrade:*)" ] } }
    merged, delta = acp.compute_merge( target, PORTABLE_STANZA[ "permissions" ] )

    assert merged[ "allow" ][ 0 ] == "Bash(alembic upgrade:*)"     # VM's own rule survives, first
    assert delta[ "added" ][ "allow" ] == [ "Bash", "Read", "Write" ]


def test_merge_is_idempotent():
    target = { "permissions": dict( PORTABLE_STANZA[ "permissions" ] ) }
    merged, delta = acp.compute_merge( target, PORTABLE_STANZA[ "permissions" ] )

    assert delta[ "added" ] == {}
    assert delta[ "mode" ] is None
    assert merged[ "allow" ] == [ "Bash", "Read", "Write" ]


def test_merge_sets_default_mode_and_reports_the_transition():
    target = { "permissions": { "allow": [] } }
    merged, delta = acp.compute_merge( target, PORTABLE_STANZA[ "permissions" ] )

    assert merged[ "defaultMode" ] == "auto"
    assert delta[ "mode" ] == ( None, "auto" )


def test_merge_leaves_default_mode_alone_when_the_stanza_omits_it():
    target = { "permissions": { "defaultMode": "plan" } }
    merged, delta = acp.compute_merge( target, { "allow": [ "Bash" ] } )

    assert merged[ "defaultMode" ] == "plan"
    assert delta[ "mode" ] is None


def test_apply_does_NOT_touch_the_targets_other_keys( tmp_path ):
    """CONTROL — a whole-file copy would clobber these. That was the rejected design."""
    machine_specific = {
        "hooks"     : { "SessionStart": [ { "command": "/vm/only/path.sh" } ] },
        "env"       : { "LUPIN_ROOT": "/mnt/lupin-data/lupin" },
        "model"     : "opusplan",
        "heartbeat" : { "owed_source_from_store": True },
    }
    target_doc = dict( machine_specific )
    target_doc[ "permissions" ] = { "allow": [ "Bash(docker compose:*)" ] }

    src = _write( tmp_path / "perms.json", PORTABLE_STANZA )
    tgt = _write( tmp_path / "settings.json", target_doc )

    assert acp.apply( src, tgt ) == 0

    after = json.load( open( tgt ) )
    for key, value in machine_specific.items():
        assert after[ key ] == value, f"{key} was modified — a merge must not clobber it"
    assert "Bash(docker compose:*)" in after[ "permissions" ][ "allow" ]
    assert "Bash" in after[ "permissions" ][ "allow" ]


def test_apply_adds_a_new_rule_without_disturbing_an_already_correct_default_mode( tmp_path ):
    """The steady state: mode was set on the first run, and a rule is added later."""
    src = _write( tmp_path / "perms.json", PORTABLE_STANZA )
    tgt = _write( tmp_path / "settings.json",
                  { "permissions": { "allow": [ "Bash", "Read" ], "deny": [ "Bash(rm -rf /)" ],
                                     "defaultMode": "auto" } } )     # "Write" absent, mode correct

    assert acp.apply( src, tgt ) == 0

    after = json.load( open( tgt ) )[ "permissions" ]
    assert "Write" in after[ "allow" ]
    assert after[ "defaultMode" ] == "auto"


def test_apply_writes_a_backup_before_changing_anything( tmp_path ):
    src = _write( tmp_path / "perms.json", PORTABLE_STANZA )
    tgt = _write( tmp_path / "settings.json", { "permissions": { "allow": [ "Grep" ] } } )
    original = open( tgt ).read()

    acp.apply( src, tgt )

    backups = [ p for p in os.listdir( tmp_path ) if p.startswith( "settings.json.bak-" ) ]
    assert len( backups ) == 1
    assert open( os.path.join( tmp_path, backups[ 0 ] ) ).read() == original


def test_apply_writes_no_backup_when_there_is_nothing_to_do( tmp_path ):
    src = _write( tmp_path / "perms.json", PORTABLE_STANZA )
    tgt = _write( tmp_path / "settings.json", PORTABLE_STANZA )

    assert acp.apply( src, tgt ) == 0
    assert [ p for p in os.listdir( tmp_path ) if ".bak-" in p ] == []


def test_dry_run_reports_the_delta_but_writes_nothing( tmp_path ):
    src    = _write( tmp_path / "perms.json", PORTABLE_STANZA )
    tgt    = _write( tmp_path / "settings.json", { "permissions": { "allow": [] } } )
    before = open( tgt ).read()

    assert acp.apply( src, tgt, dry_run=True ) == 0
    assert open( tgt ).read() == before
    assert [ p for p in os.listdir( tmp_path ) if ".bak-" in p ] == []


# ---------------------------------------------------------------- verify oracle

def test_verify_reports_IN_SYNC_when_the_target_carries_everything( tmp_path ):
    src = _write( tmp_path / "perms.json", PORTABLE_STANZA )
    tgt = _write( tmp_path / "settings.json", PORTABLE_STANZA )
    assert acp.apply( src, tgt, verify=True ) == 0


def test_verify_FAILS_on_a_target_missing_a_rule( tmp_path ):
    """CONTROL — if this can't fail, --verify is a rubber stamp in preflight."""
    src = _write( tmp_path / "perms.json", PORTABLE_STANZA )
    tgt = _write( tmp_path / "settings.json",
                  { "permissions": { "allow": [ "Bash", "Read" ], "deny": [ "Bash(rm -rf /)" ],
                                     "defaultMode": "auto" } } )     # "Write" absent

    assert acp.apply( src, tgt, verify=True ) == 1


def test_verify_FAILS_on_a_wrong_default_mode( tmp_path ):
    src = _write( tmp_path / "perms.json", PORTABLE_STANZA )
    tgt = _write( tmp_path / "settings.json",
                  { "permissions": { "allow": [ "Bash", "Read", "Write" ],
                                     "deny": [ "Bash(rm -rf /)" ], "defaultMode": "plan" } } )

    assert acp.apply( src, tgt, verify=True ) == 1


def test_missing_rules_names_each_gap():
    stanza = PORTABLE_STANZA[ "permissions" ]
    gaps   = acp.missing_rules( { "permissions": { "allow": [ "Bash" ] } }, stanza )

    assert "allow: Read"                 in gaps
    assert "allow: Write"                in gaps
    assert "deny: Bash(rm -rf /)"        in gaps
    assert any( g.startswith( "defaultMode:" ) for g in gaps )


# ---------------------------------------------------------------- path resolution

def test_default_source_path_reads_the_data_dir_env_var( monkeypatch ):
    monkeypatch.setenv( "DEEPILY_DATA_DIR", "/data/projects-data" )
    assert acp.default_source_path() == "/data/projects-data/claude-permissions.json"


def test_default_source_path_fails_loud_when_the_env_var_is_unset( monkeypatch ):
    """CONTROL — a silent fallback here would write the wrong machine's rules."""
    monkeypatch.delenv( "DEEPILY_DATA_DIR", raising=False )
    with pytest.raises( RuntimeError, match="DEEPILY_DATA_DIR is not set" ):
        acp.default_source_path()


def test_default_target_path_is_the_user_settings_file( monkeypatch, tmp_path ):
    monkeypatch.setenv( "HOME", str( tmp_path ) )
    assert acp.default_target_path() == os.path.join( str( tmp_path ), ".claude", "settings.json" )


# ---------------------------------------------------------------- CLI surface

def test_main_merges_via_explicit_flags( tmp_path ):
    src = _write( tmp_path / "perms.json", PORTABLE_STANZA )
    tgt = _write( tmp_path / "settings.json", { "permissions": { "allow": [] } } )

    assert acp.main( [ "--source", src, "--target", tgt ] ) == 0
    assert "Bash" in json.load( open( tgt ) )[ "permissions" ][ "allow" ]


def test_main_returns_2_on_a_non_portable_source( tmp_path, capsys ):
    doc = { "permissions": { "allow": [ "Read(/mnt/DATA01/**)" ] } }
    src = _write( tmp_path / "bad.json", doc )
    tgt = _write( tmp_path / "settings.json", { "permissions": {} } )

    assert acp.main( [ "--source", src, "--target", tgt ] ) == 2
    assert "/mnt/DATA01/**" in capsys.readouterr().err


def test_main_returns_2_on_a_missing_source( tmp_path ):
    tgt = _write( tmp_path / "settings.json", { "permissions": {} } )
    assert acp.main( [ "--source", str( tmp_path / "nope.json" ), "--target", tgt ] ) == 2


def test_main_returns_2_on_a_malformed_target( tmp_path ):
    """The dev box's settings.local.json was malformed for weeks — fail loud, not silent."""
    src = _write( tmp_path / "perms.json", PORTABLE_STANZA )
    tgt = tmp_path / "settings.json"
    tgt.write_text( '{ "permissions": { "allow": [ "Bash" ] }' )      # truncated on purpose

    assert acp.main( [ "--source", src, "--target", str( tgt ) ] ) == 2


def test_main_verify_flag_propagates( tmp_path ):
    src = _write( tmp_path / "perms.json", PORTABLE_STANZA )
    tgt = _write( tmp_path / "settings.json", { "permissions": { "allow": [] } } )
    assert acp.main( [ "--source", src, "--target", tgt, "--verify" ] ) == 1


def test_main_dry_run_flag_propagates( tmp_path ):
    src    = _write( tmp_path / "perms.json", PORTABLE_STANZA )
    tgt    = _write( tmp_path / "settings.json", { "permissions": { "allow": [] } } )
    before = open( tgt ).read()

    assert acp.main( [ "--source", src, "--target", tgt, "--dry-run" ] ) == 0
    assert open( tgt ).read() == before

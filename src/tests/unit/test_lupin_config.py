"""
Unit tests for src/scripts/lupin_config.py — the lupin-config CLI utility.

WHY THIS FILE EXISTS (row e2099400): src/scripts is entering the coverage frame, and
lupin_config.py was the largest file in it sitting at ZERO — 358 statements nothing
measured. These tests are the first half of that: real behaviour, not a coverage veneer.

⚠️ THE ISOLATION HAZARD, NAMED BECAUSE IT IS DESTRUCTIVE.
Every command in this module resolves its target through `Path.home()`, and `cmd_migrate`
does not merely READ the user's files — it RENAMES `~/.lupin/credentials.ini` and
`~/.notifications/config` to `.bak`. A test that ran it against the real home directory
would move the developer's live credentials out from under them.

The lever is `monkeypatch.setenv( "HOME", ... )`: on POSIX `Path.home()` resolves through
`os.path.expanduser`, which reads HOME, so the redirect is process-local and monkeypatch
restores it. Deliberately NOT `monkeypatch.setattr( Path, "home", ... )` — `Path` is a
SHARED class, and patching a method on it leaks into every other module in the process.

The `home` fixture is autouse, so a test cannot forget it and reach the real home by
omission — the failure mode has to be opted out of, not opted into.
"""

import os
import sys
import argparse
from configparser import ConfigParser
from pathlib import Path

import pytest


def _load_module():
    """Import lupin_config under its real name (src/scripts on path) so coverage can target it."""
    root        = os.environ[ "LUPIN_ROOT" ]
    scripts_dir = os.path.join( root, "src", "scripts" )
    if scripts_dir not in sys.path:
        sys.path.insert( 0, scripts_dir )
    import lupin_config
    return lupin_config


mod = _load_module()


# ── fixtures ─────────────────────────────────────────────────────────────────────

@pytest.fixture( autouse=True )
def home( tmp_path, monkeypatch ):
    """
    Redirect Path.home() into a temp dir for EVERY test in this file.

    Autouse on purpose: cmd_migrate renames real credential files, so reaching the
    developer's actual home must not be reachable by forgetting a fixture.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv( "HOME", str( fake_home ) )
    return fake_home


@pytest.fixture( autouse=True )
def no_ambient_env( monkeypatch ):
    """Clear the LUPIN_* overrides cmd_show reports, so a developer's shell cannot change a result."""
    for name in ( "LUPIN_ENV", "LUPIN_API_URL", "LUPIN_API_KEY_FILE", "LUPIN_API_KEY" ):
        monkeypatch.delenv( name, raising=False )


@pytest.fixture
def config_path( home ):
    """The path the module will compute — asserted equal, not assumed."""
    path = home / ".lupin" / "config"
    assert mod.get_config_path() == path
    return path


def _write_config( path, sections ):
    """Write an ini file from a dict-of-dicts, creating parents."""
    path.parent.mkdir( parents=True, exist_ok=True )
    config = ConfigParser()
    for name, values in sections.items():
        config[ name ] = values
    with open( path, "w" ) as f:
        config.write( f )
    return path


def _args( **kwargs ):
    """Build the argparse.Namespace the cmd_* functions expect."""
    return argparse.Namespace( **kwargs )


def _read( path ):
    config = ConfigParser()
    config.read( path )
    return config


# ── the isolation guard itself ───────────────────────────────────────────────────

def test_the_home_redirect_actually_moves_the_config_path_off_the_real_home():
    """
    The guard every other test leans on. If this fails, the suite is writing to the
    developer's real ~/.lupin and every result below is untrustworthy.
    """
    resolved = mod.get_config_path()
    assert resolved == Path( os.environ[ "HOME" ] ) / ".lupin" / "config"
    assert str( resolved ).startswith( os.environ[ "HOME" ] )
    assert ".lupin" in str( resolved )


# ── get_config_path / printers ───────────────────────────────────────────────────

def test_get_config_path_is_home_dot_lupin_config( home ):
    assert mod.get_config_path() == home / ".lupin" / "config"


def test_print_header_underlines_the_title( capsys ):
    mod.print_header( "Some Title" )
    out = capsys.readouterr().out
    assert "Some Title" in out
    assert "═" * 60 in out


def test_print_success_marks_the_line_with_a_check( capsys ):
    mod.print_success( "it worked" )
    assert "✓ it worked" in capsys.readouterr().out


def test_print_error_goes_to_stderr_not_stdout( capsys ):
    mod.print_error( "it broke" )
    captured = capsys.readouterr()
    assert "✗ it broke" in captured.err
    assert "it broke" not in captured.out


# ── cmd_init ─────────────────────────────────────────────────────────────────────

def test_init_creates_the_directory_and_a_config_with_three_sections( config_path, capsys ):
    assert not config_path.parent.exists()

    rc = mod.cmd_init( _args() )

    assert rc == 0
    assert config_path.exists()
    config = _read( config_path )
    assert set( config.sections() ) == { "lupin", "environments", "local" }
    assert config[ "environments" ][ "default" ] == "local"
    assert config[ "local" ][ "api_url" ] == "http://localhost:7999"
    assert "Created directory" in capsys.readouterr().out


def test_init_reuses_an_existing_directory_rather_than_recreating_it( config_path, capsys ):
    config_path.parent.mkdir( parents=True )

    rc = mod.cmd_init( _args() )

    assert rc == 0
    out = capsys.readouterr().out
    assert "Directory exists" in out
    assert "Created directory" not in out


def test_init_writes_the_config_mode_600_because_it_holds_a_password( config_path ):
    mod.cmd_init( _args() )
    assert ( config_path.stat().st_mode & 0o777 ) == 0o600


def test_init_is_idempotent_and_does_not_overwrite_an_existing_config( config_path, capsys ):
    _write_config( config_path, { "environments": { "default": "production" } } )

    rc = mod.cmd_init( _args() )

    assert rc == 0
    assert "already initialized" in capsys.readouterr().out
    # the pre-existing content survived — this is the point of the early return
    assert _read( config_path )[ "environments" ][ "default" ] == "production"


def test_init_reports_failure_when_the_file_cannot_be_finalized( config_path, monkeypatch, capsys ):
    """chmod sits inside cmd_init's try — a failure there must return 1, not raise."""
    def boom( *args, **kwargs ):
        raise OSError( "permission denied" )

    monkeypatch.setattr( mod.os, "chmod", boom )

    rc = mod.cmd_init( _args() )

    assert rc == 1
    assert "Failed to create config file" in capsys.readouterr().err


# ── cmd_show ─────────────────────────────────────────────────────────────────────

def _stub_api_config( monkeypatch, api_url="http://localhost:7999", api_key_file="/tmp/key" ):
    monkeypatch.setattr(
        mod, "get_api_config",
        lambda env=None: { "api_url": api_url, "api_key_file": api_key_file }
    )


def test_show_returns_1_when_no_config_file_exists( config_path, capsys ):
    rc = mod.cmd_show( _args() )

    assert rc == 1
    assert "No configuration file found" in capsys.readouterr().out


def test_show_reports_the_default_environment_when_lupin_env_is_unset( config_path, monkeypatch, capsys ):
    _write_config( config_path, {
        "environments": { "default": "staging" },
        "staging"     : { "api_url": "http://staging", "description": "the staging box" },
    } )
    _stub_api_config( monkeypatch )

    rc = mod.cmd_show( _args() )

    out = capsys.readouterr().out
    assert rc == 0
    assert "Active Environment: staging (using default)" in out
    assert "Description: the staging box" in out


def test_show_reports_lupin_env_as_the_override_when_it_is_set( config_path, monkeypatch, capsys ):
    _write_config( config_path, {
        "environments": { "default": "staging" },
        "staging"     : { "api_url": "http://staging" },
    } )
    _stub_api_config( monkeypatch )
    monkeypatch.setenv( "LUPIN_ENV", "production" )

    rc = mod.cmd_show( _args() )

    assert rc == 0
    assert "Active Environment: production (via LUPIN_ENV)" in capsys.readouterr().out


def test_show_omits_the_description_line_when_the_section_has_none( config_path, monkeypatch, capsys ):
    _write_config( config_path, {
        "environments": { "default": "bare" },
        "bare"        : { "api_url": "http://bare" },
    } )
    _stub_api_config( monkeypatch )

    rc = mod.cmd_show( _args() )

    assert rc == 0
    assert "Description:" not in capsys.readouterr().out


def test_show_tolerates_an_active_environment_with_no_section_of_its_own( config_path, monkeypatch, capsys ):
    """LUPIN_ENV can name an environment the file does not define — that must not crash."""
    _write_config( config_path, { "environments": { "default": "local" } } )
    _stub_api_config( monkeypatch )
    monkeypatch.setenv( "LUPIN_ENV", "nowhere" )

    rc = mod.cmd_show( _args() )

    assert rc == 0
    assert "Active Environment: nowhere" in capsys.readouterr().out


def test_show_returns_1_when_the_config_cannot_be_loaded( config_path, monkeypatch, capsys ):
    _write_config( config_path, { "environments": { "default": "local" } } )

    def boom( env=None ):
        raise RuntimeError( "no such environment" )

    monkeypatch.setattr( mod, "get_api_config", boom )

    rc = mod.cmd_show( _args() )

    assert rc == 1
    assert "Failed to load configuration" in capsys.readouterr().err


def test_show_lists_credential_sections_and_whether_a_password_is_set( config_path, monkeypatch, capsys ):
    _write_config( config_path, {
        "environments": { "default": "local" },
        "lupin"       : { "email": "a@b.c", "password": "secret" },
        "other"       : { "email": "d@e.f", "password": "" },
    } )
    _stub_api_config( monkeypatch )

    rc = mod.cmd_show( _args() )

    out = capsys.readouterr().out
    assert rc == 0
    assert "[lupin] email=a@b.c  password=set" in out
    assert "[other] email=d@e.f  password=MISSING" in out


def test_show_points_at_the_legacy_file_when_no_credentials_are_in_the_unified_config( config_path, home, monkeypatch, capsys ):
    _write_config( config_path, { "environments": { "default": "local" } } )
    ( home / ".lupin" / "credentials.ini" ).write_text( "[lupin]\nemail = legacy@x.y\n" )
    _stub_api_config( monkeypatch )

    rc = mod.cmd_show( _args() )

    out = capsys.readouterr().out
    assert rc == 0
    assert "Legacy file exists" in out
    assert "migrate" in out


def test_show_says_none_configured_when_there_are_no_credentials_anywhere( config_path, monkeypatch, capsys ):
    _write_config( config_path, { "environments": { "default": "local" } } )
    _stub_api_config( monkeypatch )

    rc = mod.cmd_show( _args() )

    assert rc == 0
    assert "(none configured)" in capsys.readouterr().out


def test_show_reports_env_overrides_as_not_set_when_absent( config_path, monkeypatch, capsys ):
    _write_config( config_path, { "environments": { "default": "local" } } )
    _stub_api_config( monkeypatch )

    rc = mod.cmd_show( _args() )

    out = capsys.readouterr().out
    assert rc == 0
    assert "LUPIN_API_URL: (not set)" in out
    assert "LUPIN_API_KEY: (not set)" in out


def test_show_masks_the_api_key_to_its_last_eight_characters( config_path, monkeypatch, capsys ):
    """The key is a live secret — show must never print it whole."""
    _write_config( config_path, { "environments": { "default": "local" } } )
    _stub_api_config( monkeypatch )
    monkeypatch.setenv( "LUPIN_API_KEY", "ck_live_SUPERSECRETMIDDLE_TAIL1234" )

    rc = mod.cmd_show( _args() )

    out = capsys.readouterr().out
    assert rc == 0
    assert "LUPIN_API_KEY: ck_live_...TAIL1234" in out
    assert "SUPERSECRETMIDDLE" not in out


# ── cmd_list ─────────────────────────────────────────────────────────────────────

def test_list_returns_1_when_no_config_file_exists( config_path, capsys ):
    rc = mod.cmd_list( _args() )

    assert rc == 1
    assert "No configuration file found" in capsys.readouterr().err


def test_list_marks_the_default_environment_with_a_star( config_path, capsys ):
    _write_config( config_path, {
        "environments": { "default": "production" },
        "local"       : { "api_url": "http://localhost:7999", "description": "dev box" },
        "production"  : { "api_url": "https://prod" },
    } )

    rc = mod.cmd_list( _args() )

    out = capsys.readouterr().out
    assert rc == 0
    assert " * production (default)" in out
    assert "   local" in out
    assert "Description: dev box" in out


def test_list_falls_back_to_N_A_when_an_environment_has_no_url( config_path, capsys ):
    _write_config( config_path, {
        "environments": { "default": "local" },
        "local"       : { "description": "no url here" },
    } )

    rc = mod.cmd_list( _args() )

    assert rc == 0
    assert "URL: N/A" in capsys.readouterr().out


def test_list_returns_1_when_the_file_defines_no_environments( config_path, capsys ):
    _write_config( config_path, { "environments": { "default": "local" } } )

    rc = mod.cmd_list( _args() )

    assert rc == 1
    assert "No environments configured" in capsys.readouterr().out


def test_list_returns_1_when_the_config_file_is_unparseable( config_path, capsys ):
    config_path.parent.mkdir( parents=True, exist_ok=True )
    config_path.write_text( "this is not an ini file\n[[[\n" )

    rc = mod.cmd_list( _args() )

    assert rc == 1
    assert "Failed to read configuration" in capsys.readouterr().err


# ── cmd_add ──────────────────────────────────────────────────────────────────────

def test_add_returns_1_when_no_config_file_exists( config_path, capsys ):
    rc = mod.cmd_add( _args( environment="staging", url=None, key_file=None, description=None ) )

    assert rc == 1
    assert "No configuration file found" in capsys.readouterr().err


def test_add_refuses_to_clobber_an_environment_that_already_exists( config_path, capsys ):
    _write_config( config_path, {
        "environments": { "default": "local" },
        "staging"     : { "api_url": "http://old" },
    } )

    rc = mod.cmd_add( _args( environment="staging", url="http://new", key_file="/k", description=None ) )

    assert rc == 1
    assert "already exists" in capsys.readouterr().err
    # the original survived — refusing means NOT writing
    assert _read( config_path )[ "staging" ][ "api_url" ] == "http://old"


def test_add_writes_the_new_environment_from_flags_without_prompting( config_path ):
    _write_config( config_path, { "environments": { "default": "local" } } )

    rc = mod.cmd_add( _args(
        environment="staging", url="https://staging.example.com",
        key_file="/keys/staging", description="the staging box"
    ) )

    assert rc == 0
    config = _read( config_path )
    assert config[ "staging" ][ "api_url" ]      == "https://staging.example.com"
    assert config[ "staging" ][ "api_key_file" ] == "/keys/staging"
    assert config[ "staging" ][ "description" ]  == "the staging box"


def test_add_omits_the_description_key_when_none_is_given( config_path ):
    _write_config( config_path, { "environments": { "default": "local" } } )

    rc = mod.cmd_add( _args( environment="staging", url="https://s", key_file="/k", description=None ) )

    assert rc == 0
    assert "description" not in _read( config_path )[ "staging" ]


def test_add_prompts_interactively_when_the_flags_are_incomplete( config_path, monkeypatch ):
    """url without key_file must fall through to prompting, not write a half-built section."""
    _write_config( config_path, { "environments": { "default": "local" } } )
    answers = iter( [ "https://typed.example.com", "/keys/typed", "typed in" ] )
    monkeypatch.setattr( "builtins.input", lambda prompt="": next( answers ) )

    rc = mod.cmd_add( _args( environment="staging", url="https://flag", key_file=None, description=None ) )

    assert rc == 0
    config = _read( config_path )
    assert config[ "staging" ][ "api_url" ]     == "https://typed.example.com"
    assert config[ "staging" ][ "description" ] == "typed in"


def test_add_rejects_a_url_that_is_not_http_or_https( config_path, capsys ):
    _write_config( config_path, { "environments": { "default": "local" } } )

    rc = mod.cmd_add( _args( environment="staging", url="ftp://nope", key_file="/k", description=None ) )

    assert rc == 1
    assert "Invalid URL format" in capsys.readouterr().err
    assert "staging" not in _read( config_path )


def test_add_returns_1_when_the_config_file_is_unparseable( config_path, capsys ):
    config_path.parent.mkdir( parents=True, exist_ok=True )
    config_path.write_text( "[[[ not ini\n" )

    rc = mod.cmd_add( _args( environment="staging", url="https://s", key_file="/k", description=None ) )

    assert rc == 1
    assert "Failed to add environment" in capsys.readouterr().err


# ── cmd_use ──────────────────────────────────────────────────────────────────────

def test_use_returns_1_when_no_config_file_exists( config_path, capsys ):
    rc = mod.cmd_use( _args( environment="staging" ) )

    assert rc == 1
    assert "No configuration file found" in capsys.readouterr().err


def test_use_switches_the_default_environment( config_path ):
    _write_config( config_path, {
        "environments": { "default": "local" },
        "local"       : { "api_url": "http://localhost:7999" },
        "production"  : { "api_url": "https://prod" },
    } )

    rc = mod.cmd_use( _args( environment="production" ) )

    assert rc == 0
    assert _read( config_path )[ "environments" ][ "default" ] == "production"


def test_use_lists_the_real_environments_when_the_target_is_unknown( config_path, capsys ):
    _write_config( config_path, {
        "environments": { "default": "local" },
        "local"       : { "api_url": "http://localhost:7999" },
    } )

    rc = mod.cmd_use( _args( environment="nope" ) )

    out = capsys.readouterr().out
    assert rc == 1
    assert "- local" in out
    # the bookkeeping section is not an environment and must not be offered as one
    assert "- environments" not in out
    assert _read( config_path )[ "environments" ][ "default" ] == "local"


def test_use_returns_1_when_the_config_file_is_unparseable( config_path, capsys ):
    config_path.parent.mkdir( parents=True, exist_ok=True )
    config_path.write_text( "[[[ not ini\n" )

    rc = mod.cmd_use( _args( environment="staging" ) )

    assert rc == 1
    assert "Failed to change environment" in capsys.readouterr().err


# ── cmd_test ─────────────────────────────────────────────────────────────────────

def test_test_returns_1_when_no_config_file_exists( config_path, capsys ):
    rc = mod.cmd_test( _args( environment="local" ) )

    assert rc == 1
    assert "Config file not found" in capsys.readouterr().err


def test_test_returns_1_when_the_environment_is_not_in_the_file( config_path, capsys ):
    _write_config( config_path, {
        "environments": { "default": "local" },
        "local"       : { "api_url": "http://localhost:7999" },
    } )

    rc = mod.cmd_test( _args( environment="ghost" ) )

    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_test_returns_1_when_the_api_key_file_is_missing( config_path, tmp_path, monkeypatch, capsys ):
    _write_config( config_path, {
        "environments": { "default": "local" },
        "local"       : { "api_url": "http://localhost:7999" },
    } )
    _stub_api_config( monkeypatch, api_key_file=str( tmp_path / "absent-key" ) )

    rc = mod.cmd_test( _args( environment="local" ) )

    assert rc == 1
    assert "API Key file not found" in capsys.readouterr().err


def test_test_returns_1_when_the_configuration_fails_validation( config_path, tmp_path, monkeypatch, capsys ):
    _write_config( config_path, {
        "environments": { "default": "local" },
        "local"       : { "api_url": "http://localhost:7999" },
    } )
    key_file = tmp_path / "key"
    key_file.write_text( "ck_live_abc" )
    _stub_api_config( monkeypatch, api_key_file=str( key_file ) )

    def invalid( api_config ):
        raise ValueError( "api_url is not absolute" )

    monkeypatch.setattr( mod, "validate_api_config", invalid )

    rc = mod.cmd_test( _args( environment="local" ) )

    assert rc == 1
    assert "Configuration validation failed" in capsys.readouterr().err


def test_test_passes_when_the_environment_key_file_and_validation_all_hold( config_path, tmp_path, monkeypatch, capsys ):
    _write_config( config_path, {
        "environments": { "default": "local" },
        "local"       : { "api_url": "http://localhost:7999" },
    } )
    key_file = tmp_path / "key"
    key_file.write_text( "ck_live_abc" )
    _stub_api_config( monkeypatch, api_key_file=str( key_file ) )
    monkeypatch.setattr( mod, "validate_api_config", lambda api_config: None )

    rc = mod.cmd_test( _args( environment="local" ) )

    out = capsys.readouterr().out
    assert rc == 0
    assert "Configuration tests passed" in out
    # the two unimplemented phases must still SAY they were skipped rather than imply a pass
    assert "Network test not implemented" in out
    assert "Authentication test not implemented" in out


def test_test_returns_1_when_loading_the_environment_raises( config_path, monkeypatch, capsys ):
    _write_config( config_path, {
        "environments": { "default": "local" },
        "local"       : { "api_url": "http://localhost:7999" },
    } )

    def boom( env=None ):
        raise RuntimeError( "config loader exploded" )

    monkeypatch.setattr( mod, "get_api_config", boom )

    rc = mod.cmd_test( _args( environment="local" ) )

    assert rc == 1
    assert "Configuration error" in capsys.readouterr().err


# ── cmd_migrate ──────────────────────────────────────────────────────────────────

def test_migrate_reports_nothing_to_do_when_no_legacy_files_exist( config_path, capsys ):
    rc = mod.cmd_migrate( _args() )

    assert rc == 0
    out = capsys.readouterr().out
    assert "Nothing to migrate" in out
    assert "No legacy credentials file" in out
    assert "No legacy notifications config" in out
    assert not config_path.exists()


def test_migrate_folds_legacy_credentials_into_the_unified_config( config_path, home, capsys ):
    legacy = home / ".lupin" / "credentials.ini"
    legacy.parent.mkdir( parents=True )
    legacy.write_text( "[lupin]\nemail = a@b.c\npassword = pw\n" )

    rc = mod.cmd_migrate( _args() )

    assert rc == 0
    config = _read( config_path )
    assert config[ "lupin" ][ "email" ]    == "a@b.c"
    assert config[ "lupin" ][ "password" ] == "pw"


def test_migrate_folds_legacy_notification_environments_in_too( config_path, home ):
    legacy = home / ".notifications" / "config"
    legacy.parent.mkdir( parents=True )
    legacy.write_text( "[production]\napi_url = https://prod\n" )

    rc = mod.cmd_migrate( _args() )

    assert rc == 0
    assert _read( config_path )[ "production" ][ "api_url" ] == "https://prod"


def test_migrate_never_overwrites_a_section_the_unified_config_already_has( config_path, home, capsys ):
    """The unified file is authoritative — migration adds, it does not clobber."""
    _write_config( config_path, {
        "environments": { "default": "local" },
        "lupin"       : { "email": "current@x.y", "password": "keep-me" },
    } )
    legacy = home / ".lupin" / "credentials.ini"
    legacy.write_text( "[lupin]\nemail = stale@x.y\npassword = overwrite-me\n" )
    notif = home / ".notifications" / "config"
    notif.parent.mkdir( parents=True )
    notif.write_text( "[environments]\ndefault = production\n" )

    rc = mod.cmd_migrate( _args() )

    assert rc == 0
    out = capsys.readouterr().out
    assert "already exists in unified config — skipping" in out
    config = _read( config_path )
    assert config[ "lupin" ][ "email" ]          == "current@x.y"
    assert config[ "environments" ][ "default" ] == "local"


def test_migrate_backs_up_both_legacy_files_and_chmods_the_result( config_path, home ):
    creds = home / ".lupin" / "credentials.ini"
    creds.parent.mkdir( parents=True )
    creds.write_text( "[lupin]\nemail = a@b.c\n" )
    notif = home / ".notifications" / "config"
    notif.parent.mkdir( parents=True )
    notif.write_text( "[production]\napi_url = https://prod\n" )

    rc = mod.cmd_migrate( _args() )

    assert rc == 0
    assert not creds.exists()
    assert not notif.exists()
    assert ( home / ".lupin" / "credentials.ini.bak" ).exists()
    assert ( home / ".notifications" / "config.bak" ).exists()
    assert ( config_path.stat().st_mode & 0o777 ) == 0o600


def test_migrate_returns_1_when_the_unified_config_cannot_be_finalized( config_path, home, monkeypatch, capsys ):
    creds = home / ".lupin" / "credentials.ini"
    creds.parent.mkdir( parents=True )
    creds.write_text( "[lupin]\nemail = a@b.c\n" )

    def boom( *args, **kwargs ):
        raise OSError( "read-only filesystem" )

    monkeypatch.setattr( mod.os, "chmod", boom )

    rc = mod.cmd_migrate( _args() )

    assert rc == 1
    assert "Failed to write unified config" in capsys.readouterr().err
    # the legacy file must still be there — a failed write must not have moved it
    assert creds.exists()


def test_migrate_reports_a_backup_failure_without_losing_the_migrated_config( config_path, home, capsys ):
    """
    A .bak path already occupied by a NON-EMPTY DIRECTORY makes rename fail for real —
    no patching, just the filesystem's own behaviour.
    """
    creds = home / ".lupin" / "credentials.ini"
    creds.parent.mkdir( parents=True )
    creds.write_text( "[lupin]\nemail = a@b.c\n" )
    blocker = home / ".lupin" / "credentials.ini.bak"
    blocker.mkdir()
    ( blocker / "occupant" ).write_text( "in the way" )

    rc = mod.cmd_migrate( _args() )

    assert rc == 0
    assert "Failed to backup" in capsys.readouterr().err
    # the migration itself still landed
    assert _read( config_path )[ "lupin" ][ "email" ] == "a@b.c"


def test_migrate_starts_from_the_existing_unified_config_when_one_is_present( config_path, home, capsys ):
    _write_config( config_path, { "environments": { "default": "staging" } } )
    creds = home / ".lupin" / "credentials.ini"
    creds.write_text( "[lupin]\nemail = a@b.c\n" )

    rc = mod.cmd_migrate( _args() )

    assert rc == 0
    assert "Existing config loaded" in capsys.readouterr().out
    config = _read( config_path )
    assert config[ "environments" ][ "default" ] == "staging"
    assert config[ "lupin" ][ "email" ]          == "a@b.c"


# ── main ─────────────────────────────────────────────────────────────────────────

def test_main_prints_help_and_returns_1_when_given_no_command( monkeypatch, capsys ):
    monkeypatch.setattr( sys, "argv", [ "lupin-config" ] )

    rc = mod.main()

    assert rc == 1
    assert "Available commands" in capsys.readouterr().out


@pytest.mark.parametrize( "argv, handler", [
    ( [ "lupin-config", "init" ],            "cmd_init" ),
    ( [ "lupin-config", "show" ],            "cmd_show" ),
    ( [ "lupin-config", "list" ],            "cmd_list" ),
    ( [ "lupin-config", "add", "staging" ],  "cmd_add" ),
    ( [ "lupin-config", "use", "staging" ],  "cmd_use" ),
    ( [ "lupin-config", "test", "staging" ], "cmd_test" ),
    ( [ "lupin-config", "migrate" ],         "cmd_migrate" ),
] )
def test_main_dispatches_each_subcommand_to_its_own_handler( argv, handler, monkeypatch ):
    """Every subcommand must reach its OWN function — a mis-wired set_defaults is silent otherwise."""
    called = []
    monkeypatch.setattr( mod, handler, lambda args: called.append( handler ) or 0 )
    monkeypatch.setattr( sys, "argv", argv )

    rc = mod.main()

    assert rc == 0
    assert called == [ handler ]


def test_main_passes_the_parsed_arguments_through_to_the_handler( monkeypatch ):
    seen = {}

    def capture( args ):
        seen[ "environment" ] = args.environment
        seen[ "url" ]         = args.url
        return 0

    monkeypatch.setattr( mod, "cmd_add", capture )
    monkeypatch.setattr( sys, "argv", [ "lupin-config", "add", "staging", "--url", "https://s" ] )

    assert mod.main() == 0
    assert seen == { "environment": "staging", "url": "https://s" }


def test_main_returns_the_handlers_own_exit_code( monkeypatch ):
    monkeypatch.setattr( mod, "cmd_show", lambda args: 1 )
    monkeypatch.setattr( sys, "argv", [ "lupin-config", "show" ] )

    assert mod.main() == 1


def test_main_converts_an_unexpected_handler_crash_into_exit_code_1( monkeypatch, capsys ):
    def boom( args ):
        raise RuntimeError( "handler exploded" )

    monkeypatch.setattr( mod, "cmd_show", boom )
    monkeypatch.setattr( sys, "argv", [ "lupin-config", "show" ] )

    rc = mod.main()

    captured = capsys.readouterr()
    assert rc == 1
    assert "Unexpected error" in captured.err
    assert "handler exploded" in captured.err


# ── the import-time bootstrap ────────────────────────────────────────────────────
#
# Lines 30-40 run ONCE, at import, before any test exists — so no ordinary test can
# reach the LUPIN_ROOT-missing arm or the sys.path insert. They are re-executed here
# from source under controlled conditions, which is the only honest way to cover an
# import-time guard: the alternative is a pragma that asserts nothing.

def _exec_bootstrap( namespace_name="lupin_config_bootstrap_probe" ):
    """
    Re-execute the module's own source, compiled under its REAL filename so coverage
    attributes the lines to the file rather than to a synthetic one.
    """
    # Resolved from the ALREADY-IMPORTED module, never from LUPIN_ROOT — these tests
    # manipulate that variable, so reading the path from it would point the probe at a
    # directory the test just invented.
    source_path = Path( mod.__file__ )
    code        = compile( source_path.read_text(), str( source_path ), "exec" )
    namespace   = { "__name__": namespace_name, "__file__": str( source_path ) }
    exec( code, namespace )
    return namespace


def test_the_bootstrap_exits_1_when_lupin_root_is_not_set( monkeypatch, capsys ):
    """
    A standalone `lupin-config` run with no LUPIN_ROOT must die immediately with a
    usable message, not stumble on to a TypeError inside os.path.join( None, 'src' ).
    """
    root = os.environ[ "LUPIN_ROOT" ]
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )

    with pytest.raises( SystemExit ) as exit_info:
        _exec_bootstrap()

    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "LUPIN_ROOT environment variable not set" in err
    assert "export LUPIN_ROOT=" in err
    # the probe must not have leaked the variable back
    assert os.environ.get( "LUPIN_ROOT" ) is None
    monkeypatch.setenv( "LUPIN_ROOT", root )


def test_the_bootstrap_puts_src_on_sys_path_when_it_is_absent( monkeypatch, tmp_path ):
    """
    The insert arm never runs under pytest because conftest has already put src on the
    path. Pointing LUPIN_ROOT at a directory whose src is NOT on the path exercises it.
    """
    fake_root = tmp_path / "fake-root"
    ( fake_root / "src" ).mkdir( parents=True )
    expected  = os.path.join( str( fake_root ), "src" )

    original_path = list( sys.path )
    assert expected not in sys.path
    try:
        monkeypatch.setenv( "LUPIN_ROOT", str( fake_root ) )
        _exec_bootstrap()
        assert sys.path[ 0 ] == expected, "the bootstrap must insert at position 0, not append"
    finally:
        sys.path[ : ] = original_path

    assert expected not in sys.path

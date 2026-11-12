"""The duplicate check takes its ceiling from the INI key when no flag names one."""
import json

import pytest

from cosa.config.configuration_manager import ConfigurationManager
from lupin_mcp import duplicate_check_daily as dd
from tests.unit.test_duplicate_check_daily import KeyConfig, NOW, git, history, parts_of, repo   # noqa: F401  (repo is a fixture)
from tests.unit.test_librarian_tick import cron   # noqa: F401  (fixture: the fake crontab and the fake lock)

KEY  = "external repo lupin duplicate check ceiling"
ARGS = ( "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini "
         "config_block_id=Lupin:+Development" )


@pytest.fixture
def live_config( monkeypatch ):
    """The real manager over the real INI; a fresh singleton before and after."""
    monkeypatch.setenv( "LUPIN_CONFIG_MGR_CLI_ARGS", ARGS )
    mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
    yield mgr
    ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )


def seen_by_adaptive_run( repo, tmp_path, monkeypatch, argv, config ):
    """Run main on a recording adaptive_run and return ( exit code, the ceiling it received )."""
    monkeypatch.setattr( dd.model_transport, "configure", lambda path=None: None )
    seen = []
    monkeypatch.setattr( dd, "adaptive_run", lambda *a: seen.append( a[ 7 ] ) or [ { "status": "ok" } ] )
    code = dd.main( argv + [ "--adaptive", "--root", str( repo ), "--claude-cli-path", "/bin/claude" ], parts=parts_of( tmp_path ), now=NOW, out=lambda t: None, config=config )
    return code, seen


def test_with_no_ceiling_flag_and_the_key_at_800_the_adaptive_run_receives_800( repo, tmp_path, monkeypatch, live_config ):
    assert seen_by_adaptive_run( repo, tmp_path, monkeypatch, [], live_config ) == ( 0, [ 800 ] )


def test_a_hand_run_ceiling_wins_over_the_key( repo, tmp_path, monkeypatch, live_config ):
    assert seen_by_adaptive_run( repo, tmp_path, monkeypatch, [ "--ceiling", "7" ], live_config ) == ( 0, [ 7 ] )


@pytest.mark.parametrize( "values", [ { }, { KEY: "" }, { KEY: "0" }, { KEY: "many" } ] )
def test_a_missing_or_bad_key_refuses_the_run_naming_the_key( repo, tmp_path, monkeypatch, capsys, values ):
    with pytest.raises( SystemExit ):
        seen_by_adaptive_run( repo, tmp_path, monkeypatch, [], KeyConfig( values ) )
    assert KEY in capsys.readouterr().err


def test_a_cap_alone_leaves_the_ceiling_unset_and_adaptive_still_refuses( capsys ):
    with pytest.raises( SystemExit ):
        dd.main( [ "--cap", "5", "--adaptive", "--root", "." ], config=KeyConfig( { KEY: "800" } ) )
    assert "--adaptive needs --ceiling" in capsys.readouterr().err
    assert dd.resolve_ceiling( None, 5, KeyConfig( { KEY: "800" } ) ) is None


def test_resolve_ceiling_reads_the_live_manager_when_no_config_is_given( live_config ):
    assert dd.resolve_ceiling( None, None ) == 800


def test_the_cron_lines_carry_the_ceiling_the_key_gave( tmp_path, cron ):
    out = []
    code = dd.main( [ "--print-install", "--adaptive", "--claude-cli-path", "/bin/claude", "--python", "/py" ], environ={ "LUPIN_ROOT": str( tmp_path ) }, out=out.append,
                    err=lambda t: None, crontab_cmd=cron[ "cmd" ], config=KeyConfig( { KEY: "1500" } ) )
    assert code == 0 and "--ceiling 1500" in out[ 0 ]


def test_the_reinstall_text_names_the_key_and_the_value_it_holds_now_and_never_a_flag():
    on  = dd.reinstall_command( "/m", "/py", None, "/c", "b", ceiling=1500, config=KeyConfig( { KEY: "800" } ) )
    off = dd.reinstall_command( "/m", "/py", None, "/c", "b", ceiling=1500, config=KeyConfig( { KEY: "" } ) )
    assert on.endswith( f"`{KEY}` in src/conf/lupin-app.ini and is 800 now." )
    assert off.endswith( f"`{KEY}` in src/conf/lupin-app.ini, which is blank or invalid now, so a run with no --ceiling refuses until it is set." )
    assert "--ceiling" not in on.replace( "no --ceiling", "" ) and "1500" not in on and "1500" not in off

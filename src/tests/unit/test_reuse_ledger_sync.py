"""
The Jev ledger sync and drift check (code-health plan 1, step ph1-s2).

The sync writes the ledger's limit row from the INI key. The drift check fails on a one-token difference.
A Jev run started on a drifted ledger is refused before it sends anything.
"""
import pytest

from cosa.config.configuration_manager import ConfigurationManager
from cosa.repo import code_health_settings as chs
from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_ledger_sync as sync_mod
from lupin_mcp import reuse_tools as rt
from tests.unit.symindex_helpers import make_lupin_repo

ARGS = ( "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini "
         "config_block_id=Lupin:+Development" )
KEY  = chs.repo_key( "lupin", chs.JEV_LIMIT_KIND )


@pytest.fixture
def config( monkeypatch ):
    """The real manager over the real INI; a fresh singleton before and after."""
    monkeypatch.setenv( "LUPIN_CONFIG_MGR_CLI_ARGS", ARGS )
    mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
    yield mgr
    ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )


@pytest.fixture
def limit( config ):
    """The limit the real INI holds for lupin."""
    return chs.jev_token_limit( config, "lupin" )


def make_ledger( tmp_path, tokens ):
    return rl.AccountLedger.create( tmp_path / "ledger.jsonl", tokens, "test", "fixture" )


def test_the_real_ini_key_holds_lupins_limit( limit ):
    assert limit == 1428571428


def test_sync_creates_a_missing_ledger_with_the_keys_limit( tmp_path, limit ):
    path = tmp_path / "ledger.jsonl"
    assert sync_mod.sync( path, limit, "t", "first" ) == sync_mod.CREATED
    assert rl.AccountLedger( path ).limit_tokens() == limit


def test_sync_leaves_a_ledger_that_already_matches_untouched( tmp_path, limit ):
    led    = make_ledger( tmp_path, limit )
    before = led.path.read_bytes()
    assert sync_mod.sync( led.path, limit, "t", "again" ) == sync_mod.UNCHANGED
    assert led.path.read_bytes() == before


def test_sync_appends_a_limit_row_when_the_key_moved_and_keeps_the_old_one( tmp_path, limit ):
    led = make_ledger( tmp_path, limit - 1 )
    assert sync_mod.sync( led.path, limit, "t", "moved" ) == sync_mod.SET
    assert led.limit_tokens() == limit and len( led.path.read_text().splitlines() ) == 2


def test_sync_refuses_a_damaged_ledger( tmp_path, limit ):
    path = tmp_path / "ledger.jsonl"; path.write_text( "{ not json\n" )
    with pytest.raises( rl.LedgerUnreadable ): sync_mod.sync( path, limit, "t", "damaged" )


@pytest.mark.parametrize( "delta", [ 1, -1 ] )
def test_the_drift_check_fails_on_a_one_token_difference_and_names_the_key( tmp_path, limit, delta ):
    led = make_ledger( tmp_path, limit + delta )
    with pytest.raises( sync_mod.LedgerDrift, match=KEY ): sync_mod.check_drift( led, limit, KEY )


def test_the_drift_check_passes_when_the_ledger_equals_the_key( tmp_path, limit ):
    assert sync_mod.check_drift( make_ledger( tmp_path, limit ), limit, KEY ) is None


def test_the_drift_check_passes_after_the_sync_repairs_a_drift( tmp_path, limit ):
    led = make_ledger( tmp_path, limit + 1 )
    sync_mod.sync( led.path, limit, "t", "repair" )
    assert sync_mod.check_drift( led, limit, KEY ) is None


def test_the_drift_check_passes_a_missing_ledger_up_as_unreadable( tmp_path, limit ):
    with pytest.raises( rl.LedgerUnreadable ): sync_mod.check_drift( rl.AccountLedger( tmp_path / "none.jsonl" ), limit, KEY )


def test_check_repo_reads_the_key_and_compares_it_to_the_given_ledger( config, tmp_path, limit ):
    led = make_ledger( tmp_path, limit )
    assert sync_mod.check_repo( config, "lupin", led.path ) is None
    sync_mod.sync( led.path, limit + 1, "t", "drift" )
    with pytest.raises( sync_mod.LedgerDrift ): sync_mod.check_repo( config, "lupin", led.path )


def test_check_repo_refuses_a_blank_key_naming_it( config, tmp_path ):
    with pytest.raises( chs.CodeHealthSettingError, match="external repo nobody jev token limit" ):
        sync_mod.check_repo( config, "nobody", tmp_path / "x.jsonl" )


def test_check_repo_finds_the_repos_own_ledger_when_no_path_is_given( config, tmp_path, monkeypatch, limit ):
    led   = make_ledger( tmp_path, limit )
    roots = []
    monkeypatch.setattr( rl, "ledger_path", lambda root: roots.append( root ) or led.path )
    assert sync_mod.check_repo( config, "lupin" ) is None
    import cosa.utils.util as cu
    assert roots == [ cu.get_project_root() ]


def test_repo_root_uses_the_path_key_for_another_repo_and_refuses_it_blank( config, tmp_path ):
    config.set_config( chs.repo_key( "other", sync_mod.PATH_KIND ), str( tmp_path ) )
    assert sync_mod.repo_root( config, "other" ) == str( tmp_path )
    with pytest.raises( chs.CodeHealthSettingError, match="external repo blank path" ): sync_mod.repo_root( config, "blank" )


def test_the_command_syncs_then_checks_and_reports_drift_and_refusals( config, tmp_path, limit, capsys ):
    path = str( tmp_path / "ledger.jsonl" )
    assert sync_mod.main( [ "sync", "--ledger", path ], config ) == sync_mod.EXIT_OK and f"created: {path} limit {limit}" in capsys.readouterr().out
    assert sync_mod.main( [ "check", "--ledger", path ], config ) == sync_mod.EXIT_OK and "ok:" in capsys.readouterr().out
    rl.AccountLedger( path ).set_limit( limit + 1, "t", "drift" )
    assert sync_mod.main( [ "check", "--ledger", path ], config ) == sync_mod.EXIT_DRIFT and "DRIFT:" in capsys.readouterr().err
    assert sync_mod.main( [ "check", "--repo", "nobody" ], config ) == sync_mod.EXIT_REFUSED and "REFUSED:" in capsys.readouterr().err


def test_the_command_reads_the_manager_itself_when_none_is_passed( config, tmp_path, limit ):
    path = str( tmp_path / "ledger.jsonl" )
    assert sync_mod.main( [ "sync", "--ledger", path ] ) == sync_mod.EXIT_OK
    assert rl.AccountLedger( path ).limit_tokens() == limit


def test_the_command_finds_the_repos_ledger_when_no_ledger_is_named( config, tmp_path, monkeypatch, limit ):
    monkeypatch.setattr( rl, "ledger_path", lambda root: tmp_path / "own.jsonl" )
    assert sync_mod.main( [ "sync" ], config ) == sync_mod.EXIT_OK and rl.AccountLedger( tmp_path / "own.jsonl" ).limit_tokens() == limit


def _pack_env( monkeypatch ):
    monkeypatch.setenv( "LUPIN_REUSE_JEV_PACK_SIZE", "50" ); monkeypatch.setenv( "LUPIN_REUSE_JEV_TOKEN_CEILING", "71000000" ); monkeypatch.setenv( "LUPIN_REUSE_JEV_RUN_NAME", "r" )
    monkeypatch.delenv( "LUPIN_REUSE_LEDGER_PATH", raising=False )


def test_a_run_on_a_drifted_ledger_is_refused_before_it_sends_or_spends( config, tmp_path, monkeypatch, limit ):
    led   = make_ledger( tmp_path, limit + 1 )
    posts = []
    _pack_env( monkeypatch )
    monkeypatch.setenv( jt.KEY_VARIABLE, "fake-key" )
    monkeypatch.setattr( jt, "_post", lambda *a: posts.append( a ) )
    monkeypatch.setattr( rl, "ledger_path", lambda root: led.path )
    with pytest.raises( rt.ReuseError, match="LEDGER_DRIFT" ): rt.context_from_environment( make_lupin_repo( tmp_path ) )
    assert posts == [] and led.total() == 0


def test_a_run_on_a_matching_ledger_is_admitted_past_the_check( config, tmp_path, monkeypatch, limit ):
    led = make_ledger( tmp_path, limit )
    _pack_env( monkeypatch )
    monkeypatch.setattr( rl, "ledger_path", lambda root: led.path )
    assert rt.context_from_environment( make_lupin_repo( tmp_path ) ).ledger.path == led.path


def test_a_missing_fleet_ledger_is_left_for_begin_run_to_refuse( config, tmp_path, monkeypatch ):
    _pack_env( monkeypatch )
    monkeypatch.setattr( rl, "ledger_path", lambda root: tmp_path / "none.jsonl" )
    assert rt.context_from_environment( make_lupin_repo( tmp_path ) ).ledger.path == tmp_path / "none.jsonl"


def test_a_ledger_named_by_the_variable_is_not_held_to_the_key( config, tmp_path, monkeypatch, limit ):
    led = make_ledger( tmp_path, limit + 1 )
    _pack_env( monkeypatch )
    monkeypatch.setenv( "LUPIN_REUSE_LEDGER_PATH", str( led.path ) )
    assert rt.context_from_environment( make_lupin_repo( tmp_path ) ).ledger.path == led.path

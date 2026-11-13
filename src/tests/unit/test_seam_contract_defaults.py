"""
Each of the eight code-health seams keeps today's value as its default.

Every expected value below is a literal read from the base sha d8037019f, written out here. None of them
is read from the constant it checks, so a changed default fails the test instead of changing both sides.
"""
import pathlib

import cosa.memory.embedding_provider as ep
import cosa.repo.code_health_settings as chs
import cosa.repo.duplicate_check.config as dc_config
import cosa.repo.symindex.librarian_tick as lt
import cosa.repo.symindex.spec as spec
import cosa.utils.hook_link_tick as hlt
from lupin_cli.claude_code.hooks.lib import heartbeat_hold
from lupin_mcp import duplicate_check_daily as dcd
from lupin_mcp import duplicate_check_filing as dcf

REAL_ROOT = pathlib.Path( __file__ ).resolve().parents[ 3 ]


def test_index_spec_of_a_lupin_tree_keeps_its_package_script_and_skip_defaults( tmp_path ):
    """IndexSpec: a lupin layout detects the spec written before the INI keys."""
    ( tmp_path / "src" / "cosa" ).mkdir( parents=True )
    ( tmp_path / "src" / "lupin_mcp" ).mkdir( )
    ( tmp_path / "src" / "conf" ).mkdir( )
    found = spec.detected_spec( tmp_path )
    assert [ p.name for p in found.py_roots ] == [ "cosa", "lupin_mcp" ]
    assert [ str( p.relative_to( found.root ) ) for p in found.js_roots ] == [ "src/conf" ]
    assert found.dart_roots == ()
    assert found.module_base == found.root / "src"
    assert found.skip_parts == frozenset( { "tests", "migrations", ".venv", "vendor", "node_modules", "rnd", "__pycache__", ".git" } )
    assert spec.LUPIN_PY_PACKAGES == ( "cosa", "lupin_cli", "lupin_mcp", "lupin_app", "lupin_arbiter_app", "lupin_model_server", "scripts" )
    assert spec.LUPIN_JS_DIRS == ( "src/lupin_app/static/js", "src/scripts", "src/cosa/repo/symindex", "src/conf", "src/lupin_app/static/html" )


def test_data_root_is_the_fleet_folder_named_for_the_checkout( tmp_path, monkeypatch ):
    """DataRoot: the fleet folder, or the derived projects-data sibling."""
    monkeypatch.setenv( "DEEPILY_DATA_DIR", "/DATA" )
    assert heartbeat_hold.fleet_data_root( tmp_path / "projects" / "foo" ) == pathlib.Path( "/DATA/foo" )
    monkeypatch.delenv( "DEEPILY_DATA_DIR" )
    assert heartbeat_hold.fleet_data_root( tmp_path / "projects" / "foo" ) == tmp_path / "projects-data" / "foo"


def test_embedding_provider_defaults_to_the_dev_server_when_the_variable_is_unset_or_blank( monkeypatch ):
    """EmbeddingProvider: the server URL default is the dev server, and a set value wins."""
    monkeypatch.delenv( "LUPIN_APP_SERVER_URL", raising=False )
    assert ep.EmbeddingProvider._resolve_server_url() == "http://localhost:7999"
    monkeypatch.setenv( "LUPIN_APP_SERVER_URL", "  " )
    assert ep.EmbeddingProvider._resolve_server_url() == "http://localhost:7999"
    monkeypatch.setenv( "LUPIN_APP_SERVER_URL", "http://localhost:8000" )
    assert ep.EmbeddingProvider._resolve_server_url() == "http://localhost:8000"


def test_the_duplicate_check_judge_model_is_read_from_its_ini_key_and_has_no_code_default():
    """Judge: the duplicate-check model comes from its INI key, with no pinned id in code."""
    assert not hasattr( dc_config, "MODEL_ID" )
    cfg = dc_config.build_config( "max-plan", 0, "p", "s", "u", "parser", [], 100, { "version": "5", "min_tokens": 50, "min_lines": 5, "max_size": "100kb", "chosen_in": "x" } )
    assert cfg[ "model_id" ] == "claude-fable-5-1"      # the committed INI value; the frozen config pins the same id


def test_task_store_adapter_callers_stamp_lupin_as_the_project():
    """TaskStoreAdapter: the filing project and the librarian sender_project."""
    assert dcf.PROJECT == "lupin"
    seen = { }
    def post( base, key, path, payload ):
        seen.update( base=base, path=path, payload=payload )
        return 201, ""
    assert lt.notify_owner( "rick", "hello", { }, post=post, api_key=lambda: "k" ) is True
    assert seen[ "payload" ][ "sender_project" ] == "lupin"
    assert seen[ "path" ] == "/api/dm/send"


def test_notifier_defaults_to_the_dev_server_and_the_duplicate_check_sender_id():
    """Notifier: the API base of both senders and the duplicate-check sender id."""
    assert hlt.DEFAULT_API_BASE == "http://localhost:7999"
    assert lt.DEFAULT_API_BASE == "http://localhost:7999"
    seen = { }
    def query( base, key, path, params ):
        seen.update( base=base, params=params )
        return 200, ""
    assert dcd.live_notifier( "m", "a", environ={ }, query=query, api_key=lambda: "k", target_of=lambda environ: "rick" ) is True
    assert seen[ "base" ] == "http://localhost:7999"
    assert seen[ "params" ][ "sender_id" ] == "claude.code@lupin.deepily.ai#duplicate-check-daily"


def test_scheduler_rows_with_no_repo_key_belong_to_lupin():
    """Scheduler: a registry row with no repo key is a lupin row."""
    assert chs.DEFAULT_REPO == "lupin"
    assert chs.repo_of( { "job": "x" } ) == "lupin"


def test_gate_installer_fixes_two_hook_names_and_their_two_chain_scripts():
    """Gate: the git hook installer links pre-commit and pre-push to their chain scripts."""
    text = ( REAL_ROOT / "src" / "scripts" / "install-git-hooks.sh" ).read_text()
    assert "HOOK_NAMES=( pre-commit pre-push )" in text
    assert "HOOK_SCRIPTS=( pre-commit-chain.sh pre-push-chain.sh )" in text

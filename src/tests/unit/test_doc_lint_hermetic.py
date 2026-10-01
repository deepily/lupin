"""
Hermetic model calls: the Claude Code subprocess must not see the operator's instructions.

The profile is checked three ways: the options each call passes, the profile hashed into every
prompt version, and a probe captured from the real CLI (a planted CLAUDE.md line is obeyed by the
old options and ignored by the hermetic ones).
"""

import asyncio
import json
import pathlib
import subprocess

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from cosa.repo.doc_lint import claim_extractor, claim_judge, harness_cli, harness_runner, jev_judge, model_transport as mt, prose_judge, reader_rig

FIXTURE = pathlib.Path( __file__ ).parent / "fixtures" / "doc_lint" / "hermetic-probe.json"


@pytest.fixture( autouse=True )
def reset_config():
    mt.configure( None, None )
    yield
    mt.configure( None, None )


def captured_options( **configure_kwargs ):
    seen = []
    async def query( prompt, options ):
        seen.append( options )
        yield AssistantMessage( content=[ TextBlock( "ok" ) ], model="m" )
    mt.configure( **configure_kwargs )
    asyncio.run( mt.complete( "claude-x", "sys", "user", query_fn=query ) )
    return seen[ 0 ]


def test_a_call_passes_every_isolation_option():
    options = captured_options()
    assert options.tools == []
    assert options.setting_sources == []
    assert options.extra_args == mt.ISOLATION_ARGS
    assert set( options.extra_args ) == { "settings", "strict-mcp-config", "disable-slash-commands" }
    assert options.extra_args[ "strict-mcp-config" ] is None and options.extra_args[ "disable-slash-commands" ] is None


def test_the_settings_flag_turns_off_hooks_instruction_files_and_memory():
    settings = json.loads( captured_options().extra_args[ "settings" ] )
    assert settings[ "disableAllHooks" ] is True
    assert settings[ "autoMemoryEnabled" ] is False
    assert "**/CLAUDE.md" in settings[ "claudeMdExcludes" ] and "**/CLAUDE.local.md" in settings[ "claudeMdExcludes" ]
    assert any( pattern.endswith( "/.claude/CLAUDE.md" ) for pattern in settings[ "claudeMdExcludes" ] )


def test_the_default_working_directory_is_the_project_root( monkeypatch, tmp_path ):
    monkeypatch.setattr( mt.cu, "get_project_root", lambda: str( tmp_path ) )
    assert captured_options().cwd == str( tmp_path )


def test_a_configured_working_directory_wins_and_must_exist( tmp_path ):
    assert captured_options( cwd=str( tmp_path ) ).cwd == str( tmp_path )
    mt.configure( None, None )
    with pytest.raises( ValueError, match="not a directory" ):
        mt.configure( None, str( tmp_path / "missing" ) )
    assert mt.CWD is None


def test_the_isolation_options_are_copies_so_a_call_cannot_change_the_profile():
    first = captured_options()
    first.extra_args[ "extra" ] = "x"
    first.setting_sources.append( "user" )
    assert "extra" not in mt.ISOLATION_ARGS and mt.SETTING_SOURCES == []


def test_the_profile_is_hashed_into_a_prompt_version( monkeypatch ):
    before = mt.prompt_version( "x", "a", "b" )
    monkeypatch.setattr( mt, "CALL_PROFILE", mt.CALL_PROFILE + "|changed" )
    assert mt.prompt_version( "x", "a", "b" ) != before
    assert before.startswith( "x-" ) and len( before ) == len( "x-" ) + 10


def test_the_profile_names_the_options_it_stands_for():
    assert mt.CALL_PROFILE.startswith( "hermetic-1|" )
    for word in ( "disableAllHooks", "claudeMdExcludes", "autoMemoryEnabled", "strict-mcp-config", "disable-slash-commands" ):
        assert word in mt.CALL_PROFILE


def test_the_profile_carries_every_option_with_its_value():
    label, body = mt.CALL_PROFILE.split( "|", 1 )
    profile     = json.loads( body )
    assert label == "hermetic-1"
    home = str( pathlib.Path.home() )
    assert home not in mt.CALL_PROFILE and "~/.claude/CLAUDE.md" in profile[ "settings" ][ "claudeMdExcludes" ]
    assert any( pattern.startswith( home ) for pattern in mt.ISOLATION_SETTINGS[ "claudeMdExcludes" ] )
    sent = dict( mt.ISOLATION_SETTINGS, claudeMdExcludes=[ "~/.claude/CLAUDE.md" if p.startswith( home ) else p for p in mt.ISOLATION_SETTINGS[ "claudeMdExcludes" ] ] )
    assert profile == { "settings": sent, "args": sorted( mt.ISOLATION_ARGS ), "setting_sources": [], "tools": [] }


def test_an_error_result_keeps_only_the_first_300_characters_of_the_apis_text():
    async def query( prompt, options ):
        yield ResultMessage( subtype="success", duration_ms=1, duration_api_ms=1, is_error=True, num_turns=1, session_id="s",
                             result="A" * 300 + "B" + "TAILMARK" )
    with pytest.raises( mt.ModelCallError ) as caught:
        asyncio.run( mt.complete( "claude-x", "sys", "user", query_fn=query ) )
    assert "A" * 300 in str( caught.value ) and "A" * 300 + "B" not in str( caught.value )


@pytest.mark.parametrize( "module", [ claim_extractor, claim_judge, jev_judge, prose_judge, reader_rig ] )
def test_every_prompt_version_comes_from_prompt_version_so_it_carries_the_profile( module ):
    source = pathlib.Path( module.__file__ ).read_text()
    assert "model_transport.prompt_version(" in source or "mt.prompt_version(" in source


def test_an_error_result_names_the_apis_reason():
    async def query( prompt, options ):
        yield ResultMessage( subtype="success", duration_ms=1, duration_api_ms=1, is_error=True, num_turns=1, session_id="s",
                             result="API Error: 400 version 2.1.280 or newer is required" )
    with pytest.raises( mt.ModelCallError, match="2.1.280 or newer is required" ):
        asyncio.run( mt.complete( "claude-x", "sys", "user", query_fn=query ) )


class _Done:
    def __init__( self, code, out ): self.returncode, self.stdout = code, out


def test_cli_version_reads_the_first_line_and_never_raises():
    assert mt.cli_version( None ) is None
    assert mt.cli_version( "/x/claude", run_fn=lambda *a, **k: _Done( 0, "2.1.287 (Claude Code)\nmore\n" ) ) == "2.1.287 (Claude Code)"
    assert mt.cli_version( "/x/claude", run_fn=lambda *a, **k: _Done( 1, "" ) ) == "unreadable"
    assert mt.cli_version( "/x/claude", run_fn=lambda *a, **k: _Done( 2, "usage: claude [options]\n" ) ) == "unreadable"
    assert mt.cli_version( "/x/claude", run_fn=lambda *a, **k: _Done( 0, "  \n" ) ) == "unreadable"
    def missing( *a, **k ): raise FileNotFoundError( "gone" )
    def hangs( *a, **k ): raise subprocess.TimeoutExpired( "claude", 30 )
    assert mt.cli_version( "/x/claude", run_fn=missing ) == "unreadable"
    assert mt.cli_version( "/x/claude", run_fn=hangs ) == "unreadable"


def test_cli_version_runs_the_binary_it_is_given( tmp_path ):
    binary = tmp_path / "claude"
    binary.write_text( "#!/bin/sh\necho '9.9.9 (Fake Code)'\n" )
    binary.chmod( 0o755 )
    assert mt.cli_version( str( binary ) ) == "9.9.9 (Fake Code)"


def test_the_report_records_the_profile_and_the_binary_version( tmp_path ):
    from tests.unit.test_doc_lint_jev import cli_args, cli_claude_query
    binary = tmp_path / "claude"
    binary.write_text( "#!/bin/sh\necho '9.9.9 (Fake Code)'\n" )
    binary.chmod( 0o755 )
    assert harness_cli.main( cli_args( tmp_path, "--claude-cli-path", str( binary ) ), query_fn=cli_claude_query() ) == 0
    report = json.loads( ( tmp_path / "r.json" ).read_text() )
    assert report[ "claude_cli_version" ] == "9.9.9 (Fake Code)" and report[ "call_profile" ] == mt.CALL_PROFILE
    other = tmp_path / "again"
    other.mkdir()
    assert harness_cli.main( cli_args( other ), query_fn=cli_claude_query() ) == 0
    assert json.loads( ( other / "r.json" ).read_text() )[ "claude_cli_version" ] is None


# ---- captured from the real CLI -----------------------------------------------------------

def cases( fixture, hermetic, prompt_start ):
    return [ c for c in fixture[ "cases" ] if c[ "hermetic" ] is hermetic and c[ "prompt" ].startswith( prompt_start ) ]


def test_the_captured_probe_shows_a_planted_claude_md_obeyed_before_and_ignored_after():
    fx = json.loads( FIXTURE.read_text() )
    marker = fx[ "planted_marker" ]
    assert marker and fx[ "cli_version" ].startswith( "2." ) and fx[ "call_profile" ].startswith( "hermetic-1|" )
    old, new = cases( fx, False, "In one sentence" ), cases( fx, True, "In one sentence" )
    assert len( old ) == len( new ) == 1
    assert marker in old[ 0 ][ "reply" ] and marker not in new[ 0 ][ "reply" ]
    assert "Paris" in new[ 0 ][ "reply" ]


def test_the_captured_probe_shows_the_operators_instructions_visible_before_and_absent_after():
    fx = json.loads( FIXTURE.read_text() )
    old, new = cases( fx, False, "Without using tools" )[ 0 ][ "reply" ], cases( fx, True, "Without using tools" )[ 0 ][ "reply" ]
    assert "CLAUDE.md" in old and "Instruction" in old
    assert new.startswith( "NONE" )
    for leaked in ( "BREVITY", "cosa-voice", "notify", "CLAUDE.md", "persona" ):
        assert leaked not in new


# ---- the ledger is bound to the binary that made its calls ----------------------------------

def test_a_ledger_records_its_binary_first_and_resumes_under_the_same_one( tmp_path ):
    path = str( tmp_path / "l.jsonl" )
    first = harness_runner.Ledger( path, binding="claude_cli=/a|version=1" )
    first.put( "k", { "v": 1 } )
    lines = [ json.loads( line ) for line in open( path ) ]
    assert lines[ 0 ] == { "binding": "claude_cli=/a|version=1" } and lines[ 1 ][ "key" ] == "k"
    again = harness_runner.Ledger( path, binding="claude_cli=/a|version=1" )
    assert again.get( "k" ) == { "v": 1 } and again.entries == { "k": { "v": 1 } }
    assert len( open( path ).readlines() ) == 2


def test_a_ledger_refuses_a_resume_under_another_binary( tmp_path ):
    path = str( tmp_path / "l.jsonl" )
    harness_runner.Ledger( path, binding="claude_cli=/a|version=1" ).put( "k", 1 )
    with pytest.raises( harness_runner.LedgerBindingError, match="use a new ledger" ):
        harness_runner.Ledger( path, binding="claude_cli=/a|version=2" )


def test_a_ledger_holding_only_a_binding_still_refuses_another_binary( tmp_path ):
    path = str( tmp_path / "l.jsonl" )
    harness_runner.Ledger( path, binding="one" )
    with pytest.raises( harness_runner.LedgerBindingError ):
        harness_runner.Ledger( path, binding="two" )
    assert len( open( path ).readlines() ) == 1


def test_a_ledger_with_calls_and_no_binding_is_refused_when_a_binding_is_asked_for( tmp_path ):
    path = str( tmp_path / "l.jsonl" )
    harness_runner.Ledger( path ).put( "k", 1 )
    with pytest.raises( harness_runner.LedgerBindingError, match="None" ):
        harness_runner.Ledger( path, binding="one" )


def test_a_ledger_without_a_binding_asks_nothing_and_writes_no_header( tmp_path ):
    path = str( tmp_path / "l.jsonl" )
    harness_runner.Ledger( path ).put( "k", 1 )
    assert harness_runner.Ledger( path ).get( "k" ) == 1
    assert len( open( path ).readlines() ) == 1


def test_the_cli_refuses_to_resume_a_ledger_under_a_different_binary_version( tmp_path ):
    from tests.unit.test_doc_lint_jev import cli_args, cli_claude_query
    def fake( version ):
        binary = tmp_path / f"claude-{version}"
        binary.write_text( f"#!/bin/sh\necho '{version} (Fake Code)'\n" )
        binary.chmod( 0o755 )
        return str( binary )
    one = fake( "1.0.0" )
    assert harness_cli.main( cli_args( tmp_path, "--claude-cli-path", one ), query_fn=cli_claude_query() ) == 0
    ( tmp_path / "r.json" ).unlink()
    calls = []
    async def forbidden( prompt, options ):
        calls.append( 1 )
        yield None
    ( tmp_path / "claude-1.0.0" ).write_text( "#!/bin/sh\necho '2.0.0 (Fake Code)'\n" )
    assert harness_cli.main( cli_args( tmp_path, "--claude-cli-path", one ), query_fn=forbidden ) == 2
    assert calls == [] and not ( tmp_path / "r.json" ).exists()

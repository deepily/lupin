#!/usr/bin/env python3
"""
Unit tests for cosa.agents.presentation_generator.orchestrator — HELPERS.

Target: PresentationOrchestratorAgent — the standalone (non-AgentBase), single-job,
multi-phase async state machine that drives presentation generation. This file
covers everything EXCEPT the two top-level state machines (do_all_async +
render_from_yaml_async), which live in test_orchestrator_phases.py.

Groups covered here:
  - Control/state: __init__, api_client prop, request_stop, _check_stop,
    _handle_stop, get_state
  - Ingest/parse: _ingest_async, _read_file (both bodies), _detect_format,
    _parse_markdown_sections, _parse_plaintext_sections
  - Content-gen: _analyze_async, _outline_async, _elaborate_async,
    _elaborate_chunked, _serialize_async, _write_yaml/_write_marp/_load_theme_config
  - Render/deliver: _render_text_async, _render_visuals_async,
    _build_visual_registry, _deliver_async, _export_pptx_async
  - Gates: _gate_1..4_review

Isolation contract (zero spend, zero real I/O):
  - voice_io.{notify,present_choices,ask_yes_no,get_input} → AsyncMock
  - api_client / renderers / gemini_client → MagicMock with AsyncMock methods
  - asyncio.to_thread / asyncio subprocess / open / os.path.* / os.makedirs →
    patched so NO real filesystem or process access occurs.

quick_smoke_test() and the __main__ guard are coverage-excluded by repo config.

POST-FIX: two genuine prod bugs found during this lane — duplicate _read_file
shadowing (dead `except FileNotFoundError` in _ingest_async) and Gate-4's wrong
present_choices signature (always auto-approved) — were fixed by Tiberius
(rename → _read_file_or_raise/_read_file_or_none; Gate-4 rewritten to
questions=[...]/title= + dict parse). The originally-armed xfail-strict
tripwires are now plain passing regression guards in TestPostFixContractGuards.
"""

import os
import types
import builtins
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.presentation_generator import orchestrator as orch_mod
from cosa.agents.presentation_generator.orchestrator import PresentationOrchestratorAgent
from cosa.agents.presentation_generator.state import (
    OrchestratorState,
    ArcPosition,
    NarrativeSection,
    SlideOutline,
    SlideModel,
    PresenterNotes,
    PresentationModel,
)
from cosa.agents.presentation_generator.config import PresentationConfig


# ===========================================================================
# Helpers / fixtures
# ===========================================================================
def _run( coro ):
    return asyncio.run( coro )


def _agent( source_path="/io/src/doc.md", user_id="u@test.com", config=None,
            dry_run=False, debug=False, verbose=False ):
    return PresentationOrchestratorAgent(
        source_path = source_path,
        user_id     = user_id,
        config      = config or PresentationConfig(),
        dry_run     = dry_run,
        debug       = debug,
        verbose     = verbose,
    )


def _section( heading="Intro", content="Body text here", arc=ArcPosition.SETUP, slides=1 ):
    return NarrativeSection( heading=heading, content=content, arc_position=arc, proposed_slides=slides )


def _outline( number=1, arc="opening", type="title", title="Title Slide",
              visual_type="text_only", source_hint=None ):
    return SlideOutline( number=number, arc_position=arc, type=type, title=title,
                         visual_type=visual_type, source_hint=source_hint )


def _slide( number=1, arc="opening", type="title", title="Title Slide",
            visual_type="text_only", visual_description=None, bullets=None, notes=None ):
    return SlideModel(
        number             = number,
        arc_position       = arc,
        type               = type,
        title              = title,
        visual_type        = visual_type,
        visual_description = visual_description,
        content_bullets    = bullets or [],
        presenter_notes    = notes or PresenterNotes( talking_points=[ "tp" ], timing_seconds=60 ),
    )


def _presentation( title="My Talk", slides=None, theme="default" ):
    slides = slides if slides is not None else [ _slide() ]
    return PresentationModel(
        title        = title,
        total_slides = len( slides ),
        slides       = slides,
        theme        = theme,
    )


@pytest.fixture( autouse=True )
def _silence_voice_io():
    """Mock all voice_io coroutines so no real notifications/prompts fire."""
    with patch.object( orch_mod.voice_io, "notify", new=AsyncMock() ) as notify, \
         patch.object( orch_mod.voice_io, "present_choices", new=AsyncMock() ) as choices, \
         patch.object( orch_mod.voice_io, "ask_yes_no", new=AsyncMock( return_value=True ) ) as yesno, \
         patch.object( orch_mod.voice_io, "get_input", new=AsyncMock( return_value="" ) ) as getinput:
        yield {
            "notify"  : notify,
            "choices" : choices,
            "yesno"   : yesno,
            "input"   : getinput,
        }


def _mock_api_client():
    """MagicMock api_client whose call_for_* are AsyncMocks returning a response w/ .content."""
    client   = MagicMock()
    response = MagicMock()
    response.content     = "RAW"
    response.tokens_used = 42
    response.stop_reason = "end_turn"
    client.call_for_analysis    = AsyncMock( return_value=response )
    client.call_for_outline     = AsyncMock( return_value=response )
    client.call_for_elaboration = AsyncMock( return_value=response )
    return client


# ===========================================================================
# Control/state — __init__ / lazy api_client / control / get_state (EASY)
# ===========================================================================
class TestInit:
    def test_defaults( self ):
        agent = _agent()
        assert agent.state == OrchestratorState.INITIALIZED
        assert agent.source_path == "/io/src/doc.md"
        assert agent.user_id == "u@test.com"
        assert agent._stop_requested is False
        assert agent._api_client is None
        assert agent.presentation_id.startswith( "pres-" )
        assert len( agent.presentation_id ) == len( "pres-" ) + 8
        assert agent.metrics[ "start_time" ] is None
        assert agent.metrics[ "end_time" ] is None
        assert agent.metrics[ "api_calls" ] == 0
        assert agent.metrics[ "tokens_used" ] == 0

    def test_config_supplied_is_used( self ):
        cfg = PresentationConfig()
        cfg.target_duration_minutes = 30
        assert _agent( config=cfg ).config is cfg

    def test_config_none_builds_default( self ):
        agent = PresentationOrchestratorAgent( source_path="/x.md", user_id="u", config=None )
        assert isinstance( agent.config, PresentationConfig )
        assert agent.config.target_duration_minutes == 15

    def test_internal_state_initialized( self ):
        agent = _agent( source_path="/io/src/doc.md", user_id="u@test.com" )
        assert agent._presentation_state[ "source_path" ] == "/io/src/doc.md"
        assert agent._presentation_state[ "user_id" ] == "u@test.com"
        assert agent._presentation_state[ "revision_count" ] == 0

    def test_debug_branch_prints( self, capsys ):
        _agent( debug=True )
        out = capsys.readouterr().out
        assert "Initialized for" in out
        assert "Presentation ID" in out

    def test_no_debug_silent( self, capsys ):
        _agent( debug=False )
        assert capsys.readouterr().out == ""


class TestLazyApiClient:
    def test_api_client_lazy_init_and_cached( self ):
        agent = _agent( debug=True, verbose=True )
        with patch( "cosa.agents.presentation_generator.api_client.PresentationAPIClient" ) as PAC:
            client = agent.api_client
            assert client is PAC.return_value
            # second access returns the cached instance (no second construction)
            assert agent.api_client is client
            PAC.assert_called_once_with( config=agent.config, debug=True, verbose=True )

    def test_api_client_returns_preset_instance( self ):
        agent = _agent()
        sentinel = object()
        agent._api_client = sentinel
        assert agent.api_client is sentinel


class TestControlMethods:
    def test_request_stop_sets_flag( self ):
        agent = _agent()
        assert agent._check_stop() is False
        agent.request_stop()
        assert agent._stop_requested is True
        assert agent._check_stop() is True

    def test_request_stop_debug_print( self, capsys ):
        agent = _agent( debug=True )
        capsys.readouterr()  # drain construction output
        agent.request_stop()
        assert "Stop requested" in capsys.readouterr().out

    def test_handle_stop_sets_cancelled_and_notifies( self, _silence_voice_io ):
        agent = _agent()
        result = _run( agent._handle_stop() )
        assert result is None
        assert agent.state == OrchestratorState.CANCELLED
        _silence_voice_io[ "notify" ].assert_awaited()

    def test_handle_stop_debug_print( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        capsys.readouterr()
        _run( agent._handle_stop() )
        assert "Stopped gracefully" in capsys.readouterr().out


class TestGetState:
    def test_get_state_shape( self ):
        agent = _agent( source_path="/io/src/doc.md" )
        state = agent.get_state()
        assert state[ "state" ] == "initialized"
        assert state[ "presentation_id" ] == agent.presentation_id
        assert state[ "source_path" ] == "/io/src/doc.md"
        assert state[ "metrics" ] is agent.metrics
        # internal_state excludes user_id + source_path; values coerce to bool
        assert "user_id" not in state[ "internal_state" ]
        assert "source_path" not in state[ "internal_state" ]
        assert state[ "internal_state" ][ "source_content" ] is False

    def test_get_state_reflects_populated_internal( self ):
        agent = _agent()
        agent._presentation_state[ "source_content" ] = "loaded"
        state = agent.get_state()
        assert state[ "internal_state" ][ "source_content" ] is True


# ===========================================================================
# Ingest/parse — _ingest_async + _read_file (live body) (MID)
# ===========================================================================
_MARKDOWN = "# Title\n\nSome intro.\n\n## Section A\n\n- bullet one\n- bullet two\n\n## Section B\n\nBody.\n"
_PLAINTEXT = "First paragraph of plain prose without markup.\n\nSecond paragraph here.\n"


class TestIngestAsync:
    def test_ingest_absolute_markdown_success( self, capsys, _silence_voice_io ):
        agent = _agent( source_path="/abs/doc.md", debug=True )
        with patch.object( orch_mod.asyncio, "to_thread", new=AsyncMock( return_value=_MARKDOWN ) ):
            content = _run( agent._ingest_async() )
        assert content == _MARKDOWN
        assert agent._presentation_state[ "source_format" ] == "markdown"
        assert agent._presentation_state[ "word_count" ] == len( _MARKDOWN.split() )
        assert len( agent._presentation_state[ "raw_sections" ] ) >= 1
        assert "Ingested:" in capsys.readouterr().out

    def test_ingest_relative_path_resolves_project_root( self, _silence_voice_io ):
        agent = _agent( source_path="rel/doc.md" )
        captured = {}
        async def fake_to_thread( fn, path ):
            captured[ "path" ] = path
            return _MARKDOWN
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch.object( orch_mod.asyncio, "to_thread", side_effect=fake_to_thread ):
            content = _run( agent._ingest_async() )
        assert captured[ "path" ] == "/proj/rel/doc.md"
        assert content == _MARKDOWN

    def test_ingest_plaintext_format( self, _silence_voice_io ):
        agent = _agent( source_path="/abs/notes.txt" )
        with patch.object( orch_mod.asyncio, "to_thread", new=AsyncMock( return_value=_PLAINTEXT ) ):
            _run( agent._ingest_async() )
        assert agent._presentation_state[ "source_format" ] == "plaintext"

    def test_ingest_file_not_found_returns_none( self, _silence_voice_io ):
        # Post BUG-B fix: _ingest_async calls _read_file_or_raise, so the
        # `except FileNotFoundError` arm (orchestrator.py:396-399) is now LIVE.
        agent = _agent( source_path="/abs/missing.md" )
        with patch.object( orch_mod.asyncio, "to_thread",
                           new=AsyncMock( side_effect=FileNotFoundError( "nope" ) ) ):
            assert _run( agent._ingest_async() ) is None
        assert any( c.kwargs.get( "priority" ) == "urgent"
                    for c in _silence_voice_io[ "notify" ].await_args_list )

    def test_ingest_generic_read_error_returns_none( self, _silence_voice_io ):
        agent = _agent( source_path="/abs/doc.md" )
        with patch.object( orch_mod.asyncio, "to_thread",
                           new=AsyncMock( side_effect=OSError( "disk" ) ) ):
            assert _run( agent._ingest_async() ) is None

    def test_ingest_empty_content_returns_none( self, _silence_voice_io ):
        agent = _agent( source_path="/abs/doc.md" )
        with patch.object( orch_mod.asyncio, "to_thread", new=AsyncMock( return_value="" ) ):
            assert _run( agent._ingest_async() ) is None

    def test_ingest_whitespace_only_content_returns_none( self, _silence_voice_io ):
        agent = _agent( source_path="/abs/doc.md" )
        with patch.object( orch_mod.asyncio, "to_thread", new=AsyncMock( return_value="   \n  " ) ):
            assert _run( agent._ingest_async() ) is None


class TestReadFileVariants:
    """Post BUG-B fix: two distinct methods — _read_file_or_raise (propagates) and
    _read_file_or_none (swallows → None). _ingest_async uses the raise-variant;
    _render_visuals_async uses the none-variant."""
    def test_read_file_or_raise_success( self, tmp_path ):
        p = tmp_path / "f.txt"
        p.write_text( "hello", encoding="utf-8" )
        assert PresentationOrchestratorAgent._read_file_or_raise( str( p ) ) == "hello"

    def test_read_file_or_raise_missing_raises( self ):
        # closes the formerly-dead body (orchestrator.py:452-453) — now reachable
        with pytest.raises( FileNotFoundError ):
            PresentationOrchestratorAgent._read_file_or_raise( "/no/such/file.xyz" )

    def test_read_file_or_none_success( self, tmp_path ):
        p = tmp_path / "g.txt"
        p.write_text( "world", encoding="utf-8" )
        assert PresentationOrchestratorAgent._read_file_or_none( str( p ) ) == "world"

    def test_read_file_or_none_missing_returns_none( self ):
        assert PresentationOrchestratorAgent._read_file_or_none( "/no/such/file.xyz" ) is None


# ===========================================================================
# Pure static parsers / writers / theme loader (EASY)
# ===========================================================================
class TestDetectFormat:
    @pytest.mark.parametrize( "content,expected", [
        ( "# Heading\n\n- bullet here\n", "markdown" ),          # heading + bullet → 2 indicators
        ( "```\ncode\n```\n**bold**\n", "markdown" ),            # fence + bold → 2 indicators
        ( "[link](http://x)\n**bold**\n", "markdown" ),          # link + bold → 2 indicators
        ( "Just plain prose, nothing special at all.", "plaintext" ),
        ( "# Only one heading and nothing else here", "plaintext" ),  # 1 indicator → plaintext
    ] )
    def test_detect_format( self, content, expected ):
        assert PresentationOrchestratorAgent._detect_format( content ) == expected


class TestParseMarkdownSections:
    def test_strips_frontmatter( self ):
        content = "---\ntitle: x\n---\n# Real Heading\n\nbody\n"
        sections = PresentationOrchestratorAgent._parse_markdown_sections( content )
        assert sections[ 0 ][ 0 ] == "Real Heading"

    def test_frontmatter_without_close_kept( self ):
        # opening --- but no closing --- → find returns -1, content unchanged
        content = "---\nstill text # Heading One\nmore\n"
        sections = PresentationOrchestratorAgent._parse_markdown_sections( content )
        assert sections  # no crash; single untitled section (no MULTILINE heading match)

    def test_no_headings_single_section( self ):
        sections = PresentationOrchestratorAgent._parse_markdown_sections( "just body, no headings" )
        assert sections == [ ( "(untitled)", "just body, no headings", 0 ) ]

    def test_preamble_then_headings_with_levels( self ):
        content = "Preamble line.\n\n# H1 Title\n\nbody1\n\n## H2 Sub\n\nbody2\n"
        sections = PresentationOrchestratorAgent._parse_markdown_sections( content )
        assert sections[ 0 ] == ( "(preamble)", "Preamble line.", 0 )
        assert ( "H1 Title", "body1", 1 ) in sections
        assert ( "H2 Sub", "body2", 2 ) in sections

    def test_no_preamble_when_starts_with_heading( self ):
        content = "# Start\n\nbody\n"
        sections = PresentationOrchestratorAgent._parse_markdown_sections( content )
        assert all( h != "(preamble)" for h, _, _ in sections )


class TestParsePlaintextSections:
    def test_paragraphs_numbered( self ):
        sections = PresentationOrchestratorAgent._parse_plaintext_sections( "Para one.\n\nPara two.\n\nPara three." )
        assert [ s[ 0 ] for s in sections ] == [ "Section 1", "Section 2", "Section 3" ]
        assert sections[ 0 ][ 2 ] == 0

    def test_empty_content_yields_empty_marker( self ):
        assert PresentationOrchestratorAgent._parse_plaintext_sections( "   \n\n  " ) == [ ( "(empty)", "", 0 ) ]


class TestWriters:
    def test_write_yaml_makedirs_and_write( self ):
        with patch( "os.makedirs" ) as mk, patch.object( builtins, "open", MagicMock() ) as op:
            PresentationOrchestratorAgent._write_yaml( "/out/dir/file.yaml", "content" )
        mk.assert_called_once_with( "/out/dir", exist_ok=True )
        op.assert_called_once()

    def test_write_marp_makedirs_and_write( self ):
        with patch( "os.makedirs" ) as mk, patch.object( builtins, "open", MagicMock() ) as op:
            PresentationOrchestratorAgent._write_marp( "/out/dir/file.md", "content" )
        mk.assert_called_once_with( "/out/dir", exist_ok=True )
        op.assert_called_once()


class TestLoadThemeConfig:
    def _fake_open( self, payload ):
        fh = MagicMock()
        fh.read.return_value = payload
        fo = MagicMock()
        fo.return_value.__enter__.return_value = fh
        return fo

    def test_theme_loaded_from_file( self, capsys ):
        cfg = { "theme": { "name": "default", "color": "blue" } }
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=True ), \
             patch.object( builtins, "open", self._fake_open( "yaml" ) ), \
             patch.object( orch_mod.yaml, "safe_load", return_value=cfg ):
            result = PresentationOrchestratorAgent._load_theme_config( "/src/themes/", "default", debug=True )
        assert result == cfg
        assert "Theme loaded" in capsys.readouterr().out

    def test_theme_file_missing_theme_key_falls_back( self ):
        from cosa.agents.presentation_generator.renderers.marp_text_renderer import DEFAULT_THEME_CONFIG
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=True ), \
             patch.object( builtins, "open", self._fake_open( "yaml" ) ), \
             patch.object( orch_mod.yaml, "safe_load", return_value={ "no_theme": 1 } ):
            result = PresentationOrchestratorAgent._load_theme_config( "/src/themes/", "default" )
        assert result is DEFAULT_THEME_CONFIG

    def test_theme_file_not_found_falls_back( self ):
        from cosa.agents.presentation_generator.renderers.marp_text_renderer import DEFAULT_THEME_CONFIG
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=False ):
            result = PresentationOrchestratorAgent._load_theme_config( "/src/themes/", "missing" )
        assert result is DEFAULT_THEME_CONFIG

    def test_theme_load_exception_falls_back_debug( self, capsys ):
        from cosa.agents.presentation_generator.renderers.marp_text_renderer import DEFAULT_THEME_CONFIG
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.path.exists", return_value=True ), \
             patch.object( builtins, "open", side_effect=OSError( "boom" ) ):
            result = PresentationOrchestratorAgent._load_theme_config( "/src/themes/", "default", debug=True )
        assert result is DEFAULT_THEME_CONFIG
        assert "fallback default theme" in capsys.readouterr().out


# ===========================================================================
# Content-gen — _analyze_async (MID)
# ===========================================================================
_NARR = "cosa.agents.presentation_generator.prompts.narrative"
_OUT  = "cosa.agents.presentation_generator.prompts.outline"
_ELAB = "cosa.agents.presentation_generator.prompts.elaboration"


class TestAnalyzeAsync:
    def test_dry_run_with_raw_sections( self, capsys, _silence_voice_io ):
        agent = _agent( dry_run=True, debug=True )
        agent._presentation_state[ "raw_sections" ] = [
            ( "H1", "word " * 250, 1 ), ( "H2", "short body", 2 ),
        ]
        sections = _run( agent._analyze_async( "src" ) )
        assert len( sections ) == 2
        assert all( isinstance( s, NarrativeSection ) for s in sections )
        # arc cycles; proposed_slides ≥ 1
        assert sections[ 0 ].proposed_slides >= 1
        assert "DRY RUN" in capsys.readouterr().out

    def test_dry_run_no_raw_sections_uses_default( self, _silence_voice_io ):
        agent = _agent( dry_run=True )
        agent._presentation_state[ "raw_sections" ] = []
        sections = _run( agent._analyze_async( "src" ) )
        assert len( sections ) == 1
        assert sections[ 0 ].heading == "Mock Section"

    def test_real_happy_with_arc_fallback( self, _silence_voice_io ):
        agent = _agent()
        agent._api_client = _mock_api_client()
        dicts = [
            { "heading": "Intro", "content_summary": "s", "arc_position": "setup", "proposed_slide_count": 2 },
            { "heading": "Bad", "content_summary": "s", "arc_position": "NOT_A_REAL_POS", "proposed_slide_count": 1 },
        ]
        with patch( f"{_NARR}.get_narrative_analysis_prompt", return_value="P" ), \
             patch( f"{_NARR}.parse_analysis_response", return_value=dicts ):
            sections = _run( agent._analyze_async( "src content" ) )
        assert len( sections ) == 2
        assert sections[ 1 ].arc_position == ArcPosition.ARGUMENT  # ValueError → fallback
        assert agent.metrics[ "api_calls" ] == 1

    def test_real_no_sections_raises_fail_loud( self, _silence_voice_io ):
        # D6-STRICT: an empty parse result is a degenerate deck — fail loud, do
        # NOT return []. (Defensive backstop branch: parser mocked to return [].)
        agent = _agent()
        agent._api_client = _mock_api_client()
        with patch( f"{_NARR}.get_narrative_analysis_prompt", return_value="P" ), \
             patch( f"{_NARR}.parse_analysis_response", return_value=[] ):
            with pytest.raises( ValueError, match="no usable sections" ):
                _run( agent._analyze_async( "src" ) )
        # the urgent fail-loud notify fired
        assert any( c.kwargs.get( "priority" ) == "urgent"
                    for c in _silence_voice_io[ "notify" ].await_args_list )

    def test_real_parse_failure_propagates( self, capsys, _silence_voice_io ):
        # The reviewer's scenario: a stub client returns refusal/garbage text; the
        # real D6-STRICT parser RAISES → _analyze_async must PROPAGATE (not return []).
        agent = _agent( debug=True )
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_analysis.return_value.content = "I cannot help with that request."
        with patch( f"{_NARR}.get_narrative_analysis_prompt", return_value="P" ):
            with pytest.raises( ValueError, match="recoverable JSON object" ):
                _run( agent._analyze_async( "src" ) )
        assert "Traceback" in capsys.readouterr().err

    def test_real_exception_returns_empty_debug_traceback( self, capsys, _silence_voice_io ):
        # A NON-parse API/runtime error still degrades to [] (do_all_async's
        # empty-guard then fails the job loudly downstream).
        agent = _agent( debug=True )
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_analysis = AsyncMock( side_effect=RuntimeError( "api down" ) )
        with patch( f"{_NARR}.get_narrative_analysis_prompt", return_value="P" ):
            assert _run( agent._analyze_async( "src" ) ) == []
        assert "Traceback" in capsys.readouterr().err


# ===========================================================================
# Content-gen — _outline_async (MID)
# ===========================================================================
class TestOutlineAsync:
    def test_dry_run_with_sections( self, capsys, _silence_voice_io ):
        agent = _agent( dry_run=True, debug=True )
        outlines = _run( agent._outline_async( [ _section( "S1" ), _section( "S2" ) ] ) )
        # 2 opening + body + 3 closing; budget 15 → 10 body
        assert len( outlines ) == 15
        assert outlines[ 0 ].arc_position == "opening"
        assert outlines[ -1 ].arc_position == "closing"
        assert "DRY RUN" in capsys.readouterr().out

    def test_dry_run_no_sections_body_point_titles( self, _silence_voice_io ):
        agent = _agent( dry_run=True )
        outlines = _run( agent._outline_async( [] ) )
        body = [ o for o in outlines if o.arc_position == "body" ]
        assert body and body[ 0 ].title.startswith( "[Mock] Body Point" )

    def test_real_happy_counts_and_tokens( self, _silence_voice_io ):
        agent = _agent()
        agent._api_client = _mock_api_client()
        dicts = [
            { "number": 1, "arc_position": "opening", "type": "title", "title": "T", "visual_type": "text_only" },
            { "number": 2, "arc_position": "body", "type": "key_point", "title": "B", "visual_type": "diagram", "source_hint": "h" },
            { "number": 3, "arc_position": "closing", "type": "cta", "title": "C", "visual_type": "text_only" },
        ]
        with patch( f"{_OUT}.get_outline_prompt", return_value="P" ), \
             patch( f"{_OUT}.parse_outline_response", return_value=dicts ):
            outlines = _run( agent._outline_async( [ _section() ] ) )
        assert len( outlines ) == 3
        assert agent.metrics[ "api_calls" ] == 1
        assert agent.metrics[ "tokens_used" ] == 42

    def test_real_structural_warning_branch( self, _silence_voice_io ):
        # 0 opening / 0 closing → warning branch (line 783-784)
        agent = _agent( debug=True )
        agent._api_client = _mock_api_client()
        dicts = [ { "number": 1, "arc_position": "body", "type": "key_point", "title": "B", "visual_type": "text_only" } ]
        with patch( f"{_OUT}.get_outline_prompt", return_value="P" ), \
             patch( f"{_OUT}.parse_outline_response", return_value=dicts ):
            outlines = _run( agent._outline_async( [ _section() ] ) )
        assert len( outlines ) == 1

    def test_real_parse_failure_propagates( self, _silence_voice_io ):
        # D6-STRICT: parser raises (refusal/garbage) → _outline_async PROPAGATES.
        # (debug=False → exercises the non-debug arm of the fail-loud handler.)
        agent = _agent()
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_outline.return_value.content = "Sorry, no."
        with patch( f"{_OUT}.get_outline_prompt", return_value="P" ):
            with pytest.raises( ValueError, match="recoverable JSON object" ):
                _run( agent._outline_async( [ _section() ] ) )
        assert any( c.kwargs.get( "priority" ) == "urgent"
                    for c in _silence_voice_io[ "notify" ].await_args_list )

    def test_real_parse_failure_propagates_debug_traceback( self, capsys, _silence_voice_io ):
        # debug=True → exercises the traceback arm of the fail-loud handler.
        agent = _agent( debug=True )
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_outline.return_value.content = "no json here"
        with patch( f"{_OUT}.get_outline_prompt", return_value="P" ):
            with pytest.raises( ValueError, match="recoverable JSON object" ):
                _run( agent._outline_async( [ _section() ] ) )
        assert "Traceback" in capsys.readouterr().err

    def test_real_exception_returns_empty( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_outline = AsyncMock( side_effect=RuntimeError( "boom" ) )
        with patch( f"{_OUT}.get_outline_prompt", return_value="P" ):
            assert _run( agent._outline_async( [ _section() ] ) ) == []
        assert "Traceback" in capsys.readouterr().err


# ===========================================================================
# Content-gen — _elaborate_async + _elaborate_chunked (MID)
# ===========================================================================
class TestElaborateAsync:
    def test_dry_run_title_and_keypoint_branches( self, capsys, _silence_voice_io ):
        agent = _agent( dry_run=True, debug=True )
        outline = [
            _outline( number=1, type="title", visual_type="text_only" ),
            _outline( number=2, arc="body", type="key_point", visual_type="diagram" ),
        ]
        slides = _run( agent._elaborate_async( outline ) )
        assert len( slides ) == 2
        # title slide → no bullets, no transition; key_point → bullets + transition + visual desc
        assert slides[ 0 ].content_bullets == []
        assert slides[ 0 ].presenter_notes.transition is None
        assert slides[ 1 ].content_bullets
        assert slides[ 1 ].visual_description is not None
        assert slides[ 1 ].presenter_notes.transition is not None
        assert "DRY RUN" in capsys.readouterr().out

    def test_real_happy( self, _silence_voice_io ):
        agent = _agent()
        agent._api_client = _mock_api_client()
        slide_dicts = [ {
            "number": 1, "arc_position": "opening", "type": "title", "title": "T",
            "subtitle": "sub", "visual_type": "text_only", "content_bullets": [ "a" ],
            "presenter_notes": { "transition": "t", "talking_points": [ "p" ], "timing_seconds": 90, "emphasis": "e" },
        } ]
        with patch( f"{_ELAB}.get_elaboration_prompt", return_value="P" ), \
             patch( f"{_ELAB}.parse_elaboration_response", return_value=slide_dicts ):
            slides = _run( agent._elaborate_async( [ _outline() ] ) )
        assert slides[ 0 ].subtitle == "sub"
        assert slides[ 0 ].presenter_notes.timing_seconds == 90
        assert agent.metrics[ "api_calls" ] == 1

    def test_real_truncation_triggers_chunked_fallback( self, _silence_voice_io ):
        agent = _agent()
        client = _mock_api_client()
        client.call_for_elaboration.return_value.stop_reason = "max_tokens"
        agent._api_client = client
        chunk_dicts = [ { "number": 1, "arc_position": "opening", "type": "title", "title": "T", "visual_type": "text_only" } ]
        agent._elaborate_chunked = AsyncMock( return_value=chunk_dicts )
        with patch( f"{_ELAB}.get_elaboration_prompt", return_value="P" ), \
             patch( f"{_ELAB}.parse_elaboration_response", return_value=[] ):
            slides = _run( agent._elaborate_async( [ _outline() ] ) )
        agent._elaborate_chunked.assert_awaited_once()
        assert len( slides ) == 1

    def test_real_parse_failure_complete_response_propagates( self, capsys, _silence_voice_io ):
        # D6-STRICT: a COMPLETE response (stop_reason == end_turn) that fails to
        # parse is a real defect → propagate, no chunked fallback, no empty deck.
        # (debug=True → exercises the traceback arm of the fail-loud handler.)
        agent = _agent( debug=True )
        client = _mock_api_client()                       # stop_reason defaults to "end_turn"
        client.call_for_elaboration.return_value.content = "I won't do that."
        agent._api_client = client
        agent._elaborate_chunked = AsyncMock()            # must NOT be called
        with patch( f"{_ELAB}.get_elaboration_prompt", return_value="P" ):
            with pytest.raises( ValueError, match="recoverable JSON object" ):
                _run( agent._elaborate_async( [ _outline() ] ) )
        agent._elaborate_chunked.assert_not_awaited()
        assert "Traceback" in capsys.readouterr().err
        assert any( c.kwargs.get( "priority" ) == "urgent"
                    for c in _silence_voice_io[ "notify" ].await_args_list )

    def test_real_truncated_parse_raise_triggers_chunked( self, _silence_voice_io ):
        # A TRUNCATED response whose real parse RAISES → recover via chunked
        # fallback (the failure is a length artifact, not garbage).
        agent = _agent()
        client = _mock_api_client()
        client.call_for_elaboration.return_value.content     = "truncated junk {"
        client.call_for_elaboration.return_value.stop_reason = "max_tokens"
        agent._api_client = client
        chunk_dicts = [ { "number": 1, "arc_position": "opening", "type": "title", "title": "T", "visual_type": "text_only" } ]
        agent._elaborate_chunked = AsyncMock( return_value=chunk_dicts )
        with patch( f"{_ELAB}.get_elaboration_prompt", return_value="P" ):
            slides = _run( agent._elaborate_async( [ _outline() ] ) )
        agent._elaborate_chunked.assert_awaited_once()
        assert len( slides ) == 1

    def test_real_parse_empty_complete_response_raises( self, _silence_voice_io ):
        # Defensive backstop: parser returns [] (mocked) on a COMPLETE response
        # (not truncated) → fail loud via the non-truncated empty branch.
        agent = _agent()
        agent._api_client = _mock_api_client()            # stop_reason "end_turn"
        agent._elaborate_chunked = AsyncMock()            # must NOT be called
        with patch( f"{_ELAB}.get_elaboration_prompt", return_value="P" ), \
             patch( f"{_ELAB}.parse_elaboration_response", return_value=[] ):
            with pytest.raises( ValueError, match="no usable slides" ):
                _run( agent._elaborate_async( [ _outline() ] ) )
        agent._elaborate_chunked.assert_not_awaited()

    def test_real_chunked_fallback_empty_raises( self, _silence_voice_io ):
        # Truncated → chunked fallback ALSO yields nothing → fail loud (no empty deck).
        agent = _agent()
        client = _mock_api_client()
        client.call_for_elaboration.return_value.content     = "truncated junk {"
        client.call_for_elaboration.return_value.stop_reason = "max_tokens"
        agent._api_client = client
        agent._elaborate_chunked = AsyncMock( return_value=[] )
        with patch( f"{_ELAB}.get_elaboration_prompt", return_value="P" ):
            with pytest.raises( ValueError, match="after truncation fallback" ):
                _run( agent._elaborate_async( [ _outline() ] ) )

    def test_real_exception_returns_empty( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_elaboration = AsyncMock( side_effect=RuntimeError( "x" ) )
        with patch( f"{_ELAB}.get_elaboration_prompt", return_value="P" ):
            assert _run( agent._elaborate_async( [ _outline() ] ) ) == []
        assert "Traceback" in capsys.readouterr().err


class TestElaborateChunked:
    def test_chunked_two_batches( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        agent._api_client = _mock_api_client()
        outline = [ _outline( number=i ) for i in range( 1, 8 ) ]  # 7 → 2 batches of 6+1
        with patch( f"{_ELAB}.get_elaboration_prompt", return_value="P" ), \
             patch( f"{_ELAB}.parse_elaboration_response", return_value=[ { "number": 1 } ] ):
            result = _run( agent._elaborate_chunked( outline, "src", "fb" ) )
        assert agent._api_client.call_for_elaboration.await_count == 2
        assert agent.metrics[ "api_calls" ] == 2
        assert len( result ) == 2
        assert "Chunked elaboration" in capsys.readouterr().out


# ===========================================================================
# Content-gen — _serialize_async (MID)
# ===========================================================================
class TestSerializeAsync:
    def test_serialize_title_from_title_slide( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        slides = [ _slide( number=1, type="title", title="My Real Title" ) ]
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.makedirs" ), patch.object( builtins, "open", MagicMock() ):
            pres = _run( agent._serialize_async( slides ) )
        assert pres.title == "My Real Title"
        assert agent._presentation_state[ "yaml_path" ].endswith( ".yaml" )
        assert "YAML written" in capsys.readouterr().out

    def test_serialize_title_from_filename_when_no_title_slide( self, _silence_voice_io ):
        agent = _agent( source_path="/io/src/quarterly-report.md" )
        slides = [ _slide( number=1, type="key_point", title="Not a title" ) ]
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch( "os.makedirs" ), patch.object( builtins, "open", MagicMock() ):
            pres = _run( agent._serialize_async( slides ) )
        assert pres.title == "quarterly-report"

    def test_serialize_exception_returns_none( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        agent.config = MagicMock( spec=PresentationConfig )
        agent.config.target_duration_minutes = 15
        agent.config.default_theme = "default"
        agent.config.get_output_path.side_effect = OSError( "no path" )
        slides = [ _slide( number=1, type="title", title="T" ) ]
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            assert _run( agent._serialize_async( slides ) ) is None
        assert "Traceback" in capsys.readouterr().err


# ===========================================================================
# Render/deliver — _render_text_async (MID)
# ===========================================================================
_RENDERERS = "cosa.agents.presentation_generator.renderers"


class TestRenderTextAsync:
    def test_none_presentation_skips( self, _silence_voice_io ):
        agent = _agent()
        _run( agent._render_text_async( None ) )  # no crash, early return

    def test_happy_writes_marp( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        pres = _presentation()
        with patch.object( agent, "_load_theme_config", return_value={ "theme": {} } ), \
             patch( f"{_RENDERERS}.MarpTextRenderer.render", return_value="MARP\n# slide" ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch.object( PresentationOrchestratorAgent, "_write_marp", MagicMock() ) as wm:
            _run( agent._render_text_async( pres ) )
        assert agent._presentation_state[ "marp_path" ].endswith( ".md" )
        wm.assert_called_once()
        assert "Marp written" in capsys.readouterr().out

    def test_exception_is_non_fatal( self, _silence_voice_io ):
        agent = _agent()
        pres = _presentation()
        with patch.object( agent, "_load_theme_config", side_effect=RuntimeError( "theme boom" ) ):
            _run( agent._render_text_async( pres ) )  # swallowed; urgent notify fired
        assert any( c.kwargs.get( "priority" ) == "urgent"
                    for c in _silence_voice_io[ "notify" ].await_args_list )


# ===========================================================================
# Render/deliver — _render_visuals_async (THORNY) + _build_visual_registry
# ===========================================================================
class TestRenderVisualsAsync:
    def _registry_with( self, render_return ):
        renderer = MagicMock()
        renderer.render = AsyncMock( return_value=render_return )
        registry = MagicMock()
        registry.get.return_value = renderer
        return registry, renderer

    def test_none_presentation_skips( self, _silence_voice_io ):
        agent = _agent()
        agent._presentation_state[ "marp_path" ] = "/p/x.md"
        _run( agent._render_visuals_async( None ) )

    def test_none_marp_path_skips( self, _silence_voice_io ):
        agent = _agent()
        agent._presentation_state[ "marp_path" ] = None
        _run( agent._render_visuals_async( _presentation() ) )

    def test_marp_content_none_skips( self, _silence_voice_io ):
        agent = _agent()
        agent._presentation_state[ "marp_path" ] = "/p/x.md"
        with patch.object( PresentationOrchestratorAgent, "_read_file_or_none", MagicMock( return_value=None ) ):
            _run( agent._render_visuals_async( _presentation() ) )

    def test_no_placeholders( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        agent._presentation_state[ "marp_path" ] = "/p/x.md"
        with patch.object( PresentationOrchestratorAgent, "_read_file_or_none", MagicMock( return_value="# no visuals here" ) ):
            _run( agent._render_visuals_async( _presentation() ) )
        assert agent._presentation_state[ "visuals_rendered" ] == 0

    def test_happy_renders_visual( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        # Hermetic: pre-seed the lazy api_client so the real PresentationAPIClient is
        # never constructed (it raises ValueError when the gitignored firewalled key is
        # absent — clean checkouts / CI). The renderer.render call is mocked, so the
        # forwarded api_client value is never exercised.
        agent._api_client = MagicMock()
        agent._presentation_state[ "marp_path" ] = "/p/x.md"
        marp = "## S\n<!-- VISUAL: diagram | a flow diagram -->\n"
        slide = _slide( visual_type="diagram", visual_description="a flow diagram", title="Flow Slide" )
        # extra text_only slide → exercises the False arm of the slide_titles filter loop
        text_slide = _slide( number=2, type="key_point", visual_type="text_only", title="Plain" )
        pres  = _presentation( slides=[ slide, text_slide ] )
        registry, renderer = self._registry_with( "```mermaid\nA-->B\n```" )
        with patch.object( agent, "_build_visual_registry", return_value=registry ), \
             patch.object( PresentationOrchestratorAgent, "_read_file_or_none", MagicMock( return_value=marp ) ), \
             patch.object( PresentationOrchestratorAgent, "_write_marp", MagicMock() ) as wm, \
             patch( "os.makedirs" ):
            _run( agent._render_visuals_async( pres ) )
        assert agent._presentation_state[ "visuals_rendered" ] == 1
        renderer.render.assert_awaited_once()
        wm.assert_called_once()

    def test_renderer_returns_none_uses_placeholder_fallback( self, _silence_voice_io ):
        agent = _agent()
        # Hermetic: pre-seed the lazy api_client so the real PresentationAPIClient is
        # never constructed (it raises ValueError when the gitignored firewalled key is
        # absent — clean checkouts / CI). The renderer.render call is mocked.
        agent._api_client = MagicMock()
        agent._presentation_state[ "marp_path" ] = "/p/x.md"
        marp = "<!-- VISUAL: chart | bar chart of sales -->\n"
        pres = _presentation( slides=[ _slide( visual_type="chart", visual_description="bar chart of sales" ) ] )
        registry, _ = self._registry_with( None )  # renderer returns None → fallback
        ph = MagicMock()
        ph.render = AsyncMock( return_value="[placeholder]" )
        with patch.object( agent, "_build_visual_registry", return_value=registry ), \
             patch.object( PresentationOrchestratorAgent, "_read_file_or_none", MagicMock( return_value=marp ) ), \
             patch.object( PresentationOrchestratorAgent, "_write_marp", MagicMock() ), \
             patch( f"{_RENDERERS}.PlaceholderRenderer", return_value=ph ), \
             patch( "os.makedirs" ):
            _run( agent._render_visuals_async( pres ) )
        ph.render.assert_awaited_once()
        assert agent._presentation_state[ "visuals_rendered" ] == 1

    def test_exception_is_non_fatal( self, _silence_voice_io ):
        agent = _agent()
        agent._presentation_state[ "marp_path" ] = "/p/x.md"
        marp = "<!-- VISUAL: diagram | d -->\n"
        with patch.object( PresentationOrchestratorAgent, "_read_file_or_none", MagicMock( return_value=marp ) ), \
             patch.object( agent, "_build_visual_registry", side_effect=RuntimeError( "reg boom" ) ), \
             patch( "os.makedirs" ):
            _run( agent._render_visuals_async( _presentation() ) )
        assert any( c.kwargs.get( "priority" ) == "urgent"
                    for c in _silence_voice_io[ "notify" ].await_args_list )


class TestBuildVisualRegistry:
    def test_dry_run_only_fallback( self ):
        agent = _agent( dry_run=True )
        with patch( f"{_RENDERERS}.VisualRendererRegistry" ) as VRR, \
             patch( f"{_RENDERERS}.PlaceholderRenderer" ) as PH:
            registry = agent._build_visual_registry()
        assert registry is VRR.return_value
        registry.register.assert_not_called()  # dry_run → no renderers registered

    def test_real_registers_all_with_gemini( self ):
        agent = _agent( dry_run=False )
        with patch( f"{_RENDERERS}.VisualRendererRegistry" ) as VRR, \
             patch( f"{_RENDERERS}.PlaceholderRenderer" ), \
             patch( f"{_RENDERERS}.MermaidRenderer" ), \
             patch( f"{_RENDERERS}.MatplotlibRenderer" ), \
             patch( f"{_RENDERERS}.D2Renderer" ), \
             patch( f"{_RENDERERS}.NanoBananaRenderer" ), \
             patch( f"{_RENDERERS}.VeoRenderer" ), \
             patch( "cosa.agents.presentation_generator.gemini_client.GeminiImageClient" ):
            agent._build_visual_registry()
        # mermaid+matplotlib+d2+nano_banana+veo = 5 registrations
        assert VRR.return_value.register.call_count == 5

    def test_real_gemini_unavailable_warns( self ):
        agent = _agent( dry_run=False )
        with patch( f"{_RENDERERS}.VisualRendererRegistry" ) as VRR, \
             patch( f"{_RENDERERS}.PlaceholderRenderer" ), \
             patch( f"{_RENDERERS}.MermaidRenderer" ), \
             patch( f"{_RENDERERS}.MatplotlibRenderer" ), \
             patch( f"{_RENDERERS}.D2Renderer" ), \
             patch( f"{_RENDERERS}.NanoBananaRenderer" ), \
             patch( f"{_RENDERERS}.VeoRenderer" ), \
             patch( "cosa.agents.presentation_generator.gemini_client.GeminiImageClient",
                    side_effect=RuntimeError( "no api key" ) ):
            agent._build_visual_registry()
        # mermaid+matplotlib+d2 registered; gemini block raised before nano/veo → 3
        assert VRR.return_value.register.call_count == 3


# ===========================================================================
# Render/deliver — _deliver_async (MID)
# ===========================================================================
class TestDeliverAsync:
    def test_none_presentation_skips( self, _silence_voice_io ):
        agent = _agent()
        _run( agent._deliver_async( None ) )

    def test_happy_both_artifacts_exist_debug( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        agent._presentation_state[ "yaml_path" ]        = "/p/x.yaml"
        agent._presentation_state[ "marp_path" ]        = "/p/x.md"
        agent._presentation_state[ "visuals_rendered" ] = 2
        pres = _presentation( slides=[ _slide( notes=PresenterNotes( timing_seconds=120 ) ) ] )
        with patch( "os.path.exists", return_value=True ), patch( "os.path.getsize", return_value=2048 ):
            _run( agent._deliver_async( pres ) )
        summ = agent._presentation_state[ "delivery_summary" ]
        assert summ[ "artifacts" ][ "yaml" ][ "exists" ] is True
        assert summ[ "total_timing_secs" ] == 120
        assert "Delivery summary" in capsys.readouterr().out

    def test_missing_yaml_and_none_marp_paths( self, _silence_voice_io ):
        agent = _agent()
        agent._presentation_state[ "yaml_path" ] = "/p/x.yaml"  # exists False → missing+warning
        agent._presentation_state[ "marp_path" ] = None         # falsy → else, no warning
        with patch( "os.path.exists", return_value=False ):
            _run( agent._deliver_async( _presentation() ) )
        summ = agent._presentation_state[ "delivery_summary" ]
        assert summ[ "artifacts" ][ "yaml" ][ "exists" ] is False
        assert summ[ "artifacts" ][ "marp" ][ "exists" ] is False


# ===========================================================================
# Render/deliver — _export_pptx_async (THORNY — subprocess) (MID)
# ===========================================================================
def _proc( returncode=0, out=b"", err=b"" ):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock( return_value=( out, err ) )
    return proc


class TestExportPptxAsync:
    def test_disabled_in_config( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        agent.config.pptx_export_enabled = False
        _run( agent._export_pptx_async( _presentation() ) )
        assert "PPTX export disabled" in capsys.readouterr().out

    def test_dry_run_skips( self, capsys, _silence_voice_io ):
        agent = _agent( dry_run=True, debug=True )
        agent.config.pptx_export_enabled = True
        _run( agent._export_pptx_async( _presentation() ) )
        assert "PPTX export skipped (dry run)" in capsys.readouterr().out

    def test_no_marp_path_skips( self, _silence_voice_io ):
        agent = _agent()
        agent.config.pptx_export_enabled = True
        agent._presentation_state[ "marp_path" ] = None
        _run( agent._export_pptx_async( _presentation() ) )

    def test_marp_path_missing_on_disk_skips( self, _silence_voice_io ):
        agent = _agent()
        agent.config.pptx_export_enabled = True
        agent._presentation_state[ "marp_path" ] = "/p/x.md"
        with patch( "os.path.exists", return_value=False ):
            _run( agent._export_pptx_async( _presentation() ) )

    def test_success( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        agent.config.pptx_export_enabled = True
        agent._presentation_state[ "marp_path" ] = "/p/x.md"
        with patch( "os.path.exists", return_value=True ), \
             patch( "os.path.getsize", return_value=51200 ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch.object( orch_mod.asyncio, "create_subprocess_exec",
                           new=AsyncMock( return_value=_proc( returncode=0 ) ) ):
            _run( agent._export_pptx_async( _presentation() ) )
        assert agent._presentation_state[ "pptx_path" ].endswith( ".pptx" )
        assert "PPTX written" in capsys.readouterr().out

    def test_nonzero_returncode_warns( self, _silence_voice_io ):
        agent = _agent()
        agent.config.pptx_export_enabled = True
        agent._presentation_state[ "marp_path" ] = "/p/x.md"
        with patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch.object( orch_mod.asyncio, "create_subprocess_exec",
                           new=AsyncMock( return_value=_proc( returncode=1, err=b"marp broke" ) ) ):
            _run( agent._export_pptx_async( _presentation() ) )
        assert "pptx_path" not in agent._presentation_state

    def test_marp_cli_not_found( self, _silence_voice_io ):
        agent = _agent()
        agent.config.pptx_export_enabled = True
        agent._presentation_state[ "marp_path" ] = "/p/x.md"
        with patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch.object( orch_mod.asyncio, "create_subprocess_exec",
                           new=AsyncMock( side_effect=FileNotFoundError() ) ):
            _run( agent._export_pptx_async( _presentation() ) )
        msgs = [ c.args[ 0 ] for c in _silence_voice_io[ "notify" ].await_args_list ]
        assert any( "Marp CLI not installed" in m for m in msgs )

    def test_generic_exception( self, _silence_voice_io ):
        agent = _agent()
        agent.config.pptx_export_enabled = True
        agent._presentation_state[ "marp_path" ] = "/p/x.md"
        with patch( "os.path.exists", return_value=True ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch.object( orch_mod.asyncio, "create_subprocess_exec",
                           new=AsyncMock( side_effect=RuntimeError( "kaboom" ) ) ):
            _run( agent._export_pptx_async( _presentation() ) )
        assert any( c.kwargs.get( "priority" ) == "medium"
                    for c in _silence_voice_io[ "notify" ].await_args_list )


# ===========================================================================
# Gates — _gate_1 / _gate_2 / _gate_3 (review/revise/cancel loops) (MID)
# ===========================================================================
def _ans( key, value ):
    return { "answers": { key: value } }


class TestGate1NarrativeReview:
    def test_empty_sections_refuses_to_proceed( self, capsys, _silence_voice_io ):
        # D6-STRICT: empty sections → do NOT auto-approve (was return True).
        agent = _agent( debug=True )
        assert _run( agent._gate_1_narrative_review( [] ) ) is False

    def test_dry_run_auto_approve( self, _silence_voice_io ):
        agent = _agent( dry_run=True )
        assert _run( agent._gate_1_narrative_review( [ _section() ] ) ) is True

    def test_approve( self, _silence_voice_io ):
        agent = _agent()
        _silence_voice_io[ "choices" ].return_value = _ans( "Narrative Arc", "Approve" )
        assert _run( agent._gate_1_narrative_review( [ _section() ] ) ) is True

    def test_cancel( self, _silence_voice_io ):
        agent = _agent()
        _silence_voice_io[ "choices" ].return_value = _ans( "Narrative Arc", "Cancel" )
        assert _run( agent._gate_1_narrative_review( [ _section() ] ) ) is False

    def test_revise_max_revisions_reached( self, _silence_voice_io ):
        agent = _agent()
        agent._presentation_state[ "revision_count" ] = agent.config.max_revisions
        _silence_voice_io[ "choices" ].return_value = _ans( "Narrative Arc", "Revise" )
        assert _run( agent._gate_1_narrative_review( [ _section() ] ) ) is True

    def test_revise_with_feedback_then_approve( self, _silence_voice_io ):
        agent = _agent()
        agent._analyze_async = AsyncMock( return_value=[ _section( "New" ) ] )
        _silence_voice_io[ "choices" ].side_effect = [
            _ans( "Narrative Arc", "Revise" ), _ans( "Narrative Arc", "Approve" ),
        ]
        _silence_voice_io[ "input" ].return_value = "merge sections"
        assert _run( agent._gate_1_narrative_review( [ _section() ] ) ) is True
        assert agent._presentation_state[ "revision_count" ] == 1
        agent._analyze_async.assert_awaited_once()

    def test_revise_empty_feedback_approves( self, _silence_voice_io ):
        agent = _agent()
        _silence_voice_io[ "choices" ].return_value = _ans( "Narrative Arc", "Revise" )
        _silence_voice_io[ "input" ].return_value = ""
        assert _run( agent._gate_1_narrative_review( [ _section() ] ) ) is True

    def test_voice_io_exception_auto_approves( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        _silence_voice_io[ "choices" ].side_effect = RuntimeError( "voice down" )
        assert _run( agent._gate_1_narrative_review( [ _section() ] ) ) is True


class TestGate2OutlineReview:
    def test_empty_outline_refuses_to_proceed( self, _silence_voice_io ):
        # D6-STRICT: empty outline → do NOT auto-approve (was return True).
        assert _run( _agent( debug=True )._gate_2_outline_review( [] ) ) is False

    def test_dry_run_auto_approve( self, _silence_voice_io ):
        assert _run( _agent( dry_run=True )._gate_2_outline_review( [ _outline() ] ) ) is True

    def test_approve_clears_feedback( self, _silence_voice_io ):
        agent = _agent()
        agent._presentation_state[ "human_feedback" ] = "stale"
        _silence_voice_io[ "choices" ].return_value = _ans( "Slide Outline", "Approve" )
        assert _run( agent._gate_2_outline_review( [ _outline() ] ) ) is True
        assert agent._presentation_state[ "human_feedback" ] is None

    def test_cancel( self, _silence_voice_io ):
        agent = _agent()
        _silence_voice_io[ "choices" ].return_value = _ans( "Slide Outline", "Cancel" )
        assert _run( agent._gate_2_outline_review( [ _outline() ] ) ) is False

    def test_revise_max_reached( self, _silence_voice_io ):
        agent = _agent()
        agent._presentation_state[ "outline_revision_count" ] = agent.config.max_revisions
        _silence_voice_io[ "choices" ].return_value = _ans( "Slide Outline", "Revise" )
        assert _run( agent._gate_2_outline_review( [ _outline() ] ) ) is True

    def test_revise_with_feedback_then_approve( self, _silence_voice_io ):
        agent = _agent()
        agent._outline_async = AsyncMock( return_value=[ _outline( number=2 ) ] )
        _silence_voice_io[ "choices" ].side_effect = [
            _ans( "Slide Outline", "Revise" ), _ans( "Slide Outline", "Approve" ),
        ]
        _silence_voice_io[ "input" ].return_value = "add a comparison slide"
        assert _run( agent._gate_2_outline_review( [ _outline() ] ) ) is True
        assert agent._presentation_state[ "outline_revision_count" ] == 1

    def test_revise_empty_feedback_approves( self, _silence_voice_io ):
        agent = _agent()
        _silence_voice_io[ "choices" ].return_value = _ans( "Slide Outline", "Revise" )
        _silence_voice_io[ "input" ].return_value = ""
        assert _run( agent._gate_2_outline_review( [ _outline() ] ) ) is True

    def test_exception_auto_approves( self, _silence_voice_io ):
        agent = _agent( debug=True )
        _silence_voice_io[ "choices" ].side_effect = RuntimeError( "x" )
        assert _run( agent._gate_2_outline_review( [ _outline() ] ) ) is True


class TestGate3ContentReview:
    def _slides_with_visual( self ):
        return [ _slide( visual_type="diagram", title="A", bullets=[ "b" ] ),
                 _slide( number=2, type="key_point", visual_type="text_only", title="B" ) ]

    def test_empty_slides_refuses_to_proceed( self, _silence_voice_io ):
        # D6-STRICT: empty slides → do NOT auto-approve (was return True).
        assert _run( _agent( debug=True )._gate_3_content_review( [] ) ) is False

    def test_dry_run_auto_approve( self, _silence_voice_io ):
        assert _run( _agent( dry_run=True )._gate_3_content_review( self._slides_with_visual() ) ) is True

    def test_approve_clears_feedback( self, _silence_voice_io ):
        agent = _agent()
        agent._presentation_state[ "human_feedback" ] = "stale"
        _silence_voice_io[ "choices" ].return_value = _ans( "Content Review", "Approve" )
        assert _run( agent._gate_3_content_review( self._slides_with_visual() ) ) is True
        assert agent._presentation_state[ "human_feedback" ] is None

    def test_cancel( self, _silence_voice_io ):
        agent = _agent()
        _silence_voice_io[ "choices" ].return_value = _ans( "Content Review", "Cancel" )
        assert _run( agent._gate_3_content_review( self._slides_with_visual() ) ) is False

    def test_revise_max_reached( self, _silence_voice_io ):
        agent = _agent()
        agent._presentation_state[ "elaborate_revision_count" ] = agent.config.max_revisions
        _silence_voice_io[ "choices" ].return_value = _ans( "Content Review", "Revise" )
        assert _run( agent._gate_3_content_review( self._slides_with_visual() ) ) is True

    def test_revise_with_feedback_then_approve( self, _silence_voice_io ):
        agent = _agent()
        agent._elaborate_async = AsyncMock( return_value=[ _slide( number=3 ) ] )
        _silence_voice_io[ "choices" ].side_effect = [
            _ans( "Content Review", "Revise" ), _ans( "Content Review", "Approve" ),
        ]
        _silence_voice_io[ "input" ].return_value = "slide 3 needs more data"
        assert _run( agent._gate_3_content_review( self._slides_with_visual() ) ) is True
        assert agent._presentation_state[ "elaborate_revision_count" ] == 1

    def test_revise_empty_feedback_approves( self, _silence_voice_io ):
        agent = _agent()
        _silence_voice_io[ "choices" ].return_value = _ans( "Content Review", "Revise" )
        _silence_voice_io[ "input" ].return_value = ""
        assert _run( agent._gate_3_content_review( self._slides_with_visual() ) ) is True

    def test_exception_auto_approves( self, _silence_voice_io ):
        agent = _agent( debug=True )
        _silence_voice_io[ "choices" ].side_effect = RuntimeError( "x" )
        assert _run( agent._gate_3_content_review( self._slides_with_visual() ) ) is True


# ===========================================================================
# Gate 4 — review/cancel branches (post BUG-A fix: present_choices(questions=[...]
# /title=) + dict parse on header "Visual Review", mirroring Gates 1-3).
# ===========================================================================
class TestGate4RenderReview:
    def test_dry_run_auto_approve( self, _silence_voice_io ):
        assert _run( _agent( dry_run=True )._gate_4_render_review( _presentation() ) ) is True

    def test_no_visuals_auto_approve( self, _silence_voice_io ):
        agent = _agent( debug=True )
        agent._presentation_state[ "visuals_rendered" ] = 0
        assert _run( agent._gate_4_render_review( _presentation() ) ) is True

    def test_approve( self, _silence_voice_io ):
        agent = _agent()
        agent._presentation_state[ "visuals_rendered" ] = 2
        _silence_voice_io[ "choices" ].return_value = _ans( "Visual Review", "Approve" )
        assert _run( agent._gate_4_render_review( _presentation() ) ) is True

    def test_missing_key_defaults_to_approve( self, _silence_voice_io ):
        agent = _agent()
        agent._presentation_state[ "visuals_rendered" ] = 1
        _silence_voice_io[ "choices" ].return_value = { "answers": {} }  # no header → default Approve
        assert _run( agent._gate_4_render_review( _presentation() ) ) is True

    def test_cancel( self, _silence_voice_io ):
        agent = _agent()
        agent._presentation_state[ "visuals_rendered" ] = 1
        _silence_voice_io[ "choices" ].return_value = _ans( "Visual Review", "Cancel" )
        assert _run( agent._gate_4_render_review( _presentation() ) ) is False

    def test_exception_auto_approves( self, _silence_voice_io ):
        agent = _agent()
        agent._presentation_state[ "visuals_rendered" ] = 1
        _silence_voice_io[ "choices" ].side_effect = RuntimeError( "voice down" )
        assert _run( agent._gate_4_render_review( _presentation() ) ) is True


# ===========================================================================
# POST-FIX CONTRACT GUARDS — both BUG A + BUG B are FIXED (Tiberius's prod
# batch). The former xfail-strict tripwires are now plain passing regression
# guards on the now-live paths; the buggy-behavior pin tests were deleted (the
# bugs they pinned no longer exist). These lock the fixed contract in place.
# ===========================================================================
class TestPostFixContractGuards:

    # ---- BUG A (fixed): Gate 4 uses the real present_choices signature -----
    def test_gate4_uses_correct_present_choices_signature( self, _silence_voice_io ):
        """Gate 4 invokes present_choices with the REAL signature (questions,
        timeout, title, abstract, job_id) WITHOUT raising — `reached` proves the
        stub body ran (a wrong-kwarg call would TypeError before it)."""
        agent = _agent()
        agent._presentation_state[ "visuals_rendered" ] = 2
        reached = { "ok": False }

        async def strict_present_choices( questions, timeout=120, title=None, abstract=None, job_id=None ):
            reached[ "ok" ] = True
            return { "answers": { "Visual Review": "Approve" } }

        with patch.object( orch_mod.voice_io, "present_choices", new=strict_present_choices ), \
             patch.object( orch_mod.voice_io, "notify", new=AsyncMock() ):
            result = _run( agent._gate_4_render_review( _presentation() ) )
        assert reached[ "ok" ] is True
        assert result is True

    def test_gate4_cancel_under_real_signature_returns_false( self, _silence_voice_io ):
        """The now-LIVE Cancel path: a real-signature present_choices returning
        'Cancel' under the 'Visual Review' header makes Gate 4 return False."""
        agent = _agent()
        agent._presentation_state[ "visuals_rendered" ] = 2

        async def strict_present_choices( questions, timeout=120, title=None, abstract=None, job_id=None ):
            return { "answers": { "Visual Review": "Cancel" } }

        with patch.object( orch_mod.voice_io, "present_choices", new=strict_present_choices ), \
             patch.object( orch_mod.voice_io, "notify", new=AsyncMock() ):
            assert _run( agent._gate_4_render_review( _presentation() ) ) is False

    # ---- BUG B (fixed): _ingest_async propagates+handles FileNotFoundError --
    def test_ingest_missing_file_hits_notfound_branch( self, _silence_voice_io ):
        """The now-LIVE handler: a genuinely missing source file makes
        _read_file_or_raise raise FileNotFoundError, which _ingest_async's
        `except FileNotFoundError` (orchestrator.py:396-399) catches → notifies
        'not found' and returns None."""
        agent = _agent( source_path="/abs/definitely-missing-xyz.md" )
        notify = AsyncMock()
        with patch.object( orch_mod.voice_io, "notify", new=notify ):
            assert _run( agent._ingest_async() ) is None
        msgs = [ c.args[ 0 ] for c in notify.await_args_list ]
        assert any( "not found" in m for m in msgs )


# ===========================================================================
# Branch completers — the False/alternate arms of debug + hasattr branches
# that the primary group tests don't reach (genuine 100% branch coverage).
# ===========================================================================
def _resp_without_tokens():
    """A response object that genuinely lacks `tokens_used` (MagicMock always has it)."""
    return types.SimpleNamespace( content="RAW", stop_reason="end_turn" )


class TestBranchCompleters:
    # _analyze_async: debug=True happy (line 659) + debug=False except (672->675)
    def test_analyze_happy_debug_print( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        agent._api_client = _mock_api_client()
        dicts = [ { "heading": "H", "content_summary": "s", "arc_position": "setup", "proposed_slide_count": 2 } ]
        with patch( f"{_NARR}.get_narrative_analysis_prompt", return_value="P" ), \
             patch( f"{_NARR}.parse_analysis_response", return_value=dicts ):
            _run( agent._analyze_async( "src" ) )
        assert "Narrative analysis:" in capsys.readouterr().out

    def test_analyze_exception_no_debug( self, _silence_voice_io ):
        agent = _agent( debug=False )
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_analysis = AsyncMock( side_effect=RuntimeError( "x" ) )
        with patch( f"{_NARR}.get_narrative_analysis_prompt", return_value="P" ):
            assert _run( agent._analyze_async( "src" ) ) == []

    # _outline_async: response missing tokens_used (756->760) + debug=False except (796->799)
    def test_outline_happy_no_tokens_attr( self, _silence_voice_io ):
        agent = _agent()
        client = MagicMock()
        client.call_for_outline = AsyncMock( return_value=_resp_without_tokens() )
        agent._api_client = client
        dicts = [ { "number": 1, "arc_position": "opening", "type": "title", "title": "T", "visual_type": "text_only" } ]
        with patch( f"{_OUT}.get_outline_prompt", return_value="P" ), \
             patch( f"{_OUT}.parse_outline_response", return_value=dicts ):
            outlines = _run( agent._outline_async( [ _section() ] ) )
        assert len( outlines ) == 1
        assert agent.metrics[ "tokens_used" ] == 0  # no tokens_used attr → not incremented

    def test_outline_exception_no_debug( self, _silence_voice_io ):
        agent = _agent( debug=False )
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_outline = AsyncMock( side_effect=RuntimeError( "x" ) )
        with patch( f"{_OUT}.get_outline_prompt", return_value="P" ):
            assert _run( agent._outline_async( [ _section() ] ) ) == []

    # _elaborate_async: debug=True happy + response missing tokens_used (875->879, 913)
    #                   + debug=False except (926->929)
    def test_elaborate_happy_debug_no_tokens_attr( self, capsys, _silence_voice_io ):
        agent = _agent( debug=True )
        client = MagicMock()
        client.call_for_elaboration = AsyncMock( return_value=_resp_without_tokens() )
        agent._api_client = client
        slide_dicts = [ { "number": 1, "arc_position": "opening", "type": "title", "title": "T",
                          "visual_type": "text_only" } ]
        with patch( f"{_ELAB}.get_elaboration_prompt", return_value="P" ), \
             patch( f"{_ELAB}.parse_elaboration_response", return_value=slide_dicts ):
            slides = _run( agent._elaborate_async( [ _outline() ] ) )
        assert len( slides ) == 1
        assert agent.metrics[ "tokens_used" ] == 0
        assert "Elaboration:" in capsys.readouterr().out

    def test_elaborate_exception_no_debug( self, _silence_voice_io ):
        agent = _agent( debug=False )
        agent._api_client = _mock_api_client()
        agent._api_client.call_for_elaboration = AsyncMock( side_effect=RuntimeError( "x" ) )
        with patch( f"{_ELAB}.get_elaboration_prompt", return_value="P" ):
            assert _run( agent._elaborate_async( [ _outline() ] ) ) == []

    # _elaborate_chunked: debug=False (958->961)
    def test_chunked_no_debug( self, _silence_voice_io ):
        agent = _agent( debug=False )
        agent._api_client = _mock_api_client()
        with patch( f"{_ELAB}.get_elaboration_prompt", return_value="P" ), \
             patch( f"{_ELAB}.parse_elaboration_response", return_value=[ { "number": 1 } ] ):
            result = _run( agent._elaborate_chunked( [ _outline() ], "src" ) )
        assert len( result ) == 1

    # _serialize_async: debug=False except (1048->1051)
    def test_serialize_exception_no_debug( self, _silence_voice_io ):
        agent = _agent( debug=False )
        agent.config = MagicMock( spec=PresentationConfig )
        agent.config.target_duration_minutes = 15
        agent.config.default_theme = "default"
        agent.config.get_output_path.side_effect = OSError( "no path" )
        with patch( "cosa.utils.util.get_project_root", return_value="/proj" ):
            assert _run( agent._serialize_async( [ _slide( type="title" ) ] ) ) is None

    # _render_text_async: debug=False happy (1175->1181)
    def test_render_text_happy_no_debug( self, _silence_voice_io ):
        agent = _agent( debug=False )
        with patch.object( agent, "_load_theme_config", return_value={ "theme": {} } ), \
             patch( f"{_RENDERERS}.MarpTextRenderer.render", return_value="MARP" ), \
             patch( "cosa.utils.util.get_project_root", return_value="/proj" ), \
             patch.object( PresentationOrchestratorAgent, "_write_marp", MagicMock() ):
            _run( agent._render_text_async( _presentation() ) )
        assert agent._presentation_state[ "marp_path" ].endswith( ".md" )

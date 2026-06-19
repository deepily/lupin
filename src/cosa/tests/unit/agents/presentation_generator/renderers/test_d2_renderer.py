#!/usr/bin/env python3
"""
Unit tests for renderers/d2_renderer.py

LLM-backed D2 renderer with d2-CLI SVG compilation. Boundaries mocked:
  - shutil.which (CLI availability)
  - subprocess.run (d2 CLI execution, via run_in_executor)
  - os.makedirs / os.path.exists
  - injected api_client (call_for_d2)
No real CLI / subprocess / disk.
"""

import asyncio
import subprocess
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.presentation_generator.renderers import d2_renderer as d2mod
from cosa.agents.presentation_generator.renderers.d2_renderer import D2Renderer


def _run( coro ):
    return asyncio.run( coro )


def _client( content="```d2\na -> b\n```" ):
    client = MagicMock()
    resp = MagicMock()
    resp.content = content
    client.call_for_d2 = AsyncMock( return_value=resp )
    return client


# ---------------------------------------------------------------------------
# _extract_d2_code
# ---------------------------------------------------------------------------
class TestExtractD2:
    def test_fenced_labelled( self ):
        out = D2Renderer._extract_d2_code( "```d2\na -> b -> c\n```" )
        assert "a -> b -> c" in out and "```" not in out

    def test_fenced_bare( self ):
        out = D2Renderer._extract_d2_code( "intro\n```\nserver -> db: q\n```" )
        assert "server -> db" in out

    def test_bare_arrows_with_leading_text( self ):
        out = D2Renderer._extract_d2_code( "preamble line\napi -> auth -> db" )
        assert "api -> auth -> db" in out
        assert "preamble" not in out   # leading non-node text stripped

    def test_no_match( self ):
        assert D2Renderer._extract_d2_code( "regular text no arrows" ) is None

    def test_empty_and_none( self ):
        assert D2Renderer._extract_d2_code( "" ) is None
        assert D2Renderer._extract_d2_code( None ) is None


# ---------------------------------------------------------------------------
# _check_d2_available
# ---------------------------------------------------------------------------
class TestCheckAvailable:
    def test_available_debug( self, capsys ):
        r = D2Renderer( debug=True )
        with patch.object( d2mod.shutil, "which", return_value="/usr/bin/d2" ):
            assert r._check_d2_available() is True
            # cached → second call doesn't re-query
            assert r._check_d2_available() is True
        assert "d2 CLI found" in capsys.readouterr().out

    def test_not_available_warns( self ):
        r = D2Renderer()
        with patch.object( d2mod.shutil, "which", return_value=None ):
            assert r._check_d2_available() is False


# ---------------------------------------------------------------------------
# _render_d2
# ---------------------------------------------------------------------------
class TestRenderD2:
    def _patch_run( self, returncode=0, stderr="", exc=None ):
        result = MagicMock( returncode=returncode, stderr=stderr )
        if exc:
            return patch.object( d2mod.subprocess, "run", side_effect=exc )
        return patch.object( d2mod.subprocess, "run", return_value=result )

    def test_success( self ):
        r = D2Renderer()
        with self._patch_run( returncode=0 ), patch( "os.path.exists", return_value=True ):
            ok = _run( r._render_d2( 'a -> b\nicon: icons.terrastruct.com/x', "/out/x.svg", 0 ) )
        assert ok is True

    def test_nonzero_returncode( self ):
        r = D2Renderer()
        with self._patch_run( returncode=1, stderr="boom" ):
            assert _run( r._render_d2( "a -> b", "/out/x.svg" ) ) is False

    def test_timeout( self ):
        r = D2Renderer()
        with self._patch_run( exc=subprocess.TimeoutExpired( cmd="d2", timeout=30 ) ):
            assert _run( r._render_d2( "a -> b", "/out/x.svg" ) ) is False

    def test_generic_exception( self ):
        r = D2Renderer()
        with self._patch_run( exc=OSError( "exec fail" ) ):
            assert _run( r._render_d2( "a -> b", "/out/x.svg" ) ) is False


# ---------------------------------------------------------------------------
# render (full)
# ---------------------------------------------------------------------------
class TestRender:
    def test_cli_unavailable_returns_none( self ):
        r = D2Renderer()
        with patch.object( d2mod.shutil, "which", return_value=None ):
            assert _run( r.render( "architecture", "x", api_client=_client(), output_dir="/o" ) ) is None

    def test_no_api_client( self ):
        r = D2Renderer()
        with patch.object( d2mod.shutil, "which", return_value="/usr/bin/d2" ):
            assert _run( r.render( "architecture", "x", output_dir="/o" ) ) is None

    def test_no_output_dir( self ):
        r = D2Renderer()
        with patch.object( d2mod.shutil, "which", return_value="/usr/bin/d2" ):
            assert _run( r.render( "architecture", "x", api_client=_client() ) ) is None

    def test_success_with_title_debug( self, capsys ):
        r = D2Renderer( debug=True )
        result = MagicMock( returncode=0, stderr="" )
        with patch.object( d2mod.shutil, "which", return_value="/usr/bin/d2" ), \
             patch( "os.makedirs" ), patch( "os.path.exists", return_value=True ), \
             patch.object( d2mod.subprocess, "run", return_value=result ):
            out = _run( r.render( "architecture", "desc", api_client=_client(),
                                  output_dir="/o", slide_title="Arch", slide_index=2 ) )
        assert out == "![Arch](visuals/diagram-002.svg)"
        assert "[D2Renderer] Generated SVG" in capsys.readouterr().out

    def test_success_alt_text_from_description( self ):
        r = D2Renderer()
        result = MagicMock( returncode=0, stderr="" )
        with patch.object( d2mod.shutil, "which", return_value="/usr/bin/d2" ), \
             patch( "os.makedirs" ), patch( "os.path.exists", return_value=True ), \
             patch.object( d2mod.subprocess, "run", return_value=result ):
            out = _run( r.render( "architecture", "a long visual description here",
                                  api_client=_client(), output_dir="/o" ) )
        assert out.startswith( "![a long visual description here]" )

    def test_extract_fails_returns_none( self ):
        r = D2Renderer()
        with patch.object( d2mod.shutil, "which", return_value="/usr/bin/d2" ):
            out = _run( r.render( "architecture", "x", api_client=_client( content="no code here" ),
                                  output_dir="/o" ) )
        assert out is None

    def test_render_d2_fails_returns_none( self ):
        r = D2Renderer()
        result = MagicMock( returncode=1, stderr="err" )
        with patch.object( d2mod.shutil, "which", return_value="/usr/bin/d2" ), \
             patch( "os.makedirs" ), \
             patch.object( d2mod.subprocess, "run", return_value=result ):
            out = _run( r.render( "architecture", "x", api_client=_client(), output_dir="/o" ) )
        assert out is None

    def test_api_exception_returns_none( self ):
        r = D2Renderer()
        client = MagicMock()
        client.call_for_d2 = AsyncMock( side_effect=RuntimeError( "down" ) )
        with patch.object( d2mod.shutil, "which", return_value="/usr/bin/d2" ):
            assert _run( r.render( "architecture", "x", api_client=client, output_dir="/o" ) ) is None

    def test_supported_types( self ):
        assert D2Renderer.SUPPORTED_TYPES == [ "flowchart_d2", "architecture" ]


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )

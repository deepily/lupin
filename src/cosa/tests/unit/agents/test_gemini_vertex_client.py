#!/usr/bin/env python3
"""
Unit tests for GeminiVertexClient (row 3405f0b2) — Vertex Gemini text via google-genai.

Pins the ground-truth constructor shape Extra 2 proved live on the host:
vertexai=True, project from LUPIN_GCP_PROJECT_ID (fail-loud, no default), location
"global", ADC auth — NO api_key. No network and no real ADC here: google.genai.Client
is boundary-mocked, so the suite is :7999-clean (fast, no state, no spend).
"""
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

import cosa.agents.gemini_vertex_client as gvc_mod
from cosa.agents.gemini_vertex_client import GeminiVertexClient


def _client( **kw ):
    kw.setdefault( "model_name", "gemini-3.1-flash-lite" )
    kw.setdefault( "project",    "test-proj" )
    kw.setdefault( "location",   "global" )
    return GeminiVertexClient( **kw )


class TestConstruction:

    def test_injected_values_skip_the_resolvers( self ):
        """When project/location are passed, the resolvers must NOT be consulted."""
        with patch.object( gvc_mod, "resolve_gcp_project_id" ) as rp, \
             patch.object( gvc_mod, "resolve_gcp_location" ) as rl:
            c = _client()
            rp.assert_not_called()
            rl.assert_not_called()
        assert c.model_name == "gemini-3.1-flash-lite"
        assert c.project    == "test-proj"
        assert c.location   == "global"
        assert c._client is None                      # lazy — not built at construction

    def test_defaults_come_from_the_resolvers( self ):
        """Absent explicit values, project/location come from cosa.utils.gcp_project."""
        with patch.object( gvc_mod, "resolve_gcp_project_id", return_value="resolved-proj" ) as rp, \
             patch.object( gvc_mod, "resolve_gcp_location",   return_value="global" ) as rl:
            c = GeminiVertexClient( model_name="m" )
            rp.assert_called_once()
            rl.assert_called_once()
        assert c.project  == "resolved-proj"
        assert c.location == "global"

    def test_project_failure_is_loud_never_defaulted( self ):
        """A silently-defaulted project is how you call the wrong GCP account. The
        resolver raises when unresolvable, and construction must propagate it."""
        with patch.object( gvc_mod, "resolve_gcp_project_id", side_effect=RuntimeError( "no project" ) ), \
             patch.object( gvc_mod, "resolve_gcp_location", return_value="global" ):
            with pytest.raises( RuntimeError ):
                GeminiVertexClient( model_name="m" )


class TestVertexCallShape:

    def test_run_uses_vertex_mode_with_no_api_key( self ):
        """run() builds genai.Client(vertexai=True, project, location) — and CRUCIALLY
        passes NO api_key (ADC), then returns generate_content(...).text."""
        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = MagicMock( text="OK" )
        with patch( "google.genai.Client", return_value=fake_client ) as MockClient:
            out = _client().run( "Reply with exactly: OK" )
        assert out == "OK"
        _, kwargs = MockClient.call_args
        assert kwargs[ "vertexai" ] is True
        assert kwargs[ "project" ]  == "test-proj"
        assert kwargs[ "location" ] == "global"
        assert "api_key" not in kwargs                # ADC, not an API key
        fake_client.models.generate_content.assert_called_once_with(
            model="gemini-3.1-flash-lite", contents="Reply with exactly: OK"
        )

    def test_client_is_lazy_and_reused( self ):
        """The genai.Client is built once, on first call, then reused."""
        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = MagicMock( text="A" )
        with patch( "google.genai.Client", return_value=fake_client ) as MockClient:
            c = _client()
            assert MockClient.call_count == 0         # not built at construction
            c.run( "one" )
            c.run( "two" )
            assert MockClient.call_count == 1         # built once, reused

    def test_run_async_uses_aio_path( self ):
        """run_async() awaits client.aio.models.generate_content and returns .text."""
        import asyncio
        fake_client = MagicMock()
        fake_client.aio.models.generate_content = AsyncMock( return_value=MagicMock( text="OK-async" ) )
        with patch( "google.genai.Client", return_value=fake_client ) as MockClient:
            out = asyncio.run( _client().run_async( "hi" ) )
        assert out == "OK-async"
        _, kwargs = MockClient.call_args
        assert kwargs[ "vertexai" ] is True
        assert "api_key" not in kwargs
        fake_client.aio.models.generate_content.assert_awaited_once_with(
            model="gemini-3.1-flash-lite", contents="hi"
        )


import os


@pytest.mark.skipif(
    os.environ.get( "RUN_VERTEX_LIVE" ) != "1",
    reason="live Vertex call — opt in with RUN_VERTEX_LIVE=1 on a host with ADC + LUPIN_GCP_PROJECT_ID",
)
def test_live_vertex_flash_lite_returns():
    """Ground-truth proof (Extra 2, 2026-08-16): a real Vertex Flash-Lite call returns.
    Opt-in only — mutates nothing but spends a token and needs ADC, so it never runs
    in the default :7999 suite. Mirrors the proven constructor exactly."""
    from cosa.agents.gemini_vertex_client import GeminiVertexClient
    client = GeminiVertexClient( model_name="gemini-3.1-flash-lite" )   # project fail-loud, location "global"
    out = client.run( "Reply with exactly: OK" )
    assert "OK" in out


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )

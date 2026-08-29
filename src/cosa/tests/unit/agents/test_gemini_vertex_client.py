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

    def test_injected_project_skips_the_resolver( self ):
        """When project is passed, the project resolver must NOT be consulted. There is
        no location resolver anymore (e0f67a7d) — location is always caller-supplied."""
        with patch.object( gvc_mod, "resolve_gcp_project_id" ) as rp:
            c = _client()
            rp.assert_not_called()
        assert c.model_name == "gemini-3.1-flash-lite"
        assert c.project    == "test-proj"
        assert c.location   == "global"
        assert c._client is None                      # lazy — not built at construction

    def test_project_defaults_from_resolver_location_stays_explicit( self ):
        """Absent an explicit project it comes from the resolver; location is REQUIRED
        and passed by the caller — it is never resolved from anywhere."""
        with patch.object( gvc_mod, "resolve_gcp_project_id", return_value="resolved-proj" ) as rp:
            c = GeminiVertexClient( model_name="m", location="global" )
            rp.assert_called_once()
        assert c.project  == "resolved-proj"
        assert c.location == "global"

    def test_location_required_and_env_never_consulted( self, monkeypatch ):
        """Must-fail-red control (bug e0f67a7d / Caveat 2): location is a per-arm variable
        that MUST come from the caller, NEVER the environment. Omitting it fails loud even
        when LUPIN_GCP_LOCATION is set — that is the var the old resolve_gcp_location()
        default read (verified: it returns 'us-central1' under this env), so reintroducing
        that default makes this go red by returning 'us-central1' instead of raising."""
        monkeypatch.setenv( "LUPIN_GCP_LOCATION", "us-central1" )
        with pytest.raises( ValueError, match="requires an explicit location" ):
            GeminiVertexClient( model_name="m", project="test-proj", location=None )

    def test_project_failure_is_loud_never_defaulted( self ):
        """A silently-defaulted project is how you call the wrong GCP account. The
        resolver raises when unresolvable, and construction must propagate it."""
        with patch.object( gvc_mod, "resolve_gcp_project_id", side_effect=RuntimeError( "no project" ) ):
            with pytest.raises( RuntimeError ):
                GeminiVertexClient( model_name="m", location="global" )


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
            model="gemini-3.1-flash-lite", contents="Reply with exactly: OK", config=None
        )                                                 # no params supplied -> config=None (SDK defaults)

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
            model="gemini-3.1-flash-lite", contents="hi", config=None
        )                                                 # no params supplied -> config=None (SDK defaults)


class TestGenerationParamsReachSDK:
    """Bug 3067adf6: configured temperature/max_tokens must actually reach the
    SDK generate_content call — not merely exist in INI. Every assertion here
    inspects the GenerateContentConfig object handed to the SDK, not the INI."""

    def _config_from_run( self, generation_params ):
        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = MagicMock( text="OK" )
        with patch( "google.genai.Client", return_value=fake_client ):
            _client( generation_params=generation_params ).run( "hi" )
        _, kwargs = fake_client.models.generate_content.call_args
        return kwargs[ "config" ]

    def test_temperature_and_max_tokens_reach_the_sdk_config( self ):
        """The exact INI dict {temperature:0.0, max_tokens:4096} must arrive as a
        GenerateContentConfig with temperature 0.0 and max_output_tokens 4096."""
        cfg = self._config_from_run( { "temperature": 0.0, "max_tokens": 4096 } )
        assert cfg is not None                            # config forwarded, not dropped
        assert cfg.temperature       == 0.0
        assert cfg.max_output_tokens == 4096              # max_tokens MAPPED, not splatted

    def test_max_tokens_is_mapped_not_passed_verbatim( self ):
        """`max_tokens` is not a GenerateContentConfig field — a straight splat would
        drop it. Prove the value lands under the SDK name and NOT under max_tokens."""
        cfg = self._config_from_run( { "max_tokens": 1234 } )
        assert cfg.max_output_tokens == 1234
        assert not hasattr( cfg, "max_tokens" ) or getattr( cfg, "max_tokens", None ) is None

    def test_async_path_also_forwards_config( self ):
        """The async twin (:114) must forward config too — fixing only sync leaves
        the defect alive on whichever path the study uses."""
        import asyncio
        fake_client = MagicMock()
        fake_client.aio.models.generate_content = AsyncMock( return_value=MagicMock( text="OK" ) )
        with patch( "google.genai.Client", return_value=fake_client ):
            asyncio.run( _client( generation_params={ "temperature": 0.0, "max_tokens": 4096 } ).run_async( "hi" ) )
        _, kwargs = fake_client.aio.models.generate_content.call_args
        cfg = kwargs[ "config" ]
        assert cfg.temperature       == 0.0
        assert cfg.max_output_tokens == 4096

    def test_control_keys_are_dropped_not_forwarded( self ):
        """`stream` is a control-plane key the factory carries in the same dict; it is
        NOT a generation param and must be dropped, not error, not reach the config."""
        cfg = self._config_from_run( { "temperature": 0.2, "stream": False } )
        assert cfg.temperature == 0.2                     # real knob still forwarded
        # stream never becomes an SDK field
        assert getattr( cfg, "stream", None ) is None

    def test_debug_construction_line_prints_project_location_model( self, capsys ):
        """The debug line is the only record of WHICH project/location/model a run used;
        it was the one uncovered line in this module, so a broken f-string there would
        have shipped unnoticed."""
        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = MagicMock( text="OK" )
        with patch( "google.genai.Client", return_value=fake_client ):
            _client( debug=True ).run( "hi" )
        out = capsys.readouterr().out
        assert "project=test-proj"                in out
        assert "location=global"                  in out
        assert "model=gemini-3.1-flash-lite"      in out

    def test_seed_reaches_the_sdk_config( self ):
        """Row ae43a37c: temperature 0.0 alone does not pin a Gemini call — the seed has
        to arrive at generate_content too. Before the _GEN_KEY_MAP entry this dict raised
        "unknown generation param 'seed'", so this test goes red on any revert."""
        cfg = self._config_from_run( { "temperature": 0.0, "max_tokens": 4096, "seed": 20260817 } )
        assert cfg.temperature       == 0.0
        assert cfg.max_output_tokens == 4096
        assert cfg.seed              == 20260817

    def test_seed_reaches_the_sdk_config_on_the_async_path( self ):
        """The study's harness can run either path; a seed that only lands on the sync
        twin leaves the regeneration unpinned wherever the async twin is used."""
        import asyncio
        fake_client = MagicMock()
        fake_client.aio.models.generate_content = AsyncMock( return_value=MagicMock( text="OK" ) )
        with patch( "google.genai.Client", return_value=fake_client ):
            asyncio.run( _client( generation_params={ "seed": 20260817 } ).run_async( "hi" ) )
        _, kwargs = fake_client.aio.models.generate_content.call_args
        assert kwargs[ "config" ].seed == 20260817

    def test_unknown_param_fails_loud( self ):
        """A typo like `maxtokens` must raise at construction, never silent-drop —
        silent drop is the exact bug class 3067adf6 is."""
        with pytest.raises( ValueError, match="unknown generation param" ):
            _client( generation_params={ "maxtokens": 4096 } )

    def test_no_params_means_no_config( self ):
        """Absent generation_params, _build_gen_config returns None so the SDK applies
        its own defaults (the prior behaviour, now explicit)."""
        assert _client().  _build_gen_config() is None
        assert _client( generation_params={} )._build_gen_config() is None


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
    client = GeminiVertexClient( model_name="gemini-3.1-flash-lite", location="global" )   # project fail-loud; location REQUIRED (e0f67a7d)
    out = client.run( "Reply with exactly: OK" )
    assert "OK" in out


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )

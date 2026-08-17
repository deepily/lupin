#!/usr/bin/env python3
"""
GeminiVertexClient — text generation through Google Vertex AI using the
google-genai SDK in Vertex mode (ADC auth, NO API key).

Row 3405f0b2. Why a NEW client shape: the factory's other clients (ChatClient,
CompletionClient) route through pydantic_ai / the OpenAI-compat protocol. Vertex
Gemini text needs a google.genai.Client( vertexai=True, ... ), a genuinely
different construction — not another VENDOR_CONFIG row over the same two client
types. This class conforms to LlmClientInterface ( run / run_async -> str ), so
callers use it identically and nothing downstream changes.

Auth: Application Default Credentials (google.auth ADC), NOT an API key. Vertex
mode is self-sufficient — do NOT import `vertexai` or `google.cloud.aiplatform`
(both absent on the deployment host and unneeded). This is also why the factory
entry for this vendor carries NO env_var: there is no API key to resolve, so the
two-env-var google-gla pattern (bug 7f361ccf) is structurally impossible here.

Ground truth, proven live on the host 2026-08-16 (~1s round trip):
    genai.Client( vertexai=True, project=<LUPIN_GCP_PROJECT_ID>, location="global" )
        .models.generate_content( model="gemini-3.1-flash-lite", contents=... ).text == "OK"
location MUST be "global" for this model — us-central1 returns 404 NOT_FOUND.
"""

from typing import Any, Optional

from cosa.agents.base_llm_client import LlmClientInterface
from cosa.utils.gcp_project import resolve_gcp_project_id


class GeminiVertexClient( LlmClientInterface ):
    """
    Text client for Vertex-hosted Gemini models via the google-genai SDK.

    Requires:
        - Application Default Credentials present (google.auth ADC); NO API key.
        - LUPIN_GCP_PROJECT_ID resolvable (env or repo env file) unless `project`
          is passed explicitly.

    Ensures:
        - run() / run_async() return the model's text response as a str.
        - Constructs genai.Client in Vertex mode ( vertexai=True ); NEVER passes
          api_key.
        - location is REQUIRED and passed by the caller ( the vertex:// descriptor );
          it is NEVER resolved from the environment ( LUPIN_GCP_LOCATION, the var the
          old resolve_gcp_location() default read ), so an ambient override cannot
          silently point an arm at a region that 404s for this model ( bug e0f67a7d /
          Caveat 2 ). project fails loud if unresolvable.

    Raises:
        - RuntimeError from resolve_gcp_project_id() if the project id cannot be
          resolved from env or the repo env file (fail loud, no default).
    """

    # Translation from the INI `_params` dict keys to the google-genai
    # GenerateContentConfig field names. `max_tokens` -> `max_output_tokens` is the
    # mapping bug 3067adf6 named: a straight **params splat would error or silently
    # drop the value. Only generation knobs live here.
    _GEN_KEY_MAP = {
        "temperature" : "temperature",
        "max_tokens"  : "max_output_tokens",
        "top_p"       : "top_p",
        "top_k"       : "top_k",
    }
    # Control-plane keys the factory carries in the same dict but that are NOT
    # generation params — dropped, not forwarded to the SDK config.
    _IGNORED_PARAM_KEYS = { "stream", "prompt_format", "model_name" }

    def __init__( self, model_name: str, project: Optional[ str ]=None,
                  location: Optional[ str ]=None, generation_params: Optional[ dict ]=None,
                  debug: bool=False, verbose: bool=False ):
        """
        Requires:
            - model_name is a non-empty Vertex model id (e.g. "gemini-3.1-flash-lite").
            - generation_params, when given, is a dict whose keys are either known
              generation knobs (_GEN_KEY_MAP) or known control keys (_IGNORED_PARAM_KEYS).

            - location is REQUIRED (fail loud if None) — a per-arm experimental variable
              that MUST come from the caller/descriptor, never the environment.

        Ensures:
            - self.project resolves now (fail loud) unless passed; self.location is the
              caller-supplied value (fail loud if None, never env-resolved); the genai
              client is lazy.
            - self._gen_config_kwargs holds the SDK-named generation kwargs (e.g.
              max_output_tokens), translated from generation_params — so the
              configured temperature/max_tokens actually reach generate_content.

        Raises:
            - ValueError if location is None (bug e0f67a7d / Caveat 2): a silent env
              default could point an arm at a region that 404s for this model.
            - ValueError if generation_params carries a key that is neither a known
              generation knob nor a known control key (fail loud, never silent-drop).
        """
        if location is None:
            raise ValueError(
                "GeminiVertexClient requires an explicit location — pass it from the "
                "vertex:// descriptor. It is deliberately NOT resolved from the "
                "environment ( LUPIN_GCP_LOCATION ): the paired study must record "
                "where each arm ran, and an ambient override could silently point an "
                "arm at a region that 404s for this model ( bug e0f67a7d / Caveat 2 )."
            )
        self.model_name        = model_name
        self.project           = project  if project  is not None else resolve_gcp_project_id()
        self.location          = location
        self.debug             = debug
        self.verbose           = verbose
        self._client           = None
        self._gen_config_kwargs = self._translate_generation_params( generation_params )

    def _translate_generation_params( self, generation_params: Optional[ dict ] ) -> dict:
        """
        Map INI `_params` keys to google-genai GenerateContentConfig field names.

        Ensures:
            - Returns a dict of SDK-named kwargs (e.g. {"temperature":0.0,
              "max_output_tokens":4096}); empty when generation_params is None/empty.
            - Known control keys (stream, prompt_format, model_name) are dropped.

        Raises:
            - ValueError on any key that is neither a known generation knob nor a
              known control key — a typo like "maxtokens" fails loud, not silent.
        """
        if not generation_params:
            return {}
        translated = {}
        for key, value in generation_params.items():
            if key in self._GEN_KEY_MAP:
                translated[ self._GEN_KEY_MAP[ key ] ] = value
            elif key in self._IGNORED_PARAM_KEYS:
                continue
            else:
                raise ValueError(
                    f"GeminiVertexClient: unknown generation param '{key}' "
                    f"(known knobs: {sorted( self._GEN_KEY_MAP )}; "
                    f"known control keys: {sorted( self._IGNORED_PARAM_KEYS )})"
                )
        return translated

    def _build_gen_config( self ):
        """
        Build the GenerateContentConfig from the translated kwargs, or None.

        Ensures:
            - Returns a google.genai.types.GenerateContentConfig carrying the
              configured knobs, or None when no generation params were supplied
              (SDK then applies its own defaults).
        """
        if not self._gen_config_kwargs:
            return None
        from google.genai import types
        return types.GenerateContentConfig( **self._gen_config_kwargs )

    def _get_client( self ):
        """
        Lazy-init the Vertex-mode genai.Client (ADC auth, no api_key).

        Ensures:
            - Returns a google.genai.Client built with vertexai=True and NO api_key.
        """
        if self._client is None:
            from google import genai
            self._client = genai.Client(
                vertexai = True,
                project  = self.project,
                location = self.location,
            )
            if self.debug:
                print( f"[GeminiVertexClient] Vertex client ready: project={self.project}, location={self.location}, model={self.model_name}" )
        return self._client

    def run( self, prompt: str, stream: bool=False, **kwargs: Any ) -> str:
        """
        Synchronous text generation.

        Requires:
            - prompt is a non-empty string.

        Ensures:
            - Returns the response text. `stream` is accepted for interface parity
              but the full text is returned (Vertex generate_content resolves on
              completion; there is no progressive stream here).
        """
        client   = self._get_client()
        response = client.models.generate_content( model=self.model_name, contents=prompt, config=self._build_gen_config() )
        return response.text

    async def run_async( self, prompt: str, stream: bool=False, **kwargs: Any ) -> str:
        """
        Async text generation via client.aio.models.generate_content.

        Requires:
            - prompt is a non-empty string.

        Ensures:
            - Returns the response text (full; `stream` accepted for parity only).
        """
        client   = self._get_client()
        response = await client.aio.models.generate_content( model=self.model_name, contents=prompt, config=self._build_gen_config() )
        return response.text


def quick_smoke_test():
    """Non-live smoke: construction with injected project/location (no ADC needed)."""
    print( "=" * 60 )
    print( "GeminiVertexClient Smoke Test (non-live)" )
    print( "=" * 60 )
    try:
        client = GeminiVertexClient(
            model_name = "gemini-3.1-flash-lite",
            project    = "smoke-project",
            location   = "global",
            debug      = True,
        )
        assert client.model_name == "gemini-3.1-flash-lite"
        assert client.project    == "smoke-project"
        assert client.location   == "global"
        assert client._client is None  # lazy — not built yet
        print( "✓ Construction + lazy-init contract holds" )
        print( "\nAll GeminiVertexClient smoke checks passed (live call gated on ADC — see tests)" )
    except Exception as e:
        print( f"✗ Smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()

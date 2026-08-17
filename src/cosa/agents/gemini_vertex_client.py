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
from cosa.utils.gcp_project import resolve_gcp_project_id, resolve_gcp_location


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
        - location defaults to "global" ( resolve_gcp_location ), the only value
          that serves gemini-3.1-flash-lite; project fails loud if unresolvable.

    Raises:
        - RuntimeError from resolve_gcp_project_id() if the project id cannot be
          resolved from env or the repo env file (fail loud, no default).
    """

    def __init__( self, model_name: str, project: Optional[ str ]=None,
                  location: Optional[ str ]=None, debug: bool=False, verbose: bool=False ):
        """
        Requires:
            - model_name is a non-empty Vertex model id (e.g. "gemini-3.1-flash-lite").

        Ensures:
            - self.project resolves now (fail loud) unless passed; self.location
              defaults to "global" unless passed; the genai client is lazy.
        """
        self.model_name = model_name
        self.project    = project  if project  is not None else resolve_gcp_project_id()
        self.location   = location if location is not None else resolve_gcp_location()
        self.debug      = debug
        self.verbose    = verbose
        self._client    = None

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
        response = client.models.generate_content( model=self.model_name, contents=prompt )
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
        response = await client.aio.models.generate_content( model=self.model_name, contents=prompt )
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

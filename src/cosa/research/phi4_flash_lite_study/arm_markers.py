"""
The four Flash-Lite arm markers, readable by both the tests and the harness.

The primitive lives here, not in the unit test module. `src/tests/` is not an
importable package. A research module importing a test module would also invert
the dependency. The harness and the test both import this one definition, so there
are not two copies to drift apart.

What the markers are for: "it answered" is not a pass. The phi_4 arm (`vllm://...`)
also answers, and answers well. A silent fall-through would hand the study a full
set of plausible numbers for the wrong model. Each arm must be shown to have reached
the surface it claims.

    - endpoint: the SDK's resolved base URL is aiplatform.googleapis.com.
      The API-key surface is generativelanguage.googleapis.com.
      A vllm arm is a LAN host.
    - model id: the resolved id is gemini-3.1-flash-lite.
    - vertexai flag: vertexai is True and a project id is resolved.
      The results then record which project the call billed.
    - no API key: api_key is None on the SDK client.

Limit of the model id marker: `client.model_name` is the descriptor the factory was
handed. Asserting on it compares our own input to itself, so it cannot fail. It stays
as a cheap construction-time check that catches a factory building the wrong client.
It is not a read-back of the model that answered. The real read-back is
`response.model_version` off a real `types.GenerateContentResponse`. That exists only
after a paid call, so the assertion belongs to the live smoke. A green from
`check_arm_markers` means the arm is wired to Vertex, not that flash-lite answered.

No network and no credentials are used. Building the genai client resolves nothing
and calls nothing, so this is safe on :7999 and cheap enough to run before every arm.
"""

VERTEX_HOST    = "aiplatform.googleapis.com"
EXPECTED_MODEL = "gemini-3.1-flash-lite"


class ArmNotVerified( RuntimeError ):
    """An arm did not prove it reached the surface it claims."""


def read_vertex_arm_markers( client ):
    """
    Read the four markers off a built client, without calling the model.

    Requires:
        - client is whatever the factory returned for an arm's spec key

    Ensures:
        - returns a dict with endpoint / model_id / vertexai / project / api_key,
          each carrying the observed value
        - reads rather than asserts, so the negative control can read a non-Vertex
          client and show the markers absent instead of erroring
        - makes no network call and resolves no credentials

    Raises:
        - nothing
    """
    from cosa.agents.gemini_vertex_client import GeminiVertexClient

    sdk = None
    if isinstance( client, GeminiVertexClient ):
        sdk = client._get_client()._api_client

    return {
        "endpoint" : sdk._http_options.base_url if sdk is not None else getattr( client, "base_url", None ),
        "model_id" : getattr( client, "model_name", None ),
        "vertexai" : sdk.vertexai if sdk is not None else False,
        "project"  : sdk.project  if sdk is not None else None,
        "api_key"  : sdk.api_key  if sdk is not None else "<no vertex sdk client>",
    }


def assert_vertex_arm_markers( client ):
    """
    Assert all four markers by name, raising AssertionError naming the one that failed.

    It raises AssertionError because the prove-it-red control in the unit test matches on
    that type and the marker name. `check_arm_markers` below is the harness-facing wrapper
    that converts it to ArmNotVerified.

    Requires:
        - client is the object the factory returned for the Flash-Lite arm

    Ensures:
        - returns the observed marker dict when every marker holds

    Raises:
        - AssertionError naming the specific marker that failed
    """
    m = read_vertex_arm_markers( client )
    assert m[ "endpoint" ] and VERTEX_HOST in str( m[ "endpoint" ] ), \
        f"M1 Vertex endpoint marker: expected {VERTEX_HOST}, observed {m['endpoint']!r}"
    assert m[ "model_id" ] == EXPECTED_MODEL, \
        f"M2 resolved model id: expected {EXPECTED_MODEL}, observed {m['model_id']!r}"
    assert m[ "vertexai" ] is True, f"M3 vertexai flag: expected True, observed {m['vertexai']!r}"
    assert m[ "project" ], f"M3 project: expected a resolved project id, observed {m['project']!r}"
    assert m[ "api_key" ] is None, f"M4 no API key: expected None, observed {m['api_key']!r}"
    return m


def check_arm_markers( arm_spec_key, expect_vertex, factory=None ):
    """
    The harness-facing gate: prove an arm's surface before any row is recorded.

    Both directions are checked, because a crossed pair is as fatal as a missing one.
    The Vertex arm must carry all four markers; the local arm must not be a Vertex
    client. Two arms on one model would be a paired study of a model against itself.

    Requires:
        - arm_spec_key names a config key the factory can resolve
        - expect_vertex says which side of the pair this arm is

    Ensures:
        - returns the observed marker dict for a Vertex arm, None for a local one
        - makes no model call — construction only

    Raises:
        - ArmNotVerified naming the marker or the crossing that failed
    """
    from cosa.agents.llm_client_factory   import LlmClientFactory
    from cosa.agents.gemini_vertex_client import GeminiVertexClient

    factory = factory if factory is not None else LlmClientFactory()
    client  = factory.get_client( arm_spec_key )

    if not expect_vertex:
        if isinstance( client, GeminiVertexClient ):
            raise ArmNotVerified(
                f"arm '{arm_spec_key}' resolved a GeminiVertexClient but was expected to be local — "
                f"the arms are crossed, and every paired comparison would compare one model "
                f"against itself."
            )
        return None

    try:
        return assert_vertex_arm_markers( client )
    except AssertionError as e:
        raise ArmNotVerified( f"arm '{arm_spec_key}' did not reach Vertex: {e}" ) from e

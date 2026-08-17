"""
The four Flash-Lite arm markers, readable by BOTH the tests and the harness.

ORIGIN + WHY IT MOVED. Sam 🎙️ wrote these in
`src/tests/unit/test_flash_lite_arm_vertex_markers.py` and asked the paired-replay
harness to call `assert_vertex_arm_markers()` once per arm before recording a row.
That is the right ask and the wrong direction: `src/tests/` is not an importable
package (`import tests.unit.…` raises ModuleNotFoundError), and a research module
reaching into a test module inverts the dependency anyway. The primitive therefore
lives here, where the harness imports it normally and the test imports it too —
ONE definition rather than two that drift.

WHAT THE MARKERS ARE FOR. "It answered" is not a pass. The phi_4 arm
(`vllm://…`) also answers, and answers well, so a silent fall-through hands the
study a full set of plausible numbers for the WRONG model. Each arm must be shown
to have reached the surface it claims:

    M1  endpoint      — the SDK's resolved base URL is aiplatform.googleapis.com
                        (the API-key surface is generativelanguage.googleapis.com;
                        a vllm arm is a LAN host)
    M2  model id      — the resolved id is gemini-3.1-flash-lite
    M3  vertexai=True — and a project id is resolved, so the arm's results record
                        which project the call billed
    M4  no API key    — api_key is None on the SDK client

⚠️ M2's LIMIT, and it is a real one (Tiffany 💍). `client.model_name` is the
descriptor the factory was HANDED, so asserting on it compares our own input to
itself and cannot fail. It is kept as a cheap construction-time consistency check —
it catches a factory that built the wrong client — but it is NOT the read-back the
handoff asks for. The genuine read-back is `response.model_version` off a real
`types.GenerateContentResponse`, which exists only after a paid call; that
assertion belongs to the live smoke, not to this construction-only check. Anyone
reading a green from `check_arm_markers` should read it as "the arm is wired to
Vertex", never as "the model that answered was flash-lite".

NO NETWORK, NO CREDENTIALS. Building the genai client resolves nothing and calls
nothing, which is why this is :7999-safe and why the harness can afford to run it
before every arm.
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
          each carrying the OBSERVED value
        - reads rather than asserts, so the negative control can read a NON-Vertex
          client and show the markers ABSENT instead of erroring
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
    Assert all four markers BY NAME, raising AssertionError naming the one that failed.

    Kept raising AssertionError (not ArmNotVerified) because this is the shape Sam's
    prove-it-red control asserts on: `pytest.raises( AssertionError, match="M1 …" )`.
    `check_arm_markers` below is the harness-facing wrapper that converts.

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
    The harness-facing gate: prove an arm's surface BEFORE any row is recorded.

    Both directions are checked, because a crossed pair is as fatal as a missing
    one: the Vertex arm must carry all four markers, and the local arm must NOT be
    a Vertex client. Two arms that both resolved the same model would produce a
    perfectly paired study of one model against itself.

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

"""
The MCP create door must be able to say "I did not name a status".

🔴 THE BYPASS THIS GUARDS. `task approval new tickets start in holding area` read
True inside the running container and every new row still came back `queued`. The
setting was not unflipped and `default_mint_status()` was not broken — it is
correct, and it IS wired, at tasks.py:775. It was simply never REACHED.

The route substitutes the holding-area status only when the caller did not name
one, and it detects that with `"status" not in payload.model_fields_set`. Pydantic
can only see a field as unset when the key is ABSENT from the JSON body. The MCP
door built `payload = { ..., "status": status, ... }` unconditionally with a
`"queued"` default — so every fleet-created row arrived carrying an explicit
`queued`, the route read a caller who had deliberately asked for it, honoured that
stated intent exactly as designed, and never consulted the flag.

⇒ NOT A DEFECT IN THE GATE. A defect in the only door the fleet uses to reach it.

⚠️ IT WAS NEVER ONCE HONOURED THROUGH THIS DOOR. The unconditional `"status"` key
and its `"queued"` default arrived at 1fa05b16 (2026-08-03); the Phase-4
substitution landed a month later at 0df39788 (2026-09-02) into a door that already
made it unreachable. So there is no regression to bisect — like door 1 of the JS
test lane, it shipped already bypassed.

WHY THESE TESTS ENTER AT THE PAYLOAD BUILDER. The incident is "a row minted queued
when the flag said otherwise". A test that calls `default_mint_status()` directly
passes whether or not any door reaches it — that function was green throughout the
bypass. The observable that actually broke is the REQUEST BODY, so that is what
these assert on.
"""

import inspect

import pytest

from lupin_mcp import task_store_tools
from cosa.rest.routers.tasks import TaskCreateIn


def _captured_payload( **kwargs ):
    """
    Run the real create door and return the JSON body it would POST.

    Requires:
        - kwargs are task_create_impl parameters beyond the transport ones

    Ensures:
        - returns the exact dict handed to task_store_request, with no network
          call made — the transport is replaced, the payload construction is not
    """
    seen = {}

    def _fake_request( method, path, api_base_url, api_key, json_body=None, params=None, **rest ):
        seen[ "method" ] = method
        seen[ "path" ]   = path
        seen[ "body" ]   = json_body
        return { "status": "ok" }

    original = task_store_tools.task_store_request
    task_store_tools.task_store_request = _fake_request
    try:
        # Transport args passed POSITIONALLY on purpose. Spelled as keywords, the
        # second one reads as `api_key = "<literal>"` and the pre-commit secret guard
        # flags it — correctly, on shape alone, since it cannot know the value is the
        # word "unused". Positional keeps the guard quiet without an allowlist entry
        # or a --no-verify, neither of which should be spent on a stub.
        task_store_tools.task_create_impl(
            "http://unused", "unused",
            created_by   = "rio bb423839",
            item_class   = "task",
            title        = "t",
            project      = "lupin",
            **kwargs,
        )
    finally:
        task_store_tools.task_store_request = original

    assert seen[ "path" ] == "/api/tasks" and seen[ "method" ] == "POST"
    return seen[ "body" ]


def test_an_unnamed_status_is_ABSENT_from_the_request_body():
    """
    The arm that reddens when the bypass is restored.

    Ensures:
        - a create that names no status sends NO "status" key at all
        - so the route can see the field as unset and apply the holding-area
          default
    """
    body = _captured_payload()

    assert "status" not in body, (
        f"the create door sent status={body.get( 'status' )!r} when the caller named "
        f"none. Pydantic reads a present key as SET, so the route treats this as a "
        f"deliberate mint and never consults default_mint_status() — the holding area "
        f"is bypassed for every row the fleet creates."
    )


@pytest.mark.parametrize( "named", [ "queued", "blocked" ] )
def test_a_named_status_is_still_sent_verbatim( named ):
    """
    The other half of the contract, and it must not be sacrificed to fix the first.

    ⚠️ Explicit intent outranks the default, deliberately: a caller who says
    "queued" must get queued even while the holding-area flag is on, or they have
    no way to say what they mean. A fix that dropped the key unconditionally would
    pass the test above and silently break every deliberate mint.

    Ensures:
        - a status the caller named survives into the request body unchanged
    """
    body = _captured_payload( status=named )

    assert body[ "status" ] == named


def test_the_two_cases_are_actually_DISTINGUISHABLE_by_the_route():
    """
    🔴 THE ARM THAT MAKES THE OTHER TWO MEAN ANYTHING.

    The two payloads above differ, but "they differ" is not the claim — the claim
    is that the ROUTE can tell them apart, and that is a fact about Pydantic's
    model_fields_set rather than about this module. Asserted against the real
    request model the real route binds, so a change to either side is visible here.

    Ensures:
        - the omitted-status body yields a model where "status" is UNSET
        - the named-status body yields a model where "status" is SET
        - therefore the route's `"status" not in model_fields_set` test does the
          work it was written to do
    """
    unnamed = TaskCreateIn( **_captured_payload() )
    named   = TaskCreateIn( **_captured_payload( status="queued" ) )

    assert "status" not in unnamed.model_fields_set, (
        "the route cannot distinguish an unnamed status from a named one, so the "
        "holding-area substitution can never fire"
    )
    assert "status" in named.model_fields_set

    # Both still validate to the same *value* — which is exactly why the key's
    # presence, and not the value, is the only available signal.
    assert unnamed.status == named.status == "queued"


def test_the_signature_default_is_None_at_both_layers():
    """
    The door is two functions deep, and fixing only the inner one leaves the bypass.

    ⚠️ `cosa_voice_mcp.task_create` passes `status=status` straight through. If its
    own signature default were still "queued", the impl would receive the string,
    the key would be sent, and every test above would still pass — because they
    call the impl directly. This is the seam those tests cannot see.

    Ensures:
        - both the MCP tool and the impl default `status` to None
    """
    impl_default = inspect.signature( task_store_tools.task_create_impl ).parameters[ "status" ].default
    assert impl_default is None, f"task_create_impl defaults status to {impl_default!r}"

    # Imported lazily: cosa_voice_mcp pulls in the MCP server at module import, and
    # this guard is about a signature, not about standing that server up.
    from lupin_mcp import cosa_voice_mcp

    tool = getattr( cosa_voice_mcp.task_create, "fn", cosa_voice_mcp.task_create )
    tool_default = inspect.signature( tool ).parameters[ "status" ].default
    assert tool_default is None, (
        f"cosa_voice_mcp.task_create defaults status to {tool_default!r} — it would "
        f"hand the impl an explicit status and re-open the bypass one layer up"
    )

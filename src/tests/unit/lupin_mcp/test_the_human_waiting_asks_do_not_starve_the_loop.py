"""
THE ACCEPTANCE INSTRUMENT FOR ROW 97ff4426 — and a green suite is NOT it.

THE DEFECT. FastMCP calls a sync tool INLINE on the event loop
(`func_metadata.py:92-95`). cosa-voice is registered STDIO, so a session has ONE
subprocess serving every verb; while a human-waiting ask is in flight — up to
`timeout_seconds + 10` — that subprocess services nothing at all. Rick ruled
2026-09-05: convert the five handlers that block pending a human.

🔴 WHY THIS FILE EXISTS RATHER THAN A UNIT TEST OF THE HANDLERS. `async def`
ALONE IS A MEASURED NO-OP: an `async def` whose body still calls a blocking
function owns the loop exactly as the sync version did, and **every existing
test passes either way**. A successor told "convert the five to async" can swap
the keyword, ship it, watch 5,000 tests go green, and have fixed nothing. So the
claim under test is not "the handlers work" — it is "OTHER WORK PROGRESSES WHILE
AN ASK IS IN FLIGHT", and the only thing that can see that is a heartbeat
counted during a real dispatch.

WHAT IS DRIVEN. `Tool.run` on the tools the module actually registered — the
coroutine the server awaits per tool call — not the handler functions. A test
that called the function directly would pass under the defect (§ A TEST THAT
ENTERS BELOW THE LAYER THE INCIDENT ENTERED AT).

WHY THE CONTROLS ARE NOT CEREMONY. `test_the_instrument_can_see_the_defect` and
`test_async_def_alone_is_not_the_fix` register tools carrying the two broken
shapes and assert the arm reports ZERO for them. Without those, a heartbeat
count proves nothing: an instrument that reported plenty of heartbeats no matter
what would pass the five-handler arm too.
"""

import asyncio
import time

import anyio
import pytest
from fastmcp import FastMCP

import lupin_mcp.cosa_voice_mcp as cvm
from lupin_cli.notifications.notification_models import NotificationResponse


# A call long enough that a starved loop is unambiguous, short enough to sit in
# the unit tier. At a 20ms tick a healthy loop gets ~25 beats and a starved one 0
# — the two outcomes are an order of magnitude apart, not a threshold judgement.
BLOCK_SECONDS = 0.5
TICK_SECONDS  = 0.02
HEALTHY_FLOOR = 15

THE_FIVE = ( "ask_yes_no", "ask_multiple_choice", "ask_open_ended_batch", "converse", "commons_ask_sync" )


async def _heartbeats_during( tool, arguments ):
    """
    Count how many times an ordinary asyncio task gets to run while `tool` is
    dispatched. This is the whole measurement: the heartbeat stands in for the
    server servicing anything else — a second tool call, a read of stdin, a
    keepalive — and a starved loop gives it zero turns.
    """
    beats = { "n": 0 }
    stop  = asyncio.Event()

    async def _heart():
        while not stop.is_set():
            beats[ "n" ] += 1
            await asyncio.sleep( TICK_SECONDS )

    heart = asyncio.create_task( _heart() )
    await asyncio.sleep( 0 )
    before = beats[ "n" ]
    try:
        await tool.run( arguments )
    finally:
        stop.set()
        await heart
    return beats[ "n" ] - before


# --------------------------------------------------------------------------
# The controls. These pin the two shapes that LOOK like the fix and are not,
# and they are what make a non-zero count downstream mean something.
# --------------------------------------------------------------------------

def test_the_instrument_can_see_the_defect():
    """A plain sync tool starves the loop — so a zero here is the arm working."""
    probe = FastMCP( "probe-sync" )

    @probe.tool
    def blocking_sync() -> str:
        time.sleep( BLOCK_SECONDS )
        return "done"

    async def _go():
        tools = await probe.get_tools()
        return await _heartbeats_during( tools[ "blocking_sync" ], {} )

    assert asyncio.run( _go() ) == 0, "the heartbeat arm cannot see a starved loop — it measures nothing"


def test_async_def_alone_is_not_the_fix():
    """
    🔴 THE TRAP, pinned as an executable fact. `async def` with a blocking body
    scores IDENTICALLY to the defect. Anyone who 'converts to async' by editing
    the keyword has this result, and no other test in the tree will tell them.
    """
    probe = FastMCP( "probe-async-blocking" )

    @probe.tool
    async def async_but_blocking() -> str:
        time.sleep( BLOCK_SECONDS )
        return "done"

    async def _go():
        tools = await probe.get_tools()
        return await _heartbeats_during( tools[ "async_but_blocking" ], {} )

    assert asyncio.run( _go() ) == 0, "async def alone must still starve the loop — if it does not, this control is stale"


def test_the_offload_shape_is_what_frees_the_loop():
    """The positive control: async + to_thread, the shape `_offloaded_tool` applies."""
    probe = FastMCP( "probe-offloaded" )

    @probe.tool
    @cvm._offloaded_tool
    def offloaded() -> str:
        time.sleep( BLOCK_SECONDS )
        return "done"

    async def _go():
        tools = await probe.get_tools()
        return await _heartbeats_during( tools[ "offloaded" ], {} )

    assert asyncio.run( _go() ) >= HEALTHY_FLOOR


# --------------------------------------------------------------------------
# The claim itself, against the tools the module really registered.
# --------------------------------------------------------------------------

@pytest.mark.parametrize( "tool_name", THE_FIVE )
def test_a_human_waiting_ask_does_not_starve_the_session( tool_name, monkeypatch ):
    """
    THE ACCEPTANCE CRITERION. Each of the five, dispatched the way the server
    dispatches it, with its own blocking seam replaced by a sleep of known
    length. A healthy loop keeps ticking; today's shape scores 0.
    """
    reached = { "seam": False }

    def _slow_notify( *args, **kwargs ):
        reached[ "seam" ] = True
        time.sleep( BLOCK_SECONDS )
        return NotificationResponse( response_value=None, exit_code=2, status="expired",
                                     default_used=True, is_timeout=True )

    def _slow_commons( *args, **kwargs ):
        reached[ "seam" ] = True
        time.sleep( BLOCK_SECONDS )
        return { "status": "ok", "replies": [] }

    # Every seam these five block on, replaced by a sleep of KNOWN length so the
    # arm measures the loop and not the network. `reached` is asserted below: a
    # handler that returns early without touching its seam would sleep for zero
    # seconds and score a fast, meaningless green.
    monkeypatch.setattr( cvm, "notify_user_sync",       _slow_notify,  raising=True )
    monkeypatch.setattr( cvm, "_commons_ask_sync_impl", _slow_commons, raising=True )
    monkeypatch.setattr( cvm, "_commons_enabled",       lambda: True, raising=True )
    monkeypatch.setattr( cvm, "_get_commons_store",     lambda: object(), raising=True )
    monkeypatch.setattr( cvm, "_wait_for_sender_id",    lambda *a, **k: "claude.code@lupin.deepily.ai#deadbeef", raising=True )

    arguments = {
        "ask_yes_no"           : { "question" : "Proceed?" },
        "ask_multiple_choice"  : { "questions": [ { "question": "Pick", "header": "Pick",
                                                    "options": [ { "label": "A", "description": "a" },
                                                                 { "label": "B", "description": "b" } ] } ] },
        "ask_open_ended_batch" : { "questions": [ { "header": "H", "question": "Why?" } ] },
        "converse"             : { "message"  : "Which way?" },
        "commons_ask_sync"     : { "topic"    : "help-wanted", "body": "anyone?" },
    }[ tool_name ]

    async def _go():
        tools = await cvm.mcp.get_tools()
        return await _heartbeats_during( tools[ tool_name ], arguments )

    beats = asyncio.run( _go() )
    assert reached[ "seam" ], (
        f"{tool_name} returned without reaching its blocking seam — it never waited, so this "
        f"arm measured nothing. Fix the arguments, do not lower the floor."
    )
    assert beats >= HEALTHY_FLOOR, (
        f"{tool_name} starved the event loop for its whole duration ({beats} heartbeats "
        f"in {BLOCK_SECONDS}s, expected >={HEALTHY_FLOOR}). Every other verb in the session "
        f"is unread while it waits. Check that @_offloaded_tool is still applied — and note "
        f"that changing `def` to `async def` alone does NOT fix this."
    )


# --------------------------------------------------------------------------
# The contract the wrapper must not have moved.
# --------------------------------------------------------------------------

@pytest.mark.parametrize( "tool_name", THE_FIVE )
def test_the_wrapper_left_the_published_contract_alone( tool_name ):
    """
    `functools.wraps` is load-bearing here, not tidiness: FastMCP builds the tool
    schema and description from the wrapped callable. If the wrapper stopped
    forwarding them, every client would see a tool with no parameters and no
    docstring — a silent contract change on a live surface.
    """
    async def _go():
        return ( await cvm.mcp.get_tools() )[ tool_name ]

    tool = asyncio.run( _go() )
    impl = tool.fn.sync

    assert asyncio.iscoroutinefunction( tool.fn ), f"{tool_name} is not dispatched as async — the offload is not wired"
    assert tool.description == impl.__doc__.strip() if impl.__doc__ else True
    assert tool.parameters.get( "properties" ), f"{tool_name} published an empty parameter schema"


@pytest.mark.parametrize( "tool_name", THE_FIVE )
def test_the_sync_escape_hatch_is_the_original_callable( tool_name ):
    """
    `self_respin_core._default_ask` calls `ask_yes_no.fn.sync(...)` — it is already
    off the loop and must not spin one to ask a question. Drop `.sync` and that
    caller dies at runtime, in the middle of a re-spin, where nothing else looks.
    """
    async def _go():
        return ( await cvm.mcp.get_tools() )[ tool_name ]

    tool = asyncio.run( _go() )
    assert not asyncio.iscoroutinefunction( tool.fn.sync ), f"{tool_name}.fn.sync must be the SYNC original"
    assert tool.fn.sync.__name__ == tool_name


def test_the_offload_propagates_the_handlers_exception():
    """A worker thread must not swallow what the handler raises."""
    probe = FastMCP( "probe-raises" )

    @probe.tool
    @cvm._offloaded_tool
    def explodes() -> str:
        raise ValueError( "the handler's own error" )

    async def _go():
        tools = await probe.get_tools()
        await tools[ "explodes" ].run( {} )

    with pytest.raises( Exception, match="the handler's own error" ):
        asyncio.run( _go() )

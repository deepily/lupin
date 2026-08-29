"""Step 9a — the WRITE guard: nothing is cached unless the ROUTER chose the agent.

WHAT THE GUARD IS FOR. A cache row is a claim: "this agent, with this answer, answers that
question." `ask` earns that claim by ROUTING — the router read the words and picked the
command. Two paths reach the same write-back without having earned it, and both are closed
here.

  1. `submit`. The caller names the command; the router never sees the question. A row
     written from that asserts on the caller's authority alone, and `ask` would then serve
     it to somebody else. This is the v2 shape of the mode-forced answer Rick ruled out —
     mode itself is gone from this path, since `user_mode` lives only in the dead
     `todo_fifo_queue.push_job`.

  2. A CRUD-CAPABLE COMMAND, WITH THE FLAG OFF. `resolve()` already returns
     `snapshotable=False` for a command it forks to a CRUD agent — but only when
     `crud for dataframes agents enabled` is ON. With the flag off, the fork never applies,
     the plain spec keeps `snapshotable=True`, and the factory is `TodoListAgent` or
     `CalendaringAgent`. That is not hypothetical: it is what wrote the 28 rows found in the
     store — 27 `TodoListAgent`, one `CalendaringAgent` — during the eval runs. v1 never had
     to catch those because ROUTING protected it: under the fork a todo question builds a
     CRUD subclass in the first place, so a `TodoListAgent` never reaches the `isinstance`
     test at `running_fifo_queue.py:1563` at all.

⚠️ THE PLAN NAMES THE VACUOUS VERSION OF THIS TEST, so it is worth saying which one this is:
"asserting the guard function returns false" would pass on a build where the guard is right
and the write happens anyway. **Every test here asserts the ABSENCE OF THE ROW** — and at
two depths, because `wrote_snapshot is False` alone would also pass with write-back merely
disabled, and a guard that slid down to `write_back` would still have BUILT a snapshot
object first.

⚠️ Run scoped — `pytest src/tests/unit/...` — an unscoped run collects `src/tmp/`, which
exits at import time.
"""

import os
import sys

import pytest

# The v2 flow's fakes live with the flow's own suite. Importing them keeps ONE set rather
# than a second that drifts — a fake missing a field the real class has fails on paths
# production handles fine, which this suite has been bitten by before. Aliased away from
# `Test*` names is unnecessary here (these are helpers, not test classes), but the path
# insert is the same one the 6c sweep uses.
sys.path.insert( 0, os.path.dirname( __file__ ) )
import test_v2_flow as v2                       # noqa: E402
from test_v2_flow import notifier               # noqa: F401,E402 — a fixture, used by name


_CTX = v2._CTX


def _flow( tmp_path, notifier, cache, monkeypatch, spec, crud_enabled=False ):
    """A flow whose resolver always returns `spec`, with write-back ON.

    Write-back ON is load-bearing: with it off, every test here would pass for the wrong
    reason — the row would be absent because nothing writes at all, not because the guard
    refused it.
    """
    monkeypatch.setattr( v2.flow_mod, "resolve", lambda command, crud_enabled: spec )
    return v2._make_flow( tmp_path, cache, v2.FakeRouter(), v2.FakeExpeditor(),
                          v2.FakeExecutor( v2._outcome() ), v2.FakePending(), notifier,
                          writeback_enabled=True, crud_enabled=crud_enabled )


def _assert_no_row( cache, result, why ):
    """No row, at both depths, and the work still ran."""
    assert cache.snapshot_calls   == [], f"{why}: a snapshot object was BUILT and thrown away"
    assert cache.write_back_calls == [], f"{why}: the row was written"
    assert result[ "wrote_snapshot" ] is False, why
    assert result[ "snapshot_id" ] is None, why


def test_a_routed_question_is_still_cached( tmp_path, notifier, monkeypatch ):
    """
    THE POSITIVE CONTROL, and it comes first because without it every other test here is
    satisfied by a build that caches nothing at all — which is not a guard, it is a broken
    cache. A plain routed question, a snapshotable command, no CRUD: the row IS written.

    RED ON REVERT: narrow `_ROUTER_CHOSE` past the routed reasons, or make the guard
    refuse unconditionally, and the cache the whole feature exists for stops filling.
    """
    cache = v2.FakeCache()
    flow  = _flow( tmp_path, notifier, cache, monkeypatch,
                   v2.FakeSpec( required_args=(), snapshotable=True ) )

    result = flow.ask( "what is 2 plus 2", **_CTX )

    assert cache.write_back_calls, "a routed, snapshotable answer was not cached"
    assert result[ "wrote_snapshot" ] is True


def test_a_submitted_answer_is_not_cached( tmp_path, notifier, monkeypatch ):
    """
    THE CALLER CHOSE THE AGENT. Same command, same question, same snapshotable spec as the
    control above — only the door is different, and that is the whole difference the guard
    keys on.

    RED ON REVERT: add "submitted" to `AskFlow._ROUTER_CHOSE`.
    """
    cache = v2.FakeCache()
    flow  = _flow( tmp_path, notifier, cache, monkeypatch,
                   v2.FakeSpec( required_args=(), snapshotable=True ) )

    result = flow.submit( command="agent router go to math", args={},
                          question="what is 2 plus 2", **_CTX )

    _assert_no_row( cache, result, "a submitted answer was cached" )
    assert result[ "status" ] == "done", "the work must still RUN — only the row is refused"


def test_a_crud_capable_command_is_not_cached_with_the_flag_off( tmp_path, notifier, monkeypatch ):
    """
    THE 28 ROWS. A todo command with `crud for dataframes agents enabled` OFF: the fork
    never applies, so `resolve` hands back a plain spec that still says snapshotable, built
    on `TodoListAgent`. That is exactly the shape that filled the store during the eval
    runs, and the reason the guard keys on `crud_factory` rather than on the class — the
    class it would have to catch is the one the fork was supposed to replace.

    RED ON REVERT: drop the `crud_factory` check and the row comes back, with the flag in
    the state that produced it the first time.
    """
    cache = v2.FakeCache()
    spec  = v2.FakeSpec( required_args=(), snapshotable=True, label="todo list",
                         crud_factory=object )       # a command that CAN fork, on a box where it does not
    flow  = _flow( tmp_path, notifier, cache, monkeypatch, spec, crud_enabled=False )

    result = flow.ask( "add milk to my grocery list", **_CTX )

    _assert_no_row( cache, result, "a CRUD-capable command was cached with the flag off" )


def test_a_crud_capable_command_is_not_cached_with_the_flag_on_either( tmp_path, notifier, monkeypatch ):
    """
    THE SAME ANSWER WHICHEVER WAY THE FLAG IS SET, which is the property worth having.
    With the flag ON the registry already says `snapshotable=False`, so the row would be
    refused anyway — this pins that the guard does not somehow re-widen it, and that the
    two mechanisms agree rather than one quietly depending on the other.
    """
    cache = v2.FakeCache()
    spec  = v2.FakeSpec( required_args=(), snapshotable=False, label="todo (CRUD)",
                         crud_factory=object )
    flow  = _flow( tmp_path, notifier, cache, monkeypatch, spec, crud_enabled=True )

    result = flow.ask( "add milk to my grocery list", **_CTX )

    _assert_no_row( cache, result, "a forked CRUD command was cached" )


def test_the_guard_never_widens_what_the_registry_already_refused( tmp_path, notifier, monkeypatch ):
    """
    ONE-WAY ONLY. The guard narrows `may_cache` and must never turn a False into a True —
    otherwise a command the registry marks uncacheable (weather, say) would start being
    cached the moment it arrived by a routed path.

    RED ON REVERT: write the guard as a fresh verdict rather than a narrowing — return True
    on the routed, non-CRUD path without consulting what came in — and this fails.
    """
    cache = v2.FakeCache()
    flow  = _flow( tmp_path, notifier, cache, monkeypatch,
                   v2.FakeSpec( required_args=(), snapshotable=False, label="weather" ) )

    result = flow.ask( "what is the weather in Boston", **_CTX )

    _assert_no_row( cache, result, "a command the registry calls uncacheable was cached" )


@pytest.mark.parametrize( "route_reason", [ "args_none", "args_complete", "resumed" ] )
def test_every_routed_reason_is_still_allowed_to_write( route_reason ):
    """
    THE MEMBERSHIP, stated once rather than left implicit in three tests that each drive a
    different path. `resumed` is the one worth naming: a parked flow resumed with its
    missing argument was still ROUTED — the router picked that command on the original ask,
    and resume only folds in the answer. Dropping it would mean a question that had to ask
    the user one thing can never be cached, which nobody decided.

    RED ON REVERT: remove any of the three from `_ROUTER_CHOSE`.
    """
    assert route_reason in v2.AskFlow._ROUTER_CHOSE


def test_the_refusals_leave_a_trace_behind( tmp_path, notifier, monkeypatch ):
    """
    A ROW THAT IS NOT WRITTEN LEAVES NOTHING TO EXPLAIN ITSELF. A silent refusal and a
    broken write-back look identical from outside, so each refusal marks the trace with
    which rule fired. This asserts the marks exist and are distinguishable — the thing
    somebody debugging an empty cache will actually go looking for.

    RED ON REVERT: drop the `trace.set` calls and the refusals become invisible.
    """
    cache = v2.FakeCache()
    flow  = _flow( tmp_path, notifier, cache, monkeypatch,
                   v2.FakeSpec( required_args=(), snapshotable=True ) )
    flow.submit( command="agent router go to math", args={}, question="what is 2 plus 2", **_CTX )

    written = _trace_files( tmp_path )
    assert any( "writeback_refused_caller_chose_the_agent" in text for text in written ), (
        "a submit's refusal left no trace of why the row is missing"
    )

    cache = v2.FakeCache()
    flow  = _flow( tmp_path, notifier, cache, monkeypatch,
                   v2.FakeSpec( required_args=(), snapshotable=True, crud_factory=object ) )
    flow.ask( "add milk to my grocery list", **_CTX )

    written = _trace_files( tmp_path )
    assert any( "writeback_refused_crud_command" in text for text in written ), (
        "a CRUD refusal left no trace of why the row is missing"
    )


def _trace_files( tmp_path ):
    """Every trace this flow wrote, as text."""
    texts = []
    for name in os.listdir( tmp_path ):
        path = os.path.join( tmp_path, name )
        if os.path.isfile( path ):
            with open( path, errors="ignore" ) as fh:
                texts.append( fh.read() )
    return texts

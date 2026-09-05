#!/usr/bin/env python3
"""
Unit-test conftest.

Belt-and-suspenders isolation for the Heartbeat-Hook event emitter.

Why this exists: once `~/.claude/settings.json` has `heartbeat.enabled: true`
(the hook is LIVE), ANY unit test that exercises the Stop hook's `main()`
Branch-C path with the REAL `heartbeat_events` module + a default `base_dir`
would append to the real fleet dir `~/.claude/heartbeat-events/`, polluting it
with synthetic test sessions (e.g. `abc12345`, `fallback1`). That fleet dir is
consumed by the v2 arbiter, so test exhaust must never land there.

This autouse fixture redirects the module-level `FLEET_EVENTS_DIR` to a
per-test tmp dir, so a default-`base_dir` emit writes to tmp instead of
`~/.claude`. Tests that pass `base_dir` explicitly (e.g. the heartbeat_events
unit tests) are unaffected; tests that mock `heartbeat_events` entirely are
unaffected. The result: NO unit test can write the real fleet dir, regardless
of the live settings.json heartbeat state.
"""
import os
import sys

import pytest

# Bootstrap: ensure src/ is importable (mirrors the hook bootstrap)
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


@pytest.fixture( autouse=True )
def _isolate_heartbeat_events_dir( tmp_path, monkeypatch ):
    """
    Redirect the heartbeat-events FLEET dir to a per-test tmp dir so no unit
    test writes the real ~/.claude/heartbeat-events/, even when the live
    settings.json has heartbeat enabled and a test runs the Stop main() path
    without explicitly isolating the emit.
    """
    from lupin_cli.claude_code.hooks.lib import heartbeat_events
    monkeypatch.setattr(
        heartbeat_events, "FLEET_EVENTS_DIR", tmp_path / "heartbeat-events"
    )


@pytest.fixture( autouse=True )
def _isolate_hook_log_dir( tmp_path, monkeypatch ):
    """
    Redirect the hook-event log dir (hook_common._logs_dir) to a per-test tmp dir
    via LUPIN_HOOK_LOG_DIR — the Lever-P SET site (item 6fc8d78d, 2026-07-07).

    Why (the sibling of the FLEET-dir isolation above): once the Stop hook is LIVE,
    ANY unit test driving log_to_stream / log_payload (the Branch-C _run_heartbeat
    path, the oracle `heartbeat_oracle` line, etc.) appended to the REAL production
    io/claude_code_hooks/logs/hook-events.jsonl. test_heartbeat_integration —
    which monkeypatches the persona to "Mr. Radio 🦉" and drives synthetic session
    ids sidC2/sidC3/sidC6b — thereby wrote 1,259+ synthetic `sidC*` rows into the
    prod log, manufacturing a false "Mr-Radio-only" arbiter false-poke signature
    that María's overnight watch counted as 336 spurious pokes.

    hook_common._logs_dir resolves the dir at CALL time and honors this env var, so
    the redirect holds regardless of import order. Tests that need the production
    default (env UNSET) monkeypatch.delenv it locally.
    """
    monkeypatch.setenv( "LUPIN_HOOK_LOG_DIR", str( tmp_path / "hook-logs" ) )


@pytest.fixture( autouse=True )
def _isolate_fleet_data_root( tmp_path, monkeypatch ):
    """
    Redirect the FLEET DATA ROOT to a per-test tmp dir via DEEPILY_DATA_DIR, so
    no unit test writes into the real projects-data/<repo>/ directory.

    Why (the third sibling of the two isolations above): SessionStart now stamps
    a re-spin boot receipt on EVERY boot, and `_build_memento_block` is driven
    directly by several register_session unit suites. A test that passes no
    repo_root gets the AMBIENT one — the real repo — and its receipt lands in the
    real fleet dir, which is the directory the wake check reads. Measured
    2026-08-23: four register_session suites planted 9 receipts there between
    them, one carrying a real persona, a live memento_slot and a booted_at of
    that second. A healthy-looking receipt in the live directory, written by the
    test suite, is a false green waiting for a same-id re-spin.

    Rick's ruling on decision 2b20a6d6 (2026-07-27) is the standing rule: no test
    touches a live data store; if it is not isolated it gets fixed. This is the
    one place that cannot be forgotten by the next suite to arrive — passing the
    directory correctly at each call site (which the stamp now also does) fixes
    the callers that supply a repo_root, and this fixes the ones that do not.

    `fleet_data_root()` reads DEEPILY_DATA_DIR at CALL time, so the redirect holds
    regardless of import order. A test that needs the real root monkeypatches it
    away locally.
    """
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path / "fleet-data" ) )


# ---------------------------------------------------------------------------
# RETIRED 2026-07-27 — the `_PG_ISOLATION_MODULES` allowlist and its
# `_isolate_pg_vector_store` per-test-schema fixture (bug cfcbb703 Family B).
#
# The fixture worked, but its gate was a hand-kept set of TWO module names. Any
# module that constructed a postgres-routed class and was not on the list inherited
# the hazard by default, silently — which is exactly how `test_answer_is_correct`
# spent three weeks writing into the live dev store with the remedy already in the
# tree (bug d621b111).
#
# Rick's ruling on decision 2b20a6d6 (2026-07-27) forbids the shape outright:
# "I absolutely do not want any test touching a live dev data store! If it's not
# isolated then it needs to be removed or fixed." A list of sanctioned offenders is
# neither.
#
# There is one store now, and no constructor takes a location, so a test CANNOT
# redirect a store by handing it a path — the shape that caused this is designed
# out rather than policed. test_vector_store_path_guard.py holds that line: it
# proves no store class accepts a location parameter at all, so a new offender
# fails there loudly instead of needing to be remembered here.
# ---------------------------------------------------------------------------


@pytest.fixture( autouse=True )
def _isolate_session_bridge_dir( tmp_path, monkeypatch ):
    """
    Point the session-bridge scan at a per-test tmp dir, so no unit test's result
    depends on how many Claude sessions happen to be alive on the box.

    🔴 WHY (measured 2026-09-04, and it is the fourth sibling of the three above).
    The fleet cap landed on the spawn path, and `default_fleet_gate`'s default census
    is `find_active_voice_persona_sessions()` — which globs
    `session_bridge.SESSION_DIR` for live bridges. So `spawn_sessions` became a
    function of the OPERATOR'S MACHINE. On a quiet box the tier was green; with a crew
    up, **53 unit tests failed** with

        ValueError: FLEET CAP REFUSED THIS SPAWN — the cap is 8 and the fleet is
        already running 8 (3 manager(s), 5 worker(s))

    and not one of them is a cap test. They are spawn-MECHANICS tests — model
    threading, work-dir resolution, venv provisioning, placement alarms — that now
    pass or fail on how busy the fleet is. A tier whose result moves when nothing in
    the tree moved cannot say anything about the tree.

    ⚠️ THIS ISOLATES THE WORLD, IT DOES NOT STUB THE GATE. `default_fleet_gate` still
    runs for real: it reads the real config, calls the real `census()`, and does the
    real arithmetic — against an EMPTY fleet, which is deterministic. Replacing the
    gate with a lambda would have been easier and would have left its only live path
    unexercised, which is the defect that produced this gate's own guard file.

    A test that wants a POPULATED fleet says so explicitly — it plants bridges in the
    tmp dir, or injects `fleet_gate_fn` / `census_fn`. The cap's own guards do exactly
    that, so the enforcement behaviour is still pinned; what is removed here is only
    the ambient reading nobody asked for.

    Rick's standing ruling on decision 2b20a6d6 (2026-07-27) is the same one the three
    fixtures above cite: no test touches a live data store. A bridge directory holding
    every live seat on the box is a live data store.

    ⚠️ MONKEYPATCHED BY NAME rather than via `LUPIN_HOOK_SESSIONS_DIR`, and the reason
    is in `sessions_dir`'s own docstring: `session_bridge.SESSION_DIR` is an
    IMPORT-TIME constant derived from that function, so setting the env var after the
    module is imported does not move it. The module keeps its patchable name precisely
    for this case, and ~200 existing tests already use it — a test that patches it
    itself simply wins, because monkeypatch applies in order.

    🔴 IT DELIBERATELY DOES NOT CREATE THE DIRECTORY, and that is not laziness.
    `find_active_sessions` returns [] for a directory that does not exist, so an absent
    path is already an empty fleet. Creating one costs something real: `tmp_path` is
    shared with the test itself, and `test_bridge_dir_guard.py` fingerprints that very
    directory and asserts it contains ONLY what the test planted. A `mkdir` here put
    `session-bridges/` into its result and reddened it — an isolation fixture
    manufacturing a failure in the guard that watches for stray files. Measured, then
    fixed at the cause rather than by excluding the name.
    """
    from lupin_cli.claude_code.hooks.lib import session_bridge

    monkeypatch.setattr( session_bridge, "SESSION_DIR",
                         tmp_path / "session-bridges-that-do-not-exist", raising=False )


# ---------------------------------------------------------------------------
# 🔴 NO UNIT TEST MAY FIRE A REAL YES/NO CARD AT A HUMAN — AND THE NET SITS AT THE
# TRANSPORT, NOT AT THE ASK (Rio ⚡, 2026-09-04, row b4e9b59e).
#
# WHAT HAPPENED. On 2026-09-04 a unit tier put ~20 live promotion cards in Rick's
# browser. He read them as one control double-firing; they were 20 separate asks, one
# per test, each with a fresh uuid4 — which is why answering never appeared to matter.
# Two files drove the promotion gate with enforcement active and stubbed nothing, so
# `approval_for_promotion` fell through to `_default_ask` -> `notify_user_sync` ->
# `POST http://localhost:7999/api/notify`. Both a human "yes" and a 120-second timeout
# return allowed, so the tests were green either way: the only symptom was wall clock.
#
# 🔴 WHY THIS IS NOT PATCHED AT `notify_user_sync`, WHICH WAS MY FIRST ANSWER AND WAS
# WRONG. A net on that name is a MODULE ATTRIBUTE, and any test file can set the same
# attribute from its own autouse fixture — which runs AFTER this one, so it wins.
# MEASURED, by printing the bound function at test-body time across the three files:
#
#     test_no_test_file_fires_a_live_human_ask.py        -> _refuse             (net live)
#     test_the_browser_actor_satisfies_both_endpoints.py -> _answered_in_process (net GONE)
#     test_the_edit_door_records_a_real_identity.py      -> _answered_in_process (net GONE)
#
# ⇒ The net was inert on EXACTLY the two files that leaked, and 36 tests passed with it
# and without it. A net sitting on an attribute a local stub can override is not a net.
#
# ⇒ SO IT SITS ONE LAYER DOWN, on this module's own `requests` handle. A file that
# stubs the FUNCTION never reaches here — which is safe, and is that file's own
# protection doing its job. A file that stubs nothing reaches here and is refused.
# Nothing at the function layer can revoke it.
#
# ⚠️ IT RAISES `AssertionError`, NEVER A `requests` EXCEPTION, AND THAT IS LOAD-BEARING.
# `_poll_notification_response` catches `requests.exceptions.RequestException` and
# returns None; a net that raised one would be swallowed, converting "this test leaks"
# into "this test passed having asked nobody" — the weakened-check species.
#
# ⚠️ IT PROXIES THE REST OF THE MODULE rather than replacing it, because the module
# reads `requests.exceptions` in its except clauses; a bare sentinel would turn a
# refusal into an AttributeError inside an except clause.
#
# The discriminating arms live in test_no_test_file_fires_a_live_human_ask.py — they
# hold a function stub in place and still redden when this fixture is removed.
# ---------------------------------------------------------------------------
class _RefusingTransport:
    """
    The real `requests` module with its two outbound verbs replaced by a refusal.

    Requires:
        - real is the live `requests` module

    Ensures:
        - .post / .get raise AssertionError naming the remedy
        - every other attribute (.exceptions, .Response, .Session) proxies through
    """
    def __init__( self, real ):
        self._real = real

    def __getattr__( self, name ):
        return getattr( self._real, name )

    def _refuse( self, verb, url ):
        raise AssertionError(
            f"A unit test reached the LIVE human-notification transport "
            f"({verb} {url}) and would have put a real yes/no card in front of a "
            f"person. Stub the ask in your own file — an autouse fixture that "
            f"monkeypatches "
            f"'lupin_cli.notifications.notify_user_sync.notify_user_sync' — or "
            f"inject your own ask_fn into the gate. Patching "
            f"task_promotion_gate._default_ask does NOT work: approval_for_promotion "
            f"binds it as a def-time default argument."
        )

    def post( self, url, *args, **kwargs ):
        self._refuse( "POST", url )

    def get( self, url, *args, **kwargs ):
        self._refuse( "GET", url )


@pytest.fixture( autouse=True )
def _no_unit_test_may_reach_the_live_ask_transport( monkeypatch ):
    try:
        from lupin_cli.notifications import notify_user_sync as _mod
    except Exception:
        return                                  # module absent -> nothing to leak through

    monkeypatch.setattr( _mod, "requests", _RefusingTransport( _mod.requests ), raising=True )


# ─────────────────────────────────────────────────────────────────────────────
# 🔴 TWO SUITE-WIDE AUTOUSE GUARDS NOW SIT IN THIS FILE, AND THEIR ORDER IS STATED
# RATHER THAN LEFT TO DEFINITION ORDER (Krishna 🦚, 2026-09-05, María's framing).
#
# ⚠️ Both are autouse and suite-wide. If either depended on running before the other,
# definition order would settle it SILENTLY — and getting it wrong FAILS GREEN: a
# guard that runs too late does not error, it just stops guarding. That is
# § UNGUARDED IS A THIRD STATE arriving where nobody thinks to look. So this is
# settled by READ/WRITE SETS, not by watching the suite pass — a green suite under
# either order is equally consistent with both guards being inert.
#
#   _no_unit_test_may_reach_the_live_ask_transport   (row b4e9b59e)
#       WRITES  lupin_cli.notifications.notify_user_sync.requests
#       READS   the real `requests` module, to wrap it
#
#   _a_previous_test_must_not_spend_this_test_s_notify_budget   (row 9fea3b07)
#       WRITES  cosa.rest.notify_rate_limiter._limiter._hits   (a dict, under a lock)
#       READS   nothing
#
# ⇒ DISJOINT read/write sets, in two different packages. Neither can observe the
#   other's effect, so NEITHER DEPENDS ON THE OTHER and the order is free. Verified
#   structurally rather than assumed: `notify_rate_limiter` contains ZERO references
#   to requests / urlopen / socket / http, and its `reset()` is a dict `.clear()`
#   under a lock — it performs no I/O, so the transport net cannot reach it.
#
# ⚠️ WHAT WOULD BREAK THIS, for whoever edits either one next: give the limiter reset
#   any outbound call, or make the transport net consult the limiter, and the sets
#   stop being disjoint — at which point the order becomes load-bearing and this
#   comment becomes wrong. Re-derive it then; do not inherit this paragraph.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture( autouse=True )
def _a_previous_test_must_not_spend_this_test_s_notify_budget():
    """Reset the notify backpressure limiter between tests.

    ROW `9fea3b07`. Four tests in `test_notify_delivered_field.py` passed in
    isolation and failed in every batch, and the failure was a wrong answer
    about the code under test: `429 {"detail":"notify rate limit exceeded"}`.

    THE MECHANISM, and it is shared mutable module state exactly like the three
    fixtures above:

      - `POST /api/notify` is gated by `check_notify_allowed`
        (`notifications.py:880`), whose `_limiter` in `notify_rate_limiter.py`
        is a MODULE-LEVEL SINGLETON holding PROCESS-LIFETIME state - a
        per-source sliding window, 60 per 10 seconds by default.
      - a test that posts with no `sender_id` and no `[PREFIX]` in its message
        falls through `resolve_sender_id` (`notifications.py:388`) to the
        DEFAULT key `claude.code@unknown.deepily.ai`.

    So EVERY such test in the process draws on ONE budget, and nothing reset it.
    A test then failed or passed according to how many notify-posting tests
    happened to run before it - which is what "order-dependent" meant here.

    MEASURED, 56-file batch, before this fixture: 6 failed / 1308 passed, the
    four above plus two in `test_the_answer_mark_waits_for_the_consumer.py`,
    every one of them a 429. In isolation the same files are green, because
    seven posts never reach a cap of sixty.

    WHY A RESET RATHER THAN A UNIQUE SENDER PER TEST: the limiter ships a
    `reset()` whose own docstring says "for tests", and a per-test sender id
    would have to be threaded through every call site that posts. This isolates
    the shared state at its source, which is what the fixtures above do too.

    It runs BEFORE each test rather than after, so a test is protected from its
    predecessors even when that predecessor errored out before any teardown.

    ⚠️ IT CLEARS EVERY SOURCE, NOT JUST THE DEFAULT BUDGET. `reset( source=None )`
    is the clear-all form. That is the broadest isolation and matches the three
    fixtures above, but a test that deliberately pre-seeds ANOTHER source's window
    before the test body runs would be silently cleared. Nothing does that today.

    WHY THE SUITE THAT KNOWS THE LIMITER EXISTS NEVER CAUGHT THIS, and it is a
    property rather than an oversight: A UNIT SUITE THAT TESTS A COMPONENT IN
    ISOLATION IS SUPPOSED TO BE INSULATED FROM PROCESS-WIDE ACCUMULATION. So the
    leak is invisible exactly where the component is under test, and visible only
    from tests that use it INCIDENTALLY - which is where it bit.

    Concretely, and stamped because it is a CENSUS rather than an invariant: at
    961c38f2, exactly one of the twelve tests in
    `src/tests/unit/test_lever_e_backpressure.py` reaches the real singleton's
    `check_and_record`, and that one brackets itself with resets on both sides.
    ⚠️ A stamp buys HONESTY, NOT ACCURACY - that sentence stays true about
    961c38f2 and says nothing about the tree you are reading it in. Re-count
    rather than quote it. This fixture does not depend on it either way.

    ⚠️ THREE EARLIER EXPLANATIONS OF THAT IMMUNITY WERE WRONG OR PARTIAL, recorded
    so nobody re-derives them: "it drives its own keys" (mine - a real but minor
    factor presented as the whole cause), "most tests build their own instance"
    (true of six of twelve), and "one monkeypatches `check_and_record` away" (true
    of exactly one). The accurate statement needed all the routes counted.
    """
    from cosa.rest import notify_rate_limiter

    notify_rate_limiter._limiter.reset()
    yield

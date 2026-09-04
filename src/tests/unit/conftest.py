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

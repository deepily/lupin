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

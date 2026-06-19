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

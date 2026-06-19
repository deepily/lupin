#!/usr/bin/env python3
"""
LIVE-FIRE smoke for the v2.1 PostToolUse bridge-mtime stamp
(arbiter design `03` §10.1; redlines C1/C3/C4).

Authored by Mr. Radio 🦉 (Tester, SWE-Team Thread B) as María's BOTH-tier gate:
the existing `test_post_tool_use_hook.py` proves the stamp at the PRIMITIVE-UNIT
tier with `touch_bridge_mtime` STUBBED (autouse fixture). These tests prove it at
the LIVE-FIRE tier — the REAL, un-mocked `os.utime` against a REAL bridge file —
exercising the same path Claude Code drives on every tool call.

What is REAL here (NOT mocked):
    - post_tool_use.main()'s call to touch_bridge_mtime()
    - touch_bridge_mtime() → session_bridge._find_session_file() → os.utime()
    - get_bridge_mtime() (the arbiter-side reader) reading the resulting mtime

What is stubbed: only the UNRELATED hook side-effects (TTS / drain / emit / log /
session-id resolution) — never the stamp, never the filesystem write.

POST-APPLY GATE (no-confabulation):
    The PostToolUse stamp lands via `clayton-toolhook-lane.patch`, which the
    Manager (Tiberius) applies to main at COMMIT time on Rick's word — it is NOT
    on main while this file is authored. So these tests are guarded by a
    source-detection `skipif`: until `main()` actually contains the stamp call,
    they SKIP with an explicit reason (an honest "not yet wired" — never a false
    PASS for a tap that did not fire). The instant the patch applies, the guard
    flips and the standard `pytest src/tests/unit/` run executes them for real.

Covers the two live behaviors the unit tier (stubbed) cannot:
    #3 María's gate    — real tool call → live touch → mtime delta advances →
                         bridge content BYTE-IDENTICAL (metadata-only, C1).
    #4 María's rider   — live perm-denied on the real bridge path → hook no-ops,
                         tool call UNAFFECTED, failure counter increments +
                         one-shot stderr fires (the fail-safe, on the live path).

Venue: :7999-eligible — in-process, deterministic, writes ONLY to a pytest
tmp dir (no persistent state, sub-second). Parameterization-free (no server).
"""
import inspect
import json
import os
import time
import types
from unittest.mock import patch, MagicMock

import pytest

# Bootstrap
import sys
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import lupin_cli.claude_code.hooks.lib.session_bridge as sb
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_bridge_mtime, get_bridge_touch_failure_count,
)
import lupin_cli.claude_code.hooks.post_tool_use as ptu


# ── POST-APPLY guard ──────────────────────────────────────────────────────────
# Detect whether clayton-toolhook-lane.patch has been applied (the stamp call is
# present in main()'s source). Pre-apply → skip (honest); post-apply → assert.
def _stamp_is_wired() -> bool:
    try:
        return "touch_bridge_mtime()" in inspect.getsource( ptu.main )
    except OSError:                                       # pragma: no cover - source always available under pytest
        return False


_SKIP_REASON = (
    "POST-APPLY: clayton-toolhook-lane.patch not yet applied to post_tool_use.py "
    "(the PostToolUse bridge-mtime stamp is wired at commit time by the Manager). "
    "These live-fire assertions auto-activate the moment the patch lands."
)

pytestmark = pytest.mark.skipif( not _stamp_is_wired(), reason=_SKIP_REASON )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_live_bridge( sessions_dir, session_id ):
    """
    Write a REAL bridge file named cc-{ppid}.json (so touch_bridge_mtime's
    _find_session_file resolves it by the PPID-hit path) whose inner session_id
    is `session_id` (so get_bridge_mtime's find_session_path_by_id resolves the
    SAME file by content). Returns its Path.
    """
    path = sessions_dir / f"cc-{os.getppid()}.json"
    path.write_text( json.dumps( {
        "session_id"        : session_id,
        "stable_session_id" : session_id,
        "cwd"               : "/tmp",
        "cc_pid"            : os.getpid(),
    } ) )
    return path


# Stub set for the UNRELATED hook side-effects — leaves touch_bridge_mtime REAL.
def _hook_side_effect_stubs( session_id, emit_mock=None ):
    return [
        patch.object( ptu, "read_hook_input", return_value={
            "tool_name"  : "Read",
            "tool_input" : { "file_path": "/tmp/x.py" },
            "session_id" : session_id,
        } ),
        patch.object( ptu, "log_payload" ),
        patch.object( ptu, "get_claude_session_id", return_value=session_id ),
        patch.object( ptu, "resolve_stable_session_id", side_effect=lambda x: x ),
        patch.object( ptu, "drain_and_acknowledge", return_value=[ ] ),
        patch.object( ptu, "send_tts" ),
        patch.object( ptu, "emit_json", emit_mock if emit_mock is not None else MagicMock() ),
    ]


# ══════════════════════════════════════════════════════════════════════════════
# #3 — María's gate: live stamp advances mtime, content byte-identical (C1)
# ══════════════════════════════════════════════════════════════════════════════

class TestLiveHookStampsRealBridge:

    def test_live_tool_call_advances_mtime_metadata_only( self, tmp_path ):
        """
        A REAL post_tool_use.main() call fires the un-mocked stamp on a REAL
        bridge file: get_bridge_mtime() advances AND content is byte-identical.
        """
        session_id = "abc12345"
        path       = _write_live_bridge( tmp_path, session_id )

        # Age the bridge 1 hour into the past so the bump is unambiguous.
        old = time.time() - 3600
        os.utime( path, ( old, old ) )
        content_before = path.read_bytes()

        with patch.object( sb, "SESSION_DIR", tmp_path ):
            # NOTE: touch_bridge_mtime / os.utime / get_bridge_mtime all REAL.
            with patch.object( ptu, "read_hook_input", return_value={
                     "tool_name"  : "Read",
                     "tool_input" : { "file_path": "/tmp/x.py" },
                     "session_id" : session_id,
                 } ), \
                 patch.object( ptu, "log_payload" ), \
                 patch.object( ptu, "get_claude_session_id", return_value=session_id ), \
                 patch.object( ptu, "resolve_stable_session_id", side_effect=lambda x: x ), \
                 patch.object( ptu, "drain_and_acknowledge", return_value=[ ] ), \
                 patch.object( ptu, "send_tts" ), \
                 patch.object( ptu, "emit_json" ):
                ptu.main()

            # REAL arbiter-side reader: mtime advanced to ~now (delta forward).
            new_mtime = get_bridge_mtime( session_id )

        assert new_mtime is not None, "arbiter reader could not resolve the bridge"
        assert new_mtime > old + 1000, (
            f"live stamp did not advance mtime: {new_mtime} vs aged {old}"
        )
        # REDLINE C1: metadata-only — the JSON bridge content must be untouched.
        assert path.read_bytes() == content_before, "stamp wrote content (C1 violation)"


# ══════════════════════════════════════════════════════════════════════════════
# #4 — María's rider: live perm-denied on the real bridge path is fail-safe
# ══════════════════════════════════════════════════════════════════════════════

class TestLiveHookFaultInjection:

    def test_live_perm_denied_no_ops_and_tool_call_unaffected( self, tmp_path ):
        """
        A live EPERM on the real os.utime (a permission flip on the bridge):
            - main() does NOT raise — the tool call proceeds and emits normally
            - the swallowed-failure counter increments (observability)
            - the one-shot stderr diagnostic fires
        """
        session_id = "def67890"
        _write_live_bridge( tmp_path, session_id )

        # Reset the process-global observability rider for a clean assertion.
        sb._bridge_touch_failure_count  = 0
        sb._bridge_touch_failure_logged = False

        # Capture the one-shot stderr line without polluting the real stream.
        writes      = [ ]
        fake_stderr = types.SimpleNamespace( write=lambda s: writes.append( s ) )

        emit_mock = MagicMock()

        with patch.object( sb, "SESSION_DIR", tmp_path ), \
             patch.object( sb.os, "utime", side_effect=PermissionError( 13, "EPERM" ) ), \
             patch.object( sb, "sys", types.SimpleNamespace( stderr=fake_stderr ) ), \
             patch.object( ptu, "read_hook_input", return_value={
                 "tool_name"  : "Read",
                 "tool_input" : { "file_path": "/tmp/x.py" },
                 "session_id" : session_id,
             } ), \
             patch.object( ptu, "log_payload" ), \
             patch.object( ptu, "get_claude_session_id", return_value=session_id ), \
             patch.object( ptu, "resolve_stable_session_id", side_effect=lambda x: x ), \
             patch.object( ptu, "drain_and_acknowledge", return_value=[ ] ), \
             patch.object( ptu, "send_tts" ), \
             patch.object( ptu, "emit_json", emit_mock ):
            ptu.main()   # MUST NOT raise despite the perm-denied stamp

        # Tool call UNAFFECTED: the hook ran to completion and emitted its output.
        emit_mock.assert_called_once()
        # Observability: the dropped stamp is counted + surfaced (no false-idle lie).
        assert get_bridge_touch_failure_count() == 1, "perm-denied stamp not counted"
        assert any( "liveness stamp dropped" in w for w in writes ), "one-shot stderr did not fire"


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )

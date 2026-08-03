"""
Phase 2's bridge write has NO local handler, and that is load-bearing — row `0f10ff75`.

WHAT WAS REMOVED, AND WHY IT NEEDED NO CONTROL OF ITS OWN
`register_session.main()` Phase 2 wrapped its carry-forward merge in
`except OSError: pass`. It was DEAD: `atomic_write_json` catches
`( OSError, TypeError, ValueError )` itself, unlinks its temp, prints a stderr
witness and returns `False` — its contract says "Never raises" and the body
agrees. The only other statement under that wrapper was `os.path.exists`, which
swallows `OSError` and returns `False`.

⇒ Deleting unreachable code is **behaviour-neutral**, so there is no mutation that
turns it red, and this file does not pretend to offer one. Restoring the
try/except would change nothing observable. Manufacturing a control for a
no-op change would be a receipt, not an instrument.

🔴 WHAT IS ACTUALLY AT RISK, AND WHAT THESE TESTS PIN
The deletion is only correct **while the callee's contract holds**. If
`atomic_write_json` ever starts propagating, the removed handler is exactly what
would have absorbed it — and `main()` would begin dying inside a SessionStart
hook, on the failure path, where nobody is looking. That is the real exposure,
and it long predates the deletion (the handler only covered `OSError`; a
propagating `TypeError` or `ValueError` would have escaped it anyway).

⇒ So the gate is on the CONTRACT, not on the edit:
  1. `atomic_write_json` never raises, for every failure mode it names.
  2. `main()` survives a failing bridge write and the witness still reaches stderr.

Test 2 is the one that goes red if the contract breaks — verified by making the
callee raise, which is the future regression this file exists to catch.

⚠️ CONTACT GUARD (two-tier, row e2ae4102). `main()` is driven for real here, with
`$HOME` and the bridge seam both redirected. The old guard content-hashed the
WHOLE real directory before and after EVERY test and blamed the test for any
change — which FALSE-ACCUSES on a busy box, where a peer session's own bridge
write during the run trips it. It is now split into a concurrent-safe SCOPED
canary (watches only this file's probe ids) and a whole-directory SERIAL GATE
(`@pytest.mark.serial_bridge_guard`, run only by `src/scripts/run-serial-bridge-
guard.sh` on a quiescent box). Shared logic: `tests.bridge_dir_guard`.
"""

import io
import json
import os
from contextlib import redirect_stderr
from pathlib import Path

import pytest

from lupin_cli.claude_code.hooks.lib.session_bridge import atomic_write_json
from tests.bridge_dir_guard import real_dir_fingerprint, dir_delta, contact_detail


HOOK_MODULE = "lupin_cli.claude_code.hooks.register_session"

REAL_SESSIONS_DIR = Path( os.path.expanduser( "~/.claude/sessions" ) )

# Every session id this file drives through the real `main()` carries "probe";
# a peer session never does, which is why the scoped canary cannot false-accuse.
_TEST_DRIVEN_SESSION_IDS = frozenset( { "probe" } )


@pytest.fixture( autouse=True )
def detect_scoped_real_dir_contact():
    """
    Concurrent-safe tier-1 canary — watches ONLY entries whose name embeds one of
    this file's probe ids, so a peer's concurrent write cannot trip it (row
    e2ae4102). A hardcoded-path regression that writes `cc-<probe-id>.json` into
    the real directory is still caught immediately.

    ⚠️ Cannot see a merge into a LIVE seat (real id, not a probe id) — that is the
    whole-directory SERIAL GATE's job (`test_the_real_bridge_dir_is_untouched_
    SERIAL_GATE`), which is why that gate is load-bearing.
    """
    before = real_dir_fingerprint( session_ids=_TEST_DRIVEN_SESSION_IDS )
    yield
    after = real_dir_fingerprint( session_ids=_TEST_DRIVEN_SESSION_IDS )
    detail = contact_detail( *dir_delta( before, after ) )
    assert detail is None, (
        f"🔴 A TEST DEPOSITED A PROBE-ID FILE IN THE OPERATOR'S REAL BRIDGE DIRECTORY "
        f"({REAL_SESSIONS_DIR}) — the seam was not honored.\n  {detail}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. The callee's contract — the thing the deletion depends on
# ══════════════════════════════════════════════════════════════════════════════

class TestAtomicWriteJsonNeverRaises:
    """
    `atomic_write_json`'s docstring says "Never raises". The removed handler was
    dead BECAUSE of that sentence, so the sentence is now load-bearing and needs
    to be a test rather than prose.

    ⚠️ Each case catches `BaseException`, not the specific type it expects. A test
    that catches only `OSError` would pass a regression that started propagating
    `ValueError` — and the deleted handler caught only `OSError` too, so that is
    precisely the gap being closed.
    """

    @staticmethod
    def _returns_false_without_raising( path, payload ):
        try:
            result = atomic_write_json( path, payload )
        except BaseException as e:                                # noqa: BLE001
            pytest.fail(
                f"atomic_write_json PROPAGATED {type( e ).__name__}: {e!r}. Its contract says "
                "'Never raises', and register_session Phase 2 has no local handler (row 0f10ff75) "
                "— this now kills a SessionStart hook on the failure path."
            )
        return result

    def test_unserializable_payload( self, tmp_path ):
        """TypeError from json.dump, absorbed by the callee."""
        assert self._returns_false_without_raising( tmp_path / "cc-a.json", { "bad": object() } ) is False

    def test_missing_parent_directory( self, tmp_path ):
        """OSError from mkstemp — the case the deleted handler nominally covered."""
        assert self._returns_false_without_raising( tmp_path / "no" / "such" / "cc-b.json", { "k": 1 } ) is False

    def test_replace_failure( self, tmp_path, monkeypatch ):
        """EXDEV-shaped OSError out of os.replace, after the temp file exists."""
        monkeypatch.setattr(
            os, "replace",
            lambda *a, **k: ( _ for _ in () ).throw( OSError( 18, "Invalid cross-device link" ) )
        )
        assert self._returns_false_without_raising( tmp_path / "cc-c.json", { "k": 1 } ) is False

    def test_a_successful_write_still_returns_True( self, tmp_path ):
        """
        🔴 NEGATIVE CONTROL. Three tests above assert `is False`. If
        `atomic_write_json` were broken to return `False` unconditionally — or
        replaced by a stub — all three would still pass while measuring nothing.
        """
        p = tmp_path / "cc-ok.json"
        assert self._returns_false_without_raising( p, { "k": 1 } ) is True
        assert json.loads( p.read_text() ) == { "k": 1 }


# ══════════════════════════════════════════════════════════════════════════════
# 2. The caller survives a failing write — the behaviour the deletion rests on
# ══════════════════════════════════════════════════════════════════════════════

class TestPhase2SurvivesAFailedBridgeWrite:

    @staticmethod
    def _drive_main( monkeypatch, tmp_path, session_id ):
        """Run the REAL main() with $HOME and the bridge seam both redirected."""
        home = tmp_path / "home"
        seam = tmp_path / "seam"
        ( home / ".claude" / "sessions" ).mkdir( parents=True )
        seam.mkdir()
        monkeypatch.setenv( "HOME", str( home ) )
        monkeypatch.setenv( "LUPIN_HOOK_SESSIONS_DIR", str( seam ) )

        import importlib
        module = importlib.import_module( HOOK_MODULE )
        monkeypatch.setattr( module, "read_hook_input",
                             lambda: { "session_id": session_id, "cwd": "/tmp",
                                       "transcript_path": "/x" } )
        monkeypatch.setattr( module, "emit_json", lambda *a, **k: None )

        escaped = [ ]
        buffer  = io.StringIO()
        with redirect_stderr( buffer ):
            try:
                module.main()
            except SystemExit:
                pass
            except Exception as e:                                # noqa: BLE001
                escaped.append( e )
        return buffer.getvalue(), escaped, seam, module

    def test_a_failing_write_does_not_escape_and_still_witnesses( self, monkeypatch, tmp_path ):
        """
        The callee fails the write the way it really does — returning False after
        printing its witness. Phase 2 has no handler, so this asserts the failure
        is absorbed AT THE MECHANISM and still visible on stderr.

        ⚠️ The stub is a BOUNDARY replacement (it stands in for the write), not a
        re-implementation of the logic under test: what is being verified is the
        CALLER's survival and the witness reaching stderr, neither of which the
        stub performs on the caller's behalf.
        """
        import importlib
        module = importlib.import_module( HOOK_MODULE )

        def failing_write( path, data ):
            print( f"[atomic_write_json] WARNING: bridge write FAILED for {path}: "
                   "OSError('probe') — the field did NOT persist", file=os.sys.stderr )
            return False

        monkeypatch.setattr( module, "atomic_write_json", failing_write )
        err, escaped, seam, _ = self._drive_main( monkeypatch, tmp_path, "write-fail-probe" )

        assert not escaped, f"main() propagated {escaped!r} out of a FAILED bridge write"
        assert "bridge write FAILED" in err, (
            "the callee's witness did not reach stderr — with no handler at the call site, "
            "that witness is the ONLY signal a failed bridge write produces (row 0f10ff75)"
        )
        assert not list( seam.glob( "cc-*.json" ) ), "the write was supposed to fail"

    def test_a_RAISING_callee_is_caught_by_this_gate( self, monkeypatch, tmp_path ):
        """
        🔴 THE CONTROL FOR THE DELETION. Simulates the future regression: the callee
        starts PROPAGATING instead of returning False. With no local handler, that
        exception escapes Phase 2 — and this test proves the escape is observable
        rather than silent, so the contract above is a real gate and not decoration.

        The predicted failure of `test_a_failing_write_does_not_escape_and_still_
        witnesses` under that regression is exactly what is asserted here: an
        exception in `escaped`.
        """
        import importlib
        module = importlib.import_module( HOOK_MODULE )

        def raising_write( path, data ):
            raise OSError( 28, "No space left on device" )

        monkeypatch.setattr( module, "atomic_write_json", raising_write )
        _, escaped, _, _ = self._drive_main( monkeypatch, tmp_path, "raise-probe" )

        assert escaped and isinstance( escaped[ 0 ], OSError ), (
            "a RAISING atomic_write_json did NOT escape Phase 2 — something is still "
            "swallowing it, which means the contract tests above cannot detect a "
            "regression in the callee and this gate is decoration."
        )

    def test_a_healthy_write_still_lands( self, monkeypatch, tmp_path ):
        """
        🔴 NEGATIVE CONTROL for the harness itself. Both tests above stub the write,
        so neither would notice if `_drive_main` stopped reaching Phase 2 at all —
        a payload change, an early exit, a broken import would give the same
        'no exception escaped' and 'no bridge in seam' readings.
        """
        _, escaped, seam, _ = self._drive_main( monkeypatch, tmp_path, "healthy-probe" )
        assert not escaped, f"main() propagated {escaped!r} on the healthy path"
        bridges = list( seam.glob( "cc-*.json" ) )
        assert len( bridges ) == 1, f"Phase 2 was not reached; bridges: {[ b.name for b in bridges ]}"
        assert json.loads( bridges[ 0 ].read_text() )[ "session_id" ] == "healthy-probe"


# ══════════════════════════════════════════════════════════════════════════════
# 3. The row's open item: is this the only dead handler?
# ══════════════════════════════════════════════════════════════════════════════

REGISTER_SESSION = ( Path( __file__ ).resolve().parents[ 3 ]
                     / "src" / "lupin_cli" / "claude_code" / "hooks" / "register_session.py" )


def _phase2_write_handlers():
    """
    Every `except` clause that would catch an exception from Phase 2's
    `atomic_write_json( session_file, merged )` call, by AST — not by regex.

    ⚠️ REGEX WAS THE WRONG TOOL AND THE FIRST DRAFT PROVED IT. The obvious
    pattern — a `try:` immediately followed by an `atomic_write_json` call and
    then an `except` — **would not have matched the defect this row is about.**
    The removed block had six statements between the `try:` and the call. A
    predicate that matches a NARROWER shape than the thing it guards passes on a
    clean tree and on a dirty one alike, and it is exactly the failure mode this
    fleet spent the day cataloguing. So: walk the tree, find the call, and ask
    which handlers actually enclose it.
    """
    import ast

    tree = ast.parse( REGISTER_SESSION.read_text() )

    target = None
    for node in ast.walk( tree ):
        if ( isinstance( node, ast.Call )
             and isinstance( node.func, ast.Name )
             and node.func.id == "atomic_write_json"
             and len( node.args ) == 2
             and isinstance( node.args[ 1 ], ast.Name )
             and node.args[ 1 ].id == "merged" ):
            target = node
            break
    assert target is not None, (
        "could not find Phase 2's `atomic_write_json( session_file, merged )` call in "
        f"{REGISTER_SESSION.name} — this check has lost its subject and is no longer "
        "guarding anything. Fix the locator, do not delete the test."
    )

    handlers = [ ]
    for node in ast.walk( tree ):
        if not isinstance( node, ast.Try ):
            continue
        if any( n is target for stmt in node.body for n in ast.walk( stmt ) ):
            for h in node.handlers:
                handlers.append( ast.unparse( h.type ) if h.type is not None else "bare except" )
    return handlers


class TestPhase2HasNoLocalHandler:
    """
    The row's open item was *"whether the other five hook call sites carry the same
    dead handler — treat 'one instance' as 'one instance found', not as the count."*

    SWEPT BY READING, not by a predicate — all 10 non-test call sites of
    `atomic_write_json`:
      · `session_bridge.py` ×8 — every one also wraps `open()` / `json.load()`
        inside the same `try`, so `except ( json.JSONDecodeError, OSError )` is
        LIVE; those two genuinely raise.
      · `register_session.py:174` (`_record_listener_pid`) — no handler at all,
        with a comment saying "never raises". Correct already.
      · `register_session.py` Phase 2 — the only dead one. Removed.

    ⚠️ That sweep is a MEASUREMENT, not a guarantee about future sites. Deciding
    "this handler is unreachable" in general needs reachability analysis, not a
    source scan, so no general detector is offered here — claiming one would be
    the narrower-predicate defect again. What IS pinned is the specific block.
    """

    def test_the_dead_OSError_handler_has_not_come_back( self ):
        handlers = _phase2_write_handlers()
        assert not handlers, (
            f"Phase 2's bridge write is wrapped in handler(s) {handlers} again — row 0f10ff75. "
            "`atomic_write_json` catches ( OSError, TypeError, ValueError ) itself and returns "
            "False, so a handler here is unreachable and reads as a guard that is not there. "
            "If a real behaviour change is intended (checking the return), that is remedy (2) "
            "and needs its own decision, not a reinstated dead except."
        )

    def test_the_locator_can_see_a_handler( self, tmp_path, monkeypatch ):
        """
        🔴 NEGATIVE CONTROL. The test above passes if `_phase2_write_handlers()`
        returns `[]` — including if it returns `[]` because the AST walk is broken,
        the enclosing-`try` test never matches, or the file moved. An empty list
        must be evidence of absence, not evidence of a broken instrument.

        This points the locator at a copy of the file with the handler restored and
        requires it to be reported.
        """
        source  = REGISTER_SESSION.read_text()
        anchor  = "        atomic_write_json( session_file, merged )"
        assert source.count( anchor ) == 1, "anchor for the planted regression is not unique"
        planted = source.replace(
            anchor,
            "        try:\n"
            "            atomic_write_json( session_file, merged )\n"
            "        except OSError:\n"
            "            pass"
        )
        fake = tmp_path / "register_session.py"
        fake.write_text( planted )

        monkeypatch.setitem( globals(), "REGISTER_SESSION", fake )

        assert _phase2_write_handlers() == [ "OSError" ], (
            "the locator did not report a deliberately planted `except OSError` — it is not "
            "looking where it claims, so its empty result on the real file proves nothing."
        )


# ══════════════════════════════════════════════════════════════════════════════
# 4. The whole-directory hazard guard — SERIAL GATE (row e2ae4102)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.serial_bridge_guard
def test_the_real_bridge_dir_is_untouched_SERIAL_GATE( monkeypatch, tmp_path ):
    """
    Whole-directory contact guard (row 8ccc20ab).

    🔴 NOT RUN BY THE CONCURRENT UNIT SUITE. `pytest.ini` addopts carries
    `-m "not serial_bridge_guard"`, so this is deselected everywhere by default.
    It is invoked ONLY by `src/scripts/run-serial-bridge-guard.sh`, which the
    operator runs on a QUIESCENT box at merge time per CLAUDE.md § PR MERGE
    REQUIREMENTS. If that script or its checklist line is ever removed, this
    whole-directory guard is silently gone — the scoped canary above cannot stand
    in for it, because it does not see a merge into a live seat.

    On a quiescent box any change to the real directory across this test IS
    attributable, so the whole-directory fingerprint is valid. It drives the real
    `main()` with `$HOME` and the seam redirected (a correctly-seamed hook writes
    into tmp and this passes) and fails if a hardcoded-path regression reaches the
    real directory instead.
    """
    before = real_dir_fingerprint()

    home = tmp_path / "home"
    seam = tmp_path / "seam"
    ( home / ".claude" / "sessions" ).mkdir( parents=True )
    seam.mkdir()
    monkeypatch.setenv( "HOME", str( home ) )
    monkeypatch.setenv( "LUPIN_HOOK_SESSIONS_DIR", str( seam ) )

    import importlib
    module = importlib.import_module( HOOK_MODULE )
    monkeypatch.setattr( module, "read_hook_input",
                         lambda: { "session_id": "write-probe-serial", "cwd": "/tmp",
                                   "transcript_path": "/x" } )
    monkeypatch.setattr( module, "emit_json", lambda *a, **k: None )
    with redirect_stderr( io.StringIO() ):
        try:
            module.main()
        except SystemExit:
            pass
        except Exception:                                         # noqa: BLE001
            pass

    after = real_dir_fingerprint()
    detail = contact_detail( *dir_delta( before, after ) )
    assert detail is None, (
        f"🔴 main() TOUCHED THE OPERATOR'S REAL BRIDGE DIRECTORY ({REAL_SESSIONS_DIR}) — row 8ccc20ab.\n  {detail}"
    )

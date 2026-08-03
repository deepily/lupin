"""
The two SILENT no-bridge exits in SessionStart get a witness — store row e9822f8d.

THE ROW: a spawned child's SessionStart completed and wrote NO BRIDGE AT ALL. The seat
ran, worked correctly and DM'd its manager, but had `voice_persona: null`,
`claude_code.source: "fallback"`, and `set_session_topic()` returned
`{"status":"error","reason":"No bridge file found"}`. Three instruments gave three
answers about one live session: `list_spawned_sessions` said alive/live, `dm_send` said
recipient_unresolved AND omitted it from `candidate_alternatives`, and the session itself
was fully functional. Healthy, invisible and unaddressable at once — outbound works,
inbound does not.

⚠️ WHY THE EXISTING WITNESSES DO NOT COVER THIS, which is the whole reason the row
survived two commits that named it:

  · `99589967` witnesses the persona-ALLOCATION give-up (`register_session.py`).
  · `atomic_write_json` witnesses the bridge WRITE failure (`session_bridge.py`).

Both live DOWNSTREAM of the branches tested here. **A witness bolted onto a later step
cannot fire when the hook never reaches that step.** The row's own body drew that line
and it still holds: *"in 86aa79ac the bridge EXISTED with a null persona (the except fired
and still wrote). Here there is NO BRIDGE AT ALL — a different failure point, earlier in
the hook."*

⚠️ WHAT THESE TESTS DO NOT CLAIM. They do not identify which branch fired on 2026-07-21;
that seat's payload was never captured. They make the two silent exits OBSERVABLE, so the
next occurrence is diagnosable from the session's own transcript rather than by hand.
Making a failure loud is not the same as finding it, and this file does not pretend
otherwise.
"""

import hashlib
import io
import json
import os
import runpy
import sys
from contextlib import redirect_stderr
from pathlib import Path

import pytest


# ── SERIAL BRIDGE GUARD (bug 2508b1ce) ──────────────────────────────────────────────
# EVERY test here runs under the autouse `isolate_home_and_detect_real_dir_contact`
# fixture below, which fingerprints the operator's REAL ~/.claude/sessions directory
# before and after the test and asserts it is byte-identical. A LIVE peer session writing
# its own bridge during the test window moves that fingerprint through no fault of this
# test — a false accusation, which is exactly what bug 2508b1ce surfaced. So the WHOLE
# module carries the marker (not a per-test decorator like the siblings, because here the
# autouse fixture makes every test do the contact check) and is deselected from the
# default parallel run via pytest.ini addopts `-m "not serial_bridge_guard"`. It runs
# only under src/scripts/run-serial-bridge-guard, where nothing else touches the dir.
pytestmark = pytest.mark.serial_bridge_guard


HOOK_MODULE = "lupin_cli.claude_code.hooks.register_session"

# Captured AT IMPORT, before any fixture rewrites $HOME — this must name the
# operator's REAL bridge directory or the control below is watching a decoy.
REAL_SESSIONS_DIR = Path( os.path.expanduser( "~/.claude/sessions" ) )


def _real_bridge_fingerprint():
    """
    Content fingerprint of every REAL bridge, for the contact detector below.

    Hashes CONTENT, not just names or a count. bug 2508b1ce turned on exactly
    this distinction: when this file's healthy-payload test merged into a LIVE
    seat's bridge, the file count did not move, so a count-based check cleared
    the test twice while it was actively corrupting a running session's identity
    file. Size alone is likewise insufficient — a merge can swap one id for
    another of equal length.
    """
    if not REAL_SESSIONS_DIR.is_dir():
        return { }
    out = { }
    for p in sorted( REAL_SESSIONS_DIR.glob( "cc-*.json" ) ):
        try:
            out[ p.name ] = hashlib.sha256( p.read_bytes() ).hexdigest()
        except OSError:
            out[ p.name ] = "<unreadable>"
    return out


@pytest.fixture( autouse=True )
def isolate_home_and_detect_real_dir_contact( monkeypatch, tmp_path ):
    """
    🔴 bug 2508b1ce — THIS FILE USED TO WRITE INTO THE OPERATOR'S LIVE BRIDGES.

    `_run_main_with_payload` calls the REAL `register_session.main()`. It mocked
    only `read_hook_input` and `emit_json`, and `main()` Phase 2 resolves its
    directory as `os.path.expanduser( "~/.claude/sessions" )` — hardcoded, with no
    env seam — and keys the file on a pid from `_resolve_cc_pid()` walking the
    real process tree.

    ⇒ `test_a_healthy_payload_emits_NEITHER_witness` passes a payload WITH a
    `session_id` (deliberately — it asserts neither witness fires), so `main()`
    runs PAST both guards into Phase 2 and writes a real bridge. When pytest's
    resolved pid was a live `claude` process, that MERGED into that seat's own
    bridge: observed on 2026-07-27 rewriting a running worker's `session_id` to
    the fixture value `abc-123` and dropping its `session_topic`.

    ⚠️ The read-modify-write can also NULL `voice_persona` (`atomic_write_json`'s
    own docstring says so), which would take a persona out from under a working
    session. That is an operational failure, not a reporting one.

    TWO parts, and the second is the one that matters:
      1. `$HOME` is redirected, so `expanduser` resolves into `tmp_path`.
      2. A CONTACT DETECTOR: the real directory is fingerprinted by content
         before and after every test and must be byte-identical. It does not
         assert "we used tmp" — it asserts the real dir was NOT TOUCHED, which
         is the claim that actually matters and the one a `tmp_path`-shaped
         assertion cannot make.

    ⇒ Remove the `setenv` below and this fixture FAILS, naming the file it wrote.
    """
    before = _real_bridge_fingerprint()

    monkeypatch.setenv( "HOME", str( tmp_path ) )
    ( tmp_path / ".claude" / "sessions" ).mkdir( parents=True, exist_ok=True )

    yield

    after   = _real_bridge_fingerprint()
    created = sorted( set( after ) - set( before ) )
    removed = sorted( set( before ) - set( after ) )
    changed = sorted( n for n in ( set( before ) & set( after ) ) if before[ n ] != after[ n ] )

    assert not ( created or removed or changed ), (
        "🔴 THIS TEST TOUCHED THE OPERATOR'S REAL BRIDGE DIRECTORY "
        f"({REAL_SESSIONS_DIR}) — bug 2508b1ce.\n"
        f"  created: {created}\n  removed: {removed}\n  CHANGED (merged into a live seat): {changed}\n"
        "A changed file is the dangerous case: it rewrites a RUNNING session's identity, "
        "leaves the file count unchanged, and can null that seat's voice_persona."
    )


def _run_main_with_payload( monkeypatch, payload ):
    """
    Drive `main()` with a controlled hook payload and capture stderr.

    Requires:
        - payload is what read_hook_input() should return (dict, {} or None)
        - the autouse isolation fixture above is active (it is, for this module)

    Ensures:
        - returns the captured stderr text
        - SystemExit is absorbed; the branches under test are expected to exit
        - any OTHER exception is RECORDED into `swallowed_exceptions`, not discarded
    """
    import importlib
    module = importlib.import_module( HOOK_MODULE )

    monkeypatch.setattr( module, "read_hook_input", lambda: payload )
    monkeypatch.setattr( module, "emit_json", lambda *a, **k: None )

    swallowed_exceptions.clear()
    buffer = io.StringIO()
    with redirect_stderr( buffer ):
        try:
            module.main()
        except SystemExit:
            pass
        except Exception as e:                                    # noqa: BLE001
            # ⚠️ STILL SWALLOWED, BUT NO LONGER SILENT (bug 2508b1ce). The prior
            # version discarded this with a comment noting the payload "falls
            # THROUGH into later phases, which touch tmux / the network / the
            # filesystem." That comment NAMED the hazard that was corrupting live
            # bridges — and naming a hazard in a comment is not a guard against it.
            # Recording the exception makes the swallow inspectable; the contact
            # detector above makes the filesystem reach impossible.
            swallowed_exceptions.append( e )
    return buffer.getvalue()


# Exceptions absorbed by the most recent `_run_main_with_payload` call.
swallowed_exceptions: list = []


# ----------------------------------------------------------------------------------
# Branch A — the payload is empty or unreadable
# ----------------------------------------------------------------------------------

@pytest.mark.parametrize( "payload", [ None, { }, "" ] )
def test_an_empty_payload_now_says_so_on_stderr( monkeypatch, payload ):
    """
    stderr is the correct channel and NOT an arbitrary one: hook stderr lands in the
    session's OWN transcript as a `hook_success` attachment, which the row names as the
    first place to look (the 86aa79ac method). A witness the affected seat cannot see
    would be no better than the silence.
    """
    err = _run_main_with_payload( monkeypatch, payload )
    assert "register_session" in err
    assert "NO session bridge written" in err


def test_the_empty_payload_witness_names_the_CONSEQUENCE_not_just_the_event( monkeypatch ):
    """
    "payload was empty" tells a reader nothing actionable. The three consequences —
    no persona, no session topic, no inbound DM — are what make a green roster a lie,
    and they are what a manager needs to recognize the state from the outside.
    """
    err = _run_main_with_payload( monkeypatch, { } )
    assert "voice persona" in err
    assert "session topic" in err
    assert "DM" in err
    assert "e9822f8d" in err          # the row, so the next reader lands on the diagnosis


# ----------------------------------------------------------------------------------
# Branch B — the payload parses but carries no session_id
# ----------------------------------------------------------------------------------

def test_a_payload_without_session_id_now_says_so_on_stderr( monkeypatch ):
    """
    🔴 THE BRANCH THE OTHER TWO WITNESSES CANNOT REACH. Everything in Phase 2 — the
    stable-id lockfile, the /clear detection, the bridge write — is inside
    `if session_id:`. A payload that parses but carries no session_id falls straight
    through to Phase 3 having written nothing.
    """
    err = _run_main_with_payload( monkeypatch, { "cwd": "/tmp", "transcript_path": "/x" } )
    assert "no session_id" in err
    assert "NO session bridge written" in err


def test_the_no_session_id_witness_names_the_KEYS_it_did_receive( monkeypatch ):
    """
    The payload's keys are the only evidence of WHY the field was absent — a renamed
    field, a truncated write, a different event shape. A witness that reports "absent"
    without reporting what WAS present sends the next reader back to guessing, which is
    the state this row has been in since 2026-07-21.
    """
    err = _run_main_with_payload( monkeypatch, { "cwd": "/tmp", "transcript_path": "/x" } )
    assert "cwd" in err and "transcript_path" in err


@pytest.mark.parametrize( "blank", [ "", None ] )
def test_a_blank_or_null_session_id_is_treated_as_absent( monkeypatch, blank ):
    """`payload.get("session_id","")` yields "" for both, and "" is falsy — one branch."""
    err = _run_main_with_payload( monkeypatch, { "session_id": blank, "cwd": "/tmp" } )
    assert "no session_id" in err


# ----------------------------------------------------------------------------------
# 🔴 THE NEGATIVE CONTROL — a witness that always fires is noise, not evidence
# ----------------------------------------------------------------------------------

def test_a_healthy_payload_emits_NEITHER_witness( monkeypatch ):
    """
    🔴 THE CONTROL THAT MUST FAIL IF EITHER WITNESS IS UNCONDITIONAL. A no-bridge
    warning printed on every healthy SessionStart would train every reader to ignore it —
    and this fleet's whole problem with this row is a signal nobody could see. An alarm
    that fires always is indistinguishable from one that never fires, one reader later.

    The healthy path may still raise downstream (tmux, network, filesystem); that is
    absorbed. What is asserted is that NEITHER no-bridge witness appears BEFORE it.
    """
    err = _run_main_with_payload(
        monkeypatch, { "session_id": "abc-123", "cwd": "/tmp", "transcript_path": "/x" }
    )
    assert "NO session bridge written" not in err
    assert "no session_id" not in err

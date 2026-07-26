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

import io
import json
import runpy
import sys
from contextlib import redirect_stderr

import pytest


HOOK_MODULE = "lupin_cli.claude_code.hooks.register_session"


def _run_main_with_payload( monkeypatch, payload ):
    """
    Drive `main()` with a controlled hook payload and capture stderr.

    Requires:
        - payload is what read_hook_input() should return (dict, {} or None)

    Ensures:
        - returns the captured stderr text
        - SystemExit is absorbed; both branches under test are expected to exit or
          fall through, and neither outcome is what is being asserted
    """
    import importlib
    module = importlib.import_module( HOOK_MODULE )

    monkeypatch.setattr( module, "read_hook_input", lambda: payload )
    monkeypatch.setattr( module, "emit_json", lambda *a, **k: None )

    buffer = io.StringIO()
    with redirect_stderr( buffer ):
        try:
            module.main()
        except SystemExit:
            pass
        except Exception:
            # A payload with no session_id falls THROUGH into later phases, which
            # touch tmux / the network / the filesystem. Those are not under test —
            # the witness fires before any of them, and the buffer already holds it.
            pass
    return buffer.getvalue()


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

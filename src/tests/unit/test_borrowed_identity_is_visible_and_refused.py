#!/usr/bin/env python3
"""
THE GUESS MUST BE VISIBLE AT THE BOUNDARY, AND AN IDENTITY-BEARING WRITE MUST REFUSE IT.

María's ruling, 2026-09-03, on the identity bleed Pocholo measured and Maya reduced to a
rule at `c5072728`: **make the guess visible, do NOT delete tier 4.** Deleting the tier
outright converts a silent wrong-seat into a fail-to-resolve, and a false alarm is the
thing that cost Rick an afternoon.

So this file does NOT assert that tier 4 stops firing — it asserts the two properties the
ruling actually names:

    1. the SOURCE reaches the caller alongside the id, so a guess and a certainty no
       longer arrive in the same shape;
    2. an identity-bearing write (`task_*`, `dm_send`, memento) REFUSES an identity that
       was guessed, while the same write is untouched when the identity is definitive.

⚠️ THE SECOND ARM NEEDS ITS NEGATIVE CONTROL OR IT MEASURES NOTHING. A guard that refused
every write would satisfy "a borrowed identity is refused" perfectly. The control that a
`ppid` identity is NOT refused is what makes the refusal a discriminator rather than a
mute — this repo's § UNGUARDED IS A THIRD STATE, applied before the fact rather than
after it.

⚠️ WHAT THIS FILE DOES NOT CLAIM. It does not claim the bleed is closed. Tier 4 still
adopts a live stranger's bridge by design; Maya's two arms in
`test_session_bridge_identity_bleed.py` assert the VALUE and stay red under this ruling,
which is a decision on the record and not an oversight.

VENUE: :7999-eligible — tmp_path directories and one short-lived child process. No
server, no network, no shared state.
"""
import json
import os
import subprocess

import pytest

from lupin_cli.claude_code.hooks.lib import session_bridge as sb


STRANGER_ID = "1c8db7e3"
OWN_ID      = "4ad68cc8"


@pytest.fixture
def live_stranger():
    proc = subprocess.Popen( [ "sleep", "30" ] )
    yield proc.pid
    proc.kill()
    proc.wait()


@pytest.fixture
def bridge_dir( tmp_path, monkeypatch ):
    monkeypatch.setattr( sb, "SESSION_DIR", tmp_path )
    monkeypatch.delenv( "CLAUDE_SESSION_ID", raising=False )
    sb.clear_cached_session_id()
    yield tmp_path
    sb.clear_cached_session_id()


def _write_bridge( directory, pid, session_id, cwd ):
    path = directory / f"cc-{pid}.json"
    path.write_text( json.dumps( {
        "session_id"        : session_id,
        "stable_session_id" : session_id,
        "cwd"               : cwd,
    } ) )
    return path


# ── 1. the source reaches the caller ────────────────────────────────────────

def test_a_BORROWED_id_arrives_labelled_as_a_guess( bridge_dir, live_stranger ):
    """
    The load-bearing arm. Same setup as the bleed: no bridge of our own, one live
    stranger sharing our working directory. The id still comes back — the tier is kept
    on purpose — but the caller is now told how it was reached.
    """
    _write_bridge( bridge_dir, live_stranger, STRANGER_ID, os.getcwd() )

    session_id, source = sb.get_claude_session_id_with_source()

    assert session_id == STRANGER_ID, (
        "setup did not reach tier 4 — this arm is not measuring what it claims"
    )
    assert source == sb.SOURCE_CWD_FALLBACK, (
        f"the id was reached by a cwd guess and reported source '{source}'. A caller "
        f"cannot refuse what it cannot see."
    )


def test_NEGATIVE_CONTROL_an_OWNED_id_is_not_labelled_a_guess( bridge_dir ):
    """
    Without this, a resolver that stamped every answer 'cwd_fallback' would pass the arm
    above and destroy every write on the box.
    """
    _write_bridge( bridge_dir, os.getppid(), OWN_ID, os.getcwd() )

    session_id, source = sb.get_claude_session_id_with_source()

    assert session_id == OWN_ID
    assert source == sb.SOURCE_PPID, f"a definitive PPID match was reported as '{source}'"


def test_the_WAITING_resolver_carries_the_source_too( bridge_dir, live_stranger ):
    """
    `wait_for_session_id` is the door the MCP server's watcher actually uses. A source
    exposed only on the non-blocking twin would leave the server exactly as blind.
    """
    _write_bridge( bridge_dir, live_stranger, STRANGER_ID, os.getcwd() )

    session_id, source = sb.wait_for_session_id_with_source( timeout=1.0, poll_interval=0.1 )

    assert session_id == STRANGER_ID
    assert source == sb.SOURCE_CWD_FALLBACK


def test_the_env_var_and_the_generated_fallback_are_NAMED_not_blank( bridge_dir, monkeypatch ):
    """
    Five tiers, five names. A source that is empty for two of them pushes the caller back
    to guessing which is exactly the defect.
    """
    monkeypatch.setenv( "CLAUDE_SESSION_ID", "env-supplied-id" )
    sb.clear_cached_session_id()
    assert sb.get_claude_session_id_with_source() == ( "env-supplied-id", sb.SOURCE_ENV )

    monkeypatch.delenv( "CLAUDE_SESSION_ID", raising=False )
    sb.clear_cached_session_id()
    session_id, source = sb.get_claude_session_id_with_source()   # empty dir → nothing to find
    assert source == sb.SOURCE_GENERATED, f"an invented id reported source '{source}'"
    assert session_id == sb._fallback_session_id


def test_the_BARE_accessors_still_return_a_plain_string( bridge_dir, live_stranger ):
    """
    The tier is kept AND every existing caller is untouched: this is the half of the
    ruling that keeps a wrong-seat from becoming a fail-to-resolve.
    """
    _write_bridge( bridge_dir, live_stranger, STRANGER_ID, os.getcwd() )

    assert sb.get_claude_session_id() == STRANGER_ID
    assert sb.wait_for_session_id( timeout=1.0, poll_interval=0.1 ) == STRANGER_ID


# ── 2. an identity-bearing write refuses a guess ────────────────────────────

def test_an_identity_bearing_write_REFUSES_a_borrowed_identity():
    """
    The refusal names the verb, says the identity was guessed, and does not pretend the
    write happened.
    """
    from lupin_mcp import cosa_voice_mcp as m

    refusal = m._refuse_borrowed_identity( "task_create", source=sb.SOURCE_CWD_FALLBACK )

    assert refusal is not None, "a guessed identity was allowed to write"
    assert refusal[ "status" ] == "error"
    assert refusal[ "reason" ] == "borrowed_identity"
    assert "task_create" in refusal[ "detail" ]


@pytest.mark.parametrize( "source", [ "ppid", "grandparent", "env", "generated_fallback" ] )
def test_NEGATIVE_CONTROL_every_other_source_writes_normally( source ):
    """
    🔴 THE ARM THAT MAKES THE REFUSAL A DISCRIMINATOR. A guard that refused unconditionally
    would satisfy the arm above and break every seat on the box.

    `generated_fallback` is in this list deliberately: an invented id is nobody else's, so
    it is wrong-but-harmless, where a borrowed one files work under a real colleague.
    """
    from lupin_mcp import cosa_voice_mcp as m

    assert m._refuse_borrowed_identity( "task_create", source=source ) is None


def test_the_MCP_session_info_payload_carries_the_resolution_source():
    """
    `get_session_metadata` has computed `resolution_source` all along and the MCP boundary
    dropped it, reporting only the coarse "session_file". A field computed and discarded at
    the boundary is the same defect one layer up.
    """
    from lupin_mcp import cosa_voice_mcp as m

    assert "resolution_source" in m._session_info_payload( {
        "session_id"        : STRANGER_ID,
        "source"            : "session_file",
        "resolution_source" : sb.SOURCE_CWD_FALLBACK,
    } )

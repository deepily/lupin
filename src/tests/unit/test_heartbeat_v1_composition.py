#!/usr/bin/env python3
"""
Heartbeat Hook — v1 adapter-contract COMPOSITION test.

Exercises the full v1 decision pipeline end-to-end across the four shipped
leaf modules (hold + poke-cap + decision), exactly as the Rachel-owned
Branch-C `stop.py` adapter will drive them — but with ZERO `stop.py` and ZERO
server dependency (hermetic, tmp dirs). This is the integration test Tiffany
owns per the lane/test split (Tiberius-approved 2026-06-04); Rachel wires the
`stop.py` glue, this validates the contract her glue must satisfy.

**v1 scope (reconciled with Rachel 2026-06-04):** the adapter wires ONLY the
hold-declared signal — `oracle_verdict=None`. So v1:
    - honors a fresh, reasoned hold (no poke),
    - pokes a session that left a STALE / reasonless self-declared
      `work_owed=True` hold,
    - never pokes a session with no hold (conservative).
v1 does NOT catch the undeclared-lazy-stop FM-19 case (no hold → no poke) —
that is v2, gated on María's §C.3 Q4 (authoritative TODO source + owned_by_me)
which feeds a real `oracle_verdict`. When v2 lands, only the `None` below
changes; this test's hold/cap lifecycle assertions still hold.

Venue: :7999-eligible / local — pure module composition, tmp-dir only, no
persistent state, no server, sub-second.
"""
import datetime
import os

from lupin_cli.claude_code.hooks.lib import heartbeat_hold as hold_mod
from lupin_cli.claude_code.hooks.lib import heartbeat_poke_cap as cap_mod
from lupin_cli.claude_code.hooks.lib import heartbeat_decision as decision_mod


UTC = datetime.timezone.utc
CAP = 3


def _backdate_hold_mtime( base_dir, session_id, now, seconds=10_000 ):
    """B1 (d44b7068): hold freshness is anchored on the FILE mtime, not held_at.
    A test that wants a STALE hold must backdate the written file's mtime to
    `seconds` before the (fixed) `now` — write_hold alone stamps a real-now mtime."""
    path = base_dir / f".heartbeat-hold-{session_id}.json"
    old  = ( now - datetime.timedelta( seconds=seconds ) ).timestamp()
    os.utime( path, ( old, old ) )


def _v1_adapter_step( session_id, base_dir, now=None ):
    """
    Mirror the v1 Branch-C adapter's side-effect shell (minus stop.py / notify).

    Reads the hold + current poke count, calls decide_heartbeat with
    oracle_verdict=None (v1), and applies the increment side-effect the
    result declares. Returns the full result for assertion.
    """
    hold   = hold_mod.read_hold( session_id, base_dir=base_dir )
    count  = cap_mod.get_poke_count( session_id, base_dir=base_dir )
    result = decision_mod.decide_heartbeat( hold, None, count, CAP, now=now )   # v1: oracle None
    if result[ "should_increment" ]:
        cap_mod.increment_poke_count( session_id, base_dir=base_dir )
    return result


# ── Scenario 1 — no hold → conservative no-poke ───────────────────────────────

def test_v1_no_hold_does_not_poke( tmp_path ):
    r = _v1_adapter_step( "s_nohold", base_dir=tmp_path )
    assert r[ "outcome" ]     == decision_mod.OUTCOME_NOT_OWED
    assert r[ "hook_output" ] == { "continue": True }
    assert cap_mod.get_poke_count( "s_nohold", base_dir=tmp_path ) == 0


# ── Scenario 2 — fresh reasoned hold → honored ────────────────────────────────

def test_v1_fresh_reasoned_hold_honored( tmp_path ):
    now = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )
    hold_mod.write_hold(
        "s_fresh", "María 🌸", "holding on Tiberius gate", work_owed=True,
        ttl_seconds=900, held_at=now.isoformat(), base_dir=tmp_path
    )
    r = _v1_adapter_step( "s_fresh", base_dir=tmp_path, now=now )
    assert r[ "outcome" ]     == decision_mod.OUTCOME_HONORED
    assert r[ "hook_output" ] == { "continue": True }
    assert cap_mod.get_poke_count( "s_fresh", base_dir=tmp_path ) == 0


# ── Scenario 3 — hold self-declares done → never poke ─────────────────────────

def test_v1_hold_declares_done_not_owed( tmp_path ):
    now = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )
    # work_owed False, fresh, empty reason → not honored (no reason) but declared done
    hold_mod.write_hold(
        "s_done", "Tiffany 💍", "", work_owed=False,
        ttl_seconds=900, held_at=now.isoformat(), base_dir=tmp_path
    )
    r = _v1_adapter_step( "s_done", base_dir=tmp_path, now=now )
    assert r[ "outcome" ] == decision_mod.OUTCOME_NOT_OWED
    assert cap_mod.get_poke_count( "s_done", base_dir=tmp_path ) == 0


# ── Scenario 4 — stale self-declared-owed hold → poke up to the cap ───────────

def test_v1_stale_owed_hold_pokes_to_cap_then_stops( tmp_path ):
    now   = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )
    stale = ( now - datetime.timedelta( seconds=10_000 ) ).isoformat()
    hold_mod.write_hold(
        "s_stale", "Tiffany 💍", "was holding on Rachel", work_owed=True,
        ttl_seconds=900, held_at=stale, base_dir=tmp_path
    )
    _backdate_hold_mtime( tmp_path, "s_stale", now )   # B1: stale via file mtime

    # Pokes 1..CAP — each a block carrying the declared-owed reason
    for expected_count in range( 1, CAP + 1 ):
        r = _v1_adapter_step( "s_stale", base_dir=tmp_path, now=now )
        assert r[ "outcome" ]                   == decision_mod.OUTCOME_POKE
        assert r[ "hook_output" ][ "decision" ] == "block"
        assert r[ "hook_output" ][ "reason" ]   == decision_mod.DECLARED_OWED_REASON
        assert r[ "should_increment" ]          is True
        assert cap_mod.get_poke_count( "s_stale", base_dir=tmp_path ) == expected_count

    # At the cap → stop nudging + signal the notify
    r = _v1_adapter_step( "s_stale", base_dir=tmp_path, now=now )
    assert r[ "outcome" ]            == decision_mod.OUTCOME_CAP_REACHED
    assert r[ "hook_output" ]        == { "continue": True }
    assert r[ "should_notify_cap" ]  is True
    assert r[ "should_increment" ]   is False
    assert cap_mod.get_poke_count( "s_stale", base_dir=tmp_path ) == CAP   # unchanged at cap


# ── Scenario 5 — reset (UserPromptSubmit) reopens the budget ──────────────────

def test_v1_reset_reopens_poke_budget( tmp_path ):
    now   = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )
    stale = ( now - datetime.timedelta( seconds=10_000 ) ).isoformat()
    hold_mod.write_hold(
        "s_reset", "Tiffany 💍", "stale owed", work_owed=True,
        ttl_seconds=900, held_at=stale, base_dir=tmp_path
    )
    _backdate_hold_mtime( tmp_path, "s_reset", now )   # B1: stale via file mtime

    # Burn the budget to the cap
    for _ in range( CAP ):
        _v1_adapter_step( "s_reset", base_dir=tmp_path, now=now )
    assert _v1_adapter_step( "s_reset", base_dir=tmp_path, now=now )[ "outcome" ] == decision_mod.OUTCOME_CAP_REACHED

    # Simulate genuine user re-engagement → reset_poke_count (UserPromptSubmit)
    cap_mod.reset_poke_count( "s_reset", base_dir=tmp_path )
    assert cap_mod.get_poke_count( "s_reset", base_dir=tmp_path ) == 0

    # Next idle pokes again from a fresh budget
    r = _v1_adapter_step( "s_reset", base_dir=tmp_path, now=now )
    assert r[ "outcome" ] == decision_mod.OUTCOME_POKE
    assert cap_mod.get_poke_count( "s_reset", base_dir=tmp_path ) == 1

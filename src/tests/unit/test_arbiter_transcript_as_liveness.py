#!/usr/bin/env python3
"""
RED-FIRST repro for bug fb332fcd — arbiter MANAGER-STALE false-positive in
plan mode.

Symptom (hit LIVE 2026-06-30, Tiberius): a manager deep in an APPROVED PLAN
emits no `Stop` event for the duration of the plan turn, so EVERY one of the
six existing liveness signals ages past STALE —
    bridge / event / commons / idle_prompt / dm / hold
— even though the process is demonstrably alive, appending its transcript
JSONL on every tool call. With `freshest_age_s` climbing past the
`arbiter manager stale poke threshold seconds` (2700s) the detector fires a
MANAGER-STALE poke + a Rick advisory at a manager that is actively working.

Root cause: `compute_liveness` has no signal that bumps DURING a long
single-turn tool sequence (plan-mode drafting, a big multi-Read/Edit run).
The hook-independent proof-of-life that DOES bump is the transcript `.jsonl`
file's mtime — the harness appends to it on every assistant/tool event.

Proposed fix (mirrors the DM-as-liveness 5th signal + hold-mtime 6th signal,
task 70be69f2): fold a 7th, UNCONDITIONAL, ADDITIVE, fail-safe `transcript_age`
into the freshest-of union. A fresh transcript mtime can only make a session
read MORE alive, never suppress a genuinely-dark one. LIFE signal only, never
STATE / the progress signature (C4).

These tests pass a FRESH transcript_mtime with all other signals STALE and
assert the verdict is LIVE. They FAIL today (`compute_liveness` has no
`transcript_mtime` parameter) and go GREEN once the 7th signal lands.

Venue: :7999-eligible / local — pure + injected fakes, no server, no real wait.
Design: src/rnd/v0.1.9/2026.06.30-arbiter-manager-stale-planmode-transcript-liveness.md
(bug fb332fcd) — direction (a) ratified by Tiberius before impl.
"""
import datetime

from cosa.agents.heartbeat_arbiter.fleet_render import compute_liveness


UTC = datetime.timezone.utc
NOW = datetime.datetime( 2026, 6, 30, 18, 0, 0, tzinfo=UTC )


def _ago( seconds ):
    return NOW - datetime.timedelta( seconds=seconds )


def _ago_mtime( seconds ):
    return ( NOW - datetime.timedelta( seconds=seconds ) ).timestamp()


# ── compute_liveness — the 7th transcript_age signal (RED until the fix) ──────
class TestComputeLivenessTranscriptAge:

    def test_fresh_transcript_keeps_planmode_manager_live( self ):
        """
        THE repro: all SIX existing signals STALE (4000s ≈ 67m, past the 3600s
        STALE ceiling → offline), only the transcript is fresh (5s). The manager
        is mid-plan, actively appending its transcript — must read LIVE, NOT be
        poked MANAGER-STALE.
        """
        stale_ts    = _ago( 4000 )
        stale_mtime = _ago_mtime( 4000 )
        view = {
            "last_event_ts"  : stale_ts,
            "commons_ts"     : stale_ts,
            "idle_prompt_ts" : stale_ts,
            "dm_ts"          : stale_ts,
        }
        live = compute_liveness(
            view, bridge_mtime=stale_mtime, now=NOW,
            hold_mtime=stale_mtime,
            transcript_mtime=_ago_mtime( 5 ),   # NEW 7th signal — fresh
        )
        assert live[ "transcript_age_s" ] == 5
        assert live[ "freshest_age_s" ]   == 5
        assert live[ "verdict" ]          == "LIVE"

    def test_transcript_age_always_present_and_auditable( self ):
        """transcript_age_s is an auditable column — present (None) even when no
        transcript_mtime is supplied."""
        live = compute_liveness( { "session_id": "s" }, None, NOW )
        assert "transcript_age_s" in live and live[ "transcript_age_s" ] is None

    def test_transcript_mtime_none_is_byte_identical_to_six_signal_verdict( self ):
        """
        Reversibility/additivity guarantee (mirrors hold_mtime=None): with
        transcript_mtime omitted, freshest_age_s + verdict match the prior
        six-signal block exactly — the new signal can only ADD life.
        """
        view = { "last_event_ts": _ago( 30 ) }
        baseline = compute_liveness( view, None, NOW, hold_mtime=None )
        with_none = compute_liveness( view, None, NOW, hold_mtime=None,
                                      transcript_mtime=None )
        assert with_none[ "freshest_age_s" ] == baseline[ "freshest_age_s" ]
        assert with_none[ "verdict" ]        == baseline[ "verdict" ]
        assert with_none[ "transcript_age_s" ] is None

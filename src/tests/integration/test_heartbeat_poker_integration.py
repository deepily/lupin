#!/usr/bin/env python3
"""
Integration test — HeartbeatPokerJob end-to-end (task I6, integration tier).

VENUE — :8000, scheduled via `POST /api/test-suite/submit` (§TESTING VENUES).
This tier mutates persistent state (writes real commons topic files) and needs
the running server for the Phase-3 `/api/commons/register-question` push, so it
is NOT run locally and NOT on :7999.

STATUS — module-skipped. Beyond the :8000 venue, this tier requires the
`HeartbeatPokerJob` → CJ Flow ingestion wiring, which is not yet a completed
task (`agentic_job_factory` has no `heartbeat_poker` entry — surfaced as the
I6 sequencing note). Un-skip and flesh the bodies once that wiring lands, then
schedule on :8000.

Base URL is read from `LUPIN_API_URL` (never hardcoded) per project convention.
"""

import os

import pytest

pytestmark = pytest.mark.skip(
    reason="I6 integration tier — :8000-scheduled; run via POST /api/test-suite/submit. "
           "CJ Flow ingestion wiring landed 2026-05-22 (agentic_job_factory heartbeat_poker "
           "branch) — the wiring no longer blocks; the skip now reflects venue only."
)

LUPIN_API_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )


def test_poker_pokes_recipient_end_to_end():
    """
    A `HeartbeatPokerJob`, ingested into CJ Flow, delivers pokes to a recipient
    on its cadence — each poke lands on the recipient's `dm-<persona>` commons
    topic carrying the `poke_body` envelope.

    End-to-end path: real `HeartbeatPokerJob` + real `LupinCommonsGateway` +
    real `CommonsStore` + the live :8000 server for the register-question push.

    Steps to flesh once wiring lands:
      1. construct a poker (short cadence, low `max_duration_seconds`);
      2. ingest into CJ Flow;
      3. let it run N ticks;
      4. `commons_read` the recipient's `dm-<persona>` topic — assert N pokes;
      5. assert each `poke_body` is `{kind: heartbeat, workstream, role}`.
    """
    raise NotImplementedError( "Flesh once CJ Flow ingestion wiring lands; schedule on :8000." )


def test_poker_clean_exit_on_termination_signal():
    """
    Posting an `implementation_done` kind to the termination topic AFTER job
    start drives the poker to a clean exit (`_transition_to_done`); a stale
    pre-start signal must NOT trigger exit at tick 1 (clean-exit guard).
    """
    raise NotImplementedError( "Flesh once CJ Flow ingestion wiring lands; schedule on :8000." )


def test_poker_dead_mans_switch_escalates_on_silent_recipient():
    """
    A recipient that never posts triggers the dead-man's-switch `notify()` after
    `deadman_consecutive_pokes` silent ticks — and the poker keeps poking
    (escalate, never terminate).
    """
    raise NotImplementedError( "Flesh once CJ Flow ingestion wiring lands; schedule on :8000." )

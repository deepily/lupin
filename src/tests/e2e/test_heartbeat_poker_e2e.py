#!/usr/bin/env python3
"""
E2E test — HeartbeatPokerJob cascade replay (task I6, E2E tier).

VENUE — :8000, scheduled via `POST /api/test-suite/submit` (§TESTING VENUES).
Full end-to-end: a cascade-flavored `HeartbeatPokerJob` preset poking a real
multi-recipient cascade cast. Long-running, mutates state — NOT run locally.

STATUS — module-skipped. This tier exercises the cascade-flavored poker preset
(task I7) and therefore depends on: (a) the CJ Flow ingestion wiring, and
(b) the swap-validation gates I4a-d having cleared. It is the furthest-
downstream tier — un-skip and flesh once I7 lands and the swap criteria clear.

Base URL is read from `LUPIN_API_URL` (never hardcoded) per project convention.
"""

import os

import pytest

pytestmark = pytest.mark.skip(
    reason="I6 E2E tier — :8000-scheduled; exercises the cascade-flavored poker "
           "preset (task I7, operator-gated post-run). CJ Flow ingestion wiring "
           "landed 2026-05-22; the remaining gate is task I7. Un-skip post-I7."
)

LUPIN_API_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )


def test_cascade_flavored_poker_replay_end_to_end():
    """
    Stand up a cascade-flavored `HeartbeatPokerJob` preset (the §5 Q3 swap row:
    cascade `RecipientSpec` roster — Manager + Observer + reviewers — plus
    cascade `termination_signal_kinds`) and replay a recorded cascade.

    Assert: every recipient is poked on cadence; the `cascade_complete` signal
    drives a clean exit; no dead-man false-positive on a responsive cast.

    Steps to flesh once I7 lands:
      1. build the cascade preset per the D3 swap row;
      2. ingest into CJ Flow; replay a recorded cascade transcript;
      3. assert per-recipient poke cadence + clean exit on `cascade_complete`.
    """
    raise NotImplementedError( "Flesh once task I7 (cascade-flavored preset) lands; schedule on :8000." )


def test_concurrent_pokers_route_by_poke_body():
    """
    Two pokers active simultaneously (cascade + implementer-keep-alive) — each
    tick routes to the correct role-handler via `poke_body`, no cross-poker
    signal bleed (the §4 concurrent-poker routing decision; swap-criterion 4).
    """
    raise NotImplementedError( "Flesh once task I7 lands + concurrent-poker scenario is available; schedule on :8000." )

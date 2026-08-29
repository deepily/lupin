"""
The lock-clear banner in `prove_gate_silence.py` must not claim more than it checked.

Row e6b8fe56's caller audit (commit 7f935140, doc
src/rnd/v0.2.0/2026.08.24-monopolize-as-idleness-caller-audit.md) found the
script's Gate B precondition itself CORRECT — it asks whether a monopolizer will
defer its foreign pr- job, and `monopolize_id` answers exactly that. What it
found wrong was one line of OUTPUT: the precondition prints "safe to submit",
which is a venue-wide idleness claim, while `require_lock_clear` reads only the
monopolize slot. A reader who trusts that line concludes the venue is free when
the shared pool may hold queued and inflight work.

Wording, not logic — so this pins the wording.

Venue: :7999-eligible (pure unit — no server, no DB, no state mutation).
"""

import os
import importlib.util

import pytest


def _load_proof():
    lupin_root = os.environ[ "LUPIN_ROOT" ]
    path       = os.path.join( lupin_root, "src", "scripts",
                               "presentation-gate-silence-proof", "prove_gate_silence.py" )
    spec       = importlib.util.spec_from_file_location( "prove_gate_silence", path )
    module     = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


PG = _load_proof()


def _pool_status( monopolize_id=None, monopolize_inflight=False,
                  inflight_agentic_jobs=0, pending_in_pool=0 ):
    """A /api/queue/pool-status payload, shaped per CLAUDE.md § CJ FLOW (Shape-B)."""
    return {
        "monopolize_id"         : monopolize_id,
        "monopolize_inflight"   : monopolize_inflight,
        "inflight_agentic_jobs" : inflight_agentic_jobs,
        "pending_in_pool"       : pending_in_pool,
        "max_agentic_workers"   : 3,
    }


def test_banner_does_not_claim_the_venue_is_safe():
    """
    The defect, stated as a test: a clear monopolize slot is not an idle venue.

    Three shared-pool jobs are inflight and three more are queued behind them.
    Nothing the precondition read can see any of that, so the banner must not
    speak for it.
    """
    banner = PG.lock_clear_banner( _pool_status( inflight_agentic_jobs=3, pending_in_pool=3 ) )

    assert "safe to submit" not in banner.lower(), (
        f"banner claims venue-wide safety from a monopolize-only check: {banner!r}"
    )


def test_banner_names_what_it_actually_checked():
    """A narrower claim is only useful if it says which claim it is."""
    banner = PG.lock_clear_banner( _pool_status() ).lower()

    assert "monopolize" in banner, f"banner does not name the field it read: {banner!r}"


def test_banner_discloses_the_blind_spot():
    """
    State the limit at the moment of the claim: queued and running shared-pool
    work is exactly what this precondition cannot see, so the line must say so.
    """
    banner = PG.lock_clear_banner( _pool_status() ).lower()

    assert "queued" in banner or "pending" in banner, (
        f"banner does not disclose the queued-work blind spot: {banner!r}"
    )


def test_banner_reports_the_id_it_read():
    """The evidence stays in the line — a null slot is reported as null, not omitted."""
    assert "None" in PG.lock_clear_banner( _pool_status() )
    assert "pr-deadbeef" in PG.lock_clear_banner( _pool_status( monopolize_id="pr-deadbeef" ) )


def test_the_shipped_precondition_line_makes_no_venue_wide_claim():
    """
    The tests above pin the extracted helper. This one pins the FILE, so the
    defect cannot survive by leaving the old string behind at the call site
    while a well-worded helper sits unused beside it.
    """
    lupin_root = os.environ[ "LUPIN_ROOT" ]
    path       = os.path.join( lupin_root, "src", "scripts",
                               "presentation-gate-silence-proof", "prove_gate_silence.py" )
    with open( path ) as fh:
        offenders = [
            ( n, line.rstrip() ) for n, line in enumerate( fh, start=1 )
            if "safe to submit" in line.lower()
        ]

    assert offenders == [], f"venue-wide safety claim still in the source: {offenders}"

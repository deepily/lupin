#!/usr/bin/env python3
"""
E2E harness for the manager self-re-spin verb — run against a DISPOSABLE seat only.

Row 9e0678f6. Cheech spawns the disposable seat and hands its session_id in the go
message; this harness observes that seat from OUTSIDE while it clears its own
context, and reports whether it came back. It NEVER fires at a working seat, and the
firing step is gated behind an explicit go: with no --go it takes the pre-snapshot
and stops, so "when the verb is green we run rather than write."

DESIGN (no firing here): src/rnd/2026.08.13-self-respin-disposable-seat-e2e-observation-plan.md

Two halves:
  • OBSERVATION is REAL — it drives the shipped oracle
    cosa.agents.heartbeat_arbiter.self_respin_observer.observe_fleet_self_respin.
  • FIRING is a SEAM (`fire_fn`) that defaults to a hard refusal until the verb
    lands and the CLI wires the real verb in. Nothing fires by construction unless
    a caller both passes --go AND supplies a real fire_fn.

The decision engine below is pure + injectable, so test_self_respin_disposable_seat_harness.py
proves the gating, the disposable guard, and every verdict mapping with fakes — no
seat, no clear.

Venue: the observe-only engine is :7999-local; a real --go run is a scheduled,
Cheech-gated event against a disposable seat, never CI.
"""
import argparse
import sys

from cosa.agents.heartbeat_arbiter.self_respin_observer import (
    observe_fleet_self_respin,
    SelfRespinVerdict,
)

# Harness outcomes (distinct from the observer's per-marker verdicts).
AWAITING_GO             = "AWAITING_GO"              # pre-snapshot taken; no --go, nothing fired
REFUSED_NOT_DISPOSABLE  = "REFUSED_NOT_DISPOSABLE"   # safety guard tripped; nothing fired
SUCCESS_RETURNED        = "SUCCESS_RETURNED"         # the seat came back, same identity, low context
FAIL_DEAD_NO_RETURN     = "FAIL_DEAD_NO_RETURN"      # fired and did not come back
FAIL_IDENTITY_MISMATCH  = "FAIL_IDENTITY_MISMATCH"   # a different seat answered
FAIL_TIMEOUT            = "FAIL_TIMEOUT"             # steps exhausted still PENDING (never resolved)

_VERDICT_TO_RESULT = {
    SelfRespinVerdict.RETURNED          : SUCCESS_RETURNED,
    SelfRespinVerdict.DEAD_NO_RETURN    : FAIL_DEAD_NO_RETURN,
    SelfRespinVerdict.IDENTITY_MISMATCH : FAIL_IDENTITY_MISMATCH,
}


def _refuse_to_fire( session_id ):   # default fire_fn — cannot fire by construction
    raise RuntimeError(
        f"self_respin verb not yet wired — refusing to fire at {session_id}. "
        "Inject a real fire_fn once the verb lands."
    )


def assessment_for_session( assessments, session_id ):
    """
    Ensures:
        - returns the SelfRespinAssessment whose session_id matches, or None
    """
    for a in assessments:
        if a.session_id == session_id:
            return a
    return None


def poll_until_verdict( session_id, *, base_dir, steps ):
    """
    Poll the REAL observer across a sequence of (now, pressure_section) steps and
    return the first terminal harness result.

    Requires:
        - steps is an iterable of ( now: aware datetime, pressure_section: dict )
          — each element is one observation tick (test supplies a fixed sequence;
          the CLI supplies a live generator)

    Ensures:
        - returns ( result, assessment ) at the first RETURNED / DEAD_NO_RETURN /
          IDENTITY_MISMATCH for `session_id`
        - returns ( FAIL_TIMEOUT, last_assessment_or_None ) if the steps run out
          while still PENDING (or the marker never appears)
    """
    last = None
    for now, section in steps:
        assessments = observe_fleet_self_respin(
            base_dir=base_dir, now=now, fetch_pressure=lambda: section
        )
        a = assessment_for_session( assessments, session_id )
        last = a if a is not None else last
        if a is not None and a.verdict in _VERDICT_TO_RESULT:
            return _VERDICT_TO_RESULT[ a.verdict ], a
    return FAIL_TIMEOUT, last


def run( *, session_id, go, disposable, steps, base_dir, fire_fn=_refuse_to_fire ):
    """
    The gated harness flow.

    Requires:
        - session_id is the DISPOSABLE seat's id (from Cheech's go message)
        - go is a bool — the explicit firing gate
        - disposable is a bool — the safety guard (True only for a throwaway seat)

    Ensures:
        - not go  → AWAITING_GO, fire_fn NEVER called
        - go but not disposable → REFUSED_NOT_DISPOSABLE, fire_fn NEVER called
        - go and disposable → fire_fn( session_id ) is called, then the real observer
          is polled to a terminal result
    """
    if not go:
        return AWAITING_GO, None
    if not disposable:
        return REFUSED_NOT_DISPOSABLE, None
    fire_fn( session_id )
    return poll_until_verdict( session_id, base_dir=base_dir, steps=steps )


def _build_arg_parser():
    p = argparse.ArgumentParser( description="Self-re-spin E2E harness (disposable seat only)." )
    p.add_argument( "--session-id", required=True, help="disposable seat session id (from Cheech's go)" )
    p.add_argument( "--go", action="store_true", help="arm the firing step (omit = pre-snapshot only)" )
    p.add_argument( "--i-am-disposable", action="store_true",
                    help="assert the target is a throwaway seat — required to fire" )
    p.add_argument( "--deadline-seconds", type=int, default=600 )
    p.add_argument( "--poll-seconds", type=int, default=15 )
    return p


def main( argv=None ):   # pragma: no cover - CLI wiring; the engine is unit-tested
    args = _build_arg_parser().parse_args( argv )
    if not args.go:
        print( f"[harness] pre-snapshot only for {args.session_id} — awaiting --go. Nothing fired." )
        return 0
    print( "[harness] --go set. Live firing requires the landed verb wired as fire_fn; "
           "this build refuses to fire by default. See the observation-plan doc." )
    return 0


if __name__ == "__main__":   # pragma: no cover - CLI entry point
    sys.exit( main() )

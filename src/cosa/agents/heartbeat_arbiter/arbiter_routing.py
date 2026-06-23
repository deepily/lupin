#!/usr/bin/env python3
"""
Heartbeat-Arbiter recipient routing (Round 2b-2) — the ratified Part-6 model.

A PURE encoding of the 12-case routing table (design `2026.06.08-arbiter-
consumption-gap-and-operator-loop.md` Part 6, judgment calls RESOLVED by Rick
2026-06-08). Every distinct arbiter output maps to exactly one RECIPIENT TIER;
the arbiter consumer (arbiter_job) executes the tier via its seams (notify_fn =
Rick via durable-post + live-push; send_to = directed manager/blocker DM).

Keeping the table as a pure leaf means the routing is AUDITABLE + 100%-testable
in isolation: the 12-case parametrized test asserts `CASE_TIERS` mirrors the
Part-6 table cell-for-cell, and the executor test asserts each tier emits to the
right recipients. No I/O, no seams here — the table is the contract.

The three recipient tiers + two cuts (Part 6 "pattern that falls out"):
  • OPERATOR (Rick) only, push      — infra + self-health (#1/#2/#3) + decisions
                                       (#10, Rick-primary): managers don't act on
                                       containers; decisions are the human's domain.
  • Rick + ALL active managers, push — fleet-level crises (#5 deadlock, #8 orphan
                                       worker, #9 manager-down, #11 fleet-stall):
                                       resilient to owning-manager-down; rare+severe.
  • Owning manager / the blocker, DM — the per-worker manager nudge (#7) and the
                                       blocker (#4, rewritten + cc its manager).
  • CUT: drop the roster broadcast    — #6 → /state pull-state.
  • CUT: demote the poll-error        — #12 → log; escalate to Rick only if PERSISTENT.
"""

# ── recipient tiers ─────────────────────────────────────────────────────────
TIER_RICK_ONLY           = "rick_only"            # notify_fn (durable + live push), NO managers
TIER_RICK_AND_MANAGERS   = "rick_and_managers"    # notify_fn + send_to each active manager
TIER_OWNING_MANAGER      = "owning_manager"       # send_to the resolved owning manager
TIER_BLOCKER_AND_MANAGER = "blocker_and_manager"  # send_to the blocker + cc its owning manager
TIER_DROP                = "drop"                  # no push — pull-state (/state)
TIER_LOG_THEN_RICK       = "log_then_rick"        # log; escalate to Rick only if persistent

ALL_TIERS = frozenset( {
    TIER_RICK_ONLY, TIER_RICK_AND_MANAGERS, TIER_OWNING_MANAGER,
    TIER_BLOCKER_AND_MANAGER, TIER_DROP, TIER_LOG_THEN_RICK,
} )


# ── the Part-6 table (case # → tier) — the ratified routing contract ─────────
# 1  container enter-unhealthy        (A)  → Rick only          (infra; managers don't act on containers)
# 2  container flapping               (A)  → Rick only          (ops alert)
# 3  health-watch BLIND               (A)  → Rick only          ("the arbiter's eyes are out")
# 4  blocker holding up a worker      (B)  → blocker + cc mgr    (direct nudge + manager looped in)
# 5  deadlock cycle                   (B)  → Rick + all mgrs     (human/manager breaks it)
# 6  fleet roster (per-tick)          (B)  → DROP               (pull-state — /state)
# 7  manager tap                      (B)  → owning manager     (the core actionable nudge)
# 8  unresolved-manager worker        (B)  → Rick + all mgrs     (orphan; any manager could adopt)
# 9  manager-down + HOLD              (B)  → Rick + all mgrs     (leaderless crew; re-staff)
# 10 decision-needed                  (B)  → Rick only          (+owning mgr if known; human's domain)
# 11 whole-fleet-stall                (B)  → Rick + all mgrs     (calibrated first, 2b-1)
# 12 arbiter poll-error               (B)  → log; Rick if persistent
#
# 2b-3 ADDITION (post-Part-6): the auto-poke reap-RECOMMENDATION. After a stuck
# LIVE session has absorbed ≤N bounded non-destructive pokes with no recovery, the
# arbiter emits a recommendation to REAP/REPLACE it — to Rick + ALL active managers
# (same tier as the fleet crises). It is a RECOMMENDATION ONLY: the arbiter never
# executes reap/replace (the redline). Numbered 13 so it routes through the same
# _route(case) dispatcher; it is NOT one of the original Part-6 12 outputs.
CASE_AUTO_POKE_REAP_REC = 13

# Post-game ADDITIONS (2026-06-11, missed-poke post-game — design
# src/rnd/v0.1.8/2026.06.11-arbiter-missed-poke-postgame-and-outreach-logging.md):
#   14  MANAGER-STALE advisory — a MANAGER-role session silent past the staleness
#       threshold (F2). Rick + ALL active managers: the dark manager's crew is
#       leaderless-in-waiting; any manager could step in. (The bounded staleness
#       POKE itself is a direct send_to, like the stuck-tier wake-nudge.)
#   15  FLEET-DARK — the published roster decayed to ZERO (F3). Rick ONLY: by
#       definition no managers remain to fan out to.
CASE_MANAGER_STALE_ADVISORY = 14
CASE_FLEET_DARK             = 15

# L1 ADDITIONS (2026-06-17, arbiter detector gaps — design
# src/rnd/v0.1.8/2026.06.17-arbiter-detector-gaps-L1/01-build-plan.md):
# store-aware suppression of the two false-escalating detectors. A manager whose
# only non-terminal owed work is Rick-gated (or who is owed-count 0) is NOT down
# and NOT a stall — instead of the repeating MANAGER-DOWN / WHOLE-FLEET-STALL
# loop, the arbiter emits at most ONE of these advisories per un-acked tap.
#   16  MANAGER-AWAITING-USER advisory — a tapped manager correctly BLOCKED on
#       Rick (every owed item operator-gated or blocked-on-user). Rick + ALL active
#       managers: Rick is the one who unblocks; managers see the crew is parked.
#   17  MANAGER-DONE advisory — a tapped manager with ZERO non-terminal owed work
#       (consider reaping). Rick + ALL active managers (the reap is theirs to
#       decide; the arbiter never reaps — the redline holds).
CASE_MANAGER_AWAITING_USER  = 16
CASE_MANAGER_DONE_ADVISORY  = 17

# 6929f4ac ADDITION (2026-06-22, receipts-of-progress outward twin — design
# src/rnd/2026.06.22-receipts-of-progress-heartbeat-owed-calc.md §9.2):
#   18  USER-GATE-RESURFACE — a session that went DARK while still holding an
#       OPEN, AGED direct user-gate (it stopped re-asking) → the arbiter surfaces
#       the buried question to Rick ON THE SESSION'S BEHALF. Rick ONLY: a direct
#       user-gate is the human's to answer (mirrors #10 decision-needed); a dark
#       session has no manager fan-out value here, and the whole point is the
#       owed gate reaching Rick when the session can no longer re-ask it.
CASE_USER_GATE_RESURFACE    = 18
# 19  OPERATOR-GATE routing (proactive-manager A2/A3, fcb5dbc0) — the arbiter as the
#     SINGLE pusher of STORE operator gates (gate_class='operator'), the fleet-wide
#     "awaiting the operator" queue, routed by D4 urgency: an URGENT gate interrupts
#     to Rick immediately; the NORMAL-urgency gates batch into a periodic digest;
#     LOW gates are pull-only. Rick ONLY — an operator gate is the human's to answer
#     (mirrors #18/#10). The fleet-wide STORE read covers DARK + alive sessions, so
#     this extends the case-18 dark-only resurface to ALL open operator gates.
CASE_OPERATOR_GATE          = 19

CASE_TIERS = {
    1  : TIER_RICK_ONLY,
    2  : TIER_RICK_ONLY,
    3  : TIER_RICK_ONLY,
    4  : TIER_BLOCKER_AND_MANAGER,
    5  : TIER_RICK_AND_MANAGERS,
    6  : TIER_DROP,
    7  : TIER_OWNING_MANAGER,
    8  : TIER_RICK_AND_MANAGERS,
    9  : TIER_RICK_AND_MANAGERS,
    10 : TIER_RICK_ONLY,
    11 : TIER_RICK_AND_MANAGERS,
    12 : TIER_LOG_THEN_RICK,
    CASE_AUTO_POKE_REAP_REC : TIER_RICK_AND_MANAGERS,   # 2b-3 auto-poke escalation
    CASE_MANAGER_STALE_ADVISORY : TIER_RICK_AND_MANAGERS,   # post-game F2 (2026-06-11)
    CASE_FLEET_DARK             : TIER_RICK_ONLY,           # post-game F3 (2026-06-11)
    CASE_MANAGER_AWAITING_USER  : TIER_RICK_AND_MANAGERS,   # L1 (2026-06-17) blocked-on-Rick advisory
    CASE_MANAGER_DONE_ADVISORY  : TIER_RICK_AND_MANAGERS,   # L1 (2026-06-17) consider-reaping advisory
    CASE_USER_GATE_RESURFACE    : TIER_RICK_ONLY,           # 6929f4ac (2026-06-22) dark-session gate → Rick
    CASE_OPERATOR_GATE          : TIER_RICK_ONLY,           # A2/A3 (fcb5dbc0) operator-gate urgency routing → Rick
}


def tier_for( case: int ) -> str:
    """
    The Part-6 recipient tier for an arbiter output case (1..12).

    Requires:
        - case is an int in 1..12

    Ensures:
        - returns the ratified tier string for `case`
        - raises KeyError for an unknown case (fail loud — a new output MUST be
          routed explicitly, never silently defaulted)
    """
    return CASE_TIERS[ case ]


def quick_smoke_test():
    """Self-contained smoke test. Returns True or raises AssertionError."""
    # every case maps to a known tier (Part-6 1..12 + the 2b-3 reap-rec case 13
    # + the post-game cases 14/15 + the L1 advisory cases 16/17 + the 6929f4ac
    # user-gate resurface case 18 + the A2/A3 operator-gate routing case 19)
    assert set( CASE_TIERS ) == set( range( 1, 20 ) )
    assert all( t in ALL_TIERS for t in CASE_TIERS.values() )
    # 6929f4ac (2026-06-22): the dark-session user-gate resurface is Rick-only
    assert tier_for( CASE_USER_GATE_RESURFACE ) == TIER_RICK_ONLY
    assert tier_for( CASE_AUTO_POKE_REAP_REC ) == TIER_RICK_AND_MANAGERS   # 2b-3
    # post-game (2026-06-11): manager-stale fans to Rick + managers; fleet-dark
    # is Rick-only (no managers remain by definition)
    assert tier_for( CASE_MANAGER_STALE_ADVISORY ) == TIER_RICK_AND_MANAGERS
    assert tier_for( CASE_FLEET_DARK )             == TIER_RICK_ONLY
    # L1 (2026-06-17): both store-aware advisories fan to Rick + managers
    assert tier_for( CASE_MANAGER_AWAITING_USER ) == TIER_RICK_AND_MANAGERS
    assert tier_for( CASE_MANAGER_DONE_ADVISORY ) == TIER_RICK_AND_MANAGERS
    # the three tiers + two cuts land where Part 6 says
    assert tier_for( 1 ) == tier_for( 2 ) == tier_for( 3 ) == TIER_RICK_ONLY
    assert tier_for( 6 ) == TIER_DROP                       # roster broadcast cut
    assert tier_for( 12 ) == TIER_LOG_THEN_RICK             # poll-error demoted
    assert tier_for( 4 ) == TIER_BLOCKER_AND_MANAGER
    assert tier_for( 7 ) == TIER_OWNING_MANAGER
    for c in ( 5, 8, 9, 11 ):
        assert tier_for( c ) == TIER_RICK_AND_MANAGERS
    assert tier_for( 10 ) == TIER_RICK_ONLY
    try:
        tier_for( 99 )
        raise AssertionError( "unknown case must raise KeyError" )
    except KeyError:
        pass
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"arbiter_routing smoke: {'PASS' if ok else 'FAIL'}" )

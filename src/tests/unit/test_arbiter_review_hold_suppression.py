"""
Fix tests for bug cec10ef9 (P3, lupin): the heartbeat arbiter must NOT announce a
worker that is in a DESIGNED review-gate hold (every non-terminal owed item is a
store-backed hold `blocked_by` a peer OPERATOR persona) when at least one blocking
operator is ALIVE. The suppression is UNIFORM across BOTH announce legs — the
`stuck` short-circuit AND the blocked-edge holder path (Mr. Radio ruling Q1,
2026-07-11) — and FAIL-SAFE-to-ROSTER in every uncertain direction (store hiccup /
dead operator / mixed owed work / deadlock cycle → keep rostering, never hide a
real stall).

RED-first: written to fail against pre-fix code (missing helpers / kwarg), GREEN
after the fix. Supersedes the diagnostic `test_arbiter_review_hold_fp_repro.py`.

Run: pytest src/tests/unit/test_arbiter_review_hold_suppression.py -v   (:7999-eligible, pure)
"""
import datetime

import pytest

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob
from lupin_mcp.persona_normalization import canonical_persona_key


NOW = datetime.datetime( 2026, 6, 9, 0, 0, 0, tzinfo=datetime.timezone.utc )


class _GW:
    def __init__( self ):
        self.sent, self.posts = [ ], [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b, metadata=None ): self.sent.append( ( r, b ) )
    def post( self, t, b ): self.posts.append( ( t, b ) )
    def read( self, topic, since=None, limit=50 ): return [ ]


def _job( gw=None, notify=None, **overrides ):
    cfg = dict(
        commons           = gw or _GW(),
        poll_seconds      = 5,
        manager_recipient = "DeclaredMgr",
        notify_fn         = notify or ( lambda *a, **k: None ),
    )
    cfg.update( overrides )
    return ArbiterConsumerJob( **cfg )


def _hold_item( blocker="sam", status="blocked", kind="persona" ):
    return { "id": "ca8d6a19", "status": status,
             "blocked_by": [ { "kind": kind, "id": blocker } ], "gate_class": "none" }


# ════════════════════════════════════════════════════════════════════════════
# Part 1 — _item_is_review_gate_hold (the (2)-predicate, NARROW and separate
# from the Rick-gate _item_is_user_gated)
# ════════════════════════════════════════════════════════════════════════════

def test_review_gate_hold_true_for_persona_blocked():
    assert ArbiterConsumerJob._item_is_review_gate_hold( _hold_item() ) is True


def test_review_gate_hold_false_for_user_gated():
    """A Rick-gate (blocked_by kind=user) is NOT a peer review-gate hold."""
    assert ArbiterConsumerJob._item_is_review_gate_hold(
        { "status": "blocked", "blocked_by": [ { "kind": "user", "id": "rick" } ] } ) is False


def test_review_gate_hold_false_for_operator_gate_without_persona_block():
    """gate_class=operator with no persona blocked_by ref is an operator/Rick gate,
    not a peer review-gate hold."""
    assert ArbiterConsumerJob._item_is_review_gate_hold(
        { "status": "blocked", "gate_class": "operator", "blocked_by": [ ] } ) is False


def test_review_gate_hold_false_for_non_blocked_status():
    """A queued item blocked_by a persona is not a live hold."""
    assert ArbiterConsumerJob._item_is_review_gate_hold(
        _hold_item( status="queued" ) ) is False


def test_review_gate_hold_false_for_malformed():
    assert ArbiterConsumerJob._item_is_review_gate_hold( None ) is False
    assert ArbiterConsumerJob._item_is_review_gate_hold( "nope" ) is False
    assert ArbiterConsumerJob._item_is_review_gate_hold(
        { "status": "blocked", "blocked_by": None } ) is False
    assert ArbiterConsumerJob._item_is_review_gate_hold(
        { "status": "blocked", "blocked_by": [ "bad", { "kind": "persona" } ] } ) is True  # skips junk, finds the persona ref


# ════════════════════════════════════════════════════════════════════════════
# Part 2 — _designed_hold_personas (the set/edge builder)
# ════════════════════════════════════════════════════════════════════════════

def test_designed_hold_personas_all_items_holds_included():
    """A persona whose EVERY owed item is a review-gate hold → included, with its
    canonical operator-blocker keys."""
    owed = { "Rio": [ _hold_item( blocker="sam" ), _hold_item( blocker="sam" ) ] }
    dhp  = ArbiterConsumerJob._designed_hold_personas( owed )
    assert canonical_persona_key( "Rio" ) in dhp
    assert dhp[ canonical_persona_key( "Rio" ) ] == frozenset( { canonical_persona_key( "sam" ) } )


def test_designed_hold_personas_mixed_owed_excluded():
    """A persona with ANY non-hold owed item is EXCLUDED — a real stall on the
    other work must never be hidden (mirrors _classify_owed 'every item')."""
    owed = { "Rio": [ _hold_item(), { "id": "x", "status": "queued", "blocked_by": [ ] } ] }
    assert canonical_persona_key( "Rio" ) not in ArbiterConsumerJob._designed_hold_personas( owed )


def test_designed_hold_personas_empty_owed_list_excluded():
    assert ArbiterConsumerJob._designed_hold_personas( { "Rio": [ ] } ) == { }


def test_designed_hold_personas_none_and_empty_are_failsafe_empty():
    assert ArbiterConsumerJob._designed_hold_personas( None ) == { }
    assert ArbiterConsumerJob._designed_hold_personas( { } ) == { }


def test_designed_hold_personas_unions_multiple_operators():
    owed = { "Rio": [ _hold_item( blocker="sam" ), _hold_item( blocker="tiberius" ) ] }
    dhp  = ArbiterConsumerJob._designed_hold_personas( owed )
    assert dhp[ canonical_persona_key( "Rio" ) ] == frozenset(
        { canonical_persona_key( "sam" ), canonical_persona_key( "tiberius" ) } )


def test_designed_hold_personas_idless_operator_omitted():
    """A hold item with a persona blocked_by ref but NO id yields no operator to
    liveness-check → the persona is OMITTED (fail-safe: can't suppress without a
    checkable operator)."""
    owed = { "Rio": [ { "status": "blocked", "blocked_by": [ { "kind": "persona" } ] } ] }
    assert ArbiterConsumerJob._designed_hold_personas( owed ) == { }


def test_designed_hold_personas_skips_junk_blocked_by_refs():
    """Within a qualifying hold item, non-dict / non-persona blocked_by refs are
    skipped; only the clean persona+id operator is collected."""
    owed = { "Rio": [ { "status": "blocked",
                        "blocked_by": [ "junk", { "kind": "user", "id": "rick" },
                                        { "kind": "persona", "id": "sam" } ] } ] }
    dhp = ArbiterConsumerJob._designed_hold_personas( owed )
    assert dhp[ canonical_persona_key( "Rio" ) ] == frozenset( { canonical_persona_key( "sam" ) } )


# ════════════════════════════════════════════════════════════════════════════
# Part 3 — _attention_workers suppression (BOTH paths + fail-safes)
# ════════════════════════════════════════════════════════════════════════════

def _fv( rio_stuck, sam_alive=True ):
    return {
        "rio-sid": { "session_id": "rio-sid", "persona": "Rio", "stuck": rio_stuck,
                     "state": "stuck" if rio_stuck else "active",
                     "holding_on": "peer:Sam", "alive": True },
        "sam-sid": { "session_id": "sam-sid", "persona": "Sam", "stuck": False,
                     "state": "active", "holding_on": "none", "alive": sam_alive },
    }


_DHP_RIO_ON_SAM = { canonical_persona_key( "Rio" ): frozenset( { canonical_persona_key( "Sam" ) } ) }


def test_stuck_designed_hold_on_live_operator_suppressed():
    """THE FIX (stuck leg): a stuck worker in a designed review-gate hold on a LIVE
    operator is suppressed from the attention roster."""
    job   = _job()
    graph = { "edges": { "Rio": "Sam" }, "cycles": [ ] }
    out   = job._attention_workers( _fv( rio_stuck=True ), graph, now=NOW,
                                    designed_hold_personas=_DHP_RIO_ON_SAM )
    assert "Rio" not in { v.get( "persona" ) for v in out }


def test_stuck_designed_hold_on_DEAD_operator_rostered_failsafe():
    """FAIL-SAFE: operator is not alive → the hold became a real stall → ROSTER."""
    job   = _job()
    graph = { "edges": { "Rio": "Sam" }, "cycles": [ ] }
    out   = job._attention_workers( _fv( rio_stuck=True, sam_alive=False ), graph, now=NOW,
                                    designed_hold_personas=_DHP_RIO_ON_SAM )
    assert "Rio" in { v.get( "persona" ) for v in out }


def test_stuck_worker_not_a_designed_holder_rostered():
    """A genuinely-stuck worker with NO designed hold is STILL announced (no
    over-suppression)."""
    job   = _job()
    graph = { "edges": { }, "cycles": [ ] }
    out   = job._attention_workers( _fv( rio_stuck=True ), graph, now=NOW,
                                    designed_hold_personas={ } )
    assert "Rio" in { v.get( "persona" ) for v in out }


def test_designed_hold_personas_none_preserves_todays_behavior():
    """FAIL-SAFE: designed_hold_personas None (store hiccup / unwired) → no
    suppression = today's behavior (stuck worker rostered)."""
    job   = _job()
    graph = { "edges": { "Rio": "Sam" }, "cycles": [ ] }
    out   = job._attention_workers( _fv( rio_stuck=True ), graph, now=NOW,
                                    designed_hold_personas=None )
    assert "Rio" in { v.get( "persona" ) for v in out }


def test_blocked_edge_designed_hold_on_live_operator_suppressed():
    """THE FIX (blocked-edge leg, Q1 uniform rule): a NON-stuck designed holder that
    would be rostered via the blocked-edge path (here forced by making the operator
    view a dead-peer edge) is suppressed when a store operator-blocker is alive.

    Construct: Rio NOT stuck, edge Rio->Ghost (Ghost not alive → would roster via the
    dead-peer branch), but Rio's STORE hold is on Sam who IS alive → suppress."""
    job = _job()
    fv  = {
        "rio-sid":   { "session_id": "rio-sid", "persona": "Rio", "stuck": False,
                       "state": "active", "holding_on": "peer:Ghost", "alive": True },
        "sam-sid":   { "session_id": "sam-sid", "persona": "Sam", "stuck": False,
                       "state": "active", "holding_on": "none", "alive": True },
    }
    graph = { "edges": { "Rio": "Ghost" }, "cycles": [ ] }   # Ghost absent → not alive → dead-peer roster path
    out   = job._attention_workers( fv, graph, now=NOW, designed_hold_personas=_DHP_RIO_ON_SAM )
    assert "Rio" not in { v.get( "persona" ) for v in out }


def test_deadlock_cycle_member_never_suppressed_failsafe():
    """FAIL-SAFE: a designed holder that is ALSO in a deadlock CYCLE is a mutual
    stall → NEVER suppressed (the deadlock detector stays intact)."""
    job = _job()
    fv  = _fv( rio_stuck=False )
    graph = { "edges": { "Rio": "Sam" }, "cycles": [ [ "Rio", "Sam" ] ] }
    out   = job._attention_workers( fv, graph, now=NOW, designed_hold_personas=_DHP_RIO_ON_SAM )
    assert "Rio" in { v.get( "persona" ) for v in out }


# ════════════════════════════════════════════════════════════════════════════
# Part 4 — _tap_managers E2E advisory
# ════════════════════════════════════════════════════════════════════════════

def test_tap_managers_no_stuck_advisory_for_designed_hold():
    """End-to-end: with the designed-hold set threaded in, NO 'Stuck: Rio' advisory
    is DMed (the ground-truth ca8d6a19 FP is suppressed)."""
    gw  = _GW()
    job = _job( gw, resolve_manager_fn=lambda sid, declared_manager=None: {
                    "manager_persona": "MgrX", "source": "lineage" } )
    graph = { "edges": { "Rio": "Sam" }, "cycles": [ ] }
    fired = job._tap_managers( _fv( rio_stuck=True ), graph, roster=[ ], now=NOW,
                               active_managers=[ "MgrX" ],
                               designed_hold_personas=_DHP_RIO_ON_SAM )
    assert fired == 0
    assert not any( "Stuck: Rio" in b for _r, b in gw.sent )


def test_tap_managers_still_announces_a_genuine_stuck_worker():
    """No over-suppression: a genuinely-stuck worker (no designed hold) is still
    announced to its manager."""
    gw  = _GW()
    job = _job( gw, resolve_manager_fn=lambda sid, declared_manager=None: {
                    "manager_persona": "MgrX", "source": "lineage" } )
    graph = { "edges": { }, "cycles": [ ] }
    fired = job._tap_managers( _fv( rio_stuck=True ), graph, roster=[ ], now=NOW,
                               active_managers=[ "MgrX" ], designed_hold_personas={ } )
    assert fired == 1
    assert any( "Stuck: Rio" in b for _r, b in gw.sent )

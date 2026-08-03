"""
Fix tests for bug 1ff7be20 (P3, lupin): the heartbeat arbiter must NOT roster a
NON-stuck blocked-edge holder whose `holding_on: peer:X` edge has NO authoritative
store `blocked_by` backing — the STALE activity-derived edge that produced three
live "Blocked: X" manager-tap advisories against ZERO store rows (maria x2, sam x1;
the last at 2026-07-12 00:28:48 EDT on FULLY-PATCHED code — after both ad0f6199 and
cec10ef9 went live, neither of which touches this path).

THE LIVE MECHANISM (journal-confirmed, poll @ 04:28:48Z UTC):
    maria's freshest heartbeat activity record carried `awaiting: "peer:sam-and-reviewers"`
    (a free-form label, NOT a fleet persona) and `work_owed: False`. build_fleet_view
    mints `holding_on` straight from that record, so the view carried a peer edge to a
    persona that does not exist. The awaited "peer" is absent from the fleet ⇒ NOT alive
    ⇒ the bbce7e2f dead-peer fail-safe KEEPS the holder ⇒ maria was rostered "blocked"
    and tapped to Mr. Radio — while the store held ZERO non-terminal rows for her.

THE ASYMMETRY THIS FIXES (the same poll proves it): `arbiter_poll_activity` recorded
    edges=1, pings_fired=0, taps_fired=1.
The PING leg is already store-corroborated (`edge_is_store_backed`, bug d44b7068) and
correctly fired ZERO. The ROSTER/advisory leg consults no store at all and fired the
false advisory off the very same edge. This bug closes that gap: the blocked-edge leg
of `_attention_workers` now consults the SAME per-poll authoritative store wait-graph.

SCOPE FENCE (Mr. Radio): blocked-edge leg ONLY.
  - the `stuck` leg is UNTOUCHED — sam's false "Stuck: sam" advisories ride the
    activity-derived STUCK-EPISODE flag (`_count_stuck_episodes`), a DISTINCT root that
    must not be silently absorbed here (test_stuck_leg_untouched_* pin that fence).
  - `_item_is_user_gated` (Rick-gate), the ce13b134 dedup key/cooldown, and the cec10ef9
    designed-hold suppression semantics are all untouched.
FAIL-SAFE DIRECTION IS ROSTER: store read failed/unwired (store_edges None) → no
filtering; a deadlock-cycle member → always kept. Never hide a real stall.

RED-first: the store_edges kwarg does not exist pre-fix → these fail (TypeError), GREEN
after. The characterization test pins the pre-fix behavior that the fail-safe preserves.

Run: pytest src/tests/unit/test_arbiter_unbacked_blocked_edge.py -v   (:7999-eligible, pure)
"""
import datetime

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob
from lupin_mcp.persona_normalization import canonical_persona_key


NOW = datetime.datetime( 2026, 7, 12, 4, 28, 48, tzinfo=datetime.timezone.utc )   # the live FP poll


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


# ── the LIVE fleet shape (04:28:48Z): maria alive, holding a phantom peer, sam alive ──
def _fv_maria( maria_stuck=False ):
    return {
        "6ecfb4e7": { "session_id": "6ecfb4e7", "persona": "maria", "stuck": maria_stuck,
                      "state": "holding", "holding_on": "peer:sam-and-reviewers", "alive": True },
        "sam-sid" : { "session_id": "sam-sid", "persona": "sam", "stuck": False,
                      "state": "active", "holding_on": "none", "alive": True },
    }


# the derived graph the live poll built: ONE edge to a persona that is not in the fleet
_GRAPH_PHANTOM = { "edges": { "maria": "sam-and-reviewers" }, "cycles": [ ] }

# authoritative store wait-graph (build_store_wait_edges output) — canonical-keyed
_STORE_EMPTY   = { }                                                     # read OK, maria owes/blocks nothing
_STORE_BACKED  = { canonical_persona_key( "maria" ): { canonical_persona_key( "sam" ) } }


def _personas( views ):
    return { v.get( "persona" ) for v in views }


# ════════════════════════════════════════════════════════════════════════════
# Part 1 — the DEFECT, reproduced (characterization: pre-fix behavior, which the
# store-UNKNOWN fail-safe deliberately PRESERVES post-fix)
# ════════════════════════════════════════════════════════════════════════════

def test_repro_unbacked_phantom_edge_is_rostered_when_store_unconsulted():
    """THE BUG, verbatim: with no store corroboration threaded, maria's phantom
    `peer:sam-and-reviewers` edge rosters her as blocked — the 00:28:48 EDT advisory.
    Post-fix this remains TRUE for the store-UNKNOWN path (fail-safe to ROSTER)."""
    job = _job()
    out = job._attention_workers( _fv_maria(), _GRAPH_PHANTOM, now=NOW )
    assert "maria" in _personas( out )


def test_repro_phantom_edge_advisory_body_says_blocked_maria():
    """The rostered phantom holder renders as the literal 'Blocked: maria' advisory
    line that reached Mr. Radio."""
    job  = _job()
    out  = job._attention_workers( _fv_maria(), _GRAPH_PHANTOM, now=NOW )
    body = job._format_manager_tap( "mr radio", out, _GRAPH_PHANTOM, free_n=1 )
    assert "Blocked: maria" in body
    assert "1 blocked" in body


# ════════════════════════════════════════════════════════════════════════════
# Part 2 — THE FIX: store-corroborate the blocked-edge leg
# ════════════════════════════════════════════════════════════════════════════

def test_unbacked_edge_suppressed_when_store_read_succeeded():
    """THE FIX: an authoritative store read that shows NO blocked_by backing for the
    derived edge ⇒ the holder is NOT rostered (no false 'Blocked: maria')."""
    job = _job()
    out = job._attention_workers( _fv_maria(), _GRAPH_PHANTOM, now=NOW, store_edges=_STORE_EMPTY )
    assert "maria" not in _personas( out )


def test_store_backed_edge_still_rostered():
    """NO over-suppression: a REAL store-backed block (maria blocked_by sam) with a
    dead/absent awaited peer still rosters — the store is the corroborator, not a mute."""
    job   = _job()
    fv    = _fv_maria()
    graph = { "edges": { "maria": "sam" }, "cycles": [ ] }
    fv[ "sam-sid" ][ "alive" ] = False                       # dead blocker ⇒ a genuine stall
    out   = job._attention_workers( fv, graph, now=NOW, store_edges=_STORE_BACKED )
    assert "maria" in _personas( out )


def test_store_edges_none_preserves_todays_behavior_failsafe():
    """FAIL-SAFE (store read FAILED / seam unwired ⇒ backing UNKNOWN): no filtering —
    a store outage must never silence a genuine block."""
    job = _job()
    out = job._attention_workers( _fv_maria(), _GRAPH_PHANTOM, now=NOW, store_edges=None )
    assert "maria" in _personas( out )


def test_deadlock_cycle_member_kept_even_when_unbacked():
    """FAIL-SAFE: a holder inside a deadlock CYCLE stays load-bearing regardless of
    store backing — the mutual stall is still announced (mirrors cec10ef9's carve-out)."""
    job   = _job()
    graph = { "edges": { "maria": "sam", "sam": "maria" }, "cycles": [ [ "maria", "sam" ] ] }
    out   = job._attention_workers( _fv_maria(), graph, now=NOW, store_edges=_STORE_EMPTY )
    assert "maria" in _personas( out )


def test_backing_check_is_canonical_across_spelling():
    """Persona spelling is canonicalized on BOTH sides (view 'Mr. Radio' vs store
    'mr radio') — a real backing is never missed on a spelling/casing difference."""
    job = _job()
    fv  = {
        "k-sid": { "session_id": "k-sid", "persona": "Krishna", "stuck": False,
                   "state": "holding", "holding_on": "peer:Mr. Radio", "alive": True },
    }                                                        # awaited absent from fleet ⇒ dead-peer path
    graph = { "edges": { "Krishna": "Mr. Radio" }, "cycles": [ ] }
    store = { canonical_persona_key( "krishna" ): { canonical_persona_key( "mr radio" ) } }
    out   = job._attention_workers( fv, graph, now=NOW, store_edges=store )
    assert "Krishna" in _personas( out )                     # backed → kept


def test_live_peer_exclusion_still_applies_before_store_check():
    """bbce7e2f is UNCHANGED: a holder awaiting a LIVE peer is excluded regardless of
    store backing (a healthy in-flight dependency is not an attention item)."""
    job   = _job()
    graph = { "edges": { "maria": "sam" }, "cycles": [ ] }   # sam IS alive in _fv_maria
    out   = job._attention_workers( _fv_maria(), graph, now=NOW, store_edges=_STORE_BACKED )
    assert "maria" not in _personas( out )


def test_unbacked_suppression_emits_journal_event():
    """Observability: the suppression is journaled (arbiter_unbacked_edge_suppressed)
    with the holder + the phantom awaited target, so a false-negative is auditable."""
    seen = [ ]
    job  = _job( log_fn=lambda event, **kw: seen.append( ( event, kw ) ) )
    job._attention_workers( _fv_maria(), _GRAPH_PHANTOM, now=NOW, store_edges=_STORE_EMPTY )
    events = [ ( e, kw ) for e, kw in seen if e == "arbiter_unbacked_edge_suppressed" ]
    assert len( events ) == 1
    assert events[ 0 ][ 1 ][ "persona" ] == "maria"
    assert events[ 0 ][ 1 ][ "awaited" ] == "sam-and-reviewers"


# ════════════════════════════════════════════════════════════════════════════
# Part 3 — SCOPE FENCE: the stuck leg is NOT touched (sam's FP is a distinct root)
# ════════════════════════════════════════════════════════════════════════════

def test_stuck_leg_untouched_by_store_corroboration():
    """FENCE: a STUCK worker is rostered even with an unbacked edge + empty store. The
    stuck-episode axis (sam's false 'Stuck: sam') is a DISTINCT root — suppressing it
    here would hide a genuinely wedged worker (fail-safe = ROSTER)."""
    job = _job()
    out = job._attention_workers( _fv_maria( maria_stuck=True ), _GRAPH_PHANTOM, now=NOW,
                                  store_edges=_STORE_EMPTY )
    assert "maria" in _personas( out )


def test_stuck_leg_untouched_even_with_no_edge_at_all():
    """FENCE (no-edge case): a stuck worker with zero derived edges and an empty store
    is still rostered — store corroboration gates ONLY the blocked-edge leg."""
    job = _job()
    out = job._attention_workers( _fv_maria( maria_stuck=True ), { "edges": { }, "cycles": [ ] },
                                  now=NOW, store_edges=_STORE_EMPTY )
    assert "maria" in _personas( out )


# ════════════════════════════════════════════════════════════════════════════
# Part 4 — composition with cec10ef9 (both gates active, neither cannibalizes)
# ════════════════════════════════════════════════════════════════════════════

def test_composes_with_designed_hold_suppression():
    """Both suppressions active on one poll: the designed-hold gate (cec10ef9) and the
    unbacked-edge gate (this bug) coexist — a designed holder is still suppressed and
    the phantom-edge holder is too."""
    job  = _job()
    fv   = _fv_maria()
    fv[ "k-sid" ] = { "session_id": "k-sid", "persona": "krishna", "stuck": True,
                      "state": "stuck", "holding_on": "peer:sam", "alive": True }
    graph = { "edges": { "maria": "sam-and-reviewers", "krishna": "sam" }, "cycles": [ ] }
    dhp   = { canonical_persona_key( "krishna" ): frozenset( { canonical_persona_key( "sam" ) } ) }
    out   = job._attention_workers( fv, graph, now=NOW, designed_hold_personas=dhp,
                                    store_edges=_STORE_EMPTY )
    assert _personas( out ) == set()


def test_tap_managers_threads_store_edges_through():
    """The kwarg is threaded from the poll seam: _tap_managers must accept and forward
    store_edges (else the fix is dead code on the live path)."""
    gw  = _GW()
    job = _job( gw )
    fired = job._tap_managers( _fv_maria(), _GRAPH_PHANTOM, roster=[ ], now=NOW,
                               active_managers={ "mr radio" }, store_edges=_STORE_EMPTY )
    assert fired == 0                                        # nothing to tap → no advisory
    assert gw.sent == [ ]

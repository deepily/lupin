"""
Fix tests for bug 3287ee1e (P3, lupin): the heartbeat arbiter must NOT announce
"Stuck: X" for a WORKER whose session bridge is FRESH — i.e. one that is demonstrably
taking real turns right now. Sibling of 1ff7be20 (same asymmetry shape: a gate wired
into one consumer of a signal but not its sibling consumer).

THE SELF-CONTRADICTION (journal-confirmed, ONE poll @ 2026-07-11 21:12:20 EDT):
    arbiter_stuck_bridge_veto  persona=sam  bridge_age_s=8.6   ← "don't POKE sam, he's alive"
    arbiter_outreach kind=tap → Mr. Radio: "1 stuck/dead"      ← "sam is STUCK" (same poll)
    render row: `sam  stuck  peer:rio  8s/4m  LIVE STUCK`
The 92c7ab1d bridge-fresh veto is wired into `_auto_poke` (:4005) and — via e5e33795 —
into the manager-SUBJECT stuck advisory (:2627), but NEVER into the WORKER-subject
roster leg in `_attention_workers`. So the arbiter refused to poke sam because he was
demonstrably alive, then told his manager he was stuck anyway.

VERIFY-FIRST (both premises of the filed hypothesis were overturned by evidence):
  - NOT replayed cap-history: sam's events file carries GENUINE fresh cap_reached records
    (01:00:11Z, 01:08:13Z, no intervening `honored`) → _count_stuck_episodes correctly
    returns 2 >= STUCK_REPEAT_THRESHOLD. The flag is computed right; the ADVISORY is wrong.
  - 92c7ab1d is NOT held — it is merged + live (5d4e7baa → 59ba12e5), so its veto primitive
    `_session_bridge_fresh` ALREADY EXISTS and is REUSED here rather than rebuilt.

FIX: apply the existing `_session_bridge_fresh` veto to the stuck leg of
`_attention_workers`. `bridge_mtimes` is already threaded in (bf8c5cbb) — no new plumbing,
no new mechanism, NO store read (a wedged worker often CANNOT write store rows, so
store-corroboration is the WRONG remedy shape here — Mr. Radio's ratified constraint).

FAIL-SAFE IS ROSTER: bridge_mtimes unwired / persona absent from the map / bridge STALE /
future-skewed mtime / now=None → keep rostering. A genuinely wedged session stops emitting
hook stamps, so its bridge goes stale and it is NEVER vetoed (the true positive survives).

Run: pytest src/tests/unit/test_arbiter_stuck_bridge_fresh_advisory.py -v   (:7999-eligible, pure)
"""
import datetime

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob
from lupin_mcp.persona_normalization import canonical_persona_key


NOW = datetime.datetime( 2026, 7, 12, 1, 12, 20, tzinfo=datetime.timezone.utc )   # the live FP poll


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


# ── the LIVE fleet shape @ 21:12:20 EDT: sam stuck (fresh cap-history) but bridge 8.6s fresh ──
def _fv_sam():
    return {
        "84daa020": { "session_id": "84daa020", "persona": "sam", "stuck": True,
                      "state": "stuck", "holding_on": "peer:rio", "alive": True },
        "rio-sid" : { "session_id": "rio-sid", "persona": "Rio", "stuck": False,
                      "state": "working", "holding_on": "peer:sam", "alive": True },
    }


_GRAPH_NO_CYCLE = { "edges": { }, "cycles": [ ] }


def _bridges( age_s, persona="sam" ):
    """persona→bridge-mtime map, `age_s` seconds old relative to NOW."""
    return { canonical_persona_key( persona ): NOW.timestamp() - age_s }


def _personas( views ):
    return { v.get( "persona" ) for v in views }


# ════════════════════════════════════════════════════════════════════════════
# Part 1 — the DEFECT reproduced (characterization: what shipped to Mr. Radio)
# ════════════════════════════════════════════════════════════════════════════

def test_repro_stuck_worker_rostered_when_bridge_unconsulted():
    """THE BUG: with no bridge map threaded (today's worker-leg behavior), a stuck-flagged
    worker is rostered — even though a fresh bridge proves he is taking turns."""
    job = _job()
    out = job._attention_workers( _fv_sam(), _GRAPH_NO_CYCLE, now=NOW )
    assert "sam" in _personas( out )


def test_repro_advisory_body_says_stuck_sam():
    """The rostered stuck worker renders the literal '1 stuck/dead' + 'Stuck: sam' advisory
    body that reached Mr. Radio at 21:12:20 EDT."""
    job  = _job()
    out  = job._attention_workers( _fv_sam(), _GRAPH_NO_CYCLE, now=NOW )
    body = job._format_manager_tap( "mr radio", out, _GRAPH_NO_CYCLE, free_n=0 )
    assert "Stuck: sam" in body
    assert "1 stuck/dead" in body


# ════════════════════════════════════════════════════════════════════════════
# Part 2 — THE FIX: the bridge-fresh veto reaches the WORKER stuck leg
# ════════════════════════════════════════════════════════════════════════════

def test_stuck_worker_with_fresh_bridge_suppressed():
    """THE FIX: sam's bridge was 8.6s fresh on the FP poll — demonstrably alive ⇒ NOT
    wedged ⇒ no 'Stuck: sam' advisory. The poke leg already refused to poke him."""
    job = _job()
    out = job._attention_workers( _fv_sam(), _GRAPH_NO_CYCLE, now=NOW,
                                  bridge_mtimes=_bridges( 8.6 ) )
    assert "sam" not in _personas( out )


def test_suppressed_worker_leaves_advisory_body_clean():
    """End-to-end on the announce path: the veto empties the roster, so no advisory body
    naming sam can be built at all."""
    job = _job()
    out = job._attention_workers( _fv_sam(), _GRAPH_NO_CYCLE, now=NOW,
                                  bridge_mtimes=_bridges( 8.6 ) )
    assert out == [ ]


def test_stuck_worker_with_STALE_bridge_still_rostered():
    """FAIL-SAFE (the true positive): a genuinely wedged session stops emitting hook stamps,
    so its bridge goes stale → NOT vetoed → STILL announced. This is the case the detector
    exists for and it must never be silenced."""
    job   = _job()
    stale = job.manager_stale_poke_threshold_seconds + 60
    out   = job._attention_workers( _fv_sam(), _GRAPH_NO_CYCLE, now=NOW,
                                    bridge_mtimes=_bridges( stale ) )
    assert "sam" in _personas( out )


def test_bridge_mtimes_none_preserves_todays_behavior():
    """FAIL-SAFE (seam unwired / read raised ⇒ liveness UNKNOWN): no veto = today's behavior."""
    job = _job()
    out = job._attention_workers( _fv_sam(), _GRAPH_NO_CYCLE, now=NOW, bridge_mtimes=None )
    assert "sam" in _personas( out )


def test_persona_absent_from_bridge_map_rostered():
    """FAIL-SAFE: no bridge entry for this persona ⇒ no POSITIVE liveness evidence ⇒ roster."""
    job = _job()
    out = job._attention_workers( _fv_sam(), _GRAPH_NO_CYCLE, now=NOW,
                                  bridge_mtimes=_bridges( 8.6, persona="somebody-else" ) )
    assert "sam" in _personas( out )


def test_future_bridge_mtime_rostered_clock_skew():
    """FAIL-SAFE (bug 097778b8): a FUTURE mtime (clock skew ⇒ negative age) is NOT
    ground-truth liveness ⇒ do not veto ⇒ roster."""
    job = _job()
    out = job._attention_workers( _fv_sam(), _GRAPH_NO_CYCLE, now=NOW,
                                  bridge_mtimes=_bridges( -300 ) )
    assert "sam" in _personas( out )


def test_now_none_does_not_raise_and_rosters():
    """FAIL-SAFE: an un-threaded clock (now=None) cannot age a bridge ⇒ no veto, no crash."""
    job = _job()
    out = job._attention_workers( _fv_sam(), _GRAPH_NO_CYCLE, now=None,
                                  bridge_mtimes=_bridges( 8.6 ) )
    assert "sam" in _personas( out )


def test_stuck_worker_in_deadlock_cycle_kept_even_when_bridge_fresh():
    """FAIL-SAFE: a stuck member of a deadlock CYCLE stays load-bearing regardless of bridge
    freshness — a mutual stall is still announced (mirrors the cec10ef9 / 1ff7be20 carve-outs)."""
    job   = _job()
    graph = { "edges": { "sam": "Rio", "Rio": "sam" }, "cycles": [ [ "Rio", "sam" ] ] }
    out   = job._attention_workers( _fv_sam(), graph, now=NOW, bridge_mtimes=_bridges( 8.6 ) )
    assert "sam" in _personas( out )


def test_veto_emits_journal_event():
    """Observability: the suppression reuses the EXISTING arbiter_stuck_bridge_veto event
    (92c7ab1d) — same name the poke leg emits, carrying persona + bridge age."""
    seen = [ ]
    job  = _job( log_fn=lambda event, **kw: seen.append( ( event, kw ) ) )
    job._attention_workers( _fv_sam(), _GRAPH_NO_CYCLE, now=NOW, bridge_mtimes=_bridges( 8.6 ) )
    vetoes = [ ( e, kw ) for e, kw in seen if e == "arbiter_stuck_bridge_veto" ]
    assert len( vetoes ) == 1
    assert vetoes[ 0 ][ 1 ][ "persona" ] == "sam"
    assert 8.0 <= vetoes[ 0 ][ 1 ][ "bridge_age_s" ] <= 9.0


# ════════════════════════════════════════════════════════════════════════════
# Part 3 — FENCE: the veto must not leak into the blocked-edge leg (my 96e8e0f7)
# ════════════════════════════════════════════════════════════════════════════

def test_blocked_edge_holder_with_fresh_bridge_still_governed_by_store_gate():
    """FENCE: bridge freshness gates the STUCK leg only. A NON-stuck blocked-edge holder is
    still decided by the 1ff7be20 store gate — a store-BACKED block on a dead peer is
    rostered even though the holder's own bridge is fresh (an active worker can be
    genuinely blocked)."""
    job = _job()
    fv  = {
        "m-sid": { "session_id": "m-sid", "persona": "maria", "stuck": False,
                   "state": "holding", "holding_on": "peer:ghost", "alive": True },
    }
    graph = { "edges": { "maria": "ghost" }, "cycles": [ ] }          # awaited absent ⇒ not alive
    store = { canonical_persona_key( "maria" ): { canonical_persona_key( "ghost" ) } }
    out   = job._attention_workers( fv, graph, now=NOW, store_edges=store,
                                    bridge_mtimes=_bridges( 5, persona="maria" ) )
    assert "maria" in _personas( out )                                # store-backed → rostered


def test_both_gates_compose_on_one_poll():
    """The suppressions coexist: sam suppressed by the bridge veto (stuck leg), maria
    suppressed by the store gate (unbacked blocked edge) — neither cannibalizes the other."""
    job = _job()
    fv  = _fv_sam()
    fv[ "m-sid" ] = { "session_id": "m-sid", "persona": "maria", "stuck": False,
                      "state": "holding", "holding_on": "peer:sam-and-reviewers", "alive": True }
    graph = { "edges": { "maria": "sam-and-reviewers" }, "cycles": [ ] }
    out   = job._attention_workers( fv, graph, now=NOW, store_edges={ },
                                    bridge_mtimes=_bridges( 8.6 ) )
    assert _personas( out ) == set()


def test_tap_managers_end_to_end_no_advisory_fires():
    """Live-path proof: with a fresh bridge, _tap_managers fires ZERO advisories for the
    stuck-flagged worker (the 21:12:20 EDT tap would never have been sent)."""
    gw    = _GW()
    job   = _job( gw )
    fired = job._tap_managers( _fv_sam(), _GRAPH_NO_CYCLE, roster=[ ], now=NOW,
                               active_managers={ "mr radio" }, bridge_mtimes=_bridges( 8.6 ) )
    assert fired == 0
    assert gw.sent == [ ]

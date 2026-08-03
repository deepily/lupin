"""
Unit tests for the late-answer catch-up module (§4.4, answer_catchup.py).

Sibling of test_dm_inbox_reconcile.py. All :7999-eligible (no DB, no server, no
net — fetch is dependency-injected; on-disk state uses a tmp base_dir).

Covers:
  - reconcile_answers pure core: fresh surfacing oldest-first by responded_at,
    dedup by notification_id, cursor advance, NO seed suppression (ruling 3),
    blank-row recorded-not-surfaced
  - the CROSS-PROCESS ledger (C-V1 unit form): an id the listener appended to the
    shared on-disk side-log is VISIBLE to a subsequent hook reconcile and dedupes
    it — proven with the falsifying pair (without the append it WOULD surface)
  - HWM round-trip + fail-open defaults (no `seeded` key, unlike the DM sibling)
  - surface_owed_answers IO shell: not-ok fetch → "" + no HWM advance; success →
    HWM persisted + side-log compacted; persona None → ""
  - _format_answer_block envelope (rulings 6/7)
"""

import json
import pytest

import lupin_cli.claude_code.hooks.lib.answer_catchup as ac


ISO_EARLY = "2026-08-01T11:00:00+00:00"
ISO_MID   = "2026-08-01T12:00:00+00:00"
ISO_LATE  = "2026-08-01T13:00:00+00:00"


def _row( nid, responded_at=ISO_MID, question="Ship it?", answer="yes", from_earlier=False ):
    return {
        "id"                   : nid,
        "question"             : question,
        "response_value"       : { "value": answer, "source": "ui" },
        "responded_at"         : responded_at,
        "from_earlier_session" : from_earlier,
        "sender_persona"       : "tiberius",
    }


# ── pure reconcile core ───────────────────────────────────────────────────────
class TestReconcileCore:
    def test_no_seed_suppression_first_reconcile_surfaces_everything( self ):
        # Empty state (no HWM) MUST surface all owed answers — the deliberate
        # divergence from the DM sibling (ruling 3). This is the load-bearing test.
        ctx, new = ac.reconcile_answers( "sess1234", [ _row( "n1" ), _row( "n2" ) ],
                                         { "cursor_ts": None, "surfaced_ids": [] } )
        assert "Ship it?" in ctx
        assert set( new[ "surfaced_ids" ] ) == { "n1", "n2" }

    def test_dedup_by_id_against_surfaced( self ):
        ctx, _ = ac.reconcile_answers( "s", [ _row( "n1" ) ],
                                       { "cursor_ts": None, "surfaced_ids": [ "n1" ] } )
        assert ctx == ""                                   # already surfaced → nothing fresh

    def test_extra_surfaced_ids_excluded_and_recorded( self ):
        ctx, new = ac.reconcile_answers( "s", [ _row( "n1" ) ],
                                         { "cursor_ts": None, "surfaced_ids": [] },
                                         extra_surfaced_ids=[ "n1" ] )
        assert ctx == ""
        assert "n1" in new[ "surfaced_ids" ]               # recorded so it stays deduped

    def test_oldest_first_by_responded_at( self ):
        ctx, _ = ac.reconcile_answers( "s",
            [ _row( "late", responded_at=ISO_LATE, question="LATE?" ),
              _row( "early", responded_at=ISO_EARLY, question="EARLY?" ) ],
            { "cursor_ts": None, "surfaced_ids": [] } )
        assert ctx.index( "EARLY?" ) < ctx.index( "LATE?" )

    def test_cursor_advances_to_max_responded_at( self ):
        _, new = ac.reconcile_answers( "s",
            [ _row( "a", responded_at=ISO_EARLY ), _row( "b", responded_at=ISO_LATE ) ],
            { "cursor_ts": None, "surfaced_ids": [] } )
        assert new[ "cursor_ts" ] == ISO_LATE

    def test_blank_row_recorded_not_surfaced( self ):
        blank = { "id": "n1", "question": "", "response_value": None, "responded_at": ISO_MID }
        ctx, new = ac.reconcile_answers( "s", [ blank ], { "cursor_ts": None, "surfaced_ids": [] } )
        assert ctx == ""
        assert "n1" in new[ "surfaced_ids" ]               # recorded → no re-fetch loop


# ── cross-process ledger (C-V1 unit form) ─────────────────────────────────────
class TestCrossProcessLedger:
    def _fetch_one( self, row ):
        def fetch_fn( persona, session_hash8, since, limit ):
            return ( True, [ row ], False )
        return fetch_fn

    def test_cv1_listener_appended_id_visible_to_hook_reconcile( self, tmp_path ):
        # LISTENER process writes the id to the shared on-disk side-log; the HOOK
        # process (surface_owed_answers) then reconciles a fetch of the SAME id and
        # must dedupe it — proving the dedup crosses the process boundary via the
        # on-disk dir, NOT an in-process set().
        sid, nid = "sess1234", "notif-1"
        ac.append_surfaced_id( sid, nid, base_dir=tmp_path )
        ctx = ac.surface_owed_answers( sid, persona="tiberius",
                                       fetch_fn=self._fetch_one( _row( nid ) ), base_dir=tmp_path )
        assert ctx == ""                                   # deduped against the OTHER process's write

    def test_cv1_red_proof_without_listener_append_it_surfaces( self, tmp_path ):
        # The falsifier: same fetch, but NO listener append → the answer DOES surface.
        # Together with the test above this proves the side-log is what suppresses it.
        sid, nid = "sess1234", "notif-1"
        ctx = ac.surface_owed_answers( sid, persona="tiberius",
                                       fetch_fn=self._fetch_one( _row( nid ) ), base_dir=tmp_path )
        assert "Ship it?" in ctx

    def test_append_then_read_side_log_roundtrip( self, tmp_path ):
        ac.append_surfaced_id( "s1", "a", base_dir=tmp_path )
        ac.append_surfaced_id( "s1", "b", base_dir=tmp_path )
        assert ac.read_surfaced_log( "s1", base_dir=tmp_path ) == [ "a", "b" ]

    def test_append_noops_on_empty_args( self, tmp_path ):
        assert ac.append_surfaced_id( "", "x", base_dir=tmp_path ) is False
        assert ac.append_surfaced_id( "s", "", base_dir=tmp_path ) is False


# ── HWM IO ────────────────────────────────────────────────────────────────────
class TestHwmIO:
    def test_roundtrip( self, tmp_path ):
        ac.write_hwm( "s1", { "cursor_ts": ISO_MID, "surfaced_ids": [ "n1" ] }, base_dir=tmp_path )
        got = ac.read_hwm( "s1", base_dir=tmp_path )
        assert got == { "cursor_ts": ISO_MID, "surfaced_ids": [ "n1" ] }   # NO `seeded` key

    def test_missing_defaults_empty_no_seeded_key( self, tmp_path ):
        got = ac.read_hwm( "nope", base_dir=tmp_path )
        assert got == { "cursor_ts": None, "surfaced_ids": [] }
        assert "seeded" not in got

    def test_corrupt_defaults_empty( self, tmp_path ):
        p = ac._hwm_path( "bad", base_dir=tmp_path )
        p.parent.mkdir( parents=True, exist_ok=True )
        p.write_text( "{not json" )
        assert ac.read_hwm( "bad", base_dir=tmp_path ) == { "cursor_ts": None, "surfaced_ids": [] }


# ── IO shell ──────────────────────────────────────────────────────────────────
class TestSurfaceOwedAnswers:
    def test_persona_none_returns_empty( self, tmp_path ):
        # persona-less session (accepted gap) — resolve returns None, surface nothing.
        called = { "n": 0 }
        def fetch_fn( **k ):
            called[ "n" ] += 1; return ( True, [], False )
        out = ac.surface_owed_answers( "s1", persona=None,
                                       fetch_fn=fetch_fn, base_dir=tmp_path )
        # _resolve_persona reads a bridge that does not exist here → None → "".
        assert out == ""

    def test_not_ok_fetch_returns_empty_and_no_hwm_advance( self, tmp_path ):
        def fetch_fn( **k ): return ( False, [], False )
        out = ac.surface_owed_answers( "s1", persona="tiberius", fetch_fn=fetch_fn, base_dir=tmp_path )
        assert out == ""
        # HWM must NOT have been written (retry next turn).
        assert not ac._hwm_path( "s1", base_dir=tmp_path ).exists()

    def test_success_persists_hwm_and_compacts_side_log( self, tmp_path ):
        ac.append_surfaced_id( "s1", "old", base_dir=tmp_path )
        def fetch_fn( **k ): return ( True, [ _row( "n1" ) ], False )
        out = ac.surface_owed_answers( "s1", persona="tiberius", fetch_fn=fetch_fn, base_dir=tmp_path )
        assert "Ship it?" in out
        # HWM persisted with the new id...
        hwm = ac.read_hwm( "s1", base_dir=tmp_path )
        assert "n1" in hwm[ "surfaced_ids" ]
        # ...and the side-log compacted (folded under hook ownership).
        assert ac.read_surfaced_log( "s1", base_dir=tmp_path ) == []

    def test_empty_session_id_returns_empty( self, tmp_path ):
        assert ac.surface_owed_answers( "", persona="tiberius", base_dir=tmp_path ) == ""


# ── envelope formatting (rulings 6/7) ─────────────────────────────────────────
class TestFormatBlock:
    def test_carries_question_answer_responded_at( self ):
        block = ac._format_answer_block( _row( "n1", question="Deploy?", answer="yes" ) )
        assert "Deploy?" in block
        assert "yes" in block
        assert ISO_MID in block
        assert "no action required" in block               # non-interrupt framing

    def test_earlier_session_flagged( self ):
        block = ac._format_answer_block( _row( "n1", from_earlier=True ) )
        assert "earlier session of this persona" in block

    def test_same_session_not_flagged( self ):
        block = ac._format_answer_block( _row( "n1", from_earlier=False ) )
        assert "earlier session of this persona" not in block


def isolated_unit_test():
    """Run this module's tests in isolation for the smoke-runner harness."""
    import time
    start = time.time()
    code = pytest.main( [ __file__, "-q", "-p", "no:cacheprovider" ] )
    return ( code == 0 ), time.time() - start, f"pytest exit {code}"


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} answer_catchup tests in {secs:.3f}s — {msg}" )

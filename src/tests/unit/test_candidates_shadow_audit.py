"""
Unit tests for the shadow audit.

Every case runs on a temporary data folder with a fake transport, so no call leaves the process.
Each rule has a case that fails when the rule is removed.
The bound has known values, a planted miss moves it, and a repeated audit leaves one receipt.
"""
import json

import pytest

from cosa.repo.symindex.candidates import shadow_audit as sa
from cosa.repo.symindex.candidates.errors import CandidateError

GEN   = "gen-1"
INDEX = "idx-1"
LIVE  = { "verdict": "NEW", "candidate_ids": [ "a", "b", "c" ] }


def sweep_of( verdict, ids=() ):
    """A full-sweep answer."""
    return { "verdict": verdict, "causal_ids": list( ids ) }


def receipt_for( need, verdict, ids, live=None, language="py", generation=GEN, today="2026-10-15" ):
    """One audit receipt built from a need and a full-sweep answer."""
    return sa.audit_receipt( need, language, generation, INDEX, live or LIVE, sweep_of( verdict, ids ), today )


class TestBound:
    """The 95 percent upper bound."""

    def test_zero_in_three_hundred_is_about_one_percent( self ):
        assert sa.audit_bound( 0, 300 ) == pytest.approx( 0.01 )

    def test_zero_in_thirty_is_about_ten_percent( self ):
        assert sa.audit_bound( 0, 30 ) == pytest.approx( 0.1 )

    def test_one_miss_in_three_hundred_uses_the_wilson_bound( self ):
        assert sa.audit_bound( 1, 300 ) == pytest.approx( 0.0148, abs=0.0002 )

    def test_a_planted_miss_moves_the_bound( self ):
        assert sa.audit_bound( 1, 300 ) > sa.audit_bound( 0, 300 )
        assert sa.audit_bound( 2, 300 ) > sa.audit_bound( 1, 300 )

    def test_more_audits_tighten_the_bound( self ):
        assert sa.audit_bound( 0, 600 ) < sa.audit_bound( 0, 300 )
        assert sa.audit_bound( 1, 600 ) < sa.audit_bound( 1, 300 )

    def test_no_audit_says_nothing( self ):
        assert sa.audit_bound( 0, 0 ) == 1.0

    def test_the_bound_never_passes_one( self ):
        assert sa.audit_bound( 0, 1 ) == 1.0
        assert sa.audit_bound( 5, 5 ) == pytest.approx( 1.0 )

    @pytest.mark.parametrize( "misses, n", [ ( -1, 10 ), ( 11, 10 ), ( 0, -1 ), ( 1.5, 10 ), ( 0, 10.0 ), ( True, 10 ) ] )
    def test_bad_counts_are_refused( self, misses, n ):
        with pytest.raises( CandidateError ) as caught:
            sa.audit_bound( misses, n )
        assert caught.value.code == sa.AUDIT_COUNTS_INVALID


class TestSample:
    """The sample is a hash, so it is repeatable."""

    def test_the_same_lookup_is_always_in_or_out( self ):
        answers = { sa.is_sampled( f"need {i}", GEN ) for i in range( 3 ) for _ in range( 3 ) }
        assert answers <= { True, False }
        assert sa.is_sampled( "need 7", GEN ) == sa.is_sampled( "need 7", GEN )

    def test_about_one_percent_are_taken( self ):
        taken = sum( 1 for i in range( 20000 ) if sa.is_sampled( f"need {i}", GEN ) )
        assert 150 <= taken <= 250

    def test_a_rate_of_zero_takes_none_and_one_takes_all( self ):
        assert not any( sa.is_sampled( f"n{i}", GEN, 0 ) for i in range( 200 ) )
        assert all( sa.is_sampled( f"n{i}", GEN, 1 ) for i in range( 200 ) )

    def test_a_new_generation_draws_a_new_sample( self ):
        one = { i for i in range( 5000 ) if sa.is_sampled( f"need {i}", "g1", 0.1 ) }
        two = { i for i in range( 5000 ) if sa.is_sampled( f"need {i}", "g2", 0.1 ) }
        assert one != two

    @pytest.mark.parametrize( "rate", [ -0.1, 1.1 ] )
    def test_a_rate_outside_zero_to_one_is_refused( self, rate ):
        with pytest.raises( CandidateError ) as caught:
            sa.is_sampled( "x", GEN, rate )
        assert caught.value.code == sa.AUDIT_RATE_INVALID


class TestCompare:
    """What counts as a miss."""

    def test_a_match_with_no_kept_causal_id_is_a_miss( self ):
        assert sa.compare( "NEW", "REUSE", [ "z" ], [ "a", "b" ] ) == "miss"
        assert sa.compare( "NEW", "EXTEND", [ "z", "y" ], [ "a", "b" ] ) == "miss"

    def test_a_match_with_a_kept_causal_id_is_ok( self ):
        assert sa.compare( "NEW", "REUSE", [ "b", "z" ], [ "a", "b" ] ) == "ok"

    def test_a_new_verdict_from_the_full_sweep_is_ok( self ):
        assert sa.compare( "NEW", "NEW", [], [ "a" ] ) == "ok"

    def test_an_undecided_full_sweep_is_inconclusive( self ):
        assert sa.compare( "NEW", "UNCERTAIN_READ_SOURCE", [], [ "a" ] ) == "inconclusive"

    def test_the_served_verdict_does_not_change_the_outcome( self ):
        assert sa.compare( "REUSE", "REUSE", [ "z" ], [ "a" ] ) == "miss"
        assert sa.compare( "REUSE", "REUSE", [ "a" ], [ "a" ] ) == "ok"


class TestReceipt:
    """One audit's receipt."""

    def test_miss_receipt_names_the_missed_ids_and_hides_the_words( self ):
        r = receipt_for( "read a secret config", "REUSE", [ "z", "a" ] )
        assert set( r ) == set( sa.RECEIPT_FIELDS )
        assert r[ "kind" ] == sa.KIND and r[ "outcome" ] == "ok" and r[ "missed_ids" ] == []
        miss = receipt_for( "read a secret config", "REUSE", [ "z", "y" ] )
        assert miss[ "outcome" ] == "miss" and miss[ "missed_ids" ] == [ "y", "z" ]
        assert "secret" not in json.dumps( miss )
        assert miss[ "need_hash" ] == sa.need_hash( "read a secret config" )
        assert miss[ "candidate_count" ] == 3

    def test_the_id_follows_need_generation_and_index( self ):
        base = receipt_for( "n", "NEW", [] )[ "id" ]
        assert len( base ) == 16
        assert receipt_for( "n", "NEW", [] )[ "id" ] == base
        assert receipt_for( "m", "NEW", [] )[ "id" ] != base
        assert receipt_for( "n", "NEW", [], generation="gen-2" )[ "id" ] != base
        assert sa.audit_receipt( "n", "py", GEN, "idx-2", LIVE, sweep_of( "NEW" ), "2026-10-15" )[ "id" ] != base


class TestStore:
    """Receipts are written once and read back."""

    def test_a_repeat_audit_leaves_the_first_receipt( self, tmp_path ):
        first  = sa.store_receipt( tmp_path, receipt_for( "n", "NEW", [] ) )
        second = sa.store_receipt( tmp_path, dict( receipt_for( "n", "NEW", [] ), outcome="miss" ) )
        assert second == first
        assert len( list( ( tmp_path / "receipts" ).glob( "shadow-*.json" ) ) ) == 1

    def test_load_reads_only_audit_receipts_sorted( self, tmp_path ):
        for need in ( "b", "a", "c" ): sa.store_receipt( tmp_path, receipt_for( need, "NEW", [] ) )
        ( tmp_path / "receipts" / "0123456789abcdef.json" ).write_text( json.dumps( { "tool": "check_exists" } ) )
        loaded = sa.load_receipts( tmp_path )
        assert [ r[ "id" ] for r in loaded ] == sorted( r[ "id" ] for r in loaded ) and len( loaded ) == 3

    def test_a_folder_with_no_receipts_is_empty( self, tmp_path ):
        assert sa.load_receipts( tmp_path ) == []

    @pytest.mark.parametrize( "text", [ "not json", json.dumps( [ 1 ] ), json.dumps( { "kind": "shadow_audit" } ) ] )
    def test_a_corrupt_receipt_is_named( self, tmp_path, text ):
        ( tmp_path / "receipts" ).mkdir()
        ( tmp_path / "receipts" / "shadow-bad.json" ).write_text( text )
        with pytest.raises( CandidateError ) as caught:
            sa.load_receipts( tmp_path )
        assert caught.value.code == sa.AUDIT_RECEIPT_CORRUPT
        assert "shadow-bad.json" in caught.value.detail

    def test_an_unknown_outcome_is_corrupt( self, tmp_path ):
        sa.store_receipt( tmp_path, dict( receipt_for( "n", "NEW", [] ), outcome="maybe" ) )
        with pytest.raises( CandidateError ):
            sa.load_receipts( tmp_path )


class TestTally:
    """Counting per language and generation."""

    def receipts( self ):
        out = [ receipt_for( f"py ok {i}", "NEW", [] ) for i in range( 4 ) ]
        out += [ receipt_for( "py miss", "REUSE", [ "z" ] ), receipt_for( "py unsure", "UNCERTAIN_READ_SOURCE", [] ) ]
        out += [ receipt_for( "ts ok", "NEW", [], language="ts" ), receipt_for( "py later", "NEW", [], generation="gen-2" ) ]
        return out

    def test_counts_one_language_and_generation( self ):
        t = sa.tally( self.receipts(), "py", GEN )
        assert ( t[ "audits" ], t[ "misses" ], t[ "inconclusive" ] ) == ( 5, 1, 1 )
        assert t[ "bound" ] == sa.audit_bound( 1, 5 )
        assert ( t[ "language" ], t[ "generation" ] ) == ( "py", GEN )

    def test_another_language_and_generation_are_apart( self ):
        assert sa.tally( self.receipts(), "ts", GEN )[ "audits" ] == 1
        assert sa.tally( self.receipts(), "py", "gen-2" )[ "audits" ] == 1
        assert sa.tally( [], "py", GEN )[ "bound" ] == 1.0

    def test_a_write_new_verdict_reads_the_bound_from_disk( self, tmp_path ):
        for need in ( "a", "b", "c" ): sa.store_receipt( tmp_path, receipt_for( need, "NEW", [] ) )
        got = sa.bound_for_verdict( tmp_path, "py", GEN )
        assert got[ "audits" ] == 3 and got[ "bound" ] == pytest.approx( 1.0 )


class TestQueueAndRun:
    """The sampled lookups and the scheduled drain."""

    def test_every_lookup_is_counted_and_a_sampled_one_is_queued( self, tmp_path ):
        assert sa.enqueue_if_sampled( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-15", rate=0 ) is None
        key = sa.enqueue_if_sampled( tmp_path, "n2", "py", GEN, INDEX, LIVE, "2026-10-15", rate=1 )
        assert len( key ) == 16
        assert sa.daily_volume( tmp_path ) == { "2026-10-15": { "lookups": 2, "audits": 0 } }
        assert len( list( ( tmp_path / "shadow-pending" ).glob( "*.json" ) ) ) == 1

    def test_the_same_lookup_queues_once( self, tmp_path ):
        a = sa.enqueue_if_sampled( tmp_path, "n2", "py", GEN, INDEX, LIVE, "2026-10-15", rate=1 )
        b = sa.enqueue_if_sampled( tmp_path, "n2", "py", GEN, INDEX, LIVE, "2026-10-15", rate=1 )
        assert a == b
        assert len( list( ( tmp_path / "shadow-pending" ).glob( "*.json" ) ) ) == 1

    def test_the_drain_stores_receipts_and_clears_the_queue( self, tmp_path ):
        for need in ( "n1", "n2", "n3" ): sa.enqueue_if_sampled( tmp_path, need, "py", GEN, INDEX, LIVE, "2026-10-14", rate=1 )
        seen = []
        def transport( need ):
            seen.append( need )
            return sweep_of( "REUSE", [ "z" ] if need == "n2" else [ "a" ] )
        out = sa.run_pending( tmp_path, transport, "2026-10-15" )
        assert out[ "audited" ] == 3 and out[ "failed" ] == 0 and sorted( seen ) == [ "n1", "n2", "n3" ]
        assert sorted( r[ "outcome" ] for r in out[ "receipts" ] ) == [ "miss", "ok", "ok" ]
        assert list( ( tmp_path / "shadow-pending" ).glob( "*.json" ) ) == []
        assert sa.tally( sa.load_receipts( tmp_path ), "py", GEN )[ "misses" ] == 1

    def test_a_failing_transport_leaves_the_item_queued( self, tmp_path ):
        for need in ( "n1", "n2" ): sa.enqueue_if_sampled( tmp_path, need, "py", GEN, INDEX, LIVE, "2026-10-14", rate=1 )
        def transport( need ):
            if need == "n1": raise TimeoutError( "no answer" )
            return sweep_of( "NEW" )
        out = sa.run_pending( tmp_path, transport, "2026-10-15" )
        assert ( out[ "audited" ], out[ "failed" ] ) == ( 1, 1 )
        assert len( list( ( tmp_path / "shadow-pending" ).glob( "*.json" ) ) ) == 1

    def test_limit_takes_the_first_items_only( self, tmp_path ):
        for need in ( "n1", "n2", "n3" ): sa.enqueue_if_sampled( tmp_path, need, "py", GEN, INDEX, LIVE, "2026-10-14", rate=1 )
        out = sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-15", limit=2 )
        assert out[ "audited" ] == 2
        assert len( list( ( tmp_path / "shadow-pending" ).glob( "*.json" ) ) ) == 1

    def test_an_empty_queue_audits_nothing( self, tmp_path ):
        assert sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-15" ) == { "audited": 0, "failed": 0, "receipts": [] }

    def test_daily_volume_joins_lookups_and_audits( self, tmp_path ):
        sa.enqueue_if_sampled( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14", rate=1 )
        sa.enqueue_if_sampled( tmp_path, "n2", "py", GEN, INDEX, LIVE, "2026-10-14", rate=0 )
        sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-15" )
        assert sa.daily_volume( tmp_path ) == { "2026-10-14": { "lookups": 2, "audits": 0 }, "2026-10-15": { "lookups": 0, "audits": 1 } }

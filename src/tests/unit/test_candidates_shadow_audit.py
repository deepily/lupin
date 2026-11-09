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
        assert sa.audit_bound( 0, 300 ) == pytest.approx( 0.01, abs=0.0001 )

    def test_zero_in_thirty_is_about_ten_percent( self ):
        assert sa.audit_bound( 0, 30 ) == pytest.approx( 0.095, abs=0.0005 )

    def test_zero_misses_use_the_exact_form_and_never_pass_the_rule_of_three( self ):
        assert sa.audit_bound( 0, 5 ) == pytest.approx( 1 - 0.05 ** ( 1 / 5 ) )
        assert all( sa.audit_bound( 0, n ) <= 3.0 / n for n in range( 1, 400 ) )

    def test_a_miss_never_lowers_the_bound_at_any_count( self ):
        assert all( sa.audit_bound( 1, n ) > sa.audit_bound( 0, n ) for n in range( 1, 200 ) )

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
        assert sa.audit_bound( 0, 1 ) == pytest.approx( 0.95 )
        assert sa.audit_bound( 5, 5 ) == pytest.approx( 1.0 )
        assert sa.audit_bound( 1, 1 ) <= 1.0

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

    def test_a_match_that_names_no_causal_id_is_inconclusive( self ):
        assert sa.compare( "NEW", "REUSE", [], [ "a" ] ) == "inconclusive"

    def test_an_undecided_full_sweep_is_inconclusive( self ):
        assert sa.compare( "NEW", "UNCERTAIN_READ_SOURCE", [], [ "a" ] ) == "inconclusive"

    def test_a_no_match_from_the_full_sweep_is_ok_like_the_old_new_verdict( self ):
        assert sa.compare( "NEW", "UNCERTAIN_READ_SOURCE", [], [ "a" ], "NO_MATCH" ) == "ok"

    def test_an_uncertain_full_sweep_with_any_other_cause_is_inconclusive( self ):
        assert sa.compare( "NEW", "UNCERTAIN_READ_SOURCE", [], [ "a" ], "LOW_CONFIDENCE" ) == "inconclusive"

    def test_the_receipt_reads_the_cause_of_the_sweep_when_it_has_one( self ):
        rec = sa.audit_receipt( "n", "py", GEN, "idx-1", LIVE, { **sweep_of( "UNCERTAIN_READ_SOURCE" ), "cause": "NO_MATCH" }, "2026-10-15" )
        assert rec[ "outcome" ] == "ok" and rec[ "full_verdict" ] == "UNCERTAIN_READ_SOURCE"

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
        planted = dict( receipt_for( "n", "NEW", [] ), outcome="maybe" )
        ( tmp_path / "receipts" ).mkdir()
        ( tmp_path / "receipts" / f"shadow-{planted[ 'id' ]}.json" ).write_text( json.dumps( planted ) )
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
        assert got[ "audits" ] == 3 and got[ "bound" ] == pytest.approx( sa.audit_bound( 0, 3 ) )


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

    def test_on_failure_hears_each_failed_item_with_its_id_and_the_exception( self, tmp_path ):
        for need in ( "n1", "n2" ): sa.enqueue_if_sampled( tmp_path, need, "py", GEN, INDEX, LIVE, "2026-10-14", rate=1 )
        def transport( need ):
            if need == "n1": raise TimeoutError( "no answer" )
            return sweep_of( "NEW" )
        heard = []
        out   = sa.run_pending( tmp_path, transport, "2026-10-15", on_failure=lambda item_id, exc: heard.append( ( item_id, type( exc ).__name__, str( exc ) ) ) )
        assert out[ "failed" ] == 1 and len( heard ) == 1
        assert heard[ 0 ][ 1: ] == ( "TimeoutError", "no answer" ) and len( heard[ 0 ][ 0 ] ) == 16, "the queue file's own id, not the need"

    def test_limit_takes_the_oldest_queued_items_first( self, tmp_path ):
        for need, day in ( ( "n-new", "2026-10-14" ), ( "n-old", "2026-10-12" ), ( "n-mid", "2026-10-13" ) ):
            sa.enqueue_if_sampled( tmp_path, need, "py", GEN, INDEX, LIVE, day, rate=1 )
        seen = []
        def transport( need ):
            seen.append( need )
            return sweep_of( "NEW" )
        out = sa.run_pending( tmp_path, transport, "2026-10-15", limit=2 )
        assert out[ "audited" ] == 2 and seen == [ "n-old", "n-mid" ]
        assert len( list( ( tmp_path / "shadow-pending" ).glob( "*.json" ) ) ) == 1

    def test_failing_items_go_behind_the_fresh_ones( self, tmp_path ):
        for need in ( "bad-1", "bad-2", "good" ): sa.enqueue_if_sampled( tmp_path, need, "py", GEN, INDEX, LIVE, "2026-10-14", rate=1 )
        def transport( need ):
            if need.startswith( "bad" ): raise TimeoutError( need )
            return sweep_of( "NEW" )
        runs = [ sa.run_pending( tmp_path, transport, "2026-10-15", limit=1 ) for _ in range( 3 ) ]
        assert sum( r[ "audited" ] for r in runs ) == 1
        queued = [ json.loads( p.read_text() ) for p in ( tmp_path / "shadow-pending" ).glob( "*.json" ) ]
        assert sorted( q[ "need" ] for q in queued ) == [ "bad-1", "bad-2" ]
        assert [ q[ "attempts" ] for q in queued ] == [ 1, 1 ]

    def test_a_truncated_queue_file_is_set_aside_and_the_run_goes_on( self, tmp_path ):
        sa.enqueue_if_sampled( tmp_path, "good", "py", GEN, INDEX, LIVE, "2026-10-14", rate=1 )
        ( tmp_path / "shadow-pending" / "0000000000000000.json" ).write_text( '{"id": "0000' )
        out = sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-15" )
        assert ( out[ "audited" ], out[ "corrupt" ] ) == ( 1, 1 )
        assert ( tmp_path / "shadow-pending" / "0000000000000000.json.corrupt" ).exists()

    @pytest.mark.parametrize( "text", [ "[1, 2]", "null", json.dumps( { "id": "x", "need": "n" } ), json.dumps( { **dict.fromkeys( sa.ITEM_FIELDS, 1 ), "attempts": "no" } ),
                                        json.dumps( { **dict.fromkeys( sa.ITEM_FIELDS, 1 ), "live": "not a dict" } ),
                                        json.dumps( { **dict.fromkeys( sa.ITEM_FIELDS, "x" ), "attempts": 0, "live": { }, "queued_on": None } ),
                                        json.dumps( { **dict.fromkeys( sa.ITEM_FIELDS, "x" ), "attempts": 0, "live": { }, "id": None } ) ] )
    def test_a_queue_file_of_the_wrong_shape_is_set_aside( self, tmp_path, text ):
        sa.enqueue_if_sampled( tmp_path, "good", "py", GEN, INDEX, LIVE, "2026-10-14", rate=1 )
        ( tmp_path / "shadow-pending" / "ffffffffffffffff.json" ).write_text( text )
        out = sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-15" )
        assert ( out[ "audited" ], out[ "corrupt" ] ) == ( 1, 1 )

    @pytest.mark.parametrize( "answer", [ { "verdict": "NEW" }, { "error": "boom" }, None ] )
    def test_a_malformed_sweep_answer_counts_as_a_failure_and_the_run_goes_on( self, tmp_path, answer ):
        for need in ( "bad", "good" ): sa.enqueue_if_sampled( tmp_path, need, "py", GEN, INDEX, LIVE, "2026-10-14", rate=1 )
        out = sa.run_pending( tmp_path, lambda need: answer if need == "bad" else sweep_of( "NEW" ), "2026-10-15" )
        assert ( out[ "audited" ], out[ "failed" ] ) == ( 1, 1 )
        left = [ json.loads( p.read_text() ) for p in ( tmp_path / "shadow-pending" ).glob( "*.json" ) ]
        assert [ ( q[ "need" ], q[ "attempts" ] ) for q in left ] == [ ( "bad", 1 ) ]

    @pytest.mark.parametrize( "text", [ '{"id": "ab', json.dumps( [ 1 ] ), json.dumps( { "kind": "shadow_audit" } ) ] )
    def test_a_damaged_receipt_file_fails_its_item_without_a_sweep_and_the_run_goes_on( self, tmp_path, text ):
        for need in ( "n1", "n2" ): sa.enqueue_if_sampled( tmp_path, need, "py", GEN, INDEX, LIVE, "2026-10-14", rate=1 )
        damaged = sa.audit_receipt( "n1", "py", GEN, INDEX, LIVE, sweep_of( "NEW" ), "2026-10-15" )[ "id" ]
        ( sa._folder( tmp_path, "receipts" ) / f"shadow-{damaged}.json" ).write_text( text )
        swept = []
        def transport( need ):
            swept.append( need )
            return sweep_of( "NEW" )
        for _ in range( 2 ):
            out = sa.run_pending( tmp_path, transport, "2026-10-15" )
        assert swept == [ "n2" ]                                     # n1 was never swept, on either drain
        assert ( out[ "audited" ], out[ "failed" ] ) == ( 0, 1 )
        left = [ json.loads( p.read_text() ) for p in ( tmp_path / "shadow-pending" ).glob( "*.json" ) ]
        assert [ ( q[ "need" ], q[ "attempts" ] ) for q in left ] == [ ( "n1", 2 ) ]

    @pytest.mark.parametrize( "text", [ json.dumps( [ 1 ] ), json.dumps( list( sa.RECEIPT_FIELDS ) ), json.dumps( "outcome" ) ] )
    def test_a_stored_file_that_parses_but_is_not_a_receipt_is_refused( self, tmp_path, text ):
        receipt = receipt_for( "n", "NEW", [] )
        ( tmp_path / "receipts" ).mkdir()
        ( tmp_path / "receipts" / f"shadow-{receipt[ 'id' ]}.json" ).write_text( text )
        with pytest.raises( CandidateError ) as caught:
            sa.store_receipt( tmp_path, receipt )
        assert caught.value.code == sa.AUDIT_RECEIPT_CORRUPT and "wrong shape" in caught.value.detail

    def test_a_write_in_progress_is_not_read_by_the_drain( self, tmp_path ):
        sa.enqueue_if_sampled( tmp_path, "good", "py", GEN, INDEX, LIVE, "2026-10-14", rate=1 )
        half = tmp_path / "shadow-pending" / ".tmp-123-abc.json"
        half.write_text( '{"id": "ab' )
        out = sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-15" )
        assert ( out[ "audited" ], out[ "corrupt" ] ) == ( 1, 0 )
        assert half.exists()

    def test_the_temporary_name_cannot_match_a_json_listing( self, tmp_path ):
        name = sa._temp_name( tmp_path / "abc.json" ).name
        assert name.startswith( sa.TEMP_PREFIX ) and not name.endswith( ".json" )

    def test_a_truncated_receipt_is_named_when_the_same_audit_is_stored( self, tmp_path ):
        receipt = receipt_for( "n", "NEW", [] )
        ( tmp_path / "receipts" ).mkdir()
        ( tmp_path / "receipts" / f"shadow-{receipt[ 'id' ]}.json" ).write_text( '{"kind": "shad' )
        with pytest.raises( CandidateError ) as caught:
            sa.store_receipt( tmp_path, receipt )
        assert caught.value.code == sa.AUDIT_RECEIPT_CORRUPT

    def test_no_temporary_file_is_left_behind( self, tmp_path ):
        sa.enqueue_if_sampled( tmp_path, "n", "py", GEN, INDEX, LIVE, "2026-10-14", rate=1 )
        sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-15" )
        assert list( tmp_path.rglob( ".tmp-*" ) ) == []

    def test_an_empty_queue_audits_nothing( self, tmp_path ):
        assert sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-15" ) == { "audited": 0, "failed": 0, "corrupt": 0, "dropped": 0, "receipts": [] }

    def test_daily_volume_joins_lookups_and_audits( self, tmp_path ):
        sa.enqueue_if_sampled( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14", rate=1 )
        sa.enqueue_if_sampled( tmp_path, "n2", "py", GEN, INDEX, LIVE, "2026-10-14", rate=0 )
        sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-15" )
        assert sa.daily_volume( tmp_path ) == { "2026-10-14": { "lookups": 2, "audits": 0 }, "2026-10-15": { "lookups": 0, "audits": 1 } }


class TestKnownMissAndCaps:
    """The known-miss marker, the drain order, the UNKNOWN_ENTRY drop and the weekly cap."""

    def pending( self, tmp_path ):
        """The queue files, by queue id."""
        return { p.stem: json.loads( p.read_text() ) for p in ( tmp_path / "shadow-pending" ).glob( "*.json" ) }

    def test_enqueue_pending_writes_the_item_without_a_count_or_a_sample( self, tmp_path ):
        key = sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14", known_miss=True )
        assert self.pending( tmp_path )[ key ] == { "id": key, "need": "n1", "language": "py", "generation": GEN, "index_sha": INDEX, "live": LIVE,
                                                    "queued_on": "2026-10-14", "attempts": 0, "known_miss": True, "exclude_id": None, "tie": None }
        assert not ( tmp_path / "receipts" ).exists(), "no lookup count was added"
        assert sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14" ) == key and len( self.pending( tmp_path ) ) == 1, "the same lookup queues once"

    def test_the_sampled_path_queues_through_it_with_the_marker_false_and_still_counts( self, tmp_path ):
        key = sa.enqueue_if_sampled( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14", rate=1 )
        assert self.pending( tmp_path )[ key ][ "known_miss" ] is False and sa.daily_volume( tmp_path )[ "2026-10-14" ][ "lookups" ] == 1

    def test_old_queue_and_receipt_files_without_the_marker_still_read_as_not_known_miss( self, tmp_path ):
        key  = sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14" )
        path = tmp_path / "shadow-pending" / f"{key}.json"
        old  = { k: v for k, v in json.loads( path.read_text() ).items() if k != "known_miss" }
        path.write_text( json.dumps( old ) )
        out = sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-15" )
        assert out[ "audited" ] == 1 and out[ "corrupt" ] == 0 and out[ "receipts" ][ 0 ][ "known_miss" ] is False
        stored = tmp_path / "receipts" / f"shadow-{out[ 'receipts' ][ 0 ][ 'id' ]}.json"
        stored.write_text( json.dumps( { k: v for k, v in out[ "receipts" ][ 0 ].items() if k != "known_miss" } ) )
        assert sa.load_receipts( tmp_path )[ 0 ][ "known_miss" ] is False

    def test_a_marker_that_is_not_true_or_false_is_a_corrupt_item( self, tmp_path ):
        key  = sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14" )
        path = tmp_path / "shadow-pending" / f"{key}.json"
        path.write_text( json.dumps( { **json.loads( path.read_text() ), "known_miss": "yes" } ) )
        assert sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-15" )[ "corrupt" ] == 1

    def test_known_miss_items_drain_before_older_and_fresher_random_ones( self, tmp_path ):
        sa.enqueue_pending( tmp_path, "random-old", "py", GEN, INDEX, LIVE, "2026-10-10" )
        sa.enqueue_pending( tmp_path, "known", "py", GEN, INDEX, LIVE, "2026-10-14", known_miss=True )
        seen = []
        def transport( need ):
            seen.append( need )
            return sweep_of( "NEW" )
        sa.run_pending( tmp_path, transport, "2026-10-15", limit=1 )
        assert seen == [ "known" ], "a known-miss item beats an older random one"

    def test_a_known_miss_item_that_failed_still_goes_before_a_fresh_random_one( self, tmp_path ):
        sa.enqueue_pending( tmp_path, "known", "py", GEN, INDEX, LIVE, "2026-10-14", known_miss=True )
        sa.run_pending( tmp_path, lambda need: ( _ for _ in () ).throw( TimeoutError( "x" ) ), "2026-10-15" )
        sa.enqueue_pending( tmp_path, "random", "py", GEN, INDEX, LIVE, "2026-10-14" )
        seen = []
        def transport( need ):
            seen.append( need )
            return sweep_of( "NEW" )
        sa.run_pending( tmp_path, transport, "2026-10-15", limit=1 )
        assert seen == [ "known" ]

    def test_the_receipt_carries_the_marker_and_the_two_tallies_are_separate( self, tmp_path ):
        sa.enqueue_pending( tmp_path, "known", "py", GEN, INDEX, LIVE, "2026-10-14", known_miss=True )
        sa.enqueue_pending( tmp_path, "random", "py", GEN, INDEX, LIVE, "2026-10-14" )
        sa.run_pending( tmp_path, lambda need: sweep_of( "REUSE", [ "z" ] ), "2026-10-15" )
        receipts = sa.load_receipts( tmp_path )
        assert sorted( r[ "known_miss" ] for r in receipts ) == [ False, True ]
        assert ( sa.tally( receipts, "py", GEN )[ "audits" ], sa.tally( receipts, "py", GEN )[ "misses" ] ) == ( 1, 1 ), "the random bound sees one audit"
        assert sa.tally( receipts, "py", GEN, known_miss=True )[ "audits" ] == 1

    def test_an_item_answering_unknown_entry_is_dropped_and_counted_on_its_third_failed_attempt( self, tmp_path ):
        key = sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14", known_miss=True )
        def refuse( need ): raise CandidateError( "AUDIT_SWEEP_REFUSED", sa.UNKNOWN_ENTRY )
        first  = sa.run_pending( tmp_path, refuse, "2026-10-15" )
        second = sa.run_pending( tmp_path, refuse, "2026-10-15" )
        assert ( first[ "dropped" ], second[ "dropped" ] ) == ( 0, 0 ) and self.pending( tmp_path )[ key ][ "attempts" ] == 2
        third = sa.run_pending( tmp_path, refuse, "2026-10-15" )
        assert ( third[ "dropped" ], third[ "failed" ], third[ "audited" ] ) == ( 1, 1, 0 ) and self.pending( tmp_path ) == {}

    def test_other_failures_are_never_dropped_however_often_they_repeat( self, tmp_path ):
        key = sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14" )
        def stale( need ): raise CandidateError( "AUDIT_SWEEP_REFUSED", "INDEX_STALE" )
        def late( need ): raise TimeoutError( sa.UNKNOWN_ENTRY )
        for fn in ( stale, stale, stale, late, late, late ): assert sa.run_pending( tmp_path, fn, "2026-10-15" )[ "dropped" ] == 0
        assert self.pending( tmp_path )[ key ][ "attempts" ] == 6

    def test_audits_in_week_counts_the_seven_days_ending_today_and_no_others( self, tmp_path ):
        for need, day in ( ( "n1", "2026-10-08" ), ( "n2", "2026-10-09" ), ( "n3", "2026-10-15" ), ( "n4", "2026-10-16" ) ):
            sa.enqueue_pending( tmp_path, need, "py", GEN, INDEX, LIVE, "2026-10-01" )
            sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), day )
        assert sa.audits_in_week( tmp_path, "2026-10-15" ) == 2, "the 9th through the 15th: not the 8th, not the 16th"

    def test_the_weekly_cap_stops_the_drain_and_leaves_the_rest_queued( self, tmp_path ):
        for n in range( 5 ): sa.enqueue_pending( tmp_path, f"n{n}", "py", GEN, INDEX, LIVE, "2026-10-14" )
        out = sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-15", weekly_cap=3 )
        assert ( out[ "audited" ], out[ "stopped_by" ] ) == ( 3, "weekly_cap" ) and len( self.pending( tmp_path ) ) == 2
        again = sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-16", weekly_cap=3 )
        assert ( again[ "audited" ], again[ "stopped_by" ] ) == ( 0, "weekly_cap" ), "the week is already spent"
        later = sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-22", weekly_cap=3 )
        assert later[ "audited" ] == 2 and later[ "stopped_by" ] is None, "the first three fell out of the seven days"

    def test_a_failed_attempt_does_not_use_up_the_weekly_cap( self, tmp_path ):
        for n in range( 3 ): sa.enqueue_pending( tmp_path, f"n{n}", "py", GEN, INDEX, LIVE, "2026-10-14" )
        def transport( need ):
            if need == "n0": raise TimeoutError( "x" )
            return sweep_of( "NEW" )
        out = sa.run_pending( tmp_path, transport, "2026-10-15", weekly_cap=2 )
        assert ( out[ "audited" ], out[ "failed" ] ) == ( 2, 1 ) and out[ "stopped_by" ] is None

    def test_without_a_cap_or_a_ceiling_there_is_no_stopped_by( self, tmp_path ):
        assert "stopped_by" not in sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-15" )

    def test_an_old_item_and_receipt_without_exclude_id_or_tie_read_as_none( self, tmp_path ):
        key  = sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14", known_miss=True )
        path = tmp_path / "shadow-pending" / f"{key}.json"
        path.write_text( json.dumps( { k: v for k, v in json.loads( path.read_text() ).items() if k not in ( "exclude_id", "tie" ) } ) )
        out = sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-15" )
        assert out[ "audited" ] == 1 and ( out[ "receipts" ][ 0 ][ "exclude_id" ], out[ "receipts" ][ 0 ][ "tie" ] ) == ( None, None )
        stored = tmp_path / "receipts" / f"shadow-{out[ 'receipts' ][ 0 ][ 'id' ]}.json"
        stored.write_text( json.dumps( { k: v for k, v in out[ "receipts" ][ 0 ].items() if k not in ( "exclude_id", "tie" ) } ) )
        assert ( sa.load_receipts( tmp_path )[ 0 ][ "exclude_id" ], sa.load_receipts( tmp_path )[ 0 ][ "tie" ] ) == ( None, None )

    @pytest.mark.parametrize( "field, value", [ ( "exclude_id", 5 ), ( "tie", "guess" ) ] )
    def test_an_exclude_id_that_is_not_text_or_a_tie_that_is_unknown_makes_the_item_corrupt( self, tmp_path, field, value ):
        key  = sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14" )
        path = tmp_path / "shadow-pending" / f"{key}.json"
        path.write_text( json.dumps( { **json.loads( path.read_text() ), field: value } ) )
        assert sa.run_pending( tmp_path, lambda need: sweep_of( "NEW" ), "2026-10-15" )[ "corrupt" ] == 1

    def test_an_excluded_id_gives_the_item_and_its_receipt_ids_of_their_own( self, tmp_path ):
        plain, excl = sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "d" ), sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "d", exclude_id="x" )
        assert plain != excl and len( list( ( tmp_path / "shadow-pending" ).glob( "*.json" ) ) ) == 2
        out = sa.run_pending( tmp_path, lambda need, **extra: sweep_of( "NEW" ), "2026-10-15" )
        assert out[ "audited" ] == 2 and len( { r[ "id" ] for r in out[ "receipts" ] } ) == 2

    def test_a_damaged_receipt_of_the_excluded_sweep_fails_that_item_before_any_sweep( self, tmp_path ):
        sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "d", exclude_id="x" )
        held = tmp_path / "receipts" / f"shadow-{sa._receipt_id( sa.need_hash( 'n1' ), GEN, INDEX, 'x' )}.json"
        held.parent.mkdir()
        held.write_text( "{" )
        out = sa.run_pending( tmp_path, lambda need, **extra: pytest.fail( "no sweep" ), "2026-10-15" )
        assert out[ "failed" ] == 1

    def test_a_known_miss_enqueue_for_a_lookup_already_pending_raises_its_marker_and_keeps_its_attempts( self, tmp_path ):
        key = sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14" )
        sa.run_pending( tmp_path, lambda need: ( _ for _ in () ).throw( TimeoutError( "x" ) ), "2026-10-15" )
        assert sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-16", known_miss=True, tie="ruling" ) == key
        held = self.pending( tmp_path )[ key ]
        assert ( held[ "known_miss" ], held[ "tie" ], held[ "attempts" ], held[ "queued_on" ] ) == ( True, "ruling", 1, "2026-10-14" )
        assert list( ( tmp_path / "shadow-pending" ).glob( ".tmp-*" ) ) == []

    def test_a_plain_enqueue_never_lowers_a_known_miss_item_and_a_second_known_miss_changes_nothing( self, tmp_path ):
        key = sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14", known_miss=True, tie="ruling" )
        before = ( tmp_path / "shadow-pending" / f"{key}.json" ).read_text()
        sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14" )
        sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14", known_miss=True, tie="heuristic" )
        assert ( tmp_path / "shadow-pending" / f"{key}.json" ).read_text() == before

    @pytest.mark.parametrize( "text", [ "{", json.dumps( [ 1 ] ) ] )
    def test_a_pending_file_that_is_not_an_item_is_left_alone_by_a_known_miss_enqueue( self, tmp_path, text ):
        key  = sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14" )
        path = tmp_path / "shadow-pending" / f"{key}.json"
        path.write_text( text )
        sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14", known_miss=True )
        assert path.read_text() == text

    def test_the_item_a_known_miss_enqueue_raised_drains_before_an_older_random_one( self, tmp_path ):
        sa.enqueue_pending( tmp_path, "older", "py", GEN, INDEX, LIVE, "2026-10-01" )
        sa.enqueue_pending( tmp_path, "later", "py", GEN, INDEX, LIVE, "2026-10-14" )
        sa.enqueue_pending( tmp_path, "later", "py", GEN, INDEX, LIVE, "2026-10-14", known_miss=True, tie="heuristic" )
        seen = []
        sa.run_pending( tmp_path, lambda need: seen.append( need ) or sweep_of( "NEW" ), "2026-10-15", limit=1 )
        assert seen == [ "later" ]

    def test_a_plain_enqueue_over_a_pending_random_item_leaves_it_random( self, tmp_path ):
        key = sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14", tie=None )
        sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-15" )
        assert self.pending( tmp_path )[ key ][ "known_miss" ] is False

    def test_the_id_with_no_excluded_id_is_pinned_to_the_value_receipts_already_stored_carry( self, tmp_path ):
        old = "5f0495f826ec004a"                       # sha256 of need hash, generation and index sha as the first receipts were named
        assert sa._receipt_id( sa.need_hash( "n1" ), GEN, INDEX ) == old
        assert receipt_for( "n1", "NEW", [] )[ "id" ] == old
        assert sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14" ) == old
        assert sa._receipt_id( sa.need_hash( "n1" ), GEN, INDEX, "x" ) != old

    @pytest.mark.parametrize( "detail", [ "INDEX_STALE: UNKNOWN_ENTRY was named in passing", "UNKNOWN_ENTRY_X", "unknown_entry", "" ] )
    def test_a_detail_that_only_mentions_unknown_entry_never_drops_an_item( self, tmp_path, detail ):
        key = sa.enqueue_pending( tmp_path, "n1", "py", GEN, INDEX, LIVE, "2026-10-14", known_miss=True )
        def refuse( need ): raise CandidateError( "AUDIT_SWEEP_REFUSED", detail )
        outs = [ sa.run_pending( tmp_path, refuse, "2026-10-15" ) for _ in range( sa.UNKNOWN_ENTRY_TRIES + 1 ) ]
        assert [ o[ "dropped" ] for o in outs ] == [ 0 ] * ( sa.UNKNOWN_ENTRY_TRIES + 1 ) and self.pending( tmp_path )[ key ][ "attempts" ] == sa.UNKNOWN_ENTRY_TRIES + 1

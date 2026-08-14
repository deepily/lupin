"""
Unit tests for the embedding regeneration core (row 5e848dd8).

Covers the pure decision layer at 100% — every branch that decides WHETHER a
vector is stale, whether a fresh one is usable, whether a pass may start, and
whether a swap is allowed. Nothing here opens a DB connection or an HTTP socket;
the live-IO functions carry ``# pragma: no cover`` for exactly that reason.

Created: 2026-08-02 (Cheech 🌿)
"""
import json

import pytest

from cosa.rest.db.embedding_regeneration import (
    DEFAULT_CHAR_BUDGET,
    MAX_CHAR_BUDGET,
    OFF_PEAK_END_HOUR,
    MIN_CHAR_BUDGET,
    AdaptiveBudget,
    EMBEDDING_DIM,
    LOCAL_NORM_CEILING,
    LOCAL_NORM_FLOOR,
    NORMALIZED_NORM_CEILING,
    REGEN_SPECS,
    checkpoint_path,
    classify_norm,
    is_excluded,
    is_off_peak,
    l2_norm,
    load_checkpoint,
    plan_batches,
    plan_batches_by_budget,
    qualify,
    remaining_ids,
    save_checkpoint,
    should_proceed,
    split_batch,
    summarize_verification,
    validate_fresh_vector,
)


def _vector_with_norm( norm, dim=EMBEDDING_DIM ):
    """Build a dim-length vector whose L2 norm is exactly `norm`."""
    value = ( norm ** 2 / dim ) ** 0.5
    return [ value ] * dim


# --------------------------------------------------------------------------- #
# classify_norm — the model fingerprint
# --------------------------------------------------------------------------- #
class TestClassifyNorm:

    @pytest.mark.parametrize( "norm", [ 0.0, 0.5, 1.0, NORMALIZED_NORM_CEILING ] )
    def test_normalized_reads_as_normalized( self, norm ):
        assert classify_norm( norm ) == "normalized"

    @pytest.mark.parametrize( "norm", [ LOCAL_NORM_FLOOR, 17.0, 19.809, 23.8, LOCAL_NORM_CEILING ] )
    def test_local_band_reads_as_current( self, norm ):
        assert classify_norm( norm ) == "current"

    @pytest.mark.parametrize( "norm", [ 1.011, 3.0, 4.99, LOCAL_NORM_CEILING + 0.1, 1000.0 ] )
    def test_between_and_beyond_reads_as_suspect( self, norm ):
        assert classify_norm( norm ) == "suspect"

    def test_the_live_clamp_fixture_norm_is_suspect_not_current( self ):
        # prediction_decisions `clamp-001` carries norm exactly 3.0 on purpose.
        assert classify_norm( 3.0 ) == "suspect"

    def test_norm_does_not_identify_a_model( self ):
        # The whole reason selection is by source text and not by norm: two
        # different models can land in the same band, so "current" means only
        # "not normalized and not absurd" — never "produced by the model we
        # are standardizing on".
        assert classify_norm( 17.0 ) == classify_norm( 23.8 ) == "current"


class TestL2Norm:

    def test_empty_vector_is_zero( self ):
        assert l2_norm( [] ) == 0.0

    def test_unit_vector( self ):
        assert l2_norm( [ 1.0, 0.0, 0.0 ] ) == pytest.approx( 1.0 )

    def test_known_triple( self ):
        assert l2_norm( [ 3.0, 4.0 ] ) == pytest.approx( 5.0 )

    def test_accepts_integers( self ):
        assert l2_norm( [ 3, 4 ] ) == pytest.approx( 5.0 )


# --------------------------------------------------------------------------- #
# validate_fresh_vector — the gate every regenerated vector must pass
# --------------------------------------------------------------------------- #
class TestValidateFreshVector:

    def test_good_vector_passes( self ):
        assert validate_fresh_vector( _vector_with_norm( 19.809 ) ) is None

    def test_none_is_rejected( self ):
        assert "returned nothing" in validate_fresh_vector( None )

    def test_wrong_dimension_is_rejected( self ):
        reason = validate_fresh_vector( _vector_with_norm( 19.0, dim=512 ) )
        assert "wrong dimension 512" in reason
        assert str( EMBEDDING_DIM ) in reason

    def test_nan_is_rejected( self ):
        vector = _vector_with_norm( 19.0 )
        vector[ 0 ] = float( "nan" )
        assert "non-finite" in validate_fresh_vector( vector )

    @pytest.mark.parametrize( "bad", [ float( "inf" ), float( "-inf" ) ] )
    def test_infinities_are_rejected( self, bad ):
        vector = _vector_with_norm( 19.0 )
        vector[ 5 ] = bad
        assert "non-finite" in validate_fresh_vector( vector )

    def test_normalized_output_is_rejected_as_model_drift( self ):
        # If the embedder starts returning unit vectors we are back where we
        # started — the run must stop, not write them.
        reason = validate_fresh_vector( _vector_with_norm( 1.0 ) )
        assert "may have changed again" in reason
        assert "normalized" in reason

    def test_out_of_band_norm_is_rejected( self ):
        reason = validate_fresh_vector( _vector_with_norm( 500.0 ) )
        assert "suspect" in reason

    def test_custom_expected_dim_is_honored( self ):
        assert validate_fresh_vector( _vector_with_norm( 19.0, dim=16 ), expected_dim=16 ) is None


# --------------------------------------------------------------------------- #
# Exclusions, batching, prefixes
# --------------------------------------------------------------------------- #
class TestIsExcluded:

    def test_clamp_fixture_is_excluded( self ):
        assert is_excluded( "prediction_decisions", "clamp-001" ) is True

    def test_ordinary_id_is_not_excluded( self ):
        assert is_excluded( "prediction_decisions", "some-real-id" ) is False

    def test_table_with_no_exclusions( self ):
        assert is_excluded( "input_and_output", 12345 ) is False

    def test_id_is_compared_as_string( self ):
        assert is_excluded( "input_and_output", 1 ) is False


class TestPlanBatches:

    def test_empty_input_yields_no_batches( self ):
        assert plan_batches( [], 10 ) == []

    def test_exact_multiple( self ):
        assert plan_batches( [ 1, 2, 3, 4 ], 2 ) == [ [ 1, 2 ], [ 3, 4 ] ]

    def test_ragged_tail_is_kept( self ):
        assert plan_batches( [ 1, 2, 3 ], 2 ) == [ [ 1, 2 ], [ 3 ] ]

    def test_batch_larger_than_input( self ):
        assert plan_batches( [ 1, 2 ], 100 ) == [ [ 1, 2 ] ]

    def test_every_id_appears_exactly_once( self ):
        ids = list( range( 1000 ) )
        flattened = [ row_id for batch in plan_batches( ids, 256 ) for row_id in batch ]
        assert flattened == ids

    @pytest.mark.parametrize( "bad", [ 0, -1 ] )
    def test_non_positive_batch_size_raises( self, bad ):
        with pytest.raises( ValueError, match="must be positive" ):
            plan_batches( [ 1 ], bad )


class TestQualify:

    def test_empty_prefix_returns_bare_table( self ):
        assert qualify( "input_and_output" ) == "input_and_output"

    def test_schema_prefix_is_applied( self ):
        assert qualify( "input_and_output", "regen_probe." ) == "regen_probe.input_and_output"

    def test_prefix_without_dot_raises( self ):
        with pytest.raises( ValueError, match="must end in" ):
            qualify( "input_and_output", "regen_probe" )


# --------------------------------------------------------------------------- #
# should_proceed — the busy/clock gate
# --------------------------------------------------------------------------- #
class TestIsOffPeak:

    @pytest.mark.parametrize( "hour", [ 0, 3, 8 ] )
    def test_inside_window( self, hour ):
        assert is_off_peak( hour ) is True

    @pytest.mark.parametrize( "hour", [ 14, 21, 23 ] )
    def test_outside_window( self, hour ):
        assert is_off_peak( hour ) is False

    @pytest.mark.parametrize( "hour", [ 9, 10 ] )
    def test_the_morning_hours_rick_widened_the_window_for( self, hour ):
        # Rick, 2026-08-13: the run starts after breakfast, not before 9am. These two
        # hours used to be REFUSED and are the whole reason OFF_PEAK_END_HOUR moved.
        assert is_off_peak( hour ) is True

    def test_the_window_still_closes( self, ):
        # Widening is not removing. 11:00 is the first hour outside, and a window that
        # accepted every hour would make the check decorative.
        assert is_off_peak( OFF_PEAK_END_HOUR ) is False

    def test_end_hour_is_a_parameter_not_a_hardcode( self ):
        # The boundary travels with the argument, so a caller can tighten it without
        # editing the module.
        assert is_off_peak( 5, end_hour=4 ) is False
        assert is_off_peak( 3, end_hour=4 ) is True


class TestShouldProceed:

    def test_idle_and_off_peak_proceeds( self ):
        assert should_proceed( busy=False, hour_edt=2 ) is None

    def test_busy_blocks( self ):
        assert "busy" in should_proceed( busy=True, hour_edt=2 )

    def test_busy_blocks_even_with_force( self ):
        # force is a clock override, never a queue override.
        assert "busy" in should_proceed( busy=True, hour_edt=2, force=True )

    def test_unknown_busy_state_blocks( self ):
        assert "refusing to guess" in should_proceed( busy=None, hour_edt=2 )

    def test_unknown_busy_state_blocks_even_with_force( self ):
        assert "refusing to guess" in should_proceed( busy=None, hour_edt=2, force=True )

    def test_on_peak_blocks_without_force( self ):
        reason = should_proceed( busy=False, hour_edt=21 )
        assert "off-peak" in reason and "--force" in reason

    def test_on_peak_proceeds_with_force( self ):
        assert should_proceed( busy=False, hour_edt=21, force=True ) is None

    def test_clock_check_is_skipped_when_hour_is_none( self ):
        assert should_proceed( busy=False, hour_edt=None ) is None


# --------------------------------------------------------------------------- #
# summarize_verification — the swap verdict
# --------------------------------------------------------------------------- #
class TestSummarizeVerification:

    def test_clean_run_is_ok( self ):
        report = summarize_verification( total=100, filled=100, bad_norms=0, dim_mismatches=0 )
        assert report[ "ok" ] is True
        assert report[ "reasons" ] == []

    def test_nothing_stale_nothing_filled_is_ok( self ):
        assert summarize_verification( 0, 0, 0, 0 )[ "ok" ] is True

    def test_unfilled_rows_block( self ):
        report = summarize_verification( total=100, filled=97, bad_norms=0, dim_mismatches=0 )
        assert report[ "ok" ] is False
        assert "3 of 100" in report[ "reasons" ][ 0 ]

    def test_a_partial_run_cannot_verify_clean( self ):
        # The scope is the WHOLE table now. If verify's denominator ever narrows
        # to the norm-1.0 subset again, a run that skipped the current-era rows
        # would report ok — which is the defect this whole exercise is about.
        report = summarize_verification( total=288_777, filled=79_318, bad_norms=0, dim_mismatches=0 )
        assert report[ "ok" ] is False

    def test_bad_norms_block( self ):
        report = summarize_verification( total=100, filled=100, bad_norms=2, dim_mismatches=0 )
        assert report[ "ok" ] is False
        assert "out-of-band norm" in report[ "reasons" ][ 0 ]

    def test_dim_mismatches_block( self ):
        report = summarize_verification( total=100, filled=100, bad_norms=0, dim_mismatches=1 )
        assert report[ "ok" ] is False
        assert "wrong dimension" in report[ "reasons" ][ 0 ]

    def test_all_three_failures_are_reported_together( self ):
        report = summarize_verification( total=100, filled=90, bad_norms=2, dim_mismatches=3 )
        assert len( report[ "reasons" ] ) == 3

    def test_counts_are_echoed_back( self ):
        report = summarize_verification( total=5, filled=4, bad_norms=1, dim_mismatches=0 )
        assert ( report[ "total" ], report[ "filled" ] ) == ( 5, 4 )
        assert ( report[ "bad_norms" ], report[ "dim_mismatches" ] ) == ( 1, 0 )


# --------------------------------------------------------------------------- #
# Checkpoint / resume
# --------------------------------------------------------------------------- #
class TestCheckpoint:

    def test_path_is_named_for_the_spec( self, tmp_path ):
        path = checkpoint_path( "io_input", str( tmp_path ) )
        assert path.endswith( "regen-checkpoint-io_input.json" )
        assert str( tmp_path ) in path

    def test_missing_checkpoint_reads_as_empty( self, tmp_path ):
        assert load_checkpoint( str( tmp_path / "nope.json" ) ) == { "done_ids": [] }

    def test_round_trip( self, tmp_path ):
        path = str( tmp_path / "cp.json" )
        save_checkpoint( path, [ 1, 2, 3 ] )
        assert load_checkpoint( path )[ "done_ids" ] == [ 1, 2, 3 ]

    def test_save_leaves_no_temp_file_behind( self, tmp_path ):
        path = str( tmp_path / "cp.json" )
        save_checkpoint( path, [ 1 ] )
        assert list( p.name for p in tmp_path.iterdir() ) == [ "cp.json" ]

    def test_checkpoint_missing_done_ids_key_is_healed( self, tmp_path ):
        path = tmp_path / "cp.json"
        path.write_text( json.dumps( { "note": "hand-edited" } ) )
        loaded = load_checkpoint( str( path ) )
        assert loaded[ "done_ids" ] == []
        assert loaded[ "note" ] == "hand-edited"

    def test_corrupt_checkpoint_raises_rather_than_restarting_from_zero( self, tmp_path ):
        path = tmp_path / "cp.json"
        path.write_text( "{ this is not json" )
        with pytest.raises( ValueError, match="corrupt" ):
            load_checkpoint( str( path ) )

    def test_overwrite_replaces_prior_contents( self, tmp_path ):
        path = str( tmp_path / "cp.json" )
        save_checkpoint( path, [ 1, 2, 3 ] )
        save_checkpoint( path, [ 9 ] )
        assert load_checkpoint( path )[ "done_ids" ] == [ 9 ]


class TestRemainingIds:

    def test_nothing_done_returns_everything( self ):
        assert remaining_ids( [ 1, 2, 3 ], [] ) == [ 1, 2, 3 ]

    def test_done_ids_are_subtracted( self ):
        assert remaining_ids( [ 1, 2, 3, 4 ], [ 2, 4 ] ) == [ 1, 3 ]

    def test_order_is_preserved( self ):
        assert remaining_ids( [ 5, 1, 9, 3 ], [ 1 ] ) == [ 5, 9, 3 ]

    def test_all_done_returns_empty( self ):
        assert remaining_ids( [ 1, 2 ], [ 1, 2 ] ) == []

    def test_string_and_int_ids_compare_equal( self ):
        # The checkpoint round-trips through JSON, so an int id can come back
        # as a string; resume must not re-do work because of that.
        assert remaining_ids( [ 1, 2 ], [ "1" ] ) == [ 2 ]

    def test_done_ids_not_in_the_work_list_are_ignored( self ):
        assert remaining_ids( [ 1, 2 ], [ 99 ] ) == [ 1, 2 ]


# --------------------------------------------------------------------------- #
# Spec registry sanity — a shadow column must never collide with a live one
# --------------------------------------------------------------------------- #
class TestRegenSpecs:

    def test_shadow_columns_are_distinct_from_live_columns( self ):
        for spec in REGEN_SPECS:
            assert spec.shadow_column != spec.vector_column

    def test_shadow_column_names_are_unique( self ):
        names = [ spec.shadow_column for spec in REGEN_SPECS ]
        assert len( names ) == len( set( names ) )

    def test_labels_are_unique( self ):
        labels = [ spec.label for spec in REGEN_SPECS ]
        assert len( labels ) == len( set( labels ) )

    def test_every_spec_names_a_text_source( self ):
        for spec in REGEN_SPECS:
            assert spec.text_column and spec.content_type in ( "prose", "code" )


# --------------------------------------------------------------------------- #
# Budget batching + split-on-failure — the CUDA-OOM fix.
#
# Measured 2026-08-02: 256 typical texts (17,850 chars) embed in 0.42s, while
# EIGHT of the longest texts (~100k chars) return HTTP 500 with
# torch.OutOfMemoryError on a GPU already ~99% held by two other processes.
# Cost tracks total text, not row count.
# --------------------------------------------------------------------------- #
class TestPlanBatchesByBudget:

    @staticmethod
    def _size( item ):
        return item

    def test_empty_input( self ):
        assert plan_batches_by_budget( [], self._size ) == []

    def test_everything_fits_in_one_batch( self ):
        assert plan_batches_by_budget( [ 10, 20, 30 ], self._size, char_budget=100 ) == [ [ 10, 20, 30 ] ]

    def test_splits_when_the_budget_is_exceeded( self ):
        assert plan_batches_by_budget( [ 60, 60, 60 ], self._size, char_budget=100 ) == [ [ 60 ], [ 60 ], [ 60 ] ]

    def test_packs_up_to_the_budget( self ):
        assert plan_batches_by_budget( [ 40, 40, 40 ], self._size, char_budget=100 ) == [ [ 40, 40 ], [ 40 ] ]

    def test_count_ceiling_still_applies_under_budget( self ):
        # Tiny texts must not produce a 10,000-row batch just because they fit.
        batches = plan_batches_by_budget( [ 1 ] * 10, self._size, char_budget=10_000, max_count=4 )
        assert [ len( b ) for b in batches ] == [ 4, 4, 2 ]

    def test_an_oversized_single_item_is_isolated_not_dropped( self ):
        # The whole-table scope means a 14,418-char row exists and must still be
        # attempted — alone, where it succeeded in measurement.
        batches = plan_batches_by_budget( [ 10, 500, 10 ], self._size, char_budget=100 )
        assert [ 500 ] in batches
        assert sum( len( b ) for b in batches ) == 3

    def test_every_item_appears_exactly_once_and_in_order( self ):
        items   = list( range( 1, 200 ) )
        batches = plan_batches_by_budget( items, self._size, char_budget=500, max_count=7 )
        assert [ x for b in batches for x in b ] == items

    def test_no_batch_exceeds_the_budget_unless_it_is_a_lone_oversized_item( self ):
        items   = [ 3, 900, 4, 5, 6 ]
        for batch in plan_batches_by_budget( items, self._size, char_budget=10 ):
            assert sum( batch ) <= 10 or len( batch ) == 1

    def test_size_of_is_applied_to_the_item( self ):
        pairs   = [ ( "a", "xxxxx" ), ( "b", "yyyyy" ) ]
        batches = plan_batches_by_budget( pairs, lambda p: len( p[ 1 ] ), char_budget=6 )
        assert batches == [ [ ( "a", "xxxxx" ) ], [ ( "b", "yyyyy" ) ] ]

    def test_the_real_default_budget_admits_a_measured_typical_batch( self ):
        # 256 typical texts totalled 17,850 chars live and embedded fine.
        assert len( plan_batches_by_budget( [ 70 ] * 256, self._size,
                                            char_budget=DEFAULT_CHAR_BUDGET, max_count=256 ) ) == 1

    def test_the_real_default_budget_rejects_the_measured_failing_batch( self ):
        # Eight of the longest texts (~100k chars) OOM'd. They must not co-batch.
        batches = plan_batches_by_budget( [ 12_500 ] * 8, self._size,
                                          char_budget=DEFAULT_CHAR_BUDGET, max_count=256 )
        assert len( batches ) > 1
        for batch in batches:
            assert sum( batch ) <= DEFAULT_CHAR_BUDGET

    @pytest.mark.parametrize( "bad", [ 0, -1 ] )
    def test_non_positive_budget_raises( self, bad ):
        with pytest.raises( ValueError, match="char_budget must be positive" ):
            plan_batches_by_budget( [ 1 ], self._size, char_budget=bad )

    @pytest.mark.parametrize( "bad", [ 0, -1 ] )
    def test_non_positive_max_count_raises( self, bad ):
        with pytest.raises( ValueError, match="max_count must be positive" ):
            plan_batches_by_budget( [ 1 ], self._size, max_count=bad )


class TestSplitBatch:

    def test_empty_cannot_split( self ):
        assert split_batch( [] ) == []

    def test_single_item_cannot_split( self ):
        # The recursion's floor: one row that fails alone is a REAL failure, not
        # a batch-size problem, and must not be retried forever.
        assert split_batch( [ "only" ] ) == []

    def test_even_split( self ):
        assert split_batch( [ 1, 2, 3, 4 ] ) == [ [ 1, 2 ], [ 3, 4 ] ]

    def test_odd_split_keeps_every_item( self ):
        halves = split_batch( [ 1, 2, 3 ] )
        assert [ x for h in halves for x in h ] == [ 1, 2, 3 ]
        assert all( halves )

    def test_halves_are_strictly_smaller_so_recursion_terminates( self ):
        batch = list( range( 9 ) )
        for half in split_batch( batch ):
            assert 0 < len( half ) < len( batch )

    def test_repeated_splitting_reaches_single_items( self ):
        work, singles = [ list( range( 8 ) ) ], 0
        while work:
            batch  = work.pop()
            halves = split_batch( batch )
            if not halves: singles += 1
            else: work.extend( halves )
        assert singles == 8


# --------------------------------------------------------------------------- #
# AdaptiveBudget — the answer to "we can unload the other models first".
#
# DEFAULT_CHAR_BUDGET was calibrated on a GPU with 23 MiB free, because a
# 16.7 GiB vLLM was sharing the card. That number describes a machine that will
# not exist at run time. Rather than scale it by an invented chars-per-MiB rate,
# the budget grows on success and halves on refusal, so the run finds the real
# ceiling on whatever hardware it meets.
# --------------------------------------------------------------------------- #
class TestAdaptiveBudget:

    def test_starts_where_told( self ):
        assert AdaptiveBudget( start=40_000 ).current() == 40_000

    def test_start_is_clamped_into_range( self ):
        assert AdaptiveBudget( start=1 ).current() == MIN_CHAR_BUDGET
        assert AdaptiveBudget( start=10 ** 12 ).current() == MAX_CHAR_BUDGET

    def test_success_widens( self ):
        b = AdaptiveBudget( start=10_000, growth=1.5 )
        assert b.record_success() == 15_000

    def test_failure_halves( self ):
        b = AdaptiveBudget( start=40_000 )
        assert b.record_failure() == 20_000

    def test_growth_stops_at_the_ceiling( self ):
        b = AdaptiveBudget( start=MAX_CHAR_BUDGET, growth=2.0 )
        assert b.record_success() == MAX_CHAR_BUDGET

    def test_shrink_stops_at_the_floor( self ):
        b = AdaptiveBudget( start=MIN_CHAR_BUDGET )
        assert b.record_failure() == MIN_CHAR_BUDGET

    def test_repeated_failure_converges_on_the_floor_not_zero( self ):
        # A budget that halved to 0 would make every batch empty and the run
        # would spin forever making no progress.
        b = AdaptiveBudget( start=MAX_CHAR_BUDGET )
        for _ in range( 200 ):
            b.record_failure()
        assert b.current() == MIN_CHAR_BUDGET

    def test_it_climbs_to_the_ceiling_on_a_cleared_gpu( self ):
        # The behaviour Rick asked for: unload the other models and the run
        # should USE the headroom without anyone re-tuning a constant.
        b = AdaptiveBudget( start=DEFAULT_CHAR_BUDGET )
        for _ in range( 100 ):
            b.record_success()
        assert b.current() == MAX_CHAR_BUDGET

    def test_it_settles_back_down_on_a_crowded_gpu( self ):
        # And the converse: if the card is still busy, growth is undone by the
        # refusals it causes, so it does not thrash upward forever.
        b = AdaptiveBudget( start=DEFAULT_CHAR_BUDGET )
        for _ in range( 40 ):
            b.record_success(); b.record_failure(); b.record_failure()
        assert b.current() == MIN_CHAR_BUDGET

    @pytest.mark.parametrize( "floor,ceiling", [ ( 0, 100 ), ( -5, 100 ), ( 500, 100 ) ] )
    def test_inconsistent_bounds_raise( self, floor, ceiling ):
        with pytest.raises( ValueError, match="floor" ):
            AdaptiveBudget( start=50, floor=floor, ceiling=ceiling )

    @pytest.mark.parametrize( "growth", [ 1.0, 0.5, 0.0 ] )
    def test_non_growing_growth_raises( self, growth ):
        # growth <= 1.0 would mean success never widens anything, which silently
        # turns the adaptive budget back into the hardcoded constant it replaced.
        with pytest.raises( ValueError, match="growth" ):
            AdaptiveBudget( start=50_000, growth=growth )

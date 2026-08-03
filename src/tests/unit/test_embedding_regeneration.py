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
    qualify,
    remaining_ids,
    save_checkpoint,
    should_proceed,
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

    @pytest.mark.parametrize( "hour", [ 9, 14, 21, 23 ] )
    def test_outside_window( self, hour ):
        assert is_off_peak( hour ) is False


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

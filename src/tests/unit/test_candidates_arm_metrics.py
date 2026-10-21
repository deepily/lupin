"""
Unit tests for the offline comparison's measures.

Each measure is worked by hand on a case small enough to check in the head.
The positive control is a shortlist that holds the whole reference, which must give recall 1.0.
"""
import pytest

from cosa.repo.symindex import verdict as vd
from cosa.repo.symindex.candidates import arm_metrics as am


def probs( reuse, extend, unrelated ):
    """A valid answer."""
    return { "reuse": reuse, "extend": extend, "unrelated": unrelated }


REUSE   = probs( 0.95, 0.03, 0.02 )
NEWISH  = probs( 0.02, 0.03, 0.95 )


class TestRecall:
    """Share of the reference that a shortlist holds."""

    def test_positive_control_is_one( self ):
        assert am.recall_at_k( [ "a", "b", "c", "d" ], [ "b", "c" ] ) == 1.0

    def test_half( self ):
        assert am.recall_at_k( [ "a", "b" ], [ "b", "z" ] ) == 0.5

    def test_none_held_is_zero( self ):
        assert am.recall_at_k( [ "a" ], [ "x", "y" ] ) == 0.0

    def test_repeats_in_the_reference_count_once( self ):
        assert am.recall_at_k( [ "a" ], [ "a", "a", "z" ] ) == 0.5

    def test_empty_reference_is_an_error( self ):
        with pytest.raises( ValueError ):
            am.recall_at_k( [ "a" ], [] )


class TestT1Table:
    """Mean recall per arm and K."""

    def test_mean_and_per_need( self ):
        shortlists = { "C0": { 32: { "n1": [ "a" ], "n2": [ "a", "b" ] } }, "B1": { 32: { "n1": [ "a", "b" ], "n2": [ "a", "b" ] } } }
        references = { "n1": [ "a", "b" ], "n2": [ "a", "b" ] }
        table      = am.t1_table( shortlists, references )
        assert table[ "C0" ][ 32 ][ "per_need" ] == { "n1": 0.5, "n2": 1.0 }
        assert table[ "C0" ][ 32 ][ "mean" ] == 0.75
        assert table[ "C0" ][ 32 ][ "mean_size" ] == 1.5
        assert table[ "B1" ][ 32 ][ "mean_size" ] == 2.0
        assert table[ "B1" ][ 32 ][ "mean" ] == 1.0

    def test_a_need_with_no_reference_is_left_out( self ):
        table = am.t1_table( { "C0": { 64: { "n1": [ "a" ], "n2": [ "a" ] } } }, { "n1": [ "a" ], "n2": [] } )
        assert table[ "C0" ][ 64 ][ "per_need" ] == { "n1": 1.0 }

    def test_no_measured_need_gives_no_mean( self ):
        table = am.t1_table( { "C0": { 64: { "n2": [ "a" ] } } }, { "n2": [] } )
        assert table[ "C0" ][ 64 ][ "mean" ] is None
        assert table[ "C0" ][ 64 ][ "mean_size" ] == 1.0

    def test_reference_ids_come_from_a_decision( self ):
        decision = vd.decide( [ { "id": "b", "probabilities": REUSE }, { "id": "a", "probabilities": REUSE },
                                { "id": "c", "probabilities": NEWISH } ], [ "a", "b", "c" ], [], set() )
        assert am.reference_ids( decision ) == [ "a", "b" ]


class TestTwinRank:
    """Where a twin lands."""

    def test_position_is_one_based( self ):
        assert am.twin_rank( [ "x", "y", "z" ], "x" ) == 1
        assert am.twin_rank( [ "x", "y", "z" ], "z" ) == 3

    def test_absent_twin_is_none( self ):
        assert am.twin_rank( [ "x" ], "q" ) is None

    def test_summary_by_language( self ):
        out = am.t3_summary( { "py": [ 1, 4, 60, None ], "ts": [ 200, 130 ], "js": [ None ] } )
        assert out[ "py" ] == { "members": 4, "unranked": 1, "median": 4, "median_all": 32.0, "within": { 10: 2, 50: 2, 128: 3 } }
        assert out[ "ts" ] == { "members": 2, "unranked": 0, "median": 165.0, "median_all": 165.0, "within": { 10: 0, 50: 0, 128: 0 } }
        assert out[ "js" ][ "median" ] is None
        assert out[ "js" ][ "unranked" ] == 1
        assert out[ "js" ][ "median_all" ] == am.UNRANKED_RANK

    def test_arm_that_loses_most_twins_does_not_win_the_vector_rule( self ):
        out = am.t3_summary( { "x": [ 1, None, None, None ], "y": [ 20, 20, 20, 20 ] } )
        assert out[ "x" ][ "median" ] == 1
        assert out[ "x" ][ "median_all" ] == am.UNRANKED_RANK
        one = { "recall_128": 0.5, "median_rank": out[ "y" ][ "median_all" ] }
        two = { "recall_128": 0.4, "median_rank": out[ "x" ][ "median_all" ] }
        assert am.choose_vectors( one, two ) == "B1"


class TestT2Replay:
    """Verdicts replayed from cached answers."""

    ANSWERS = { ( "n1", 1 ): { "a": REUSE, "b": NEWISH }, ( "n1", 2 ): { "a": REUSE, "b": NEWISH },
                ( "n2", 1 ): { "a": NEWISH, "b": REUSE }, ( "n2", 2 ): { "a": NEWISH, "b": NEWISH } }

    def test_real_verdict_table( self ):
        out = am.t2_replay( { "n1": [ "a" ], "n2": [ "b" ] }, self.ANSWERS )
        assert out[ "verdicts" ] == { "n1": [ "REUSE", "REUSE" ], "n2": [ "REUSE", "NEW" ] }
        assert out[ "flip_rate" ] == 0.5
        assert out[ "needs" ] == 2

    def test_agreement_against_the_full_sweep( self ):
        # full sweep: n1 REUSE REUSE, n2 REUSE NEW. A shortlist of only b flips n1 to NEW in both repeats.
        out = am.t2_replay( { "n1": [ "b" ], "n2": [ "b" ] }, self.ANSWERS )
        assert out[ "verdicts" ] == { "n1": [ "NEW", "NEW" ], "n2": [ "REUSE", "NEW" ] }
        assert out[ "agreement" ] == 0.5

    def test_uncached_answers_are_counted_not_guessed( self ):
        out = am.t2_replay( { "n1": [ "a", "zz" ] }, self.ANSWERS )
        assert out[ "uncached" ] == 2
        assert out[ "verdicts" ][ "n1" ] == [ "REUSE", "REUSE" ]

    def test_a_fake_decider_reaches_the_table( self ):
        out = am.t2_replay( { "n1": [ "a", "b" ] }, self.ANSWERS, decide_fn=lambda rows, ids: str( len( rows ) ) )
        assert out[ "verdicts" ] == { "n1": [ "2", "2" ] }
        assert out[ "agreement" ] == 1.0

    def test_no_needs_gives_no_rates( self ):
        out = am.t2_replay( {}, {} )
        assert out[ "flip_rate" ] is None and out[ "agreement" ] is None and out[ "needs" ] == 0

    def test_provides_shaped_answers_are_replayed_by_the_new_question_table( self ):
        answers = { ( "n1", 1 ): { "a": { "provides": 0.99, "coverage": { "0": 0.0, "1": 0.0, "2": 0.0, "3": 1.0 } } } }
        out = am.t2_replay( { "n1": [ "a" ] }, answers )
        assert out[ "verdicts" ] == { "n1": [ "REUSE" ] }
        assert out[ "agreement" ] == 1.0

    def test_decide_with_ids_returns_the_verdict_string( self ):
        assert am.decide_with_ids( [ { "id": "a", "probabilities": REUSE } ], [ "a" ] ) == "REUSE"


class TestChooseVectors:
    """Two vectors only when they earn it."""

    def test_better_recall_keeps_two( self ):
        assert am.choose_vectors( { "recall_128": 0.80, "median_rank": 10 }, { "recall_128": 0.85, "median_rank": 10 } ) == "B2"

    def test_better_rank_keeps_two( self ):
        assert am.choose_vectors( { "recall_128": 0.80, "median_rank": 10 }, { "recall_128": 0.80, "median_rank": 7 } ) == "B2"

    def test_tie_keeps_one( self ):
        assert am.choose_vectors( { "recall_128": 0.80, "median_rank": 10 }, { "recall_128": 0.80, "median_rank": 10 } ) == "B1"

    def test_worse_keeps_one( self ):
        assert am.choose_vectors( { "recall_128": 0.80, "median_rank": 10 }, { "recall_128": 0.70, "median_rank": 12 } ) == "B1"

    def test_missing_figure_never_wins( self ):
        assert am.choose_vectors( { "recall_128": None, "median_rank": None }, { "recall_128": 0.9, "median_rank": 1 } ) == "B1"

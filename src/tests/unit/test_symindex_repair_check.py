"""
Unit tests for symindex.repair_check, run over cached answers: no Jev call is made.
"""
import pytest

from cosa.repo.symindex import repair_check as rc


class Cached:
    """
    A replay with prepared shortlists and index shas, counting its calls.

    With sha None every call reports its own sha, so a rewrite always reads as a changed input.
    """
    def __init__( self, answers, sha=None ):
        self.answers, self.calls, self.sha = list( answers ), 0, sha

    def __call__( self, receipt_id ):
        self.calls += 1
        answer = self.answers.pop( 0 )
        if isinstance( answer, Exception ): raise answer
        return rc.Replayed( answer, f"s{self.calls}" if self.sha is None else self.sha )


class Rewrite:
    def __init__( self ): self.calls = 0
    def __call__( self ): self.calls += 1


ON, OFF = [ "a", "target", "b" ], [ "a", "b" ]


def test_the_default_run_count_is_five():
    assert rc.R == 5


def test_repaired_when_absent_five_of_five_before_and_present_five_of_five_after():
    replay, rewrite = Cached( [ OFF ] * 5 + [ ON ] * 5 ), Rewrite()
    got = rc.run_repair_check( replay, rewrite, "r-1", "target" )
    assert got == rc.RepairResult( rc.REPAIRED, 0, 5, 5 ) and replay.calls == 10 and rewrite.calls == 1


def test_one_flip_after_the_rewrite_is_flippy_not_repaired():
    got = rc.run_repair_check( Cached( [ OFF ] * 5 + [ ON ] * 4 + [ OFF ] ), Rewrite(), "r-1", "target" )
    assert got == rc.RepairResult( rc.FLIPPY_AFTER, 0, 4, 5 )


def test_never_present_after_the_rewrite_is_not_repaired():
    got = rc.run_repair_check( Cached( [ OFF ] * 10 ), Rewrite(), "r-1", "target" )
    assert got == rc.RepairResult( rc.NOT_REPAIRED, 0, 0, 5 )


def test_present_before_every_time_means_no_miss_was_reproduced_and_nothing_is_rewritten():
    rewrite = Rewrite()
    got = rc.run_repair_check( Cached( [ ON ] * 5 ), rewrite, "r-1", "target" )
    assert got == rc.RepairResult( rc.ALREADY_MATCHED, 5, None, 5 ) and rewrite.calls == 0


def test_a_mixed_before_count_is_flippy_and_nothing_is_rewritten():
    rewrite = Rewrite()
    got = rc.run_repair_check( Cached( [ OFF, ON, OFF, OFF, OFF ] ), rewrite, "r-1", "target" )
    assert got == rc.RepairResult( rc.FLIPPY_BEFORE, 1, None, 5 ) and rewrite.calls == 0


def test_four_of_five_before_is_flippy_not_already_matched():
    got = rc.run_repair_check( Cached( [ ON ] * 4 + [ OFF ] ), Rewrite(), "r-1", "target" )
    assert got == rc.RepairResult( rc.FLIPPY_BEFORE, 4, None, 5 )


def test_a_failed_replay_before_is_call_failed_never_absent():
    rewrite = Rewrite()
    got = rc.run_repair_check( Cached( [ OFF, rc.ReplayFailed( "down" ) ] ), rewrite, "r-1", "target" )
    assert got == rc.RepairResult( rc.CALL_FAILED, None, None, 5 ) and rewrite.calls == 0


def test_a_failed_replay_after_keeps_the_before_count():
    got = rc.run_repair_check( Cached( [ OFF ] * 5 + [ ON, rc.ReplayFailed( "down" ) ] ), Rewrite(), "r-1", "target" )
    assert got == rc.RepairResult( rc.CALL_FAILED, 0, None, 5 )


def test_a_failed_first_replay_after_the_rewrite_is_call_failed_too():
    got = rc.run_repair_check( Cached( [ OFF ] * 5 + [ rc.ReplayFailed( "down" ) ] ), Rewrite(), "r-1", "target" )
    assert got == rc.RepairResult( rc.CALL_FAILED, 0, None, 5 )


def test_runs_is_configurable_and_the_receipt_id_reaches_the_replay():
    seen = []
    def replay( receipt_id ):
        seen.append( receipt_id )
        return rc.Replayed( ON if len( seen ) > 2 else OFF, f"s{len( seen )}" )
    got = rc.run_repair_check( replay, Rewrite(), "r-9", "target", runs=2 )
    assert got.verdict == rc.REPAIRED and seen == [ "r-9" ] * 4


@pytest.mark.parametrize( "bad", [ 0, -1, 2.5, "5", None, True ] )
def test_runs_must_be_a_positive_int( bad ):
    replay = Cached( [] )
    with pytest.raises( ValueError, match="positive int" ): rc.run_repair_check( replay, Rewrite(), "r", "s", runs=bad )
    assert replay.calls == 0


def test_an_error_that_is_not_replay_failed_propagates_and_nothing_is_rewritten():
    rewrite = Rewrite()
    with pytest.raises( KeyError ): rc.run_repair_check( Cached( [ KeyError( "receipt" ) ] ), rewrite, "r", "s" )
    assert rewrite.calls == 0


# ---- the input-changed guard ----------------------------------------------------------------

def test_a_rewrite_that_changed_no_input_returns_no_input_change_after_one_replay():
    replay = Cached( [ OFF ] * 5 + [ OFF ] * 5, sha="same" )
    got    = rc.run_repair_check( replay, Rewrite(), "r-1", "target" )
    assert got == rc.RepairResult( rc.NO_INPUT_CHANGE, 0, None, 5 ) and replay.calls == 6


def test_a_changed_index_sha_after_the_rewrite_goes_on_to_the_remaining_replays():
    replay = Cached( [ OFF ] * 5 + [ ON ] * 5 )
    got    = rc.run_repair_check( replay, Rewrite(), "r-1", "target" )
    assert got.verdict == rc.REPAIRED and replay.calls == 10


def test_the_first_after_replay_counts_toward_the_after_hits_when_the_input_changed():
    got = rc.run_repair_check( Cached( [ OFF ] * 5 + [ ON ] + [ OFF ] * 4 ), Rewrite(), "r-1", "target" )
    assert got == rc.RepairResult( rc.FLIPPY_AFTER, 0, 1, 5 )


def test_the_guard_compares_the_last_before_sha_with_the_first_after_sha():
    shas, calls = [ "a", "b", "c", "d", "e", "e" ] + [ "f" ] * 4, [ 0 ]
    def replay( receipt_id ):
        calls[ 0 ] += 1
        return rc.Replayed( OFF, shas[ calls[ 0 ] - 1 ] )
    assert rc.run_repair_check( replay, Rewrite(), "r", "target" ).verdict == rc.NO_INPUT_CHANGE


# ---- the adapter over the real replay tool result -------------------------------------------
# Shapes are read from lupin_mcp.reuse_tools.replay_impl: status ok with a head dict, or status error with a name.

def head( verdict="NEW", cause=None, ids=(), route="full", sha="x" ):
    return { "status": "ok", "receipt_id": "r", "stored": { "route": route }, "head": { "verdict": verdict, "cause": cause, "index_sha": sha,
                                                                                       "shortlist": [ { "id": i, "score": 0.9 } for i in ids ] } }


def test_read_head_reads_the_shortlist_ids_in_order_and_the_index_sha():
    assert rc.read_head( head( "REUSE", None, [ "b", "a" ], sha="abc" ) ) == rc.Replayed( [ "b", "a" ], "abc" )


@pytest.mark.parametrize( "cause", [ "CALL_FAILED", "KEY_UNREADABLE", "INDEX_STALE", "NOT_LUPIN_TREE", "MALFORMED_ANSWER", "DEPENDENCY_MISSING" ] )
def test_an_uncertain_head_is_replay_failed_even_with_a_shortlist( cause ):
    with pytest.raises( rc.ReplayFailed, match=f"uncertain read: {cause}" ): rc.read_head( head( "UNCERTAIN_READ_SOURCE", cause, [ "a" ] ) )


@pytest.mark.parametrize( "name", [ "RECEIPT_MISSING", "RECEIPT_CORRUPT", "SNAPSHOT_MISSING", "CACHE_MISSING" ] )
def test_an_error_result_is_replay_failed_naming_the_error( name ):
    with pytest.raises( rc.ReplayFailed, match=f"replay error: {name}" ): rc.read_head( { "status": "error", "error": name, "receipt_id": "r" } )


def test_a_result_with_no_head_run_is_replay_failed():
    with pytest.raises( rc.ReplayFailed, match="no HEAD run" ): rc.read_head( { **head(), "head": None } )


def test_low_confidence_is_a_real_shortlist_not_a_failed_replay():
    assert rc.read_head( head( "UNCERTAIN_READ_SOURCE", "LOW_CONFIDENCE", [ "target" ] ) ).ids == [ "target" ]
    assert rc.read_head( head( "UNCERTAIN_READ_SOURCE", "LOW_CONFIDENCE", [ "other" ] ) ).ids == [ "other" ]


def test_a_low_confidence_replay_counts_as_present_or_absent_in_the_harness():
    on  = lambda rid, repeat: head( "UNCERTAIN_READ_SOURCE", "LOW_CONFIDENCE", [ "target" ] )
    off = lambda rid, repeat: head( "UNCERTAIN_READ_SOURCE", "LOW_CONFIDENCE", [ "other" ] )
    assert rc.run_repair_check( rc.replayer_over( on ), Rewrite(), "r", "target" ).verdict == rc.ALREADY_MATCHED
    assert rc.run_repair_check( rc.replayer_over( off ), Rewrite(), "r", "target" ).verdict == rc.NO_INPUT_CHANGE


def test_the_adapter_feeds_the_harness_and_an_uncertain_replay_is_call_failed_not_absent():
    ok  = lambda rid, repeat: head( "NEW", None, [ "a" ], sha=f"s{repeat}" )
    bad = lambda rid, repeat: head( "UNCERTAIN_READ_SOURCE", "CALL_FAILED", [] )
    assert rc.run_repair_check( rc.replayer_over( bad ), Rewrite(), "r", "target" ).verdict == rc.CALL_FAILED
    assert rc.run_repair_check( rc.replayer_over( ok ), Rewrite(), "r", "target" ).verdict == rc.NOT_REPAIRED


def test_a_full_sweep_receipt_is_repaired_when_a_docstring_rewrite_changed_the_index():
    def tool( receipt_id, repeat ):
        return head( "NEW", None, [ "target" ] if repeat > 5 else [], route="full", sha="after" if repeat > 5 else "before" )
    got = rc.run_repair_check( rc.replayer_over( tool ), Rewrite(), "r", "target" )
    assert got == rc.RepairResult( rc.REPAIRED, 0, 5, 5 )


def test_a_full_sweep_receipt_whose_rewrite_changed_nothing_is_no_input_change_not_an_exception():
    tool = lambda receipt_id, repeat: head( "NEW", None, [], route="full", sha="same" )
    assert rc.run_repair_check( rc.replayer_over( tool ), Rewrite(), "r", "target" ).verdict == rc.NO_INPUT_CHANGE


# ---- the repeat counter ---------------------------------------------------------------------

def test_the_adapter_asks_for_repeat_one_to_n_in_order_across_before_and_after():
    seen = []
    def tool( receipt_id, repeat ):
        seen.append( repeat )
        return head( "NEW", None, [ "target" ] if len( seen ) > 5 else [], sha=f"s{len( seen )}" )
    got = rc.run_repair_check( rc.replayer_over( tool ), Rewrite(), "r", "target" )
    assert got.verdict == rc.REPAIRED and seen == list( range( 1, 11 ) )


def test_first_repeat_moves_the_counter_so_a_re_check_draws_new_repeats():
    seen = []
    def tool( receipt_id, repeat ):
        seen.append( repeat )
        return head( "NEW", None, [], sha=f"s{len( seen )}" )
    rc.run_repair_check( rc.replayer_over( tool, first_repeat=11 ), Rewrite(), "r", "target" )
    assert seen == list( range( 11, 21 ) )


@pytest.mark.parametrize( "bad", [ 0, -3, 1.5, "1", None, True ] )
def test_first_repeat_must_be_a_positive_int( bad ):
    with pytest.raises( ValueError, match="first_repeat must be a positive int" ): rc.replayer_over( lambda r, repeat: None, first_repeat=bad )


def test_each_wrapper_counts_from_its_own_first_repeat():
    seen = []
    def tool( receipt_id, repeat ):
        seen.append( repeat )
        return head( "NEW", None, [ "x" ] )
    a = rc.replayer_over( tool )
    b = rc.replayer_over( tool, first_repeat=7 )
    a( "r" ), a( "r" ), b( "r" )
    assert seen == [ 1, 2, 7 ]


def test_a_no_match_head_is_a_readable_empty_shortlist_not_a_failure():
    assert rc.read_head( head( "UNCERTAIN_READ_SOURCE", "NO_MATCH", [], sha="s1" ) ) == rc.Replayed( [], "s1" )          # the shipped policy's word for the old verdict NEW


def test_a_miss_is_repaired_when_the_before_state_is_no_match():
    tool = lambda receipt_id, repeat: head( "UNCERTAIN_READ_SOURCE", "NO_MATCH", [], sha="before" ) if repeat <= 5 else head( "REUSE", None, [ "target" ], sha="after" )
    out  = rc.run_repair_check( rc.replayer_over( tool ), lambda: None, "r1", "target", runs=5 )
    assert ( out.verdict, out.before, out.after ) == ( rc.REPAIRED, 0, 5 )

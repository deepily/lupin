"""
Unit tests for symindex.repair_check, run over cached answers: no Jev call is made.
"""
import pytest

from cosa.repo.symindex import repair_check as rc


class Cached:
    """
    A replay that returns prepared shortlists in order, and counts its calls.
    """
    def __init__( self, answers ):
        self.answers, self.calls = list( answers ), 0

    def __call__( self, receipt_id ):
        self.calls += 1
        answer = self.answers.pop( 0 )
        if isinstance( answer, Exception ): raise answer
        return answer


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


def test_runs_is_configurable_and_the_receipt_id_reaches_the_replay():
    seen = []
    def replay( receipt_id ):
        seen.append( receipt_id )
        return ON if len( seen ) > 2 else OFF
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


# ---- the adapter over the real replay tool result ------------------------------------------
# Shapes are read from lupin_mcp.reuse_tools.replay_impl: status ok with a head dict, or status error with a name.

def head( verdict="NEW", cause=None, ids=(), route="pages" ):
    return { "status": "ok", "receipt_id": "r", "stored": { "route": route }, "head": { "verdict": verdict, "cause": cause, "index_sha": "x",
                                                         "shortlist": [ { "id": i, "score": 0.9 } for i in ids ] } }


def test_shortlist_ids_reads_the_head_shortlist_in_order():
    assert rc.shortlist_ids( head( "REUSE", None, [ "b", "a" ] ) ) == [ "b", "a" ]


@pytest.mark.parametrize( "cause", [ "CALL_FAILED", "KEY_UNREADABLE", "INDEX_STALE", "NOT_LUPIN_TREE", "MALFORMED_ANSWER", "DEPENDENCY_MISSING" ] )
def test_an_uncertain_head_is_replay_failed_even_with_a_shortlist( cause ):
    with pytest.raises( rc.ReplayFailed, match=f"uncertain read: {cause}" ): rc.shortlist_ids( head( "UNCERTAIN_READ_SOURCE", cause, [ "a" ] ) )


@pytest.mark.parametrize( "name", [ "RECEIPT_MISSING", "RECEIPT_CORRUPT", "SNAPSHOT_MISSING", "CACHE_MISSING" ] )
def test_an_error_result_is_replay_failed_naming_the_error( name ):
    with pytest.raises( rc.ReplayFailed, match=f"replay error: {name}" ): rc.shortlist_ids( { "status": "error", "error": name, "receipt_id": "r" } )


def test_a_result_with_no_head_run_is_replay_failed():
    with pytest.raises( rc.ReplayFailed, match="no HEAD run" ): rc.shortlist_ids( { **head(), "head": None } )


def test_the_adapter_feeds_the_harness_and_an_uncertain_replay_is_call_failed_not_absent():
    ok  = lambda rid, repeat: head( "NEW", None, [ "a" ] )
    bad = lambda rid, repeat: head( "UNCERTAIN_READ_SOURCE", "CALL_FAILED", [] )
    assert rc.run_repair_check( rc.replayer_over( bad ), Rewrite(), "r", "target" ).verdict == rc.CALL_FAILED
    assert rc.run_repair_check( rc.replayer_over( ok ), Rewrite(), "r", "target" ).verdict == rc.NOT_REPAIRED


def test_low_confidence_is_a_real_shortlist_not_a_failed_replay():
    assert rc.shortlist_ids( head( "UNCERTAIN_READ_SOURCE", "LOW_CONFIDENCE", [ "target" ] ) ) == [ "target" ]
    assert rc.shortlist_ids( head( "UNCERTAIN_READ_SOURCE", "LOW_CONFIDENCE", [ "other" ] ) ) == [ "other" ]


def test_a_low_confidence_replay_counts_as_present_or_absent_in_the_harness():
    on  = lambda rid, repeat: head( "UNCERTAIN_READ_SOURCE", "LOW_CONFIDENCE", [ "target" ] )
    off = lambda rid, repeat: head( "UNCERTAIN_READ_SOURCE", "LOW_CONFIDENCE", [ "other" ] )
    assert rc.run_repair_check( rc.replayer_over( on ), Rewrite(), "r", "target" ).verdict == rc.ALREADY_MATCHED
    assert rc.run_repair_check( rc.replayer_over( off ), Rewrite(), "r", "target" ).verdict == rc.NOT_REPAIRED


def test_the_adapter_asks_for_repeat_one_to_n_in_order_across_before_and_after():
    seen = []
    def tool( receipt_id, repeat ):
        seen.append( repeat )
        return head( "NEW", None, [ "target" ] if len( seen ) > 5 else [] )
    got = rc.run_repair_check( rc.replayer_over( tool ), Rewrite(), "r", "target" )
    assert got.verdict == rc.REPAIRED and seen == list( range( 1, 11 ) )


@pytest.mark.parametrize( "route", [ "full", None ] )
def test_a_receipt_that_never_reads_the_wiki_is_refused_with_a_clear_error( route ):
    result = head( "NEW", None, [ "a" ], route=route )
    if route is None: result[ "stored" ] = {}                                              # a receipt from before page-first has no route
    with pytest.raises( rc.UnrepairableReceipt, match="full-sweep receipt.*never reads the wiki" ): rc.shortlist_ids( result )


@pytest.mark.parametrize( "route", [ "pages", "pages_then_full" ] )
def test_a_page_route_receipt_can_prove_a_repair( route ):
    assert rc.shortlist_ids( head( "NEW", None, [ "a" ], route=route ) ) == [ "a" ]


def test_the_harness_does_not_swallow_the_refusal_and_rewrites_nothing():
    rewrite = Rewrite()
    tool    = lambda rid, repeat: head( "NEW", None, [], route="full" )
    with pytest.raises( rc.UnrepairableReceipt ): rc.run_repair_check( rc.replayer_over( tool ), rewrite, "r", "s" )
    assert rewrite.calls == 0

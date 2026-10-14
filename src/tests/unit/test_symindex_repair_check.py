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


@pytest.mark.parametrize( "bad", [ 0, -1, 2.5, "5", None ] )
def test_runs_must_be_a_positive_int( bad ):
    replay = Cached( [] )
    with pytest.raises( ValueError, match="positive int" ): rc.run_repair_check( replay, Rewrite(), "r", "s", runs=bad )
    assert replay.calls == 0

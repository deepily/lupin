"""
The repair check: replay a missed receipt R times before and after a rewrite.

The live proof that two repeats can differ is a scheduled test, not the unit tier.
The unit tier covers this harness over cached answers only.
"""
from collections import namedtuple
from dataclasses import dataclass

R = 5

REPAIRED        = "REPAIRED"
ALREADY_MATCHED = "ALREADY_MATCHED"
FLIPPY_BEFORE   = "FLIPPY_BEFORE"
FLIPPY_AFTER    = "FLIPPY_AFTER"
NOT_REPAIRED    = "NOT_REPAIRED"
NO_INPUT_CHANGE = "NO_INPUT_CHANGE"
READABLE_CAUSES = ( "LOW_CONFIDENCE", "NO_MATCH" )          # an uncertain head with one of these still holds a real shortlist, empty or not
CALL_FAILED     = "CALL_FAILED"

Replayed = namedtuple( "Replayed", [ "ids", "index_sha" ] )


class ReplayFailed( Exception ):
    """A replay could not produce a shortlist, so the symbol's absence is unknown."""


@dataclass
class RepairResult:
    """
    The outcome of one repair check.

    Ensures:
        - verdict is one of the module's verdict names
        - before and after count the runs that held the symbol, or are None when not run
        - runs is the replay count asked for
    """

    verdict : str
    before  : int
    after   : int
    runs    : int


def run_repair_check( replay, rewrite, receipt_id, symbol, runs=R ):
    """
    Check that a rewrite repaired a miss, replaying before and after.

    Requires:
        - replay( receipt_id ) returns a Replayed, the shortlist ids and the index sha of that run, or raises ReplayFailed
        - rewrite() applies the summary rewrite and takes no arguments
        - runs is a positive int, R by default

    Ensures:
        - rewrite is called only when every before-run lacked the symbol
        - verdict `REPAIRED` means 0 of runs before and runs of runs after
        - `ALREADY_MATCHED` means the symbol was on every before-shortlist: no miss was reproduced
        - `FLIPPY_BEFORE` and `FLIPPY_AFTER` mean a mixed count, which is not evidence either way
        - `NOT_REPAIRED` means the symbol was still absent in every after-run
        - `NO_INPUT_CHANGE` means the first after-run saw the same index sha as the last before-run,
          so the rewrite changed nothing the replay reads; the other after-runs are not spent
        - the guard is coarse: the index sha moves for an edit to any symbol the sweep reads,
          so `NOT_REPAIRED` can follow an edit to some other symbol
        - the first after-run counts toward the after hits when the index sha changed
        - `CALL_FAILED` means a replay raised ReplayFailed; the counts are None for phases not reached

    Raises:
        - ValueError when runs is not a positive int
    """
    if not isinstance( runs, int ) or isinstance( runs, bool ) or runs < 1: raise ValueError( f"runs must be a positive int, got {runs!r}" )
    try:
        seen   = [ replay( receipt_id ) for _ in range( runs ) ]
        before = sum( 1 for r in seen if symbol in r.ids )
    except ReplayFailed:
        return RepairResult( CALL_FAILED, None, None, runs )
    if before == runs: return RepairResult( ALREADY_MATCHED, before, None, runs )
    if before > 0:     return RepairResult( FLIPPY_BEFORE, before, None, runs )
    rewrite()
    try:
        first = replay( receipt_id )
        if first.index_sha == seen[ -1 ].index_sha: return RepairResult( NO_INPUT_CHANGE, before, None, runs )
        after = ( 1 if symbol in first.ids else 0 ) + sum( 1 for _ in range( runs - 1 ) if symbol in replay( receipt_id ).ids )
    except ReplayFailed:
        return RepairResult( CALL_FAILED, before, None, runs )
    if after == runs: return RepairResult( REPAIRED, before, after, runs )
    if after > 0:     return RepairResult( FLIPPY_AFTER, before, after, runs )
    return RepairResult( NOT_REPAIRED, before, after, runs )


def read_head( result ):
    """
    Read the HEAD shortlist ids and index sha out of a replay tool result.

    Requires:
        - result is the dict the replay tool returns

    Ensures:
        - returns a Replayed of the ids of result["head"]["shortlist"], in order, and result["head"]["index_sha"]
        - an error result raises ReplayFailed naming its error, and so does a missing head
        - a head that is uncertain for a gap cause (a failed call, a malformed answer, an unreadable key,
          a stale index, a foreign tree, a missing tool) raises ReplayFailed naming the cause
        - a head that is uncertain only for low confidence returns its shortlist, since that is a real
          shortlist and its absence of the symbol is a finding
        - a head whose cause is `NO_MATCH` (the shipped policy's word for what was once the verdict `NEW`) returns its empty
          shortlist, since a complete sweep that found nothing is the "before" state of a miss

    Raises:
        - ReplayFailed in the cases above
    """
    if result[ "status" ] != "ok": raise ReplayFailed( f"replay error: {result[ 'error' ]}" )
    head = result[ "head" ]
    if head is None: raise ReplayFailed( "replay returned no HEAD run" )
    if head[ "verdict" ] == "UNCERTAIN_READ_SOURCE" and head[ "cause" ] not in READABLE_CAUSES: raise ReplayFailed( f"uncertain read: {head[ 'cause' ]}" )
    return Replayed( [ entry[ "id" ] for entry in head[ "shortlist" ] ], head[ "index_sha" ] )


def replayer_over( replay_tool, first_repeat=1 ):
    """
    Wrap a replay tool as the replay callable run_repair_check takes.

    Requires:
        - replay_tool( receipt_id, repeat=n ) returns the replay tool's result dict, and answers repeat
          n under its own cache key (lupin_mcp.reuse_tools.replay_impl does, from n = 1)
        - first_repeat is a positive int; pass a higher base to re-check a receipt with new draws

    Ensures:
        - returns replay( receipt_id ) giving a Replayed, or raising as read_head does
        - the k-th call passes repeat = first_repeat + k - 1, across before and after, so every replay is its own draw
        - the default first_repeat of 1 repeats draws once: a second check with the same base reads the first check's cached answers
        - a replay tool without a repeat index would read one cached answer R times, so it must not be passed here

    Raises:
        - ValueError when first_repeat is not a positive int
    """
    if not isinstance( first_repeat, int ) or isinstance( first_repeat, bool ) or first_repeat < 1:
        raise ValueError( f"first_repeat must be a positive int, got {first_repeat!r}" )
    calls = [ first_repeat - 1 ]

    def replay( receipt_id ):
        calls[ 0 ] += 1
        return read_head( replay_tool( receipt_id, repeat=calls[ 0 ] ) )
    return replay

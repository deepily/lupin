"""
The repair check: replay a missed receipt R times before and after a rewrite.

The live proof that two repeats can differ is a scheduled test, not the unit tier.
The unit tier covers this harness over cached answers only.
"""
from dataclasses import dataclass

R = 5

REPAIRED        = "REPAIRED"
ALREADY_MATCHED = "ALREADY_MATCHED"
FLIPPY_BEFORE   = "FLIPPY_BEFORE"
FLIPPY_AFTER    = "FLIPPY_AFTER"
NOT_REPAIRED    = "NOT_REPAIRED"
CALL_FAILED     = "CALL_FAILED"


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


def count_hits( replay, receipt_id, symbol, runs ):
    """
    Replay a receipt and count the runs whose shortlist holds the symbol.

    Requires:
        - replay( receipt_id ) returns an iterable of symbol ids, or raises ReplayFailed
        - runs is a positive int

    Ensures:
        - returns an int from 0 to runs
        - makes exactly runs calls, stopping early only by an exception

    Raises:
        - ReplayFailed from replay, so an unknown is never counted as absent
    """
    return sum( 1 for _ in range( runs ) if symbol in set( replay( receipt_id ) ) )


def run_repair_check( replay, rewrite, receipt_id, symbol, runs=R ):
    """
    Check that a rewrite repaired a miss, replaying before and after.

    Requires:
        - replay( receipt_id ) returns the shortlist at the current HEAD, or raises ReplayFailed
        - rewrite() applies the summary rewrite and takes no arguments
        - runs is a positive int, R by default

    Ensures:
        - rewrite is called only when every before-run lacked the symbol
        - verdict `REPAIRED` means 0 of runs before and runs of runs after
        - `ALREADY_MATCHED` means the symbol was on every before-shortlist: no miss was reproduced
        - `FLIPPY_BEFORE` and `FLIPPY_AFTER` mean a mixed count, which is not evidence either way
        - `NOT_REPAIRED` means the symbol was still absent in every after-run
        - `CALL_FAILED` means a replay raised ReplayFailed; the counts are None for phases not reached

    Raises:
        - ValueError when runs is not a positive int
    """
    if not isinstance( runs, int ) or isinstance( runs, bool ) or runs < 1: raise ValueError( f"runs must be a positive int, got {runs!r}" )
    try:
        before = count_hits( replay, receipt_id, symbol, runs )
    except ReplayFailed:
        return RepairResult( CALL_FAILED, None, None, runs )
    if before == runs: return RepairResult( ALREADY_MATCHED, before, None, runs )
    if before > 0:     return RepairResult( FLIPPY_BEFORE, before, None, runs )
    rewrite()
    try:
        after = count_hits( replay, receipt_id, symbol, runs )
    except ReplayFailed:
        return RepairResult( CALL_FAILED, before, None, runs )
    if after == runs: return RepairResult( REPAIRED, before, after, runs )
    if after > 0:     return RepairResult( FLIPPY_AFTER, before, after, runs )
    return RepairResult( NOT_REPAIRED, before, after, runs )


PAGE_ROUTES = ( "pages", "pages_then_full" )


class UnrepairableReceipt( ValueError ):
    """A full-sweep receipt never reads the wiki, so no rewrite of a summary can repair it."""


def shortlist_ids( result ):
    """
    Read the HEAD shortlist ids out of a replay tool result.

    Requires:
        - result is the dict the replay tool returns

    Ensures:
        - returns the ids of result["head"]["shortlist"], in order
        - an error result raises ReplayFailed naming its error, and so does a missing head
        - a head that is uncertain for a gap cause (a failed call, a malformed answer, an unreadable key,
          a stale index, a foreign tree, a missing tool) raises ReplayFailed naming the cause
        - a head that is uncertain only for low confidence returns its shortlist, since that is a real
          shortlist and its absence of the symbol is a finding

    Raises:
        - UnrepairableReceipt when the receipt's route is not a page route, or has none
        - ReplayFailed in the cases above
    """
    if result[ "status" ] != "ok": raise ReplayFailed( f"replay error: {result[ 'error' ]}" )
    route = result[ "stored" ].get( "route" )
    if route not in PAGE_ROUTES:
        raise UnrepairableReceipt( f"full-sweep receipt (route {route!r}) never reads the wiki, so a summary rewrite cannot repair it; only {', '.join( PAGE_ROUTES )} receipts can" )
    head = result[ "head" ]
    if head is None: raise ReplayFailed( "replay returned no HEAD run" )
    if head[ "verdict" ] == "UNCERTAIN_READ_SOURCE" and head[ "cause" ] != "LOW_CONFIDENCE": raise ReplayFailed( f"uncertain read: {head[ 'cause' ]}" )
    return [ entry[ "id" ] for entry in head[ "shortlist" ] ]


def replayer_over( replay_tool ):
    """
    Wrap a replay tool as the replay callable run_repair_check takes.

    Requires:
        - replay_tool( receipt_id, repeat=n ) returns the replay tool's result dict, and answers repeat
          n under its own cache key (lupin_mcp.reuse_tools.replay_impl does, from n = 1)

    Ensures:
        - returns replay( receipt_id ) giving the HEAD shortlist ids, or raising as shortlist_ids does
        - the k-th call passes repeat=k, counting from 1 and across before and after, so every replay is its own draw
        - a replay tool without a repeat index would read one cached answer R times, so it must not be passed here

    Raises:
        - nothing
    """
    calls = [ 0 ]

    def replay( receipt_id ):
        calls[ 0 ] += 1
        return shortlist_ids( replay_tool( receipt_id, repeat=calls[ 0 ] ) )
    return replay

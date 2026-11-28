"""
Pair two arms' replay records by ask id, within one snapshot, never by position.

replay_loop.paired_wins zips two record lists, so it is given the lists this returns.
The checks follow phi4_flash_lite_study.replay_harness.pair_records, which keys on a frozen index instead of the ask id.
The plan is 2026.11.23-answer-signal-experiment-plan.md, the retrospective re-score.
"""


def pair_by_ask( records_a, records_b ):
    """
    Put the second arm's records in the first arm's ask order.

    Requires:
        - both lists hold replay records, each with snapshot_sha256 and meta.notification_id

    Ensures:
        - returns ( records_a as given, records_b reordered ), so the two records at one place are of one ask
        - two empty lists return two empty lists

    Raises:
        - ValueError when the lists name different snapshots or more than one, when a list holds an ask twice, or when the lists do not hold the same asks
        - KeyError for a record with no snapshot_sha256 or no ask id
    """
    snapshots = [ { r[ "snapshot_sha256" ] for r in records } for records in ( records_a, records_b ) ]
    if snapshots[ 0 ] != snapshots[ 1 ] or len( snapshots[ 0 ] ) > 1:
        raise ValueError( f"the two arms must come from one snapshot, not {sorted( snapshots[ 0 ] )} and {sorted( snapshots[ 1 ] )}" )
    by_id = []
    for records in ( records_a, records_b ):
        held = { r[ "meta" ][ "notification_id" ]: r for r in records }
        if len( held ) != len( records ): raise ValueError( "an arm holds one ask twice" )
        by_id.append( held )
    first, second = by_id
    if set( first ) != set( second ): raise ValueError( f"the arms hold different asks: {sorted( set( first ) ^ set( second ) )[ :5 ]}" )
    return list( records_a ), [ second[ r[ "meta" ][ "notification_id" ] ] for r in records_a ]

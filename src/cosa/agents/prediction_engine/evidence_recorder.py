"""
Per-thread record of the cases a forecast retrieved, so the forecast row can store them.

`predict()` runs on one worker thread per ask. The retrieval paths call `note( similar_cases )` after each search.
`predict()` calls `begin()` first and `collect()` last. So the ids and scores stored on the row are the ones that
ask retrieved, and no other ask's.
"""
import threading

_local = threading.local()


def begin() -> None:
    """
    Start an empty evidence list for the calling thread.

    Ensures:
        - any evidence left by an earlier ask on this thread is dropped
    """
    _local.cases = []


def note( similar_cases ) -> None:
    """
    Add the retrieved cases to the calling thread's evidence.

    Requires:
        - similar_cases is a list of ( similarity, record ) pairs, as find_similar returns

    Ensures:
        - each pair adds one { id, score } entry in retrieval order
        - does nothing when begin() has not been called on this thread
    """
    if not hasattr( _local, "cases" ): return
    for similarity, record in similar_cases:
        _local.cases.append( { "id": record.get( "id" ), "score": round( float( similarity ), 4 ) } )


def collect() -> tuple:
    """
    Return the calling thread's evidence and clear it.

    Ensures:
        - returns ( ids, scores ), two lists of the same length in retrieval order
        - returns two empty lists when nothing was retrieved or begin() was never called
        - the thread holds no evidence afterwards
    """
    cases = _local.cases if hasattr( _local, "cases" ) else []
    _local.cases = []
    return [ c[ "id" ] for c in cases ], [ c[ "score" ] for c in cases ]

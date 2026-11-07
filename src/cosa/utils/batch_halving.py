"""
Retry a refused batch in halves.

A batch the embedder refuses is not evidence that any text in it is bad. It may only have been too big for the memory
free at that moment. Halving finds the real culprit, or success, in log2(n) attempts. Two callers use it.
The vector builder raises when a single text is refused.
The database regeneration marks that row and goes on.
They differ in what happens around each attempt, so the algorithm takes those as callables.
"""
from typing import Any, List, Sequence


def split_batch( batch: Sequence[Any] ) -> List[List[Any]]:
    """
    Halve a batch that the embedder refused, for retry.

    Requires:
        - batch is a sequence

    Ensures:
        - returns [] for an empty batch
        - returns [] for a single-item batch: one item cannot be split, and the caller must treat that as a genuine per-row failure rather than retry forever
        - otherwise returns exactly two non-empty halves covering the batch in order
    """
    if len( batch ) <= 1: return []
    middle = len( batch ) // 2
    return [ list( batch[ :middle ] ), list( batch[ middle: ] ) ]


def embed_in_halves( embed, batch, alone_failed, before_half=None, on_failure=None, on_success=None, passthrough=(), depth=0 ):
    """
    Embed one batch, and when it is refused, embed its two halves instead, down to one item.

    Requires:
        - embed( batch ) returns a list with one result per item, or raises
        - alone_failed( error, batch ) is called for a refused batch of one item, and returns the list to use or raises
        - before_half( depth ), on_failure( error, batch ) and on_success( depth ) are None or callables
        - passthrough is a tuple of exception classes that are never split

    Ensures:
        - returns the results in order, the halves' lists joined
        - on_success is called with depth 0 for a whole batch that was not refused, and with the deeper depth for a half
        - on_failure is called for each refused batch before it is split
        - before_half is called with the half's depth before each half, so a caller can pause between attempts
        - an exception in passthrough reaches the caller untouched, with no on_failure call and no split

    Raises:
        - whatever embed raises that is in passthrough, and whatever alone_failed raises
    """
    try:
        result = embed( batch )
        if on_success is not None: on_success( depth )
        return result
    except passthrough: raise
    except Exception as error:
        if on_failure is not None: on_failure( error, batch )
        halves = split_batch( batch )
        if not halves: return alone_failed( error, batch )
        out = [ ]
        for half in halves:
            if before_half is not None: before_half( depth + 1 )
            out.extend( embed_in_halves( embed, half, alone_failed, before_half, on_failure, on_success, passthrough, depth + 1 ) )
        return out

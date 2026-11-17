"""Halving a refused batch: call order, hooks, passthrough and the one-item case."""
import pytest

from cosa.utils.batch_halving import embed_in_halves, split_batch


class Refused( Exception ):
    """A refusal the embedder raises for a batch that is too big."""


class Dead( Exception ):
    """A refusal that no smaller batch can cure."""


def _embedder( limit, seen, bad=( ) ):
    """Ensures: returns an embed that refuses a big or bad batch, and records each batch."""
    def embed( batch ):
        seen.append( list( batch ) )
        if len( batch ) > limit or any( b in bad for b in batch ): raise Refused( f"{len( batch )} items" )
        return [ f"v{b}" for b in batch ]
    return embed


def _raise( error, _batch ):
    raise error


def test_a_batch_that_fits_is_embedded_once_and_the_success_hook_sees_depth_zero():
    seen, ok = [ ], [ ]
    assert embed_in_halves( _embedder( 4, seen ), [ 1, 2, 3 ], _raise, on_success=ok.append ) == [ "v1", "v2", "v3" ]
    assert seen == [ [ 1, 2, 3 ] ] and ok == [ 0 ]


def test_a_refused_batch_is_halved_down_until_each_half_fits_and_the_results_keep_their_order():
    seen, fails, pauses, ok = [ ], [ ], [ ], [ ]
    got = embed_in_halves( _embedder( 2, seen ), [ 1, 2, 3, 4, 5 ], _raise, before_half=pauses.append,
                           on_failure=lambda error, batch: fails.append( ( type( error ), batch ) ), on_success=ok.append )
    assert got == [ "v1", "v2", "v3", "v4", "v5" ]
    assert seen == [ [ 1, 2, 3, 4, 5 ], [ 1, 2 ], [ 3, 4, 5 ], [ 3 ], [ 4, 5 ] ]
    assert fails == [ ( Refused, [ 1, 2, 3, 4, 5 ] ), ( Refused, [ 3, 4, 5 ] ) ]
    assert pauses == [ 1, 1, 2, 2 ] and ok == [ 1, 2, 2 ]


def test_a_refused_single_item_goes_to_alone_failed_which_may_return_or_raise():
    seen = [ ]
    assert embed_in_halves( _embedder( 9, seen, bad=( 2, ) ), [ 1, 2 ], lambda error, batch: [ ( batch[ 0 ], None ) ] ) == [ "v1", ( 2, None ) ]
    with pytest.raises( Refused ):
        embed_in_halves( _embedder( 9, [ ], bad=( 2, ) ), [ 1, 2 ], _raise )


def test_a_passthrough_error_is_not_split_and_no_failure_hook_runs():
    def embed( batch ):
        raise Dead( "down" )
    fails = [ ]
    with pytest.raises( Dead ):
        embed_in_halves( embed, [ 1, 2, 3, 4 ], _raise, on_failure=lambda *a: fails.append( a ), passthrough=( Dead, ) )
    assert fails == [ ]


def test_the_helper_and_the_split_agree_on_the_halves():
    assert split_batch( [ 1, 2, 3 ] ) == [ [ 1 ], [ 2, 3 ] ] and split_batch( [ 1 ] ) == [ ] and split_batch( [ ] ) == [ ]

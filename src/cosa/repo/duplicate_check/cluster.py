"""Clusters of duplicate definitions and the score per 100 passing tests."""
import collections

from cosa.repo.semdup import errors as err
from cosa.repo.semdup.judge import FLAG_VERDICTS


def join_pairs( verdicts ):
    """
    Turn verdict rows into the pairs of definitions the judge flagged.

    Requires:
        - verdicts are rows { id, candidate, verdict, ... } from judge_run

    Ensures:
        - returns a sorted list of [ a, b ] with a < b
        - a pair is listed when either definition's ruling on the other is duplicate or near_duplicate
        - related and distinct rulings join nothing
        - a pair is listed once, whatever the number of rows or slots that flag it
    """
    flagged = { tuple( sorted( ( v[ "id" ], v[ "candidate" ] ) ) ) for v in verdicts if v[ "verdict" ] in FLAG_VERDICTS and v[ "id" ] != v[ "candidate" ] }
    return [ list( pair ) for pair in sorted( flagged ) ]


def clusters( ids, pairs ):
    """
    Group definitions into connected clusters by union-find.

    Requires:
        - ids are the ids of every definition, new and server, unique
        - pairs are [ a, b ] lists of ids

    Ensures:
        - returns the clusters, each a sorted list of ids, ordered by their first id
        - every id is in exactly one cluster; an id with no pair is a cluster of one
        - a chain a~b, b~c is one cluster of three

    Raises:
        - ValueError if a pair names an id that is not in ids
    """
    parent = { i: i for i in ids }

    def find( i ):
        """Return the root of i, flattening the path on the way."""
        while parent[ i ] != i:
            parent[ i ] = parent[ parent[ i ] ]
            i           = parent[ i ]
        return i

    for a, b in pairs:
        for i in ( a, b ):
            if i not in parent: raise ValueError( f"pair names {i}, which is not a definition of the run" )
        parent[ find( a ) ] = find( b )
    groups = collections.defaultdict( list )
    for i in ids: groups[ find( i ) ].append( i )
    return sorted( ( sorted( members ) for members in groups.values() ), key=lambda members: members[ 0 ] )


def surplus( groups, origin ):
    """
    Count the surplus copies: the new definitions beyond the one a cluster needs.

    Requires:
        - groups came from clusters
        - origin maps every id to "new" or "server"

    Ensures:
        - returns the sum over clusters of ( new definitions in it ) minus ( 1 if it holds no server definition, else 0 )
        - with only new definitions this is definitions minus clusters
        - a new definition that repeats server code counts, because the server copy is not subtracted
        - a cluster of servers only adds nothing
    """
    total = 0
    for members in groups:
        new_count = sum( 1 for i in members if origin[ i ] == "new" )
        if new_count == 0: continue
        has_server = any( origin[ i ] == "server" for i in members )
        total     += new_count - ( 0 if has_server else 1 )
    return total


def sizes( groups ):
    """
    Count the clusters of two or more definitions by their size.

    Requires:
        - groups came from clusters

    Ensures:
        - returns { "2": n, "3": m, ... } keyed by the size as text, so it is JSON as written; clusters of one are left out
    """
    counted = collections.Counter( len( members ) for members in groups if len( members ) > 1 )
    return { str( size ): counted[ size ] for size in sorted( counted ) }


def score( surplus_count, passing ):
    """
    Return the surplus copies per 100 passing acceptance tests.

    Requires:
        - surplus_count is the count from surplus
        - passing is the number of passing acceptance tests

    Ensures:
        - returns 100 * surplus_count / passing

    Raises:
        - SemdupError NO_PASSING_TESTS if passing is below 1
    """
    if passing < 1: raise err.SemdupError( err.NO_PASSING_TESTS, f"{passing} passing tests: a per-100 figure is undefined (raw surplus {surplus_count})" )
    return 100 * surplus_count / passing

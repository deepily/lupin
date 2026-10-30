"""The proof's loader: reviewers' pair labels and the answer key in, { pair key: bool } out."""
import json
import pathlib

from cosa.repo.labelling import packets as pk
from cosa.repo.labelling import pair_labels as pl
from cosa.repo.semdup.proof import proof_run


def key_rows( key_path ):
    """Ensures: returns { item_id: { a, b, ... } } from the key; a and b are definition ids."""
    return json.loads( pathlib.Path( key_path ).read_text( encoding="utf-8" ) )[ "items" ]


def _known( item_ids, rows ):
    """Raises: ValueError naming the item ids the key does not know."""
    unknown = sorted( set( item_ids ) - set( rows ) )
    if unknown: raise ValueError( f"labels for items the key does not know: {', '.join( unknown )}" )


def pair_key_labels( labels_path, key_path ):
    """
    Turn one reviewer's labels file into the proof's labels.

    Requires:
        - labels_path is a labels file of one reviewer, key_path the answer key of the same run

    Ensures:
        - returns { pair key: bool } with the key written as proof_run.label_key writes it
        - an unsure label counts at its leaning choice

    Raises:
        - LabellingError BAD_LABEL from the reader, or for a choice a pair never takes
        - ValueError naming the item ids the key does not know
    """
    rows   = key_rows( key_path )
    labels = pl.same_job_labels( labels_path )
    _known( labels, rows )
    return { proof_run.label_key( rows[ i ][ "a" ], rows[ i ][ "b" ] ): same for i, same in labels.items() }


def third_votes( labels_path, key_path ):
    """
    Turn the third rater's labels file into votes on the disputed pairs.

    Requires:
        - labels_path is the third rater's labels file, key_path the answer key of the same run

    Ensures:
        - returns { pair key: bool or None }; an unsure label is None, because Rick ruled that it cannot make a majority

    Raises:
        - LabellingError BAD_LABEL from the reader, or for a choice a pair never takes
        - ValueError naming the item ids the key does not know
    """
    rows   = key_rows( key_path )
    labels = pk.read_labels( labels_path )
    _known( [ label[ "item_id" ] for label in labels ], rows )
    votes  = {}
    for label in labels:
        same = pl.same_job( label )
        votes[ proof_run.label_key( rows[ label[ "item_id" ] ][ "a" ], rows[ label[ "item_id" ] ][ "b" ] ) ] = None if pl.is_unsure( label ) else same
    return votes


def disputed_items( first_path, second_path ):
    """Ensures: returns the sorted item ids both reviewers labelled, and labelled differently."""
    first, second = ( pl.same_job_labels( p ) for p in ( first_path, second_path ) )
    return sorted( i for i in set( first ) & set( second ) if first[ i ] != second[ i ] )


def resolved_labels( first_path, second_path, key_path, rulings=None, third_path=None ):
    """
    Settle every pair of the key from the reviewers' labels files.

    Two reviewers label every pair; a third rater labels only the pairs they disagree on.

    Requires:
        - rulings is None or { pair key: bool }, Rick's call on a disagreement the third rater does not settle
        - third_path is None or the third rater's labels file, covering the disputed pairs and no others

    Ensures:
        - returns { pair key: bool }, as proof_run takes in spec[ "labels" ], from proof_run.resolve_label
        - a disputed pair the third rater labels without "unsure" takes that label, the 2-to-1 majority, over any ruling;
          every other disputed pair takes Rick's ruling

    Raises:
        - ValueError naming the pair keys either reviewer has not labelled, the pairs the third rater labels that are not disputed,
          the disputed pairs the third rater has not labelled, or the disagreements that have no majority and no ruling
    """
    rows     = key_rows( key_path )
    every    = sorted( proof_run.label_key( r[ "a" ], r[ "b" ] ) for r in rows.values() )
    mine     = [ pair_key_labels( p, key_path ) for p in ( first_path, second_path ) ]
    missing  = sorted( k for k in every if k not in mine[ 0 ] or k not in mine[ 1 ] )
    if missing: raise ValueError( f"{len( missing )} pairs are not labelled by both reviewers: {', '.join( missing )}" )
    disputed = [ k for k in every if mine[ 0 ][ k ] != mine[ 1 ][ k ] ]
    votes    = third_votes( third_path, key_path ) if third_path is not None else {}
    if third_path is not None:
        extra  = sorted( set( votes ) - set( disputed ) )
        absent = sorted( set( disputed ) - set( votes ) )
        if extra: raise ValueError( f"the third rater labelled {len( extra )} pairs that are not disputed: {', '.join( extra )}" )
        if absent: raise ValueError( f"the third rater has not labelled {len( absent )} disputed pairs: {', '.join( absent )}" )
    calls    = { **( rulings or {} ), **{ k: v for k, v in votes.items() if v is not None } }
    owed     = [ k for k in disputed if k not in calls ]
    if owed: raise ValueError( f"{len( owed )} disagreements have no ruling: {', '.join( owed )}" )
    return { k: proof_run.resolve_label( mine[ 0 ][ k ], mine[ 1 ][ k ], calls.get( k ) ) for k in every }

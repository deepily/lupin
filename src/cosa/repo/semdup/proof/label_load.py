"""The proof's loader: reviewers' pair labels and the answer key in, { pair key: bool } out."""
import json
import pathlib

from cosa.repo.labelling import pair_labels as pl
from cosa.repo.semdup.proof import proof_run


def key_rows( key_path ):
    """Ensures: returns { item_id: { a, b, ... } } from the key; a and b are definition ids."""
    return json.loads( pathlib.Path( key_path ).read_text( encoding="utf-8" ) )[ "items" ]


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
    rows    = key_rows( key_path )
    labels  = pl.same_job_labels( labels_path )
    unknown = sorted( set( labels ) - set( rows ) )
    if unknown: raise ValueError( f"labels for items the key does not know: {', '.join( unknown )}" )
    return { proof_run.label_key( rows[ i ][ "a" ], rows[ i ][ "b" ] ): same for i, same in labels.items() }


def resolved_labels( first_path, second_path, key_path, rulings=None ):
    """
    Settle every pair of the key from two reviewers' labels files.

    Requires:
        - rulings is None or { pair key: bool }, the call made on each disagreement

    Ensures:
        - returns { pair key: bool }, as proof_run takes in spec[ "labels" ], from proof_run.resolve_label

    Raises:
        - ValueError naming the pair keys either reviewer has not labelled, or the disagreements that have no ruling
    """
    rows    = key_rows( key_path )
    every   = sorted( proof_run.label_key( r[ "a" ], r[ "b" ] ) for r in rows.values() )
    mine    = [ pair_key_labels( p, key_path ) for p in ( first_path, second_path ) ]
    missing = sorted( k for k in every if k not in mine[ 0 ] or k not in mine[ 1 ] )
    if missing: raise ValueError( f"{len( missing )} pairs are not labelled by both reviewers: {', '.join( missing )}" )
    rulings = rulings or {}
    owed    = [ k for k in every if mine[ 0 ][ k ] != mine[ 1 ][ k ] and k not in rulings ]
    if owed: raise ValueError( f"{len( owed )} disagreements have no ruling: {', '.join( owed )}" )
    return { k: proof_run.resolve_label( mine[ 0 ][ k ], mine[ 1 ][ k ], rulings.get( k ) ) for k in every }

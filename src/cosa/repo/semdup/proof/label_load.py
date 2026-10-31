"""The proof's loader: reviewers' pair labels and the answer key in, { pair key: bool } out."""
import json
import pathlib

from cosa.repo.labelling import packets as pk
from cosa.repo.labelling import pair_labels as pl
from cosa.repo.semdup.proof import proof_run
from cosa.repo.symindex.candidates import arm_run


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


def supplement_rows( supplement, key_path ):
    """
    Read the answer key a supplement adds, and refuse it if it overlaps the run's key.

    A supplement is labels for pairs the run's key does not hold. They live in files of their own, so the run's labels files stay as they were.

    Requires:
        - supplement is { key: path of a key file shaped like the run's, labels: [ the first reviewer's labels file, the second's ] }
        - key_path is the run's answer key

    Ensures:
        - returns { item_id: { a, b, ... } } from the supplement's key

    Raises:
        - ValueError if the supplement does not name two labels files, reuses an item id of the run's key, or holds a pair the run's key holds
    """
    if len( supplement[ "labels" ] ) != 2: raise ValueError( f"a supplement takes two labels files, {len( supplement[ 'labels' ] )} given" )
    main, rows = key_rows( key_path ), key_rows( supplement[ "key" ] )
    reused     = sorted( set( rows ) & set( main ) )
    if reused: raise ValueError( f"supplement item ids already in the key: {', '.join( reused )}" )
    held       = { proof_run.label_key( r[ "a" ], r[ "b" ] ) for r in main.values() }
    twins      = sorted( k for k in ( proof_run.label_key( r[ "a" ], r[ "b" ] ) for r in rows.values() ) if k in held )
    if twins: raise ValueError( f"supplement pairs already in the key: {', '.join( twins )}" )
    return rows


def resolved_labels( first_path, second_path, key_path, rulings=None, third_path=None, supplement=None ):
    """
    Settle every pair of the key from the reviewers' labels files.

    Two reviewers label every pair; a third rater labels only the pairs they disagree on.

    Requires:
        - rulings is None or { pair key: bool }, Rick's call on a disagreement the third rater does not settle
        - third_path is None or the third rater's labels file, covering the disputed pairs of the run's key and no others
        - supplement is None or as supplement_rows takes it; its pairs must be labelled by both reviewers like any other

    Ensures:
        - returns { pair key: bool }, as proof_run takes in spec[ "labels" ], from proof_run.resolve_label
        - a disputed pair the third rater labels without "unsure" takes that label, the 2-to-1 majority, over any ruling;
          every other disputed pair takes Rick's ruling
        - a disputed supplement pair has no third rater and takes Rick's ruling

    Raises:
        - ValueError naming the pair keys either reviewer has not labelled, the pairs the third rater labels that are not disputed,
          the disputed pairs the third rater has not labelled, or the disagreements that have no majority and no ruling
    """
    rows     = key_rows( key_path )
    every    = sorted( proof_run.label_key( r[ "a" ], r[ "b" ] ) for r in rows.values() )
    mine     = [ pair_key_labels( p, key_path ) for p in ( first_path, second_path ) ]
    if supplement is not None:
        added  = supplement_rows( supplement, key_path )
        every  = sorted( [ *every, *( proof_run.label_key( r[ "a" ], r[ "b" ] ) for r in added.values() ) ] )
        mine   = [ { **m, **pair_key_labels( p, supplement[ "key" ] ) } for m, p in zip( mine, supplement[ "labels" ] ) ]
    missing  = sorted( k for k in every if k not in mine[ 0 ] or k not in mine[ 1 ] )
    if missing: raise ValueError( f"{len( missing )} pairs are not labelled by both reviewers: {', '.join( missing )}" )
    disputed = [ k for k in every if mine[ 0 ][ k ] != mine[ 1 ][ k ] ]
    votes    = third_votes( third_path, key_path ) if third_path is not None else {}
    if third_path is not None:
        in_key = { proof_run.label_key( r[ "a" ], r[ "b" ] ) for r in rows.values() }
        extra  = sorted( set( votes ) - set( disputed ) )
        absent = sorted( ( set( disputed ) & in_key ) - set( votes ) )
        if extra: raise ValueError( f"the third rater labelled {len( extra )} pairs that are not disputed: {', '.join( extra )}" )
        if absent: raise ValueError( f"the third rater has not labelled {len( absent )} disputed pairs: {', '.join( absent )}" )
    calls    = { **( rulings or {} ), **{ k: v for k, v in votes.items() if v is not None } }
    owed     = [ k for k in disputed if k not in calls ]
    if owed: raise ValueError( f"{len( owed )} disagreements have no ruling: {', '.join( owed )}" )
    return { k: proof_run.resolve_label( mine[ 0 ][ k ], mine[ 1 ][ k ], calls.get( k ) ) for k in every }


def fingerprints( labels_paths, rulings_path, third_path, key_path, tree_root, supplement=None ):
    """
    Name the exact inputs a proof run settled its labels from.

    Requires:
        - labels_paths is the list of reviewers' labels files used; rulings_path and third_path are None or the files used
        - key_path is the answer key of the run; tree_root is the root of the tree the run is made from
        - supplement is None or as supplement_rows takes it

    Ensures:
        - returns { labels: { path: sha256 }, rulings: sha256 or None, third_labels: sha256 or None, answer_key: sha256, tree_root }
        - with a supplement the record also holds supplement: { key: sha256, labels: { path: sha256 } }; without one it has no such field
        - the digests are of the bytes on disk now, so a later edit of a file, an appended answer included, no longer matches
    """
    prints = { "labels": { str( p ): arm_run.sha256_of( p ) for p in labels_paths },
               "rulings": arm_run.sha256_of( rulings_path ) if rulings_path is not None else None,
               "third_labels": arm_run.sha256_of( third_path ) if third_path is not None else None,
               "answer_key": arm_run.sha256_of( key_path ), "tree_root": str( tree_root ) }
    if supplement is not None: prints[ "supplement" ] = { "key": arm_run.sha256_of( supplement[ "key" ] ), "labels": { str( p ): arm_run.sha256_of( p ) for p in supplement[ "labels" ] } }
    return prints


def unsure_pair_keys( labels_paths, key_path, supplement=None ):
    """
    List the pairs any of these reviewers marked unsure, at their latest answer.

    Requires:
        - labels_paths are labels files of the reviewers, key_path the answer key of the same run
        - supplement is None or as supplement_rows takes it

    Ensures:
        - returns the sorted pair keys, written as proof_run.label_key writes them, the supplement's included

    Raises:
        - ValueError naming the item ids the key does not know
    """
    rows   = key_rows( key_path )
    unsure = set()
    for path in labels_paths:
        labels = pk.read_labels( path )
        _known( [ label[ "item_id" ] for label in labels ], rows )
        unsure |= { proof_run.label_key( rows[ l[ "item_id" ] ][ "a" ], rows[ l[ "item_id" ] ][ "b" ] ) for l in labels if pl.is_unsure( l ) }
    if supplement is not None: unsure |= set( unsure_pair_keys( supplement[ "labels" ], supplement[ "key" ] ) )
    return sorted( unsure )

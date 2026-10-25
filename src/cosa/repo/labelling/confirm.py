"""
Confirm mode of the packet tool: a seeded 20% blind, the rest shown with Rick's label.

The second reviewer labels the blind sample without seeing any label, and sees Rick's label on every other item, which
the reviewer confirms or disputes. Kappa is computed on the blind sample only, because a label given with the other
label in view is not independent. The report says so and gives the sample size.
"""
import json
import pathlib
import random

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import packets as pk
from cosa.repo.labelling.adjudicate import differs
from cosa.repo.labelling.agreement import agreement_report, paired

BLIND_SHARE     = 0.2
MODE_BLIND      = "blind"
MODE_CONFIRM    = "confirm"
MANIFEST_FORMAT = "confirm-manifest-1"
MANIFEST_KEYS   = ( "format", "seed", "share", "reviewer", "rick", "n_items", "n_blind", "blind_ids" )
KAPPA_BASIS     = "blind sample only"


def manifest_path( out_dir, reviewer ):
    """Return the path of the manifest that goes with one reviewer's confirm packet."""
    return pathlib.Path( out_dir ) / f"confirm-manifest-{reviewer}.json"


def blind_sample_ids( item_ids, seed, share=BLIND_SHARE ):
    """
    Draw the items the second reviewer labels blind.

    Requires:
        - item_ids are distinct strings; share is a number above 0 and below 1

    Ensures:
        - returns the sorted ids of int( share * n + 0.5 ) items, half rounded up as the plan counts, not Python's half-to-even round
        - the same ids, seed and share give the same sample whatever the order the ids arrive in
    """
    ordered = sorted( item_ids )
    return sorted( random.Random( f"{seed}|confirm-sample" ).sample( ordered, int( share * len( ordered ) + 0.5 ) ) )


def _line( item, rick_label, blind ):
    """Return one item's packet line: blind form, mode and, off the sample, Rick's label."""
    line = dict( pk.blind_form( item ), mode=MODE_BLIND if blind else MODE_CONFIRM )
    if not blind: line[ "rick_label" ] = { "choice": rick_label[ "choice" ], "symbols": list( rick_label[ "symbols" ] ) }
    return line


def _check_written( path, expected ):
    """
    Read a packet back and check each line is exactly what was meant to be written.

    Raises:
        - LabellingError PACKET_LEAK when a line differs from the expected line of its item, which is how an extra field shows
    """
    for line in path.read_text( encoding="utf-8" ).splitlines():
        got = json.loads( line )
        if got != expected.get( got.get( "item_id" ) ): raise er.LabellingError( er.PACKET_LEAK, f"{got.get( 'item_id' )}: the written line is not the intended one" )


def export_confirm_packet( items, rick_labels, reviewer, seed, out_dir, share=BLIND_SHARE ):
    """
    Write the second reviewer's packet in confirm mode, and its manifest.

    Requires:
        - items are labelling items with distinct ids; rick_labels is Rick's read_labels output, one label per item and no other
        - reviewer is a name of letters, digits, _ and -, and is not the name on Rick's labels
        - share is above 0 and below 1, and draws at least one item

    Ensures:
        - returns { path, manifest_path, blind_ids, confirm_ids }
        - the blind items carry the blind form and the mode; every other item also carries Rick's choice and symbols, and no note, time or other field
        - the sample is drawn with the seed, which the manifest records with the share, the item count and the blind ids
        - the bytes written are read back and compared with the intended lines; on a mismatch the files are removed

    Raises:
        - LabellingError BAD_ITEM for an invalid item, duplicate ids, a bad or repeated reviewer name, a share outside 0 to 1 or an empty sample
        - LabellingError BAD_LABEL when Rick's labels and the items are not the same set
        - LabellingError PACKET_LEAK as export_packets does
    """
    clean = [ pk.blind_form( i ) for i in items ]
    ids   = [ i[ "item_id" ] for i in clean ]
    if len( set( ids ) ) != len( ids ): raise er.LabellingError( er.BAD_ITEM, "item ids repeat" )
    if not pk.NAME_RE.fullmatch( reviewer ): raise er.LabellingError( er.BAD_ITEM, "the reviewer name needs letters, digits, _ and -" )
    if not 0 < share < 1: raise er.LabellingError( er.BAD_ITEM, "the blind share must be above 0 and below 1" )
    rick = { l[ "item_id" ]: l for l in rick_labels }
    if set( rick ) != set( ids ) or len( rick ) != len( rick_labels ): raise er.LabellingError( er.BAD_LABEL, f"Rick's labels must cover exactly the items: {sorted( set( rick ) ^ set( ids ) )[ :5 ]}" )
    blind = blind_sample_ids( ids, seed, share )
    if not blind: raise er.LabellingError( er.BAD_ITEM, f"{len( ids )} items at {share} draw no blind sample" )
    rick_name = rick_labels[ 0 ][ "reviewer" ]
    if reviewer == rick_name: raise er.LabellingError( er.BAD_ITEM, f"the second reviewer cannot be {rick_name}, who labelled the rest" )
    order    = sorted( clean, key=lambda i: i[ "item_id" ] )
    random.Random( f"{seed}|confirm-order" ).shuffle( order )
    lines    = [ _line( i, rick[ i[ "item_id" ] ], i[ "item_id" ] in blind ) for i in order ]
    out      = pathlib.Path( out_dir )
    out.mkdir( parents=True, exist_ok=True )
    path, mpath = pk.packet_path( out, reviewer ), manifest_path( out, reviewer )
    path.write_text( "".join( json.dumps( l, sort_keys=True ) + "\n" for l in lines ), encoding="utf-8" )
    mpath.write_text( json.dumps( { "format": MANIFEST_FORMAT, "seed": seed, "share": share, "reviewer": reviewer, "rick": rick_name, "n_items": len( ids ), "n_blind": len( blind ), "blind_ids": blind },
                                  sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    try:
        _check_written( path, { l[ "item_id" ]: l for l in lines } )
    except er.LabellingError:
        path.unlink(); mpath.unlink()
        raise
    return { "path": path, "manifest_path": mpath, "blind_ids": blind, "confirm_ids": sorted( set( ids ) - set( blind ) ) }


def read_manifest( path ):
    """
    Read a confirm manifest.

    Ensures:
        - returns the manifest dict when it has the manifest keys and no others, the current format and an n_blind equal to the number of blind ids

    Raises:
        - LabellingError BAD_LABEL naming the file when it is not a manifest
    """
    try:
        manifest = json.loads( pathlib.Path( path ).read_text( encoding="utf-8" ) )
    except ValueError:
        raise er.LabellingError( er.BAD_LABEL, f"{path}: not JSON" )
    if not isinstance( manifest, dict ) or set( manifest ) != set( MANIFEST_KEYS ) or manifest[ "format" ] != MANIFEST_FORMAT or manifest[ "n_blind" ] != len( manifest[ "blind_ids" ] ):
        raise er.LabellingError( er.BAD_LABEL, f"{path}: not a {MANIFEST_FORMAT} manifest" )
    return manifest


def confirm_report( rick_labels, reviewer_labels, manifest, categories=pk.CHOICES ):
    """
    Report a confirm-mode round.

    Requires:
        - rick_labels and reviewer_labels each hold one label per item, the same items; manifest is a read_manifest result
        - every blind id of the manifest is an item

    Ensures:
        - returns { kappa_basis, kappa_n, kappa, blind, confirm_n, confirmed, disputed_blind, disputed_confirm, disputes_for_rick, seed, statement }
        - kappa and blind (the agreement_report) are computed over the blind sample only; kappa is None when every blind label is one category
        - confirmed counts the other items whose reviewer label equals Rick's in choice and symbols; disputed_* list the differing item ids, sorted
        - disputes_for_rick is every disputed id from both parts, sorted, for Rick to settle
        - statement says that kappa was computed on the blind sample, gives its size and the seed

    Raises:
        - LabellingError BAD_LABEL when the two sets of labels cover different items or a blind id is not an item
    """
    pairs = paired( rick_labels, reviewer_labels )
    ids   = { a[ "item_id" ] for a, _ in pairs }
    blind = set( manifest[ "blind_ids" ] )
    if not blind <= ids: raise er.LabellingError( er.BAD_LABEL, f"blind ids that are not items: {sorted( blind - ids )[ :5 ]}" )
    sample = [ ( a, b ) for a, b in pairs if a[ "item_id" ] in blind ]
    rest   = [ ( a, b ) for a, b in pairs if a[ "item_id" ] not in blind ]
    try:
        agreement = agreement_report( [ a for a, _ in sample ], [ b for _, b in sample ], categories )
    except er.LabellingError as e:
        if e.code != er.KAPPA_UNDEFINED: raise
        agreement = None
    disputed_blind   = sorted( a[ "item_id" ] for a, b in sample if differs( a, b ) )
    disputed_confirm = sorted( a[ "item_id" ] for a, b in rest if differs( a, b ) )
    statement = ( f"Cohen's kappa was computed on the blind sample only: {len( sample )} of {len( pairs )} items, drawn with seed {manifest[ 'seed' ]}. "
                  f"The other {len( rest )} items were confirmed against {manifest[ 'rick' ]}'s labels, not labelled blind, and are not in kappa." )
    return { "kappa_basis": KAPPA_BASIS, "kappa_n": len( sample ), "kappa": None if agreement is None else agreement[ "kappa" ], "blind": agreement,
             "confirm_n": len( rest ), "confirmed": len( rest ) - len( disputed_confirm ), "disputed_blind": disputed_blind, "disputed_confirm": disputed_confirm,
             "disputes_for_rick": sorted( disputed_blind + disputed_confirm ), "seed": manifest[ "seed" ], "statement": statement }

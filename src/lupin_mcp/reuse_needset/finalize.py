"""Choose the needs people label, build the final set and verify its manifest."""
import copy
import json
import pathlib
import random

from cosa.repo.labelling import call_sites as cs
from cosa.repo.labelling import items as lb
from cosa.repo.labelling import run_check as rc
from cosa.utils.file_hash import file_sha256
from lupin_mcp.reuse_needset import check, freeze, schema
from lupin_mcp.reuse_needset import errors as er

SAMPLE_PERCENT = 15
DISPUTED       = "disputed"
NOTHING        = "nothing"
RUN_CHECK      = "run_check"
SAMPLE         = "sample"
DUPLICATE_PAIR = "semdup_pair"   # the value stays: it matches the packets already written


def sample_size( n_agreed ):
    """Return 15 percent of n_agreed with a half rounded up, so 30 gives 5."""
    return ( SAMPLE_PERCENT * n_agreed + 50 ) // 100


def select_for_labelling( needs, seed, duplicate_items=(), person_check_ids=(), run_checks=None ):
    """
    Choose what the reviewers see, keeping each item's reason apart from the item.

    Requires:
        - needs are checked needs; duplicate_items are ids of pairs the duplicate checker hands over
        - run_checks, when given, is the { need id: run_check record } mapping; every need whose record routes to a person is selected, as person_check_ids are

    Ensures:
        - returns [ { id, reason } ] in this order: every disputed need, every nothing need not already listed, every need in person_check_ids not already listed (reason run_check), a seeded 15 percent of the agreed matched needs, then the pairs
        - each group is sorted by id, and the same needs and seed give the same list
        - the sample is sample_size( agreed matched needs ) needs

    Raises:
        - NeedsetError BAD_NEED for a need that is not checked or is a smoke need
    """
    for n in needs:
        if n[ "status" ] != "checked": raise er.NeedsetError( er.BAD_NEED, f"{n[ 'id' ]}: only a checked need is selected, this one is {n[ 'status' ]}" )
        if "smoke" in n: raise er.NeedsetError( er.BAD_NEED, f"{n[ 'id' ]}: a smoke need never reaches a reviewer" )
    picked   = [ { "id": n[ "id" ], "reason": DISPUTED } for n in sorted( needs, key=lambda n: n[ "id" ] ) if check.disputed( n ) ]
    listed   = { p[ "id" ] for p in picked }
    picked  += [ { "id": n[ "id" ], "reason": NOTHING } for n in sorted( needs, key=lambda n: n[ "id" ] ) if n[ "kind" ] == "nothing" and n[ "id" ] not in listed ]
    listed   = { p[ "id" ] for p in picked }
    person   = set( person_check_ids ) | ( set() if run_checks is None else { i for i, r in run_checks.items() if r[ "route" ] == rc.PERSON_CHECK } )
    picked  += [ { "id": n[ "id" ], "reason": RUN_CHECK } for n in sorted( needs, key=lambda n: n[ "id" ] ) if n[ "id" ] in person and n[ "id" ] not in listed ]
    listed   = { p[ "id" ] for p in picked }
    agreed   = sorted( n[ "id" ] for n in needs if n[ "id" ] not in listed )
    chosen   = random.Random( f"{seed}|labelling" ).sample( agreed, sample_size( len( agreed ) ) )
    picked  += [ { "id": i, "reason": SAMPLE } for i in sorted( chosen ) ]
    return picked + [ { "id": i, "reason": DUPLICATE_PAIR } for i in sorted( duplicate_items ) ]


def need_item( need, key_texts=None, hits=None, call_sites=None, run_check=None ):
    """
    Build the item a reviewer sees for a need.

    Requires:
        - a matched need comes with key_texts, the source of each key symbol; a nothing need with hits, the top search hit lines
        - call_sites, when given, are up to five lines showing where the key symbol is called; run_check, when given, is the record from run_check.check_pair

    Ensures:
        - returns a need_key item holding the sentence and the key sources (and the call sites when given), or the sentence, nothing_exists true and the hits
        - the item holds no verdict, route, drafter, checker or run-check field

    Raises:
        - NeedsetError KEY_REJECTED when run_check rejected the key, naming the reason
        - LabellingError BAD_ITEM when the material does not fit the kind
    """
    if run_check is not None and run_check[ "route" ] == rc.REJECT: raise er.NeedsetError( er.KEY_REJECTED, f"{need[ 'id' ]}: the work-alike does not behave like its original: {run_check[ 'reason' ]}" )
    payload = { "need": need[ "need" ], "nothing_exists": True, "hits": hits } if need[ "kind" ] == "nothing" else { "need": need[ "need" ], "key_sources": key_texts }
    if call_sites is not None: payload[ "call_sites" ] = call_sites
    return lb.make_item( lb.NEED_KEY, need[ "id" ], payload )


def run_check_needs( needs, pairs, seed, checker=rc.check_pair ):
    """
    Run-check the work-alike rewrites the caller hands in.

    Requires:
        - pairs maps a need id to ( original source, rewrite source ); needs are the drafted or checked needs of the run

    Ensures:
        - returns { need id: run_check record } for each pair, in the order of pairs
        - a need with no pair is not run-checked and has no record

    Raises:
        - NeedsetError BAD_NEED for a pair whose need id is not among the needs
        - LabellingError SANDBOX_UNAVAILABLE from the checker when the sandbox cannot start
    """
    known = { n[ "id" ] for n in needs }
    stray = [ i for i in pairs if i not in known ]
    if stray: raise er.NeedsetError( er.BAD_NEED, f"run-check pairs for needs that are not in the run: {stray[ :5 ]}" )
    return { i: checker( original, rewrite, seed ) for i, ( original, rewrite ) in pairs.items() }


def screen_needs( needs, run_checks ):
    """
    Split needs by what the run-check ruled on their keys.

    Requires:
        - run_checks maps a need id to a run_check.check_pair record; a need with no record was not run-checked

    Ensures:
        - returns ( kept, rejected, person_check_ids ) where rejected is [ { id, reason } ] for the needs whose key was rejected, in need order
        - kept holds every other need in its order; person_check_ids is the set of kept ids whose record routes to a person
    """
    kept, rejected, person = [], [], set()
    for n in needs:
        record = run_checks[ n[ "id" ] ] if n[ "id" ] in run_checks else None
        if record is not None and record[ "route" ] == rc.REJECT:
            rejected.append( { "id": n[ "id" ], "reason": record[ "reason" ] } )
            continue
        kept.append( n )
        if record is not None and record[ "route" ] == rc.PERSON_CHECK: person.add( n[ "id" ] )
    return kept, rejected, person


def key_call_sites( need, by_id, root, files ):
    """
    Find where a matched need's key symbols are called.

    Requires:
        - by_id maps an index id to its record; files are tracked paths relative to root

    Ensures:
        - returns up to five lines over all the key symbols that are Python, in key order
        - returns None when no key symbol is Python, so a TypeScript key shows no call-site claim at all
    """
    python = [ by_id[ i ] for i in need[ "key" ][ "symbols" ] if by_id[ i ][ "lang" ] == "py" ]
    if not python: return None
    sites = []
    for rec in python:
        room = cs.LIMIT - len( sites )
        if room <= 0: break
        sites += cs.find_call_sites( rec[ "name" ], rec[ "file" ], files, root, room )
    return sites


def labelling_items( needs, selection, source_of, hits_of, call_sites_of, run_checks ):
    """
    Build the items for the needs select_for_labelling picked.

    Requires:
        - selection is the list from select_for_labelling; needs hold every picked need
        - source_of( symbol id ) returns a symbol's source; hits_of( need ) returns a nothing need's hit lines; call_sites_of( need ) returns a matched need's call sites or None

    Ensures:
        - returns one need_key item per picked need, in selection order; duplicate-check pairs are not needs and are skipped
        - a matched item holds the key sources and the call sites; a nothing item holds the hits

    Raises:
        - NeedsetError KEY_REJECTED for a picked need whose key the run-check rejected
    """
    by_id, out = { n[ "id" ]: n for n in needs }, []
    for pick in selection:
        if pick[ "reason" ] == DUPLICATE_PAIR: continue
        need   = by_id[ pick[ "id" ] ]
        ruling = run_checks[ need[ "id" ] ] if need[ "id" ] in run_checks else None
        if need[ "kind" ] == "nothing": out.append( need_item( need, hits=hits_of( need ), run_check=ruling ) )
        else: out.append( need_item( need, key_texts=[ source_of( i ) for i in need[ "key" ][ "symbols" ] ], call_sites=call_sites_of( need ), run_check=ruling ) )
    return out


FINAL_FILE      = "needset-final.jsonl"
MANIFEST_FILE   = "needset-manifest.json"
MANIFEST_FORMAT = "needset-manifest-1"
EXPECTED        = { "rows": 400, "matched": 300, "nothing": 100, "ts": 240, "py": 160 }
HUMAN_SOURCES   = ( "agreed", "rick_tiebreak" )
MODEL_AGREED    = "model_agreed"
REVIEWER_KEY    = "reviewer_confirmed"


def _mismatch( condition, detail ):
    """Raises: NeedsetError MANIFEST_MISMATCH naming the condition that failed."""
    raise er.NeedsetError( er.MANIFEST_MISMATCH, f"{condition}: {detail}" )


def _repeated( ids ):
    """Return the ids that occur more than once, sorted."""
    seen, again = set(), set()
    for i in ids:
        if i in seen: again.add( i )
        seen.add( i )
    return sorted( again )


def final_row( need, label ):
    """
    Join a checked need with its final label.

    Requires:
        - label is { choice, symbols, final_source } from adjudicate.resolve

    Ensures:
        - returns a copy at status final, holding the label as final
        - a matched need labelled with other symbols takes the reviewers' symbols as its key, version raised by one and provenance reviewer_confirmed
        - a nothing need is confirmed by AS_PROPOSED; an unlabelled need keeps its proposal with final_source model_agreed

    Raises:
        - NeedsetError BAD_NEED for a smoke need, or a need that is not checked (the row then fails validation)
        - NeedsetError MANIFEST_MISMATCH when the label rejects the need: none on a matched need, anything but AS_PROPOSED on a nothing need
    """
    if "smoke" in need: raise er.NeedsetError( er.BAD_NEED, f"{need[ 'id' ]}: finalize refuses a smoke need" )
    row, choice = copy.deepcopy( need ), label[ "choice" ]
    nothing     = need[ "kind" ] == "nothing"
    if choice is not None and ( ( nothing and choice != "AS_PROPOSED" ) or ( not nothing and choice == "NONE" ) ):
        _mismatch( "REJECTED", f"{need[ 'id' ]}: the reviewers rejected this need ({choice}); replace it before finalising" )
    if choice == "OTHER":
        row[ "key" ] = dict( row[ "key" ], symbols=list( label[ "symbols" ] ), version=row[ "key" ][ "version" ] + 1, provenance=REVIEWER_KEY )
    row[ "status" ] = "final"
    row[ "final" ]  = { "choice": choice, "symbols": label[ "symbols" ], "final_source": label[ "final_source" ] }
    schema.validate_need( row )
    return row


def _frozen_hashes( holder ):
    """Raises: NeedsetError MANIFEST_MISMATCH when a frozen hash is missing or empty."""
    absent = [ k for k in freeze.IDENTITY_KEYS if not isinstance( holder.get( k ), str ) or not holder[ k ] ]
    if absent: _mismatch( "FROZEN", f"no frozen hash for {absent}" )


def finalize( needs, labels, kappa, seed, source_commit, frozen, out_dir, known_symbols=None ):
    """
    Write the final set and its manifest.

    Requires:
        - labels maps each need id to its final label; every need has one
        - kappa is the reviewers' kappa, a number
        - frozen is freeze.identity's result for the frozen index and vector set the keys were written against
        - known_symbols is None, or the set of symbols that exist in the index

    Ensures:
        - writes needset-final.jsonl, one row per need sorted by id, then needset-manifest.json holding the counts, the seed, the source commit, kappa, the three frozen hashes and the sha256 of the final file
        - returns the manifest

    Raises:
        - NeedsetError BAD_NEED from final_row, MANIFEST_MISMATCH for a need without a label, a repeated need id, a kappa that is not a number, a frozen identity that lacks a hash, or a typed symbol outside known_symbols
    """
    if isinstance( kappa, bool ) or not isinstance( kappa, ( int, float ) ): _mismatch( "KAPPA", f"kappa must be a number, got {kappa!r}" )
    _frozen_hashes( frozen )
    repeated = _repeated( n[ "id" ] for n in needs )
    if repeated: _mismatch( "IDS", f"repeated need ids: {repeated[ :5 ]}" )
    missing = sorted( n[ "id" ] for n in needs if n[ "id" ] not in labels )
    if missing: _mismatch( "LABELS", f"needs without a final label: {missing[ :5 ]}" )
    if known_symbols is not None:
        unknown = sorted( { s for n in needs if labels[ n[ "id" ] ][ "choice" ] == "OTHER" for s in labels[ n[ "id" ] ][ "symbols" ] } - set( known_symbols ) )
        if unknown: _mismatch( "SYMBOLS", f"typed symbols that are not in the index: {unknown[ :5 ]}" )
    rows = [ final_row( n, labels[ n[ "id" ] ] ) for n in sorted( needs, key=lambda n: n[ "id" ] ) ]
    out  = pathlib.Path( out_dir )
    ( out / FINAL_FILE ).write_text( "".join( json.dumps( r, sort_keys=True ) + "\n" for r in rows ), encoding="utf-8" )
    manifest = { "format": MANIFEST_FORMAT, "seed": seed, "source_commit": source_commit, "kappa": kappa, **{ k: frozen[ k ] for k in freeze.IDENTITY_KEYS }, "final_sha256": file_sha256( out / FINAL_FILE ),
                 "counts": { "rows": len( rows ), "matched": sum( 1 for r in rows if r[ "kind" ] != "nothing" ), "nothing": sum( 1 for r in rows if r[ "kind" ] == "nothing" ),
                             "ts": sum( 1 for r in rows if r[ "write_lang" ] == "ts" ), "py": sum( 1 for r in rows if r[ "write_lang" ] == "py" ) } }
    ( out / MANIFEST_FILE ).write_text( json.dumps( manifest, sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    return manifest


def verify_manifest( path, expected=None ):
    """
    Check a finished set against the shape the project requires.

    Requires:
        - path is the manifest file; the final file sits beside it

    Ensures:
        - returns None when the row count, the matched and nothing counts and the ts and py counts equal expected (400, 300, 100, 240, 160 by default)
        - every row is a valid final need, so a matched row has a key and a nothing row has none
        - every nothing row and every disputed row has a human final_source, and no row is a smoke row
        - no need id repeats, and every row's source_commit is the manifest's
        - the manifest's counts equal the rows' counts, and the manifest holds a seed
        - the manifest's sha256 equals the final file's, and the manifest holds a kappa
        - the manifest holds the three frozen hashes

    Raises:
        - NeedsetError MANIFEST_MISMATCH starting its detail with the failed condition: files, rows, ids, smoke, kinds, langs, commit, counts, seed, human, sha, kappa or frozen, in capitals
    """
    expected = EXPECTED if expected is None else expected
    path     = pathlib.Path( path )
    final    = path.with_name( FINAL_FILE )
    if not path.is_file() or not final.is_file(): _mismatch( "FILES", f"{path.name} and {FINAL_FILE} must both exist in {path.parent}" )
    try:
        manifest = json.loads( path.read_text( encoding="utf-8" ) )
        rows     = [ json.loads( l ) for l in final.read_text( encoding="utf-8" ).splitlines() ]
    except ValueError as e:
        _mismatch( "FILES", f"not JSON: {e}" )
    if len( rows ) != expected[ "rows" ]: _mismatch( "ROWS", f"{len( rows )} rows, expected {expected[ 'rows' ]}" )
    for r in rows:
        if isinstance( r, dict ) and "smoke" in r: _mismatch( "SMOKE", f"{r.get( 'id', '?' )}: a smoke row is in the final set" )
        try:
            schema.validate_need( r )
        except er.NeedsetError as e:
            _mismatch( "ROWS", f"invalid row: {e.detail}" )
        if r[ "status" ] != "final" or "final" not in r: _mismatch( "ROWS", f"{r[ 'id' ]}: not a final row" )
    repeated = _repeated( r[ "id" ] for r in rows )
    if repeated: _mismatch( "IDS", f"{len( { r[ 'id' ] for r in rows } )} unique ids in {len( rows )} rows; repeated: {repeated[ :5 ]}" )
    got = { "matched": sum( 1 for r in rows if r[ "kind" ] != "nothing" ), "nothing": sum( 1 for r in rows if r[ "kind" ] == "nothing" ) }
    if got[ "matched" ] != expected[ "matched" ]: _mismatch( "KINDS", f"{got[ 'matched' ]} matched and {got[ 'nothing' ]} nothing, expected {expected[ 'matched' ]} and {expected[ 'nothing' ]}" )
    langs = { l: sum( 1 for r in rows if r[ "write_lang" ] == l ) for l in ( "ts", "py" ) }
    if langs[ "ts" ] != expected[ "ts" ]: _mismatch( "LANGS", f"{langs[ 'ts' ]} ts and {langs[ 'py' ]} py, expected {expected[ 'ts' ]} and {expected[ 'py' ]}" )
    if manifest.get( "counts" ) != { "rows": len( rows ), "matched": got[ "matched" ], "nothing": got[ "nothing" ], "ts": langs[ "ts" ], "py": langs[ "py" ] }:
        _mismatch( "COUNTS", f"the manifest's counts {manifest.get( 'counts' )} are not the rows' counts" )
    wrong = [ r[ "id" ] for r in rows if r[ "source_commit" ] != manifest.get( "source_commit" ) ]
    if wrong or not manifest.get( "source_commit" ): _mismatch( "COMMIT", f"{len( wrong )} rows carry a source_commit other than the manifest's {manifest.get( 'source_commit' )!r}" )
    if manifest.get( "seed" ) is None: _mismatch( "SEED", "the manifest holds no seed" )
    for r in rows:
        if ( r[ "kind" ] == "nothing" or check.disputed( r ) ) and r[ "final" ][ "final_source" ] not in HUMAN_SOURCES:
            _mismatch( "HUMAN", f"{r[ 'id' ]}: a {r[ 'kind' ]} row or a disputed row needs a human final source, this one is {r[ 'final' ][ 'final_source' ]}" )
    if manifest.get( "final_sha256" ) != file_sha256( final ): _mismatch( "SHA", "the manifest's sha256 is not the final file's" )
    if isinstance( manifest.get( "kappa" ), bool ) or not isinstance( manifest.get( "kappa" ), ( int, float ) ): _mismatch( "KAPPA", "the manifest holds no kappa" )
    _frozen_hashes( manifest )


STATUS_FILE = "needset-status.json"


def check_committed_set( folder ):
    """
    Check the committed set against the status file beside it.

    Requires:
        - folder is the folder that holds needset-status.json

    Ensures:
        - returns None when the status is pending and neither the final file nor the manifest exists, so a half-set cannot be committed
        - returns None when the status is final and verify_manifest passes over the folder's manifest and final file

    Raises:
        - NeedsetError MANIFEST_MISMATCH starting its detail with the word status in capitals when the status file is missing, unreadable or unknown, or a pending set has a set file
        - NeedsetError MANIFEST_MISMATCH from verify_manifest when the status is final and a file is missing or a condition fails
    """
    folder = pathlib.Path( folder )
    try:
        status = json.loads( ( folder / STATUS_FILE ).read_text( encoding="utf-8" ) )[ "status" ]
    except ( OSError, ValueError, KeyError, TypeError ) as e:
        _mismatch( "STATUS", f"no readable {STATUS_FILE} in {folder}: {e!r}" )
    if status == "pending":
        present = [ n for n in ( FINAL_FILE, MANIFEST_FILE ) if ( folder / n ).exists() ]
        if present: _mismatch( "STATUS", f"the status is pending but {present} exist; flip the status in the same commit that adds the set" )
    elif status == "final":
        verify_manifest( folder / MANIFEST_FILE )
    else:
        _mismatch( "STATUS", f"the status is {status!r}, expected pending or final" )

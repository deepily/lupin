"""
The mechanical check of the need sentences for the end-to-end run.

Plan: src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.07-jev-reuse-sweep-packed-request-plan.md
section 12.2, the third numbered point. A need must describe its member without handing Jev the answer.
It may hold no identifier of the member or of its twins. It may share no run of 4 words with the text Jev
sees of the member or of a twin. It must have the length and form of the second numbered point.

A twin is every other member of the member's connected twin group, exact clusters and near pairs joined.
Two members linked only through a third are therefore twins of each other.
The script writes two files. One is for the reviewer: it names the offending token or run.
The other is for the need writer: it holds member ids and check names only.
Nothing here reaches Jev.
"""
import argparse
import ast
import hashlib
import json
import pathlib
import re
import sys

from lupin_mcp import reuse_tools as rt

DATA_ROOT        = "/mnt/DATA01/include/www.deepily.ai/projects-data/lupin"
DEFAULT_NEEDS    = DATA_ROOT + "/reuse-e2e-2026.10/needs.json"
DEFAULT_MANIFEST = DATA_ROOT + "/reuse-recall-baseline-2026.10.06/manifest.json"
DEFAULT_SAMPLE   = "/mnt/DATA01/include/www.deepily.ai/projects/lupin/io/tmp/2026.10.07-john-jev-e2e-sample-by-component-58-42-seed-20261007.json"

DEFAULT_SAMPLE_SHA   = "5b6d84fc2dd8dc458b36255e129001f55e3fbe4d252c14c6d65a4994779a91fd"      # plan 12.1, ruling R1
DEFAULT_MANIFEST_SHA = "bfbfceab399cf753093f0c9ee0bec73a0de00738a0696126a669e129de466941"      # plan 12.1

NEEDS_FORMAT     = "reuse-e2e-needs-1"                            # the document need_writer.needs_document emits and the driver loads
SAMPLE_SIZE      = 100
MIN_WORDS        = 8
MAX_WORDS        = 40
RUN_LENGTH       = 4                                              # John's number, not a measurement
FORM_STARTS      = ( "a function that ", "a method that ", "a class that " )
CHECKS           = ( "form", "identifier", "member_text_run", "twin_text_run", "sample" )


def entry_text_of( rec ):
    """Ensures: returns what Jev sees of one symbol, as the production reader builds it."""
    return rt.entry_text( rec )


def file_sha256( path ):
    """Ensures: returns the sha256 hex digest of the file's bytes."""
    return hashlib.sha256( pathlib.Path( path ).read_bytes() ).hexdigest()


def twin_groups( manifest ):
    """
    Join the exact clusters and near pairs into connected groups.

    Requires:
        - manifest holds "exact" and "near" lists, each item with a "members" list of dicts with an "id"

    Ensures:
        - returns { member id: sorted list of every other member of its group }
        - a member linked only to itself maps to an empty list
    """
    parent = {}

    def find( x ):
        parent.setdefault( x, x )
        while parent[ x ] != x:
            parent[ x ] = parent[ parent[ x ] ]
            x = parent[ x ]
        return x

    for item in manifest[ "exact" ] + manifest[ "near" ]:
        ids = [ m[ "id" ] for m in item[ "members" ] ]
        for other in ids[ 1: ]: parent[ find( other ) ] = find( ids[ 0 ] )
        find( ids[ 0 ] )
    members = {}
    for x in list( parent ): members.setdefault( find( x ), [] ).append( x )
    return { x: sorted( y for y in group if y != x ) for group in members.values() for x in group }


def _argument_names( sig ):
    """Ensures: returns the argument names of a signature string such as "( self, a, *b, **c )"."""
    try:
        a = ast.parse( "def _" + sig + ": pass" ).body[ 0 ].args
    except SyntaxError:
        return set( re.findall( r"[A-Za-z_][A-Za-z0-9_]*", sig ) )
    named = a.posonlyargs + a.args + a.kwonlyargs + [ x for x in ( a.vararg, a.kwarg ) if x ]
    return { x.arg for x in named }


def identifier_tokens( rec ):
    """
    Return the identifier tokens of one symbol record.

    Ensures:
        - returns the lowercase identifier tokens of one symbol record
        - the tokens are the dotted parts of its id, its file stem and its argument names, each whole
        - a word that is only a piece of one of those names is not a token
    """
    names = set( rec[ "id" ].split( "." ) ) | { pathlib.PurePosixPath( rec[ "file" ] ).stem } | _argument_names( rec[ "sig" ] )
    return { n.lower() for n in names }


def _words( text ):
    """Ensures: returns the lowercase alphanumeric words of text, in order."""
    return re.findall( r"[a-z0-9]+", text.lower() )


def shared_run( need, text, n=RUN_LENGTH ):
    """Ensures: returns the first n-word run of need found in text, else None."""
    a, b  = _words( need ), _words( text )
    seen  = { tuple( b[ i : i + n ] ) for i in range( len( b ) - n + 1 ) }
    for i in range( len( a ) - n + 1 ):
        if tuple( a[ i : i + n ] ) in seen: return " ".join( a[ i : i + n ] )
    return None


def check_form( need ):
    """Ensures: returns None for one well-formed sentence, else the reasons it is not."""
    why   = []
    count = len( need.split() )
    if not MIN_WORDS <= count <= MAX_WORDS: why.append( f"words: {count}, not {MIN_WORDS} to {MAX_WORDS}" )
    if not need.lower().startswith( FORM_STARTS ): why.append( "start: not 'A function that', 'A method that' or 'A class that'" )
    if re.search( r"[.!?]\s+\S", need.strip() ): why.append( "sentence: more than one sentence" )
    return "; ".join( why ) if why else None


def _record( index, member_id ):
    """Ensures: returns the index record, or raises ValueError naming the id."""
    if member_id not in index: raise ValueError( f"{member_id} is not in the index" )
    return index[ member_id ]


def check_need( member_id, need, index, groups ):
    """
    Check one need against its member and every member of its twin group.

    Requires:
        - member_id and every twin of it are keys of index

    Ensures:
        - returns a list of { "check", "detail" }, empty when the need passes the form, identifier and run checks
        - "detail" names the offending token or run
    """
    out   = []
    twins = groups.get( member_id, [] )
    rec   = _record( index, member_id )
    form  = check_form( need )
    if form: out.append( { "check": "form", "detail": form } )
    banned = identifier_tokens( rec )
    for t in twins: banned |= identifier_tokens( _record( index, t ) )
    tokens = set( re.findall( r"[a-z0-9_]+", need.lower() ) )
    tokens |= { p for t in tokens for p in t.split( "_" ) if p }
    hits   = sorted( tokens & banned )
    if hits: out.append( { "check": "identifier", "detail": "identifier tokens: " + ", ".join( hits ) } )
    run = shared_run( need, entry_text_of( rec ) )
    if run: out.append( { "check": "member_text_run", "detail": f"4-word run shared with the member: {run}" } )
    for t in twins:
        run = shared_run( need, entry_text_of( _record( index, t ) ) )
        if run:
            out.append( { "check": "twin_text_run", "detail": f"4-word run shared with a twin ({t}): {run}" } )
            break
    return out


def check_all( needs, sample_ids, index, groups ):
    """
    Check every sampled member's need.

    Requires:
        - needs maps member id to need text; sample_ids is the frozen sample, not empty

    Ensures:
        - returns rows and a summary, with one row per sample id
        - a sample id with no need fails the "sample" check
        - a need for an id outside the sample is listed under "extra"
    """
    if not sample_ids: raise ValueError( "the sample is empty: nothing to check" )
    rows, missing = [], []
    for m in sample_ids:
        if m not in needs:
            missing.append( m )
            rows.append( { "member": m, "ok": False, "failures": [ { "check": "sample", "detail": "no need for this member" } ] } )
            continue
        f = check_need( m, needs[ m ], index, groups )
        rows.append( { "member": m, "ok": not f, "failures": f } )
    extra   = sorted( set( needs ) - set( sample_ids ) )
    failed  = sum( 1 for r in rows if not r[ "ok" ] )
    summary = { "sample": len( sample_ids ), "checked": len( sample_ids ) - len( missing ), "failed": failed,
                "missing": missing, "extra": extra, "all_pass": failed == 0 and not extra }
    return { "rows": rows, "summary": summary }


def resend_list( results ):
    """Ensures: returns the member id and check names of each failed row, nothing else."""
    return [ { "member": r[ "member" ], "failed": sorted( { f[ "check" ] for f in r[ "failures" ] } ) } for r in results[ "rows" ] if not r[ "ok" ] ]


def load_sample_ids( path ):
    """
    Requires:
        - path names a sample file with "strata", each stratum holding a "members" list

    Ensures:
        - returns the member ids in file order
    Raises:
        - ValueError when the file holds no members or names one twice
    """
    data = json.loads( pathlib.Path( path ).read_text( encoding="utf-8" ) )
    ids  = [ m for s in data[ "strata" ].values() for m in s[ "members" ] ]
    if not ids: raise ValueError( f"{path} holds no members" )
    for m in ids:
        if ids.count( m ) > 1: raise ValueError( f"{m} is named twice in {path}" )
    return ids


def load_needs( path, sample_sha256 ):
    """
    Read the needs document the writer emits.

    Requires:
        - path names a JSON document { format, sample_sha256, needs: [ { member, need, ... } ] }
        - sample_sha256 is the sha256 of the sample file this check uses

    Ensures:
        - returns { member id: need text } in document order

    Raises:
        - ValueError when the format or sample_sha256 differs, needs is not a list,
          an entry lacks a text member and need, or a member is named twice
    """
    doc = json.loads( pathlib.Path( path ).read_text( encoding="utf-8" ) )
    if not isinstance( doc, dict ) or doc.get( "format" ) != NEEDS_FORMAT: raise ValueError( f"format is not {NEEDS_FORMAT}" )
    if doc.get( "sample_sha256" ) != sample_sha256: raise ValueError( f"sample_sha256 in the document is {doc.get( 'sample_sha256' )}, not the sample's {sample_sha256}" )
    if not isinstance( doc.get( "needs" ), list ): raise ValueError( "needs is not a list" )
    out = {}
    for i, e in enumerate( doc[ "needs" ] ):
        if not ( isinstance( e, dict ) and isinstance( e.get( "member" ), str ) and isinstance( e.get( "need" ), str ) ):
            raise ValueError( f"entry {i} has no text member and need" )
        if e[ "member" ] in out: raise ValueError( f"{e[ 'member' ]} is named twice in the needs document" )
        out[ e[ "member" ] ] = e[ "need" ]
    return out


def load_index( path ):
    """Ensures: returns { id: record } from a symbols.jsonl file, blank lines skipped."""
    recs = [ json.loads( l ) for l in pathlib.Path( path ).read_text( encoding="utf-8" ).splitlines() if l.strip() ]
    return { r[ "id" ]: r for r in recs }


def main( argv=None ):
    """
    Run the check and write check-results.json and resend-list.json.

    Ensures:
        - returns 0 when exactly --size needs were checked and all pass, 1 when any fails or the count differs
        - returns 2, writing nothing, when an input is missing, unreadable or malformed
        - returns 2, writing nothing, when the sample or manifest sha256 is not the one named
        - returns 2, writing nothing, when a member or a twin of one is not in the index
    """
    ap = argparse.ArgumentParser( description=__doc__ )
    ap.add_argument( "--needs",    default=DEFAULT_NEEDS )
    ap.add_argument( "--manifest", default=DEFAULT_MANIFEST )
    ap.add_argument( "--sample",   default=DEFAULT_SAMPLE )
    ap.add_argument( "--index",    required=True, help="symbols.jsonl of the index the run used" )
    ap.add_argument( "--out-dir",  required=True )
    ap.add_argument( "--size",     type=int, default=SAMPLE_SIZE )
    ap.add_argument( "--sample-sha256",   default=DEFAULT_SAMPLE_SHA )
    ap.add_argument( "--manifest-sha256", default=DEFAULT_MANIFEST_SHA )
    a = ap.parse_args( argv )
    try:
        groups   = twin_groups( json.loads( pathlib.Path( a.manifest ).read_text( encoding="utf-8" ) ) )
        index    = load_index( a.index )
        sample   = load_sample_ids( a.sample )
        shas     = { "needs_sha256": file_sha256( a.needs ), "sample_sha256": file_sha256( a.sample ), "manifest_sha256": file_sha256( a.manifest ),
                     "index_generation": pathlib.Path( a.index ).resolve().parent.name, "index_sha256": file_sha256( a.index ) }
        for name, want in ( ( "sample_sha256", a.sample_sha256 ), ( "manifest_sha256", a.manifest_sha256 ) ):
            if shas[ name ] != want: raise ValueError( f"{name} is {shas[ name ]}, not the {want} named" )
        needs   = load_needs( a.needs, shas[ "sample_sha256" ] )
        results = check_all( needs, sample, index, groups )
    except ( OSError, ValueError, KeyError, AttributeError ) as e:
        print( f"need check: cannot read an input: {e}" )
        return 2
    results.update( shas )
    results[ "sample_size_expected" ] = a.size
    out = pathlib.Path( a.out_dir )
    out.mkdir( parents=True, exist_ok=True )
    ( out / "check-results.json" ).write_text( json.dumps( results, indent=2 ) + "\n", encoding="utf-8" )
    ( out / "resend-list.json" ).write_text( json.dumps( resend_list( results ), indent=2 ) + "\n", encoding="utf-8" )
    ok = results[ "summary" ][ "all_pass" ] and len( sample ) == a.size
    print( f"need check: {results[ 'summary' ][ 'checked' ]} of {len( sample )} checked, {results[ 'summary' ][ 'failed' ]} failed, exit {0 if ok else 1}" )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit( main() )

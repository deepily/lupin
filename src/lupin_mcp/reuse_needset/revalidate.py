"""
Re-check a frozen need set against a newer index, the day before the first scored run.

The command lists three things. A key symbol that was renamed or deleted. A definition added since the freeze that the
checker's search ranks near a matched need, which may be a new twin. A definition added since the freeze that the search
ranks near a nothing-exists need. Each flagged need becomes a reviewer item, with its reason kept apart from the item.
"""
import argparse
import collections
import json
import pathlib

from cosa.repo.symindex import build as sx_build
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import finalize, freeze, keys

REPORT_FORMAT = "needset-revalidation-1"
REPORT_FILE   = "needset-revalidation.json"
DELETED       = "deleted"
RENAMED       = "renamed"
NEW_TWIN      = "new_twin_candidate"
NEAR_NOTHING  = "near_nothing_need"
BROKEN_KEY    = "broken_key"
REFROZEN_DIR  = "refrozen"


def read_index( gen ):
    """Ensures: returns { id: record } of the searchable definitions of an index generation."""
    return { r[ "id" ]: r for r in sx_build.read_searchable( gen ) }


def load_frozen( frozen_dir, expected=None ):
    """
    Read a frozen need set and check that its copy is the one the manifest names.

    Requires:
        - frozen_dir holds the manifest, the final file and the frozen folder the draw wrote; expected is verify_manifest's, None for 400 needs

    Ensures:
        - returns ( manifest, needs, old index by id )
        - the frozen copy's three hashes equal the manifest's, so the diff is against the index the keys were written on

    Raises:
        - NeedsetError MANIFEST_MISMATCH from verify_manifest
        - NeedsetError INDEX_DIFFERS, VECTORS_DIFFER or FREEZE_INCOMPLETE from freeze.require_same
    """
    folder = pathlib.Path( frozen_dir )
    finalize.verify_manifest( folder / finalize.MANIFEST_FILE, expected )
    manifest = json.loads( ( folder / finalize.MANIFEST_FILE ).read_text( encoding="utf-8" ) )
    needs    = [ json.loads( l ) for l in ( folder / finalize.FINAL_FILE ).read_text( encoding="utf-8" ).splitlines() ]
    copy     = folder / freeze.FROZEN_DIR
    freeze.require_same( manifest, freeze.identity( copy / freeze.INDEX_SUBDIR, copy / freeze.VECTOR_SUBDIR ), "revalidate" )
    return manifest, needs, read_index( copy / freeze.INDEX_SUBDIR )


def _shape( rec ):
    """Ensures: returns what a rename keeps: the file, kind, signature and whole docstring."""
    return ( rec[ "file" ], rec[ "kind" ], rec[ "sig" ], rec[ "doc_full" ] )


def broken_keys( needs, old, new ):
    """
    List the key symbols the new index no longer holds.

    Requires:
        - needs are final needs; old and new map id to index record

    Ensures:
        - returns [ { need, symbol, state, renamed_to } ] sorted by need and symbol
        - state is renamed when exactly one id new to the index has the old record's file, kind, signature and docstring, else deleted
        - renamed_to is that id or None; a definition moved to another file or edited as it was renamed reads as deleted
        - a key symbol that is still present is never listed, whatever happened to its body
    """
    added = collections.defaultdict( list )
    for i, r in sorted( new.items() ):
        if i not in old: added[ _shape( r ) ].append( i )
    out = []
    for n in sorted( needs, key=lambda n: n[ "id" ] ):
        for s in sorted( n[ "key" ][ "symbols" ] ):
            if s in new: continue
            same  = added.get( _shape( old[ s ] ), [] ) if s in old else []
            moved = same[ 0 ] if len( same ) == 1 else None
            out.append( { "need": n[ "id" ], "symbol": s, "state": RENAMED if moved else DELETED, "renamed_to": moved } )
    return out


def near_new_definitions( needs, added, evidence, top ):
    """
    List, per need, the definitions added since the freeze that the search ranks near it.

    Requires:
        - added is the set of ids new to the index; evidence( text ) returns { words, vectors } id lists, best first
        - top is how many of each list count as near

    Ensures:
        - returns { need id: sorted ids } holding only needs with at least one such definition
    """
    out = {}
    for n in sorted( needs, key=lambda n: n[ "id" ] ):
        seen  = evidence( n[ "need" ] )
        found = sorted( ( set( seen[ "words" ][ :top ] ) | set( seen[ "vectors" ][ :top ] ) ) & added )
        if found: out[ n[ "id" ] ] = found
    return out


def gone_line( symbol_id, old ):
    """
    Describe a key symbol the new index lacks, so the reviewer sees what the key named.

    Ensures:
        - returns one line holding the id, the words no longer in the index, and the old kind, name, signature and first docstring line
        - a symbol the old index never held gets the id and the words only
    """
    r = old.get( symbol_id )
    if r is None: return f"{symbol_id} (no longer in the index)"
    first = ( r[ "doc_full" ].strip().splitlines() or [ "" ] )[ 0 ]
    return f"{symbol_id} (no longer in the index; it was {r[ 'kind' ]} {r[ 'name' ]}{r[ 'sig' ]}: {first})"


def revalidate( frozen_dir, new_gen, evidence, top, source_of, expected=None ):
    """
    Compare a frozen need set with a newer index.

    Requires:
        - frozen_dir is as for load_frozen; new_gen is the newer index generation
        - evidence( text ) ranks the newer index; source_of( id ) gives a definition's source text there
        - top is a positive number; expected is as for load_frozen

    Ensures:
        - returns { report, flags, items } and writes nothing
        - report holds the format, the manifest's hashes, the new index's, the count of added definitions, broken_keys, new_twins and near_nothing
        - flags is [ { id, reasons } ] sorted by need id; items is one reviewer item per flagged need, in flag order, with no reason in it
        - a broken-key need shows the reviewer the surviving key symbols, the renamed one's new id, the candidate twins and a line for each symbol that is gone; a nothing need shows the candidates

    Raises:
        - NeedsetError BAD_NEED when top is not a positive number
        - errors of load_frozen
    """
    if isinstance( top, bool ) or not isinstance( top, int ) or top < 1: raise er.NeedsetError( er.BAD_NEED, f"top must be a positive whole number, got {top!r}" )
    manifest, needs, old = load_frozen( frozen_dir, expected )
    new    = read_index( new_gen )
    added  = set( new ) - set( old )
    broken = broken_keys( [ n for n in needs if n[ "kind" ] != "nothing" ], old, new )
    near   = near_new_definitions( needs, added, evidence, top )
    by_id  = { n[ "id" ]: n for n in needs }
    twins  = { i: c for i, c in near.items() if by_id[ i ][ "kind" ] != "nothing" }
    nearno = { i: c for i, c in near.items() if by_id[ i ][ "kind" ] == "nothing" }
    reasons = {}
    for b in broken: reasons.setdefault( b[ "need" ], set() ).add( BROKEN_KEY )
    for i in twins: reasons.setdefault( i, set() ).add( NEW_TWIN )
    for i in nearno: reasons.setdefault( i, set() ).add( NEAR_NOTHING )
    flags  = [ { "id": i, "reasons": sorted( r ) } for i, r in sorted( reasons.items() ) ]
    items  = []
    for f in flags:
        need = by_id[ f[ "id" ] ]
        if need[ "kind" ] == "nothing": items.append( finalize.need_item( need, hits=[ source_of( c ) for c in near[ need[ "id" ] ] ] ) )
        else:
            gone   = [ s for s in need[ "key" ][ "symbols" ] if s not in new ]
            moved  = { b[ "renamed_to" ] for b in broken if b[ "need" ] == need[ "id" ] and b[ "renamed_to" ] }
            shown  = sorted( ( set( need[ "key" ][ "symbols" ] ) & set( new ) ) | moved | set( near.get( need[ "id" ], [] ) ) )
            items.append( finalize.need_item( need, key_texts=[ source_of( c ) for c in shown ] + [ gone_line( s, old ) for s in gone ] ) )
    report = { "format": REPORT_FORMAT, "frozen": { k: manifest[ k ] for k in freeze.IDENTITY_KEYS }, "new_index_symbols_sha": sx_build.read_header( new_gen )[ "symbols_sha" ],
               "index_before": len( old ), "index_after": len( new ), "added": len( added ), "removed": len( set( old ) - set( new ) ),
               "broken_keys": broken, "new_twins": twins, "near_nothing": nearno, "flagged": len( flags ) }
    return { "report": report, "flags": flags, "items": items }


def refreeze( frozen_dir, new_gen, new_vectors, dest, new, report_path, expected=None ):
    """
    Move a frozen set to the newer index and write its new manifest.

    Requires:
        - new is revalidate's result over the same frozen_dir and new_gen
        - dest is a folder that does not exist yet; expected is as for load_frozen
        - report_path is the path the new result's report was written to, so the manifest can name its hash

    Ensures:
        - writes dest/frozen (read-only), the unchanged final file, and a manifest with the new three hashes
        - the manifest keeps the old hashes under refrozen_from, with the old final hash and the report's hash, and passes verify_manifest
        - the need rows are not touched; a flagged need still waits for its reviewers

    Raises:
        - NeedsetError REVALIDATION_OPEN when the report still lists a broken key, since a refreeze would bless a key the index no longer has
        - NeedsetError FROZEN_COPY_EXISTS, FREEZE_INCOMPLETE and VECTORS_NOT_FROM_INDEX from freeze.freeze
    """
    broken = new[ "report" ][ "broken_keys" ]
    if broken: raise er.NeedsetError( er.REVALIDATION_OPEN, f"{len( broken )} key symbols are renamed or deleted, first: {broken[ 0 ][ 'need' ]} {broken[ 0 ][ 'symbol' ]}; fix those keys before the refreeze" )
    folder   = pathlib.Path( frozen_dir )
    old      = json.loads( ( folder / finalize.MANIFEST_FILE ).read_text( encoding="utf-8" ) )
    dest     = pathlib.Path( dest )
    got      = freeze.freeze( new_gen, new_vectors, dest / freeze.FROZEN_DIR )
    ( dest / finalize.FINAL_FILE ).write_bytes( ( folder / finalize.FINAL_FILE ).read_bytes() )
    manifest = dict( old, **got, refrozen_from={ **{ k: old[ k ] for k in freeze.IDENTITY_KEYS }, "final_sha256": old[ "final_sha256" ], "report_sha256": finalize.file_sha256( report_path ) } )
    ( dest / finalize.MANIFEST_FILE ).write_text( json.dumps( manifest, sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    finalize.verify_manifest( dest / finalize.MANIFEST_FILE, expected )
    return manifest


def source_reader( root, records ):
    """
    Build the function that reads a definition's source from a tree.

    Requires:
        - root is the checkout of the newer commit; records maps id to an index record with file, line and end_line

    Ensures:
        - returns source_of( id ) giving the id, then the lines of the definition
    """
    root = pathlib.Path( root )
    def source_of( symbol_id ):
        """Ensures: returns the symbol's id and its source lines from the tree."""
        r     = records[ symbol_id ]
        lines = ( root / r[ "file" ] ).read_text( encoding="utf-8" ).splitlines()
        return symbol_id + "\n" + "\n".join( lines[ r[ "line" ] - 1:r[ "end_line" ] ] )
    return source_of


def real_evidence( stage, vectors, embed, top ):
    """Ensures: returns evidence( text ), the word and vector search over the newer index."""
    return lambda text: keys.absence_evidence( text, stage, vectors, embed( text ), top )


def parse_args( argv ):
    """Ensures: returns the parsed command line; only --refreeze is optional."""
    ap = argparse.ArgumentParser( description=__doc__ )
    for name in ( "frozen-dir", "new-index", "new-vectors", "root", "query-cache-dir", "out" ): ap.add_argument( f"--{name}", required=True )
    ap.add_argument( "--top", type=int, required=True, help="how many of each search list count as near" )
    ap.add_argument( "--refreeze", help="a new folder to write the refrozen set into; refused while a key is broken" )
    return ap.parse_args( argv )


def load_parts( args ):  # pragma: no cover -- loads the real vector set and calls the live embeddings endpoint; main's test replaces it
    """Ensures: returns ( evidence, source_of ) over the newer index and tree."""
    from cosa.repo.symindex.candidates import candidate_stage, vector_build, vector_store
    records = sx_build.read_searchable( args.new_index )
    vectors = vector_store.load_vectors( args.new_vectors )
    client  = vector_build.EndpointClient()
    embed   = lambda text: vector_store.query_vectors( text, client, args.query_cache_dir, vectors.manifest )[ "concat" ]
    return real_evidence( candidate_stage.build_stage( records ), vectors, embed, args.top ), source_reader( args.root, { r[ "id" ]: r for r in records } )


def main( argv=None, parts=None ):
    """
    Run the re-validation from the command line.

    Requires:
        - parts( args ) returns ( evidence, source_of ); None uses load_parts

    Ensures:
        - writes needset-revalidation.json and needset-revalidation-items.json into --out, and returns the report
        - with --refreeze it then writes the new manifest and frozen copy into that folder
    """
    args = parse_args( argv )
    evidence, source_of = ( load_parts if parts is None else parts )( args )
    got = revalidate( args.frozen_dir, args.new_index, evidence, args.top, source_of )
    out = pathlib.Path( args.out )
    out.mkdir( parents=True, exist_ok=True )
    ( out / REPORT_FILE ).write_text( json.dumps( { **got[ "report" ], "flags": got[ "flags" ] }, sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    ( out / "needset-revalidation-items.json" ).write_text( json.dumps( got[ "items" ], sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    if args.refreeze: refreeze( args.frozen_dir, args.new_index, args.new_vectors, args.refreeze, got, out / REPORT_FILE )
    return got[ "report" ]


if __name__ == "__main__":  # pragma: no cover -- the guard line only; main() has its own test
    print( json.dumps( main(), indent=4 ) )

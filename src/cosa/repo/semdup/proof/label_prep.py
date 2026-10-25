"""Label preparation for the proof: planted and monolith pairs, blind packets, answer key."""
import argparse
import asyncio
import concurrent.futures
import hashlib
import json
import pathlib
import random
import re
import shutil
import subprocess
import tempfile

import cosa.utils.util as cu
from cosa.repo.doc_lint import model_transport
from cosa.repo.labelling import items as lb_items
from cosa.repo.labelling import packets as lb_packets
from cosa.repo.semdup import blind, body_vectors, extract, frozen, structural
from cosa.repo.semdup import config as cfg_mod
from cosa.repo.semdup.proof import monolith_pairs, plant
from cosa.repo.symindex import dups, js_index, need_input, need_writer
from cosa.repo.symindex import spec as sp
from cosa.repo.symindex.candidates import vector_build

MONOLITH_FILE  = "src/lupin_app/static/js/notifications.js"
MONOLITH_BLOB  = "f7473f11b19d552da34966cb5bb04bd3ed6bb3cb"
CLIENT_DIR     = "src/lupin_app/static/js"
PLANTED_COUNT  = 60
ALIKE_EVERY    = 3
PER_SOURCE     = 30
THREADS        = 6
STRATA         = ( "fable-planted", "opus-work-alike" )
REWRITE_MODEL  = "claude-fable-5-1"
ALIKE_MODEL    = "claude-opus-5-5"
SENTENCE_MODEL = need_writer.DEFAULT_MODEL
LANG_NAMES     = { "py": "Python", "ts": "TypeScript" }
FENCE          = re.compile( r"^```[A-Za-z]*\s*\n(.*?)\n?```\s*$", re.DOTALL )
ALIKE_SYSTEM   = "You write one function from a short description. Reply with the function source only, in the language named, with no comments about the description."
KEY_FILE       = "answer-key.json"
WRAPPER        = "PlantedWrapper"
PLANTED_FILE   = "planted.json"
SEED           = 20261025
REVIEWERS      = ( "rick", "reviewer-2" )


def make_ask( complete, model ):
    """
    Wrap the async model call as the sync ask that plant_rewrite takes.

    Requires:
        - complete is model_transport.complete or a stand-in with its ( model, system, user ) signature; model is a model id

    Ensures:
        - returns ask( system, user ) giving the reply text, each call run to the end before it returns
    """
    return lambda system, user: unfence( asyncio.run( complete( model, system, user ) ) )


def unfence( text ):
    """
    Remove one surrounding code fence from a reply.

    Requires:
        - text is a string

    Ensures:
        - returns the text between a leading ``` line and a closing ```, stripped, when the whole reply is one fenced block
        - returns the reply stripped otherwise
    """
    found = FENCE.match( text.strip() )
    return ( found.group( 1 ) if found else text ).strip()


def script_shape( text ):
    """
    Return the shingle set of the first function in script source, or None.

    Requires:
        - text is a function, an arrow function in a const, or a class member, as the definitions of the client are

    Ensures:
        - returns dups.shingles_of of the node kinds of the first function-like definition, read by the TypeScript compiler
        - a source that does not parse alone is tried once inside a class body, so a bare method counts
        - returns None when neither reading holds a function
    """
    for wrapped in ( text, f"class Wrapper {{\n{text}\n}}\n" ):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path( tmp ) / "shape.ts"
            path.write_text( wrapped, encoding="utf-8" )
            found = js_index.extract_js_shapes( tmp, [ path ] )[ "defs" ]
        if found: return dups.shingles_of( found[ 0 ][ "kinds" ] )
    return None


def _need_for( rec, root ):
    """Return the stripped need input for a definition, by need_input or strip_names."""
    if rec[ "lang" ] == "py": return plant.python_need( rec, root )
    text, names = plant.strip_names( rec[ "text" ], rec[ "declared" ], rec[ "name" ].split( "." )[ -1 ] )
    kind        = "method" if "." in rec[ "name" ] and "<locals>" not in rec[ "name" ] else "function"
    return need_input.NeedInput( member_id=rec[ "id" ], kind=kind, text=text, forbidden=names )


def write_sentence( need, lang, ask ):
    """
    Ask for the one-sentence need of a stripped definition until it passes the form check.

    Requires:
        - need is a NeedInput; lang is "py" or "ts"; ask takes ( system prompt, user prompt ) and returns the reply text

    Ensures:
        - returns the first sentence for which need_writer.check_form finds no failure
        - returns None after need_writer.MAX_ATTEMPTS tries, each retry naming the last failure kinds
    """
    failures = None
    for _ in range( need_writer.MAX_ATTEMPTS ):
        sentence = need_writer.extract_sentence( ask( need_writer.system_prompt( lang ), need_writer.build_prompt( need, failures=failures, write_lang=lang ) ) )
        failures = need_writer.check_form( sentence, need )
        if not failures: return sentence
    return None


def plant_one( rec, root, method, asks, shape_of ):
    """
    Plant one pair for an original, by a Fable rewrite or an Opus work-alike.

    Requires:
        - rec is a definition record; method is "fable-planted" or "opus-work-alike"
        - asks holds rewrite, sentence and alike, each an ask( system, user ); shape_of reads a source's shingles

    Ensures:
        - returns { original, stratum, rewrite_text, ... } with status "planted", or status "failed" and the failure kinds when no rewrite passed
        - a definition need_input cannot resolve, and a rewrite that cannot be extracted as a definition, are failures naming the reason, so the next original is tried and the run goes on
        - a Fable rewrite is made by plant_rewrite with the banned words; an Opus work-alike is written from the need sentence alone, never seeing the original
        - a work-alike must parse and must not have the original's shape; it is not checked for banned words because it never saw them
    """
    lang  = "py" if rec[ "lang" ] == "py" else "ts"
    base  = { "original": rec[ "id" ], "stratum": method }
    try:
        need = _need_for( rec, root )
    except ValueError as e:
        return { **base, "status": "failed", "failures": [ { "need": str( e ) } ] }
    if method == STRATA[ 0 ]:
        banned = plant.banned_names( rec, need.forbidden if rec[ "lang" ] == "py" else [] )
        made   = plant.plant_rewrite( rec[ "text" ], banned, asks[ "rewrite" ], shape_of )
        if made[ "status" ] == "failed": return { **base, "status": "failed", "failures": made[ "failures" ] }
        return checked( rec, { **base, "status": "planted", "rewrite_text": made[ "rewrite" ], "tries": made[ "tries" ] } )
    sentence = write_sentence( need, lang, asks[ "sentence" ] )
    if sentence is None: return { **base, "status": "failed", "failures": [ { "sentence": "no sentence passed the form check" } ] }
    reply    = asks[ "alike" ]( ALIKE_SYSTEM, f"Language: {LANG_NAMES[ rec[ 'lang' ] ]}\nDescription: {sentence}" )
    failed   = plant.check_rewrite( rec[ "text" ], reply, [], shape_of )
    if failed: return { **base, "status": "failed", "failures": [ failed ] }
    return checked( rec, { **base, "status": "planted", "rewrite_text": reply, "tries": 1, "sentence": sentence } )


def plant_all( originals, root, asks, shape_of, count=PLANTED_COUNT, threads=THREADS, alike_every=ALIKE_EVERY ):
    """
    Plant pairs for originals in waves until count are planted or the originals run out.

    Requires:
        - originals are definition records in the order they are to be tried, script and Python in the shares wanted
        - asks, shape_of as plant_one takes them

    Ensures:
        - every ALIKE_EVERY-th original in the order is an Opus work-alike and the rest Fable rewrites
        - returns { planted, failed }: the planted results, at most count, in the order of originals, and the failed ones with their failure kinds
        - the next wave tries only as many originals as there are places still to fill
    """
    planted, failed, nxt = [], [], 0
    with concurrent.futures.ThreadPoolExecutor( max_workers=threads ) as pool:
        while len( planted ) < count and nxt < len( originals ):
            wave = originals[ nxt : nxt + ( count - len( planted ) ) ]
            jobs = [ pool.submit( plant_one, rec, root, STRATA[ 1 ] if ( nxt + i ) % alike_every == 0 else STRATA[ 0 ], asks, shape_of ) for i, rec in enumerate( wave ) ]
            nxt += len( wave )
            for job in jobs: ( planted if ( r := job.result() )[ "status" ] == "planted" else failed ).append( r )
    return { "planted": planted, "failed": failed }


def monolith_definitions( root, min_nodes ):
    """
    Extract the monolith's definitions from a copy of its pinned bytes.

    Requires:
        - root is the repository root holding MONOLITH_FILE

    Ensures:
        - raises unless the file is the pinned blob; copies it to a temporary tree at the same relative path, so ids equal those of an extraction from root
        - returns ( temporary tree path as TemporaryDirectory, definitions of min_nodes nodes or more, in extraction order )

    Raises:
        - ValueError if the file is not the pinned blob
    """
    source = pathlib.Path( root ) / MONOLITH_FILE
    monolith_pairs.check_pin( source, MONOLITH_BLOB )
    tmp    = tempfile.TemporaryDirectory()
    copy   = pathlib.Path( tmp.name ) / MONOLITH_FILE
    copy.parent.mkdir( parents=True )
    shutil.copyfile( source, copy )
    report = extract.extract_tree( tmp.name, [ copy ], "server" )
    extract.completeness( report )
    return tmp, [ d for d in report[ "definitions" ] if d[ "nodes" ] >= min_nodes ]


def monolith_candidates( root, cfg, client, cache_dir, per_source=PER_SOURCE, nominated=() ):
    """
    Build the tagged candidate pairs of the monolith from its two automatic sources.

    Requires:
        - cfg is the frozen configuration; client embeds bodies (body_vectors.ensure_vectors); nominated is empty unless a person named pairs

    Ensures:
        - returns { defs, pairs, blob }: the monolith's definitions, up to per_source pairs from each source tagged structural and neighbour (and the nominated ones), and the pinned blob sha
        - the structural source is jscpd over a copy of the pinned file
    """
    tmp, defs = monolith_definitions( root, cfg[ "min_nodes" ] )
    with tmp:
        report = structural.run_jscpd( tmp.name, [ CLIENT_DIR ], cfg )
    pairs   = structural.parse_jscpd( report, defs, cfg[ "clone_cover" ] )
    vectors = body_vectors.ensure_vectors( defs, client, cache_dir, cfg[ "body_chars" ] )[ "vectors" ]
    tagged  = monolith_pairs.candidate_pairs( defs, pairs, vectors, [ list( n ) for n in nominated ], per_source )
    return { "defs": defs, "pairs": monolith_pairs.assemble_pairs( tagged ), "blob": MONOLITH_BLOB }


def unordered_key( a, b ):
    """Return the key of an unordered pair of definition ids, as proof_run.label_key writes it."""
    return "|".join( sorted( ( a, b ) ) )


def item_id( a, b ):
    """Return an opaque item id for a pair that carries no source, stratum or order."""
    return "pair-" + hashlib.sha256( unordered_key( a, b ).encode( "utf-8" ) ).hexdigest()[ :10 ]


def pair_item( first, second, seed ):
    """
    Build one blind item from two definition records.

    Requires:
        - first and second are definition records with id and text

    Ensures:
        - returns { item, row }: a semdup_pair item whose payload is the two sources, one as a and the other as b, in an order drawn by the seed and the pair key, and a key row naming which id is a
        - the item holds nothing but the two texts
    """
    mine    = sorted( [ first, second ], key=lambda d: d[ "id" ] )
    random.Random( f"{seed}|{unordered_key( first[ 'id' ], second[ 'id' ] )}" ).shuffle( mine )
    return { "item": lb_items.make_item( lb_items.SEMDUP_PAIR, item_id( first[ "id" ], second[ "id" ] ), { "a": mine[ 0 ][ "text" ], "b": mine[ 1 ][ "text" ] } ),
             "row": { "a": mine[ 0 ][ "id" ], "b": mine[ 1 ][ "id" ] } }


def rewrite_record( result, original, folder, number ):
    """
    Make the definition record of a planted rewrite, new-origin, from its text.

    Requires:
        - result is a planted result of plant_one; original is its original's record; folder is a writable directory; number makes the folder unique

    Ensures:
        - returns the first definition extracted from the rewrite, written under folder/<number> at the original's own file path, so nothing in the record says it was planted
        - a script rewrite that does not parse alone is tried inside a class body, and the class name is taken off the definition's name
        - the id is the one definition_id gives the new-origin record
        - raises when the extraction finds no definition

    Raises:
        - ValueError if no definition could be extracted from the rewrite
    """
    root = pathlib.Path( folder ) / f"{number:03d}"
    path = root / original[ "file" ]
    path.parent.mkdir( parents=True, exist_ok=True )
    for wrapped in ( False, True ):
        path.write_text( f"class {WRAPPER} {{\n{result[ 'rewrite_text' ]}\n}}\n" if wrapped else result[ "rewrite_text" ] + "\n", encoding="utf-8" )
        found = extract.extract_tree( root, [ path ], "new" )[ "definitions" ]
        if found or original[ "lang" ] == "py": break
    if not found: raise ValueError( f"no definition could be extracted from the rewrite of {original[ 'id' ]}" )
    made = found[ 0 ]
    if wrapped:
        made[ "name" ] = made[ "name" ].removeprefix( f"{WRAPPER}." )
        made[ "id" ]   = extract.definition_id( "new", made[ "file" ], made[ "name" ], made[ "text" ] )
    return made


def checked( original, planted ):
    """
    Turn a planted result into a failure when its rewrite cannot be made into a definition.

    Requires:
        - original is the definition record; planted is a planted result of plant_one

    Ensures:
        - returns planted unchanged when rewrite_record can extract a definition from it
        - otherwise returns the same result with status "failed" and the reason, so the next original takes its place
    """
    with tempfile.TemporaryDirectory() as tmp:
        try:
            rewrite_record( planted, original, tmp, 0 )
        except ValueError as e:
            return { "original": planted[ "original" ], "stratum": planted[ "stratum" ], "status": "failed", "failures": [ { "extract": str( e ) } ] }
    return planted


def prepare( planted, mono, reviewers, seed, out_dir, config_sha ):
    """
    Write the blind packets and, apart from them, the answer key.

    Requires:
        - planted is a list of { original, rewrite, stratum } with both sides definition records; mono is monolith_candidates' result
        - reviewers are two or more names for export_packets

    Ensures:
        - writes <out_dir>/packets/packet-<reviewer>.jsonl with the same items in a different order each, and <out_dir>/key/answer-key.json once
        - a packet holds item ids and the two texts only; the key maps each item id to its ids, which side is a, its kind and its stratum or source
        - returns { packets, key, items }

    Raises:
        - FileExistsError if the key already exists, before anything is written
    """
    by_id, built = { d[ "id" ]: d for d in mono[ "defs" ] }, []
    rows  = {}
    for p in planted:
        made = pair_item( p[ "original" ], p[ "rewrite" ], seed )
        rows[ made[ "item" ][ "item_id" ] ] = { **made[ "row" ], "kind": "planted", "stratum": p[ "stratum" ] }
        built.append( made[ "item" ] )
    for p in mono[ "pairs" ]:
        made = pair_item( by_id[ p[ "ids" ][ 0 ] ], by_id[ p[ "ids" ][ 1 ] ], seed )
        rows[ made[ "item" ][ "item_id" ] ] = { **made[ "row" ], "kind": "monolith", "stratum": f"monolith:{p[ 'source' ]}" }
        built.append( made[ "item" ] )
    out   = pathlib.Path( out_dir )
    key   = out / "key" / KEY_FILE
    if key.exists(): raise FileExistsError( f"{key} already exists; packets are made once" )
    key.parent.mkdir( parents=True, exist_ok=True )
    paths = lb_packets.export_packets( built, reviewers, seed, out / "packets" )
    record = { "config_sha": config_sha, "seed": seed, "monolith_blob": mono[ "blob" ], "items": rows }
    with open( key, "x", encoding="utf-8" ) as f: json.dump( record, f, indent=2, sort_keys=True )
    return { "packets": { r: str( p ) for r, p in paths.items() }, "key": str( key ), "items": len( built ) }


def select_pools( server_defs, client_defs, cfg, seed, count=PLANTED_COUNT ):
    """
    Choose the originals to plant from, twice as many as needed.

    Requires:
        - server_defs and client_defs are server-origin definition records; the monolith is not among client_defs

    Ensures:
        - definitions that carry a scrub token, and nested ones (named <locals>, which need_input cannot address), are left out, and the rest are drawn by plant.select_originals with the frozen minimum
        - returns { script, python }: lists of originals in id order, each long enough to fill its share of count twice over
    """
    scrub  = blind.scrub_tokens( () )
    pool   = [ *server_defs, *client_defs ]
    banned = set( blind.breaching_ids( pool, scrub ) )
    drawn  = plant.select_originals( [ d for d in pool if d[ "id" ] not in banned and "<locals>" not in d[ "name" ] ], count * 2, seed, cfg[ "min_nodes" ] )
    return { "script": [ d for d in drawn if d[ "lang" ] != "py" ], "python": [ d for d in drawn if d[ "lang" ] == "py" ] }


def run( root, out_dir, cfg, wiring, seed=SEED, count=PLANTED_COUNT, reviewers=REVIEWERS ):
    """
    Plant the pairs, collect the monolith pairs and write the packets and key.

    Requires:
        - cfg is the verified frozen configuration
        - wiring holds server_defs and client_defs (server-origin records, the monolith left out of client_defs), asks, shape_of ( a dict of readers keyed py and ts ), client and cache_dir

    Ensures:
        - plants count pairs, 60% script and 40% Python, one third of each share as Opus work-alikes, each rewrite extracted to a new-origin record
        - the planted pairs are written to <out>/key/planted.json before the monolith step, and a run that finds the file reads it instead of asking the models again, so a later failure costs no model call
        - returns prepare's result plus planted and failed counts by stratum, so a short count is visible
    """
    folder = pathlib.Path( out_dir ) / "key"
    saved  = folder / PLANTED_FILE
    if saved.exists():
        stored  = json.loads( saved.read_text( encoding="utf-8" ) )
        planted, failed = stored[ "planted" ], stored[ "failed" ]
    else:
        pools   = select_pools( wiring[ "server_defs" ], wiring[ "client_defs" ], cfg, seed, count )
        want    = round( count * plant.SCRIPT_SHARE )
        made    = [ plant_all( pools[ "script" ], root, wiring[ "asks" ], wiring[ "shape_of" ][ "ts" ], want ), plant_all( pools[ "python" ], root, wiring[ "asks" ], wiring[ "shape_of" ][ "py" ], count - want ) ]
        by_id   = { d[ "id" ]: d for d in [ *pools[ "script" ], *pools[ "python" ] ] }
        planted = [ { "original": by_id[ r[ "original" ] ], "rewrite": rewrite_record( r, by_id[ r[ "original" ] ], folder / "rewrites", i ), "stratum": r[ "stratum" ] }
                    for i, r in enumerate( [ *made[ 0 ][ "planted" ], *made[ 1 ][ "planted" ] ] ) ]
        failed  = [ r for m in made for r in m[ "failed" ] ]
        folder.mkdir( parents=True, exist_ok=True )
        with open( saved, "x", encoding="utf-8" ) as f: json.dump( { "planted": planted, "failed": failed }, f, indent=2, sort_keys=True )
    mono   = monolith_candidates( root, cfg, wiring[ "client" ], wiring[ "cache_dir" ] )
    out    = prepare( planted, mono, reviewers, seed, out_dir, cfg[ "config_sha" ] )
    return { **out, "planted": { s: sum( 1 for p in planted if p[ "stratum" ] == s ) for s in STRATA }, "failed": len( failed ),
             "monolith": { src: sum( 1 for p in mono[ "pairs" ] if p[ "source" ] == src ) for src in monolith_pairs.SOURCES } }


def live_wiring( root, cache_dir, complete=model_transport.complete, client=None ):
    """
    Build the wiring that talks to the real tree and the real models.

    Requires:
        - root is the repository root; cache_dir is the vectors folder; complete is the async model call; client embeds bodies, or None for the FastAPI endpoints

    Ensures:
        - returns the dict run takes: server-origin definitions of every Python file of the spec and of the tracked client script files except the monolith,
          three asks (Fable for rewrites, the need-writer model for sentences, Opus for work-alikes) and the shape readers
    """
    py_files = [ f for f in sp.all_files( sp.spec_for( root ) ) if str( f ).endswith( ".py" ) ]
    tracked  = subprocess.run( [ "git", "ls-files", "--", CLIENT_DIR ], cwd=root, capture_output=True, text=True, check=True ).stdout.split()
    js_files = [ pathlib.Path( root ) / f for f in tracked if f.endswith( extract.SCRIPT_SUFFIXES ) and not f.endswith( ( ".d.ts", ".min.js" ) ) and f != MONOLITH_FILE ]
    return { "server_defs": extract.extract_tree( root, py_files, "server" )[ "definitions" ], "client_defs": extract.extract_tree( root, js_files, "server" )[ "definitions" ],
             "asks": { "rewrite": make_ask( complete, REWRITE_MODEL ), "sentence": make_ask( complete, SENTENCE_MODEL ), "alike": make_ask( complete, ALIKE_MODEL ) },
             "shape_of": { "py": plant.python_shape, "ts": script_shape },
             "client": client if client is not None else vector_build.EndpointClient(), "cache_dir": cache_dir }


def main( argv=None, make_wiring=live_wiring ):
    """
    Prepare the proof labelling packets and print what was written.

    Requires:
        - argv holds --out, a folder that does not hold an answer key yet, and optionally --claude-cli-path, a binary new enough for the models; make_wiring( root, cache_dir ) gives the wiring

    Ensures:
        - checks the frozen configuration against the live one first, then runs run() under the project root and prints the result as JSON
        - returns 0

    Raises:
        - SemdupError CONFIG_DRIFT if the frozen file is not the live configuration
    """
    parser = argparse.ArgumentParser( description="Prepare the Phase 2 proof labelling packets." )
    parser.add_argument( "--out", required=True )
    parser.add_argument( "--claude-cli-path", default=None )
    args   = parser.parse_args( argv )
    model_transport.configure( args.claude_cli_path )
    root   = cu.get_project_root()
    cfg    = cfg_mod.verify_frozen( frozen.frozen_path(), frozen.live_config() )
    result = run( root, args.out, cfg, make_wiring( root, pathlib.Path( args.out ) / "vectors" ) )
    print( json.dumps( result, indent=2, sort_keys=True ) )
    return 0


if __name__ == "__main__": raise SystemExit( main() )  # pragma: no cover - command-line entry point

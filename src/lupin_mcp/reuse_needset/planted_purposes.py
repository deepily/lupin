"""
Purpose lines for the positive control's planted rewrites, written the production way.

A real index entry carries a one-line purpose that a bounded Claude Code job wrote once.
A planted rewrite used to carry none, so its prose and vector text were poorer than any real entry's.
This module gives each rewrite its line through the same writer, prompt, screen and version string as production.
The job reads a copy of each rewrite's text, kept in a gitignored file of the run folder. A small symbols file points at the copy.
The planted entry itself keeps the rewrite's recorded file, which the strip and the judge read.
"""
import argparse
import json
import os
import pathlib
import subprocess

from cosa.repo.symindex import candidate_build
from cosa.repo.symindex.candidates import purpose_lines as pl
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import planted_pool, positive_control

SOURCE_DIR  = "planted-src"
SYMBOLS     = "planted-symbols.jsonl"
OUT_DIR     = "purpose-plants"
STORE       = "purpose.jsonl"
SUFFIX_OF   = { "py": "py", "ts": "ts" }


def lines_path( run_dir ):
    """Ensures: returns the plants' purpose.jsonl path inside the run folder."""
    return f"{run_dir}/{OUT_DIR}/{STORE}"


def is_ignored( path, main_root ):
    """
    Say whether git ignores a path of the main checkout.

    Requires:
        - main_root is a git working tree

    Ensures:
        - returns True when git check-ignore answers that the path is ignored, False when it is not
    """
    return subprocess.run( [ "git", "-C", str( main_root ), "check-ignore", "-q", str( path ) ], capture_output=True ).returncode == 0


def stage_sources( pairs, run_dir, main_root ):
    """
    Copy each rewrite's text to a file the purpose job can read, and list its symbols.

    Requires:
        - pairs come from positive_control.load_pairs; each rewrite holds id, lang, name, sig and text
        - run_dir is a folder under main_root, the checkout the job container mounts, and git ignores the files made there

    Ensures:
        - writes planted-src/<rewrite id>.<py|ts> and planted-symbols.jsonl in the run folder, and returns the symbols rows in pair order
        - each row names the copy by its path from main_root, line 1 and the copy's last line, and holds the plant's pin, so the writer's answer lands on the entry
        - nothing is written outside the run folder

    Raises:
        - NeedsetError PLANT_SOURCE_OUTSIDE when run_dir is not under main_root
        - NeedsetError PLANT_SOURCE_TRACKED when git would track a file made there
        - NeedsetError PLANT_LANG_UNKNOWN for a rewrite language with no file suffix
    """
    run, root = pathlib.Path( run_dir ).resolve(), pathlib.Path( main_root ).resolve()
    if root not in run.parents: raise er.NeedsetError( er.PLANT_SOURCE_OUTSIDE, f"{run} is not under the main checkout {root}, which the job container mounts" )
    folder = run / SOURCE_DIR
    folder.mkdir( parents=True, exist_ok=True )
    rows   = []
    for p in pairs:
        rw = p[ "rewrite" ]
        if rw[ "lang" ] not in SUFFIX_OF: raise er.NeedsetError( er.PLANT_LANG_UNKNOWN, f"{rw[ 'id' ]}: language {rw[ 'lang' ]!r} has no file suffix" )
        copy_path = folder / f"{rw[ 'id' ]}.{SUFFIX_OF[ rw[ 'lang' ] ]}"
        if not is_ignored( copy_path, root ): raise er.NeedsetError( er.PLANT_SOURCE_TRACKED, f"{copy_path}: git does not ignore it, so it could be committed" )
        copy_path.write_text( rw[ "text" ], encoding="utf-8" )
        entry = planted_pool.planted_entry( rw )
        rows.append( { "id": rw[ "id" ], "file": os.path.relpath( copy_path, root ), "line": 1, "end_line": len( rw[ "text" ].splitlines() ), "name": rw[ "name" ], "sig": rw[ "sig" ],
                       "lang": rw[ "lang" ], "kind": "function", "module": entry[ "module" ], "doc": "", "doc_full": "", "pin": entry[ "pin" ], "public": entry[ "scope" ] == "public", "scope": entry[ "scope" ] } )
    ( run / SYMBOLS ).write_text( "".join( json.dumps( r, sort_keys=True ) + "\n" for r in rows ), encoding="utf-8" )
    return rows


def write_lines( pairs, run_dir, main_root, writer, screen, writer_version=candidate_build.WRITER_VERSION, write=pl.write_purpose_lines ):
    """
    Write the purpose lines of the plants into the run folder's own store.

    Requires:
        - pairs and run_dir are as stage_sources takes them; writer takes a list of ids and returns { id: purpose }
        - screen is a purpose_lines.Screen; write is purpose_lines.write_purpose_lines or a stand-in with its signature

    Ensures:
        - the sources and the symbols file are staged first, then the writer is asked for the plants that hold no stored line
        - the store is the run folder's, never the live purpose store, and a stored row is kept as it is
        - returns the writer's report { written, kept, dropped_screen, dropped_output, missing }

    Raises:
        - whatever stage_sources and the writer raise
    """
    stage_sources( pairs, run_dir, main_root )
    entries = [ planted_pool.planted_entry( p[ "rewrite" ] ) for p in pairs ]
    return write( entries, writer, lines_path( run_dir ), writer_version, screen )


def load_lines( store_path, pairs ):
    """
    Read the plants' lines from a store.

    Requires:
        - store_path is a purpose.jsonl path, or names no file; pairs come from load_pairs

    Ensures:
        - returns ( { pin: purpose line } for the plants that hold one, [ rewrite id ] for the plants that hold none, in pair order )
        - a store that does not exist holds no line, so every plant is listed
    """
    stored = pl.load_lines( store_path )
    lines, without = {}, []
    for p in pairs:
        pin = planted_pool.planted_entry( p[ "rewrite" ] )[ "pin" ]
        if pin in stored and stored[ pin ][ "purpose" ].strip(): lines[ pin ] = stored[ pin ][ "purpose" ].strip()
        else: without.append( p[ "rewrite" ][ "id" ] )
    return lines, without


def merged_store( live_path, lines, out_path ):
    """
    Write a purpose store of the live lines and the plants' lines.

    Requires:
        - live_path is the live purpose.jsonl, or None; lines is { pin: purpose line }

    Ensures:
        - out_path holds every row of the live store, then one row for each plant line whose pin the live store lacks
        - the live store is only read
        - returns out_path
    """
    path = pathlib.Path( out_path )
    path.parent.mkdir( parents=True, exist_ok=True )
    live = pathlib.Path( live_path ).read_text( encoding="utf-8" ) if live_path is not None else ""
    live = live if live == "" or live.endswith( "\n" ) else live + "\n"
    held = set( pl.load_lines( live_path ) ) if live_path is not None else set()
    path.write_text( live + "".join( json.dumps( { "pin": pin, "purpose": line }, sort_keys=True ) + "\n" for pin, line in sorted( lines.items() ) if pin not in held ), encoding="utf-8" )
    return str( path )


def main( argv=None, environ=None, writer_factory=None, screen=None ):
    """
    Command line entry: write the plants' purpose lines with one bounded job.

    Requires:
        - environ holds LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and _PASSWORD unless writer_factory is given
        - the run folder is under the main checkout, and the dev server is up

    Ensures:
        - prints the writer's report as JSON and returns 0
        - writer_factory( root, base_url, environ, index, out_dir ) is candidate_build.make_job_writer unless a test hands another
    """
    environ = os.environ if environ is None else environ
    parser  = argparse.ArgumentParser( description="Write purpose lines for the positive control's planted rewrites." )
    parser.add_argument( "--root", required=True, help="the main checkout the job container mounts" )
    parser.add_argument( "--run-dir", required=True )
    parser.add_argument( "--planted", required=True )
    parser.add_argument( "--base-url", default=environ.get( "LUPIN_APP_SERVER_URL", "http://localhost:7999" ) )
    args    = parser.parse_args( argv )
    pairs   = positive_control.load_pairs( args.planted )
    make    = candidate_build.make_job_writer if writer_factory is None else writer_factory
    writer  = make( args.root, args.base_url, environ, index=f"{args.run_dir}/{SYMBOLS}", out_dir=f"{args.run_dir}/{OUT_DIR}" )
    report  = write_lines( pairs, args.run_dir, args.root, writer, pl.default_screen() if screen is None else screen )
    print( json.dumps( report, indent=4, sort_keys=True ) )
    return 0


if __name__ == "__main__":  # pragma: no cover  reason: the command line entry; main is tested with stand-ins
    import sys
    sys.exit( main() )

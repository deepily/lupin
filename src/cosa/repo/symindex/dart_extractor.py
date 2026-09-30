"""
Dart extractor for the symbol index: declarations of a Flutter tree, read with the Dart analyzer.

Implements the extractor contract in extractor_contract for language "dart". The parse is
syntactic only (the analyzer's parseString), run by dart_extract.dart inside a scratch pub
project under the repo's data directory, so nothing is written into the tree being indexed and
no `pub get` runs there.
"""

import json
import os
import shutil
import subprocess
import sys

import cosa.utils.util as cu

from .errors import DependencyMissing
from .extractor_contract import validate_record

ANALYZER_VERSION = "7.7.1"
PIN_ALGORITHM    = f"dart-analyzer-parseString/{ANALYZER_VERSION}"
SCRATCH_NAME     = "dart-scratch"
SCRIPT_REL       = "/src/cosa/repo/symindex/dart_extract.dart"
PUBSPEC          = f"name: dart_symbols\npublish_to: none\nenvironment:\n  sdk: ^3.6.0\ndependencies:\n  analyzer: {ANALYZER_VERSION}\n"
RUN_TIMEOUT      = 600


def sibling_dart():
    """
    Find the Flutter SDK's dart beside the lupin repository, where lupin-mobile keeps it.

    Requires:
        - LUPIN_ROOT names a lupin checkout or one of its worktrees

    Ensures:
        - walks up from the project root and returns the first lupin-mobile/flutter/bin/dart found
          beside an ancestor, which covers the main checkout and any worktree under .claude/worktrees
        - returns None when there is none

    Raises:
        - nothing
    """
    here = os.path.abspath( cu.get_project_root() )
    while here != os.path.dirname( here ):
        candidate = os.path.join( here, "lupin-mobile", "flutter", "bin", "dart" )
        if os.path.exists( candidate ): return candidate
        here = os.path.dirname( here )
    return None


def find_dart( root ):
    """
    Locate the dart executable.

    Requires:
        - root is the index root, a git working-tree root, or None when it is not known

    Ensures:
        - returns the first of: the LUPIN_DART override, root/flutter/bin/dart (only when root
          is given), dart on the search path, the lupin-mobile SDK beside the lupin checkout
        - returns None when none exists

    Raises:
        - nothing
    """
    override = os.environ.get( "LUPIN_DART" )
    if override and os.path.exists( override ): return override
    if root is not None:
        bundled = os.path.join( str( root ), "flutter", "bin", "dart" )
        if os.path.exists( bundled ): return bundled
    return shutil.which( "dart" ) or sibling_dart()


def check_dependencies( root=None ):
    """
    Say whether Dart and the analyzer package are usable, without extracting anything.

    Requires:
        - root is the index root, or None to look only at LUPIN_DART and the search path

    Ensures:
        - returns None when dart is found and the analyzer package is in the pub cache
        - the pub cache is PUB_CACHE, else ~/.pub-cache

    Raises:
        - DependencyMissing with what "dart" when no dart executable is found
        - DependencyMissing with what "analyzer" when the pinned analyzer is not in the pub cache
    """
    if find_dart( root ) is None: raise DependencyMissing( "dart", "no flutter/bin/dart under the index root, no LUPIN_DART, none on the search path" )
    cache = os.environ.get( "PUB_CACHE" ) or os.path.join( os.path.expanduser( "~" ), ".pub-cache" )
    if not os.path.isdir( os.path.join( cache, "hosted", "pub.dev", f"analyzer-{ANALYZER_VERSION}" ) ):
        raise DependencyMissing( "analyzer", f"analyzer-{ANALYZER_VERSION} is not in the pub cache {cache}" )


def _write_if_changed( path, text ):
    """
    Write a text file only when its content differs.

    Requires:
        - the parent directory of path exists

    Ensures:
        - returns True when the file was written, False when it already held text
        - the file is UTF-8

    Raises:
        - OSError when the write fails
    """
    current = None
    if os.path.exists( path ):
        with open( path, encoding="utf-8" ) as handle: current = handle.read()
    if current == text: return False
    with open( path, "w", encoding="utf-8" ) as handle: handle.write( text )
    return True


def prepare_scratch( dart, data_root, runner=subprocess.run ):
    """
    Create or refresh the scratch pub project that holds the extractor script.

    Requires:
        - dart is the path of a dart executable
        - data_root is the repo's own data directory, never the tree being indexed

    Ensures:
        - returns the scratch directory, under data_root, with pubspec.yaml, bin/dart_extract.dart
          and resolved packages
        - `pub get` runs offline first and online only when the offline run fails
        - an unchanged project with resolved packages skips `pub get`

    Raises:
        - DependencyMissing when the analyzer package cannot be resolved
        - OSError when the project files cannot be written
    """
    scratch = os.path.join( str( data_root ), SCRATCH_NAME )
    os.makedirs( os.path.join( scratch, "bin" ), exist_ok=True )
    with open( cu.get_project_root() + SCRIPT_REL, encoding="utf-8" ) as handle: script = handle.read()
    changed  = _write_if_changed( os.path.join( scratch, "pubspec.yaml" ), PUBSPEC )
    changed |= _write_if_changed( os.path.join( scratch, "bin", "dart_extract.dart" ), script )
    if not changed and os.path.exists( os.path.join( scratch, ".dart_tool", "package_config.json" ) ): return scratch
    for flags in ( [ "--offline" ], [] ):
        res = runner( [ dart, "pub", "get", *flags ], cwd=scratch, capture_output=True, text=True, encoding="utf-8", timeout=RUN_TIMEOUT )
        if res.returncode == 0: return scratch
    raise DependencyMissing( f"analyzer {ANALYZER_VERSION} for dart", res.stderr.strip()[ :200 ] )


def extract_dart( root, files, data_root, runner=subprocess.run, warnings=None ):
    """
    Return one record per Dart declaration in files.

    Requires:
        - root is the index root; nothing under it is written
        - files are absolute .dart paths taken from the index spec; this function never globs
        - data_root is the repo's own data directory
        - warnings is a list to append to, or None to print to stderr

    Ensures:
        - returns [] for no files, without looking for dart
        - each record has lang "dart" and passes validate_record
        - a file with parse errors yields no records, and one warning naming the file and its
          error count, because error recovery can put a declaration in the wrong scope
        - typedefs, top-level variables and constants are not indexed; the contract has no kind for them

    Raises:
        - DependencyMissing when dart or the analyzer package is not available
        - RuntimeError carrying the analyzer script's stderr when the script fails
    """
    if not files: return []
    dart = find_dart( root )
    if dart is None: raise DependencyMissing( "dart", "no flutter/bin/dart under the index root, no LUPIN_DART, none on the search path" )
    scratch = prepare_scratch( dart, data_root, runner )
    payload = json.dumps( { "root": str( root ), "files": [ str( f ) for f in files ] } ) + "\n"
    res = runner( [ dart, "run", "bin/dart_extract.dart" ], cwd=scratch, input=payload, capture_output=True, text=True, encoding="utf-8", timeout=RUN_TIMEOUT )
    if res.returncode != 0: raise RuntimeError( f"dart_extract.dart failed (exit {res.returncode}): {res.stderr.strip()[ :500 ]}" )
    parsed  = json.loads( res.stdout )
    records = parsed[ "records" ]
    for name, count in sorted( parsed[ "parse_errors" ].items() ):
        message = f"{name}: {count} parse errors, file skipped"
        if warnings is None: print( f"[symindex] WARNING: {message}", file=sys.stderr )
        else: warnings.append( message )
    for rec in records:
        rec[ "lang" ] = "dart"
        validate_record( rec )
    return records

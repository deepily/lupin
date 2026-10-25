"""
Build, freshness check and atomic publication of the symbol index.

One generation directory holds every generated file, and a `current` symlink names the live
generation, replaced with os.replace. A reader therefore never sees one new file beside one
old file, and never sees a half-written index. Rebuilds run under an flock.
"""
import collections
import fcntl
import hashlib
import json
import os
import pathlib
import re
import shutil
import sys
import time

from cosa.repo.symindex import routes as routes_mod
from cosa.repo.symindex.errors import DependencyMissing
from cosa.repo.symindex.extractor_contract import validate_record
from cosa.repo.symindex.js_index import extract_js, find_node, find_typescript, typescript_version
from cosa.repo.symindex.paths import default_out_dir
from cosa.repo.symindex.py_index import extract_python
from cosa.repo.symindex.spec import SCRIPT_SUFFIXES, is_lupin_tree, is_test_path, iter_files, manifest, spec_for

KEEP_GENERATIONS = 3
SEARCH_SCOPES    = ( "public", "private" )          # the scopes a search may ask about; `test` only on request, `nested` never


def logic_version( py_source, js_source, dart_source ):
    """
    Identify the extractor logic that decides pins.

    Ensures:
        - returns 6 hex characters over the Python extractor's AST with docstrings removed, the
          JS extractor with comments removed and the Dart extractor with whole-line comments removed,
          so editing a comment never changes it and editing code does
        - an edit to py_index.py, ts_extract.js or dart_extract.dart that could change a record
          (a pin, or the public flag) therefore changes the pin algorithm by itself, and an index
          built before the edit is stale; nobody has to remember to bump a constant
    """
    import ast
    from cosa.repo.symindex.py_index import strip_docs
    code = re.sub( r"/\*.*?\*/|//[^\n]*", "", js_source, flags=re.S )
    dart = "\n".join( line for line in dart_source.split( "\n" ) if not line.lstrip().startswith( "//" ) )
    return _hash_text( ast.dump( strip_docs( ast.parse( py_source ) ) ) + "\0" + " ".join( code.split() ) + "\0" + " ".join( dart.split() ) )[ :6 ]

SEP              = " — "            # the em dash between signature and summary in symbols.md


def _hash_text( text ):
    """Ensures: returns the first 10 hex characters of sha1( text )."""
    return hashlib.sha1( text.encode( "utf-8" ) ).hexdigest()[ :10 ]


EXTRACTOR_LOGIC = logic_version( ( pathlib.Path( __file__ ).with_name( "py_index.py" ) ).read_text( encoding="utf-8" ),
                                 ( pathlib.Path( __file__ ).with_name( "ts_extract.js" ) ).read_text( encoding="utf-8" )
                                 + "\n" + ( pathlib.Path( __file__ ).with_name( "ts_kind_names.cjs" ) ).read_text( encoding="utf-8" ),
                                 ( pathlib.Path( __file__ ).with_name( "dart_extract.dart" ) ).read_text( encoding="utf-8" ) )


def _assign_ids( spec, records ):
    """
    Give every record a unique id.

    Requires:
        - records are sorted by ( file, line )
    Ensures:
        - id is "<module>.<name>" for Python and "<file stem, dots for slashes>.<name>" otherwise,
          prefixed "<repo>:" for every tree that is not lupin
        - a repeated id gets "#2", "#3" in encounter order, so every id is unique
    """
    prefix = "" if is_lupin_tree( spec.root ) else f"{spec.name}:"
    seen   = {}
    for r in records:
        base = r[ "module" ] if r[ "lang" ] == "py" else pathlib.PurePosixPath( r[ "file" ] ).with_suffix( "" ).as_posix().replace( "/", "." )
        rid  = prefix + ".".join( x for x in ( base, r[ "name" ] ) if x )
        seen[ rid ] = seen.get( rid, 0 ) + 1
        r[ "id" ]   = rid if seen[ rid ] == 1 else f"{rid}#{seen[ rid ]}"


def environment( spec ):
    """
    Report the extraction tools as they are now, without extracting anything.

    Ensures:
        - returns ( pin_algorithm, missing ): the algorithm string a build would record (Python minor,
          the extractor-logic version, then the TypeScript and Dart parser versions) and the sorted
          list of tools that are not available
        - Python is always present; JavaScript and TypeScript need node and the typescript package; Dart needs the
          extractor module and its check_dependencies() to pass. A tool the tree does not use is
          never required
    """
    algo, missing = [ f"py{sys.version_info.major}.{sys.version_info.minor}.x{EXTRACTOR_LOGIC}" ], []
    if iter_files( spec, spec.js_roots, set( SCRIPT_SUFFIXES ) ):
        try:
            find_node()
            algo.append( f"ts{typescript_version( find_typescript( spec.root ) )}" )
        except DependencyMissing as e:
            missing.append( e.what )
    if iter_files( spec, spec.dart_roots, { ".dart" } ):
        try:
            from cosa.repo.symindex import dart_extractor
            dart_extractor.check_dependencies( spec.root )
            algo.append( dart_extractor.PIN_ALGORITHM )
        except ImportError:
            missing.append( "dart_extractor" )
        except DependencyMissing as e:
            missing.append( e.what )
    return "/".join( algo ), sorted( set( missing ) )


def collect( spec ):
    """
    Extract every symbol and route under spec.

    Ensures:
        - returns a dict { symbols, all_symbols, routes, missing, unparsed, skipped_files, pin_algorithm }
        - skipped_files counts the files of an indexed suffix that a skip rule left out, per rule (a directory name or a file suffix)
        - all_symbols holds every definition; symbols holds the public ones; ids match in both
        - a missing tool (node, typescript, the Dart extractor) is listed in `missing`,
          its symbols are absent, and the rest of the index is still built
        - a Python or Dart file that does not parse is listed in `unparsed` and skipped
    """
    recs, unparsed = [], []
    algo, missing  = environment( spec )
    drops          = {}
    py_files       = iter_files( spec, spec.py_roots, { ".py" }, drops )
    for p in py_files:
        try:
            found = extract_python( spec, p, include_all=True )
        except ( SyntaxError, UnicodeDecodeError ):
            unparsed.append( p.relative_to( spec.root ).as_posix() ); continue
        recs.extend( found )
    js_files = iter_files( spec, spec.js_roots, set( SCRIPT_SUFFIXES ), drops )
    if js_files and "node" not in missing and "typescript" not in missing:
        recs.extend( extract_js( spec.root, js_files ) )
    dart_files = iter_files( spec, spec.dart_roots, { ".dart" }, drops )
    if dart_files and not any( m in missing for m in ( "dart", "analyzer", "dart_extractor" ) ):
        from cosa.repo.symindex import dart_extractor
        from cosa.repo.symindex.paths import data_dir
        dart_unparsed = []
        for r in dart_extractor.extract_dart( spec.root, dart_files, data_dir( spec.root ), unparsed=dart_unparsed ):
            validate_record( r ); recs.append( r )
        unparsed.extend( dart_unparsed )
    for r in recs:
        if "pin" not in r: r[ "pin" ] = _hash_text( r[ "pin_text" ] )
        r.pop( "pin_text", None )
        r[ "scope" ] = scope_of( r )
    recs.sort( key=lambda r: ( r[ "file" ], r[ "line" ], r[ "name" ] ) )
    _assign_ids( spec, recs )
    per_file = _route_files( spec, recs, py_files )
    for r in recs: r.pop( "_node", None )
    return { "symbols"     : [ r for r in recs if r[ "public" ] ],
             "all_symbols" : recs,
             "routes"      : routes_mod.resolve( per_file ),
             "missing"     : sorted( set( missing ) ),
             "unparsed"    : unparsed,
             "skipped_files": dict( sorted( collections.Counter( drops.values() ).items() ) ),
             "pin_algorithm": algo }


def _route_files( spec, recs, py_files ):
    """
    Collect the route facts of each Python file that defines or includes routers.

    Ensures:
        - returns the per-file route facts for routes.resolve(): router prefixes, include_router
          prefixes, import aliases and decorated handlers
        - only files that mention APIRouter, FastAPI or include_router are parsed a second time, so a module
          that only includes routers (and defines no function) is still seen
    """
    import ast
    handlers = {}
    for r in recs:
        if r[ "lang" ] == "py":
            for recv, method, path in routes_mod.route_decorators( r[ "_node" ] ):
                handlers.setdefault( r[ "file" ], [] ).append( ( recv, method, path, r[ "id" ] ) )
    out = []
    for p in py_files:
        rel  = p.relative_to( spec.root ).as_posix()
        text = p.read_text( encoding="utf-8", errors="replace" )
        if not any( k in text for k in ( "APIRouter", "FastAPI", "include_router" ) ): continue
        try:
            routers, includes, imports = routes_mod.scan_file( ast.parse( text ) )
        except SyntaxError:
            continue
        out.append( { "file": rel, "stem": pathlib.PurePosixPath( rel ).stem, "routers": routers, "includes": includes,
                      "imports": imports, "decorated": handlers.get( rel, [] ) } )
    return out


def scope_of( rec ):
    """
    Classify one definition for the search.

    Requires:
        - rec holds file, name and public
    Ensures:
        - returns `test` for a file under a tests directory
        - otherwise `public` for a public definition, `nested` for a helper inside a function
          (its name holds `<locals>`), and `private` for any other definition
    """
    if is_test_path( rec[ "file" ] ): return "test"
    if rec[ "public" ]: return "public"
    return "nested" if "<locals>" in rec[ "name" ] else "private"


def judge_doc( rec ):
    """
    Return the docstring text the judge reads.

    Ensures:
        - returns the whole docstring when the record has one, else its first line
    """
    return rec[ "doc_full" ] if "doc_full" in rec else rec[ "doc" ]


def search_sha( records ):
    """
    Hash the definitions a search may ask about.

    Requires:
        - records are searchable definitions, each with id, pin, sig and doc
    Ensures:
        - returns 40 hex characters over the sorted ( id, pin, signature, judge docstring ) rows
        - a new or changed private definition changes it, though the public listing does not move
    """
    rows = sorted( f"{r[ 'id' ]}\t{r[ 'pin' ]}\t{r[ 'sig' ]}\t{judge_doc( r )}" for r in records )
    return hashlib.sha1( "\n".join( rows ).encode( "utf-8" ) ).hexdigest()


def symbol_line( r ):
    """Ensures: returns the symbols.md line "<file>::<name><sig> — <doc> [<id>@<pin>]"."""
    return f"{r[ 'file' ]}::{r[ 'name' ]}{r[ 'sig' ]}{SEP}{r[ 'doc' ]} [{r[ 'id' ]}@{r[ 'pin' ]}]"


def _jsonl( records ):
    """Ensures: returns one compact JSON object per line, keys sorted, ending in a newline."""
    return "".join( json.dumps( r, sort_keys=True, ensure_ascii=False ) + "\n" for r in records )


def _write_generation( tmp, spec, data, man ):
    """
    Write every file of one index generation into tmp.

    Requires:
        - tmp is an empty directory
    Ensures:
        - writes symbols.md, routes.md, symbols.jsonl, symbols-all.jsonl and header.json, all utf-8
        - the header holds skipped_files, the per-rule count of files a skip rule left out, beside unparsed
        - search_sha covers the records of spec.scopes (public and private when the spec names none), so the tests spec's header holds the tests' own hash
        - returns the header dict
    """
    symbols_md = "\n".join( symbol_line( r ) for r in data[ "symbols" ] ) + "\n"
    files      = { "symbols.md": symbols_md, "routes.md": "\n".join( data[ "routes" ] ) + "\n",
                   "symbols.jsonl": _jsonl( data[ "symbols" ] ), "symbols-all.jsonl": _jsonl( data[ "all_symbols" ] ) }
    scopes     = SEARCH_SCOPES if spec.scopes is None else spec.scopes
    searchable = [ r for r in data[ "all_symbols" ] if r[ "scope" ] in scopes ]
    header     = { "index_root"   : str( spec.root ), "repo": spec.name, "manifest": man,
                   "symbols_sha"  : hashlib.sha1( symbols_md.encode( "utf-8" ) ).hexdigest(),
                   "search_sha"   : search_sha( searchable ),
                   "pin_algorithm": data[ "pin_algorithm" ],
                   "counts"       : { "symbols": len( data[ "symbols" ] ), "searchable": len( searchable ), "all": len( data[ "all_symbols" ] ), "routes": len( data[ "routes" ] ) },
                   "missing_dependencies": data[ "missing" ], "unparsed": data[ "unparsed" ], "skipped_files": data[ "skipped_files" ] }
    files[ "header.json" ] = json.dumps( header, indent=2, sort_keys=True ) + "\n"
    for name, text in files.items():
        ( tmp / name ).write_text( text, encoding="utf-8" )
    return header


def build( root=None, out_dir=None, spec=None ):
    """
    Build the index for a repository and publish it atomically.

    Requires:
        - root is a repository root (default: the git toplevel of the current directory)
        - spec is None for the repository's own index spec, or an IndexSpec such as spec.tests_spec( root ) with its own out_dir
    Ensures:
        - out_dir/current points at a complete generation for the tree as it is now
        - a generation that already exists for the same manifest, pin algorithm and missing-tool list is kept
          as it is, never deleted and rewritten; a change in any of the three names a new generation
        - two processes building at once serialize on out_dir/.build.lock; neither publishes a torn index
        - only the newest KEEP_GENERATIONS generations are kept
        - returns { "gen_dir": Path, "header": dict }
    """
    from cosa.repo.symindex.spec import git_toplevel
    if spec is None: spec = spec_for( git_toplevel() if root is None else root )
    out  = pathlib.Path( out_dir ) if out_dir is not None else default_out_dir( spec.root )
    out.mkdir( parents=True, exist_ok=True )
    with open( out / ".build.lock", "w" ) as lock:
        fcntl.flock( lock, fcntl.LOCK_EX )
        man  = manifest( spec )
        data = collect( spec )
        gen  = out / f"gen-{_hash_text( man + data[ 'pin_algorithm' ] + ','.join( data[ 'missing' ] ) ) }"
        tmp  = out / f".tmp-{os.getpid()}"
        shutil.rmtree( tmp, ignore_errors=True )
        tmp.mkdir()
        header = _write_generation( tmp, spec, data, man )
        if ( gen / "header.json" ).is_file():
            shutil.rmtree( tmp )                                   # same tree, same bytes: keep the generation a reader may have open
        else:
            shutil.rmtree( gen, ignore_errors=True )               # a leftover of a crashed build
            os.rename( tmp, gen )
        link = out / f".current-{os.getpid()}"
        if link.is_symlink(): link.unlink()
        os.symlink( gen.name, link )
        os.replace( link, out / "current" )
        _prune( out, gen.name )
    return { "gen_dir": gen, "header": header }


def _prune( out, keep_name ):
    """
    Remove old generations and stale temporary directories.

    Ensures:
        - removes all but the newest KEEP_GENERATIONS gen-* directories, never `keep_name`
        - removes .tmp-* directories left by a crashed build once they are over an hour old
    """
    for t in out.glob( ".tmp-*" ):
        if t.is_dir() and time.time() - t.stat().st_mtime > 3600: shutil.rmtree( t, ignore_errors=True )
    gens = sorted( [ g for g in out.glob( "gen-*" ) if g.is_dir() ], key=lambda g: g.stat().st_mtime, reverse=True )
    for g in gens[ KEEP_GENERATIONS: ]:
        if g.name != keep_name: shutil.rmtree( g, ignore_errors=True )


def current_generation( out_dir ):
    """
    Find the live generation directory.

    Ensures:
        - returns the Path of the live generation directory, or None when nothing is published
    """
    link = pathlib.Path( out_dir ) / "current"
    return link.resolve() if link.is_symlink() and link.resolve().is_dir() else None


def read_header( gen ):
    """Ensures: returns the parsed header.json of a generation."""
    return json.loads( ( pathlib.Path( gen ) / "header.json" ).read_text( encoding="utf-8" ) )


def read_symbols( gen, all_symbols=False ):
    """
    Read the symbol records of a generation.

    Ensures:
        - returns the list of symbol dicts of a generation (public only unless all_symbols)
    """
    text = ( pathlib.Path( gen ) / ( "symbols-all.jsonl" if all_symbols else "symbols.jsonl" ) ).read_text( encoding="utf-8" )
    return [ json.loads( line ) for line in text.splitlines() if line ]


def read_searchable( gen, tests=False ):
    """
    Read the definitions a search may ask about.

    Requires:
        - gen is a published generation written with scopes
    Ensures:
        - returns the records of `symbols-all.jsonl` whose scope is public or private, in file order
        - nested helpers are never returned
        - tests adds the records of scope `test`
    """
    scopes = SEARCH_SCOPES + ( "test", ) if tests else SEARCH_SCOPES
    return [ r for r in read_symbols( gen, all_symbols=True ) if r[ "scope" ] in scopes ]


def attach_purposes( records, purposes ):
    """
    Add each record's stored purpose line to it.

    Requires:
        - records are index records with a pin
        - purposes is { pin: purpose line }, or None

    Ensures:
        - returns a new list; a record whose pin has a line is a copy carrying it as `purpose`, any other record is the same object
        - no record is changed in place
    """
    if not purposes: return list( records )
    return [ { **r, "purpose": purposes[ r[ "pin" ] ] } if r[ "pin" ] in purposes else r for r in records ]


def searchable_jsonl( gen, tests=False, purposes=None ):
    """Ensures: returns read_searchable( gen, tests ), with the purposes attached, as jsonl text."""
    return _jsonl( attach_purposes( read_searchable( gen, tests ), purposes ) )


def is_fresh( spec, out_dir ):
    """
    Say whether the published index still matches the tree and the available tools.

    Ensures:
        - True iff a generation is published, its manifest equals the manifest of the tree now (so
          added, deleted, resized and touched files make it stale), it was built with the same pin
          algorithm, and it lists the same missing tools as environment() does now (so installing
          a tool that was absent, or upgrading the compiler, makes it stale)
    """
    gen = current_generation( out_dir )
    if gen is None: return False
    head = read_header( gen )
    algo, missing = environment( spec )
    return head[ "manifest" ] == manifest( spec ) and head[ "pin_algorithm" ] == algo and head[ "missing_dependencies" ] == missing


def ensure( root=None, out_dir=None, spec=None ):
    """
    Return the live generation, building it first when it is missing or stale.

    Requires:
        - spec is None for the repository's own index spec, or an IndexSpec with its own out_dir (the tests spec publishes to its own folder)
    Ensures:
        - returns the live generation Path, building it first when the index is missing or stale
    """
    from cosa.repo.symindex.spec import git_toplevel
    if spec is None: spec = spec_for( git_toplevel() if root is None else root )
    out  = pathlib.Path( out_dir ) if out_dir is not None else default_out_dir( spec.root )
    if not is_fresh( spec, out ): return build( spec.root, out, spec )[ "gen_dir" ]
    return current_generation( out )

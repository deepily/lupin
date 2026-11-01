"""Extraction of every definition a run wrote, Python and script, with a closing account."""
import ast
import hashlib
import pathlib

from cosa.repo.semdup import errors as err
from cosa.repo.symindex import js_index, py_index
from cosa.repo.symindex import spec as sp
from cosa.repo.symindex.errors import DependencyMissing

PY_SUFFIXES     = ( ".py", )
SCRIPT_SUFFIXES = ( ".ts", ".tsx", ".js", ".mjs", ".cjs" )
ORIGINS         = ( "new", "server" )
MAX_CALLS       = 50


def definition_id( origin, file, name, text ):
    """
    Return the id of a definition: "d-" and ten hex digits of a sha256 over four fields.

    Requires:
        - all four arguments are strings

    Ensures:
        - the four fields are origin, file, name and text; the same four strings give the same id in every process
        - a change to any one of them changes the id
    """
    return "d-" + hashlib.sha256( "\0".join( ( origin, file, name, text ) ).encode( "utf-8" ) ).hexdigest()[ :10 ]


def _check_origin( origin ):
    """
    Refuse an origin that is not "new" or "server".

    Requires:
        - nothing about origin

    Ensures:
        - returns None for "new" and "server"

    Raises:
        - ValueError for anything else
    """
    if origin not in ORIGINS: raise ValueError( f"origin must be one of {ORIGINS}, got {origin!r}" )


def _record( origin, lang, file, name, line, end_line, sig, text, calls, nodes, public, declared ):
    """
    Build the definition record the rest of the checker passes around.

    Requires:
        - origin is "new" or "server"; the other arguments are what the extractors report

    Ensures:
        - returns a dict with id, origin, lang, file, name, line, end_line, sig, text, calls, nodes, public and declared
        - calls holds at most MAX_CALLS names
    """
    return { "id": definition_id( origin, file, name, text ), "origin": origin, "lang": lang, "file": file, "name": name, "line": line,
             "end_line": end_line, "sig": sig, "text": text, "calls": calls[ :MAX_CALLS ], "nodes": nodes, "public": public, "declared": declared }


def _callee_names( node ):
    """
    List the distinct names a Python definition calls, in the order ast.walk meets them.

    Requires:
        - node is an ast node

    Ensures:
        - holds the id of a called name and the attribute of a called member, each once
        - a call through an index or a call result has no name and adds none
    """
    names = {}
    for n in ast.walk( node ):
        if not isinstance( n, ast.Call ): continue
        if isinstance( n.func, ast.Name ): names[ n.func.id ] = True
        elif isinstance( n.func, ast.Attribute ): names[ n.func.attr ] = True
    return list( names )


def _declared_names( node ):
    """
    List the parameter and local names a Python definition declares, once each.

    Requires:
        - node is a function definition

    Ensures:
        - names come in the order ast.walk meets them
        - holds every parameter of the definition and of anything nested in it, every name assigned, bound by a loop,
          a comprehension, a with block or a walrus, and every name an except clause binds
        - never holds the definition's own name
    """
    names = {}
    for n in ast.walk( node ):
        if isinstance( n, ast.arg ): names[ n.arg ] = True
        elif isinstance( n, ast.Name ) and isinstance( n.ctx, ast.Store ): names[ n.id ] = True
        elif isinstance( n, ast.ExceptHandler ) and n.name is not None: names[ n.name ] = True
    return list( names )


def _dedent( segment, indent ):
    """
    Remove a definition's own indentation from the lines after its first.

    Requires:
        - segment is the source of one definition, whose first line was cut where the definition starts
        - indent is the leading white space of the line the definition starts on

    Ensures:
        - returns the first line unchanged and every later line without a leading indent
        - a later line that does not start with indent, such as a blank line or the inside of a multi-line string, is left as it is
        - the same body gives the same text whether it sits in a class or at the top of a file
    """
    first, *rest = segment.split( "\n" )
    return "\n".join( [ first ] + [ line[ len( indent ): ] if indent and line.startswith( indent ) else line for line in rest ] )


def extract_python( root, path, origin ):
    """
    Extract one record per definition of a Python file, nested and private included.

    Requires:
        - root is the repository root and path is a Python file under it
        - origin is "new" or "server"

    Ensures:
        - classes are left out; the name, signature, line and public flag are those symindex.py_index.extract_python returns, so there is one
          signature builder in the tree
        - each record adds end_line, text (the source of the definition, without its own indentation), calls, nodes (ast nodes, counted as dups counts) and declared

    Raises:
        - ValueError if origin is neither "new" nor "server"
        - SyntaxError if the file does not parse
        - UnicodeDecodeError if the file is not readable text
    """
    _check_origin( origin )
    spec    = sp.spec_for( root )
    source  = pathlib.Path( path ).read_text( encoding="utf-8" )
    lines   = source.split( "\n" )
    records = []
    for r in py_index.extract_python( spec, pathlib.Path( path ), include_all=True ):
        if r[ "kind" ] == "class": continue
        node = r[ "_node" ]
        first  = lines[ node.lineno - 1 ]
        indent = first[ :len( first ) - len( first.lstrip() ) ]
        records.append( _record( origin, "py", r[ "file" ], r[ "name" ], r[ "line" ], node.end_lineno, r[ "sig" ], _dedent( ast.get_source_segment( source, node ), indent ),
                                 _callee_names( node ), sum( 1 for _ in ast.walk( node ) ), r[ "public" ], _declared_names( node ) ) )
    return records


def extract_script( root, files, origin ):
    """
    Extract one record per definition of script files, with the compiler's own node count.

    Requires:
        - root is the repository root and files are absolute paths of script files under it
        - origin is "new" or "server"

    Ensures:
        - returns { "definitions", "skipped", "accounts" }
        - skipped lists the files the parser rejected; accounts holds, for each file read, function_like_total, anonymous_walked and reported
        - nodes is the length of the definition's kind list, as dups counts a script definition
        - private and nested definitions are included, with public false
        - an empty file list returns empty lists without starting node

    Raises:
        - ValueError if origin is neither "new" nor "server"
        - SemdupError DEPENDENCY_MISSING if node or the compiler is absent
    """
    _check_origin( origin )
    if not files: return { "definitions": [], "skipped": [], "accounts": [] }
    try:
        shapes = js_index.extract_js_shapes( root, files, bodies=True )
    except DependencyMissing as e:
        raise err.SemdupError( err.DEPENDENCY_MISSING, str( e ) ) from e
    definitions = [ _record( origin, "ts", d[ "file" ], d[ "name" ], d[ "line" ], d[ "end_line" ], d[ "sig" ], d[ "text" ], d[ "calls" ], len( d[ "kinds" ] ),
                             d[ "public" ], d[ "declared" ] ) for d in shapes[ "defs" ] ]
    accounts    = [ { **a, "reported": sum( 1 for d in shapes[ "defs" ] if d[ "file" ] == a[ "file" ] ) } for a in shapes[ "scanned" ] ]
    return { "definitions": definitions, "skipped": shapes[ "skipped" ], "accounts": accounts }


def extract_tree( root, files, origin ):
    """
    Extract every definition of the given files and account for what could not be read.

    Requires:
        - root is the repository root; files are absolute paths under it, each a Python or script file
        - origin is "new" or "server"

    Ensures:
        - returns { "definitions", "skipped_python", "skipped_script", "script_accounts", "repeated_ids" }
        - the Python definitions come first, in the order of the files, then the script ones
        - a Python file that does not parse is listed in skipped_python and nothing is raised for it
        - a definition whose id was already taken (the same origin, file, name and text twice) is left out and listed in repeated_ids
          with its line, so a union over ids never sees one id twice

    Raises:
        - ValueError if origin is neither "new" nor "server", or a file is neither Python nor script
        - SemdupError DEPENDENCY_MISSING if script files were given and node or the compiler is absent
    """
    _check_origin( origin )
    root        = pathlib.Path( root ).resolve()
    py_files    = [ pathlib.Path( f ) for f in files if str( f ).endswith( PY_SUFFIXES ) ]
    script      = [ pathlib.Path( f ) for f in files if str( f ).endswith( SCRIPT_SUFFIXES ) ]
    other       = [ str( f ) for f in files if not str( f ).endswith( PY_SUFFIXES + SCRIPT_SUFFIXES ) ]
    if other: raise ValueError( f"neither Python nor script files: {other}" )
    found, skipped_python = [], []
    for path in py_files:
        try:
            found.extend( extract_python( root, path, origin ) )
        except SyntaxError:
            skipped_python.append( path.relative_to( root ).as_posix() )
    scripted    = extract_script( root, script, origin )
    definitions, repeated, taken = [], [], set()
    for d in found + scripted[ "definitions" ]:
        if d[ "id" ] in taken:
            repeated.append( { "id": d[ "id" ], "file": d[ "file" ], "name": d[ "name" ], "line": d[ "line" ] } )
        else:
            taken.add( d[ "id" ] )
            definitions.append( d )
    return { "definitions": definitions, "skipped_python": skipped_python, "skipped_script": scripted[ "skipped" ], "script_accounts": scripted[ "accounts" ],
             "repeated_ids": repeated }


def completeness( report ):
    """
    Refuse a partial extraction of script files.

    Requires:
        - report came from extract_tree

    Ensures:
        - returns None when no script file was skipped and, for every script file read, reported + anonymous_walked equals the
          compiler's own function_like_total
        - skipped Python files do not count against completeness

    Raises:
        - SemdupError EXTRACT_INCOMPLETE naming each skipped file and each file whose account does not close
    """
    problems = [ f"{file} did not parse" for file in report[ "skipped_script" ] ]
    for a in report[ "script_accounts" ]:
        if a[ "reported" ] + a[ "anonymous_walked" ] != a[ "function_like_total" ]:
            problems.append( f"{a[ 'file' ]}: {a[ 'reported' ]} reported + {a[ 'anonymous_walked' ]} anonymous != {a[ 'function_like_total' ]} function-like nodes" )
    if problems: raise err.SemdupError( err.EXTRACT_INCOMPLETE, "; ".join( problems ) )

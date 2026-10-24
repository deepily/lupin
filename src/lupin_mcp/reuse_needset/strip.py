"""
Member text for the need set: stripped names for the drafter, raw bodies for search.

Python members go through the existing need_input step. Script members go through needset_strip.js, one node start per call.
"""
import ast
import pathlib
import textwrap

from cosa.repo.symindex import js_index, need_input
from lupin_mcp.reuse_needset import errors as er

STRIP_SCRIPT = pathlib.Path( __file__ ).resolve().with_name( "needset_strip.js" )
MODE_STRIP   = "strip"
MODE_TEXT    = "text"
MODE_SHAPE   = "shape"


def module_of( rec ):
    """
    Read the module path out of a record's id.

    Requires:
        - rec has id and name, and the id ends with the name, optionally followed by "#N"

    Ensures:
        - returns the dotted module path, which is the id without the name
    """
    return rec[ "id" ].split( "#" )[ 0 ][ : -( len( rec[ "name" ] ) + 1 ) ]


def src_root_of( root, rec ):
    """
    Find the directory that the module ids of a record are rooted at.

    Requires:
        - rec has id, name and file, and the module path matches the file path

    Ensures:
        - returns the path under root that holds the first module part, or root itself when the module starts at the top
    """
    parts = list( pathlib.PurePosixPath( rec[ "file" ] ).with_suffix( "" ).parts )
    if parts[ -1 ] == "__init__": parts.pop()
    return pathlib.Path( root ).joinpath( *parts[ : len( parts ) - len( module_of( rec ).split( "." ) ) ] )


def dotted_id( rec ):
    """Return the record's id without a repeat suffix, the id that need_input resolves."""
    return rec[ "id" ].split( "#" )[ 0 ]


def python_text( rec, root ):
    """
    Read a Python member's source as written, decorators and docstring included.

    Requires:
        - rec is a Python index record whose module file exists under root

    Ensures:
        - returns the member's lines, dedented
    Raises:
        - NeedsetError STRIP_FAILED when the member cannot be found
    """
    try:
        path, qualname = need_input.resolve_member( dotted_id( rec ), str( src_root_of( root, rec ) ) )
        source         = pathlib.Path( path ).read_text( encoding="utf-8" )
        node, _        = need_input._find_node( ast.parse( source ), qualname )
    except ( ValueError, OSError, SyntaxError ) as e:
        raise er.NeedsetError( er.STRIP_FAILED, f"{rec[ 'id' ]}: {e}" ) from e
    first = min( [ node.lineno ] + [ d.lineno for d in node.decorator_list ] )
    return textwrap.dedent( "\n".join( source.splitlines()[ first - 1 : node.end_lineno ] ) )


def script_results( root, recs, mode, strict=True ):
    """
    Run needset_strip.js once over script records.

    Requires:
        - recs is a list of script index records with id, file, name and line; mode is strip, text or shape

    Ensures:
        - returns the script's results in the order of recs, a member that was not found as { ok: False } when strict is off
        - an empty list starts no process
    Raises:
        - NeedsetError STRIP_FAILED when a member is not found and strict is set
        - DependencyMissing when node or typescript is absent
    """
    if not recs: return []
    root    = pathlib.Path( root )
    targets = [ { "file": r[ "file" ], "name": r[ "name" ], "line": r[ "line" ], "module_parts": module_of( r ).split( "." ) } for r in recs ]
    files   = sorted( { root / r[ "file" ] for r in recs } )
    out     = js_index._run( root, files, { "mode": mode, "targets": targets }, script=STRIP_SCRIPT )[ "results" ]
    for r, res in zip( recs, out ):
        if strict and not res[ "ok" ]: raise er.NeedsetError( er.STRIP_FAILED, f"{r[ 'id' ]}: {res[ 'error' ]}" )
    return out


def strip_members( recs, root ):
    """
    Strip the names out of members.

    Requires:
        - recs are index records of the py or ts language

    Ensures:
        - returns { id: { "kind", "text", "forbidden" } } where text holds none of the names in forbidden
        - all script records share one node start
    Raises:
        - NeedsetError STRIP_FAILED when a member cannot be found
    """
    out, scripts = {}, [ r for r in recs if r[ "lang" ] != "py" ]
    for r in recs:
        if r[ "lang" ] != "py": continue
        try:
            got = need_input.build_input( dotted_id( r ), str( src_root_of( root, r ) ) )
        except ( ValueError, OSError, SyntaxError ) as e:
            raise er.NeedsetError( er.STRIP_FAILED, f"{r[ 'id' ]}: {e}" ) from e
        out[ r[ "id" ] ] = { "kind": got.kind, "text": got.text, "forbidden": got.forbidden }
    for r, res in zip( scripts, script_results( root, scripts, MODE_STRIP ) ):
        out[ r[ "id" ] ] = { "kind": res[ "kind" ], "text": res[ "text" ], "forbidden": res[ "forbidden" ] }
    return out


def strip_member( rec, root ):
    """Strip one member; see strip_members."""
    return strip_members( [ rec ], root )[ rec[ "id" ] ]


def bodies_for( recs, root ):
    """
    Read members' source as written.

    Ensures:
        - returns { id: text }, Python by the need_input lookup and script members through one node start
    Raises:
        - NeedsetError STRIP_FAILED when a member cannot be found
    """
    scripts = [ r for r in recs if r[ "lang" ] != "py" ]
    out     = { r[ "id" ]: python_text( r, root ) for r in recs if r[ "lang" ] == "py" }
    for r, res in zip( scripts, script_results( root, scripts, MODE_TEXT ) ): out[ r[ "id" ] ] = res[ "text" ]
    return out

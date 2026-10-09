#!/usr/bin/env python3
"""
The identifier-stripped text a need writer reads for one twin-sample member.

The writer sees a member's docstring and body with its names removed. The sentence it writes
then describes behaviour and cannot hand a search the answer. Names removed: the member's
own name, its enclosing class, the module path parts, and every parameter name.
"""

import ast
import os
import re
import textwrap
from dataclasses import dataclass, field

KEEP_NAMES = frozenset( { "self", "cls" } )
MIN_NAME_LEN = 3


@dataclass
class NeedInput:
    """
    One member's stripped text.

    Requires:
        - kind is "function", "method" or "class"

    Ensures:
        - text holds no identifier listed in forbidden
        - forbidden lists every name that was replaced, longest first
    """
    member_id : str
    kind      : str
    text      : str
    forbidden : list = field( default_factory=list )


def resolve_member( member_id, src_root ):
    """
    Split a dotted member id into its module file and the name path inside it.

    Requires:
        - member_id is a dotted string whose leading parts name a module under src_root

    Ensures:
        - returns ( path of the .py file, qualified name inside it ), longest module first

    Raises:
        - ValueError when no prefix of member_id names a module file
    """
    parts = member_id.split( "." )
    for cut in range( len( parts ) - 1, 0, -1 ):
        base = os.path.join( src_root, *parts[ :cut ] )
        for candidate in ( base + ".py", os.path.join( base, "__init__.py" ) ):
            if os.path.isfile( candidate ): return candidate, ".".join( parts[ cut: ] )
    raise ValueError( f"no module file under {src_root} for member {member_id}" )


def _find_node( tree, qualname ):
    """
    Walk the module tree down a dotted name.

    Ensures:
        - returns ( node, parent class node or None )

    Raises:
        - ValueError when a part of qualname is not defined at its level
    """
    scope, parent = tree, None
    for part in qualname.split( "." ):
        found = None
        for node in scope.body:
            if isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef ) ) and node.name == part:
                found = node
        if found is None: raise ValueError( f"{qualname} not found: no definition named {part}" )
        if isinstance( scope, ast.ClassDef ): parent = scope
        scope = found
    return scope, parent


def _param_names( node ):
    """Ensures: returns every parameter name of a function, or of every method of a class."""
    names = []
    funcs = [ node ] if not isinstance( node, ast.ClassDef ) else [
        sub for sub in ast.walk( node ) if isinstance( sub, ( ast.FunctionDef, ast.AsyncFunctionDef ) ) ]
    for func in funcs:
        args = func.args
        for arg in args.posonlyargs + args.args + args.kwonlyargs + [ args.vararg, args.kwarg ]:
            if arg is not None and arg.arg not in names: names.append( arg.arg )
    return names


def _attr_names( node ):
    """Ensures: returns the names read or written as self.x or cls.x inside the member."""
    names = []
    for sub in ast.walk( node ):
        if isinstance( sub, ast.Attribute ) and isinstance( sub.value, ast.Name ) and sub.value.id in KEEP_NAMES:
            if sub.attr not in names: names.append( sub.attr )
    return names


def _member_names( node ):
    """Ensures: returns the member's own name plus, for a class, the name of each method."""
    names = [ node.name ]
    if isinstance( node, ast.ClassDef ):
        names += [ sub.name for sub in node.body if isinstance( sub, ( ast.FunctionDef, ast.AsyncFunctionDef ) ) ]
    return names


def build_input( member_id, src_root ):
    """
    Build the stripped input for one member.

    Requires:
        - member_id resolves to a function, method or class under src_root

    Ensures:
        - returns a NeedInput whose text no longer holds the member's name, its class name,
          a module path part or a parameter name
        - self, cls, dunder names and names shorter than three characters are kept
        - placeholders, written in capitals in the text: one each for the member and its methods,
          for a class itself, for the enclosing class and for path parts; numbered ones for
          parameters (first-seen order) and for self.x and cls.x attribute names

    Raises:
        - ValueError when the member cannot be resolved or found
    """
    path, qualname = resolve_member( member_id, src_root )
    with open( path, encoding="utf-8" ) as handle: source = handle.read()
    node, parent = _find_node( ast.parse( source ), qualname )
    kind         = "class" if isinstance( node, ast.ClassDef ) else ( "method" if parent is not None else "function" )
    first        = min( [ node.lineno ] + [ d.lineno for d in node.decorator_list ] )
    segment      = textwrap.dedent( "\n".join( source.splitlines()[ first - 1 : node.end_lineno ] ) )

    replacements = {}
    for name in _member_names( node ): replacements.setdefault( name, "NAME" )
    if kind == "class": replacements[ node.name ] = "CLASS"
    if parent is not None: replacements.setdefault( parent.name, "CLASS" )
    for part in member_id.split( "." )[ : -len( qualname.split( "." ) ) ]: replacements.setdefault( part, "MODULE" )
    for index, name in enumerate( _param_names( node ), start=1 ): replacements.setdefault( name, f"ARG{index}" )
    for index, name in enumerate( _attr_names( node ), start=1 ): replacements.setdefault( name, f"ATTR{index}" )
    for name in list( replacements ):
        if name in KEEP_NAMES or len( name ) < MIN_NAME_LEN or ( name.startswith( "__" ) and name.endswith( "__" ) ): del replacements[ name ]

    forbidden = sorted( replacements, key=lambda name: ( -len( name ), name ) )
    pattern   = re.compile( r"(?<![A-Za-z0-9_])(" + "|".join( re.escape( name ) for name in forbidden ) + r")(?![A-Za-z0-9_])" )
    text      = pattern.sub( lambda match: replacements[ match.group( 1 ) ], segment ) if forbidden else segment
    return NeedInput( member_id=member_id, kind=kind, text=text, forbidden=forbidden )

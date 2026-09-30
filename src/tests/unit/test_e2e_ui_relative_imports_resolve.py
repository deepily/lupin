#!/usr/bin/env python3
"""
Every relative import in `src/tests/e2e_ui/` names something that exists.

Row 0a678842's fix replaced the geometry module's `_DOC_LINK_MD` constant with a per-case
`_doc_link_md( marker )` helper. `test_doc_link_renders_in_app_without_a_new_page.py` still did
`from .test_doc_link_pane_is_in_the_viewport_in_vertical import ( _DOC_LINK_MD, … )`, so pytest
could not IMPORT it, and one collection error interrupts the run: no e2e test executed at all,
in either half of the gate. Nothing in the unit tier noticed, because the unit tier never
imports the e2e modules (their conftest needs a live server).

This reads the import statements with `ast` instead of importing anything, so it needs no server
and no browser. A collection error is a property of the files, not of the venue.

Venue: :7999-eligible — reads tracked files only, no network, no writes outside tmp_path.
"""

import ast
import os
import subprocess

LUPIN_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
E2E_DIR    = os.path.join( "src", "tests", "e2e_ui" )


def _bound_names( statements ):
    """
    Names a module binds at top level, including inside `if` / `try` / `with` blocks.

    Ensures:
        - includes assignments (plain, annotated, augmented, tuple), def / async def / class,
          and import aliases (`import a.b` binds `a`)
        - does NOT descend into function or class bodies: those bind locals
    """
    names = set()
    for node in statements:
        if isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef ) ):
            names.add( node.name )
        elif isinstance( node, ast.Assign ):
            for target in node.targets: names.update( _target_names( target ) )
        elif isinstance( node, ( ast.AnnAssign, ast.AugAssign ) ):
            names.update( _target_names( node.target ) )
        elif isinstance( node, ast.Import ):
            names.update( ( a.asname or a.name.split( "." )[ 0 ] ) for a in node.names )
        elif isinstance( node, ast.ImportFrom ):
            names.update( ( a.asname or a.name ) for a in node.names )
        elif isinstance( node, ( ast.If, ast.While ) ):
            names.update( _bound_names( node.body ) | _bound_names( node.orelse ) )
        elif isinstance( node, ast.For ):
            names.update( _target_names( node.target ) | _bound_names( node.body ) | _bound_names( node.orelse ) )
        elif isinstance( node, ast.With ):
            for item in node.items:
                if item.optional_vars is not None: names.update( _target_names( item.optional_vars ) )
            names.update( _bound_names( node.body ) )
        elif isinstance( node, ast.Try ):
            for block in ( node.body, node.orelse, node.finalbody, *[ h.body for h in node.handlers ] ):
                names.update( _bound_names( block ) )
    return names


def _target_names( target ):
    if isinstance( target, ast.Name ): return { target.id }
    if isinstance( target, ( ast.Tuple, ast.List ) ):
        found = set()
        for element in target.elts: found |= _target_names( element )
        return found
    if isinstance( target, ast.Starred ): return _target_names( target.value )
    return set()


def unresolved_relative_imports( root, files ):
    """
    Every `from .x import y` in `files` whose target module or name does not exist.

    Requires:
        - root is a directory; files are paths relative to it, all inside one package tree

    Ensures:
        - returns a list of ( file, lineno, "module", "name", reason ), empty when all resolve
        - `from .m import n` needs m.py (or m/__init__.py) to exist AND to bind n at top level,
          or n to be a submodule of m
        - `from . import n` needs n.py, n/ or a binding of n in __init__.py
        - `import *` and absolute imports are out of scope: the first cannot be checked
          name by name, the second is not this guard's failure
    """
    problems = [ ]
    cache    = { }

    def module_file( directory, dotted ):
        base = os.path.join( directory, *dotted.split( "." ) ) if dotted else directory
        for candidate in ( base + ".py", os.path.join( base, "__init__.py" ) ):
            if os.path.isfile( candidate ): return candidate
        return None

    def names_of( path ):
        if path not in cache:
            with open( path, "r", encoding="utf-8" ) as f:
                cache[ path ] = _bound_names( ast.parse( f.read(), filename=path ).body )
        return cache[ path ]

    for relative in files:
        path = os.path.join( root, relative )
        with open( path, "r", encoding="utf-8" ) as f:
            tree = ast.parse( f.read(), filename=path )
        for node in ast.walk( tree ):
            if not isinstance( node, ast.ImportFrom ) or node.level == 0: continue
            directory = os.path.dirname( path )
            for _ in range( node.level - 1 ): directory = os.path.dirname( directory )
            target = module_file( directory, node.module ) if node.module else os.path.join( directory, "__init__.py" )
            for alias in node.names:
                if alias.name == "*": continue
                is_submodule = module_file( os.path.join( directory, *( node.module.split( "." ) if node.module else [ ] ) ), alias.name )
                if node.module and ( target is None ):
                    problems.append( ( relative, node.lineno, node.module, alias.name, "module not found" ) )
                elif is_submodule is not None:
                    continue
                elif target is None or not os.path.isfile( target ) or alias.name not in names_of( target ):
                    problems.append( ( relative, node.lineno, node.module or ".", alias.name, "name not defined there" ) )
    return problems


def _tracked_e2e_python():
    out = subprocess.run( [ "git", "ls-files", E2E_DIR ], cwd=LUPIN_ROOT, capture_output=True, text=True, check=True ).stdout
    return sorted( line for line in out.splitlines() if line.endswith( ".py" ) )


def test_every_relative_import_in_the_e2e_tree_resolves():
    files = _tracked_e2e_python()
    assert len( files ) > 100, f"the e2e population looks wrong ({len( files )} tracked .py files): the guard would be a loop over nothing"
    importing = [ f for f in files if "from ." in open( os.path.join( LUPIN_ROOT, f ), encoding="utf-8" ).read() ]
    assert len( importing ) > 10, "almost nothing imports relatively, so this guard is watching nothing"
    problems = unresolved_relative_imports( LUPIN_ROOT, files )
    assert problems == [], "\n".join(
        f"{f}:{line}: `from {module} import {name}` — {reason}" for f, line, module, name, reason in problems )


# ── positive controls: the instrument must be able to find the incident ─────────────────

def _package( tmp_path, files ):
    for name, body in files.items():
        ( tmp_path / name ).write_text( body )
    return [ name for name in files if name.endswith( ".py" ) ]


def test_the_incident_shape_is_found_a_name_replaced_by_a_helper( tmp_path ):
    """Row 0a678842, replayed: the geometry module lost `_DOC_LINK_MD` and grew a function."""
    names = _package( tmp_path, {
        "geometry.py" : "_DOC_HREF = '/x'\ndef _doc_link_md( marker ):\n    return marker\n",
        "renders.py"  : "from .geometry import ( _DOC_HREF, _DOC_LINK_MD )\n",
    } )
    assert unresolved_relative_imports( str( tmp_path ), names ) == [ ( "renders.py", 1, "geometry", "_DOC_LINK_MD", "name not defined there" ) ]


def test_a_missing_module_and_a_missing_submodule_are_found( tmp_path ):
    names = _package( tmp_path, {
        "a.py" : "X = 1\n",
        "b.py" : "from .gone import Z\nfrom . import nothing_here\nfrom . import a\n",
    } )
    found = { ( m, n, why ) for _, _, m, n, why in unresolved_relative_imports( str( tmp_path ), names ) }
    assert found == { ( "gone", "Z", "module not found" ), ( ".", "nothing_here", "name not defined there" ) }


def test_every_way_a_name_can_be_bound_counts_as_defined( tmp_path ):
    names = _package( tmp_path, {
        "a.py" : (
            "import os.path\nimport json as js\nfrom os import sep as SEP\n"
            "A = 1\nB: int = 2\nC, ( D, E ) = 3, ( 4, 5 )\nF = 0\nF += 1\n"
            "def fn(): pass\nasync def afn(): pass\nclass K: pass\n"
            "if True:\n    IF_BOUND = 1\ntry:\n    TRY_BOUND = 1\nexcept Exception:\n    EXC_BOUND = 1\n"
            "with open( __file__ ) as WITH_BOUND:\n    pass\n"
            "for LOOP_VAR in []:\n    pass\n"
        ),
        "b.py" : "from .a import ( os, js, SEP, A, B, C, D, E, F, fn, afn, K, IF_BOUND, TRY_BOUND, EXC_BOUND, WITH_BOUND, LOOP_VAR )\n",
    } )
    assert unresolved_relative_imports( str( tmp_path ), names ) == []


def test_a_name_bound_only_inside_a_function_is_not_defined_at_module_level( tmp_path ):
    names = _package( tmp_path, {
        "a.py" : "def fn():\n    local_only = 1\n",
        "b.py" : "from .a import local_only\n",
    } )
    assert [ p[ 3 ] for p in unresolved_relative_imports( str( tmp_path ), names ) ] == [ "local_only" ]


def test_star_imports_and_absolute_imports_are_out_of_scope( tmp_path ):
    names = _package( tmp_path, {
        "a.py" : "X = 1\n",
        "b.py" : "from .a import *\nfrom os import nothing\nimport json\n",
    } )
    assert unresolved_relative_imports( str( tmp_path ), names ) == []

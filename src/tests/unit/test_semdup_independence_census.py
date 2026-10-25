"""Census guard: no module under semdup/ imports the reuse tools it is built to measure."""
import ast
import pathlib

import pytest

import cosa.utils.util as cu

SEMDUP    = pathlib.Path( cu.get_project_root() ) / "src" / "cosa" / "repo" / "semdup"
FORBIDDEN = ( "lupin_mcp", "cosa.repo.symindex.verdict", "cosa.repo.symindex.candidates.search" )


def imported_names( source, package ):
    """List the module names a source imports, from-imports also as module.name."""
    names = []
    for node in ast.walk( ast.parse( source ) ):
        if isinstance( node, ast.Import ):
            names.extend( alias.name for alias in node.names )
        elif isinstance( node, ast.ImportFrom ):
            base = ".".join( package.split( "." )[ :len( package.split( "." ) ) - node.level + 1 ] + ( [ node.module ] if node.module else [] ) ) if node.level else node.module
            names.append( base )
            names.extend( f"{base}.{alias.name}" for alias in node.names )
    return names


def forbidden_imports( source, package="cosa.repo.semdup" ):
    """Return the forbidden modules a source imports, whole names only, so lookalikes pass."""
    return sorted( { n for n in imported_names( source, package ) for f in FORBIDDEN if n == f or n.startswith( f + "." ) } )


def semdup_modules():
    """List the Python modules under semdup/, with their package name."""
    return [ ( path, ".".join( path.relative_to( SEMDUP.parent.parent.parent ).with_suffix( "" ).parts[ :-1 ] ) ) for path in sorted( SEMDUP.rglob( "*.py" ) ) ]


def test_the_population_is_every_module_of_the_package_and_includes_the_ones_that_could_slip():
    names = { path.name for path, _ in semdup_modules() }
    assert len( names ) >= 10 and { "judge.py", "candidates.py", "score_run.py", "structural.py" } <= names


def test_no_module_under_semdup_imports_lupin_mcp_the_verdict_module_or_the_search_module():
    found = { path.name: forbidden_imports( path.read_text( encoding="utf-8" ), package ) for path, package in semdup_modules() }
    assert { name: hits for name, hits in found.items() if hits } == {}


@pytest.mark.parametrize( "line, hits", [
    ( "import lupin_mcp", [ "lupin_mcp" ] ),
    ( "from lupin_mcp.reuse_tools import record_search", [ "lupin_mcp.reuse_tools", "lupin_mcp.reuse_tools.record_search" ] ),
    ( "import cosa.repo.symindex.verdict as v", [ "cosa.repo.symindex.verdict" ] ),
    ( "from cosa.repo.symindex import verdict", [ "cosa.repo.symindex.verdict" ] ),
    ( "from cosa.repo.symindex.verdict import judge", [ "cosa.repo.symindex.verdict", "cosa.repo.symindex.verdict.judge" ] ),
    ( "from cosa.repo.symindex.candidates import search", [ "cosa.repo.symindex.candidates.search" ] ),
    ( "from cosa.repo.symindex.candidates.search import answer", [ "cosa.repo.symindex.candidates.search", "cosa.repo.symindex.candidates.search.answer" ] ),
    ( "from ..symindex import verdict", [ "cosa.repo.symindex.verdict" ] ),
    ( "from ..symindex.candidates import search", [ "cosa.repo.symindex.candidates.search" ] ),
] )
def test_the_guard_flags_each_way_of_importing_a_forbidden_module(line, hits):
    assert forbidden_imports( line + "\n" ) == hits


@pytest.mark.parametrize( "line", [
    "from cosa.repo.symindex.candidates import bm25, rank_fusion, vector_build, identifier_split",
    "from cosa.repo.symindex import dups, js_index, py_index",
    "import cosa.repo.symindex.candidates.vector_store as vs",
    "from cosa.repo.symindex.candidates import searcher",
    "import lupin_mcp_helpers",
    "from . import config",
    "from .proof import plant",
] )
def test_the_guard_leaves_the_allowed_reuse_and_lookalike_names_alone(line):
    assert forbidden_imports( line + "\n" ) == []


def test_a_planted_forbidden_import_in_a_copy_of_a_real_module_is_caught():
    source = ( SEMDUP / "config.py" ).read_text( encoding="utf-8" )
    assert forbidden_imports( source ) == []
    assert forbidden_imports( "from lupin_mcp import reuse_tools\n" + source ) == [ "lupin_mcp", "lupin_mcp.reuse_tools" ]

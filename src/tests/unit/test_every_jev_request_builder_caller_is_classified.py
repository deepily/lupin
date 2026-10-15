"""
Census guard: every caller that builds a Jev request from a need is classified.

The need redactor (plan section 6, the redactor phase) runs once, in `_run_question`, before the first sweep. A module
that builds a request from a need and is not reached through `run_question` would send the need as typed.
This guard counts the callers of the request builders across the tracked tree. A new caller fails the census
until someone says whether it is reached through the redactor or is allowed to take raw needs.

The population comes from `git ls-files`, never from a disk walk. The denominator is pinned at the bottom.
"""
import ast
import pathlib
import subprocess

from cosa.repo.symindex.spec import git_toplevel

ROOT     = git_toplevel( pathlib.Path( __file__ ).resolve().parent )
BUILDERS = frozenset( { "build_request", "pack_request", "pair_key", "candidate_key", "stage1_key", "replay_key" } )

# Reached from `run_question`, where the need is redacted before any sweep starts.
PRODUCTION = { "src/lupin_mcp/reuse_tools.py": { "build_request" },
               "src/lupin_mcp/reuse_pack.py" : { "candidate_key", "pack_request", "pair_key", "replay_key", "stage1_key" } }

# Measurement drivers. They replay answers cached under the raw need text, so they take raw needs by design (plan Phase 2).
MEASUREMENT = { "src/lupin_mcp/reuse_stage1.py"         : { "pack_request" },
                "src/lupin_mcp/reuse_stage1_analysis.py": { "build_request" } }


def builders_called( source ):
    """Ensures: returns the request-builder names a module's source calls."""
    found = set()
    for node in ast.walk( ast.parse( source ) ):
        if isinstance( node, ast.Call ):
            f = node.func
            name = f.id if isinstance( f, ast.Name ) else ( f.attr if isinstance( f, ast.Attribute ) else None )
            if name in BUILDERS: found.add( name )
    return found


def tracked_python():
    """Ensures: returns the tracked .py paths outside tests and rnd, from git."""
    out = subprocess.run( [ "git", "-C", str( ROOT ), "ls-files", "*.py" ], capture_output=True, text=True, check=True ).stdout.split( "\n" )
    return [ p for p in out if p and "/tests/" not in p and not p.startswith( "src/rnd/" ) and ".venv" not in p ]


def census():
    """Ensures: returns { path: builder names } for every tracked module that calls a builder."""
    found = {}
    for path in tracked_python():
        text = ( ROOT / path ).read_text( encoding="utf-8" )
        if not any( b in text for b in BUILDERS ): continue
        names = builders_called( text )
        if names: found[ path ] = names
    return found


def test_the_detector_finds_a_caller_in_a_synthetic_source():
    assert builders_called( "x = pair_key( need, text )\ny = rp.pack_request( n, e )\nz = other( n )" ) == { "pair_key", "pack_request" }
    assert builders_called( "def f():\n    return 1\n" ) == set()


def test_every_caller_of_a_request_builder_is_classified():
    found = census()
    assert found, "the census found no caller at all: the detector or the population is wrong"
    assert found == { **PRODUCTION, **MEASUREMENT }


def test_the_classes_do_not_overlap_and_name_real_files():
    assert not set( PRODUCTION ) & set( MEASUREMENT )
    assert all( ( ROOT / p ).is_file() for p in { **PRODUCTION, **MEASUREMENT } )


def test_run_question_redacts_the_need_before_the_first_sweep():
    tree = ast.parse( ( ROOT / "src/lupin_mcp/reuse_tools.py" ).read_text( encoding="utf-8" ) )
    fn   = next( n for n in ast.walk( tree ) if isinstance( n, ast.FunctionDef ) and n.name == "_run_question" )
    calls = [ ( c.lineno, c.func.attr if isinstance( c.func, ast.Attribute ) else c.func.id ) for c in ast.walk( fn ) if isinstance( c, ast.Call )
              and isinstance( c.func, ( ast.Attribute, ast.Name ) ) ]
    redact = [ ln for ln, name in calls if name == "redact_need" ]
    sweep  = [ ln for ln, name in calls if name in ( "_route", "_route_pair" ) ]
    assert redact and sweep and min( redact ) < min( sweep )

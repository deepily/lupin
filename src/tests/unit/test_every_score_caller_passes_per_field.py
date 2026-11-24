"""
Census guard: every production call of replay_loop._score names the per-field switch.

A call that left it out would score a typed Other on a different basis from the engine arms.
"""
import ast
import subprocess
from pathlib import Path

ROOT = Path( __file__ ).resolve().parents[ 3 ]


def _calls():
    tracked = subprocess.run( [ "git", "ls-files", "src/*.py" ], cwd=ROOT, capture_output=True, text=True, check=True ).stdout.split()
    found   = []
    for name in tracked:
        if "/tests/" in name or "/.venv/" in name or name.startswith( "src/tests/" ): continue
        tree = ast.parse( ( ROOT / name ).read_text( encoding="utf-8" ) )
        for node in ast.walk( tree ):
            if not isinstance( node, ast.Call ): continue
            func = node.func
            if ( isinstance( func, ast.Name ) and func.id == "_score" ) or ( isinstance( func, ast.Attribute ) and func.attr == "_score" ):
                found.append( ( name, node.lineno, len( node.args ) >= 5 or any( k.arg == "per_field" for k in node.keywords ) ) )
    return found


def test_every_score_caller_passes_per_field():
    found = _calls()
    assert len( found ) == 5, f"the five known call sites moved or grew: {found}"   # replay_loop 1, archive_replay 2, answer_attrition_table 2
    assert [ site for site in found if not site[ 2 ] ] == []


def test_every_score_caller_guard_can_see_a_call_that_omits_it():
    tree  = ast.parse( "_score( a, b, c, d )" )
    call  = next( n for n in ast.walk( tree ) if isinstance( n, ast.Call ) )
    assert not ( len( call.args ) >= 5 or any( k.arg == "per_field" for k in call.keywords ) )

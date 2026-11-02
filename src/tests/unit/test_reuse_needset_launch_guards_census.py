"""
Census: every refusal the launch guards can raise is declared, defined and given a test.

The denominator comes from the source: each `er.<CODE>` a guard module raises, found by walking its syntax tree.
"""
import ast
import pathlib

from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import launch_preflight, rebuild_vectors

TESTS = pathlib.Path( __file__ ).resolve().parent
GUARDS = {
    launch_preflight: TESTS / "test_reuse_needset_launch_preflight.py",
    rebuild_vectors : TESTS / "test_reuse_needset_rebuild_vectors.py",
}


def raised_codes( module ):
    """Ensures: returns the error names the module passes to NeedsetError."""
    tree  = ast.parse( pathlib.Path( module.__file__ ).read_text( encoding="utf-8" ) )
    found = set()
    for node in ast.walk( tree ):
        if isinstance( node, ast.Call ) and getattr( node.func, "attr", None ) == "NeedsetError" and node.args:
            first = node.args[ 0 ]
            if isinstance( first, ast.Attribute ) and getattr( first.value, "id", None ) == "er": found.add( first.attr )
    return found


def test_every_code_a_launch_guard_raises_is_declared_in_its_refusals():
    for module in GUARDS:
        own = raised_codes( module )
        assert own, f"{module.__name__} raises nothing: the walk found no NeedsetError, so the census is empty"
        assert own <= set( module.REFUSALS ), f"{module.__name__} raises {sorted( own - set( module.REFUSALS ) )} outside its REFUSALS"


def test_every_declared_refusal_is_a_defined_error_code_and_is_named_in_its_test_file():
    for module, test_file in GUARDS.items():
        text = test_file.read_text( encoding="utf-8" )
        for code in module.REFUSALS:
            assert getattr( er, code ) == code, f"{code} is not a code in errors.py"
            assert f"er.{code}" in text, f"{test_file.name} never asserts {code}"

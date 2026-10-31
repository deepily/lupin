"""
W9: the run-check that runs an original and its synthetic work-alike on the same inputs.

The child tests start a real `python -I` process, so the isolation is measured and not assumed.
"""
import ast
import io
import json
import os

import pytest

from cosa.repo.labelling import run_check as rc
from cosa.repo.labelling import run_check_child as child

ADD  = "def add( a: int, b: int ) -> int:\n    return a + b\n"
ADD2 = "def total( a: int, b: int ) -> int:\n    return b + a\n"


def node( source ):
    """Return the first function node of source."""
    return rc.first_function( source )


def ann( text ):
    """Return the ast annotation node for an annotation text."""
    return ast.parse( f"def f( x: {text} ): pass" ).body[ 0 ].args.args[ 0 ].annotation


# --- parent side: reading the signature ---------------------------------------------------------

def test_first_function_finds_a_def_an_async_def_and_nothing():
    assert node( "x = 1\ndef f(): pass" ).name == "f"
    assert node( "    async def g(): pass" ).name == "g"
    assert node( "x = 1" ) is None and node( "def (" ) is None


@pytest.mark.parametrize( "text, first, has_none", [
    ( "int", 0, False ), ( "str", "", False ), ( "List[int]", [], False ), ( "Dict[str, int]", {}, False ), ( "bool", True, False ),
    ( "Optional[int]", None, True ), ( "int | None", 0, True ), ( "None", None, True ), ( "Tuple[int, int]", [], False ), ( "Set[int]", [], False ),
] )
def test_pool_for_known_annotations( text, first, has_none ):
    pool = rc.pool_for( ann( text ) )
    assert pool[ 0 ] == first and ( None in pool ) == has_none


@pytest.mark.parametrize( "text", [ "Foo", "Callable[[int], int]", "int | Foo", "Foo | int", "Optional[Foo]", "a.b" ] )
def test_pool_for_unknown_annotations_is_none( text ):
    assert rc.pool_for( ann( text ) ) is None


def test_pool_for_no_annotation_is_none():
    assert rc.pool_for( None ) is None


def test_parameter_pools_per_parameter_and_defaults():
    pools, why = rc.parameter_pools( node( "def f( a: int, b: str = 'z', *args, **kw ): pass" ) )
    assert why is None and pools[ 0 ][ 0 ] == 0 and pools[ 1 ][ 0 ] == "z" and "" in pools[ 1 ] and len( pools ) == 2
    pools, why = rc.parameter_pools( node( "def f( a=3 ): pass" ) )
    assert pools == [ [ 3 ] ]
    assert rc.parameter_pools( node( "def f(): pass" ) ) == ( [], None )


@pytest.mark.parametrize( "source, fragment", [
    ( "def f( self, a: int ): pass", "is a method" ),
    ( "def f( cls ): pass", "is a method" ),
    ( "def f( a ): pass", "parameter a has no type" ),
    ( "def f( a: Foo ): pass", "parameter a has no type" ),
    ( "def f( a=some_call() ): pass", "default the check cannot read" ),
    ( "def f( *, k ): pass", "keyword-only parameter has no default" ),
] )
def test_parameter_pools_refuses_with_a_reason( source, fragment ):
    pools, why = rc.parameter_pools( node( source ) )
    assert pools is None and fragment in why


def test_a_keyword_only_parameter_with_a_default_is_allowed():
    assert rc.parameter_pools( node( "def f( a: int, *, k=1 ): pass" ) )[ 1 ] is None


def test_make_cases_first_case_takes_first_values_and_the_seed_fixes_the_rest():
    pools = [ [ 1, 2, 3 ], [ "a", "b" ] ]
    one   = rc.make_cases( pools, 5 )
    assert one[ 0 ] == [ 1, "a" ] and len( one ) == rc.CASE_COUNT
    assert rc.make_cases( pools, 5 ) == one and rc.make_cases( pools, 6 ) != one
    assert all( c[ 0 ] in pools[ 0 ] and c[ 1 ] in pools[ 1 ] for c in one )
    assert rc.make_cases( [], 1, 3 ) == [ [], [], [] ]


# --- compare -------------------------------------------------------------------------------------

def outcome( **kw ):
    """Return an outcome record, changed by kw."""
    return dict( { "returned": "1", "raised": None, "args_after": "[]", "stdout": "", "files": {} }, **kw )


def test_compare_equal_is_none_and_every_field_is_compared():
    assert rc.compare( [ outcome() ], [ outcome() ] ) is None
    for key, other in ( ( "returned", "2" ), ( "raised", "KeyError" ), ( "args_after", "[1]" ), ( "stdout", "x" ), ( "files", { "f": "h" } ) ):
        got = rc.compare( [ outcome(), outcome() ], [ outcome(), outcome( **{ key: other } ) ] )
        assert got.startswith( f"case 1: {key} differs" ), key


# --- the child, in process (for coverage) and as a real process (for isolation) -----------------

def test_child_helpers_in_process(tmp_path):
    assert child.settle( object ).startswith( "<class" )
    assert "0x?" in child.settle( "x at 0xdeadbeef" ) and "deadbeef" not in child.settle( "x at 0xdeadbeef" )
    ( tmp_path / "sub" ).mkdir()
    ( tmp_path / "sub" / "f.txt" ).write_text( "hi" )
    state = child.folder_state( str( tmp_path ) )
    assert list( state ) == [ os.path.join( "sub", "f.txt" ) ] and len( state[ os.path.join( "sub", "f.txt" ) ] ) == 64
    child.clear_folder( str( tmp_path ) )
    assert child.folder_state( str( tmp_path ) ) == {}
    with pytest.raises( PermissionError ): child._blocked()


def test_limit_resources_sets_the_three_limits(monkeypatch):
    seen = {}
    monkeypatch.setattr( child.resource, "setrlimit", lambda which, pair: seen.update( { which: pair } ) )
    child.limit_resources()
    assert seen == { child.resource.RLIMIT_CPU: ( 4, 4 ), child.resource.RLIMIT_AS: ( child.MEMORY_BYTES, child.MEMORY_BYTES ), child.resource.RLIMIT_FSIZE: ( child.FILE_BYTES, child.FILE_BYTES ) }


def test_block_outside_world_replaces_each_door_and_the_patch_is_undone_afterwards(monkeypatch):
    for owner, name in ( ( child.socket, "socket" ), ( child.socket, "create_connection" ), ( child.socket, "getaddrinfo" ), ( child.os, "system" ), ( child.subprocess, "Popen" ) ):
        monkeypatch.setattr( owner, name, getattr( owner, name ) )
    child.block_outside_world()
    for call in ( child.socket.socket, child.socket.create_connection, child.socket.getaddrinfo, child.os.system, child.subprocess.Popen ):
        with pytest.raises( PermissionError ): call()


def test_run_case_reports_return_exception_arguments_stdout_and_files(tmp_path, monkeypatch):
    monkeypatch.chdir( tmp_path )
    space = {}
    exec( "def f( xs ):\n    xs.append( 9 )\n    print( 'hi' )\n    open( 'out.txt', 'w' ).write( 'z' )\n    return len( xs )\n"
          "def boom( x ):\n    raise KeyError( x )\n"
          "async def co( x ):\n    return x * 2\n", space )
    got = child.run_case( space[ "f" ], [ [ 1 ] ], str( tmp_path ) )
    assert got[ "returned" ] == "2" and got[ "raised" ] is None and got[ "args_after" ] == "[[1, 9]]" and got[ "stdout" ] == "hi\n"
    assert list( got[ "files" ] ) == [ "out.txt" ] and os.listdir( tmp_path ) == []
    assert child.run_case( space[ "boom" ], [ 1 ], str( tmp_path ) )[ "raised" ] == "KeyError"
    assert child.run_case( space[ "co" ], [ 4 ], str( tmp_path ) )[ "returned" ] == "8"
    args = [ [ 1 ] ]
    child.run_case( space[ "f" ], [ args[ 0 ] ], str( tmp_path ) )
    assert args == [ [ 1 ] ], "the caller's list is a copy and must not change"


def test_run_request_runs_cases_and_reports_a_setup_error(tmp_path, monkeypatch):
    monkeypatch.chdir( tmp_path )
    got = child.run_request( { "source": ADD, "name": "add", "cases": [ [ 1, 2 ], [ 0, 0 ] ] }, str( tmp_path ) )
    assert [ o[ "returned" ] for o in got[ "outcomes" ] ] == [ "3", "0" ]
    assert child.run_request( { "source": ADD, "name": "nope", "cases": [] }, str( tmp_path ) ) == { "setup_error": "KeyError" }
    assert child.run_request( { "source": "def (", "name": "x", "cases": [] }, str( tmp_path ) ) == { "setup_error": "SyntaxError" }


def test_main_reads_stdin_limits_and_writes_json(monkeypatch, tmp_path):
    monkeypatch.chdir( tmp_path )
    calls = []
    monkeypatch.setattr( child, "limit_resources", lambda: calls.append( "limit" ) )
    monkeypatch.setattr( child, "block_outside_world", lambda: calls.append( "block" ) )
    out = io.StringIO()
    assert child.main( io.StringIO( json.dumps( { "source": ADD, "name": "add", "cases": [ [ 2, 3 ] ] } ) ), out ) == 0
    assert calls == [ "limit", "block" ] and json.loads( out.getvalue() )[ "outcomes" ][ 0 ][ "returned" ] == "5"


def test_main_defaults_to_the_real_standard_streams(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir( tmp_path )
    monkeypatch.setattr( child, "limit_resources", lambda: None )
    monkeypatch.setattr( child, "block_outside_world", lambda: None )
    monkeypatch.setattr( "sys.stdin", io.StringIO( json.dumps( { "source": ADD, "name": "add", "cases": [ [ 1, 1 ] ] } ) ) )
    assert child.main() == 0
    assert json.loads( capsys.readouterr().out )[ "outcomes" ][ 0 ][ "returned" ] == "2"


def test_limits_and_blocks_take_effect_in_a_real_child():
    """The network block takes effect in a real child process."""
    source = ( "def probe( x: int ):\n    import socket\n    try:\n        socket.socket()\n    except PermissionError:\n        return 'blocked'\n    return 'open'\n" )
    got = rc.run_side( source, "probe", [ [ 1 ] ] )
    assert got[ "outcomes" ][ 0 ][ "returned" ] == "'blocked'"


def test_a_real_child_has_an_empty_environment_and_a_fresh_empty_folder():
    source = "def probe( x: int ):\n    import os\n    return [ sorted( os.environ ), os.listdir( '.' ) ]\n"
    got = rc.run_side( source, "probe", [ [ 1 ] ] )[ "outcomes" ][ 0 ]
    assert got[ "returned" ] in ( "[[], []]", "[['LC_CTYPE'], []]" ), "Python itself may set LC_CTYPE; nothing from the parent may arrive"


def test_a_real_child_cannot_start_a_process():
    source = "def probe( x: int ):\n    import subprocess\n    subprocess.Popen( [ 'true' ] )\n"
    assert rc.run_side( source, "probe", [ [ 1 ] ] )[ "outcomes" ][ 0 ][ "raised" ] == "PermissionError"


def test_a_real_child_that_runs_too_long_is_reported_as_timed_out():
    source = "def spin( x: int ):\n    while True: pass\n"
    got = rc.run_side( source, "spin", [ [ 1 ] ], timeout=1 )
    assert "failed" in got


def test_a_real_child_that_dies_is_reported():
    assert rc.run_side( "def die( x: int ):\n    import os\n    os._exit( 3 )\n", "die", [ [ 1 ] ] ) == { "failed": "the child exited with code 3" }


def test_a_child_that_prints_not_json_is_reported(monkeypatch):
    class Done:
        returncode = 0
        stdout     = "not json"
    monkeypatch.setattr( rc.subprocess, "run", lambda *a, **k: Done() )
    assert rc.run_side( ADD, "add", [ [ 1, 2 ] ] ) == { "failed": "the child's answer was not JSON" }


def test_the_child_receives_the_dedented_source():
    assert rc.run_side( "    def add( a: int ):\n        return a\n", "add", [ [ 4 ] ] )[ "outcomes" ][ 0 ][ "returned" ] == "4"


# --- the ruling ----------------------------------------------------------------------------------

def test_a_matching_work_alike_is_accepted():
    got = rc.check_pair( ADD, ADD2, 1 )
    assert got[ "route" ] == rc.ACCEPT and got[ "status" ] == rc.MATCH and got[ "cases" ] == rc.CASE_COUNT


def test_a_mismatch_rejects_the_key_and_names_the_case_and_field():
    got = rc.check_pair( ADD, "def total( a: int, b: int ) -> int:\n    return a - b\n", 1 )
    assert got[ "route" ] == rc.REJECT and got[ "status" ] == rc.MISMATCH
    assert got[ "reason" ].startswith( "case " ) and "returned differs" in got[ "reason" ]


def test_a_difference_in_a_side_effect_alone_rejects_the_key():
    original = "def put( a: int ) -> int:\n    open( 'f', 'w' ).write( 'x' )\n    return a\n"
    rewrite  = "def stash( a: int ) -> int:\n    return a\n"
    got = rc.check_pair( original, rewrite, 1 )
    assert got[ "route" ] == rc.REJECT and "files differs" in got[ "reason" ]


def test_a_difference_in_a_mutated_argument_rejects_the_key():
    original = "def grow( xs: list ):\n    xs.append( 1 )\n"
    rewrite  = "def grow2( xs: list ):\n    return None\n"
    assert "args_after differs" in rc.check_pair( original, rewrite, 1 )[ "reason" ]


def test_a_rewrite_that_fails_when_loaded_is_rejected():
    got = rc.check_pair( ADD, "@no_such_decorator\ndef total( a: int, b: int ) -> int:\n    return a + b\n", 1 )
    assert got[ "route" ] == rc.REJECT and got[ "reason" ] == "the rewrite does not load: NameError"


def test_a_rewrite_that_does_not_parse_goes_to_a_person_because_the_check_has_nothing_to_run():
    got = rc.check_pair( ADD, "def total( a, b ):\n    return (\n", 1 )
    assert got[ "route" ] == rc.PERSON_CHECK and "no function definition" in got[ "reason" ]


@pytest.mark.parametrize( "original, rewrite, fragment", [
    ( "x = 1", ADD, "no function definition" ),
    ( ADD, "x = 1", "no function definition" ),
    ( "def f( self, a: int ): pass", ADD, "is a method" ),
    ( "def f( a ): pass", ADD, "no type" ),
    ( "def f( a: int ):\n    return missing_name\n", ADD, "needs its module" ),
    ( "def f( a: int ):\n    import not_a_real_module_xyz\n", ADD, "needs its module" ),
] )
def test_a_pair_the_check_cannot_run_goes_to_a_person_with_the_reason( original, rewrite, fragment ):
    got = rc.check_pair( original, rewrite, 1 )
    assert got[ "route" ] == rc.PERSON_CHECK and got[ "status" ] == rc.NOT_RUNNABLE and fragment in got[ "reason" ]


def test_an_original_that_is_not_deterministic_goes_to_a_person():
    got = rc.check_pair( "def r( a: int ):\n    import random\n    return random.random()\n", ADD, 1 )
    assert got[ "route" ] == rc.PERSON_CHECK and "different answers on two runs" in got[ "reason" ]


def test_failures_from_the_runner_go_to_a_person_for_each_side():
    def fail_first( source, name, cases ): return { "failed": "timed out after 5 s" }
    assert rc.check_pair( ADD, ADD2, 1, runner=fail_first )[ "reason" ] == "the original timed out after 5 s"

    def setup_first( source, name, cases ): return { "setup_error": "SyntaxError" }
    assert "does not load alone: SyntaxError" in rc.check_pair( ADD, ADD2, 1, runner=setup_first )[ "reason" ]

    real = rc.run_side
    def fail_second( source, name, cases ): return real( source, name, cases ) if name == "add" else { "failed": "timed out after 5 s" }
    got = rc.check_pair( ADD, ADD2, 1, runner=fail_second )
    assert got[ "route" ] == rc.PERSON_CHECK and got[ "reason" ] == "the rewrite timed out after 5 s"

"""
W9: run an original and its work-alike on the same inputs and compare what they do.

A mismatch rejects the key. A pair the check cannot run goes to a person with the reason, and is neither accepted nor rejected.
"""
import ast
import json
import pathlib
import os
import random
import shutil
import subprocess
import sys
import textwrap

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import run_check_child

ACCEPT        = "accept"
REJECT        = "reject"
PERSON_CHECK  = "person_check"
MATCH         = "match"
MISMATCH      = "mismatch"
NOT_RUNNABLE  = "not_runnable"
CASE_COUNT    = 8
TIMEOUT       = 5
CHILD_PATH    = pathlib.Path( run_check_child.__file__ )
OUTCOME_KEYS  = ( "returned", "raised", "args_after", "stdout", "files" )
ENVIRONMENT   = ( "NameError", "ImportError", "ModuleNotFoundError", "PermissionError" )
WORK_FOLDER   = "/work"
CHILD_INSIDE  = "/sandbox/run_check_child.py"
POOLS         = {
    "int"   : [ 0, 1, -1, 7, 100 ],
    "float" : [ 0.0, 1.5, -2.25 ],
    "str"   : [ "", "a", "hello world", "A,b;C" ],
    "bool"  : [ True, False ],
    "bytes" : [ "" ],
    "list"  : [ [], [ 1, 2, 3 ], [ 3, 1, 2, 2 ] ],
    "dict"  : [ {}, { "a": 1, "b": 2 } ],
    "tuple" : [ [], [ 1, 2 ] ],
    "set"   : [ [], [ 1, 2, 3 ] ],
}
ALIASES       = { "List": "list", "Sequence": "list", "Iterable": "list", "Dict": "dict", "Mapping": "dict", "Tuple": "tuple", "Set": "set" }


def first_function( source ):
    """
    Return the first function definition in source, or None.

    Ensures:
        - returns the ast node of the first def or async def, indentation removed first; None when the text does not parse or holds none
    """
    try:
        tree = ast.parse( textwrap.dedent( source ) )
    except SyntaxError:
        return None
    for node in ast.walk( tree ):
        if isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef ) ): return node
    return None


def pool_for( annotation ):
    """
    Return the value pool for an annotation, or None when the check cannot generate it.

    Requires:
        - annotation is an ast expression node, or None for a parameter without one

    Ensures:
        - returns a list of JSON values for int, float, str, bool, list, dict, tuple and set, with List[...] style spellings
        - Optional[X] and X | None add None to X's pool
        - returns None for any other annotation, and for no annotation
    """
    if annotation is None: return None
    if isinstance( annotation, ast.Constant ) and annotation.value is None: return [ None ]
    if isinstance( annotation, ast.Name ):
        name = ALIASES[ annotation.id ] if annotation.id in ALIASES else annotation.id
        return list( POOLS[ name ] ) if name in POOLS else None
    if isinstance( annotation, ast.Subscript ) and isinstance( annotation.value, ast.Name ):
        head = annotation.value.id
        if head == "Optional":
            inner = pool_for( annotation.slice )
            return None if inner is None else [ None ] + inner
        return pool_for( annotation.value )
    if isinstance( annotation, ast.BinOp ) and isinstance( annotation.op, ast.BitOr ):
        left, right = pool_for( annotation.left ), pool_for( annotation.right )
        return None if left is None or right is None else left + right
    return None


def parameter_pools( node ):
    """
    Return the value pool of each parameter the check has to supply, or the reason it cannot.

    Requires:
        - node is a function definition node

    Ensures:
        - returns ( pools, None ) with one pool per positional parameter, or ( None, reason )
        - a parameter with a default gets the default added to its pool
        - self and cls, an untyped parameter without a default, and an unknown annotation each give a reason
        - *args and **kwargs are not supplied
    """
    args, pools = node.args, []
    plain       = args.posonlyargs + args.args
    defaults    = [ None ] * ( len( plain ) - len( args.defaults ) ) + list( args.defaults )
    for arg, default in zip( plain, defaults ):
        if arg.arg in ( "self", "cls" ): return None, f"{node.name} is a method; it needs an instance"
        pool = pool_for( arg.annotation )
        if default is not None:
            try:
                value = ast.literal_eval( default )
            except ValueError:
                return None, f"parameter {arg.arg} has a default the check cannot read"
            pool  = [ value ] if pool is None else [ value ] + pool
        if pool is None: return None, f"parameter {arg.arg} has no type the check can generate"
        pools.append( pool )
    if args.kwonlyargs and any( k_default is None for k_default in args.kw_defaults ): return None, "a keyword-only parameter has no default"
    return pools, None


def make_cases( pools, seed, count=CASE_COUNT ):
    """
    Build the argument lists both sides are called with.

    Requires:
        - pools is the list from parameter_pools

    Ensures:
        - the first case takes the first value of every pool, the rest are seeded draws, and the same seed gives the same cases
        - returns [ [] ] for a function with no parameters
    """
    rng   = random.Random( seed )
    first = [ [ p[ 0 ] for p in pools ] ]
    return first + [ [ rng.choice( p ) for p in pools ] for _ in range( count - 1 ) ]


def sandbox_command():
    """
    Build the command that starts the child inside a bubblewrap sandbox.

    Ensures:
        - the sandbox has no network, no process view of the host, no host files except the read-only interpreter, system libraries and the child script, and a memory-only work folder
        - the environment inside holds only PYTHONHASHSEED=0, so the order of a set of strings is the same in every child

    Raises:
        - LabellingError SANDBOX_UNAVAILABLE when bwrap is not installed; the check never runs unsandboxed
    """
    bwrap = shutil.which( "bwrap" )
    if bwrap is None: raise er.LabellingError( er.SANDBOX_UNAVAILABLE, "bwrap is not installed; the run-check refuses to run without it" )
    python = os.path.realpath( sys.executable )
    return [ bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv", "--setenv", "PYTHONHASHSEED", "0",
             "--ro-bind", sys.base_prefix, sys.base_prefix, "--ro-bind", "/usr", "/usr", "--ro-bind-try", "/lib", "/lib", "--ro-bind-try", "/lib64", "/lib64",
             "--ro-bind", str( CHILD_PATH ), CHILD_INSIDE, "--dev", "/dev", "--tmpfs", WORK_FOLDER, "--chdir", WORK_FOLDER, "--", python, "-s", "-P", CHILD_INSIDE ]


def run_side( source, name, cases, timeout=TIMEOUT ):
    """
    Run one definition on the cases in a sandboxed child process.

    Requires:
        - source defines name; cases are lists of JSON values

    Ensures:
        - the child runs under sandbox_command, limited in time, memory, file size and process count
        - returns the child's answer, { outcomes } or { setup_error }
        - returns { "failed": reason } when the child times out, dies, or prints something that is not JSON

    Raises:
        - LabellingError SANDBOX_UNAVAILABLE when bwrap is missing or cannot start the sandbox
    """
    request = json.dumps( { "source": textwrap.dedent( source ), "name": name, "cases": cases } )
    try:
        done = subprocess.run( sandbox_command(), input=request, capture_output=True, text=True, timeout=timeout, cwd="/", env={} )
    except subprocess.TimeoutExpired:
        return { "failed": f"timed out after {timeout} s" }
    if done.stderr.startswith( "bwrap:" ): raise er.LabellingError( er.SANDBOX_UNAVAILABLE, done.stderr.strip() )
    if done.returncode != 0: return { "failed": f"exited with code {done.returncode}" }
    try:
        return json.loads( done.stdout )
    except ValueError:
        return { "failed": "gave an answer that was not JSON" }


def _verdict( route, status, reason, cases=0 ):
    """Return the record of one check."""
    return { "route": route, "status": status, "reason": reason, "cases": cases }


def compare( original_out, rewrite_out ):
    """
    Find the first case where two outcome lists differ.

    Requires:
        - both are equal-length lists from run_check_child.run_case

    Ensures:
        - returns None when every case agrees on returned, raised, args_after, stdout and files
        - otherwise returns "case <n>: <field> differs" for the first difference
    """
    for n, ( a, b ) in enumerate( zip( original_out, rewrite_out ) ):
        for key in OUTCOME_KEYS:
            if a[ key ] != b[ key ]: return f"case {n}: {key} differs ({a[ key ]!r} against {b[ key ]!r})"
    return None


def needs_environment( answer ):
    """Return True when a child's answer shows a missing name, module or permission."""
    if "setup_error" in answer: return answer[ "setup_error" ] in ENVIRONMENT
    return any( o[ "raised" ] in ENVIRONMENT for o in answer[ "outcomes" ] )


def check_pair( original, rewrite, seed, runner=run_side ):
    """
    Run an original and its work-alike on the same inputs and rule on the pair.

    Requires:
        - original and rewrite are definition sources; seed is the draw's seed; runner has the signature of run_side

    Ensures:
        - returns { route, status, reason, cases }
        - match: route accept; mismatch: route reject, reason names the first differing case and field
        - not_runnable: route person_check, reason says why; this covers a method, a parameter the check cannot generate, source that does not define a function, a child that timed out or died, an original that gives different answers on two runs, and an original that raises on every generated input
        - a side that needs a name, module or permission it does not have (NameError, ImportError, PermissionError) goes to a person too, whichever side it is
        - the original is run twice; its two runs must agree before the rewrite is compared

    Raises:
        - LabellingError SANDBOX_UNAVAILABLE from the runner when the sandbox cannot start; no ruling is made without it
    """
    o_node, r_node = first_function( original ), first_function( rewrite )
    if o_node is None or r_node is None: return _verdict( PERSON_CHECK, NOT_RUNNABLE, "one side holds no function definition" )
    pools, why = parameter_pools( o_node )
    if why: return _verdict( PERSON_CHECK, NOT_RUNNABLE, why )
    cases = make_cases( pools, seed )
    first = runner( original, o_node.name, cases )
    if "failed" in first: return _verdict( PERSON_CHECK, NOT_RUNNABLE, f"the original {first[ 'failed' ]}" )
    if "setup_error" in first: return _verdict( PERSON_CHECK, NOT_RUNNABLE, f"the original does not load alone: {first[ 'setup_error' ]}" )
    if needs_environment( first ): return _verdict( PERSON_CHECK, NOT_RUNNABLE, "the original needs its module, the network or a process to run" )
    if all( o[ "raised" ] is not None for o in first[ "outcomes" ] ): return _verdict( PERSON_CHECK, NOT_RUNNABLE, "the original raised on every generated input, so nothing was compared" )
    again = runner( original, o_node.name, cases )
    if again != first: return _verdict( PERSON_CHECK, NOT_RUNNABLE, "the original gives different answers on two runs" )
    other = runner( rewrite, r_node.name, cases )
    if "failed" in other: return _verdict( PERSON_CHECK, NOT_RUNNABLE, f"the rewrite {other[ 'failed' ]}" )
    if needs_environment( other ): return _verdict( PERSON_CHECK, NOT_RUNNABLE, "the rewrite needs its module, the network or a process to run" )
    if "setup_error" in other: return _verdict( REJECT, MISMATCH, f"the rewrite does not load: {other[ 'setup_error' ]}", len( cases ) )
    differs = compare( first[ "outcomes" ], other[ "outcomes" ] )
    if differs: return _verdict( REJECT, MISMATCH, differs, len( cases ) )
    return _verdict( ACCEPT, MATCH, "same returns and side effects on every case", len( cases ) )

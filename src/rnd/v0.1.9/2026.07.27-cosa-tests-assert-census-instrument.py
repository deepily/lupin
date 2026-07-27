#!/usr/bin/env python3
"""
Row f9eb6c3c — do the green CoSA tests ASSERT anything?

INSTRUMENT: AST, not grep. A grep for "assert" matches a DESCRIPTION of an
assertion (comments, docstrings, the word inside a string). This walks the
parsed tree and only counts assertion-shaped NODES.

⚠️ THE TWO-DIRECTIONAL ERROR A BODY-ONLY SCAN HAS, AND WHY THIS ISN'T THAT:

  OVER-count of "asserts nothing": a test whose body has no assert node but
  which CALLS a helper that asserts. Body-only scanning calls that test
  assertion-free. It is not. -> fixed here by resolving intra-module calls
  transitively (see resolve()).

  UNDER-count: a test that asserts VACUOUSLY (`assert True`, `assertTrue(1)`)
  parses as asserting and is counted as fine. Not detectable structurally.
  -> This is why the headline number is a FLOOR, never a total.

So the reported number counts tests for which we can PROVE no assertion is
reachable. Tests calling helpers we cannot resolve (imported, or attributes on
objects) are reported SEPARATELY as UNRESOLVED — they are NOT folded into the
floor, because "I could not follow the call" is not "there is no assertion".
"""
import ast, os, sys, json, builtins
from collections import defaultdict

# A builtin call is NOT an unresolvable helper. Treating `print(x)` as "a call I
# could not follow" pushed three known-floor tests into UNRESOLVED on the control
# fixture — i.e. it made the floor look SMALLER than it is, the direction that
# flatters the tree. Caught 2026-07-27 by the control, not by reading the code.
BUILTIN_NAMES = set( dir( builtins ) )

ROOT = sys.argv[1] if len( sys.argv ) > 1 else "src/cosa/tests"

# Names that constitute an assertion when CALLED.
UNITTEST_ASSERT_PREFIX = "assert"          # self.assertEqual, self.assertRaises, ...
PYTEST_FAILERS         = { "fail", "xfail", "exit" }   # pytest.fail(...) etc.
RAISES_NAMES           = { "raises", "warns", "deprecated_call" }  # pytest.raises(...)


def call_name( node ):
    """Rightmost attribute/name of a Call's func, plus the full dotted string."""
    f = node.func
    if isinstance( f, ast.Name ):      return f.id, f.id
    if isinstance( f, ast.Attribute ):
        parts = []
        cur   = f
        while isinstance( cur, ast.Attribute ):
            parts.append( cur.attr ); cur = cur.value
        if isinstance( cur, ast.Name ): parts.append( cur.id )
        parts.reverse()
        return f.attr, ".".join( parts )
    return None, None


class BodyScan( ast.NodeVisitor ):
    """Assertion nodes + outbound call names inside ONE function body.

    Nested function DEFS are not descended into unless they are called — a
    closure that asserts but is never invoked asserts nothing.
    """
    def __init__( self ):
        self.asserts = False
        self.calls   = set()      # bare names, for intra-module resolution
        self.opaque  = set()      # dotted calls we cannot resolve locally
        self.nested  = {}         # nested defs, name -> node
        self.names   = set()      # every bare Name LOADED in this body

    def visit_Assert( self, node ):
        self.asserts = True

    def visit_Name( self, node ):
        if isinstance( node.ctx, ast.Load ): self.names.add( node.id )

    def visit_FunctionDef( self, node ):
        # Do NOT blanket-skip nested defs. A closure that is never referenced
        # asserts nothing — but `asyncio.run( inner() )` and `run_test( inner )`
        # DO invoke it, and refusing to descend put 62+16 async tests into
        # UNRESOLVED that plainly assert. Record it; reachability is decided in
        # resolve() by whether the parent body mentions the name at all.
        self.nested[ node.name ] = node

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call( self, node ):
        short, dotted = call_name( node )
        if short:
            if short.startswith( UNITTEST_ASSERT_PREFIX ):        self.asserts = True
            elif dotted and dotted.startswith( "pytest." ) and short in ( PYTEST_FAILERS | RAISES_NAMES ):
                self.asserts = True
            elif short in BUILTIN_NAMES and dotted == short:        pass
            elif dotted == short:                                  self.calls.add( short )
            else:                                                  self.opaque.add( dotted )
        self.generic_visit( node )


def is_test_func( name ):
    return name.startswith( "test_" )


def collectable_class( node ):
    """pytest collects Test*-named classes that define no __init__."""
    if not node.name.startswith( "Test" ): return False
    return not any( isinstance( b, ( ast.FunctionDef, ast.AsyncFunctionDef ) ) and b.name == "__init__"
                    for b in node.body )


results   = { "no_assert": [], "unresolved": [], "asserts": 0, "files": 0, "parse_errors": [] }
per_file  = {}

for dirpath, dirnames, filenames in os.walk( ROOT ):
    dirnames[ : ] = [ d for d in dirnames if d != "__pycache__" ]
    for fn in filenames:
        if not ( fn.startswith( "test_" ) and fn.endswith( ".py" ) ): continue
        path = os.path.join( dirpath, fn )
        try:
            tree = ast.parse( open( path, encoding="utf-8" ).read(), filename=path )
        except SyntaxError as e:
            results[ "parse_errors" ].append( f"{path}: {e}" ); continue
        results[ "files" ] += 1

        # every def in the module, by bare name -> its BodyScan
        scans = {}
        tests = []          # (nodeid, bare_name)

        def walk_body( body, cls=None ):
            for n in body:
                if isinstance( n, ( ast.FunctionDef, ast.AsyncFunctionDef ) ):
                    s = BodyScan();
                    for stmt in n.body: s.visit( stmt )
                    scans[ n.name ] = s
                    if is_test_func( n.name ) and ( cls is None or collectable_class_ok.get( cls, False ) ):
                        tests.append( ( f"{path}::{cls + '::' if cls else ''}{n.name}", n.name ) )
                elif isinstance( n, ast.ClassDef ):
                    collectable_class_ok[ n.name ] = collectable_class( n )
                    walk_body( n.body, cls=n.name )

        collectable_class_ok = {}
        walk_body( tree.body )

        def resolve( name, seen ):
            """(asserts, saw_unresolved_call) following intra-module calls."""
            if name in seen: return False, False
            seen.add( name )
            s = scans.get( name )
            if s is None: return False, True          # callee not in this module
            if s.asserts: return True, False
            unresolved = bool( s.opaque )
            # nested defs the body actually MENTIONS are reachable
            for nname, nnode in s.nested.items():
                if nname not in s.names: continue      # defined, never referenced
                ns = BodyScan()
                for stmt in nnode.body: ns.visit( stmt )
                scans.setdefault( f"<nested>{nname}", ns )
                a, u = resolve( f"<nested>{nname}", seen )
                if a: return True, False
                unresolved = unresolved or u
            for c in s.calls:
                a, u = resolve( c, seen )
                if a: return True, False
                unresolved = unresolved or u
            return False, unresolved

        for nodeid, bare in tests:
            asserts, unresolved = resolve( bare, set() )
            if asserts:        results[ "asserts" ] += 1
            elif unresolved:   results[ "unresolved" ].append( nodeid )
            else:              results[ "no_assert" ].append( nodeid )

total = results[ "asserts" ] + len( results[ "unresolved" ] ) + len( results[ "no_assert" ] )
print( f"files parsed          {results['files']}" )
print( f"test functions found  {total}" )
print( f"  ASSERTS (proven)    {results['asserts']}" )
print( f"  NO ASSERT (proven)  {len(results['no_assert'])}   <- the FLOOR" )
print( f"  UNRESOLVED call     {len(results['unresolved'])}   <- cannot follow; NOT in the floor" )
if results[ "parse_errors" ]: print( f"  parse errors        {len(results['parse_errors'])}" )
json.dump( results, open( sys.argv[2], "w" ) if len( sys.argv ) > 2 else sys.stdout, indent=1 )

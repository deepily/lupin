#!/usr/bin/env python3
"""
Mutation harness that proves WHERE a falsifier bit, not merely THAT something went red.

THE FAILURE THIS PREVENTS, and it happened here on 2026-08-25 (row d2e23ecb).

A falsifier is supposed to prove a test suite can fail: change the product, watch the
gate redden. Phase 5 extracted eleven `if`/`elif` branch bodies into eleven builder
functions, and the bodies were DEDENTED from eight spaces to four in the move. The
falsifier's search pattern still carried the original eight-space indent. It therefore
did NOT match the builder it named -- it matched the LEGACY copy of the same code
further down the same file, which had kept its original indentation.

The suite went red. The red was real. It was also completely uninformative: it proved
the legacy function could break, which nobody doubted, while the new path went
unexercised. Nothing in the output said so.

⇒ THAT IS THE WHOLE POINT. A mutation that lands somewhere other than where you aimed it
does not fail loudly -- it still goes red, and it reads exactly like success. The only
signal that anything was wrong came from a test written for that mutation staying GREEN,
which is a thing a person has to notice.

HOW THIS TOOL REMOVES THE FAILURE MODE

  1. The target is resolved STRUCTURALLY, by `ast`, from the function's NAME. Whatever
     the function is indented to, now or after any future refactor, it is found.
  2. The pattern is matched line-by-line with LEADING INDENTATION STRIPPED, so a dedent
     cannot break it and cannot silently redirect it.
  3. The substitution is applied ONLY inside that function's line span.
  4. The run ABORTS unless EXACTLY ONE match was found inside the named function -- zero
     matches and two matches are both refusals.
  5. After writing, the file is RE-PARSED and the mutation is confirmed to sit inside the
     intended function. A mutation that moved is a hard error.
  6. The original file is always restored, including on failure.

🔴 EVERY ONE OF THOSE REFUSALS IS A HARD ABORT AND MUST STAY ONE. Downgrading any of them
to a warning reinstates the exact defect this file exists to remove: the run would carry
on, produce a red, and that red would once again mean nothing in particular. A harness
that "warns" about mutating blind is a harness that mutates blind.

USAGE
    falsify.py --target <file.py> --suite <test_file.py> --func <function_name> \\
               --old <snippet_file> --new <snippet_file> [--label "..."]

Exit codes: 0 the mutation reddened at least one case (the falsifier fired);
            1 the mutation applied and NOTHING reddened (the gate is blind to it);
            2 the mutation was refused (bad target, bad pattern, or it moved).
"""
import argparse
import ast
import os
import re
import shutil
import subprocess
import sys


class MutationRefused( Exception ):
    """Raised when the mutation cannot be placed EXACTLY where it was aimed.

    Deliberately an exception and not a warning -- see this module's docstring.
    """


def span_of( path, func_name ):
    """
    Locate a function's line span by NAME, structurally.

    Requires:
        - path names a readable, parseable Python file
        - func_name is a function defined at module level in that file

    Ensures:
        - returns ( start, end ) as 0-indexed, end-exclusive line numbers
        - the result is independent of how the function is indented

    Raises:
        - MutationRefused if no module-level function of that name exists -- a typo must
          never silently mutate nothing, or worse, something else
    """
    tree = ast.parse( open( path ).read() )
    for node in tree.body:
        if isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef ) ) and node.name == func_name:
            return node.lineno - 1, node.end_lineno
    raise MutationRefused( f"no module-level function named {func_name} in {path}" )


def norm( block ):
    """
    Reduce a snippet to indentation-free lines for matching.

    Requires:
        - block is a string

    Ensures:
        - returns a list of stripped, non-empty-preserving lines
        - two snippets that differ ONLY in leading whitespace compare equal
    """
    return [ l.strip() for l in block.strip( "\n" ).split( "\n" ) ]


def apply_mutation( target, func_name, old_block, new_block ):
    """
    Replace `old_block` with `new_block` INSIDE `func_name`, and prove it landed there.

    Requires:
        - target names a readable, parseable Python file
        - func_name is a module-level function in it
        - old_block appears EXACTLY ONCE inside that function, ignoring indentation

    Ensures:
        - the file is rewritten with the substitution applied at that one site
        - the replacement is re-indented to match the line it replaced
        - the file is RE-PARSED and the mutation confirmed inside func_name
        - returns the 1-indexed line the mutation was written at

    Raises:
        - MutationRefused when the pattern matches zero or more than one time inside the
          function, or when the mutation is not inside func_name after re-parsing. BOTH
          are hard refusals ON PURPOSE: a mutation that lands elsewhere still produces a
          red, and that red is indistinguishable from a real one.
    """
    lines  = open( target ).read().split( "\n" )
    lo, hi = span_of( target, func_name )
    want   = norm( old_block )
    hits   = [ i for i in range( lo, hi - len( want ) + 1 )
               if [ l.strip() for l in lines[ i : i + len( want ) ] ] == want ]
    if len( hits ) != 1:
        raise MutationRefused(
            f"pattern matched {len(hits)} times inside {func_name} (need exactly 1) "
            f"-- refusing to mutate blind"
        )
    at     = hits[ 0 ]
    indent = re.match( r"\s*", lines[ at ] ).group( 0 )
    repl   = [ ( indent + l ) if l else "" for l in norm( new_block ) ]
    open( target, "w" ).write( "\n".join( lines[ :at ] + repl + lines[ at + len( want ): ] ) )

    lo2, hi2 = span_of( target, func_name )
    body     = [ l.strip() for l in open( target ).read().split( "\n" )[ lo2 : hi2 ] ]
    if norm( new_block )[ 0 ] not in body:
        raise MutationRefused( f"mutation is not inside {func_name} after re-parse -- it moved" )
    return at + 1


def run_suite( suite ):
    """
    Run one pytest file and report which cases failed, by name.

    Requires:
        - suite names a pytest-collectable file

    Ensures:
        - returns ( failed_case_names, summary_line )
        - case names are the bare node ids a reader can paste back into pytest
        - random ordering is disabled so a re-run names the same cases
    """
    env = { **os.environ, "PYTHONPATH": "src", "LUPIN_ROOT": os.getcwd() }
    r   = subprocess.run(
        [ ".venv/bin/pytest", suite, "-q", "--no-header", "-p", "no:randomly", "--tb=no" ],
        capture_output=True, text=True, env=env,
    )
    failed  = [ l.split( "::" )[ -1 ].strip() for l in r.stdout.split( "\n" ) if l.startswith( "FAILED" ) ]
    summary = next( ( l for l in reversed( r.stdout.split( "\n" ) )
                     if "passed" in l or "failed" in l or "error" in l ), "(no summary)" )
    return failed, summary


def falsify( target, suite, func, old_block, new_block, label, out=print ):
    """
    Apply one mutation, run the suite, report which cases reddened, and always restore.

    Ensures:
        - the target file is restored to its original content whether the run passes,
          fails, or raises
        - returns 0 when the mutation reddened at least one case, 1 when it reddened
          none, 2 when the mutation was refused
    """
    backup = target + ".falsify-backup"
    shutil.copy( target, backup )
    try:
        line          = apply_mutation( target, func, old_block, new_block )
        failed, summ  = run_suite( suite )
        out( f"\n=== {label} ===" )
        out( f"mutated {func} at line {line} (ast-scoped, indentation-agnostic)" )
        out( f"result : {summ}" )
        if failed:
            out( f"REDDENED {len(failed)} case(s), by name:" )
            for f in failed: out( f"    - {f}" )
            return 0
        out( "DID NOT FIRE -- the gate is blind to this change" )
        return 1
    except MutationRefused as e:
        out( f"\n=== {label} ===" )
        out( f"REFUSED: {e}" )
        return 2
    finally:
        shutil.move( backup, target )


def main( argv=None ):
    p = argparse.ArgumentParser( description="Prove a test suite can fail, and prove WHERE the mutation landed." )
    p.add_argument( "--target", required=True, help="the .py file to mutate" )
    p.add_argument( "--suite",  required=True, help="the pytest file that should redden" )
    p.add_argument( "--func",   required=True, help="module-level function to mutate INSIDE" )
    p.add_argument( "--old",    required=True, help="file holding the snippet to replace" )
    p.add_argument( "--new",    required=True, help="file holding the replacement snippet" )
    p.add_argument( "--label",  default="falsifier" )
    a = p.parse_args( argv )
    return falsify( a.target, a.suite, a.func, open( a.old ).read(), open( a.new ).read(), a.label )


if __name__ == "__main__":
    sys.exit( main() )

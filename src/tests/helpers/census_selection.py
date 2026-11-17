"""
Choose the census selection: guard files by name, and guard tests elsewhere.

src/tests/run-census-guards.sh feeds it the tracked unit test files on stdin and runs what it prints.
A file whose name matches NAME_RULE is run whole.
In any other file each test_every_* function, and each test or class marked @pytest.mark.census, is run by node id.
So a guard written in an ordinarily named file is not missed.

    git ls-files 'src/tests/unit/*' | PYTHONPATH=src python -m tests.helpers.census_selection
"""
import ast
import pathlib
import re
import sys
import warnings

NAME_RULE    = re.compile( r"/test_(every_|[^/]*(census|_pin|pins|pinned))[^/]*\.py$" )
GUARD_PREFIX = "test_every_"
GUARD_MARK   = "pytest.mark.census"


def picked_by_name( path ):
    """
    Say whether the runner runs the whole file because of its name.

    Requires:
        - path is a posix repo-relative path

    Ensures:
        - returns True for test_every_*, and for test_ files whose name holds census, _pin, pins or pinned
    """
    return NAME_RULE.search( path ) is not None


def _marked( node ):
    """
    Say whether a function or class carries @pytest.mark.census.

    The mark is for a test that counts something across the whole tree.
    """
    return any( ast.unparse( decorator ) == GUARD_MARK for decorator in node.decorator_list )


def _defs( body, owners ):
    """
    Yield the owner chain of each guard in a body, through classes and blocks.

    A guard is a test_every_* function, or a function or class marked @pytest.mark.census.
    A marked class is yielded whole and not searched, so no id is listed twice.
    """
    for node in body:
        if isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef ) ):
            if node.name.startswith( GUARD_PREFIX ) or _marked( node ): yield owners + [ node.name ]
        elif isinstance( node, ast.ClassDef ):
            if _marked( node ): yield owners + [ node.name ]
            else: yield from _defs( node.body, owners + [ node.name ] )
        elif isinstance( node, ( ast.If, ast.Try, ast.With, ast.For, ast.While ) ):
            yield from _defs( node.body, owners )
            for handler in getattr( node, "handlers", [] ):
                yield from _defs( handler.body, owners )
            for field in ( "orelse", "finalbody" ):
                yield from _defs( getattr( node, field, [] ), owners )


def guard_ids( path, source ):
    """
    List the node ids of the guards of one file.

    A guard is a test_every_* function, or a test or class marked census.

    Requires:
        - source is the text of the Python file at path

    Ensures:
        - returns path::name, or path::Class::name for a method, in file order, each id once
        - a function nested inside another function is not listed, because pytest does not collect it

    Raises:
        - SyntaxError when the source does not parse
    """
    with warnings.catch_warnings():
        warnings.simplefilter( "ignore", SyntaxWarning )                      # a test file's own escape warnings are not this tool's to print
        tree = ast.parse( source, filename=path )
    ids = [ "::".join( [ path ] + chain ) for chain in _defs( tree.body, [] ) ]
    return list( dict.fromkeys( ids ) )


def select( paths, read ):
    """
    Choose the census selection from the tracked unit test files.

    Requires:
        - paths are posix repo-relative paths of .py files; read is a callable path -> source text

    Ensures:
        - returns the paths picked by name, whole, and the guard node ids (test_every_* or marked census) of every other file, in path order
        - a file picked by name never also contributes node ids

    Raises:
        - SyntaxError, OSError or UnicodeDecodeError from a file that cannot be read or parsed as Python
    """
    chosen = []
    for path in sorted( p for p in paths if p.endswith( ".py" ) ):
        if picked_by_name( path ): chosen.append( path )
        else: chosen.extend( guard_ids( path, read( path ) ) )
    return chosen


def main( stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr, read=None ):
    """
    Print the census selection for the tracked files named on stdin, one per line.

    Requires:
        - stdin holds one repo-relative path per line, relative to the working directory

    Ensures:
        - returns 0 after printing the selection
        - returns 2 and prints nothing to stdout when a file cannot be read or parsed, naming the file on stderr:
          a selection that skipped a file would be a census that quietly ran less
    """
    read  = ( lambda path: pathlib.Path( path ).read_text( encoding="utf-8" ) ) if read is None else read
    paths = [ line.strip() for line in stdin.read().splitlines() if line.strip() ]
    seen  = []

    def watched( path ):
        seen.append( path )
        return read( path )

    try:
        chosen = select( paths, watched )
    except ( SyntaxError, OSError, UnicodeDecodeError ) as error:
        print( f"census_selection: could not read {seen[ -1 ] if seen else '(no file)'}: {error}", file=stderr )
        return 2
    print( "\n".join( chosen ), file=stdout )
    return 0


if __name__ == "__main__":  # pragma: no cover  reason: the command line entry; main is tested with stand-in streams
    sys.exit( main() )

"""
Census: no tracked Python code names the session-bridge folder except the seam.

`sessions_dir()` in `src/lupin_cli/claude_code/hooks/lib/sessions_dir.py` is the one place
that resolves the session-bridge folder. Its default is to move to a folder Lupin owns, which
only works if no reader or writer spells the old path itself.

The guard reads each file's syntax tree, not its text. Comments are not in the tree, and a
string that stands alone as a statement (a docstring) is prose, so both are skipped. Each
path expression is read as one text: a string, an f-string, a chain of `+` or `/`, or the
arguments of a `join` call. A name assigned such a chain ending in `.claude` counts as
`.claude` wherever the file uses it. The expression is refused when its text, with repeated
slashes collapsed, holds `.claude/sessions` as whole path parts. Not seen: a base passed in
from another module or built across a function call that is not a join.

The population is every tracked `.py` file outside the test folders and the R&D folders,
taken from `git ls-files`. The seam module itself is left out, because it holds the default.
"""

import ast
import os
import re
import subprocess

import pytest

SEAM        = "src/lupin_cli/claude_code/hooks/lib/sessions_dir.py"
PATTERN     = re.compile( r"(?:^|/)\.claude/sessions(?:/|$)" )
JOINERS     = { "join", "joinpath" }
PASSERS     = { "expanduser", "expandvars", "abspath", "realpath", "normpath", "Path", "PurePath", "PosixPath", "str", "fspath" }
SKIP_PREFIX = ( "src/rnd/", "src/cosa/rnd/", "src/tests/", "src/cosa/tests/" )


def _prose_nodes( tree ):
    """
    Return the ids of every node inside a string that stands alone as a statement.

    Requires:
        - tree is a parsed `ast.Module`

    Ensures:
        - returns a set of `id()` values covering each bare string statement (docstrings and
          any other standalone string, f-strings included) and all nodes under it
        - every other string constant is left out of the set, so it is checked as code
    """
    ids = set()
    for node in ast.walk( tree ):
        if isinstance( node, ast.Expr ) and isinstance( node.value, ( ast.Constant, ast.JoinedStr ) ):
            ids.update( id( sub ) for sub in ast.walk( node.value ) )
    return ids


def _call_name( node ):
    """
    Return the bare name a call is made through.

    Requires:
        - node is an `ast.Call`

    Ensures:
        - returns `join` for `os.path.join( ... )`, `Path` for `Path( ... )`, and "" for anything else
    """
    func = node.func
    if isinstance( func, ast.Attribute ): return func.attr
    if isinstance( func, ast.Name ): return func.id
    return ""


def _path_text( node, bases ):
    """
    Read one expression as the path text it builds.

    Requires:
        - node is an `ast` expression node
        - bases is a set of names known to hold a `.claude` folder

    Ensures:
        - a string gives its value; an f-string gives its literal parts, with "{}" for each field
        - a name in bases gives ".claude"
        - `a + b` gives the two texts joined; `a / b` gives them joined with "/"
        - a `join` or `joinpath` call gives its arguments joined with "/"
        - a call of a passing-through name (expanduser, Path, str, and the like) gives its first argument's text
        - anything else gives "{}"
    """
    if isinstance( node, ast.Constant ) and isinstance( node.value, str ): return node.value
    if isinstance( node, ast.JoinedStr ):
        return "".join( v.value if isinstance( v, ast.Constant ) else "{}" for v in node.values )
    if isinstance( node, ast.Name ) and node.id in bases: return ".claude"
    if isinstance( node, ast.BinOp ) and isinstance( node.op, ast.Add ):
        return _path_text( node.left, bases ) + _path_text( node.right, bases )
    if isinstance( node, ast.BinOp ) and isinstance( node.op, ast.Div ):
        return _path_text( node.left, bases ) + "/" + _path_text( node.right, bases )
    if isinstance( node, ast.Call ):
        name = _call_name( node )
        if name in JOINERS: return "/".join( _path_text( a, bases ) for a in node.args )
        if name in PASSERS and node.args: return _path_text( node.args[ 0 ], bases )
    return "{}"


def _names_holding_claude( tree ):
    """
    Return the names a file assigns a path ending in the `.claude` folder.

    Requires:
        - tree is a parsed `ast.Module`

    Ensures:
        - returns the set of plain names whose assigned value reads, by _path_text, as a path whose last part is `.claude`
        - a name assigned from another such name is included, to a depth of three assignments
    """
    bases = set()
    for _ in range( 3 ):
        for node in ast.walk( tree ):
            if isinstance( node, ( ast.Assign, ast.AnnAssign ) ) and node.value is not None:
                targets = node.targets if isinstance( node, ast.Assign ) else [ node.target ]
                text    = re.sub( "/+", "/", _path_text( node.value, bases ) ).rstrip( "/" )
                if text == ".claude" or text.endswith( "/.claude" ):
                    bases.update( t.id for t in targets if isinstance( t, ast.Name ) )
    return bases


def offending_strings( source ):
    """
    Return the code expressions in one file's source that spell the session-bridge folder.

    Requires:
        - source is the text of a Python file that parses

    Ensures:
        - returns a list of ( line number, path text ) pairs, in line order, one per line, holding the longest text on that line
        - a pair is listed when an expression's path text, with repeated slashes collapsed, holds
          `.claude/sessions` as whole path parts
        - a dict or call that merely holds both words, not joined as a path, is not listed
        - comments and standalone strings (docstrings) are never listed

    Raises:
        - SyntaxError when the source does not parse
    """
    tree  = ast.parse( source )
    prose = _prose_nodes( tree )
    bases = _names_holding_claude( tree )
    found = { }
    for node in ast.walk( tree ):
        if id( node ) in prose or not isinstance( node, ( ast.Constant, ast.JoinedStr, ast.BinOp, ast.Call ) ): continue
        text = re.sub( "/+", "/", _path_text( node, bases ) )
        if PATTERN.search( text ) and len( text ) > len( found.get( node.lineno, "" ) ): found[ node.lineno ] = text
    return sorted( found.items() )


def _population( root ):
    """
    List the tracked Python files the census walks.

    Requires:
        - root is the top of a git checkout

    Ensures:
        - returns the repo-relative paths of tracked `.py` files, without the seam module,
          the R&D folders, the test folders or any file named `test_*.py`
    """
    files = subprocess.run( [ "git", "ls-files", "*.py" ], cwd=root,
                            capture_output=True, text=True, check=True ).stdout.split()
    return [
        rel for rel in files
        if rel != SEAM
        and not rel.startswith( SKIP_PREFIX )
        and not os.path.basename( rel ).startswith( "test_" )
    ]


@pytest.mark.parametrize( "source, expected", [
    ( 'X = "~/.claude/sessions"\n',                                   [ ( 1, "~/.claude/sessions" ) ] ),
    ( 'X = f"{h}/.claude/sessions/cc-1.json"\n',                      [ ( 1, "{}/.claude/sessions/cc-1.json" ) ] ),
    ( 'X = Path.home() / ".claude" / "sessions"\n',                   [ ( 1, "{}/.claude/sessions" ) ] ),
    ( 'X = os.path.join( h, ".claude", "sessions/x" )\n',             [ ( 1, "{}/.claude/sessions/x" ) ] ),
    ( 'X = os.path.expanduser( "~/.claude/" ) + "sessions"\n',        [ ( 1, "~/.claude/sessions" ) ] ),
    ( 'X = home + "/.claude" + "/sessions"\n',                        [ ( 1, "{}/.claude/sessions" ) ] ),
    ( 'C = Path.home() / ".claude"\nY = "x"\nZ = C / "sessions"\n',   [ ( 3, ".claude/sessions" ) ] ),
    ( '"""Reads ~/.claude/sessions."""\n# ~/.claude/sessions\n',      [ ] ),
    ( 'def f():\n    """Writes ~/.claude/sessions."""\n    return 1\n', [ ] ),
    ( 'X = Path.home() / ".claude" / "mementos"\n',                   [ ] ),
    ( 'X = { "dir": ".claude", "sessions": 1 }\n',                    [ ] ),
    ( 'X = "~/.claude/sessions-test"\n',                              [ ] ),
] )
def test_the_detector_tells_a_use_from_a_mention( source, expected ):
    assert offending_strings( source ) == expected


def test_every_session_bridge_path_goes_through_the_seam():
    """Census: a code string naming the bridge folder outside the seam is a second authority."""
    root  = os.environ[ "LUPIN_ROOT" ]
    files = _population( root )
    assert len( files ) > 1000, f"the census walked the wrong population: {len( files )} files"
    with open( os.path.join( root, SEAM ), encoding="utf-8" ) as fh:
        assert offending_strings( fh.read() ), "the detector cannot see the seam's own default"
    found = { }
    for rel in files:
        with open( os.path.join( root, rel ), encoding="utf-8" ) as fh:
            hits = offending_strings( fh.read() )
        if hits: found[ rel ] = hits
    assert found == { }, f"resolve these through sessions_dir() instead: {found}"

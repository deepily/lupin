"""
Census: no tracked Python code names the session-bridge folder except the seam.

`sessions_dir()` in `src/lupin_cli/claude_code/hooks/lib/sessions_dir.py` is the one place
that resolves the session-bridge folder. Its default is to move to a folder Lupin owns, which
only works if no reader or writer spells the old path itself.

The guard reads each file's syntax tree, not its text. Comments are not in the tree, and a
string that stands alone as a statement (a docstring) is prose, so both are skipped. Every
other string constant is code and is checked. Two spellings are refused: a string containing
`.claude/sessions`, and a `.claude` string followed directly by a `sessions` string, as in
`Path.home() / ".claude" / "sessions"`.

The population is every tracked `.py` file outside the test folders and the R&D folders,
taken from `git ls-files`. The seam module itself is left out, because it holds the default.
"""

import ast
import os
import subprocess

import pytest

SEAM        = "src/lupin_cli/claude_code/hooks/lib/sessions_dir.py"
LITERAL     = ".claude/sessions"
CLAUDE_PART = { ".claude", "~/.claude" }
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


def offending_strings( source ):
    """
    Return the code strings in one file's source that spell the session-bridge folder.

    Requires:
        - source is the text of a Python file that parses

    Ensures:
        - returns a list of ( line number, string value ) pairs, in source order
        - a pair is listed when a code string contains `.claude/sessions`, or when a `.claude`
          string is directly followed by a string that is `sessions` or starts `sessions/`
        - comments and standalone strings (docstrings) are never listed

    Raises:
        - SyntaxError when the source does not parse
    """
    tree    = ast.parse( source )
    prose   = _prose_nodes( tree )
    strings = sorted(
        ( node.lineno, node.col_offset, node.value )
        for node in ast.walk( tree )
        if isinstance( node, ast.Constant ) and isinstance( node.value, str ) and id( node ) not in prose
    )
    found = []
    for i, ( line, _col, value ) in enumerate( strings ):
        if LITERAL in value:
            found.append( ( line, value ) )
            continue
        if value in CLAUDE_PART and i + 1 < len( strings ):
            following = strings[ i + 1 ][ 2 ]
            if following == "sessions" or following.startswith( "sessions/" ):
                found.append( ( line, value + " / " + following ) )
    return found


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
    ( 'X = "~/.claude/sessions"\n',                          [ ( 1, "~/.claude/sessions" ) ] ),
    ( 'X = f"{h}/.claude/sessions/cc-1.json"\n',             [ ( 1, "/.claude/sessions/cc-1.json" ) ] ),
    ( 'X = Path.home() / ".claude" / "sessions"\n',          [ ( 1, ".claude / sessions" ) ] ),
    ( 'X = os.path.join( h, ".claude", "sessions/x" )\n',    [ ( 1, ".claude / sessions/x" ) ] ),
    ( '"""Reads ~/.claude/sessions."""\n# ~/.claude/sessions\n', [ ] ),
    ( 'def f():\n    """Writes ~/.claude/sessions."""\n    return 1\n', [ ] ),
    ( 'X = Path.home() / ".claude" / "mementos"\n',          [ ] ),
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

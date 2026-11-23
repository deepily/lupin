"""
Census: only the seam names the session-bridge folder, by its old or its new name.

`sessions_dir()` in `src/lupin_cli/claude_code/hooks/lib/sessions_dir.py` is the one place
that resolves the session-bridge folder. Its default is to move to a folder Lupin owns, which
only works if no reader or writer spells the old path itself.

The guard reads each file's syntax tree, not its text. Comments are not in the tree, and a
string that stands alone as a statement (a docstring) is prose, so both are skipped. A dict
key is a label, not a path, so it is skipped too. The rule is about the pieces, not the way
they are joined, because no reading of joins is complete. A file is refused when a code string
holds `.claude/sessions` as whole path parts. It is also refused when one code string ends in
the `.claude` folder and another has `sessions` as a whole path part. A wrong
refusal is loud and cheap to clear, while a missed path is silent. Not seen: a file that gets
the `.claude` base from another module and adds only `sessions`.

The population is every tracked `.py` file outside the test folders and the R&D folders,
taken from `git ls-files`. The seam module itself is left out, because it holds the default.
"""

import ast
import os
import re
import subprocess

import pytest

SEAM        = "src/lupin_cli/claude_code/hooks/lib/sessions_dir.py"
WHOLE       = re.compile( r"(?:^|/)\.claude/+(?:lupin-)?sessions(?:/|$)" )
CLAUDE_END  = re.compile( r"(?:^|/)\.claude/*$" )
SESSIONS    = re.compile( r"(?:^|/)(?:lupin-)?sessions(?:/|$)" )
KEY_READERS = { "get", "pop", "setdefault" }
SKIP_PREFIX = ( "src/rnd/", "src/cosa/rnd/", "src/tests/", "src/cosa/tests/" )


def _skipped_nodes( tree ):
    """
    Return the ids of every string node that is prose or a key.

    Requires:
        - tree is a parsed `ast.Module`

    Ensures:
        - returns a set of `id()` values covering each bare string statement (docstrings and
          any other standalone string, f-strings included) and all nodes under it
        - also covers every key, which labels a value and is not a path: a dict literal's keys, a
          string subscript such as `snap[ "sessions" ]`, and the first argument of `.get`, `.pop` and `.setdefault`
        - every other string constant is left out of the set, so it is checked as code
    """
    ids = set()
    for node in ast.walk( tree ):
        if isinstance( node, ast.Expr ) and isinstance( node.value, ( ast.Constant, ast.JoinedStr ) ):
            ids.update( id( sub ) for sub in ast.walk( node.value ) )
        if isinstance( node, ast.Dict ):
            ids.update( id( k ) for k in node.keys if k is not None )
        if isinstance( node, ast.Subscript ) and isinstance( node.slice, ast.Constant ):
            ids.add( id( node.slice ) )
        if isinstance( node, ast.Call ) and isinstance( node.func, ast.Attribute ) and node.func.attr in KEY_READERS and node.args:
            ids.add( id( node.args[ 0 ] ) )
    return ids


def offending_strings( source ):
    """
    Return the code strings in one file's source that spell the session-bridge folder.

    Requires:
        - source is the text of a Python file that parses

    Ensures:
        - returns a list of ( line number, string value ) pairs, in source order
        - lists every code string holding `.claude/sessions` as whole path parts
        - when the file has both a code string ending in the `.claude` folder and one with `sessions` as a
          whole path part, lists all of both kinds, however the file joins them
        - returns [] when neither holds; comments, docstrings and dict keys are never listed

    Raises:
        - SyntaxError when the source does not parse
    """
    tree    = ast.parse( source )
    skipped = _skipped_nodes( tree )
    strings = sorted(
        ( node.lineno, node.col_offset, node.value )
        for node in ast.walk( tree )
        if isinstance( node, ast.Constant ) and isinstance( node.value, str ) and id( node ) not in skipped
    )
    whole    = [ ( line, value ) for line, _col, value in strings if WHOLE.search( value ) ]
    claude   = [ ( line, value ) for line, _col, value in strings if CLAUDE_END.search( value ) ]
    sessions = [ ( line, value ) for line, _col, value in strings if SESSIONS.search( value ) ]
    pieces   = claude + sessions if claude and sessions else []
    return sorted( set( whole + pieces ) )


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


USES = [
    'X = "~/.claude/sessions"\n',
    'X = "~/.claude/lupin-sessions"\n',
    'X = Path.home() / ".claude" / "lupin-sessions"\n',
    'X = f"{h}/.claude/sessions/cc-1.json"\n',
    'X = Path.home() / ".claude" / "sessions"\n',
    'X = os.path.join( h, ".claude", "sessions/x" )\n',
    'X = os.path.expanduser( "~/.claude/" ) + "sessions"\n',
    'X = home + "/.claude" + "/sessions"\n',
    'C = Path.home() / ".claude"\nY = "x"\nZ = C / "sessions"\n',
    'X = Path( "~/.claude" ).expanduser() / "sessions"\n',
    'X = Path.home().joinpath( ".claude" ).joinpath( "sessions" )\n',
    'C = Path.home() / ".claude"\nX = f"{C}/sessions"\n',
    'class A:\n    def __init__( self ):\n        self.base = Path.home() / ".claude"\n    def p( self ):\n        return self.base / "sessions"\n',
    'p = Path.home() / ".claude"\np /= "sessions"\n',
    'X = "%s/sessions" % ( home + "/.claude" )\n',
    'X = "{}/sessions".format( Path.home() / ".claude" )\n',
    'X = "/".join( [ home, ".claude", "sessions" ] )\n',
    'def base():\n    return Path.home() / ".claude"\nX = base() / "sessions"\n',
    'if ( c := Path.home() / ".claude" ):\n    X = c / "sessions"\n',
]

MENTIONS = [
    '"""Reads ~/.claude/sessions."""\n# ~/.claude/sessions\n',
    'def f():\n    """Writes ~/.claude/sessions."""\n    return 1\n',
    'X = Path.home() / ".claude" / "mementos"\n',
    'X = { ".claude": 1, "sessions": 2 }\n',
    'X = "~/.claude/sessions-test"\n',
    'X = "/api/sessions"\n',
    'W = os.path.join( root, ".claude", "worktrees" )\nn = snap[ "sessions" ]\n',
    'W = Path.home() / ".claude"\nn = snap.get( "sessions", [] )\nm = d.pop( "sessions" )\nd.setdefault( "sessions", 0 )\n',
]


@pytest.mark.parametrize( "source", USES )
def test_the_detector_sees_every_spelling_of_the_folder( source ):
    assert offending_strings( source ), source


@pytest.mark.parametrize( "source", MENTIONS )
def test_the_detector_passes_prose_labels_and_other_folders( source ):
    assert offending_strings( source ) == [], source


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

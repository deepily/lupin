"""
Linter for `#` comment lines in Python: banners, shouting and emphasis glyphs.

Uses tokenize, so a `#` inside a string is not a comment. The sentence, reference and history
rules are not applied to comments, which hold working notes rather than documentation.

Three deterministic rules check what a comment points at or holds.
`line-pointer` flags a `file.ext:NNN` citation. `dangling-path` flags a cited repo path git does not track.
`commented-out-code` flags a comment that is a Python statement.
"""

import ast
import io
import re
import subprocess
import sys
import tokenize

from .cli import run_linter
from .text_rules import Finding, emphasis_findings, rhetoric_findings, history_findings
from .waivers import WAIVER_REGEX


POINTER_EXTENSIONS = "py|ts|js|mjs|md|ini|sh|json|yml|yaml|toml|css|html|dart|sql|txt|cfg"
LINE_POINTER_RE    = re.compile( rf"(?<![\w/.~-])((?:[\w.-]+/)*[\w.-]+\.(?:{POINTER_EXTENSIONS})):(\d+)\b" )
CITED_PATH_RE      = re.compile( rf"(?<![\w/.~-])((?:[\w.-]+/)+[\w.-]+\.(?:{POINTER_EXTENSIONS}))\b" )
HEADER_RE          = re.compile( r"(?:async\s+)?(?:if|for|while|with|def|class)\b.*:$" )
BARE_HEADERS       = ( "else:", "try:", "finally:" )
PLACEHOLDER_STEMS  = frozenset( { "foo", "bar", "baz", "x", "y", "a", "b", "example", "test_foo", "test_bar", "test_x" } )
WAIVABLE_RULES     = frozenset( { "line-pointer", "dangling-path", "commented-out-code" } )
CODE_STATEMENTS    = ( ast.Assign, ast.AugAssign, ast.Import, ast.ImportFrom, ast.Delete )
KEYWORD_STATEMENTS = ( ast.Return, ast.Raise, ast.Assert )


GIT_TIMEOUT_SECONDS = 30
GIT_FAILURES        = ( RuntimeError, OSError, subprocess.TimeoutExpired, UnicodeDecodeError )
PATH_CACHE          = { "listings": None, "failure": None }


def tracked_paths( root ):
    """
    List the files git tracks under root, as a frozenset of repo-relative posix paths.

    Requires:
        - root is a git working tree

    Ensures:
        - returns the index listing, so a file staged for the first time counts as tracked
        - the answer is cached per root while main runs a whole-corpus pass, and read from git each time otherwise, so a commit sees the index as it is

    Raises:
        - RuntimeError when git cannot list the files, OSError when git is missing, subprocess.TimeoutExpired when it does not answer in GIT_TIMEOUT_SECONDS
    """
    listings = PATH_CACHE[ "listings" ]
    if listings is not None and root in listings: return listings[ root ]
    res = subprocess.run( [ "git", "-C", str( root ), "ls-files", "-z" ], capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS )
    if res.returncode != 0: raise RuntimeError( f"git ls-files failed in {root}: {res.stderr.strip()}" )
    found = frozenset( name for name in res.stdout.split( "\0" ) if name )
    if listings is not None: listings[ root ] = found
    return found


def ignored_paths( root, names ):
    """
    List which of the named paths git ignores.

    Requires:
        - root is a git working tree
        - names is a non-empty list of repo-relative paths

    Ensures:
        - returns the subset `git check-ignore` matches, as a set

    Raises:
        - RuntimeError when git cannot answer, OSError when git is missing, subprocess.TimeoutExpired when it does not answer in GIT_TIMEOUT_SECONDS
    """
    res = subprocess.run( [ "git", "-C", str( root ), "check-ignore", "-z", "--stdin" ], input="\0".join( names ) + "\0", capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS )
    if res.returncode not in ( 0, 1 ): raise RuntimeError( f"git check-ignore failed in {root}: {res.stderr.strip()}" )
    return { name for name in res.stdout.split( "\0" ) if name }


def take_path_failure():
    """
    Hand over, and clear, the reason the dangling-path check could not run.

    Requires:
        - nothing

    Ensures:
        - returns the one-line reason since the last call, or None when git answered every time
        - clears it, so each run reports at most once

    Raises:
        - nothing
    """
    reason = PATH_CACHE[ "failure" ]
    PATH_CACHE[ "failure" ] = None
    return reason


def line_pointer_findings( text, path, line ):
    """
    Flag every `file.ext:NNN` citation in one comment.

    Requires:
        - text is the comment without its leading hash

    Ensures:
        - returns one line-pointer Finding per citation, naming it
        - the extension must be one of POINTER_EXTENSIONS, so host:port and version strings pass

    Raises:
        - nothing
    """
    return [ Finding( path, line, "line-pointer", f"'{hit.group( 0 )}' cites a line number, which goes stale; name the function or heading" )
             for hit in LINE_POINTER_RE.finditer( text ) ]


def dangling_path_findings( text, path, line, root ):
    """
    Flag every cited repo path that git does not track.

    Requires:
        - text is the comment without its leading hash
        - root is the repo working tree, or None to skip the check

    Ensures:
        - a path counts as cited when it holds a slash, ends in a POINTER_EXTENSIONS suffix and starts with a top-level directory git tracks
        - returns one dangling-path Finding per cited path that is not tracked
        - a path with a wildcard, a leading slash or a URL is never matched
        - a path that holds `...`, names a placeholder such as foo or x, or that `git check-ignore` matches is not flagged

        - a git failure (non-zero exit, git missing, no answer in time) turns this one rule off for the rest of the run: it returns [] and records the reason for take_path_failure, so every other rule still runs

    Raises:
        - nothing
    """
    if root is None or PATH_CACHE[ "failure" ] is not None: return []
    cited = [ hit.group( 1 ) for hit in CITED_PATH_RE.finditer( text ) ]
    if not cited: return []
    try:
        tracked = tracked_paths( str( root ) )
        tops    = { name.split( "/", 1 )[ 0 ] for name in tracked if "/" in name }
        missing = [ name for name in cited if name.split( "/", 1 )[ 0 ] in tops and name not in tracked
                    and "..." not in name and name.rsplit( "/", 1 )[ -1 ].rsplit( ".", 1 )[ 0 ] not in PLACEHOLDER_STEMS ]
        if not missing: return []
        ignored = ignored_paths( str( root ), missing )
    except GIT_FAILURES as err:
        PATH_CACHE[ "failure" ] = f"{type( err ).__name__}: {err}"
        return []
    return [ Finding( path, line, "dangling-path", f"'{name}' is not a file git tracks" ) for name in missing if name not in ignored ]


def is_commented_out_code( text ):
    """
    Say whether one comment is a Python statement rather than prose.

    Requires:
        - text is the comment without its leading hash

    Ensures:
        - True for an assignment, import, delete or call that parses on its own
        - True for a return, raise or assert that parses and holds a bracket, dot or equals sign, so prose such as `return early` passes
        - True for an if, for, while, with, def or class header ending in a colon, and for else:, try: and finally:
        - False for prose, a bare word, a pragma such as `noqa: E501`, and a bare name or attribute
        - a `doc-lint: waive` marker, with or without its own hash, is cut off before the parse, so it never changes the answer

    Raises:
        - nothing
    """
    marker = WAIVER_REGEX.search( text )
    body   = ( text[ : marker.start() ] if marker else text ).strip()
    if not body: return False
    if body in BARE_HEADERS: return True
    source = body + "\n    pass\n" if HEADER_RE.match( body ) else body
    try:
        tree = ast.parse( source )
    except ( SyntaxError, ValueError ):
        return False
    if len( tree.body ) != 1: return False
    node = tree.body[ 0 ]
    if isinstance( node, ( ast.If, ast.For, ast.While, ast.With, ast.AsyncFor, ast.AsyncWith, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef ) ): return True
    if isinstance( node, ast.AnnAssign ): return node.value is not None
    if isinstance( node, ast.Expr ): return isinstance( node.value, ast.Call )
    if isinstance( node, KEYWORD_STATEMENTS ): return any( mark in body for mark in "(.=[" )
    return isinstance( node, CODE_STATEMENTS )


def commented_out_code_findings( text, path, line ):
    """
    Flag one comment that is a Python statement.

    Requires:
        - text is the comment without its leading hash

    Ensures:
        - returns one commented-out-code Finding, or an empty list

    Raises:
        - nothing
    """
    if not is_commented_out_code( text ): return []
    return [ Finding( path, line, "commented-out-code", "this comment is code; delete it, git keeps the history" ) ]


def lint_source( path, source, root=None ):
    """
    Lint every `#` comment in one Python file.

    Requires:
        - path is the repo-relative path used in findings
        - root is the repo working tree, or None to skip checks that need it

    Ensures:
        - returns a list of Finding, sorted by line
        - the shebang line is skipped
        - a comment also gets the line-pointer and commented-out-code rules, and the dangling-path rule when root is given
        - a file that cannot be tokenized yields one parse-error finding

    Raises:
        - nothing
    """
    findings = []
    try:
        for tok in tokenize.generate_tokens( io.StringIO( source ).readline ):
            if tok.type != tokenize.COMMENT: continue
            line, text = tok.start[ 0 ], tok.string[ 1 : ]
            if line == 1 and tok.string.startswith( "#!" ): continue
            findings += emphasis_findings( text, path, line )
            findings += rhetoric_findings( text, path, line )
            findings += history_findings( text, path, line )
            findings += line_pointer_findings( text, path, line )
            findings += dangling_path_findings( text, path, line, root )
            findings += commented_out_code_findings( text, path, line )
    except ( tokenize.TokenError, IndentationError ) as err:
        return [ Finding( path, 1, "parse-error", f"cannot tokenize: {err}" ) ]
    return sorted( findings, key=lambda f: ( f.line, f.rule, f.message ) )


def main( argv=None, out=None ):
    """
    Command-line entry point.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]

    Ensures:
        - returns the exit code from run_linter
        - when git could not answer, writes one warning line saying the dangling-path check was skipped

    Raises:
        - nothing beyond run_linter's
    """
    PATH_CACHE[ "listings" ] = {}
    PATH_CACHE[ "failure" ]  = None
    try:
        code = run_linter( "Lint Python # comments for banners, shouting, pointers, dangling paths and dead code.", ( ".py", ), lint_source, sys.argv[ 1: ] if argv is None else argv, out )
        reason = take_path_failure()
        if reason is not None: ( out if out is not None else sys.stdout ).write( f"WARNING: the dangling-path check was skipped, git could not answer ({reason}); every other rule ran\n" )
        return code
    finally:
        PATH_CACHE[ "listings" ] = None


if __name__ == "__main__":
    sys.exit( main() )

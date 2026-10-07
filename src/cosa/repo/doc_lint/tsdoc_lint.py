"""
Doc-comment linter for TypeScript and JavaScript: the text rules over extractor output.

A Node script reads each file with the TypeScript compiler and prints its comments as JSON Lines.
This module groups them per file and runs the same text rules the Python docstrings get. A JSDoc
block gets every rule. A line run, block or trailing comment gets the reduced set that comment_lint
applies to Python comments. The first line run of a file, its header, also gets the summary rule.
Stdlib only apart from the doc_lint modules.

Design: src/rnd/v0.2.2/2026.10.06-ts-js-doc-checker-design.md
"""

import json
import os
import re
import subprocess
import sys

from .changed_ranges import changed_line_ranges, filter_findings
from .cli import build_parser
from .links import design_path_findings
from .rule_lists import DOCSTRING_MAX_LINES
from .text_rules import Finding, emphasis_findings, history_findings, lint_text, rhetoric_findings, summary_findings
from .word_list import configure_root

SUFFIXES          = ( ".ts", ".js", ".mjs" )
EXCLUDED_SEGMENTS = frozenset( { "node_modules", ".venv", "dist" } )
EXTRACTOR_REL     = "src/scripts/ts_doc_extract.mjs"
FILE_HEADER_KEY   = "<file-header>"
CHUNK_SIZE        = 200

# Tags whose first word after the type is a name, not prose.
NAMED_TAGS = frozenset( { "param", "arg", "argument", "property", "prop", "typedef", "template", "callback" } )

TAG_LINE   = re.compile( r"([ \t]*)(@[A-Za-z][\w-]*)" )
NAME_TOKEN = re.compile( r"\[[^\]]*\]|[\w$.]+" )
LINK_SPAN  = re.compile( r"\{@(?:link|linkcode|linkplain)\b[^}]*\}" )


def in_scope( path ):
    """
    Say whether a repo-relative path is a TypeScript or JavaScript file this linter reads.

    Requires:
        - path is a posix repo-relative path

    Ensures:
        - True for a .ts, .js or .mjs file, test files included, since a test header is documentation
        - False under node_modules, .venv or dist, and for a vendored minified file
        - False for every other suffix

    Raises:
        - nothing
    """
    parts = path.split( "/" )
    if not path.endswith( SUFFIXES ): return False
    if any( p in EXCLUDED_SEGMENTS for p in parts[ : -1 ] ): return False
    return not ( parts[ -1 ].endswith( ".min.js" ) and "vendor" in parts[ : -1 ] )


def tracked_files( repo_root ):
    """
    List the git-tracked TypeScript and JavaScript files in scope.

    Requires:
        - repo_root is a git working tree

    Ensures:
        - returns sorted repo-relative posix paths that pass in_scope
        - the population comes from git, never from a disk walk

    Raises:
        - RuntimeError naming the git error when ls-files fails
    """
    res = subprocess.run( [ "git", "-C", str( repo_root ), "ls-files", "--", ":/" ], capture_output=True, text=True, encoding="utf-8" )
    if res.returncode != 0: raise RuntimeError( f"git ls-files failed: {res.stderr.strip()}" )
    return sorted( p for p in res.stdout.split( "\n" ) if in_scope( p ) )


def _balanced_end( text, start ):
    """
    Return the index just past the brace that closes the one at start.

    Requires:
        - text[ start ] is an opening brace

    Ensures:
        - nested braces are counted, so generics and object types close correctly
        - the search runs across line breaks, so a type written over several lines closes
        - returns None when the text ends before the brace closes

    Raises:
        - nothing
    """
    depth = 0
    for i in range( start, len( text ) ):
        if text[ i ] == "{": depth += 1
        elif text[ i ] == "}":
            depth -= 1
            if depth == 0: return i + 1
    return None


def _mask_tag_at( text, start, blank ):
    """
    Blank the parts of one JSDoc tag that are type syntax or names, not prose.

    Requires:
        - start is the offset of the first character of a line in text
        - blank( first, last ) replaces the characters from first up to last with spaces, line breaks kept

    Ensures:
        - the tag word, a balanced type in braces and, for a named tag, the name are blanked
        - a type may run over several lines; the name is read after its closing brace
        - an opening brace that never closes ends the masking after the tag word, so the rest is read as prose
        - a line that does not start with a tag blanks nothing
        - returns the offset just past the last character blanked, or start when nothing was
        - Python docstrings have no such shape, so text_rules never sees it; this masking is new

    Raises:
        - nothing
    """
    tag = TAG_LINE.match( text, start )
    if tag is None: return start
    blank( tag.start( 2 ), tag.end( 2 ) )
    pos = tag.end()
    while pos < len( text ) and text[ pos ] == " ": pos += 1
    if pos < len( text ) and text[ pos ] == "{":
        end = _balanced_end( text, pos )
        if end is None: return tag.end( 2 )
        blank( pos, end )
        pos = end
    if tag.group( 2 )[ 1 : ] in NAMED_TAGS:
        while pos < len( text ) and text[ pos ] == " ": pos += 1
        name = NAME_TOKEN.match( text, pos )
        if name is not None:
            blank( name.start(), name.end() )
            pos = name.end()
    return pos


def mask_jsdoc( text ):
    """
    Blank the JSDoc-only syntax in a comment body before the text rules read it.

    Requires:
        - text is the body of a JSDoc comment, delimiters removed

    Ensures:
        - tags are masked by _mask_tag_at, and each {@link ...} span is blanked
        - nothing else is masked: a backtick span, a dotted name, a URL, a fenced block, a bracketed
          placeholder, a key = value line and a file name reach the rules as they are
        - the result has the same length and the same line breaks as text, also when a type or a
          link runs over several lines

    Raises:
        - nothing
    """
    chars = list( text )

    def blank( first, last ):
        for i in range( first, last ):
            if chars[ i ] != "\n": chars[ i ] = " "

    consumed = 0
    offset   = 0
    for line in text.split( "\n" ):
        if offset >= consumed: consumed = max( consumed, _mask_tag_at( text, offset, blank ) )
        offset += len( line ) + 1
    for link in LINK_SPAN.finditer( text ): blank( link.start(), link.end() )
    return "".join( chars )


def _jsdoc_findings( path, comment, root ):
    """
    Run every rule over one JSDoc block.

    Requires:
        - comment is an extractor record of kind jsdoc
        - root is the repo working tree, or None to skip the Design path check

    Ensures:
        - returns the findings of lint_text with the structure rules and the model-order rule
        - adds a docstring-length finding when the block is longer than DOCSTRING_MAX_LINES
        - with root given, adds a dead-design finding for a Design: path that does not exist

    Raises:
        - nothing
    """
    text     = comment[ "text" ]
    first    = comment[ "start_line" ]
    findings = lint_text( mask_jsdoc( text ), path, first, structure=True, agent_rule=True )
    if root is not None: findings += design_path_findings( text, path, first, root )
    lines = text.strip( "\n" ).count( "\n" ) + 1
    if lines > DOCSTRING_MAX_LINES:
        findings.append( Finding( path, first, "docstring-length", f"JSDoc block of {lines} lines, limit {DOCSTRING_MAX_LINES}" ) )
    return findings


def _plain_findings( path, comment ):
    """
    Run the reduced rule set over one non-JSDoc comment.

    Requires:
        - comment is an extractor record of kind line-run, block or trailing

    Ensures:
        - returns the emphasis, tic and history findings, as comment_lint does for Python comments
        - the history rule runs without its model-order check
        - a file header run also gets the summary rule
        - sentence, reference and length rules are not applied: a comment is a working note

    Raises:
        - nothing
    """
    text     = comment[ "text" ]
    first    = comment[ "start_line" ]
    findings = emphasis_findings( text, path, first ) + rhetoric_findings( text, path, first ) + history_findings( text, path, first, agent_rule=False )
    if comment[ "kind" ] == "line-run" and comment[ "symbol_key" ] == FILE_HEADER_KEY:
        findings += summary_findings( text, path, first )
    return findings


def lint_comment( path, comment, root=None ):
    """
    Lint one extractor comment record.

    Requires:
        - comment holds kind, text, start_line, symbol_key and directive; commented_code is optional
        - root is the repo working tree, or None

    Ensures:
        - a directive comment gives no findings
        - a line run marked as commented-out code gives no findings
        - a JSDoc block gets the full rule set, any other comment the reduced set
        - a finding sits on start_line plus the index of the text line that caused it

    Raises:
        - nothing
    """
    if comment[ "directive" ]: return []
    if comment[ "kind" ] == "jsdoc": return _jsdoc_findings( path, comment, root )
    if comment[ "kind" ] == "line-run" and comment.get( "commented_code", False ): return []
    return _plain_findings( path, comment )


def lint_comments( path, comments, root=None ):
    """
    Lint every extractor record of one file.

    Requires:
        - comments is the list of that file's records: one file record and its comment records
        - root is the repo working tree, or None to skip the Design path check

    Ensures:
        - returns a list of Finding sorted by line, then rule, then message
        - a file record with parse errors adds one parse-error finding, at its first error line
        - the comments of that file are still linted

    Raises:
        - nothing
    """
    findings = []
    for comment in comments:
        if comment[ "kind" ] == "file":
            errors = comment[ "parse_errors" ]
            if errors: findings.append( Finding( path, errors[ 0 ][ "line" ], "parse-error", f"does not parse: {errors[ 0 ][ 'message' ]}" ) )
            continue
        findings += lint_comment( path, comment, root )
    return sorted( findings, key=lambda f: ( f.line, f.rule, f.message ) )


def run_extractor( repo_root, files ):
    """
    Run the Node extractor over files and group its records by file.

    Requires:
        - repo_root is a git working tree that holds the extractor script
        - files is a list of repo-relative paths

    Ensures:
        - returns { path: [ record, ... ] } with a key for every file asked for, in extractor order
        - files go to Node in batches of CHUNK_SIZE, one process per batch, never one per file
        - an empty list starts no process

    Raises:
        - RuntimeError when Node cannot start, exits non-zero, or prints a line that is not JSON
    """
    by_file = { path: [] for path in files }
    script  = os.path.join( str( repo_root ), EXTRACTOR_REL )
    for i in range( 0, len( files ), CHUNK_SIZE ):
        cmd = [ "node", script, "--repo-root", str( repo_root ), *files[ i : i + CHUNK_SIZE ] ]
        try:
            res = subprocess.run( cmd, capture_output=True, text=True, encoding="utf-8" )
        except OSError as err:
            raise RuntimeError( f"cannot run node: {err}" ) from err
        if res.returncode != 0: raise RuntimeError( f"extractor failed: {res.stderr.strip()}" )
        for raw in res.stdout.split( "\n" ):
            if not raw.strip(): continue
            try:
                record = json.loads( raw )
            except json.JSONDecodeError as err:
                raise RuntimeError( f"extractor printed a line that is not JSON: {raw[ : 80 ]!r}" ) from err
            by_file.setdefault( record[ "file" ], [] ).append( record )
    return by_file


def main( argv=None, out=None ):
    """
    Command-line entry point.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]
        - out is a writable text stream, or None for stdout

    Ensures:
        - returns 0, or 1 when --strict is given and findings remain
        - paths given on the command line are filtered by in_scope; none given means every tracked file
        - --changed and --staged keep only findings on touched lines
        - --json prints the findings as a JSON list, otherwise one line per finding and a count

    Raises:
        - RuntimeError from git or from the extractor
    """
    out  = out if out is not None else sys.stdout
    args = build_parser( "Lint TypeScript and JavaScript comments against the text rules." ).parse_args( sys.argv[ 1: ] if argv is None else argv )
    root = args.repo_root
    configure_root( root )
    paths   = sorted( p for p in args.paths if in_scope( p ) ) if args.paths else tracked_files( root )
    by_file = run_extractor( root, paths )
    findings = []
    for path in paths: findings += lint_comments( path, by_file[ path ], root )
    if args.changed is not None or args.staged:
        findings = filter_findings( findings, changed_line_ranges( root, args.changed, cached=args.staged ) )
    if args.json:
        json.dump( [ f._asdict() for f in findings ], out, indent=2 )
        out.write( "\n" )
    else:
        for f in findings: out.write( f"{f.path}:{f.line}: {f.rule}: {f.message}\n" )
        out.write( f"{len( findings )} findings in {len( paths )} files\n" )
    return 1 if args.strict and findings else 0


if __name__ == "__main__":
    sys.exit( main() )

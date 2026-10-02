"""
Dart pair builder: a git range to per-symbol before and after doc-comment text.

The claim harness takes plain text pairs. This module builds them for Dart. It reads two
revisions of a repository with git show. It finds every doc-comment block with the lexer in
dartdoc_lint and names each block by the declaration under it. The two revisions are joined on
( file, symbol ). The output rows have the labelled-set pair shape. A pairs file written here
loads through labelled_pairs.load_pairs once a keys file exists. No model is called.

Known limits:
    - a symbol is "Owner.member": "Owner.new" for the unnamed constructor, "Owner.named" for a named one
    - the owner is the class, mixin, enum or extension whose body holds the block. The body runs from a
      declaration at column 0 ending in { to the next line that starts with } at column 0
    - a one-line declaration has no body, and a nested type is not an owner
    - an unnamed extension ( extension on Foo ) has no name and its blocks read "<unattached>"
    - a renamed or moved symbol is reported as gone and as new, never as a pair
    - two declarations with the same name under one owner are named name, name#2, name#3 in file order
"""

import argparse
import json
import re
import subprocess
import sys

from .dartdoc_lint import doc_blocks
from .docs_only_diff import _show

OWNER_REGEX  = re.compile( r"^(?:(?:abstract|base|sealed|final|interface|mixin)\s+)*(?:class|mixin|enum|extension(?:\s+type)?|typedef)\s+(?!on\b)([A-Za-z_]\w*)?" )
UNNAMED_EXTENSION = re.compile( r"^extension\s+on\b" )
OPERATOR_REGEX = re.compile( r"\boperator\s*([^\s(]+)" )
LIBRARY_REGEX = re.compile( r"^(?:library|part|import|export)\b" )
HEAD_STOP    = re.compile( r"[({=;]|=>" )
MODIFIERS    = frozenset( "static final const late external abstract covariant factory async sync base sealed interface".split() )
MAX_HEAD_LINES = 6
DEFAULT_PREFIX = "lib"


def block_text( text ):
    """
    Normalize one doc block for comparison and storage.

    Requires:
        - text is the joined text of a doc block, comment markers already removed

    Ensures:
        - trailing whitespace is removed from every line
        - leading and trailing blank lines are removed
        - inner blank lines and indentation are kept, so a markdown list or code sample survives

    Raises:
        - nothing
    """
    return "\n".join( line.rstrip() for line in text.split( "\n" ) ).strip( "\n" )


def squash( text ):
    """
    Reduce text to its words for an unchanged check.

    Requires:
        - text is a str

    Ensures:
        - returns the text with every run of whitespace as one space and no edge space

    Raises:
        - nothing
    """
    return " ".join( text.split() )


def _skip_annotations( lines, index ):
    """
    Move past the annotation lines that sit between a doc block and its declaration.

    Requires:
        - lines is a list of source lines; index is a 0-based line to start at

    Ensures:
        - returns the index of the first line that is not blank, not a plain // comment, not the tail
          of a block comment (a line starting with *) and not part of an @annotation, a multi-line annotation included (found by balancing parentheses)
        - returns len( lines ) when the file ends first

    Raises:
        - nothing
    """
    while index < len( lines ):
        stripped = lines[ index ].strip()
        if not stripped or stripped.startswith( "*" ) or ( stripped.startswith( "//" ) and not stripped.startswith( "///" ) ):
            index += 1
            continue
        if stripped.startswith( "@" ):
            depth = stripped.count( "(" ) - stripped.count( ")" )
            index += 1
            while depth > 0 and index < len( lines ):
                depth += lines[ index ].count( "(" ) - lines[ index ].count( ")" )
                index += 1
            continue
        return index
    return index


def declaration_name( lines, index ):
    """
    Name the declaration that starts at a line.

    Requires:
        - lines is a list of source lines; index is the 0-based line of the declaration

    Ensures:
        - returns the identifier the declaration introduces, found from the head before the first
          ( { = ; or =>: the last word of the head with generic arguments removed, so
          "List<String> items" gives "items" and "static bool isRegistered<T extends Object>" gives "isRegistered"
        - a getter is named by its word, a setter as "word=", an operator as "operator==" and so on
          (read from the first line, before the = in the operator is taken for a delimiter)
        - an unnamed extension ( extension on Foo ) gives None
        - a constructor keeps its dots, so "Foo.named" and "factory Foo.fromJson" give "Foo.named" and "Foo.fromJson"
        - a class, mixin, enum, extension or typedef is named by its name
        - library, part, import and export lines give "<library>"
        - returns None when no name can be read

    Raises:
        - nothing
    """
    if index >= len( lines ): return None
    first = lines[ index ].strip()
    if LIBRARY_REGEX.match( first ): return "<library>"
    if UNNAMED_EXTENSION.match( first ): return None
    operator = OPERATOR_REGEX.search( first )
    if operator: return f"operator{operator.group( 1 )}"
    owner = OWNER_REGEX.match( first )
    if owner: return owner.group( 1 )
    head = ""
    for line in lines[ index : index + MAX_HEAD_LINES ]:
        stop = HEAD_STOP.search( line )
        head += " " + ( line[ : stop.start() ] if stop else line )
        if stop: break
    stripped = None
    while stripped != head:
        stripped, head = head, re.sub( r"<[^<>]*>", "", head )
    words = [ w for w in re.split( r"\s+", head.strip() ) if w and w not in MODIFIERS ]
    if not words: return None
    if len( words ) >= 2 and words[ -2 ] == "set": return f"{words[ -1 ]}="
    match = re.search( r"([A-Za-z_$][\w$.]*)$", words[ -1 ] )
    return match.group( 1 ) if match else None


def extract_blocks( source ):
    """
    List the doc-comment blocks of a Dart source with the symbol each documents.

    Requires:
        - source is Dart text

    Ensures:
        - returns [ ( symbol, first_line, text ) ] in file order, text normalized by block_text
        - symbol is "Owner.member" under an owner, else the bare name; a block with no readable
          declaration under it is named "<unattached>"
        - a repeated symbol gets #2, #3 and so on, so every symbol in the result is unique
        - first_line is 1-based

    Raises:
        - nothing
    """
    lines  = source.split( "\n" )
    spans, opened = [], None
    for number, line in enumerate( lines ):
        if not line or line[ 0 ].isspace(): continue
        match = OWNER_REGEX.match( line )
        if match and match.group( 1 ):
            if line.count( "{" ) > line.count( "}" ): opened = ( number, match.group( 1 ) )
        elif line[ 0 ] == "}" and opened is not None:
            spans.append( ( opened[ 0 ], number, opened[ 1 ] ) )
            opened = None
    if opened is not None: spans.append( ( opened[ 0 ], len( lines ), opened[ 1 ] ) )
    out, seen = [], {}
    for first_line, text in doc_blocks( source ):
        count = len( text.split( "\n" ) )
        after = _skip_annotations( lines, first_line - 1 + count )
        name  = declaration_name( lines, after ) or "<unattached>"
        owner = next( ( name_ for start, end, name_ in spans if start < after < end ), None )
        declared_here = after < len( lines ) and OWNER_REGEX.match( lines[ after ].strip() ) and not lines[ after ][ :1 ].isspace()
        if owner is None or declared_here or name in ( "<library>", "<unattached>" ) or name.startswith( f"{owner}." ): symbol = name
        elif name == owner: symbol = f"{owner}.new"
        else: symbol = f"{owner}.{name}"
        seen[ symbol ] = seen.get( symbol, 0 ) + 1
        out.append( ( symbol if seen[ symbol ] == 1 else f"{symbol}#{seen[ symbol ]}", first_line, block_text( text ) ) )
    return out


def dart_files( root, rev, prefix=DEFAULT_PREFIX ):
    """
    List the .dart files tracked under a prefix at a revision.

    Requires:
        - root is a git working tree; rev is a revision

    Ensures:
        - returns sorted repo-relative paths, from git ls-tree and never from a disk walk

    Raises:
        - RuntimeError naming the git error when the listing fails
    """
    res = subprocess.run( [ "git", "-C", str( root ), "ls-tree", "-r", "--name-only", "-z", rev, "--", prefix ], capture_output=True, text=True, encoding="utf-8" )
    if res.returncode != 0: raise RuntimeError( f"git ls-tree {rev} failed: {res.stderr.strip()}" )
    return sorted( p for p in res.stdout.split( "\0" ) if p.endswith( ".dart" ) )


def build_pairs( root, old_rev, new_rev, prefix=DEFAULT_PREFIX, min_words=30, include_unchanged=False ):
    """
    Build the before and after pairs for a Dart range.

    Requires:
        - root is a git working tree holding both revisions
        - min_words is the least word count of the old block that makes it eligible, as in the labelled set

    Ensures:
        - returns ( pairs, report ), pairs in ( file, symbol ) order
        - a pair is one doc block found at old_rev with at least min_words words and a block of the same
          file and symbol at new_rev; its row is { id, file, symbol, old, new, linked_doc }, id being
          "file::symbol" and linked_doc None
        - a pair whose old and new differ only in whitespace is dropped unless include_unchanged
        - the report counts what was not paired and why, so a drop is never silent:
          files_old, files_new, files_only_old, files_only_new, blocks_old, blocks_new, eligible_old,
          dropped_file_deleted, dropped_symbol_gone, dropped_unchanged, pairs, and the two file lists

    Raises:
        - RuntimeError from git when a listing fails
    """
    old_files, new_files = dart_files( root, old_rev, prefix ), dart_files( root, new_rev, prefix )
    only_old = sorted( set( old_files ) - set( new_files ) )
    only_new = sorted( set( new_files ) - set( old_files ) )
    report = { "files_old" : len( old_files ), "files_new" : len( new_files ), "files_only_old" : only_old, "files_only_new" : only_new,
               "blocks_old" : 0, "blocks_new" : 0, "eligible_old" : 0,
               "dropped_file_deleted" : 0, "dropped_symbol_gone" : 0, "dropped_unchanged" : 0, "pairs" : 0 }
    for path in new_files: report[ "blocks_new" ] += len( extract_blocks( _show( root, new_rev, path ) or "" ) )
    pairs = []
    for path in old_files:
        old_blocks = extract_blocks( _show( root, old_rev, path ) or "" )
        report[ "blocks_old" ] += len( old_blocks )
        new_source = _show( root, new_rev, path )
        new_by_symbol = { s : t for s, _, t in extract_blocks( new_source ) } if new_source is not None else {}
        for symbol, _, old_text in old_blocks:
            if len( old_text.split() ) < min_words: continue
            report[ "eligible_old" ] += 1
            if new_source is None:
                report[ "dropped_file_deleted" ] += 1
                continue
            if symbol not in new_by_symbol:
                report[ "dropped_symbol_gone" ] += 1
                continue
            new_text = new_by_symbol[ symbol ]
            if squash( old_text ) == squash( new_text ) and not include_unchanged:
                report[ "dropped_unchanged" ] += 1
                continue
            pairs.append( { "id" : f"{path}::{symbol}", "file" : path, "symbol" : symbol, "old" : old_text, "new" : new_text, "linked_doc" : None } )
    report[ "pairs" ] = len( pairs )
    return pairs, report


def write_jsonl( pairs, path ):
    """
    Write pairs as JSON Lines.

    Requires:
        - pairs is a list of dicts; path is a writable file path

    Ensures:
        - one JSON object per line, UTF-8, keys in insertion order

    Raises:
        - OSError when the file cannot be written
    """
    with open( path, "w", encoding="utf-8" ) as handle:
        for pair in pairs: handle.write( json.dumps( pair, ensure_ascii=False ) + "\n" )


def main( argv=None, out=None ):
    """
    Command line: build the pairs for a Dart range and print the report.

    Requires:
        - --repo-root is a git working tree holding --old and --new

    Ensures:
        - writes the pairs to --out when given
        - prints the report as JSON, the two file lists included
        - returns 0

    Raises:
        - RuntimeError from git
    """
    out = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="Build before and after doc-comment pairs for a Dart git range" )
    parser.add_argument( "--repo-root", required=True, help="git working tree that holds both revisions" )
    parser.add_argument( "--old", required=True, help="revision for the old text" )
    parser.add_argument( "--new", required=True, help="revision for the new text" )
    parser.add_argument( "--prefix", default=DEFAULT_PREFIX, help="directory to read, default lib" )
    parser.add_argument( "--min-words", type=int, default=30, help="least words in the old block, default 30" )
    parser.add_argument( "--include-unchanged", action="store_true", help="keep pairs whose text did not change" )
    parser.add_argument( "--out", help="write the pairs here as JSON Lines" )
    args = parser.parse_args( argv )
    pairs, report = build_pairs( args.repo_root, args.old, args.new, args.prefix, args.min_words, args.include_unchanged )
    if args.out: write_jsonl( pairs, args.out )
    out.write( json.dumps( report, indent=2 ) + "\n" )
    return 0


if __name__ == "__main__": sys.exit( main() )  # pragma: no cover -- script entry, main() is tested

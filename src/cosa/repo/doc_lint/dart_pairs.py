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
      declaration at column 0 to the next line that starts with } at column 0. The { may sit on the
      header line or on an indented line after it
    - a block turned into a // comment is paired with that comment (new_kind plain_comment), a removed one
      with empty text (none); a vanished declaration is still dropped
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
DIRECTIVE_REGEX = re.compile( r"^(?:[a-z][\w-]*:(?!//)|dart format (?:on|off)\b)" )
MARKER_REGEX = re.compile( r"^[A-Z]{2,}(?:\([^)]*\))?(?::|\s*$)" )
HEAD_STOP    = re.compile( r"[({}=;,]|=>" )
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


def _after_parentheses( text, start ):
    """
    Return the text after the parenthesis that opens at start and its matching close.

    Requires:
        - text[ start ] is an opening parenthesis

    Ensures:
        - nested parentheses are balanced
        - returns "" when the parenthesis never closes

    Raises:
        - nothing
    """
    depth = 0
    for position in range( start, len( text ) ):
        if text[ position ] == "(": depth += 1
        elif text[ position ] == ")":
            depth -= 1
            if depth == 0: return text[ position + 1 : ]
    return ""


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
        - a member whose type is a function type, such as "final void Function( int x )? onTap;", is named by the
          word after the closing parenthesis of the parameter list ( onTap ), not by "Function"
        - an enum value with a trailing comma is named without the comma
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
    text, previous = " ".join( lines[ index : index + MAX_HEAD_LINES ] ), None
    while previous != text:
        previous, text = text, re.sub( r"<[^<>]*>", "", text )
    stop = HEAD_STOP.search( text )
    head = text[ : stop.start() ] if stop else text
    if stop and text[ stop.start() ] == "(" and head.split()[ -1: ] == [ "Function" ]:
        after = _after_parentheses( text, stop.start() )
        named = re.match( r"\s*\??\s*([A-Za-z_$][\w$]*)", after )
        return named.group( 1 ) if named else None
    words = [ w for w in re.split( r"\s+", head.strip() ) if w and w not in MODIFIERS ]
    if not words: return None
    if len( words ) >= 2 and words[ -2 ] == "set": return f"{words[ -1 ]}="
    match = re.search( r"([A-Za-z_$][\w$.]*)$", words[ -1 ] )
    return match.group( 1 ) if match else None


def _header_opens_body( lines, number ):
    """
    Tell whether the owner header at a line opens its body, even over several lines.

    Requires:
        - lines is a list of source lines and number indexes an owner header at column 0

    Ensures:
        - returns True when the header, or the indented lines right after it, bring more { than }
          before a ; or a blank or column-0 line ends the search
        - returns False for a header that ends in ; or never opens a body

    Raises:
        - nothing
    """
    opens = 0
    for index in range( number, len( lines ) ):
        line = lines[ index ]
        if index > number and ( not line or not line[ 0 ].isspace() ): return False
        opens += line.count( "{" ) - line.count( "}" )
        if opens > 0: return True
        if ";" in line: return False
    return False


def _owner_spans( lines ):
    """
    Find the owner bodies of a Dart source.

    Requires:
        - lines is a list of source lines

    Ensures:
        - returns [ ( first_line_index, end_line_index, owner_name ) ] for each class, mixin, enum or
          extension that opens with { at column 0 and closes with } at column 0 (or the end of the file)

    Raises:
        - nothing
    """
    spans, opened = [], None
    for number, line in enumerate( lines ):
        if not line or line[ 0 ].isspace(): continue
        match = OWNER_REGEX.match( line )
        if match and match.group( 1 ):
            if _header_opens_body( lines, number ): opened = ( number, match.group( 1 ) )
        elif line[ 0 ] == "}" and opened is not None:
            spans.append( ( opened[ 0 ], number, opened[ 1 ] ) )
            opened = None
    if opened is not None: spans.append( ( opened[ 0 ], len( lines ), opened[ 1 ] ) )
    return spans


def _symbol( name, owner ):
    """Ensures: returns Owner.member, Owner.new or the bare name for a declaration."""
    if owner is None or name in ( "<library>", "<unattached>" ) or name.startswith( f"{owner}." ): return name
    return f"{owner}.new" if name == owner else f"{owner}.{name}"


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
    spans  = _owner_spans( lines )
    out, seen = [], {}
    for first_line, text in doc_blocks( source ):
        count = len( text.split( "\n" ) )
        after = _skip_annotations( lines, first_line - 1 + count )
        name  = declaration_name( lines, after ) or "<unattached>"
        owner = next( ( name_ for start, end, name_ in spans if start < after < end ), None )
        symbol = _symbol( name, owner )
        seen[ symbol ] = seen.get( symbol, 0 ) + 1
        out.append( ( symbol if seen[ symbol ] == 1 else f"{symbol}#{seen[ symbol ]}", first_line, block_text( text ) ) )
    return out


def declarations( source ):
    """
    List the declarations at member level, whether or not a comment sits above them.

    Requires:
        - source is Dart text

    Ensures:
        - returns [ ( symbol, line_index ) ] in file order, named as extract_blocks names a block's symbol
          and numbered #2, #3 for a repeat
        - a member is a line at the smallest indent found in its owner's body; deeper lines (a statement
          in a method body, a parameter on its own line) and annotation lines are not declarations
        - a top-level declaration is a line at column 0 outside an owner's body

    Raises:
        - nothing
    """
    lines = source.split( "\n" )
    spans = _owner_spans( lines )
    found, inside = [], set()
    for start, end, owner in spans:
        body = [ i for i in range( start + 1, min( end, len( lines ) ) ) if lines[ i ].strip() and not lines[ i ].lstrip().startswith( "//" ) ]
        inside.update( range( start + 1, min( end, len( lines ) ) ) )
        if not body: continue
        indent = min( len( lines[ i ] ) - len( lines[ i ].lstrip() ) for i in body )
        found += [ ( i, owner ) for i in body if len( lines[ i ] ) - len( lines[ i ].lstrip() ) == indent and lines[ i ].lstrip()[ 0 ] not in "@)]}*" ]
    found += [ ( i, None ) for i, line in enumerate( lines ) if i not in inside and line and not line[ 0 ].isspace() and line[ 0 ] not in "@)]}*/" ]
    out, seen = [], {}
    for index, owner in sorted( found ):
        name = declaration_name( lines, index )
        if name is None or name == "<library>": continue
        symbol = _symbol( name, owner )
        seen[ symbol ] = seen.get( symbol, 0 ) + 1
        out.append( ( symbol if seen[ symbol ] == 1 else f"{symbol}#{seen[ symbol ]}", index ) )
    return out


def comment_prose( run ):
    """
    Keep the prose of a run of // lines and drop the tool directives and task markers in it.

    Requires:
        - run is a list of // comment lines

    Ensures:
        - a line is a directive when, after the markers, it is a lowercase word glued to a colon (not a URL)
          or a dart format on or off switch; it is dropped wherever it sits
        - a line is a marker when it is a word of two or more capitals, an optional owner in parentheses, and
          a colon or the end of the line; it and every later line of the run are dropped
        - returns the remaining lines, markers removed and normalized by block_text, or an empty string

    Raises:
        - nothing
    """
    kept = []
    for line in run:
        text = re.sub( r"^\s*//\s?", "", line )
        if MARKER_REGEX.match( text.strip() ): break
        if DIRECTIVE_REGEX.match( text.strip() ): continue
        kept.append( text )
    return block_text( "\n".join( kept ) )


def plain_comments( source ):
    """
    Map each declaration to the plain // comment directly above it.

    Requires:
        - source is Dart text

    Ensures:
        - returns { symbol: text } for a run of // lines (not ///) that ends on the line just above the
          declaration or just above its annotations; a blank line in between means no comment
        - text has the // markers and one leading space removed and is normalized by block_text
        - tool directives and task markers are not text (see comment_prose); a run of nothing else is no comment
        - a run above anything that is not a member-level declaration is ignored

    Raises:
        - nothing
    """
    lines = source.split( "\n" )
    by_line = { index : symbol for symbol, index in declarations( source ) }
    plain = lambda line: line.strip().startswith( "//" ) and not line.strip().startswith( "///" )
    out, index = {}, 0
    while index < len( lines ):
        if not plain( lines[ index ] ):
            index += 1
            continue
        end = index
        while end + 1 < len( lines ) and plain( lines[ end + 1 ] ): end += 1
        following = lines[ end + 1 ].strip() if end + 1 < len( lines ) else ""
        if following and not following.startswith( "///" ):
            symbol = by_line.get( _skip_annotations( lines, end + 1 ) )
            prose  = comment_prose( lines[ index : end + 1 ] )
            if symbol is not None and prose: out.setdefault( symbol, prose )
        index = end + 1
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
          file and symbol at new_rev; its row is { id, file, symbol, old, new, new_kind, linked_doc, changed },
          id being "file::symbol", linked_doc None and changed False for a pair kept only by include_unchanged
        - when the symbol has no doc block at new_rev but its declaration is still there, the old block pairs
          with the plain // comment directly above it (new_kind "plain_comment") or with "" (new_kind "none");
          a normal pair has new_kind "doc". A declaration that is gone is dropped_symbol_gone
        - a pair whose old and new differ only in whitespace is dropped unless include_unchanged
        - the report counts what was not paired and why, so a drop is never silent:
          files_old, files_new, files_only_old, files_only_new, blocks_old, blocks_new, eligible_old,
          below_min_words, dropped_file_deleted, dropped_symbol_gone, dropped_unchanged, paired_plain_comment,
          paired_no_comment, pairs, and the two file lists

    Raises:
        - RuntimeError from git when a listing fails
    """
    old_files, new_files = dart_files( root, old_rev, prefix ), dart_files( root, new_rev, prefix )
    only_old = sorted( set( old_files ) - set( new_files ) )
    only_new = sorted( set( new_files ) - set( old_files ) )
    report = { "files_old" : len( old_files ), "files_new" : len( new_files ), "files_only_old" : only_old, "files_only_new" : only_new,
               "blocks_old" : 0, "blocks_new" : 0, "eligible_old" : 0, "below_min_words" : 0,
               "dropped_file_deleted" : 0, "dropped_symbol_gone" : 0, "dropped_unchanged" : 0,
               "paired_plain_comment" : 0, "paired_no_comment" : 0, "pairs" : 0 }
    new_blocks = { path : extract_blocks( _show( root, new_rev, path ) or "" ) for path in new_files }
    report[ "blocks_new" ] = sum( len( blocks ) for blocks in new_blocks.values() )
    pairs, left_behind = [], {}

    def what_is_left( path, symbol ):
        """Ensures: returns ( text, kind ) for a symbol with no doc block now, or None if it is gone."""
        if path not in left_behind:
            source = _show( root, new_rev, path ) or ""
            left_behind[ path ] = ( plain_comments( source ), { s for s, _ in declarations( source ) } )
        plain, declared = left_behind[ path ]
        if symbol in plain: return plain[ symbol ], "plain_comment"
        return ( "", "none" ) if symbol in declared else None

    for path in old_files:
        old_blocks = extract_blocks( _show( root, old_rev, path ) or "" )
        report[ "blocks_old" ] += len( old_blocks )
        new_by_symbol = { s : t for s, _, t in new_blocks[ path ] } if path in new_blocks else {}
        for symbol, _, old_text in old_blocks:
            if len( old_text.split() ) < min_words:
                report[ "below_min_words" ] += 1
                continue
            report[ "eligible_old" ] += 1
            if path not in new_blocks:
                report[ "dropped_file_deleted" ] += 1
                continue
            if symbol in new_by_symbol: new_text, kind = new_by_symbol[ symbol ], "doc"
            else:
                left = what_is_left( path, symbol )
                if left is None:
                    report[ "dropped_symbol_gone" ] += 1
                    continue
                new_text, kind = left
            changed = squash( old_text ) != squash( new_text )
            if not changed and not include_unchanged:
                report[ "dropped_unchanged" ] += 1
                continue
            if kind != "doc": report[ "paired_plain_comment" if kind == "plain_comment" else "paired_no_comment" ] += 1
            pairs.append( { "id" : f"{path}::{symbol}", "file" : path, "symbol" : symbol, "old" : old_text, "new" : new_text, "new_kind" : kind, "linked_doc" : None, "changed" : changed } )
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

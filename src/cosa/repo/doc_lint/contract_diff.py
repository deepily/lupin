"""
Contract diff: Requires, Ensures and Raises item counts before and after a change.

Counts the items of every Python function and class under each heading, flags a heading that
vanished, and names the items most likely lost. A rewrite may reword a clause but may not lose one
unnoticed. Reworded items are matched by word overlap, not by exact text. Stdlib only.

Known limits (the count and the guard words are the signal, word overlap is not):
    - an item swapped for another under an unchanged count is not a finding: an exception type
      ("ValueError" to "TypeError"), a number ("at most 3" to "at most 30") or the whole clause
    - only a dropped guard word or comparison operator is reported, as a changed finding
    - an item made only of stopwords and guard words, such as "the is never", has no content word to
      match on, so weakening it can go unreported
    - a split item plus a dropped item keeps the count equal and shows no finding
"""

import argparse
import ast
import inspect
import json
import re
import sys

from .docs_only_diff import _show, changed_files

SECTIONS      = ( "Requires", "Ensures", "Raises" )
STAND_IN_MIN  = 0.3
MATCH_MIN     = 0.5
GUARD_WORDS   = frozenset( "not no never none nothing nor only always must should may might cannot without unless except all any every each at least most more less fewer than before after".split() )
OPERATOR_REGEX = re.compile( r">=|<=|==|!=|>|<" )
STOPWORDS     = frozenset( "a an the is are was be been being of to in on for with and or if it its this that as at by from when then so into than also only".split() )
WORD_REGEX    = re.compile( r"[a-z0-9_]+" )
HEADER_REGEX  = re.compile( r"^\s*([A-Za-z][A-Za-z ]{0,30}):\s*$" )
BULLET_REGEX  = re.compile( r"^(\s*)(?:[-*\u2022]|\d+[.)])\s+(.*)$" )


def tokens( item ):
    """
    Reduce an item to the set of words that carry its meaning.

    Requires:
        - item is a str

    Ensures:
        - returns lowercase words and numbers without the words in STOPWORDS
        - a trailing "s" is dropped from words longer than three letters, so "returns" and "return" agree
        - case, punctuation and word order do not matter

    Raises:
        - nothing
    """
    words = ( w[ :-1 ] if len( w ) > 3 and w.endswith( "s" ) else w for w in WORD_REGEX.findall( item.lower() ) )
    return { w for w in words if w not in STOPWORDS }


def overlap( old_item, new_item ):
    """
    Say how much of an old item's meaning a new item still carries.

    Requires:
        - both are str

    Ensures:
        - returns a float from 0.0 to 1.0: the share of the old item's words that the new item has
        - an old item with no words scores 1.0 against anything, since there is nothing to lose

    Raises:
        - nothing
    """
    old = tokens( old_item )
    return len( old & tokens( new_item ) ) / len( old ) if old else 1.0


def guards( item ):
    """
    List the words and operators that limit how far a clause reaches.

    Requires:
        - item is a str

    Ensures:
        - returns a sorted list of the negations, quantifiers, limits and comparison operators in the item,
          counting repeats, from GUARD_WORDS and OPERATOR_REGEX
        - dropping a "never" or turning ">=" into ">" changes the list; rewording around them does not

    Raises:
        - nothing
    """
    words = [ w for w in WORD_REGEX.findall( item.lower() ) if w in GUARD_WORDS ]
    return sorted( words + OPERATOR_REGEX.findall( item ) )


def changed_items( before, after ):
    """
    Find old items whose closest new item says the same thing with a different reach.

    Requires:
        - before and after are lists of item text

    Ensures:
        - returns [ ( old, new ) ] for each old item whose best-overlapping new item reaches MATCH_MIN overlap
          while a guard word or operator of the old item is missing from the new items assigned to it
        - old and new items are matched one to one, best overlap first, ties going to the pair that also overlaps
          most the other way round (new against old), then to the lower old and new index, so every old item
          claims its closest new item before any leftover is placed
        - a new item left over joins the old item it overlaps most, if that is at least STAND_IN_MIN, so an
          item the writer split in two keeps its "never" in either half
        - a new item therefore vouches for one old item only, and a neighbour's "never" cannot cover for it
        - a guard that is only added is not reported
        - an old item with no new item that close is not paired, since that is a loss and not a change

    Raises:
        - nothing
    """
    ranked = sorted( ( -overlap( old, new ), -overlap( new, old ), i, j ) for i, old in enumerate( before ) for j, new in enumerate( after ) )
    claimed, taken, group = {}, set(), { i : [] for i in range( len( before ) ) }
    for score, _, i, j in ranked:
        if i in claimed or j in taken or -score < STAND_IN_MIN: continue
        claimed[ i ] = j
        taken.add( j )
        group[ i ].append( after[ j ] )
    for score, _, i, j in ranked:
        if j not in taken and -score >= STAND_IN_MIN and i in claimed:
            taken.add( j )
            group[ i ].append( after[ j ] )
    pairs = []
    for i, old in enumerate( before ):
        if i not in claimed: continue
        best = after[ claimed[ i ] ]
        if overlap( old, best ) < MATCH_MIN: continue
        if set( guards( old ) ) - { g for new in group[ i ] for g in guards( new ) }: pairs.append( ( old, best ) )
    return pairs


def likely_lost( before, after, count ):
    """
    Pick the old items most likely to be the ones that were lost.

    Requires:
        - before and after are lists of item text; count is how many items to pick

    Ensures:
        - returns up to count old items, in their old order, whose best overlap with any new item is lowest
        - an item kept verbatim or reworded scores high and is picked last

    Raises:
        - nothing
    """
    if count <= 0: return []
    scored = sorted( ( max( ( overlap( item, new ) for new in after ), default=0.0 ), i ) for i, item in enumerate( before ) )
    return [ before[ i ] for i in sorted( i for _, i in scored[ :count ] ) ]


def stand_in( before, new_sections, own_headings ):
    """
    Find the new heading that now holds a vanished heading's items.

    Requires:
        - before is the old item list; new_sections is { heading: items } after the change
        - own_headings is the set of headings that already matched their own old section

    Ensures:
        - returns ( heading, items ) for the other new heading whose items overlap the old items most, or
          ( None, [] ) when none reaches STAND_IN_MIN
        - nothing is accepted as a synonym by name; only the words in the items decide

    Raises:
        - nothing
    """
    best, best_score = ( None, [] ), STAND_IN_MIN
    for heading, items in new_sections.items():
        if heading in own_headings: continue
        score = sum( max( ( overlap( old, new ) for new in items ), default=0.0 ) for old in before ) / len( before )
        if score >= best_score: best, best_score = ( heading, items ), score
    return best


def parse_sections( docstring ):
    """
    Read every section of bulleted items out of one docstring.

    Requires:
        - docstring is a str, or None for a definition without one

    Ensures:
        - returns { heading: [ item text, ... ] } for each heading line ("Word:") that is followed by items
        - an item starts with "-", "*" or a number and a period; bullets may sit flush with the heading
        - an indented continuation line joins the item above it with a single space
        - a section ends at a blank line, at the next heading, or at a line that is neither an item nor
          a continuation

    Raises:
        - nothing
    """
    sections = {}
    if not docstring: return sections
    name, header_indent, bullet_indent = None, 0, None
    for raw in inspect.cleandoc( docstring ).split( "\n" ):
        line   = raw.strip()
        indent = len( raw ) - len( raw.lstrip() )
        header = HEADER_REGEX.match( raw )
        bullet = BULLET_REGEX.match( raw )
        if not line:
            name = None
        elif header and not bullet:
            name, header_indent, bullet_indent = header.group( 1 ), indent, None
        elif name is not None and bullet and len( bullet.group( 1 ) ) >= header_indent:
            sections.setdefault( name, [] ).append( bullet.group( 2 ).strip() )
            bullet_indent = len( bullet.group( 1 ) )
        elif name is not None and bullet_indent is not None and indent > bullet_indent:
            sections[ name ][ -1 ] += " " + line
        else:
            name = None
    return sections


def definition_sections( source ):
    """
    Map each function and class to its parsed sections.

    Requires:
        - source is Python text that parses

    Ensures:
        - returns { name: sections } for every def and class, nested ones included
        - a class is named "K (class)" so it cannot collide with a function of the same name
        - a second definition of the same name, such as a property setter, is named "name#2", "name#3" and so on
        - a definition with no docstring maps to an empty dict

    Raises:
        - SyntaxError when source does not parse
    """
    found, seen = {}, {}

    def walk( node, prefix ):
        for child in ast.iter_child_nodes( node ):
            if isinstance( child, ( ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef ) ):
                base = prefix + child.name + ( " (class)" if isinstance( child, ast.ClassDef ) else "" )
                seen[ base ] = seen.get( base, 0 ) + 1
                name = base if seen[ base ] == 1 else f"{base}#{seen[ base ]}"
                found[ name ] = parse_sections( ast.get_docstring( child, clean=False ) )
                walk( child, prefix + child.name + "." )
            else:
                walk( child, prefix )

    walk( ast.parse( source ), "" )
    return found


def diff_contracts( old_source, new_source ):
    """
    Compare the contracts of two versions of one file.

    Requires:
        - both sources are str or None (None means the file is absent on that side)

    Ensures:
        - returns one row per definition that existed before and per contract heading (Requires, Ensures,
          Raises) that had items before or has items after: { function, section, before, after,
          heading_missing, stand_in, lost, changed }
        - heading_missing is True when the old text had the heading with items and the new text has no such
          heading; a different heading is never accepted as a synonym, but when one carries the old items
          it is named in stand_in and its item count is the row's after
        - changed lists ( old, new ) pairs that match by words but differ in a guard word or comparison operator,
          such as a dropped "never" or ">=" turned into ">", at or above MATCH_MIN overlap
        - lost lists the old items most likely to be gone, as many as the count fell, chosen by word overlap
          so a reworded item is not reported; a removed definition loses them all
        - a definition that only exists after has no row, since nothing was lost

    Raises:
        - SyntaxError when a present side does not parse
    """
    old = definition_sections( old_source ) if old_source is not None else {}
    new = definition_sections( new_source ) if new_source is not None else {}
    rows = []
    for name in sorted( old ):
        new_sections = new.get( name, {} )
        own          = { s for s in SECTIONS if s in new_sections and old[ name ].get( s ) }
        for section in SECTIONS:
            before, after = old[ name ].get( section, [] ), new_sections.get( section, [] )
            if not before and not after: continue
            missing  = bool( before ) and section not in new_sections
            heading  = None
            if missing: heading, after = stand_in( before, new_sections, own )
            rows.append( {
                "function"        : name,
                "section"         : section,
                "before"          : len( before ),
                "after"           : len( after ),
                "heading_missing" : missing,
                "stand_in"        : heading,
                "lost"            : likely_lost( before, after, len( before ) - len( after ) ),
                "changed"         : changed_items( before, after )
            } )
    return rows


def findings( results ):
    """
    List the failing findings in a check_diff result.

    Requires:
        - results is the dict check_diff returns

    Ensures:
        - returns one string for each heading that disappeared, and one for each row whose item count fell,
          naming the items most likely lost
        - a renamed heading with every item kept is exactly one finding; with one item dropped as well, two
        - a clause weakened under an unchanged count, as a `CHANGED` finding naming both versions
        - items reworded under an unchanged count, with the same guard words, are not findings

    Raises:
        - nothing
    """
    found = []
    for path, rows in results.items():
        for r in rows:
            where = f"{path} {r[ 'function' ]} {r[ 'section' ]}"
            if r[ "heading_missing" ]:
                now = f" (items now under {r[ 'stand_in' ]})" if r[ "stand_in" ] else ""
                found.append( f"HEADING MISSING: {where}{now}" )
            found += [ f"CHANGED: {where}: {old!r} -> {new!r}" for old, new in r[ "changed" ] ]
            if r[ "after" ] < r[ "before" ]:
                found.append( f"COUNT FELL {r[ 'before' ]} -> {r[ 'after' ]}: {where}: {'; '.join( r[ 'lost' ] )}" )
    return found


def check_diff( root, base, head=None ):
    """
    Diff the contracts of every changed .py file between base and head.

    Requires:
        - root is a git working tree; base is a revision
        - head is a revision, or None for the working tree

    Ensures:
        - returns { path: rows } sorted by path, for each changed .py file that has at least one row
        - paths are read with -z, so a non-ASCII name is not lost
        - a rename counts as a delete plus an add, so the old path shows every contract as dropped

    Raises:
        - RuntimeError from git when a command fails
        - SyntaxError when a changed file does not parse
    """
    found = {}
    for path in sorted( p for p in changed_files( root, base, head ) if p.endswith( ".py" ) ):
        rows = diff_contracts( _show( root, base, path ), _show( root, head, path ) )
        if rows: found[ path ] = rows
    return found


def render_table( results ):
    """
    Render the results as a markdown table, one row per definition and section.

    Requires:
        - results is the dict check_diff returns

    Ensures:
        - returns a str with a header row and one line per row
        - the finding column reads `HEADING MISSING` (with the heading that took the items), `COUNT FELL` or "-"
        - the lost column lists the items most likely gone, as many as the count fell
        - the count columns are the signal; the lost column is the best guess at which items they were

    Raises:
        - nothing
    """
    lines = [ "| file | function | section | before | after | finding | likely lost |", "| --- | --- | --- | --- | --- | --- | --- |" ]
    for path, rows in results.items():
        for r in rows:
            finding = "-"
            if r[ "heading_missing" ]: finding = "HEADING MISSING" + ( f" (now {r[ 'stand_in' ]})" if r[ "stand_in" ] else "" )
            if r[ "after" ] < r[ "before" ]: finding = ( finding + ", COUNT FELL" ) if finding != "-" else "COUNT FELL"
            if r[ "changed" ]: finding = ( finding + ", CHANGED" ) if finding != "-" else "CHANGED"
            lost = "; ".join( r[ "lost" ] ) if r[ "lost" ] else "-"
            lines.append( f"| {path} | {r[ 'function' ]} | {r[ 'section' ]} | {r[ 'before' ]} | {r[ 'after' ]} | {finding} | {lost} |" )
    return "\n".join( lines ) + "\n"


def main( argv=None, out=None ):
    """
    Command-line entry: print the contract table, or JSON with --json.

    Requires:
        - argv is a list of arguments, or None for sys.argv

    Ensures:
        - returns 1 when --strict is given and findings() is not empty, otherwise 0
        - the report is printed either way

    Raises:
        - RuntimeError from git when a command fails
    """
    out    = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="List the contract clauses a change dropped" )
    parser.add_argument( "--base", required=True, help="revision to compare from" )
    parser.add_argument( "--head", help="revision to compare to; default is the working tree" )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    parser.add_argument( "--json", action="store_true", help="print rows as JSON" )
    parser.add_argument( "--strict", action="store_true", help="exit 1 on a missing heading or a fallen item count" )
    args    = parser.parse_args( argv )
    results = check_diff( args.repo_root, args.base, args.head )
    if args.json:
        json.dump( results, out, indent=2 )
        out.write( "\n" )
    else:
        out.write( render_table( results ) )
    return 1 if args.strict and findings( results ) else 0


if __name__ == "__main__": sys.exit( main() )  # pragma: no cover -- script entry, main() is tested

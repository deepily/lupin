"""
Split checker: a page cut into an index and parts keeps every line of the old page, once.

Given the old page (a git revision and a path) and the new index plus its parts, it fails unless the
parts keep every line. Each non-blank line of the old page must be in the parts as often as in the old
page. A line the old page had once must be in exactly one part. A line it had twice must be in the parts twice. The report
names each dropped line and each doubled line. Lines the index or a part adds are allowed and listed.
Table rows, fences, headings and link targets are counted old against new and printed. No model is called.

One difference is allowed, because a part sits in a folder beside the old path. Outside code fences and
code spans, a link or image target "](X)" whose X does not start with a scheme, "#" or "/" becomes "](../X)".
Each such target is counted and listed per part. Any other change to a line is a dropped line plus an added
line. A relative target a part leaves without the "../" is named as unmoved, since that link would break.

A second form is allowed for an in-page link. In a part, "](#x)" may become "](<part-file>.md#x)" when
heading x is in that part file. A "](#x)" left in a part whose heading x is now in another part would
break, so it is named as dangling and fails. Each repointed link is listed per part.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter

RESULT_NAME  = "split-check.json"
SCHEME       = re.compile( r"^[A-Za-z][A-Za-z0-9+.\-]*:" )
CODE_SPAN    = re.compile( r"(`[^`\n]*`)" )
TABLE_RULE   = re.compile( r"^\s*\|[\s:|\-]+\|?\s*$" )
FENCE        = re.compile( r"^\s*(?:```|~~~)" )
HEADING      = re.compile( r"^#{1,6}\s+(\S.*?)\s*#*\s*$" )
INPAGE_LINK  = re.compile( r"\]\(#([^)\s]+)\)" )
LINK_TARGET  = re.compile( r"\]\(([^)\s]*)" )
FILE_ANCHOR  = re.compile( r"\]\(([^)#\s/]+\.md)#([^)\s]+)\)" )


def non_blank_lines( text ):
    """
    Number the non-blank lines of a text, trailing white space removed.

    Requires:
        - text is a str

    Ensures:
        - returns [ ( line number from 1, line ) ] in order, for each line with something other than white space
        - the line is kept with its leading indentation and without trailing white space or a carriage return

    Raises:
        - nothing
    """
    return [ ( n, raw.rstrip() ) for n, raw in enumerate( text.split( "\n" ), 1 ) if raw.strip() ]


def move_targets( line ):
    """
    Add the leading "../" to each relative link target outside a code span.

    Requires:
        - line is a str

    Ensures:
        - returns the line with each "](X)" whose X is non-empty and does not start with a scheme, "#" or "/" turned into "](../X)"
        - text inside backtick spans is left byte for byte
        - a line with no such target comes back equal

    Raises:
        - nothing
    """
    def one( match ):
        target = match.group( 1 )
        if not target or target[ 0 ] in "#/" or SCHEME.match( target ): return match.group( 0 )
        return "](../" + target
    pieces = CODE_SPAN.split( line )
    return "".join( p if i % 2 else LINK_TARGET.sub( one, p ) for i, p in enumerate( pieces ) )


def expected_lines( old_text ):
    """
    Number the non-blank lines of the old page with the form each takes in a part.

    Requires:
        - old_text is a str

    Ensures:
        - returns [ ( line number, old line, expected line ) ] for each non-blank line, in order
        - a line inside a code fence is expected unchanged; any other line is expected as move_targets makes it
        - fence lines toggle the fence and are expected unchanged

    Raises:
        - nothing
    """
    rows, inside = [], False
    for number, raw in enumerate( old_text.split( "\n" ), 1 ):
        if FENCE.match( raw ):
            inside = not inside
            if raw.strip(): rows.append( ( number, raw.rstrip(), raw.rstrip() ) )
            continue
        if not raw.strip(): continue
        line = raw.rstrip()
        rows.append( ( number, line, line if inside else move_targets( line ) ) )
    return rows


def targets_of( line ):
    """
    List the link targets of a line, outside code spans.

    Requires:
        - line is a str

    Ensures:
        - returns the X of each "](X" in order, text inside backtick spans skipped

    Raises:
        - nothing
    """
    found = []
    for i, piece in enumerate( CODE_SPAN.split( line ) ):
        if i % 2 == 0: found += LINK_TARGET.findall( piece )
    return found


def github_slug( heading ):
    """
    Approximate the anchor GitHub makes from a heading.

    Requires:
        - heading is the heading text without its leading hashes

    Ensures:
        - returns the text lowercased, backticks and punctuation other than hyphen, underscore and space removed, spaces made hyphens

    Raises:
        - nothing
    """
    kept = re.sub( r"[^\w\- ]", "", heading.replace( "`", "" ).lower() )
    return kept.replace( " ", "-" )


def structure_counts( text ):
    """
    Count the structure of a page.

    Requires:
        - text is a str

    Ensures:
        - returns { table_rows, fences, headings, link_targets }
        - table_rows counts rows that are not separator rules, outside fences
        - fences counts opening and closing fence lines, headings counts heading lines outside fences
        - link_targets counts every "](target" in the text outside fences

    Raises:
        - nothing
    """
    counts, inside = { "table_rows": 0, "fences": 0, "headings": 0, "link_targets": 0 }, False
    for raw in text.split( "\n" ):
        if FENCE.match( raw ):
            counts[ "fences" ] += 1
            inside = not inside
            continue
        if inside: continue
        if raw.lstrip().startswith( "|" ) and not TABLE_RULE.match( raw ): counts[ "table_rows" ] += 1
        if HEADING.match( raw ): counts[ "headings" ] += 1
        counts[ "link_targets" ] += len( LINK_TARGET.findall( raw ) )
    return counts


def heading_homes( part_texts ):
    """
    Map each heading anchor to the part file that holds it.

    Requires:
        - part_texts is { name: text } in reading order

    Ensures:
        - returns { anchor: basename of the part file }, anchors as github_slug makes them
        - a heading repeated across or within parts gets the suffixes -1, -2 in reading order, as GitHub does
        - headings inside code fences are skipped

    Raises:
        - nothing
    """
    homes, seen = {}, Counter()
    for name, text in part_texts.items():
        inside = False
        for raw in text.split( "\n" ):
            if FENCE.match( raw ):
                inside = not inside
                continue
            match = None if inside else HEADING.match( raw )
            if match is None: continue
            slug = github_slug( match.group( 1 ) )
            n    = seen[ slug ]
            seen[ slug ] += 1
            homes[ slug if n == 0 else f"{slug}-{n}" ] = os.path.basename( name )
    return homes


def unresolved_anchors( part_texts, homes ):
    """
    Find in-page links whose heading is in no part.

    Requires:
        - part_texts is { name: text }; homes is heading_homes( part_texts )

    Ensures:
        - returns [ { part, anchor } ] for each "](#anchor)" link outside fences and code spans whose anchor is no heading of any part
        - such a link was not made by the split, and is listed, never failed

    Raises:
        - nothing
    """
    found = []
    for name, text in part_texts.items():
        inside = False
        for raw in text.split( "\n" ):
            if FENCE.match( raw ):
                inside = not inside
                continue
            if inside: continue
            for i, piece in enumerate( CODE_SPAN.split( raw ) ):
                if i % 2 == 0: found += [ { "part": name, "anchor": a } for a in INPAGE_LINK.findall( piece ) if a not in homes ]
    return found


def repoint_back( line, homes ):
    """
    Undo the allowed in-page repoint on a part line.

    Requires:
        - line is a str; homes is heading_homes of the parts

    Ensures:
        - returns ( line, repointed ): each "](F.md#x)" outside a code span whose heading x is in part file F turned back to "](#x)"
        - repointed is [ { old, new } ] with old "#x" and new "F.md#x", in order
        - a target with a directory part, or whose anchor is in another file, is left alone

    Raises:
        - nothing
    """
    repointed = []
    def one( match ):
        file, anchor = match.group( 1 ), match.group( 2 )
        if homes.get( anchor ) != file: return match.group( 0 )
        repointed.append( { "old": f"#{anchor}", "new": f"{file}#{anchor}" } )
        return f"](#{anchor})"
    pieces = CODE_SPAN.split( line )
    return "".join( p if i % 2 else FILE_ANCHOR.sub( one, p ) for i, p in enumerate( pieces ) ), repointed


def dangling_in( line, part_base, homes ):
    """
    List the in-page links of a line whose heading is now in another part.

    Requires:
        - line is a str outside a code fence; part_base is the basename of the part holding it; homes is heading_homes

    Ensures:
        - returns [ ( anchor, home file ) ] for each "](#anchor)" outside code spans whose heading is in a part file other than part_base

    Raises:
        - nothing
    """
    found = []
    for i, piece in enumerate( CODE_SPAN.split( line ) ):
        if i % 2 == 0: found += [ ( a, homes[ a ] ) for a in INPAGE_LINK.findall( piece ) if a in homes and homes[ a ] != part_base ]
    return found


def part_rows( text ):
    """
    Number the non-blank lines of a part with whether each is inside a code fence.

    Requires:
        - text is a str

    Ensures:
        - returns [ ( line number, line, inside ) ]; a fence line itself is not inside, white space is stripped from the right

    Raises:
        - nothing
    """
    rows, inside = [], False
    for number, raw in enumerate( text.split( "\n" ), 1 ):
        if FENCE.match( raw ):
            inside = not inside
            if raw.strip(): rows.append( ( number, raw.rstrip(), False ) )
            continue
        if raw.strip(): rows.append( ( number, raw.rstrip(), inside ) )
    return rows


def compare( old_text, index_text, part_texts, allow_index_lines=False, max_added=None ):
    """
    Compare an old page with its index and parts.

    Requires:
        - old_text and index_text are str; part_texts is { name: text } in the order the parts read
        - allow_index_lines is True to let a line the index repeats from the old page count toward its cover
        - max_added is an int cap on lines a single part may add, or None for no cap

    Ensures:
        - returns { dropped, doubled, unmoved, dangling, index_added, index_repeats, parts, structure, unresolved_anchors, max_added_exceeded, pass }
        - dropped is [ { line, old_line, missing } ] and doubled is [ { line, extra, parts } ], each naming the old line
        - unmoved is [ { part, line_number, line } ] for a part line that is an old line with relative targets and kept them as they were
        - dangling is [ { part, line_number, anchor, should_be } ] for a "](#anchor)" in a part whose heading is in another part file
        - parts is { name: { lines, added, moved, repointed } }; added is [ ( number, line ) ]; moved is [ { line_number, old, new } ], one per target that gained "../"; repointed is [ { line_number, old, new } ], one per in-page link made a link to the part that holds its heading
        - a part line must equal an old line, or the form move_targets gives it, or either with in-page links repointed to the part that holds the heading; anything else is added, and the old line it came from is dropped
        - pass is True only when nothing is dropped, doubled, unmoved or dangling and no part adds more than max_added lines
        - without allow_index_lines the index never covers an old line; its lines are index_repeats or index_added

    Raises:
        - nothing
    """
    rows      = expected_lines( old_text )
    totals    = Counter( expected for _, _, expected in rows )
    original  = {}
    first     = {}
    for number, old, expected in rows:
        original.setdefault( expected, old )
        first.setdefault( expected, number )
    plain     = { old: expected for _, old, expected in rows if old != expected }
    left      = Counter( totals )
    index_added, index_repeats = [], []
    old_set   = { old for _, old, _ in rows }
    for number, line in non_blank_lines( index_text ):
        if line not in old_set: index_added.append( { "line_number": number, "line": line } )
        else:
            index_repeats.append( { "line_number": number, "line": line } )
            key = plain.get( line, line )
            if allow_index_lines and left[ key ] > 0: left[ key ] -= 1
    homes     = heading_homes( part_texts )
    doubled, unmoved, dangling, parts = {}, [], [], {}
    for name, text in part_texts.items():
        base                      = os.path.basename( name )
        added, moved, repointed   = [], [], []
        rows_in                   = part_rows( text )
        for number, raw, inside in rows_in:
            line, again = ( raw, [] ) if inside else repoint_back( raw, homes )
            if not inside:
                dangling += [ { "part": name, "line_number": number, "anchor": a, "should_be": f"{h}#{a}" } for a, h in dangling_in( raw, base, homes ) ]
            if line in totals:
                if left[ line ] > 0:
                    left[ line ] -= 1
                    old = original[ line ]
                    if old != line: moved += [ { "line_number": number, "old": o, "new": n } for o, n in zip( targets_of( old ), targets_of( line ) ) if o != n ]
                    repointed += [ { "line_number": number, **r } for r in again ]
                else:
                    entry = doubled.setdefault( line, { "line": original[ line ], "extra": 0, "parts": [] } )
                    entry[ "extra" ] += 1
                    if name not in entry[ "parts" ]: entry[ "parts" ].append( name )
            elif line in plain: unmoved.append( { "part": name, "line_number": number, "line": raw } )
            else: added.append( ( number, raw ) )
        parts[ name ] = { "lines": len( rows_in ), "added": added, "moved": moved, "repointed": repointed }
    dropped = [ { "line": original[ key ], "old_line": first[ key ], "missing": count } for key, count in left.items() if count > 0 ]
    new_all = "\n".join( [ index_text ] + list( part_texts.values() ) )
    over    = max_added is not None and any( len( p[ "added" ] ) > max_added for p in parts.values() )
    return {
        "dropped"            : sorted( dropped, key=lambda d: d[ "old_line" ] ),
        "doubled"            : list( doubled.values() ),
        "unmoved"            : unmoved,
        "index_added"        : index_added,
        "index_repeats"      : index_repeats,
        "parts"              : parts,
        "structure"          : {
            "old"       : structure_counts( old_text ),
            "parts"     : structure_counts( "\n".join( part_texts.values() ) ),
            "index"     : structure_counts( index_text ),
            "new_total" : structure_counts( new_all )
        },
        "unresolved_anchors" : unresolved_anchors( part_texts, homes ),
        "dangling"           : dangling,
        "max_added_exceeded" : over,
        "pass"               : not dropped and not doubled and not unmoved and not dangling and not over
    }


def read_old( root, rev, path ):
    """
    Read a page as it was at a revision.

    Requires:
        - root is a git working tree, rev a revision, path a repo-relative path

    Ensures:
        - returns the text of git show rev:path

    Raises:
        - RuntimeError naming the git error when the revision or path does not resolve
    """
    res = subprocess.run( [ "git", "-C", str( root ), "show", f"{rev}:{path}" ], capture_output=True, text=True, encoding="utf-8" )
    if res.returncode != 0: raise RuntimeError( f"git show {rev}:{path} failed: {res.stderr.strip()}" )
    return res.stdout


def read_new( root, path, rev=None ):
    """
    Read a new file from the working tree, or from a revision.

    Requires:
        - root is a git working tree, path a repo-relative path, rev a revision or None

    Ensures:
        - returns the file text; with rev None it is read from the tree, otherwise as of rev

    Raises:
        - OSError when a tree file cannot be read
        - RuntimeError naming the git error when the revision or path does not resolve
    """
    if rev is not None: return read_old( root, rev, path )
    with open( os.path.join( str( root ), path ), encoding="utf-8" ) as handle: return handle.read()


def check_split( root, old_rev, old_path, index_path, part_paths, new_rev=None, allow_index_lines=False, max_added=None ):
    """
    Check one split.

    Requires:
        - root is a git working tree; old_rev and old_path name the page before the split
        - index_path and part_paths are repo-relative paths of the new files, read from the tree or from new_rev

    Ensures:
        - returns compare's result plus old, index, parts (the inputs), refused and message
        - with no parts, or an unreadable file, or a revision that does not resolve, refused holds the reason and pass is False
        - a refusal never carries a partial comparison

    Raises:
        - nothing
    """
    base = { "old": f"{old_rev}:{old_path}", "index": index_path, "part_paths": list( part_paths ) }
    try:
        if not part_paths: raise ValueError( "no parts were given" )
        old_text   = read_old( root, old_rev, old_path )
        index_text = read_new( root, index_path, new_rev )
        part_texts = { p: read_new( root, p, new_rev ) for p in part_paths }
    except ( OSError, RuntimeError, ValueError ) as err:
        return { **base, "refused": f"{type( err ).__name__}: {err}", "message": f"{type( err ).__name__}: {err}", "pass": False }
    result = compare( old_text, index_text, part_texts, allow_index_lines, max_added )
    result.update( base )
    result[ "refused" ] = None
    result[ "message" ] = "nothing lost" if result[ "pass" ] else f"{len( result[ 'dropped' ] )} dropped, {len( result[ 'doubled' ] )} doubled"
    return result


def format_report( result ):
    """
    Render a result as the text a reader checks.

    Requires:
        - result is a check_split result

    Ensures:
        - returns a list of lines: the verdict first, then each dropped, doubled, unmoved and dangling line by name, the lines added, the targets moved and the links repointed, and the structure counts old against new
        - a refused result is its reason only

    Raises:
        - nothing
    """
    if result[ "refused" ] is not None: return [ f"REFUSED: {result[ 'refused' ]}" ]
    out = [ ( "PASS" if result[ "pass" ] else "FAIL" ) + f": {result[ 'message' ]}  ({result[ 'old' ]} -> {result[ 'index' ]} + {len( result[ 'parts' ] )} parts)" ]
    for d in result[ "dropped" ]: out.append( f"DROPPED (old line {d[ 'old_line' ]}, {d[ 'missing' ]} missing): {d[ 'line' ]}" )
    for d in result[ "doubled" ]: out.append( f"DOUBLED ({d[ 'extra' ]} extra, in {', '.join( d[ 'parts' ] )}): {d[ 'line' ]}" )
    for d in result[ "dangling" ]: out.append( f"DANGLING in-page link in {d[ 'part' ]} L{d[ 'line_number' ]} (#{d[ 'anchor' ]} is in {d[ 'should_be' ].split( '#' )[ 0 ]}): should be {d[ 'should_be' ]}" )
    for u in result[ "unmoved" ]: out.append( f"UNMOVED link in {u[ 'part' ]} L{u[ 'line_number' ]} (relative target without ../): {u[ 'line' ]}" )
    if result[ "max_added_exceeded" ]: out.append( "FAIL: a part adds more lines than --max-added allows" )
    for name, part in result[ "parts" ].items():
        out.append( f"part {name}: {part[ 'lines' ]} lines, {len( part[ 'added' ] )} added, {len( part[ 'moved' ] )} link targets gained ../" )
        for number, line in part[ "added" ]: out.append( f"  added L{number}: {line}" )
        for row in part[ "moved" ]: out.append( f"  moved L{row[ 'line_number' ]}: {row[ 'old' ]} -> {row[ 'new' ]}" )
        for row in part[ "repointed" ]: out.append( f"  repointed L{row[ 'line_number' ]}: {row[ 'old' ]} -> {row[ 'new' ]}" )
    out.append( f"index: {len( result[ 'index_added' ] )} lines added, {len( result[ 'index_repeats' ] )} repeat old lines" )
    for row in result[ "index_added" ]: out.append( f"  index added L{row[ 'line_number' ]}: {row[ 'line' ]}" )
    for row in result[ "index_repeats" ]: out.append( f"  index repeats L{row[ 'line_number' ]}: {row[ 'line' ]}" )
    for anchor in result[ "unresolved_anchors" ]: out.append( f"in-page link with no heading in any part (not made by the split): {anchor[ 'part' ]} #{anchor[ 'anchor' ]}" )
    out.append( "structure          old   parts   index   new_total" )
    for key in ( "table_rows", "fences", "headings", "link_targets" ):
        s = result[ "structure" ]
        out.append( f"{key:<16} {s[ 'old' ][ key ]:>5} {s[ 'parts' ][ key ]:>7} {s[ 'index' ][ key ]:>7} {s[ 'new_total' ][ key ]:>11}" )
    return out


def main( argv=None, out=None ):
    """
    Command-line entry point.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]

    Ensures:
        - prints the report and, with --out, writes split-check.json there
        - returns 0 when nothing is lost, 1 when a line is dropped, doubled, unmoved or dangling, or a part adds too many, 2 on a refusal

    Raises:
        - nothing
    """
    out    = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="Check that a split page keeps every line of the old page, once." )
    parser.add_argument( "--repo-root", default=".", help="git working tree" )
    parser.add_argument( "--old-rev", required=True, help="revision that holds the page before the split" )
    parser.add_argument( "--old-path", required=True, help="repo-relative path of the page before the split" )
    parser.add_argument( "--index", required=True, help="repo-relative path of the new index page" )
    parser.add_argument( "--part", action="append", default=[], help="repo-relative path of a part; repeat for each" )
    parser.add_argument( "--new-rev", help="read the index and parts as of this revision, not from the tree" )
    parser.add_argument( "--allow-index-lines", action="store_true", help="let an old line the index repeats count toward its cover" )
    parser.add_argument( "--max-added", type=int, help="fail when one part adds more than this many lines" )
    parser.add_argument( "--out", help="directory to create for split-check.json" )
    args   = parser.parse_args( sys.argv[ 1: ] if argv is None else argv )
    result = check_split( args.repo_root, args.old_rev, args.old_path, args.index, args.part, args.new_rev, args.allow_index_lines, args.max_added )
    if args.out is not None:
        os.makedirs( args.out, exist_ok=True )
        with open( f"{args.out}/{RESULT_NAME}", "w", encoding="utf-8" ) as handle:
            json.dump( result, handle, indent=2 )
            handle.write( "\n" )
    for line in format_report( result ): out.write( line + "\n" )
    if result[ "refused" ] is not None: return 2
    return 0 if result[ "pass" ] else 1


if __name__ == "__main__":
    sys.exit( main() )

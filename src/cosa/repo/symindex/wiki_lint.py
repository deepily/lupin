"""
Lint the code wiki against the generated symbol index; produce the librarian's work queue.

Findings (one dict each):
  stale              a page pins symbol@hash and the code changed since
  dangling           a page pins a symbol that no longer exists
  unindexed          a capability page missing from INDEX.md, so it can never be selected
  orphan             a public symbol in a package that has a page, which no page covers
  orphan_package     a package with no capability page: one finding with a count, not one per symbol
  pin_algorithm_changed  the index was built with a different parser than the pages were pinned with;
                     reported once, and stale checks are skipped because every pin would differ
"""
import pathlib
import re

from cosa.repo.symindex.build import read_header, read_symbols

PIN_RE      = re.compile( r"([\w.\-:#$]+)@([0-9a-f]{10})" )
FRONT_RE    = re.compile( r"\A---\n(.*?)\n---", re.S )
ALGO_RE     = re.compile( r"^pin_algorithm:\s*(\S+)\s*$", re.M )
LINK_RE     = re.compile( r"\[\[([\w-]+)\]\]" )


def _package( symbol_id ):
    """Ensures: returns the first two dotted parts of an id (for example "cosa.rest"), after any "repo:" prefix."""
    return ".".join( symbol_id.split( ":" )[ -1 ].split( "." )[ :2 ] )


def queue( wiki_dir, gen ):
    """
    Produce the lint findings for a wiki directory against one index generation.

    Requires:
        - wiki_dir holds capabilities/*.md and optionally INDEX.md
        - gen is a published generation directory
    Ensures:
        - returns the list of finding dicts, each with a "kind"
        - an empty or missing wiki returns only orphan_package findings
        - duplicate ids in the index cannot hide a finding: ids are unique by construction
    """
    wiki  = pathlib.Path( wiki_dir )
    live  = { r[ "id" ]: r[ "pin" ] for r in read_symbols( gen ) }
    algo  = read_header( gen )[ "pin_algorithm" ]
    toc   = wiki / "INDEX.md"
    index = set( LINK_RE.findall( toc.read_text( encoding="utf-8" ) ) ) if toc.exists() else set()
    covered, pages_by_pkg, out, algo_changed = set(), set(), [], False
    for page in sorted( ( wiki / "capabilities" ).glob( "*.md" ) ) if ( wiki / "capabilities" ).is_dir() else []:
        m      = FRONT_RE.match( page.read_text( encoding="utf-8" ) )
        front  = m.group( 1 ) if m else ""
        pins   = PIN_RE.findall( front )
        a      = ALGO_RE.search( front )
        if a and a.group( 1 ) != algo and not algo_changed:
            algo_changed = True
            out.append( { "kind": "pin_algorithm_changed", "page": page.stem, "was": a.group( 1 ), "now": algo } )
        if page.stem not in index: out.append( { "kind": "unindexed", "page": page.stem } )
        for sid, h in pins:
            covered.add( sid ); pages_by_pkg.add( _package( sid ) )
            if sid not in live:
                out.append( { "kind": "dangling", "page": page.stem, "symbol": sid } )
            elif live[ sid ] != h and not algo_changed:
                out.append( { "kind": "stale", "page": page.stem, "symbol": sid, "was": h, "now": live[ sid ] } )
    counts = {}
    for sid in sorted( set( live ) - covered ):
        pkg = _package( sid )
        if pkg in pages_by_pkg: out.append( { "kind": "orphan", "symbol": sid, "package": pkg } )
        else: counts[ pkg ] = counts.get( pkg, 0 ) + 1
    for pkg in sorted( counts ): out.append( { "kind": "orphan_package", "package": pkg, "count": counts[ pkg ] } )
    return out

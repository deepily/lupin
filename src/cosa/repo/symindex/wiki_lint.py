"""
Lint the code wiki against the generated symbol index; produce the librarian's work queue.

Findings (one dict each):
  stale              a page pins symbol@hash and the code changed since
  dangling           a page pins a symbol that no longer exists
  unindexed          a capability page missing from INDEX.md, so it can never be selected
  orphan             a public symbol in a package that has a page, which no page covers
  orphan_package     a package with no capability page: one finding with a count, not one per symbol
  pin_algorithm_changed  a pinned page records a different pin algorithm than the index; reported once
  pin_algorithm_missing  a pinned page records no pin algorithm at all; reported once
                     either of the two switches stale checks off for every page, because every pin would differ
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
        - the pin-algorithm check runs once, before any page is judged, so page order cannot change the result
        - duplicate ids in the index cannot hide a finding: ids are unique by construction
    """
    wiki  = pathlib.Path( wiki_dir )
    live  = { r[ "id" ]: r[ "pin" ] for r in read_symbols( gen ) }
    algo  = read_header( gen )[ "pin_algorithm" ]
    toc   = wiki / "INDEX.md"
    index = set( LINK_RE.findall( toc.read_text( encoding="utf-8" ) ) ) if toc.exists() else set()
    parsed = []
    for page in sorted( ( wiki / "capabilities" ).glob( "*.md" ) ) if ( wiki / "capabilities" ).is_dir() else []:
        m     = FRONT_RE.match( page.read_text( encoding="utf-8" ) )
        front = m.group( 1 ) if m else ""
        a     = ALGO_RE.search( front )
        parsed.append( ( page, PIN_RE.findall( front ), a.group( 1 ) if a else None ) )
    pinned  = [ ( pg, al ) for pg, pins, al in parsed if pins ]
    changed = [ pg.stem for pg, al in pinned if al is not None and al != algo ]
    missing = [ pg.stem for pg, al in pinned if al is None ]
    covered, pages_by_pkg, out = set(), set(), []
    if changed: out.append( { "kind": "pin_algorithm_changed", "pages": changed, "was": sorted( { al for _, al in pinned if al is not None and al != algo } ), "now": algo } )
    if missing: out.append( { "kind": "pin_algorithm_missing", "pages": missing, "now": algo } )
    for page, pins, _ in parsed:
        if page.stem not in index: out.append( { "kind": "unindexed", "page": page.stem } )
        for sid, h in pins:
            covered.add( sid ); pages_by_pkg.add( _package( sid ) )
            if sid not in live:
                out.append( { "kind": "dangling", "page": page.stem, "symbol": sid } )
            elif live[ sid ] != h and not ( changed or missing ):
                out.append( { "kind": "stale", "page": page.stem, "symbol": sid, "was": h, "now": live[ sid ] } )
    counts = {}
    for sid in sorted( set( live ) - covered ):
        pkg = _package( sid )
        if pkg in pages_by_pkg: out.append( { "kind": "orphan", "symbol": sid, "package": pkg } )
        else: counts[ pkg ] = counts.get( pkg, 0 ) + 1
    for pkg in sorted( counts ): out.append( { "kind": "orphan_package", "package": pkg, "count": counts[ pkg ] } )
    return out

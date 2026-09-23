"""
selector_census.py — the DENOMINATOR for the page-anchor selector guard.

WHY THIS EXISTS (row `04735b66`, Mr. Radio 🦉)
----------------------------------------------
`selector_guard.py` classifies a selector as SHIPPED / RUNTIME_INJECTED / DEAD. It was built
after one hand-typed selector (`multiplexer-fleet-pane`) named nothing and the probe reported
that as a finding about the product. The guard works. What it could not state was its
DENOMINATOR: how many selectors of that class exist across the tree, and how many any guard
actually sees.

⇒ A guard that cannot state its denominator is describing its CORPUS, not the SURFACE. The 24
selectors that happened to run through it on 2026-09-22 are traffic. This module counts the
population.

THE CLASS BEING COUNTED — say it precisely, because the number gets quoted
-------------------------------------------------------------------------
A **surface selector literal**: a string literal, in a probe / test / script, that names an
anchor on one of the two served surfaces this row is about (the multiplexer client and the
legacy notifications client), by `id` or by `data-testid`.

That is the class where "resolved nothing" is ambiguous between a product finding and a probe
bug — the defect this row exists for.

⚠️ QUOTE-AGNOSTIC ON PURPOSE. The first cut of this extractor matched only double-quoted outer
strings and reported SIX literals where a fixed-string `git grep` found forty-four. Python
probes in this tree overwhelmingly write `'[data-testid="x"]'` — single outside, double
inside. A census that cannot see the tree's dominant spelling returns a small clean number
that looks exactly like a small clean surface. The instrument was proved against the grep
count before any number here was believed.

HOW A LITERAL IS JUDGED IN-SURFACE
----------------------------------
Two clauses, and the first is what makes the defect case countable:
  1. it is spelled `multiplexer-*`  — catches a DEAD selector, which by definition is in no
     registry and would be invisible to a registry-membership test alone;
  2. it resolves against the anchors the two pages actually ship — catches the legacy side,
     whose ids (`#fleet-status-pane`) carry no distinguishing prefix.

🔴 THE LIMIT THIS LEAVES, NAMED RATHER THAN BRIDGED: a DEAD plain `#id` that is not spelled
`multiplexer-*` satisfies neither clause and is NOT counted. Such a literal is
indistinguishable, by spelling alone, from a selector for some other page in the app. Closing
it needs per-file knowledge of which surface each probe drives, which this census does not
have. Unmeasured, stated, not started.

WHAT IS COUNTED SEPARATELY, AND WHY
-----------------------------------
- COMPOUND (`#x .y`, `button.z[data-token='T']`) — a real live-page selector that can go dead
  the same way, but `selector_guard.classify_selector()` cannot classify its shape today.
  Folding it into PAGE_ANCHOR would report coverage the guard does not have.
- JSDOM_ONLY — `*.test.ts` render a component into jsdom and query their OWN output. Their
  anchors are not the served page's anchors, so the guard's oracle is the wrong one for them.
- UNRESOLVABLE — a literal with `{` in it is a name-GENERATOR, not a name. The guard can only
  classify a name. An honest third bucket, not a silent drop.

Requires:
    - LUPIN_ROOT names a git checkout; `git` is on PATH
Ensures:
    - census() derives its file population from `git ls-files` — never a disk walk, which is
      ~92% .venv in this tree
    - every extracted literal lands in exactly one bucket; the buckets partition the total
"""
import os, pathlib, re, subprocess

# The file population, as git pathspecs. Stated so a reader can re-derive the number rather
# than trust it.
POPULATION_PATHSPECS = [ "src/tests", "src/scripts" ]

# Extensions that can hold a browser-locator literal. `.test.ts` is included and then split
# off by bucket — dropping it at the extension level would hide the split.
POPULATION_SUFFIXES = ( ".py", ".ts", ".js", ".sh", ".mjs" )

# The product pages whose shipped anchors define the surface.
SURFACE_HTML  = ( "src/lupin_app/static/html/multiplexer.html",
                  "src/lupin_app/static/html/notifications.html" )
SURFACE_PREFIX = "multiplexer-"

# --- extraction -------------------------------------------------------------------------
# Quote-agnostic: `([\"'])(...)\1` so a single-quoted outer string holding double quotes — the
# tree's dominant spelling — is seen. See the QUOTE-AGNOSTIC note in the module docstring.
_STRING_LITERAL = re.compile( r'''(["'])((?:(?!\1)[^\\\n]|\\.){1,200})\1''' )
_GET_BY_TEST_ID = re.compile( r'''(?:get_by_test_id|getByTestId)\(\s*f?r?b?(["'])((?:(?!\1)[^\\\n])+)\1''' )

_CSS_TESTID   = re.compile( r'\[data-testid=(["\'])([^"\'\[\]]+)\1\]' )
_PLAIN_ID     = re.compile( r'^#[a-zA-Z0-9_-]+$' )
_PLAIN_TESTID = re.compile( r'''^\[data-testid=(["'])[a-zA-Z0-9_-]+\1\]$''' )


class Bucket:
    """The four buckets a literal can land in. Exhaustive and mutually exclusive."""
    PAGE_ANCHOR  = "PAGE_ANCHOR"    # guard-classifiable shape, served-page surface
    COMPOUND     = "COMPOUND"       # a real live-page selector whose shape the guard rejects
    JSDOM_ONLY   = "JSDOM_ONLY"     # named only by *.test.ts — a different oracle
    UNRESOLVABLE = "UNRESOLVABLE"   # interpolated; a name-generator, not a name
    ALL          = ( PAGE_ANCHOR, COMPOUND, JSDOM_ONLY, UNRESOLVABLE )


def _root( root=None ):
    if root is not None: return pathlib.Path( root )
    r = os.environ.get( "LUPIN_ROOT" )
    if r is None: raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
    return pathlib.Path( r )


def population_files( root=None, pathspecs=None ):
    """
    The file population, DERIVED FROM GIT.

    Requires:
        - root is a git checkout
    Ensures:
        - returns a sorted list of repo-relative paths, tracked only, filtered to
          POPULATION_SUFFIXES
    Raises:
        - RuntimeError when git returns nothing. An empty population makes every later count
          read as a clean zero — the exact two-states-one-representation defect this row is
          about, turned on the census itself.
    """
    root      = _root( root )
    pathspecs = pathspecs if pathspecs is not None else POPULATION_PATHSPECS
    out       = subprocess.run( [ "git", "ls-files", "--", *pathspecs ],
                                cwd=str( root ), capture_output=True, text=True, check=True ).stdout
    files = sorted( p for p in out.splitlines() if p.endswith( POPULATION_SUFFIXES ) )
    if not files:
        raise RuntimeError( f"git ls-files returned ZERO files for {pathspecs} in {root} — the "
                            "instrument is broken, not the tree. Refusing to report a census "
                            "over an empty population." )
    return files


def shipped_anchor_names( root=None ):
    """
    Every id and data-testid the two surface pages ship.

    Ensures:
        - returns a non-empty set of bare anchor names
    Raises:
        - RuntimeError on an empty parse — an empty anchor set would silently shrink the
          surface predicate to its spelling clause alone
    """
    root  = _root( root )
    names = set()
    for rel in SURFACE_HTML:
        html = ( root / rel ).read_text()
        names |= set( re.findall( r'\bid="([a-zA-Z0-9_-]+)"', html ) )
        names |= set( re.findall( r'\bdata-testid="([a-zA-Z0-9_-]+)"', html ) )
    if not names:
        raise RuntimeError( f"parsed ZERO anchors from {SURFACE_HTML} — instrument broken." )
    return names


def normalise( literal ):
    """
    Canonical spelling for one literal, so two spellings of one anchor count once.

    Ensures:
        - a CSS literal keeps its own text, with the attribute value re-quoted in double
          quotes so `[data-testid='x']` and `[data-testid="x"]` count as one anchor
        - anything else is returned unchanged
    """
    return _CSS_TESTID.sub( lambda m: f'[data-testid="{m.group( 2 )}"]', literal )


def extract_literals( text ):
    """
    Every selector-shaped string literal in one file's text, canonicalised.

    🔴 ONLY WHAT SOMEBODY ACTUALLY WROTE AS A SELECTOR. A bare name is counted ONLY inside a
    testid call (`get_by_test_id("x")`), never as a loose quoted string.

    The first cut of this function treated ANY bare `[a-zA-Z0-9_-]+` literal as a testid and
    rewrote it to `[data-testid="<name>"]`. That MANUFACTURED selectors nobody had written:
    `conftest.py:1119` holds `"audio": "audio-ws-status"`, an ID in a lookup table, and the
    census turned it into a data-testid selector and then reported it DEAD. The product ships
    that anchor as `id="audio-ws-status"`, so the census had invented a probe bug and blamed
    the tree for it.

    ⇒ That is this row's own defect — a confident verdict standing in for "I guessed what this
    string was for" — committed by the instrument built to count it. Recorded rather than
    quietly fixed, because a census that has never been caught inventing is one nobody has
    checked.

    Ensures:
        - returns a set of canonical literals
        - a get_by_test_id("x") call contributes [data-testid="x"] — the two spellings name
          one anchor, and counting them apart would inflate the denominator
    """
    found = set()
    for m in _GET_BY_TEST_ID.finditer( text ):
        found.add( f'[data-testid="{m.group( 2 )}"]' )
    for m in _STRING_LITERAL.finditer( text ):
        lit = m.group( 2 )
        if _CSS_TESTID.search( lit ) or lit.startswith( "#" ):
            found.add( normalise( lit ) )
    return found


def names_surface( literal, shipped ):
    """
    Is this literal about one of the two surfaces?

    Clause 1 (spelling) is what makes a DEAD selector countable — it is in no registry, so a
    membership test alone could never see it. Clause 2 catches the legacy side, whose ids
    carry no prefix. The gap both leave is named in the module docstring.

    Ensures:
        - returns a bool
    """
    if SURFACE_PREFIX in literal: return True
    m = _CSS_TESTID.search( literal )
    if m: return m.group( 2 ) in shipped
    # The ROOT id of the selector, not the whole string. `#fleet-status-pane .inner` is about
    # this surface; a whole-string membership test sees `fleet-status-pane .inner`, finds no
    # such anchor, and silently drops every compound selector rooted at a legacy id — an
    # undercount that would have made the COMPOUND bucket look smaller than it is.
    root_id = re.match( r'^#([a-zA-Z0-9_-]+)', literal )
    return bool( root_id ) and root_id.group( 1 ) in shipped


def bucket_for( literal, from_jsdom_test ):
    """
    Place ONE literal in exactly one bucket.

    Requires:
        - literal is canonical (normalise() has run)
        - from_jsdom_test says whether its ONLY home is a *.test.ts
    Ensures:
        - returns one member of Bucket.ALL
    """
    if "{" in literal:
        return Bucket.UNRESOLVABLE
    if from_jsdom_test:
        return Bucket.JSDOM_ONLY
    if _PLAIN_ID.fullmatch( literal ) or _PLAIN_TESTID.fullmatch( literal ):
        return Bucket.PAGE_ANCHOR
    return Bucket.COMPOUND


def census( root=None, pathspecs=None ):
    """
    Count the whole surface, bucketed, with each literal's homes recorded.

    Ensures:
        - returns { "files": n, "buckets": { bucket: [ literals ] }, "homes": { literal: [ files ] } }
        - the bucket sizes sum to the number of distinct literals
    """
    root    = _root( root )
    files   = population_files( root, pathspecs )
    shipped = shipped_anchor_names( root )
    homes   = {}
    jsdom   = {}
    for rel in files:
        text     = ( root / rel ).read_text( errors="replace" )
        is_jsdom = rel.endswith( ".test.ts" )
        for lit in extract_literals( text ):
            if not names_surface( lit, shipped ): continue
            homes.setdefault( lit, [] ).append( rel )
            jsdom[ lit ] = jsdom.get( lit, True ) and is_jsdom

    buckets = { b: [] for b in Bucket.ALL }
    for lit in sorted( homes ):
        buckets[ bucket_for( lit, jsdom[ lit ] ) ].append( lit )
    return { "files": len( files ), "buckets": buckets, "homes": homes }


def guard_coverage( page_anchors, root=None ):
    """
    What `selector_guard` says about each PAGE_ANCHOR literal.

    This is coverage-IN-PRINCIPLE: the classifier reaching a verdict. It is NOT
    coverage-in-fact — a selector no caller ever hands to preflight() is unguarded however
    classifiable it is. Conflating the two would credit the guard for selectors it has never
    seen.

    Ensures:
        - returns { literal: ( state, detail ) } for every input literal
    """
    from selector_guard import classify_selector, load_page_anchors, load_registry
    root     = _root( root )
    registry = load_registry( root )
    anchors  = load_page_anchors( root )
    return { lit: classify_selector( lit, registry, anchors ) for lit in page_anchors }


def render( result, coverage=None ):
    """
    Ensures:
        - returns a plain-text report naming the population and every bucket count
    """
    b     = result[ "buckets" ]
    total = sum( len( v ) for v in b.values() )
    lines = [ f"POPULATION: {result['files']} tracked files "
              f"(git ls-files -- {' '.join( POPULATION_PATHSPECS )}, suffixes "
              f"{' '.join( POPULATION_SUFFIXES )})",
              f"DISTINCT SURFACE SELECTOR LITERALS: {total}",
              "" ]
    for name in Bucket.ALL:
        lines.append( f"  {name:14} {len( b[ name ] ):4}" )
    if coverage is not None:
        states = {}
        for state, _detail in coverage.values():
            states[ state ] = states.get( state, 0 ) + 1
        lines += [ "", f"  selector_guard verdicts over the {len( coverage )} PAGE_ANCHOR literals:" ]
        for state in sorted( states ):
            lines.append( f"    {state:18} {states[ state ]:4}" )
    return "\n".join( lines )


def main():                                                 # pragma: no cover - CLI entry point
    root   = _root()
    result = census( root )
    cov    = guard_coverage( result[ "buckets" ][ Bucket.PAGE_ANCHOR ], root )
    print( render( result, cov ) )
    for lit, ( state, detail ) in sorted( cov.items() ):
        if state == "DEAD":
            print( f"\nDEAD  {lit}\n      {detail}\n      homes: {result['homes'][ lit ]}" )
    return 0


if __name__ == "__main__":                                  # pragma: no cover - CLI entry point
    import sys
    sys.path.insert( 0, str( pathlib.Path( __file__ ).parent ) )
    raise SystemExit( main() )

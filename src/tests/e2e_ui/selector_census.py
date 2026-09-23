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
#: A data-testid selector plus any descendant tail, matched by SHAPE rather than by pairing
#: quotes — see the escape-hidden pass in extract_literals().
_ESCAPE_HIDDEN_TESTID = re.compile(
    r'''\[data-testid="[a-zA-Z0-9_-]+"\][^"\'\n()]*''' )


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
    # 🔴 SCANNED TWICE: once raw, once UNESCAPED. A selector nested inside another string
    # literal reaches the file as `"… '[data-testid=\\"multiplexer-x\\"] tr.row' …"`, and the
    # backslashes stop the attribute pattern matching — `test_multiplexer_task_list.py:228`
    # drives its polling predicate exactly that way, and it was INVISIBLE to this census.
    # Found by Mr. Radio's review, 2026-09-23 18:32 EDT; the third escape from this extractor
    # after the quote-blindness and the invented bare names.
    #
    # ⇒ UNESCAPE THE TEXT, NOT THE CAPTURED LITERAL. Unescaping the capture would hand back
    # the whole enclosing JS expression — `() => document.querySelectorAll( … ).length > 0` —
    # as if it were a selector. Unescaping the text first turns the INNER quoted selector into
    # an ordinary literal the normal scan finds, which is the thing somebody actually wrote.
    for m in _GET_BY_TEST_ID.finditer( text ):
        found.add( f'[data-testid="{m.group( 2 )}"]' )
    for m in _STRING_LITERAL.finditer( text ):
        lit = m.group( 2 )
        if _CSS_TESTID.search( lit ) or lit.startswith( "#" ):
            found.add( normalise( lit ) )

    # The ESCAPE-HIDDEN pass. String-literal pairing cannot find these: once the quotes are
    # unescaped the outer and inner quotes are the same character, so a left-to-right pairing
    # scan straddles the selector and captures a fragment of the enclosing expression instead.
    # So this matches the selector BY SHAPE, anchored on the attribute.
    #
    # ⚠️ ONLY THE ATTRIBUTE FORM NEEDS THIS, and that is a property of the syntax rather than a
    # simplification: a `#id` selector contains NO QUOTES, so nothing in it can ever be
    # escaped, so it can never be escape-hidden. Only a quoted-attribute selector can.
    unescaped = text.replace( '\\"', '"' ).replace( "\\'", "'" )
    for m in _ESCAPE_HIDDEN_TESTID.finditer( unescaped ):
        found.add( normalise( m.group( 0 ).strip() ) )
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


# ==========================================================================================
# THE ENFORCED POPULATION — what a gate may REFUSE, which is not what the census DESCRIBES
# ==========================================================================================
#
# Row `485442ea`. The census above answers "how many exist". A gate needs a different and
# strictly smaller question: "which of these, if dead, is a real defect I should refuse?"
#
# 🔴 THE TWO POPULATIONS ARE NOT THE SAME, AND CONFLATING THEM FAILS ON DAY ONE.
# Measured at 65810c0e: the descriptive census reports SIX DEAD literals, and ALL SIX are
# deliberate negative controls — `multiplexer-fleet-pane` and `multiplexer-not-a-real-surface`
# in `selector_guard.self_test`, plus four in the unit fixtures. A gate refusing any DEAD
# literal would have gone red the moment it was written, for reasons that are the guard
# working correctly.
#
# ⇒ And the obvious repair — an allowlist of files to skip — is an ENUMERATION DEFECT INSIDE
# THE FIX FOR ONE. It goes stale silently, and a real probe added to a skipped file inherits
# the exemption. So every clause below is DERIVED from what the file does:
#
#   1. the literal sits at a LOCATOR CALL SITE — somebody handed it to a browser to find an
#      element. A quoted CSS-shaped string in a list, a dict or a parametrize table is not a
#      lookup, and treating it as one is how the census once invented selectors nobody wrote.
#   2. it is NOT in a `*.test.ts` — those render a component into jsdom and query their own
#      output, so the served page is the wrong oracle. Already a named census bucket, and two
#      of the three survivors of clause 1 alone were exactly this: a wrong-oracle verdict, not
#      a defect.
#   3. it is NOT in a guard module, nor a file importing one — which is what "this file's job
#      is testing the guard" actually MEANS, rather than a list of names that drifts.
#
# MEASURED under all three: 196 literals, 196 with a classifiable root anchor, 0 DEAD.

# 🔴 THERE IS NO LIST OF LOCATOR METHODS HERE, AND THE FIRST CUT HAD ONE.
#
# It enumerated `.locator`, `.wait_for_selector`, `.query_selector`, `get_by_test_id` and
# called that "a locator call site". Mr. Radio's review (2026-09-23 18:25 EDT) found it
# missing REAL lookups in `test_multiplexer_broadcast_card.py` and
# `test_layout_mode_toolbar_centering.py`: Playwright's action methods take the selector as
# their FIRST ARGUMENT — `page.click( sel )`, `page.fill( sel, v )`, `page.text_content( sel )`,
# `page.input_value( sel )` — and there are some thirty of them.
#
# ⇒ Writing the list out is the defect, not the omission from it. The predicate the list was
# approximating is simply: A STRING LITERAL THAT NAMES ONE OF THE TWO SURFACES. `names_surface`
# already decides that against the product's own shipped anchors, so no API enumeration is
# needed and none can go stale. Measured: the enumeration guarded 196 selectors, the predicate
# guards 272.

#: An import of any guard module, relative or absolute.
_IMPORTS_A_GUARD = re.compile(
    r'\b(?:import|from)\s+\.?(?:selector_guard|selector_census|selector_altitude|live_dom_check)\b' )

#: The guard modules themselves. They define the API the clause above detects importers of, so
#: they cannot be caught by it — a module does not import itself. Kept as a set rather than a
#: path prefix so `test_guard_corpus_is_exactly_the_guard_modules` can assert each one really
#: does define guard API, which is what stops this set being a quiet allowlist.
GUARD_MODULES = { "selector_guard.py", "selector_census.py",
                  "selector_altitude.py", "live_dom_check.py" }

#: The leading anchor of a selector — the part the guard has authority over.
_ROOT_ANCHOR = re.compile( r'^(#[a-zA-Z0-9_-]+|\[data-testid="[a-zA-Z0-9_-]+"\])' )


def root_anchor( literal ):
    """
    The leading `#id` or `[data-testid="x"]` of a selector, or None.

    A COMPOUND selector (`#fleet-status-pane .inner`) can go dead exactly the way a plain one
    can, and it is the ROOT that goes dead — the trailing `.inner` is a class, which the guard
    has no authority over and does not pretend to.

    Ensures:
        - returns the root anchor string, or None when the selector is rooted at a class, a
          tag or text
        - a plain anchor is its own root, so PAGE_ANCHOR and COMPOUND go through one path
    """
    m = _ROOT_ANCHOR.match( literal )
    return m.group( 1 ) if m else None


def is_enforceable_file( rel, text ):
    """
    May a gate refuse a dead selector found in this file?

    Requires:
        - rel is the repo-relative path; text is the file's contents
    🔴 CLAUSE 3 USED TO READ "ANY FILE THAT IMPORTS A GUARD MODULE", AND THAT PUT A HOLE IN
    THE GUARD WITH THE VERY COMMIT THAT WIRED IT IN. `e2e_ui/conftest.py` gained two fixtures
    importing `live_dom_check` and `selector_altitude`, so the shared helper behind all 118
    e2e tests exempted itself BY USING the guard. Caught by Mr. Radio's review, 2026-09-23
    18:25 EDT, not by me.

    ⚠️ Scope, stated honestly: conftest's own selectors are login/register anchors, so they
    name neither guarded surface and nothing was in fact unguarded. The defect is that the
    exemption keyed on the WRONG PROPERTY — the day conftest gains a multiplexer selector it
    would be silently exempt.

    ⇒ The clause conflated two opposite things: a file whose JOB IS TESTING the guard (full of
    deliberate DEAD controls) and a file that merely USES it. A user of the guard should be
    MORE guarded, never exempt. The corrected predicate names the first and only the first: a
    guard module, or a UNIT TEST of one. Measured: 9 files exempt — the 4 guard modules and
    their 5 unit tests, and nothing else.

    Ensures:
        - returns False for a jsdom test, a guard module, or a unit test importing one
        - every clause is derived from what the file IS or DOES — see the block comment above
          for why an allowlist was refused
    """
    if rel.endswith( ".test.ts" ):                 return False   # jsdom: wrong oracle
    if pathlib.Path( rel ).name in GUARD_MODULES:  return False   # the guard itself
    if rel.startswith( "src/tests/unit/" ) and _IMPORTS_A_GUARD.search( text ):
        return False                                              # a unit test OF the guard
    return True


def enforced_population( root=None, pathspecs=None ):
    """
    Every selector a gate may refuse, with the files that name it.

    Ensures:
        - returns { literal: sorted[ files ] }
        - only literals in an enforceable file that name one of the two surfaces and are not
          interpolated — no list of locator methods, see the block comment above
    Raises:
        - RuntimeError when the population is empty. A gate over nothing passes every
          assertion in it, and would report green forever.
    """
    root    = _root( root )
    shipped = shipped_anchor_names( root )
    homes   = {}
    for rel in population_files( root, pathspecs ):
        text = ( root / rel ).read_text( errors="replace" )
        if not is_enforceable_file( rel, text ): continue
        for lit in extract_literals( text ):
            if "{" in lit: continue                       # a name-generator, not a name
            if not names_surface( lit, shipped ): continue
            homes.setdefault( lit, set() ).add( rel )
    if not homes:
        raise RuntimeError(
            "the enforced population is EMPTY — no enforceable file named either surface. A "
            "gate over nothing passes every assertion in it, so this refuses rather than "
            "reporting a green run over zero selectors." )
    return { lit: sorted( files ) for lit, files in homes.items() }


def dead_in_enforced_population( root=None, pathspecs=None ):
    """
    The gate's verdict: every enforceable selector whose ROOT anchor is DEAD.

    Ensures:
        - returns { literal: ( detail, [ files ] ) }, empty when the tree is clean
        - a selector with no classifiable root is SKIPPED, not passed — the guard has no
          authority over a class-rooted selector and says so by declining, rather than
          returning a verdict it cannot support
    """
    from selector_guard import classify_selector, load_page_anchors, load_registry
    root     = _root( root )
    registry = load_registry( root )
    anchors  = load_page_anchors( root )
    dead     = {}
    for lit, files in enforced_population( root, pathspecs ).items():
        anchor = root_anchor( lit )
        if anchor is None: continue
        state, detail = classify_selector( anchor, registry, anchors )
        if state == "DEAD": dead[ lit ] = ( detail, files )
    return dead

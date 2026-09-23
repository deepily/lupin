"""
selector_guard.py — make a DEAD selector loud.

THE DEFECT THIS EXISTS FOR (Mr. Radio 🦉, 2026-09-22)
-----------------------------------------------------
`pixel_compare.py` paired legacy `fleet-status-section` with mux testid
`multiplexer-fleet-pane`. Nothing ships that testid: the pane carries
`id="fleet-status-pane"` and `data-testid="multiplexer-fleet-status-pane"`
(multiplexer.html:214-215). The locator matched nothing, `grab()` returned the string
"absent", and the row printed `NOT COMPARABLE — missing a side`.

That verdict is indistinguishable from the honest one. "The pane is not on the page" and
"I asked for a pane that does not exist" are DIFFERENT FACTS with different owners — the
first is a finding about the product, the second is a bug in the probe — and the old code
rendered both as the same six characters. The fleet-status pair was never compared, and the
run reported that in a form nobody could act on.

WHAT THIS MODULE DOES
---------------------
Resolves every mux selector against the product's OWN registry BEFORE the browser starts,
and refuses the run if any selector names something the product never ships. A probe that
cannot find its target must fail like a broken instrument, not emit a finding about the
thing it failed to look at.

FOUR STATES, NOT TWO:
  SHIPPED_ID       — `#<id>`, and the id is in the served page
  SHIPPED_TESTID   — the data-testid is in the served page
  RUNTIME_INJECTED — named only by the TS / SECTION_TOGGLES, so it is created at runtime
                     (commons-activity-pane is injected by broadcastCard.ts — sectionToolbar.ts
                     says so in its own header comment)
  DEAD             — names nothing anywhere. A PROBE BUG. It aborts the run.

WHY THE REGISTRY AND NOT A PAGE SCRAPE
--------------------------------------
`SECTION_TOGGLES` in sectionToolbar.ts is the product's own list of sections, and its header
comment warns in as many words that it is NOT a scrape of the page — one entry is injected at
runtime, so a page-only authority would delete a working pane. The registry is the population;
the served page is one sample of it.

Requires:
    - LUPIN_ROOT names a checkout containing src/lupin_app/static/
Ensures:
    - classify_selector() returns exactly one of the four states
    - preflight() raises DeadSelector naming EVERY dead selector, not just the first
"""
import os, pathlib, re

SECTION_TOOLBAR    = "src/lupin_app/static/js/multiplexer/render/templates/sectionToolbar.ts"
MULTIPLEXER_HTML   = "src/lupin_app/static/html/multiplexer.html"
MULTIPLEXER_TS_DIR = "src/lupin_app/static/js/multiplexer"

# 🔴 BOTH SURFACES, WIDENED 2026-09-23 (row 04735b66, Krishna 🦚) — THIS USED TO BE
# MULTIPLEXER-ONLY AND THAT MADE IT LIE ON THE LEGACY HALF.
#
# The guard was built against the multiplexer corpus and its authority was multiplexer.html
# plus the multiplexer TS. Nothing stopped a caller handing it a LEGACY selector, and when the
# census did exactly that, 206 of 264 page-anchor literals came back DEAD. They are not dead:
# `#clock`, `#env-label`, `#audio-session`, `#epic-board-container` and 200-odd others are
# shipped by notifications.html, which the guard had never read.
#
# ⇒ That is the SAME defect the guard exists to prevent, pointed the other way. The original
# bug reported a probe error as a product finding; this one reported a working selector as a
# probe bug. Both are one confident verdict standing in for "I did not look there."
#
# ⇒ AND IT IS THE DENOMINATOR QUESTION'S WHOLE POINT. Every selector the guard had actually
# been run on was a multiplexer selector, so its corpus and its authority agreed and the hole
# was invisible. Counting the surface is what exposed it.
NOTIFICATIONS_HTML = "src/lupin_app/static/html/notifications.html"
SURFACE_HTML       = ( MULTIPLEXER_HTML, NOTIFICATIONS_HTML )
# Script roots whose files can create an anchor at runtime. Kept to the directories that
# actually render these two surfaces — sweeping all of static/js/ would drag vendor bundles in
# and turn RUNTIME_INJECTED into a bucket that absorbs everything.
SCRIPT_ROOTS       = ( MULTIPLEXER_TS_DIR,
                       "src/lupin_app/static/js/shared",
                       "src/lupin_app/static/js/nav",
                       "src/lupin_app/static/js/notifications.js",
                       "src/lupin_app/static/js/broadcast-panel.js" )
SCRIPT_SUFFIXES    = ( ".ts", ".js" )


class DeadSelector( Exception ):
    """Raised when a selector names something the product does not ship."""


def _root():
    r = os.environ.get( "LUPIN_ROOT" )
    if r is None: raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
    return pathlib.Path( r )


def load_registry( root=None ):
    """
    The product's own section list, read from SECTION_TOGGLES.

    Ensures:
        - returns a non-empty set of sectionId strings
        - raises when the parse finds nothing: an empty registry would make every selector
          look RUNTIME_INJECTED and the guard would pass vacuously
    """
    root = root or _root()
    ids  = set( re.findall( r'sectionId\s*:\s*"([a-z0-9-]+)"', ( root / SECTION_TOOLBAR ).read_text() ) )
    if not ids:
        raise RuntimeError( f"SECTION_TOGGLES parse found ZERO sectionIds in {SECTION_TOOLBAR} — "
                            "the instrument is broken, not the registry. Refusing to classify." )
    return ids


def load_page_anchors( root=None ):
    """
    Every id and data-testid the product ships, KEPT SEPARATE BY PROVENANCE.

    The separation is the whole point. An anchor in the served HTML is there on first paint;
    one that exists only in TypeScript is created at runtime and is legitimately missing from a
    page that has not reached that code yet. Folding them together makes a runtime-injected pane
    look shipped-and-broken instead of shipped-and-late.

    Ensures:
        - returns dict with keys html_ids, html_testids, ts_ids, ts_testids
        - the served-page sets and the TS testid set are non-empty (empty means a broken parse)
    """
    root = root or _root()
    out  = { "html_ids": set(), "html_testids": set(), "ts_ids": set(), "ts_testids": set(),
             "ts_testid_patterns": set() }

    for rel in SURFACE_HTML:
        html = ( root / rel ).read_text()
        out[ "html_ids"     ] |= set( re.findall( r'\bid="([a-zA-Z0-9_-]+)"', html ) )
        out[ "html_testids" ] |= set( re.findall( r'\bdata-testid="([a-zA-Z0-9_-]+)"', html ) )

    for rel in SCRIPT_ROOTS:
        base    = root / rel
        sources = ( [ base ] if base.is_file()
                    else [ p for s in SCRIPT_SUFFIXES for p in base.rglob( f"*{s}" ) ] )
        for src in sources:
            body = src.read_text()
            # Testids in a rendered template: data-testid="x".
            out[ "ts_testids" ] |= set( re.findall( r'\bdata-testid="([a-zA-Z0-9_-]+)"', body ) )
            # Testids set imperatively: setAttribute( "data-testid", "x" ). Matched by its
            # ASSIGNMENT CONTEXT, never as a bare quoted string — a bare-string sweep would
            # make every literal in the bundle look runtime-injected, and the guard would pass
            # vacuously for exactly the selectors it is meant to refuse.
            out[ "ts_testids" ] |= set( re.findall(
                r'["\']data-testid["\']\s*,\s*["\']([a-zA-Z0-9_-]+)["\']', body ) )
            # A testid handed to a RENDER HELPER as an argument, never touching an attribute
            # in this file: `range( "multiplexer-flow-ratio-threshold", … )`,
            # `testid : "multiplexer-holding-area-request-badge"`,
            # `testidPrefix : "multiplexer-new-ticket"`.
            #
            # ⚠️ THIS IS A BARE-STRING SWEEP, which the docstring above warns can make the
            # guard pass vacuously — and it is safe ONLY because the `multiplexer-` prefix
            # bounds it. It cannot absorb an arbitrary name; it can only vouch for a name the
            # product source actually spells out. The two DEAD self-test cases are the proof:
            # `multiplexer-fleet-pane` and `multiplexer-not-a-real-surface` appear in no
            # product file, so both stay DEAD with this sweep in place.
            #
            # ⚠️ AND IT WAS IN THE ORIGINAL GUARD. Widening the authority to both surfaces
            # replaced it with the narrower attribute-only parse, which is what turned these
            # four live anchors into false DEAD verdicts. A widening on one axis narrowed
            # another, and only counting the surface made that visible.
            out[ "ts_testids" ] |= set( re.findall( r'["\'](multiplexer-[a-zA-Z0-9_-]+)["\']', body ) )
            out[ "ts_ids" ]     |= set( re.findall( r'\bid="([a-zA-Z0-9_-]+)"', body ) )
            out[ "ts_ids" ]     |= set( re.findall(
                r'querySelector[^(]*\(\s*["\']#([a-zA-Z0-9_-]+)["\']', body ) )
            out[ "ts_ids" ]     |= set( re.findall(
                r'getElementById\(\s*["\']([a-zA-Z0-9_-]+)["\']', body ) )
            # 🔴 TESTIDS COMPOSED AT RUNTIME FROM A TEMPLATE — the guard's THIRD blind state,
            # found 2026-09-23 by the census (row 04735b66) and false-DEAD until now.
            #
            # `JobsPaneRenderer.ts:300` writes
            #     btn.setAttribute( "data-testid", `multiplexer-jobs-filter-${mode}-btn` )
            # so the name `multiplexer-jobs-filter-own-btn` EXISTS ON THE RUNNING PAGE and
            # appears NOWHERE in the source as a literal. A parse that only collects literals
            # calls it DEAD and accuses a working probe of a typo.
            #
            # ⇒ Same shape as the original defect and as the legacy hole above: one verdict
            # covering both "the product does not ship this" and "I cannot see how it is
            # built". Three instances of one mechanism in one module is the finding, not the
            # three fixes.
            out[ "ts_testid_patterns" ] |= set( re.findall(
                r'["\']data-testid["\']\s*,\s*`([^`]*\$\{[^`]*)`', body ) )

    if not out[ "html_ids" ] or not out[ "html_testids" ]:
        raise RuntimeError( "served-page anchor parse found no ids or no testids — instrument broken." )
    if not out[ "ts_testids" ]:
        raise RuntimeError( "script anchor parse found no testids — instrument broken." )
    return out


def template_to_regex( template ):
    """
    Turn one JS template literal into a regex that matches the names it can produce.

    `multiplexer-jobs-filter-${mode}-btn` -> ^multiplexer\\-jobs\\-filter\\-[a-zA-Z0-9_-]+\\-btn$

    Requires:
        - template contains at least one ${...} hole
    Ensures:
        - returns a compiled anchored regex
        - the literal segments are ESCAPED, so a `.` or `+` in a name cannot widen the match
        - each hole becomes [a-zA-Z0-9_-]+ — ONE OR MORE, never `*`. A `*` hole would let
          `multiplexer--btn` match, and more importantly would let a template with a single
          hole and no literal text match every name in the tree, turning RUNTIME_INJECTED into
          a bucket that absorbs the DEAD ones the guard exists to catch.
    """
    parts = re.split( r'\$\{[^}]*\}', template )
    return re.compile( "^" + "[a-zA-Z0-9_-]+".join( re.escape( p ) for p in parts ) + "$" )


#: A template must begin with this much literal text before it is allowed to match anything.
#: Not a tuning knob — see the refusal rationale in is_anchoring_template().
MIN_TEMPLATE_PREFIX = 3


def is_anchoring_template( template ):
    """
    May this template be used to explain a testid at all?

    🔴 THE NEGATIVE CONTROL CAUGHT THIS ONE, WHICH IS THE ONLY REASON IT IS HERE.
    The first cut refused only a template with NO literal text. `ttsChrome.ts` writes
    `` `${ tid }-${ field }` `` — one hyphen of literal text and two open holes — which
    compiles to `^[a-zA-Z0-9_-]+\\-[a-zA-Z0-9_-]+$` and matches nearly every hyphenated name
    in the tree. It re-classified BOTH self-test DEAD cases as RUNTIME_INJECTED, including
    `multiplexer-not-a-real-surface`, the deliberate negative control.

    ⇒ The guard would have passed vacuously for exactly the selectors it exists to refuse, and
    the only thing standing between that and a green run was a case someone had written down
    because it was supposed to fail. A guard's negative control is not ceremony.

    ⚠️ AND THE FIRST TIGHTENING WAS STILL NOT ENOUGH — the control caught it twice. Requiring
    a literal PREFIX still admitted `` `multiplexer-${ pillIdFor( status ) }` ``, a trailing
    open hole that vouches for every name beginning `multiplexer-`, negative control included.

    THE RULE, in its settled form: EVERY hole must be BOUNDED ON BOTH SIDES by literal text,
    and the leading literal must be at least MIN_TEMPLATE_PREFIX characters. A template that
    begins or ends with a hole is open-ended; it describes a shape, and a shape cannot vouch
    for a name.

    ⇒ This REFUSES some templates that do legitimately build a name, so their products stay
    DEAD. That is the deliberate direction of the error. A false DEAD aborts a working probe
    loudly and is fixed in one line; a false RUNTIME_INJECTED waves a typo through silently,
    which is the defect this whole module exists to prevent.

    Ensures:
        - returns a bool; False for a template that starts or ends with a hole, or whose
          leading literal is shorter than MIN_TEMPLATE_PREFIX
    """
    parts = re.split( r'\$\{[^}]*\}', template )
    if len( parts ) < 2:                 return False   # no hole at all — not a template
    if not parts[ 0 ] or not parts[ -1 ]: return False   # hole-first or hole-last: open-ended
    if any( not p for p in parts[ 1:-1 ] ): return False  # two adjacent holes: unbounded middle
    return len( parts[ 0 ].strip( "-_" ) ) >= MIN_TEMPLATE_PREFIX


def matching_template( tid, templates ):
    """
    The first template that could have produced this testid, or None.

    Ensures:
        - returns the template STRING (so the message can name it) or None
        - a non-anchoring template is REFUSED, never matched
    """
    for tpl in sorted( templates ):
        if not is_anchoring_template( tpl ): continue
        if template_to_regex( tpl ).fullmatch( tid ): return tpl
    return None


def classify_selector( sel, registry, anchors ):
    """
    Classify ONE selector into exactly one of the four states.

    Requires:
        - sel is either '#<id>' or '[data-testid="<tid>"]'
        - anchors is the dict load_page_anchors() returns
    Ensures:
        - returns ( state, detail ), state in {SHIPPED_ID, SHIPPED_TESTID, RUNTIME_INJECTED, DEAD}
    """
    m = re.fullmatch( r'#([a-zA-Z0-9_-]+)', sel )
    if m:
        name = m.group( 1 )
        if name in anchors[ "html_ids" ]:
            return "SHIPPED_ID", f"id={name} present in the served page"
        if name in anchors[ "ts_ids" ] or name in registry:
            return "RUNTIME_INJECTED", ( f"id={name} absent from multiplexer.html but named by the "
                                         f"TS / SECTION_TOGGLES — created at runtime" )
        return "DEAD", f"id={name} is in neither the served page, the TS source, nor SECTION_TOGGLES"

    m = re.fullmatch( r'\[data-testid="([a-zA-Z0-9_-]+)"\]', sel )
    if m:
        tid = m.group( 1 )
        if tid in anchors[ "html_testids" ]:
            return "SHIPPED_TESTID", f"data-testid={tid} present in the served page"
        if tid in anchors[ "ts_testids" ]:
            return "RUNTIME_INJECTED", f"data-testid={tid} set from TypeScript — created at runtime"
        tpl = matching_template( tid, anchors.get( "ts_testid_patterns", set() ) )
        if tpl:
            return "RUNTIME_INJECTED", ( f"data-testid={tid} is COMPOSED at runtime from the "
                                         f"template `{tpl}` — the literal name is in no source file" )
        stem = tid.replace( "multiplexer-", "" ).split( "-" )[ 0 ]
        near = sorted( t for t in ( anchors[ "html_testids" ] | anchors[ "ts_testids" ] ) if stem in t )[ :3 ]
        return "DEAD", f"data-testid={tid} is shipped by nothing" + ( f"; nearest shipped: {near}" if near else "" )

    return "DEAD", f"unrecognised selector shape: {sel!r}"


def preflight( selectors, root=None ):
    """
    Classify every selector and REFUSE the run if any is dead.

    Ensures:
        - returns { selector: ( state, detail ) } when all selectors resolve
    Raises:
        - DeadSelector naming EVERY dead selector — reporting only the first hides the rest
          behind one fix-and-rerun cycle each
    """
    root     = root or _root()
    registry = load_registry( root )
    anchors  = load_page_anchors( root )
    verdicts = { s: classify_selector( s, registry, anchors ) for s in selectors }
    dead     = { s: d for s, ( st, d ) in verdicts.items() if st == "DEAD" }
    if dead:
        lines = "\n".join( f"    {s}\n        {d}" for s, d in sorted( dead.items() ) )
        raise DeadSelector(
            f"{len( dead )} of {len( selectors )} selectors name nothing the product ships.\n"
            f"This is a PROBE BUG, not a finding about the product — a dead selector cannot tell\n"
            f"you whether the surface is present, so no verdict about it is reportable.\n"
            f"{lines}" )
    return verdicts


def self_test():
    """
    Prove the instrument can find something. A negative result is worth nothing until the same
    check has been watched returning a positive one.
    """
    root     = _root()
    registry = load_registry( root )
    anchors  = load_page_anchors( root )

    cases = [
        ( '[data-testid="multiplexer-fleet-pane"]',         "DEAD",             "the selector that caused this module" ),
        ( '[data-testid="multiplexer-fleet-status-pane"]',  "SHIPPED_TESTID",   "the real one, multiplexer.html:215" ),
        ( '#fleet-status-pane',                             "SHIPPED_ID",       "the registry's own key" ),
        ( '#commons-activity-pane',                         "RUNTIME_INJECTED", "injected by broadcastCard.ts, absent from the page" ),
        ( '[data-testid="multiplexer-not-a-real-surface"]', "DEAD",             "negative control" ),
    ]
    print( f"registry: {len( registry )} sectionIds | served page: {len( anchors['html_ids'] )} ids, "
           f"{len( anchors['html_testids'] )} testids | TS: {len( anchors['ts_ids'] )} ids, "
           f"{len( anchors['ts_testids'] )} testids\n" )
    failures = 0
    for sel, expected, why in cases:
        state, detail = classify_selector( sel, registry, anchors )
        ok = state == expected
        failures += 0 if ok else 1
        print( f"  {'PASS' if ok else 'FAIL'}  {sel:50} -> {state:16} (want {expected})  # {why}" )
        if not ok: print( f"        detail: {detail}" )
    print()
    if failures:
        raise SystemExit( f"self-test FAILED: {failures}/{len( cases )} cases wrong — do not trust this guard" )
    print( f"self-test passed {len( cases )}/{len( cases )}: the guard separates dead from shipped, "
           f"and shipped from runtime-injected." )


if __name__ == "__main__":
    self_test()

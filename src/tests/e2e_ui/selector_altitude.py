"""
selector_altitude.py — the WRONG-LEVEL half of the selector guard.

THE HOLE THIS CLOSES (row `04735b66`, Krishna 🦚, 2026-09-23)
-------------------------------------------------------------
`selector_guard` catches a selector that names NOTHING. `live_dom_check` catches a selector
the running page did not produce. Neither catches a selector that names the WRONG LEVEL of
the page — an inner element where its section wrapper was meant.

A wrong-altitude selector is the worst-behaved of the three, because every existing control
passes it:
    · it is shipped, so preflight says SHIPPED_ID
    · it resolves, so assert_live_dom counts 1
    · it screenshots cleanly, so the comparator gets two real images
    · and it returns a CONFIDENT DIFFER about a size difference the probe invented

MEASURED, 2026-09-22: `pixel_compare.py` paired the multiplexer's section wrapper against
legacy's `#fleet-status-section`, which is the `section-content` INNER div — the wrapper is
its ancestor `#section-fleet-status`, and it carries the header the inner div excludes.
Re-pairing to the wrapper took Δw to ZERO on all seven pairs. The 4px width "regression"
across five of them was entirely the altitude error.

⇒ And the width defect was the ONLY thing stopping the comparator reaching colour. Every
comparison aborted on size first, so a whole class of colour findings had never been reached.
A wrong-altitude selector does not just produce one wrong number; it can mask an entire
downstream stage while looking like a finding.

⚠️ THE NAMES ARE NEARLY ANAGRAMS AND THAT IS NOT A COINCIDENCE:
        #fleet-status-section   ← the INNER content div        (class="section-content")
        #section-fleet-status   ← the WRAPPER, the right level (class="collapsible-section")
A reviewer's eye slides straight over the difference, which is why this wants a mechanical
check rather than a convention.

⚠️ AND THE `-section` SUFFIX DOES NOT DECIDE ALTITUDE. `#action-required-section` and
`#tts-queue-section` ARE wrappers; `#fleet-status-section` is not. Any rule keyed on the name
would be wrong on the real page — the check has to ask the DOM.

THE PREDICATE
-------------
For a selector meant to name a section-level surface, the resolved element must BE its own
wrapper:

    el.closest( '.collapsible-section' ) === el

· equal          → the selector is at wrapper altitude. PASS.
· not equal      → it named a DESCENDANT. WRONG LEVEL, and the wrapper it should have used is
                   already in hand, so the failure names the fix rather than just the fault.
· no wrapper     → the element is outside any section. Reported as UNWRAPPED, a separate
                   state, NOT folded into the pass — "correct altitude" and "no altitude to be
                   wrong about" are different facts, and this module exists because two facts
                   sharing one representation is how the original defect happened.

Requires:
    - a page already navigated to the surface under test
Ensures:
    - assert_section_altitude() raises WrongAltitude naming EVERY offender and the wrapper
      each should have used, never just the first
"""

#: The class that marks a section wrapper on both surfaces. `enumerate.py:17` already resolved
#: `el.closest( '.collapsible-section' )` on the legacy side — the correct altitude was
#: sitting in a sibling probe the whole time, and the newer pixel probe hand-typed ids at the
#: wrong level instead of reusing it.
WRAPPER_CLASS = "collapsible-section"

#: Returns, for ONE selector: whether it resolved, whether the first match IS its own wrapper,
#: and the wrapper's id when it is not. Kept as a module constant so the unit tests and the
#: live control run the SAME script — a control over a different probe than the one that ships
#: proves nothing about the one that ships.
ALTITUDE_PROBE_JS = """
( args ) => {
  const out = {};
  for ( const sel of args.selectors ) {
    const el = document.querySelector( sel );
    if ( !el ) { out[ sel ] = { resolved: false }; continue; }
    const wrap = el.closest( '.' + args.wrapperClass );
    out[ sel ] = {
      resolved   : true,
      hasWrapper : wrap !== null,
      isWrapper  : wrap === el,
      wrapperId  : wrap ? wrap.id : null,
      wrapperCls : wrap ? wrap.className : null,
      ownCls     : el.className,
    };
  }
  return out;
}
"""


class WrongAltitude( Exception ):
    """Raised when a selector resolves to a descendant of the section it was meant to name."""


class Altitude:
    """The three states a resolved selector can be in. Exhaustive and mutually exclusive."""
    WRAPPER     = "WRAPPER"      # it IS the section wrapper — the intended altitude
    DESCENDANT  = "DESCENDANT"   # it is INSIDE a wrapper — the defect
    UNWRAPPED   = "UNWRAPPED"    # no wrapper ancestor — outside any section
    UNRESOLVED  = "UNRESOLVED"   # matched nothing; live_dom_check's question, not this one
    ALL         = ( WRAPPER, DESCENDANT, UNWRAPPED, UNRESOLVED )


def classify_altitude( probe ):
    """
    Classify ONE probe result into exactly one Altitude state.

    Kept PURE — it takes the dict the browser returned and touches no page. The browser half
    and the deciding half are separable on purpose: a decision that can only be exercised
    through a live page is a decision nobody can write a fast test for.

    Requires:
        - probe is one value from ALTITUDE_PROBE_JS's return map
    Ensures:
        - returns ( state, detail ), state in Altitude.ALL
    """
    if not probe.get( "resolved" ):
        return Altitude.UNRESOLVED, "matched nothing — that is live_dom_check's question, not this one"
    if not probe.get( "hasWrapper" ):
        return Altitude.UNWRAPPED, ( f"no .{WRAPPER_CLASS} ancestor — the element is outside any "
                                     f"section, so it has no altitude to be wrong about "
                                     f"(class={probe.get( 'ownCls' )!r})" )
    if probe.get( "isWrapper" ):
        return Altitude.WRAPPER, f"is its own .{WRAPPER_CLASS} (class={probe.get( 'ownCls' )!r})"
    return Altitude.DESCENDANT, ( f"resolves to a DESCENDANT (class={probe.get( 'ownCls' )!r}); the "
                                  f"section wrapper is #{probe.get( 'wrapperId' )} "
                                  f"(class={probe.get( 'wrapperCls' )!r}) — measure that instead" )


def altitudes( page, selectors, wrapper_class=WRAPPER_CLASS ):
    """
    Classify every selector against the LIVE page.

    Ensures:
        - returns { selector: ( state, detail ) }
    Raises:
        - WrongAltitude on an empty selector list — a loop over nothing satisfies every
          assertion in it, so a vacuous pass is refused rather than reported
    """
    if not selectors:
        raise WrongAltitude( "altitudes() called with ZERO selectors — a loop over nothing passes "
                             "every assertion in it. Refusing to report a vacuous pass." )
    probes = page.evaluate( ALTITUDE_PROBE_JS,
                            { "selectors": list( selectors ), "wrapperClass": wrapper_class } )
    return { sel: classify_altitude( probes[ sel ] ) for sel in selectors }


def assert_section_altitude( page, selectors, wrapper_class=WRAPPER_CLASS ):
    """
    Assert every selector names a section WRAPPER, not something inside one.

    Requires:
        - page has navigated to the surface under test
        - selectors are section-level selectors; passing a button here is a category error and
          will correctly report DESCENDANT
    Ensures:
        - returns { selector: ( state, detail ) } when none is a DESCENDANT
    Raises:
        - WrongAltitude naming EVERY descendant and the wrapper each should have used.
          Reporting only the first hides the rest behind a fix-and-rerun cycle each, and this
          defect arrives in batches — one mis-levelled pairing list produced five of them.
    """
    verdicts = altitudes( page, selectors, wrapper_class )
    wrong    = { s: d for s, ( st, d ) in verdicts.items() if st == Altitude.DESCENDANT }
    if wrong:
        lines = "\n".join( f"    {s}\n        {d}" for s, d in sorted( wrong.items() ) )
        raise WrongAltitude(
            f"WRONG LEVEL — {len( wrong )} of {len( selectors )} selectors resolve to an element\n"
            f"INSIDE a .{wrapper_class} instead of the section itself. Each one is live, resolves,\n"
            f"and screenshots cleanly, so every other guard passes it — and the size it reports is\n"
            f"the probe's error, not the product's.\n{lines}" )
    return verdicts

"""
Layout-Parity Oracle — the APPEARANCE axis for the 13 inner-accordion rows.

john's `test_tier1_accordions_cross_client.py` proved these 13 rows agree
STRUCTURALLY and BEHAVIOURALLY, and said plainly what it did not establish:
"every green here is DOM and behaviour, never appearance: no computed style, no
geometry, no screenshot." This module is that missing half — the NAMED
computed-style properties of every contract row, read from both clients.

WHY BOTH SIDES ARE DRIVEN AT THE REAL PAGES, AND WHY THE HARNESS WOULD LIE HERE.
Appearance is produced by the CASCADE, not by the renderer. The component-
isolation harness links its own <link> set, so a computed style read there is a
fact about the harness page rather than about the client. This is the same
"enter at the layer the question lives at" lesson john's click probe learned one
level down — his harness mounted templates and could not see a delegated
listener; a harness page cannot see a sheet the real page links.

    legacy  /app/notifications?classic=1
    mux     /app/multiplexer

NAMED PROPERTIES, NOT PIXEL DIFFS (María's constraint, 2026-09-06). Everything
below is a `getComputedStyle` property value — including the two that sound
geometric. "Row height" is the resolved `height` property; "indent depth" is
`padding-left` + `text-indent`; "chevron glyph size" is the chevron span's
`font-size`. No bounding boxes, no screenshots, no tolerance window.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# The appearance property set. Every entry is one of the named properties in the
# assignment, or the property that RESOLVES one of them.
#
# Deliberately EXCLUDED: `width` (sub-pixel flex distribution — the Tier 2 rider
# excludes resolved sizing for exactly this reason, and a pane's width is set by
# its container rather than by the row's own styling).
# ---------------------------------------------------------------------------

ACCORDION_APPEARANCE_PROPS = [
    # font family / size / weight
    "font-family", "font-size", "font-weight", "font-style",
    "line-height", "letter-spacing", "text-transform",
    # color / background
    "color", "background-color",
    # padding  (padding-left doubles as the indent-depth reading)
    "padding-top", "padding-right", "padding-bottom", "padding-left",
    # margins
    "margin-top", "margin-right", "margin-bottom", "margin-left",
    # indent depth
    "text-indent",
    # alignment
    "text-align", "vertical-align", "align-items", "justify-content",
    # row height
    "height",
    # the rest of the visual frame
    "display", "opacity", "border-radius",
    "border-top-width", "border-right-width", "border-bottom-width", "border-left-width",
    "border-top-style", "border-right-style", "border-bottom-style", "border-left-style",
    "border-top-color", "border-right-color", "border-bottom-color", "border-left-color",
]

# ---------------------------------------------------------------------------
# The walker. Keys are IDENTITY-derived (data-owner / data-epic / data-filer)
# rather than positional, so the two clients align on the thing itself and a
# reordering cannot masquerade as a style divergence.
#
# It walks the 13 contract rows of LAYOUT-CONTRACT.md § "The inner accordions"
# and NOTHING else. The section-level chrome is out of population (five measured
# divergences on it are with Rick) — and john measured ZERO overlap between
# `.toggle-button` and these rows in both clients, so his section-chevron work
# cannot move anything read here.
#
# `found` is returned per family so an EMPTY walk is visible as an empty walk
# rather than as a clean pass: a loop over nothing satisfies every per-item
# assertion in it.
# ---------------------------------------------------------------------------

ACCORDION_APPEARANCE_JS = r"""
( args ) => {
    const { props } = args;
    const styleOf = ( el ) => {
        const cs  = getComputedStyle( el );
        const out = {};
        for ( const p of props ) out[ p ] = cs.getPropertyValue( p );
        return out;
    };
    const nodes = {};
    const put = ( key, el ) => { if ( el ) nodes[ key ] = styleOf( el ); };

    // ---- task pane: 3 contract rows -------------------------------------
    const taskGroups = [ ...document.querySelectorAll( "tbody.task-group" ) ];
    for ( const g of taskGroups ) {
        const owner = g.getAttribute( "data-owner" ) || "__unassigned__";
        const hdr   = g.querySelector( ":scope > tr.task-group-header" );
        put( `task[${owner}]`,          g );
        put( `task[${owner}]>header`,   hdr );
        put( `task[${owner}]>chevron`,  hdr && hdr.querySelector( ".task-group-chevron" ) );
    }

    // ---- epic pane: 5 contract rows -------------------------------------
    const epicGroups = [ ...document.querySelectorAll( "tbody.epic-group" ) ];
    for ( const g of epicGroups ) {
        const epic = g.getAttribute( "data-epic" ) || "__none__";
        const hdr  = g.querySelector( ":scope > tr.epic-group-header" );
        put( `epic[${epic}]>header`,  hdr );
        put( `epic[${epic}]>chevron`, hdr && hdr.querySelector( ".epic-group-chevron" ) );
        put( `epic[${epic}]>label`,   hdr && hdr.querySelector( ".epic-group-label" ) );
        put( `epic[${epic}]>count`,   hdr && hdr.querySelector( ".epic-group-count" ) );
        const stories = [ ...g.querySelectorAll( ":scope > tr.epic-story-row" ) ];
        stories.forEach( ( s, i ) => put( `epic[${epic}]>story[${i}]`, s ) );
    }

    // ---- holding pane: 5 contract rows ----------------------------------
    const holdGroups = [ ...document.querySelectorAll( "div.holding-area-group" ) ];
    for ( const g of holdGroups ) {
        const filer = g.getAttribute( "data-filer" ) || "__none__";
        const hdr   = g.querySelector( ":scope > .holding-area-group-header" );
        put( `holding[${filer}]`,         g );
        put( `holding[${filer}]>header`,  hdr );
        put( `holding[${filer}]>filer`,   hdr && hdr.querySelector( ".holding-area-filer" ) );
        put( `holding[${filer}]>count`,   hdr && hdr.querySelector( ".holding-area-group-count" ) );
        put( `holding[${filer}]>status`,  hdr && hdr.querySelector( ".holding-area-group-status" ) );
    }

    return {
        nodes,
        found : {
            task_groups    : taskGroups.length,
            epic_groups    : epicGroups.length,
            holding_groups : holdGroups.length,
        },
    };
}
"""

# The 13 contract rows, as the key SHAPE each one produces. Used to prove the
# walk reached every row type rather than merely returning a non-empty dict.
CONTRACT_ROW_SHAPES = (
    "task[*]", "task[*]>header", "task[*]>chevron",
    "epic[*]>header", "epic[*]>chevron", "epic[*]>label", "epic[*]>count", "epic[*]>story[*]",
    "holding[*]", "holding[*]>header", "holding[*]>filer", "holding[*]>count", "holding[*]>status",
)


def row_shape( key: str ) -> str:
    """Collapse an identity-keyed node key back to its contract-row shape.

    Requires:
        - key is a walker key such as "epic[epic:alpha]>story[0]"

    Ensures:
        - returns the same key with every [...] payload replaced by [*]
    """
    out, depth, buf = [], 0, []
    for ch in key:
        if ch == "[":
            depth += 1
            if depth == 1:
                out.append( "[*" )
                continue
        if ch == "]":
            depth -= 1
            if depth == 0:
                out.append( "]" )
                continue
        if depth == 0:
            out.append( ch )
    return "".join( out )

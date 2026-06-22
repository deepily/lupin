"""
WS3 — Layout-Parity Oracle: shared Python helpers.

Single-sources the bits the oracle tiers and the golden-capture script share:
  - repo path resolution (per CLAUDE.md PATH MANAGEMENT — via cu.get_project_root)
  - the expected shared-sheet path (WS1 / Clayton's lane)
  - the `<link>`-extraction used by Tier 0 (CSS Source Identity)
  - the 12-char content hash used both by Tier 0 and as the golden's
    staleness trip-wire (Rider C: a shared-sheet content drift fails the golden
    and forces recapture)

No server, no browser — pure path + text + hash logic.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import cosa.utils.util as cu

# Expected home of WS1's single-source contract sheet (Doc 01 Pillar 1, S2).
SHARED_SHEET_RELPATH = "src/lupin_app/static/css/shared/notifications-surface.css"

# The canonical layout-parity scenario — the single-source fixture (WS3).
FIXTURE_RELPATH = "src/tests/e2e_ui/fixtures/notifications-parity-scenario.json"

# Served URL of the component-isolation harness page (static mount).
HARNESS_URL_PATH = "/static/html/parity-harness.html"

# ---------------------------------------------------------------------------
# Layout-Contract skeleton walker (Doc 01 — Tier 1 DOM Contract Conformance).
#
# A single browser-side function that walks the sender-card contract subtree
# under `rootSel` and returns the normalized layout skeleton: for every contract
# node, its identity + contract classes + contract-driving attributes (NOT text,
# NOT timestamps — Category-4 noise). The SAME walker runs against the mux
# component-isolation harness (Tier 1) and against legacy (golden-capture), so
# "the same" is defined by ONE referee, not two hand-written checks. Contract
# classes are verbatim-shared between clients (Q-C), so one walker fits both.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Tier 2/3 — computed-style + geometry walker (Doc 01; D4 rider).
#
# LAYOUT_STYLE_PROPS = the DECLARATIVE layout property set asserted EXACTLY by
# Tier 2 (D4 rider): deliberately EXCLUDES resolved width/height/min/max sizing
# (sub-pixel flex distribution → flaky; resolved geometry is Tier 3's ±1px job)
# and excludes text/timestamps/animation mid-states (Category-4 noise).
#
# CONTRACT_STYLE_GEOM_JS returns, per contract node, a stable key + its declared
# style subset + its geometry RELATIVE TO ITS OWN SENDER CARD (intra-card
# offsets + node size). Intra-card framing makes Tier 3 robust to the fact that
# the legacy golden is captured from the full legacy page (card sits below other
# sections) while the mux render is isolated — only the card's own width must be
# matched (the capture records it; the Tier 3 test sizes the harness to it).
# Cards are keyed by data-sender-id (both clients set it); messages positionally
# (legacy sets neither data-id-hash nor data-date-key — both newest-first).
# ---------------------------------------------------------------------------

LAYOUT_STYLE_PROPS = [
    "display", "position", "box-sizing", "float", "clear",
    "margin-top", "margin-right", "margin-bottom", "margin-left",
    "padding-top", "padding-right", "padding-bottom", "padding-left",
    "border-top-width", "border-right-width", "border-bottom-width", "border-left-width",
    "border-top-style", "border-right-style", "border-bottom-style", "border-left-style",
    "flex-direction", "flex-wrap", "flex-grow", "flex-shrink", "align-items",
    "align-self", "justify-content", "gap", "order",
    "font-family", "font-size", "font-weight", "line-height", "letter-spacing",
    "white-space", "text-align",
    "color", "background-color", "box-shadow", "border-radius", "opacity",
]

CONTRACT_STYLE_GEOM_JS = r"""
( args ) => {
    const { rootSel, props } = args;
    const root = document.querySelector( rootSel );
    if ( !root ) return null;
    const round1 = ( n ) => Math.round( n * 10 ) / 10;
    const styleOf = ( el ) => {
        const cs = getComputedStyle( el );
        const out = {};
        for ( const p of props ) out[ p ] = cs.getPropertyValue( p );
        return out;
    };
    const nodes = [];
    const cards = [ ...root.querySelectorAll( ':scope > .sender-card' ) ]
        .sort( ( a, b ) => ( a.getAttribute( 'data-sender-id' ) || '' )
            .localeCompare( b.getAttribute( 'data-sender-id' ) || '' ) );
    for ( const card of cards ) {
        const sid = card.getAttribute( 'data-sender-id' );
        const cardRect = card.getBoundingClientRect();
        const rel = ( el ) => {
            const r = el.getBoundingClientRect();
            return { dx: round1( r.left - cardRect.left ), dy: round1( r.top - cardRect.top ),
                     w: round1( r.width ), h: round1( r.height ) };
        };
        nodes.push( { key: `card:${sid}`, styles: styleOf( card ),
                      geom: { dx: 0, dy: 0, w: round1( cardRect.width ), h: round1( cardRect.height ) } } );
        const header = card.querySelector( ':scope > .sender-card-header' );
        if ( header ) nodes.push( { key: `card:${sid}>header`, styles: styleOf( header ), geom: rel( header ) } );
        // Date-accordion region nodes (positional accordion index) — captures the
        // header→first-message gap surfaces so a vertical-metric divergence
        // localizes to an exact node (accordion-header / its date-text label /
        // the messages well) rather than only showing as a card-height delta.
        const accs = [ ...card.querySelectorAll( '.date-accordion' ) ];
        accs.forEach( ( acc, ai ) => {
            const ah = acc.querySelector( '.date-accordion-header' );
            if ( ah ) nodes.push( { key: `card:${sid}>acc[${ai}]>header`, styles: styleOf( ah ), geom: rel( ah ) } );
            const dt = acc.querySelector( '.date-text' );
            if ( dt ) nodes.push( { key: `card:${sid}>acc[${ai}]>date-text`, styles: styleOf( dt ), geom: rel( dt ) } );
            const am = acc.querySelector( '.date-accordion-messages' );
            if ( am ) nodes.push( { key: `card:${sid}>acc[${ai}]>messages`, styles: styleOf( am ), geom: rel( am ) } );
        } );
        const msgs = [ ...card.querySelectorAll( '.sender-message' ) ];
        msgs.forEach( ( m, i ) => {
            nodes.push( { key: `card:${sid}>msg[${i}]`, styles: styleOf( m ), geom: rel( m ) } );
            const t = m.querySelector( '.message-time' );
            const x = m.querySelector( '.message-text' );
            if ( t ) nodes.push( { key: `card:${sid}>msg[${i}]>time`, styles: styleOf( t ), geom: rel( t ) } );
            if ( x ) nodes.push( { key: `card:${sid}>msg[${i}]>text`, styles: styleOf( x ), geom: rel( x ) } );
        } );
    }
    return { nodes };
}
"""

CONTRACT_SKELETON_JS = r"""
( rootSel ) => {
    const root = document.querySelector( rootSel );
    if ( !root ) return null;
    const direction = ( el ) =>
        el.classList.contains( 'outgoing' ) ? 'outgoing'
        : el.classList.contains( 'incoming' ) ? 'incoming'
        : null;
    const cards = [ ...root.querySelectorAll( ':scope > .sender-card' ) ].map( ( card ) => ( {
        sender_id     : card.getAttribute( 'data-sender-id' ),
        has_header    : card.querySelector( ':scope > .sender-card-header' ) !== null,
        has_dates     : card.querySelector( '.sender-card-dates' ) !== null,
        persona_badge : card.querySelector( '.sender-persona-badge, .persona-badge' ) !== null,
        accordions    : [ ...card.querySelectorAll( '.date-accordion' ) ].map( ( acc ) => ( {
            date_key   : acc.getAttribute( 'data-date-key' ),
            has_header : acc.querySelector( '.date-accordion-header' ) !== null,
            has_text   : acc.querySelector( '.date-text' ) !== null,
            has_count  : acc.querySelector( '.date-count' ) !== null,
            has_toggle : acc.querySelector( '.date-toggle' ) !== null,
            messages   : [ ...acc.querySelectorAll( '.sender-message' ) ].map( ( m ) => ( {
                id_hash            : m.getAttribute( 'data-id-hash' ),
                direction          : direction( m ),
                has_time           : m.querySelector( '.message-time' ) !== null,
                has_text           : m.querySelector( '.message-text' ) !== null,
                expired_badge      : m.querySelector( '.expired-badge' ) !== null,
                abstract_indicator : m.querySelector( '.abstract-indicator' ) !== null,
            } ) ),
        } ) ),
    } ) );
    return { cards };
}
"""

# The served href the pages <link> — `/static/...` maps to `src/lupin_app/static/...`.
SHARED_SHEET_HREF = "/static/css/shared/notifications-surface.css"

# Matches any <link> href ending in notifications-surface.css (tolerant of
# query-string cache-busters like `?v=...`).
_SHARED_SHEET_HREF_RE = re.compile( r'href="([^"]*notifications-surface\.css[^"]*)"' )


def repo_root() -> Path:
    """Project root via the canonical resolver (reads LUPIN_ROOT)."""
    return Path( cu.get_project_root() )


def shared_sheet_path() -> Path:
    """On-disk path of WS1's shared contract sheet (may not exist until WS1 lands)."""
    return repo_root() / SHARED_SHEET_RELPATH


def html_path( name: str ) -> Path:
    """On-disk path of a static HTML page (e.g. 'multiplexer.html')."""
    return repo_root() / "src" / "lupin_app" / "static" / "html" / name


def linked_shared_hrefs( html_text: str ) -> list[ str ]:
    """Every <link> href in `html_text` that points at notifications-surface.css."""
    return _SHARED_SHEET_HREF_RE.findall( html_text )


def content_hash( path: Path ) -> str:
    """12-char sha256 of a file's bytes (same short-hash convention as build-multiplexer.sh)."""
    return hashlib.sha256( path.read_bytes() ).hexdigest()[ :12 ]


def fixture_path() -> Path:
    """On-disk path of the canonical layout-parity scenario JSON."""
    return repo_root() / FIXTURE_RELPATH


def load_scenario() -> dict[ str, Any ]:
    """Parse the canonical scenario — the same input both clients render."""
    return json.loads( fixture_path().read_text() )

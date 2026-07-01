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


# ===========================================================================
# FULL-PAGE CHROME PARITY (V1/V2/V3/V4/V5/V7/V9/V13) — page-scoped oracle.
#
# The sender-card oracle above compares a single-sourced contract subtree, so a
# blanket computed-style ISOMORPHISM is valid there. The PAGE CHROME is NOT
# uniformly single-sourced — most of it is re-implemented in the mux's own
# stylesheets — so a blanket style-iso would be FALSE NOISE. Each chrome row
# therefore carries a parity CATEGORY that scopes what claim is legitimately
# provable (ground-truthed live on :7999, 2026-07-01):
#
#   "A" single-sourced  → style + geometry isomorphism VALID.
#                          Only the top nav (both render <nav.lupin-nav> from the
#                          SAME lupin-nav.css at identical 0,0 geometry).
#   "B" re-implemented   → STRUCTURAL (presence) + GEOMETRIC (width / intra-node)
#                          parity ONLY; the palette/border look-fidelity that the
#                          iso deliberately skips is a human STYLE verdict, not
#                          this harness's job.
#   "C" mux-native OR    → presence + DISPLAY-STATE finding only. V13 toolbar has
#       display-asymmetric  no clean legacy equivalent; V4 PLY / V9 strip differ in
#                          idle display state (legacy hides PLY until playback while
#                          the mux shows an idle empty panel; the mux hides the strip
#                          while legacy shows it). Their colored-accordion / sub-icon
#                          GEOMETRY parity needs a seeded fixture → a future tier.
#
# Comparison is IDLE-STATE + fixture-free + deterministic: only the chrome that
# renders at idle in BOTH clients is compared. Absolute page-offset (dy from the
# page top) is deliberately NOT compared — the section ORDER legitimately differs
# between clients (the B1 reorder) — so Tier 3 asserts WIDTH + intra-node geometry,
# never absolute vertical position.
# ===========================================================================

# Served full-page URLs (idle state; the `?classic=1` escape hatch pins legacy
# even after the switchover flip redirects /app/notifications → /app/multiplexer).
LEGACY_FULLPAGE_PATH = "/app/notifications?classic=1"
MUX_FULLPAGE_PATH    = "/app/multiplexer"

# Chrome stylesheets BOTH pages must <link> (Tier 0 chrome CSS-source identity) —
# lupin-nav.css single-sources the top nav (the one Category-A chrome surface).
SHARED_CHROME_SHEETS = [ "lupin-nav.css", "lupin-base.css" ]

# Legacy chrome stylesheets baked into the golden as a staleness trip-wire
# (Rider-C analogue for page chrome — a content drift fails the golden → recapture).
LEGACY_CHROME_SHEET_RELPATHS = [
    "src/lupin_app/static/css/lupin-nav.css",
    "src/lupin_app/static/css/notifications.css",
    "src/lupin_app/static/css/broadcast-panel.css",
]

FULLPAGE_GOLDEN_RELPATH = "src/tests/e2e_ui/fixtures/golden/notifications-legacy-fullpage.golden.json"

# The semantic chrome-row contract: ONE row per visual surface, with the per-client
# selector written down (the §5-step-3 id-normalization the methodology mandates)
# and its parity category. `legacy` is None for a mux-native row (no reference).
CHROME_ROWS: list[ dict[ str, Any ] ] = [
    { "key": "V1-nav",       "legacy": "nav.lupin-nav",                          "mux": "nav.lupin-nav",                                "category": "A" },
    { "key": "V1-logout",    "legacy": "#logout-button",                         "mux": "#lupin-nav-mount button.lupin-nav-logout",     "category": "B" },
    { "key": "V2-env-label", "legacy": "#env-label",                             "mux": "#env-label",                                   "category": "B" },
    { "key": "V2-clock",     "legacy": "#clock",                                 "mux": "#clock",                                       "category": "B" },
    { "key": "V3-AR",        "legacy": "#action-required-section",               "mux": "#action-required-section",                     "category": "B" },
    { "key": "V3-AR-empty",  "legacy": "#action-required-empty",                 "mux": "#action-required-empty",                       "category": "B" },
    { "key": "V4-PLY",       "legacy": "#tts-queue-section",                     "mux": "#tts-pane",                                    "category": "C" },
    { "key": "V5-header",    "legacy": "#section-notifications > .section-header","mux": ".notifications-header-region",                  "category": "B" },
    { "key": "V7-broadcast", "legacy": "#broadcast-submit-card",                 "mux": "#broadcast-card-mount",                        "category": "B" },
    { "key": "V7-toggle",    "legacy": "#broadcast-submit-toggle",               "mux": "#broadcast-submit-toggle",                     "category": "B" },
    { "key": "V9-strip",     "legacy": "#cc-session-strip",                      "mux": "#cc-session-strip",                            "category": "C" },
    { "key": "V13-toolbar",  "legacy": None,                                     "mux": "#section-toolbar-mount",                       "category": "C" },
]

# V5 header boundary (Rachel's verdict, batch-merge): the mux V5 node is the header
# REGION wrapper (.notifications-header-region), NOT #notifications-header-mount
# alone. Legacy NESTS the TTS-fraction slider inside its section-header (→ 956px
# full-width); the mux SPLITS the slider to a sibling #tts-preview-slider-mount, so
# #notifications-header-mount alone reads 733px — measuring it would false-flag a
# 733-vs-956 width gap that is really just the slider relocation. The region wrapper
# spans BOTH mounts → full-width, the true parity boundary (Tier 3 asserts it).

# Rows KNOWN to be OPEN gaps in the mux. EMPTIED at the H2 batch-merge (Sam commit
# a81b2114 — env-label + live clock now render in the mux notifications header): the
# break-on-close sentinel FIRED by design, so V2-env-label + V2-clock were promoted
# from expect-ABSENT to Tier-1 present-required — that GREEN is H2's full-page proof.
# The set stays as the freshness-guard hook for any FUTURE chrome gap: add a row here
# to pin it, and Tier 1 breaks loudly the moment the mux starts rendering it.
KNOWN_OPEN_CHROME_ROWS: set[ str ] = set()

# The declarative layout property subset compared for Category-A style-iso (nav) —
# same spirit as LAYOUT_STYLE_PROPS but page-frame oriented.
CHROME_STYLE_PROPS = [
    "display", "position", "box-sizing",
    "margin-top", "margin-right", "margin-bottom", "margin-left",
    "padding-top", "padding-right", "padding-bottom", "padding-left",
    "border-bottom-width", "border-bottom-style",
    "flex-direction", "align-items", "justify-content", "gap",
    "font-family", "font-size", "font-weight", "line-height",
    "color", "background-color",
]

# Browser-side chrome walker: given the per-client resolved rows + the property set
# + the page-container selector, returns for every row its presence, computed
# display, the declarative style subset, and geometry framed BOTH absolutely (x/y —
# for the nav which lives outside .container) and container-relative (dx = inset
# from container left; cw = container width — the width-parity reference).
PAGE_CHROME_WALK_JS = r"""
( args ) => {
    const { rows, props, containerSel } = args;
    const container = document.querySelector( containerSel );
    const cRect = container ? container.getBoundingClientRect() : { left: 0, top: 0, width: 0 };
    const round1 = ( n ) => Math.round( n * 10 ) / 10;
    const out = {};
    for ( const row of rows ) {
        let el = null;
        if ( row.sel ) { try { el = document.querySelector( row.sel ); } catch ( e ) { el = null; } }
        if ( !el ) { out[ row.key ] = { present: false }; continue; }
        const cs = getComputedStyle( el );
        const r  = el.getBoundingClientRect();
        const styles = {};
        for ( const p of props ) styles[ p ] = cs.getPropertyValue( p );
        out[ row.key ] = {
            present : true,
            display : cs.getPropertyValue( "display" ),
            styles  : styles,
            geom    : {
                x  : round1( r.left ),   y  : round1( r.top ),
                w  : round1( r.width ),  h  : round1( r.height ),
                dx : round1( r.left - cRect.left ),
                cw : round1( cRect.width ),
            },
        };
    }
    return out;
}
"""


def chrome_rows_for( client: str ) -> list[ dict[ str, Any ] ]:
    """Resolve the semantic chrome contract to ONE client's selectors.

    Requires:
        - client is "legacy" or "mux"

    Ensures:
        - returns one {key, sel, category} per CHROME_ROWS entry, in order
        - sel is the client's selector for that row (None if the row has no
          equivalent on that client — e.g. the mux-native V13 toolbar on legacy)

    Raises:
        - ValueError if client is not a known client key
    """
    if client not in ( "legacy", "mux" ):
        raise ValueError( f"unknown client {client!r} — expected 'legacy' or 'mux'" )
    return [ { "key": r[ "key" ], "sel": r[ client ], "category": r[ "category" ] } for r in CHROME_ROWS ]


def fullpage_golden_path() -> Path:
    """On-disk path of the page-scoped legacy chrome golden (separate from the
    sender-card golden — never overwrite that one)."""
    return repo_root() / FULLPAGE_GOLDEN_RELPATH


def legacy_chrome_sheet_paths() -> list[ Path ]:
    """On-disk paths of the legacy chrome stylesheets hashed into the golden."""
    return [ repo_root() / rel for rel in LEGACY_CHROME_SHEET_RELPATHS ]


def chrome_css_hashes() -> dict[ str, str ]:
    """Map of {basename: 12-char content hash} for every legacy chrome sheet —
    the golden's page-chrome staleness trip-wire reference."""
    return { p.name: content_hash( p ) for p in legacy_chrome_sheet_paths() }


def links_stylesheet( html_text: str, css_basename: str ) -> bool:
    """True iff html_text has a <link> href referencing css_basename (tolerant of
    any directory prefix AND a ?v=... cache-buster suffix)."""
    pattern = re.compile( r'href="[^"]*' + re.escape( css_basename ) + r'[^"?]*(?:\?[^"]*)?"' )
    return pattern.search( html_text ) is not None


def fullpage_golden_is_stale( golden: dict[ str, Any ] ) -> bool:
    """True iff any legacy chrome sheet hashed into the golden has drifted from the
    live on-disk bytes — the golden must be recaptured before Tier 2/3 trust it."""
    return golden.get( "css_hashes" ) != chrome_css_hashes()

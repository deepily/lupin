#!/usr/bin/env python3
"""
Phase-2 / WS3 — A/B visual-comparison report ("how far we've come" snapshot).

Rick's 2026-06-30 ask: "double back and re-run the process with A/B visual
comparison." This is the AUTOMATED layer of that ask (the roadmap's "A/B
visual-comparison design", src/rnd/v0.1.9/2026.06.30-mux-switchover-mvp-finish-
roadmap.md §"A/B visual-comparison design", layer 1). The SUBJECTIVE layer
(Rick's Chrome) is the one EXECUTOR:HUMAN tier this defers.

WHAT IT DOES
------------
Drives BOTH clients from the ONE canonical layout-parity scenario
(fixtures/notifications-parity-scenario.json) via the SAME parityFixture.ts
adapters the oracle uses (single-source — any delta is CSS/DOM, never data):

  legacy  →  /app/notifications?classic=1   (root #notifications-list)
  mux     →  /app/multiplexer                (root #sender-cards-container)

For each client it (a) route-stubs senders-visible + conversation-by-date from
the adapter shapes, (b) captures a tight element screenshot of the card stack +
a full-page context screenshot, and (c) injects the SAME CONTRACT_STYLE_GEOM
walker the oracle Tier 2/3 use (parity_oracle.CONTRACT_STYLE_GEOM_JS) for a
node-by-node computed-style + intra-card-geometry capture. It then DIFFS the two
node maps and emits a side-by-side HTML report + a JSON artifact.

This is a MEASUREMENT snapshot, NOT a pass/fail gate (the oracle tiers are the
gate — test_tier0/1, test_tier2_tier3). Expect real deltas: B5 has not yet
single-sourced the CSS, so rules that live only in the legacy notifications.css
monolith do not reach the mux (which links only the shared sheet). The report's
job is to MEASURE and CLASSIFY the residual node-by-node, tagging each delta:

  [STRUCTURAL]    a contract node present on one side, absent on the other
                  (DOM, not CSS — B5 will NOT close it; needs eyes).
  [B5-CANDIDATE]  a computed-style divergence — a CSS-cascade gap that B5's
                  single-source MOVE is expected to close (re-run post-B5 to
                  confirm).
  [GENUINE-DRIFT] an intra-card geometry divergence (>1px) with NO style delta
                  on that node — declared styles agree but the box renders
                  differently, so it is NOT a pure rule-location issue and
                  warrants a human look.

Card WIDTH context: legacy renders the card in the full notifications page; the
mux renders it inside #notifications-pane — different pane widths. To isolate
intra-card layout from pane-width cascade (exactly as oracle Tier 3 does), the
mux cards are normalized to the legacy card widths before the geometry capture;
the raw card-width delta is reported once, separately, as expected context.

VENUE: :7999 (dev) — read-only, fully route-stubbed, < 2 min → AI-discretionary
per CLAUDE.md §TESTING VENUES. Override the base URL for a :8000 run.

USAGE
-----
    # bundles fresh first (dist/ is gitignored):
    bash src/scripts/build-parity-harness.sh
    bash src/scripts/build-multiplexer.sh

    # credentials (CLAUDE.md §TEST CREDENTIALS):
    export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL=...
    export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD=...

    PYTHONPATH=src python src/tests/parity_oracle/ab_visual_report.py
    # → writes src/rnd/v0.1.9/ab-visual-report/<timestamp>/{report.html,report.json,*.png}

    # against the :8000 test server:
    LUPIN_TEST_BASE_URL=http://localhost:8000 \
        PYTHONPATH=src python src/tests/parity_oracle/ab_visual_report.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

# Bootstrap exception (CLAUDE.md §PATH MANAGEMENT): this script may run before
# cosa is importable, so seed sys.path from LUPIN_ROOT, then use cu thereafter.
_lupin_root = os.environ.get( "LUPIN_ROOT" )
if _lupin_root is not None:
    _src = os.path.join( _lupin_root, "src" )
    if _src not in sys.path: sys.path.insert( 0, _src )

from tests.e2e_ui.parity_oracle import (   # noqa: E402
    CONTRACT_STYLE_GEOM_JS,
    HARNESS_URL_PATH,
    LAYOUT_STYLE_PROPS,
    load_scenario,
    repo_root,
)

# Supplementary walker: the B4 per-message corner controls (⏸/⏹) are NOT in the
# contract-skeleton walker's node set (CONTRACT_STYLE_GEOM_JS walks card / header /
# accordion / message / text / time only), so their gate state is invisible to a
# pure style/geom diff — yet an UN-gated corner button reserves ~57px in the
# message flex row and shrinks the flex:1 `.message-text`, which surfaces ONLY as
# a message-text WIDTH geometry delta with no captured style delta. This walker
# captures, per message (keyed identically to CONTRACT_STYLE_GEOM_JS so the keys
# align), whether any corner control renders visible (display != none). A mux-
# visible / legacy-hidden divergence is the B5 corner-control-gate gap (the gate
# `.notification-corner-pause-btn{display:none}` + `.tts-playing` reveal lives in
# notifications.css:381-501, monolith-only; legacy links it, mux links only the
# shared sheet → B5 MOVES it so the mux hides them too).
CORNER_GATE_JS = r"""
( rootSel ) => {
    const root = document.querySelector( rootSel );
    if ( !root ) return null;
    const round1 = ( n ) => Math.round( n * 10 ) / 10;
    const cards = [ ...root.querySelectorAll( ':scope > .sender-card' ) ]
        .sort( ( a, b ) => ( a.getAttribute( 'data-sender-id' ) || '' )
            .localeCompare( b.getAttribute( 'data-sender-id' ) || '' ) );
    const out = {};
    for ( const card of cards ) {
        const sid = card.getAttribute( 'data-sender-id' );
        const msgs = [ ...card.querySelectorAll( '.sender-message' ) ];
        msgs.forEach( ( m, i ) => {
            const btns = [ ...m.querySelectorAll(
                '.notification-corner-pause-btn, .notification-corner-stop-btn' ) ];
            let visible = 0, reserved = 0;
            for ( const b of btns ) {
                const cs = getComputedStyle( b );
                if ( cs.display !== 'none' && cs.visibility !== 'hidden' ) {
                    visible += 1;
                    reserved += b.getBoundingClientRect().width;
                }
            }
            out[ `card:${sid}>msg[${i}]` ] = {
                button_count : btns.length,
                visible      : visible,
                reserved_px  : round1( reserved ),
            };
        } );
    }
    return out;
}
"""

BASE_URL    = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:7999" )
HARNESS_URL = f"{BASE_URL}{HARNESS_URL_PATH}"
LEGACY_URL  = f"{BASE_URL}/app/notifications?classic=1"
MUX_URL     = f"{BASE_URL}/app/multiplexer"

# Contract-subtree roots (per parity_oracle: legacy cards live under
# #notifications-list, mux cards under #sender-cards-container).
LEGACY_ROOT = "#notifications-list"
MUX_ROOT    = "#sender-cards-container"

GEOM_TOL_PX = 1.0   # Doc 01 Tier 3 tolerance — same as the oracle.

# Deterministic-font Chromium launch args (mirror e2e_ui + parity_oracle conftests).
LAUNCH_ARGS = [
    "--font-render-hinting=none",
    "--disable-lcd-text",
    "--force-color-profile=srgb",
    "--force-device-scale-factor=1",
]
# 1280x720 viewport pin (e2e_ui conftest — bug 99326963; width is load-bearing).
VIEWPORT = { "width": 1280, "height": 720 }


# ---------------------------------------------------------------------------
# Auth + adapter shapes
# ---------------------------------------------------------------------------

def _login() -> tuple[ str, str ]:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        raise SystemExit(
            "Set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and "
            "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD (CLAUDE.md §TEST CREDENTIALS)."
        )
    resp = requests.post(
        f"{BASE_URL}/auth/login", json={ "email": email, "password": password }, timeout=10,
    )
    if resp.status_code != 200:
        raise SystemExit( f"login failed: {resp.status_code} {resp.text}" )
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ]


def _adapter_shapes( page ) -> dict:
    """Compute the legacy/shared REST stub bodies via the SAME TS adapter both
    clients render from (parityFixture.toSendersVisible + toConversationByDate)."""
    page.goto( HARNESS_URL, wait_until="networkidle", timeout=20_000 )
    page.wait_for_function(
        "() => window.__parityHarnessReady === true && typeof window.__parityLegacyShapes === 'function'",
        timeout=10_000,
    )
    return page.evaluate( "( s ) => window.__parityLegacyShapes( s )", load_scenario() )


def _recency_bump( shapes: dict ) -> str:
    """Bump every senders-visible row's `last_activity` to NOW (identically for
    BOTH clients) so the mux boot's 48h rolling-window gate
    (NotificationStore.hydrateHistory, DEFAULT_HISTORY_WINDOW_HOURS=48) does not
    drop the canonical fixture (dated 2026-06-20, > 48h old) BEFORE the per-sender
    conversation-by-date fetch. Legacy applies no such gate, so bumping it is a
    no-op there; bumping BOTH identically keeps legacy==mux input. Only the
    sender META date moves — the conversation-by-date ROWS keep the canonical
    fixed timestamps, so card layout + date-accordion grouping (what the oracle
    measures) is unchanged. Returns the bumped ISO timestamp for the report."""
    now_iso = datetime.now( timezone.utc ).isoformat()
    for row in shapes[ "sendersVisible" ]:
        row[ "last_activity" ] = now_iso
    return now_iso


def _install_stubs( page, shapes: dict ):
    """Route-stub senders-visible + conversation-by-date — the ONE hydration path
    BOTH clients share (legacy loadDateGrouped…; mux NotificationStore.hydrateHistory)."""
    senders_visible      = shapes[ "sendersVisible" ]
    conversation_by_date = shapes[ "conversationByDate" ]

    def _senders( route ):
        route.fulfill( status=200, content_type="application/json", body=json.dumps( senders_visible ) )

    def _conversation( route ):
        url  = route.request.url
        body: dict = {}
        for sender_id, payload in conversation_by_date.items():
            quoted = requests.utils.quote( sender_id, safe="" )
            if f"conversation-by-date/{quoted}/" in url or f"conversation-by-date/{sender_id}/" in url:
                body = payload
                break
        route.fulfill( status=200, content_type="application/json", body=json.dumps( body ) )

    page.route( "**/api/notifications/senders-visible/**", _senders )
    page.route( "**/api/notifications/conversation-by-date/**", _conversation )


# ---------------------------------------------------------------------------
# Per-client capture
# ---------------------------------------------------------------------------

def _capture( context, *, url: str, root: str, access: str, refresh: str,
              ready_js: str, out_dir: Path, tag: str,
              card_widths: dict[ str, float ] | None,
              prep_js: str | None = None, prep_wait_js: str | None = None ) -> dict:
    """Open a client, hydrate from the stubs, screenshot the card stack + the
    full page, and capture the contract node map. If `prep_js` is given it runs
    after the first card paints (e.g. neutralize the mux's default filter), then
    waits on `prep_wait_js`. If `card_widths` is given, normalize each card to
    that width (mux side → legacy width) so intra-card geometry is comparable
    across different pane widths."""
    page = context.new_page()
    page.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', {json.dumps( access )});"
        f"window.localStorage.setItem('lupin_refresh_token', {json.dumps( refresh )});"
    )
    shapes = _adapter_shapes_cache[ "shapes" ]
    _install_stubs( page, shapes )

    page.goto( url, wait_until="networkidle", timeout=25_000 )
    page.wait_for_function( ready_js, timeout=15_000 )
    page.wait_for_selector( f"{root} .sender-card", timeout=15_000 )

    if prep_js:
        page.evaluate( prep_js )
        if prep_wait_js:
            page.wait_for_function( prep_wait_js, timeout=10_000 )

    if card_widths:
        page.evaluate(
            """( args ) => {
                const { root, widths } = args;
                for ( const card of document.querySelectorAll( `${root} .sender-card` ) ) {
                    const w = widths[ card.getAttribute( 'data-sender-id' ) ];
                    if ( w ) { card.style.boxSizing = 'border-box'; card.style.width = w + 'px'; }
                }
            }""",
            { "root": root, "widths": card_widths },
        )

    cards_png = out_dir / f"{tag}-cards.png"
    full_png  = out_dir / f"{tag}-full.png"
    page.locator( root ).screenshot( path=str( cards_png ) )
    page.screenshot( path=str( full_png ), full_page=True )

    node_list = page.evaluate(
        CONTRACT_STYLE_GEOM_JS, { "rootSel": root, "props": LAYOUT_STYLE_PROPS },
    )[ "nodes" ]
    corner = page.evaluate( CORNER_GATE_JS, root ) or {}
    page.close()
    return {
        "nodes"     : { n[ "key" ]: n for n in node_list },
        "corner"    : corner,
        "cards_png" : cards_png.name,
        "full_png"  : full_png.name,
    }


def _card_widths( nodes: dict ) -> dict[ str, float ]:
    """The per-card width of every top-level card node (key `card:<sid>`)."""
    out: dict[ str, float ] = {}
    for key, node in nodes.items():
        if key.startswith( "card:" ) and ">" not in key:
            out[ key[ len( "card:" ): ] ] = node[ "geom" ][ "w" ]
    return out


_adapter_shapes_cache: dict = {}


# ---------------------------------------------------------------------------
# Diff + classify
# ---------------------------------------------------------------------------

def _card_of( key: str ) -> str | None:
    """The `card:<sid>` of a contract-node key (the sid up to the first `>`)."""
    if not key.startswith( "card:" ):
        return None
    return key.split( ">", 1 )[ 0 ]


def _message_prefix( key: str ) -> str | None:
    """The `card:<sid>>msg[<i>]` prefix of a contract-node key (or None)."""
    if ">msg[" not in key:
        return None
    head, _sep, _tail = key.partition( ">msg[" )
    idx, _b, _rest = _tail.partition( "]" )
    return f"{head}>msg[{idx}]"


def _corner_gate( legacy_corner: dict, mux_corner: dict ) -> tuple[ list, set, set ]:
    """Per-message corner-control gate divergence. Returns (rows, affected_msgs,
    affected_cards) where `affected_msgs` is the set of `card:sid>msg[i]` prefixes
    whose mux render shows MORE visible corner buttons than legacy (the B5 gate
    gap — gate CSS is monolith-only; mux links only the shared sheet), and
    `affected_cards` is the set of `card:sid` those messages belong to (for the
    container vertical cascade: taller wrapped text grows the messages well +
    the card height)."""
    rows: list[ dict ] = []
    affected_msgs:  set = set()
    affected_cards: set = set()
    for key in sorted( set( legacy_corner ) & set( mux_corner ) ):
        lg, mg = legacy_corner[ key ], mux_corner[ key ]
        if mg[ "visible" ] != lg[ "visible" ] or mg[ "reserved_px" ] != lg[ "reserved_px" ]:
            rows.append( {
                "key"          : key,
                "legacy_visible": lg[ "visible" ], "mux_visible": mg[ "visible" ],
                "legacy_px"    : lg[ "reserved_px" ], "mux_px": mg[ "reserved_px" ],
            } )
            if mg[ "visible" ] > lg[ "visible" ]:
                affected_msgs.add( key )
                card = _card_of( key )
                if card is not None:
                    affected_cards.add( card )
    return rows, affected_msgs, affected_cards


def _diff( legacy_cap: dict, mux_cap: dict ) -> dict:
    """Build the classified delta set across the two node maps + the corner-gate
    supplementary capture."""
    legacy, mux = legacy_cap[ "nodes" ], mux_cap[ "nodes" ]
    corner_rows, gate_affected, gate_cards = _corner_gate(
        legacy_cap.get( "corner", {} ), mux_cap.get( "corner", {} ),
    )

    legacy_keys = set( legacy )
    mux_keys    = set( mux )
    common      = sorted( legacy_keys & mux_keys )

    structural: list[ dict ] = []
    for key in sorted( legacy_keys - mux_keys ):
        structural.append( { "key": key, "side": "legacy-only" } )
    for key in sorted( mux_keys - legacy_keys ):
        structural.append( { "key": key, "side": "mux-only" } )

    style_deltas: list[ dict ] = []   # [B5-CANDIDATE]
    geom_drift:   list[ dict ] = []   # [B5-CANDIDATE | GENUINE-DRIFT]
    width_ctx:    list[ dict ] = []   # informational pane-width context

    for key in common:
        lg, mg = legacy[ key ], mux[ key ]

        node_style_props: list[ str ] = []
        for prop in LAYOUT_STYLE_PROPS:
            lv, mv = lg[ "styles" ].get( prop ), mg[ "styles" ].get( prop )
            if lv != mv:
                node_style_props.append( prop )
                style_deltas.append( { "key": key, "prop": prop, "legacy": lv, "mux": mv } )

        node_has_style_delta = bool( node_style_props )
        is_top_card          = key.startswith( "card:" ) and ">" not in key
        # A node is corner-gate-explained if it (or its parent message) belongs to
        # a message whose mux render shows un-gated corner buttons. That reserves
        # flex width → shrinks .message-text → the message wraps taller, cascading
        # into the message's own vertical offsets AND its containers' heights (the
        # messages well + the card). All of it closes when B5 moves the gate.
        in_gate_msg          = _message_prefix( key ) in gate_affected
        # A CONTAINER whose HEIGHT genuinely grows when its messages wrap taller:
        # the top-level card, or a date-accordion messages well. (NOT the header /
        # date-text — those sit ABOVE the messages and cannot be pushed by them.)
        is_msg_container     = is_top_card or key.endswith( ">messages" )
        card_gate_affected   = _card_of( key ) in gate_cards

        for axis in ( "dx", "dy", "w", "h" ):
            d = abs( lg[ "geom" ][ axis ] - mg[ "geom" ][ axis ] )
            if d <= GEOM_TOL_PX:
                continue
            row = { "key": key, "axis": axis,
                    "legacy": lg[ "geom" ][ axis ], "mux": mg[ "geom" ][ axis ],
                    "delta": round( d, 1 ) }
            if is_top_card and axis == "w":
                # Top-level card width delta — pane-width context (mux normalized
                # to legacy). Informational unless the card itself is gate-affected.
                width_ctx.append( row )
            elif node_has_style_delta:
                geom_drift.append( { **row, "cause": "style", "classification": "B5-CANDIDATE" } )
            elif in_gate_msg:
                geom_drift.append( { **row, "cause": "corner-gate", "classification": "B5-CANDIDATE" } )
            elif card_gate_affected and is_msg_container and axis == "h":
                # Container HEIGHT delta within a gate-affected card — the
                # messages-well / card height grows as the un-gated-button messages
                # wrap taller. Closes with B5.
                geom_drift.append( { **row, "cause": "corner-gate-cascade", "classification": "B5-CANDIDATE" } )
            else:
                geom_drift.append( { **row, "cause": "none", "classification": "GENUINE-DRIFT" } )

    return {
        "node_counts" : { "legacy": len( legacy ), "mux": len( mux ), "common": len( common ) },
        "structural"  : structural,
        "style_deltas": style_deltas,
        "geom_drift"  : geom_drift,
        "width_ctx"   : width_ctx,
        "corner_gate" : corner_rows,
        "corner_gate_affected_count": len( gate_affected ),
    }


# ---------------------------------------------------------------------------
# Report emit
# ---------------------------------------------------------------------------

def _summary_counts( diff: dict ) -> dict:
    genuine = [ g for g in diff[ "geom_drift" ] if g[ "classification" ] == "GENUINE-DRIFT" ]
    b5_geom = [ g for g in diff[ "geom_drift" ] if g[ "classification" ] == "B5-CANDIDATE" ]
    return {
        "structural"     : len( diff[ "structural" ] ),
        "b5_candidate"   : len( diff[ "style_deltas" ] ) + len( b5_geom ),
        "genuine_drift"  : len( genuine ),
        "width_context"  : len( diff[ "width_ctx" ] ),
        "style_deltas"   : len( diff[ "style_deltas" ] ),
        "geom_b5"        : len( b5_geom ),
        "geom_genuine"   : len( genuine ),
        "corner_gate"    : len( diff.get( "corner_gate", [] ) ),
    }


def _html_report( diff: dict, legacy_cap: dict, mux_cap: dict, meta: dict ) -> str:
    s = _summary_counts( diff )

    def _rows_struct() -> str:
        if not diff[ "structural" ]:
            return "<tr><td colspan='2'><em>none — every contract node aligns</em></td></tr>"
        return "".join(
            f"<tr><td><code>{escape( r['key'] )}</code></td><td>{escape( r['side'] )}</td></tr>"
            for r in diff[ "structural" ]
        )

    def _rows_style() -> str:
        if not diff[ "style_deltas" ]:
            return "<tr><td colspan='4'><em>none — full computed-style isomorphism</em></td></tr>"
        return "".join(
            f"<tr><td><code>{escape( r['key'] )}</code></td><td><code>{escape( r['prop'] )}</code></td>"
            f"<td>{escape( str( r['legacy'] ) )}</td><td>{escape( str( r['mux'] ) )}</td></tr>"
            for r in diff[ "style_deltas" ]
        )

    def _rows_geom( classification: str ) -> str:
        rows = [ g for g in diff[ "geom_drift" ] if g[ "classification" ] == classification ]
        if not rows:
            return "<tr><td colspan='5'><em>none</em></td></tr>"
        return "".join(
            f"<tr><td><code>{escape( r['key'] )}</code></td><td>{escape( r['axis'] )}</td>"
            f"<td>legacy {r['legacy']} · mux {r['mux']}</td><td>Δ{r['delta']}px</td>"
            f"<td>{escape( r.get( 'cause', '' ) )}</td></tr>"
            for r in rows
        )

    def _rows_corner() -> str:
        rows = diff.get( "corner_gate", [] )
        if not rows:
            return "<tr><td colspan='3'><em>none — corner controls gated identically on both</em></td></tr>"
        return "".join(
            f"<tr><td><code>{escape( r['key'] )}</code></td>"
            f"<td>legacy {r['legacy_visible']} vis ({r['legacy_px']}px) · "
            f"mux {r['mux_visible']} vis ({r['mux_px']}px)</td>"
            f"<td>{'mux un-gated → B5 MOVE closes' if r['mux_visible'] > r['legacy_visible'] else 'review'}</td></tr>"
            for r in rows
        )

    def _rows_width() -> str:
        if not diff[ "width_ctx" ]:
            return "<tr><td colspan='3'><em>none — card widths matched after normalization</em></td></tr>"
        return "".join(
            f"<tr><td><code>{escape( r['key'] )}</code></td>"
            f"<td>legacy {r['legacy']} · mux {r['mux']}</td><td>Δ{r['delta']}px</td></tr>"
            for r in diff[ "width_ctx" ]
        )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Mux ↔ Legacy A/B visual-parity report</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; color: #1a1a1a; }}
  h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; margin-top: 28px; border-bottom: 2px solid #eee; padding-bottom: 4px; }}
  .meta {{ color: #555; font-size: 13px; }}
  .cards {{ display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap; }}
  .cards figure {{ margin: 0; flex: 1 1 380px; }}
  .cards img {{ width: 100%; border: 1px solid #ccc; border-radius: 6px; }}
  figcaption {{ font-weight: 600; margin-bottom: 6px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 12px; margin-top: 8px; }}
  th, td {{ border: 1px solid #ddd; padding: 4px 8px; text-align: left; vertical-align: top; }}
  th {{ background: #f5f5f5; }} code {{ font-size: 11px; }}
  .pill {{ display: inline-block; padding: 2px 9px; border-radius: 11px; font-size: 12px; font-weight: 600; margin-right: 6px; }}
  .p-struct {{ background: #ffe0e0; color: #a00; }}
  .p-b5 {{ background: #fff3cd; color: #8a6d00; }}
  .p-drift {{ background: #ffd9b3; color: #a04000; }}
  .p-ok {{ background: #d6f5d6; color: #0a6b0a; }}
  .p-ctx {{ background: #e6e6e6; color: #444; }}
  .legend {{ font-size: 12.5px; line-height: 1.7; }}
</style></head><body>

<h1>Multiplexer ↔ Legacy — A/B visual-parity snapshot</h1>
<p class="meta">
  Generated for Rick's "how far we've come" review (Phase-2, v0.1.9).<br>
  legacy: <code>{escape( meta['legacy_url'] )}</code> &nbsp;·&nbsp; mux: <code>{escape( meta['mux_url'] )}</code><br>
  one canonical scenario via <code>parityFixture.ts</code> · viewport {meta['viewport']['width']}×{meta['viewport']['height']}
  · deterministic-font · geometry tol ±{GEOM_TOL_PX:g}px · mux cards normalized to legacy width.<br>
  <strong>This is a MEASUREMENT snapshot, not a pass/fail gate.</strong> B5 has not yet single-sourced the CSS.
</p>

<h2>Harness adaptations (read first)</h2>
<ul class="legend">
  {"".join( f"<li>{escape( note )}</li>" for note in meta['harness_notes'] )}
</ul>

<h2>Summary</h2>
<p>
  <span class="pill p-struct">{s['structural']} structural</span>
  <span class="pill p-b5">{s['b5_candidate']} B5-candidate</span>
  <span class="pill p-drift">{s['genuine_drift']} genuine-drift</span>
  <span class="pill p-ctx">{s['width_context']} width-context</span>
</p>
<p class="legend">
  <span class="pill p-struct">STRUCTURAL</span> contract node present on one side only — DOM, not CSS; B5 will NOT close it; needs eyes.<br>
  <span class="pill p-b5">B5-CANDIDATE</span> computed-style divergence (and geometry that follows from it) — a CSS-cascade gap B5's single-source MOVE is expected to close; re-run post-B5 to confirm.<br>
  <span class="pill p-drift">GENUINE-DRIFT</span> intra-card geometry &gt;{GEOM_TOL_PX:g}px with NO style delta on the node — declared styles agree but the box renders differently; not a pure rule-location issue.<br>
  <span class="pill p-ctx">WIDTH-CONTEXT</span> top-level card width delta — pane-width context (mux normalized to legacy); informational, not a parity defect.
</p>

<h2>Side-by-side — notification card stack</h2>
<div class="cards">
  <figure><figcaption>Legacy ({LEGACY_ROOT})</figcaption><img src="{escape( legacy_cap['cards_png'] )}" alt="legacy cards"></figure>
  <figure><figcaption>Multiplexer ({MUX_ROOT})</figcaption><img src="{escape( mux_cap['cards_png'] )}" alt="mux cards"></figure>
</div>

<h2>Full-page context</h2>
<div class="cards">
  <figure><figcaption>Legacy — full notifications page</figcaption><img src="{escape( legacy_cap['full_png'] )}" alt="legacy full"></figure>
  <figure><figcaption>Multiplexer — full page</figcaption><img src="{escape( mux_cap['full_png'] )}" alt="mux full"></figure>
</div>

<h2><span class="pill p-struct">STRUCTURAL</span> node presence ({s['structural']})</h2>
<table><tr><th>node key</th><th>present on</th></tr>{_rows_struct()}</table>

<h2><span class="pill p-b5">B5-CANDIDATE</span> computed-style divergence ({s['style_deltas']})</h2>
<table><tr><th>node key</th><th>property</th><th>legacy</th><th>mux</th></tr>{_rows_style()}</table>

<h2><span class="pill p-b5">B5-CANDIDATE</span> corner-control gate gap ({s['corner_gate']})</h2>
<p class="legend">B4 renders ⏸/⏹ corner controls into every message; the gate that hides them by
default (<code>.notification-corner-pause-btn{{display:none}}</code> + the <code>.tts-playing</code> reveal)
lives in <code>notifications.css:381-501</code> — the legacy monolith ONLY. Legacy links it (buttons hidden);
the mux links only the shared sheet (no gate → buttons visible, reserving flex width → <code>.message-text</code>
shrinks → vertical cascade). <strong>B5 MOVES this gate into the shared sheet → the mux hides them too and
every geometry delta below closes.</strong></p>
<table><tr><th>message</th><th>corner controls visible</th><th>verdict</th></tr>{_rows_corner()}</table>

<h2><span class="pill p-b5">B5-CANDIDATE</span> geometry caused by a style / corner-gate delta ({s['geom_b5']})</h2>
<table><tr><th>node key</th><th>axis</th><th>values</th><th>Δ</th><th>cause</th></tr>{_rows_geom( 'B5-CANDIDATE' )}</table>

<h2><span class="pill p-drift">GENUINE-DRIFT</span> geometry without a style or corner-gate cause ({s['geom_genuine']})</h2>
<table><tr><th>node key</th><th>axis</th><th>values</th><th>Δ</th><th>cause</th></tr>{_rows_geom( 'GENUINE-DRIFT' )}</table>

<h2><span class="pill p-ctx">WIDTH-CONTEXT</span> card-width delta ({s['width_context']})</h2>
<table><tr><th>node key</th><th>values</th><th>Δ</th></tr>{_rows_width()}</table>

<p class="meta">Node counts — legacy {diff['node_counts']['legacy']} · mux {diff['node_counts']['mux']} · aligned {diff['node_counts']['common']}.</p>
</body></html>
"""


def _console_summary( diff: dict, report_path: Path ):
    s = _summary_counts( diff )
    print( "\n" + "=" * 64 )
    print( "  A/B VISUAL-PARITY SNAPSHOT — mux ↔ legacy" )
    print( "=" * 64 )
    print( f"  {'category':<22}{'count':>8}   meaning" )
    print( "  " + "-" * 60 )
    print( f"  {'STRUCTURAL':<22}{s['structural']:>8}   DOM node present one side only" )
    print( f"  {'B5-CANDIDATE':<22}{s['b5_candidate']:>8}   CSS gap B5 single-source should close" )
    print( f"  {'  ├─ style deltas':<22}{s['style_deltas']:>8}   computed-style divergence" )
    print( f"  {'  └─ geom (caused)':<22}{s['geom_b5']:>8}   geometry from style/corner-gate cause" )
    print( f"  {'corner-gate msgs':<22}{s['corner_gate']:>8}   messages w/ un-gated mux corner ctrls" )
    print( f"  {'GENUINE-DRIFT':<22}{s['genuine_drift']:>8}   geom >1px, NO known cause — needs eyes" )
    print( f"  {'WIDTH-CONTEXT':<22}{s['width_context']:>8}   pane-width context (informational)" )
    print( "  " + "-" * 60 )
    print( f"  nodes: legacy {diff['node_counts']['legacy']} · mux {diff['node_counts']['mux']} · aligned {diff['node_counts']['common']}" )
    print( f"\n  report → {report_path}" )
    print( "=" * 64 + "\n" )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run( out_root: Path ) -> Path:
    out_root.mkdir( parents=True, exist_ok=True )
    access, refresh = _login()

    with sync_playwright() as p:
        browser = p.chromium.launch( args=LAUNCH_ARGS )
        context = browser.new_context( viewport=VIEWPORT, device_scale_factor=1 )

        # Compute the shared adapter shapes ONCE (via the TS adapter on the harness).
        shapes_page = context.new_page()
        shapes = _adapter_shapes( shapes_page )
        shapes_page.close()
        # Recency-bump the sender meta so the mux's 48h window gate passes (rows
        # keep canonical dates — see _recency_bump).
        bumped_iso = _recency_bump( shapes )
        _adapter_shapes_cache[ "shapes" ] = shapes

        legacy_cap = _capture(
            context, url=LEGACY_URL, root=LEGACY_ROOT, access=access, refresh=refresh,
            ready_js=f"() => document.querySelector( '{LEGACY_ROOT} .sender-card' ) !== null",
            out_dir=out_root, tag="legacy", card_widths=None,
        )
        # Normalize the mux cards to the legacy widths (isolate intra-card layout).
        legacy_widths = _card_widths( legacy_cap[ "nodes" ] )
        mux_cap = _capture(
            context, url=MUX_URL, root=MUX_ROOT, access=access, refresh=refresh,
            ready_js="() => window.__multiplexerTestHook !== undefined "
                     f"&& document.querySelector( '{MUX_ROOT} .sender-card' ) !== null",
            out_dir=out_root, tag="mux", card_widths=legacy_widths,
            # Neutralize the B3 default notification filter (mode='own', which
            # hides OUTGOING sent-reply bubbles — matchesNotificationFilter) so the
            # LAYOUT comparison runs on content equal to legacy. Wait for the
            # outgoing bubble to (re-)render before capture. Axis is frozen pending
            # Rick's ruling — surfaced as a harness note, not a layout delta.
            prep_js="() => window.__multiplexerTestHook.stores.notifications.setFilterMode( 'all' )",
            prep_wait_js=f"() => document.querySelector( '{MUX_ROOT} .sender-message.outgoing' ) !== null",
        )
        browser.close()

    diff = _diff( legacy_cap, mux_cap )
    meta = {
        "legacy_url": LEGACY_URL, "mux_url": MUX_URL,
        "viewport": VIEWPORT, "geom_tol_px": GEOM_TOL_PX,
        "sender_last_activity_bumped_to": bumped_iso,
        "harness_notes": [
            "Sender meta `last_activity` bumped to NOW (both clients identically) so the mux "
            "boot 48h rolling-window gate (hydrateHistory) does not drop the canonical fixture "
            "(dated 2026-06-20). Conversation rows keep canonical dates → card layout unchanged.",
            "Mux filter set to mode='all' before capture. The B3 default mode='own' "
            "(matchesNotificationFilter) HIDES outgoing sent-reply bubbles, which would make "
            "the mux render 4 messages vs legacy's 5 and poison positional alignment. The "
            "filter AXIS is frozen pending Rick's ruling — neutralized here so the comparison "
            "is layout-on-equal-content, not a filter-content difference.",
        ],
    }

    json_path = out_root / "report.json"
    json_path.write_text( json.dumps( {
        "meta": meta, "summary": _summary_counts( diff ), "diff": diff,
        "screenshots": {
            "legacy": { "cards": legacy_cap[ "cards_png" ], "full": legacy_cap[ "full_png" ] },
            "mux":    { "cards": mux_cap[ "cards_png" ],    "full": mux_cap[ "full_png" ] },
        },
    }, indent=2 ) + "\n" )

    report_path = out_root / "report.html"
    report_path.write_text( _html_report( diff, legacy_cap, mux_cap, meta ) )

    _console_summary( diff, report_path )
    return report_path


def main():
    ap = argparse.ArgumentParser( description="A/B visual-parity report — mux vs legacy." )
    ap.add_argument( "--stamp", default="latest",
                     help="output sub-dir name under src/rnd/v0.1.9/ab-visual-report/ (default: latest)" )
    args = ap.parse_args()
    out_root = repo_root() / "src" / "rnd" / "v0.1.9" / "ab-visual-report" / args.stamp
    run( out_root )


if __name__ == "__main__":
    main()

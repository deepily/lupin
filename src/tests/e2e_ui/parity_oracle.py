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

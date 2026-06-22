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
import re
from pathlib import Path

import cosa.utils.util as cu

# Expected home of WS1's single-source contract sheet (Doc 01 Pillar 1, S2).
SHARED_SHEET_RELPATH = "src/lupin_app/static/css/shared/notifications-surface.css"

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

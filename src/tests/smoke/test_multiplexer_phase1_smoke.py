#!/usr/bin/env python3
"""
Phase 1 acceptance smoke for the multiplexer notifications UI rebuild.

Verifies all 7 acceptance criteria from
src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/02-phase1-scaffolding-design.md:

  AC1  curl GET /app/multiplexer returns 200 + text/html
  AC2  build script emits boot.<hash>.js + boot.js with non-zero size
  AC3  --watch mode starts and exits cleanly on SIGINT
  AC4  Playwright headless: document.title === "Multiplexer", body element,
       console contains "hello multiplexer"
  AC5  tsc --noEmit -p tsconfig.json exits 0
  AC6  eslint exits 0
  AC7  /app/admin/dev-tools contains a "Multiplexer (next-gen)" card whose
       href is /app/multiplexer (markup-level verification — does NOT trigger
       client-side requireAdmin gate)

Venue: :7999 (AI-discretionary). Non-destructive, fast, read-only.

Usage:
    pytest src/tests/smoke/test_multiplexer_phase1_smoke.py -v
    LUPIN_API_URL=http://localhost:7999 pytest src/tests/smoke/test_multiplexer_phase1_smoke.py -v
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from pathlib import Path

import pytest

from tests.smoke.multiplexer_auth import seed_multiplexer_auth
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )

# Resolve project root from this file's location (src/tests/smoke/<file>.py → ../../..).
PROJECT_ROOT = Path( __file__ ).resolve().parents[ 3 ]

DIST_DIR     = PROJECT_ROOT / "src/lupin_app/static/dist/multiplexer"
BUILD_SCRIPT = PROJECT_ROOT / "src/scripts/build-multiplexer.sh"
TSCONFIG     = PROJECT_ROOT / "tsconfig.json"
MULTIPLEXER_DIR = PROJECT_ROOT / "src/lupin_app/static/js/multiplexer"


# ---------------------------------------------------------------------------
# AC1 — Route smoke
# ---------------------------------------------------------------------------

def test_ac1_route_returns_200_html():
    """
    GET /app/multiplexer -> 200 + text/html (HEAD returns 405 by FastAPI convention).

    Boot-tag assertion refreshed 2026-08-26: commit 53fef419 replaced the static
    `<script src=".../boot.js">` tag with a manifest-driven inline ES module that
    fetches manifest.json, resolves the content-hashed bundle name and imports it
    (falling back to the stable boot.js on any manifest failure). The old literal
    is genuinely absent from the served HTML, so the test now asserts the two
    strings the current boot path actually emits.
    """
    resp = requests.get( f"{BASE_URL}/app/multiplexer", timeout=10 )
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}"
    assert resp.headers.get( "content-type", "" ).startswith( "text/html" )
    assert "<h1>Multiplexer</h1>" in resp.text
    assert '<script type="module">'                          in resp.text
    assert '"/static/dist/multiplexer/"'                      in resp.text
    assert 'DIST_BASE + "manifest.json"'                      in resp.text
    assert 'DIST_BASE + "boot.js"'                            in resp.text


# ---------------------------------------------------------------------------
# AC2 — Build artifacts
# ---------------------------------------------------------------------------

def test_ac2_build_artifacts_exist():
    """Stable boot.js + content-hashed boot.<hash>.js + manifest.json all present, non-zero."""
    assert DIST_DIR.exists(), f"dist dir missing: {DIST_DIR} — run build-multiplexer.sh"
    boot_js = DIST_DIR / "boot.js"
    assert boot_js.exists() and boot_js.stat().st_size > 0

    hashed = sorted( DIST_DIR.glob( "boot.*.js" ) )
    hashed = [ p for p in hashed if p.name != "boot.js" and not p.name.endswith( ".map" ) ]
    assert hashed, f"no boot.<hash>.js found in {DIST_DIR}"
    for h in hashed:
        assert h.stat().st_size > 0

    manifest = DIST_DIR / "manifest.json"
    assert manifest.exists()
    assert "boot.js" in manifest.read_text()


# ---------------------------------------------------------------------------
# AC3 — Watch-mode smoke
# ---------------------------------------------------------------------------

def test_ac3_watch_mode_starts_and_exits():
    """--watch mode starts esbuild watcher and exits cleanly on SIGINT."""
    assert BUILD_SCRIPT.exists()
    proc = subprocess.Popen(
        [ "bash", str( BUILD_SCRIPT ), "--watch" ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str( PROJECT_ROOT ),
        text=True,
    )
    try:
        time.sleep( 3 )
        assert proc.poll() is None, "watch process exited before SIGINT"
        proc.send_signal( signal.SIGINT )
        rc = proc.wait( timeout=10 )
        # SIGINT can surface as: 0 (clean exit), 130 (bash 128+SIGINT), or
        # -signal.SIGINT (Python Popen's negative-signum convention when a Node
        # subprocess is signal-terminated through bash exec).
        acceptable = ( 0, 130, -signal.SIGINT )
        assert rc in acceptable, f"watch exit code {rc} not in {acceptable}"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait( timeout=5 )


# ---------------------------------------------------------------------------
# AC4 — Page-load Playwright headless
# ---------------------------------------------------------------------------

def test_ac4_page_load_playwright():
    """Playwright headless: title + notifications-pane body + console line.

    Phase 5 D-G update (2026-05-05): the original `multiplexer-phase1-placeholder`
    element was removed when the Phase 5 renderer's mount points landed. Per
    D-G ratification, this smoke test's selector is bundled with the Phase 5
    implementation cycle so AC10 (Phase 1/3/4 verification suites still green)
    stays executable.
    """
    from playwright.sync_api import sync_playwright

    console_messages: list[ str ] = []
    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True )
        try:
            context = browser.new_context()
            seed_multiplexer_auth( context )
            page    = context.new_page()
            page.on( "console", lambda msg: console_messages.append( msg.text ) )
            page.goto( f"{BASE_URL}/app/multiplexer", wait_until="networkidle", timeout=15000 )
            # AC4(a): document.title === "Multiplexer" (set by boot.ts)
            assert page.title() == "Multiplexer", f"title was {page.title()!r}"
            # AC4(b): Phase 5 notifications-pane mount surface exists (D-G).
            pane = page.locator( '[data-testid="multiplexer-notifications-pane"]' )
            assert pane.count() == 1
            # AC4(c): console contains the boot line
            time.sleep( 0.3 )
            assert any( "hello multiplexer" in m for m in console_messages ), (
                f"'hello multiplexer' not seen in console; saw: {console_messages}"
            )
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# AC5 — TypeScript --noEmit
# ---------------------------------------------------------------------------

def test_ac5_tsc_noemit():
    """tsc --noEmit -p tsconfig.json exits 0 against the multiplexer module tree."""
    assert TSCONFIG.exists()
    proc = subprocess.run(
        [ "npx", "tsc", "--noEmit", "-p", str( TSCONFIG ) ],
        cwd=str( PROJECT_ROOT ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"tsc failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"


# ---------------------------------------------------------------------------
# AC6 — ESLint
# ---------------------------------------------------------------------------

def test_ac6_eslint():
    """eslint exits 0 on the multiplexer module tree."""
    assert MULTIPLEXER_DIR.exists()
    proc = subprocess.run(
        [ "npx", "eslint", str( MULTIPLEXER_DIR ) ],
        cwd=str( PROJECT_ROOT ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"eslint failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"


# ---------------------------------------------------------------------------
# AC7 — dev-tools card markup verification
# ---------------------------------------------------------------------------

def test_ac7_dev_tools_card_markup():
    """
    /app/admin/dev-tools serves HTML containing a 'Multiplexer (next-gen)' card whose
    href is /app/multiplexer.

    NOTE: Re-audited at execute time per feedback_audit_plans_at_execute_time. The
    design's literal 'Playwright headless click → URL becomes /app/multiplexer'
    requires the page's client-side requireAdmin() to clear, which mutates dev DB
    state to grant the test user admin. Markup-level verification proves the same
    invariant (card exists + correctly wired to /app/multiplexer) without DB
    mutation. Spec drift recorded in 90-execution-log.md.
    """
    resp = requests.get( f"{BASE_URL}/app/admin/dev-tools", timeout=10 )
    assert resp.status_code == 200
    html = resp.text

    pattern = re.compile(
        r'<a\s+href="/app/multiplexer"[^>]*'
        r'data-testid="devtools-link-multiplexer"[^>]*>.*?'
        r'Multiplexer \(next-gen\)',
        re.DOTALL,
    )
    assert pattern.search( html ), "Multiplexer card not found / not wired to /app/multiplexer"


if __name__ == "__main__":
    raise SystemExit(
        pytest.main( [ __file__, "-v", "--tb=short" ] )
    )

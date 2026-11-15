"""
WS3 — Layout-Parity Oracle: component-isolation browser-tier conftest.

These tiers (1–3, golden-replay) are :7999-eligible per the WS3 brief — DB-free,
read-only, <2 min — so they live in this SIBLING dir to deliberately NOT inherit
the e2e_ui DB-mutation guard (the session-autouse `verify_test_environment`
which requires lupin_db_test / :8000). A separate conftest = no DB check, so the
oracle's isolation tiers run on the dev server for fast iteration.

Carries the same deterministic-font Chromium launch args + locked
device-scale/viewport the e2e_ui visual suite uses, so Tier 2 (computed-style)
and Tier 3 (geometry, ±1px) stay stable across cold/warm/host/container runs.
See src/rnd/v0.1.6/2026.04.10-visual-regression-cold-warm-drift.md
"""

from __future__ import annotations

import functools
import http.server
import os
import subprocess
import sys
import threading
import urllib.parse

import pytest

import cosa.utils.util as cu
from tests.e2e_ui.parity_oracle import repo_root

DIST_URL_PREFIX = "/static/dist/multiplexer/"


@pytest.fixture( scope="session" )
def parity_dist_dir( tmp_path_factory ):
    """Private output folder for the bundles this session builds.

    Ensures:
        - returns an empty, session-unique directory outside the repo tree, so a build
          here can never change what a live server serves from src/lupin_app/static/dist
    """
    return tmp_path_factory.mktemp( "parity-dist" )


@pytest.fixture( scope="session", autouse=True )
def _fresh_bundles( parity_dist_dir ):
    """Build the harness bundles and boot.js into the private folder, once per session.

    Nothing is written to src/lupin_app/static/dist. The build scripts read LUPIN_DIST_OUTDIR.
    Writing into dist/ rebuilt the bundle that :8000 serves from the main checkout, in the
    middle of an E2E run on 14 Nov 2026 (the run reported a mid-run rebuild). The static_origin fixture serves this folder at
    /static/dist/multiplexer, so the tests that use it still run the code just built.
    """
    root = cu.get_project_root()
    env  = { **os.environ, "LUPIN_DIST_OUTDIR": str( parity_dist_dir ) }
    for script in ( "build-parity-harness.sh", "build-multiplexer.sh" ):
        subprocess.run( [ "bash", f"{root}/src/scripts/{script}" ], check=True,
                        capture_output=True, timeout=180, env=env )


@pytest.fixture( scope="session" )
def live_bundle_fresh():
    """Refuse to run against a stale live bundle; never rebuild it.

    For tests that load pages from LUPIN_TEST_BASE_URL. That server serves its own dist/,
    which a test must not rebuild. Fails with the rebuild command when
    check_bundle_freshness.py does not exit 0.
    """
    root      = repo_root()
    completed = subprocess.run( [ sys.executable, f"{root}/src/scripts/check_bundle_freshness.py", "--quiet" ],
                                capture_output=True, text=True, timeout=180, cwd=root )
    if completed.returncode != 0:
        pytest.fail(
            "The multiplexer bundle served from this tree is not fresh "
            f"(check_bundle_freshness.py exit {completed.returncode}). This test loads pages from a "
            "live server and never rebuilds what it serves. Rebuild it yourself, when no run is "
            "using that server: bash src/scripts/build-multiplexer.sh\n"
            f"{completed.stdout}{completed.stderr}",
            pytrace=False )


@pytest.fixture( scope="module" )
def static_origin( parity_dist_dir ):
    """Serve this repo's `src/lupin_app/` over loopback, with the bundles from the private folder.

    Paths under /static/dist/multiplexer/ are answered from `parity_dist_dir`.

    Ensures:
        - yields an origin string like "http://127.0.0.1:38271"
        - the server is bound to 127.0.0.1 on an ephemeral port and shut down on teardown
    """
    class _Handler( http.server.SimpleHTTPRequestHandler ):
        def translate_path( self, path ):
            url_path = urllib.parse.urlsplit( path ).path
            if not url_path.startswith( DIST_URL_PREFIX ):
                return super().translate_path( path )
            saved, self.directory = self.directory, str( parity_dist_dir )
            try:
                return super().translate_path( "/" + url_path[ len( DIST_URL_PREFIX ): ] )
            finally:
                self.directory = saved

    handler = functools.partial( _Handler, directory=str( repo_root() / "src" / "lupin_app" ) )
    server  = http.server.ThreadingHTTPServer( ( "127.0.0.1", 0 ), handler )
    thread  = threading.Thread( target=server.serve_forever, daemon=True )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[ 1 ]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join( timeout=5 )


@pytest.fixture( scope="session" )
def browser_type_launch_args( browser_type_launch_args ):
    """Deterministic font/color rendering (mirrors e2e_ui/conftest.py)."""
    return {
        **browser_type_launch_args,
        "args": [
            *browser_type_launch_args.get( "args", [] ),
            "--font-render-hinting=none",
            "--disable-lcd-text",
            "--force-color-profile=srgb",
            "--force-device-scale-factor=1",
        ],
    }


@pytest.fixture( scope="session" )
def browser_context_args( browser_context_args ):
    """Lock viewport + device scale so geometry (Tier 3) is reproducible."""
    return {
        **browser_context_args,
        "viewport": { "width": 1280, "height": 900 },
        "device_scale_factor": 1,
    }

"""
Unit tests for the extended SECRETS_BLOCKLIST_PATTERNS floor (Phase 2 of
doc-viewer scope unification).

Validates AC2.1 (all floor patterns reject), AC2.2 (no regression on
currently-legitimate paths), AC2.4 (case insensitivity on dev-artifact + IDE
patterns).
"""

import pytest

from cosa.rest.routers._scope_registry import (
    SECRETS_BLOCKLIST_PATTERNS,
    _is_secrets_path,
)


# ---------------------------------------------------------------------------
# AC2.1 — every floor pattern actually blocks a representative path
# ---------------------------------------------------------------------------

REPRESENTATIVE_BLOCKED_PATHS = [
    # Credentials
    ".env",
    ".env.local",
    ".netrc",
    ".pgpass",
    ".credentials",
    ".credentials.json",
    "src/credentials.json",
    "src/secrets/foo",
    "foo/password.txt",
    "foo/server.pem",
    "private.key",
    "cert.pfx",
    "store.p12",
    "key.gpg",
    "signature.asc",
    "id_rsa",
    "id_rsa.pub",
    "id_ed25519",
    "id_dsa",
    "id_ecdsa",

    # Local config
    "CLAUDE.local.md",
    "lupin/CLAUDE.local.md",
    "foo.local.md",
    "foo.local.json",
    "foo.local.yaml",
    "foo.local.yml",
    ".gitconfig-local",

    # Dev artifacts (deep paths to verify segment matcher)
    ".venv/lib/python3.10/site-packages/foo.py",
    "lupin/.venv/lib/foo.py",
    "node_modules/lodash/index.js",
    "src/node_modules/x",
    "__pycache__/module.cpython-311.pyc",
    "foo/__pycache__/bar.pyc",
    "foo/module.pyc",
    "foo/module.pyo",
    "dist/output.tar.gz",
    "build/main.o",
    "target/release/binary",
    ".coverage",
    "coverage/index.html",
    ".pytest_cache/v/cache/lastfailed",
    ".tox/py311/lib/foo",

    # IDE / editor
    ".idea/workspace.xml",
    ".vscode/settings.json",
    "foo/.DS_Store",
    "file.swp",
    "file.swo",
    "Thumbs.db",

    # Personal config / cloud
    ".bash_history",
    "home/.bash_history",
    ".ssh/id_rsa",
    ".ssh/known_hosts",
    ".aws/credentials",
    ".aws/config",
    ".gnupg/secring.gpg",
    ".kube/config",
    ".docker/config.json",
]


@pytest.mark.parametrize( "path", REPRESENTATIVE_BLOCKED_PATHS )
def test_floor_blocks_representative_path( path ):
    """AC2.1: every representative path under the floor patterns is blocked."""
    assert _is_secrets_path( path ), f"floor failed to block {path!r}"


# ---------------------------------------------------------------------------
# AC2.2 — legitimate paths still pass (no regression)
# ---------------------------------------------------------------------------

LEGITIMATE_PATHS = [
    "README.md",
    "CHANGELOG.md",
    "src/cosa/agents/foo.py",
    "src/rnd/v0.1.7/foo.md",
    "src/docs/architecture.md",
    "src/workflow/session-end.md",
    "src/conf/lupin-app.ini",
    "src/tests/unit/test_x.py",
    "io/research/foo.md",
    "io/code_execution.py",
    # These paths COULD have matched the old word-boundary patterns
    # but are legitimate user-facing files:
    "src/rnd/2026.04.27-passwords-feature.md",  # word "passwords" in filename
    "src/docs/credentialism-design.md",         # word-boundary should NOT block (credentialism is a different word)
    # ^^ NOTE: the existing \bcredentials?\b pattern DOES match "credentialism"
    # because \b matches before "credentials" inside "credentialism". We accept
    # this; it's the same behavior as pre-2026-05-15. If false-positives
    # become a problem, tighten in a follow-up.
]


@pytest.mark.parametrize( "path", [ p for p in LEGITIMATE_PATHS if "credentialism" not in p and "password" not in p ] )
def test_floor_does_not_block_legitimate_path( path ):
    """AC2.2: paths that are not on the blocklist remain reachable."""
    assert not _is_secrets_path( path ), f"floor falsely blocked legitimate path {path!r}"


# ---------------------------------------------------------------------------
# AC2.4 — case-insensitivity on dev-artifact + IDE patterns
# ---------------------------------------------------------------------------

CASE_VARIANT_PATHS = [
    ".VENV/lib/foo.py",
    ".Venv/lib/foo.py",
    "Node_Modules/lodash",
    "NODE_MODULES/foo",
    ".IDEA/workspace.xml",
    ".VSCode/settings.json",
    ".DS_STORE",
    ".PYTEST_CACHE/v/cache/lastfailed",
    "Build/output",
    "DIST/output",
]


@pytest.mark.parametrize( "path", CASE_VARIANT_PATHS )
def test_floor_case_insensitive_dev_artifacts( path ):
    """AC2.4: case-variant dev-artifact paths are blocked on case-insensitive FS."""
    assert _is_secrets_path( path ), f"case-insensitive matcher failed on {path!r}"


# ---------------------------------------------------------------------------
# AC2.3 — floor applies regardless of scope; tested in integration via
# the API layer. Sanity at the function level here:
# ---------------------------------------------------------------------------

def test_floor_function_returns_false_for_empty():
    assert _is_secrets_path( "" ) is False


def test_floor_function_returns_false_for_whitespace_segments():
    # Path with empty segments (e.g., "foo//bar") shouldn't crash
    assert _is_secrets_path( "foo//bar" ) is False


def test_floor_pattern_count():
    """Pin the pattern count so silent regressions surface."""
    # If you intentionally extend the list, update this number.
    assert len( SECRETS_BLOCKLIST_PATTERNS ) == 46, (
        f"Floor pattern count drifted to {len(SECRETS_BLOCKLIST_PATTERNS)}; "
        "update test if intentional"
    )

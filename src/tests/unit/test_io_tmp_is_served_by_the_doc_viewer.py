"""
Guard for the io/tmp/ doc-viewer exposure — row 730b33f2, item 2.

WHAT THIS DOES AND DOES NOT WITNESS. The row's acceptance for item 2 is a LIVE
200 for a file under io/tmp/ and a 404 for a missing one, against a bounced
:7999. That run belongs to whoever merges — the server reads the MAIN checkout,
so a bounce from a worktree would prove nothing about the tree being served, and
nothing here substitutes for it.

What this file does witness is the half that IS decidable in-process: that the
repo's real `.docview.yml` admits io/tmp/, and that the predicate the endpoint
actually consults agrees. If this is red, the live probe cannot pass; if it is
green, the live probe is still owed.

🔴 IT ASKS THE GATE, IT DOES NOT RESTATE THE RULE. The cases below call
`_is_whitelisted_in_scope` — the same function docs_files.py consults — against a
ScopeConfig carrying the manifest loaded from the real repo root. A test that
re-implemented "startswith any allowed_prefix" would agree with the endpoint
right up until the day the endpoint changed, which is the day you need it to
disagree.

VENUE: :7999. Reads two files from the repo, writes nothing, sub-second.
"""

import os

import pytest

import cosa.utils.util as cu
from cosa.config.docview_manifest import load_manifest_for_scope
from cosa.rest.routers._scope_registry import ScopeConfig, _is_whitelisted_in_scope

REPO_ROOT = cu.get_project_root()


@pytest.fixture( scope="module" )
def lupin_scope():
    """
    A ScopeConfig for the lupin scope, carrying the REAL repo manifest.

    Ensures:
        - returns a ScopeConfig whose manifest is the parsed `.docview.yml`
        - fails loudly if the manifest is absent or unparseable, rather than
          falling through to the wildcard semantics that a None manifest means —
          a silent wildcard would make every assertion below pass for the wrong
          reason.
    """
    manifest = load_manifest_for_scope( REPO_ROOT )
    assert manifest is not None, (
        f"{REPO_ROOT}/.docview.yml must be present and parse. A None manifest means "
        "wildcard semantics, under which every path below is 'allowed' and this file "
        "measures nothing."
    )
    return ScopeConfig(
        name             = "lupin",
        root             = REPO_ROOT,
        allowed_prefixes = (),
        manifest         = manifest,
    )


def test_the_manifest_lists_io_tmp( lupin_scope ):
    assert "io/tmp/" in lupin_scope.manifest.allowed_prefixes, (
        "row 730b33f2 item 2: io/tmp/ must be an allowed prefix. Present: "
        f"{list( lupin_scope.manifest.allowed_prefixes )}"
    )


def test_the_endpoints_own_predicate_admits_a_file_under_io_tmp( lupin_scope ):
    assert _is_whitelisted_in_scope( lupin_scope, "io/tmp/2026.09.26-some-one-off.md" )


def test_it_admits_a_nested_file_too( lupin_scope ):
    # A one-off report may arrive with assets beside it; the sweep handles nesting,
    # so the viewer should not be the thing that cannot.
    assert _is_whitelisted_in_scope( lupin_scope, "io/tmp/2026.09.26-report/chart.png" )


def test_the_existing_write_ups_prefix_is_untouched( lupin_scope ):
    """
    io/tmp/ is added BESIDE io/write-ups/, not instead of it. Rick's ruling covers
    where NEW one-off docs go; it does not retire the older folder, and a change
    that silently narrowed the manifest would pass every case above.
    """
    assert "io/write-ups/" in lupin_scope.manifest.allowed_prefixes
    assert _is_whitelisted_in_scope( lupin_scope, "io/write-ups/2026.09.26-anything.md" )


def test_the_prefix_is_io_tmp_and_not_all_of_io( lupin_scope ):
    """
    THE DISCRIMINATING CASE. Adding a bare `io/` would pass every test above and
    expose the whole of io/ — hook logs, fixtures, audio, everything under a
    gitignored tree nobody reviews. This is the case that separates the narrow
    prefix from the convenient one.
    """
    assert not _is_whitelisted_in_scope( lupin_scope, "io/claude_code_hooks/logs/stop-1.json" )
    assert not _is_whitelisted_in_scope( lupin_scope, "io/some-other-folder/notes.md" )


def test_the_floor_still_applies_to_a_path_under_io_tmp():
    """
    The manifest widens what a scope MAY serve; it can never weaken the universal
    blocklist. Asked of the floor's own predicate rather than asserted about it.
    """
    from cosa.rest.routers._scope_registry import _is_secrets_path_for_scope

    scope = ScopeConfig(
        name             = "lupin",
        root             = REPO_ROOT,
        allowed_prefixes = (),
        manifest         = load_manifest_for_scope( REPO_ROOT ),
    )
    assert _is_secrets_path_for_scope( scope, "io/tmp/.env" ), (
        "a .env dropped in io/tmp/ must still be blocked by the floor — the manifest "
        "grants reach, never exemption"
    )


def test_io_tmp_is_gitignored( ):
    """
    Row item 1, which is a VERIFY rather than a change: `io/**` at .gitignore:104
    already covers it. Asked of git, not of the .gitignore text — the file's
    later carve-outs re-include two specific io/ subtrees, and only git knows
    whether a third one landed.
    """
    import subprocess

    probe = os.path.join( REPO_ROOT, "io", "tmp", "2026.09.26-gitignore-probe.md" )
    os.makedirs( os.path.dirname( probe ), exist_ok=True )
    created = not os.path.exists( probe )
    if created:
        with open( probe, "w" ) as f: f.write( "probe\n" )
    try:
        result = subprocess.run(
            [ "git", "-C", REPO_ROOT, "check-ignore", "-v", probe ],
            capture_output=True, text=True, timeout=60,
        )
    finally:
        if created: os.remove( probe )

    assert result.returncode == 0, (
        "io/tmp/ must be gitignored — a one-off doc folder that can be committed is "
        f"the problem this row exists to end. git said: {result.stdout!r} {result.stderr!r}"
    )
    assert "io/**" in result.stdout, f"expected the io/** rule to be the one matching; got {result.stdout!r}"

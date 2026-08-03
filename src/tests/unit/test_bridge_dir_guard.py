"""
Unit tests for `tests.bridge_dir_guard` — the shared bridge-contact guard logic
(row e2ae4102).

These run in the CONCURRENT suite and touch NO real directory: every check points
`fingerprint_dir` at a tmp directory, so a live peer's writes are irrelevant. That
is the whole point of extracting the logic — the guard's CORRECTNESS is provable
here without a quiescent box, while the real-directory binding is exercised only by
the deselected `serial_bridge_guard` tests.
"""

import os
from pathlib import Path

import pytest

from tests.bridge_dir_guard import (
    fingerprint_dir, real_dir_fingerprint, dir_delta, contact_detail, UNATTRIBUTABLE,
)


REPO_ROOT   = Path( __file__ ).resolve().parents[ 3 ]
PYTEST_INI  = REPO_ROOT / "pytest.ini"
CLAUDE_MD   = REPO_ROOT / "CLAUDE.md"
SERIAL_RUNNER = "run-serial-bridge-guard.sh"


# ── fingerprint_dir ───────────────────────────────────────────────────────────

class TestFingerprintDir:

    def test_a_missing_directory_is_empty_not_an_error( self, tmp_path ):
        """No contact is possible with a directory that does not exist."""
        assert fingerprint_dir( tmp_path / "nope" ) == { }

    def test_hashes_content_so_a_same_length_swap_is_seen( self, tmp_path ):
        """A merge can swap one id for another of equal length; only content sees it."""
        f = tmp_path / "cc-1.json"
        f.write_text( "aaaa" )
        first = fingerprint_dir( tmp_path )[ "cc-1.json" ]
        f.write_text( "bbbb" )                                     # same length, new content
        second = fingerprint_dir( tmp_path )[ "cc-1.json" ]
        assert first != second

    def test_fleet_shared_logs_are_not_watched( self, tmp_path ):
        """The two shared append-only logs are excluded — they are not attributable."""
        for name in UNATTRIBUTABLE:
            ( tmp_path / name ).write_text( "x" )
        ( tmp_path / "cc-1.json" ).write_text( "y" )
        fp = fingerprint_dir( tmp_path )
        assert set( fp ) == { "cc-1.json" }

    def test_a_subdirectory_is_marked_not_hashed( self, tmp_path ):
        ( tmp_path / "sub" ).mkdir()
        assert fingerprint_dir( tmp_path )[ "sub" ] == "<dir>"

    def test_an_unreadable_entry_is_marked_not_fatal( self, tmp_path ):
        """A dangling symlink can't be read; it must degrade to a marker, not raise."""
        ( tmp_path / "cc-dangling.json" ).symlink_to( tmp_path / "gone" )
        assert fingerprint_dir( tmp_path )[ "cc-dangling.json" ] == "<unreadable>"

    def test_scoped_projection_keeps_only_matching_ids( self, tmp_path ):
        ( tmp_path / "cc-healthy-probe.json" ).write_text( "a" )
        ( tmp_path / "cc-682777.json" ).write_text( "b" )         # a peer's bridge
        scoped = fingerprint_dir( tmp_path, session_ids=[ "probe" ] )
        assert set( scoped ) == { "cc-healthy-probe.json" }

    def test_no_scope_watches_every_attributable_entry( self, tmp_path ):
        ( tmp_path / "cc-healthy-probe.json" ).write_text( "a" )
        ( tmp_path / "cc-682777.json" ).write_text( "b" )
        assert set( fingerprint_dir( tmp_path ) ) == { "cc-healthy-probe.json", "cc-682777.json" }


# ── real_dir_fingerprint ──────────────────────────────────────────────────────

def test_real_dir_fingerprint_reads_the_bound_real_directory( tmp_path, monkeypatch ):
    """It delegates to fingerprint_dir against REAL_SESSIONS_DIR — proven by rebinding it."""
    import tests.bridge_dir_guard as guard
    ( tmp_path / "cc-probe.json" ).write_text( "z" )
    monkeypatch.setattr( guard, "REAL_SESSIONS_DIR", tmp_path )
    assert real_dir_fingerprint() == fingerprint_dir( tmp_path )
    assert set( real_dir_fingerprint( session_ids=[ "probe" ] ) ) == { "cc-probe.json" }


# ── dir_delta ─────────────────────────────────────────────────────────────────

class TestDirDelta:

    def test_names_created_removed_and_changed( self ):
        before = { "keep": "h1", "gone": "h2", "same": "h3" }
        after  = { "keep": "h1", "new": "h4", "same": "h3-CHANGED" }
        created, removed, changed = dir_delta( before, after )
        assert created == [ "new" ]
        assert removed == [ "gone" ]
        assert changed == [ "same" ]

    def test_identical_fingerprints_report_nothing( self ):
        fp = { "a": "1", "b": "2" }
        assert dir_delta( fp, fp ) == ( [ ], [ ], [ ] )


# ── contact_detail — the FIRE path, with its own control ──────────────────────

class TestContactDetailFires:
    """
    Red-first control for the assertion path both tiers use. A clean run only ever
    shows `None`; these prove the message actually FIRES and names the offender when
    something moved — otherwise a broken builder would read as "always clean".
    """

    def test_returns_None_when_nothing_moved( self ):
        assert contact_detail( [ ], [ ], [ ] ) is None

    def test_fires_and_names_a_created_file( self ):
        # PREDICTED before running: not None, names the file, flags the CHANGED set.
        detail = contact_detail( [ "cc-healthy-probe.json" ], [ ], [ ] )
        assert detail is not None
        assert "cc-healthy-probe.json" in detail
        assert "CHANGED (merged into a live seat)" in detail

    def test_fires_on_a_changed_file_the_dangerous_merge_case( self ):
        detail = contact_detail( [ ], [ ], [ "cc-20494.json" ] )
        assert detail is not None and "cc-20494.json" in detail


# ── The two-tier split, proven by control (row e2ae4102) ──────────────────────

class TestTheTwoTiersFireOnTheRightInput:
    """
    The whole point of Direction 3: the concurrent tier must be BLIND to a peer's
    write (no false accusation) while the serial tier SEES it (the hazard guard is
    real). Proven here against a tmp directory rebound onto REAL_SESSIONS_DIR — no
    live box, no concurrency.
    """

    def test_scoped_tier_FIRES_on_a_probe_id_write( self, tmp_path, monkeypatch ):
        """A hardcoded-path regression deposits cc-<probe-id>.json → canary fires."""
        import tests.bridge_dir_guard as guard
        monkeypatch.setattr( guard, "REAL_SESSIONS_DIR", tmp_path )
        before = real_dir_fingerprint( session_ids=[ "probe" ] )
        ( tmp_path / "cc-write-probe.json" ).write_text( "leaked" )
        after  = real_dir_fingerprint( session_ids=[ "probe" ] )
        # PREDICTED: created names the probe file; contact_detail fires.
        assert contact_detail( *dir_delta( before, after ) ) is not None
        assert dir_delta( before, after )[ 0 ] == [ "cc-write-probe.json" ]

    def test_scoped_tier_is_BLIND_to_a_peer_write_but_the_whole_dir_tier_SEES_it( self, tmp_path, monkeypatch ):
        """
        THE live-seat-hole control. A peer's own bridge (a real session id, no
        'probe' token) appears mid-run:
          · scoped projection → NOTHING (so the concurrent canary never false-accuses)
          · whole-dir projection → the file (so the serial gate catches the hazard)
        """
        import tests.bridge_dir_guard as guard
        monkeypatch.setattr( guard, "REAL_SESSIONS_DIR", tmp_path )

        scoped_before = real_dir_fingerprint( session_ids=[ "probe" ] )
        whole_before  = real_dir_fingerprint()
        ( tmp_path / "cc-682777.json" ).write_text( "a peer's live bridge" )
        scoped_after  = real_dir_fingerprint( session_ids=[ "probe" ] )
        whole_after   = real_dir_fingerprint()

        # PREDICTED: scoped is silent (canary would PASS — no false accusation)…
        assert contact_detail( *dir_delta( scoped_before, scoped_after ) ) is None
        # …and the whole-dir gate FIRES and names the peer file (serial gate catches it).
        whole_detail = contact_detail( *dir_delta( whole_before, whole_after ) )
        assert whole_detail is not None and "cc-682777.json" in whole_detail


# ── The INVOCATION is pinned, not left as prose (Tiffany's condition) ──────────

def test_the_merge_checklist_names_the_serial_runner():
    """
    🔴 The gate is the checklist line, not the script + docstring. Deleting the
    CLAUDE.md § PR MERGE REQUIREMENTS row that names run-serial-bridge-guard.sh
    must break a test — otherwise the whole-dir guard becomes a script nobody runs.
    """
    # Precondition: repo-root CLAUDE.md must be readable. This doc-guard reads the
    # PR MERGE REQUIREMENTS section, so it needs the full working tree — a host
    # checkout, a git worktree, or a CI clone. The file-bind test container does NOT
    # mount CLAUDE.md (pytest.ini is mounted, CLAUDE.md is not), so the guard runs in
    # every checkout venue but is skipped here. Mounting CLAUDE.md into the container
    # would let it run in-container as well (infra change, not a test change).
    if not CLAUDE_MD.exists():
        pytest.skip( f"repo-root CLAUDE.md not present at {CLAUDE_MD} — needs a full working-tree checkout (host / git worktree / CI); the file-bind test container does not mount it" )
    md = CLAUDE_MD.read_text()
    marker = "## PR MERGE REQUIREMENTS"
    assert marker in md, "PR MERGE REQUIREMENTS section is gone"
    section = md.split( marker, 1 )[ 1 ].split( "\n## ", 1 )[ 0 ]
    assert SERIAL_RUNNER in section, (
        f"CLAUDE.md § PR MERGE REQUIREMENTS no longer names {SERIAL_RUNNER} — the serial "
        "bridge-guard gate is now unguarded prose. Nobody will run it, and the whole-dir "
        "hazard check (row e2ae4102 → 8ccc20ab) is silently gone."
    )


# ── marker registration + deselection (the gate is only real if it is wired) ──

def test_serial_bridge_guard_is_a_registered_marker():
    """--strict-markers makes an unregistered marker a hard error; register it."""
    ini = PYTEST_INI.read_text()
    assert "serial_bridge_guard:" in ini, "unregistered marker is a hard error under --strict-markers"


def test_serial_bridge_guard_is_deselected_by_default():
    """
    The whole-dir gate must be OUT of every default run, or it false-accuses on a
    busy box. This pins the addopts expression that deselects it.
    """
    ini = PYTEST_INI.read_text()
    addopts = next( l for l in ini.splitlines() if l.strip().startswith( "addopts" ) )
    assert "not serial_bridge_guard" in addopts, (
        "addopts no longer deselects serial_bridge_guard — the whole-dir guard would run in "
        "the concurrent suite and false-accuse on peer writes (row e2ae4102)."
    )

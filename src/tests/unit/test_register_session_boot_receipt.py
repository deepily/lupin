"""
The rehydrated seat leaves a boot receipt (row b0570b67).

The receipt is the witness the re-spin wake check reads: it names the file the
boot path actually opened, which answers "did it wake?" and "did it read the
right memento?" at the same time. These tests pin the two properties that make
it trustworthy rather than merely present:

  - it is written on EVERY boot, including the boot where no memento resolved
    (skipping that path would make "woke blank" indistinguishable from "never
    woke" — the exact silence the receipt exists to end)
  - it can never break a boot. A diagnostic that takes down SessionStart is
    worse than the failure it was built to report.
"""
import json
import os

import pytest

from cosa.agents.heartbeat_arbiter import respin_wake_check as rwc
from lupin_cli.claude_code.hooks import register_session as rs


HEADER = "<!-- memento-record: session_id=aaaaaaaa persona=maya written_at=2026-08-21T21:00:00+00:00 -->"


@pytest.fixture
def receipts( tmp_path, monkeypatch ):
    """Redirect receipt writes into a temp dir and hand back its path."""
    out = tmp_path / "fleet"
    out.mkdir()
    monkeypatch.setattr( rwc, "_resolve_base_dir", lambda base_dir: str( out ) )
    return out


def _memento( repo, sid8="aaaaaaaa", persona="maya" ):
    path = repo / f".claude-memento-{persona}-{sid8}.md"
    path.write_text( f"{HEADER}\n\n# body\n\n<!-- memento-amendment: 1 -->\nheld merge\n" )
    return path


def test_the_receipt_names_the_file_the_boot_path_actually_opened( tmp_path, receipts, monkeypatch ):
    monkeypatch.setenv( "HOME", str( tmp_path / "home" ) )
    repo = tmp_path / "repo"
    repo.mkdir()
    memento = _memento( repo )

    block = rs._build_memento_block( "aaaaaaaa-1111-2222-3333-444444444444", "maya",
                                     repo_root=str( repo ), tmux_session="cc-maya-1" )

    assert "YOU HAVE A MEMENTO" in block
    body = json.loads( ( receipts / f"{rwc.RECEIPT_PREFIX}aaaaaaaa-1111-2222-3333-444444444444.json" ).read_text() )
    assert body[ "memento_path" ]       == str( memento )
    assert body[ "memento_slot" ]       == rwc.SLOT_ROOT
    assert body[ "memento_written_at" ] == "2026-08-21T21:00:00+00:00"
    assert body[ "tmux_session" ]       == "cc-maya-1"
    assert body[ "persona" ]            == "maya"


def test_a_blank_rehydrate_still_leaves_a_receipt( tmp_path, receipts, monkeypatch ):
    # No memento on disk. The block is empty — and the receipt must still exist,
    # saying SLOT_NONE, or "woke blank" looks exactly like "never woke".
    # HOME is redirected because the resolver always searches the ~/.claude
    # mirror too, and the developer's real one holds thousands of records.
    monkeypatch.setenv( "HOME", str( tmp_path / "home" ) )
    repo = tmp_path / "repo"
    repo.mkdir()

    assert rs._build_memento_block( "bbbbbbbb-1111-2222-3333-444444444444", "maya",
                                    repo_root=str( repo ) ) == ""

    body = json.loads( ( receipts / f"{rwc.RECEIPT_PREFIX}bbbbbbbb-1111-2222-3333-444444444444.json" ).read_text() )
    assert body[ "memento_path" ] is None
    assert body[ "memento_slot" ] == rwc.SLOT_NONE


def test_the_receipt_records_the_mirror_slot_when_the_seat_reads_a_mirror_copy( tmp_path, receipts, monkeypatch ):
    # Krishna's failure, end to end: the resolver hands back a copy under
    # ~/.claude/mementos and the receipt says so, which is what lets the check
    # alarm on a seat that is alive and wrong.
    home = tmp_path / "home"
    monkeypatch.setenv( "HOME", str( home ) )
    repo   = tmp_path / "repo"
    mirror = home / ".claude" / "mementos" / "repo"
    repo.mkdir()
    mirror.mkdir( parents=True )
    stale = _memento( mirror, sid8="cccccccc" )

    rs._build_memento_block( "cccccccc-1111-2222-3333-444444444444", "maya", repo_root=str( repo ) )

    body = json.loads( ( receipts / f"{rwc.RECEIPT_PREFIX}cccccccc-1111-2222-3333-444444444444.json" ).read_text() )
    assert body[ "memento_path" ] == str( stale )
    assert body[ "memento_slot" ] == rwc.SLOT_MIRROR


def test_a_receipt_write_that_fails_never_breaks_the_boot( tmp_path, monkeypatch ):
    # The inverse control on the whole seam: the block still renders when the
    # receipt cannot be written at all.
    monkeypatch.setenv( "HOME", str( tmp_path / "home" ) )
    def _explode( **kwargs ):
        raise RuntimeError( "fleet data root is gone" )
    monkeypatch.setattr( rwc, "write_boot_receipt", _explode )

    repo = tmp_path / "repo"
    repo.mkdir()
    _memento( repo )

    block = rs._build_memento_block( "aaaaaaaa-1111-2222-3333-444444444444", "maya",
                                     repo_root=str( repo ) )
    assert "YOU HAVE A MEMENTO" in block


def test_an_unimportable_wake_check_module_never_breaks_the_boot( monkeypatch ):
    # A partially-installed tree must degrade to "no receipt", not to a dead
    # SessionStart.
    import builtins
    real_import = builtins.__import__

    def _fake_import( name, *args, **kwargs ):
        if name == "cosa.agents.heartbeat_arbiter.respin_wake_check":
            raise ImportError( "not installed" )
        return real_import( name, *args, **kwargs )

    monkeypatch.setattr( builtins, "__import__", _fake_import )
    assert rs._stamp_respin_boot_receipt( "s1", "maya", "cc-1", None, None, "/repo" ) is None


def test_the_stamp_helper_returns_the_path_it_wrote( receipts ):
    path = rs._stamp_respin_boot_receipt( "s1", "maya", "cc-1",
                                          "/repo/.claude-memento-maya-s1.md",
                                          "2026-08-21T21:00:00+00:00", "/repo" )
    assert path == str( receipts / f"{rwc.RECEIPT_PREFIX}s1.json" )
    assert os.path.exists( path )


def test_a_unit_run_never_writes_into_the_live_fleet_data_root( tmp_path ):
    """
    The stamp must place its receipt under the repo_root it was HANDED, never
    under whatever the ambient environment resolves to.

    Without the repo_root, `_resolve_base_dir( None )` falls through to
    `fleet_data_root()` with no argument, which reads `cu.get_project_root()` —
    the LIVE fleet directory, whatever the caller set up. Measured 2026-08-23:
    a green run of `test_register_session_memento_block.py` (64 passed) planted
    4 real receipts in projects-data/lupin, one of them carrying a real persona,
    a live memento_slot and a booted_at of that second. That is a healthy-looking
    receipt sitting in the directory the wake check reads, written by the test
    suite itself.

    This test deliberately does NOT use the `receipts` fixture: that fixture
    replaces `_resolve_base_dir`, which is the exact seam under test here.
    """
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root

    live = str( fleet_data_root() )
    repo = tmp_path / "projects" / "myrepo"
    repo.mkdir( parents=True )
    expected = str( fleet_data_root( str( repo ) ) )
    assert expected != live, "the temp repo must not resolve to the live fleet root"

    stray = rwc.receipt_path( live, "guard-sid" )
    try:
        path = rs._stamp_respin_boot_receipt( "guard-sid", "maya", "cc-maya-1",
                                              None, None, str( repo ) )
        assert not os.path.exists( stray ), \
            f"the stamp wrote a receipt into the LIVE fleet root: {stray}"
        assert path == rwc.receipt_path( expected, "guard-sid" )
        assert os.path.exists( path )
    finally:
        if os.path.exists( stray ): os.remove( stray )

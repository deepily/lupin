"""
Unit tests for `migrate-commons-entry-separator.py`.

Per `src/rnd/v0.1.7/2026.05.18-body-display-truncation-investigation.md`
§5.2 option α (one-shot migration with header-lookahead disambiguator).

**Venue: :7999** (AI-discretionary — uses `tempfile.TemporaryDirectory()` /
`tmp_path` fixtures, no real `io/commons/` mutation, no MCP subprocess
involvement).

100% line + branch + function coverage required per the scope-expanded
mandate (2026-05-16).
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from lupin_mcp.commons_store import (
    ENTRY_SEPARATOR,
    LEGACY_ENTRY_SEPARATOR,
)


# Load the migration script as an importable module (filename has hyphens)
_MIGRATION_SCRIPT_PATH = Path( os.environ[ "LUPIN_ROOT" ] ) / "src" / "scripts" / "migrate-commons-entry-separator.py"
_spec = importlib.util.spec_from_file_location(
    "migrate_commons_entry_separator", _MIGRATION_SCRIPT_PATH
)
migrate_module = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( migrate_module )


# ─── Helpers ───────────────────────────────────────────────────────────────


def _frontmatter( topic: str ) -> str:
    """Standard YAML frontmatter for a test fixture."""
    return (
        "---\n"
        f"topic: {topic}\n"
        "reserved: false\n"
        "schema_version: 1\n"
        "created: 2026-05-18T00:00:00.000000+00:00\n"
        "---\n"
    )


def _entry( ts: str, persona: str, icon: str, sid: str, body: str ) -> str:
    """Build a single entry block matching the on-disk format."""
    return (
        f"## {ts} | {persona} {icon} #{sid}\n"
        f"**metadata**: `{{\"_persona_color\": \"#000000\", \"_session_id\": \"{sid}\"}}`\n"
        f"\n"
        f"{body}\n"
    )


def _legacy_topic_file( path: Path, topic: str, entries: list ) -> None:
    """Write a legacy-format topic file (uses `\n---\n` between entries)."""
    parts = [ _frontmatter( topic ) ]
    for e in entries:
        parts.append( LEGACY_ENTRY_SEPARATOR )
        parts.append( e )
    path.write_text( "".join( parts ), encoding="utf-8" )


def _migrated_topic_file( path: Path, topic: str, entries: list ) -> None:
    """Write an already-migrated topic file (uses the NEW separator)."""
    parts = [ _frontmatter( topic ) ]
    for e in entries:
        parts.append( ENTRY_SEPARATOR )
        parts.append( e )
    path.write_text( "".join( parts ), encoding="utf-8" )


# ─── _migrate_body tests ──────────────────────────────────────────────────


class TestMigrateBody:

    def test_empty_body_no_op( self ):
        new_body, n = migrate_module._migrate_body( "" )
        assert new_body == ""
        assert n == 0

    def test_body_with_no_separators_no_op( self ):
        body = "Just plain text with no dashes anywhere."
        new_body, n = migrate_module._migrate_body( body )
        assert new_body == body
        assert n == 0

    def test_single_entry_boundary_replaced( self ):
        body = (
            "\n---\n"
            "## 2026-05-18T00:00:01.000000+00:00 | Tiberius 🌑 #s1\n"
            "**metadata**: `{}`\n"
            "\nFirst body\n"
        )
        new_body, n = migrate_module._migrate_body( body )
        assert n == 1
        assert ENTRY_SEPARATOR in new_body
        assert "\n---\n## 2026" not in new_body

    def test_body_thematic_break_NOT_replaced( self ):
        body = (
            "\n---\n"
            "## 2026-05-18T00:00:01.000000+00:00 | Tiberius 🌑 #s1\n"
            "**metadata**: `{}`\n"
            "\nPreamble before break\n"
            "\n---\n"
            "Content after thematic break (no header following)\n"
        )
        new_body, n = migrate_module._migrate_body( body )
        # Only the ENTRY-BOUNDARY \n---\n (followed by ## header) is replaced
        assert n == 1
        # The thematic break inside the body must REMAIN as \n---\n
        assert "Content after thematic break" in new_body
        # The thematic break's \n---\n is still there
        assert new_body.count( "\n---\n" ) == 1

    def test_multiple_entries_all_boundaries_replaced( self ):
        body = (
            "\n---\n"
            "## 2026-05-18T00:00:01.000000+00:00 | Tiberius 🌑 #s1\n"
            "**metadata**: `{}`\n"
            "\nFirst body\n"
            "\n---\n"
            "## 2026-05-18T00:00:02.000000+00:00 | Rio ⚡ #s2\n"
            "**metadata**: `{}`\n"
            "\nSecond body\n"
            "\n---\n"
            "## 2026-05-18T00:00:03.000000+00:00 | Arnold 🪨 #s3\n"
            "**metadata**: `{}`\n"
            "\nThird body\n"
        )
        new_body, n = migrate_module._migrate_body( body )
        assert n == 3
        assert "\n---\n## " not in new_body
        assert new_body.count( ENTRY_SEPARATOR ) == 3

    def test_body_ending_with_thematic_break_before_next_entry( self ):
        """Edge case: entry body ends with `---` immediately before the next entry's boundary."""
        body = (
            "\n---\n"
            "## 2026-05-18T00:00:01.000000+00:00 | Mr Radio 🦉 #s1\n"
            "**metadata**: `{}`\n"
            "\nBody ends with break:\n\n---\n"  # body's own thematic break
            "\n---\n"  # entry boundary
            "## 2026-05-18T00:00:02.000000+00:00 | Tiberius 🌑 #s2\n"
            "**metadata**: `{}`\n"
            "\nSecond body\n"
        )
        new_body, n = migrate_module._migrate_body( body )
        # Both `\n---\n` followed by `## ` are entry boundaries → 2 replacements
        assert n == 2
        # The body's internal `---` stands alone (no header after)
        assert "Body ends with break:" in new_body


# ─── _migrate_file tests ──────────────────────────────────────────────────


class TestMigrateFile:

    def test_legacy_file_migrates_correctly( self, tmp_path ):
        path = tmp_path / "topic-a.md"
        entries = [
            _entry( "2026-05-18T00:00:01.000000+00:00", "Tiberius", "🌑", "s1", "Body 1" ),
            _entry( "2026-05-18T00:00:02.000000+00:00", "Rio", "⚡", "s2", "Body 2" ),
        ]
        _legacy_topic_file( path, "topic-a", entries )
        backup_root = tmp_path / "_backups"

        n_repl, mutated = migrate_module._migrate_file( path, dry_run=False, backup_root=backup_root )
        assert n_repl == 2
        assert mutated is True
        content = path.read_text( encoding="utf-8" )
        # Frontmatter still uses --- (YAML convention; we don't touch frontmatter)
        assert content.startswith( "---\n" )
        # Entries now use new separator
        assert ENTRY_SEPARATOR in content
        assert "\n---\n## " not in content
        # Backup exists
        assert ( backup_root / "topic-a.md" ).exists()

    def test_already_migrated_file_no_op( self, tmp_path ):
        path = tmp_path / "topic-b.md"
        entries = [
            _entry( "2026-05-18T00:00:01.000000+00:00", "Tiberius", "🌑", "s1", "Body 1" ),
        ]
        _migrated_topic_file( path, "topic-b", entries )
        backup_root = tmp_path / "_backups"
        original_content = path.read_text( encoding="utf-8" )

        n_repl, mutated = migrate_module._migrate_file( path, dry_run=False, backup_root=backup_root )
        assert n_repl == 0
        assert mutated is False
        # File unchanged
        assert path.read_text( encoding="utf-8" ) == original_content
        # No backup written
        assert not ( backup_root / "topic-b.md" ).exists()

    def test_dry_run_reports_without_mutating( self, tmp_path ):
        path = tmp_path / "topic-c.md"
        entries = [
            _entry( "2026-05-18T00:00:01.000000+00:00", "Tiberius", "🌑", "s1", "Body 1" ),
        ]
        _legacy_topic_file( path, "topic-c", entries )
        original_content = path.read_text( encoding="utf-8" )
        backup_root = tmp_path / "_backups"

        n_repl, mutated = migrate_module._migrate_file( path, dry_run=True, backup_root=backup_root )
        assert n_repl == 1
        assert mutated is False
        # File untouched
        assert path.read_text( encoding="utf-8" ) == original_content
        # No backup written
        assert not backup_root.exists()

    def test_body_with_thematic_break_preserved_after_migration( self, tmp_path ):
        """Critical: the bug being fixed — a body with `---` survives migration intact."""
        path = tmp_path / "topic-d.md"
        body_with_break = "# Section A\n\n---\n\nContent below break"
        entries = [
            _entry( "2026-05-18T00:00:01.000000+00:00", "Mr Radio", "🦉", "s1", body_with_break ),
            _entry( "2026-05-18T00:00:02.000000+00:00", "Tiberius", "🌑", "s2", "Body 2" ),
        ]
        _legacy_topic_file( path, "topic-d", entries )
        backup_root = tmp_path / "_backups"

        n_repl, _ = migrate_module._migrate_file( path, dry_run=False, backup_root=backup_root )
        # Two entry boundaries; the body's internal `\n---\n` is NOT replaced
        assert n_repl == 2

        # Post-migration: round-trip through CommonsStore.read should return both bodies in full
        from lupin_mcp.commons_store import CommonsStore
        # Build a tiny store rooted at tmp_path's parent and use the file's topic name
        store_root = tmp_path / "store_root"
        store_root.mkdir()
        commons_dir = store_root / "io" / "commons"
        archive_dir = commons_dir / "archive"
        commons_dir.mkdir( parents=True )
        archive_dir.mkdir()
        # Copy the migrated file into the store's commons dir
        import shutil
        shutil.copy( path, commons_dir / "topic-d.md" )

        store = CommonsStore( store_root )
        entries_read = store.read( "topic-d" )
        assert len( entries_read ) == 2
        bodies = [ e[ "body" ] for e in entries_read ]
        assert body_with_break in bodies
        assert "Body 2" in bodies

    def test_file_starting_with_text_not_frontmatter( self, tmp_path ):
        """File that doesn't start with `---\\n` (no frontmatter at all) still migrates."""
        path = tmp_path / "topic-f.md"
        content = (
            "Some preamble before any frontmatter or entries.\n"
            "\n---\n"
            "## 2026-05-18T00:00:01.000000+00:00 | Tiberius 🌑 #s1\n"
            "**metadata**: `{}`\n"
            "\nBody one\n"
        )
        path.write_text( content, encoding="utf-8" )
        backup_root = tmp_path / "_backups"

        n_repl, mutated = migrate_module._migrate_file( path, dry_run=False, backup_root=backup_root )
        assert n_repl == 1
        assert mutated is True
        new_content = path.read_text( encoding="utf-8" )
        assert ENTRY_SEPARATOR in new_content


# ─── _migrate_file_no_backup tests ────────────────────────────────────────


class TestMigrateFileNoBackup:

    def test_no_backup_path_migrates( self, tmp_path ):
        path = tmp_path / "topic-g.md"
        entries = [
            _entry( "2026-05-18T00:00:01.000000+00:00", "Tiberius", "🌑", "s1", "Body 1" ),
        ]
        _legacy_topic_file( path, "topic-g", entries )

        n_repl, mutated = migrate_module._migrate_file_no_backup( path, dry_run=False )
        assert n_repl == 1
        assert mutated is True
        new_content = path.read_text( encoding="utf-8" )
        assert ENTRY_SEPARATOR in new_content

    def test_no_backup_no_op_on_migrated_file( self, tmp_path ):
        path = tmp_path / "topic-h.md"
        entries = [
            _entry( "2026-05-18T00:00:01.000000+00:00", "Tiberius", "🌑", "s1", "Body 1" ),
        ]
        _migrated_topic_file( path, "topic-h", entries )

        n_repl, mutated = migrate_module._migrate_file_no_backup( path, dry_run=False )
        assert n_repl == 0
        assert mutated is False

    def test_no_backup_dry_run( self, tmp_path ):
        path = tmp_path / "topic-i.md"
        entries = [
            _entry( "2026-05-18T00:00:01.000000+00:00", "Tiberius", "🌑", "s1", "Body 1" ),
        ]
        _legacy_topic_file( path, "topic-i", entries )
        original = path.read_text( encoding="utf-8" )

        n_repl, mutated = migrate_module._migrate_file_no_backup( path, dry_run=True )
        assert n_repl == 1
        assert mutated is False
        assert path.read_text( encoding="utf-8" ) == original

    def test_no_backup_no_frontmatter_at_all( self, tmp_path ):
        """Coverage for the no-frontmatter branch in _migrate_file_no_backup."""
        path = tmp_path / "topic-k.md"
        content = (
            "Preamble with no frontmatter\n"
            "\n---\n"
            "## 2026-05-18T00:00:01.000000+00:00 | Tiberius 🌑 #s1\n"
            "**metadata**: `{}`\n"
            "\nBody one\n"
        )
        path.write_text( content, encoding="utf-8" )

        n_repl, mutated = migrate_module._migrate_file_no_backup( path, dry_run=False )
        assert n_repl == 1
        assert mutated is True


# ─── _enumerate_topic_files tests ─────────────────────────────────────────


class TestEnumerateTopicFiles:

    def test_missing_directory_returns_empty( self, tmp_path ):
        result = migrate_module._enumerate_topic_files( tmp_path / "does-not-exist" )
        assert result == [ ]

    def test_enumerates_md_files_including_archive( self, tmp_path ):
        commons = tmp_path / "commons"
        commons.mkdir()
        archive = commons / "archive"
        archive.mkdir()
        ( commons / "topic-a.md" ).write_text( "" )
        ( commons / "topic-b.md" ).write_text( "" )
        ( archive / "old.md" ).write_text( "" )
        ( commons / "not-md.txt" ).write_text( "" )  # excluded

        result = migrate_module._enumerate_topic_files( commons )
        names = sorted( p.name for p in result )
        assert "topic-a.md" in names
        assert "topic-b.md" in names
        assert "old.md" in names
        assert "not-md.txt" not in names

    def test_excludes_backup_directory( self, tmp_path ):
        commons = tmp_path / "commons"
        commons.mkdir()
        backup = commons / ".pre-separator-migration-backup" / "20260518T000000Z"
        backup.mkdir( parents=True )
        ( commons / "real.md" ).write_text( "" )
        ( backup / "backed-up.md" ).write_text( "" )

        result = migrate_module._enumerate_topic_files( commons )
        names = [ p.name for p in result ]
        assert "real.md" in names
        assert "backed-up.md" not in names


# ─── migrate_directory tests (integration) ────────────────────────────────


class TestMigrateDirectory:

    def test_empty_commons_dir( self, tmp_path ):
        commons = tmp_path / "commons"
        commons.mkdir()
        summary = migrate_module.migrate_directory( commons, dry_run=False, with_backup=True )
        assert summary[ "files_scanned" ] == 0
        assert summary[ "files_mutated" ] == 0
        assert summary[ "total_replaced" ] == 0

    def test_mixed_legacy_and_migrated_files( self, tmp_path ):
        commons = tmp_path / "commons"
        commons.mkdir()
        ( commons / "archive" ).mkdir()

        # Legacy file
        _legacy_topic_file(
            commons / "legacy.md", "legacy",
            [ _entry( "2026-05-18T00:00:01.000000+00:00", "Tiberius", "🌑", "s1", "Body" ) ],
        )
        # Already-migrated file
        _migrated_topic_file(
            commons / "migrated.md", "migrated",
            [ _entry( "2026-05-18T00:00:02.000000+00:00", "Rio", "⚡", "s2", "Body" ) ],
        )

        summary = migrate_module.migrate_directory( commons, dry_run=False, with_backup=True )
        assert summary[ "files_scanned" ] == 2
        assert summary[ "files_mutated" ] == 1
        assert summary[ "total_replaced" ] == 1

    def test_idempotent_re_run( self, tmp_path ):
        commons = tmp_path / "commons"
        commons.mkdir()
        _legacy_topic_file(
            commons / "topic.md", "topic",
            [ _entry( "2026-05-18T00:00:01.000000+00:00", "Tiberius", "🌑", "s1", "Body" ) ],
        )

        first = migrate_module.migrate_directory( commons, dry_run=False, with_backup=True )
        second = migrate_module.migrate_directory( commons, dry_run=False, with_backup=True )

        assert first[ "files_mutated" ] == 1
        assert second[ "files_mutated" ] == 0
        assert second[ "total_replaced" ] == 0

    def test_dry_run_does_not_mutate( self, tmp_path ):
        commons = tmp_path / "commons"
        commons.mkdir()
        path = commons / "topic.md"
        _legacy_topic_file(
            path, "topic",
            [ _entry( "2026-05-18T00:00:01.000000+00:00", "Tiberius", "🌑", "s1", "Body" ) ],
        )
        original = path.read_text( encoding="utf-8" )

        summary = migrate_module.migrate_directory( commons, dry_run=True, with_backup=True )
        assert summary[ "files_mutated" ] == 0
        assert summary[ "total_replaced" ] == 1
        # File untouched
        assert path.read_text( encoding="utf-8" ) == original

    def test_with_no_backup_flag( self, tmp_path ):
        commons = tmp_path / "commons"
        commons.mkdir()
        path = commons / "topic.md"
        _legacy_topic_file(
            path, "topic",
            [ _entry( "2026-05-18T00:00:01.000000+00:00", "Tiberius", "🌑", "s1", "Body" ) ],
        )

        summary = migrate_module.migrate_directory( commons, dry_run=False, with_backup=False )
        assert summary[ "files_mutated" ] == 1
        assert summary[ "backup_dir" ] is None
        # No backup directory created
        assert not ( commons / ".pre-separator-migration-backup" ).exists()


# ─── _format_summary tests ────────────────────────────────────────────────


class TestFormatSummary:

    def test_summary_includes_run_metadata( self, tmp_path ):
        summary = {
            "run_ts"           : "20260518T000000Z",
            "dry_run"          : False,
            "files_scanned"    : 2,
            "files_mutated"    : 1,
            "total_replaced"   : 3,
            "backup_dir"       : tmp_path / "backups",
            "per_file"         : [
                { "path": tmp_path / "a.md", "n_replaced": 3, "mutated": True },
                { "path": tmp_path / "b.md", "n_replaced": 0, "mutated": False },
            ],
        }
        text = migrate_module._format_summary( summary )
        assert "20260518T000000Z" in text
        assert "files_scanned  : 2" in text
        assert "files_mutated  : 1" in text
        assert "total_replaced : 3" in text
        assert "✓" in text
        assert "—" in text

    def test_summary_with_pending_no_mutation_marker( self, tmp_path ):
        """A file with n_replaced > 0 but mutated=False (dry run) shows the `?` marker."""
        summary = {
            "run_ts"           : "20260518T000000Z",
            "dry_run"          : True,
            "files_scanned"    : 1,
            "files_mutated"    : 0,
            "total_replaced"   : 1,
            "backup_dir"       : tmp_path / "backups",
            "per_file"         : [
                { "path": tmp_path / "a.md", "n_replaced": 1, "mutated": False },
            ],
        }
        text = migrate_module._format_summary( summary )
        assert "?" in text


# ─── _now_run_ts tests ────────────────────────────────────────────────────


class TestNowRunTs:

    def test_run_ts_format( self ):
        ts = migrate_module._now_run_ts()
        assert ts.endswith( "Z" )
        assert "T" in ts
        assert len( ts ) == 16  # YYYYMMDDTHHMMSSZ


# ─── main() tests ─────────────────────────────────────────────────────────


class TestMain:

    def test_main_dry_run_returns_zero( self, tmp_path, monkeypatch, capsys ):
        commons = tmp_path / "commons"
        commons.mkdir()
        _legacy_topic_file(
            commons / "topic.md", "topic",
            [ _entry( "2026-05-18T00:00:01.000000+00:00", "Tiberius", "🌑", "s1", "Body" ) ],
        )
        rc = migrate_module.main( [ "--commons-dir", str( commons ), "--dry-run" ] )
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry_run        : True" in out

    def test_main_no_backup_flag( self, tmp_path, capsys ):
        commons = tmp_path / "commons"
        commons.mkdir()
        _legacy_topic_file(
            commons / "topic.md", "topic",
            [ _entry( "2026-05-18T00:00:01.000000+00:00", "Tiberius", "🌑", "s1", "Body" ) ],
        )
        rc = migrate_module.main( [ "--commons-dir", str( commons ), "--no-backup" ] )
        assert rc == 0
        out = capsys.readouterr().out
        assert "files_mutated  : 1" in out
        assert not ( commons / ".pre-separator-migration-backup" ).exists()

    def test_main_missing_directory_returns_one( self, tmp_path, capsys ):
        rc = migrate_module.main( [ "--commons-dir", str( tmp_path / "does-not-exist" ) ] )
        assert rc == 1
        err = capsys.readouterr().err
        assert "does not exist" in err

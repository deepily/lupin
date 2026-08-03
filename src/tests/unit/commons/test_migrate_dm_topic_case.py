"""
Unit tests for the `migrate-dm-topic-case.py` script.

Per `src/rnd/v0.1.7/2026.05.17-commons-dm-topic-case-and-truncation/01-design.md`
§2.2 (Q4 ratified rename-and-merge migration) + Q9 binding 100% coverage rule.

**Venue: :7999** (AI-discretionary — uses `tempfile.TemporaryDirectory()` for
isolation, no real `io/commons/` mutation, no MCP subprocess involvement).
"""

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest


# Load the migration script as an importable module (it has hyphens in its
# filename, so plain `import` doesn't work — use `importlib`).
_MIGRATION_SCRIPT_PATH = Path( os.environ[ "LUPIN_ROOT" ] ) / "src" / "scripts" / "migrate-dm-topic-case.py"
_spec = importlib.util.spec_from_file_location( "migrate_dm_topic_case", _MIGRATION_SCRIPT_PATH )
migrate_dm_topic_case = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( migrate_dm_topic_case )


# ─── Helpers ───────────────────────────────────────────────────────────────


def _write_topic_file( path: Path, topic: str, entries: list ) -> None:
    """Write a topic file with the given entries (mirrors CommonsStore.post output)."""
    from lupin_mcp.commons_store import (
        ENTRY_SEPARATOR,
        _format_entry,
        _frontmatter_block,
    )
    parts = [ _frontmatter_block( topic, False, "2026-05-17T00:00:00+00:00" ) ]
    for e in entries:
        parts.append( ENTRY_SEPARATOR )
        parts.append( _format_entry(
            ts            = e[ "ts" ],
            session_id    = e[ "session_id" ],
            persona_name  = e[ "persona_name" ],
            persona_icon  = e[ "persona_icon" ],
            persona_color = e[ "persona_color" ],
            body          = e[ "body" ],
            metadata      = e[ "metadata" ],
        ) )
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( "".join( parts ), encoding="utf-8" )


def _make_entry( ts: str, body: str, session_id: str = "abc123", persona: str = "Tiberius" ) -> dict:
    return {
        "ts"            : ts,
        "session_id"    : session_id,
        "persona_name"  : persona,
        "persona_icon"  : "🌑",
        "persona_color" : "#3F51B5",
        "body"          : body,
        "metadata"      : { "kind": "test" },
    }


# ─── TestDeriveCanonicalStem ───────────────────────────────────────────────


class TestDeriveCanonicalStem:
    """The filename-stripping + canonical-derivation helper."""

    def test_already_canonical_lowercase_round_trips( self ):
        assert migrate_dm_topic_case._derive_canonical_stem( "dm-tiberius.md" ) == "tiberius"

    def test_capitalized_variant_lowercases( self ):
        assert migrate_dm_topic_case._derive_canonical_stem( "dm-Tiberius.md" ) == "tiberius"

    def test_space_variant_sanitizes( self ):
        # If such a file existed (pre-fix workaround), the migration would route it
        assert migrate_dm_topic_case._derive_canonical_stem( "dm-Mr Radio.md" ) == "mr_radio"

    def test_unicode_persona_accent_stripped( self ):
        """Phase 3 ripple (intended, plan-aligned): `_derive_canonical_stem` rides
        `_derive_dm_topic`, now routed through the shared `persona_slug` root, so
        accents strip to the canonical store form ("dm-María.md" → "maria", was
        "maría"). BENEFICIAL: accent variants (dm-María vs dm-maria) now group to
        the SAME canonical stem and dedupe-merge, instead of living as split
        topics. Keeping migrate on the shared root (vs a private slugger) is the
        whole point of the normalization plan."""
        assert migrate_dm_topic_case._derive_canonical_stem( "dm-María.md" ) == "maria"

    def test_alias_map_radio_to_mr_radio( self ):
        """`dm-radio` is Tiberius's manual workaround; ALIAS_MAP routes it to canonical."""
        assert migrate_dm_topic_case._derive_canonical_stem( "dm-radio.md" ) == "mr_radio"

    def test_non_dm_filename_raises( self ):
        with pytest.raises( ValueError ):
            migrate_dm_topic_case._derive_canonical_stem( "broadcasts.md" )

    def test_missing_md_suffix_raises( self ):
        with pytest.raises( ValueError ):
            migrate_dm_topic_case._derive_canonical_stem( "dm-tiberius.txt" )


# ─── TestGroupTopicsByCanonical ────────────────────────────────────────────


class TestGroupTopicsByCanonical:
    """Filename grouping logic."""

    def test_groups_case_variants_together( self, tmp_path ):
        files = [
            tmp_path / "dm-tiberius.md",
            tmp_path / "dm-Tiberius.md",
            tmp_path / "dm-TIBERIUS.md",
        ]
        for f in files:
            f.touch()
        groups = migrate_dm_topic_case._group_topics_by_canonical( files )
        assert "tiberius" in groups
        assert len( groups[ "tiberius" ] ) == 3

    def test_separates_distinct_personas( self, tmp_path ):
        files = [
            tmp_path / "dm-tiberius.md",
            tmp_path / "dm-maria.md",
        ]
        for f in files:
            f.touch()
        groups = migrate_dm_topic_case._group_topics_by_canonical( files )
        assert set( groups.keys() ) == { "tiberius", "maria" }

    def test_alias_groups_with_canonical( self, tmp_path ):
        """`dm-radio` and `dm-mr_radio` group together via ALIAS_MAP."""
        files = [
            tmp_path / "dm-radio.md",
            tmp_path / "dm-mr_radio.md",
        ]
        for f in files:
            f.touch()
        groups = migrate_dm_topic_case._group_topics_by_canonical( files )
        assert "mr_radio" in groups
        assert len( groups[ "mr_radio" ] ) == 2

    def test_invalid_filename_skipped_silently( self, tmp_path ):
        good = tmp_path / "dm-tiberius.md"
        good.touch()
        bad  = tmp_path / "not-a-dm-file.md"
        bad.touch()
        groups = migrate_dm_topic_case._group_topics_by_canonical( [ good, bad ] )
        assert "tiberius" in groups
        assert len( groups[ "tiberius" ] ) == 1


# ─── TestEntryParsingAndMerging ────────────────────────────────────────────


class TestEntryParsingAndMerging:
    """Round-trip the entry parser + the dedupe/sort merge."""

    def test_parse_topic_file_returns_entries( self, tmp_path ):
        path = tmp_path / "dm-tiberius.md"
        _write_topic_file( path, "dm-tiberius", [
            _make_entry( "2026-05-17T10:00:00+00:00", "hello" ),
            _make_entry( "2026-05-17T11:00:00+00:00", "world" ),
        ] )
        _, entries = migrate_dm_topic_case._parse_topic_file( path )
        assert len( entries ) == 2
        assert entries[ 0 ][ "body" ] == "hello"
        assert entries[ 1 ][ "body" ] == "world"

    def test_dedupe_key_collides_on_identical_ts_session_body( self ):
        e1 = { "ts": "T1", "sender_session_id": "S1", "body": "B" }
        e2 = { "ts": "T1", "sender_session_id": "S1", "body": "B" }
        assert migrate_dm_topic_case._entry_dedupe_key( e1 ) == migrate_dm_topic_case._entry_dedupe_key( e2 )

    def test_dedupe_key_differs_on_body( self ):
        e1 = { "ts": "T1", "sender_session_id": "S1", "body": "B1" }
        e2 = { "ts": "T1", "sender_session_id": "S1", "body": "B2" }
        assert migrate_dm_topic_case._entry_dedupe_key( e1 ) != migrate_dm_topic_case._entry_dedupe_key( e2 )

    def test_merge_dedupes_and_sorts( self ):
        e1 = _make_entry( "2026-05-17T03:00:00+00:00", "third" )
        e2 = _make_entry( "2026-05-17T01:00:00+00:00", "first" )
        e3 = _make_entry( "2026-05-17T02:00:00+00:00", "second" )
        # e1 also appears in the second list — should dedupe
        merged = migrate_dm_topic_case._merge_entries( [
            [ e1, e2 ],
            [ e3, e1 ],
        ] )
        # Convert to lookup-friendly form
        bodies = [ e[ "body" ] for e in merged ]
        assert bodies == [ "first", "second", "third" ]


# ─── TestMigrateDirectory — the end-to-end behavior ────────────────────────


class TestMigrateDirectory:
    """End-to-end migration scenarios per design §2.2 step coverage."""

    def test_canonical_only_is_noop( self, tmp_path ):
        """Single canonical file with no variants → no-op."""
        path = tmp_path / "dm-tiberius.md"
        _write_topic_file( path, "dm-tiberius", [
            _make_entry( "2026-05-17T10:00:00+00:00", "hello" ),
        ] )
        original_content = path.read_text( encoding="utf-8" )

        stats = migrate_dm_topic_case.migrate_directory( tmp_path, dry_run=False )

        assert stats[ "no_op" ] == 1
        assert stats[ "renamed" ] == 0
        assert stats[ "merged" ] == 0
        assert path.exists()
        assert path.read_text( encoding="utf-8" ) == original_content   # truly untouched

    def test_variant_only_renames_to_canonical( self, tmp_path ):
        """Capitalized variant with NO canonical → rename to canonical."""
        variant = tmp_path / "dm-Tiberius.md"
        _write_topic_file( variant, "dm-Tiberius", [
            _make_entry( "2026-05-17T10:00:00+00:00", "from variant" ),
        ] )
        original_content = variant.read_text( encoding="utf-8" )

        stats = migrate_dm_topic_case.migrate_directory( tmp_path, dry_run=False )

        assert stats[ "renamed" ] == 1
        assert stats[ "no_op" ] == 0
        assert stats[ "merged" ] == 0
        assert not variant.exists()
        canonical = tmp_path / "dm-tiberius.md"
        assert canonical.exists()
        assert canonical.read_text( encoding="utf-8" ) == original_content   # contents preserved

    def test_canonical_plus_variant_merges_by_ts( self, tmp_path ):
        """Both canonical and variant exist → merge entries sorted by ts, unlink variant."""
        canonical = tmp_path / "dm-tiberius.md"
        variant   = tmp_path / "dm-Tiberius.md"
        _write_topic_file( canonical, "dm-tiberius", [
            _make_entry( "2026-05-17T01:00:00+00:00", "first" ),
            _make_entry( "2026-05-17T03:00:00+00:00", "third" ),
        ] )
        _write_topic_file( variant, "dm-Tiberius", [
            _make_entry( "2026-05-17T02:00:00+00:00", "second" ),
        ] )

        stats = migrate_dm_topic_case.migrate_directory( tmp_path, dry_run=False )

        assert stats[ "merged" ] == 1
        assert stats[ "files_unlinked" ] == 1
        assert not variant.exists()
        assert canonical.exists()
        _, entries = migrate_dm_topic_case._parse_topic_file( canonical )
        assert [ e[ "body" ] for e in entries ] == [ "first", "second", "third" ]

    def test_alias_radio_merges_into_mr_radio( self, tmp_path ):
        """`dm-radio` (alias) merges into `dm-mr_radio` (canonical) via ALIAS_MAP."""
        radio = tmp_path / "dm-radio.md"
        canon = tmp_path / "dm-mr_radio.md"
        _write_topic_file( radio, "dm-radio", [
            _make_entry( "2026-05-17T02:00:00+00:00", "from radio alias" ),
        ] )
        _write_topic_file( canon, "dm-mr_radio", [
            _make_entry( "2026-05-17T01:00:00+00:00", "from canonical" ),
        ] )

        stats = migrate_dm_topic_case.migrate_directory( tmp_path, dry_run=False )

        assert stats[ "merged" ] == 1
        assert not radio.exists()
        assert canon.exists()
        _, entries = migrate_dm_topic_case._parse_topic_file( canon )
        bodies = [ e[ "body" ] for e in entries ]
        assert bodies == [ "from canonical", "from radio alias" ]

    def test_multiple_variants_no_canonical_merges_into_new_canonical( self, tmp_path ):
        """Two case-variants with NO canonical → merge into newly-created canonical."""
        v1 = tmp_path / "dm-Tiberius.md"
        v2 = tmp_path / "dm-TIBERIUS.md"
        _write_topic_file( v1, "dm-Tiberius", [
            _make_entry( "2026-05-17T01:00:00+00:00", "from variant 1" ),
        ] )
        _write_topic_file( v2, "dm-TIBERIUS", [
            _make_entry( "2026-05-17T02:00:00+00:00", "from variant 2" ),
        ] )

        stats = migrate_dm_topic_case.migrate_directory( tmp_path, dry_run=False )

        assert stats[ "merged" ] == 1
        canonical = tmp_path / "dm-tiberius.md"
        assert canonical.exists()
        assert not v1.exists()
        assert not v2.exists()

    def test_dry_run_does_not_mutate( self, tmp_path ):
        """Dry-run reports correctly but leaves filesystem unchanged."""
        variant = tmp_path / "dm-Tiberius.md"
        _write_topic_file( variant, "dm-Tiberius", [
            _make_entry( "2026-05-17T10:00:00+00:00", "untouched" ),
        ] )
        original_content = variant.read_text( encoding="utf-8" )

        stats = migrate_dm_topic_case.migrate_directory( tmp_path, dry_run=True )

        assert stats[ "renamed" ] == 1   # would rename
        assert variant.exists()           # but didn't
        canonical = tmp_path / "dm-tiberius.md"
        assert not canonical.exists()
        assert variant.read_text( encoding="utf-8" ) == original_content

    def test_backup_copies_files_before_destructive_op( self, tmp_path ):
        """When `backup_root` is supplied, files are copied before rename/merge."""
        variant = tmp_path / "dm-Tiberius.md"
        _write_topic_file( variant, "dm-Tiberius", [
            _make_entry( "2026-05-17T10:00:00+00:00", "backup me" ),
        ] )
        backup_root = tmp_path / ".backup"

        migrate_dm_topic_case.migrate_directory( tmp_path, dry_run=False, backup_root=backup_root )

        backup_file = backup_root / "dm-Tiberius.md"
        assert backup_file.exists(), "Backup should have preserved the pre-migration file"

    def test_backup_copies_both_files_on_merge( self, tmp_path ):
        """Merge branch: backup copies BOTH the canonical and the variant before merging."""
        canonical = tmp_path / "dm-tiberius.md"
        variant   = tmp_path / "dm-Tiberius.md"
        _write_topic_file( canonical, "dm-tiberius", [
            _make_entry( "2026-05-17T01:00:00+00:00", "canonical orig" ),
        ] )
        _write_topic_file( variant, "dm-Tiberius", [
            _make_entry( "2026-05-17T02:00:00+00:00", "variant orig" ),
        ] )
        backup_root = tmp_path / ".backup"

        migrate_dm_topic_case.migrate_directory( tmp_path, dry_run=False, backup_root=backup_root )

        # Both pre-merge files must exist in backup
        assert ( backup_root / "dm-tiberius.md" ).exists()
        assert ( backup_root / "dm-Tiberius.md" ).exists()

    def test_missing_directory_returns_zero_stats( self, tmp_path ):
        """Missing commons_dir → empty stats, no crash."""
        ghost = tmp_path / "nonexistent"
        stats = migrate_dm_topic_case.migrate_directory( ghost, dry_run=False )
        assert stats == { "scanned": 0, "no_op": 0, "renamed": 0, "merged": 0, "files_unlinked": 0 }

    def test_idempotent_on_clean_tree( self, tmp_path ):
        """Re-running the migration on an already-canonical tree is a no-op."""
        path = tmp_path / "dm-tiberius.md"
        _write_topic_file( path, "dm-tiberius", [
            _make_entry( "2026-05-17T10:00:00+00:00", "stable" ),
        ] )

        # First run
        stats1 = migrate_dm_topic_case.migrate_directory( tmp_path, dry_run=False )
        # Second run
        stats2 = migrate_dm_topic_case.migrate_directory( tmp_path, dry_run=False )

        assert stats1[ "no_op" ] == 1
        assert stats2[ "no_op" ] == 1
        assert stats1[ "renamed" ] == stats2[ "renamed" ] == 0
        assert stats1[ "merged" ] == stats2[ "merged" ] == 0


# ─── TestRebuildTopicFileText ──────────────────────────────────────────────


class TestRebuildTopicFileText:
    """The frontmatter + entry-block reconstruction step."""

    def test_rebuild_with_entries_preserves_first_ts_in_frontmatter( self ):
        entries = [
            _make_entry( "2026-05-17T01:00:00+00:00", "first" ),
            _make_entry( "2026-05-17T02:00:00+00:00", "second" ),
        ]
        # Match the parser's expected shape
        entries_for_rebuild = [
            {
                "ts"                : e[ "ts" ],
                "sender_session_id" : e[ "session_id" ],
                "persona_name"      : e[ "persona_name" ],
                "persona_icon"      : e[ "persona_icon" ],
                "persona_color"     : e[ "persona_color" ],
                "body"              : e[ "body" ],
                "metadata"          : e[ "metadata" ],
            }
            for e in entries
        ]
        text = migrate_dm_topic_case._rebuild_topic_file_text( "dm-tiberius", entries_for_rebuild )
        assert "topic: dm-tiberius" in text
        assert "created: 2026-05-17T01:00:00+00:00" in text   # first entry's ts
        assert "first" in text
        assert "second" in text

    def test_rebuild_with_no_entries_yields_frontmatter_only( self ):
        text = migrate_dm_topic_case._rebuild_topic_file_text( "dm-empty", [ ] )
        assert "topic: dm-empty" in text
        # No `---` separator beyond the frontmatter's own
        assert text.count( "---" ) == 2   # opening + closing of frontmatter

    def test_unicode_topic_round_trips_through_rebuild( self ):
        text = migrate_dm_topic_case._rebuild_topic_file_text( "dm-maría", [ ] )
        assert "topic: dm-maría" in text


# ─── TestNowRunTs ──────────────────────────────────────────────────────────


class TestNowRunTs:
    """The backup-timestamp helper."""

    def test_returns_iso_compact_utc_format( self ):
        """Format is `YYYYMMDDTHHMMSSZ` — filesystem-safe."""
        result = migrate_dm_topic_case._now_run_ts()
        import re
        assert re.match( r"^\d{8}T\d{6}Z$", result ), (
            f"Expected YYYYMMDDTHHMMSSZ format, got {result!r}"
        )


# ─── TestMain — CLI entry point ─────────────────────────────────────────────


class TestMain:
    """Exercise main() via mocked sys.argv. Covers argparse + bootstrap glue."""

    def test_main_dry_run_returns_zero( self, tmp_path, monkeypatch, capsys ):
        # Set up a fixture commons dir
        commons_dir = tmp_path / "io" / "commons"
        commons_dir.mkdir( parents=True )
        variant = commons_dir / "dm-Tiberius.md"
        _write_topic_file( variant, "dm-Tiberius", [
            _make_entry( "2026-05-17T10:00:00+00:00", "test body" ),
        ] )

        monkeypatch.setattr(
            "sys.argv",
            [
                "migrate-dm-topic-case.py",
                "--commons-root", str( commons_dir ),
                "--dry-run",
            ],
        )

        result = migrate_dm_topic_case.main()
        assert result == 0
        # Dry-run leaves filesystem unchanged
        assert variant.exists()
        # Summary printed
        captured = capsys.readouterr()
        assert "Summary" in captured.out
        assert "dry-run" in captured.out

    def test_main_real_run_with_backup( self, tmp_path, monkeypatch, capsys ):
        commons_dir = tmp_path / "io" / "commons"
        commons_dir.mkdir( parents=True )
        variant = commons_dir / "dm-Tiberius.md"
        _write_topic_file( variant, "dm-Tiberius", [
            _make_entry( "2026-05-17T10:00:00+00:00", "test body" ),
        ] )

        monkeypatch.setattr(
            "sys.argv",
            [
                "migrate-dm-topic-case.py",
                "--commons-root", str( commons_dir ),
            ],
        )

        result = migrate_dm_topic_case.main()
        assert result == 0
        # File renamed
        assert not variant.exists()
        assert ( commons_dir / "dm-tiberius.md" ).exists()
        # Backup created somewhere under .pre-migration-backup/
        backup_root_parent = commons_dir / ".pre-migration-backup"
        assert backup_root_parent.exists()
        # Output mentions Backup dir line
        captured = capsys.readouterr()
        assert "Backup dir" in captured.out

    def test_main_no_backup_flag_skips_backup( self, tmp_path, monkeypatch ):
        commons_dir = tmp_path / "io" / "commons"
        commons_dir.mkdir( parents=True )
        variant = commons_dir / "dm-Tiberius.md"
        _write_topic_file( variant, "dm-Tiberius", [
            _make_entry( "2026-05-17T10:00:00+00:00", "no backup" ),
        ] )

        monkeypatch.setattr(
            "sys.argv",
            [
                "migrate-dm-topic-case.py",
                "--commons-root", str( commons_dir ),
                "--no-backup",
            ],
        )

        result = migrate_dm_topic_case.main()
        assert result == 0
        assert ( commons_dir / "dm-tiberius.md" ).exists()
        assert not ( commons_dir / ".pre-migration-backup" ).exists()

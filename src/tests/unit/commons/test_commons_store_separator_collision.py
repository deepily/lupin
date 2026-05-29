"""
Unit tests for the entry-separator collision fix in commons_store.

Per `src/rnd/v0.1.7/2026.05.18-body-display-truncation-investigation.md` —
the legacy `ENTRY_SEPARATOR = "\\n---\\n"` collided with markdown
thematic-break syntax in entry bodies, silently truncating bodies that
contained `---` lines.

This file covers:
- The new `ENTRY_SEPARATOR` doesn't collide with markdown thematic breaks
- `read()` falls back to legacy separator for un-migrated files
- `_warn_orphan_blocks` fires when reading legacy-collision corruption
- Multi-entry files with thematic breaks in bodies round-trip cleanly

Coverage target: 100% lines/branches/functions on the touched code paths
per `feedback_100pct_coverage_multiplexer` (scope-expanded 2026-05-16).
"""

import tempfile
from pathlib import Path

import pytest

from lupin_mcp.commons_store import (
    CommonsStore,
    ENTRY_SEPARATOR,
    LEGACY_ENTRY_SEPARATOR,
    _warn_orphan_blocks,
)


# ---------- Module-level constant checks ----------


def test_entry_separator_is_non_colliding():
    """The new canonical separator MUST NOT contain markdown thematic-break syntax."""
    assert "---" not in ENTRY_SEPARATOR
    assert "<<<__lupin_commons_entry_boundary__>>>" in ENTRY_SEPARATOR


def test_legacy_separator_preserved_for_migration():
    """LEGACY_ENTRY_SEPARATOR is still exported so the migration script + the read() fallback can reference it."""
    assert LEGACY_ENTRY_SEPARATOR == "\n---\n"


# ---------- Round-trip tests against the live store (uses NEW separator on write) ----------


@pytest.fixture
def store():
    """Fresh CommonsStore in a tempdir; auto-cleanup on test exit."""
    with tempfile.TemporaryDirectory() as tmp:
        yield CommonsStore( tmp )


def test_roundtrip_body_with_single_thematic_break( store ):
    """Body with one markdown `---` thematic break must round-trip unchanged."""
    body = "Header text\n\n---\n\nFooter text"
    store.post(
        topic             = "design-notes",
        body              = body,
        sender_session_id = "s1",
        persona_name      = "Tiberius",
        persona_icon      = "🌑",
        persona_color     = "#3F51B5",
    )
    entries = store.read( "design-notes" )
    assert len( entries ) == 1
    assert entries[ 0 ][ "body" ] == body


def test_roundtrip_body_with_multiple_thematic_breaks( store ):
    """Body with multiple `---` thematic breaks must round-trip unchanged."""
    body = "First\n\n---\n\nSecond\n\n---\n\nThird\n\n---\n\nFourth"
    store.post(
        topic             = "design-notes",
        body              = body,
        sender_session_id = "s1",
        persona_name      = "Tiberius",
        persona_icon      = "🌑",
        persona_color     = "#3F51B5",
    )
    entries = store.read( "design-notes" )
    assert len( entries ) == 1
    assert entries[ 0 ][ "body" ] == body


def test_roundtrip_body_without_thematic_break( store ):
    """Regression: bodies without `---` must still work."""
    body = "Simple body with no separators at all."
    store.post(
        topic             = "status",
        body              = body,
        sender_session_id = "s1",
        persona_name      = "Rio",
        persona_icon      = "⚡",
        persona_color     = "#880E4F",
    )
    entries = store.read( "status" )
    assert len( entries ) == 1
    assert entries[ 0 ][ "body" ] == body


def test_multi_entry_with_thematic_breaks_in_bodies( store ):
    """Two entries each containing `---` thematic breaks: both bodies round-trip intact."""
    body_a = "# Section A\n\n---\n\nContent A\n\n## Subsection\n\n---\n\nContent A bottom"
    body_b = "# Section B\n\n---\n\nContent B"
    store.post(
        topic             = "design-notes",
        body              = body_a,
        sender_session_id = "s1",
        persona_name      = "Mr Radio",
        persona_icon      = "🦉",
        persona_color     = "#FFA000",
    )
    store.post(
        topic             = "design-notes",
        body              = body_b,
        sender_session_id = "s2",
        persona_name      = "Tiberius",
        persona_icon      = "🌑",
        persona_color     = "#3F51B5",
    )
    entries = store.read( "design-notes" )
    assert len( entries ) == 2
    # read() returns newest-first
    assert entries[ 0 ][ "body" ] == body_b
    assert entries[ 1 ][ "body" ] == body_a


# ---------- Legacy-separator fallback tests ----------


def test_read_legacy_file_via_fallback( store ):
    """
    A topic file written with the LEGACY separator (no NEW separator present)
    must still be readable. Tests the fallback branch in read().
    """
    # Hand-craft a legacy-format topic file (no NEW separator, just \n---\n)
    topic_path = store.commons_dir / "legacy-topic.md"
    legacy_content = (
        "---\n"
        "topic: legacy-topic\n"
        "reserved: false\n"
        "schema_version: 1\n"
        "created: 2026-05-18T00:00:00.000000+00:00\n"
        "---\n"
        "\n---\n"
        "## 2026-05-18T00:00:01.000000+00:00 | Tiberius 🌑 #s1\n"
        "**metadata**: `{\"_persona_color\": \"#3F51B5\", \"_session_id\": \"s1\"}`\n"
        "\n"
        "Body one without thematic break.\n"
        "\n---\n"
        "## 2026-05-18T00:00:02.000000+00:00 | Rio ⚡ #s2\n"
        "**metadata**: `{\"_persona_color\": \"#880E4F\", \"_session_id\": \"s2\"}`\n"
        "\n"
        "Body two also clean.\n"
    )
    topic_path.write_text( legacy_content, encoding="utf-8" )

    entries = store.read( "legacy-topic" )
    assert len( entries ) == 2
    bodies = sorted( e[ "body" ] for e in entries )
    assert bodies == [ "Body one without thematic break.", "Body two also clean." ]


def test_read_legacy_file_truncates_when_body_has_thematic_break( store ):
    """
    PROOF-OF-BUG TEST: with the legacy separator, an entry whose body contains
    `\\n---\\n` IS truncated on read. This documents the EXACT BUG the
    migration script must close. The post-migration tests (which use NEW
    separator on write) prove the bug is gone for fresh writes.
    """
    topic_path = store.commons_dir / "legacy-collision.md"
    # The "body" intentionally contains `---` to demonstrate the legacy bug
    legacy_content = (
        "---\n"
        "topic: legacy-collision\n"
        "reserved: false\n"
        "schema_version: 1\n"
        "created: 2026-05-18T00:00:00.000000+00:00\n"
        "---\n"
        "\n---\n"
        "## 2026-05-18T00:00:01.000000+00:00 | Mr Radio 🦉 #s1\n"
        "**metadata**: `{\"_persona_color\": \"#FFA000\", \"_session_id\": \"s1\"}`\n"
        "\n"
        "Preamble before thematic break.\n"
        "\n---\n"
        "Content after thematic break that the legacy parser drops.\n"
    )
    topic_path.write_text( legacy_content, encoding="utf-8" )

    entries = store.read( "legacy-collision" )
    # Legacy fallback splits on `\n---\n` which collides with body content
    # → the post-thematic-break content becomes an orphan block (dropped)
    assert len( entries ) == 1
    body = entries[ 0 ][ "body" ]
    assert "Preamble before thematic break." in body
    assert "Content after thematic break" not in body  # the bug being demonstrated


# ---------- Orphan-block warn tests ----------


def test_warn_orphan_blocks_emits_to_stderr( capsys, tmp_path ):
    """_warn_orphan_blocks writes a single-line WARN to stderr."""
    fake_path = tmp_path / "fake.md"
    _warn_orphan_blocks( fake_path, 3 )
    captured = capsys.readouterr()
    assert "[commons_store] WARN" in captured.err
    assert "3 orphan block(s)" in captured.err
    assert "fake.md" in captured.err
    assert "migrate-commons-entry-separator.py" in captured.err
    # stdout should be silent
    assert captured.out == ""


def test_read_emits_warn_when_orphan_blocks_present( capsys, store ):
    """End-to-end: reading a legacy file with thematic-break collision triggers the warn."""
    topic_path = store.commons_dir / "collision-warn.md"
    legacy_content = (
        "---\n"
        "topic: collision-warn\n"
        "reserved: false\n"
        "schema_version: 1\n"
        "created: 2026-05-18T00:00:00.000000+00:00\n"
        "---\n"
        "\n---\n"
        "## 2026-05-18T00:00:01.000000+00:00 | Mr Radio 🦉 #s1\n"
        "**metadata**: `{\"_persona_color\": \"#FFA000\", \"_session_id\": \"s1\"}`\n"
        "\n"
        "Body before break.\n"
        "\n---\n"
        "Orphan content after break.\n"
    )
    topic_path.write_text( legacy_content, encoding="utf-8" )

    store.read( "collision-warn" )
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "orphan block" in captured.err


def test_read_no_warn_when_clean( capsys, store ):
    """Clean read (no orphan blocks) emits NO warn — keeps logs quiet in the happy path."""
    store.post(
        topic             = "clean",
        body              = "simple body",
        sender_session_id = "s1",
        persona_name      = "Rio",
        persona_icon      = "⚡",
        persona_color     = "#880E4F",
    )
    store.read( "clean" )
    captured = capsys.readouterr()
    assert "WARN" not in captured.err


# ---------- Edge cases ----------


def test_roundtrip_body_ending_with_thematic_break( store ):
    """Edge case: body that ends with `---\\n` (no trailing content)."""
    body = "Some text\n\n---\n"
    store.post(
        topic             = "edge",
        body              = body,
        sender_session_id = "s1",
        persona_name      = "Rio",
        persona_icon      = "⚡",
        persona_color     = "#880E4F",
    )
    entries = store.read( "edge" )
    assert len( entries ) == 1
    # body.strip() is called during write; trailing whitespace is consumed
    assert entries[ 0 ][ "body" ].rstrip() == body.rstrip()


def test_roundtrip_body_starting_with_thematic_break( store ):
    """Edge case: body that starts with `---\\n`."""
    body = "---\n\nLeading break, then content."
    store.post(
        topic             = "edge",
        body              = body,
        sender_session_id = "s1",
        persona_name      = "Rio",
        persona_icon      = "⚡",
        persona_color     = "#880E4F",
    )
    entries = store.read( "edge" )
    assert len( entries ) == 1
    assert entries[ 0 ][ "body" ] == body


def test_since_filter_preserves_thematic_break_bodies( store ):
    """Regression: the `since` filter path also returns full bodies (no separate truncation site)."""
    body_a = "First entry\n\n---\n\nWith break"
    body_b = "Second entry\n\n---\n\nAlso with break"
    store.post(
        topic             = "design",
        body              = body_a,
        sender_session_id = "s1",
        persona_name      = "Tiberius",
        persona_icon      = "🌑",
        persona_color     = "#3F51B5",
    )
    entries_all = store.read( "design" )
    first_ts = entries_all[ -1 ][ "ts" ]  # earliest
    store.post(
        topic             = "design",
        body              = body_b,
        sender_session_id = "s2",
        persona_name      = "Rio",
        persona_icon      = "⚡",
        persona_color     = "#880E4F",
    )
    entries_after = store.read( "design", since=first_ts )
    assert len( entries_after ) == 1
    assert entries_after[ 0 ][ "body" ] == body_b

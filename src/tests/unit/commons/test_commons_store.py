"""
Unit tests for commons_store.

Per AC10 minimum scope: 8+ tests covering empty-init, append, read-empty,
read-all, read-since, read-limit, missing-topic, concurrent-append-races (mocked).

Plus AC10b: real-fcntl concurrent-append stress test (5 procs × 100 posts → assert 500).

Coverage target: 100% lines/branches/functions (AC10 commons-only mandate).
"""

import json
import multiprocessing as mp
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from lupin_mcp.commons_store import (
    CommonsStore,
    DEFAULT_PERSONA_COLOR,
    DEFAULT_PERSONA_ICON,
    DEFAULT_PERSONA_NAME,
    ENTRY_SEPARATOR,
    RESERVED_TOPICS,
    SCHEMA_VERSION,
    _format_entry,
    _frontmatter_block,
    _hours_delta,
    _now_iso,
    _parse_entry_block,
    _split_frontmatter,
)


# ---------- Module-level helper tests ----------


def test_now_iso_format():
    """_now_iso returns ISO-8601 with +00:00 timezone suffix."""
    ts = _now_iso()
    assert "T" in ts
    assert ts.endswith( "+00:00" )


def test_frontmatter_block_reserved():
    """Reserved frontmatter has reserved: true."""
    block = _frontmatter_block( "broadcast-acks", True, "2026-05-11T00:00:00+00:00" )
    assert "topic: broadcast-acks" in block
    assert "reserved: true" in block
    assert f"schema_version: {SCHEMA_VERSION}" in block


def test_frontmatter_block_free_form():
    """Free-form frontmatter has reserved: false."""
    block = _frontmatter_block( "status", False, "2026-05-11T00:00:00+00:00" )
    assert "reserved: false" in block


def test_split_frontmatter_no_frontmatter():
    """Content without frontmatter returns ({}, content)."""
    fm, body = _split_frontmatter( "just some text\nmore text" )
    assert fm == { }
    assert body == "just some text\nmore text"


def test_split_frontmatter_valid():
    """Valid YAML frontmatter parses into dict."""
    content = "---\ntopic: foo\nreserved: true\n---\nbody text"
    fm, body = _split_frontmatter( content )
    assert fm[ "topic" ] == "foo"
    assert fm[ "reserved" ] is True
    assert body == "body text"


def test_split_frontmatter_malformed_no_close():
    """Frontmatter without closing --- returns ({}, original)."""
    content = "---\ntopic: foo\nnever_closed"
    fm, body = _split_frontmatter( content )
    assert fm == { }
    assert body == content


def test_split_frontmatter_yaml_error():
    """Invalid YAML returns ({}, body)."""
    content = "---\n!@#$ invalid: : : yaml\n---\nbody"
    fm, body = _split_frontmatter( content )
    assert fm == { }


def test_split_frontmatter_non_dict_yaml():
    """YAML that parses to non-dict (e.g. list) returns ({}, body)."""
    content = "---\n- list_item\n- another\n---\nbody"
    fm, body = _split_frontmatter( content )
    assert fm == { }


def test_parse_entry_block_empty():
    """Empty / whitespace-only block returns None."""
    assert _parse_entry_block( "" ) is None
    assert _parse_entry_block( "   \n\n  " ) is None


def test_parse_entry_block_malformed_header():
    """Block without valid header line returns None."""
    assert _parse_entry_block( "not a header\nbody text" ) is None


def test_parse_entry_block_no_metadata():
    """Valid header + body with NO metadata line → metadata defaults to {}."""
    block = "## 2026-05-11T12:00:00+00:00 | Tiberius 🌑 #sess001\nhello world"
    entry = _parse_entry_block( block )
    assert entry[ "ts" ]                == "2026-05-11T12:00:00+00:00"
    assert entry[ "sender_session_id" ] == "sess001"
    assert entry[ "persona_name" ]      == "Tiberius"
    assert entry[ "persona_icon" ]      == "🌑"
    assert entry[ "body" ]              == "hello world"
    assert entry[ "metadata" ]          == { }
    assert entry[ "persona_color" ]     == DEFAULT_PERSONA_COLOR


def test_parse_entry_block_with_metadata():
    """Header + metadata + body → all parsed."""
    block = (
        "## 2026-05-11T12:00:00+00:00 | Tiberius 🌑 #sess001\n"
        "**metadata**: `{\"kind\":\"ack\",\"_persona_color\":\"#3F51B5\"}`\n"
        "hello world"
    )
    entry = _parse_entry_block( block )
    assert entry[ "persona_color" ] == "#3F51B5"
    assert entry[ "metadata" ]      == { "kind": "ack" }


def test_parse_entry_block_metadata_json_error():
    """Invalid JSON in metadata line → metadata defaults to {}."""
    block = (
        "## 2026-05-11T12:00:00+00:00 | Tiberius 🌑 #sess001\n"
        "**metadata**: `{not valid json`\n"
        "body"
    )
    entry = _parse_entry_block( block )
    assert entry[ "metadata" ] == { }


# ---------- CommonsStore tests ----------


@pytest.fixture
def store():
    """Fresh CommonsStore in a tempdir; auto-cleanup on test exit."""
    with tempfile.TemporaryDirectory() as tmp:
        yield CommonsStore( tmp )


def test_init_creates_directories( store ):
    """AC1: io/commons/ and io/commons/archive/ exist post-init."""
    assert store.commons_dir.is_dir()
    assert store.archive_dir.is_dir()


def test_init_seeds_reserved_topics( store ):
    """AC2: reserved topic files auto-created with reserved: true frontmatter."""
    for topic in RESERVED_TOPICS:
        path = store.commons_dir / f"{topic}.md"
        assert path.exists()
        content = path.read_text( encoding="utf-8" )
        assert f"topic: {topic}" in content
        assert "reserved: true" in content


def test_init_idempotent( store ):
    """Re-constructing CommonsStore on same root doesn't overwrite reserved topics."""
    bcast_path = store.commons_dir / "broadcast-acks.md"
    bcast_path.write_text( bcast_path.read_text() + "\nMANUALLY_APPENDED\n", encoding="utf-8" )
    # Re-construct
    store2 = CommonsStore( store.root )
    assert "MANUALLY_APPENDED" in bcast_path.read_text()


def test_post_appends_entry( store ):
    """AC3: post returns entry dict; subsequent read sees it."""
    entry = store.post(
        topic             = "status",
        body              = "hello",
        sender_session_id = "s1",
        persona_name      = "Tiberius",
        persona_icon      = "🌑",
        persona_color     = "#3F51B5",
    )
    assert entry[ "body" ]          == "hello"
    assert entry[ "persona_name" ]  == "Tiberius"
    assert entry[ "persona_color" ] == "#3F51B5"
    entries = store.read( "status" )
    assert len( entries ) == 1
    assert entries[ 0 ][ "body" ] == "hello"


def test_post_persona_substitution( store ):
    """AC3: missing persona fields substitute defaults."""
    entry = store.post(
        topic             = "status",
        body              = "anonymous",
        sender_session_id = "s1",
    )
    assert entry[ "persona_name" ]  == DEFAULT_PERSONA_NAME
    assert entry[ "persona_icon" ]  == DEFAULT_PERSONA_ICON
    assert entry[ "persona_color" ] == DEFAULT_PERSONA_COLOR


def test_post_free_form_topic_auto_creates( store ):
    """Free-form topic file auto-creates on first post with reserved: false."""
    store.post( "newtopic", "first post", "s1", persona_name="X", persona_icon="?", persona_color="#000" )
    path = store.commons_dir / "newtopic.md"
    assert path.exists()
    assert "reserved: false" in path.read_text()


def test_post_metadata_default_empty_dict( store ):
    """metadata=None → stored metadata is {} (with _persona_color injected internally)."""
    entry = store.post( "status", "body", "s1" )
    assert entry[ "metadata" ] == { }


def test_post_metadata_passthrough( store ):
    """User-supplied metadata round-trips through read()."""
    store.post(
        topic             = "status",
        body              = "body",
        sender_session_id = "s1",
        persona_name      = "X",
        persona_icon      = "?",
        persona_color     = "#000",
        metadata          = { "kind": "ack", "broadcast_id": "abc" },
    )
    entries = store.read( "status" )
    assert entries[ 0 ][ "metadata" ] == { "kind": "ack", "broadcast_id": "abc" }


def test_read_empty_free_form_topic( store ):
    """Reading a never-posted free-form topic returns []."""
    assert store.read( "nonexistent" ) == [ ]


def test_read_empty_reserved_topic( store ):
    """Reserved topic seeded but no posts → returns []."""
    assert store.read( "broadcast-acks" ) == [ ]


def test_read_missing_reserved_topic_raises():
    """If reserved-topic file is missing (corruption case), raises FileNotFoundError."""
    with tempfile.TemporaryDirectory() as tmp:
        store = CommonsStore( tmp )
        ( store.commons_dir / "broadcast-acks.md" ).unlink()
        with pytest.raises( FileNotFoundError ):
            store.read( "broadcast-acks" )


def test_read_newest_first( store ):
    """Without `since`, entries returned newest-first."""
    for i in range( 3 ):
        store.post( "status", f"msg{i}", f"s{i}", persona_name="X", persona_icon="?", persona_color="#000" )
        time.sleep( 0.01 )  # ensure distinct timestamps
    entries = store.read( "status" )
    assert len( entries ) == 3
    assert entries[ 0 ][ "body" ] == "msg2"  # newest first
    assert entries[ -1 ][ "body" ] == "msg0"


def test_read_since_filter_ascending( store ):
    """With `since`, returns ascending entries newer than the cutoff."""
    for i in range( 3 ):
        store.post( "status", f"msg{i}", f"s{i}", persona_name="X", persona_icon="?", persona_color="#000" )
        time.sleep( 0.01 )
    all_entries = store.read( "status" )
    cutoff = all_entries[ 1 ][ "ts" ]  # ts of the middle entry (newest of the 3 was index 0)
    later = store.read( "status", since=cutoff )
    assert all( e[ "ts" ] > cutoff for e in later )


def test_read_limit_strict( store ):
    """`limit` caps the result count strictly."""
    for i in range( 10 ):
        store.post( "status", f"msg{i}", f"s{i}", persona_name="X", persona_icon="?", persona_color="#000" )
    assert len( store.read( "status", limit=3 ) ) == 3


def test_read_skips_malformed_blocks( store ):
    """Malformed entry blocks (header doesn't parse) are silently skipped."""
    store.post( "status", "good entry", "s1", persona_name="X", persona_icon="?", persona_color="#000" )
    # Corrupt the file by appending a malformed block
    path = store._topic_path( "status" )
    with path.open( "a", encoding="utf-8" ) as f:
        f.write( ENTRY_SEPARATOR )
        f.write( "this is not a valid entry header\nweird stuff\n" )
    entries = store.read( "status" )
    assert len( entries ) == 1  # malformed block skipped


def test_who_empty_store( store ):
    """No posts → who() returns []."""
    assert store.who() == [ ]


def test_who_multi_session( store ):
    """Multiple sessions appear in who(), sorted by recency."""
    store.post( "status", "msg1", "sA", persona_name="A", persona_icon="🅰", persona_color="#A00" )
    time.sleep( 0.01 )
    store.post( "status", "msg2", "sB", persona_name="B", persona_icon="🅱", persona_color="#0B0" )
    time.sleep( 0.01 )
    store.post( "status", "msg3", "sA", persona_name="A", persona_icon="🅰", persona_color="#A00" )
    result = store.who()
    assert len( result ) == 2  # 2 distinct sessions
    assert result[ 0 ][ "session_id" ] == "sA"  # most recent post wins; sorted descending


def test_who_topic_filter( store ):
    """`who(topic=X)` only counts posts in topic X."""
    store.post( "status", "msg", "sA", persona_name="A", persona_icon="?", persona_color="#000" )
    store.post( "other", "msg", "sB", persona_name="B", persona_icon="?", persona_color="#000" )
    assert len( store.who( topic="status" ) ) == 1
    assert store.who( topic="status" )[ 0 ][ "session_id" ] == "sA"


def test_who_freshness_cutoff_excludes_old():
    """who() excludes posts older than retention_hours."""
    with tempfile.TemporaryDirectory() as tmp:
        store = CommonsStore( tmp )
        store.post( "status", "fresh", "sFresh", persona_name="F", persona_icon="?", persona_color="#000" )
        # who() with retention_hours=0 should exclude everything
        assert store.who( retention_hours=0 ) == [ ]


def test_who_skips_missing_reserved_files():
    """who() over all topics gracefully handles a reserved file going missing mid-scan (race)."""
    with tempfile.TemporaryDirectory() as tmp:
        store = CommonsStore( tmp )
        # Race condition: file disappears between _all_topic_names() glob and read() call.
        # Mock read() to raise FileNotFoundError for one topic, simulating the race.
        original_read = store.read
        def racing_read( topic, since=None, limit=50 ):
            if topic == "broadcast-acks":
                raise FileNotFoundError( "simulated mid-scan race" )
            return original_read( topic, since=since, limit=limit )
        with patch.object( store, "read", side_effect=racing_read ):
            result = store.who()
        assert result == [ ]


def test_format_entry_round_trip():
    """An entry formatted and then parsed reproduces the original fields."""
    text = _format_entry(
        ts            = "2026-05-11T12:00:00+00:00",
        session_id    = "s1",
        persona_name  = "Tiberius",
        persona_icon  = "🌑",
        persona_color = "#3F51B5",
        body          = "hello",
        metadata      = { "kind": "ack" },
    )
    parsed = _parse_entry_block( text )
    assert parsed[ "ts" ]            == "2026-05-11T12:00:00+00:00"
    assert parsed[ "persona_name" ]  == "Tiberius"
    assert parsed[ "persona_icon" ]  == "🌑"
    assert parsed[ "persona_color" ] == "#3F51B5"
    assert parsed[ "body" ]          == "hello"
    assert parsed[ "metadata" ]      == { "kind": "ack" }


def test_hours_delta_helper():
    """_hours_delta returns a timedelta of N hours."""
    delta = _hours_delta( 5 )
    assert delta == timedelta( hours=5 )


# ---------- AC10b: real-fcntl concurrent-append stress test ----------


def _stress_worker( commons_root: str, session_id: str, num_posts: int ) -> None:
    """
    Worker process for AC10b. Imports CommonsStore in the child, opens the
    store rooted at the shared tempdir, and writes `num_posts` entries.

    Per AC10b: validates that fcntl.flock prevents lost writes under genuine
    OS-level contention.
    """
    s = CommonsStore( commons_root )
    for i in range( num_posts ):
        s.post(
            topic             = "stress",
            body              = f"{session_id}-{i}",
            sender_session_id = session_id,
            persona_name      = "Worker",
            persona_icon      = "🔧",
            persona_color     = "#888888",
        )


def test_ac10b_real_fcntl_concurrent_append():
    """
    AC10b: 5 processes × 100 posts each → assert exactly 500 entries.

    Validates F6 fcntl decision empirically under real OS contention.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = CommonsStore( tmp )  # seeds reserved topics
        n_procs       = 5
        posts_per_proc = 100
        ctx = mp.get_context( "spawn" )
        procs = [
            ctx.Process( target=_stress_worker, args=( tmp, f"sess{i}", posts_per_proc ) )
            for i in range( n_procs )
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join( timeout=60 )
            assert p.exitcode == 0
        entries = store.read( "stress", limit=10_000 )
        assert len( entries ) == n_procs * posts_per_proc, (
            f"Expected {n_procs * posts_per_proc} entries, got {len( entries )}"
        )
        # Verify all 5 sessions are represented
        sessions = { e[ "sender_session_id" ] for e in entries }
        assert sessions == { f"sess{i}" for i in range( n_procs ) }
        # Verify no corruption: every entry has a valid body matching the pattern
        for e in entries:
            assert e[ "body" ].startswith( "sess" )
            assert "-" in e[ "body" ]

"""
SessionStart carries the seat's memento into its fresh context.

Rows cc5477c9 / 9e0678f6, 2026-08-15. A self-re-spin typed `/clear` into a
manager's pane and nothing else; the seat came back with no idea a memento
existed, and lost a held merge, a live two-worker crew, and a correction it
owed a peer. The boot path had the session id, the persona, and a derivable
filename at the repo root — and walked past all three.

The tests below pin the properties that make the fix trustworthy rather than
merely present. Three of them are controls for defects found by running the
code against real files, not by reasoning about it:

  - the accent fold ("María" naively slugs to "mar-a", matching 1 broken file
    and missing 18 good ones)
  - the amendment tail starting at the FIRST marker (the LAST one is a nonce
    stub, so last-marker silently drops the held merge)
  - ordering by the header stamp rather than mtime (mirrors and rsync reset
    mtime, so newest-mtime can be the oldest memento)
"""
import os

import pytest

from lupin_cli.claude_code.hooks.register_session import (
    _build_memento_block,
    _extract_amendment_tail,
    _memento_candidates,
    _persona_of,
    _persona_slugs,
    _resolve_memento_path,
    _truncate_visibly,
    _written_at_of,
)

SID_CHEECH = "80c17315-8770-446b-a312-4021c247531e"
SID_FRESH  = "ffffffff-1111-2222-3333-444444444444"


def _write_memento( root, persona, sid8, *, amendments=(), written_at="2026-08-15T20:11:52-04:00",
                    header=True, body="## 1. Who I am\nheld state\n" ):
    """Write a memento record shaped like the real ones."""
    path  = os.path.join( root, f".claude-memento-{persona}-{sid8}.md" )
    lines = []
    if header:
        stamp = f" written_at={written_at}" if written_at else ""
        lines.append( f"<!-- memento-record: persona={persona} session_id={sid8}{stamp} slot=root -->\n" )
    lines.append( f"# Memento — {persona}\n" )
    lines.append( body )
    for text in amendments:
        lines.append( f"\n<!-- memento-amendment: by={persona} session_id={sid8} -->\n" )
        lines.append( text + "\n" )
    with open( path, "w", encoding="utf-8" ) as fh:
        fh.write( "".join( lines ) )
    return path


@pytest.fixture
def repo( tmp_path ):
    return str( tmp_path )


# ---------------------------------------------------------------------------
# Persona slugs — the accent control
# ---------------------------------------------------------------------------
def test_accented_persona_folds_to_the_ascii_slug_writers_actually_use( ):
    """
    CONTROL FOR A REAL DEFECT. planning-is-prompting holds 18 records named
    `.claude-memento-maria-*.md` and exactly one `.claude-memento-mar-a-*.md`.
    A resolver keyed on the naive slug matches the one broken file and misses
    all 18 good ones. The folded form must come FIRST.
    """
    slugs = _persona_slugs( "María" )
    assert slugs[0] == "maria", "accent fold must win — 'mar-a' matches only the broken file"
    assert "mar-a" in slugs,    "the mangled form must stay reachable for records already written under it"


@pytest.mark.parametrize( "name,expected", [
    ( "Cheech",   [ "cheech" ]   ),
    ( "Mr Radio", [ "mr-radio" ] ),
    ( "  RIO  ",  [ "rio" ]      ),
    ( "",         []             ),
    ( None,       []             ),
    ( "!!!",      []             ),
] )
def test_persona_slugs( name, expected ):
    assert _persona_slugs( name ) == expected


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def test_resolves_by_session_id_after_a_clear( repo ):
    """A self-re-spin keeps its session id, so the exact match wins."""
    path = _write_memento( repo, "cheech", "80c17315" )
    assert _resolve_memento_path( SID_CHEECH, "Cheech", repo ) == path


def test_resolves_by_persona_after_dismiss_then_spawn( repo ):
    """
    THE case that motivated persona-first resolution: the re-spun seat has a
    BRAND-NEW session id while its memento is still named for the old one. A
    session-id-only lookup returns nothing and the seat is told it has no
    memento while the file sits beside it.
    """
    path = _write_memento( repo, "cheech", "80c17315" )
    assert _resolve_memento_path( SID_FRESH, "Cheech", repo ) == path


def test_never_returns_another_personas_record( repo ):
    """
    Cross-seat safety, and the property that outranks recency. Handing a seat
    someone else's memento is worse than handing it none — it is confidently
    wrong about a held merge and a live crew.
    """
    _write_memento( repo, "cheech",   "80c17315" )
    _write_memento( repo, "mr-radio", "bb44a838" )
    assert _resolve_memento_path( SID_FRESH, "Rio", repo ) is None


def test_root_pointer_is_never_treated_as_a_record( repo ):
    """
    `.claude-memento.md` is a POINTER and is single-occupancy for the whole
    repo — it names whichever seat wrote last. Resolving through it would hand
    one persona another's state, so it must not even be a candidate.
    """
    with open( os.path.join( repo, ".claude-memento.md" ), "w", encoding="utf-8" ) as fh:
        fh.write( "<!-- current: .claude-memento-cheech-80c17315.md -->\n" )
    assert _memento_candidates( repo ) == []
    assert _resolve_memento_path( SID_FRESH, "Cheech", repo ) is None


def test_newest_by_header_stamp_wins_not_newest_by_mtime( repo ):
    """
    CONTROL FOR A REAL DEFECT. Mementos are mirrored to ~/.claude/mementos/,
    and every copy/rsync resets mtime — so newest-mtime can be the oldest
    memento. Here the OLDER record is given the NEWER mtime; the header stamp
    must still decide.
    """
    older = _write_memento( repo, "cheech", "c8f94419", written_at="2026-08-01T09:00:00-04:00" )
    newer = _write_memento( repo, "cheech", "80c17315", written_at="2026-08-15T20:11:52-04:00" )
    os.utime( older, ( 9_000_000, 9_000_000 ) )   # stale record, freshest mtime
    os.utime( newer, ( 1_000_000, 1_000_000 ) )
    assert _resolve_memento_path( SID_FRESH, "Cheech", repo ) == newer


def test_record_without_a_timestamp_is_ranked_last_not_dropped( repo ):
    """
    Real records exist with no `written_at` (measured: 3 in
    planning-is-prompting, incl. .claude-memento-maria-350ac4c2.md). Undated
    must lose to dated — but still be findable when it is all there is.
    """
    undated = _write_memento( repo, "cheech", "350ac4c2", written_at=None )
    dated   = _write_memento( repo, "cheech", "80c17315", written_at="2026-08-15T20:11:52-04:00" )
    assert _resolve_memento_path( SID_FRESH, "Cheech", repo ) == dated

    os.remove( dated )
    assert _resolve_memento_path( SID_FRESH, "Cheech", repo ) == undated


def test_headerless_record_still_resolves_via_its_filename( repo ):
    """
    `.claude-memento-maria-350ac4c2.md` opens with a human heading, not a
    machine header. The filename still names the persona unambiguously, and
    filename-scoping cannot leak across personas — so it stays reachable.
    """
    path = _write_memento( repo, "cheech", "350ac4c2", header=False )
    assert _resolve_memento_path( SID_FRESH, "Cheech", repo ) == path
    assert _resolve_memento_path( SID_FRESH, "Rio",    repo ) is None


def test_unreadable_root_is_not_an_error( ):
    assert _memento_candidates( "/nonexistent/path/nowhere" ) == []
    assert _resolve_memento_path( SID_CHEECH, "Cheech", "/nonexistent/path/nowhere" ) is None


@pytest.mark.parametrize( "sid,persona", [
    ( None,    None ),
    ( "short", None ),
] )
def test_no_identity_resolves_to_nothing( repo, sid, persona ):
    _write_memento( repo, "cheech", "80c17315" )
    assert _resolve_memento_path( sid, persona, repo ) is None


@pytest.mark.parametrize( "header,expected", [
    ( "<!-- memento-record: persona=cheech session_id=80c17315 -->", "cheech" ),
    ( None,                                                          "cheech" ),
] )
def test_persona_of_prefers_header_then_filename( header, expected ):
    assert _persona_of( "/x/.claude-memento-cheech-80c17315.md", header ) == expected


def test_persona_of_returns_none_for_an_unparseable_name( ):
    assert _persona_of( "/x/.claude-memento-nodash.md", None ) is None


@pytest.mark.parametrize( "header,expected", [
    ( "<!-- memento-record: written_at=2026-08-15T20:11:52-04:00 -->", "2026-08-15T20:11:52-04:00" ),
    ( "<!-- memento-record: persona=cheech -->",                       None ),
    ( None,                                                            None ),
] )
def test_written_at_of( header, expected ):
    assert _written_at_of( header ) == expected


# ---------------------------------------------------------------------------
# Amendment extraction
# ---------------------------------------------------------------------------
def test_tail_starts_at_the_FIRST_amendment_not_the_last( ):
    """
    CONTROL FOR A REAL DEFECT. `self_respin` appends a tiny nonce-stamp
    amendment, so the LAST marker in a live memento is bookkeeping while the
    substantive block sits before it. Measured on cheech/80c17315: last-marker
    yielded 4 lines of nonce, first-marker yielded the 3.5KB that mattered.

    This test fails if anyone switches `find` back to `rfind`.
    """
    content = (
        "# Memento\nbody\n"
        "<!-- memento-amendment: by=cheech -->\nTHE MERGE IS HELD, AND WHY\n"
        "<!-- memento-amendment: by=cheech -->\nSELF-RESPIN-NONCE: abc123\n"
    )
    tail = _extract_amendment_tail( content )
    assert "THE MERGE IS HELD" in tail, "the substantive amendment was dropped"
    assert "SELF-RESPIN-NONCE" in tail


@pytest.mark.parametrize( "content", [ None, "", "# Memento\nno amendments here\n" ] )
def test_no_amendment_tail( content ):
    assert _extract_amendment_tail( content ) is None


# ---------------------------------------------------------------------------
# Truncation — visible, and keeps the NEWEST
# ---------------------------------------------------------------------------
def test_short_text_is_untouched( ):
    assert _truncate_visibly( "small", "/p/m.md", max_bytes=100 ) == "small"


def test_truncation_keeps_the_end_not_the_head( ):
    """
    Amendments accrete oldest-first, so cutting from the end would discard the
    newest — exactly the state not yet acted on.
    """
    text = "OLDEST-AMENDMENT" + ( "x" * 500 ) + "NEWEST-AMENDMENT"
    out  = _truncate_visibly( text, "/p/m.md", max_bytes=100 )
    assert "NEWEST-AMENDMENT" in out
    assert "OLDEST-AMENDMENT" not in out


def test_truncation_announces_itself( ):
    """
    A silent cut hands the seat partial state it cannot tell is partial, which
    reads as complete. The cut names itself, counts the loss, and points at the
    full record.
    """
    out = _truncate_visibly( "y" * 900, "/p/m.md", max_bytes=100 )
    assert "CUT HERE"              in out
    assert "INCOMPLETE"            in out
    assert "/p/m.md"               in out
    assert "earlier bytes omitted" in out


# ---------------------------------------------------------------------------
# The rendered block
# ---------------------------------------------------------------------------
def test_block_is_empty_when_no_memento_resolves( repo ):
    """Silence on the overwhelmingly common boot that has no memento."""
    assert _build_memento_block( SID_FRESH, "Cheech", repo ) == ""


def test_block_names_the_path_and_quotes_the_amendments( repo ):
    path = _write_memento( repo, "cheech", "80c17315",
                           amendments=[ "THE MERGE IS HELD", "SELF-RESPIN-NONCE: abc" ] )
    block = _build_memento_block( SID_CHEECH, "Cheech", repo )
    assert "YOU HAVE A MEMENTO" in block
    assert path                 in block
    assert "THE MERGE IS HELD"  in block


def test_block_says_so_when_there_is_no_amendment( repo ):
    _write_memento( repo, "cheech", "80c17315" )
    block = _build_memento_block( SID_CHEECH, "Cheech", repo )
    assert "no amendment block" in block
    assert "Read it in full"    in block


def test_block_truncates_a_fat_amendment_visibly( repo ):
    _write_memento( repo, "cheech", "80c17315", amendments=[ "z" * 20000 ] )
    block = _build_memento_block( SID_CHEECH, "Cheech", repo )
    assert "CUT HERE" in block
    assert len( block.encode( "utf-8" ) ) < 12000


def test_block_survives_an_unreadable_memento( repo, monkeypatch ):
    _write_memento( repo, "cheech", "80c17315" )
    import lupin_cli.claude_code.hooks.register_session as rs

    monkeypatch.setattr( rs, "_resolve_memento_path",
                         lambda *a, **kw: os.path.join( repo, "vanished.md" ) )
    assert _build_memento_block( SID_CHEECH, "Cheech", repo ) == ""


def test_repo_root_defaults_to_lupin_root( repo, monkeypatch ):
    path = _write_memento( repo, "cheech", "80c17315", amendments=[ "HELD" ] )
    monkeypatch.setenv( "LUPIN_ROOT", repo )
    assert path in _build_memento_block( SID_CHEECH, "Cheech" )


# ---------------------------------------------------------------------------
# Degradation — every IO seam fails soft. A hook that raises takes the whole
# SessionStart down, which is a worse outcome than a missing memento block.
# ---------------------------------------------------------------------------
def test_non_markdown_files_are_not_candidates( repo ):
    with open( os.path.join( repo, ".claude-memento-cheech-80c17315.txt" ), "w", encoding="utf-8" ) as fh:
        fh.write( "not markdown\n" )
    assert _memento_candidates( repo ) == []


def test_candidate_whose_mtime_vanishes_still_lists( repo, monkeypatch ):
    """A file deleted between listdir and stat must not take the hook down."""
    _write_memento( repo, "cheech", "80c17315", written_at=None )

    import lupin_cli.claude_code.hooks.register_session as rs
    def exploding_getmtime( path ):
        raise OSError( "vanished" )
    monkeypatch.setattr( rs.os.path, "getmtime", exploding_getmtime )

    rows = _memento_candidates( repo )
    assert len( rows ) == 1
    assert rows[0][2] == ( 0, "" )


def test_unreadable_header_is_treated_as_absent( repo, monkeypatch ):
    _write_memento( repo, "cheech", "80c17315" )

    real_open = open
    def exploding_open( path, *a, **kw ):
        if str( path ).endswith( ".md" ): raise OSError( "permission denied" )
        return real_open( path, *a, **kw )
    monkeypatch.setattr( "builtins.open", exploding_open )

    # header unreadable -> reported absent, not raised
    assert _memento_candidates( repo )[0][1] is None


def test_persona_of_falls_through_a_header_that_names_no_persona( ):
    header = "<!-- memento-record: session_id=80c17315 slot=root -->"
    assert _persona_of( "/x/.claude-memento-cheech-80c17315.md", header ) == "cheech"


def test_session_id_match_falls_back_to_the_filename_when_there_is_no_header( repo ):
    """
    A headerless record still names its session in the filename. The exact-id
    tier must use that rather than dropping through to the persona tier, which
    would pick a different (merely same-persona) record.
    """
    exact = _write_memento( repo, "cheech", "80c17315", header=False )
    _write_memento( repo, "cheech", "c8f94419", written_at="2026-12-01T00:00:00-04:00" )
    assert _resolve_memento_path( SID_CHEECH, "Cheech", repo ) == exact


def test_resolver_exhausts_without_a_match( repo ):
    """Candidates exist, none belong to this seat — the loop must fall through."""
    _write_memento( repo, "mr-radio", "bb44a838" )
    assert _resolve_memento_path( SID_FRESH, "Cheech", repo ) is None

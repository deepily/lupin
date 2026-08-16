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
    _names_this_seat,
    _persona_of,
    _persona_slugs,
    _resolve_memento_path,
    _resolve_repo_root,
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


# ---------------------------------------------------------------------------
# The io slot — the third cause of a blank rehydrate
# ---------------------------------------------------------------------------
def _write_io_memento( root, persona, sid8, *, amendments=(), written_at="2026-08-15T19:12:47-04:00" ):
    """A record in the io slot: `io/mementos/<persona>-<sid8>.md`, no filename prefix."""
    slot = os.path.join( root, "io", "mementos" )
    os.makedirs( slot, exist_ok=True )
    path = os.path.join( slot, f"{persona}-{sid8}.md" )
    body = [ f"<!-- memento-record: persona={persona} session_id={sid8} written_at={written_at} slot=io -->\n",
             f"# Memento — {persona}\nheld state\n" ]
    for text in amendments:
        body.append( f"\n<!-- memento-amendment: by={persona} session_id={sid8} -->\n{text}\n" )
    with open( path, "w", encoding="utf-8" ) as fh:
        fh.write( "".join( body ) )
    return path


def test_resolves_a_record_in_the_io_slot( repo ):
    """
    CONTROL FOR A REAL DEFECT (Rachel 🕊️, reproduced against 8b9a10e9).

    There are TWO slot families. The first cut enumerated only repo-root files
    named `.claude-memento-*`, so a record at `io/mementos/<persona>-<sid8>.md`
    — hers was a real 23KB memento whose own header says `slot=io` — was
    invisible, and she rehydrated blank on the third distinct cause in one
    night.
    """
    path = _write_io_memento( repo, "rachel", "9eb9253c", amendments=[ "BOARD IS 5 ROWS" ] )
    assert _resolve_memento_path( "9eb9253c-3dc1-45a7-a148-37b03964915a", "Rachel", repo ) == path
    assert "BOARD IS 5 ROWS" in _build_memento_block( "9eb9253c-3dc1-45a7-a148-37b03964915a", "Rachel", repo )


def test_io_slot_resolves_by_persona_after_a_respawn( repo ):
    """Same persona-carries-over rule as the root slot, in the other family."""
    path = _write_io_memento( repo, "rachel", "9eb9253c" )
    assert _resolve_memento_path( SID_FRESH, "Rachel", repo ) == path


def test_io_slot_never_leaks_across_personas( repo ):
    _write_io_memento( repo, "rachel", "9eb9253c" )
    _write_io_memento( repo, "arnold", "ca8fbfcc" )
    assert _resolve_memento_path( SID_FRESH, "Rio", repo ) is None


def test_both_slots_are_searched_and_the_newest_wins( repo ):
    """A seat can hold records in BOTH families; recency still decides."""
    _write_memento(    repo, "rachel", "aaaaaaaa", written_at="2026-08-01T09:00:00-04:00" )
    io_new = _write_io_memento( repo, "rachel", "9eb9253c", written_at="2026-08-15T19:12:47-04:00" )
    assert _resolve_memento_path( SID_FRESH, "Rachel", repo ) == io_new


def test_a_bare_persona_filename_resolves( repo ):
    """`io/mementos/arnold.md` — no session id in the name at all."""
    slot = os.path.join( repo, "io", "mementos" )
    os.makedirs( slot, exist_ok=True )
    path = os.path.join( slot, "arnold.md" )
    with open( path, "w", encoding="utf-8" ) as fh:
        fh.write( "<!-- memento-record: persona=arnold session_id=ca8fbfcc written_at=2026-08-15T18:37:00-04:00 slot=io -->\n# Memento\n" )
    assert _resolve_memento_path( SID_FRESH, "arnold", repo ) == path


def test_unrelated_files_in_the_io_slot_are_not_candidates( repo ):
    """
    The pre-filter must not admit another seat's record. The io slot holds
    hundreds of files fleet-wide, so a resolver that reads them all is both
    slow and one bad header away from handing over the wrong state.
    """
    _write_io_memento( repo, "rio",    "11111111" )
    _write_io_memento( repo, "arnold", "22222222" )
    rows = _memento_candidates( repo, sid8=None, slugs=[ "rachel" ] )
    assert rows == []


def test_the_pre_filter_bounds_the_boot_cost( repo ):
    """
    Every session in the fleet pays this on boot. With no pre-filter the
    resolver would open every record in the slot; with one it opens only the
    seat's own. This asserts the mechanism, not a wall-clock number.
    """
    for i in range( 30 ):
        _write_io_memento( repo, f"other{i}", f"{i:08d}" )
    mine = _write_io_memento( repo, "rachel", "9eb9253c" )

    filtered = _memento_candidates( repo, sid8="9eb9253c", slugs=[ "rachel" ] )
    assert [ p for p, _, _ in filtered ] == [ mine ]

    # Unfiltered sees all 31 — which is exactly the cost the pre-filter avoids,
    # and the reason resolution must never be called without an identity.
    assert len( _memento_candidates( repo ) ) == 31


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


def test_a_name_with_no_session_id_is_still_a_persona( ):
    """
    Rewritten when the io slot landed: `arnold.md` and
    `.claude-memento-nodash.md` are legitimate bare-persona shapes, so a
    missing session id is no longer unparseable. The old assertion encoded the
    root-slot-only rule.
    """
    assert _persona_of( "/x/.claude-memento-nodash.md", None ) == "nodash"
    assert _persona_of( "/x/io/mementos/arnold.md",     None ) == "arnold"


def test_persona_of_returns_none_when_there_is_no_name_at_all( ):
    assert _persona_of( "/x/.claude-memento-.md", None ) is None


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
    """
    Wording tightened 2026-08-15 after Rachel's three-seat measurement — see
    test_a_record_with_no_amendment_is_flagged_not_congratulated for why the
    soft version was a hazard. This keeps the original intent (the seat is told
    the record is thin) against the current, louder text.
    """
    _write_memento( repo, "cheech", "80c17315" )
    block = _build_memento_block( SID_CHEECH, "Cheech", repo )
    assert "NO amendment block"      in block
    assert "Read the full record"    in block


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


def test_root_resolves_from_the_seats_own_cwd_not_lupin_root( repo, monkeypatch ):
    """
    CONTROL FOR A REAL DEFECT (María 🌸, reproduced against 8ff014e2).

    This hook is installed fleet-wide, not only in lupin. The first cut read
    the root from LUPIN_ROOT, so every non-lupin seat searched lupin's
    directory — where its memento does not live — and rehydrated blank with its
    own record sitting beside it. That was her stall.

    Here LUPIN_ROOT deliberately points somewhere ELSE, so pointing at the env
    var can never silently win again.
    """
    other = str( repo )
    path  = _write_memento( other, "maria", "e02f9c93", amendments=[ "HELD" ] )
    os.mkdir( os.path.join( other, ".git" ) )

    monkeypatch.setenv( "LUPIN_ROOT", "/somewhere/else/entirely" )
    block = _build_memento_block( "e02f9c93-0351-4508-ac0b-ddf11ec1900e", "María", cwd=other )
    assert path in block, "resolution followed LUPIN_ROOT instead of the seat's own repo"


def test_root_walks_up_to_the_nearest_git_ancestor( repo ):
    """cwd is usually a subdirectory, not the repo root itself."""
    os.mkdir( os.path.join( repo, ".git" ) )
    nested = os.path.join( repo, "src", "deep", "nested" )
    os.makedirs( nested )
    assert _resolve_repo_root( nested ) == repo


def test_root_accepts_a_git_FILE_not_only_a_directory( repo ):
    """
    A worktree's `.git` is a FILE, not a directory — `exists`, never `isdir`.
    Every spawned worker runs in a worktree, so an isdir check would skip the
    whole crew.
    """
    with open( os.path.join( repo, ".git" ), "w", encoding="utf-8" ) as fh:
        fh.write( "gitdir: /somewhere/.git/worktrees/wt\n" )
    assert _resolve_repo_root( repo ) == repo


def test_root_falls_back_to_lupin_root_when_no_git_ancestor( tmp_path, monkeypatch ):
    """An unrooted cwd still has to produce an answer rather than an error."""
    monkeypatch.setenv( "LUPIN_ROOT", "/fallback/root" )
    assert _resolve_repo_root( str( tmp_path ) ) == "/fallback/root"


def test_root_handles_an_unusable_cwd( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", "/fallback/root" )

    import lupin_cli.claude_code.hooks.register_session as rs
    def exploding_abspath( p ):
        raise OSError( "no such cwd" )
    monkeypatch.setattr( rs.os.path, "abspath", exploding_abspath )

    assert _resolve_repo_root( "/gone" ) == "/fallback/root"


def test_root_defaults_to_process_cwd_when_none_given( repo, monkeypatch ):
    os.mkdir( os.path.join( repo, ".git" ) )
    monkeypatch.chdir( repo )
    assert _resolve_repo_root( None ) == repo


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


def test_a_non_markdown_name_is_never_this_seats( ):
    """The cheap filter rejects on extension before it looks at identity."""
    assert _names_this_seat( "rachel-9eb9253c.txt", "9eb9253c", [ "rachel" ] ) is False
    assert _names_this_seat( "rachel-9eb9253c.md",  "9eb9253c", [ "rachel" ] ) is True


def test_the_same_record_reachable_twice_is_listed_once( repo ):
    """
    The mirror and the in-repo slot can be the same file. Listing it twice
    would let one record outvote another purely by being reachable by two
    paths, so dedupe is on realpath, not on name.
    """
    real = _write_io_memento( repo, "rachel", "9eb9253c" )
    slot = os.path.join( repo, "io", "mementos" )
    os.symlink( real, os.path.join( slot, "rachel-mirror.md" ) )

    rows = _memento_candidates( repo, sid8="9eb9253c", slugs=[ "rachel" ] )
    assert len( rows ) == 1, "the same record was counted twice"


def test_persona_search_exhausts_every_slug_without_a_match( repo ):
    """Both accent forms tried, neither present — falls through to None."""
    _write_io_memento( repo, "arnold", "ca8fbfcc" )
    assert _resolve_memento_path( SID_FRESH, "María", repo ) is None


def test_header_persona_overrules_a_misleading_filename( repo ):
    """
    Closes the last branch, and pins the property that matters: a file NAMED
    for one persona whose header declares another belongs to the header's
    owner. The cheap filename filter admits it; the header confirmation is what
    refuses it. Without that split, renaming a file would hand over its
    contents.
    """
    slot = os.path.join( repo, "io", "mementos" )
    os.makedirs( slot, exist_ok=True )
    path = os.path.join( slot, "maria-9eb9253c.md" )
    with open( path, "w", encoding="utf-8" ) as fh:
        fh.write( "<!-- memento-record: persona=rachel session_id=9eb9253c written_at=2026-08-15T19:12:47-04:00 slot=io -->\n# Memento\n" )

    # The name says maría; the header says rachel. María must NOT get it.
    assert _resolve_memento_path( SID_FRESH, "María", repo ) is None

    # Rachel reaches it by SESSION ID, which the filename also carries.
    assert _resolve_memento_path( "9eb9253c-3dc1-45a7-a148-37b03964915a", "Rachel", repo ) == path

    # THE LIMITATION, STATED RATHER THAN HIDDEN: with a fresh session id and
    # only a persona to go on, the true owner cannot reach a record filed under
    # someone else's name — the filename pre-filter never admits it. That is the
    # price of not reading 679 headers on every boot. It fails CLOSED (no
    # memento), never open (someone else's memento), which is the safe
    # direction; a record filed under the wrong persona is a writer-side bug.
    assert _resolve_memento_path( SID_FRESH, "Rachel", repo ) is None


def test_the_mirror_root_slot_is_searched_too( repo, monkeypatch, tmp_path ):
    """
    CONTROL FOR THE FOURTH SLOT (Rachel 🕊️, 2026-08-15). Records also live at
    `~/.claude/mementos/<project>/.claude-memento-<persona>-<sid8>.md` — four of
    hers do. Missing it is the same blank rehydrate one directory over.

    Note this slot uses the DOTTED filename shape while the io slot beneath it
    uses the bare one, so a directory cannot be trusted to imply its own naming
    convention.
    """
    home    = tmp_path / "fakehome"
    project = os.path.basename( os.path.normpath( repo ) )
    mirror  = home / ".claude" / "mementos" / project
    mirror.mkdir( parents=True )
    path = mirror / ".claude-memento-rachel-35d5ced0.md"
    path.write_text(
        "<!-- memento-record: persona=rachel session_id=35d5ced0 written_at=2026-08-01T18:36:00-04:00 slot=root -->\n"
        "# Memento\n<!-- memento-amendment: by=rachel -->\nMIRROR ROOT RECORD\n",
        encoding="utf-8" )

    monkeypatch.setenv( "HOME", str( home ) )
    assert _resolve_memento_path( "35d5ced0-0000-0000-0000-000000000000", "Rachel", repo ) == str( path )
    assert "MIRROR ROOT RECORD" in _build_memento_block( "35d5ced0-0000-0000-0000-000000000000", "Rachel", repo )
    assert _resolve_memento_path( SID_FRESH, "Rio", repo ) is None


# ---------------------------------------------------------------------------
# A near-blank return must not wear a success banner
# ---------------------------------------------------------------------------
def test_a_record_with_no_amendment_is_flagged_not_congratulated( repo ):
    """
    CONTROL FOR A REAL HAZARD (Rachel 🕊️, 2026-08-15). Three seats re-spun;
    two of their records carried no amendment, so the block was ~440 bytes
    against ~8,700 for one with a tail — and it arrived under a "YOU HAVE A
    MEMENTO" banner. A seat gets a pointer, no state, and no signal anything is
    missing. A near-blank rehydrate wearing a green banner is worse than a red
    one, because nobody goes looking.
    """
    _write_io_memento( repo, "tiffany", "74225471" )   # no amendments
    block = _build_memento_block( SID_FRESH, "Tiffany", repo )

    assert "CARRIES NO STATE"    in block
    assert "NEAR-BLANK RETURN"   in block
    assert "YOU HAVE A MEMENTO" not in block, "a stateless record must not read as success"
    assert "the store is the authority" in block, "must point at the surface that IS current"


def test_a_record_with_an_amendment_keeps_the_success_banner( repo ):
    """The warning must not fire on the good case, or it stops meaning anything."""
    _write_io_memento( repo, "rachel", "9eb9253c", amendments=[ "BOARD IS 5 ROWS" ] )
    block = _build_memento_block( SID_FRESH, "Rachel", repo )

    assert "YOU HAVE A MEMENTO" in block
    assert "CARRIES NO STATE"   not in block


def test_the_block_always_states_when_the_record_was_written( repo ):
    """
    Staleness is invisible without it: a record written 20 minutes ago and one
    written three days ago are the same pointer on the page.
    """
    _write_io_memento( repo, "rachel", "9eb9253c",
                       amendments=[ "HELD" ], written_at="2026-08-15T19:12:47-04:00" )
    assert "written 2026-08-15T19:12:47-04:00" in _build_memento_block( SID_FRESH, "Rachel", repo )


def test_an_undated_record_says_so_rather_than_omitting_it( repo ):
    """Silence about the date reads as 'recent'; UNDATED reads as 'unknown'."""
    path = _write_memento( repo, "cheech", "80c17315", written_at=None, amendments=[ "HELD" ] )
    assert path  # written to the root slot, no written_at stamp
    block = _build_memento_block( SID_CHEECH, "Cheech", repo )
    assert "UNDATED" in block

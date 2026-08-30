"""
test_memento_slot.py — the slot check must be CAPABLE OF FAILING (row 8068c65e).

WHY THE NEGATIVE CONTROLS ARE THE POINT OF THIS FILE, AND NOT AN EXTRA. The check
being replaced could not fail: it verified the memento by the path the caller handed
it, so its success criterion came from the same caller whose mistake it was meant to
catch. A test suite that only proves the new check PASSES on a correct memento would
prove exactly what the old check also proved — nothing. So every leg here is exercised
in both directions, and the two misplacements that actually happened on 2026-08-30 are
replayed by name as fixtures:

  * POCHOLO 📣 — correct tool, correct header, WRONG SLOT. He wrote `--slot io` on
    08-29 and `--slot root` on 08-30; the reap reads `io`, so the 08-30 memento was
    invisible to the door that needed it while the `io` pointer still named the
    08-29 session. (Case supplied by Pocholo himself, who offered the two writes as
    a regression pair.)
  * TIBERIUS 👑 — a bare `~/.claude/mementos/<persona>-<sid>-memento.md`. That
    directory IS memento_io's mirror home, but a mirror lives at
    `<mirror_home>/<repo>/<record-path>`; a file at its bare top has no repo segment
    and is not a mirror. Neither slot, no reader.

Both fixtures assert on the FAILURE and on the reason naming the acceptable targets —
a check that fails silently, or fails without saying where the file should have gone,
sends the seat back to guessing.
"""

import datetime

import pytest

import lupin_mcp.memento_slot as ms


UTC = datetime.timezone.utc


def _dt( minute ):
    return datetime.datetime( 2026, 8, 30, 19, minute, 0, tzinfo=UTC )


_BODY = ( "board state: row 8068c65e in progress, manager mr radio, the slot check "
          "derives its target from seat identity rather than the caller.\n" ) * 12


def _record_text( slug, sid8, written_at ):
    return (
        f"<!-- memento-record: persona={slug} session_id={sid8} "
        f"written_at={written_at.isoformat()} slot=root -->\n"
        f"# Memento — {slug} ({sid8})\n" + _BODY
    )


def _pointer_text( record_name, record_text ):
    return (
        "<!-- MEMENTO POINTER — NOT THE RECORD. Safe to overwrite; it destroys nothing. -->\n"
        f"<!-- current: {record_name} -->\n" + record_text
    )


def _fs( mapping ):
    """A read_text_fn over an in-memory {path: text}; anything absent reads None."""
    return lambda path: mapping.get( str( path ) )


def _root_slot_fs( repo_root, persona="chloe", sid="5288a6e5", written_at=None ):
    """Ensures: ( read_text_fn, pointer_path_str ) for a well-formed root slot."""
    written_at = written_at if written_at is not None else _dt( 20 )
    pointer    = ms.slot_pointer_path( repo_root, persona )
    record     = ms.slot_record_path( repo_root, persona, sid )
    rec_text   = _record_text( ms.persona_slug( persona ), sid[ :8 ], written_at )
    return _fs( {
        str( record ) : rec_text,
        str( pointer ): _pointer_text( record.name, rec_text ),
    } ), str( pointer )


# ---------------------------------------------------------------------------
# Path derivation — both slots, and a refusal on an unknown one
# ---------------------------------------------------------------------------
def test_root_slot_pointer_is_the_persona_less_shared_file():
    # The collision that motivates leg 2: every persona in a repo shares this one file.
    a = ms.slot_pointer_path( "/repo", "Pocholo 📣", ms.SLOT_ROOT )
    b = ms.slot_pointer_path( "/repo", "Mr. Radio 🦉", ms.SLOT_ROOT )
    assert str( a ) == "/repo/.claude-memento.md"
    assert a == b


def test_io_slot_pointer_is_per_persona():
    p = ms.slot_pointer_path( "/repo", "Mr. Radio 🦉", ms.SLOT_IO )
    assert str( p ) == "/repo/io/mementos/mr-radio.md"


def test_root_slot_record_carries_persona_and_sid():
    r = ms.slot_record_path( "/repo", "Pocholo 📣", "FD1BF2E0abc", ms.SLOT_ROOT )
    assert str( r ) == "/repo/.claude-memento-pocholo-fd1bf2e0.md"


def test_io_slot_record_carries_persona_and_sid():
    r = ms.slot_record_path( "/repo", "Pocholo 📣", "7b4e09c5", ms.SLOT_IO )
    assert str( r ) == "/repo/io/mementos/pocholo-7b4e09c5.md"


def test_record_path_tolerates_a_missing_sid():
    assert str( ms.slot_record_path( "/repo", "chloe", None ) ) == "/repo/.claude-memento-chloe-.md"


def test_pointer_path_refuses_an_unknown_slot():
    with pytest.raises( ValueError ) as exc:
        ms.slot_pointer_path( "/repo", "chloe", "tmp" )
    assert "unknown memento slot" in str( exc.value )


def test_record_path_refuses_an_unknown_slot():
    with pytest.raises( ValueError ):
        ms.slot_record_path( "/repo", "chloe", "sid1", "tmp" )


def test_acceptable_targets_returns_pointer_then_record():
    pointer, record = ms.acceptable_slot_targets( "/repo", "chloe", "5288a6e5" )
    assert str( pointer ) == "/repo/.claude-memento.md"
    assert str( record )  == "/repo/.claude-memento-chloe-5288a6e5.md"


# ---------------------------------------------------------------------------
# resolve_repo_root — refuses rather than guessing
# ---------------------------------------------------------------------------
def test_resolve_repo_root_returns_the_git_toplevel():
    assert ms.resolve_repo_root( start="/repo/src", run_fn=lambda argv, cwd: "/repo\n" ) == "/repo"


def test_resolve_repo_root_passes_start_through_as_cwd():
    seen = {}
    def run( argv, cwd ):
        seen[ "argv" ] = argv
        seen[ "cwd" ]  = cwd
        return "/repo\n"
    ms.resolve_repo_root( start="/repo/src", run_fn=run )
    assert seen[ "cwd" ]  == "/repo/src"
    assert seen[ "argv" ] == [ "git", "rev-parse", "--show-toplevel" ]


def test_resolve_repo_root_defaults_start_to_cwd( monkeypatch ):
    monkeypatch.chdir( "/tmp" )
    seen = {}
    ms.resolve_repo_root( run_fn=lambda argv, cwd: seen.setdefault( "cwd", cwd ) or "/repo" )
    assert seen[ "cwd" ] == "/tmp"


def test_resolve_repo_root_is_none_when_git_fails():
    assert ms.resolve_repo_root( start="/x", run_fn=lambda argv, cwd: None ) is None


def test_resolve_repo_root_is_none_on_blank_output():
    assert ms.resolve_repo_root( start="/x", run_fn=lambda argv, cwd: "   \n" ) is None


def test_resolve_repo_root_is_none_when_git_raises():
    def boom( argv, cwd ):
        raise OSError( "git not on PATH" )
    assert ms.resolve_repo_root( start="/x", run_fn=boom ) is None


# ---------------------------------------------------------------------------
# _same_file
# ---------------------------------------------------------------------------
def test_same_file_matches_through_dot_segments( tmp_path ):
    real = tmp_path / ".claude-memento.md"
    real.write_text( "x" )
    assert ms._same_file( real, tmp_path / "sub" / ".." / ".claude-memento.md" ) is True


def test_same_file_rejects_different_paths( tmp_path ):
    assert ms._same_file( tmp_path / "a.md", tmp_path / "b.md" ) is False


def test_same_file_is_false_rather_than_raising_on_garbage():
    assert ms._same_file( None, "/repo/.claude-memento.md" ) is False


def test_same_file_is_false_rather_than_raising_on_an_unresolvable_path():
    """
    A NUL byte makes realpath raise rather than answer. `memento_path` is caller-supplied
    text, so this must answer "not the same file" instead of turning a bad path into a
    crash inside the very guard that exists to check caller-supplied paths.
    """
    assert ms._same_file( "/repo/\x00bad.md", "/repo/.claude-memento.md" ) is False


# ---------------------------------------------------------------------------
# verify_memento_at_slot — the happy path
# ---------------------------------------------------------------------------
def test_verify_passes_for_the_pointer_at_the_slot( tmp_path ):
    read, pointer = _root_slot_fs( tmp_path )
    ok, reason = ms.verify_memento_at_slot(
        pointer, repo_root=str( tmp_path ), persona="chloe", session_id="5288a6e5",
        now=_dt( 25 ), read_text_fn=read,
    )
    assert ok is True
    assert "at the 'root' slot" in reason


def test_verify_passes_for_this_sessions_record_at_the_slot( tmp_path ):
    read, _ = _root_slot_fs( tmp_path )
    record  = ms.slot_record_path( tmp_path, "chloe", "5288a6e5" )
    ok, _ = ms.verify_memento_at_slot(
        str( record ), repo_root=str( tmp_path ), persona="chloe", session_id="5288a6e5",
        now=_dt( 25 ), read_text_fn=read,
    )
    assert ok is True


# ---------------------------------------------------------------------------
# 🔴 NEGATIVE CONTROLS — the check must FAIL on a memento written to the wrong place
# ---------------------------------------------------------------------------
def test_negative_control_pocholo_wrote_the_root_slot_while_the_reap_reads_io( tmp_path ):
    """
    Pocholo's real 2026-08-30 case. His `.claude-memento-pocholo-fd1bf2e0.md` is a
    WELL-FORMED root-slot record — right tool, right header, mirrored — and it is
    still invisible to the `io` door. Checked against the `io` slot it must FAIL, and
    the reason must name where the file should have gone.
    """
    written = _dt( 20 )
    root_record = tmp_path / ".claude-memento-pocholo-fd1bf2e0.md"
    root_record.write_text( _record_text( "pocholo", "fd1bf2e0", written ) )

    ok, reason = ms.verify_memento_at_slot(
        str( root_record ), repo_root=str( tmp_path ), persona="Pocholo 📣",
        session_id="fd1bf2e0", now=_dt( 25 ),
        read_text_fn=lambda p: root_record.read_text() if str( p ) == str( root_record ) else None,
        slot=ms.SLOT_IO,
    )
    assert ok is False
    assert "not at this seat's 'io' slot" in reason
    assert "io/mementos/pocholo.md" in reason              # the pointer it should be
    assert "io/mementos/pocholo-fd1bf2e0.md" in reason     # the record it should be
    assert "--slot io" in reason                           # and how to get it there


def test_negative_control_tiberius_wrote_the_bare_mirror_home( tmp_path ):
    """
    Tiberius's real 2026-08-30 case: `~/.claude/mementos/tiberius-f032ae9f-memento.md`.
    That directory is memento_io's MIRROR_HOME, but a mirror lives at
    <mirror_home>/<repo>/<record-path>. A file at its bare top is neither slot nor
    mirror — and self_respin reported success on it.
    """
    stray = tmp_path / "home" / ".claude" / "mementos" / "tiberius-f032ae9f-memento.md"
    stray.parent.mkdir( parents=True )
    stray.write_text( _record_text( "tiberius", "f032ae9f", _dt( 20 ) ) )

    repo = tmp_path / "repo"
    repo.mkdir()
    ok, reason = ms.verify_memento_at_slot(
        str( stray ), repo_root=str( repo ), persona="Tiberius 👑",
        session_id="f032ae9f", now=_dt( 25 ), read_text_fn=lambda p: None,
    )
    assert ok is False
    assert "not at this seat's 'root' slot" in reason


def test_negative_control_leg2_catches_the_shared_root_pointer_collision( tmp_path ):
    """
    Leg 1 alone is not enough. The root pointer is PERSONA-LESS, so a seat's record
    can sit correctly at its own derived path while the pointer a naive reader follows
    names SOMEBODY ELSE — measured 2026-08-30, Pocholo took `.claude-memento.md` at
    14:41 and Mr. Radio took it back at 15:20. Leg 1 passes here; leg 2 must not.
    """
    written = _dt( 20 )
    mine    = ms.slot_record_path( tmp_path, "pocholo", "fd1bf2e0" )
    theirs  = ms.slot_record_path( tmp_path, "mr radio", "93a8751c" )
    pointer = ms.slot_pointer_path( tmp_path, "pocholo" )
    their_text = _record_text( "mr-radio", "93a8751c", written )
    read = _fs( {
        str( mine )   : _record_text( "pocholo", "fd1bf2e0", written ),
        str( theirs ) : their_text,
        str( pointer ): _pointer_text( theirs.name, their_text ),   # the pointer names THEM
    } )

    ok, reason = ms.verify_memento_at_slot(
        str( mine ), repo_root=str( tmp_path ), persona="Pocholo 📣",
        session_id="fd1bf2e0", now=_dt( 25 ), read_text_fn=read,
    )
    assert ok is False
    assert "fails the reap's memento proof" in reason
    assert "93a8751c" in reason and "fd1bf2e0" in reason


def test_negative_control_another_sessions_record_for_the_same_persona( tmp_path ):
    """A stale record from the SAME persona's earlier session is not this session's."""
    read, _ = _root_slot_fs( tmp_path )
    stale   = ms.slot_record_path( tmp_path, "chloe", "7b4e09c5" )
    ok, reason = ms.verify_memento_at_slot(
        str( stale ), repo_root=str( tmp_path ), persona="chloe", session_id="5288a6e5",
        now=_dt( 25 ), read_text_fn=read,
    )
    assert ok is False
    assert "not at this seat's 'root' slot" in reason


def test_verify_refuses_when_the_repo_root_cannot_be_resolved():
    ok, reason = ms.verify_memento_at_slot(
        "/anywhere/.claude-memento.md", repo_root=None, persona="chloe",
        session_id="5288a6e5", now=_dt( 25 ), read_text_fn=lambda p: None,
    )
    assert ok is False
    assert "cannot resolve this seat's repo root" in reason


def test_verify_refuses_on_a_blank_repo_root():
    ok, reason = ms.verify_memento_at_slot(
        "/anywhere/.claude-memento.md", repo_root="   ", persona="chloe",
        session_id="5288a6e5", now=_dt( 25 ), read_text_fn=lambda p: None,
    )
    assert ok is False
    assert "cannot resolve this seat's repo root" in reason


def test_leg2_fails_when_the_slot_pointer_is_absent_entirely( tmp_path ):
    """Placement can pass on the record while the pointer no reader follows is missing."""
    record = ms.slot_record_path( tmp_path, "chloe", "5288a6e5" )
    read   = _fs( { str( record ): _record_text( "chloe", "5288a6e5", _dt( 20 ) ) } )
    ok, reason = ms.verify_memento_at_slot(
        str( record ), repo_root=str( tmp_path ), persona="chloe", session_id="5288a6e5",
        now=_dt( 25 ), read_text_fn=read,
    )
    assert ok is False
    assert "no memento at slot" in reason


def test_leg2_fails_on_a_stale_written_at( tmp_path ):
    read, pointer = _root_slot_fs( tmp_path, written_at=_dt( 20 ) )
    ok, reason = ms.verify_memento_at_slot(
        pointer, repo_root=str( tmp_path ), persona="chloe", session_id="5288a6e5",
        now=_dt( 25 ), read_text_fn=read, window_seconds=1,
    )
    assert ok is False
    assert "fails the reap's memento proof" in reason


def test_leg2_fails_on_a_body_under_the_byte_floor( tmp_path ):
    pointer = ms.slot_pointer_path( tmp_path, "chloe" )
    record  = ms.slot_record_path( tmp_path, "chloe", "5288a6e5" )
    tiny    = f"<!-- memento-record: persona=chloe session_id=5288a6e5 written_at={_dt( 20 ).isoformat()} slot=root -->\n# stub\n"
    read    = _fs( { str( record ): tiny, str( pointer ): _pointer_text( record.name, tiny ) } )
    ok, reason = ms.verify_memento_at_slot(
        str( pointer ), repo_root=str( tmp_path ), persona="chloe", session_id="5288a6e5",
        now=_dt( 25 ), read_text_fn=read,
    )
    assert ok is False
    assert "too small" in reason


def test_verify_tolerates_a_missing_session_id_by_failing_not_raising( tmp_path ):
    read, pointer = _root_slot_fs( tmp_path )
    ok, reason = ms.verify_memento_at_slot(
        pointer, repo_root=str( tmp_path ), persona="chloe", session_id=None,
        now=_dt( 25 ), read_text_fn=read,
    )
    assert ok is False


def test_self_respin_slot_is_root_and_disjoint_from_the_reap_slot():
    """The doctrine reap_memento records: a reap reads `io`, a self-respin reads `root`."""
    assert ms.SELF_RESPIN_SLOT == ms.SLOT_ROOT
    assert ms.SLOT_ROOT != ms.SLOT_IO


# ---------------------------------------------------------------------------
# The MIRROR-home clause on an abort (Tiberius's request, 2026-08-30)
#
# The abort message is the only text a seat in this situation actually reads —
# he wrote to ~/.claude/mementos without consulting the docs, because that
# directory looks exactly like where mementos go. It IS one: memento_io's
# out-of-repo mirror. Saying so is what the old message left out.
# ---------------------------------------------------------------------------
def test_mirror_clause_fires_for_a_file_at_the_bare_mirror_home( monkeypatch, tmp_path ):
    """Tiberius's exact shape: <mirror_home>/<persona>-<sid>-memento.md."""
    mirror = tmp_path / "home" / ".claude" / "mementos"
    mirror.mkdir( parents=True )
    monkeypatch.setattr( ms, "MIRROR_HOME", mirror )

    clause = ms.mirror_home_clause( mirror / "tiberius-f032ae9f-memento.md" )
    assert "MIRROR, not a slot" in clause
    assert "<mirror_home>/<repo>/<record-path>" in clause
    assert clause.startswith( " " )          # it appends to a sentence, not a new line


def test_mirror_clause_fires_for_a_correctly_shaped_mirror_path_too( monkeypatch, tmp_path ):
    """
    A real mirror path is still not a SLOT — self_respin reads the repo, never the mirror.
    The clause explains the directory; it does not grade the path under it.
    """
    mirror = tmp_path / "home" / ".claude" / "mementos"
    mirror.mkdir( parents=True )
    monkeypatch.setattr( ms, "MIRROR_HOME", mirror )
    assert ms.mirror_home_clause( mirror / "lupin" / ".claude-memento-chloe-5288a6e5.md" ) != ""


def test_mirror_clause_is_silent_for_every_other_wrong_path( monkeypatch, tmp_path ):
    """
    🔴 The clause must NOT be appended always. A message that explains every case is a
    message nobody finishes reading — it fires for the one plausible destination only.
    """
    mirror = tmp_path / "home" / ".claude" / "mementos"
    mirror.mkdir( parents=True )
    monkeypatch.setattr( ms, "MIRROR_HOME", mirror )
    assert ms.mirror_home_clause( tmp_path / "repo" / "notes.md" ) == ""


def test_mirror_clause_is_silent_rather_than_raising_on_an_unresolvable_path( monkeypatch, tmp_path ):
    monkeypatch.setattr( ms, "MIRROR_HOME", tmp_path / "home" / ".claude" / "mementos" )
    assert ms.mirror_home_clause( "/repo/\x00bad.md" ) == ""


def test_the_abort_carries_the_clause_for_the_tiberius_case( monkeypatch, tmp_path ):
    """End to end: his real case, and the message now says WHY the directory is wrong."""
    mirror = tmp_path / "home" / ".claude" / "mementos"
    mirror.mkdir( parents=True )
    monkeypatch.setattr( ms, "MIRROR_HOME", mirror )
    stray = mirror / "tiberius-f032ae9f-memento.md"
    stray.write_text( _record_text( "tiberius", "f032ae9f", _dt( 20 ) ) )

    repo = tmp_path / "repo"
    repo.mkdir()
    ok, reason = ms.verify_memento_at_slot(
        str( stray ), repo_root=str( repo ), persona="Tiberius 👑",
        session_id="f032ae9f", now=_dt( 25 ), read_text_fn=lambda p: None,
    )
    assert ok is False
    assert "not at this seat's 'root' slot" in reason   # the placement verdict, unchanged
    assert "MIRROR, not a slot"             in reason   # ...and now the reason WHY


def test_the_abort_stays_short_for_an_ordinary_wrong_path( monkeypatch, tmp_path ):
    """The paired negative: no clause, so every other abort is unchanged in length."""
    monkeypatch.setattr( ms, "MIRROR_HOME", tmp_path / "home" / ".claude" / "mementos" )
    stray = tmp_path / "elsewhere.md"
    stray.write_text( _record_text( "chloe", "5288a6e5", _dt( 20 ) ) )
    ok, reason = ms.verify_memento_at_slot(
        str( stray ), repo_root=str( tmp_path ), persona="chloe",
        session_id="5288a6e5", now=_dt( 25 ), read_text_fn=lambda p: None,
    )
    assert ok is False
    assert "MIRROR, not a slot" not in reason

"""
Unit tests for `heartbeat_hold_io` — the hold WRITE/READ/CLEAR verb (row 3ebc6c3d, A3).

BOTH POLARITIES, EVERY VERB. The row this file closes is a row about a guard that
could not fire: 22 hold files declared quiescence, defended nothing, and were poked
for four weeks in silence. So a suite here that proved only the happy path would be
the same defect one level up — a test that cannot tell this CLI from a `print`.

Two properties are asserted that an exit code alone cannot carry:

  * A REFUSED WRITE LEAVES NOTHING ON DISK. Not "returns 2" — the file is asserted
    ABSENT, and so is its atomic-write `.tmp` sibling. The corpus this row exists
    for is 22 files nobody meant to leave behind.
  * A SUCCESSFUL WRITE IS HONORED BY THE REAL READER. The CLI's own success banner
    is not the evidence; `read_hold` + `is_honored` are, read back through exactly
    the path the Stop hook uses.
"""
import json
import sys

import pytest

from lupin_cli.claude_code.hooks.lib import heartbeat_hold_io as hio
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import (
    DEFAULT_TTL_SECONDS, hold_path, is_honored, read_hold,
)


SID = "cli-0000-1111-2222"


def _write_argv( base, sid=SID, **extra ):
    """
    Ensures: returns a minimal valid `write` argv for `base`, plus any extra flags.
    """
    argv = [ "write", "--session-id", sid, "--persona", "Clayton 😎",
             "--reason", "holding on the A3 build", "--base-dir", str( base ) ]
    for flag, value in extra.items():
        argv.append( flag )
        if value is not None:
            argv.append( str( value ) )
    return argv


# ------------------------------------------------------------------ write: POSITIVE

def test_write_returns_ok_and_lands_an_honored_hold( tmp_path ):
    assert hio.main( _write_argv( tmp_path ) ) == hio.EXIT_OK

    path = hold_path( SID, base_dir=tmp_path )
    assert path.exists(), "a successful write must land the artifact"

    hold = read_hold( SID, base_dir=tmp_path )
    assert is_honored( hold ), "the hook must HONOR what this verb writes"
    assert hold[ "ttl_seconds" ] == DEFAULT_TTL_SECONDS
    assert hold[ "awaiting" ] == "none"
    assert hold[ "work_owed" ] is True
    assert hold[ "persona" ] == "Clayton 😎"


def test_write_persists_every_supplied_flag( tmp_path ):
    argv = _write_argv( tmp_path, **{ "--ttl-seconds": 14400, "--awaiting": "user:rick" } )
    assert hio.main( argv ) == hio.EXIT_OK

    hold = read_hold( SID, base_dir=tmp_path )
    assert hold[ "ttl_seconds" ] == 14400
    assert hold[ "awaiting" ]    == "user:rick"
    assert hold[ "reason" ]      == "holding on the A3 build"


def test_write_no_work_owed_flips_the_flag( tmp_path ):
    assert hio.main( _write_argv( tmp_path, **{ "--no-work-owed": None } ) ) == hio.EXIT_OK
    assert read_hold( SID, base_dir=tmp_path )[ "work_owed" ] is False


def test_write_explicit_work_owed_flag_is_accepted( tmp_path ):
    assert hio.main( _write_argv( tmp_path, **{ "--work-owed": None } ) ) == hio.EXIT_OK
    assert read_hold( SID, base_dir=tmp_path )[ "work_owed" ] is True


def test_write_banner_names_the_path_and_the_ttl( tmp_path, capsys ):
    hio.main( _write_argv( tmp_path, **{ "--ttl-seconds": 60 } ) )
    out = capsys.readouterr().out
    assert str( hold_path( SID, base_dir=tmp_path ) ) in out, "banner must name WHAT landed"
    assert "60s" in out and "honored  yes" in out


def test_write_is_a_refresh_not_a_refusal( tmp_path ):
    """A hold is REFRESHED in place — unlike a memento record, it is not immutable."""
    assert hio.main( _write_argv( tmp_path, **{ "--ttl-seconds": 60 } ) ) == hio.EXIT_OK
    assert hio.main( _write_argv( tmp_path, **{ "--ttl-seconds": 120 } ) ) == hio.EXIT_OK
    assert read_hold( SID, base_dir=tmp_path )[ "ttl_seconds" ] == 120


# ------------------------------------------------------------------ write: NEGATIVE

@pytest.mark.parametrize( "ttl", [ 0, -1, -900 ] )
def test_a_non_positive_ttl_is_refused_and_leaves_nothing_behind( tmp_path, ttl, capsys ):
    """
    The polarity that matters. Not just "exit 2" — NOTHING on disk, including the
    atomic-write `.tmp` sibling. A guard that refuses but leaves a partial file is
    how a corpus of 22 unusable holds accumulates in the first place.
    """
    assert hio.main( _write_argv( tmp_path, **{ "--ttl-seconds": ttl } ) ) == hio.EXIT_REFUSED

    path = hold_path( SID, base_dir=tmp_path )
    assert not path.exists(),                                  "a refused write must leave NO artifact"
    assert not path.with_name( path.name + ".tmp" ).exists(),  "nor a partial .tmp"
    assert list( tmp_path.iterdir() ) == [ ],                  "nor anything else at all"
    assert "REFUSED" in capsys.readouterr().err


def test_the_refusal_message_is_write_holds_own_words( tmp_path, capsys ):
    """Re-wording the ValueError would cost the caller the explanation it carries."""
    hio.main( _write_argv( tmp_path, **{ "--ttl-seconds": 0 } ) )
    err = capsys.readouterr().err
    assert "ttl_seconds must be POSITIVE" in err
    assert "expires the hold the instant it is written" in err


def test_a_non_numeric_ttl_is_refused_by_argparse_before_write_hold( tmp_path ):
    """
    Documented boundary (module docstring item 3): `type=int` means the non-numeric
    branch of `write_hold`'s guard is unreachable from this CLI. argparse refuses
    first, with its own exit-2 SystemExit — asserted, not assumed.
    """
    with pytest.raises( SystemExit ) as exc:
        hio.main( _write_argv( tmp_path, **{ "--ttl-seconds": "abc" } ) )
    assert exc.value.code == 2
    assert not hold_path( SID, base_dir=tmp_path ).exists()


def test_an_unwritable_base_dir_is_refused_not_a_traceback( tmp_path, capsys ):
    missing = tmp_path / "does" / "not" / "exist"
    assert hio.main( _write_argv( missing ) ) == hio.EXIT_REFUSED
    assert "REFUSED" in capsys.readouterr().err


@pytest.mark.parametrize( "reason", [ "", "   ", "\t\n", " " ] )
def test_an_unhonorable_reason_is_refused_and_leaves_nothing_behind( tmp_path, reason, capsys ):
    """
    Finding A-1 (Rio ⚡, 2026-07-21). `write --reason ""` used to exit 3 with the
    unhonorable hold ON DISK — the 22-file corpus shape, minted by the verb built
    to stop minting it.

    PARAMETERIZED PAST THE EMPTY STRING ON PURPOSE. `is_honored` tests
    `bool( reason and str( reason ).strip() )`, so a guard that rejected only ""
    would let "   " walk through and reopen A-1 one keystroke over. The guard is
    the exact complement of that predicate, and these params are what proves it —
    `\\u00a0` (non-breaking space) is included because Python's `str.strip()`
    treats it as whitespace and a hand-rolled `== ""` check would not.
    """
    assert hio.main( _write_argv( tmp_path, **{ "--reason": reason } ) ) == hio.EXIT_REFUSED

    path = hold_path( SID, base_dir=tmp_path )
    assert not path.exists(),                                 "a refused write must leave NO artifact"
    assert not path.with_name( path.name + ".tmp" ).exists(), "nor a partial .tmp"
    assert list( tmp_path.iterdir() ) == [ ],                 "nor anything else at all"
    assert "reason must be a non-empty" in capsys.readouterr().err


def test_an_unhonorable_reason_cannot_destroy_a_live_hold( tmp_path, capsys ):
    """
    The A-1 REFRESH variant, and the reason unlink-on-failure was the wrong fix:
    the destructive act is the overwrite, not the leftover. Measured before the
    fix — a live `honored=True` hold came back `honored=False` after an
    empty-reason write. The guard raises BEFORE any filesystem touch, so the
    good hold is never overwritten at all.
    """
    hio.main( _write_argv( tmp_path, **{ "--ttl-seconds": 14400 } ) )
    capsys.readouterr()
    before = read_hold( SID, base_dir=tmp_path )
    assert is_honored( before )

    assert hio.main( _write_argv( tmp_path, **{ "--reason": "" } ) ) == hio.EXIT_REFUSED

    after = read_hold( SID, base_dir=tmp_path )
    assert is_honored( after ),                          "a refused write must not cost a live defense"
    assert after[ "reason" ]      == before[ "reason" ]
    assert after[ "ttl_seconds" ] == before[ "ttl_seconds" ] == 14400


def test_write_refuses_to_destroy_a_hold_carrying_cargo( tmp_path, capsys ):
    """
    Row 955f7eb4 (María 🌸). `write_hold` persists EXACTLY the schema through an
    `os.replace`, so refreshing a hold that carries `blocked_rows` /
    `note_to_my_successor` DESTROYED them — at exit 0, under a success banner.
    That is A-1's shape on the SUCCESS path, where nothing signals it.

    Found by running the prescribed command against a real hold, not by reading
    the code: the verb built to stop the corpus would have destroyed the payload
    in every member of it on first use.
    """
    path = hold_path( SID, base_dir=tmp_path )
    path.write_text( json.dumps( {
        "session_id": SID, "persona": "María 🌸", "held_at": "2026-07-21T12:00:00+00:00",
        "ttl_seconds": 14400, "work_owed": True, "reason": "holding", "awaiting": "user:rick",
        "blocked_rows": [ "955f7eb4" ], "note_to_my_successor": "irreplaceable",
    }, indent=2 ) )
    before = path.read_bytes()

    assert hio.main( _write_argv( tmp_path ) ) == hio.EXIT_CARGO
    assert path.read_bytes() == before, "the cargo-bearing hold must be untouched"

    err = capsys.readouterr().err
    assert "blocked_rows" in err and "note_to_my_successor" in err, "every field must be NAMED"
    assert "memento_io.py" in err, "and the caller told where continuity actually belongs"


def test_write_accepts_exactly_these_flags_and_no_others():
    """
    There is deliberately no escape from the cargo guard: an escape you can take
    silently is not a gate, and the payload is irreplaceable.

    ASSERTED AS A WHITELIST, NOT A BLACKLIST — finding C-1 (Rio ⚡, 2026-07-21),
    proved by adding an escape. The first version of this test read
    `assert not { "--force", "--discard-cargo", "--overwrite" } & flags`; he
    injected `--allow-cargo` into the subparser and it reported **1 passed**. A
    future author using any spelling outside those three would ship an escape
    under a green test whose NAME promised there was none.

    The irony he named: `hold_cargo_keys` is a COMPLEMENT predicate
    (`k not in HOLD_SCHEMA_FIELDS`) — confirmed by execution, an unseen key
    `zzz_never_seen_before` still exits 6. **The guard enumerates nothing; its
    test enumerated three.** So the test is inverted to match the guard: any new
    flag fails here until someone deliberately widens this set, which is a diff a
    reviewer sees rather than an addition that hides behind a green.
    """
    write_parser = hio.build_parser()._subparsers._group_actions[ 0 ].choices[ "write" ]
    flags        = { option for action in write_parser._actions for option in action.option_strings }

    assert flags == {
        "-h", "--help",
        "--session-id", "--base-dir",
        "--persona", "--reason", "--ttl-seconds", "--awaiting",
        "--work-owed", "--no-work-owed",
    }, "a flag was added to `write` — if it is an escape from the cargo guard, it does not belong"


def test_a_schema_only_hold_is_not_cargo_bearing( tmp_path, capsys ):
    """PRESENCE-assertion: the guard must not block an ordinary refresh."""
    hio.main( _write_argv( tmp_path, **{ "--ttl-seconds": 60 } ) )
    capsys.readouterr()
    assert hio.main( _write_argv( tmp_path, **{ "--ttl-seconds": 120 } ) ) == hio.EXIT_OK
    assert read_hold( SID, base_dir=tmp_path )[ "ttl_seconds" ] == 120


@pytest.mark.parametrize( "verb", [ "read", "clear" ] )
def test_a_not_found_says_WHERE_it_looked( tmp_path, verb, capsys ):
    """
    A null that does not name its search directory is not evidence. This exact
    message read "no hold found" to a `plan` session whose hold was alive one
    directory over — `--base-dir` defaults to LUPIN_ROOT, which is right for a
    lupin session and wrong for every other (María, 2026-07-21).
    """
    assert hio.main( [ verb, "--session-id", SID, "--base-dir", str( tmp_path ) ] ) == hio.EXIT_NO_HOLD
    assert str( tmp_path ) in capsys.readouterr().err, "the null must name the directory searched"


def test_a_hold_that_lands_but_would_not_be_honored_is_not_a_success( tmp_path, monkeypatch, capsys ):
    """
    Verify-by-execution, proven by defeating it: the write succeeds, but the reader
    the hook uses cannot honor the result. The banner must NOT print.

    This is detector 2's isolating test — the one that goes red under mutation B
    (`if not is_honored( read_back )` → `if False`). Synthetic by necessity: after
    A-1's fix there is no ENUMERATED class detector 2 catches alone, so the only
    way to exercise it is to inject one. That is stated in the module docstring
    rather than dressed up as a real divergence.
    """
    monkeypatch.setattr( hio, "read_hold", lambda *a, **k: None )
    assert hio.main( _write_argv( tmp_path ) ) == hio.EXIT_NOT_HONORED

    captured = capsys.readouterr()
    assert "would NOT be honored" in captured.err
    assert "honored  yes" not in captured.out, "a failed verify must never print success"


def test_a_failed_verify_unlinks_when_there_was_no_prior_hold( tmp_path, monkeypatch, capsys ):
    """ROLLBACK, fresh case: nothing was there, so nothing may be left."""
    monkeypatch.setattr( hio, "read_hold", lambda *a, **k: None )
    assert hio.main( _write_argv( tmp_path ) ) == hio.EXIT_NOT_HONORED

    assert not hold_path( SID, base_dir=tmp_path ).exists()
    assert list( tmp_path.iterdir() ) == [ ], "a failed verify must not leave the corpus a new file"
    assert "nothing was written" in capsys.readouterr().err


def test_a_failed_verify_restores_the_previous_hold_byte_for_byte( tmp_path, monkeypatch, capsys ):
    """
    ROLLBACK, refresh case — the one unlinking does NOT save. The prior hold's
    bytes must come back, not merely "some honored hold": a restore that rewrote
    the file would silently change held_at and hand the session a different
    freshness window than the one it had.
    """
    hio.main( _write_argv( tmp_path, **{ "--ttl-seconds": 14400 } ) )
    capsys.readouterr()
    path   = hold_path( SID, base_dir=tmp_path )
    before = path.read_bytes()

    monkeypatch.setattr( hio, "read_hold", lambda *a, **k: None )
    assert hio.main( _write_argv( tmp_path, **{ "--ttl-seconds": 60 } ) ) == hio.EXIT_NOT_HONORED

    assert path.read_bytes() == before, "the prior hold must be restored BYTE-FOR-BYTE"
    assert "RESTORED" in capsys.readouterr().err
    assert list( tmp_path.iterdir() ) == [ path ], "and no second artifact may survive"

    monkeypatch.undo()
    assert is_honored( read_hold( SID, base_dir=tmp_path ) ), "and it must still defend the session"


def test_a_failed_verify_does_not_resurrect_a_stale_prior_hold( tmp_path, monkeypatch, capsys ):
    """
    S4 — the arm a content assertion sails straight past, and the row's own defect
    INVERTED: a hold that defends a session it should not.

    `is_fresh` anchors on the FILE MTIME (B1), not `held_at`. So restoring by
    writing identical bytes back RESETS the anchor and a correctly-dead hold comes
    back alive. Measured before the fix: stale prior honored=False → naive restore
    honored=TRUE. This asserts the mtime, not the bytes, because only the mtime
    can tell the two implementations apart.
    """
    import os

    hio.main( _write_argv( tmp_path, **{ "--ttl-seconds": 60 } ) )
    capsys.readouterr()
    path = hold_path( SID, base_dir=tmp_path )
    os.utime( path, ( 0, 0 ) )                     # force the prior STALE
    assert not is_honored( read_hold( SID, base_dir=tmp_path ) ), "precondition: prior is dead"
    stale_mtime = path.stat().st_mtime

    monkeypatch.setattr( hio, "read_hold", lambda *a, **k: None )
    assert hio.main( _write_argv( tmp_path ) ) == hio.EXIT_NOT_HONORED

    assert path.stat().st_mtime == stale_mtime, "the restore must preserve mtime, not reset it"
    monkeypatch.undo()
    assert not is_honored( read_hold( SID, base_dir=tmp_path ) ), \
        "a dead hold must STAY dead — a naive restore resurrects it"


def test_a_failed_verify_restores_an_already_unhonorable_prior_rather_than_deleting_it( tmp_path, monkeypatch, capsys ):
    """
    S3, per the ruling (Mr Radio 🦉 + Rio ⚡): this verb must not silently delete
    something it did not create. A hand-written corpus member is exactly what the
    janitor triages later — unaccountably removing it here would be a bigger
    surprise than leaving it, and this verb exists to stop unaccountable hold
    FILES, not to start unaccountable DELETIONS.
    """
    path = hold_path( SID, base_dir=tmp_path )
    path.write_text( json.dumps( { "session_id": SID, "note_to_my_successor": "irreplaceable" } ) )
    corpus_member = path.read_bytes()

    monkeypatch.setattr( hio, "read_hold", lambda *a, **k: None )
    assert hio.main( _write_argv( tmp_path ) ) == hio.EXIT_NOT_HONORED

    assert path.exists(),                     "a hold this verb did not create must survive its refusal"
    assert path.read_bytes() == corpus_member, "byte-exact, cargo and all"
    assert "RESTORED" in capsys.readouterr().err


# ------------------------------------------------------------------ read

def test_read_prints_the_hold_and_returns_ok( tmp_path, capsys ):
    hio.main( _write_argv( tmp_path ) )
    capsys.readouterr()

    assert hio.main( [ "read", "--session-id", SID, "--base-dir", str( tmp_path ) ] ) == hio.EXIT_OK
    captured = capsys.readouterr()
    payload  = json.loads( captured.out )
    assert payload[ "session_id" ] == SID
    assert payload[ "persona" ]    == "Clayton 😎", "non-ASCII must survive the JSON dump"
    assert "_hold_file_mtime_epoch" in payload,     "the reader's B1 annotation is part of the truth"
    assert "honored  yes" in captured.err


def test_read_of_an_absent_hold_is_a_distinct_outcome( tmp_path, capsys ):
    assert hio.main( [ "read", "--session-id", SID, "--base-dir", str( tmp_path ) ] ) == hio.EXIT_NO_HOLD
    assert "no hold found" in capsys.readouterr().err


def test_read_reports_an_expired_hold_as_not_honored( tmp_path, capsys ):
    import os

    hio.main( _write_argv( tmp_path, **{ "--ttl-seconds": 1 } ) )
    capsys.readouterr()
    path = hold_path( SID, base_dir=tmp_path )
    os.utime( path, ( 0, 0 ) )                     # drive expiry through the mtime anchor (B1)

    assert hio.main( [ "read", "--session-id", SID, "--base-dir", str( tmp_path ) ] ) == hio.EXIT_OK
    assert "honored  NO" in capsys.readouterr().err


# ------------------------------------------------------------------ clear

def test_clear_removes_the_hold( tmp_path, capsys ):
    hio.main( _write_argv( tmp_path ) )
    capsys.readouterr()

    assert hio.main( [ "clear", "--session-id", SID, "--base-dir", str( tmp_path ) ] ) == hio.EXIT_OK
    assert not hold_path( SID, base_dir=tmp_path ).exists()
    assert "CLEARED" in capsys.readouterr().out


def test_clear_names_the_cargo_it_destroys( tmp_path, capsys ):
    """
    C-2 (Rio ⚡). `write` refuses to drop cargo and routes the caller HERE —
    "deleting it should be an act you can point at". A `clear` that removes an
    irreplaceable payload without saying so is not pointable-at, which would make
    write's refusal text a cheque this verb did not honor.

    The deletion is still ALLOWED — deliberate removal is the whole point of the
    verb. It just stops being silent.
    """
    path = hold_path( SID, base_dir=tmp_path )
    path.write_text( json.dumps( {
        "session_id": SID, "persona": "P", "held_at": "2026-07-21T12:00:00+00:00",
        "ttl_seconds": 900, "work_owed": True, "reason": "r", "awaiting": "none",
        "blocked_rows": [ "955f7eb4" ], "note_to_my_successor": "irreplaceable",
    }, indent=2 ) )

    assert hio.main( [ "clear", "--session-id", SID, "--base-dir", str( tmp_path ) ] ) == hio.EXIT_OK
    assert not path.exists(), "a deliberate clear must still delete"

    captured = capsys.readouterr()
    assert "CLEARED" in captured.out
    assert "blocked_rows" in captured.err and "note_to_my_successor" in captured.err, \
        "every destroyed field must be named"
    assert "GONE" in captured.err


def test_clear_of_a_schema_only_hold_says_nothing_about_cargo( tmp_path, capsys ):
    """The quiet path stays quiet — no cargo, no cargo line."""
    hio.main( _write_argv( tmp_path ) )
    capsys.readouterr()

    assert hio.main( [ "clear", "--session-id", SID, "--base-dir", str( tmp_path ) ] ) == hio.EXIT_OK
    assert "GONE" not in capsys.readouterr().err


def test_clear_of_an_absent_hold_says_so_rather_than_claiming_success( tmp_path, capsys ):
    assert hio.main( [ "clear", "--session-id", SID, "--base-dir", str( tmp_path ) ] ) == hio.EXIT_NO_HOLD
    assert "no hold found" in capsys.readouterr().err


def test_clear_names_a_prefix_matched_orphan_and_deletes_nothing( tmp_path, capsys ):
    """
    A-3, C2 — the arm that killed the obvious fix. `read_hold` resolves by PREFIX
    when the exact path is absent (facet 2, c121037b), so "clear whatever read
    resolved" would make this call destroy ANOTHER session's live hold while
    naming neither that id nor any existing file. Its owner would then be poked
    out of a quiescence it correctly declared — this row's own defect, caused by
    the fix for it.

    So the deletion is exact-path-only and the orphan is NAMED. A verb that
    refuses to guess is the paved road; a verb that guesses at deletion is a new
    hazard wearing the fix's name. The cure — write/clear symmetry — is row
    39219cc1; this only stops the silence.
    """
    full = "c121037b-aaaa-1111-2222-333344445555"
    hio.main( _write_argv( tmp_path, sid=full ) )
    capsys.readouterr()
    before = hold_path( full, base_dir=tmp_path ).read_bytes()

    assert hio.main( [ "clear", "--session-id", "c121037b",
                       "--base-dir", str( tmp_path ) ] ) == hio.EXIT_ORPHAN

    assert hold_path( full, base_dir=tmp_path ).read_bytes() == before, \
        "a prefix-matched hold must NEVER be deleted by an id that does not name it"
    assert is_honored( read_hold( full, base_dir=tmp_path ) ), "and it must still defend its session"
    captured = capsys.readouterr()
    assert "Nothing was deleted" in captured.err and full in captured.err, \
        "the orphan must be NAMED, not hinted at"
    assert "CLEARED" not in captured.out, \
        "A-4: this used to print CLEARED at exit 0 for a path that never existed"


def test_clear_with_multiple_prefix_matches_still_deletes_nothing( tmp_path, capsys ):
    """
    A-3, C3. `_read_hold_path` prefers longest-then-lexical — the right rule for
    "which should I READ", an arbitrary one for "which should I DESTROY". With two
    candidates, picking one and reporting CLEARED would orphan the other and
    destroy a coin-flip.
    """
    a = "c121037b-aaaa-1111-2222-333344445555"
    b = "c121037b-bbbb-9999-8888-777766665555"
    hio.main( _write_argv( tmp_path, sid=a ) )
    hio.main( _write_argv( tmp_path, sid=b ) )
    capsys.readouterr()

    assert hio.main( [ "clear", "--session-id", "c121037b",
                       "--base-dir", str( tmp_path ) ] ) == hio.EXIT_ORPHAN
    assert hold_path( a, base_dir=tmp_path ).exists() and hold_path( b, base_dir=tmp_path ).exists(), \
        "neither candidate may be destroyed on an arbitrary tie-break"
    assert len( list( tmp_path.iterdir() ) ) == 2

    captured = capsys.readouterr()
    assert a in captured.err and b in captured.err, \
        "EVERY orphan must be named — naming one of two is A-4 with better manners"
    assert "2 hold(s)" in captured.err
    assert "CLEARED" not in captured.out


def test_prefix_siblings_of_an_empty_session_id_is_empty( tmp_path ):
    """An empty id prefixes EVERYTHING — it must never enumerate the whole directory."""
    hio.main( _write_argv( tmp_path, sid="anything-at-all" ) )
    assert hio._prefix_siblings( "", base_dir=tmp_path ) == [ ]


def test_prefix_siblings_survives_an_unreadable_directory( tmp_path, monkeypatch ):
    """A glob OSError yields no orphans rather than a traceback out of `clear`."""
    def _boom( *a, **k ):
        raise OSError( "unreadable" )
    monkeypatch.setattr( type( tmp_path ), "glob", _boom )
    assert hio._prefix_siblings( SID, base_dir=tmp_path ) == [ ]


def test_prefix_siblings_excludes_the_exact_path_and_tmp_artifacts( tmp_path ):
    """The exact path is not its own orphan, and a half-written .tmp is not a hold."""
    full = "c121037b-aaaa-1111-2222-333344445555"
    hio.main( _write_argv( tmp_path, sid=full ) )
    exact = hold_path( full, base_dir=tmp_path )
    exact.with_name( exact.name + ".tmp" ).write_text( "{}" )

    assert hio._prefix_siblings( full, base_dir=tmp_path ) == [ ], \
        "its own path and a .tmp artifact are neither of them orphans"
    assert hio._prefix_siblings( "c121037b", base_dir=tmp_path ) == [ exact ]


def test_clear_of_an_exact_hold_is_unaffected_by_the_orphan_guard( tmp_path, capsys ):
    """The PRESENCE-assertion beside the two refusals: the guard is not a brick wall."""
    full = "c121037b-aaaa-1111-2222-333344445555"
    hio.main( _write_argv( tmp_path, sid=full ) )
    capsys.readouterr()

    assert hio.main( [ "clear", "--session-id", full, "--base-dir", str( tmp_path ) ] ) == hio.EXIT_OK
    assert list( tmp_path.iterdir() ) == [ ]


# ------------------------------------------------------------------ parser

def test_a_missing_subcommand_is_a_usage_error():
    with pytest.raises( SystemExit ) as exc:
        hio.main( [ ] )
    assert exc.value.code == 2


@pytest.mark.parametrize( "argv", [
    [ "write", "--persona", "p", "--reason", "r" ],                     # no --session-id
    [ "write", "--session-id", SID, "--reason", "r" ],                  # no --persona
    [ "write", "--session-id", SID, "--persona", "p" ],                 # no --reason
    [ "read" ],                                                         # no --session-id
    [ "clear" ],                                                        # no --session-id
] )
def test_every_required_flag_is_actually_required( argv ):
    with pytest.raises( SystemExit ) as exc:
        hio.main( argv )
    assert exc.value.code == 2


def test_build_parser_defaults_match_the_writers_defaults():
    args = hio.build_parser().parse_args( [ "write", "--session-id", SID,
                                            "--persona", "p", "--reason", "r" ] )
    assert args.ttl_seconds == DEFAULT_TTL_SECONDS
    assert args.awaiting    == "none"
    assert args.work_owed is True
    assert args.base_dir is None, "default base_dir must be write_hold's, not a second rule"


# ------------------------------------------------------------------ sys.path bootstrap

def test_bootstrap_inserts_lupin_src_when_absent( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    monkeypatch.setattr( sys, "path", [ "/somewhere/else" ] )

    assert hio._bootstrap_sys_path() is True
    assert sys.path[ 0 ] == str( tmp_path / "src" )


def test_bootstrap_is_idempotent( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    monkeypatch.setattr( sys, "path", [ str( tmp_path / "src" ) ] )

    assert hio._bootstrap_sys_path() is False, "a second import must not stack sys.path entries"
    assert sys.path == [ str( tmp_path / "src" ) ]


def test_bootstrap_without_lupin_root_is_a_no_op_not_a_raise( monkeypatch ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    before = list( sys.path )

    assert hio._bootstrap_sys_path() is False
    assert sys.path == before


# ------------------------------------------------------------------ inline smoke

def test_quick_smoke_test_passes():
    assert hio.quick_smoke_test() is True

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
import datetime
import json
import pathlib
import sys

import pytest

from lupin_cli.claude_code.hooks.lib import heartbeat_hold_io as hio
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import (
    DEFAULT_TTL_SECONDS, _parse_iso, get_last_looked_in_ts, get_last_spinup_check_ts,
    get_last_surfaced_questions_ts, hold_path, is_honored, read_hold,
)
from lupin_cli.claude_code.hooks.lib.heartbeat_work_owed import _iso_age_seconds


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
        # 1dcaf65c — the three debounce stamps. Widened DELIBERATELY, which is the
        # diff this test exists to force: they set schema fields `write_hold`
        # already owns, so none of them is an escape from the cargo guard.
        "--looked-in", "--spinup-check", "--surfaced-questions",
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

    # BOTH readers, deliberately (8abdcbbf). The subject here is the RESTORE, so
    # the cargo guard has to be out of the way — and the guard now reads the
    # EXACT path while the verify reads through the resolver, so one patch no
    # longer stands the whole scenario up. This test previously disabled the
    # guard as a SIDE EFFECT of patching the verify's reader; naming both is what
    # that always meant. The guard's own behaviour is covered by the 8abdcbbf
    # block below — this prior carries cargo only so the restore can be asserted
    # byte-exact WITH cargo present.
    monkeypatch.setattr( hio, "read_hold",       lambda *a, **k: None )
    monkeypatch.setattr( hio, "read_hold_exact", lambda *a, **k: None )
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


# ══════════════════════════════════════════════════════════════════════════════
# 8abdcbbf — THE CARGO GUARD MUST READ THE FILE THE WRITE WILL REPLACE.
#
# Mine, shipped in 378f1499. `cmd_write`'s cargo guard read through `read_hold`,
# which is PREFIX-TOLERANT, and then wrote the EXACT path. Guard and action
# resolved differently — A-4's shape, eleven lines from where I fixed A-4 in
# `cmd_clear`, in the same commit.
#
# MEASURED: one hold on disk under the FULL id carrying cargo, nothing at the
# short id's own path. `write --session-id <short>` was REFUSED at exit 6 against
# a path that does not exist, and the short hold was never written. The cargo was
# in a different file — and a prefix sibling is not guaranteed to be yours. A
# session that cannot write a hold IS POKED FOREVER: the ping-storm this surface
# exists to prevent, caused by a guard against a different failure.
#
# The fix has no judgement call in it. `write_hold` replaces exactly ONE file, so
# that file's cargo is the only cargo this call can destroy — the guard reads it
# and nothing else. Both controls below must survive: cargo at the exact path
# still refuses, and the banner names a path that exists.
#
# WHY NO EXISTING TEST CAUGHT IT: every test in this file uses a single session
# id, so no prefix sibling ever reaches disk. A guard whose bug only appears with
# two id forms cannot be caught by a suite that only ever writes one.
# ══════════════════════════════════════════════════════════════════════════════

FULL_SID  = "c121037b-aaaa-1111-2222-333344445555"
SHORT_SID = "c121037b"


def _cargo_hold_at( base, sid, key="note_to_my_successor", value="irreplaceable" ):
    """Ensures: an honored hold at `sid`'s EXACT path, carrying one cargo field."""
    assert hio.main( _write_argv( base, sid=sid ) ) == hio.EXIT_OK
    path = hold_path( sid, base_dir=base )
    data = json.loads( path.read_text() )
    data[ key ] = value
    path.write_text( json.dumps( data ) )
    return path


def test_cargo_in_a_prefix_sibling_does_not_deny_this_session_its_hold( tmp_path ):
    """THE DEFECT: cargo living in ANOTHER file refused this session its hold
    outright — exit 6, nothing written, poked forever."""
    _cargo_hold_at( tmp_path, FULL_SID )                       # cargo lives HERE...
    assert hio.main( _write_argv( tmp_path, sid=SHORT_SID ) ) == hio.EXIT_OK
    assert is_honored( read_hold( SHORT_SID, base_dir=tmp_path ) )


def test_the_prefix_siblings_cargo_is_left_untouched( tmp_path ):
    """The point of the guard is that cargo is never destroyed — and the sibling's
    cargo is no less irreplaceable for being in a file this write ignores."""
    sibling = _cargo_hold_at( tmp_path, FULL_SID )
    hio.main( _write_argv( tmp_path, sid=SHORT_SID ) )
    assert json.loads( sibling.read_text() )[ "note_to_my_successor" ] == "irreplaceable"


def test_cargo_AT_the_exact_path_still_refuses( tmp_path ):
    """CONTROL — the guard being repaired is real and must not be eaten by its own
    repair. If this ever goes green, the fix has removed the cargo guard."""
    _cargo_hold_at( tmp_path, SHORT_SID )                      # cargo at its OWN path
    assert hio.main( _write_argv( tmp_path, sid=SHORT_SID ) ) == hio.EXIT_CARGO


def test_no_refusal_names_a_path_that_does_not_exist( tmp_path, capsys ):
    """The banner named `.heartbeat-hold-c121037b.json` — a file that never
    existed — and sent the caller to move cargo out of a file they cannot find.
    That is the A-4 sentence ("CLEARED a path that never existed") one verb over.
    Post-fix a refusal can only arise from the exact path, so the banner is
    truthful BY CONSTRUCTION rather than by a second check."""
    _cargo_hold_at( tmp_path, FULL_SID )
    assert hio.main( _write_argv( tmp_path, sid=SHORT_SID ) ) == hio.EXIT_OK
    err = capsys.readouterr().err
    assert "REFUSED" not in err
    assert str( hold_path( SHORT_SID, base_dir=tmp_path ) ) not in err


def test_cargo_at_the_exact_path_refuses_even_beside_a_clean_sibling( tmp_path ):
    """CONTROL, second direction. A clean prefix sibling must not talk the guard
    OUT of a refusal it owes. (Pre-fix this already passed — `read_hold` prefers
    the exact path when it exists, so both resolutions agreed here. It is kept
    because the fix must not disturb the case where they agree, which is every
    ordinary call.)"""
    assert hio.main( _write_argv( tmp_path, sid=FULL_SID ) ) == hio.EXIT_OK   # clean sibling
    _cargo_hold_at( tmp_path, SHORT_SID )                                     # cargo at exact
    assert hio.main( _write_argv( tmp_path, sid=SHORT_SID ) ) == hio.EXIT_CARGO


# ══════════════════════════════════════════════════════════════════════════════
# 39219cc1 F1 + F3 — WHERE READ AND WRITE/CLEAR DISAGREE, SAY SO.
#
# The prefix fallback STAYS (it closes c121037b facet 2), and write/clear stay
# EXACT — the reversal on this row settled that: a delete decided by a wildcard
# can destroy a live peer's honored hold (C2) and orphans the rest on multiple
# matches (C3). Nothing below deletes or overwrites anything it was not named.
#
# What is left is the seam itself, and the rule is: NEITHER VERB MAY REPORT A
# RESULT ITS OWN READER CONTRADICTS.
#
#   F1  clear --session-id <short>  -> "CLEARED", exit 0
#       read  --session-id <short>  -> "honored yes"      (surviving sibling)
#       The exact delete SUCCEEDED and the caller is STILL HELD. Reporting that
#       as a plain success is the false success this verb was written to kill,
#       hiding in its other branch: the sibling check only ran when the exact
#       path was ABSENT, so the delete path never asked whether the id still
#       resolved to a hold.
#
#   F3  two writes by one session under its two id forms mint two files, and
#       nothing says so. Not refused — losing a hold is worse than owning a
#       duplicate, and refusing is precisely what 8abdcbbf did wrong — but the
#       second file is the corpus growth this surface exists to stop, arriving
#       BY THE PAVED ROAD rather than by hand.
# ══════════════════════════════════════════════════════════════════════════════

def _both_forms( base ):
    """Ensures: one session holds under BOTH id forms — two files, one session."""
    assert hio.main( _write_argv( base, sid=FULL_SID ) ) == hio.EXIT_OK
    assert hio.main( _write_argv( base, sid=SHORT_SID ) ) == hio.EXIT_OK


# ── F1: a clear that leaves you held is not a success ─────────────────────────

def test_clear_that_leaves_the_session_still_held_is_not_exit_ok( tmp_path ):
    _both_forms( tmp_path )
    assert hio.main( [ "clear", "--session-id", SHORT_SID,
                       "--base-dir", str( tmp_path ) ] ) == hio.EXIT_STILL_HELD


def test_the_still_held_verdict_is_read_back_not_asserted( tmp_path ):
    """The claim the exit code makes — you are still held — is exactly what the
    reader the hook uses reports. The verdict is measured, not declared."""
    _both_forms( tmp_path )
    hio.main( [ "clear", "--session-id", SHORT_SID, "--base-dir", str( tmp_path ) ] )
    assert is_honored( read_hold( SHORT_SID, base_dir=tmp_path ) ) is True


def test_still_held_names_the_file_that_is_still_holding( tmp_path, capsys ):
    """A caller told "still held" without being told BY WHAT cannot act on it —
    the null that did not name its directory, one verb over."""
    _both_forms( tmp_path )
    hio.main( [ "clear", "--session-id", SHORT_SID, "--base-dir", str( tmp_path ) ] )
    assert str( hold_path( FULL_SID, base_dir=tmp_path ) ) in capsys.readouterr().err


def test_a_still_held_clear_deletes_ONLY_its_own_file( tmp_path ):
    """THE REVERSAL, honored: report, never guess. The survivor may be another
    session's live hold — deleting it is C2, the ping-storm caused by the fix for
    the ping-storm."""
    _both_forms( tmp_path )
    hio.main( [ "clear", "--session-id", SHORT_SID, "--base-dir", str( tmp_path ) ] )
    assert hold_path( SHORT_SID, base_dir=tmp_path ).exists() is False   # mine: gone
    assert hold_path( FULL_SID,  base_dir=tmp_path ).exists() is True    # not mine: intact


def test_a_clean_clear_is_still_a_plain_success( tmp_path, capsys ):
    """CONTROL — with no sibling, clear stays exit 0 and says CLEARED. The new arm
    must cost the ordinary release nothing, or it becomes noise and the real
    signal goes unread."""
    assert hio.main( _write_argv( tmp_path, sid=FULL_SID ) ) == hio.EXIT_OK
    assert hio.main( [ "clear", "--session-id", FULL_SID,
                       "--base-dir", str( tmp_path ) ] ) == hio.EXIT_OK
    assert "CLEARED" in capsys.readouterr().out


def test_the_exact_absent_orphan_branch_is_unchanged( tmp_path ):
    """CONTROL — the OTHER sibling branch (nothing at my path, siblings exist)
    still refuses at EXIT_ORPHAN, deleting nothing. Two distinct outcomes keep two
    distinct codes: "I deleted mine and you are still held" is not "I deleted
    nothing because I will not guess"."""
    assert hio.main( _write_argv( tmp_path, sid=FULL_SID ) ) == hio.EXIT_OK
    assert hio.main( [ "clear", "--session-id", SHORT_SID,
                       "--base-dir", str( tmp_path ) ] ) == hio.EXIT_ORPHAN
    assert hold_path( FULL_SID, base_dir=tmp_path ).exists() is True


# ── F3: minting a second file for one session is named, never silent ──────────

def test_write_names_the_sibling_it_just_minted_a_duplicate_beside( tmp_path, capsys ):
    _both_forms( tmp_path )
    assert str( hold_path( FULL_SID, base_dir=tmp_path ) ) in capsys.readouterr().err


def test_the_duplicate_write_still_LANDS( tmp_path ):
    """NOT A REFUSAL, and this is the line to hold. Losing a hold is worse than
    owning a duplicate: a session that cannot declare a hold is poked forever,
    which is exactly what 8abdcbbf did."""
    _both_forms( tmp_path )
    assert is_honored( read_hold( SHORT_SID, base_dir=tmp_path ) )
    assert hold_path( SHORT_SID, base_dir=tmp_path ).exists()


def test_a_lone_write_says_nothing_about_siblings( tmp_path, capsys ):
    """CONTROL — the ordinary write stays quiet. A warning on every write is noise,
    and noise is how the real one gets missed."""
    assert hio.main( _write_argv( tmp_path, sid=FULL_SID ) ) == hio.EXIT_OK
    assert "PREFIX" not in capsys.readouterr().err.upper()


def test_a_refresh_of_the_same_id_is_not_a_duplicate( tmp_path, capsys ):
    """CONTROL — rewriting your OWN hold is a refresh, not a second file. The
    warning keys on OTHER files sharing the prefix, so the commonest call in the
    system (a session re-declaring) stays silent."""
    assert hio.main( _write_argv( tmp_path, sid=FULL_SID ) ) == hio.EXIT_OK
    capsys.readouterr()
    assert hio.main( _write_argv( tmp_path, sid=FULL_SID ) ) == hio.EXIT_OK
    assert "PREFIX" not in capsys.readouterr().err.upper()


# ------------------------------------------------- write: the debounce stamps (1dcaf65c)
#
# THE GAP THESE CLOSE. The Stop-hook poke tells a manager to stamp
# `last_looked_in_on_workers_ts`. The field is real, `write_hold` has taken it as a
# kwarg since A1, and `get_last_looked_in_ts` reads it — but the SANCTIONED CLI had
# no flag for it. A manager who obeys the poke, runs the verb and finds no flag is
# pushed toward the hand-written JSON that CLAUDE.md bans and row 011f1f90 counts 33
# of. So the assertions below are read back through the REAL getters the hook calls,
# not through the CLI's own banner: the question is whether the debounce can SEE the
# stamp, and a banner cannot answer that.

STAMP_CASES = [
    ( "--looked-in",          get_last_looked_in_ts,          "last_looked_in_on_workers_ts" ),
    ( "--spinup-check",       get_last_spinup_check_ts,       "last_spinup_check_ts" ),
    ( "--surfaced-questions", get_last_surfaced_questions_ts, "last_surfaced_questions_ts" ),
]


@pytest.mark.parametrize( "flag,getter,field", STAMP_CASES )
def test_each_stamp_flag_lands_where_the_debounce_reads_it( tmp_path, flag, getter, field ):
    """RED ON THE OLD CLI: argparse rejects the unknown flag at exit 2."""
    assert hio.main( _write_argv( tmp_path, **{ flag: "now" } ) ) == hio.EXIT_OK

    hold = read_hold( SID, base_dir=tmp_path )
    assert getter( hold ) is not None,   f"{flag} must reach the field the hook reads"
    assert hold[ field ] == getter( hold )
    assert is_honored( hold ),           "stamping must not cost the hold its honor"


@pytest.mark.parametrize( "flag,getter,field", STAMP_CASES )
def test_an_unpassed_stamp_flag_leaves_its_field_none( tmp_path, flag, getter, field ):
    """
    THE CONTROL FOR THE TEST ABOVE. Without it, a write that stamped all three
    fields unconditionally would pass every positive assertion here — and would
    silently tell the debounce a manager had run checks it never ran.
    """
    assert hio.main( _write_argv( tmp_path ) ) == hio.EXIT_OK
    assert getter( read_hold( SID, base_dir=tmp_path ) ) is None, \
        f"{flag} was not passed — its field must stay None (never run)"


@pytest.mark.parametrize( "flag,getter,_field", STAMP_CASES )
def test_a_stamp_flag_touches_only_its_own_field( tmp_path, flag, getter, _field ):
    """One flag, one field — a table-driven pass-through can cross its own wires."""
    assert hio.main( _write_argv( tmp_path, **{ flag: "now" } ) ) == hio.EXIT_OK

    hold = read_hold( SID, base_dir=tmp_path )
    for other_flag, other_getter, _ in STAMP_CASES:
        if other_flag == flag:
            continue
        assert other_getter( hold ) is None, \
            f"{flag} must not also stamp the field behind {other_flag}"


def test_all_three_stamps_can_be_set_in_one_call( tmp_path ):
    argv = _write_argv( tmp_path, **{ "--looked-in":          "2026-06-22T12:00:00+00:00",
                                      "--spinup-check":       "2026-06-23T10:00:00+00:00",
                                      "--surfaced-questions": "2026-06-23T11:00:00+00:00" } )
    assert hio.main( argv ) == hio.EXIT_OK

    hold = read_hold( SID, base_dir=tmp_path )
    assert get_last_looked_in_ts( hold )          == "2026-06-22T12:00:00+00:00"
    assert get_last_spinup_check_ts( hold )       == "2026-06-23T10:00:00+00:00"
    assert get_last_surfaced_questions_ts( hold ) == "2026-06-23T11:00:00+00:00"


def test_now_resolves_to_a_stamp_the_age_arithmetic_reads_as_fresh( tmp_path ):
    """
    "now" is only useful if the debounce dates it as ~0 seconds old. Asserting a
    non-None string would pass on a stamp no reader can subtract.
    """
    assert hio.main( _write_argv( tmp_path, **{ "--looked-in": "now" } ) ) == hio.EXIT_OK

    stamp = get_last_looked_in_ts( read_hold( SID, base_dir=tmp_path ) )
    age   = _iso_age_seconds( stamp, datetime.datetime.now( datetime.timezone.utc ).timestamp() )
    assert age is not None,   "the age helper must be able to date what `now` wrote"
    assert -5 < age < 60,     f"`now` must date as roughly now, got {age}s"


@pytest.mark.parametrize( "spelling", [ "now", "NOW", "Now", "  now  " ] )
def test_now_is_case_and_whitespace_tolerant( tmp_path, spelling ):
    assert hio.main( _write_argv( tmp_path, **{ "--looked-in": spelling } ) ) == hio.EXIT_OK
    assert get_last_looked_in_ts( read_hold( SID, base_dir=tmp_path ) ) is not None


def test_a_zone_less_timestamp_is_REFUSED_rather_than_assumed_to_be_utc( tmp_path, capsys ):
    """
    Cheech's call, 2026-08-20: normalizing a naive stamp picks a timezone the caller
    did not give. When that guess is wrong the stamp is not rejected and not
    obviously bad — it is off by the host offset, which is the size of error that
    reads as a plausible timestamp and debounces the wrong way.
    """
    argv = _write_argv( tmp_path, **{ "--looked-in": "2026-06-22T12:00:00" } )
    assert hio.main( argv ) == hio.EXIT_REFUSED
    assert not hold_path( SID, base_dir=tmp_path ).exists(), "a refused write must leave NOTHING"

    err = capsys.readouterr().err
    assert "--looked-in" in err and "offset" in err, "the refusal must name the flag and what is missing"
    assert "2026-06-22T12:00:00+00:00" in err,       "and show the caller the fix, not just the fault"


def test_the_two_readers_really_do_disagree_by_the_host_offset( tmp_path ):
    """
    THE MEASUREMENT BEHIND THE REFUSAL ABOVE, asserted rather than asserted-about.
    A guard whose justification is never executed is a comment. On a UTC-4 host the
    gap is 14400s; this asserts the gap EXISTS and equals the host offset, so the
    test still holds on a box in another zone (and goes quiet only on a UTC host,
    where the two readers genuinely agree).
    """
    naive    = "2026-06-22T12:00:00"
    as_utc   = _parse_iso( naive ).timestamp()
    as_local = datetime.datetime.fromisoformat( naive ).timestamp()

    # The offset AT THE STAMP'S OWN DATE, not today's — a host whose stamp and
    # "now" straddle a DST boundary has two different offsets, and comparing
    # against the wrong one would fail here for a reason that is not the defect.
    offset_then = datetime.datetime.fromisoformat( naive ).astimezone().utcoffset().total_seconds()

    assert as_utc - as_local == offset_then, \
        "the naive-stamp divergence is exactly the host UTC offset — that is what is refused"


@pytest.mark.parametrize( "stamp,expected", [
    ( "2026-06-22T12:00:00+00:00", "2026-06-22T12:00:00+00:00" ),
    ( "2026-06-22T12:00:00Z",      "2026-06-22T12:00:00+00:00" ),   # Zulu IS an offset
    ( "2026-06-22T08:00:00-04:00", "2026-06-22T08:00:00-04:00" ),   # preserved, not re-zoned
] )
def test_an_offset_bearing_timestamp_is_accepted_and_its_offset_preserved( tmp_path, stamp, expected ):
    assert hio.main( _write_argv( tmp_path, **{ "--looked-in": stamp } ) ) == hio.EXIT_OK
    assert get_last_looked_in_ts( read_hold( SID, base_dir=tmp_path ) ) == expected


def test_now_lands_the_same_shape_write_hold_already_stamps_into_held_at( tmp_path ):
    """
    The house format, measured rather than assumed: `write_hold` writes `held_at`
    through `_now()`, so it is offset-bearing UTC. `"now"` must match it, or this
    verb would be introducing a second timestamp convention into one file.
    """
    assert hio.main( _write_argv( tmp_path, **{ "--looked-in": "now" } ) ) == hio.EXIT_OK

    hold = read_hold( SID, base_dir=tmp_path )
    assert _parse_iso( hold[ "held_at" ] ).utcoffset() == datetime.timedelta( 0 )
    assert _parse_iso( get_last_looked_in_ts( hold ) ).utcoffset() == datetime.timedelta( 0 )


@pytest.mark.parametrize( "flag,_getter,_field", STAMP_CASES )
@pytest.mark.parametrize( "bad", [ "yesterday", "", "   ", "2026-13-45", "1750000000" ] )
def test_an_undatable_stamp_is_refused_and_leaves_nothing_behind( tmp_path, flag, _getter, _field, bad, capsys ):
    """
    WHY A REFUSAL AND NOT A PASS-THROUGH. Every reader degrades to None on a stamp
    it cannot date, so an undatable value would land under a SUCCESS banner and
    still read as "never ran" — the caller believes the poke is cleared and is
    poked anyway. That is the row's own defect wearing a green exit code.
    """
    assert hio.main( _write_argv( tmp_path, **{ flag: bad } ) ) == hio.EXIT_REFUSED
    assert not hold_path( SID, base_dir=tmp_path ).exists(), "a refused write must leave NOTHING"
    assert not list( tmp_path.glob( "*.tmp" ) ),             "nor an atomic-write sibling"

    err = capsys.readouterr().err
    assert flag in err and "ISO-8601" in err, "the refusal must name the flag and what it wanted"


def test_an_undatable_stamp_cannot_destroy_a_live_hold( tmp_path ):
    """
    The refresh case, which is where a destructive refusal costs the most: a live
    hold overwritten by a typo'd stamp would strip a running session its defense.
    """
    assert hio.main( _write_argv( tmp_path, **{ "--awaiting": "user:rick" } ) ) == hio.EXIT_OK
    before = hold_path( SID, base_dir=tmp_path ).read_bytes()

    assert hio.main( _write_argv( tmp_path, **{ "--looked-in": "whenever" } ) ) == hio.EXIT_REFUSED

    after = hold_path( SID, base_dir=tmp_path ).read_bytes()
    assert after == before,                                  "the live hold must be untouched"
    assert is_honored( read_hold( SID, base_dir=tmp_path ) ), "and still defending its session"


def test_a_stamp_is_refused_before_the_cargo_guard_can_be_reached( tmp_path, capsys ):
    """
    Ordering, asserted rather than assumed: a bad flag is a usage error and must be
    refused ahead of any filesystem inspection, so 'the refusal left the disk as it
    found it' holds by construction on this path instead of by a rollback.
    """
    path = hold_path( SID, base_dir=tmp_path )
    path.write_text( json.dumps( { "session_id": SID, "note_to_my_successor": "irreplaceable" } ) )

    assert hio.main( _write_argv( tmp_path, **{ "--looked-in": "yesterday" } ) ) == hio.EXIT_REFUSED

    err = capsys.readouterr().err
    assert "--looked-in" in err,   "the flag is the offender the caller must be told about"
    assert "note_to_my_successor" in json.loads( path.read_text() ), "and the cargo is untouched"


def test_the_banner_names_each_stamp_that_landed( tmp_path, capsys ):
    """The caller passed the flag to clear a poke; "ok" does not say whether it is."""
    argv = _write_argv( tmp_path, **{ "--looked-in": "2026-06-22T12:00:00+00:00" } )
    assert hio.main( argv ) == hio.EXIT_OK

    out = capsys.readouterr().out
    assert "2026-06-22T12:00:00+00:00" in out, "the value that landed is what the debounce reads"
    assert "--looked-in" in out
    assert "--spinup-check" not in out, "an unstamped field must not be announced as stamped"


def test_the_stamp_table_covers_every_stamp_field_write_hold_takes( tmp_path ):
    """
    THE ANTI-RECURRENCE CHECK. This bug WAS a field the writer accepted and the CLI
    could not reach. A fourth stamp added to `write_hold` and forgotten here would
    reproduce it exactly — so the table is compared against the writer's own
    signature rather than against a second hand-maintained list.
    """
    import inspect
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import write_hold as _wh

    writer_stamp_kwargs = { name for name in inspect.signature( _wh ).parameters
                            if name.startswith( "last_" ) }
    table_fields        = { field for _dest, _flag, field, _label in hio.STAMP_ARGS }

    assert table_fields == writer_stamp_kwargs, \
        "write_hold takes a stamp kwarg the CLI cannot set — that IS bug 1dcaf65c"


@pytest.mark.parametrize( "dest,flag,field,label", list( hio.STAMP_ARGS ) )
def test_every_table_row_is_wired_end_to_end( dest, flag, field, label ):
    """dest/flag/field declared together must actually agree with the parser."""
    write_parser = hio.build_parser()._subparsers._group_actions[ 0 ].choices[ "write" ]
    matched      = [ a for a in write_parser._actions if flag in a.option_strings ]

    assert matched,                       f"{flag} is in the table but not on the parser"
    assert matched[ 0 ].dest == dest,     f"{flag} must write to args.{dest}"
    assert matched[ 0 ].default is None,  "an unpassed stamp flag must default to None"
    assert label in ( matched[ 0 ].help or "" ), "the help text must say which stamp this is"


def test_build_parser_defaults_leave_every_stamp_unset():
    args = hio.build_parser().parse_args( [ "write", "--session-id", SID,
                                            "--persona", "p", "--reason", "r" ] )
    for dest, _flag, _field, _label in hio.STAMP_ARGS:
        assert getattr( args, dest ) is None, f"args.{dest} must default to None"


def test_resolve_stamp_returns_none_for_none():
    assert hio._resolve_stamp( None, "--looked-in" ) is None


def test_a_write_without_stamp_flags_WIPES_a_previously_stamped_field( tmp_path ):
    """
    CHARACTERIZATION, NOT ENDORSEMENT — reported to Cheech, not fixed here.

    `write_hold` persists EXACTLY HOLD_SCHEMA_FIELDS, so a refresh that omits the
    flags rewrites every stamp to None. A manager who stamps a look-in and later
    refreshes the hold with a new reason silently loses the stamp and is poked
    again. This predates the flags (the Python API has always behaved this way) and
    closing it is a decision about carry-forward semantics, not a pass-through fix
    — so it is pinned here where a change to it shows up as a diff.
    """
    assert hio.main( _write_argv( tmp_path, **{ "--looked-in": "now" } ) ) == hio.EXIT_OK
    assert get_last_looked_in_ts( read_hold( SID, base_dir=tmp_path ) ) is not None

    assert hio.main( _write_argv( tmp_path, **{ "--reason": "a different reason" } ) ) == hio.EXIT_OK
    assert get_last_looked_in_ts( read_hold( SID, base_dir=tmp_path ) ) is None, \
        "known gap 1dcaf65c-followup: an omitted flag WIPES the prior stamp"


def test_the_hold_lands_in_fleet_data_root_when_no_base_dir_is_given( tmp_path, monkeypatch ):
    """
    THE MISPLACED-FILE PROPERTY (row 011f1f90). A hold written anywhere but
    `fleet_data_root()` — the repo root, most often — parks the session INVISIBLY:
    neither the arbiter nor the Stop hook looks there, so the poke keeps coming.
    The whole point of adding these flags is to keep managers on the verb; the verb
    must therefore still resolve the same directory `write_hold` does when
    `--base-dir` is omitted.
    """
    import lupin_cli.claude_code.hooks.lib.heartbeat_hold as hh

    fleet_root = tmp_path / "projects-data" / "lupin"
    fleet_root.mkdir( parents=True )
    monkeypatch.setattr( hh, "fleet_data_root", lambda *a, **k: fleet_root )

    argv = [ "write", "--session-id", SID, "--persona", "Krishna 🦚",
             "--reason", "clearing a worker-verification poke", "--looked-in", "now" ]
    assert hio.main( argv ) == hio.EXIT_OK

    landed = fleet_root / f".heartbeat-hold-{SID}.json"
    assert landed.exists(), "the stamped hold must land in fleet_data_root(), where the readers look"
    assert get_last_looked_in_ts( json.loads( landed.read_text() ) ) is not None

    repo_root = pathlib.Path( __file__ ).resolve().parents[ 3 ]
    assert not ( repo_root / f".heartbeat-hold-{SID}.json" ).exists(), \
        "and NOT in the repo root — that is the 011f1f90 corpus"

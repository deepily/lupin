"""
test_memento_slot_refusal_names_the_transient_id_trap.py — store row 2dbf9618.

Run:

    cd <this worktree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" \\
      .venv/bin/python -m pytest src/tests/unit/test_memento_slot_refusal_names_the_transient_id_trap.py -q

WHAT WENT WRONG. María 🌸 wrote a root-slot memento, and ninety seconds later `self_respin`
told her it was A PRIOR HOLDER'S and refused to clear. The verdict was TRUE about the file it
read. The file she wanted was in the same directory, under a name derived from her seat's
TRANSIENT session id, because `memento_io write --session-id` trusted whatever it was handed
and she had handed it `claude_code.session_id` — the field literally named `session_id`, and
the one that changes at every /clear.

THE WRITER'S HALF OF THAT IS FIXED IN THE OTHER REPO (planning-is-prompting, this same row,
`test_memento_io_stamps_the_id_that_survives_the_clear.py`). THIS FILE IS THE READER'S HALF,
and it is deliberately the cheap half: the refusal already told the truth, so nothing here
changes a verdict. What it changes is that a seat reading the refusal can now ACT on it.

🔴 WHY A BETTER MESSAGE IS WORTH A TEST AT ALL, since it fixes no defect. The instructed
response to a memento that cannot be found is to WRITE ONE, and a seat at high context with a
clear pending is exactly the population that hand-writes a record — the single anti-pattern the
memento mechanism exists to remove. A refusal that names one candidate id when the reader has
two is what sends them down that path. It induced exactly that from a seat twelve hours before
the row was filed.

WHAT IS ASSERTED, IN BOTH DIRECTIONS — a clause that always fires is noise, not a diagnosis:

    it FIRES   when this persona has a record on disk under a different session id
    it is MUTE when the directory holds nothing else of theirs
    it NEVER names the seat's own record back to it

AND ONE THING IS DELIBERATELY *NOT* ASSERTED: that a stray record belongs to the caller. It
cannot be known from a filename, and a genuinely prior holder's file looks identical from here.
The clause reports what is on disk and names the likeliest cause; a test demanding more would
be pinning an invention.

⚠️ THE CASE-NORMALISATION HALF OF THIS ROW IS LATENT, NOT LIVE, AND ITS TEST SAYS SO. LEG 1
lower-cased the sid8 and LEG 2 did not — but LEG 2's callee `verify_seat_memento` case-folds
both sides itself, so an uppercase id was already handled. `test_both_legs_agree_on_an_uppercase
_session_id` pins the agreement so a future change to either derivation is visible; it is not
evidence that anything was ever broken, and it is not written as if it were.
"""

import pytest

from lupin_mcp.memento_slot import (
    SLOT_IO,
    SLOT_ROOT,
    short_sid,
    slot_record_path,
    stray_record_clause,
    verify_memento_at_slot,
)


# Two ids for ONE seat, differing in their first 8 characters — the whole shape of the row.
STABLE    = "3ab6f6c0-e4ab-491b-91d6-e83bc512b0bf"
TRANSIENT = "53adacf3-180b-44a7-9f56-b4d5b12e3434"


def _plant( repo, persona, sid, slot=SLOT_ROOT, text="probe\n" ):
    """
    Requires:
        - repo is an existing directory
    Ensures:
        - writes a record file at the path this module DERIVES for (persona, sid, slot),
          creating parents, and returns it
        - the path comes from `slot_record_path` rather than being spelled by hand, so a
          change to the naming scheme moves the fixture with the code instead of leaving
          it asserting against a layout that no longer exists
    """
    p = slot_record_path( repo, persona, sid, slot )
    p.parent.mkdir( parents=True, exist_ok=True )
    p.write_text( text )
    return p


# ────────────────────────────────────────────────────────── the clause, both directions

def test_the_clause_names_a_record_stamped_with_another_session_id( tmp_path ):
    """
    🔴 THE HEADLINE, and María's exact situation reconstructed: the seat is `STABLE`, and a
    record for the same persona sits on disk under `TRANSIENT`.
    """
    _plant( tmp_path, "john", TRANSIENT )

    clause = stray_record_clause( tmp_path, "john", STABLE, SLOT_ROOT )

    assert f".claude-memento-john-{short_sid( TRANSIENT )}.md" in clause, \
           f"the clause does not name the stray record:\n{clause}"
    assert "stable_session_id" in clause, "the clause does not name the id that survives a clear"
    assert "--session-id" in clause, "the clause does not tell the reader what to type instead"


def test_the_clause_is_mute_when_nothing_else_is_on_disk( tmp_path ):
    """
    🔴 THE DISCRIMINATING HALF, AND WITHOUT IT THE TEST ABOVE PROVES NOTHING. A clause
    appended unconditionally would satisfy every assertion in this file's first case while
    telling every reader, always, that they probably used the wrong id. That is not a
    diagnosis — it is a horoscope, and it would train seats to skip the paragraph.
    """
    assert stray_record_clause( tmp_path, "john", STABLE, SLOT_ROOT ) == ""


def test_the_clause_does_not_report_the_seats_own_record_as_a_stray( tmp_path ):
    """
    The seat's OWN record is on disk in the ordinary case — a LEG 2 failure (a stale
    written_at, say) happens with the correct record right there. Reporting it back as
    evidence of an id mix-up would send the reader to fix something that is already right.
    """
    _plant( tmp_path, "john", STABLE )

    assert stray_record_clause( tmp_path, "john", STABLE, SLOT_ROOT ) == ""


def test_the_clause_ignores_another_personas_records( tmp_path ):
    """
    A peer's record in the same directory is not this seat's business, and naming it would
    have a seat chasing a colleague's file. Scoped by persona, asserted rather than assumed.
    """
    _plant( tmp_path, "maria", TRANSIENT )

    assert stray_record_clause( tmp_path, "john", STABLE, SLOT_ROOT ) == ""


def test_the_clause_works_on_the_io_slot_too( tmp_path ):
    """
    The two slots put their records in different places — `io/mementos/<slug>-<sid>.md`
    against `.claude-memento-<slug>-<sid>.md` at the root. A clause that derived its glob
    from one layout would be silently mute on the other, which is the failure mode where a
    reader concludes "nothing else is here" from a search that could not look.
    """
    _plant( tmp_path, "john", TRANSIENT, slot=SLOT_IO )

    clause = stray_record_clause( tmp_path, "john", STABLE, SLOT_IO )

    assert f"john-{short_sid( TRANSIENT )}.md" in clause, f"io slot not searched:\n{clause}"


# ──────────────────────────────────────────────── the clause reaches the real refusal

def test_the_placement_refusal_carries_the_clause( tmp_path ):
    """
    THE WIRING, WHICH IS A SEPARATE CLAIM FROM "THE CLAUSE WORKS". A helper can be correct,
    covered, and never called, so this drives `verify_memento_at_slot` itself and asserts
    the sentence reaches the string a seat actually reads.

    🔴 THIS TEST WAS BLIND ON ITS FIRST WRITING AND A MUTATION ARM CAUGHT IT — recorded here
    because the trap is easy to walk back into. It originally passed the stray record itself
    as `memento_path` and then asserted that the stray's FILENAME appeared in the reason. It
    does — LEG 1's message echoes `memento_path` verbatim. So the assertion had TWO
    sufficient causes and could not tell them apart: unwiring the clause left all 49 tests
    green (measured, sha 009617dd -> 4f046395, restored and sha-verified).

    Both halves of the repair matter and neither is sufficient alone:
      · `memento_path` is now a path that is NEITHER record, so the stray's name can reach
        the reason ONLY through the clause;
      · the assertion keys on `THIS PERSONA HAS`, a phrase the base refusal does not contain.
    """
    _plant( tmp_path, "john", TRANSIENT )                     # the stray, NOT the path we pass
    elsewhere = tmp_path / "hand-written-memento.md"          # neither record nor pointer
    elsewhere.write_text( "probe\n" )

    ok, reason = verify_memento_at_slot(
        str( elsewhere ),
        repo_root    = str( tmp_path ),
        persona      = "john",
        session_id   = STABLE,
        now          = None,                # never reached — LEG 1 refuses first
        read_text_fn = lambda p: None,
        slot         = SLOT_ROOT,
    )

    assert ok is False
    assert "not at this seat" in reason, "this is not the placement refusal — the arm is wrong"
    assert "THIS PERSONA HAS" in reason, \
           f"the clause is not wired into the placement refusal:\n{reason}"
    assert f".claude-memento-john-{short_sid( TRANSIENT )}.md" in reason, \
           f"the placement refusal does not name the stray record:\n{reason}"


def test_an_ordinary_placement_refusal_is_not_padded( tmp_path ):
    """
    The negative control for the wiring: a placement failure with no stray record present
    must read exactly as it did before this change. A refusal that grew a paragraph in every
    case would be a regression dressed as an improvement.
    """
    ok, reason = verify_memento_at_slot(
        str( tmp_path / "somewhere-else.md" ),
        repo_root    = str( tmp_path ),
        persona      = "john",
        session_id   = STABLE,
        now          = None,
        read_text_fn = lambda p: None,
        slot         = SLOT_ROOT,
    )

    assert ok is False
    assert "THIS PERSONA HAS" not in reason, f"the refusal was padded with an empty finding:\n{reason}"


# ─────────────────────────────────────────────────────────────── the one derivation

@pytest.mark.parametrize( "raw, expected", [
    ( "3AB6F6C0-E4AB-491B", "3ab6f6c0" ),
    ( "3ab6f6c0-e4ab-491b", "3ab6f6c0" ),
    ( "3ab6f6c0",           "3ab6f6c0" ),
    ( None,                 ""         ),
    ( "",                   ""         ),
] )
def test_short_sid_is_one_derivation( raw, expected ):
    """
    `short_sid` is now the only place this module shortens a session id. Pinning None and
    "" alongside the ordinary cases because both reach it — `verify_memento_at_slot` is
    called with whatever the seat resolved, and a seat that resolved nothing must produce
    a comparison that fails, not a crash.
    """
    assert short_sid( raw ) == expected


def test_both_legs_agree_on_an_uppercase_session_id( tmp_path ):
    """
    ⚠️ THIS PINS AN AGREEMENT, IT DOES NOT RECORD A FIXED BUG, AND THE DIFFERENCE MATTERS.
    LEG 1 lower-cased the sid8 via `slot_record_path` while LEG 2 passed a raw `[:8]`. That
    is a genuine second derivation of one value and it is now gone. But it was LATENT:
    measured while fixing it, LEG 2's callee `reap_memento.verify_seat_memento` case-folds
    both sides itself, so an uppercase id was already handled downstream and nothing was
    ever observed failing this way.

    The test is worth keeping anyway — it makes a future divergence between the two
    derivations visible instead of silent — but a reader must not take it as evidence that
    an uppercase id ever broke anything, because it did not.
    """
    record = _plant( tmp_path, "john", STABLE )

    ok, reason = verify_memento_at_slot(
        str( record ),
        repo_root    = str( tmp_path ),
        persona      = "john",
        session_id   = STABLE.upper(),      # the seat's id, shouted
        now          = None,
        read_text_fn = lambda p: None,
        slot         = SLOT_ROOT,
    )

    # LEG 1 must PASS on an uppercase id — the record is at the right place. It then fails
    # in LEG 2 on the read_text_fn stub, which is a different and expected refusal.
    assert "not at this seat" not in reason, \
           f"LEG 1 rejected the seat's own record over letter case:\n{reason}"

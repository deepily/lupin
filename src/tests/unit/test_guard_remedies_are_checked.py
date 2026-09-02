"""
Both guards' REMEDY TEXT, checked against reality — one file, because it is one class.

THE CLASS (Tiberius 👑 `30ba7976` / `92445956`, Rio ⚡ `9350649d`, 2026-09-01)
-----------------------------------------------------------------------------
Two hook guards shipped a deny/notice message recommending the very hazard the guard
exists to prevent, found about an hour apart. A guard's refusal is tested; its remedy
is executable advice nothing checked.

Mr. Radio 🦉 ruled ONE test serving both guards beats two, so the shared predicates
live in `tests.helpers.guard_remedy` and this file is the only caller.

WHICH PREDICATE GOES WHERE — assert what the message actually CLAIMS:

    stash_guard         claims its substitutes are SAFE   -> remedy_carries_its_caveat
    commit_scope_guard  claims its shape gets REVIEWED    -> remedy_is_readable

Neither implies the other: both original remedies were perfectly legal commands.

⚠️ THE NEGATIVE CONTROLS BELOW ARE NOT DECORATION. An empty `missing`/`broken` list
is the same output whether the check did its job or looked at nothing, so each
predicate is also pointed at a message that MUST fail it. Without those, a green here
would only prove the assertions run.

🔴 AND THE TWO PREDICATES ARE ASYMMETRIC ABOUT THAT, WHICH IS A DEFECT IN THE HELPER,
NOT IN ITS CALLERS (Mr. Radio 🦉 and Rio ⚡, independently, 2026-09-01).
`remedy_is_readable` REFUSES a vacuous pass — it asserts it found a command matching
its prefix, so an empty result can only mean "every remedy parsed".
`remedy_carries_its_caveat` returns only what is MISSING, never what it MATCHED, so
its `[]` collapses two opposite facts:

    every hazard it named is qualified          <- the pass we want
    the message named no table hazard at all    <- measured nothing

Measured this turn: `kill_guard` and `merge_head_guard` both recommend indented
commands and both return `[]` from the SECOND kind. A test on either today would be
green by measuring nothing.

⇒ Until the helper reports its matches, the vacuity guard belongs to the CALLER, and
`test_the_stash_deny_actually_names_a_table_hazard` below is it. It is not decoration
either: delete it and `test_the_stash_deny_qualifies_every_hazard_it_names` silently
becomes an assertion about nothing the moment the deny text is reworded.

⚠️ GREEN MEANS "carries the caveats we know to demand", never "this advice is safe" —
the hazard table is a floor and says so in its own docstring.

Venue: :7999-eligible. Pure string work; no git, no server, no filesystem.
"""
import re

from lupin_cli.claude_code.hooks.lib.stash_guard import _deny_reason_for
from lupin_cli.claude_code.hooks.lib.commit_scope_guard import (
    git_commit_match, _pathspec_of, _notice_for,
)
from lupin_cli.claude_code.hooks.lib.merge_head_guard import (
    KIND_SQUASH, KIND_MERGE, _deny_reason_for as _merge_head_deny,
)
from tests.helpers.guard_remedy import (
    HAZARD_CAVEATS, remedy_commands, remedy_is_readable, remedy_carries_its_caveat,
)


def _read( command ):
    """
    Ensures:
        - returns ( paths, why ) exactly as the commit scope guard would see it
        - returns ( None, <why> ) when the matcher never engages, which is the shape
          `remedy_is_readable` reads as "the guard cannot act on its own advice"
    """
    match = git_commit_match( command )
    if not match:
        return None, "the guard's matcher never engaged on its own recommended command"
    return _pathspec_of( command, match )


# ---------------------------------------------------------------------------
# stash_guard — the message claims its substitutes are safe. Is it HONEST?
# ---------------------------------------------------------------------------

def test_the_stash_deny_qualifies_every_hazard_it_names():
    missing = remedy_carries_its_caveat( _deny_reason_for( "push" ) )
    assert missing == [], (
        "the stash deny recommends a hazardous operation without its caveat nearby: "
        f"{missing} — this is the shape of 30ba7976, where `git checkout -- <path>` "
        "was called safe"
    )


def test_the_stash_deny_actually_names_a_table_hazard():
    """
    THE VACUITY GUARD for the assertion above — see this module's docstring.

    `remedy_carries_its_caveat` reports only what is MISSING, so its `[]` cannot tell
    "every hazard is qualified" from "no hazard was named". This asserts the second
    reading is false, which is the only thing that makes the first one evidence.

    Belongs here rather than in the helper only because the helper is another seat's
    file and live; when it reports its matches, this moves inside it.
    """
    text    = _deny_reason_for( "push" )
    matched = [ p for p in HAZARD_CAVEATS if re.search( p, text ) ]
    assert matched, (
        "the stash deny names none of the table's hazards, so the caveat assertion "
        "above is passing against nothing — either the deny text was reworded away "
        f"from {list( HAZARD_CAVEATS )} or the table drifted"
    )


def test_the_stash_deny_names_a_substitute_at_all():
    """A message recommending nothing would pass the caveat check vacuously."""
    assert remedy_commands( _deny_reason_for( "push" ) ), (
        "the deny text sets off no indented substitute — the extraction is stale and "
        "the caveat assertion above is then passing against nothing"
    )


def test_the_caveat_check_can_fail():
    """NEGATIVE CONTROL — the exact sentence 30ba7976 removed must still be caught."""
    unqualified = (
        "USE INSTEAD:\n"
        "  · `git checkout <sha> -- <path>` — it touches nothing shared, races nothing.\n"
    )
    assert remedy_carries_its_caveat( unqualified ), (
        "the withdrawn sentence passed the caveat check — the check is measuring "
        "nothing, and every green above is worthless"
    )


# ---------------------------------------------------------------------------
# merge_head_guard — ONE of its two branches is checkable. The other is not.
#
# Rio's reset row (`37fb6c5a`, `r"git\s+reset\b"` with no lookahead) is what made
# the SQUASH branch testable: before it, this guard returned [] because the table
# named nothing it recommends. The MERGE branch still does, and is deliberately
# left uncovered below rather than given a green that measures nothing.
# ---------------------------------------------------------------------------

def test_the_squash_refusal_qualifies_the_reset_it_recommends():
    """
    The squash remedy recommends a bare `git reset`. In a shared checkout that
    clears the WHOLE index, including a peer's staged work — so the message has to
    say so, and the table row exists to make that a check rather than a habit.
    """
    text    = _merge_head_deny( KIND_SQUASH )
    matched = [ p for p in HAZARD_CAVEATS if re.search( p, text ) ]
    assert matched, (
        "the squash refusal names none of the table's hazards, so the assertion "
        "below would pass against nothing — the remedy was reworded, or the reset "
        "row was removed"
    )
    missing = remedy_carries_its_caveat( text )
    assert missing == [], (
        f"the squash refusal recommends a hazardous operation unqualified: {missing}"
    )


def test_the_merge_branch_is_not_covered_and_this_records_why():
    """
    🔴 A DELIBERATE NON-TEST, pinned so the gap is visible rather than forgotten.

    The MERGE branch recommends only the escape hatch and "ask the owner" — it names
    no operation in the table, so `remedy_carries_its_caveat` returns [] by measuring
    nothing. Asserting on that would be the vacuous green this whole file exists to
    refuse. This asserts the VACUITY itself, so the day the branch starts naming a
    table hazard, this test fails and tells the next reader to write the real one.
    """
    text    = _merge_head_deny( KIND_MERGE, "a" * 40 )
    matched = [ p for p in HAZARD_CAVEATS if re.search( p, text ) ]
    assert matched == [], (
        f"the merge branch now names table hazard(s) {matched} — it has become "
        "checkable, so replace this non-test with a real caveat assertion"
    )


# ---------------------------------------------------------------------------
# commit_scope_guard — the message claims its shape gets reviewed. Does it WORK?
# ---------------------------------------------------------------------------

def test_the_not_reviewed_notice_recommends_a_command_the_guard_can_read():
    broken = remedy_is_readable(
        _notice_for( "a reason" ), _read, "git commit",
        substitutions={ "<paths>": "src/a.py" },
    )
    assert broken == [], (
        "the NOT REVIEWED notice recommends a commit shape the guard itself cannot "
        f"read: {broken} — this is the shape of 9350649d, where the advice was legal "
        "and still unreviewable"
    )


def test_the_readable_check_can_fail():
    """NEGATIVE CONTROL — the unreviewable shape must still be caught."""
    broken = remedy_is_readable(
        "The shape that gets reviewed:\n"
        "  git commit -F /dev/stdin -- <paths> <<'EOF'\n",
        _read, "git commit", substitutions={ "<paths>": "src/a.py" },
    )
    assert broken, (
        "an attached heredoc passed the readable check — the check is measuring "
        "nothing, and every green above is worthless"
    )

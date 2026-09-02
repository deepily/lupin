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

⚠️ GREEN MEANS "carries the caveats we know to demand", never "this advice is safe" —
the hazard table is a floor and says so in its own docstring.

Venue: :7999-eligible. Pure string work; no git, no server, no filesystem.
"""
from lupin_cli.claude_code.hooks.lib.stash_guard import _deny_reason_for
from lupin_cli.claude_code.hooks.lib.commit_scope_guard import (
    git_commit_match, _pathspec_of, _notice_for,
)
from tests.helpers.guard_remedy import (
    remedy_commands, remedy_is_readable, remedy_carries_its_caveat,
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

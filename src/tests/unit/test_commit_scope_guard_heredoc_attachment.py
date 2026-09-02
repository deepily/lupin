"""
Which `git commit` shapes the scope guard can READ, and which make it give up.

THE SHAPE (row 084adbaf, addenda 10689 + 10690)
-----------------------------------------------
The guard reads which paths a commit names and checks them against the committer's
section of `.claude-session.md`. It refuses to guess: handed a command it cannot
parse it ALLOWS the commit and prints `NOT REVIEWED — <why>`. That notice is easy to
walk past, so a commit lands unexamined while looking like a clean one.

Measured 2026-09-01 on a real commit (`623a351b`): `git commit -F /dev/stdin --
<path> <<'EOF' ... EOF` went unreviewed.

🔴 WHAT THIS FILE PINS IS THE **ATTACHMENT** RULE, NOT A RULE ABOUT HEREDOCS.
A heredoc in a PRECEDING command — the mandated pattern, write the message file then
commit cleanly — is read fine. Only a heredoc or here-string on the `git commit`
invocation ITSELF defeats the parse. The first cut of this rule said "no heredoc
anywhere in a git commit command", which read literally bans the mandated pattern; it
was withdrawn the same evening. An ambiguous rule fails the way an ambiguous pointer
fails, so the two directions are pinned SEPARATELY below rather than in one list.

THE MECHANISM, which PREDICTS both tables rather than describing them:
`_pathspec_of` reads only `command[ match.end(): ]` — the tail AFTER the `git commit`
match — then splits at the first `;`, `&`, `|` or newline. A preceding heredoc is not
in that tail and can never reach the check. What IS in the tail meets
`_strip_heredoc_bodies`, which removes the heredoc BODY and leaves the operator; the
surviving `<<` then trips `_without_redirections`, which answers "not sure".

⚠️ THE REVIEWED CASES ARE THE POSITIVE CONTROL AND ARE NOT DECORATION. Without them a
BYPASSED result proves only that the probe says bypass — the same trap row 084adbaf's
body already records from the other side, where a probe used a command the guard
allows and every negative it returned meant nothing.

⚠️ These tests do NOT assert the give-up is CORRECT. Whether it should fire when the
paths already parse is an open ruling for Rick — in every bypassed case below the
pathspec is unambiguous, so the refusal may be wider than the doubt warrants. This
file pins TODAY'S behaviour so that a change to it is visible rather than silent.

Venue: :7999-eligible. Pure string parsing; no git, no server, no filesystem.
"""
import pytest

from lupin_cli.claude_code.hooks.lib.commit_scope_guard import (
    git_commit_match, _pathspec_of,
)

PATHS = "src/a.py"
BODY  = "subject\n\nbody line\n"


def _read( command ):
    """
    Ensures:
        - returns ( paths, why ) as the guard itself would see the command
        - raises rather than returning a verdict when the matcher does not fire at
          all: a command the guard never engages on is a DIFFERENT outcome from one
          it declines to read, and collapsing the two would hide a matcher defect
          behind a parse result
    """
    match = git_commit_match( command )
    assert match, f"the guard's matcher never engaged on: {command!r}"
    return _pathspec_of( command, match )


# ---------------------------------------------------------------------------
# READABLE — the positive control. A heredoc BEFORE the commit is out of scope.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "label,command", [
    ( "the mandated pattern",
      f"cat > msg.txt <<'EOF'\n{BODY}EOF\ngit commit -F msg.txt -- {PATHS}" ),
    ( "the mandated pattern, && joined",
      f"cat > msg.txt <<'EOF'\n{BODY}EOF\n&& git commit -F msg.txt -- {PATHS}" ),
    ( "the mandated pattern, output redirected",
      f"cat > msg.txt <<'EOF'\n{BODY}EOF\ngit commit -F msg.txt -- {PATHS} 2>&1 | tail -3" ),
    ( "a heredoc BODY that names a git commit of its own",
      f"cat > msg.txt <<'EOF'\nsee git commit -F x -- evil.py\nEOF\ngit commit -F msg.txt -- {PATHS}" ),
    ( "message from a file",             f"git commit -F msg.txt -- {PATHS}" ),
    ( "/dev/stdin with NO heredoc",      f"git commit -F /dev/stdin -- {PATHS}" ),
    ( "process substitution",            f"git commit -F <(printf m) -- {PATHS}" ),
    ( "piped in",                        f"printf m | git commit -F - -- {PATHS}" ),
    ( "inline -m",                       f'git commit -m "subject" -- {PATHS}' ),
] )
def test_the_guard_READS_these_and_sees_the_real_pathspec( label, command ):
    """
    Each of these must yield the pathspec, not an "I am not sure".

    This half is what makes the other half mean something, and it is also the half
    that protects the mandated workflow: if a future widening of the give-up makes
    `cat > msg.txt <<'EOF'` unreadable, every commit this fleet makes goes unreviewed
    and nothing else in the tree would say so.
    """
    paths, why = _read( command )
    assert why is None, f"{label}: the guard gave up on a readable command — {why}"
    assert paths == [ PATHS ], f"{label}: parsed {paths!r}"


# ---------------------------------------------------------------------------
# UNREADABLE — a heredoc or here-string ON the commit line itself.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "label,command", [
    ( "-F /dev/stdin with a heredoc",
      f"git commit -F /dev/stdin -- {PATHS} <<'EOF'\n{BODY}EOF" ),
    ( "-F - with a heredoc",
      f"git commit -F - -- {PATHS} <<'EOF'\n{BODY}EOF" ),
    ( "the MESSAGE-FILE form, heredoc still attached",
      f"git commit -F msg.txt -- {PATHS} <<'EOF'\n{BODY}EOF" ),
    ( "an UNQUOTED heredoc word",
      f"git commit -F /dev/stdin -- {PATHS} <<EOF\n{BODY}EOF" ),
    ( "a here-STRING",
      f"git commit -F /dev/stdin -- {PATHS} <<< 'body'" ),
] )
def test_the_guard_GIVES_UP_on_a_heredoc_attached_to_the_commit( label, command ):
    """
    Today the guard declines these and the caller ALLOWS with a notice.

    ⚠️ This asserts the CURRENT contract, not that it is the right one. The third
    case is the one worth staring at: it carries the mandated `-F msg.txt`, so
    following the message-file rule is NOT sufficient on its own — the heredoc has to
    be off the commit line as well.
    """
    paths, why = _read( command )
    assert paths is None, f"{label}: expected a give-up, got the pathspec {paths!r}"
    assert why, f"{label}: gave up without saying why — the notice is the only signal"


def test_the_two_halves_differ_ONLY_in_where_the_heredoc_SITS():
    """
    The controlled pair, because the tables above vary several things at once.

    One heredoc, one body, one pathspec, one message source. The ONLY difference is
    whether the heredoc is attached to the `git commit` or to a preceding command —
    so this, and not the parametrised lists, is what establishes attachment as the
    variable that matters.
    """
    before   = f"cat > msg.txt <<'EOF'\n{BODY}EOF\ngit commit -F msg.txt -- {PATHS}"
    attached = f"git commit -F msg.txt -- {PATHS} <<'EOF'\n{BODY}EOF"

    assert _read( before )   == ( [ PATHS ], None )
    assert _read( attached )[ 0 ] is None

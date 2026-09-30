"""
The merge-head guard: a `git commit` during a live merge must be refused.

WHY THIS EXISTS. A merge is a two-step operation over TREE-GLOBAL state — `git
merge` stages the result and sets MERGE_HEAD, a later `git commit` writes the
merge commit. In between, the merge belongs to the tree rather than to whoever
started it, so any seat committing there concludes somebody else's merge under
its own message. That happened on 2026-08-31 (row f3306404): parentage lost, the
lane landed with one parent, ten shas non-ancestors, four seats and about an hour
to repair.

🔴 THE TESTS THAT MATTER MOST ARE THE THREE THAT USE REAL GIT, not an injected
reader. The whole hazard is that the OBVIOUS ways to look are wrong:

    test -f .git/MERGE_HEAD    absent in a LINKED WORKTREE — reports no merge
                               while one is live, in every linked worktree, which
                               is all but one of this repo's trees
    git status --porcelain     silent once conflicts are staged
    git status --porcelain=v2  silent too

A test that only ever drives an injected `merge_reader` proves the plumbing
around the check and says NOTHING about the check itself — it would pass just as
happily over the broken path form. So `TestAgainstRealGit` builds actual repos,
including a linked worktree with a live merge, and measures all three.

⚠️ EVERY FIXTURE HERE HONOURS ITS INPUT. A `merge_reader` that returned the same
sha whatever directory it was handed could not tell a guard that respects
`git -C <path>` from one that ignores it, and every assertion written over it
would inherit that blindness. The readers below RECORD the directory they were
called with, and the `-C` tests assert on that recording rather than on the
verdict alone.
"""
import os
import subprocess

import pytest

from lupin_cli.claude_code.hooks.lib.merge_head_guard import (
    merge_head_deny_reason,
    _squash_in_flight,
    SQUASH_MSG_ARGV,
    build_merge_head_deny_response,
    _guard_disabled,
    _hatch_in_prefix,
    _target_directory,
    _live_merge_head,
    MERGE_HEAD_ARGV,
)


LIVE_SHA = "a749abc86decd4689dd1b6652d4a6f0121383c62"


def _recording_reader( sha=LIVE_SHA ):
    """
    A merge reader that REMEMBERS which directory it was asked about.

    Ensures:
        - returns <sha> for every call
        - exposes `.seen`, the list of directories it was handed, so a test can
          assert the guard looked in the right tree rather than merely denying
    """
    seen = []

    def reader( cwd ):
        seen.append( cwd )
        return sha

    reader.seen = seen
    return reader


def _no_squash( _cwd ):
    """A tree with no squash merge staged."""
    return False


def _guard( command, **kw ):
    """
    Drive the guard over one Bash command, live MERGE_HEAD by default.

    Both readers are stubbed by default. The squash one defaults to False so that
    a test about MERGE_HEAD is measuring MERGE_HEAD — otherwise a broken first
    probe would be covered by the second and every test would still pass.
    """
    kw.setdefault( "enabled", True )
    kw.setdefault( "merge_reader", _recording_reader() )
    kw.setdefault( "squash_reader", _no_squash )
    return merge_head_deny_reason( "Bash", { "command": command }, **kw )


def _no_merge( _cwd ):
    """A tree with no merge in flight."""
    return None


# ═════════════════════════════════════════════════════════════════════════════
# THE VERDICT
# ═════════════════════════════════════════════════════════════════════════════

class TestTheVerdict:

    def test_a_commit_during_a_live_merge_is_denied( self ):
        assert _guard( "git commit -m 'my work'" ) is not None

    def test_the_same_commit_with_no_merge_live_is_allowed( self ):
        """
        THE CONTROL. Without it, a guard that denied every `git commit`
        unconditionally would satisfy the test above.
        """
        assert _guard( "git commit -m 'my work'", merge_reader=_no_merge ) is None

    def test_a_command_that_is_not_a_commit_is_allowed_even_mid_merge( self ):
        """
        THE SECOND CONTROL, and it is the one that separates this guard from a
        blanket refusal: a live merge does not make every command dangerous.
        """
        for command in ( "git status", "ls -la", "git merge --abort", "git log -1" ):
            assert _guard( command ) is None, f"{command!r} was refused and is not a commit"

    def test_a_non_commit_never_reaches_the_git_read( self ):
        """
        HOT-PATH COST, pinned rather than asserted in a comment.

        This runs inside PreToolUse — before EVERY tool call in EVERY session. If
        the guard read git before checking whether the command is a commit, every
        `ls` in the fleet would pay for a subprocess. The match is deliberately
        first, and this is the only test that can see the ordering: a guard with
        the two swapped returns the same verdict on every case above.
        """
        reader = _recording_reader()
        for command in ( "ls -la", "git status", "pytest -q", "echo hello" ):
            _guard( command, merge_reader=reader )
        assert reader.seen == [], (
            f"git was read for a non-commit {reader.seen!r} - the match must come "
            "first or every tool call in the fleet pays for a subprocess"
        )

    def test_a_pathspec_commit_is_refused_too( self ):
        """
        Git itself refuses a partial commit during a merge ("fatal: cannot do a
        partial commit during a merge"), so this deny costs a command that was
        going to be rejected anyway. It is kept because carving it out would add
        a condition whose only effect is one more way to be wrong.
        """
        assert _guard( "git commit -m x -- src/foo.py" ) is not None

    def test_a_commit_with_dash_a_is_refused( self ):
        assert _guard( "git commit -am 'sweep'" ) is not None


# ═════════════════════════════════════════════════════════════════════════════
# WHAT THE REFUSAL SAYS
# ═════════════════════════════════════════════════════════════════════════════

class TestTheRefusalText:

    def test_it_names_the_live_merge_sha( self ):
        """Without the sha the committer cannot identify the merge before acting."""
        assert LIVE_SHA[ :12 ] in _guard( "git commit -m x" )

    def test_it_warns_that_porcelain_will_not_show_the_merge( self ):
        """
        The seat's next instinct is to check `git status --porcelain` and be
        reassured by nothing. A refusal that sends them there has made things
        worse than silence.
        """
        assert "--porcelain" in _guard( "git commit -m x" )

    def test_it_gives_the_hatch_verbatim( self ):
        """
        The instruction has to be copyable. stash_guard's hatch spent most of its
        life broken while its deny message told people to use it.
        """
        assert "LUPIN_ALLOW_MERGE_COMMIT=1" in _guard( "git commit -m x" )

    def test_the_squash_refusal_does_not_lead_with_the_hatch( self ):
        """
        🔴 THE REFUSAL'S INSTRUCTION MUST NOT CAUSE THE HARM IT REFUSES.

        Found by Rachel 🕊️ on review, 2026-08-31. The squash refusal pointed at the
        escape hatch, and the hatch is exactly what a seat must NOT reach for when
        the staged squash is not theirs: using it LANDS the squash under their
        message, which is the damage this guard exists to prevent. A seat meeting
        this refusal is almost always trying to commit their OWN unrelated work.

        A refusal whose instruction produces the harm is worse than no refusal,
        because it carries authority.
        """
        squash = _guard(
            "git commit -m 'my own work'", merge_reader=_no_merge, squash_reader=lambda _c: True
        )
        assert "git reset" in squash, "the squash refusal does not offer the safe way out"
        assert "DO NOT use the hatch" in squash, (
            "the squash refusal does not warn against the hatch - a seat clearing "
            "somebody else's squash would land it under their own message"
        )

    def test_the_squash_refusal_warns_that_reset_leaves_the_files_unstaged( self ):
        """
        `git reset` clears SQUASH_MSG and keeps every file — MEASURED — but it leaves
        the lane's files in the worktree UNSTAGED. A later `git add -A` or
        `git commit -a` sweeps them back in and lands them without ancestry: the same
        damage reached by a second route. The remedy is only safe with that said.
        """
        squash = _guard(
            "git commit -m x", merge_reader=_no_merge, squash_reader=lambda _c: True
        )
        assert "UNSTAGED" in squash
        assert "BY NAME"  in squash

    def test_the_merge_refusal_does_not_tell_you_to_clear_it( self ):
        """
        THE OTHER HALF, and it is why the two states cannot share one remedy. A live
        MERGE_HEAD is NOT yours to clear — `git merge --abort` destroys the owner's
        conflict resolution. `git reset` is the right answer for a squash and the
        wrong one here.
        """
        merge = _guard( "git commit -m x" )
        assert "git reset" not in merge, (
            "the merge refusal offers the squash remedy - aborting a peer's live "
            "merge destroys their conflict resolution"
        )
        assert "ask the owner to finish" in merge

    def test_the_two_remedies_are_not_the_same_text( self ):
        """
        THE CONTROL. Without it, a single shared remedy block passes both tests above
        by accident as soon as it happens to contain the right words.
        """
        merge  = _guard( "git commit -m x" )
        squash = _guard( "git commit -m x", merge_reader=_no_merge, squash_reader=lambda _c: True )
        assert merge.split( "IF " )[ 1: ] != squash.split( "IF " )[ 1: ]

    def test_it_names_its_own_residuals( self ):
        """
        A RESIDUAL RECORDED ONLY IN A DOCSTRING AND A TEST IS INVISIBLE TO THE
        PERSON WHO MEETS THE GUARD. The refusal is the only text a seat reads, and a
        seat that has been refused once will reasonably assume the guard covers
        every way a merge gets concluded. It does not: `git merge --continue` is not
        checked and a squash merge sets no MERGE_HEAD at all.

        Raised by mr radio 🦉 on review — "make sure the gap is legible where a seat
        will meet it, not only in the test."
        """
        reason = _guard( "git commit -m x" )
        assert "merge --continue" in reason, "the refusal does not admit what it misses"
        assert "squash" not in reason.split( "WHAT THIS GUARD DOES NOT COVER" )[ 1 ], (
            "the refusal still lists squash as a gap - Rick ruled it CLOSED on "
            "2026-08-31, and a stale residual list is worse than none because a "
            "reader trusts it"
        )

    def test_it_says_that_silence_is_not_evidence( self ):
        """
        The dangerous reading of a scoped guard is the inverse one: no refusal
        therefore no merge. That inference is false for both residuals, so the
        refusal has to deny it in words.
        """
        assert "not evidence" in _guard( "git commit -m x" )

    def test_it_names_the_incident_row( self ):
        assert "f3306404" in _guard( "git commit -m x" )

    def test_the_reasons_for_two_different_merges_are_distinguishable( self ):
        """
        A message that reads the same for any merge cannot be used to tell one
        from another, however precisely it is worded.
        """
        one = _guard( "git commit -m x", merge_reader=_recording_reader( "1" * 40 ) )
        two = _guard( "git commit -m x", merge_reader=_recording_reader( "2" * 40 ) )
        assert one != two


# ═════════════════════════════════════════════════════════════════════════════
# WHICH TREE GETS CHECKED
# ═════════════════════════════════════════════════════════════════════════════

class TestTheTargetTree:
    """
    WHICH TREE THE MERGE STATE IS READ FROM, which is the difference between this
    guard working in this fleet and not.

    MEASURED against the real hook, live merge in a linked worktree, hook standing
    in the main checkout:

        git -C <merge tree> commit       DENY     - -C was handled from the start
        cd <merge tree> && git commit    ALLOWED  - the miss, now fixed

    The Bash tool resets its working directory to the session root on every call, so
    a seat working in a worktree types `cd <worktree> && git ...` all day. A guard
    that only followed -C would have missed nearly every commit in the fleet while
    passing every test that used an injected reader.

    ⚠️ These assert on the DIRECTORY THE READER WAS HANDED, never on the verdict. A
    guard that ignored cd and -C entirely would still deny in most of these cases,
    so a verdict assertion could not tell the two apart.
    """

    @pytest.fixture
    def trees( self, tmp_path ):
        """Two real directories, because the resolver checks that its target exists."""
        seat  = tmp_path / "seat";  seat.mkdir()
        other = tmp_path / "other"; other.mkdir()
        ( seat / "sub" ).mkdir()
        return str( seat ), str( other )

    def test_a_plain_commit_is_judged_against_the_hook_cwd( self, trees ):
        seat, _ = trees
        reader  = _recording_reader()
        _guard( "git commit -m x", cwd=seat, merge_reader=reader )
        assert reader.seen == [ seat ]

    def test_a_leading_cd_retargets_the_check( self, trees ):
        """THE FLEET'S ACTUAL SHAPE. Without this the guard reads the session tree."""
        seat, other = trees
        reader = _recording_reader()
        _guard( f"cd {other} && git commit -m x", cwd=seat, merge_reader=reader )
        assert reader.seen == [ other ]

    def test_a_relative_cd_resolves_against_the_hook_cwd( self, trees ):
        seat, _ = trees
        reader  = _recording_reader()
        _guard( "cd sub && git commit -m x", cwd=seat, merge_reader=reader )
        assert reader.seen == [ os.path.join( seat, "sub" ) ]

    def test_the_last_cd_before_the_commit_wins( self, trees ):
        seat, other = trees
        reader = _recording_reader()
        _guard( f"cd {seat} ; cd {other} && git commit -m x", cwd=seat, merge_reader=reader )
        assert reader.seen == [ other ]

    def test_a_cd_AFTER_the_commit_does_not_count( self, trees ):
        """It has not run yet when the commit does."""
        seat, other = trees
        reader = _recording_reader()
        _guard( f"git commit -m x && cd {other}", cwd=seat, merge_reader=reader )
        assert reader.seen == [ seat ]

    def test_dash_C_retargets_the_check_at_the_named_tree( self, trees ):
        seat, other = trees
        reader = _recording_reader()
        _guard( f"git -C {other} commit -m x", cwd=seat, merge_reader=reader )
        assert reader.seen == [ other ]

    def test_cd_and_dash_C_compose_with_dash_C_applied_last( self, trees ):
        """git -C is relative to the directory the shell is already standing in."""
        seat, other = trees
        reader = _recording_reader()
        _guard( f"cd {seat} && git -C {other} commit -m x", cwd=seat, merge_reader=reader )
        assert reader.seen == [ other ]

    def test_an_unresolvable_target_falls_back_to_the_hook_cwd( self, trees ):
        """
        THE PROPERTY THAT MAKES THE LOOSE `cd` SCAN SAFE. A `cd` misread out of a
        quoted literal would otherwise send the check at a directory that does not
        exist, where it reads as NO MERGE and allows. Falling back to cwd degrades
        to the behaviour before this scan existed instead of losing the check.
        """
        seat, _ = trees
        reader  = _recording_reader()
        _guard( "cd /no/such/directory/anywhere && git commit -m x", cwd=seat, merge_reader=reader )
        assert reader.seen == [ seat ]

    def test_cd_dash_is_ignored( self, trees ):
        """`cd -` is the previous directory and is not knowable from the text."""
        seat, _ = trees
        reader  = _recording_reader()
        _guard( "cd - && git commit -m x", cwd=seat, merge_reader=reader )
        assert reader.seen == [ seat ]

    def test_lowercase_dash_c_is_a_config_override_and_never_a_directory( self, trees ):
        """`-c user.name=x` is not a path. Reading it as one would check nowhere."""
        seat, _ = trees
        reader  = _recording_reader()
        _guard( "git -c user.name=nobody commit -m x", cwd=seat, merge_reader=reader )
        assert reader.seen == [ seat ]

    def test_a_bare_commit_with_no_cd_and_no_dash_C_passes_cwd_through_unchanged( self ):
        """
        Including None, which means "the process cwd" — the resolver must not
        substitute a value the caller did not give it.
        """
        reader = _recording_reader()
        _guard( "git commit -m x", cwd=None, merge_reader=reader )
        assert reader.seen == [ None ]


# ═════════════════════════════════════════════════════════════════════════════
# THE ESCAPE HATCH
# ═════════════════════════════════════════════════════════════════════════════

class TestTheEscapeHatch:

    def test_the_inline_prefix_allows_the_commit( self ):
        """
        The form the deny message tells people to use. It CANNOT be honoured
        through os.environ — the hook is a separate process and the prefix belongs
        to a command that has not run — so it is read off the command itself.
        """
        assert _guard( "LUPIN_ALLOW_MERGE_COMMIT=1 git commit -m 'conclude my merge'" ) is None

    @pytest.mark.parametrize( "value", [ "1", "true", "on", "yes", "TRUE", " Yes " ] )
    def test_every_documented_truthy_spelling_is_honoured( self, value ):
        assert _guard( f"LUPIN_ALLOW_MERGE_COMMIT={value.strip()} git commit -m x" ) is None

    def test_a_falsy_value_does_not_open_the_hatch( self ):
        for value in ( "0", "false", "off", "no", "" ):
            assert _guard( f"LUPIN_ALLOW_MERGE_COMMIT={value} git commit -m x" ) is not None, \
                f"the hatch opened on {value!r}"

    def test_an_unrelated_env_prefix_does_not_open_the_hatch( self ):
        """
        The split that matters: arbitrary env prefixes still deny, only the hatch
        prefix passes. stash_guard's hatch was broken for months precisely because
        the two were indistinguishable.
        """
        assert _guard( "GIT_AUTHOR_NAME=nobody git commit -m x" ) is not None

    def test_the_flag_elsewhere_in_the_line_does_not_unlock_a_later_commit( self ):
        """Scoped to THIS invocation's own prefix, never to the whole line."""
        assert _guard( "echo LUPIN_ALLOW_MERGE_COMMIT=1; git commit -m x" ) is not None

    def test_the_process_environment_also_disables_the_guard( self ):
        """For a session deliberately exported into merge work."""
        assert merge_head_deny_reason(
            "Bash", { "command": "git commit -m x" },
            env={ "LUPIN_ALLOW_MERGE_COMMIT": "1" }, merge_reader=_recording_reader(),
        ) is None

    def test_a_clean_environment_leaves_the_guard_armed( self ):
        assert merge_head_deny_reason(
            "Bash", { "command": "git commit -m x" },
            env={}, merge_reader=_recording_reader(),
        ) is not None

    def test_guard_disabled_reads_the_real_environment_when_none_is_injected( self, monkeypatch ):
        monkeypatch.delenv( "LUPIN_ALLOW_MERGE_COMMIT", raising=False )
        assert _guard_disabled() is False
        monkeypatch.setenv( "LUPIN_ALLOW_MERGE_COMMIT", "1" )
        assert _guard_disabled() is True

    def test_hatch_in_prefix_on_the_empty_cases( self ):
        assert _hatch_in_prefix( None ) is False
        assert _hatch_in_prefix( "" )   is False
        assert _hatch_in_prefix( " SOMETHING_ELSE=1 " ) is False

    def test_an_explicit_enabled_false_disables_the_guard( self ):
        assert merge_head_deny_reason(
            "Bash", { "command": "git commit -m x" },
            enabled=False, merge_reader=_recording_reader(),
        ) is None


# ═════════════════════════════════════════════════════════════════════════════
# THE PAYLOAD IT IS HANDED
# ═════════════════════════════════════════════════════════════════════════════

class TestMalformedPayloads:

    def test_a_non_bash_tool_is_ignored( self ):
        assert merge_head_deny_reason(
            "Read", { "command": "git commit -m x" },
            enabled=True, merge_reader=_recording_reader(),
        ) is None

    def test_a_tool_input_that_is_not_a_dict_is_ignored( self ):
        assert merge_head_deny_reason(
            "Bash", "git commit -m x", enabled=True, merge_reader=_recording_reader(),
        ) is None

    def test_a_missing_or_empty_or_non_string_command_is_ignored( self ):
        for tool_input in ( {}, { "command": "" }, { "command": None }, { "command": 17 } ):
            assert merge_head_deny_reason(
                "Bash", tool_input, enabled=True, merge_reader=_recording_reader(),
            ) is None, f"{tool_input!r} was not ignored"


# ═════════════════════════════════════════════════════════════════════════════
# FAIL OPEN
# ═════════════════════════════════════════════════════════════════════════════

class TestFailOpen:

    def test_a_reader_that_raises_allows_the_commit( self ):
        """
        A guard that blocks all work when its own check errors is worse than the
        hazard it prevents. This exercises the backstop rather than asserting it.
        """
        def exploding( _cwd ):
            raise RuntimeError( "git went away" )

        assert _guard( "git commit -m x", merge_reader=exploding ) is None

    def test_a_directory_that_does_not_exist_reads_as_no_merge( self ):
        assert _live_merge_head( "/nonexistent/path/for/this/test" ) is None

    def test_a_directory_that_is_not_a_repo_reads_as_no_merge( self, tmp_path ):
        assert _live_merge_head( str( tmp_path ) ) is None

    def test_a_timeout_reads_as_no_merge( self, monkeypatch ):
        def slow( *a, **kw ):
            raise subprocess.TimeoutExpired( cmd="git", timeout=5 )

        monkeypatch.setattr( subprocess, "run", slow )
        assert _live_merge_head( "/tmp" ) is None

    def test_an_exit_zero_with_no_output_reads_as_no_merge( self, monkeypatch ):
        """
        Belt to the exit-code braces. A `git` that succeeded and said nothing has
        not told us a merge is live, and minting a refusal from an empty sha would
        put "MERGE_HEAD " with nothing after it in front of the committer.
        """
        class _Done:
            returncode = 0
            stdout     = "  \n"

        monkeypatch.setattr( subprocess, "run", lambda *a, **kw: _Done() )
        assert _live_merge_head( "/tmp" ) is None


# ═════════════════════════════════════════════════════════════════════════════
# THE RESPONSE ENVELOPE
# ═════════════════════════════════════════════════════════════════════════════

class TestTheResponseEnvelope:

    def test_it_is_a_pre_tool_use_deny( self ):
        envelope = build_merge_head_deny_response( "because" )
        assert envelope == {
            "hookSpecificOutput": {
                "hookEventName"            : "PreToolUse",
                "permissionDecision"       : "deny",
                "permissionDecisionReason" : "because",
            }
        }


# ═════════════════════════════════════════════════════════════════════════════
# REAL GIT — the part an injected reader structurally cannot test
# ═════════════════════════════════════════════════════════════════════════════

def _git( *args, cwd ):
    """Run git, raising on failure so a broken fixture cannot look like a finding."""
    return subprocess.run(
        [ "git", *args ], cwd=cwd, capture_output=True, text=True, check=True,
    ).stdout


@pytest.fixture
def repo_with_live_merge( tmp_path ):
    """
    A repo whose LINKED WORKTREE is sitting on a conflicted, resolved, STAGED
    merge — the exact state the founding incident was in.

    Ensures:
        - yields ( main_checkout, linked_worktree ) as str paths
        - the linked worktree has MERGE_HEAD live and its conflict staged
        - the main checkout has NO merge in flight, so it serves as the negative
          control in the same fixture
    """
    main = tmp_path / "main"
    main.mkdir()
    _git( "init", "-q", "-b", "trunk", ".", cwd=main )
    _git( "config", "user.email", "t@t", cwd=main )
    _git( "config", "user.name", "t", cwd=main )
    ( main / "f.txt" ).write_text( "base\n" )
    _git( "add", "f.txt", cwd=main )
    _git( "commit", "-qm", "base", cwd=main )

    _git( "checkout", "-q", "-b", "other", cwd=main )
    ( main / "f.txt" ).write_text( "other\n" )
    _git( "commit", "-qam", "other", cwd=main )
    _git( "checkout", "-q", "trunk", cwd=main )
    ( main / "f.txt" ).write_text( "mine\n" )
    _git( "commit", "-qam", "mine", cwd=main )

    linked = tmp_path / "linked"
    _git( "worktree", "add", "-q", "-b", "wt", str( linked ), "trunk", cwd=main )

    # Conflicts, then resolved and staged — the state BOTH porcelain forms hide.
    subprocess.run( [ "git", "merge", "other" ], cwd=linked, capture_output=True )
    ( linked / "f.txt" ).write_text( "resolved\n" )
    _git( "add", "f.txt", cwd=linked )

    yield str( main ), str( linked )


class TestAgainstRealGit:

    def test_the_check_finds_a_live_merge_in_a_linked_worktree( self, repo_with_live_merge ):
        _main, linked = repo_with_live_merge
        assert _live_merge_head( linked ), "no MERGE_HEAD found where one is live"

    def test_the_same_check_finds_nothing_in_a_tree_with_no_merge( self, repo_with_live_merge ):
        """
        THE POSITIVE CONTROL'S OTHER HALF. Without this, a `_live_merge_head` that
        returned a sha unconditionally would pass the test above.
        """
        main, _linked = repo_with_live_merge
        assert _live_merge_head( main ) is None

    def test_the_dot_git_path_form_reports_NO_MERGE_while_one_is_live( self, repo_with_live_merge ):
        """
        🔴 THE REGRESSION CONTROL FOR THE ONE MISTAKE THIS GUARD MUST NEVER MAKE.

        In a linked worktree `.git` is a FILE, not a directory, so `.git/MERGE_HEAD`
        does not exist — and the obvious check reports a clean tree while a merge is
        live. Wrong, and wrong in the SAFE-LOOKING direction, on the 92 trees where
        this fleet's work happens. Measured here rather than asserted, so nobody can
        "simplify" the guard onto the path form without this reddening.
        """
        _main, linked = repo_with_live_merge

        assert os.path.isfile( os.path.join( linked, ".git" ) ), \
            "a linked worktree's .git must be a FILE — this fixture is not testing what it claims"
        assert not os.path.exists( os.path.join( linked, ".git", "MERGE_HEAD" ) ), \
            "the path form found MERGE_HEAD — this test no longer demonstrates the trap"
        assert _live_merge_head( linked ), \
            "the plumbing check missed a merge the path form also missed — the guard is blind"

    def test_both_machine_readable_status_forms_hide_the_live_merge( self, repo_with_live_merge ):
        """
        Why this needs plumbing and not a status parse. Both porcelain forms show
        the staged file and say nothing about the merge; only the long form does.
        """
        _main, linked = repo_with_live_merge

        v1 = _git( "status", "--porcelain", cwd=linked )
        v2 = _git( "status", "--porcelain=v2", "--branch", cwd=linked )
        assert "merg" not in v1.lower(), f"porcelain v1 mentioned the merge after all: {v1!r}"
        assert "merg" not in v2.lower(), f"porcelain v2 mentioned the merge after all: {v2!r}"

        assert "still merging" in _git( "status", cwd=linked ).lower(), \
            "the LONG form stopped saying it — this test's premise has moved"

    def test_the_guard_end_to_end_refuses_a_commit_in_that_worktree( self, repo_with_live_merge ):
        """No injected reader anywhere: real command, real git, real refusal."""
        _main, linked = repo_with_live_merge
        assert merge_head_deny_reason(
            "Bash", { "command": "git commit -m 'my own work'" },
            enabled=True, cwd=linked,
        ) is not None

    def test_the_guard_end_to_end_allows_the_same_commit_in_a_clean_tree( self, repo_with_live_merge ):
        main, _linked = repo_with_live_merge
        assert merge_head_deny_reason(
            "Bash", { "command": "git commit -m 'my own work'" },
            enabled=True, cwd=main,
        ) is None

    def test_a_cd_into_a_merge_tree_is_refused_from_a_CLEAN_cwd( self, repo_with_live_merge ):
        """
        🔴 THE TEST THAT FAILS IF THE GUARD READS THE PROCESS CWD INSTEAD OF THE
        COMMAND'S TREE. No injected reader anywhere — real git, real merge, and the
        two directories deliberately DISAGREE.

        The hook stands in a tree with NO merge; the command cds into the one that
        has a live merge. A guard that consulted its own cwd sees a clean tree and
        allows. Only a guard that follows the command's `cd` can refuse here.

        This is the shape the fleet uses for nearly every commit — the Bash tool
        resets its working directory to the session root on every call — and it is
        the miss that shipped green at 100% coverage until it was measured against
        the real hook. Asked for by mr radio 🦉 on review.
        """
        main, linked = repo_with_live_merge
        assert merge_head_deny_reason(
            "Bash", { "command": f"cd {linked} && git commit -m 'my own work'" },
            enabled=True, cwd=main,
        ) is not None, "the guard read its own cwd, not the tree the commit lands in"

    def test_a_cd_into_a_CLEAN_tree_is_allowed_from_a_MERGING_cwd( self, repo_with_live_merge ):
        """
        THE INVERSE, and it is the half that makes the pair meaningful. The
        directories disagree the other way: the hook stands in the tree with the live
        merge, the command cds into the clean one.

        A guard that ignored the `cd` and read its own cwd would REFUSE here. So the
        two tests together cannot both pass unless the guard genuinely follows the
        command — neither alone establishes that.
        """
        main, linked = repo_with_live_merge
        assert merge_head_deny_reason(
            "Bash", { "command": f"cd {main} && git commit -m 'unrelated work'" },
            enabled=True, cwd=linked,
        ) is None, "the guard refused a commit in a tree that has no merge"

    def test_the_argv_is_the_plumbing_form_and_not_a_status_parse( self ):
        """
        Pins the command itself. `--porcelain` here would be the defect this whole
        module exists to refuse, and it would pass every behavioural test above on
        a tree where the merge happens to be unstaged.
        """
        assert MERGE_HEAD_ARGV == ( "git", "rev-parse", "-q", "--verify", "MERGE_HEAD" )


class TestTheHeredocChoice:

    # A line that BEGINS `git commit` — a newline opens a command slot, so this is
    # the shape that matches. commit_scope_guard's own false positive was exactly
    # this: a body line reading `git commit  -> the index`.
    LINE_START = "cat > msg.txt <<'EOF'\ngit commit  -> the index\nEOF"

    # Mid-line prose. `git` is not in command position after a colon and a space,
    # so this does NOT match, with or without a merge live.
    MID_LINE   = "cat > msg.txt <<'EOF'\nthe rule is: git commit takes the index\nEOF"

    def test_a_commit_quoted_in_a_heredoc_is_refused_mid_merge( self ):
        """
        PINNED AS A DECISION, NOT AN OVERSIGHT.

        `commit_scope_guard` strips heredoc bodies before matching, because text
        that is DATA read as COMMAND made it refuse the very commit carrying its
        own message. This guard does not strip, and the reason is the direction of
        harm: there a false deny blocks an honest commit at ANY time; here it can
        only fire while a merge is ALREADY LIVE, a state in which being stopped is
        nearly always right. Not stripping also means a heredoc that opens and
        never closes cannot hide a real commit behind it.

        If someone later decides the friction is not worth it, this test is where
        that decision gets made deliberately rather than discovered.
        """
        assert _guard( self.LINE_START ) is not None, (
            "the heredoc body stopped being matched - if that was deliberate, delete "
            "this test and amend the module docstring's residual list"
        )

    def test_mid_line_prose_in_a_heredoc_is_NOT_matched( self ):
        """
        THE BOUNDARY OF THE RESIDUAL, and it narrows it usefully. `git` after a
        colon and a space is not in command position, so ordinary prose mentioning
        a commit costs nothing even mid-merge. Only a line that BEGINS with it does.

        This test exists because the docstring first claimed the whole heredoc was
        refused. It is not, and the test above failed until the claim was cut back
        to what was measured.
        """
        assert _guard( self.MID_LINE ) is None

    def test_the_same_heredoc_is_allowed_when_no_merge_is_live( self ):
        """
        THE CONTROL that makes the trade acceptable: prose about `git commit` is
        refused ONLY during a live merge, never in the ordinary case.
        """
        assert _guard( self.LINE_START, merge_reader=_no_merge ) is None


class TestTheSquashProbe:
    """
    THE SECOND PROBE, ruled in by Rick 2026-08-31 ~21:05 EDT after he was shown that
    a MERGE_HEAD-only guard would not have caught its own founding incident.

    `git merge --squash` stages the whole merge and sets NO MERGE_HEAD, so the first
    probe is structurally blind to it — and the commit that follows carries ONE
    parent and loses the lane's ancestry, which is the shape the incident ended in.
    """

    def test_a_staged_squash_is_refused_even_with_no_MERGE_HEAD( self ):
        assert _guard(
            "git commit -m 'lands the lane'", merge_reader=_no_merge, squash_reader=lambda _c: True
        ) is not None

    def test_neither_probe_firing_allows_the_commit( self ):
        """THE CONTROL. Two probes give two ways to deny always; this rules both out."""
        assert _guard(
            "git commit -m x", merge_reader=_no_merge, squash_reader=_no_squash
        ) is None

    def test_the_two_states_are_worded_differently( self ):
        """
        A squash has no sha to name, and its harm is the LOST ANCESTRY rather than a
        peer's merge landing under your message. One message for both would make the
        committer look for a MERGE_HEAD that is not there.
        """
        merge  = _guard( "git commit -m x" )
        squash = _guard( "git commit -m x", merge_reader=_no_merge, squash_reader=lambda _c: True )
        assert merge != squash
        assert "MERGE_HEAD" in merge
        assert "SQUASH"     in squash.upper()

    def test_MERGE_HEAD_is_checked_first_when_both_are_somehow_present( self ):
        """
        A sha the committer can look up beats wording that has none. Asserting the
        ORDER, which no other test can see: both probes firing must give the merge
        message, not the squash one.
        """
        reason = _guard( "git commit -m x", squash_reader=lambda _c: True )
        assert "MERGE_HEAD" in reason

    def test_the_squash_probe_is_not_consulted_when_a_merge_is_live( self ):
        """Short-circuit, so the ordinary refusal costs one git read and not two."""
        calls = []
        _guard( "git commit -m x", squash_reader=lambda c: calls.append( c ) or True )
        assert calls == [], "the squash probe ran even though MERGE_HEAD had already answered"

    def test_the_squash_probe_asks_git_for_the_path_and_never_builds_one( self ):
        """
        `.git/SQUASH_MSG` would be wrong for the same reason `.git/MERGE_HEAD` is:
        in a linked worktree `.git` is a FILE. `--git-path` resolves through the
        worktree's own git dir.
        """
        assert SQUASH_MSG_ARGV == ( "git", "rev-parse", "--git-path", "SQUASH_MSG" )

    def test_the_probe_reads_False_outside_a_repo( self, tmp_path ):
        assert _squash_in_flight( str( tmp_path ) ) is False

    def test_the_probe_reads_False_for_a_missing_directory( self ):
        assert _squash_in_flight( "/nonexistent/path/for/this/test" ) is False

    def test_a_timeout_reads_as_no_squash( self, monkeypatch ):
        def slow( *a, **kw ):
            raise subprocess.TimeoutExpired( cmd="git", timeout=5 )

        monkeypatch.setattr( subprocess, "run", slow )
        assert _squash_in_flight( "/tmp" ) is False

    def test_an_empty_path_answer_reads_as_no_squash( self, monkeypatch ):
        class _Done:
            returncode = 0
            stdout     = "  \n"

        monkeypatch.setattr( subprocess, "run", lambda *a, **kw: _Done() )
        assert _squash_in_flight( "/tmp" ) is False

    def test_an_unstattable_path_reads_as_no_squash( self, monkeypatch ):
        """The isfile call is the last thing that can raise; it must not."""
        class _Done:
            returncode = 0
            stdout     = "/some/path\n"

        monkeypatch.setattr( subprocess, "run", lambda *a, **kw: _Done() )
        monkeypatch.setattr( os.path, "isfile", lambda _p: ( _ for _ in () ).throw( OSError( "nope" ) ) )
        assert _squash_in_flight( "/tmp" ) is False

    def test_a_relative_git_path_answer_is_resolved_against_the_cwd( self, monkeypatch, tmp_path ):
        """`--git-path` answers relative when cwd is inside the repo."""
        ( tmp_path / ".git" ).mkdir()
        ( tmp_path / ".git" / "SQUASH_MSG" ).write_text( "squash\n" )

        class _Done:
            returncode = 0
            stdout     = ".git/SQUASH_MSG\n"

        monkeypatch.setattr( subprocess, "run", lambda *a, **kw: _Done() )
        assert _squash_in_flight( str( tmp_path ) ) is True

    def test_a_relative_answer_with_no_cwd_resolves_against_the_process_cwd( self, monkeypatch ):
        class _Done:
            returncode = 0
            stdout     = "definitely/not/here/SQUASH_MSG\n"

        monkeypatch.setattr( subprocess, "run", lambda *a, **kw: _Done() )
        assert _squash_in_flight( None ) is False

    def test_a_non_zero_exit_reads_as_no_squash( self, monkeypatch ):
        class _Done:
            returncode = 128
            stdout     = ""

        monkeypatch.setattr( subprocess, "run", lambda *a, **kw: _Done() )
        assert _squash_in_flight( "/tmp" ) is False


class TestTheKnownGap:

    def test_git_merge_continue_is_not_covered( self ):
        """
        PINNED AS KNOWN, LIKE THE SQUASH GAP.

        `git merge --continue` concludes a live merge — measured: two parents,
        MERGE_HEAD cleared, same as a plain commit. This guard does not see it,
        because Rick ruled on the COMMIT. It differs in the one way that matters
        to the founding incident: it writes git's own default merge message, not
        the running seat's, so a peer's merge does not land under somebody else's
        words.

        Fails if the scope is ever widened, at which point delete it.
        """
        assert _guard( "git merge --continue" ) is None, \
            "the guard now covers `git merge --continue` — widen the docstring or delete this test"

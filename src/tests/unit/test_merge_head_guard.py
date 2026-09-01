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


def _guard( command, **kw ):
    """Drive the guard over one Bash command, live merge by default."""
    kw.setdefault( "enabled", True )
    kw.setdefault( "merge_reader", _recording_reader() )
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

    def test_a_plain_commit_is_judged_against_the_hook_cwd( self ):
        reader = _recording_reader()
        _guard( "git commit -m x", cwd="/tmp/seat", merge_reader=reader )
        assert reader.seen == [ "/tmp/seat" ]

    def test_dash_C_retargets_the_check_at_the_named_tree( self ):
        """
        `git -C <path> commit` runs in ANOTHER tree, so that tree's merge state is
        the one that decides. Asserting on the recorded directory, not on the
        verdict — a guard that ignored -C would still deny here.
        """
        reader = _recording_reader()
        _guard( "git -C /other/tree commit -m x", cwd="/tmp/seat", merge_reader=reader )
        assert reader.seen == [ "/other/tree" ]

    def test_a_relative_dash_C_resolves_against_the_hook_cwd( self ):
        reader = _recording_reader()
        _guard( "git -C sub commit -m x", cwd="/tmp/seat", merge_reader=reader )
        assert reader.seen == [ os.path.join( "/tmp/seat", "sub" ) ]

    def test_lowercase_dash_c_is_a_config_override_and_never_a_directory( self ):
        """`-c user.name=x` is not a path. Reading it as one would check nowhere."""
        reader = _recording_reader()
        _guard( "git -c user.name=nobody commit -m x", cwd="/tmp/seat", merge_reader=reader )
        assert reader.seen == [ "/tmp/seat" ]

    def test_target_directory_returns_the_cwd_when_there_is_no_pre_span( self ):
        assert _target_directory( None, "/tmp/seat" ) == "/tmp/seat"
        assert _target_directory( "", "/tmp/seat" )   == "/tmp/seat"

    def test_target_directory_returns_the_cwd_when_the_options_name_no_directory( self ):
        assert _target_directory( " --amend --no-verify", "/tmp/seat" ) == "/tmp/seat"

    def test_repeated_dash_C_composes_and_a_later_absolute_path_wins( self ):
        """Git applies each -C relative to the last; an absolute one starts over."""
        assert _target_directory( " -C a -C b", "/tmp/seat" ) == os.path.join( "/tmp/seat", "a", "b" )
        assert _target_directory( " -C a -C /abs", "/tmp/seat" ) == "/abs"

    def test_target_directory_falls_back_to_the_process_cwd( self ):
        assert _target_directory( " -C sub", None ) == os.path.join( os.getcwd(), "sub" )


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


class TestTheKnownGap:

    def test_a_squash_merge_is_invisible_to_this_guard( self, tmp_path ):
        """
        🔴 PINNED AS KNOWN AND ACCEPTED, NOT AS CORRECT.

        `git merge --squash` stages a merge and sets NO MERGE_HEAD, so this guard
        allows a commit that concludes it — and that is the shape which produces
        the ONE-PARENT commit the founding incident recorded. SQUASH_MSG is a
        viable second probe (git clears it on commit, so it cannot linger into a
        false deny), but widening past MERGE_HEAD is outside this row's ratified
        scope and is with the manager.

        This test exists so the gap cannot quietly become a surprise. If the scope
        is widened it will fail, and whoever widens it should delete it.
        """
        main = tmp_path / "sq"
        main.mkdir()
        _git( "init", "-q", "-b", "trunk", ".", cwd=main )
        _git( "config", "user.email", "t@t", cwd=main )
        _git( "config", "user.name", "t", cwd=main )
        ( main / "f.txt" ).write_text( "base\n" )
        _git( "add", "f.txt", cwd=main )
        _git( "commit", "-qm", "base", cwd=main )
        _git( "checkout", "-q", "-b", "other", cwd=main )
        ( main / "g.txt" ).write_text( "other\n" )
        _git( "add", "g.txt", cwd=main )
        _git( "commit", "-qm", "other", cwd=main )
        _git( "checkout", "-q", "trunk", cwd=main )

        subprocess.run( [ "git", "merge", "--squash", "other" ], cwd=main, capture_output=True )

        squash_msg = _git( "rev-parse", "--git-path", "SQUASH_MSG", cwd=main ).strip()
        assert os.path.exists( os.path.join( main, squash_msg ) ), \
            "no squash is in flight — this test is not measuring what it claims"

        assert _live_merge_head( str( main ) ) is None, \
            "MERGE_HEAD now sees a squash merge — the gap closed; delete this test"
        assert merge_head_deny_reason(
            "Bash", { "command": "git commit -m 'concludes a squash'" },
            enabled=True, cwd=str( main ),
        ) is None, "the guard now catches squash merges — the gap closed; delete this test"

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

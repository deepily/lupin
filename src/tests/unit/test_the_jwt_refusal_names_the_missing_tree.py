"""
THE CONTROL FOR ROW dde8b87a's THIRD MEMBER: when `import lupin_app.main` refuses inside
a worktree, the refusal must name the missing TREE, not just the missing VARIABLE.

WHY THIS MEMBER IS NOT PROVISIONED, AND WILL NOT BE. The repo-root `.env` is gitignored,
so it is present in the main checkout and absent from every worktree — the same shape as
`node_modules` and `src/scripts/cloud-run.env`, which ARE borrowed. It is excluded
because of what is IN it: JWT_SECRET_KEY and POSTGRES_PASSWORD. A venv is a build
artifact; a key is a secret, and Mr. Radio's 2026-09-01 ruling on `src/conf/keys/**`
governs this file for the same reason — a symlink puts a live credential inside a
throwaway tree that gets rm -rf'd, copied and shared.

⇒ So the remedy for THIS member is a message that tells the truth about why the variable
is absent. A reader who is told "JWT_SECRET_KEY must be set" goes and sets it, having
learned nothing; a reader told "you are in a worktree and this file cannot be there"
knows which of the two trees to stand in.

⚠️ THE NEGATIVE ARM IS THE LOAD-BEARING HALF. A hint that appended itself to every
refusal would satisfy the positive test and mislead every reader in the main checkout,
where the variable really IS just unset.
"""

import os
import subprocess
import sys

from cosa.rest.jwt_service import _missing_secret_message, _missing_tree_hint


def _fake_worktree( tmp_path, main_has_env=True, gitdir_marker=True ):
    """
    Build the two directories the hint reasons over: a "main checkout" holding a `.env`,
    and a "worktree" whose `.git` is a FILE naming the main checkout's gitdir.

    Ensures:
        - returns (main, worktree) as path strings
        - the worktree never has a `.env` of its own
        - `<main>/.env` exists iff main_has_env
        - `<worktree>/.git` is a gitdir FILE iff gitdir_marker, else a directory
    """
    main = tmp_path / "main"
    ( main / ".git" / "worktrees" / "seat" ).mkdir( parents=True )
    if main_has_env: ( main / ".env" ).write_text( "JWT_SECRET_KEY=x\n" )

    seat = tmp_path / "seat"
    seat.mkdir()
    if gitdir_marker:
        ( seat / ".git" ).write_text( f"gitdir: {main}/.git/worktrees/seat\n" )
    else:
        ( seat / ".git" ).mkdir()
    return str( main ), str( seat )


class TestTheRefusalNamesTheTree:

    def test_a_worktree_missing_env_is_told_it_is_a_missing_tree( self, tmp_path ):
        main, seat = _fake_worktree( tmp_path )
        hint = _missing_tree_hint( here=seat )

        assert "MISSING TREE, NOT A MISSING SETTING" in hint
        assert seat in hint, "the hint must name the tree the reader is standing in"
        assert main in hint, "the hint must name the tree that has the file"
        assert "POSTGRES_PASSWORD" in hint, "the reader must be told WHY it is not borrowed"

    def test_the_main_checkout_gets_no_hint( self, tmp_path ):
        """
        THE NEGATIVE CONTROL. In a checkout whose `.git` is a real directory the variable
        really is just unset, and a worktree explanation would send the reader hunting a
        tree that is not the problem. A hint that appended itself always would pass the
        test above and be worse than none.
        """
        _, seat = _fake_worktree( tmp_path, gitdir_marker=False )
        assert _missing_tree_hint( here=seat ) == ""

    def test_a_tree_that_has_its_own_env_gets_no_hint( self, tmp_path ):
        """The file is present; whatever went wrong, it was not this."""
        _, seat = _fake_worktree( tmp_path )
        with open( os.path.join( seat, ".env" ), "w" ) as f: f.write( "JWT_SECRET_KEY=y\n" )
        assert _missing_tree_hint( here=seat ) == ""

    def test_a_main_checkout_with_no_env_either_gets_no_hint( self, tmp_path ):
        """
        Nothing to point at. Claiming the main checkout has the file when it does not
        would be a confident answer to a question nobody asked.
        """
        _, seat = _fake_worktree( tmp_path, main_has_env=False )
        assert _missing_tree_hint( here=seat ) == ""

    def test_a_git_file_that_is_not_a_gitdir_pointer_gets_no_hint( self, tmp_path ):
        _, seat = _fake_worktree( tmp_path )
        with open( os.path.join( seat, ".git" ), "w" ) as f: f.write( "something else\n" )
        assert _missing_tree_hint( here=seat ) == ""

    def test_a_tree_with_no_git_entry_at_all_gets_no_hint( self, tmp_path ):
        bare = tmp_path / "bare"
        bare.mkdir()
        assert _missing_tree_hint( here=str( bare ) ) == ""

    def test_the_hint_can_never_turn_a_legible_refusal_into_a_traceback( self, tmp_path, monkeypatch ):
        """
        This runs during a module import that is ALREADY failing. A hint that raised
        would replace a clear refusal with an obscure one, which is strictly worse than
        no hint at all.
        """
        def _explode( *a, **k ): raise OSError( "disk gone" )

        monkeypatch.setattr( os.path, "exists", _explode )
        assert _missing_tree_hint( here=str( tmp_path ) ) == ""

    def test_the_default_root_is_this_files_own_tree_and_not_LUPIN_ROOT( self, monkeypatch ):
        """
        The import-time caller passes nothing, so the default must resolve from the code
        that is actually running. Resolving it from LUPIN_ROOT would describe whatever
        repo the runner's shell happened to be standing in — the wrong-tree family.
        """
        monkeypatch.setenv( "LUPIN_ROOT", "/nonexistent/elsewhere" )
        assert _missing_tree_hint() == _missing_tree_hint( here=None )


class TestTheHintActuallyReachesTheRefusal:
    """
    🔴 THE WIRING, WHICH THE TESTS ABOVE DO NOT COVER. Every one of them calls
    `_missing_tree_hint` directly, so all eight would stay green if the composition
    dropped the hint entirely and the reader got the old variable-only sentence back.
    A component can be complete, correct, fully covered and absent from the message
    anyone actually sees.
    """

    def test_the_refusal_carries_both_the_standing_advice_and_the_tree_hint( self, tmp_path ):
        _, seat  = _fake_worktree( tmp_path )
        message  = _missing_secret_message( here=seat )

        assert "JWT_SECRET_KEY environment variable must be set" in message
        assert "MISSING TREE, NOT A MISSING SETTING" in message
        assert seat in message

    def test_the_refusal_outside_a_worktree_is_the_standing_advice_alone( self, tmp_path ):
        """
        THE NEGATIVE CONTROL for the composition. A message that always carried the hint
        would pass the test above and lie to every reader in the main checkout.
        """
        _, seat = _fake_worktree( tmp_path, gitdir_marker=False )
        message = _missing_secret_message( here=seat )

        assert "JWT_SECRET_KEY environment variable must be set" in message
        assert "MISSING TREE" not in message


class TestTheRaiseItselfActuallyFires:
    """
    🔴 THE LAST LAYER, AND EVERY TEST ABOVE IS BLIND TO IT. They all call functions
    directly. The `raise` lives at MODULE SCOPE and fires only when JWT_SECRET_KEY is
    unset — and `src/cosa/tests/conftest.py:91` does `os.environ.setdefault(
    "JWT_SECRET_KEY", ... )` at COLLECTION time precisely so the tier can import the
    module at all. So under this suite the refusal NEVER EXECUTES, and a change that
    broke it would leave all ten tests above green.

    ⇒ The only way to watch it fire is a fresh interpreter with the variable removed and
    no conftest in the way. That is what this does: a real import, in a real subprocess,
    reading the real tree.
    """

    def _refusal_from_a_fresh_interpreter( self ):
        """Import the module with JWT_SECRET_KEY removed; return the process's stderr."""
        root = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )
        env  = { k: v for k, v in os.environ.items() if k != "JWT_SECRET_KEY" }
        env[ "LUPIN_ROOT" ]  = root
        env[ "PYTHONPATH" ]  = os.path.join( root, "src" )
        out = subprocess.run(
            [ sys.executable, "-c", "import cosa.rest.jwt_service" ],
            capture_output=True, text=True, env=env, cwd=root, timeout=120
        )
        return out

    def test_an_unset_secret_really_refuses_the_import( self ):
        """
        The refusal is the whole security property (row adce3547): there is no default
        signing secret, so a missing one must be a boot failure rather than tokens signed
        with a value anyone can read.
        """
        out = self._refusal_from_a_fresh_interpreter()
        assert out.returncode != 0, "the module imported cleanly with NO signing secret set"
        assert "JWT_SECRET_KEY environment variable must be set" in out.stderr

    def test_the_tree_hint_reaches_the_real_refusal_exactly_when_it_should( self ):
        """
        🔴 TWO PROVENANCES, WHICH IS WHAT MAKES THIS A TEST RATHER THAN A TAUTOLOGY. The
        left side is the stderr of a REAL failing import in a REAL subprocess; the right
        side is the predicate evaluated in THIS process. They are computed by different
        code paths over the same tree, so they can genuinely disagree.

        ⚠️ IT IS AN IFF, NOT AN ASSERTION THAT THE HINT IS PRESENT. This suite runs in a
        worktree on most seats and in the main checkout at the merge gate, and the
        correct answer differs between them — a test asserting the hint always appears
        would redden at the gate, and one asserting it never does would redden everywhere
        else. Both would be measuring which tree ran them.
        """
        out      = self._refusal_from_a_fresh_interpreter()
        expected = bool( _missing_tree_hint() )

        assert ( "MISSING TREE, NOT A MISSING SETTING" in out.stderr ) == expected, (
            f"the real refusal disagrees with the predicate for this tree "
            f"(expected hint: {expected})"
        )

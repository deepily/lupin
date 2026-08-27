"""
The four process-inspection helpers in `register_session.py` — row `e2099400` §3d, target 1.

WHY THESE FOUR. `register_session.py` was the largest single hole in `lupin_cli` when this was
written: 67 missing statements of the package's 252, measured at sha 6b7533eb on the unit tier
with an isolated coverage data file. Eighteen of the 67 sit in small helpers ABOVE `main()`,
and every one of them answers a question about the machine — is this PID alive, which tmux
window is it in, is the voice server registered. They are uncovered for the same reason: a
test that does not fake the machine gets whatever the machine happens to say.

🔴 AND FOR ONE OF THEM THAT IS NOT A FIGURE OF SPEECH — THE COVERAGE NUMBER MOVES WITH THE
DEVELOPER'S HOME DIRECTORY. `_check_cosa_voice_status()` opens the REAL `~/.claude/settings.json`
and the REAL `./.mcp.json` when the unit tier runs. Measured on this box, 2026-08-26: the
settings file exists but has no `mcpServers` key at all, and there is no local `.mcp.json` — so
line 667 ("registered (user scope)") and lines 671-674 (the local-scope branch) cannot execute
HERE, and are reported as untested code. Register cosa-voice at user scope — which this repo's
own CLAUDE.md instructs everybody to do — and those lines start being covered with no change to
the tree at all.

    A line that becomes covered when you configure your laptop is not being tested by anything.

That is the same family as the run whose coverage moved with the clock
(src/rnd/v0.2.0/2026.08.25-coverage-that-moves-with-the-clock.md): a measurement reading
something other than the tests. The remedy here is the same in spirit — take the environment
away from the function and hand it a known one. Every case below supplies its own settings
file, its own process table, its own tmux output.

Venue: :7999-eligible — in-process, no server, no network, no persistent-state mutation. Nothing
here touches the real ~/.claude, the real /proc, or a real tmux.
"""

import json
import os
import subprocess
import unittest

from unittest import mock

from lupin_cli.claude_code.hooks import register_session as rs


def _tmux_output( returncode=0, stdout="" ):
    """A stand-in for the CompletedProcess `tmux list-panes` hands back."""
    return subprocess.CompletedProcess( args=[ "tmux" ], returncode=returncode, stdout=stdout, stderr="" )


def _proc_stat( ppid, comm="bash" ):
    """
    A `/proc/<pid>/stat` line whose parent field is `ppid`.

    The comm field is deliberately allowed to contain a paren — the parser finds the LAST ")"
    for exactly this reason, and a stat line without one would not exercise that choice.
    """
    return f"4242 ({comm}) S {ppid} 4242 4242 0 -1 4194560 1234 0 0 0 1 2 3 4 20 0 1 0 100 0 0\n"


class FindTmuxSessionTest( unittest.TestCase ):
    """`_find_tmux_session` — which tmux window a Claude Code process is sitting in."""

    def test_a_direct_pane_match_names_the_session( self ):
        with mock.patch.object( rs.subprocess, "run",
                                return_value=_tmux_output( stdout="cc-author-john-1 900\ncc-manager-1 901\n" ) ):
            self.assertEqual( rs._find_tmux_session( 900 ), "cc-author-john-1" )

    def test_a_failing_tmux_gives_up_rather_than_reading_its_output( self ):
        """
        `tmux list-panes` outside a server prints its complaint and exits non-zero. The stdout
        here is deliberately WELL-FORMED: if the return code were ignored the parse would
        succeed and hand back a session name from a failed command.
        """
        with mock.patch.object( rs.subprocess, "run",
                                return_value=_tmux_output( returncode=1, stdout="ghost 900\n" ) ):
            self.assertIsNone( rs._find_tmux_session( 900 ) )

    def test_a_pane_line_whose_pid_is_not_a_number_is_skipped_not_fatal( self ):
        """
        One malformed line must not cost the lines around it. The good entry sits AFTER the bad
        one, so a parser that gave up on the first failure would return None here.
        """
        stdout = "broken not-a-pid\ncc-author-john-1 900\n"
        with mock.patch.object( rs.subprocess, "run", return_value=_tmux_output( stdout=stdout ) ):
            self.assertEqual( rs._find_tmux_session( 900 ), "cc-author-john-1" )

    def test_a_shell_wrapped_process_is_found_through_its_parent( self ):
        """
        The launcher runs a pane's bash, and bash runs claude — so the pane PID is the SHELL's,
        not Claude Code's. Without this walk-up, every tmux-launched session reports no window.
        """
        with mock.patch.object( rs.subprocess, "run", return_value=_tmux_output( stdout="cc-author-john-1 800\n" ) ), \
             mock.patch( "builtins.open", mock.mock_open( read_data=_proc_stat( ppid=800 ) ) ):
            self.assertEqual( rs._find_tmux_session( 900 ), "cc-author-john-1" )

    def test_a_parent_that_is_also_not_a_pane_gives_up_quietly( self ):
        with mock.patch.object( rs.subprocess, "run", return_value=_tmux_output( stdout="cc-author-john-1 800\n" ) ), \
             mock.patch( "builtins.open", mock.mock_open( read_data=_proc_stat( ppid=777 ) ) ):
            self.assertIsNone( rs._find_tmux_session( 900 ) )

    def test_an_unreadable_proc_entry_is_not_an_error( self ):
        """The process can exit between the tmux call and the stat read. That is normal, not a fault."""
        with mock.patch.object( rs.subprocess, "run", return_value=_tmux_output( stdout="cc-author-john-1 800\n" ) ), \
             mock.patch( "builtins.open", side_effect=FileNotFoundError ):
            self.assertIsNone( rs._find_tmux_session( 900 ) )

    def test_no_tmux_installed_is_answered_with_none_not_an_exception( self ):
        """
        This runs inside a SessionStart hook. A raise here does not degrade the tmux lookup —
        it takes session registration down.
        """
        with mock.patch.object( rs.subprocess, "run", side_effect=FileNotFoundError ):
            self.assertIsNone( rs._find_tmux_session( 900 ) )

    def test_a_hanging_tmux_is_answered_with_none_too( self ):
        with mock.patch.object( rs.subprocess, "run",
                                side_effect=subprocess.TimeoutExpired( cmd="tmux", timeout=2 ) ):
            self.assertIsNone( rs._find_tmux_session( 900 ) )


class ResolveCcPidTest( unittest.TestCase ):
    """
    `_resolve_cc_pid` — walks from the hook's parent (a bash wrapper) up to Claude Code itself.

    Getting this wrong does not raise; it returns the WRONG process, and every downstream
    liveness check then asks about a shell that exits the moment the hook does.
    """

    def test_the_grandparent_pid_is_what_comes_back( self ):
        with mock.patch( "builtins.open", mock.mock_open( read_data=_proc_stat( ppid=1234 ) ) ):
            self.assertEqual( rs._resolve_cc_pid( 999 ), 1234 )

    def test_a_comm_field_containing_a_close_paren_does_not_shift_the_parse( self ):
        """
        The comm field is the process name, it is NOT escaped, and a process may set it to
        anything — including a ")". The parser looks for the LAST ")" for exactly that reason.

        ⚠️ THE COMM STRING HERE IS CHOSEN, NOT DECORATIVE, and the first draft of this test
        got it wrong. `(bash (login))` reads the same either way: the extra ")" is adjacent to
        the real one, so first-paren and last-paren land two characters apart and the field
        split comes out identical — the test passed against a parser using `.index()`, which
        means it guarded nothing. `bash) S 777` is the shape that separates them: with the
        wrong paren the parse reads 777, a number that looks exactly like a pid and is not one.
        """
        stat = "4242 (bash) S 777) S 1234 4242 4242 0 -1 4194560 1234 0 0 0 1 2 3 4 20 0 1 0 100 0 0\n"
        with mock.patch( "builtins.open", mock.mock_open( read_data=stat ) ):
            self.assertEqual( rs._resolve_cc_pid( 999 ), 1234 )

    def test_an_unreadable_stat_file_falls_back_to_the_caller_s_own_parent( self ):
        """
        The documented safe fallback. Returning the hook's parent is wrong-but-harmless;
        raising would fail session registration outright.
        """
        with mock.patch( "builtins.open", side_effect=FileNotFoundError ):
            self.assertEqual( rs._resolve_cc_pid( 999 ), 999 )

    def test_a_truncated_stat_line_falls_back_the_same_way( self ):
        with mock.patch( "builtins.open", mock.mock_open( read_data="4242 (bash)\n" ) ):
            self.assertEqual( rs._resolve_cc_pid( 999 ), 999 )


class IsLiveCcProcessTest( unittest.TestCase ):
    """
    `_is_live_cc_process` — the liveness question the stale-lockfile purge asks before deleting.

    ⚠️ ITS THREE ANSWERS ARE NOT SYMMETRIC, AND THE ASYMMETRY IS THE POINT. "Alive" and
    "exists but I may not signal it" BOTH mean do-not-purge; only "no such process" and "that
    is not a pid" mean purge. Treating the permission case as dead would delete a live seat's
    lockfile, which is the failure this function is shaped to avoid.
    """

    def test_a_live_pid_is_alive( self ):
        with mock.patch.object( rs.os, "kill", return_value=None ) as killed:
            self.assertIs( rs._is_live_cc_process( "4242" ), True )
        killed.assert_called_once_with( 4242, 0 )

    def test_a_dead_pid_is_not( self ):
        with mock.patch.object( rs.os, "kill", side_effect=ProcessLookupError ):
            self.assertIs( rs._is_live_cc_process( "4242" ), False )

    def test_something_that_is_not_a_pid_is_not_alive_either( self ):
        with mock.patch.object( rs.os, "kill", return_value=None ):
            self.assertIs( rs._is_live_cc_process( "cc-stable" ), False )

    def test_a_process_we_may_not_signal_counts_as_ALIVE( self ):
        """
        Another user's process, or one we lost the right to signal. It exists. Purging its
        lockfile because we could not prove it exists is the error worth guarding.
        """
        with mock.patch.object( rs.os, "kill", side_effect=PermissionError ):
            self.assertIs( rs._is_live_cc_process( "4242" ), True )


class CheckCosaVoiceStatusTest( unittest.TestCase ):
    """
    `_check_cosa_voice_status` — the banner a session prints about its own prerequisites.

    EVERY CASE HERE SUPPLIES ITS OWN FILES. See this module's header: without that, three of
    these branches are decided by whether the person running the suite happens to have
    registered the voice server on their laptop.
    """

    def _run( self, *, settings=None, local_mcp=None, detect_raises=False ):
        """Run the status check against a fabricated home directory and cwd."""
        present = { }
        if settings  is not None: present[ os.path.expanduser( "~/.claude/settings.json" ) ] = settings
        if local_mcp is not None: present[ os.path.join( os.getcwd(), ".mcp.json" ) ]        = local_mcp

        def fake_exists( path ):
            return path in present

        def fake_open( path, *args, **kwargs ):
            if path not in present: raise FileNotFoundError( path )
            return mock.mock_open( read_data=json.dumps( present[ path ] ) )()

        detect = mock.Mock( side_effect=RuntimeError( "no repo here" ) ) if detect_raises \
                 else mock.Mock( return_value="lupin" )

        with mock.patch.object( rs.os.path, "exists", fake_exists ), \
             mock.patch( "builtins.open", fake_open ), \
             mock.patch.object( rs, "detect_project", detect ), \
             mock.patch.object( rs, "is_known_project", mock.Mock( return_value=True ) ):
            return rs._check_cosa_voice_status()

    def test_a_user_scope_registration_is_reported_as_such( self ):
        """
        THE BRANCH THAT MOVES WITH THE LAPTOP. This box has no `mcpServers` key at all, so
        before this test the line was untested code — and would have quietly become "tested"
        the day somebody followed the repo's own setup instructions.
        """
        block = self._run( settings={ "mcpServers": { "cosa-voice": { } } } )
        self.assertIn( "registered (user scope)", block )

    def test_a_local_registration_is_reported_AND_nudged_toward_the_global_one( self ):
        """
        A project-local `.mcp.json` works but does not follow the session to another repo. The
        wording carries that advice, so assert the advice and not merely the word "registered".
        """
        block = self._run( settings={ "mcpServers": { } }, local_mcp={ "mcpServers": { "cosa-voice": { } } } )
        self.assertIn( "registered (local scope", block )
        self.assertIn( "migrating to global", block )

    def test_a_local_file_that_does_not_mention_the_server_leaves_the_status_alone( self ):
        """The local file is read whenever it exists; only a MATCH may change the verdict."""
        block = self._run( settings={ "mcpServers": { "cosa-voice": { } } },
                           local_mcp={ "mcpServers": { "something-else": { } } } )
        self.assertIn( "registered (user scope)", block )

    def test_no_registration_anywhere_says_not_found( self ):
        block = self._run( settings={ "mcpServers": { } } )
        self.assertIn( "not found", block )

    def test_unreadable_settings_are_reported_as_a_failed_check_not_as_absence( self ):
        """
        "check failed" and "not found" are different facts and the banner keeps them apart —
        one says look at your file, the other says register the server.
        """
        with mock.patch.object( rs.os.path, "exists", lambda p: True ), \
             mock.patch( "builtins.open", side_effect=PermissionError ), \
             mock.patch.object( rs, "detect_project", mock.Mock( return_value="lupin" ) ), \
             mock.patch.object( rs, "is_known_project", mock.Mock( return_value=True ) ):
            block = rs._check_cosa_voice_status()
        self.assertIn( "check failed", block )

    def test_a_project_that_cannot_be_detected_says_so_and_the_banner_still_renders( self ):
        """
        Project detection walks up for a `.git` ancestor and can fail outright. The banner is
        printed at session start, so a raise here would be a hook crash rather than a missing line.
        """
        block = self._run( settings={ "mcpServers": { } }, detect_raises=True )
        self.assertIn( "detection failed", block )

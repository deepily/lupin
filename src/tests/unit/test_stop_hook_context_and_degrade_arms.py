"""
The Stop hook's context reader and three of its degrade-safe arms. Row `e2099400` §3d, target 4.

WHY THESE. `stop.py` had 28 missing statements, measured at sha 6b7533eb on the unit tier with
an isolated coverage data file. Mapped back to their functions they are almost all the same
kind of line: the arm that runs when something the hook merely CONSULTS is unavailable. The
Stop hook decides whether a session may finish its turn; a raise anywhere in it does not
degrade a status line, it breaks the turn. So the arms that catch are the load-bearing part,
and they were the untested part.

🔴 AND ONE OF THEM IS NOT AN ERROR ARM AT ALL — IT IS THE HAPPY PATH NOBODY WAS RUNNING.
`_get_session_context` reads the git branch only `if cwd`, and every existing test called it
without one, so the whole branch lookup was dead in the suite. The two lines it feeds — the
`**Session**` and `**Branch**` rows of the "Anything else?" card — were dead for the same
reason. That card is what the user reads when a session asks whether it may stop; the lines
saying WHICH session and WHICH branch is asking had no test behind them.

Venue: :7999-eligible — in-process, no server, no network, no persistent-state mutation. The
git call is stubbed; nothing here shells out.
"""

import unittest

from unittest import mock

from lupin_cli.claude_code.hooks import stop


# The models validate this shape, and a stand-in that does not match it fails INSIDE the
# function under test — where a broad `except` swallows it and the test sees only a silent
# empty result. Cost me a debugging round; recorded so the next person types a real one.
VALID_SENDER_ID = "claude.code@lupin.deepily.ai#47a835e8"


class GetSessionContextTest( unittest.TestCase ):
    """
    `_get_session_context` — the topic and branch shown on the "Anything else?" card.

    Two independent lookups with independent guards. Neither is allowed to fail the hook, and
    neither is allowed to take the other down with it — which is the property worth pinning,
    because they are written as two separate try blocks precisely so one can fail alone.
    """

    def _run( self, cwd, *, meta=None, meta_raises=None, branch=None, branch_raises=None ):
        bridge = mock.Mock( side_effect=meta_raises, return_value=( meta or { } ) )
        check  = mock.Mock( side_effect=branch_raises, return_value=( branch or "" ) )
        with mock.patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_session_metadata", bridge ), \
             mock.patch( "subprocess.check_output", check ):
            return stop._get_session_context( cwd ), check

    def test_both_lookups_succeeding_gives_both_answers( self ):
        ( topic, branch ), check = self._run(
            "/repo", meta={ "session_topic": "Coverage work" }, branch="wip-v0.2.0\n" )

        self.assertEqual( topic,  "Coverage work" )
        self.assertEqual( branch, "wip-v0.2.0" )
        self.assertEqual( check.call_args.args[ 0 ], [ "git", "rev-parse", "--abbrev-ref", "HEAD" ] )
        self.assertEqual( check.call_args.kwargs[ "cwd" ], "/repo" )

    def test_the_branch_name_is_stripped( self ):
        """`git rev-parse` ends its output with a newline; an unstripped name renders as a break."""
        ( _topic, branch ), _ = self._run( "/repo", branch="  wip-v0.2.0  \n" )
        self.assertEqual( branch, "wip-v0.2.0" )

    def test_no_cwd_means_no_git_call_at_all( self ):
        """
        There is nothing to run `git` IN. Calling it anyway would inherit the hook process's
        own working directory and report a branch belonging to some other repository.
        """
        ( _topic, branch ), check = self._run( None, meta={ "session_topic": "t" } )

        self.assertIsNone( branch )
        check.assert_not_called()

    def test_an_unreadable_bridge_costs_the_topic_and_nothing_else( self ):
        ( topic, branch ), _ = self._run(
            "/repo", meta_raises=RuntimeError( "bridge is gone" ), branch="wip-v0.2.0" )

        self.assertIsNone( topic )
        self.assertEqual( branch, "wip-v0.2.0", "a failed topic lookup must not cost the branch" )

    def test_a_failing_git_costs_the_branch_and_nothing_else( self ):
        """A cwd outside any repository, a git that is not installed, a call that times out."""
        ( topic, branch ), _ = self._run(
            "/not/a/repo", meta={ "session_topic": "Coverage work" },
            branch_raises=OSError( "not a git repository" ) )

        self.assertEqual( topic, "Coverage work" )
        self.assertIsNone( branch )

    def test_both_failing_is_still_a_clean_pair_of_nones( self ):
        """The hook must get a two-tuple back no matter what. It unpacks the result unguarded."""
        ( topic, branch ), _ = self._run(
            "/repo", meta_raises=RuntimeError( "gone" ), branch_raises=OSError( "gone" ) )

        self.assertIsNone( topic )
        self.assertIsNone( branch )

    def test_a_bridge_with_no_topic_yields_no_topic( self ):
        ( topic, _branch ), _ = self._run( "/repo", meta={ } )
        self.assertIsNone( topic )


class AnythingElseCardContextTest( unittest.TestCase ):
    """
    The `**Session**` and `**Branch**` rows of the card the user actually reads.

    This is the notification that asks whether a finished session may stop. With several
    sessions running, those two rows are the ONLY thing distinguishing one card from another —
    and both lines were untested, for the same reason as the lookup that feeds them.
    """

    def _card( self, topic, branch ):
        """Drive `_ask_anything_else` far enough to capture the request it builds."""
        captured = { }

        def capture( request ):
            captured[ "request" ] = request
            raise RuntimeError( "stop here — the card is built, the transport is not the subject" )

        with mock.patch.object( stop, "_get_session_context", return_value=( topic, branch ) ), \
             mock.patch.object( stop, "_summarize_task", return_value="the coverage work" ), \
             mock.patch.object( stop, "build_sender_id_for_cc", return_value=VALID_SENDER_ID ), \
             mock.patch.object( stop, "notify_user_sync", side_effect=capture ), \
             mock.patch.object( stop, "log_to_stream" ):
            stop._ask_anything_else( "sess-1", "last message", cwd="/repo" )

        return captured[ "request" ].abstract

    def test_both_rows_appear_when_both_are_known( self ):
        abstract = self._card( "Coverage work", "wip-v0.2.0" )

        self.assertIn( "**Session**: Coverage work", abstract )
        self.assertIn( "**Branch**: `wip-v0.2.0`", abstract )

    def test_a_known_topic_alone_still_gets_its_row( self ):
        abstract = self._card( "Coverage work", None )

        self.assertIn( "**Session**: Coverage work", abstract )
        self.assertNotIn( "**Branch**", abstract )

    def test_a_known_branch_alone_still_gets_its_row( self ):
        abstract = self._card( None, "wip-v0.2.0" )

        self.assertIn( "**Branch**: `wip-v0.2.0`", abstract )
        self.assertNotIn( "**Session**", abstract )

    def test_neither_known_leaves_the_card_without_an_abstract( self ):
        """
        An empty string would render as a blank block on the card. None is the absence, and
        the code says so explicitly — worth pinning so a later refactor does not "simplify" it.
        """
        self.assertIsNone( self._card( None, None ) )


class SelectGoalRoleTest( unittest.TestCase ):
    """
    `_select_goal_role` — which goal line the self-poke addresses this seat with.

    ⚠️ ITS LAST RESORT IS THE INTERESTING ONE. The roster lookup imports a governance helper
    and asks whether this persona is a declared manager. If that import or lookup fails, the
    answer is "agnostic" — NOT "manager" and NOT "worker". Guessing either way would address a
    session with a role it does not have, and the goal line is what the seat is told to do.
    """

    def test_a_stamped_manager_role_is_taken_at_face_value( self ):
        self.assertEqual( stop._select_goal_role( "sess-1", "manager" ), "manager" )

    def test_any_other_stamped_role_is_a_worker( self ):
        for role in ( "author", "reviewer", "tester", "worker" ):
            with self.subTest( role=role ):
                self.assertEqual( stop._select_goal_role( "sess-1", role ), "worker" )

    def test_the_stamped_role_is_read_case_and_space_insensitively( self ):
        self.assertEqual( stop._select_goal_role( "sess-1", "  MANAGER  " ), "manager" )

    def test_no_stamp_falls_through_to_the_declared_roster( self ):
        with mock.patch( "lupin_cli.claude_code.hooks.lib.subagent_governance._is_manager_persona",
                         return_value=True ):
            self.assertEqual( stop._select_goal_role( "sess-1", None ), "manager" )

    def test_no_stamp_and_not_on_the_roster_is_agnostic( self ):
        with mock.patch( "lupin_cli.claude_code.hooks.lib.subagent_governance._is_manager_persona",
                         return_value=False ):
            self.assertEqual( stop._select_goal_role( "sess-1", None ), "agnostic" )

    def test_a_roster_lookup_that_blows_up_is_agnostic_rather_than_a_guess( self ):
        with mock.patch( "lupin_cli.claude_code.hooks.lib.subagent_governance._is_manager_persona",
                         side_effect=RuntimeError( "roster unreadable" ) ):
            self.assertEqual( stop._select_goal_role( "sess-1", None ), "agnostic" )


class BoardSweepLineTest( unittest.TestCase ):
    """
    `_board_sweep_line` — the sweep-gate sentence, or nothing.

    ⚠️ SILENCE MEANS EXACTLY ONE THING HERE AND THE COMMENT IN THE SOURCE IS EMPHATIC ABOUT IT:
    "" means WE COULD NOT IDENTIFY THE SEAT, never "the ledger looked fine". A ledger that
    cannot be READ is reported loudly by `sweep_progress_line` itself. This test pins the
    boundary, because collapsing the two would turn a gate that failed into a gate that passed.
    """

    def test_a_resolved_seat_gets_its_sweep_sentence( self ):
        with mock.patch.object( stop, "get_voice_persona", return_value={ "name": "john" } ), \
             mock.patch.object( stop, "sweep_progress_line", return_value="3 of 9 swept" ) as line:
            self.assertEqual( stop._board_sweep_line( "sess-1", live_owed=4 ), "3 of 9 swept" )
        self.assertEqual( line.call_args.args[ 0 ], "john" )
        self.assertEqual( line.call_args.kwargs[ "live_owed" ], 4 )

    def test_no_persona_at_all_means_no_seat_and_therefore_no_line( self ):
        with mock.patch.object( stop, "get_voice_persona", return_value=None ):
            self.assertEqual( stop._board_sweep_line( "sess-1", live_owed=0 ), "" )

    def test_a_persona_without_a_name_means_no_seat_either( self ):
        with mock.patch.object( stop, "get_voice_persona", return_value={ } ):
            self.assertEqual( stop._board_sweep_line( "sess-1", live_owed=0 ), "" )

    def test_a_bridge_read_that_blows_up_is_silence_not_a_broken_poke( self ):
        """
        The degrade-safe arm. A broken bridge read must cost this one line and let the poke go
        out — the alternative is a Stop hook that raises, which costs the whole turn.
        """
        with mock.patch.object( stop, "get_voice_persona", side_effect=RuntimeError( "bridge gone" ) ):
            self.assertEqual( stop._board_sweep_line( "sess-1", live_owed=0 ), "" )


class AnnounceIdleAbstractTest( unittest.TestCase ):
    """
    `_announce_idle` — the four things a quiet Stop can actually mean.

    THREE OF THEM ARE NOT "IDLE". Muted-and-unknown, unknown, and owed-but-not-poked all end a
    turn without a poke, and only the fourth means nothing is outstanding. The abstract is where
    that distinction is written down, so an operator reading a quiet session can tell "nothing
    to do" from "we could not find out".
    """

    def _abstract( self, **kwargs ):
        captured = { }
        with mock.patch.object( stop, "notify_user_async",
                                side_effect=lambda req: captured.__setitem__( "req", req ) ), \
             mock.patch.object( stop, "build_sender_id_for_cc", return_value=VALID_SENDER_ID ), \
             mock.patch.object( stop, "_idle_sentence", return_value="John is idle." ), \
             mock.patch.object( stop, "log_to_stream" ):
            stop._announce_idle( "sess-1", "john", **kwargs )
        return captured[ "req" ].abstract

    def test_muted_and_unknown_says_muting_is_not_an_all_clear( self ):
        abstract = self._abstract( owed_unknown=True, muted=True )

        self.assertIn( "MUTED", abstract )
        self.assertIn( "Muting buys silence, not an all-clear.", abstract )

    def test_unknown_alone_blames_the_store_and_asks_for_a_manual_check( self ):
        abstract = self._abstract( owed_unknown=True )

        self.assertIn( "task store unreachable", abstract )
        self.assertIn( "NOT idle", abstract )

    def test_owed_with_a_count_names_the_count( self ):
        """The line an operator reads to decide whether a quiet session needs chasing."""
        abstract = self._abstract( owed=True, total_owed=3 )

        self.assertIn( "3 owed referent(s)", abstract )
        self.assertIn( "idle but NOT done", abstract )

    def test_owed_with_no_count_says_so_rather_than_reporting_zero_owed( self ):
        """
        A referent-less signal is still work owed. Rendering it as "0 owed referent(s)" would
        read as nothing outstanding — the opposite of what the flag means.
        """
        abstract = self._abstract( owed=True, total_owed=0 )

        self.assertIn( "referent-less signal", abstract )
        self.assertNotIn( "0 owed referent(s)", abstract )

    def test_genuinely_idle_is_the_only_one_that_says_nothing_owed( self ):
        self.assertEqual( self._abstract(), "Heartbeat: idle — nothing owed." )

    def test_a_transport_failure_is_logged_and_never_raised( self ):
        """
        This runs at the end of every turn. A raise here turns a status announcement into a
        failed Stop, which is a strictly worse outcome than a missing announcement.
        """
        with mock.patch.object( stop, "notify_user_async", side_effect=RuntimeError( "server down" ) ), \
             mock.patch.object( stop, "build_sender_id_for_cc", return_value=VALID_SENDER_ID ), \
             mock.patch.object( stop, "_idle_sentence", return_value="John is idle." ), \
             mock.patch.object( stop, "log_to_stream" ) as logged:
            stop._announce_idle( "sess-1", "john" )

        phases = [ call.kwargs[ "extra" ][ "phase" ] for call in logged.call_args_list
                   if "extra" in call.kwargs ]
        self.assertIn( "idle_announce_error", phases )

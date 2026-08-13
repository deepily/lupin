"""
The DM tutor ON THE SEND PATH — Rick, 2026-08-13: "implement it fully and make
sure it's actually in use."

WHAT THIS SUITE EXISTS TO CATCH
-------------------------------
The tutor was built on 2026-08-11 and shipped NOTHING for two days, because
nothing called it. `rewrite_dm()` existed, was fail-closed, was unit-tested, and
was dead code — the send path never referenced it. Every test that agent had
passed while the fleet's DMs went out untouched.

That is the failure mode this file is aimed at: not "does the tutor work" (the
agent suite covers that) but "does a DM going through execute_dm_send come out
the other side distilled, and does the corpus row say so honestly". A suite that
only exercised `_apply_dm_tutor` in isolation would have been just as green
against the dead-code state as against this one, so the integration tests below
assert on what was PUSHED to the recipient, not on what a helper returned.

Row: 8f5813cf
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import cosa.utils.util as cu


# The three-claim house style plus a trailing path — what a compliant DM looks like.
_COMPLIANT = (
    "The tutor ships fleet-wide today.\n"
    "It fires above the ruled trigger.\n"
    "The corpus moved out of the repo.\n"
    "src/cosa/rest/routers/dm.py"
)

# Six claims — comfortably over any trigger this suite sets.
_VERBOSE = (
    "I spent the morning tracing the leak. "
    "It sits in the queue module. "
    "The line shipped last Tuesday. "
    "I am fairly confident about the diagnosis. "
    "Have a look when you get a moment. "
    "Tell me whether you read it the same way."
)


def _cfg( **overrides ):
    """A tutor config dict with explicit values — never read from the live ini."""
    base = { "enabled": True, "trigger_claims": 4, "gate_enabled": False, "gate_max_claims": 4 }
    base.update( overrides )
    return base


class TestFixtureControl( unittest.TestCase ):
    """
    CONTROL — the fixtures must sit on the sides of the trigger this suite claims.

    Without this, a change to the claim counter could quietly move `_VERBOSE` under
    the trigger and every "the tutor fired" test below would pass while asserting
    against a tutor that never ran.
    """

    def test_the_fixtures_straddle_the_trigger( self ):
        from cosa.rest.routers.dm import _count_claims
        self.assertLessEqual( _count_claims( _COMPLIANT ), 4, "compliant fixture is over the trigger" )
        self.assertGreater( _count_claims( _VERBOSE ), 4, "verbose fixture is not over the trigger" )


class TestApplyDmTutor( unittest.TestCase ):
    """The decision layer: when the tutor runs, when it does not, what it records."""

    def setUp( self ):
        from cosa.rest.routers.dm import _apply_dm_tutor
        self.apply = _apply_dm_tutor

    def test_disabled_delivers_the_original_and_never_calls_the_model( self ):
        called = []
        text, meta = self.apply( _VERBOSE, config=_cfg( enabled=False ),
                                 rewrite_fn=lambda b: called.append( b ) or "short." )
        self.assertEqual( text, _VERBOSE )
        self.assertEqual( meta[ "tutor_outcome" ], "disabled" )
        self.assertFalse( meta[ "tutor_fired" ] )
        self.assertEqual( called, [], "the model was called while the tutor was disabled" )

    def test_under_the_trigger_delivers_the_original_and_never_calls_the_model( self ):
        called = []
        text, meta = self.apply( _COMPLIANT, config=_cfg(),
                                 rewrite_fn=lambda b: called.append( b ) or "short." )
        self.assertEqual( text, _COMPLIANT )
        self.assertEqual( meta[ "tutor_outcome" ], "under_trigger" )
        self.assertFalse( meta[ "tutor_fired" ] )
        self.assertEqual( called, [], "a compliant DM was sent to the model" )

    def test_over_the_trigger_delivers_the_rewrite( self ):
        # Not an equality check: a delivered rewrite also carries the recipient notice
        # (see TestTheRecipientIsTold). What matters here is that the REWRITE is what
        # goes out and the sender's original does not.
        text, meta = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: "Verdict.\nOne.\nTwo." )
        self.assertIn( "Verdict.\nOne.\nTwo.", text )
        self.assertNotIn( "I spent the morning tracing the leak", text )
        self.assertEqual( meta[ "tutor_outcome" ], "rewritten" )
        self.assertTrue( meta[ "tutor_fired" ] )

    def test_the_trigger_is_strictly_greater_than( self ):
        """
        A message sitting EXACTLY on the trigger must not fire. That property is what
        lets the compliant house style coexist with the trigger instead of being
        rewritten forever — the trap the canned P.S. sprang once already.
        """
        from cosa.rest.routers.dm import _count_claims
        exactly_four = "One claim. Two claims. Three claims. Four claims."
        self.assertEqual( _count_claims( exactly_four ), 4 )

        _, meta = self.apply( exactly_four, config=_cfg( trigger_claims=4 ), rewrite_fn=lambda b: "x." )
        self.assertEqual( meta[ "tutor_outcome" ], "under_trigger" )

        _, meta = self.apply( exactly_four, config=_cfg( trigger_claims=3 ), rewrite_fn=lambda b: "x." )
        self.assertEqual( meta[ "tutor_outcome" ], "rewritten" )

    def test_a_model_failure_delivers_the_original( self ):
        """FAIL-CLOSED. rewrite_dm returns None on every internal failure."""
        text, meta = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: None )
        self.assertEqual( text, _VERBOSE )
        self.assertEqual( meta[ "tutor_outcome" ], "model_failed" )
        self.assertTrue( meta[ "tutor_fired" ], "the attempt must still be recorded as fired" )

    def test_a_blank_rewrite_is_a_failure_not_a_delivery( self ):
        """An empty string is not a distillation — delivering it would silently erase
        the sender's message, the worst outcome available to this code."""
        text, meta = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: "   \n  " )
        self.assertEqual( text, _VERBOSE )
        self.assertEqual( meta[ "tutor_outcome" ], "model_failed" )

    def test_a_raising_model_delivers_the_original_and_records_the_reason( self ):
        text, meta = self.apply( _VERBOSE, config=_cfg(),
                                 rewrite_fn=MagicMock( side_effect=RuntimeError( "vllm down" ) ) )
        self.assertEqual( text, _VERBOSE )
        self.assertEqual( meta[ "tutor_outcome" ], "error" )
        self.assertIn( "vllm down", meta[ "tutor_error" ] )

    def test_the_gate_when_ON_discards_an_over_long_rewrite( self ):
        long_rewrite = "One. Two. Three. Four. Five. Six."
        text, meta = self.apply( _VERBOSE, config=_cfg( gate_enabled=True, gate_max_claims=4 ),
                                 rewrite_fn=lambda b: long_rewrite )
        self.assertEqual( text, _VERBOSE, "the gate must fall back to the ORIGINAL, not the rewrite" )
        self.assertEqual( meta[ "tutor_outcome" ], "gate_rejected" )

    def test_the_gate_when_OFF_delivers_that_same_rewrite( self ):
        """
        The CONTROL for the gate test. Without it, an always-on gate and a correctly-off
        gate are indistinguishable — both green.
        """
        long_rewrite = "One. Two. Three. Four. Five. Six."
        text, meta = self.apply( _VERBOSE, config=_cfg( gate_enabled=False ),
                                 rewrite_fn=lambda b: long_rewrite )
        self.assertIn( long_rewrite, text )          # + the recipient notice
        self.assertEqual( meta[ "tutor_outcome" ], "rewritten" )

    def test_the_shipped_default_has_the_gate_OFF( self ):
        """Rick ruled no output gate. Every test above passes an explicit config, so none
        of them would notice if the shipped default were True."""
        from cosa.rest.routers.dm import get_dm_tutor_config
        self.assertFalse( get_dm_tutor_config()[ "gate_enabled" ] )

    def test_the_shipped_trigger_is_the_ruled_value( self ):
        """Rick lowered it from 6 to 4 on 2026-08-13."""
        from cosa.rest.routers.dm import get_dm_tutor_config
        self.assertEqual( get_dm_tutor_config()[ "trigger_claims" ], 4 )

    def test_the_shipped_config_has_the_tutor_ON( self ):
        """'Make sure it's actually in use.' A suite that only ever passes its own config
        cannot tell a shipped-on tutor from a shipped-off one."""
        from cosa.rest.routers.dm import get_dm_tutor_config
        self.assertTrue( get_dm_tutor_config()[ "enabled" ] )

    def test_measurements_are_recorded_in_and_out( self ):
        _, meta = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: "Verdict.\nOne.\nTwo." )
        self.assertEqual( meta[ "tutor_claims_in" ], 6 )
        self.assertEqual( meta[ "tutor_claims_out" ], 3 )
        self.assertGreater( meta[ "tutor_words_in" ], meta[ "tutor_words_out" ] )

    def test_claims_out_is_null_when_no_output_existed( self ):
        """A null must mean "there was no output", never "the output measured zero"."""
        _, meta = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: None )
        self.assertIsNone( meta[ "tutor_claims_out" ] )

    def test_an_unreadable_config_turns_the_tutor_OFF( self ):
        """A config failure must not route every DM in the fleet through a model on
        assumptions."""
        from cosa.rest.routers.dm import get_dm_tutor_config
        with patch( "cosa.config.configuration_manager.ConfigurationManager",
                    side_effect=RuntimeError( "ini unreadable" ) ):
            self.assertFalse( get_dm_tutor_config()[ "enabled" ] )

    def test_the_outcome_vocabulary_is_disjoint( self ):
        """
        Each of the five states must be distinguishable in the corpus. Before this field
        they were one silence: a row simply lacking a rewrite could not say whether the
        tutor was off, did not fire, fired and failed, or was gated.
        """
        outcomes = {
            self.apply( _VERBOSE,   config=_cfg( enabled=False ), rewrite_fn=lambda b: "x." )[ 1 ][ "tutor_outcome" ],
            self.apply( _COMPLIANT, config=_cfg(),               rewrite_fn=lambda b: "x." )[ 1 ][ "tutor_outcome" ],
            self.apply( _VERBOSE,   config=_cfg(),               rewrite_fn=lambda b: "x." )[ 1 ][ "tutor_outcome" ],
            self.apply( _VERBOSE,   config=_cfg(),               rewrite_fn=lambda b: None )[ 1 ][ "tutor_outcome" ],
            self.apply( _VERBOSE,   config=_cfg( gate_enabled=True, gate_max_claims=1 ),
                        rewrite_fn=lambda b: "One. Two. Three." )[ 1 ][ "tutor_outcome" ],
        }
        self.assertEqual(
            outcomes, { "disabled", "under_trigger", "rewritten", "model_failed", "gate_rejected" }
        )


class TestTheRecipientIsTold( unittest.TestCase ):
    """
    The reader is owed the fact that the prose is not the sender's (Cheech, 2026-08-13).

    ⚠️ THE GAP THIS CLOSES was invisible to every other test in this file, and the
    reason is worth stating: every disclosure test here checks what the SENDER must not
    learn. Nobody asked what the RECIPIENT is owed. So a reader could quote distilled
    wording back at the person who never wrote it, and the whole suite stayed green.
    """

    def setUp( self ):
        from cosa.rest.routers.dm import _apply_dm_tutor, DM_TUTOR_NOTICE
        self.apply  = _apply_dm_tutor
        self.notice = DM_TUTOR_NOTICE

    def test_a_rewritten_dm_carries_the_notice( self ):
        text, meta = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: "Verdict.\nOne.\nTwo." )
        self.assertEqual( meta[ "tutor_outcome" ], "rewritten" )
        self.assertIn( self.notice, text )

    def test_an_UNtouched_dm_carries_no_notice( self ):
        """A notice on a message the tutor never rewrote would be a lie about provenance."""
        for label, text_in, cfg in (
            ( "under trigger", _COMPLIANT, _cfg() ),
            ( "disabled",      _VERBOSE,   _cfg( enabled=False ) ),
        ):
            with self.subTest( case=label ):
                text, _ = self.apply( text_in, config=cfg, rewrite_fn=lambda b: "x." )
                self.assertNotIn( self.notice, text )

    def test_a_failed_rewrite_carries_no_notice( self ):
        """The sender's own words went out — saying otherwise would be backwards."""
        text, _ = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: None )
        self.assertNotIn( self.notice, text )

    def test_the_notice_names_no_number( self ):
        """It says THAT the message was shortened, never how long it was or what fired."""
        import re
        self.assertIsNone( re.search( r"\d", self.notice ),
                           f"the recipient notice leaks a number: {self.notice!r}" )

    def test_the_notice_is_STRUCTURE_not_a_claim( self ):
        """
        🔴 THE CANNED-P.S. TRAP, which this would have sprung identically. The notice is
        appended to EVERY rewrite, so if it counted as a claim, a clean three-claim
        distillation would arrive reading as four — and the tutor would rewrite its own
        output forever, firing hardest on the messages it had just fixed.
        """
        from cosa.agents.dm_tutor.sentences import count_sentences
        self.assertEqual( count_sentences( self.notice ), 0 )

        text, _ = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: "Verdict.\nOne.\nTwo." )
        self.assertEqual( count_sentences( text ), 3, "the notice inflated the delivered claim count" )

    def test_a_tutored_message_resent_does_not_re_trigger( self ):
        """The end-to-end form of the trap: feeding a delivered message back in must not fire."""
        text, _ = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: "Verdict.\nOne.\nTwo." )
        _, meta = self.apply( text, config=_cfg(), rewrite_fn=lambda b: "SHOULD NOT FIRE" )
        self.assertEqual( meta[ "tutor_outcome" ], "under_trigger" )

    def test_the_counter_and_the_constant_cannot_drift_apart( self ):
        """
        Pins the two sides together. They live in different modules, and editing the
        wording in dm.py alone would silently turn the notice back into a claim —
        re-arming the trap with no test noticing.
        """
        from cosa.agents.dm_tutor.sentences import count_sentences
        self.assertEqual(
            count_sentences( self.notice ), 0,
            "DM_TUTOR_NOTICE no longer matches the structure pattern in sentences.py — "
            "edit both, or the tutor will start rewriting its own output"
        )


class TestCorpusLocation( unittest.TestCase ):
    """Rick, 2026-08-13: the corpus sits OUTSIDE the repo."""

    def test_the_corpus_is_not_inside_the_checkout( self ):
        import cosa.rest.routers.dm as dm
        repo = os.path.abspath( cu.get_project_root() )
        self.assertFalse(
            os.path.abspath( dm._DM_TRAFFIC_JSONL ).startswith( repo + os.sep ),
            f"the corpus resolved back INSIDE the repo: {dm._DM_TRAFFIC_JSONL}"
        )

    def test_the_env_var_wins_when_set( self ):
        """This is how the containers point at their bind-mount."""
        import cosa.rest.routers.dm as dm
        with patch.dict( os.environ, { "LUPIN_DM_CORPUS_DIR": "/var/lupin/dm-corpus" } ):
            self.assertEqual( dm._resolve_dm_corpus_dir(), "/var/lupin/dm-corpus" )

    def test_the_fallback_is_still_outside_the_repo( self ):
        """
        The degradation path matters more than the happy one: a fallback that quietly
        returned a path inside the tree would undo the whole move, and would do it
        exactly when the fleet-root helper was unavailable — i.e. silently.
        """
        import cosa.rest.routers.dm as dm
        repo = os.path.abspath( cu.get_project_root() )
        with patch.dict( os.environ, {}, clear=True ):
            with patch( "lupin_cli.claude_code.hooks.lib.heartbeat_hold.fleet_data_root",
                        side_effect=ImportError( "no helper" ) ):
                resolved = os.path.abspath( dm._resolve_dm_corpus_dir() )
        self.assertFalse( resolved.startswith( repo + os.sep ), f"fallback landed in the repo: {resolved}" )


class _SendHarness( unittest.TestCase ):
    """Drives the REAL execute_dm_send with the tutor in place."""

    def setUp( self ):
        import cosa.rest.routers.dm as dm
        from cosa.rest.routers.dm import execute_dm_send, DmSendRequest
        from cosa.rest import dm_experiment

        self.dm            = dm
        self.execute       = execute_dm_send
        self.DmSendRequest = DmSendRequest
        self.queue         = MagicMock()
        self.persist       = MagicMock( return_value="db-123" )
        self.resolve       = MagicMock( return_value={
            "http_status": 200, "session_id": "abcdef1234567890", "persona_name": "mr radio",
        } )

        self.corpus_path = os.path.join( tempfile.mkdtemp(), "dm_traffic.jsonl" )
        p = patch.object( dm, "_DM_TRAFFIC_JSONL", self.corpus_path )
        p.start(); self.addCleanup( p.stop )

        # The pilot IS suspended, but pin it inactive here so this suite can never be
        # flipped onto the experiment path by the wall clock or by a config edit.
        q = patch.object( dm_experiment, "assignment_at", lambda instant: None )
        q.start(); self.addCleanup( q.stop )

    def _send( self, body_text, tutor_config, rewrite_fn ):
        body = self.DmSendRequest(
            sender_session_id = "sender-aaaa", body = body_text,
            recipient_persona = "mr radio",   sender_persona = "María",
            sender_icon       = "🌸",         sender_project = "lupin",
        )
        real_apply = self.dm._apply_dm_tutor
        with patch.object( self.dm, "_apply_dm_tutor",
                           lambda text: real_apply( text, config=tutor_config, rewrite_fn=rewrite_fn ) ):
            return self.execute(
                authenticated_user_id = "user-1", body = body,
                notification_queue    = self.queue,
                resolve_recipient_fn  = self.resolve,
                build_sender_id       = lambda sid, project=None: f"{sid}@{project}",
                persist_fn            = self.persist,
                new_id_fn             = lambda: "msg-1",
                now_fn                = None,
                grade_quality_fn      = lambda b: None,
            )

    def _rows( self ):
        return [ json.loads( line ) for line in
                 open( self.corpus_path, encoding="utf-8" ).read().splitlines() ]

    def _row( self ):
        return self._rows()[ 0 ]


class TestTheRewriteIsWhatGetsDelivered( _SendHarness ):
    """
    ⚠️ THE FAILURE THIS PREVENTS, and the reason this file exists. The tutor could
    return a perfect distillation, the corpus row could record it, and the ORIGINAL
    could still reach the recipient — every helper-level test would stay green and the
    fleet would see no change at all. These assert on what was PUSHED.
    """

    def test_the_recipient_receives_the_distilled_text( self ):
        self._send( _VERBOSE, _cfg(), lambda b: "Verdict.\nOne.\nTwo." )
        pushed = self.queue.push_notification.call_args.kwargs[ "message" ]
        self.assertIn( "Verdict.", pushed )
        self.assertNotIn( "I spent the morning tracing the leak", pushed )

    def test_the_stored_notification_carries_the_distilled_text_too( self ):
        """The recipient's history must agree with what they were pushed."""
        self._send( _VERBOSE, _cfg(), lambda b: "Verdict.\nOne.\nTwo." )
        stored = self.persist.call_args.kwargs[ "message" ]
        self.assertIn( "Verdict.", stored )
        self.assertNotIn( "I spent the morning tracing the leak", stored )

    def test_a_compliant_dm_reaches_the_recipient_untouched( self ):
        """The CONTROL: the tutor must be invisible to a message that obeys the shape."""
        self._send( _COMPLIANT, _cfg(), lambda b: "SHOULD NOT APPEAR" )
        pushed = self.queue.push_notification.call_args.kwargs[ "message" ]
        self.assertIn( "The tutor ships fleet-wide today.", pushed )
        self.assertNotIn( "SHOULD NOT APPEAR", pushed )

    def test_a_model_failure_delivers_the_senders_own_words( self ):
        self._send( _VERBOSE, _cfg(), lambda b: None )
        pushed = self.queue.push_notification.call_args.kwargs[ "message" ]
        self.assertIn( "I spent the morning tracing the leak", pushed )

    def test_the_delivered_text_never_names_the_trigger( self ):
        """
        🔴 The trigger number is UNPUBLISHED. A count shown only when the tutor fires
        leaks the height by arithmetic, and senders then write to the number instead of
        to the shape.
        """
        self._send( _VERBOSE, _cfg( trigger_claims=4 ), lambda b: "Verdict.\nOne.\nTwo." )
        pushed = self.queue.push_notification.call_args.kwargs[ "message" ].lower()
        for leak in ( "4 claims", "four claims", "trigger", "over the limit", "too long" ):
            self.assertNotIn( leak, pushed )


class TestTheCorpusRowTellsTheTruth( _SendHarness ):
    """Both bodies, the provenance, and an outcome that is never a silence."""

    def test_both_the_submitted_and_the_delivered_body_are_recorded( self ):
        """
        With only one of them the tutor's effect is unmeasurable in the very corpus
        built to measure it: the delivered text cannot recover what the sender wrote,
        and the submitted text cannot show what was sent.
        """
        self._send( _VERBOSE, _cfg(), lambda b: "Verdict.\nOne.\nTwo." )
        row = self._row()
        self.assertIn( "I spent the morning tracing the leak", row[ "body" ] )
        self.assertIn( "Verdict.", row[ "delivered_body" ] )
        self.assertTrue( row[ "body_was_rewritten" ] )
        self.assertGreater( row[ "words" ], row[ "delivered_words" ] )

    def test_an_untouched_dm_records_identical_bodies_and_says_so( self ):
        self._send( _COMPLIANT, _cfg(), lambda b: "SHOULD NOT APPEAR" )
        row = self._row()
        self.assertEqual( row[ "body" ], row[ "delivered_body" ] )
        self.assertFalse( row[ "body_was_rewritten" ] )
        self.assertEqual( row[ "tutor_outcome" ], "under_trigger" )

    def test_the_legacy_fields_still_describe_the_SUBMITTED_message( self ):
        """
        `words`/`chars`/`sentences`/`body` predate the tutor and are queried by existing
        analysis. Re-pointing them at the delivered text would silently change what every
        historical query means without changing its name.
        """
        self._send( _VERBOSE, _cfg(), lambda b: "Verdict.\nOne.\nTwo." )
        row = self._row()
        self.assertEqual( row[ "body" ], _VERBOSE )
        self.assertEqual( row[ "words" ], self.dm.dm_word_count( _VERBOSE ) )

    def test_every_row_carries_process_provenance( self ):
        """Rick: "enough identifying information that we can understand exactly which
        process created the serialized copies"."""
        self._send( _COMPLIANT, _cfg(), lambda b: None )
        row = self._row()
        for field in ( "corpus_schema_version", "writer", "boot_id", "pid", "host",
                       "server_port", "git_sha" ):
            self.assertIn( field, row, f"provenance field '{field}' missing from the row" )
        self.assertEqual( row[ "corpus_schema_version" ], self.dm.DM_CORPUS_SCHEMA_VERSION )

    def test_the_boot_id_is_stable_within_a_process( self ):
        """It groups a server lifetime. Changing per row would identify nothing, and a
        restart boundary would still have to be guessed from a gap in `ts`."""
        self._send( _COMPLIANT, _cfg(), lambda b: None )
        self._send( _COMPLIANT, _cfg(), lambda b: None )
        rows = self._rows()
        self.assertEqual( rows[ 0 ][ "boot_id" ], rows[ 1 ][ "boot_id" ] )

    def test_the_canonical_claim_count_rides_beside_the_legacy_count( self ):
        """
        Rows written before today carry only the naive `sentences` count. Overwriting
        that field with the claim count would make old and new rows incomparable while
        looking like one clean column.
        """
        self._send( _VERBOSE, _cfg(), lambda b: None )
        row = self._row()
        self.assertIn( "sentences", row )
        self.assertIn( "claims", row )
        self.assertEqual( row[ "claims" ], self.dm._count_claims( _VERBOSE ) )

    def test_the_tutor_outcome_is_present_on_every_row( self ):
        for label, text, cfg in (
            ( "compliant", _COMPLIANT, _cfg() ),
            ( "verbose",   _VERBOSE,   _cfg() ),
            ( "disabled",  _VERBOSE,   _cfg( enabled=False ) ),
        ):
            with self.subTest( case=label ):
                if os.path.exists( self.corpus_path ): os.remove( self.corpus_path )
                self._send( text, cfg, lambda b: "Verdict.\nOne.\nTwo." )
                self.assertIn( "tutor_outcome", self._row() )


if __name__ == "__main__":
    unittest.main()

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
from cosa.rest.routers.dm import _DM_TUTOR_DEFAULTS


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


# A FAITHFUL rewrite of _VERBOSE — it reuses the sender's own vocabulary, which is what
# a real rewrite does. Fixtures that invented new capitalised words ("Verdict. One. Two.")
# are now REFUSED by the fabrication guard, correctly: on the 27 real corpus pairs that
# guard has a 4% false-positive rate, so it was the FIXTURES that were unrealistic, not
# the check. Keeping the old ones would have meant loosening a guard to protect a test.
_FAITHFUL = (
    "The leak sits in the queue module.\n"
    "The line shipped last Tuesday.\n"
    "Tell me whether you read it the same way."
)

# Six claims, still drawn entirely from _VERBOSE's vocabulary — for the output-gate tests,
# which need an over-long rewrite that is not ALSO a fabrication.
_FAITHFUL_LONG = (
    "The leak sits in the queue module. The line shipped last Tuesday. "
    "Tell me whether you read it the same way. I am fairly confident about the diagnosis. "
    "Have a look when you get a moment. It sits in the module."
)


def _count_claims_helper( text ):
    """The canonical claim counter, for fixture-straddle CONTROLS in this file."""
    from cosa.rest.routers.dm import _count_claims
    return _count_claims( text )


def _cfg( **overrides ):
    """
    A tutor config dict with explicit values — never read from the live ini.

    ⚠️ SEEDED FROM `_DM_TUTOR_DEFAULTS`, not from a hand-written literal. The send path
    reads its config by direct indexing (`config[ "enabled" ]`), per the house rule that
    a missing key fails loudly rather than falling back — so a hand-written dict that
    misses a newly-added key raises KeyError inside `_apply_dm_tutor`, which catches it
    and delivers the ORIGINAL. Every "the tutor fired" test then fails with an assertion
    about delivered text, naming nothing about config. That happened when
    `fab_guard_strict` was added (row ddf7581e): 22 tests in this file went red at once.
    Seeding from the defaults means the next key costs nothing here.
    """
    base = dict( _DM_TUTOR_DEFAULTS )
    base.update( { "enabled": True, "trigger_claims": 4, "gate_enabled": False, "gate_max_claims": 4 } )
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
        text, meta = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: _FAITHFUL )
        self.assertIn( _FAITHFUL, text )
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
        long_rewrite = _FAITHFUL_LONG
        text, meta = self.apply( _VERBOSE, config=_cfg( gate_enabled=True, gate_max_claims=4 ),
                                 rewrite_fn=lambda b: long_rewrite )
        self.assertEqual( text, _VERBOSE, "the gate must fall back to the ORIGINAL, not the rewrite" )
        self.assertEqual( meta[ "tutor_outcome" ], "gate_rejected" )

    def test_the_gate_when_OFF_delivers_that_same_rewrite( self ):
        """
        The CONTROL for the gate test. Without it, an always-on gate and a correctly-off
        gate are indistinguishable — both green.
        """
        long_rewrite = _FAITHFUL_LONG
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
        _, meta = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: _FAITHFUL )
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
                        rewrite_fn=lambda b: _FAITHFUL )[ 1 ][ "tutor_outcome" ],
        }
        self.assertEqual(
            outcomes, { "disabled", "under_trigger", "rewritten", "model_failed", "gate_rejected" }
        )


class TestFabricationIsRefused( unittest.TestCase ):
    """
    ⚠️ A rewrite that INVENTS a fact is refused (Cheech's finding, 2026-08-13).

    THE INCIDENT: the tutor turned a message about a task-store row into three sentences
    about "the reviewer" wanting documentation. There was no reviewer.

    WHY THIS OUTRANKS THE LOSS DEFECTS, in Cheech's words and I agree: a DROPPED path is
    visibly missing, so he asked. An INVENTED one READS AS SIGNAL — his first instinct
    was to work out which reviewer and which change, and only the rest of the message
    being incoherent stopped him. And it is UNBOUNDED: a rewriter that can add one fact
    can add any fact, so no trigger value limits it. That is why raising the trigger was
    withdrawn as the answer.
    """

    def setUp( self ):
        from cosa.rest.routers.dm import _apply_dm_tutor, _fabricated_facts
        self.apply    = _apply_dm_tutor
        self.detect   = _fabricated_facts
        self.original = ( "I recreated the container from committed code. "
                          "I carried the credentials forward. Health is green. "
                          "The mount landed. The env vars landed." )

    def test_a_fabricated_hex_id_is_refused( self ):
        found = self.detect( self.original, "Deployed from commit b8d10bd3." )
        self.assertIn( "hex_id", found )

    def test_a_fabricated_number_is_refused( self ):
        self.assertIn( "number", self.detect( self.original, "Recreated 42 containers." ) )

    def test_a_fabricated_path_is_refused( self ):
        self.assertIn( "path", self.detect( self.original, "See src/cosa/rest/routers/dm.py." ) )

    def test_a_fabricated_name_is_refused_ANYWHERE_in_the_sentence( self ):
        """
        Position-independence is load-bearing and was a real bug in my first draft: I
        excluded sentence-initial words to cut false positives, which blinded the check
        to a fabricated name in the commonest position there is. The control caught it
        before it shipped, which is the entire reason to write controls.
        """
        self.assertIn( "name", self.detect( self.original, "Krishna recreated the container." ) )
        self.assertIn( "name", self.detect( self.original, "The container was recreated by Krishna." ) )

    def test_a_FAITHFUL_rewrite_is_not_refused( self ):
        """The control that stops this guard from simply blocking everything."""
        faithful = "The container was recreated from committed code.\nCredentials carried forward.\nHealth is green."
        self.assertEqual( self.detect( self.original, faithful ), {} )

    def test_a_faithful_REORDERING_is_not_refused( self ):
        reordered = "Health is green.\nCredentials were carried forward.\nThe container was recreated."
        self.assertEqual( self.detect( self.original, reordered ), {} )

    def test_the_sender_original_is_delivered_when_a_rewrite_fabricates( self ):
        text, meta = self.apply( self.original, config=_cfg(),
                                 rewrite_fn=lambda b: "Krishna deployed from commit b8d10bd3." )
        self.assertEqual( text, self.original, "a fabricating rewrite must not reach the recipient" )
        self.assertEqual( meta[ "tutor_outcome" ], "fabrication_blocked" )

    def test_what_was_fabricated_is_RECORDED_not_just_logged( self ):
        """
        "The tutor refused something" is unanswerable from a log line the next reader
        does not have. The corpus row must say WHAT was invented.
        """
        _, meta = self.apply( self.original, config=_cfg(),
                              rewrite_fn=lambda b: "Krishna deployed from commit b8d10bd3." )
        self.assertIn( "b8d10bd3", meta[ "tutor_fabricated" ][ "hex_id" ] )
        self.assertIn( "Krishna",  meta[ "tutor_fabricated" ][ "name" ] )

    def test_a_clean_rewrite_records_no_fabrication( self ):
        _, meta = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: _FAITHFUL )
        self.assertEqual( meta[ "tutor_outcome" ], "rewritten" )
        self.assertIsNone( meta[ "tutor_fabricated" ] )

    def test_the_guard_never_raises_into_the_send_path( self ):
        self.assertEqual( self.detect( None, None ), {} )

    def test_the_KNOWN_LIMIT_is_real_and_documented( self ):
        """
        ⚠️ HONESTY TEST. This guard would NOT have caught the incident that prompted it:
        "the reviewer" is a lowercase common noun, outside every class it checks. Pinning
        that here stops anyone — including me — from later reading this suite as proof
        the fabrication problem is solved. It is not; the remaining half needs the
        fail-first prompt regression, which is not built.

        The alternative was measured and rejected: a content-word novelty rule would have
        blocked 23 of the 27 real corpus pairs, because paraphrasing is the whole point.
        """
        original = "I will not rule on row e0bb5a94 from your relay of Krishna's finding."
        invented = "The reviewer is asking for additional documentation before approving."
        self.assertEqual(
            self.detect( original, invented ), {},
            "if this now FIRES, the guard has been widened — update the docstring's stated "
            "limit and re-measure the false-positive rate on the real corpus pairs"
        )


class TestThePathSurvives( unittest.TestCase ):
    """
    ⚠️ A LIVE DEFECT, found by Cheech 2026-08-13 in a real DM I sent him.

    The tutor PARAPHRASED A PATH AWAY, leaving the literal words "probe script path"
    where the path had been. The house rule the tutor exists to teach is "three
    sentences and A PATH" — so the one element the rule names by name is the element
    the rewrite destroyed, and it did so while the message otherwise looked compliant.

    The repair is deterministic rather than a prompt instruction, for the reason this
    whole module exists: asking a model to reproduce something exactly is a request
    that fails silently and only in the cases that matter.
    """

    def setUp( self ):
        from cosa.rest.routers.dm import _apply_dm_tutor, _restore_dropped_pointers
        self.apply   = _apply_dm_tutor
        self.restore = _restore_dropped_pointers

    # The actual message that failed, reduced to its shape.
    _WITH_PATH = (
        "I handed the row to Krishna with my refutation written in.\n"
        "The truncation theory is refuted by my own probe.\n"
        "He should copy the probe before using it.\n"
        "One more claim here.\n"
        "And another one.\n"
        "/tmp/claude-1001/scratchpad/repro_podcast_script.py"
    )
    _ATE_THE_PATH = (
        "Krishna has the row and the refutation.\n"
        "The truncation theory is refuted.\n"
        "He should copy the probe script path first."
    )

    def test_a_paraphrased_away_path_is_restored( self ):
        text, meta = self.apply( self._WITH_PATH, config=_cfg(),
                                 rewrite_fn=lambda b: self._ATE_THE_PATH )
        self.assertEqual( meta[ "tutor_outcome" ], "rewritten" )
        self.assertIn( "/tmp/claude-1001/scratchpad/repro_podcast_script.py", text )

    def test_the_instrument_can_fail( self ):
        """
        CONTROL. Without this, a restore that silently did nothing and a rewrite that
        never dropped the path would look identical — the test above would pass on
        unfixed code as long as the fixture happened to keep it.
        """
        self.assertNotIn( "/tmp/claude-1001/scratchpad/repro_podcast_script.py",
                          self._ATE_THE_PATH,
                          "the fixture no longer drops the path — this suite proves nothing" )

    def test_a_kept_path_is_not_duplicated( self ):
        kept = "Verdict.\nOne.\n/tmp/claude-1001/scratchpad/repro_podcast_script.py"
        self.assertEqual( self.restore( self._WITH_PATH, kept ), kept )

    def test_a_path_kept_INLINE_is_not_re_appended( self ):
        """Membership is checked against the whole rewrite, not line by line — a model
        that folded the path into a sentence still kept it."""
        inline = "Verdict.\nThe probe is at /tmp/claude-1001/scratchpad/repro_podcast_script.py now.\nTwo."
        self.assertEqual( self.restore( self._WITH_PATH, inline ), inline )

    def test_restoring_cannot_push_a_message_back_over_the_trigger( self ):
        """
        A restored pointer is STRUCTURE, so repairing a message can never re-trigger it.
        If it counted as a claim, the repair would arm the loop the canned P.S. taught.
        """
        from cosa.agents.dm_tutor.sentences import count_sentences
        _, meta = self.apply( self._WITH_PATH, config=_cfg(),
                              rewrite_fn=lambda b: self._ATE_THE_PATH )
        self.assertEqual( meta[ "tutor_claims_out" ], 3 )

    def test_a_body_with_no_pointer_is_untouched( self ):
        rewrite = _FAITHFUL
        self.assertEqual( self.restore( "Some prose. More prose.", rewrite ), rewrite )

    def test_the_repair_never_costs_the_caller_the_rewrite( self ):
        """A failure inside the repair must return the rewrite, not raise into delivery."""
        with patch( "cosa.agents.dm_tutor.sentences.pointer_tokens",
                    side_effect=RuntimeError( "boom" ) ):
            self.assertEqual( self.restore( self._WITH_PATH, "Verdict." ), "Verdict." )


class TestMidSentencePointersSurvive( unittest.TestCase ):
    """
    ⚠️ THE LINE-ANCHORED RESTORE ATE MID-SENTENCE POINTERS (row a74f2176).

    The first fix scanned whole lines with the structure rule, so it only saw a
    pointer that OWNED its line. A path or an 8-hex row id written INSIDE a sentence —
    "(running_fifo_queue.py:422)", "recording to row e0bb5a94" — was invisible, and the
    model paraphrased it away with the sentence around it. Measured on the served sha:
    4 of 26 rewrites dropped a file path, 9 dropped a row id. The earlier suite could
    not catch this because its one fixture put the path on its own line — exactly the
    case the line-anchored code already handled.
    """

    def setUp( self ):
        from cosa.rest.routers.dm import _apply_dm_tutor, _restore_dropped_pointers
        self.apply   = _apply_dm_tutor
        self.restore = _restore_dropped_pointers

    # Pointers buried MID-SENTENCE, the shape the line-anchored restore could not see:
    # a slashed path, a bare filename:line, a bare filename, and an 8-hex row id.
    _WITH_MID = (
        "I handed the row to Krishna and wrote in my refutation.\n"
        "The truncation theory is refuted by the probe at "
        "/tmp/claude-1001/scratchpad/repro.py which he should copy first.\n"
        "The leak is in running_fifo_queue.py:422 and also job.py, "
        "recording to row e0bb5a94 for continuity.\n"
        "I am fairly confident about the whole diagnosis.\n"
        "Tell me whether you read it the same way."
    )
    # A rewrite that keeps NONE of the four pointers — the failure this suite exists for.
    _ATE_THEM = (
        "Krishna has the row and the refutation.\n"
        "The truncation theory is refuted by my own probe script.\n"
        "The leak is in the running queue module; tell me if you agree."
    )

    def test_all_four_mid_sentence_pointers_are_restored( self ):
        text, meta = self.apply( self._WITH_MID, config=_cfg(),
                                 rewrite_fn=lambda b: self._ATE_THEM )
        self.assertEqual( meta[ "tutor_outcome" ], "rewritten" )
        for pointer in ( "/tmp/claude-1001/scratchpad/repro.py",
                         "running_fifo_queue.py:422", "job.py", "e0bb5a94" ):
            self.assertIn( pointer, text, f"{pointer} was not restored" )

    def test_the_instrument_can_fail( self ):
        """CONTROL — the fixture must actually DROP every pointer, or this proves nothing."""
        for pointer in ( "/tmp/claude-1001/scratchpad/repro.py",
                         "running_fifo_queue.py:422", "job.py", "e0bb5a94" ):
            self.assertNotIn( pointer, self._ATE_THEM,
                              f"fixture no longer drops {pointer} — suite proves nothing" )

    def test_a_mid_sentence_pointer_kept_INLINE_is_not_re_appended( self ):
        """A pointer the model carried through in prose must not be appended a second time."""
        kept = "The leak is over in running_fifo_queue.py:422 now, look there."
        result = self.restore( "See running_fifo_queue.py:422 for the leak.", kept )
        self.assertEqual( result, kept )
        self.assertEqual( result.count( "running_fifo_queue.py:422" ), 1 )

    def test_restoring_mid_sentence_pointers_cannot_re_trigger( self ):
        """
        Each restored token is appended as its OWN line, which _ATTACHMENT now reads as
        a whole-line pointer — so a bare filename or row id is structure once alone, and
        the repair can never push the message back over the trigger.
        """
        from cosa.agents.dm_tutor.sentences import count_sentences
        _, meta = self.apply( self._WITH_MID, config=_cfg(),
                              rewrite_fn=lambda b: self._ATE_THEM )
        self.assertEqual( meta[ "tutor_claims_out" ], count_sentences( self._ATE_THEM ) )
        self.assertLessEqual( meta[ "tutor_claims_out" ], _cfg()[ "trigger_claims" ] )

    def test_a_restored_row_id_is_not_read_as_fabricated( self ):
        """
        The restore runs BEFORE the fabrication check on purpose — a row id we put back
        came from the original, so it must never be flagged as an invented hex id.
        """
        text, meta = self.apply( self._WITH_MID, config=_cfg(),
                                 rewrite_fn=lambda b: self._ATE_THEM )
        self.assertEqual( meta[ "tutor_outcome" ], "rewritten" )
        self.assertIsNone( meta[ "tutor_fabricated" ] )


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
        text, meta = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: _FAITHFUL )
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

        text, _ = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: _FAITHFUL )
        self.assertEqual( count_sentences( text ), 3, "the notice inflated the delivered claim count" )

    def test_a_tutored_message_resent_does_not_re_trigger( self ):
        """The end-to-end form of the trap: feeding a delivered message back in must not fire."""
        text, _ = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: _FAITHFUL )
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
        self._send( _VERBOSE, _cfg(), lambda b: _FAITHFUL )
        pushed = self.queue.push_notification.call_args.kwargs[ "message" ]
        self.assertIn( "The leak sits in the queue module.", pushed )
        self.assertNotIn( "I spent the morning tracing the leak", pushed )

    def test_the_stored_notification_carries_the_distilled_text_too( self ):
        """The recipient's history must agree with what they were pushed."""
        self._send( _VERBOSE, _cfg(), lambda b: _FAITHFUL )
        stored = self.persist.call_args.kwargs[ "message" ]
        self.assertIn( "The leak sits in the queue module.", stored )
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
        self._send( _VERBOSE, _cfg( trigger_claims=4 ), lambda b: _FAITHFUL )
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
        self._send( _VERBOSE, _cfg(), lambda b: _FAITHFUL )
        row = self._row()
        self.assertIn( "I spent the morning tracing the leak", row[ "body" ] )
        self.assertIn( "The leak sits in the queue module.", row[ "delivered_body" ] )
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
        self._send( _VERBOSE, _cfg(), lambda b: _FAITHFUL )
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
                self._send( text, cfg, lambda b: _FAITHFUL )
                self.assertIn( "tutor_outcome", self._row() )


class TestAQuantityMayNotChangeSides( unittest.TestCase ):
    """
    Row c1a2e859 — a rewrite may not move a number from one side of a ledger to the other.

    THE INCIDENT (2026-08-14 03:51:21, live, in the corpus, Mr. Radio → María):

        sent      "tonight's 72 commits undercount by whatever is in them"
                  → the 72 ARE counted; the undercount is the 7 uncommitted files
        delivered "The roll-up undercounts by 72 commits plus whatever is in the 7
                   modified files"
                  → the 72 are now the MISSING amount

    María had just published the roll-up with those 72 commits in it. As delivered, a
    peer appeared to be telling her the number was wrong. She asked whether the line was
    mine, which is the only reason it was caught.

    WHY `_fabricated_facts` CANNOT SEE IT: nothing was invented. Both numbers appear in
    the input. What changed is which clause a quantity is bound to, and that guard has
    no notion of binding — it compares sets of values.

    THE PREDICATE, and what it costs, MEASURED on the live corpus (315 rewrite pairs,
    193 carrying a real quantity) rather than assumed:

        · refuse any sentence carrying a numeral that was altered  → blocks 104/193 (54%)
        · refuse on ANY scope word gained before a quantity        → blocks   5/193 (2.6%)
        · refuse on a LEDGER marker gained before a quantity       → blocks   1/193 (0.5%)

    The third is what ships: it refuses the known inversion and nothing else in a day's
    real traffic. The four the second rule adds were all read and all benign ("Section D
    IS sections 7, 9, 10" → "Section D INCLUDES sections 7, 9, 10").

    KNOWN LIMIT, stated rather than glossed: the ledger vocabulary is a closed set, so
    this catches the shape that actually occurred, not every possible re-scoping. A
    rewrite that inverts meaning without one of those markers passes untouched.
    """

    # Verbatim from the corpus row, trimmed to the sentences that carry the quantity.
    ORIGINAL  = ( "One loose end before you go: the roll-up you said you were running. "
                  "If it has not shipped, say so plainly to Rick rather than leaving it implied, "
                  "and if it has, it needs a caveat — lupin's working tree still holds 7 modified "
                  "files, so tonight's 72 commits undercount by whatever is in them. "
                  "Pushed and clean are not the same claim." )
    DELIVERED = ( "Has the roll-up shipped? "
                  "If not shipped, state plainly to Rick; if shipped, note lupin's working tree "
                  "holds 7 modified files. "
                  "The roll-up undercounts by 72 commits plus whatever is in the 7 modified files." )

    def setUp( self ):
        from cosa.rest.routers.dm import _apply_dm_tutor, _rescoped_quantities
        self.apply  = _apply_dm_tutor
        self.detect = _rescoped_quantities

    def test_the_real_inversion_is_caught( self ):
        """The one that happened. If this ever goes quiet, the guard has stopped working."""
        self.assertIn( "72", self.detect( self.ORIGINAL, self.DELIVERED ) )

    def test_a_FAITHFUL_compression_of_the_same_message_is_not_refused( self ):
        """
        The control. A guard that refuses the honest rewrite too is not a guard, it is an
        off switch — and it would be switched off.
        """
        faithful = ( "The roll-up needs a caveat: lupin's working tree holds 7 modified files, "
                     "so tonight's 72 commits undercount by whatever is in them." )
        self.assertEqual( self.detect( self.ORIGINAL, faithful ), {} )

    def test_a_quantity_the_rewrite_never_mentions_is_not_our_business( self ):
        """Dropping a number is the pointer-restore's problem; this guard only judges bindings."""
        self.assertEqual( self.detect( self.ORIGINAL, "The roll-up needs a caveat." ), {} )

    def test_a_NEW_number_is_left_to_the_fabrication_guard( self ):
        """Two guards, two jobs. Double-reporting would make each one's count unreadable."""
        self.assertEqual( self.detect( "Seven files are dirty.", "Nine files are dirty by 400." ), {} )

    def test_a_row_id_is_not_a_quantity( self ):
        """
        `41333974` is an identifier and is never on a side of a ledger. Measured as a live
        false positive on the corpus before this exclusion existed — the first cut of the
        harness also split `0c4e8cfa` into a `0`, and reported eight hits of which six
        were id fragments. The count looked like a finding and was an artefact.
        """
        self.assertEqual(
            self.detect( "Row 41333974 is a precondition for merging D.",
                         "Sam's builder lands first, ensuring no redundancy. Row 41333974 is a precondition." ),
            {} )

    def test_the_sender_original_is_delivered_when_a_rewrite_RE_SCOPES( self ):
        """The whole point: the recipient must get the sender's words, not the inversion."""
        text, meta = self.apply( self.ORIGINAL, config=_cfg( trigger_claims=2 ),
                                 rewrite_fn=lambda b: self.DELIVERED )
        self.assertEqual( text, self.ORIGINAL, "a re-scoping rewrite must not reach the recipient" )
        self.assertEqual( meta[ "tutor_outcome" ], "rescope_blocked" )

    def test_what_was_re_scoped_is_RECORDED_on_the_row( self ):
        """A corpus reader must be able to answer WHICH quantity moved, not just that one did."""
        _, meta = self.apply( self.ORIGINAL, config=_cfg( trigger_claims=2 ),
                              rewrite_fn=lambda b: self.DELIVERED )
        self.assertIn( "72", meta[ "tutor_rescoped" ] )

    def test_a_clean_rewrite_still_gets_delivered( self ):
        """The other half of the control, at the send path rather than the predicate."""
        text, meta = self.apply( _VERBOSE, config=_cfg(), rewrite_fn=lambda b: _FAITHFUL )
        self.assertEqual( meta[ "tutor_outcome" ], "rewritten" )
        self.assertIn( _FAITHFUL.split( "\n" )[ 0 ], text )

    def test_the_fixture_is_over_the_trigger_the_send_path_tests_use( self ):
        """
        CONTROL, and it earned its place on the first run: the corpus excerpt counts 3
        claims, so at the house trigger of 4 the tutor never fired and the two send-path
        tests above were measuring a tutor that never ran. If the claim counter moves,
        this fails instead of those two going quiet.
        """
        from cosa.rest.routers.dm import _count_claims
        self.assertGreater( _count_claims( self.ORIGINAL ), 2,
                            "the excerpt no longer clears trigger_claims=2" )

    def test_the_guard_never_takes_the_send_path_down( self ):
        """A check that raises must fail open, exactly as the fabrication guard does."""
        self.assertEqual( self.detect( 5, "the roll-up undercounts by 72 commits" ), {} )


class TestTheCondenserMayNotInventAnIdsType( unittest.TestCase ):
    """
    Row b1f3d2df — the rewrite may not supply a type noun the sender never wrote.

    A store row id and a git sha are both bare hex, so the condenser guesses a plausible
    noun and sometimes picks the wrong one. Observed live on 2026-08-13/14, verbatim from
    the corpus:

        sent      "DO NOT CLOSE 0c4e8cfa"                        (a store ROW)
        delivered "the mechanism identified by commit hash 0c4e8cfa"

        sent      "same session 6794a377 + same tmux"            (a SESSION)
        delivered "bug 6794a377"

    The reader's natural recovery — "go look up that commit" — fails silently, because
    the id resolves to nothing in git. And it is invisible to the sender, who sees only
    what they wrote. Mr. Radio corrected the SENDER twice for sloppy labelling; the
    sender had written it correctly both times.

    A LUCKY GUESS IS STILL REFUSED. When the condenser labels row `52912c4f` as "row" it
    happens to be right, and this still counts as invented — because a reader cannot tell
    a lucky guess from a wrong one, which is the entire failure.

    REPAIR FIRST, REFUSE ONLY IF THE REPAIR DOES NOT TAKE. Measured over the live corpus
    (134 rewrite pairs carrying a bare hex id):

        invented a type noun          18  (13.4%)
          repaired clean, delivered   12  ( 9.0%)  <- compression kept, false noun gone
          residual, so refused         6  ( 4.5%)  <- sender's original goes out

    Refusing all 18 was the obvious design and it throws away the tutor's whole purpose
    on a defect that is usually precisely repairable. Repairing WITHOUT re-checking was
    the tempting one, and it is worse than refusing: 6 of 18 keep a false label after a
    naive strip, so the repair would report success while the wrong noun was still on the
    wire. The re-check IS the gate.
    """

    def setUp( self ):
        from cosa.rest.routers.dm import (
            _apply_dm_tutor, _invented_id_labels, _strip_invented_id_labels )
        self.apply  = _apply_dm_tutor
        self.detect = _invented_id_labels
        self.strip  = _strip_invented_id_labels

    def test_a_row_id_relabelled_as_a_commit_is_caught( self ):
        found = self.detect( "DO NOT CLOSE 0c4e8cfa — Sam has live evidence.",
                             "The mechanism identified by commit hash 0c4e8cfa still fires." )
        self.assertIn( "0c4e8cfa", found )
        self.assertIn( "commit", found[ "0c4e8cfa" ] )

    def test_a_session_relabelled_as_a_bug_is_caught( self ):
        found = self.detect( "same session 6794a377 + same tmux returned at 11.2%",
                             "bug 6794a377 returned at 11.2%" )
        self.assertIn( "bug", found[ "6794a377" ] )

    def test_a_label_the_sender_WROTE_is_carried_forward_freely( self ):
        """The control. Keeping the sender's own noun is the whole point of not inventing."""
        self.assertEqual(
            self.detect( "Merged commit 341aeb8a after review.", "Merged commit 341aeb8a." ), {} )

    def test_a_bare_id_that_STAYS_bare_is_fine( self ):
        self.assertEqual( self.detect( "Row closed, see 29e98243.", "Closed. 29e98243" ), {} )

    def test_a_CORRECT_guess_is_still_invented( self ):
        """`52912c4f` really is a row — and the reader cannot tell that from a wrong guess."""
        self.assertIn( "row", self.detect( "52912c4f DONE (held)", "row 52912c4f is done" )[ "52912c4f" ] )

    def test_an_id_only_the_rewrite_mentions_is_the_fabrication_guards_job( self ):
        self.assertEqual( self.detect( "Nothing to see.", "See commit b8d10bd3." ), {} )

    def test_the_repair_removes_the_invented_noun_and_keeps_the_sentence( self ):
        original  = "DO NOT CLOSE 0c4e8cfa — Sam has live evidence."
        rewritten = "The mechanism identified by commit hash 0c4e8cfa still fires."
        repaired  = self.strip( original, rewritten )
        self.assertIn( "0c4e8cfa", repaired,  "the id itself must survive the repair" )
        self.assertNotIn( "commit", repaired )
        self.assertIn( "identified by 0c4e8cfa", repaired )
        self.assertEqual( self.detect( original, repaired ), {},
                          "a repaired body must be clean by this guard's own reading" )

    def test_a_repaired_rewrite_is_DELIVERED_not_refused( self ):
        original  = ( "DO NOT CLOSE 0c4e8cfa — Sam has live evidence the mechanism still fires. "
                      "It contradicts the verdict I relayed this morning. "
                      "His run enqueued a child job. The submit returned 200. "
                      "Tell me if you read it differently." )
        text, meta = self.apply( original, config=_cfg(),
                                 rewrite_fn=lambda b: "The mechanism identified by commit hash 0c4e8cfa still fires." )
        self.assertEqual( meta[ "tutor_outcome" ], "rewritten",
                          "a repairable label must not cost the sender the compression" )
        self.assertNotIn( "commit", text )
        self.assertIn( "0c4e8cfa", text )
        self.assertIn( "0c4e8cfa", meta[ "tutor_id_labels" ],
                       "the repair must be RECORDED — a silent repair is unauditable" )

    def test_a_rewrite_whose_label_SURVIVES_the_repair_is_refused( self ):
        """
        The gate that makes the repair honest — and this is a REAL corpus case
        (2026-08-13 16:11:44, Mr. Radio → Cheech), not an invented shape.

        Stripping "commit hash" slides the window back and EXPOSES a second invented noun
        that was previously out of reach:

            rewrite   "The task with commit hash 0c4e8cfa was closed incorrectly"
            stripped  "The task with 0c4e8cfa was closed incorrectly"   <- "task" now visible

        A one-pass repair would have delivered that, having "fixed" the message, while it
        still mislabels a row as a task. The re-check is what turns the repair from a
        claim into a gate.
        """
        original  = ( "Sam is right and my close was wrong — I closed 0c4e8cfa this morning "
                      "on a green test and his live run shows the behaviour still happening. "
                      "I have written the correction onto the row. "
                      "You need to know before you act on my earlier verdict. "
                      "Tell me if you read it differently." )
        self.assertGreater( _count_claims_helper( original ), 3,
                            "CONTROL: the fixture must clear the trigger, or this measures a tutor that never ran" )
        text, meta = self.apply(
            original, config=_cfg( trigger_claims=3 ),
            rewrite_fn=lambda b: "The task with commit hash 0c4e8cfa was closed incorrectly." )
        self.assertEqual( meta[ "tutor_outcome" ], "label_blocked" )
        self.assertEqual( text, original, "an unrepairable false label must not reach the recipient" )
        self.assertIn( "task", meta[ "tutor_id_labels" ][ "0c4e8cfa" ],
                       "the row must record the noun that SURVIVED, not the one already stripped" )

    def test_KNOWN_LIMIT_a_noun_placed_AFTER_the_id_is_not_seen( self ):
        """
        Stated rather than glossed, because the guard's silence here is not innocence.

        The window looks BEFORE an id only. "92062fe2, the commit, should be added"
        carries the same false label and this guard does not fire on it. Widening to a
        following window was not measured, so it is not claimed — if this test ever goes
        red, somebody widened the window and should re-price the whole rule on the corpus.
        """
        self.assertEqual(
            self.detect( "Closing 92062fe2 today.", "92062fe2, the commit, should be added." ),
            {} )

    def test_the_guard_never_takes_the_send_path_down( self ):
        self.assertEqual( self.detect( 5, "commit 0c4e8cfa" ), {} )
        self.assertEqual( self.strip( 5, "commit 0c4e8cfa" ), "commit 0c4e8cfa" )

    def test_a_repair_that_RAISES_costs_the_caller_nothing( self ):
        """
        The fail-open contract, pinned rather than assumed. `_invented_id_labels` swallows
        its own failures, so the strip's own except is not reachable through bad input —
        it is reachable only if the substitution itself blows up. Forcing that is the
        difference between a defensive branch that is tested and one that is merely
        believed.
        """
        from unittest.mock import patch
        import cosa.rest.routers.dm as dm

        original, rewritten = "Closed 0c4e8cfa today.", "Closed commit 0c4e8cfa today."
        with patch.object( dm.re, "sub", side_effect=RuntimeError( "boom" ) ):
            self.assertEqual( self.strip( original, rewritten ), rewritten,
                              "a raising repair must return the rewrite untouched, never lose it" )


class TestSlashEnumerationsAreNotRestoredAsPointers( unittest.TestCase ):
    """
    🔴 REGRESSION, row 206dd6ea (María, 2026-08-15). A clean rewrite arrived with a
    garbage final line — "training/" — that read as a message truncated mid-word. The
    cause was NOT XML truncation (that fails closed correctly): the sender's own prose
    carried a slash-enumeration ("§5.3: training/ ...") and a ratio ("10/10", "6/10")
    that the pointer regex mistook for file paths, so `_restore_dropped_pointers`
    appended one as its own line. The restore must append a real path and NOTHING else.

    The steer: a faithful shorter body is safe, a fragment is not. Here the fix delivers
    the faithful three-line rewrite WITHOUT the mis-read fragment.
    """

    def setUp( self ):
        from cosa.rest.routers.dm import _apply_dm_tutor, _restore_dropped_pointers, DM_TUTOR_NOTICE
        self.apply   = _apply_dm_tutor
        self.restore = _restore_dropped_pointers
        self.notice  = DM_TUTOR_NOTICE

    # Rachel's real DM to María, reduced to its shape: three claims plus prose that
    # happens to contain a slash-enumeration and two ratios.
    _WITH_ENUMS = (
        "Short form. Design stands; two gates don't.\n"
        "§6: assertions 5 and 6 can't fail as written.\n"
        "§5.3: training/ has five files in two namespaces; a glob false-orphans 21.\n"
        "§5.4: unresolved — Tiberius reads 10/10 where you cite 6/10."
    )
    # A faithful rewrite that (correctly) drops the enum fragment and keeps the ratios
    # inside its §5.4 sentence.
    _FAITHFUL_REWRITE = (
        "Design stands; two gates don't.\n"
        "§6: assertions 5 and 6 can't fail as written.\n"
        "§5.4: unresolved — Tiberius reads 10/10 where you cite 6/10."
    )

    def test_the_delivered_body_gains_no_garbage_pointer_line( self ):
        text, meta = self.apply( self._WITH_ENUMS, config=_cfg(),
                                 rewrite_fn=lambda b: self._FAITHFUL_REWRITE )
        self.assertEqual( meta[ "tutor_outcome" ], "rewritten" )
        self.assertNotIn( "training/", text,
                          "a slash-enumeration was mis-restored as a pointer line" )
        # The faithful three claims survive; nothing was appended below them.
        body = text.split( self.notice )[ 0 ].rstrip()
        self.assertEqual( body, self._FAITHFUL_REWRITE )

    def test_the_restore_appends_nothing_for_a_body_of_only_enums( self ):
        self.assertEqual( self.restore( self._WITH_ENUMS, self._FAITHFUL_REWRITE ),
                          self._FAITHFUL_REWRITE )

    def test_the_instrument_can_fail( self ):
        """
        CONTROL. The fixture MUST carry a token the old regex would have mis-read, or
        the assertion above proves nothing. Delete `_is_real_pointer`'s filtering and
        the un-fixed regex yields "training/" here, turning both tests above red.
        """
        from cosa.agents.dm_tutor.sentences import _POINTER_TOKEN
        raw = _POINTER_TOKEN.findall( self._WITH_ENUMS )
        self.assertIn( "training/", raw,
                       "fixture lost the mis-read fragment — this suite proves nothing" )

    def test_a_real_path_beside_the_enums_is_still_restored( self ):
        """The fix must not over-correct: a genuine dropped path is still put back."""
        with_path = self._WITH_ENUMS + "\nfull detail in src/rnd/v0.2.0/cascade-r2.md"
        text, meta = self.apply( with_path, config=_cfg(),
                                 rewrite_fn=lambda b: self._FAITHFUL_REWRITE )
        self.assertIn( "src/rnd/v0.2.0/cascade-r2.md", text )
        self.assertNotIn( "training/", text )


if __name__ == "__main__":
    unittest.main()

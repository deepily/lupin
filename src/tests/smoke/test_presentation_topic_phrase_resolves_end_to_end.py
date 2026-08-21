#!/usr/bin/env python3
"""
END-TO-END, IN PROCESS: a presentation whose `source` is a topic phrase resolves to a
REAL FILE ON DISK instead of ending the job FAILED (row 5bc22180).

WHY THIS EXISTS ALONGSIDE THE UNIT TESTS. The unit tests mock
`_handle_fuzzy_file_match`, so they prove the CALL is made with the right arguments and
nothing about whether the resolution actually lands on a file. This runs the real
handler, the real matcher, the real keyword prefilter and a real directory of real
files. The only things stubbed are the ones that are not the code under test: the LLM
that extracts args from the utterance, and the two surfaces that would otherwise wait
for a human (the "which document?" ask and the confirmation step). The real
ConfigurationManager runs — the handler builds its own inside the method, and letting
it do so keeps the config lookup real too.

WHAT IT WOULD HAVE DONE BEFORE THE FIX. `source="KISS"` is present-not-missing, so the
missing-args loop skips it, and the rescue loop was fenced to the podcast command — so
"KISS" travelled downstream, `presentation_generator/job.py` pre-validated the path,
raised FileNotFoundError("Source document not found: KISS"), and the job ended FAILED.

NO LLM CALL HAPPENS HERE, and that is deliberate rather than lucky: the matcher's
`dominant_keyword_match` step resolves a description that clearly names one candidate
before the LLM step is reached. A test that quietly needed a model would be a test that
fails when the model is down.

VENUE: :7999-eligible — no server, no network, no persistent state (everything lives in
a temp directory), well under a second.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import cosa.agents.runtime_argument_expeditor.expeditor as ex_mod
from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor


PR    = "agent router go to presentation generator"
EMAIL = "u@example.com"

# One document the utterance clearly names, plus decoys that share no keywords with it.
DOCS = {
    "kiss-protocol.md"        : "# The KISS protocol\n\nKeep it short.\n",
    "quantum-annealing.md"    : "# Quantum annealing\n\nUnrelated.\n",
    "supply-chain-review.md"  : "# Supply chain review\n\nAlso unrelated.\n",
}


def _seed_research_dir( root ):
    """Write the real files the real matcher will search. Returns the directory."""
    research_dir = os.path.join( root, "io", "deep-research", EMAIL )
    os.makedirs( research_dir, exist_ok=True )
    for name, body in DOCS.items():
        with open( os.path.join( research_dir, name ), "w", encoding="utf-8" ) as handle:
            handle.write( body )
    return research_dir


def _link_real_config( root ):
    """
    Point the temp root's `src/conf` at the repo's real one.

    The handler builds a real ConfigurationManager, which resolves its ini file under
    the project root — and the project root is the temp directory here. Symlinking the
    real config in keeps the config lookup REAL while the documents stay in a temp
    directory: copying it would let this test pass against a stale copy of a file the
    rest of the system reads live.
    """
    repo_conf = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "conf" )
    os.makedirs( os.path.join( root, "src" ), exist_ok=True )
    os.symlink( repo_conf, os.path.join( root, "src", "conf" ) )


def _mk_expeditor():
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, **kw: default
    with patch.object( ex_mod, "LlmClientFactory", MagicMock() ):
        o = RuntimeArgumentExpeditor( cfg, debug=False )
    o.prompt_template_path = "/t.txt"
    o.llm_spec_key         = "spec"
    return o


def _parsed_with_topic_phrase_source():
    """What the extraction LLM hands back: `source` present, but a topic phrase."""
    parsed = MagicMock()
    parsed.is_complete.return_value  = False
    parsed.get_present_dict.return_value = { "source": "KISS" }
    return parsed


class TestPresentationTopicPhraseResolvesToARealFile( unittest.TestCase ):

    def setUp( self ):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.research_dir = _seed_research_dir( self.root )
        _link_real_config( self.root )
        self.addCleanup( self._tmp.cleanup )

    def _run_expedite( self, utterance, extra_patches=() ):
        """
        Drive the real expedite() with only the non-subject seams stubbed.

        Ensures:
            - the real _handle_fuzzy_file_match, the real matcher and the real
              directory listing are all exercised
            - returns (final_args_or_None, ask_mock)
        """
        o    = _mk_expeditor()
        asks = MagicMock( return_value=None )   # a fired ask returns None → cancel, and is visible
        patches = [
            patch.object( ex_mod, "get_cli_help", return_value="help" ),
            patch.object( ex_mod, "get_user_visible_args", return_value=[ "source" ] ),
            patch.object( ex_mod.cu, "get_file_as_string", return_value="tmpl {system_args}{help_text}{voice_command}{extracted_args}{required_args}" ),
            patch.object( ex_mod.cu, "get_project_root", return_value=self.root ),
            patch.object( ex_mod, "PromptTemplateProcessor" ),
            patch.object( ex_mod.ExpeditorResponse, "from_xml",
                          return_value=_parsed_with_topic_phrase_source() ),
            patch.object( o, "_ask_for_arg", asks ),
            patch.object( o, "_confirm_and_iterate", side_effect=lambda args, *rest: args ),
        ] + list( extra_patches )
        for p in patches: p.start()
        ex_mod.PromptTemplateProcessor.return_value.process_template.side_effect = lambda t, n: t
        try:
            out = o.expedite( PR, "", EMAIL, "s", "uid", utterance )
        finally:
            for p in reversed( patches ): p.stop()
        return out, asks

    def test_topic_phrase_source_resolves_to_the_real_document_on_disk( self ):
        # THE PROOF. "KISS" arrives as the value of `source`; the rescue runs the real
        # matcher over the real directory and comes back with the real file — no
        # question asked, because the utterance names exactly one candidate.
        out, asks = self._run_expedite( "make me a presentation on the KISS protocol" )

        self.assertIsNotNone( out, "expedite returned None — the flow cancelled instead of resolving" )
        self.assertEqual( out[ "source" ], os.path.join( self.research_dir, "kiss-protocol.md" ) )
        self.assertTrue( os.path.exists( out[ "source" ] ), "resolved to a path that does not exist" )
        self.assertNotEqual( out[ "source" ], "KISS", "still the bare topic — the rescue did not fire" )
        asks.assert_not_called()   # auto-resolved: the user was asked nothing

    def test_the_resolved_value_is_what_the_job_pre_validation_demands( self ):
        # The failure this row is about happens in presentation_generator/job.py, which
        # pre-validates with os.path.exists BEFORE building the orchestrator. Asserting
        # against that same predicate ties the proof to the real gate rather than to a
        # string comparison.
        out, _ = self._run_expedite( "make me a presentation on the KISS protocol" )
        self.assertTrue( os.path.exists( out[ "source" ] ) )

    def test_control_with_the_rescue_suppressed_the_bare_topic_survives( self ):
        # THE CAN-FAIL CONTROL. Make the rescue believe `source` is already a real path
        # — which is exactly what the podcast fence did for presentation, skip the
        # resolve — and the assertion above inverts: `source` stays "KISS", the value
        # that made the job raise FileNotFoundError. Without this arm, the test above
        # proves only that something ran.
        out, _ = self._run_expedite(
            "make me a presentation on the KISS protocol",
            extra_patches=[ patch.object( RuntimeArgumentExpeditor, "_value_is_existing_path",
                                          return_value=True ) ],
        )
        self.assertEqual( out[ "source" ], "KISS" )
        self.assertFalse( os.path.exists( out[ "source" ] ) )   # the pre-fix failure, reproduced

    def test_a_topic_phrase_matching_nothing_falls_through_to_the_ask_not_a_crash( self ):
        # The other half of the contract: when the matcher cannot narrow to one file,
        # the user is ASKED. It must never crash and never pass the bare topic on.
        out, asks = self._run_expedite( "make me a presentation about medieval falconry" )
        asks.assert_called()          # the user was asked
        self.assertIsNone( out )      # the stub answers None (cancel) → clean exit


if __name__ == "__main__":
    unittest.main()

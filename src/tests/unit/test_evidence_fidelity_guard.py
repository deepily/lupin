#!/usr/bin/env python3
"""
Evidence-fidelity guard (row assigned by Cheech 2026-08-17) — both directions.

EXECUTOR: AI — pure text/JSON logic over temp files + a read-only scan of the real
src/rnd tree; no server, no git. :7999-class.

The guard must FIRE on the f008951a shape (an .md's embedded JSON disagreeing with its
raw .bridge.json sibling on key presence, UNLABELLED) and stay SILENT when the .md is
labelled a projection OR agrees with the raw sibling OR has no raw sibling at all (the
honest standalone dump, e.g. the maria bridge). The real-tree scan asserts the current
src/rnd is clean, so a future unlabelled projection lands red here.

Run: PYTHONPATH=src python -m pytest src/tests/unit/test_evidence_fidelity_guard.py -v
"""

import json
import os
import shutil
import tempfile
import unittest

import cosa.utils.util as cu
from tests import evidence_fidelity_guard as guard


_RAW = { "session_id": "s-1", "voice_persona": None, "cwd": "/x" }   # note: NO manager_figure_implicit


def _md_with_json( obj, *, labelled ):
    label = (
        "> ⚠️ This JSON block is a SELECTIVE PROJECTION, not a faithful dump — "
        "do not read key presence off it. The raw .bridge.json wins.\n\n"
        if labelled else ""
    )
    return f"# evidence\n\n{label}```json\n{json.dumps( obj, indent=2 )}\n```\n"


class TestPredicate( unittest.TestCase ):

    def test_label_detection( self ):
        self.assertTrue( guard.has_projection_label( "prefix SELECTIVE PROJECTION suffix" ) )
        self.assertTrue( guard.has_projection_label( "do not read key presence off it" ) )
        self.assertFalse( guard.has_projection_label( "an ordinary evidence note" ) )

    def test_presence_disagreement_names_the_invented_key( self ):
        # .md block carries manager_figure_implicit:null; raw lacks it → the f008951a shape.
        md  = _md_with_json( { **_RAW, "manager_figure_implicit": None }, labelled=False )
        dis = guard.presence_disagreement( md, json.dumps( _RAW ) )
        self.assertEqual( dis, { "manager_figure_implicit" } )

    def test_agreement_is_silent( self ):
        md = _md_with_json( _RAW, labelled=False )
        self.assertEqual( guard.presence_disagreement( md, json.dumps( _RAW ) ), set() )

    def test_unparseable_raw_is_failsafe_silent( self ):
        md = _md_with_json( { **_RAW, "x": 1 }, labelled=False )
        self.assertEqual( guard.presence_disagreement( md, "not json at all" ), set() )

    def test_embedded_blocks_skip_nondict_and_unparseable_fences( self ):
        # a ```json block that parses to a non-dict (array) AND one that does not parse:
        # both must be skipped, so only the real dict block's keys count.
        md = (
            "```json\n[ 1, 2, 3 ]\n```\n"                       # parses, not a dict → dropped
            "```json\n{ not valid json ,,, }\n```\n"            # unparseable → dropped
            "```json\n{ \"session_id\": \"s-1\" }\n```\n"       # the real one
        )
        self.assertEqual( guard.embedded_json_key_sets( md ), [ { "session_id" } ] )

    # -- check_pair: the honesty decision --------------------------------------
    def test_check_pair_FIRES_on_unlabelled_disagreement( self ):
        md     = _md_with_json( { **_RAW, "manager_figure_implicit": None }, labelled=False )
        reason = guard.check_pair( md, json.dumps( _RAW ) )
        self.assertIsNotNone( reason )
        self.assertIn( "manager_figure_implicit", reason )

    def test_check_pair_SILENT_when_labelled( self ):
        # same disagreement, but labelled a projection → honest → silent (the f008951a FIX).
        md = _md_with_json( { **_RAW, "manager_figure_implicit": None }, labelled=True )
        self.assertIsNone( guard.check_pair( md, json.dumps( _RAW ) ) )

    def test_check_pair_SILENT_when_agreeing_even_unlabelled( self ):
        md = _md_with_json( _RAW, labelled=False )
        self.assertIsNone( guard.check_pair( md, json.dumps( _RAW ) ) )


class TestTreeScan( unittest.TestCase ):

    def setUp( self ):
        self._tmp = tempfile.mkdtemp()

    def tearDown( self ):
        shutil.rmtree( self._tmp, ignore_errors=True )

    def _write( self, rel, text ):
        path = os.path.join( self._tmp, rel )
        os.makedirs( os.path.dirname( path ), exist_ok=True )
        with open( path, "w", encoding="utf-8" ) as handle:
            handle.write( text )
        return path

    def test_standalone_raw_dump_is_not_a_pair( self ):
        # a raw .bridge.json with NO .md partner (the honest maria case) → no pair, no problem.
        self._write( "d/x.bridge.json", json.dumps( _RAW ) )
        self.assertEqual( guard.find_paired_evidence( self._tmp ), [] )
        self.assertEqual( guard.check_evidence_tree( self._tmp ), [] )

    def test_tree_scan_FIRES_on_an_unlabelled_disagreeing_pair( self ):
        self._write( "d/e.md", _md_with_json( { **_RAW, "manager_figure_implicit": None }, labelled=False ) )
        self._write( "d/e.md.bridge.json", json.dumps( _RAW ) )
        problems = guard.check_evidence_tree( self._tmp )
        self.assertEqual( len( problems ), 1 )
        self.assertIn( "manager_figure_implicit", problems[ 0 ] )

    def test_tree_scan_SILENT_on_the_labelled_pair( self ):
        self._write( "d/e.md", _md_with_json( { **_RAW, "manager_figure_implicit": None }, labelled=True ) )
        self._write( "d/e.md.bridge.json", json.dumps( _RAW ) )
        self.assertEqual( guard.check_evidence_tree( self._tmp ), [] )

    def test_scan_reach_counts_what_the_walk_saw( self ):
        self._write( "d/e.md", "# x" )
        self._write( "d/e.md.bridge.json", json.dumps( _RAW ) )
        self._write( "d/notes.txt", "x" )
        self.assertEqual(
            guard.scan_reach( self._tmp ),
            { "files": 3, "markdown": 1, "raw_siblings": 1 }
        )

    def test_scan_reach_is_all_zero_for_a_root_that_is_not_there( self ):
        # the vacuity the real-tree canary exists to catch: a walk over nothing.
        self.assertEqual(
            guard.scan_reach( os.path.join( self._tmp, "no-such-dir" ) ),
            { "files": 0, "markdown": 0, "raw_siblings": 0 }
        )


class TestRealTreeIsClean( unittest.TestCase ):
    """The live src/rnd tree must be clean — so a FUTURE unlabelled projection lands red here."""

    def _rnd( self ):
        return cu.get_project_root() + "/src/rnd"

    def test_no_unlabelled_projection_in_src_rnd( self ):
        problems = guard.check_evidence_tree( self._rnd() )
        self.assertEqual( problems, [], "evidence-fidelity problems in src/rnd:\n" + "\n".join( problems ) )

    def test_the_clean_verdict_is_not_vacuous( self ):
        """
        The canary for the assertion above, which can go vacuously green two ways — and
        BOTH are checked here, neither by naming a file in the tree.

        The previous shape asserted one hard-coded src/rnd filename was in the scan, and
        went red the day Rick deleted that doc (c752ab9e, row a8222a71). Worse, the tree now
        holds ZERO paired evidence, so no assertion about the real tree's CONTENTS can be
        both green and meaningful. So: prove the FINDER on a pair this test plants itself
        (repo-independent — no future tidy-up of src/rnd can break it), and prove the WALK
        reaches the real root separately.
        """
        # (1) the finder still finds — the pair-discovery check_evidence_tree() depends on.
        tmp = tempfile.mkdtemp()
        self.addCleanup( shutil.rmtree, tmp, True )
        md  = os.path.join( tmp, "deep", "nested", "planted-evidence.md" )
        os.makedirs( os.path.dirname( md ), exist_ok=True )
        with open( md, "w", encoding="utf-8" ) as handle:
            handle.write( _md_with_json( _RAW, labelled=False ) )
        with open( md + guard.RAW_SIBLING_SUFFIX, "w", encoding="utf-8" ) as handle:
            handle.write( json.dumps( _RAW ) )
        self.assertEqual(
            guard.find_paired_evidence( tmp ),
            [ ( md, md + guard.RAW_SIBLING_SUFFIX ) ],
            "the pair finder no longer finds a planted pair — the real-tree scan above is "
            "reporting clean because it discovers nothing, not because the tree is honest"
        )

        # (2) the walk still reaches the real root — same walk find_paired_evidence uses.
        reach = guard.scan_reach( self._rnd() )
        self.assertGreater(
            reach[ "markdown" ], 0,
            f"src/rnd looks unreachable or empty at {self._rnd()}: {reach} — a clean verdict "
            "from a walk that saw nothing is vacuous, check LUPIN_ROOT and the tree"
        )


if __name__ == "__main__":
    unittest.main()

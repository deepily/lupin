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


class TestRealTreeIsClean( unittest.TestCase ):
    """The live src/rnd tree must be clean — so a FUTURE unlabelled projection lands red here."""

    def test_no_unlabelled_projection_in_src_rnd( self ):
        rnd = cu.get_project_root() + "/src/rnd"
        problems = guard.check_evidence_tree( rnd )
        self.assertEqual( problems, [], "evidence-fidelity problems in src/rnd:\n" + "\n".join( problems ) )

    def test_the_scan_actually_found_the_known_pair( self ):
        # guard against a silent-empty scan: the e071e834 pair must be discovered, or the
        # real-tree assertion above is vacuously green.
        rnd   = cu.get_project_root() + "/src/rnd"
        pairs = guard.find_paired_evidence( rnd )
        self.assertTrue(
            any( md.endswith( "2026.08.16-nameless-seat-e071e834-live-evidence.md" ) for md, _raw in pairs ),
            f"expected the e071e834 evidence pair in the scan; found {[ os.path.basename( m ) for m, _ in pairs ]}"
        )


if __name__ == "__main__":
    unittest.main()

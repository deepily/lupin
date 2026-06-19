"""
Unit tests for runtime_argument_expeditor/xml_models.py:
  - ExpeditorResponse        : gap-analysis model (is_complete, get_missing_list, get_present_dict)
  - ArgConfirmationResponse  : modify-intent model (is_approval, is_cancel, is_modify)

Both are BaseXMLModel subclasses — pure parsing/logic, no LLM/SDK/network.
quick_smoke_test methods are excluded via the root pyproject coverage config.

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, runtime_argument_expeditor lane).
"""

import unittest

import cosa.agents.runtime_argument_expeditor.xml_models as xm


# ============================================================================
# ExpeditorResponse
# ============================================================================

class TestExpeditorResponse( unittest.TestCase ):

    def test_is_complete_true_and_false( self ):
        self.assertTrue( xm.ExpeditorResponse( all_required_met="TRUE", args_present="", args_missing="" ).is_complete() )
        self.assertFalse( xm.ExpeditorResponse( all_required_met="false", args_present="", args_missing="" ).is_complete() )

    def test_get_missing_list_empty_and_populated( self ):
        empty = xm.ExpeditorResponse( all_required_met="true", args_present="", args_missing="   " )
        self.assertEqual( empty.get_missing_list(), [] )
        populated = xm.ExpeditorResponse( all_required_met="false", args_present="", args_missing=" budget , audience ,, " )
        self.assertEqual( populated.get_missing_list(), [ "budget", "audience" ] )

    def test_get_present_dict_parses_pairs_and_skips_non_pairs( self ):
        r = xm.ExpeditorResponse(
            all_required_met="false",
            args_present="query=quantum computing, budget=10, junk_no_equals, url=http://x?a=b",
            args_missing="",
        )
        d = r.get_present_dict()
        self.assertEqual( d[ "query" ], "quantum computing" )
        self.assertEqual( d[ "budget" ], "10" )
        self.assertNotIn( "junk_no_equals", d )         # no '=' → skipped
        self.assertEqual( d[ "url" ], "http://x?a=b" )  # split on FIRST '=' only

    def test_get_present_dict_empty( self ):
        self.assertEqual(
            xm.ExpeditorResponse( all_required_met="true", args_present="  ", args_missing="" ).get_present_dict(),
            {},
        )

    def test_none_coercion( self ):
        r = xm.ExpeditorResponse( all_required_met="true", args_present=None, args_missing=None )
        self.assertEqual( r.args_present, "" )
        self.assertEqual( r.args_missing, "" )

    def test_get_example_for_template( self ):
        ex = xm.ExpeditorResponse.get_example_for_template()
        self.assertIn( "biodiversity", ex.args_present )
        self.assertEqual( ex.args_missing, "budget" )


# ============================================================================
# ArgConfirmationResponse
# ============================================================================

class TestArgConfirmationResponse( unittest.TestCase ):

    def test_is_approval_variants( self ):
        for word in ( "approve", "YES", "ok" ):
            self.assertTrue( xm.ArgConfirmationResponse( action=word, arg_name="", new_value="" ).is_approval() )
        self.assertFalse( xm.ArgConfirmationResponse( action="modify", arg_name="", new_value="" ).is_approval() )

    def test_is_cancel_variants( self ):
        for word in ( "cancel", "STOP", "quit" ):
            self.assertTrue( xm.ArgConfirmationResponse( action=word, arg_name="", new_value="" ).is_cancel() )
        self.assertFalse( xm.ArgConfirmationResponse( action="approve", arg_name="", new_value="" ).is_cancel() )

    def test_is_modify( self ):
        self.assertTrue( xm.ArgConfirmationResponse( action=" Modify ", arg_name="b", new_value="5" ).is_modify() )
        self.assertFalse( xm.ArgConfirmationResponse( action="approve", arg_name="", new_value="" ).is_modify() )

    def test_none_coercion( self ):
        r = xm.ArgConfirmationResponse( action="approve", arg_name=None, new_value=None )
        self.assertEqual( r.arg_name, "" )
        self.assertEqual( r.new_value, "" )

    def test_get_example_for_template( self ):
        ex = xm.ArgConfirmationResponse.get_example_for_template()
        self.assertEqual( ex.action, "modify" )
        self.assertEqual( ex.arg_name, "budget" )


if __name__ == "__main__":
    unittest.main()

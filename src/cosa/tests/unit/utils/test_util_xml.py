"""
Unit tests for cosa.utils.util_xml (DEPRECATED legacy XML helpers).

The module is deprecated but still in the coverage denominator. All functions
are pure string transforms; the per-call DeprecationWarnings are expected and
suppressed. Assertions harvested from the docstring examples and strengthened
with the not-found / no-match / markdown-rescue branches.
"""

import unittest
import warnings

from cosa.utils.util_xml import (
    get_value_by_xml_tag_name,
    get_xml_tag_and_value_by_name,
    get_nested_list,
    remove_xml_escapes,
    rescue_code_using_tick_tick_tick_syntax,
    strip_all_white_space,
)


class TestUtilXml( unittest.TestCase ):
    """Legacy XML extraction / formatting helpers."""

    def setUp( self ):
        # The module intentionally warns on every deprecated call; silence here.
        warnings.simplefilter( "ignore", DeprecationWarning )

    def test_get_value_found( self ):
        self.assertEqual( get_value_by_xml_tag_name( "<foo>bar</foo>", "foo" ), "bar" )

    def test_get_value_missing_returns_error_when_no_default( self ):
        out = get_value_by_xml_tag_name( "<a>x</a>", "foo" )
        self.assertIn( "not found", out )

    def test_get_value_missing_returns_default( self ):
        self.assertEqual(
            get_value_by_xml_tag_name( "<a>x</a>", "foo", default_value="fallback" ),
            "fallback",
        )

    def test_get_tag_and_value_wraps( self ):
        self.assertEqual(
            get_xml_tag_and_value_by_name( "<foo>bar</foo>", "foo" ), "<foo>bar</foo>"
        )

    def test_remove_xml_escapes( self ):
        self.assertEqual(
            remove_xml_escapes( "a &lt;b&gt; &amp; c" ), "a <b> & c"
        )

    def test_get_nested_list_extracts_lines( self ):
        xml = "<code>\n<line>print( 1 )</line>\n<line>print( 2 )</line>\n</code>"
        out = get_nested_list( xml, tag_name="code", debug=True, verbose=True )
        self.assertEqual( out, [ "print( 1 )", "print( 2 )" ] )

    def test_get_nested_list_skips_non_matching_lines( self ):
        xml = "<code>\n<line>only</line>\nnot a line tag\n</code>"
        out = get_nested_list( xml, tag_name="code", debug=True, verbose=True )
        self.assertEqual( out, [ "only" ] )

    def test_rescue_code_extracts_python_block( self ):
        raw = "```python\nx = 1\ny = 2\n```"
        out = rescue_code_using_tick_tick_tick_syntax( raw, debug=True )
        self.assertIn( "<line>x = 1</line>", out )
        self.assertIn( "<line>y = 2</line>", out )

    def test_rescue_code_block_non_debug( self ):
        # Valid block but debug=False -> the plain-print + non-debug return branches.
        out = rescue_code_using_tick_tick_tick_syntax( "```python\nx = 1\n```" )
        self.assertIn( "<line>x = 1</line>", out )

    def test_rescue_code_no_block_returns_empty( self ):
        self.assertEqual(
            rescue_code_using_tick_tick_tick_syntax( "no code here", debug=True ), ""
        )

    def test_rescue_code_no_block_non_debug( self ):
        self.assertEqual(
            rescue_code_using_tick_tick_tick_syntax( "plain text" ), ""
        )

    def test_strip_all_white_space( self ):
        self.assertEqual(
            strip_all_white_space( "<a> <b>text</b> </a>" ), "<a><b>text</b></a>"
        )


if __name__ == "__main__":
    unittest.main()

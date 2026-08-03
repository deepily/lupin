"""
The invariant that actually pins bug 652271f3.

WHY A SOURCE SCANNER AND NOT A UNIT TEST. `build_bounce_message` has accepted a
`server_label` keyword since it was written — it defaulted to ":7999" and was
correct in isolation. The defect lived one layer up: `src/lupin_app/main.py`
called it twice and passed the label neither time, so the TEST container
broadcast the DEV server's name to the whole fleet (io/commons/broadcasts.md:450
— "✅ :7999 is back up — boot #3", emitted by lupin-rest-test).

That means a test of the MODULE cannot catch this. A test asserting
`build_bounce_message( "warning", server_label=":8000" )` says ":8000" passes
just as happily against the broken tree. The thing worth pinning is that every
call site in `main.py` SUPPLIES the label — which is a property of the caller,
not the callee.

`main.py` sits outside `[tool.coverage.run] source = ["cosa"]`, so nothing there
is measured; a scanner over its source is how this invariant gets a gate at all.

THE CONTROL is `test_the_scanner_finds_an_unlabelled_call`, which runs the same
detector over the code as it was BEFORE the fix and requires it to fire. A
scanner that has never gone red is indistinguishable from one that cannot.
"""

import ast
import unittest

from pathlib import Path

import cosa.utils.util as cu


BUILDER = "build_bounce_message"


def unlabelled_call_lines( source: str ):
    """
    Line numbers of `build_bounce_message(...)` calls that omit `server_label`.

    Requires:
        - source is parseable Python

    Ensures:
        - returns a sorted list of 1-indexed line numbers
        - a call passing server_label by keyword is NOT reported
        - a call whose callee is named differently is NOT reported
    """
    tree    = ast.parse( source )
    offenders = []

    for node in ast.walk( tree ):
        if not isinstance( node, ast.Call ): continue

        name = node.func.attr if isinstance( node.func, ast.Attribute ) else getattr( node.func, "id", None )
        if name != BUILDER: continue

        if not any( kw.arg == "server_label" for kw in node.keywords ):
            offenders.append( node.lineno )

    return sorted( offenders )


class ManagedBounceServerLabelSeamTests( unittest.TestCase ):

    def _main_py( self ):
        return Path( cu.get_project_root() ) / "src/lupin_app/main.py"

    def test_every_call_site_in_main_supplies_the_server_label( self ):
        path   = self._main_py()
        source = path.read_text( encoding="utf-8" )

        # Guard against a silent pass if the call sites are ever moved out of
        # main.py — an empty search space would satisfy the assertion below
        # while proving nothing about where the calls actually live now.
        self.assertGreaterEqual(
            source.count( BUILDER ), 2,
            f"expected at least two {BUILDER} call sites in {path}; if they moved, move this gate with them"
        )

        self.assertEqual(
            unlabelled_call_lines( source ), [],
            f"{path} calls {BUILDER} without server_label — the test server will announce itself "
            "as the dev server to the whole fleet (bug 652271f3). Pass "
            "_managed_bounce_server_label() at every call site."
        )

    def test_the_scanner_finds_an_unlabelled_call( self ):
        """The control: the code as it was BEFORE the fix must be reported."""
        before = (
            "from cosa.rest.managed_bounce_broadcast import build_bounce_message\n"
            "_emit_managed_bounce( 'warning', build_bounce_message( 'warning' ) )\n"
        )

        self.assertEqual( unlabelled_call_lines( before ), [ 2 ] )

    def test_the_scanner_accepts_a_labelled_call( self ):
        after = (
            "build_bounce_message( 'warning', server_label=_managed_bounce_server_label() )\n"
        )

        self.assertEqual( unlabelled_call_lines( after ), [] )

    def test_the_scanner_ignores_a_different_callee( self ):
        # A near-miss name must not be swept in — the gate should fail for the
        # reason it claims, not because it matches too much.
        other = "build_bounce_message_v2( 'warning' )\nsomething.build_other_message( 'warning' )\n"

        self.assertEqual( unlabelled_call_lines( other ), [] )

    def test_the_scanner_sees_an_attribute_style_call( self ):
        # `mbb.build_bounce_message(...)` is the same defect wearing a module prefix.
        attr = "mbb.build_bounce_message( 'warning' )\n"

        self.assertEqual( unlabelled_call_lines( attr ), [ 1 ] )


if __name__ == "__main__":
    unittest.main()

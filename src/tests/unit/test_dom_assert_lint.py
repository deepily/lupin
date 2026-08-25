"""
The DOM-assert lint — row `f5768ee4`, the SOURCE half of the OOM hazard.

Row `32c58572` named the allocator: `node:assert` builds its failure diff by
deep-inspecting the ACTUAL value, and on a happy-dom element that walk reaches
the whole Window graph and never terminates. The containment half (the capped
lane, row `282d4c19`) stops a runaway from taking the box. This half stops the
runaway being written in the first place.

⚠️ THE RATCHET IS NOT A CAP ON COVERAGE. 276 known violations exist across 35
files as of 2026-08-24. They are recorded in `dom_assert_baseline.txt` and are
NOT silently tolerated: the count may only fall, lowering it requires editing
the baseline, and any file that gains a violation goes red. Burning down the 276
is separate work — the row says explicitly not to bulk-rewrite them blind,
because each is a real assertion whose intent has to survive the change.
"""
import collections
from pathlib import Path

import pytest

from tests.collected_count_guard import assert_every_declared_test_is_collected
from tests.dom_assert_lint import scan_text, scan_tree, DOM_TERMINAL

import os
ROOT     = Path( os.environ[ "LUPIN_ROOT" ] )
TESTS    = ROOT / "src" / "tests"
BASELINE = ROOT / "src" / "tests" / "dom_assert_baseline.txt"


def _rel( path ):
    """Repo-relative path — the baseline is stored relative so it is diffable and
    machine-independent, while scan_tree returns whatever root it was given."""
    return os.path.relpath( os.path.realpath( str( path ) ), str( ROOT ) )


def _current_counts():
    return collections.Counter( _rel( v.path ) for v in scan_tree( TESTS ) )


def _baseline():
    counts = {}
    for line in BASELINE.read_text( encoding="utf-8" ).splitlines():
        line = line.strip()
        if not line or line.startswith( "#" ): continue
        path, _, n = line.rpartition( " " )
        counts[ path.strip() ] = int( n )
    return counts


# ══════════════════════════════════════════════════════════════════════════════
# 1. The rule itself — what it flags and, more importantly, what it does not
# ══════════════════════════════════════════════════════════════════════════════

class TestTheRule:

    @pytest.mark.parametrize( "src", [
        'assert.equal( root.querySelector(".x"), null );',
        'assert.strictEqual( document.getElementById("a"), null );',
        'assert.deepEqual( el.firstChild, null );',
        'assert.equal( container.children[0], undefined );',
        'assert.equal( el.parentElement, null );',
    ] )
    def test_it_FLAGS_a_dom_node_as_the_actual_value( self, src ):
        assert scan_text( src ), "should have flagged: %s" % src

    @pytest.mark.parametrize( "src", [
        # Primitive PROJECTIONS — the correct form, and the whole point of the
        # rule is that these stay legal. A lint that banned querySelector
        # outright would be obeyed by deleting the assertions.
        'assert.equal( root.querySelector(".x").textContent, "hi" );',
        'assert.equal( root.querySelectorAll(".x").length, 3 );',
        'assert.equal( document.getElementById("a")?.id, "a" );',
        'assert.equal( el.firstChild.nodeName, "DIV" );',
        'assert.equal( container.children.length, 2 );',
        # Not a DOM `.body` — a captured fetch call's payload. The first draft of
        # this rule flagged 20 of these before `.body` was narrowed to
        # `document.body`.
        'assert.equal( calls[0]?.body, "{}" );',
        'assert.deepEqual( ctx.calls[0]!.body, {} );',
    ] )
    def test_it_does_NOT_flag_a_primitive_projection( self, src ):
        assert not scan_text( src ), "false positive on: %s" % src

    def test_a_nested_call_argument_does_not_confuse_the_scanner( self ):
        # The comma inside the selector must not terminate the first argument.
        src = 'assert.equal( root.querySelector(".a, .b"), null );'
        assert scan_text( src )

    def test_the_terminal_rule_is_what_distinguishes_them( self ):
        # Same call, one character of projection apart.
        assert     scan_text( 'assert.equal( q.querySelector("x"), null );' )
        assert not scan_text( 'assert.equal( q.querySelector("x").id, null );' )


# ══════════════════════════════════════════════════════════════════════════════
# 2. The ratchet
# ══════════════════════════════════════════════════════════════════════════════

class TestTheRatchet:

    def test_no_file_has_MORE_violations_than_its_baseline( self ):
        current  = _current_counts()
        baseline = _baseline()
        risen = { p: ( n, baseline.get( p, 0 ) ) for p, n in current.items()
                  if n > baseline.get( p, 0 ) }
        assert not risen, (
            "🔴 NEW `assert.<equal>(<DOM node>, ...)` — a FAILING one of these deep-inspects the "
            "happy-dom Window graph at ~2.5 GB/s until the kernel intervenes (rows f5768ee4 / "
            "32c58572).\n"
            "  file: (now, baseline)\n  %s\n"
            "Assert a PRIMITIVE PROJECTION instead — .textContent, .id, .tagName, a count, a boolean."
            % risen
        )

    def test_the_baseline_does_not_list_files_that_are_already_clean( self ):
        # A stale baseline entry is a ratchet that has quietly stopped ratcheting:
        # it leaves room for a violation to be re-added for free.
        current  = _current_counts()
        baseline = _baseline()
        stale = { p: n for p, n in baseline.items() if current.get( p, 0 ) < n }
        assert not stale, (
            "Baseline entries are now over-stated — the violations were fixed but the baseline "
            "was not lowered, so each leaves free room for a regression:\n  %s\n"
            "Lower these to the current counts." % stale
        )

    def test_the_baseline_file_explains_that_it_may_only_shrink( self ):
        text = BASELINE.read_text( encoding="utf-8" )
        assert "RATCHET" in text and "may only fall" in text


# ══════════════════════════════════════════════════════════════════════════════
# 3. The falsifier the row demands
# ══════════════════════════════════════════════════════════════════════════════

class TestTheFalsifier:

    def test_a_deliberate_violation_in_a_real_file_IS_caught( self, tmp_path ):
        """
        Row f5768ee4: "re-add a deliberate assert.equal(<happy-dom element>, null)
        and confirm the check goes RED. A lint that cannot be made to fire is a
        lint that is not running."
        """
        f = tmp_path / "planted.test.ts"
        f.write_text(
            'import assert from "node:assert/strict";\n'
            'test("x", () => {\n'
            '  assert.equal( document.body.querySelector(".boom"), null );\n'
            '});\n',
            encoding="utf-8",
        )
        found = scan_tree( tmp_path )
        assert len( found ) == 1, "the planted violation was not caught: %r" % ( found, )
        assert found[ 0 ].line == 3

    def test_the_scanner_returns_NOTHING_on_a_clean_file( self ):
        # The other half of the falsifier: a scanner that flags everything would
        # also pass the test above.
        f = 'assert.equal( root.querySelector(".x").textContent, "hi" );'
        assert scan_text( f ) == []


# ══════════════════════════════════════════════════════════════════════════════
# 4. The rule reaches the author BEFORE the test is written — row f5768ee4 item 3
# ══════════════════════════════════════════════════════════════════════════════
#
# The lint fires AFTER a violation is written and only when the Python tier runs.
# Item 3 asks for the rule where a person hits it while AUTHORING. That surface is
# src/tests/README.md — which, until row f5768ee4, did not mention the TypeScript
# tier at all: 119 *.test.ts files and no line in the testing document about them.
#
# A doc is not an installed control, so it is guarded here. Delete the section and
# the Python unit tier goes red — the same ratchet logic applied to the prose.

README = ROOT / "src" / "tests" / "README.md"


class TestTheRuleIsWhereTheAuthorWillSeeIt:

    def test_the_testing_readme_documents_the_typescript_tier_at_all( self ):
        text = README.read_text( encoding="utf-8" )
        assert "*.test.ts" in text, (
            "src/tests/README.md does not mention the TypeScript tier. 119 .test.ts files "
            "exist under src/tests/unit/ — a person writing one has nothing to read."
        )

    def test_the_testing_readme_states_the_rule_and_its_mechanism( self ):
        text = README.read_text( encoding="utf-8" )
        missing = [ phrase for phrase in (
            "Never pass a DOM node as the ACTUAL value",   # the rule
            "primitive",                                   # what to do instead
            "deep-inspects",                               # WHY — the allocator
            "dom_assert_lint.py",                          # where enforcement lives
        ) if phrase not in text ]
        assert not missing, (
            "The authoring surface lost part of the rule — a reader now gets an instruction "
            "without the mechanism, which is the shape that gets ignored: %s" % missing
        )

    def test_the_readme_warns_that_the_tier_is_banned( self ):
        # The ban holds by FILENAME only; a new runner globbing these paths re-arms
        # the hazard silently. An author who does not know that will write one.
        text = README.read_text( encoding="utf-8" )
        assert "node --test" in text and "92e94cb7" in text

    def test_the_guard_can_be_made_to_FIRE( self ):
        # Falsifier. A doc guard that cannot go red is a doc guard that is not running —
        # the exact defect class row f5768ee4 exists to stop.
        text = README.read_text( encoding="utf-8" )
        mutated = text.replace( "Never pass a DOM node as the ACTUAL value", "" )
        assert mutated != text, "mutation was a no-op — the guard is asserting nothing"
        assert "Never pass a DOM node as the ACTUAL value" not in mutated


def test_every_test_this_file_declares_is_actually_collected( request ):
    assert_every_declared_test_is_collected( request, __file__ )

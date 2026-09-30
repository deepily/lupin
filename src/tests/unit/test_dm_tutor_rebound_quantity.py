"""
The condenser re-bound a NUMBER and turned a green run into a red one — row `de03a059`.

THE SPECIMEN, and it is real rather than synthetic. On 2026-08-29 a DM reporting a clean
test run reached its reader as a ratio implying two failures:

    sent       "… neither of which builds the venv those 21 tests need. … 19 passed."
    delivered  "… and 19 out of 21 tests passed."

Nothing failed. The file was `19 passed in 0.15s` at commit `f65ffae8`, re-run by both
sender and reader.

🔴 THE ROW THAT FILED THIS SAID "There is no 21." THAT IS WRONG, AND THE CORRECTION IS THE
WHOLE POINT OF THIS FILE. `21` WAS in the sent text — bound to a completely different
subject, the 21 venv-dependent tests that skip without a `.venv`. The condenser invented no
numeral at all. It moved one: out of a sentence about which tests need a virtual environment,
into a denominator under "passed".

That distinction decides where the fix belongs, so it is asserted here rather than argued:

  · `literal_violations` is SILENT, and correctly so. It flags literals appearing MORE often
    than sent, or never sent at all. Here `19` and `21` each appear exactly once on both
    sides. Every count is preserved. Nothing was added and nothing multiplied — so this is
    not a coverage gap in that guard, and widening it to notice ratios would be aiming at
    the wrong property.

  · `attribution_violations` is also silent, because it models NAMES bound to speech acts.

This is the numeric twin of the defect `attribution_violations` already exists for. Its own
docstring describes the shape exactly: "María WAS in the original — as the addressee. The
condenser did not invent a token, it invented a RELATIONSHIP … So `literal_violations`
passes it cleanly; only the binding is new." Swap the name for a number and that is this
specimen. The missing guard is a QUANTITY-BINDING guard, sibling to the attribution one —
not a ratio detector, and not a widening of the literal counter.

⚠️ WHAT THIS FILE DOES NOT DO: it does not fix the defect. There is no quantity-binding
guard yet, and adding a new gate that can REJECT real messages is a call for the manager and
Rick, not something to slip in under a regression test. These tests pin the specimen and pin
which guards are blind to it, so that when a guard is built there is a real case to build it
against, and so the "there is no 21" reading cannot come back.

⚠️ PROVENANCE, stated because the two halves are not equally sourced. The SENT text below is
verbatim — the sender holds it. The DELIVERED text is quoted from row `de03a059`, recorded by
the reader; it was not observed directly by the author of this file.

Venue :7999 — pure string comparison, no subprocess, no network, no state.

See: row de03a059 · siblings cf1587cd (dropped subject), f3d96537 (fabricated filename),
     897a8db1 (the attribution specimen this one rhymes with)
"""

import pytest

from cosa.agents.dm_tutor.tutor import attribution_violations, literal_violations


# Verbatim, from the sender's own dm_send call (message 2d438759). Trimmed to the two
# sentences that carry the numerals; the elision changes no count of `19` or `21`.
SENT = (
    "My replacement said \"this repo has NO requirements.txt\", which is true of the root and "
    "would send anyone who goes looking straight into requirements-test.txt or "
    "src/cosa/requirements.txt, neither of which builds the venv those 21 tests need. "
    "String only, no logic. 19 passed."
)

# As recorded by the reader in row de03a059. NOT observed by this file's author.
DELIVERED = "The three files named caught a second defect, and 19 out of 21 tests passed."


class TestTheNumeralWasNotInvented:

    def test_21_was_in_the_sent_text( self ):
        """
        THE CORRECTION. The row states "There is no 21". There is: the sender wrote it about
        the 21 venv-dependent tests. Everything else here follows from this being a MOVE and
        not a fabrication, so it is asserted first and on its own.
        """

        assert "21" in SENT, (
            "the premise of this whole file is that 21 WAS sent. If this ever fails, the "
            "specimen has been edited and the analysis on row de03a059 must be re-derived."
        )

    def test_the_sent_21_is_bound_to_something_other_than_a_pass_count( self ):
        """It is the count of tests that NEED A VENV, not a denominator of a test run. The
        binding is the thing that changed; the token never did."""

        carrier = next( s for s in SENT.split( ". " ) if "21" in s )

        assert "venv" in carrier
        assert "passed" not in carrier

    def test_both_numerals_survive_unchanged_in_count( self ):
        """Neither numeral was added, dropped or multiplied — which is exactly why a
        count-based guard cannot see this."""

        for numeral in ( "19", "21" ):
            assert SENT.count( numeral ) == 1
            assert DELIVERED.count( numeral ) == 1


class TestWhichGuardsAreBlindToIt:

    def test_literal_violations_is_silent_and_is_right_to_be( self ):
        """
        Not a bug in this guard. It exists to catch literals that appear MORE often than sent
        or were never sent; here every count is preserved. Widening it to notice ratios would
        aim at the wrong property and would fire on honest rewrites that happen to contain a
        slash or the word "of".
        """

        assert literal_violations( SENT, DELIVERED ) == []

    def test_attribution_violations_is_silent_because_it_models_names( self ):
        """The right-shaped guard, wrong domain: it binds NAMES to speech acts. This
        specimen binds a NUMBER to a result."""

        assert attribution_violations( SENT, DELIVERED ) == []

    @pytest.mark.xfail(
        reason="row de03a059: no quantity-binding guard exists yet. Building a new gate that "
               "can REJECT real messages is the manager's and Rick's call, not something to "
               "add under a regression test. This xfail is the placeholder that goes GREEN "
               "the day such a guard lands — at which point wire it in here and delete the mark.",
        strict=True,
    )
    def test_some_guard_rejects_a_ratio_the_original_never_contained( self ):
        """
        The case a future quantity-binding guard must pass. Written as a STRICT xfail so it
        fails loudly the moment it starts passing — a placeholder that silently turned green
        would be its own small version of this row's defect.
        """

        violations = literal_violations( SENT, DELIVERED ) + attribution_violations( SENT, DELIVERED )

        assert violations, "no guard rejected a fabricated pass/total ratio"

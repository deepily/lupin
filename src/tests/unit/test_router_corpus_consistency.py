"""
Corpus consistency gate for the router training data.

Two directions, both green today:

    no line in the MATH corpus asks for something CalculatorAgent implements
    no line in the CALCULATOR corpus is symbolic work the calculator has no operation for

Green here means the training set already agrees with the capability rule ruled on
2026-08-21, so no lines needed to move. The gate exists so that a future edit that
disagrees with the rule fails a test instead of reaching a training run.

A third check holds the line on duplicates: per-file duplicate-group counts must not
increase. Zero duplicates is not the bar -- the corpus already carries some -- so the
bar is that a change adds none.
"""

import os
import re
import sys
import glob
import collections
import importlib.util

import pytest

_ROOT = os.environ.get( "LUPIN_ROOT" )
if _ROOT is None: raise RuntimeError( "LUPIN_ROOT not set" )

# Resolved from this file's own location for the same reason the corpus paths below
# are: the gate must exercise THIS checkout's tool against THIS checkout's corpus.
_TEST_TREE = os.path.realpath( os.path.join( os.path.dirname( os.path.abspath( __file__ ) ), "..", "..", ".." ) )

_SCRIPT = os.path.join( _TEST_TREE, "src", "scripts", "router_label_audit.py" )
_spec   = importlib.util.spec_from_file_location( "router_label_audit_guard", _SCRIPT )
rla     = importlib.util.module_from_spec( _spec )
sys.modules[ "router_label_audit_guard" ] = rla
_spec.loader.exec_module( rla )

# The corpus this gate guards is the one in the checkout the TEST FILE lives in --
# not whatever LUPIN_ROOT happens to point at. Resolving it from the environment
# lets a run in worktree A silently guard worktree B's corpus: you edit one file,
# the gate reads another, and it reports green about a file you never touched.
# This is the one place `__file__` is the right authority rather than the banned
# path-fishing pattern, because "which tree does this test belong to" is exactly
# the question being asked. LUPIN_ROOT is still checked -- against this, loudly.
MATH_CORPUS = os.path.join( _TEST_TREE, rla.MATH_FILE )
CALC_CORPUS = os.path.join( _TEST_TREE, rla.CALC_FILE )

# Measured 2026-08-21 on wt-router-label-fix. A file may appear here with a count;
# it may never appear with a HIGHER count.
DUP_GROUP_BASELINE = {
    "synthetic-data-agent-routing-calculator.txt"                 : 15,
    "synthetic-data-agent-routing-deep-research.txt"              :  1,
    "synthetic-data-agent-routing-math.txt"                       :  1,
    "synthetic-data-agent-routing-presentation-generator.txt"     :  2,
    "synthetic-data-agent-routing-receptionist.txt"               :  1,
    "synthetic-data-agent-routing-test-suite.txt"                 :  3,
    "synthetic-data-agent-routing-todo-lists.txt"                 : 24,
    "synthetic-data-agent-search-static-vs-dynamic.txt"           :  3,
    "synthetic-data-load-url-current-tab.txt"                     : 22,
    "synthetic-data-search-clipboard-GENERIC-current-tab.txt"     :  2,
    "synthetic-data-search-clipboard-google-in-current-tab.txt"   :  2,
    "synthetic-data-search-clipboard-google-scholar-in-current-tab.txt" : 2,
    "synthetic-data-search-clipboard-in-current-tab.txt"          :  1,
    "synthetic-data-search-clipboard-kagi-in-current-tab.txt"     :  1,
    "synthetic-data-search-clipboard-perplexity-in-current-tab.txt" : 1,
    "synthetic-data-search-google-in-current-tab.txt"             : 36,
    "synthetic-data-search-google-in-new-tab.txt"                 :  7,
    "synthetic-data-search-google-scholar-in-new-tab.txt"         :  3,
    "synthetic-data-search-kagi-in-current-tab.txt"               : 16,
    "synthetic-data-search-kagi-in-new-tab.txt"                   :  5,
}


def _dup_groups( path ):
    """
    Count duplicate GROUPS in a corpus file.

    Requires:
        - path names a readable corpus file

    Ensures:
        - returns the number of normalized utterances appearing more than once
          (a line repeated three times is one group, not two)
    """
    lines  = [ raw for _n, raw in rla.read_utterances( path ) ]
    counts = collections.Counter( rla._norm( raw ) for raw in lines )
    return sum( 1 for _key, count in counts.items() if count > 1 )


class TestTheGateGuardsItsOwnCheckout:

    def test_the_corpus_files_the_gate_reads_exist_in_this_tree( self ):
        assert os.path.isfile( MATH_CORPUS ), MATH_CORPUS
        assert os.path.isfile( CALC_CORPUS ), CALC_CORPUS

    def test_lupin_root_points_at_the_tree_this_test_lives_in( self ):
        # A mismatch means the run is configured to guard a different checkout's corpus.
        # Fail loudly rather than report green about a file nobody edited.
        assert os.path.realpath( _ROOT ) == _TEST_TREE, (
            f"LUPIN_ROOT is {os.path.realpath( _ROOT )} but this test file lives in {_TEST_TREE}; "
            f"the gate would guard the wrong checkout's corpus" )

    def test_the_gate_reads_the_bytes_on_disk_not_a_cached_copy( self, tmp_path ):
        # Edit-then-read round trip on a real file, proving read_utterances() is not
        # holding a snapshot from import time.
        probe = tmp_path / "probe.txt"
        probe.write_text( "How do you solve the equation 3x + 7 = 22?\n", encoding="utf-8" )
        assert len( rla.read_utterances( str( probe ) ) ) == 1
        probe.write_text( "How do you solve the equation 3x + 7 = 22?\nWhat is 2 plus 2?\n", encoding="utf-8" )
        assert len( rla.read_utterances( str( probe ) ) ) == 2


class TestMathCorpusHoldsNoCalculatorWork:

    def test_no_math_line_asks_for_a_calculator_operation( self ):
        offenders = [ ( n, raw.strip() ) for n, raw in rla.read_utterances( MATH_CORPUS )
                      if rla.is_calculator_shaped( raw ) ]
        assert offenders == [], (
            f"{len( offenders )} math-corpus line(s) ask for convert/compare_prices/mortgage; "
            f"move them to the calculator corpus: {offenders[ :5 ]}" )

    def test_the_gate_goes_red_when_a_calculator_line_is_planted( self, tmp_path ):
        # Asserted as a DELTA, not an absolute count. An absolute "== 1" fails for the
        # wrong reason on a corpus that already holds an offender -- which is exactly
        # the state a reviewer creates while poisoning the corpus to check the gate.
        # A prove-red test must test the GATE, never re-test the corpus.
        original = open( MATH_CORPUS, encoding="utf-8" ).read()
        before   = { n for n, raw in rla.read_utterances( MATH_CORPUS )
                     if rla.is_calculator_shaped( raw ) }

        planted = tmp_path / "math_with_a_bad_line.txt"
        planted.write_text( original + "How many miles is 10 kilometers?\n", encoding="utf-8" )

        new_offenders = [ raw.strip() for n, raw in rla.read_utterances( str( planted ) )
                          if rla.is_calculator_shaped( raw ) and n not in before ]

        assert new_offenders == [ "How many miles is 10 kilometers?" ], (
            f"gate should catch the plant and nothing else; caught {new_offenders}" )

        # And the real corpus is untouched by the plant.
        assert open( MATH_CORPUS, encoding="utf-8" ).read() == original


class TestCalculatorCorpusHoldsNoSymbolicWork:

    def test_no_calculator_line_is_symbolic( self ):
        offenders = [ ( n, raw.strip() ) for n, raw in rla.read_utterances( CALC_CORPUS )
                      if rla.is_math_shaped( raw ) ]
        assert offenders == [], (
            f"{len( offenders )} calculator-corpus line(s) are symbolic work the calculator "
            f"has no operation for; move them to the math corpus: {offenders[ :5 ]}" )

    def test_the_gate_goes_red_when_a_math_line_is_planted( self, tmp_path ):
        # Delta, not absolute count -- same reason as the mirror test above.
        original = open( CALC_CORPUS, encoding="utf-8" ).read()
        before   = { n for n, raw in rla.read_utterances( CALC_CORPUS )
                     if rla.is_math_shaped( raw ) }

        planted = tmp_path / "calc_with_a_bad_line.txt"
        planted.write_text( original + "How do you solve the equation 3x + 7 = 22?\n", encoding="utf-8" )

        new_offenders = [ raw.strip() for n, raw in rla.read_utterances( str( planted ) )
                          if rla.is_math_shaped( raw ) and n not in before ]

        assert new_offenders == [ "How do you solve the equation 3x + 7 = 22?" ], (
            f"gate should catch the plant and nothing else; caught {new_offenders}" )
        assert open( CALC_CORPUS, encoding="utf-8" ).read() == original


class TestTheProveRedTestsSurviveAPoisonedCorpus:
    """
    The prove-red tests must exercise the GATE, not the corpus. When the corpus
    already holds offenders -- the state a reviewer creates while poisoning it to
    check the gate -- the plant must still register as the one NEW offender. These
    build an already-poisoned corpus, then plant on top of it.
    """

    def test_a_plant_on_an_already_poisoned_math_corpus_is_still_the_only_new_offender( self, tmp_path ):
        poisoned = tmp_path / "already_poisoned_math.txt"
        poisoned.write_text( "How do you solve the equation 3x + 7 = 22?\n"
                             "Convert 180 centimeters to feet\n",          # pre-existing offender
                             encoding="utf-8" )
        before = { n for n, raw in rla.read_utterances( str( poisoned ) )
                   if rla.is_calculator_shaped( raw ) }
        assert len( before ) == 1

        planted = tmp_path / "planted_math.txt"
        planted.write_text( poisoned.read_text( encoding="utf-8" ) +
                            "How many miles is 10 kilometers?\n", encoding="utf-8" )
        new_offenders = [ raw.strip() for n, raw in rla.read_utterances( str( planted ) )
                          if rla.is_calculator_shaped( raw ) and n not in before ]

        assert new_offenders == [ "How many miles is 10 kilometers?" ]

    def test_a_plant_on_an_already_poisoned_calculator_corpus_is_still_the_only_new_offender( self, tmp_path ):
        poisoned = tmp_path / "already_poisoned_calc.txt"
        poisoned.write_text( "Convert 180 centimeters to feet\n"
                             "What's the derivative of f(x) = 3x squared + 4x?\n",   # pre-existing offender
                             encoding="utf-8" )
        before = { n for n, raw in rla.read_utterances( str( poisoned ) )
                   if rla.is_math_shaped( raw ) }
        assert len( before ) == 1

        planted = tmp_path / "planted_calc.txt"
        planted.write_text( poisoned.read_text( encoding="utf-8" ) +
                            "How do you solve the equation 3x + 7 = 22?\n", encoding="utf-8" )
        new_offenders = [ raw.strip() for n, raw in rla.read_utterances( str( planted ) )
                          if rla.is_math_shaped( raw ) and n not in before ]

        assert new_offenders == [ "How do you solve the equation 3x + 7 = 22?" ]


class TestGuardPrimitives:

    @pytest.mark.parametrize( "utterance", [
        "How many miles is 10 kilometers?",
        "Convert 180 centimeters to feet",
        "What's the monthly payment on a $300,000 mortgage at 6.5% over 30 years?",
        "Which is cheaper, 12 ounces at $3.49 or 24 ounces at $5.99?",
        "Take me to the price comparison tool",
    ] )
    def test_calculator_shapes_are_recognized( self, utterance ):
        assert rla.is_calculator_shaped( utterance ) is True

    @pytest.mark.parametrize( "utterance", [
        "What is 253 plus 147?",
        "How do you solve the equation 3x + 7 = 22?",
        "If a car travels at a speed of 60 miles per hour for 2.5 hours, how far does it travel?",
    ] )
    def test_math_work_is_not_mistaken_for_a_calculator_operation( self, utterance ):
        assert rla.is_calculator_shaped( utterance ) is False

    @pytest.mark.parametrize( "utterance", [
        "How do you solve the equation 3x + 7 = 22?",
        "What's the derivative of f(x) = 3x squared + 4x?",
        "What is the area of a circle with a radius of 6?",
        "Can you explain how to use the Pythagorean theorem to find the hypotenuse?",
    ] )
    def test_symbolic_shapes_are_recognized( self, utterance ):
        assert rla.is_math_shaped( utterance ) is True

    @pytest.mark.parametrize( "utterance", [
        "How many miles is 10 kilometers?",
        "What's the monthly payment on a $300,000 mortgage at 6.5% over 30 years?",
    ] )
    def test_calculator_work_is_not_mistaken_for_symbolic( self, utterance ):
        assert rla.is_math_shaped( utterance ) is False

    def test_ambiguous_word_alone_is_not_a_unit( self ):
        # "in" is a preposition and "c" a coefficient; neither makes this a conversion.
        assert rla.guard_unit_tokens( "solving in the form a x squared plus b x plus c" ) == set()

    @pytest.mark.parametrize( "utterance,expected", [
        ( "Convert 2 liters to fluid ounces",  { "liter", "fl_oz" } ),
        ( "How many fluid ounces in a cup?",   { "fl_oz", "cup" } ),
        ( "What's 100 ml in fluid ounces?",    { "ml", "fl_oz" } ),
    ] )
    def test_multi_word_unit_names_resolve_to_the_right_category( self, utterance, expected ):
        # "fluid ounces" is fl_oz, a VOLUME unit. A single-token scan reads "ounces"
        # as the MASS unit and the conversion looks cross-category, which it is not.
        assert rla.guard_unit_tokens( utterance ) == expected

    def test_a_multi_word_name_with_no_category_is_not_counted( self ):
        # "fl oz" resolves; a phrase that resolves to nothing in the tables must not.
        assert "tablespoon" not in rla.guard_unit_tokens( "How many tablespoons in a cup?" )

    def test_singular_and_plural_unit_names_both_resolve( self ):
        assert rla.guard_unit_tokens( "How many meters are in a kilometer?" ) == { "meter", "km" }


class TestDuplicateGroupsDoNotGrow:

    def test_no_corpus_file_gained_a_duplicate_group( self ):
        pattern = os.path.join( _ROOT, "src", "ephemera", "prompts", "data", "synthetic-data-*.txt" )
        grown   = []
        for path in sorted( glob.glob( pattern ) ):
            name    = os.path.basename( path )
            groups  = _dup_groups( path )
            allowed = DUP_GROUP_BASELINE.get( name, 0 )
            if groups > allowed: grown.append( ( name, allowed, groups ) )
        assert grown == [], f"duplicate groups increased (file, baseline, now): {grown}"

    def test_the_baseline_is_a_ceiling_not_a_target( self ):
        # A file that loses duplicates must not fail; only growth is a failure.
        counts = { os.path.basename( p ): _dup_groups( p )
                   for p in glob.glob( os.path.join( _ROOT, "src", "ephemera", "prompts", "data",
                                                     "synthetic-data-agent-routing-math.txt" ) ) }
        assert counts[ "synthetic-data-agent-routing-math.txt" ] <= DUP_GROUP_BASELINE[ "synthetic-data-agent-routing-math.txt" ]

    def test_a_repeated_line_counts_as_one_group( self, tmp_path ):
        p = tmp_path / "corpus.txt"
        p.write_text( "same line\nsame line\nsame line\nother\n", encoding="utf-8" )
        assert _dup_groups( str( p ) ) == 1

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

_SCRIPT = os.path.join( _ROOT, "src", "scripts", "router_label_audit.py" )
_spec   = importlib.util.spec_from_file_location( "router_label_audit_guard", _SCRIPT )
rla     = importlib.util.module_from_spec( _spec )
sys.modules[ "router_label_audit_guard" ] = rla
_spec.loader.exec_module( rla )

MATH_CORPUS = os.path.join( _ROOT, rla.MATH_FILE )
CALC_CORPUS = os.path.join( _ROOT, rla.CALC_FILE )

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


class TestMathCorpusHoldsNoCalculatorWork:

    def test_no_math_line_asks_for_a_calculator_operation( self ):
        offenders = [ ( n, raw.strip() ) for n, raw in rla.read_utterances( MATH_CORPUS )
                      if rla.is_calculator_shaped( raw ) ]
        assert offenders == [], (
            f"{len( offenders )} math-corpus line(s) ask for convert/compare_prices/mortgage; "
            f"move them to the calculator corpus: {offenders[ :5 ]}" )

    def test_the_gate_goes_red_when_a_calculator_line_is_planted( self, tmp_path ):
        planted = tmp_path / "math_with_a_bad_line.txt"
        original = open( MATH_CORPUS, encoding="utf-8" ).read()
        planted.write_text( original + "How many miles is 10 kilometers?\n", encoding="utf-8" )

        offenders = [ n for n, raw in rla.read_utterances( str( planted ) )
                      if rla.is_calculator_shaped( raw ) ]
        assert len( offenders ) == 1

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
        planted = tmp_path / "calc_with_a_bad_line.txt"
        original = open( CALC_CORPUS, encoding="utf-8" ).read()
        planted.write_text( original + "How do you solve the equation 3x + 7 = 22?\n", encoding="utf-8" )

        offenders = [ n for n, raw in rla.read_utterances( str( planted ) )
                      if rla.is_math_shaped( raw ) ]
        assert len( offenders ) == 1
        assert open( CALC_CORPUS, encoding="utf-8" ).read() == original


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

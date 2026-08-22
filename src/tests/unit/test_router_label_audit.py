"""
Unit tests for src/scripts/router_label_audit.py.

Covers the bucket classifier, both destination rules, the duplicate check,
and the cold-pass recount.
"""

import os
import sys
import json
import importlib.util

import pytest

_ROOT = os.environ.get( "LUPIN_ROOT" )
if _ROOT is None: raise RuntimeError( "LUPIN_ROOT not set" )

_SCRIPT = os.path.join( _ROOT, "src", "scripts", "router_label_audit.py" )
_spec   = importlib.util.spec_from_file_location( "router_label_audit", _SCRIPT )
rla     = importlib.util.module_from_spec( _spec )
sys.modules[ "router_label_audit" ] = rla
_spec.loader.exec_module( rla )


class TestClassifyBucket:

    @pytest.mark.parametrize( "utterance", [
        "What is 253 plus 147?",
        "How do you subtract 89 from 123?",
        "What is the product of 64 and 23?",
        "How many times does 12 go into 144?",
    ] )
    def test_bare_arithmetic_is_bucket_1( self, utterance ):
        assert rla.classify_bucket( utterance ) == "1-bare-arithmetic"

    @pytest.mark.parametrize( "utterance", [
        "How do you solve the equation 3x + 7 = 22?",
        "What is the area of a circle with a radius of 6?",
        "What's the derivative of f(x) = 3x squared + 4x?",
        "How do you find the sine of a 30-degree angle?",
    ] )
    def test_symbolic_is_bucket_2( self, utterance ):
        assert rla.classify_bucket( utterance ) == "2-symbolic"

    @pytest.mark.parametrize( "utterance", [
        "If I buy 3 apples at $1.20 each and 2 bananas at $0.75 each, how much will the total cost be?",
        "If 4 bags of flour cost $32, how much does 1 bag of flour cost?",
    ] )
    def test_scenario_is_bucket_3( self, utterance ):
        assert rla.classify_bucket( utterance ) == "3-word-problem"

    def test_routing_phrase_has_its_own_bucket( self ):
        assert rla.classify_bucket( "Open up the math agent for me" ) == "0-routing-phrase"

    def test_blank_line_raises( self ):
        with pytest.raises( ValueError ):
            rla.classify_bucket( "   " )


class TestCapabilityRule:

    def test_bare_arithmetic_stays_math( self ):
        label, _reason = rla.destination_capability( "What is 253 plus 147?" )
        assert label == rla.MATH_LABEL

    def test_same_category_conversion_goes_to_calculator( self ):
        label, reason = rla.destination_capability( "How many miles is 10 kilometers?" )
        assert label == rla.CALC_LABEL
        assert "convert" in reason

    def test_cross_category_units_are_not_a_conversion( self ):
        # convert() only works within one category; km-to-liters is a rate problem.
        label, _reason = rla.destination_capability(
            "A car travels 360 km using 24 liters of gasoline. How many kilometers can it travel with 60 liters?" )
        assert label == rla.MATH_LABEL

    def test_ambiguous_alias_does_not_manufacture_a_conversion( self ):
        # "in" is a preposition here, not inches; "c" is a coefficient, not celsius.
        label, _reason = rla.destination_capability(
            "What is the quadratic formula for solving an equation in the form a times x squared plus b times x plus c equals zero?" )
        assert label == rla.MATH_LABEL

    def test_mortgage_goes_to_calculator( self ):
        label, reason = rla.destination_capability( "What's the monthly payment on a $300,000 mortgage at 6.5% over 30 years?" )
        assert label == rla.CALC_LABEL
        assert "mortgage" in reason

    def test_price_comparison_goes_to_calculator( self ):
        label, reason = rla.destination_capability( "Which is cheaper, 12 ounces for $4 or 20 ounces for $6?" )
        assert label == rla.CALC_LABEL
        assert "compare_prices" in reason


class TestArithmeticRule:

    def test_bucket_1_moves_to_calculator( self ):
        label, reason = rla.destination_arithmetic( "What is 253 plus 147?" )
        assert label == rla.CALC_LABEL
        assert "bucket 1" in reason

    def test_bucket_2_stays_math( self ):
        label, _reason = rla.destination_arithmetic( "How do you solve the equation 3x + 7 = 22?" )
        assert label == rla.MATH_LABEL

    def test_bucket_3_four_operations_only_moves( self ):
        label, reason = rla.destination_arithmetic(
            "If I buy 3 apples at $1.20 each and 2 bananas at $0.75 each, how much will the total cost be?" )
        assert label == rla.CALC_LABEL
        assert "only +-*/" in reason

    @pytest.mark.parametrize( "utterance", [
        "If a car travels at a speed of 60 miles per hour for 2.5 hours, how far does it travel?",
        "A tank can be filled by a pipe in 5 hours, but it can be emptied by another pipe in 7 hours. If both pipes are opened, how long will it take to fill the tank?",
        "If a train travels at 80 km/h and covers 320 km, how long did the journey take?",
    ] )
    def test_bucket_3_rate_or_formula_stays_math( self, utterance ):
        label, _reason = rla.destination_arithmetic( utterance )
        assert label == rla.MATH_LABEL


class TestNormalizeAndDuplicates:

    def test_norm_folds_curly_quotes_and_whitespace( self ):
        assert rla._norm( "  What’s   the   sum?  " ) == "what's the sum?"

    def test_cross_file_duplicate_is_reported( self ):
        calc  = [ ( 1, "What is 253 plus 147?" ) ]
        cross, internal = rla.duplicate_check( [ "what is 253 PLUS 147?" ], calc )
        assert cross    == [ "what is 253 PLUS 147?" ]
        assert internal == []

    def test_internal_duplicate_is_reported( self ):
        cross, internal = rla.duplicate_check( [ "What is 2 plus 2?", "what is 2 plus 2?" ], [] )
        assert cross    == []
        assert len( internal ) == 1

    def test_clean_movers_report_nothing( self ):
        cross, internal = rla.duplicate_check( [ "What is 5 plus 5?" ], [ ( 1, "Convert 10 km to miles" ) ] )
        assert cross == [] and internal == []


class TestReadUtterances:

    def test_blanks_and_comments_are_skipped( self, tmp_path ):
        p = tmp_path / "corpus.txt"
        p.write_text( "# header\n\nWhat is 1 plus 1?\n\n# another\nWhat is 2 plus 2?\n", encoding="utf-8" )
        rows = rla.read_utterances( str( p ) )
        assert [ n for n, _raw in rows ] == [ 3, 6 ]


class TestRecountCold:

    def _records( self, tmp_path ):
        rows = [
            { "utterance": "What is 253 plus 147?", "pass_kind": "cold",
              "expected_command": rla.MATH_LABEL, "payload": { "command": rla.CALC_LABEL } },
            { "utterance": "How do you solve the equation 3x + 7 = 22?", "pass_kind": "cold",
              "expected_command": rla.MATH_LABEL, "payload": { "command": rla.MATH_LABEL } },
            { "utterance": "What is 253 plus 147?", "pass_kind": "warm",
              "expected_command": rla.MATH_LABEL, "payload": { "command": rla.CALC_LABEL } },
        ]
        p = tmp_path / "records.jsonl"
        p.write_text( "\n".join( json.dumps( r ) for r in rows ) + "\n", encoding="utf-8" )
        return str( p )

    def test_warm_rows_are_excluded( self, tmp_path ):
        stats = rla.recount_cold( self._records( tmp_path ), rla.destination_capability )
        assert stats[ "n" ] == 2

    def test_capability_rule_leaves_the_count_alone( self, tmp_path ):
        stats = rla.recount_cold( self._records( tmp_path ), rla.destination_capability )
        assert stats[ "correct_before" ] == 1
        assert stats[ "correct_after"  ] == 1
        assert stats[ "relabelled"     ] == 0

    def test_arithmetic_rule_relabels_and_lifts_the_count( self, tmp_path ):
        stats = rla.recount_cold( self._records( tmp_path ), rla.destination_arithmetic )
        assert stats[ "relabelled"    ] == 1
        assert stats[ "correct_after" ] == 2

    def test_router_output_is_reported_unchanged( self, tmp_path ):
        stats = rla.recount_cold( self._records( tmp_path ), rla.destination_arithmetic )
        assert stats[ "routed_by_router" ] == { rla.CALC_LABEL: 1, rla.MATH_LABEL: 1 }


class TestModuleBootstrap:

    def test_missing_lupin_root_raises_at_import( self, monkeypatch ):
        monkeypatch.delenv( "LUPIN_ROOT", raising=False )
        spec = importlib.util.spec_from_file_location( "router_label_audit_noroot", _SCRIPT )
        mod  = importlib.util.module_from_spec( spec )
        with pytest.raises( RuntimeError, match="LUPIN_ROOT not set" ):
            spec.loader.exec_module( mod )


class TestClassifierFallthrough:

    def test_numeral_without_operator_or_scenario_falls_through_to_symbolic( self ):
        assert rla.classify_bucket( "Round 3.14159 to two decimal places" ) == "2-symbolic"


class _Corpus:
    """Build a throwaway two-file corpus and point the module at it."""

    def __init__( self, tmp_path, monkeypatch, math_lines, calc_lines ):
        data = tmp_path / "src" / "ephemera" / "prompts" / "data"
        data.mkdir( parents=True )
        self.math_rel = "src/ephemera/prompts/data/math.txt"
        self.calc_rel = "src/ephemera/prompts/data/calc.txt"
        self.math_abs = tmp_path / self.math_rel
        self.calc_abs = tmp_path / self.calc_rel
        self.math_abs.write_text( math_lines, encoding="utf-8" )
        self.calc_abs.write_text( calc_lines, encoding="utf-8" )
        monkeypatch.setattr( rla, "lupin_root", str( tmp_path ) )
        monkeypatch.setattr( rla, "MATH_FILE",  self.math_rel )
        monkeypatch.setattr( rla, "CALC_FILE",  self.calc_rel )


class TestMain:

    def test_dry_run_prints_counts_and_does_not_touch_the_files( self, tmp_path, monkeypatch, capsys ):
        c = _Corpus( tmp_path, monkeypatch,
                     "# header\nWhat is 253 plus 147?\nHow do you solve the equation 3x + 7 = 22?\n",
                     "Convert 10 km to miles\n" )
        before = c.math_abs.read_text( encoding="utf-8" )
        monkeypatch.setattr( sys, "argv", [ "router_label_audit.py", "--rule", "arithmetic" ] )
        rla.main()
        out = capsys.readouterr().out
        assert "rule              : arithmetic" in out
        assert "proposed movers   : 1"          in out
        assert c.math_abs.read_text( encoding="utf-8" ) == before

    def test_audit_csv_is_written_with_one_row_per_utterance( self, tmp_path, monkeypatch ):
        _Corpus( tmp_path, monkeypatch,
                 "What is 253 plus 147?\nHow do you solve the equation 3x + 7 = 22?\n",
                 "Convert 10 km to miles\n" )
        csv_path = tmp_path / "audit.csv"
        monkeypatch.setattr( sys, "argv", [ "router_label_audit.py", "--rule", "capability",
                                            "--audit-csv", str( csv_path ) ] )
        rla.main()
        import csv as _csv
        rows = list( _csv.DictReader( open( csv_path, encoding="utf-8" ) ) )
        assert len( rows ) == 2
        assert rows[ 0 ][ "destination" ] == rla.MATH_LABEL

    def test_records_flag_prints_the_recount( self, tmp_path, monkeypatch, capsys ):
        _Corpus( tmp_path, monkeypatch, "What is 253 plus 147?\n", "Convert 10 km to miles\n" )
        rec = tmp_path / "records.jsonl"
        rec.write_text( json.dumps( { "utterance": "What is 253 plus 147?", "pass_kind": "cold",
                                      "expected_command": rla.MATH_LABEL,
                                      "payload": { "command": rla.CALC_LABEL } } ) + "\n", encoding="utf-8" )
        monkeypatch.setattr( sys, "argv", [ "router_label_audit.py", "--rule", "arithmetic",
                                            "--records", str( rec ) ] )
        rla.main()
        assert "cold recount" in capsys.readouterr().out

    def test_apply_moves_the_lines_and_keeps_the_headers( self, tmp_path, monkeypatch, capsys ):
        c = _Corpus( tmp_path, monkeypatch,
                     "# ALGEBRA\nWhat is 253 plus 147?\nHow do you solve the equation 3x + 7 = 22?\n",
                     "# CONVERSIONS\nConvert 10 km to miles\n" )
        monkeypatch.setattr( sys, "argv", [ "router_label_audit.py", "--rule", "arithmetic", "--apply" ] )
        rla.main()
        math_after = c.math_abs.read_text( encoding="utf-8" )
        calc_after = c.calc_abs.read_text( encoding="utf-8" )
        assert "# ALGEBRA"             in math_after
        assert "What is 253 plus 147?" not in math_after
        assert "3x + 7 = 22"           in math_after
        assert "What is 253 plus 147?" in calc_after
        assert "MOVED FROM MATH"       in calc_after
        assert "moved 1 lines"         in capsys.readouterr().out

    def test_apply_refuses_when_a_mover_already_exists_in_the_calculator_file( self, tmp_path, monkeypatch ):
        _Corpus( tmp_path, monkeypatch,
                 "What is 253 plus 147?\n",
                 "what is 253 plus 147?\n" )
        monkeypatch.setattr( sys, "argv", [ "router_label_audit.py", "--rule", "arithmetic", "--apply" ] )
        with pytest.raises( ValueError, match="refusing to apply" ):
            rla.main()

    def test_apply_with_nothing_to_move_is_a_no_op( self, tmp_path, monkeypatch, capsys ):
        c = _Corpus( tmp_path, monkeypatch,
                     "How do you solve the equation 3x + 7 = 22?\n",
                     "Convert 10 km to miles\n" )
        before = c.math_abs.read_text( encoding="utf-8" )
        monkeypatch.setattr( sys, "argv", [ "router_label_audit.py", "--rule", "capability", "--apply" ] )
        rla.main()
        assert "nothing to move" in capsys.readouterr().out
        assert c.math_abs.read_text( encoding="utf-8" ) == before

    def test_duplicate_lines_are_printed_in_the_dry_run( self, tmp_path, monkeypatch, capsys ):
        _Corpus( tmp_path, monkeypatch,
                 "What is 253 plus 147?\nWhat is 253 plus 147?\n",
                 "what is 253 plus 147?\n" )
        monkeypatch.setattr( sys, "argv", [ "router_label_audit.py", "--rule", "arithmetic" ] )
        rla.main()
        out = capsys.readouterr().out
        assert "DUP-CROSS"    in out
        assert "DUP-INTERNAL" in out

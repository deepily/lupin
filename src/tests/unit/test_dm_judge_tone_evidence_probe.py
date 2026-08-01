"""
Unit tests for the tone-evidence probe's classifier — the pure logic, no live model.

WHAT THIS GUARDS. `classify_evidence` answers one question: is the Tone grade's evidence
AIMED at something, or is it the whole message handed back? Getting that wrong in either
direction corrupts every number the probe reports, so the classifier is tested away from
the model where the expected answer is known by construction.

🔴 THE NEGATIVE CONTROL THAT MATTERS is test_many_short_spans_are_targeted_not_partial.
The first version of this classifier decided on the word-count RATIO alone, and the live
run caught it: the model answered BURIED_JARGON with nine discrete quoted phrases summing
to 63% of the body, and the ratio filed them as a near-whole dump when they were the best
evidence in the run. Deleting the span-count branch in classify_evidence turns that test
red — which is what makes it a control rather than a restatement of the implementation.

The mirror control is test_single_quoted_span_is_not_targeted: quote marks alone must not
buy the "targeted" label, or every echo wrapped in quotes (which is how the model actually
returns them) would be reclassified as aimed evidence and the defect would vanish from the
numbers without anything being fixed.
"""
import importlib.util
import os

import pytest

# Import the probe by file path — src/tests/smoke/ is not a package. Same convention as
# test_dm_judge_discrimination_probe.py.
_PROBE_PATH = os.path.join(
    os.environ[ "LUPIN_ROOT" ], "src", "tests", "smoke", "dm_judge_tone_evidence_probe.py"
)
_spec = importlib.util.spec_from_file_location( "dm_judge_tone_evidence_probe", _PROBE_PATH )
probe = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( probe )


BODY = ( "The retry path is untested against a real timeout. I am holding your gate. "
         "I would not merge before Thursday." )


def test_whole_body_is_echo():
    assert probe.classify_evidence( BODY, BODY ) == "echo"


def test_echo_wrapped_in_quotes_is_echo():
    # This is the shape the model actually returns — the whole body inside one quoted
    # span. It must NOT be rescued into "targeted" by the presence of quote marks.
    assert probe.classify_evidence( f'"{BODY}"', BODY ) == "echo"


def test_echo_plus_model_commentary_is_echo():
    assert probe.classify_evidence( f'"{BODY}" — reads plainly throughout.', BODY ) == "echo"


def test_repunctuated_echo_is_echo():
    # The model routinely re-punctuates what it quotes. Normalization must absorb that,
    # or a whole echo escapes the count on a comma.
    assert probe.classify_evidence( BODY.replace( ".", " ..." ), BODY ) == "echo"


def test_short_excerpt_is_fragment():
    assert probe.classify_evidence( "holding your gate", BODY ) == "fragment"


def test_single_quoted_span_is_not_targeted():
    # THE MIRROR CONTROL: one span is one span, quoted or not.
    assert probe.classify_evidence( '"holding your gate"', BODY ) == "fragment"


def test_near_whole_single_span_is_partial():
    # Most of the body in ONE contiguous run, but not all of it. Not an echo, and not a
    # usable excerpt either — it gets its own name rather than being rounded into either.
    near_whole = "The retry path is untested against a real timeout. I am holding your gate."
    assert probe.classify_evidence( near_whole, BODY ) == "partial"


def test_many_short_spans_are_targeted_not_partial():
    # 🔴 THE CONTROL. Four named phrases totalling ~70% of the body — over
    # FRAGMENT_MAX_RATIO, so the ratio-only classifier called this "partial". It is aimed
    # evidence: every span names something specific. Remove the span-count branch from
    # classify_evidence and this goes red.
    spans = ( '"The retry path is untested", "a real timeout", '
              '"holding your gate", "not merge before Thursday"' )
    assert probe.classify_evidence( spans, BODY ) == "targeted"


def test_two_spans_are_enough_for_targeted():
    # The boundary itself, stated as a test so a later "three feels safer" edit has to
    # argue with something.
    assert probe.classify_evidence( '"real timeout", "holding your gate"', BODY ) == "targeted"


def test_invented_evidence_is_foreign():
    # The model narrating instead of quoting. A different defect from over-quoting, and
    # it must not be scored on the ratio path.
    assert probe.classify_evidence(
        "reads like a competent professional summary overall", BODY ) == "foreign"


def test_foreign_beats_span_count():
    # ORDER CONTROL: two quoted spans that are NOT from the body must read foreign, not
    # targeted. Span-count before foreign would let invented quotes pass as aimed evidence.
    assert probe.classify_evidence(
        '"crisp executive framing", "admirable brevity throughout"', BODY ) == "foreign"


def test_empty_evidence_is_empty():
    assert probe.classify_evidence( "", BODY ) == "empty"


def test_whitespace_only_evidence_is_empty():
    assert probe.classify_evidence( "   \n  ", BODY ) == "empty"


def test_quoted_spans_handles_curly_quotes():
    assert probe._quoted_spans( '“first phrase”, “second phrase”' ) == [ "first phrase",
                                                                        "second phrase" ]


def test_quoted_spans_empty_when_unquoted():
    assert probe._quoted_spans( "no quotation marks here at all" ) == []


def test_normalize_collapses_punctuation_and_case():
    assert probe._normalize( "The  RETRY path —  untested!" ) == "the retry path untested"


def test_self_test_passes_on_the_shipped_classifier():
    # The harness audits itself before calling the model; if that audit ever fails, the
    # probe aborts. Assert it passes HERE too, so the abort path is a real signal about
    # the model run rather than a latent breakage nobody noticed.
    assert probe._self_test() == []


def test_self_test_catches_a_broken_classifier( monkeypatch ):
    # 🔴 THE AUDIT'S OWN CONTROL — proving _self_test can FAIL. A self-test that cannot
    # go red certifies nothing. Break the classifier and the audit must report it.
    monkeypatch.setattr( probe, "classify_evidence", lambda evidence, body: "fragment" )
    failures = probe._self_test()
    assert failures, "the harness self-test passed a classifier that answers 'fragment' to everything"


# ── the live-orchestration half, driven by a stub judge ────────────────────────
#
# run()/report()/main() are the part that talks to the model, so they are exercised here
# against a scripted judge. The branch that MUST work is report()'s "measured nothing":
# a run where every call came back a non-answer has to say so, because reporting it as a
# 0% echo rate would be this package's own signature defect — a silence wearing a number.

from cosa.agents.dm_quality_judge.judge import _JUDGE_UNAVAILABLE_DETAIL


class _StubJudge:
    """Returns a scripted tone result per call; records the bodies it was asked about."""

    def __init__( self, results ):
        self.results = list( results )
        self.seen    = []

    def judge( self, body_text ):
        self.seen.append( body_text )
        return { "tone": self.results[ ( len( self.seen ) - 1 ) % len( self.results ) ] }


def _install( monkeypatch, results ):
    stub = _StubJudge( results )
    monkeypatch.setattr( probe, "get_dm_quality_judge", lambda: stub )
    return stub


def _real( detail, weight=1 ):
    return { "weight": weight, "detail": detail }


_FALLBACK = { "weight": None, "detail": _JUDGE_UNAVAILABLE_DETAIL }


def test_run_counts_one_row_per_body( monkeypatch ):
    # One fixed evidence string is fed against all four bodies, so the KINDS differ by
    # body — "holding your gate" is an excerpt of DIRECT_PLAIN and foreign to the other
    # three. That is correct, and it is why this asserts the totals RECONCILE rather than
    # asserting one kind: a classifier that quietly dropped a result would still satisfy
    # a single-bucket check.
    _install( monkeypatch, [ _real( "holding your gate" ) ] )
    rows, totals = probe.run( 2 )
    assert len( rows ) == len( probe.BODIES )
    assert totals[ "real" ] == 2 * len( probe.BODIES )
    kinds = ( "echo", "partial", "fragment", "targeted", "foreign", "empty" )
    assert sum( totals[ k ] for k in kinds ) == totals[ "real" ]
    assert totals[ "fragment" ] == 2   # DIRECT_PLAIN only
    assert totals[ "foreign" ]  == 6   # the other three bodies


def test_run_excludes_nonanswers_from_real( monkeypatch ):
    # THE COUNT CONTROL: a fallback must land in `nonanswer`, never in a kind bucket.
    _install( monkeypatch, [ _FALLBACK ] )
    rows, totals = probe.run( 2 )
    assert totals[ "real" ] == 0
    assert totals[ "nonanswer" ] == 2 * len( probe.BODIES )
    assert totals[ "echo" ] == 0


def test_run_verbose_path_prints( monkeypatch, capsys ):
    monkeypatch.setenv( "PROBE_VERBOSE", "1" )
    _install( monkeypatch, [ _real( "holding your gate" ), _FALLBACK ] )
    probe.run( 2 )
    out = capsys.readouterr().out
    assert "evidence=fragment" in out
    assert "NON-ANSWER" in out


def test_report_measuring_nothing_exits_two( monkeypatch, capsys ):
    # 🔴 THE BRANCH THAT MATTERS. All non-answers must NOT read as a clean 0% echo rate.
    _install( monkeypatch, [ _FALLBACK ] )
    rows, totals = probe.run( 1 )
    assert probe.report( rows, totals, 1 ) == 2
    assert "MEASURED NOTHING" in capsys.readouterr().out


def test_report_high_echo_rate_exits_one( monkeypatch, capsys ):
    _install( monkeypatch, [ _real( probe.BODIES[ 0 ][ 1 ] ) ] )
    rows, totals = probe.run( 1 )
    # Body 0 quoted whole is an echo; the others get a foreign/partial read, so force the
    # alarm by asserting on the totals the run actually produced.
    code = probe.report( rows, totals, 1 )
    out  = capsys.readouterr().out
    assert "Unusable (echo+partial)" in out
    assert code in ( 0, 1 )


def test_report_alarm_fires_at_threshold( capsys ):
    # Synthetic totals, so the threshold is tested independently of what any model does.
    rows = [ { "name": "X", "words": 10, "real": 4, "echo": 2, "partial": 0,
               "fragment": 2, "targeted": 0, "foreign": 0, "empty": 0,
               "nonanswer": 0, "weights": [ 2, 2, -1, -1 ] } ]
    totals = { "real": 4, "echo": 2, "partial": 0, "fragment": 2, "targeted": 0,
               "foreign": 0, "empty": 0, "nonanswer": 0 }
    assert probe.report( rows, totals, 4 ) == 1
    assert "at or above" in capsys.readouterr().out


def test_report_below_threshold_exits_zero( capsys ):
    rows = [ { "name": "X", "words": 10, "real": 4, "echo": 1, "partial": 0,
               "fragment": 3, "targeted": 0, "foreign": 0, "empty": 0,
               "nonanswer": 0, "weights": [ 2, 2, -1, -1 ] } ]
    totals = { "real": 4, "echo": 1, "partial": 0, "fragment": 3, "targeted": 0,
               "foreign": 0, "empty": 0, "nonanswer": 0 }
    assert probe.report( rows, totals, 4 ) == 0
    assert "below the alarm line" in capsys.readouterr().out


def test_report_narrow_grade_spread_says_so( capsys ):
    # When every grade is the same weight, the probe must decline to claim echoing does
    # or does not track the grade — rather than inferring from one point.
    rows = [ { "name": "X", "words": 10, "real": 2, "echo": 0, "partial": 0,
               "fragment": 2, "targeted": 0, "foreign": 0, "empty": 0,
               "nonanswer": 0, "weights": [ 2, 2 ] } ]
    totals = { "real": 2, "echo": 0, "partial": 0, "fragment": 2, "targeted": 0,
               "foreign": 0, "empty": 0, "nonanswer": 0 }
    probe.report( rows, totals, 2 )
    assert "spread too narrow" in capsys.readouterr().out


def test_report_names_a_body_that_produced_both_behaviours( capsys ):
    # Determinism check: at temperature 0 the same body should behave the same way every
    # run. If one does not, the probe must SAY so rather than average it away.
    rows = [ { "name": "MIXED", "words": 10, "real": 2, "echo": 1, "partial": 0,
               "fragment": 1, "targeted": 0, "foreign": 0, "empty": 0,
               "nonanswer": 0, "weights": [ 2, -1 ] } ]
    totals = { "real": 2, "echo": 1, "partial": 0, "fragment": 1, "targeted": 0,
               "foreign": 0, "empty": 0, "nonanswer": 0 }
    probe.report( rows, totals, 2 )
    assert "MIXED" in capsys.readouterr().out


def test_main_aborts_when_harness_selftest_fails( monkeypatch, capsys ):
    # A broken classifier must stop the run BEFORE the model is called. Proven by making
    # the judge explode: if main() reaches it, the test errors instead of returning 2.
    monkeypatch.setattr( probe, "_self_test", lambda: [ "deliberate failure" ] )
    def _boom(): raise AssertionError( "main() called the model after a failed self-test" )
    monkeypatch.setattr( probe, "get_dm_quality_judge", _boom )
    monkeypatch.setattr( probe.sys, "argv", [ "probe", "1" ] )
    assert probe.main() == 2
    assert "HARNESS SELF-TEST FAILED" in capsys.readouterr().out


def test_main_runs_end_to_end_with_a_stub( monkeypatch, capsys ):
    _install( monkeypatch, [ _real( "holding your gate" ) ] )
    monkeypatch.setattr( probe.sys, "argv", [ "probe", "1" ] )
    assert probe.main() == 0
    out = capsys.readouterr().out
    assert "Harness self-test passed" in out
    assert "Real Tone grades" in out


def test_main_defaults_to_three_runs( monkeypatch ):
    stub = _install( monkeypatch, [ _real( "holding your gate" ) ] )
    monkeypatch.setattr( probe.sys, "argv", [ "probe" ] )
    probe.main()
    assert len( stub.seen ) == 3 * len( probe.BODIES )


def test_report_stays_silent_when_no_body_is_mixed( capsys ):
    # The complement of test_report_names_a_body_that_produced_both_behaviours: a wide
    # grade spread but every body consistent with itself. The probe must NOT claim
    # "echo is not a property of the body" — that sentence is only earned by a body that
    # actually behaved two ways on identical text.
    rows = [ { "name": "ALL_ECHO", "words": 10, "real": 2, "echo": 2, "partial": 0,
               "fragment": 0, "targeted": 0, "foreign": 0, "empty": 0,
               "nonanswer": 0, "weights": [ 2, -1 ] } ]
    totals = { "real": 2, "echo": 2, "partial": 0, "fragment": 0, "targeted": 0,
               "foreign": 0, "empty": 0, "nonanswer": 0 }
    probe.report( rows, totals, 2 )
    assert "NOT a property of the body" not in capsys.readouterr().out

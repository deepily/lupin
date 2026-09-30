"""
The census gate must SEE a result stated in the bare present tense — row `7fb0db55`.

WHY THIS FILE EXISTS. The census in `src/rnd/v0.2.0/dm_passfail_census.py` counts corrupted
pass/fail claims against a denominator of DMs whose submitted body states a result. Its
outcome vocabulary listed inflected forms only — passed / passing / failed / failing /
failure — so a sender who wrote "so 3 fail and 2 pass" stated a result the gate could not
see. One of the two real corruptions in the entire corpus was hidden behind that gap: the
detector flagged it correctly the moment the gate let it through. A denominator filter that
silently narrows turns a floor into something that reads as a rate.

Each test names the change that reddens it, because a guard nobody can falsify is decoration.
"""

import importlib.util
import json
import os

import pytest


def _load_census():
    """Import the census script by path — it lives in src/rnd/, not on the package path."""

    here = os.path.dirname( os.path.abspath( __file__ ) )
    root = os.path.abspath( os.path.join( here, "..", "..", "..", ".." ) )
    path = os.path.join( root, "src", "rnd", "v0.2.0", "dm_passfail_census.py" )

    spec   = importlib.util.spec_from_file_location( "dm_passfail_census", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )

    return module


CENSUS = _load_census()

# The three adjudicated specimens, verbatim from the corpus. These are the controls: a gate
# that drops any of them is measuring something other than what the census claims.
SPECIMEN_1_SENT = (
    "19 passed on the branch, and those 21 tests need the fixture before they can run."
)
SPECIMEN_2_SENT = (
    "the answer is no - it does not exit 0 under the guard, it exits 4, so the guard worked."
)
SPECIMEN_3_SENT = (
    "Maria ran at 78f6683d, which is the RED commit: the test lands there, the alias is "
    "still present there by design, so 3 fail and 2 pass."
)
SPECIMEN_3_DELIVERED = (
    "At 78f6683d, the test fails 3 out of 5 times, which is expected as the alias is still "
    "present by design."
)


# ── the gap this row closed ───────────────────────────────────────────────────────────────

def test_bare_present_tense_result_is_in_the_denominator():
    """Reddens if BARE_LEAD is dropped from carries_a_result — the exact shipped defect."""

    assert CENSUS.carries_a_result( SPECIMEN_3_SENT ) is True


def test_the_detector_flags_specimen_3_once_the_gate_admits_it():
    """
    The detector was never blind — the gate was. Reddens if fabricated_ratio stops seeing a
    ratio the delivered text states and the submitted never did.
    """

    assert CENSUS.fabricated_ratio( SPECIMEN_3_SENT, SPECIMEN_3_DELIVERED ) == [ ( "3", "5" ) ]


@pytest.mark.parametrize( "sent", [ SPECIMEN_1_SENT, SPECIMEN_2_SENT, SPECIMEN_3_SENT ] )
def test_all_three_specimens_stay_in_the_denominator( sent ):
    """Reddens if any future narrowing of the vocabulary drops a known positive control."""

    assert CENSUS.carries_a_result( sent ) is True


# ── the ordinal sense the gate must NOT admit ─────────────────────────────────────────────

@pytest.mark.parametrize( "ordinal", [
    "Handed to Chloe for pass 3.",          # a review pass, not a test result
    "SKILL.md pass 2 finished + committed", # likewise
] )
def test_trailing_bare_pass_is_an_ordinal_and_is_refused( ordinal ):
    """Reddens if BARE_LEAD is widened to the trailing form, which inflates the denominator."""

    assert CENSUS.carries_a_result( ordinal ) is False


def test_inflected_trailing_form_is_still_admitted():
    """
    The leading-only restriction applies to the BARE verbs only. Reddens if the fix narrows
    BOUND itself — "passed 16861" and "green 20/20" are real results in trailing form.
    """

    assert CENSUS.carries_a_result( "passed 16861 / failed 5 / error 0" ) is True


# ── the numeral extractor moves with the gate ─────────────────────────────────────────────

def test_bound_numerals_sees_the_bare_present_tense():
    """Reddens if bound_numerals is left on the narrow vocabulary while the gate widens."""

    assert CENSUS.bound_numerals( SPECIMEN_3_SENT ) == { "3", "2" }


def test_ratios_reads_both_spellings():
    """'19 out of 21' and '19/21' are the same claim. Reddens if RATIO loses either form."""

    assert CENSUS.ratios( "19 out of 21" ) == { ( "19", "21" ) }
    assert CENSUS.ratios( "19/21" )        == { ( "19", "21" ) }


# ── D2 keeps its third condition ──────────────────────────────────────────────────────────

def test_d2_stays_silent_when_the_sender_reported_the_failure_himself():
    """
    A refutation quotes what it refutes. Reddens if the third condition is dropped, which is
    what produced the 15.14% artefact.
    """

    assert CENSUS.dropped_result_with_failure_claim(
        "the run failed, 4 failed of 8848", "it failed" ) == []


def test_d2_stays_silent_when_the_delivered_text_claims_no_failure():
    """Reddens if the delivered-asserts-failure condition is dropped."""

    assert CENSUS.dropped_result_with_failure_claim(
        "19 passed on the branch", "the branch is green" ) == []


def test_d2_fires_on_green_delivered_as_red():
    """The shape D2 exists for. Reddens if the dropped-numeral comparison is inverted."""

    assert CENSUS.dropped_result_with_failure_claim(
        "19 passed on the branch", "three checks failed during the build" ) == [ "19" ]


# ── main(), against a fixture corpus rather than the live 31 MB file ───────────────────────

def _row( ts, body, delivered, origin="live", rewritten=True ):

    return { "ts"                 : ts,
             "from"               : "rio",
             "to"                 : "mr radio",
             "origin"             : origin,
             "body_was_rewritten" : rewritten,
             "body"               : body,
             "delivered_body"     : delivered }


def test_main_reports_missing_corpus_rather_than_crashing( monkeypatch, tmp_path, capsys ):
    """Reddens if the missing-corpus branch is removed — a silent 0 would read as 'no corruption'."""

    monkeypatch.setattr( CENSUS, "CORPUS", str( tmp_path / "absent.jsonl" ) )

    assert CENSUS.main() == 2
    assert "corpus not found" in capsys.readouterr().out


def test_main_counts_and_prints_a_flagged_row( monkeypatch, tmp_path, capsys ):
    """
    End to end over a fixture corpus carrying one flagged row, one honest row, one test-origin
    row and one un-rewritten row. Reddens if the origin/rewritten filter stops excluding.
    """

    corpus = tmp_path / "dm_traffic.jsonl"
    rows   = [ _row( "2026-08-25T02:21:47", SPECIMEN_3_SENT, SPECIMEN_3_DELIVERED ),
               _row( "2026-08-25T03:00:00", "40 pass in the edited file", "40 pass, clean" ),
               _row( "2026-08-25T04:00:00", "3 fail and 2 pass", "1 out of 9", origin="test" ),
               _row( "2026-08-25T05:00:00", "3 fail and 2 pass", "1 out of 9", rewritten=False ),
               _row( "2026-08-25T06:00:00", "no numbers here at all", "still none" ) ]
    corpus.write_text( "\n".join( json.dumps( r ) for r in rows ) + "\n\n", encoding="utf-8" )
    monkeypatch.setattr( CENSUS, "CORPUS", str( corpus ) )

    assert CENSUS.main() == 0
    out = capsys.readouterr().out

    squeezed = " ".join( out.split() )

    assert "live AND rewritten by the condenser 3" in squeezed
    assert "DENOMINATOR: of those, submitted states a result 2" in squeezed
    assert "D1 fabricated ratio 1" in squeezed
    assert "D1 RATE (ratio re-binding) 50.00% (1/2)" in squeezed
    assert "NONE — detector misses control 2" in out
    assert "2026-08-25T02:21:47" in out
    assert "3 Rio 3-of-5 (deterministic -> flaky) in denominator: 1 flagged: 1" in squeezed


def test_main_survives_a_corpus_with_no_qualifying_rows( monkeypatch, tmp_path, capsys ):
    """
    The empty-denominator branch. Reddens if main divides by a zero denominator — the census
    must be able to say 'nothing measured' rather than raise.
    """

    corpus = tmp_path / "dm_traffic.jsonl"
    corpus.write_text( json.dumps( _row( "2026-08-25T02:00:00", "nothing", "nothing",
                                         origin="test" ) ) + "\n", encoding="utf-8" )
    monkeypatch.setattr( CENSUS, "CORPUS", str( corpus ) )

    assert CENSUS.main() == 0
    out = capsys.readouterr().out

    assert "DENOMINATOR: of those, submitted states a result 0" in " ".join( out.split() )
    assert "D1 RATE" not in out


def test_main_reports_no_window_for_an_empty_corpus( monkeypatch, tmp_path, capsys ):
    """The empty-rows branch. Reddens if main() calls min() on an empty corpus."""

    corpus = tmp_path / "dm_traffic.jsonl"
    corpus.write_text( "", encoding="utf-8" )
    monkeypatch.setattr( CENSUS, "CORPUS", str( corpus ) )

    assert CENSUS.main() == 0
    assert "window" not in capsys.readouterr().out


def test_a_d2_only_row_is_printed_with_its_d2_tag( monkeypatch, tmp_path, capsys ):
    """
    Covers the D2-tagging branch of the adjudication listing. Reddens if a D2 hit is counted
    but not printed — a detector whose hits cannot be read is not adjudicable.
    """

    corpus = tmp_path / "dm_traffic.jsonl"
    corpus.write_text( json.dumps( _row( "2026-08-25T07:00:00",
                                         "19 passed on the branch",
                                         "three checks failed during the build" ) ) + "\n",
                       encoding="utf-8" )
    monkeypatch.setattr( CENSUS, "CORPUS", str( corpus ) )

    assert CENSUS.main() == 0
    out = capsys.readouterr().out

    assert "D2 dropped=['19']" in out
    assert "D1 ratio" not in out

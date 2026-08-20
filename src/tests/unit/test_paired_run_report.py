"""
Unit coverage for the paired-run report renderer (row d8d019f6).

WHAT THIS PROTECTS: a median delta with no failure rate and no category composition beside
it is not a readable result (Mr Radio, from María's 08-17 finding, row 2ebe4ccb). Routing
accuracy and latency are computed over usable records only, so an arm that loses a whole
category is scored on a different corpus than its partner — and scores BETTER for having
lost its hardest work. The divergence flag is the control; these tests prove it fires on
the real 08-17 shape and stays quiet on a clean run.
"""

import importlib.util, json, os

import pytest

import cosa.utils.util as cu

_SPEC = importlib.util.spec_from_file_location(
    "paired_report", os.path.join( cu.get_project_root(), "src", "scripts", "render-paired-run-report.py" ) )
report = importlib.util.module_from_spec( _SPEC )
_SPEC.loader.exec_module( report )


def _artifact( spans, n=100, ok=100, ok_key="ok_n", failure_rate=0.0 ):
    return { "metrics": { "spans_by_utterance": spans, "n": n, ok_key: ok,
                          "failure_rate": failure_rate }, "provenance": {} }


# ---------------------------------------------------------------------------
# surviving_by_category
# ---------------------------------------------------------------------------
def test_surviving_counts_group_by_corpus_command():
    mapping = { "a": "todo", "b": "todo", "c": "math" }
    art     = _artifact( { "a": 1.0, "b": 2.0, "c": 3.0 } )
    assert report.surviving_by_category( art, mapping ) == { "todo": 2, "math": 1 }


def test_an_utterance_missing_from_the_corpus_map_is_surfaced_not_dropped():
    """A mapping gap must not quietly shrink a category — that would look like the exact
    category loss this report exists to detect."""
    art = report.surviving_by_category( _artifact( { "mystery": 1.0 } ), {} )
    assert art == { "(unmapped)": 1 }


def test_a_missing_arm_contributes_no_counts_rather_than_raising():
    assert report.surviving_by_category( None, { "a": "todo" } ) == {}


# ---------------------------------------------------------------------------
# The divergence flag — the actual control
# ---------------------------------------------------------------------------
def test_the_2026_08_17_category_loss_is_flagged():
    """v2 keeps 1 of the 20 routing utterances v1 kept — the shape that made the damaged
    arm score better on 08-17. RED if this stops being flagged."""
    lines, flagged = report.composition_table( { "routing": 20, "todo": 20 },
                                               { "routing": 1,  "todo": 20 } )
    assert flagged
    assert any( "DIVERGENT" in line and "routing" in line for line in lines )
    assert not any( "DIVERGENT" in line and "todo" in line for line in lines )


def test_the_flag_names_WHICH_arm_lost_the_category():
    """"divergent" alone sends the reader back to the data. The row must say which arm."""
    lines, _ = report.composition_table( { "routing": 20 }, { "routing": 1 } )
    assert "v2 lost 19 of 20" in " ".join( lines )
    lines, _ = report.composition_table( { "routing": 1 }, { "routing": 20 } )
    assert "v1 lost 19 of 20" in " ".join( lines )


def test_a_clean_run_is_not_flagged():
    """A control that fires on healthy runs is one people learn to ignore."""
    _, flagged = report.composition_table( { "routing": 20, "todo": 20 },
                                           { "routing": 20, "todo": 20 } )
    assert not flagged


def test_ordinary_jitter_is_not_flagged():
    """One or two lost out of twenty is noise, not a lost category."""
    _, flagged = report.composition_table( { "routing": 20 }, { "routing": 18 } )
    assert not flagged


def test_a_category_missing_entirely_from_one_arm_is_flagged():
    """The most severe form: the category never appears in that arm at all."""
    _, flagged = report.composition_table( { "routing": 20 }, {} )
    assert flagged


def test_both_arms_below_the_sampled_size_is_noted_even_when_they_agree():
    """Two arms can agree and both be wrong — a category where BOTH lost most of the
    sample is not divergent, but it is not healthy either."""
    lines, flagged = report.composition_table( { "routing": 3 }, { "routing": 3 },
                                               expected_per_command=20 )
    assert not flagged
    assert "both below the 20 sampled" in " ".join( lines )


# ---------------------------------------------------------------------------
# load_artifacts / render
# ---------------------------------------------------------------------------
def test_a_v1_only_directory_still_renders( tmp_path ):
    """The early v1-only dump exists precisely so a v2-arm death leaves v1 readable.
    A report tool that refuses to open that directory would waste what the dump saved."""
    with open( tmp_path / "v1-arm-artifact.json", "w" ) as fh:
        json.dump( _artifact( { "a": 1.0 } ), fh )
    text, ok = report.render( str( tmp_path ) )
    assert "The v2 arm wrote no artifact" in text
    assert "one-armed" in text


def test_an_empty_directory_says_nothing_was_measured( tmp_path ):
    text, ok = report.render( str( tmp_path ) )
    assert ok is False
    assert "NO ARTIFACTS" in text


def test_load_artifacts_returns_none_for_each_absent_arm( tmp_path ):
    assert report.load_artifacts( str( tmp_path ) ) == ( None, None )


# ---------------------------------------------------------------------------
# A one-armed run must NOT be given a divergence verdict (found by running the
# tool against the live run's early v1-only dump — every row read DIVERGENT,
# which described a missing file rather than a lost category).
# ---------------------------------------------------------------------------
def test_a_one_armed_run_does_not_claim_divergence( tmp_path ):
    """RED if the report ever again reads "v2 lost everything" when v2 simply has not
    returned. A control that fires on a state it cannot speak to is noise, and noise is
    how a real flag gets ignored later."""
    with open( tmp_path / "v1-arm-artifact.json", "w" ) as fh:
        json.dump( _artifact( { "a": 1.0, "b": 2.0 } ), fh )
    text, _ = report.render( str( tmp_path ) )
    assert "Divergence not assessed" in text
    assert "DIVERGENT" not in text.split( "Divergence not assessed" )[ 1 ]
    assert "compares like with like" not in text      # nor a false all-clear


def test_a_category_absent_from_BOTH_arms_is_called_out( monkeypatch, tmp_path ):
    """The completest form of the loss, and the one a survivors-only table cannot show:
    a corpus category that produced no usable record on either side has no row at all."""
    for name in ( "v1", "v2" ):
        with open( tmp_path / f"{name}-arm-artifact.json", "w" ) as fh:
            json.dump( _artifact( { "a": 1.0 }, ok_key="ok_n" if name == "v1" else "n_ok" ), fh )

    import types
    fake_v2 = types.SimpleNamespace(
        load_corpus=lambda name: [ ( "a", "kept" ), ( "z", "vanished" ) ] )
    fake_pe = types.SimpleNamespace(
        build_paired_verdict=lambda a, b: { "fired": False, "reason": "stub" },
        render_paired_verdict=lambda v: "## stub verdict" )
    monkeypatch.setitem( __import__( "sys" ).modules, "v2_eval", fake_v2 )
    monkeypatch.setitem( __import__( "sys" ).modules, "paired_eval", fake_pe )

    text, ok = report.render( str( tmp_path ) )
    assert "Absent from BOTH arms entirely" in text
    assert "vanished" in text.split( "Absent from BOTH arms entirely" )[ 1 ]


# ---------------------------------------------------------------------------
# Attrition is a SEPARATE question from divergence (found in the both-arms
# rehearsal: a pair that kept 53 of 100 with one category entirely gone still
# rendered a green tick, because the two arms lost the SAME records).
# ---------------------------------------------------------------------------
def _pair( tmp_path, failure_rate, spans=None ):
    spans = spans if spans is not None else { "a": 1.0 }
    for name, ok_key in ( ( "v1", "ok_n" ), ( "v2", "n_ok" ) ):
        with open( tmp_path / f"{name}-arm-artifact.json", "w" ) as fh:
            json.dump( _artifact( spans, ok_key=ok_key, failure_rate=failure_rate ), fh )


def _stub_deps( monkeypatch, pairs ):
    import sys, types
    monkeypatch.setitem( sys.modules, "v2_eval",
                         types.SimpleNamespace( load_corpus=lambda name: pairs ) )
    monkeypatch.setitem( sys.modules, "paired_eval", types.SimpleNamespace(
        build_paired_verdict=lambda a, b: { "fired": False, "reason": "stub" },
        render_paired_verdict=lambda v: "## stub verdict" ) )


def test_high_attrition_is_flagged_even_when_the_arms_agree_perfectly( monkeypatch, tmp_path ):
    """THE REHEARSAL DEFECT. Two arms that lose the SAME half of the corpus diverge not at
    all, and a divergence-only report calls that like-for-like. It is — and it is still a
    delta measured over a selected subsample. RED if the attrition line disappears."""
    _pair( tmp_path, failure_rate=0.47 )
    _stub_deps( monkeypatch, [ ( "a", "kept" ) ] )
    text, _ = report.render( str( tmp_path ) )
    assert "HIGH ATTRITION" in text
    assert "47%" in text


def test_a_low_attrition_run_gets_no_attrition_warning( monkeypatch, tmp_path ):
    """The negative control — a warning that always fires is not a warning."""
    _pair( tmp_path, failure_rate=0.02 )
    _stub_deps( monkeypatch, [ ( "a", "kept" ) ] )
    text, _ = report.render( str( tmp_path ) )
    assert "HIGH ATTRITION" not in text


def test_the_clean_tick_no_longer_claims_the_comparison_is_sound( monkeypatch, tmp_path ):
    """The tick speaks only to divergence. It used to read "compares like with like", which
    a reader takes as a verdict on the whole run rather than on one of its two failure modes."""
    _pair( tmp_path, failure_rate=0.47 )
    _stub_deps( monkeypatch, [ ( "a", "kept" ) ] )
    text, _ = report.render( str( tmp_path ) )
    assert "compares like with like" not in text
    assert "neither arm lost ground the other kept" in text

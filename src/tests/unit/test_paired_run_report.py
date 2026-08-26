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


# ═══════════════════════════════════════════════════════════════════════════════
# Provenance header (row 224fbb68)
#
# THE DEFECT: this report carried NO provenance at all. Counted across the full
# rendered output, each of these appeared exactly ZERO times — the v1 sha, the v2
# sha, `git_sha`, `written_by`, `seed`, `n_per_command`. The stamp lives in the
# JSON and was dropped precisely where a human reads it.
#
# It is a RULING, not a nicety. Mr Radio, row 647f3733, 2026-08-21, verbatim:
# "REPORT MUST SAY: referent sha 15536409, contains bf77852b, pre-drift
# alternative b0735467 remains available by pinning; whether the referent choice
# moves any headline number is UNMEASURED." The renderer could not satisfy it.
# These tests move the enforcement from whoever remembers the ruling to the harness.
# ═══════════════════════════════════════════════════════════════════════════════

def _prov_artifact( git_sha, written_by="ts-abcd1234", signature="sig-aaaa" ):
    return {
        "metrics"    : { "spans_by_utterance": {}, "n": 100, "ok_n": 100, "failure_rate": 0.0 },
        "provenance" : { "git_sha": git_sha, "corpus": "simple", "seed": 1024,
                         "n_per_command": 20, "sampled_n": 100,
                         "sample_signature": signature },
        "written_at" : "2026-08-25T23:00:00",
        "written_by" : written_by,
    }


def _render_prov( v1_sha, **kw ):
    from v1_eval_arm import V1_PIN_SHA          # noqa: F401 — imported for the pin value in tests
    return "\n".join( report.provenance_block( _prov_artifact( v1_sha, **kw ),
                                               _prov_artifact( "f86ee2d7", **kw ) ) )


def test_the_report_names_the_v1_sha_it_measured():
    """
    The ruling's core requirement. A report that cannot say WHICH v1 it measured is
    not comparable to anything — the 08-14 ruling's premise is that drift is a
    labelling problem, and this is the label.
    """
    from v1_eval_arm import V1_PIN_SHA
    text = _render_prov( V1_PIN_SHA )
    assert V1_PIN_SHA in text
    assert "f86ee2d7" in text, "the v2 sha must be named too"


def test_the_pinned_referent_carries_its_rationale_and_the_unmeasured_caveat():
    """The ruling names three things beyond the sha; all three must survive rendering."""
    from v1_eval_arm import V1_PIN_SHA
    text = _render_prov( V1_PIN_SHA )
    assert "bf77852b" in text,  "must say the referent carries the leak fix"
    assert "b0735467" in text,  "must say the pre-drift alternative remains available by pinning"
    assert "UNMEASURED" in text, "must say the referent choice's effect on headline numbers is unmeasured"


def test_a_run_against_the_rejected_pre_drift_sha_is_flagged_not_printed_flat():
    """
    The 08-20 artifact really was written against `b0735467`. Printed without comment
    it reads as just another sha; it is the REJECTED referent and it is LEAKY.
    """
    text = _render_prov( "b0735467" )
    assert "REFERENT MISMATCH" in text
    assert "LEAKY" in text
    assert "bf77852b" in text, "must say WHY it is leaky, not merely that it is"


def test_the_mismatch_branch_does_not_emit_a_tautology_for_other_shas():
    """
    Scope guard on my own first draft: the generic branch used to read
    'If <sha> is b0735467, that arm is LEAKY' — which renders as
    'If b0735467 is b0735467' on the one case that matters. The pre-drift sha is
    now named only when it is actually the one.
    """
    text = _render_prov( "deadbeef" )
    assert "REFERENT MISMATCH" in text
    assert "b0735467" not in text.split( "REFERENT MISMATCH" )[ 1 ], (
        "an unrelated sha must not drag the pre-drift warning in with it"
    )


def test_unknown_caller_is_surfaced_as_an_alarm():
    """
    `unknown-caller` was built as the tell that nothing identified itself as a real
    run — and row 224fbb68 measured that nothing ever SET the variable it reads, so
    the tell could never fire. Surfacing it here is what gives it back its meaning.
    """
    from v1_eval_arm import V1_PIN_SHA
    text = _render_prov( V1_PIN_SHA, written_by="unknown-caller" )
    assert "unknown-caller" in text
    assert "Do not cite these numbers" in text


def test_a_real_job_id_raises_no_alarm():
    """The alarm must stay quiet on a genuine run, or it becomes noise."""
    from v1_eval_arm import V1_PIN_SHA
    text = _render_prov( V1_PIN_SHA, written_by="ts-f06f5961" )
    assert "unknown-caller" not in text


def test_differing_sample_signatures_are_flagged_as_not_a_paired_measurement():
    """Two arms that did not draw the same sample are not paired, whatever the delta says."""
    from v1_eval_arm import V1_PIN_SHA
    v1 = _prov_artifact( V1_PIN_SHA, signature="sig-aaaa" )
    v2 = _prov_artifact( "f86ee2d7",  signature="sig-bbbb" )
    text = "\n".join( report.provenance_block( v1, v2 ) )
    assert "SAMPLE SIGNATURES DIFFER" in text


def test_a_missing_arm_says_so_rather_than_rendering_a_blank_sha():
    """An absent artifact must not read as a run with an empty label."""
    text = "\n".join( report.provenance_block( None, _prov_artifact( "f86ee2d7" ) ) )
    assert "wrote no git_sha" in text


def test_the_provenance_header_appears_in_the_full_rendered_report( tmp_path ):
    """
    End-to-end, not just the helper: the block must actually reach the document a
    human reads. The defect was that the data existed and never made it to the page.
    """
    from v1_eval_arm import V1_PIN_SHA
    for arm, sha in ( ( "v1", V1_PIN_SHA ), ( "v2", "f86ee2d7" ) ):
        ( tmp_path / f"{arm}-arm-artifact.json" ).write_text( json.dumps( _prov_artifact( sha ) ) )
    text, _ok = report.render( str( tmp_path ) )
    assert "## Provenance" in text
    assert V1_PIN_SHA in text

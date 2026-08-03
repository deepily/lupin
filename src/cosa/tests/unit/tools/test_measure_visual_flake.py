#!/usr/bin/env python3
"""
Unit tests for cosa.tests.tools.measure_visual_flake — the visual-flake triage
harness's PURE verdict logic (item 7ffa1998).

Scope: 100% line+branch on `classify_visual_flake` (the decision function). The
CLI/IO shell (`main`), the `format_report` string builder, and the `measure`
orchestration are `# pragma: no cover` with reasons (pre-approved by Tiberius,
2026-07-07): they carry no decision logic, and the two comparators `measure`
drives are themselves 100%-covered by test_visual_aa_scatter_tolerant.py /
test_visual_content_shift.py.

The verdict fn is duck-typed over the comparator result attributes, so these
tests use lightweight fakes — no PIL/numpy/scipy image stack, no real PNGs.

Venue: :7999 (unit, isolated, no state) — `pytest src/cosa/tests/unit/tools/`.
"""

from __future__ import annotations

from types import SimpleNamespace

from cosa.tests.tools.measure_visual_flake import (
    ESCALATE,
    RECAPTURE,
    SWAP,
    FlakeVerdict,
    classify_visual_flake,
)


# ---------------------------------------------------------------------------
# Fake comparator results (duck-typed — classify_visual_flake reads attributes
# only, never isinstance-checks, so a SimpleNamespace stands in for the real
# frozen dataclasses without pulling in the image stack).
# ---------------------------------------------------------------------------

def _aa( *, matched=False, reason="", total_diff_pixels=0, component_count=0,
         largest_cluster_area=0, erosion_survivors=0 ):
    return SimpleNamespace(
        matched              = matched,
        reason               = reason,
        total_diff_pixels    = total_diff_pixels,
        component_count      = component_count,
        largest_cluster_area = largest_cluster_area,
        erosion_survivors    = erosion_survivors,
    )


def _cs( *, matched=False, best_dx=0, best_dy=0, best_mismatch=0 ):
    return SimpleNamespace(
        matched       = matched,
        best_dx       = best_dx,
        best_dy       = best_dy,
        best_mismatch = best_mismatch,
    )


# ---------------------------------------------------------------------------
# Branch 1 — content-shift match → SWAP
# ---------------------------------------------------------------------------

def test_content_shift_match_returns_swap():
    aa = _aa( matched=False )
    cs = _cs( matched=True, best_dx=1, best_dy=0 )
    v = classify_visual_flake( aa, cs )
    assert isinstance( v, FlakeVerdict )
    assert v.verdict == SWAP
    assert v.exit_code == 0
    assert "content-shift" in v.rationale
    assert "(1,0)px" in v.rationale        # cites the decisive offset
    assert v.aa is aa and v.content_shift is cs


# ---------------------------------------------------------------------------
# Branch 2 — aa-scatter match (content-shift did NOT) → SWAP
# ---------------------------------------------------------------------------

def test_aa_scatter_match_returns_swap():
    aa = _aa( matched=True, total_diff_pixels=1200, component_count=40, largest_cluster_area=2 )
    cs = _cs( matched=False )
    v = classify_visual_flake( aa, cs )
    assert v.verdict == SWAP
    assert v.exit_code == 0
    assert "aa-scatter" in v.rationale
    assert "1200px" in v.rationale         # cites the forgiven scatter count


# ---------------------------------------------------------------------------
# Branch 1 precedence — when BOTH match, content-shift wins the rationale
# (it is checked first / is the stricter forgiveness).
# ---------------------------------------------------------------------------

def test_both_match_prefers_content_shift():
    aa = _aa( matched=True, total_diff_pixels=50 )
    cs = _cs( matched=True, best_dx=0, best_dy=1 )
    v = classify_visual_flake( aa, cs )
    assert v.verdict == SWAP
    assert "content-shift" in v.rationale
    assert "aa-scatter" not in v.rationale


# ---------------------------------------------------------------------------
# Branch 3 — neither matched, size refused (0 diff + 0 components) → ESCALATE
# ---------------------------------------------------------------------------

def test_size_refusal_returns_escalate():
    aa = _aa(
        matched=False, reason="width mismatch: actual 900px vs baseline 880px (not tolerated)",
        total_diff_pixels=0, component_count=0,
    )
    cs = _cs( matched=False )
    v = classify_visual_flake( aa, cs )
    assert v.verdict == ESCALATE
    assert v.exit_code == 2
    assert "size mismatch refused" in v.rationale
    assert "width mismatch" in v.rationale     # surfaces the comparator's own reason


# ---------------------------------------------------------------------------
# Branch 4 — neither matched, a solid block survived erosion → ESCALATE
# ---------------------------------------------------------------------------

def test_erosion_survivor_returns_escalate():
    aa = _aa(
        matched=False, total_diff_pixels=520, component_count=3,
        largest_cluster_area=400, erosion_survivors=180,
    )
    cs = _cs( matched=False )
    v = classify_visual_flake( aa, cs )
    assert v.verdict == ESCALATE
    assert v.exit_code == 2
    assert "survived erosion" in v.rationale
    assert "180px" in v.rationale


# ---------------------------------------------------------------------------
# Branch 5 — neither matched, over the AA floor but NO contiguity → RECAPTURE
# ---------------------------------------------------------------------------

def test_noncontiguous_over_floor_returns_recapture():
    aa = _aa(
        matched=False, total_diff_pixels=900, component_count=120,
        largest_cluster_area=6, erosion_survivors=0,
    )
    cs = _cs( matched=False )
    v = classify_visual_flake( aa, cs )
    assert v.verdict == RECAPTURE
    assert v.exit_code == 1
    assert "no solid block" in v.rationale
    assert "--update-snapshots" in v.rationale


# ---------------------------------------------------------------------------
# Guard the exit-code map is exhaustive over the three verdict constants.
# ---------------------------------------------------------------------------

def test_exit_codes_distinct_and_complete():
    swap     = classify_visual_flake( _aa(), _cs( matched=True ) )
    recap    = classify_visual_flake(
        _aa( total_diff_pixels=10, component_count=5, largest_cluster_area=3, erosion_survivors=0 ),
        _cs( matched=False ),
    )
    escalate = classify_visual_flake( _aa( total_diff_pixels=0, component_count=0 ), _cs( matched=False ) )
    codes = { swap.exit_code, recap.exit_code, escalate.exit_code }
    assert codes == { 0, 1, 2 }

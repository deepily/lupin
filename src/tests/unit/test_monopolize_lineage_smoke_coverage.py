"""
Every smoke that submits to a LINEAGE-AWARE endpoint must thread the parent id — row 7451bebe.

THE DEFECT THIS EXISTS TO CATCH
-------------------------------
Bug 5ed4f187 added `parent_id_hash` to six submit routers so the consumer's Gate B admits a
monopolizer's own children through the intake hold instead of deferring them as foreign
writers (the 900s starvation). The routers were all changed correctly. But only the
presentation-family smokes ever SET the field, so on podcast and deep-research the parameter
was real in the router and unreachable on the only path that would exercise it live: those
children still submitted `parent_id_hash=None` and still starved.

⚠️ WHY THE ROUTER UNIT TESTS DID NOT CATCH IT, which is the reusable part: they assert the
stamp LANDS on the job when the field is supplied. Whether anything ever supplies it is a
different question, and no test was asking it. A per-site check that is correct about its own
site and silent about the population is how this class of gap survives a green suite.

WHAT THIS ASSERTS
-----------------
The endpoint set is DERIVED, never hand-listed: any router declaring `parent_id_hash` is
lineage-aware, and its submit path is read off its own `prefix=` / `@router.post` lines. Any
test file that POSTs to one of those paths must also read `LUPIN_TEST_MONOPOLIZE_PARENT_ID`.
Add a seventh lineage-aware router tomorrow, or a new smoke against an existing one, and this
holds the line without anyone remembering to update a list.

SCOPE — what a green here does NOT mean: this proves the tag is THREADED, not that Gate B
admits the child. That is the :8000 monopolize sweep, and it is still owed on row 7451bebe.
A green here is the floor that makes the sweep worth running.

Venue: :7999-eligible. Pure file reads; no server, no docker, no network.
"""
import os
import re

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
ROUTER_DIR   = os.path.join( PROJECT_ROOT, "src/cosa/rest/routers" )
TEST_DIRS    = ( "src/tests/smoke", "src/tests/integration" )

LINEAGE_FIELD = "parent_id_hash"
LINEAGE_ENV   = "LUPIN_TEST_MONOPOLIZE_PARENT_ID"

PREFIX_RE = re.compile( r"""prefix\s*=\s*["']([^"']+)["']""" )
POST_RE   = re.compile( r"""@router\.post\(\s*\n?\s*["']([^"']+)["']""", re.MULTILINE )


def lineage_aware_endpoints( router_dir ):
    """
    Every submit path whose router declares the lineage field.

    Requires:
        - router_dir holds FastAPI router modules

    Ensures:
        - returns a dict of { full_path: router_filename } for each router mentioning
          `parent_id_hash`, joining `prefix=` to each `@router.post` path
        - a router with no prefix contributes its post paths verbatim (they are absolute)
    """
    endpoints = {}
    for name in sorted( os.listdir( router_dir ) ):
        if not name.endswith( ".py" ) or name.startswith( "._" ): continue   # ._ = AppleDouble sidecar, not source
        with open( os.path.join( router_dir, name ), "r", errors="ignore" ) as f: text = f.read()
        if LINEAGE_FIELD not in text: continue
        prefix = PREFIX_RE.search( text )
        prefix = prefix.group( 1 ) if prefix else ""
        for path in POST_RE.findall( text ):
            full = path if path.startswith( "/api/" ) else f"{prefix}{path}"
            if full.startswith( "/api/" ): endpoints[ full ] = name
    return endpoints


def untagged_callers( endpoints, root, test_dirs ):
    """
    Test files that POST to a lineage-aware endpoint without reading the parent-id env var.

    Ensures:
        - returns a list of ( relative_path, endpoint ) pairs, one per offending file
        - a file mentioning the env var anywhere is accepted (threading it is the point;
          how it is spelled is the author's business)
    """
    offenders = []
    for d in test_dirs:
        full_dir = os.path.join( root, d )
        if not os.path.isdir( full_dir ): continue
        for name in sorted( os.listdir( full_dir ) ):
            if not name.endswith( ".py" ) or name.startswith( "._" ): continue   # AppleDouble sidecar
            path = os.path.join( full_dir, name )
            with open( path, "r", errors="ignore" ) as f: text = f.read()
            if LINEAGE_ENV in text: continue
            for endpoint in endpoints:
                if endpoint in text:
                    offenders.append( ( os.path.join( d, name ), endpoint ) )
                    break
    return offenders


# ── can-fail controls: the checker must flag a synthetic gap ────────────────
def test_a_router_without_the_field_is_not_lineage_aware( tmp_path ):
    """A router that never mentions the field contributes no endpoint — no false positives."""
    ( tmp_path / "plain.py" ).write_text(
        'router = APIRouter( prefix="/api/plain" )\n@router.post( "/submit" )\ndef go(): pass\n'
    )
    assert lineage_aware_endpoints( str( tmp_path ) ) == {}


def test_the_checker_flags_a_smoke_that_skips_the_tag( tmp_path ):
    """
    THE CONTROL. Without this arm, a green above could mean the tree is clean OR that the
    checker cannot see anything at all — and those are indistinguishable from the outside.
    """
    smoke_dir = tmp_path / "smoke"
    smoke_dir.mkdir()
    ( smoke_dir / "test_untagged.py" ).write_text(
        'requests.post( f"{BASE_URL}/api/deep-research/submit", json={ "query": "x" } )\n'
    )
    offenders = untagged_callers( { "/api/deep-research/submit": "deep_research.py" },
                                  str( tmp_path ), ( "smoke", ) )
    assert offenders == [ ( "smoke/test_untagged.py", "/api/deep-research/submit" ) ]


def test_the_checker_accepts_a_smoke_that_threads_the_tag( tmp_path ):
    """The same file passes once it reads the env var — the checker discriminates."""
    smoke_dir = tmp_path / "smoke"
    smoke_dir.mkdir()
    ( smoke_dir / "test_tagged.py" ).write_text(
        f'parent = os.environ.get( "{LINEAGE_ENV}" )\n'
        'requests.post( f"{BASE_URL}/api/deep-research/submit", json=payload )\n'
    )
    assert untagged_callers( { "/api/deep-research/submit": "deep_research.py" },
                             str( tmp_path ), ( "smoke", ) ) == []


# ── the real-tree assertions ────────────────────────────────────────────────
def test_the_derivation_finds_the_lineage_aware_routers():
    """
    Non-vacuity guard: if the regexes rot, every assertion below passes over an empty set.

    Ensures:
        - the derived set is non-empty and contains the two endpoints row 7451bebe named
    """
    endpoints = lineage_aware_endpoints( ROUTER_DIR )
    assert endpoints, "derived ZERO lineage-aware endpoints — the router parse has rotted"
    assert "/api/deep-research/submit" in endpoints
    assert "/api/podcast-generator/submit" in endpoints


@pytest.mark.xfail(
    strict=True,
    reason=(
        "MEASURED 2026-08-19 (row 7451bebe): EIGHT callers still submit untagged, and three of "
        "them are swe_team — the ORIGINAL 3a14292b surface, fixed months before the presentation "
        "one. Tiffany closed two tonight (deep_research_submit, podcast_generator_dry_run); the "
        "rest are unowned as of this commit: test_approach_d_user_messages, "
        "test_bfe_phase6_repair_loop_smoke, test_deep_research_dry_run_smoke, "
        "test_presentation_dry_run_smoke, test_proxy_notifications, "
        "test_research_to_podcast_dry_run_smoke, test_research_to_presentation_dry_run_smoke, "
        "test_swe_team_mock_endpoint. strict=True on purpose: the day the last one is tagged this "
        "XPASSes and FAILS, forcing the waiver off rather than letting it outlive the gap it "
        "excuses — same discipline as the marker on test_compose_env_contract_coverage."
    ),
)
def test_every_lineage_aware_caller_threads_the_parent_id():
    """
    The row's assertion: no test may submit to a lineage-aware endpoint untagged.

    Ensures:
        - the offender list is empty
        - the failure message names file and endpoint, and points at the pattern to copy
    """
    endpoints = lineage_aware_endpoints( ROUTER_DIR )
    offenders = untagged_callers( endpoints, PROJECT_ROOT, TEST_DIRS )
    assert not offenders, (
        "these submit to a lineage-aware endpoint without threading "
        f"{LINEAGE_ENV}, so under a monopolize sweep the consumer's Gate B defers them as "
        "foreign and they starve 900s: "
        + "; ".join( f"{f} -> {e}" for f, e in offenders )
        + " — copy the three lines at src/tests/smoke/test_presentation_live_smoke.py:265-267 (row 5ed4f187)."
    )

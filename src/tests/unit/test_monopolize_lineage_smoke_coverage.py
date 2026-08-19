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

SCOPE — two things a green here does NOT mean.
  · It proves the tag is THREADED, not that Gate B ADMITS the child. That is the :8000
    monopolize sweep, still owed on row 7451bebe. A green here is the floor that makes the
    sweep worth running.
  · The check is FILE-LEVEL: a file that reads the env var anywhere passes, even if one of
    its submit sites still goes out untagged. That is deliberate — several of these files
    submit raw payloads on purpose to probe a 422, and those must stay untagged — but it
    means this cannot certify every CALL SITE, only that no file is wholly unaware.

HISTORY, because the marker did its job and should be remembered for it: this arm shipped
2026-08-19 as xfail(strict=True) over EIGHT untagged callers, three of them swe_team. Tiffany
tagged all eight within the hour, the arm XPASSed, strict turned that into a FAILURE, and the
waiver came off the same evening it went on. A non-strict marker would still be sitting here.

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


def _code_only( text ):
    """
    The file's CODE, with comment tails removed.

    ⚠️ WHY THIS EXISTS — my own control caught it. The first version of this checker accepted
    any file MENTIONING the env var, and every tagged file also carries a comment naming it.
    So neutering the actual read (`parent_id = None`) left the comment behind and the checker
    stayed green over a genuinely untagged file. An instrument that a comment can satisfy is
    the same defect this file was written to catch, one level up.

    Ensures:
        - returns the text with everything after an unquoted-looking `#` dropped per line
        - crude by design: it can only make the check STRICTER, never more permissive
    """
    return "\n".join( line.split( "#" )[ 0 ] for line in text.splitlines() )


def untagged_callers( endpoints, root, test_dirs ):
    """
    Test files that POST to a lineage-aware endpoint without READING the parent-id env var.

    Ensures:
        - returns a list of ( relative_path, endpoint ) pairs, one per offending file
        - the env var must appear in CODE, not in a comment (see _code_only)
        - the file must also stamp `parent_id_hash` in code — reading the var and never
          putting it in a payload is not threading it
    """
    offenders = []
    for d in test_dirs:
        full_dir = os.path.join( root, d )
        if not os.path.isdir( full_dir ): continue
        for name in sorted( os.listdir( full_dir ) ):
            if not name.endswith( ".py" ) or name.startswith( "._" ): continue   # AppleDouble sidecar
            path = os.path.join( full_dir, name )
            with open( path, "r", errors="ignore" ) as f: text = f.read()
            code = _code_only( text )
            if LINEAGE_ENV in code and LINEAGE_FIELD in code: continue
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
        'payload[ "parent_id_hash" ] = parent\n'
        'requests.post( f"{BASE_URL}/api/deep-research/submit", json=payload )\n'
    )
    assert untagged_callers( { "/api/deep-research/submit": "deep_research.py" },
                             str( tmp_path ), ( "smoke", ) ) == []


def test_a_comment_naming_the_env_var_does_NOT_satisfy_the_check( tmp_path ):
    """
    THE CONTROL THAT CAUGHT MY OWN INSTRUMENT. A file that only TALKS about the tag is
    untagged, and must be flagged as such — otherwise neutering the real read leaves the
    comment behind and the checker reports clean over a live gap.
    """
    smoke_dir = tmp_path / "smoke"
    smoke_dir.mkdir()
    ( smoke_dir / "test_comment_only.py" ).write_text(
        f'# threads {LINEAGE_ENV} as parent_id_hash — except it does not\n'
        'parent_id = None\n'
        'requests.post( f"{BASE_URL}/api/deep-research/submit", json=payload )\n'
    )
    assert untagged_callers( { "/api/deep-research/submit": "deep_research.py" },
                             str( tmp_path ), ( "smoke", ) ) == [
        ( "smoke/test_comment_only.py", "/api/deep-research/submit" ) ]


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

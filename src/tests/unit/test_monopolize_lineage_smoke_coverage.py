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
The endpoint set is DERIVED, never hand-listed: a POST door is lineage-aware when the
request model in ITS OWN handler signature declares `parent_id_hash`. Any test file that
POSTs to one of those doors must also read `LUPIN_TEST_MONOPOLIZE_PARENT_ID`. Add a seventh
lineage-aware door tomorrow, or a new smoke against an existing one, and this holds the line
without anyone remembering to update a list.

⚠️ The question is asked PER DOOR because it used to be asked per FILE — "any router
mentioning the field is lineage-aware, and every `@router.post` in it is one of its doors".
That held while each router had exactly one submit endpoint. `v2_ask.py` has three and only
`/api/v2/submit` takes the field, so the file-level rule accused nine test files of failing
to tag `/api/v2/ask` with a field that door does not accept. See `lineage_aware_endpoints`.

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
import ast
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


def _lineage_models( tree ):
    """
    The request-model classes in one router that declare the lineage field.

    Ensures:
        - returns a set of class names having a `parent_id_hash` annotated attribute
    """
    models = set()
    for node in ast.walk( tree ):
        if not isinstance( node, ast.ClassDef ): continue
        for stmt in node.body:
            if isinstance( stmt, ast.AnnAssign ) and isinstance( stmt.target, ast.Name ) \
               and stmt.target.id == LINEAGE_FIELD:
                models.add( node.name )
    return models


def _post_paths( decorator ):
    """Every literal path on one `@router.post( ... )` decorator, or [] if it is not one."""
    func = decorator.func
    if not ( isinstance( func, ast.Attribute ) and func.attr == "post" ): return [ ]
    return [ a.value for a in decorator.args
             if isinstance( a, ast.Constant ) and isinstance( a.value, str ) ]


def lineage_aware_endpoints( router_dir ):
    """
    Every POST path whose OWN request model declares the lineage field.

    ⚠️ THIS USED TO BE A PER-FILE CHECK, AND THAT WENT WRONG THE DAY A ROUTER GREW A
    SECOND DOOR. The rule was "any router mentioning `parent_id_hash` is lineage-aware,
    and every `@router.post` in it is one of its doors" — fine while each router had a
    single submit endpoint, which was true of all six when this was written. `v2_ask.py`
    has three doors and only `/api/v2/submit` takes the field, so the old rule accused
    nine test files of failing to tag `/api/v2/ask` with a field that endpoint does not
    accept and would reject. A checker that names innocent files teaches people to
    ignore it, which costs more than the gap it was watching for.

    So the question is asked per ENDPOINT: does the model in THIS handler's signature
    declare the field? A router-wide mention is not evidence about any one door.

    Requires:
        - router_dir holds FastAPI router modules

    IT REPORTS WHAT IT COULD NOT MATCH, because the failure mode of a derived set is
    silence. A router that mentions the field but whose model was renamed, or whose
    handler stopped taking that model, would simply stop contributing a door — the
    endpoint quietly leaves the watched set and every test posting to it passes for the
    wrong reason. So the second return value names each such file, and the test below
    fails on it by name (Pocholo, reviewing the per-door narrowing).

    Ensures:
        - returns ( endpoints, unmatched )
        - endpoints is { full_path: router_filename } for each POST handler whose
          annotated request model declares `parent_id_hash`, joining `prefix=` to the
          post path; a router with no prefix contributes its post paths verbatim
        - unmatched is [ ( filename, why ) ] for each router that mentions the field
          and yields no door at all — never dropped in silence
    """
    endpoints = {}
    unmatched = [ ]
    for name in sorted( os.listdir( router_dir ) ):
        if not name.endswith( ".py" ) or name.startswith( "._" ): continue   # ._ = AppleDouble sidecar, not source
        with open( os.path.join( router_dir, name ), "r", errors="ignore" ) as f: text = f.read()
        if LINEAGE_FIELD not in text: continue
        try:
            tree = ast.parse( text )
        except SyntaxError:                                  # pragma: no cover - no router in the tree fails to parse
            continue
        models = _lineage_models( tree )
        if not models:
            unmatched.append( ( name, "mentions the field but no request model declares it" ) )
            continue
        prefix = PREFIX_RE.search( text )
        prefix = prefix.group( 1 ) if prefix else ""
        matched = False
        for node in ast.walk( tree ):
            if not isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef ) ): continue
            annotated = { arg.annotation.id
                          for arg in list( node.args.args ) + list( node.args.kwonlyargs )
                          if isinstance( arg.annotation, ast.Name ) }
            if not ( annotated & models ): continue
            for decorator in node.decorator_list:
                if not isinstance( decorator, ast.Call ): continue
                for path in _post_paths( decorator ):
                    full = path if path.startswith( "/api/" ) else f"{prefix}{path}"
                    if full.startswith( "/api/" ):
                        endpoints[ full ] = name
                        matched = True
        if not matched:
            unmatched.append( ( name, "declares the field on a model no POST handler takes" ) )
    return endpoints, unmatched


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
    endpoints, unmatched = lineage_aware_endpoints( str( tmp_path ) )
    assert endpoints == {}
    assert unmatched == [], "a router that never mentions the field is not a miss, it is out of scope"


def test_only_the_door_whose_model_declares_the_field_is_lineage_aware( tmp_path ):
    """
    THE CONTROL FOR THE PER-ENDPOINT NARROWING. A router with three doors where only one
    takes the field — the shape of `v2_ask.py`, which is what broke the old per-file rule.

    RED ON REVERT: go back to "every post path in a router that mentions the field" and
    all three doors come back, which is the false accusation this fixed.
    """
    ( tmp_path / "two_doors.py" ).write_text(
        "from pydantic import BaseModel\n"
        "router = APIRouter()\n"
        "class AskRequest( BaseModel ):\n"
        "    question : str = Field( ... )\n"
        "class SubmitRequest( BaseModel ):\n"
        f"    {LINEAGE_FIELD} : Optional[ str ] = Field( None )\n"
        '@router.post( "/api/two/ask" )\n'
        "async def ask( request: AskRequest ): pass\n"
        '@router.post( "/api/two/submit" )\n'
        "async def submit( request: SubmitRequest ): pass\n"
        '@router.post( "/api/two/resume" )\n'
        "async def resume( request: AskRequest ): pass\n"
    )
    endpoints, unmatched = lineage_aware_endpoints( str( tmp_path ) )
    assert endpoints == { "/api/two/submit": "two_doors.py" }
    assert unmatched == [], "one door matched, so the file is understood — the other two are simply not doors"


def test_a_router_that_only_talks_about_the_field_contributes_nothing( tmp_path ):
    """The same lesson as the comment-only control below, one level up: a docstring
    naming the field is not a door that accepts it."""
    ( tmp_path / "prose.py" ).write_text(
        "from pydantic import BaseModel\n"
        "router = APIRouter()\n"
        "class SubmitRequest( BaseModel ):\n"
        "    query : str = Field( ... )\n"
        '@router.post( "/api/prose/submit" )\n'
        "async def submit( request: SubmitRequest ):\n"
        f'    """Someday this may carry {LINEAGE_FIELD}, but today it does not."""\n'
        "    pass\n"
    )
    endpoints, unmatched = lineage_aware_endpoints( str( tmp_path ) )
    assert endpoints == {}
    assert [ f for f, _why in unmatched ] == [ "prose.py" ], "mentioning the field and yielding no door must be REPORTED, not dropped"


def test_the_checker_reports_a_router_whose_model_no_handler_takes( tmp_path ):
    """
    THE CONTROL FOR THE LOUD MISS. The failure mode of a DERIVED set is silence: rename
    the model, or change which model the handler takes, and the door quietly leaves the
    watched set while every test posting to it keeps passing — for the wrong reason.

    RED ON REVERT: go back to `if not models: continue` with nothing recorded, and this
    file disappears from the report with no test saying so.
    """
    ( tmp_path / "orphan.py" ).write_text(
        "from pydantic import BaseModel\n"
        "router = APIRouter()\n"
        "class SubmitRequest( BaseModel ):\n"
        f"    {LINEAGE_FIELD} : Optional[ str ] = Field( None )\n"
        "class SomethingElse( BaseModel ):\n"
        "    query : str = Field( ... )\n"
        '@router.post( "/api/orphan/submit" )\n'
        "async def submit( request: SomethingElse ): pass\n"
    )
    endpoints, unmatched = lineage_aware_endpoints( str( tmp_path ) )
    assert endpoints == {}
    assert [ f for f, _why in unmatched ] == [ "orphan.py" ]


def test_no_router_in_the_tree_is_unmatched():
    """
    Against the REAL tree: every router that mentions the field must yield at least one
    door. A name in this failure is not a style complaint — it is an endpoint that has
    silently stopped being watched.
    """
    _endpoints, unmatched = lineage_aware_endpoints( ROUTER_DIR )
    assert not unmatched, (
        "these routers mention " + LINEAGE_FIELD + " but yield no lineage-aware door, so any "
        "endpoint they own has left the watched set without a word: "
        + "; ".join( f"{f} ({why})" for f, why in unmatched )
    )


def test_the_v2_submit_door_is_lineage_aware_and_its_siblings_are_not():
    """
    Against the REAL router tree, not a synthetic one. `/api/v2/submit` gained the field
    when the nine retiring doors' scheduling and lineage moved onto it; `/api/v2/ask` and
    `/api/v2/resume` never took it and must not be held to it.
    """
    endpoints, _unmatched = lineage_aware_endpoints( ROUTER_DIR )

    assert endpoints.get( "/api/v2/submit" ) == "v2_ask.py"
    assert "/api/v2/ask"    not in endpoints
    assert "/api/v2/resume" not in endpoints
    # and the six v1 doors this file was written for are still watched
    assert endpoints.get( "/api/deep-research/submit" ) == "deep_research.py"
    assert endpoints.get( "/api/swe-team/submit" )      == "swe_team.py"


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
    endpoints, _unmatched = lineage_aware_endpoints( ROUTER_DIR )
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
    endpoints, _unmatched = lineage_aware_endpoints( ROUTER_DIR )
    offenders = untagged_callers( endpoints, PROJECT_ROOT, TEST_DIRS )
    assert not offenders, (
        "these submit to a lineage-aware endpoint without threading "
        f"{LINEAGE_ENV}, so under a monopolize sweep the consumer's Gate B defers them as "
        "foreign and they starve 900s: "
        + "; ".join( f"{f} -> {e}" for f, e in offenders )
        + " — copy the three lines at src/tests/smoke/test_presentation_live_smoke.py:265-267 (row 5ed4f187)."
    )

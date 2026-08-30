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
    The request-model classes in one router: which declare the lineage field, and all of them.

    Ensures:
        - returns ( lineage_models, all_classes ) as two sets of class names
        - lineage_models are those with a `parent_id_hash` annotated attribute
        - all_classes is every class defined in the module, which is what lets the caller
          tell "this door takes a model that is not lineage-aware" (fine) from "this
          door's body could not be read at all" (not fine — see lineage_aware_endpoints)
    """
    models  = set()
    classes = set()
    for node in ast.walk( tree ):
        if not isinstance( node, ast.ClassDef ): continue
        classes.add( node.name )
        for stmt in node.body:
            if isinstance( stmt, ast.AnnAssign ) and isinstance( stmt.target, ast.Name ) \
               and stmt.target.id == LINEAGE_FIELD:
                models.add( node.name )
    return models, classes


def _post_paths( decorator ):
    """Every literal path on one `@router.post( ... )` decorator, or [] if it is not one."""
    func = decorator.func
    if not ( isinstance( func, ast.Attribute ) and func.attr == "post" ): return [ ]
    return [ a.value for a in decorator.args
             if isinstance( a, ast.Constant ) and isinstance( a.value, str ) ]


FRAMEWORK_PARAMS = { "Request", "Response", "BackgroundTasks", "WebSocket", "UploadFile" }


def _takes_an_unreadable_body( node, classes ):
    """
    Whether this handler accepts a body parameter this checker cannot resolve.

    THE DISTINCTION THAT MATTERS, and getting it wrong in either direction breaks the
    check. A tombstone takes NO parameters at all — it reads nothing, so there is no body
    for a lineage field to hide in and it must stay silent. A handler that takes
    `body: dict = Body( ... )` and digs `parent_id_hash` out of it by hand is the real
    hole: it accepts the field, this checker cannot see that it does, and the door
    silently leaves the watched set.

    Requires:
        - node is a FunctionDef / AsyncFunctionDef carrying a @router.post decorator
        - classes is the set of class names defined in the same module

    Ensures:
        - False when no parameter could carry a body — no parameters at all, or every
          parameter is a Depends() injection or a framework type
        - False when some parameter is annotated with a class defined in this module —
          that body WAS read, whatever the answer turned out to be
        - True otherwise: something body-shaped arrives here and this checker cannot say
          what is in it
    """
    for arg, default in _params_with_defaults( node ):
        annotation = arg.annotation
        if isinstance( annotation, ast.Name ):
            if annotation.id in classes:         return False      # read, and understood
            if annotation.id in FRAMEWORK_PARAMS: continue         # not a body
        if isinstance( default, ast.Call ) and _callee_name( default ) == "Depends":
            continue                                               # an injection, not a body
        if annotation is None and default is None:
            continue                                               # bare positional, nothing to read
        return True
    return False


def _params_with_defaults( node ):
    """Pair every parameter with its default, or None — defaults are right-aligned."""
    args     = list( node.args.args ) + list( node.args.kwonlyargs )
    defaults = ( [ None ] * ( len( node.args.args ) - len( node.args.defaults ) ) ) + list( node.args.defaults )
    defaults += list( node.args.kw_defaults )
    return list( zip( args, defaults + [ None ] * ( len( args ) - len( defaults ) ) ) )


def _callee_name( call ):
    """The bare name of whatever a Call node calls, or None."""
    func = call.func
    if isinstance( func, ast.Name ):      return func.id
    if isinstance( func, ast.Attribute ): return func.attr
    return None


# Routes that are NOT DOORS, and never will be — Cheech's ruling, 2026-08-21.
#
# ONLY A PUSHER IS A DOOR. This checker exists to catch an endpoint that PUTS WORK ON THE
# QUEUE while quietly accepting the lineage field, because such an endpoint can be
# submitted to untagged and starve a monopolize sweep's own children. The three routes
# below do not put work on the queue: two are job CONTROL (message a running job, cancel
# one) and the third rebuilds a job from server-side state, which is why it is one of the
# HELD v1 doors rather than a retired one — an HTTP SubmitRequest can say command and args
# but never "resume job X".
#
# They stay v1 and they are not being made doors tonight. Listing them here says that in
# one place instead of leaving it to a heuristic that would have to guess.
#
# ⚠️ ON THE FACTS, none of the three names the lineage field at all today; the only mention
# in queues.py was a tombstone COMMENT. So this list is not describing routes that carry
# the field — it is recording which routes are outside this checker's remit, whatever
# their signature.
#
# ⚠️ WHY THIS IS BELT AND SUSPENDERS RATHER THAN THE FIX. The red that produced this list
# came from ARMING (a comment armed queues.py — see `_mentions_the_field_in_code`), and
# with that fixed these three are unreachable anyway. But the day somebody legitimately
# adds the lineage field to a model in that file, the arming fix stops helping and this
# list is what keeps the accusation from coming back. Both are worth having: one guard
# against prose, one against the heuristic that reads a plain path parameter like
# `job_id: str` as a body it cannot parse.
NOT_A_DOOR = {
    "/api/jobs/{job_id}/message",                   # job control — messages a RUNNING job
    "/api/jobs/{job_id}/cancel",                    # job control — cancels a RUNNING job
    "/api/jobs/{id_hash}/resume-from-checkpoint",   # held v1 door; rebuilds from server state
}


def _mentions_the_field_in_code( tree ):
    """
    Whether a router module names the lineage field in CODE, as opposed to in prose.

    THE DEFECT THIS CLOSES, and it is worth being blunt about: the docstring below has
    always promised that "a file that merely mentions the field in prose" stays silent,
    and the code did not do that. The outer filter was `if LINEAGE_FIELD not in text`, a
    raw substring test over the whole file — comments and docstrings included. Nothing
    caught it because until tonight no router had ever said `parent_id_hash` in prose.

    Then a tombstone comment did. Retiring `/api/push-agentic` left a comment in
    `queues.py` explaining that `parent_id_hash` is available on the new door — one line of
    documentation, no behaviour — and it armed the whole file. The three unrelated POST
    routes that live there (`/api/jobs/{job_id}/message`, `/cancel`,
    `/resume-from-checkpoint`) take bodies this checker cannot read, so all three were
    reported as endpoints that had "silently stopped being watched". None of them had
    moved, been renamed, or lost anything. The accusation came from a sentence.

    WHY THE FIX GOES HERE AND NOT IN THE COMMENT. Rewording the comment would have turned
    the run green in one edit, and left a checker that punishes anyone who documents this
    field near a router. A guard that makes accurate prose dangerous will be satisfied by
    deleting the prose, and the next person pays the same tax without knowing why. The
    checker's own docstring already said what it should do; this makes it true.

    Requires:
        - tree is a parsed module

    Ensures:
        - True when the field appears as an identifier (a model field, an attribute
          access, a parameter) or as a string literal used in an expression, e.g.
          `body.get( "parent_id_hash" )` — the hand-rolled read this checker exists for
        - False when every occurrence is a comment (invisible to ast) or a docstring
    """
    docstrings = set()
    for node in ast.walk( tree ):
        if isinstance( node, ( ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef ) ):
            body = getattr( node, "body", [ ] )
            if body and isinstance( body[ 0 ], ast.Expr ) and isinstance( body[ 0 ].value, ast.Constant ) \
               and isinstance( body[ 0 ].value.value, str ):
                docstrings.add( id( body[ 0 ].value ) )

    for node in ast.walk( tree ):
        if isinstance( node, ast.Name )      and node.id   == LINEAGE_FIELD: return True
        if isinstance( node, ast.Attribute ) and node.attr == LINEAGE_FIELD: return True
        if isinstance( node, ast.arg )       and node.arg  == LINEAGE_FIELD: return True
        if isinstance( node, ast.keyword )   and node.arg  == LINEAGE_FIELD: return True
        if isinstance( node, ast.Constant ) and isinstance( node.value, str ) \
           and node.value == LINEAGE_FIELD and id( node ) not in docstrings:
            return True
    return False


def lineage_aware_endpoints( router_dir ):
    """
    Every POST path whose own handler takes a request model declaring the lineage field.

    ⚠️ THIS USED TO BE A PER-FILE CHECK, AND THAT WENT WRONG THE DAY A ROUTER GREW A
    SECOND DOOR. The rule was "any router mentioning `parent_id_hash` is lineage-aware,
    and every `@router.post` in it is one of its doors" — fine while each router had a
    single submit endpoint, which was true of all six when this was written. `v2_ask.py`
    has three doors and only `/api/v2/submit` takes the field, so the old rule accused
    nine test files of failing to tag `/api/v2/ask` with a field that endpoint does not
    accept and would reject. A checker that names innocent files teaches people to ignore
    it, which costs more than the gap it was watching for.

    So the question is asked per DOOR: does the model in THIS handler's signature declare
    the field? A router-wide mention is not evidence about any one door.

    ⚠️ AND THE SECOND RETURN VALUE IS ALSO PER DOOR, for a reason worth stating because
    an earlier version of this function got it wrong twice. The failure mode of a derived
    set is silence: a door whose model was renamed, or that takes `body: dict = Body(...)`
    and reads the field out by hand, simply stops contributing — it leaves the watched set
    and every test posting to it passes for the wrong reason. Keying that report on the
    FILE hid it whenever a readable door sat beside it; gating it on the file declaring a
    lineage model hid it whenever such a door was the file's ONLY evidence, which is
    precisely the door class it exists for (Pocholo, twice).

    Requires:
        - router_dir holds FastAPI router modules

    Ensures:
        - returns ( endpoints, unmatched )
        - endpoints is { full_path: router_filename } for each POST handler whose
          annotated request model declares `parent_id_hash`, joining `prefix=` to the
          post path; a router with no prefix contributes its post paths verbatim
        - unmatched is [ ( "file::path", why ) ] per DOOR that accepts a body this
          checker cannot read — never per file, never gated on the file's models
        - a handler taking no body at all (a tombstone) is silent, and so is a file that
          merely mentions the field in prose
        - a path listed in NOT_A_DOOR is silent whatever its signature — it does not push
          work onto the queue, so it is not a door this checker is about
    """
    endpoints = {}
    unmatched = [ ]
    for name in sorted( os.listdir( router_dir ) ):
        if not name.endswith( ".py" ) or name.startswith( "._" ): continue   # ._ = AppleDouble sidecar, not source
        with open( os.path.join( router_dir, name ), "r", errors="ignore" ) as f: text = f.read()
        # The outer filter: a file that never mentions the field owns no lineage-aware
        # door and cannot hide one, so the per-door scan below stays narrow.
        #
        # ⚠️ THIS READS CODE, NOT RAW TEXT, and the difference is a real defect this test
        # once had. `LINEAGE_FIELD not in text` armed a file on a COMMENT, and one line of
        # tombstone documentation in `queues.py` made this checker accuse three untouched
        # routes of leaving the watched set. See `_mentions_the_field_in_code`.
        if LINEAGE_FIELD not in text: continue               # cheap pre-filter; the real test is below
        try:
            tree = ast.parse( text )
        except SyntaxError as e:
            # A router that does not parse is a router this checker did not read, so it
            # rides the SAME `unmatched` channel as a door it cannot understand rather
            # than dropping out silently. The pragma stayed: no router in the tree fails
            # to parse today, and the arm is proven by its own fixture test (row 5c3f3d94).
            unmatched.append( ( f"{name}::<unparseable>", f"{type( e ).__name__}: {e}" ) )
            continue
        if not _mentions_the_field_in_code( tree ): continue
        models, classes = _lineage_models( tree )
        prefix = PREFIX_RE.search( text )
        prefix = prefix.group( 1 ) if prefix else ""
        for node in ast.walk( tree ):
            if not isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef ) ): continue
            paths = [ ]
            for decorator in node.decorator_list:
                if isinstance( decorator, ast.Call ): paths += _post_paths( decorator )
            paths = [ p if p.startswith( "/api/" ) else f"{prefix}{p}" for p in paths ]
            paths = [ p for p in paths if p.startswith( "/api/" ) ]
            if not paths: continue
            annotated = { arg.annotation.id
                          for arg in list( node.args.args ) + list( node.args.kwonlyargs )
                          if isinstance( arg.annotation, ast.Name ) }
            if annotated & models:
                for path in paths: endpoints[ path ] = name
            elif paths[ 0 ] in NOT_A_DOOR:
                continue                                 # ruled not a door — see NOT_A_DOOR
            elif _takes_an_unreadable_body( node, classes ):
                unmatched.append( ( f"{name}::{paths[ 0 ]}",
                                    "POST handler takes a body this checker cannot read" ) )
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
    assert unmatched == [], (
        "a file that only TALKS about the field owns no lineage-aware door — reporting it "
        "is the false accusation this checker exists to avoid, and a tombstone comment "
        "naming the field is enough to trigger it" )


def test_a_comment_naming_the_field_does_not_arm_a_router( tmp_path ):
    """
    THE EXACT REGRESSION, and the test above did not catch it because its door was
    READABLE. Reproduce the real shape: a router whose only mention of the field is a
    COMMENT, sitting beside a door whose body this checker cannot read.

    That is `queues.py` after `/api/push-agentic` retired. One line of tombstone
    documentation — "`parent_id_hash` is available now where it was not before" — armed
    the file, and three untouched routes (`/api/jobs/{job_id}/message`, `/cancel`,
    `/resume-from-checkpoint`) were reported as endpoints that had silently stopped being
    watched. Nothing had moved or been renamed. The accusation came from a sentence.

    RED ON REVERT: put the raw `LINEAGE_FIELD not in text` filter back and this fails,
    naming the door it falsely accused. TWO tests fail on that revert — this one and the
    docstring one below. NOT the real-tree check: NOT_A_DOOR silences all three queues.py
    routes now, so the tree stays green whether arming is fixed or not. That is the belt
    doing its job and it is exactly why these two synthetics have to carry the proof.
    """
    # ⚠️ THE PATH IS DELIBERATELY NOT ONE OF THE REAL ROUTES, and getting that wrong is
    # how this test first shipped unable to fail. Written against
    # `/api/jobs/{job_id}/message` it was silenced by NOT_A_DOOR — added in the SAME commit
    # — so reverting the arming fix left it green and the red-on-revert claim was false
    # (Pocholo). A synthetic must exercise ONE guard at a time; `/jobs/{job_id}/frobnicate`
    # is body-shaped to this checker and on nobody's exemption list.
    ( tmp_path / "commented.py" ).write_text(
        "router = APIRouter( prefix=\"/api\" )\n"
        f"# The new door carries {LINEAGE_FIELD} as a top-level field.\n"
        '@router.post( "/jobs/{job_id}/frobnicate" )\n'
        "async def frobnicate( job_id: str, request: Request ):\n"
        "    pass\n"
    )
    endpoints, unmatched = lineage_aware_endpoints( str( tmp_path ) )
    assert endpoints == {}
    assert unmatched == [], (
        "a COMMENT armed the file and the checker accused an untouched route of leaving "
        "the watched set — documentation must be safe to write next to a router" )


def test_a_docstring_naming_the_field_does_not_arm_a_router_either( tmp_path ):
    """The same rule one syntax over: prose is prose whether it is `#` or triple-quoted,
    and a module docstring explaining the field is as innocent as a comment."""
    # Same reason as the test above: a path outside NOT_A_DOOR, so this measures arming
    # and nothing else.
    ( tmp_path / "documented.py" ).write_text(
        f'"""This router used to hand {LINEAGE_FIELD} to the queue by hand."""\n'
        "router = APIRouter( prefix=\"/api\" )\n"
        '@router.post( "/jobs/{job_id}/frobnicate" )\n'
        "async def frobnicate( job_id: str, request: Request ):\n"
        "    pass\n"
    )
    endpoints, unmatched = lineage_aware_endpoints( str( tmp_path ) )
    assert endpoints == {}
    assert unmatched == []


def test_a_ruled_not_a_door_route_stays_silent_even_in_an_armed_file( tmp_path ):
    """
    CHEECH'S RULING, PINNED — and pinned against the case where it actually matters.

    /api/jobs/{job_id}/message, /cancel and /resume-from-checkpoint stay v1 and are NOT
    doors: only an endpoint that PUTS WORK ON THE QUEUE is a door this checker is about.
    Two of them are job control and the third rebuilds a job from server-side state.

    The arming fix alone would make them silent today, because nothing in queues.py names
    the field in code any more. That is not the same as honouring the ruling: the day
    someone legitimately adds the lineage field to a model in that file, arming is correct
    and these three would be accused again. So this test builds an ARMED file — a real
    model declaring the field, a real door beside them — and asserts they stay silent
    anyway. RED ON REVERT: drop the NOT_A_DOOR arm and all three come back.
    """
    ( tmp_path / "queuesish.py" ).write_text(
        "from pydantic import BaseModel\n"
        "router = APIRouter( prefix=\"/api\" )\n"
        "class SubmitRequest( BaseModel ):\n"
        f"    {LINEAGE_FIELD} : Optional[ str ] = Field( None )\n"
        '@router.post( "/v2/submit" )\n'
        "async def submit( request: SubmitRequest ):\n"
        "    pass\n"
        '@router.post( "/jobs/{job_id}/message" )\n'
        "async def message( job_id: str, request: Request ):\n"
        "    pass\n"
        '@router.post( "/jobs/{job_id}/cancel" )\n'
        "async def cancel( job_id: str, request: Request ):\n"
        "    pass\n"
        '@router.post( "/jobs/{id_hash}/resume-from-checkpoint" )\n'
        "async def resume( id_hash: str, request: Request ):\n"
        "    pass\n"
    )
    endpoints, unmatched = lineage_aware_endpoints( str( tmp_path ) )
    assert endpoints == { "/api/v2/submit": "queuesish.py" }, (
        "the real door beside them must still be watched — a ruling that silenced the "
        "whole file would be an exemption, not a classification" )
    assert unmatched == [], (
        "a route ruled NOT a door must stay silent even when its file is legitimately "
        "armed; only an endpoint that pushes work onto the queue is a door" )


def test_a_hand_rolled_read_still_arms_the_router( tmp_path ):
    """
    THE CONTROL THAT KEEPS THE FIX HONEST, and without it the change above would be
    indistinguishable from switching the checker off. The hole this whole file exists for
    is a door that digs the field out of a raw body by hand: it ACCEPTS the field, the
    checker cannot see the model, and the door leaves the watched set in silence.

    That read is `body.get( "parent_id_hash" )` — a string literal in an expression, not a
    docstring — so it still arms the file and the unreadable door is still reported.
    Blinding the checker to comments must not blind it to code.

    The door here takes `body: dict = Body( ... )` on purpose. A handler annotated
    `request: Request` is FRAMEWORK-EXEMPT and is never reported however it reads the body,
    so writing this control that way would have made it pass for the wrong reason — it
    would have proved the exemption, not the arming.
    """
    ( tmp_path / "handrolled.py" ).write_text(
        "router = APIRouter( prefix=\"/api\" )\n"
        '@router.post( "/jobs/raw" )\n'
        "async def raw( body: dict = Body( ... ) ):\n"
        f'    lineage = body.get( "{LINEAGE_FIELD}" )\n'
        "    return lineage\n"
    )
    endpoints, unmatched = lineage_aware_endpoints( str( tmp_path ) )
    assert endpoints == {}
    assert unmatched == [ ( "handrolled.py::/api/jobs/raw",
                            "POST handler takes a body this checker cannot read" ) ]


def test_the_checker_reports_a_door_it_could_not_read( tmp_path ):
    """
    THE CONTROL FOR THE LOUD MISS, and it is per DOOR. The failure mode of a derived set
    is silence: a second submit-shaped handler written in a different style — a string
    annotation, a `Body(...)`, a bare dict — could take the lineage field and never be
    watched, while the readable door beside it made the FILE look understood.

    RED ON REVERT: key the report on the file again, and `/api/two/raw` vanishes from it
    because `/api/two/submit` matched.
    """
    ( tmp_path / "mixed.py" ).write_text(
        "from pydantic import BaseModel\n"
        "router = APIRouter()\n"
        "class SubmitRequest( BaseModel ):\n"
        f"    {LINEAGE_FIELD} : Optional[ str ] = Field( None )\n"
        '@router.post( "/api/two/submit" )\n'
        "async def submit( request: SubmitRequest ): pass\n"
        '@router.post( "/api/two/raw" )\n'
        "async def raw( body: dict = Body( ... ) ): pass\n"
    )
    endpoints, unmatched = lineage_aware_endpoints( str( tmp_path ) )

    assert endpoints == { "/api/two/submit": "mixed.py" }
    assert [ f for f, _why in unmatched ] == [ "mixed.py::/api/two/raw" ], (
        "the readable door must not silence the report for the one beside it" )


def test_a_door_taking_a_model_that_is_simply_not_lineage_aware_is_not_reported( tmp_path ):
    """
    The other side of that line, and the reason the check asks about ALL local classes
    rather than only the lineage ones. `/api/v2/ask` takes AskRequest: the checker read
    that door and the answer was no. Reporting it would be the same false accusation the
    per-door narrowing was written to stop, wearing the loud-miss costume.
    """
    ( tmp_path / "siblings.py" ).write_text(
        "from pydantic import BaseModel\n"
        "router = APIRouter()\n"
        "class AskRequest( BaseModel ):\n"
        "    question : str = Field( ... )\n"
        "class SubmitRequest( BaseModel ):\n"
        f"    {LINEAGE_FIELD} : Optional[ str ] = Field( None )\n"
        '@router.post( "/api/sib/ask" )\n'
        "async def ask( request: AskRequest ): pass\n"
        '@router.post( "/api/sib/submit" )\n'
        "async def submit( request: SubmitRequest ): pass\n"
    )
    endpoints, unmatched = lineage_aware_endpoints( str( tmp_path ) )

    assert endpoints == { "/api/sib/submit": "siblings.py" }
    assert unmatched == []


def test_a_lone_unreadable_door_is_reported_even_with_no_model_in_the_file( tmp_path ):
    """
    THE CASE THE PREVIOUS FIX RE-OPENED, and the reason the per-door scan is no longer
    behind a "does this file declare a lineage model" gate. A handler that takes
    `body: dict = Body( ... )` and digs the field out by hand IS a lineage-aware door —
    it just is not one this checker can read. Gating the scan on the file declaring a
    model meant that door was reported only when some OTHER model in the same file
    happened to declare the field, and was silent when it was the file's only evidence,
    which is precisely the door class the check exists for (Pocholo, measured).

    RED ON REVERT: put `if not models: continue` back above the door loop and this goes
    silent while every other test here stays green.
    """
    ( tmp_path / "lone_raw.py" ).write_text(
        "from fastapi import APIRouter, Body\n"
        "router = APIRouter()\n"
        '@router.post( "/api/lone/submit" )\n'
        "async def submit( body: dict = Body( ... ) ):\n"
        f'    parent = body.get( "{LINEAGE_FIELD}" )\n'
        "    return parent\n"
    )
    endpoints, unmatched = lineage_aware_endpoints( str( tmp_path ) )

    assert endpoints == {}
    assert [ f for f, _why in unmatched ] == [ "lone_raw.py::/api/lone/submit" ]


def test_a_tombstone_that_reads_no_body_is_silent( tmp_path ):
    """
    The other half, and it is the half a blunt fix breaks. A retired door takes NO
    parameters at all: there is no body for the field to hide in, so it must stay quiet —
    even though its tombstone comment names the field, which is exactly what the first
    submit-shaped retirement wrote and what put this checker onto its own author.
    """
    ( tmp_path / "tombstone.py" ).write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        f"# the caller now sends {LINEAGE_FIELD} to /api/v2/submit instead\n"
        '@router.post( "/api/dead/submit" )\n'
        "async def dead(): pass\n"
    )
    endpoints, unmatched = lineage_aware_endpoints( str( tmp_path ) )

    assert endpoints == {}
    assert unmatched == []


def test_a_door_taking_only_injected_dependencies_is_silent( tmp_path ):
    """A handler whose every parameter is a Depends() injection reads no body either.
    Without this, hoisting the scan would flood the report with routers that never took
    a body at all."""
    ( tmp_path / "injected.py" ).write_text(
        "from fastapi import APIRouter, Depends\n"
        "router = APIRouter()\n"
        f"# mentions {LINEAGE_FIELD} in passing\n"
        '@router.post( "/api/inject/go" )\n'
        "async def go( current_user: dict = Depends( get_current_user ), q = Depends( get_queue ) ): pass\n"
    )
    endpoints, unmatched = lineage_aware_endpoints( str( tmp_path ) )

    assert endpoints == {}
    assert unmatched == []


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

    # The v1 doors still LIVE are still watched. This used to name the research doors as
    # its examples; they retired, their models went with their handlers, and they left the
    # set — correctly, since a tombstone reads no body and there is nowhere for the field
    # to hide in it. A retired door leaving here is the system working, not a gap.
    # NOTHING LIVE IS LEFT TO NAME HERE. swe-team was the last lineage-aware v1 door, and
    # its retirement leaves /api/v2/submit as the only one — which is the point of the
    # cutover rather than a gap in this check. The assertion above already pins it.
    for retired in ( "/api/deep-research/submit",
                     "/api/deep-research-to-podcast/submit",
                     "/api/deep-research-to-presentation/submit",
                     "/api/bug-fix-expediter/submit",
                     "/api/presentation-generator/submit",
                     "/api/podcast-generator/submit",
                     "/api/swe-team/submit" ):
        assert retired not in endpoints, f"{retired} is a tombstone and reads no body"


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
        - the derived set is non-empty and contains doors that are still LIVE

    The named examples are live doors on purpose. Naming a retired one would make this
    guard fail the day that door was tombstoned — which is a real event correctly handled,
    not a rotted parse, and the two are worth telling apart.
    """
    endpoints, _unmatched = lineage_aware_endpoints( ROUTER_DIR )
    assert endpoints, "derived ZERO lineage-aware endpoints — the router parse has rotted"
    assert "/api/v2/submit" in endpoints


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

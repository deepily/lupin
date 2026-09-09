#!/usr/bin/env python3
"""
THE OPT-IN IS THE DEFAULT AT ONE DOOR, AND THE BROWSER CANNOT REACH IT.

Row `8ed76594`. Prior rows: `3493ae9b` (the async path itself), `96cf5cec` (the read
timeout this exists to kill).

🔴 WHAT THIS FILE IS FOR, AND IT IS NOT "the 202 works" — `test_the_asynchronous_
promotion_resolves_or_shouts.py` already owns that. Both gates were built, both were
measured open, and for a day NOBODY WALKED THROUGH: the only `asynchronous=True` anywhere
in the tree was a docstring. A capability every caller must REMEMBER to ask for is a
capability nobody uses. So the MCP verb now opts in BY DEFAULT, and the two claims that
makes safe are the ones below.

CLAIM 1 — EXACTLY ONE CALLER OPTED IN. The default lives on the `@mcp.tool` verb
`task_transition`, deliberately NOT on `task_transition_impl`, because `session_spawner`
calls that impl too. Moving the default down one layer would opt IT in as well, and "one
caller, and nothing else" was the condition this shipped under (Mr. Radio, 2026-09-09).

CLAIM 2 — THE BROWSER CANNOT OPT IN, AND THE TWO CLIENT LAYERS EARN THAT DIFFERENTLY.
The TYPED layer (the multiplexer's `.ts`) types its extras `Record<string, string | null>`,
so a boolean cannot be placed in one — unreachable BY CONSTRUCTION. **The probe asks
`tsc`, it does not restate the type**: two pieces of code deciding one rule agree right up
until they do not, and a regex asserting the type is exactly the restatement that goes off
by one.

🔴 THE UNTYPED LAYER IS UNREACHABLE BY ABSENCE, WHICH IS A WEAKER PROPERTY, AND SAYING SO
IS THE POINT. `notifications.js` is vanilla JS with no type system at all and holds a
THIRD transition call site — `_transitionTask( taskId, toStatus, extras = {} )`, which
spreads `...extras` into the body and returns `{ ok: true }` for any 2xx. Nothing there
STOPS an opt-in; today there simply is not one. So that layer gets an absence arm, and the
arm is labelled as an absence rather than dressed up as a guarantee.

⚠️ AND ITS DEFECT SHAPE IS MILDER THAN `TaskListStore`'S, measured rather than assumed:
neither untyped call site writes an optimistic row. One re-reads the pane
(`if ( result.ok ) await this.refreshTaskList()`), the other advances a batch counter. A
202 there would over-report success and then repaint the row's REAL state — bad, but not
the "approved and stays approved" false fact that `TaskListStore.ts:229` produces.

⚠️ AND ITS CONTROL IS THE HALF THAT MATTERS. A *string* `"true"` COMPILES CLEAN — that is
Tiffany 💍's finding, and it is why the server's `StrictBool` is the real defence and the
type system is only the reason no client sends one today. An unreachability guard whose
control did not compile would be measuring a broken probe.

⚠️ THIS FILE NEEDS `node_modules` AND WILL FAIL LOUDLY WITHOUT IT rather than skip. A
guard that reports a clean nothing when it checked nothing prints exactly what a clean
tree prints. In a worktree, borrow the artifacts first:
`src/scripts/link-worktree-artifacts.sh <worktree>`.

🔴 EVERY ARM HERE WAS CHECKED AGAINST THE PENDING MERGE, so the next reader does not have
to. Commit `b76fe07b` (branch `john-202-is-not-a-success`, unmerged at the time of writing)
rewrites `TaskListStore.ts`, `HoldingAreaStore.ts` and `notifications.js` — the three files
these arms read. Measured against ITS versions of those files, 2026-09-09:

| arm | post-merge |
|---|---|
| the typed census | **survives** — both stores keep exactly 2 `Record<string, string | null>` annotations (a markdown pipe would need escaping; the table cell keeps it bare on purpose) |
| the untyped absence arm | **survives** — 0 non-comment `asynchronous` uses, and `park_reason` (its control) still present |
| the tsc probe | **survives by construction** — its outcome depends only on the `extras` annotation, and that is byte-identical |

⚠️ WHAT DOES *NOT* SURVIVE IS A SENTENCE, NOT AN ARM. `notifications.js` at `b76fe07b`
DOES discriminate `response.status === 202` (verified), so any prose here describing that
file as reading every 2xx as success is true of `b26c32ee` only. The arms are sha-robust;
the narration around them is sha-bound, and that asymmetry is worth knowing which way round
it runs.

VENUE: `:7999`. Reads source, and runs `tsc --noEmit` on a probe written to pytest's own
`tmp_path`. No persistent-state mutation, no writes inside the repo, ~1s, no monopoly.
"""
import ast
import json
import os
import re
import subprocess

import pytest

LUPIN_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )

MCP_VERBS_PATH = os.path.join( LUPIN_ROOT, "src", "lupin_mcp", "cosa_voice_mcp.py" )
IMPL_PATH      = os.path.join( LUPIN_ROOT, "src", "lupin_mcp", "task_store_tools.py" )
SPAWNER_PATH   = os.path.join( LUPIN_ROOT, "src", "lupin_mcp", "session_spawner.py" )
TSC_PATH       = os.path.join( LUPIN_ROOT, "node_modules", ".bin", "tsc" )
BASE_TSCONFIG  = os.path.join( LUPIN_ROOT, "tsconfig.json" )
MUX_ROOT       = os.path.join( LUPIN_ROOT, "src", "lupin_app", "static", "js", "multiplexer" )
# The UNTYPED client layer — no type system, so no compiler arm is possible here.
NOTIFICATIONS_JS = os.path.join( LUPIN_ROOT, "src", "lupin_app", "static", "js",
                                 "notifications.js" )

# An `extras` PARAMETER'S DECLARED TYPE. Deliberately not a `transitionTask` line search:
# the declaration spans several lines in both renderers while the invocation sits on one,
# so a line-based search finds the call and misses the type it was asked about.
ANNOTATION_RE  = re.compile( r"extras\s*:\s*([A-Za-z_$][\w$]*(?:<[^>]*>)?)" )


# ═══════════════════════════════════════════════════════════════════════════════════
# The reader — AST, not regex, so a docstring cannot satisfy an arm about a default
# ═══════════════════════════════════════════════════════════════════════════════════

def _defaults_of( path, func_name ):
    """
    Every keyword default on one function, read from the parse tree.

    Requires:
        - path is a readable Python source file
        - func_name names exactly one top-level `def` in it

    Ensures:
        - returns { arg_name: literal_default } for every argument that HAS a default
        - an argument with no default is absent from the mapping, never present as None
          (that distinction is the whole point here: `None` is itself a default value)

    Raises:
        - AssertionError if the function is absent, or defined more than once — a reader
          that silently picked one of two `def`s would report a true fact about the
          wrong function
    """
    tree  = ast.parse( open( path, encoding="utf-8" ).read(), filename=path )
    found = [ n for n in ast.walk( tree )
              if isinstance( n, ( ast.FunctionDef, ast.AsyncFunctionDef ) )
              and n.name == func_name ]
    assert len( found ) == 1, (
        f"expected exactly one `def {func_name}` in {os.path.basename( path )}, found "
        f"{len( found )} — this reader cannot say which one the server mounts" )

    fn        = found[ 0 ]
    args      = fn.args.args + fn.args.kwonlyargs
    defaults  = list( fn.args.defaults ) + list( fn.args.kw_defaults )
    # `args.defaults` right-aligns against positional args; kwonly is 1:1 and may hold
    # None for "no default". Pair them the way the grammar does rather than by index.
    positional = fn.args.args
    pos_pairs  = list( zip( positional[ len( positional ) - len( fn.args.defaults ): ],
                            fn.args.defaults ) )
    kw_pairs   = [ ( a, d ) for a, d in zip( fn.args.kwonlyargs, fn.args.kw_defaults )
                   if d is not None ]
    return { a.arg: ast.literal_eval( d ) for a, d in pos_pairs + kw_pairs }


# ═══════════════════════════════════════════════════════════════════════════════════
# 1 · THE DOOR OPTS IN
# ═══════════════════════════════════════════════════════════════════════════════════

def test_the_MCP_verb_DEFAULTS_the_opt_in_ON():
    """
    🔴 THE ARM THAT IS THE WHOLE ROW. `asynchronous` existed on this verb, wired all the
    way through, defaulting to None — and so every promotion in the fleet took the
    synchronous path that times out at 10s and then answers 422 to the retry.

    ⚠️ AND DO NOT ADD A BEHAVIOURAL TWIN OF THIS — ONE ALREADY EXISTS. This arm proves the
    default is WRITTEN; that the default TRAVELS is proven in
    `test_cosa_voice_task_store_wrappers.py::TestTaskTransitionWrapper::test_stamps_actor_and_passes_through`,
    which calls the verb WITHOUT mentioning `asynchronous` and asserts by exact dict equality
    that `asynchronous: True` arrives at the impl. (That test went red when this default
    flipped, which is how it earns the claim.) Two arms, two different questions — a third
    would measure neither. I nearly wrote one, having just been caught doing exactly this on
    the optimistic-row guard.
    """
    default = _defaults_of( MCP_VERBS_PATH, "task_transition" ).get( "asynchronous" )
    assert default is True, (
        f"the MCP `task_transition` verb defaults `asynchronous` to {default!r}. Unless "
        f"it is True, every caller must remember to opt in, and the measurement on row "
        f"8ed76594 is that none of them do." )


def test_the_reader_reports_the_OTHER_defaults_ON_THAT_SAME_VERB_correctly():
    """
    POSITIVE CONTROL ON THE INSTRUMENT. A reader that returned True for anything it was
    asked about would satisfy the arm above. These two are read from the same parse of the
    same function, and neither is True.
    """
    defaults = _defaults_of( MCP_VERBS_PATH, "task_transition" )
    assert defaults[ "authority" ]   == "standing", defaults
    assert defaults[ "park_reason" ] is None,       defaults
    assert "task_id" not in defaults, (
        "the reader invented a default for a required argument, so an absent default and "
        "a `None` default are indistinguishable to it" )


# ═══════════════════════════════════════════════════════════════════════════════════
# 2 · ONE CALLER OPTED IN, AND NOT TWO
# ═══════════════════════════════════════════════════════════════════════════════════

def test_the_impl_still_DEFAULTS_TO_OMITTING_so_the_seam_is_the_verb():
    """
    🔴 THE ARM THAT KEEPS THE OPT-IN AT ONE CALLER. `task_transition_impl` has a second
    caller — `session_spawner` — and its request must stay byte-identical to today's.
    Move this default to True and the opt-in widens silently to a caller nobody reviewed.
    """
    default = _defaults_of( IMPL_PATH, "task_transition_impl" ).get( "asynchronous", "ABSENT" )
    assert default is None, (
        f"`task_transition_impl` defaults `asynchronous` to {default!r}. The opt-in is "
        f"supposed to live on the MCP verb ALONE; this default hands it to every caller "
        f"of the impl, including session_spawner's `->done` close during spawn." )


def test_the_session_spawner_call_does_NOT_mention_the_opt_in():
    """
    The claim above is about a default; this one is about the OTHER caller actually
    staying silent. Both are needed — a caller could pass `asynchronous=True` explicitly
    and the impl's default would still read None.

    Its own positive control is inline: the same call IS asserted to pass `receipt_refs`,
    so a reader that found no keywords at all would fail here rather than pass.
    """
    tree = ast.parse( open( SPAWNER_PATH, encoding="utf-8" ).read(), filename=SPAWNER_PATH )
    calls = [ n for n in ast.walk( tree )
              if isinstance( n, ast.Call )
              and isinstance( n.func, ast.Attribute )
              and n.func.attr == "task_transition_impl" ]
    assert calls, (
        "no call to `task_transition_impl` was found in session_spawner.py — this arm's "
        "subject has moved, and an absent call reads the same as a silent one" )

    for call in calls:
        keywords = { kw.arg for kw in call.keywords }
        assert "receipt_refs" in keywords, (
            f"the reader found a task_transition_impl call carrying {sorted( keywords )} "
            f"— it is not seeing keywords, so its silence about `asynchronous` is worth "
            f"nothing" )
        assert "asynchronous" not in keywords, (
            "session_spawner opts into the 202 path. It closes rows during session "
            "spawn; a 25s poll budget belongs to an interactive verb, not to that." )


# ═══════════════════════════════════════════════════════════════════════════════════
# 3 · THE BROWSER CANNOT OPT IN — AND THE COMPILER IS ASKED, NOT QUOTED
# ═══════════════════════════════════════════════════════════════════════════════════

def _typecheck( tmp_path, extras_literal ):
    """
    Run the REPO'S OWN tsc over a probe that assigns `extras_literal` to the real client
    transition surface, and return its output.

    Requires:
        - node_modules/.bin/tsc and the repo tsconfig.json are both present

    Ensures:
        - the probe inherits the repo's real compilerOptions via `extends`, so this arm
          cannot drift from the settings the typecheck gate actually enforces
        - returns tsc's combined stdout+stderr verbatim (empty means it compiled)

    Raises:
        - AssertionError, naming the remedy, if tsc or the tsconfig is missing. A guard
          that skipped here would print what a passing guard prints.
    """
    assert os.path.isfile( BASE_TSCONFIG ), (
        f"REFUSING: no tsconfig.json at {BASE_TSCONFIG}. Nothing was checked." )
    assert os.access( TSC_PATH, os.X_OK ), (
        f"REFUSING: no executable tsc at {TSC_PATH}. Nothing was checked. In a worktree "
        f"this means node_modules was never borrowed — run "
        f"src/scripts/link-worktree-artifacts.sh <worktree> first." )

    store = os.path.join( MUX_ROOT, "stores", "TaskListStore" )
    ( tmp_path / "probe.ts" ).write_text(
        f'import type {{ TaskListStore }} from "{store}";\n'
        f'declare const store: TaskListStore;\n'
        f'store.transitionTask( "id", "queued", {extras_literal} );\n',
        encoding="utf-8" )
    # `rootDir: "/"` because the probe lives outside the repo (pytest's tmp_path) while
    # its imports live inside it, and the inherited rootDir would call that TS6059. It
    # is an EMIT-layout key and this project is noEmit, so it changes no check.
    ( tmp_path / "tsconfig.json" ).write_text( json.dumps( {
        "extends"         : BASE_TSCONFIG,
        "compilerOptions" : { "noEmit": True, "rootDir": "/" },
        "include"         : [ "probe.ts" ],
    } ), encoding="utf-8" )

    return subprocess.run( [ TSC_PATH, "--noEmit", "-p", str( tmp_path / "tsconfig.json" ) ],
                           cwd=LUPIN_ROOT, capture_output=True, text=True,
                           timeout=120 ).stdout


def test_a_BOOLEAN_is_REFUSED_BY_THE_COMPILER_on_the_client_transition_surface( tmp_path ):
    """
    🔴 THE UNREACHABILITY GUARD (Mr. Radio's condition, 2026-09-09). The row asks for a
    test that a 202 leaves no optimistic "approved" row behind. That defect is currently
    UNREACHABLE rather than merely unguarded — no client can opt in — and driving a 202
    into `TaskListStore` would mean BUILDING the opt-in into the browser first, in order
    to guard it. This pins the unreachability instead, so the day someone widens that
    type a named test reddens and the optimistic-row arm becomes owed.
    """
    out = _typecheck( tmp_path, "{ asynchronous: true }" )
    assert "error TS2322" in out and "boolean" in out, (
        f"a real boolean was ACCEPTED by the client transition surface. The optimistic "
        f"'approved' row defect is now reachable from the browser and this file's "
        f"argument for not guarding it has expired. tsc said:\n{out or '(nothing)'}" )


def test_a_STRING_COMPILES_which_is_why_the_SERVER_is_the_real_defence( tmp_path ):
    """
    🔴 THE CONTROL, AND THE MORE IMPORTANT HALF. Tiffany 💍 killed the original overclaim
    that the client's type system stopped this: `Record<string, string | null>` carries
    the STRING "true" perfectly well. So the compiler refusal above is about ONE shape,
    the server's `StrictBool` is what refuses the other, and without this arm the arm
    above would also pass against a probe harness that simply cannot compile anything.
    """
    out = _typecheck( tmp_path, '{ asynchronous: "true" }' )
    assert out.strip() == "", (
        f"the probe harness cannot compile even a well-typed extras map, so the boolean "
        f"refusal above proves nothing about booleans. tsc said:\n{out}" )


@pytest.mark.parametrize( "relative_path", [
    os.path.join( "render", "taskVerbs.ts" ),          # the PRODUCER of the extras map
    os.path.join( "stores", "TaskListStore.ts" ),
    os.path.join( "stores", "HoldingAreaStore.ts" ),
    os.path.join( "render", "TaskListRenderer.ts" ),
    os.path.join( "render", "HoldingAreaRenderer.ts" ),
] )
def test_every_client_transition_DECLARATION_types_its_extras_string_only( relative_path ):
    """
    THE DENOMINATOR ARM. The compiler probe above interrogates ONE surface,
    `TaskListStore`. A second store declared with a wider extras type would leave that
    probe green and the browser able to opt in — so this states how many transition
    surfaces exist and watches all of them, rather than reporting on the one that
    happened to get tested.

    ⚠️ IT IS A SOURCE READ AND THEREFORE THE WEAKER INSTRUMENT — that is why the arm
    above asks tsc. This one is here for BREADTH, and its parametrize list is the
    denominator: five files, seven annotations, and a sixth added on disk is invisible to
    it until someone adds it here.

    🔴 THE LIST BELOW WAS WRITTEN WITH FOUR FILES IN IT AND THE CENSUS ARM CAUGHT IT.
    `taskVerbs.ts` — which BUILDS the map every one of the others receives — was missing.
    That is the receipt that the census discriminates rather than agreeing with whatever
    it is handed. `test_the_transition_surface_is_still_FIVE_FILES` is what fires then.
    """
    source = open( os.path.join( MUX_ROOT, relative_path ), encoding="utf-8" ).read()
    # The ANNOTATION, never the call site. A line-based `transitionTask` search catches
    # `await this.store.transitionTask( id, needs.status, extras )` — an invocation, which
    # carries no type and would fail an arm about types. Measured: it did.
    annotations = ANNOTATION_RE.findall( source )
    assert annotations, (
        f"{relative_path} was named as a transition surface and annotates no `extras` "
        f"parameter — the list in this test is stale, and a guard reading a file that has "
        f"moved on reports a clean nothing" )
    for declared in annotations:
        assert declared == "Record<string, string | null>", (
            f"{relative_path} annotates an extras parameter as `{declared}`. A non-string "
            f"value can now reach the transition body, so `asynchronous: true` may be "
            f"reachable from the browser. The optimistic-'approved' arm for that door is "
            f"already WRITTEN — task_list_store_202_leaves_no_optimistic_approval.test.ts, "
            f"commit b76fe07b, HELD on Rick's ruling — so this red means its hold needs "
            f"revisiting, NOT that a new arm needs writing." )


def test_the_UNTYPED_client_layer_does_not_opt_in_EITHER():
    """
    🔴 THE THIRD CALL SITE, WHICH THE TYPED CENSUS ABOVE CANNOT SEE. `notifications.js` is
    vanilla JS with no type system, and its `_transitionTask( taskId, toStatus, extras = {} )`
    spreads `...extras` straight into the request body. Found because Mr. Radio 🦉 asked for
    a client-side sweep before this row closed (2026-09-09); the census above walks only the
    multiplexer `.ts` tree, and my own docstring had claimed every client surface was typed.

    🔴 AND THIS ARM IS SHA-BOUND, WHICH IS THE PART TO CARRY FORWARD. Measured at
    `b26c32ee`, where that method reads `if ( response.ok ) return { ok: true }`. Commit
    `b76fe07b` — unmerged, branch `john-202-is-not-a-success` — CHANGES IT to discriminate
    on `response.status === 202` and answer `{ ok: false, pending: true, ticketId }`, and
    ships its own guard `src/tests/unit/notifications_js/the_202_is_not_a_success.test.ts`.
    So the "reads any 2xx as success" half of this arm's rationale expires the moment that
    branch lands; the ABSENCE half below is what still holds either way.

    ⚠️ THIS IS AN ABSENCE ARM AND IT IS WEAKER THAN THE COMPILER ARM, WHICH IS WHY IT SAYS
    SO IN ITS NAME. There is no type to widen here and therefore nothing to refuse: the
    property is "nobody has added an opt-in", not "an opt-in cannot be added". A guard that
    called that unreachability would be handing the next reader a guarantee it does not have.

    ⚠️ ITS OWN INSTRUMENT IS CONTROLLED. `park_reason` is asserted present in the same file,
    because a search that finds no transition fields AT ALL would satisfy this arm while
    measuring nothing but a bad path.

    Measured 2026-09-09: `asynchronous` appears twice in that file, both times as prose in a
    comment ("asynchronous execution via the CJ Flow queue", "asynchronously — re-walking").
    A hit is not a use, so the substring alone is not the assertion — the two known prose
    lines are subtracted and what must be zero is what remains.
    """
    source = open( NOTIFICATIONS_JS, encoding="utf-8" ).read()

    assert "park_reason" in source, (
        f"{os.path.basename( NOTIFICATIONS_JS )} carries no `park_reason` — this arm is "
        f"reading the wrong file, and its silence about `asynchronous` means nothing" )

    # A USE, not a hit: the field would have to appear as a JSON key or an object property.
    uses = [ line.strip() for line in source.splitlines()
             if "asynchronous" in line and not line.strip().startswith( ( "*", "//", "/*" ) ) ]
    assert uses == [], (
        f"the untyped client layer now mentions `asynchronous` outside a comment:\n"
        + "\n".join( f"    {u}" for u in uses )
        + f"\nIf that is a real opt-in, this layer can now receive a 202 — and whether "
          f"that is a defect depends on whether commit b76fe07b has landed, since it is "
          f"what teaches this file to discriminate a 202 from a 200. Check that first; the "
          f"absence this arm relied on is gone either way." )


def test_the_transition_surface_is_still_FIVE_FILES():
    """
    🔴 THE ARM THAT CATCHES A SIXTH SURFACE, AND IT HAS ALREADY EARNED ITS KEEP: the list
    above was written with four entries and this arm named the fifth. Enumerate the
    surface, not the traffic — a list somebody maintains is silent about what is not on
    it. This counts what is actually on disk and fails when the two disagree.
    """
    declaring = sorted(
        os.path.relpath( os.path.join( where, name ), MUX_ROOT )
        for where, _, names in os.walk( MUX_ROOT )
        for name in names
        if name.endswith( ".ts" ) and "testkit" not in where
        and ANNOTATION_RE.search( open( os.path.join( where, name ), encoding="utf-8" ).read() )
    )
    expected = sorted( [
        os.path.join( "render", "taskVerbs.ts" ),
        os.path.join( "stores", "TaskListStore.ts" ),
        os.path.join( "stores", "HoldingAreaStore.ts" ),
        os.path.join( "render", "TaskListRenderer.ts" ),
        os.path.join( "render", "HoldingAreaRenderer.ts" ),
    ] )
    assert declaring == expected, (
        f"the client transition surface changed.\n  on disk : {declaring}\n  watched : "
        f"{expected}\nAdd the new file to "
        f"`test_every_client_transition_DECLARATION_types_its_extras_string_only` and "
        f"check its extras type before doing so — an unwatched transition surface is how "
        f"the opt-in reaches a browser." )


def quick_smoke_test():
    """Non-destructive: run the AST arms only, no tsc, no server."""
    print( "Opt-in default at the MCP door..." )
    print( f"  task_transition.asynchronous       = "
           f"{_defaults_of( MCP_VERBS_PATH, 'task_transition' ).get( 'asynchronous' )!r}" )
    print( f"  task_transition_impl.asynchronous  = "
           f"{_defaults_of( IMPL_PATH, 'task_transition_impl' ).get( 'asynchronous' )!r}" )


if __name__ == "__main__":
    quick_smoke_test()

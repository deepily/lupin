"""
Step 12 THROUGH-PATH: the six internal callers go through `flow.submit()`.

WHAT STEP 12 SAYS. Sixteen doors die and their callers move to `/api/v2/submit`, but
six callers have NO endpoint to disable — they push work onto the queue from inside the
process. They must reach `flow.submit()` like everyone else, and `job_persistence:830`
— the boot-time catch-up restore — is RULED IN by Rick precisely because it is *"the
caller least likely to be noticed misbehaving: startup, unattended, re-enqueueing work
an interruption left behind."*

⚠️ RUN THIS FILE SCOPED — `pytest src/tests/unit/...`, never a bare `pytest` from the
repo root. An unscoped run collects `src/tmp/`, and `src/tmp/test_fastapi_integration.py`
calls `sys.exit( 1 )` from an `except ImportError` handler AT IMPORT TIME, which pytest
reports as INTERNALERROR before any test runs. The import it fails on is
`from fastapi_app.main import lifespan` — a module that no longer exists under that name
— so the exit is guaranteed, not occasional. `src/tmp/` is UNTRACKED scratch (git ls-files
returns nothing for it); it is present in a worktree only because the git-ignored files
have to be copied in for eleven unit tests to pass. The project's own tier command already
scopes to `src/tests/unit`, so this bites only ad-hoc runs. (Rachel, 2026-08-21;
verified here.) The sweep below walks the tree itself and excludes `tmp` explicitly, so
the test is unaffected either way.

LIVE AS OF STEP 12 (2026-08-21). The three skip marks came off with the commit that
routed the seven sites; the file was written held-out because every assertion was red
until `flow.submit()` / `flow.ask()` existed and the flow was built in lifespan.

THE SIX, RE-VERIFIED AT HEAD `efadc2bc` RATHER THAN COPIED FROM THE PLAN — the plan's
line numbers were written this morning and one path in it was wrong:

    src/cosa/rest/dead_queue_watchdog.py:486             self.todo_queue.push( bfe_job )
    src/cosa/rest/test_suite_completion_watchdog.py:282  self.todo_queue.push( tfe_job )
    src/cosa/rest/job_persistence.py:830                 todo_queue.push( job )
    src/cosa/rest/arbiter_bootstrap.py:184               todo_queue.push( job )
    src/cosa/agents/test_fix_expediter/orchestrator.py:2174  todo_queue.push( validation_job )
    src/cosa/agents/bug_fix_expediter/job.py:586         todo_queue.push( new_job )

⚠️ `arbiter_bootstrap.py` lives under `src/cosa/rest/`, NOT `src/lupin_app/`. Every
other line number checked out exactly.

🔴 IT IS SEVEN SITES, NOT SIX, AND THEY ARE TWO SHAPES — Rachel's recon, ruled by Cheech
2026-08-21 13:04, and measured here independently at HEAD before being written down. The
plan counts SIX because it counts FILES; `dead_queue_watchdog` carries ONE OF EACH SHAPE.

    SHAPE A — a PREBUILT JOB, `todo_queue.push( job )` => becomes `flow.submit()`
        dead_queue_watchdog.py:486            self.todo_queue.push( bfe_job )
        test_suite_completion_watchdog.py:282 self.todo_queue.push( tfe_job )
        job_persistence.py:830                todo_queue.push( job )
        arbiter_bootstrap.py:184              todo_queue.push( job )        [src/cosa/rest/]
        tfe/orchestrator.py:2174              todo_queue.push( validation_job )
        bfe/job.py:586                        todo_queue.push( new_job )

    SHAPE B — a BARE QUESTION, `push_job( question, session_id, user_id, user_email )`
              => becomes `flow.ask()`, NOT submit. The door-5 ruling: a bare question with
              nothing decided is exactly what `ask` takes.
        dead_queue_watchdog.py:401            self.todo_queue.push_job( question, ... )

⚠️ THE TARGET IS DECIDED BY THE SHAPE OF THE CALL, NOT BY THE FILE. Sending shape B to
`submit()` would skip the routing a bare question needs; sending shape A to `ask()` would
re-route work whose command was already decided. Both still produce an answer, so getting
it backwards is SILENT — which is why the table below is keyed on ( file, shape, target )
and never on the file alone.

📏 Measured, so a later reader can refute rather than re-derive: shape A outside
routers/tests = 6 sites, shape B = 1 site. The only other `push_job(` in the tree is
`routers/speech.py:338` — door 8, excluded by the router rule and separately broken (one
argument against four required). Everything else the grep turns up in `todo_fifo_queue.py`
is print text, not a call.

⚠️ THE PIPELINE-INTERNAL PUSHES NEED NO FILENAME EXCLUSION, and deliberately do not get
one. `running_fifo_queue.py` and `queue_consumer.py` push onto `running_queue`,
`jobs_done_queue` and `jobs_dead_queue` — never `todo_queue` — so the patterns below miss
them by construction. Excluding those files BY NAME would also hide a real
`todo_queue.push(` added to them later, which is the failure this sweep exists to prevent.

That measurement is why the sweep below is a POPULATION check over BOTH shapes rather than
a list check. The plan's own lesson: *"a loop that silently covers fifteen is how door 8
stayed invisible for a day"* — and this list already grew from six to seven once.
"""

import ast
import io
import os
import re
import tokenize

import pytest

# ( repo-relative path, shape, the flow method it must reach, label )
#   shape "job"      — a prebuilt job  -> flow.submit()
#   shape "question" — a bare question -> flow.ask()   (door-5 ruling)
INTERNAL_CALL_SITES = [
    ( "src/cosa/rest/dead_queue_watchdog.py",               "job",      "submit", "dead_queue_watchdog_prebuilt_job" ),
    ( "src/cosa/rest/dead_queue_watchdog.py",               "question", "ask",    "dead_queue_watchdog_bare_question" ),
    ( "src/cosa/rest/test_suite_completion_watchdog.py",    "job",      "submit", "test_suite_completion_watchdog" ),
    ( "src/cosa/rest/job_persistence.py",                   "job",      "submit", "job_persistence" ),
    ( "src/cosa/rest/arbiter_bootstrap.py",                 "job",      "submit", "arbiter_bootstrap" ),
    ( "src/cosa/agents/test_fix_expediter/orchestrator.py", "job",      "submit", "tfe_orchestrator" ),
    ( "src/cosa/agents/bug_fix_expediter/job.py",           "job",      "submit", "bfe_job" ),
]

EXPECTED_SITE_COUNT = 7

# SHAPE A: a prebuilt job handed to the todo queue.
_PUSH_CALL     = re.compile( r"todo_queue\s*\.\s*push\s*\(" )
# SHAPE B: a bare question. Anchored on `push_job(` with the paren, so it cannot also
# match `push_job_agentic(` — a THIRD shape step 12 does not touch, and a sweep that
# swept it up would fail against code nobody asked to change.
_PUSH_JOB_CALL = re.compile( r"todo_queue\s*\.\s*push_job\s*\(" )
_SUBMIT_CALL   = re.compile( r"\.submit\s*\(" )
_ASK_CALL      = re.compile( r"\.ask\s*\(" )

_SHAPE_PATTERN  = { "job": _PUSH_CALL, "question": _PUSH_JOB_CALL }
_TARGET_PATTERN = { "submit": _SUBMIT_CALL, "ask": _ASK_CALL }


def _repo_root():
    root = os.environ.get( "LUPIN_ROOT" )
    assert root, "LUPIN_ROOT must be set — see CLAUDE.md § PATH MANAGEMENT"
    return root


def _read( rel ):
    with open( os.path.join( _repo_root(), rel ) ) as fh:
        return fh.read()


def _code_only( source ):
    """Return `source` with every comment and string literal blanked out.

    THE SWEEP USED TO BE A RAW TEXT SEARCH, and it accused a DOCSTRING. When
    `restore_pending_jobs` moved onto the flow, its contract said in prose that the
    third argument "used to be the todo queue and the line below used to be
    todo_queue.push( job )" — which is exactly the sentence a later reader needs, and
    the sweep read it as a live call. The fix is not to delete the sentence: a module
    that cannot name what it replaced is worse documented because of its own guard.
    Blank the strings and comments, keep every real call. Tokenising cannot miss a
    call the regex would have caught — a call is never a STRING or a COMMENT token.
    """
    out = [ ]
    try:
        tokens = list( tokenize.generate_tokens( io.StringIO( source ).readline ) )
    except ( tokenize.TokenError, IndentationError, SyntaxError ):
        return source          # unparseable: fall back to the raw text, never quieter
    for tok in tokens:
        if tok.type in ( tokenize.STRING, tokenize.COMMENT ):
            # Preserve the line/column shape so nothing else shifts; the CONTENT goes.
            out.append( re.sub( r"\S", " ", tok.string ) )
        else:
            out.append( tok.string )
    return "".join( out )


def test_the_site_table_still_holds_the_ruled_population():
    """SEVEN sites, not six. This fails if anyone trims the table back to one row per file.

    NOT skipped — it checks this file's own table, not the code under construction, so it
    is meaningful today and guards the count while step 12 is still being built.
    """
    assert len( INTERNAL_CALL_SITES ) == EXPECTED_SITE_COUNT, (
        f"the table holds {len( INTERNAL_CALL_SITES )} sites; the ruled population is "
        f"{EXPECTED_SITE_COUNT}. dead_queue_watchdog carries TWO — a prebuilt job at :486 "
        f"and a bare question at :401 — so a row-per-file table is short by one."
    )
    assert sum( 1 for _r, shape, _t, _l in INTERNAL_CALL_SITES if shape == "question" ) == 1
    assert sum( 1 for _r, shape, _t, _l in INTERNAL_CALL_SITES if shape == "job" ) == 6


@pytest.mark.parametrize( "rel,shape,target,label", INTERNAL_CALL_SITES,
                          ids=[ label for _r, _s, _t, label in INTERNAL_CALL_SITES ] )
def test_each_internal_call_site_reaches_the_flow_by_its_shape( rel, shape, target, label ):
    """One reported case per SITE, and the target asserted by SHAPE.

    A prebuilt job must reach `submit` (its command is already decided); a bare question
    must reach `ask` (it still needs routing). Getting this backwards is SILENT — both
    paths still produce an answer, and only the routing differs.
    """
    source = _code_only( _read( rel ) )
    assert not _SHAPE_PATTERN[ shape ].search( source ), (
        f"{rel} still makes a {shape}-shaped call onto the todo queue directly; step 12 "
        f"routes it through flow.{target}() so the guarded write-back applies to it too"
    )
    assert _TARGET_PATTERN[ target ].search( source ), (
        f"{rel} no longer makes the {shape}-shaped queue call, but nothing in it reaches "
        f"flow.{target}() either"
    )


def test_no_internal_caller_still_reaches_the_queue_directly():
    """POPULATION CHECK — the guard a hand-list of six cannot give you.

    Sweeps the whole tree for `todo_queue.push(` and allows it ONLY in the retired-door
    routers (step 11 tombstones them), in tests/scratch, and in the ONE place the push
    now lives. Anything else is an internal caller that step 12 missed — including one
    added AFTER this file was written, which is exactly the case a fixed list of six
    would sail past.

    🔴 `src/cosa/rest/v2/executor.py` IS THE ALLOWED SITE, and allowing it is the point
    of the step rather than a hole in the test. Step 12 does not abolish the push; it
    moves it from seven scattered callers into `QueuedExecutor.submit`, which scopes the
    id and pushes exactly as the v1 tail did. One pushing site is the property this
    sweep is really asserting — so it is named here, as a single file, and a second one
    appearing anywhere still fails.
    """
    root      = _repo_root()
    offenders = []
    allowed   = { os.path.join( "src", "cosa", "rest", "v2", "executor.py" ) }
    for dirpath, dirnames, filenames in os.walk( os.path.join( root, "src" ) ):
        dirnames[ : ] = [ d for d in dirnames if d not in ( "__pycache__", "tmp", "tests", ".git" ) ]
        if f"{os.sep}routers" in dirpath: continue          # the retired doors — step 11's job
        for name in filenames:
            if not name.endswith( ".py" ): continue
            full = os.path.join( dirpath, name )
            rel  = os.path.relpath( full, root )
            if rel in allowed: continue
            with open( full, errors="ignore" ) as fh:
                source = _code_only( fh.read() )
            # BOTH shapes — the population grew from six to seven the moment anyone
            # looked for the second one.
            if _PUSH_CALL.search( source ) or _PUSH_JOB_CALL.search( source ):
                offenders.append( rel )
    assert not offenders, (
        f"these modules still reach the todo queue directly — todo_queue.push( ... ) or "
        f"todo_queue.push_job( ... ) — instead of going through flow.submit()/flow.ask(): "
        f"{sorted( offenders )}"
    )


def test_the_one_allowed_pushing_site_actually_pushes():
    """The allowance above is only safe while the thing it allows is doing the pushing.

    Without this, deleting the push out of `QueuedExecutor` — and with it every
    caller's route to the queue — would leave the sweep green: it only looks for
    pushes it does NOT want. An allow-list nobody checks is a hole with a comment
    on it.
    """
    source = _code_only( _read( os.path.join( "src", "cosa", "rest", "v2", "executor.py" ) ) )
    assert _PUSH_CALL.search( source ), (
        "QueuedExecutor no longer pushes onto the todo queue. Step 12 routed seven "
        "callers through it; if the push is gone, none of them reach the queue at all "
        "and the sweep above would still pass."
    )


# ── the boot-order precondition, which the plan calls a precondition and not a nicety ──

def test_the_flow_exists_before_the_catch_up_restore_runs():
    """`job_persistence:830` restores jobs at BOOT. If the flow is not built yet, it has
    nothing to submit to.

    SOURCE-ORDER assertion on purpose, matching the idiom of
    `test_main_boot_order_v2_submit.py`: importing `lupin_app.main` runs the module
    graph but does NOT run `lifespan`, so the ordering fact is only visible in the
    source. That neighbouring file records the finding this test pins the fix for —
    at HEAD the flow is built by a REQUEST-time dependency (`v2_ask.get_ask_flow`),
    and the restore runs before any request exists.
    """
    path = os.path.join( _repo_root(), "src", "lupin_app", "main.py" )
    with open( path ) as fh:
        tree = ast.parse( fh.read() )

    lifespan = next( ( n for n in ast.walk( tree )
                       if isinstance( n, ast.AsyncFunctionDef ) and n.name == "lifespan" ), None )
    assert lifespan is not None, "lupin_app.main has no async lifespan() — this pin's premise is gone"

    def _first_line( predicate ):
        hits = [ child.lineno for child in ast.walk( lifespan ) if predicate( child ) ]
        return min( hits ) if hits else None

    flow_line = _first_line(
        lambda n: isinstance( n, ast.Attribute ) and n.attr in ( "ask_flow", "flow" )
                  and isinstance( n.value, ast.Attribute ) and n.value.attr == "state"
    )
    restore_line = _first_line(
        lambda n: isinstance( n, ast.Call ) and isinstance( n.func, ast.Name )
                  and n.func.id == "restore_pending_jobs"
    )

    assert restore_line is not None, "restore_pending_jobs() is no longer called in lifespan"
    assert flow_line is not None, (
        "lifespan never puts the flow on app.state. At HEAD the flow is built by the "
        "request-time dependency v2_ask.get_ask_flow, and the catch-up restore runs "
        "before any request exists — so the restore has nothing to submit to. Step 12 "
        "must construct it in lifespan, before the restore."
    )
    assert flow_line < restore_line, (
        f"the catch-up restore (main.py:{restore_line}) runs BEFORE the flow is placed on "
        f"app.state (main.py:{flow_line}) — the boot-time caller would submit to nothing"
    )

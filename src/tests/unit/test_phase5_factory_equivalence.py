"""
Phase 5 pass-A gate: the eleven construction branches must build EXACTLY what they
build today, proven command by command.

Row d2e23ecb. Design: src/rnd/v0.2.0/2026.08.25-phase-5-job-factory-dispatch-by-lookup.md
Rick's ruling 2, verbatim in substance: "Pure refactor, no behaviour change."

WHY THIS SUITE EXISTS RATHER THAN A REVIEWER READING ELEVEN BODIES. The phase rests on
one falsifiable claim -- same command, same args, identical Job -- so the gate is a direct
comparison of the old path against the new one. A reviewer forming an opinion about
eleven moved bodies is not a gate; this is.

⚠️ THIS SUITE IS TEMPORARY BY CONSTRUCTION. It compares `create_agentic_job` against
`_legacy_create_agentic_job`, and the moment step 2 deletes the legacy function it can no
longer prove anything. It is a ONE-TIME MIGRATION PROOF, not the standing guard --
nothing in here notices a twelfth command arriving next month with a fresh construction
branch bolted into the factory. That is step 3's job, in test_v2_registry_drift_guard.py,
and the two must not be conflated (design doc, "Step 3 is a different gate").

🔴 THE COMPARISON EXCLUDES FIELDS BY NAME, NEVER BY TYPE. Two Job objects are never `==`
by default and carry different id_hash and creation timestamps. Filtering those out by
type -- "drop anything that looks like a hash or a time" -- would also drop a genuinely
changed field of the same shape, and the suite would go green over a real regression.
Every exclusion below is named, and adding one is a deliberate act a reviewer can see.
"""
import inspect
import pytest


# The fields that legitimately differ between two constructions of the same job, NAMED.
# Adding to this list is how this gate gets quietly weakened -- so it lives here, in one
# place, with a reason per entry, rather than as a predicate over field names.
EXCLUDED_FIELDS = {
    "id_hash"      : "content hash; differs per construction by design",
    "id"           : "per-instance identity",
    "created_date" : "wall-clock at construction",
    "created_time" : "wall-clock at construction",
    "timestamp"    : "wall-clock at construction",
    # ADDED 2026-08-25 AFTER THE GATE CAUGHT IT, and the way it was caught is the point.
    # Every one of the eleven cases failed on run_date alone -- two constructions
    # microseconds apart. A type-based filter ("drop anything that parses as a time")
    # would have absorbed this WITHOUT A WORD, and would equally have absorbed a
    # genuinely-changed timestamp field. Naming it is what made the reviewer see it.
    "run_date"     : "ISO wall-clock stamped in the Job constructor; differs by microseconds between two builds of the same job",
}


def _comparable( job ):
    """
    Reduce a Job to the attribute set a refactor must preserve.

    Requires:
        - job is a constructed AgenticJobBase subclass instance, or None

    Ensures:
        - returns None when handed None, so a "no such job" answer compares equal to a
          "no such job" answer rather than raising
        - returns a dict of the job's public instance attributes with EXCLUDED_FIELDS
          removed BY NAME
        - values that are not comparable by equality are reduced to their repr, so a
          nested object's identity does not defeat the comparison

    Raises:
        - nothing; an unreadable attribute is recorded as its exception text rather than
          aborting the comparison, because a field that raises on both paths is not a
          difference
    """
    if job is None: return None
    out = {}
    for name, value in sorted( vars( job ).items() ):
        if name.startswith( "_" ):     continue
        if name in EXCLUDED_FIELDS:    continue
        try:
            hash( value )
            out[ name ] = value
        except TypeError:
            out[ name ] = repr( value )
    return out


FIXED_CONTEXT = {
    "user_id"      : "sys-test-user",
    "user_email"   : "phase5@test.invalid",
    "session_id"   : "wise-penguin",
    "debug"        : False,
    "verbose"      : False,
}


# ─────────────────────────────────────────────── the eleven cases

# 🔴 THESE ARGUMENTS EXERCISE THE BRANCH BODIES, NOT THEIR HAPPY PATH. A case set that
# only sends well-formed input proves the dispatch works and says NOTHING about whether a
# body moved intact -- which is the only thing this phase changes. So: both shapes for
# every parser, the semantic-none words, and the queue directives that are dropped in
# silence when they go missing.
ELEVEN_CASES = [
    # ── the two languages parsers: BOTH shapes, because they branch on isinstance ──
    pytest.param(
        "agent router go to podcast generator",
        { "description": "a podcast about otters", "languages": [ "en", "es" ] },
        id="podcast-languages-as-list",
    ),
    pytest.param(
        "agent router go to podcast generator",
        { "description": "a podcast about otters", "languages": "en, es , fr" },
        id="podcast-languages-as-comma-string",
    ),
    pytest.param(
        "agent router go to research to podcast",
        { "query": "otter behaviour", "languages": [ "en" ] },
        id="research-to-podcast-languages-as-list",
    ),
    pytest.param(
        "agent router go to research to podcast",
        { "query": "otter behaviour", "languages": "en, de" },
        id="research-to-podcast-languages-as-comma-string",
    ),

    # ── test suite: 39 lines, the most discriminating branch in the file ──
    pytest.param(
        "agent router go to test suite",
        { "test_types": "integration, e2e", "pytest_args": "" },
        id="testsuite-types-comma-string-and-empty-args",
    ),
    pytest.param(
        "agent router go to test suite",
        { "test_types": [ "unit" ], "pytest_args": [ "-x", "-q" ] },
        id="testsuite-types-and-args-already-lists",
    ),
    pytest.param(
        "agent router go to test suite",
        # shlex, NOT str.split: a quoted -k expression must survive as ONE value. The
        # naive word-split shattered it and pytest read the bare `or` as a file arg,
        # exiting 4 -- a silent zero-test run that LOOKED submitted (2026-06-11).
        { "test_types": "unit", "pytest_args": '-k "a or b" --maxfail=1' },
        id="testsuite-quoted-k-expression-must-survive-whole",
    ),
    pytest.param(
        "agent router go to test suite",
        { "test_types": "unit", "pytest_args": "none" },
        id="testsuite-semantic-none-args",
    ),
    pytest.param(
        "agent router go to test suite",
        # 🔴 ARGUMENTS DELIBERATELY OMITTED so the branch's DEFAULTS are exercised.
        # Added 2026-08-25 because the falsifier did not fire without it: mutating
        # _build_test_suite's default test_types left all 18 cases GREEN, since every
        # other case passes test_types explicitly. A suite that cannot see a default is
        # blind to any change to one -- which is most of what a moved body can get wrong.
        {},
        id="testsuite-defaults-only-no-args-supplied",
    ),

    # ── the remaining constructors, one case each ──
    pytest.param(
        "agent router go to deep research",
        { "query": "otter population trends", "budget": "no limit" },
        id="deep-research-semantic-none-budget",
    ),
    pytest.param(
        "agent router go to claude code",
        { "prompt": "summarise the diff", "task_type": "BOUNDED" },
        id="claude-code",
    ),
    pytest.param(
        "agent router go to presentation generator",
        { "description": "a deck about otters" },
        id="presentation-generator",
    ),
    pytest.param(
        "agent router go to research to presentation",
        { "query": "otter habitats" },
        id="research-to-presentation",
    ),
    pytest.param(
        "agent router go to swe team",
        { "task": "add a health endpoint" },
        id="swe-team",
    ),
    pytest.param(
        "agent router go to bug fix expediter",
        { "bug_description": "the queue drops jobs" },
        id="bug-fix-expediter",
    ),
    pytest.param(
        "agent router go to test fix expediter",
        { "test_target": "src/tests/unit" },
        id="test-fix-expediter",
    ),
]


# ─────────────────────────────────────────────── the gate

def _both_paths( command, args, **overrides ):
    """
    Build the same job down the old path and the new one.

    Requires:
        - command is a routing command string
        - args is the argument dict to build from

    Ensures:
        - returns ( legacy_result, current_result ), each reduced by _comparable
        - passes FIXED_CONTEXT to both, so the ONLY difference between the two calls is
          which function was called

    Raises:
        - pytest.skip when _legacy_create_agentic_job is absent, which is the EXPECTED
          state both BEFORE extraction and AFTER step 2 deletes it. A hard error there
          would read as a regression when it is this file outside its window.
    """
    from cosa.rest import agentic_job_factory as f
    legacy = getattr( f, "_legacy_create_agentic_job", None )
    if legacy is None:
        pytest.skip(
            "_legacy_create_agentic_job is absent -- either extraction has not landed "
            "yet, or step 2 deleted it and this migration proof has outlived its "
            "purpose. The standing guard is test_v2_registry_drift_guard.py."
        )
    ctx = dict( FIXED_CONTEXT, **overrides )
    return ( _comparable( legacy( command, args, **ctx ) ),
             _comparable( f.create_agentic_job( command, args, **ctx ) ) )


@pytest.mark.parametrize( "command,args", ELEVEN_CASES )
def test_new_path_builds_what_the_old_path_built( command, args ):
    """The whole phase as one falsifiable claim: same command, same args, identical Job."""
    old, new = _both_paths( command, args )
    assert new == old, f"{command} diverged:\n  old={old}\n  new={new}"


def test_scheduled_at_survives_the_move():
    """
    A left-in scheduled_at is dropped IN SILENCE and the job runs immediately while the
    caller believes it is scheduled -- the factory reads arguments by name and does not
    name the queue directives. That failure is invisible without an explicit case.
    """
    old, new = _both_paths(
        "agent router go to deep research",
        { "query": "otters" },
        scheduled_at="2026-08-26T11:00:00-04:00", monopolize=True, spawned_by_id_hash="abc123",
    )
    assert new == old
    assert new[ "scheduled_at" ]       == "2026-08-26T11:00:00-04:00"
    assert new[ "monopolize" ]         is True
    assert new[ "spawned_by_id_hash" ] == "abc123"


def test_unknown_command_returns_none_on_both_paths():
    """
    Returning None for an unrecognised command is CONTRACT, promised in the docstring. A
    lookup that raises KeyError on a miss is a behaviour change and violates ruling 2.
    """
    old, new = _both_paths( "agent router go to nowhere at all", {} )
    assert old is None and new is None


def test_malformed_pytest_args_still_raises_on_both_paths():
    """
    Unbalanced quotes must fail LOUD at submit time; the silent alternative is the
    zero-test run that looked submitted. A refactor that turned this into a swallow
    would leave every other case in this file green.
    """
    from cosa.rest import agentic_job_factory as f
    if getattr( f, "_legacy_create_agentic_job", None ) is None:
        pytest.skip( "outside this file's window; see _both_paths" )
    bad = { "test_types": "unit", "pytest_args": '-k "unbalanced' }
    for fn in ( f._legacy_create_agentic_job, f.create_agentic_job ):
        with pytest.raises( ValueError ):
            fn( "agent router go to test suite", bad, **FIXED_CONTEXT )


# ─────────────────────────────────────────────── the exempt branch

# 🔴 THIS SECTION EXISTS BECAUSE FALSIFIER 2 DID NOT FIRE WITHOUT IT.
#
# Mutating `_build_test_fix_expediter_resume` to route through `_finish` left all 19
# other cases GREEN -- because none of them reach that branch. The ONE branch that is
# structurally different from the other ten, and the entire reason FINISH_EXEMPT exists,
# was completely uncovered by the gate that is supposed to prove the move.
#
# It cannot be driven by arguments alone: it resolves `resume_from` against job_history
# and rebuilds through `resume_job()`. So both seams are replaced, identically for both
# paths, and what is asserted is the thing the exemption is FOR -- that a resumed job
# keeps its ORIGINAL routing_command and args instead of having them overwritten.

class _FakeResumedJob:
    """Stands in for the job resume_job() rebuilds from job_history."""
    def __init__( self ):
        self.routing_command    = "agent router go to test fix expediter"   # the ORIGINAL
        self.original_args      = { "test_target": "the/original/target" }  # the ORIGINAL
        self.scheduled_at       = None
        self.monopolize         = False
        self.spawned_by_id_hash = None


def _patch_resume_seams( monkeypatch ):
    """Replace both resume seams so the branch is reachable without a live job_history."""
    from cosa.rest import agentic_job_factory as f
    from cosa.agents.test_fix_expediter import resume_resolver as rr

    class _Target:
        job_id = "tfe-deadbeef"

    monkeypatch.setattr( rr, "resolve_resume_target", lambda resume_from, user_email: _Target() )
    monkeypatch.setattr( f,  "resume_job",            lambda job_id, args_overrides=None: _FakeResumedJob() )
    return f


def test_resume_branch_is_equivalent_across_both_paths( monkeypatch ):
    """The exempt branch builds the same thing on both paths — the case falsifier 2 needed."""
    f = _patch_resume_seams( monkeypatch )
    if getattr( f, "_legacy_create_agentic_job", None ) is None:
        pytest.skip( "outside this file's window; see _both_paths" )
    args = { "resume_from": "the last stalled one", "thinking_effort": "high" }
    old = _comparable( f._legacy_create_agentic_job( "agent router go to test fix expediter resume", args, **FIXED_CONTEXT ) )
    new = _comparable( f.create_agentic_job(         "agent router go to test fix expediter resume", args, **FIXED_CONTEXT ) )
    assert new == old


def test_resume_keeps_its_original_provenance_not_the_resume_args( monkeypatch ):
    """
    THE ASSERTION THE EXEMPTION EXISTS FOR. Routing the resumed job through _finish would
    overwrite routing_command with the resume command and original_args with the resume
    args -- silently -- and job_history would then describe the wrong job. This is what
    goes red if somebody "tidies up" the exemption.
    """
    f = _patch_resume_seams( monkeypatch )
    job = f.create_agentic_job(
        "agent router go to test fix expediter resume",
        { "resume_from": "the last stalled one" },
        **FIXED_CONTEXT
    )
    assert job.routing_command == "agent router go to test fix expediter", \
        "the resumed job lost its ORIGINAL routing_command — _finish was applied to an exempt builder"
    assert job.original_args   == { "test_target": "the/original/target" }, \
        "the resumed job lost its ORIGINAL args — _finish was applied to an exempt builder"


def test_resume_still_stamps_queue_directives_itself( monkeypatch ):
    """Exempt from _finish is not exempt from scheduling — it stamps them on its own."""
    f = _patch_resume_seams( monkeypatch )
    job = f.create_agentic_job(
        "agent router go to test fix expediter resume",
        { "resume_from": "the last stalled one" },
        scheduled_at="2026-08-26T11:00:00-04:00", monopolize=True, **FIXED_CONTEXT
    )
    assert job.scheduled_at == "2026-08-26T11:00:00-04:00"
    assert job.monopolize   is True


def test_every_builder_either_calls_finish_or_is_named_exempt():
    """
    Mr Radio's ruling, 2026-08-25: every builder either calls _finish OR appears on an
    explicit named exemption list carrying its reason. Forgetting to call _finish is
    silent; naming an exemption is deliberate. This is the assertion that keeps them
    different — and it is what makes FINISH_EXEMPT a control rather than a comment.
    """
    import inspect
    from cosa.rest import agentic_job_factory as f
    for name, fn in vars( f ).items():
        if not name.startswith( "_build_" ): continue
        calls_finish = "_finish(" in inspect.getsource( fn )
        exempt       = name in f.FINISH_EXEMPT
        assert calls_finish or exempt, f"{name} neither calls _finish nor is named in FINISH_EXEMPT"
        assert not ( calls_finish and exempt ), f"{name} both calls _finish and claims exemption"
        if exempt:
            assert len( f.FINISH_EXEMPT[ name ].strip() ) > 40, f"{name}'s exemption has no real reason"

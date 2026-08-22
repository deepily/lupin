"""Step 9b — the READ guard: an unconfirmed row is never served, not even once.

RICK'S SENTENCE, AND THE READING IT FORBIDS. *"We want to keep unconfirmed answers from
replaying until they are confirmed."* Two readings differ in a way that matters: under one
an unconfirmed row is NEVER served; under the other its FIRST replay still happens and only
a later one is stopped. His sentence forbids the second, so the guard refuses every hit,
every time, until the end-of-execution confirmation flips the row to True.

WHERE THE VERDICT COMES FROM. Nothing new is asked at the head end. The only question put to
the user is the existing end-of-execution "was this answer correct?", which fires after the
agent runs, on a daemon thread that does not block — so on a timeout it leaves
`answer_is_correct` as None, and the row was written before the user answered at all. Three
states starting at unknown, so the guard FAILS CLOSED. That is the correction of a mistake
already made once in this area: the `routing_command` guard was hung on a loosely-typed
nullable column and failed OPEN.

⚠️ THE PLAN NAMES THE VACUOUS VERSION: "asserting the lookup returned nothing". The guard is
only real if THE REPLAY DOES NOT HAPPEN, so every test here asserts the executor was handed
an AGENT rather than a replay, and that the answer came back on the agent path.

⚠️ THIS IS THE OBSERVABLE ONE. Until confirmations flip rows to True, the cache appears to
stop working — every hit re-runs. Rick's ruling is explicit that this is correct, and the
control tests here are what make that a statement about unconfirmed rows and not about the
cache: a CONFIRMED row still replays.

⚠️ Run scoped — `pytest src/tests/unit/...` — an unscoped run collects `src/tmp/`, which
exits at import time.
"""

import os
import re
import sys
import types

import pytest

sys.path.insert( 0, os.path.dirname( __file__ ) )
import test_v2_flow as v2                       # noqa: E402
from test_v2_flow import notifier               # noqa: F401,E402 — a fixture, used by name


_CTX = v2._CTX


class _RecordingExecutor( v2.FakeExecutor ):
    """Remembers what KIND of work it was handed — replay or agent.

    The whole claim of this step is about which of those two happened, and a fake that only
    reported an outcome could not tell them apart.
    """

    def __init__( self, outcome ):
        super().__init__( outcome )
        self.kinds = []

    def submit( self, work, trace ):
        self.kinds.append( work.kind )
        return super().submit( work, trace )


def _flow( tmp_path, notifier, monkeypatch, lookup, executor, confirmer=None, threshold=90.0 ):
    monkeypatch.setattr( v2.flow_mod, "resolve",
                         lambda command, crud_enabled: v2.FakeSpec( required_args=(), snapshotable=False ) )
    return v2.AskFlow(
        v2.FakeCache( lookup_result=lookup ), v2.FakeRouter(), v2.FakeExpeditor(), executor,
        v2.FakePending(), crud_enabled=False, confirmation_threshold=threshold,
        confirmation_enabled=confirmer is not None,
        confirmer=confirmer if confirmer is not None else v2._FakeConfirmer(),
        receptionist_factory=v2.FakeReceptionist, notifier=notifier, trace_dir=str( tmp_path ),
    )


def _traces( tmp_path ):
    texts = []
    for name in os.listdir( tmp_path ):
        path = os.path.join( tmp_path, name )
        if os.path.isfile( path ):
            with open( path, errors="ignore" ) as fh:
                texts.append( fh.read() )
    return texts


@pytest.mark.parametrize( "verdict, what", [
    ( None,  "never answered — the confirmation timed out or has not fired yet" ),
    ( False, "the user said the answer was WRONG" ),
] )
def test_an_unconfirmed_exact_hit_is_not_served_and_the_agent_re_runs(
        verdict, what, tmp_path, notifier, monkeypatch ):
    """
    THE STEP. An exact cache hit on a row whose answer was not confirmed correct: the row is
    not served, and the question is answered by running the agent instead.

    Both unconfirmed states are driven, because they are different facts about the world and
    only one of them is a timeout.

    RED ON REVERT: drop the `_may_serve` call at the exact-hit decision and the executor is
    handed a replay.
    """
    executor = _RecordingExecutor( v2._outcome() )
    row      = v2._snapshot( routing_command="agent router go to math", answer_is_correct=verdict )
    flow     = _flow( tmp_path, notifier, monkeypatch,
                      v2._lookup( is_replay_hit=True, snapshot=row ), executor )

    result = flow.ask( "what is 2 plus 2", **_CTX )

    assert "replay" not in executor.kinds, f"an unconfirmed row was SERVED ({what})"
    assert executor.kinds == [ "agent" ], f"the agent did not re-run: {executor.kinds}"
    assert result[ "path" ] == "agent", f"the answer did not come back on the agent path: {result}"
    assert result[ "cache_hit" ] is False, "an unconfirmed row was reported to the caller as a cache hit"


def test_a_confirmed_exact_hit_is_still_served( tmp_path, notifier, monkeypatch ):
    """
    THE NEGATIVE CONTROL, and it is what makes "the cache appears to stop working" a
    statement about unconfirmed rows rather than about the cache. Without it, a build where
    the guard refuses EVERYTHING passes every other test in this file.

    RED ON REVERT: make `_may_serve` return False unconditionally.
    """
    executor = _RecordingExecutor( v2._outcome() )
    row      = v2._snapshot( routing_command="agent router go to math", answer_is_correct=True )
    flow     = _flow( tmp_path, notifier, monkeypatch,
                      v2._lookup( is_replay_hit=True, snapshot=row ), executor )

    result = flow.ask( "what is 2 plus 2", **_CTX )

    assert executor.kinds == [ "replay" ], f"a confirmed row was not served: {executor.kinds}"
    assert result[ "path" ] == "replay"
    assert result[ "cache_hit" ] is True


def test_an_unconfirmed_near_match_is_not_even_put_to_the_user( tmp_path, notifier, monkeypatch ):
    """
    THE SECOND REPLAY PATH, and the ask is skipped rather than asked-and-then-refused. A user
    answering "yes" about a row the guard will not serve is a question whose answer cannot
    change the outcome — and "never served, not even once" would be false if a near match
    could carry a row past the guard the exact path applies.

    RED ON REVERT: remove the `_may_serve` call from `_near_match_replay` — the confirmer is
    called and, on the yes, a replay is served.
    """
    confirmer = v2._FakeConfirmer( response_value="yes" )
    executor  = _RecordingExecutor( v2._outcome() )
    candidate = v2._snapshot( question="what is 2 plus 2", id_hash="near-1", answer_is_correct=None )
    flow      = _flow( tmp_path, notifier, monkeypatch,
                       v2._lookup( is_replay_hit=False, best_candidate=candidate,
                                   best_score=95.0, similarity=95.0, tier="ann" ),
                       executor, confirmer=confirmer )

    result = flow.ask( "what's 2 plus 2", **_CTX )

    assert confirmer.requests == [], "the user was asked about a row that could not be served either way"
    assert executor.kinds == [ "agent" ], f"an unconfirmed near match was served: {executor.kinds}"
    assert result[ "path" ] == "agent"


def test_a_confirmed_near_match_is_still_asked_about_and_served( tmp_path, notifier, monkeypatch ):
    """
    THE CONTROL ON THE SECOND PATH. The near-match ask still happens for a row that CAN be
    served, so 9b narrowed that branch rather than disabling it.

    RED ON REVERT: make the guard refuse on this path regardless of the verdict and the ask
    stops happening at all.
    """
    confirmer = v2._FakeConfirmer( response_value="yes" )
    executor  = _RecordingExecutor( v2._outcome() )
    candidate = v2._snapshot( question="what is 2 plus 2", id_hash="near-1", answer_is_correct=True )
    flow      = _flow( tmp_path, notifier, monkeypatch,
                       v2._lookup( is_replay_hit=False, best_candidate=candidate,
                                   best_score=95.0, similarity=95.0, tier="ann" ),
                       executor, confirmer=confirmer )

    result = flow.ask( "what's 2 plus 2", **_CTX )

    assert confirmer.requests, "a confirmed near match was not put to the user"
    assert executor.kinds == [ "replay" ], f"the confirmed near match was not served: {executor.kinds}"
    assert result[ "path" ] == "replay"


@pytest.mark.parametrize( "impostor", [ "true", "True", 1, "yes" ] )
def test_a_verdict_that_merely_looks_true_is_refused( impostor, tmp_path, notifier, monkeypatch ):
    """
    FAILS CLOSED ON A LOOSELY-TYPED COLUMN, which is the specific mistake this area has
    already made once. `answer_is_correct` is nullable and not type-constrained, so a writer
    that skipped the shared record builder could put a string or an int there. Truthiness
    would read every one of these as consent.

    RED ON REVERT: change `verdict is True` to `if verdict:` and all four are served.
    """
    executor = _RecordingExecutor( v2._outcome() )
    row      = v2._snapshot( routing_command="agent router go to math", answer_is_correct=impostor )
    flow     = _flow( tmp_path, notifier, monkeypatch,
                      v2._lookup( is_replay_hit=True, snapshot=row ), executor )

    flow.ask( "what is 2 plus 2", **_CTX )

    assert executor.kinds == [ "agent" ], (
        f"a row whose verdict was {impostor!r} — not the boolean True — was served"
    )


def test_a_row_missing_the_field_entirely_is_refused( tmp_path, notifier, monkeypatch ):
    """
    A row written before the column existed, or one a partial serializer built, carries no
    verdict at all. ABSENT IS NOT CONSENT — and this is the one place in the guard where a
    defaulted attribute read is right rather than the prohibited defensive kind: it defaults
    toward REFUSING. The write guard's spec attribute is the opposite case and is read
    plainly, so a missing one fails loud.

    RED ON REVERT: default the lookup to True when the attribute is missing.
    """
    executor = _RecordingExecutor( v2._outcome() )
    row      = types.SimpleNamespace( routing_command="agent router go to math" )   # no field at all
    flow     = _flow( tmp_path, notifier, monkeypatch,
                      v2._lookup( is_replay_hit=True, snapshot=row ), executor )

    flow.ask( "what is 2 plus 2", **_CTX )

    assert executor.kinds == [ "agent" ], "a row with no verdict field was served"


def test_the_refusal_says_so_in_the_trace( tmp_path, notifier, monkeypatch ):
    """
    THE ONLY WAY TO TELL A REFUSAL FROM A BROKEN CACHE. Both look like "the cache stopped
    working" from outside, and this step is expected to make a lot of that happen at once —
    so each refusal writes down which path it was on and what the verdict actually was.

    RED ON REVERT: drop the `trace.set` in `_may_serve`.
    """
    executor = _RecordingExecutor( v2._outcome() )
    row      = v2._snapshot( routing_command="agent router go to math", answer_is_correct=None )
    flow     = _flow( tmp_path, notifier, monkeypatch,
                      v2._lookup( is_replay_hit=True, snapshot=row ), executor )

    flow.ask( "what is 2 plus 2", **_CTX )

    assert any( "replay_refused_unconfirmed" in text for text in _traces( tmp_path ) ), (
        "a refused replay left nothing behind saying why the cache did not answer"
    )


# ─────────────────────── where the guard lives, and where it must not
#
# maya's finding, and it is the stronger reason for the placement: a guard inside
# `get_snapshots_by_question` would not even block a replay. Replays come from the tier-1
# exact path via `get_snapshot_by_id`; `get_snapshots_by_question` is the tier-2 ANN call
# that always returns `is_replay_hit=False`. So the guard has to sit on the replay decision
# to work at all — and putting it in the shared lookup would ALSO filter
# `GET /api/admin/snapshots/search`, blinding the one person whose job is to inspect the
# cache, silently.
_SHARED_LOOKUP_FILES = (
    os.path.join( "src", "cosa", "memory", "two_tier_question_search.py" ),
    os.path.join( "src", "cosa", "memory", "postgres_solution_manager.py" ),
    os.path.join( "src", "cosa", "rest", "db", "repositories", "solution_snapshot_repository.py" ),
)


def _repo_root():
    here = os.path.dirname( os.path.abspath( __file__ ) )
    return os.path.dirname( os.path.dirname( os.path.dirname( here ) ) )


_FILTER_SHAPES = (
    re.compile( r"answer_is_correct\s*(==|!=|>|<)" ),          # a comparison
    re.compile( r"answer_is_correct\s+is\b" ),                 # `... is True` / `is not None`
    re.compile( r"\.filter\([^)]*answer_is_correct" ),         # a SQLAlchemy filter
    re.compile( r"WHERE[^\n]*answer_is_correct", re.IGNORECASE ),  # raw SQL
    re.compile( r"if[^\n]*answer_is_correct" ),                 # a plain branch on it
)


@pytest.mark.parametrize( "relative_path", _SHARED_LOOKUP_FILES )
def test_the_shared_lookup_does_not_filter_on_the_verdict( relative_path ):
    """
    THE PLACEMENT, AND WHAT THIS TEST CAN HONESTLY CLAIM. It reads the shared search files
    and fails if any of them starts DECIDING on `answer_is_correct` — comparing it, branching
    on it, or putting it in a WHERE. That is a STRUCTURAL claim and is stated as one: it says
    the guard has not been moved down into the shared path. It does NOT prove the admin
    search still lists unconfirmed rows; that needs a live call to
    `GET /api/admin/snapshots/search` and belongs at the integration tier, where it is not
    yet written.

    It looks for filter SHAPES rather than for the name, because these files legitimately
    mention the column all over — they SELECT it, serialize it and hydrate it onto the
    snapshot, which is exactly how the verdict reaches the guard in the first place. A test
    that banned the word would fail on the plumbing it depends on.

    Kept because the failure it catches is a helpful-looking edit: somebody reads 9b, thinks
    the filter belongs "closer to the data", moves it, and every test above stays green while
    the admin surface goes quietly blind. maya's finding is the stronger reason it must not
    move: replays come from the tier-1 exact path via `get_snapshot_by_id`, while
    `get_snapshots_by_question` is the tier-2 ANN call that always returns
    `is_replay_hit=False` — so a guard here would not block a single replay AND would blind
    the admin search.

    RED ON REVERT: add any comparison, branch or WHERE on answer_is_correct to these files.
    """
    path = os.path.join( _repo_root(), relative_path )
    with open( path, errors="ignore" ) as fh:
        code = "\n".join( line for line in fh.read().splitlines()
                          if not line.strip().startswith( "#" ) )
    offenders = [ shape.pattern for shape in _FILTER_SHAPES if shape.search( code ) ]
    assert not offenders, (
        f"{relative_path} now DECIDES on answer_is_correct {offenders}. If the read guard "
        f"moved here it would not block a replay — replays come from the tier-1 exact path, "
        f"not from this ANN search — and it WOULD filter GET /api/admin/snapshots/search, "
        f"blinding the cache's only human inspector."
    )

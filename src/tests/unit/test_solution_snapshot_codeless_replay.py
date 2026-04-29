"""
Unit tests for SolutionSnapshot.run_code() codeless-agent replay.

Background (2026-04-28): CalculatorAgent (and similar deterministic-dispatch
agents) save snapshots with `code = ['']` BY DESIGN — there's no Python source
to save because the agent dispatches a parsed intent struct to pure-Python
helpers. On replay, those snapshots' answers come from `self.answer`, not
from re-execution.

Prior to the fix, `run_code()` raised ValueError on the empty-code guard for
codeless-agent snapshots, which the consumer thread caught and dead-lettered
(observed in 22:35 ts-90890bae and 19:19 ts-976bdc44 runs). The fix mirrors
the existing CalculatorAgent special-case in `run_formatter()` to short-circuit
codeless-agent replay to the cached answer.

GPU-RULE COMPLIANCE: SolutionSnapshot.__init__() loads embedding models onto
CUDA:0 (loads nomic-embed-text-v1.5 + CodeRankEmbed) — see
`feedback_never_grab_gpu` in MEMORY.md. These tests bypass __init__ entirely
via `SolutionSnapshot.__new__()` + direct attribute setting. We only exercise
the run_code() method; no embedding generation, no GPU touch.

Created: 2026-04-28 (post ts-976bdc44 verification)
"""

import pytest

from cosa.memory.solution_snapshot import SolutionSnapshot


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def _make_snapshot_no_init( agent_class_name=None, code=None, answer="" ):
    """
    Build a SolutionSnapshot WITHOUT calling __init__ — bypass the embedding
    generation that would otherwise hit CUDA:0.

    This is a deliberate `__new__()` + attribute-set pattern because:
      1. Constructor loads ~1 GB of embedding models onto GPU 0
      2. Per `feedback_never_grab_gpu`, tests must never touch GPU
      3. We only exercise `run_code()` here, which doesn't need any
         embedding state — just `agent_class_name`, `code`, `answer`,
         `id_hash`.
    """
    snap                  = SolutionSnapshot.__new__( SolutionSnapshot )
    snap.agent_class_name = agent_class_name
    snap.code             = code if code is not None else []
    snap.answer           = answer
    snap.code_example     = ""
    snap.code_returns     = ""
    snap.routing_command  = "agent router go to calculator"
    snap.id_hash          = "test-snapshot-id"
    snap.debug            = False
    snap.verbose          = False
    return snap


# ─────────────────────────────────────────────────────────────────────────
# Codeless agent (CalculatorAgent) replay path
# ─────────────────────────────────────────────────────────────────────────

def test_calc_agent_codeless_replay_returns_cached_answer():
    """CalculatorAgent snapshot with empty code + populated answer replays cleanly."""
    snap = _make_snapshot_no_init(
        agent_class_name = "CalculatorAgent",
        code             = [ "" ],   # empty by design
        answer           = "10 km is about 6.21 miles.",
    )
    result = snap.run_code()
    assert result == { "return_code": 0, "output": "10 km is about 6.21 miles." }
    # code_response_dict gets populated for downstream consumers
    assert snap.code_response_dict[ "return_code" ] == 0


def test_calc_agent_codeless_replay_with_dict_answer():
    """CalculatorAgent answer can be a dict (typical real shape from calc_operations)."""
    answer_dict = { "status": "ok", "result": 22.22, "from_value": 72.0 }
    snap = _make_snapshot_no_init(
        agent_class_name = "CalculatorAgent",
        code             = [ "" ],
        answer           = answer_dict,
    )
    result = snap.run_code()
    assert result == { "return_code": 0, "output": answer_dict }


def test_calc_agent_empty_code_list_replay():
    """Same path works whether code is `['']` or `[]`."""
    snap = _make_snapshot_no_init(
        agent_class_name = "CalculatorAgent",
        code             = [],
        answer           = "test answer",
    )
    result = snap.run_code()
    assert result[ "output" ] == "test answer"


def test_calc_agent_no_answer_raises():
    """CalculatorAgent snapshot with neither code nor answer is genuinely corrupted."""
    snap = _make_snapshot_no_init(
        agent_class_name = "CalculatorAgent",
        code             = [ "" ],
        answer           = "",
    )
    with pytest.raises( ValueError, match="CalculatorAgent snapshot has no answer" ):
        snap.run_code()


# ─────────────────────────────────────────────────────────────────────────
# Non-codeless-agent path (existing behavior preserved)
# ─────────────────────────────────────────────────────────────────────────

def test_non_calc_agent_empty_code_still_raises():
    """MathAgent (or any agent without the codeless flag) MUST still raise on empty code."""
    snap = _make_snapshot_no_init(
        agent_class_name = "MathAgent",
        code             = [ "" ],
        answer           = "some cached answer",
    )
    with pytest.raises( ValueError, match="Cannot execute empty code list" ):
        snap.run_code()


def test_unknown_agent_empty_code_still_raises():
    """Unknown agent_class_name is treated as code-generating; empty code raises."""
    snap = _make_snapshot_no_init(
        agent_class_name = None,
        code             = [ "" ],
        answer           = "irrelevant",
    )
    with pytest.raises( ValueError, match="Cannot execute empty code list" ):
        snap.run_code()

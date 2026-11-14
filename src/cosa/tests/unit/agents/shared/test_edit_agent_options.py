"""
Unit tests for cosa.agents.shared.edit_agent_options.

The builder gives every fix crew's coder and tester the same tools, permission mode, budget and effort.
It takes only the prompt, the safety callback and the turn limit from its caller.
ClaudeAgentOptions is the real SDK dataclass; nothing else is mocked.

Venue: :7999-eligible (pure unit).
"""
from types import SimpleNamespace

import cosa.utils.util as cu
from cosa.agents.shared.edit_agent_options import build_edit_agent_options


def _config():
    return SimpleNamespace( worker_model="model-w", budget_usd=1.5, thinking_effort="low" )


def test_options_carry_the_config_the_callers_pieces_and_the_edit_tools():
    cb   = lambda *a, **k: None
    opts = build_edit_agent_options( _config(), "/tmp/wt", "PROMPT", cb, 7 )
    assert opts.model           == "model-w"
    assert opts.system_prompt   == "PROMPT"
    assert opts.tools           == [ "Read", "Edit", "Bash" ]
    assert opts.cwd             == "/tmp/wt"
    assert opts.permission_mode == "acceptEdits"
    assert opts.can_use_tool    is cb
    assert opts.max_turns       == 7
    assert opts.max_budget_usd  == 1.5
    assert opts.effort          == "low"


def test_no_worktree_means_the_project_root():
    opts = build_edit_agent_options( _config(), None, "P", lambda *a, **k: None, 3 )
    assert opts.cwd == cu.get_project_root()


def test_each_call_gets_its_own_tools_list():
    a = build_edit_agent_options( _config(), None, "P", lambda *a, **k: None, 3 )
    b = build_edit_agent_options( _config(), None, "P", lambda *a, **k: None, 3 )
    a.tools.append( "Write" )
    assert b.tools == [ "Read", "Edit", "Bash" ]

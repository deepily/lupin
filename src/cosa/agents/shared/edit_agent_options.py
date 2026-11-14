#!/usr/bin/env python3
"""
One builder for the SDK options of a fix crew's coder or tester.

The bug-fix and test-fix expediters each built the same four ClaudeAgentOptions blocks by hand.
They differed only in the system prompt, the safety callback and the turn limit.
The callback is made by the caller, so each orchestrator keeps its own build_can_use_tool name in its own module.
"""
import cosa.utils.util as cu

EDIT_AGENT_TOOLS = [ "Read", "Edit", "Bash" ]


def build_edit_agent_options( config, worktree_cwd, system_prompt, can_use_tool, max_turns ):
    """
    Build the ClaudeAgentOptions of a coder or tester that may read, edit and run commands.

    Requires:
        - config has worker_model, budget_usd and thinking_effort
        - worktree_cwd is a directory path or None
        - can_use_tool is the safety callback the caller built for this role

    Ensures:
        - returns options for config.worker_model with the Read, Edit and Bash tools and acceptEdits permission
        - the working directory is worktree_cwd, or the project root when that is None
        - the budget and effort come from config; the turn limit is max_turns

    Raises:
        - ImportError when claude_agent_sdk is not installed
    """
    from claude_agent_sdk import ClaudeAgentOptions
    return ClaudeAgentOptions(
        model           = config.worker_model,
        system_prompt   = system_prompt,
        tools           = list( EDIT_AGENT_TOOLS ),
        cwd             = worktree_cwd or cu.get_project_root(),
        permission_mode = "acceptEdits",
        can_use_tool    = can_use_tool,
        max_turns       = max_turns,
        max_budget_usd  = config.budget_usd,
        effort          = config.thinking_effort,
    )

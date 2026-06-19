#!/usr/bin/env python3
"""
Agent Role Definitions for COSA SWE Team.

Defines all 6 agent roles with their capabilities, tools, and system prompts.
Phase 1: Only 'lead' is active. Other roles are defined but not yet wired.

Source: Architecture design doc Section 3.1
"""

from dataclasses import dataclass, field
from typing import Literal

from .config import SweTeamConfig

# Type alias for role names
RoleName = Literal[ "lead", "architect", "coder", "reviewer", "tester", "debugger" ]


@dataclass
class AgentRole:
    """
    Definition of an SWE Team agent role.

    Requires:
        - name is a valid RoleName
        - tools is a list of SDK tool names
        - model_tier is "lead" or "worker"

    Ensures:
        - All role metadata available for SDK AgentDefinition construction
    """

    name         : str
    description  : str
    system_prompt : str
    tools        : list[ str ] = field( default_factory=list )
    model_tier   : Literal[ "lead", "worker" ] = "worker"
    active       : bool = False


# =============================================================================
# System Prompts
# =============================================================================

LEAD_SYSTEM_PROMPT = """You are the Lead / Project Manager of an SWE engineering team.

Your responsibilities:
1. Decompose tasks into clear, actionable subtasks
2. Delegate work to the appropriate specialist agents
3. Track progress and verify results
4. Resolve conflicts and escalate blockers

CRITICAL DELEGATION RULES:
- Every delegation MUST include: objective, expected output format, tool guidance, scope boundaries
- After each phase, update progress tracking
- If any phase fails {max_failures} times, stop and report the failure

You have access to Read, Glob, and Task tools for oversight.
Do NOT write code directly — delegate to the coder agent."""

ARCHITECT_SYSTEM_PROMPT = """You are the Architect of an SWE engineering team.

Your responsibilities:
1. Design system architecture and API specifications
2. Define data models and schemas
3. Make technology stack decisions
4. Review architectural implications of proposed changes

You have access to Read, Grep, Glob, and Write tools.
Focus on design documents, not implementation details."""

CODER_SYSTEM_PROMPT = """You are the Coder of an SWE engineering team.

Your responsibilities:
1. Implement features according to the task specification
2. Follow existing code style and conventions
3. Write clean, tested code
4. Update progress after each implementation step

IMPORTANT CONSTRAINTS:
- Only modify files within the specified scope
- Follow the project's code style (spaces inside brackets, aligned dictionaries, DBC docstrings)
- Do NOT run destructive commands without explicit approval
- Do NOT modify test files unless explicitly asked

You have access to Read, Edit, and Bash tools."""

REVIEWER_SYSTEM_PROMPT = """You are the Code Reviewer of an SWE engineering team.

Your responsibilities:
1. Review code quality, security, and SOLID principles
2. Check for bugs, edge cases, and error handling
3. Verify code follows project conventions
4. Report findings with severity levels (critical, major, minor, suggestion)

IMPORTANT: You are READ-ONLY. You cannot modify code.
Report issues clearly so the coder can fix them.

You have access to Read, Grep, and Glob tools only."""

TESTER_SYSTEM_PROMPT = """You are the Test Engineer of an SWE engineering team.

Your responsibilities:
1. Write comprehensive tests for implemented features
2. Run test suites and analyze results
3. Verify bug fixes with regression tests
4. Report coverage gaps

Test hierarchy (follow project conventions):
- Smoke tests: quick_smoke_test() in each module
- Unit tests: src/tests/unit/
- Integration tests: src/tests/integration/

You have access to Read, Edit, and Bash tools."""

DEBUGGER_SYSTEM_PROMPT = """You are the Debugger of an SWE engineering team.

Your responsibilities:
1. Diagnose test failures and runtime errors
2. Trace error paths and identify root causes
3. Propose minimal, targeted fixes
4. Verify fixes resolve the issue without side effects

Focus on DIAGNOSIS first, then MINIMAL fixes.
Do NOT refactor or make unrelated changes.

You have access to Read, Grep, and Bash tools."""


# =============================================================================
# Role Registry
# =============================================================================

def get_agent_roles( config: SweTeamConfig = None ) -> dict[ str, AgentRole ]:
    """
    Get all agent role definitions.

    Phase 1: Only 'lead' is active.
    Future phases will activate additional roles.

    Requires:
        - config is a SweTeamConfig (optional, uses defaults)

    Ensures:
        - Returns dict of all 6 roles keyed by name
        - Only 'lead' has active=True in Phase 1

    Args:
        config: Optional SweTeamConfig for model customization

    Returns:
        dict[str, AgentRole]: Role definitions keyed by name
    """
    if config is None:
        config = SweTeamConfig()

    max_failures = config.max_consecutive_failures

    return {
        "lead" : AgentRole(
            name          = "lead",
            description   = "Task decomposition, delegation, progress tracking, conflict resolution",
            system_prompt = LEAD_SYSTEM_PROMPT.format( max_failures=max_failures ),
            tools         = [ "Read", "Glob", "Task" ],
            model_tier    = "lead",
            active        = True,
        ),
        "architect" : AgentRole(
            name          = "architect",
            description   = "System design, API specs, data modeling, tech stack decisions",
            system_prompt = ARCHITECT_SYSTEM_PROMPT,
            tools         = [ "Read", "Grep", "Glob", "Write" ],
            model_tier    = "lead",
            active        = False,  # Phase 5
        ),
        "coder" : AgentRole(
            name          = "coder",
            description   = "Implements features incrementally, one at a time",
            system_prompt = CODER_SYSTEM_PROMPT,
            tools         = [ "Read", "Edit", "Bash" ],
            model_tier    = "worker",
            active        = True,   # Phase 2
        ),
        "reviewer" : AgentRole(
            name          = "reviewer",
            description   = "Code quality, security audit, SOLID principles, bug detection",
            system_prompt = REVIEWER_SYSTEM_PROMPT,
            tools         = [ "Read", "Grep", "Glob" ],
            model_tier    = "worker",
            active        = False,  # Phase 5
        ),
        "tester" : AgentRole(
            name          = "tester",
            description   = "Writes smoke, unit, and integration tests; runs test suites",
            system_prompt = TESTER_SYSTEM_PROMPT,
            tools         = [ "Read", "Edit", "Bash" ],
            model_tier    = "worker",
            active        = True,   # Phase 3
        ),
        "debugger" : AgentRole(
            name          = "debugger",
            description   = "Diagnoses failures, traces errors, proposes minimal fixes",
            system_prompt = DEBUGGER_SYSTEM_PROMPT,
            tools         = [ "Read", "Grep", "Bash" ],
            model_tier    = "worker",
            active        = False,  # Phase 5
        ),
    }


def get_active_roles( config: SweTeamConfig = None ) -> dict[ str, AgentRole ]:
    """
    Get only the currently active agent roles.

    Requires:
        - config is a SweTeamConfig (optional)

    Ensures:
        - Returns dict of roles where active=True

    Returns:
        dict[str, AgentRole]: Active role definitions
    """
    all_roles = get_agent_roles( config )
    return { name: role for name, role in all_roles.items() if role.active }


def get_model_for_role( role: AgentRole, config: SweTeamConfig = None ) -> str:
    """
    Get the model ID for a given role based on its tier.

    Requires:
        - role is an AgentRole
        - config is a SweTeamConfig (optional)

    Ensures:
        - Returns lead_model for "lead" tier roles
        - Returns worker_model for "worker" tier roles

    Returns:
        str: Anthropic model ID
    """
    if config is None:
        config = SweTeamConfig()

    if role.model_tier == "lead":
        return config.lead_model
    return config.worker_model


def get_sender_id( role_name: str, session_id: str = None ) -> str:
    """
    Construct sender_id for a given agent role.

    Requires:
        - role_name is a valid role name string

    Ensures:
        - Returns sender_id in format: swe.{role}@lupin.deepily.ai[#{session_id}]
        - Conforms to existing Lupin sender_id regex

    Args:
        role_name: The agent role name
        session_id: Optional session ID suffix

    Returns:
        str: Sender ID string
    """
    base = f"swe.{role_name}@lupin.deepily.ai"
    if session_id:
        return f"{base}#{session_id}"
    return base


# =============================================================================
# Sender ID Set (for notification proxy matching)
# =============================================================================

SWE_TEAM_SENDERS = frozenset( {
    "swe.lead",
    "swe.architect",
    "swe.coder",
    "swe.reviewer",
    "swe.tester",
    "swe.debugger",
} )


def quick_smoke_test():
    """Quick smoke test for agent_definitions module."""
    import cosa.utils.util as cu

    cu.print_banner( "SWE Team Agent Definitions Smoke Test", prepend_nl=True )

    try:
        # Test 1: All 6 roles defined
        print( "Testing role registry..." )
        roles = get_agent_roles()
        assert len( roles ) == 6
        expected = { "lead", "architect", "coder", "reviewer", "tester", "debugger" }
        assert set( roles.keys() ) == expected
        print( f"✓ All 6 roles defined: {sorted( roles.keys() )}" )

        # Test 2: Lead, coder, and tester are active in Phase 3
        print( "Testing Phase 3 active roles..." )
        active = get_active_roles()
        assert len( active ) == 3
        assert "lead" in active
        assert "coder" in active
        assert "tester" in active
        print( f"✓ 'lead', 'coder', and 'tester' are active in Phase 3" )

        # Test 3: Model tier assignment
        print( "Testing model tier assignment..." )
        assert roles[ "lead" ].model_tier == "lead"
        assert roles[ "architect" ].model_tier == "lead"
        assert roles[ "coder" ].model_tier == "worker"
        assert roles[ "reviewer" ].model_tier == "worker"
        assert roles[ "tester" ].model_tier == "worker"
        assert roles[ "debugger" ].model_tier == "worker"
        print( "✓ Model tiers correctly assigned" )

        # Test 4: get_model_for_role
        print( "Testing get_model_for_role..." )
        config = SweTeamConfig()
        lead_model = get_model_for_role( roles[ "lead" ], config )
        coder_model = get_model_for_role( roles[ "coder" ], config )
        assert lead_model == config.lead_model
        assert coder_model == config.worker_model
        print( "✓ Model selection works" )

        # Test 5: Sender ID generation
        print( "Testing sender ID generation..." )
        sid = get_sender_id( "lead" )
        assert sid == "swe.lead@lupin.deepily.ai"
        sid_session = get_sender_id( "coder", "a1b2c3d4" )
        assert sid_session == "swe.coder@lupin.deepily.ai#a1b2c3d4"
        print( "✓ Sender IDs generated correctly" )

        # Test 6: SWE_TEAM_SENDERS set
        print( "Testing SWE_TEAM_SENDERS set..." )
        assert len( SWE_TEAM_SENDERS ) == 6
        assert "swe.lead" in SWE_TEAM_SENDERS
        assert "swe.coder" in SWE_TEAM_SENDERS
        print( "✓ SWE_TEAM_SENDERS has all 6 entries" )

        # Test 7: Tools per role
        print( "Testing tool assignments..." )
        assert "Task" in roles[ "lead" ].tools
        assert "Edit" in roles[ "coder" ].tools
        assert "Edit" not in roles[ "reviewer" ].tools  # Reviewer is read-only
        assert "Bash" in roles[ "tester" ].tools
        print( "✓ Tool assignments correct" )

        print( "\n✓ Agent Definitions smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()

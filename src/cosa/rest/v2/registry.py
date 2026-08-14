"""
CJ Flow v2 — the single command→agent registry (plan §3, §3a; revised by cascade
handoff §3.A, R-A1/R-A2/R-A3).

Replaces the three v1 routing mechanisms the survey found drifting apart — the
if/elif chain (`todo_fifo_queue.py:697-777`), `MODE_TO_AGENT` (`:58`), and the
second if/elif in `agentic_job_factory.py:103`. One map, keyed on the FULL routing
string, is what the §9 registry-guard test defends so that drift cannot reappear.

Resolution order for `required_args` is the MIGRATION PATH, not a fallback chain
(§3a): the agent declares its own args first (phase 2), then the `AGENTIC_AGENTS`
table (today, for the agentic commands), then the spec's literal tuple (today, for
the conversational agents). In phase 1 no agent declares, so every lookup lands on
a table exactly as it does now.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional

from cosa.agents.math_agent          import MathAgent
from cosa.agents.calculator.agent    import CalculatorAgent
from cosa.agents.date_and_time_agent import DateAndTimeAgent
from cosa.agents.todo_list_agent     import TodoListAgent
from cosa.agents.calendaring_agent   import CalendaringAgent
from cosa.agents.weather_agent       import WeatherAgent
from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS


@dataclass( frozen=True )
class AgentSpec:
    """
    One command's binding: the full routing string, the factory that builds its
    agent, its short-form aliases, whether its results are snapshotable, and its
    literal required-args fallback.

    Requires:
        - command is the FULL routing string (e.g. "agent router go to weather");
          short forms live in aliases (R-A1)
        - factory constructs the agent (the executor calls it with the bare
          question and the shared 11-kwarg signature)

    Ensures:
        - required_args resolves agent-first (declared_args), then AGENTIC_AGENTS,
          then the literal _required_args tuple (§3a migration path)
        - frozen: specs are immutable table data
    """
    command       : str
    factory       : Callable[ ..., Any ]
    aliases       : tuple[ str, ... ] = ()
    snapshotable  : bool              = True
    _required_args: Optional[ tuple[ str, ... ] ] = None

    @property
    def required_args( self ) -> tuple[ str, ... ]:
        """
        Resolve this command's required arguments along the §3a migration path.

        Requires:
            - self.factory is set; AGENTIC_AGENTS is importable

        Ensures:
            - Returns the agent's own declared required args when it implements
              declared_args() (phase 2 destination)
            - Else the AGENTIC_AGENTS entry's required_user_args when present
            - Else this spec's literal _required_args, or () when unset
        """
        if hasattr( self.factory, "declared_args" ):
            return self.factory.declared_args().required
        entry = AGENTIC_AGENTS.get( self.command )
        if entry:
            return tuple( entry[ "required_user_args" ] )
        return self._required_args or ()


# ── The six phase-1 agents ────────────────────────────────────────────────────
# Keyed on the FULL routing string (R-A1); short forms are aliases. NON-CRUD
# classes are pinned (R-A3): v1 forks calendar/todo to CRUD agents when the
# `crud for dataframes agents enabled` flag is set, and CRUD agents are never
# snapshotted — inheriting that fork would report 0% cache-hit forever and read as
# a v2 bug. The executor calls spec.factory with the shared 11-kwarg signature and
# the BARE question for every agent (v2 drops MathAgent's salutation quirk, risk 10).
V2_AGENTS = {
    spec.command: spec
    for spec in (
        AgentSpec( "agent router go to math",       MathAgent,        aliases=( "math", ) ),
        AgentSpec( "agent router go to calculator", CalculatorAgent,  aliases=( "calculator", ) ),
        AgentSpec( "agent router go to datetime",   DateAndTimeAgent, aliases=( "datetime", ) ),
        AgentSpec( "agent router go to todo",       TodoListAgent,    aliases=( "todo", "todo list" ) ),
        AgentSpec( "agent router go to calendar",   CalendaringAgent, aliases=( "calendar", ) ),
        AgentSpec( "agent router go to weather",    WeatherAgent,
                   aliases=( "weather", ), snapshotable=False, _required_args=( "location", ) ),
    )
}

# Router-emittable commands v2 does NOT run in phase 1 — the heavy/agentic set.
# Explicit so the §9 guard is a set-equality, never a silent superset.
DEFERRED_COMMANDS = frozenset( {
    "agent router go to deep research",
    "agent router go to podcast generator",
    "agent router go to research to podcast",
    "agent router go to presentation generator",
    "agent router go to research to presentation",
    "agent router go to claude code",
    "agent router go to swe team",
} )

# Mode-control commands — NOT agents (R-A2). `automatic` clears the user's mode and
# returns early (todo_fifo_queue.py:739-747); it never routes to an agent. Bucketed
# separately so the guard's four-bucket set-equality holds (the plan's original
# three buckets failed on this command's first appearance, R-A2/R-D4).
CONTROL_COMMANDS = frozenset( { "agent router go to automatic" } )

# The else — deliberately NOT registry entries (§3a). `receptionist` is a router
# template command; `none` is the internal no-command outcome. Neither is an agent;
# resolve() returns None for both and the flow routes None to the receptionist (§4).
RECEPTIONIST_OR_NONE = frozenset( { "agent router go to receptionist", "none" } )


def resolve( command ):
    """
    Resolve a routing command to its AgentSpec, or None when it is not a v2 agent.

    Requires:
        - command is a routing string: a full form ("agent router go to weather")
          or a registered short-form alias ("weather")

    Ensures:
        - Returns the AgentSpec for a phase-1 agent command or one of its aliases
        - Returns None for every non-agent command — deferred, control,
          receptionist, none, or unknown — which the flow routes to the
          receptionist (§4, route_reason="unknown_command")
        - Never raises on an unknown command

    Args:
        command: The routing command string from the router.

    Returns:
        AgentSpec or None
    """
    spec = V2_AGENTS.get( command )
    if spec is not None:
        return spec
    for candidate in V2_AGENTS.values():
        if command in candidate.aliases:
            return candidate
    return None

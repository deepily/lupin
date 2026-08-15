"""
CJ Flow v2 — the single command→agent registry (plan §3, §3a; revised by cascade
handoff §3.A, R-A1/R-A2/R-A3; agentic set folded in by the 2026.08.15
single-source design, phase 1).

Replaces the three v1 routing mechanisms the survey found drifting apart — the
if/elif chain (`todo_fifo_queue.py:697-777`), `MODE_TO_AGENT` (`:58`), and the
second if/elif in `agentic_job_factory.py:103`. One map, keyed on the FULL routing
string, is what the §9 registry-guard test defends so that drift cannot reappear.

Resolution order for `required_args` is the MIGRATION PATH, not a fallback chain
(§3a): the agent declares its own args first (phase 2), then the `AGENTIC_AGENTS`
table (today, for the agentic commands), then the spec's literal tuple (today, for
the conversational agents). In phase 1 no agent declares, so every lookup lands on
a table exactly as it does now.

Phase 1 of the single-source design (2026.08.15-agent-registration-single-source.md
§5.1 / §7): the registry now OWNS the agentic set. Every command carries a
`CommandClass`, and the four template buckets are DERIVED from that label (§5.1.2)
rather than hand-maintained. `resolve()` stays scoped to CONVERSATIONAL so this
bookkeeping change does not silently widen what the router-facing resolver returns
(§5.1.3); agentic commands are reached through the separate `resolve_agentic()`.
No behaviour change: `resolve()` returns exactly what it did before.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

from cosa.agents.math_agent          import MathAgent
from cosa.agents.calculator.agent    import CalculatorAgent
from cosa.agents.date_and_time_agent import DateAndTimeAgent
from cosa.agents.todo_list_agent     import TodoListAgent
from cosa.agents.calendaring_agent   import CalendaringAgent
from cosa.agents.weather_agent       import WeatherAgent
from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS
from cosa.agents.runtime_argument_expeditor.expeditor      import ArgSpec


class CommandClass( Enum ):
    """
    What a router command IS — the label the derived buckets (§5.1.2) and the
    phase-2 class-aware drift guard read instead of inferring class from a
    command's absence from one list or another.
    """
    CONVERSATIONAL = "conversational"   # fast-lane agent, no job, no CLI
    AGENTIC        = "agentic"          # builds a job; has an argument contract
    CONTROL        = "control"          # mode control; never routes to an agent
    NONE           = "none"             # receptionist / no-command outcome


@dataclass( frozen=True )
class AgentSpec:
    """
    One command's binding: the full routing string, its class, the factory that
    builds its agent (conversational only), its short-form aliases, whether its
    results are snapshotable, its literal required-args fallback, and — for the
    agentic set — the CLI module and the typed `ArgSpec` carrier.

    Requires:
        - command is the FULL routing string (e.g. "agent router go to weather");
          short forms live in aliases (R-A1)
        - factory constructs a CONVERSATIONAL agent (the executor calls it with
          the bare question and the shared 11-kwarg signature); it is None for
          agentic / control / none commands, which resolve() never returns

    Ensures:
        - required_args resolves agent-first (declared_args), then AGENTIC_AGENTS,
          then the literal _required_args tuple (§3a migration path)
        - frozen: specs are immutable table data
        - arg_spec, when present, is an ArgSpec built via ArgSpec.from_entry so the
          expeditor's copy semantics come along and no field is re-declared (§5.1.1)
    """
    command       : str
    factory       : Optional[ Callable[ ..., Any ] ] = None
    aliases       : tuple[ str, ... ] = ()
    snapshotable  : bool              = True
    _required_args: Optional[ tuple[ str, ... ] ] = None
    # ── added by the 2026.08.15 single-source design (phase 1) ──
    cls           : CommandClass      = CommandClass.CONVERSATIONAL
    job_factory   : Optional[ Callable[ ..., Any ] ] = None   # agentic: builds the Job (wired in phase 5)
    cli_module    : Optional[ str ]   = None                  # None ⇒ API-invoked (test_suite)
    cli_style     : Optional[ str ]   = None                  # "package" | "module" — documentation only (§6)
    arg_spec      : Optional[ ArgSpec ] = None                # the expeditor's carrier, §5.1.1

    @property
    def required_args( self ) -> tuple[ str, ... ]:
        """
        Resolve this command's required arguments along the §3a migration path.

        Requires:
            - AGENTIC_AGENTS is importable

        Ensures:
            - Returns the agent's own declared required args when its factory
              implements declared_args() (phase 2 destination)
            - Else the AGENTIC_AGENTS entry's required_user_args when present
            - Else this spec's literal _required_args, or () when unset
        """
        if hasattr( self.factory, "declared_args" ):
            return self.factory.declared_args().required
        entry = AGENTIC_AGENTS.get( self.command )
        if entry:
            return tuple( entry[ "required_user_args" ] )
        return self._required_args or ()


# ── The six conversational (phase-1) agents ──────────────────────────────────
# Keyed on the FULL routing string (R-A1); short forms are aliases. NON-CRUD
# classes are pinned (R-A3): v1 forks calendar/todo to CRUD agents when the
# `crud for dataframes agents enabled` flag is set, and CRUD agents are never
# snapshotted — inheriting that fork would report 0% cache-hit forever and read as
# a v2 bug. The executor calls spec.factory with the shared 11-kwarg signature and
# the BARE question for every agent (v2 drops MathAgent's salutation quirk, risk 10).
_CONVERSATIONAL = (
    AgentSpec( "agent router go to math",       MathAgent,        aliases=( "math", ) ),
    AgentSpec( "agent router go to calculator", CalculatorAgent,  aliases=( "calculator", ) ),
    AgentSpec( "agent router go to datetime",   DateAndTimeAgent, aliases=( "datetime", ) ),
    AgentSpec( "agent router go to todo",       TodoListAgent,    aliases=( "todo", "todo list" ) ),
    AgentSpec( "agent router go to calendar",   CalendaringAgent, aliases=( "calendar", ) ),
    AgentSpec( "agent router go to weather",    WeatherAgent,
               aliases=( "weather", ), snapshotable=False, _required_args=( "location", ) ),
)


def _agentic_spec( command, entry ):
    """
    Build an AGENTIC AgentSpec from a raw AGENTIC_AGENTS entry (§5.1 / §5.1.1).

    Ensures:
        - arg_spec is ArgSpec.from_entry( entry ) — the eight expeditor fields are
          reused, not re-declared, so the copy semantics (bug 8aa89f42) come along
        - cli_module is the entry's, or None (test_suite is API-invoked)
        - cli_style is "module" for a *.cli module-with-__main__-guard, "package"
          for a package needing __main__.py, or None when there is no CLI. It is
          documentation only in phase 1 — no guard branches on it (§6 assertion 5′)
        - job_factory is None in phase 1; phase 5 wires factory dispatch by lookup
    """
    cli_module = entry.get( "cli_module" )
    if cli_module is None:
        cli_style = None
    elif cli_module.endswith( ".cli" ):
        cli_style = "module"
    else:
        cli_style = "package"
    return AgentSpec(
        command    = command,
        cls        = CommandClass.AGENTIC,
        cli_module = cli_module,
        cli_style  = cli_style,
        arg_spec   = ArgSpec.from_entry( entry ),
    )


# ── The agentic set — now OWNED by the registry (§5.1) ────────────────────────
# One spec per AGENTIC_AGENTS entry (10), built by iterating the table itself. So
# AGENTIC_COMMANDS (derived below from the CommandClass.AGENTIC label) equals the
# AGENTIC_AGENTS key set BY CONSTRUCTION — there is no second hand-written list to
# drift from it. (Tiberius's §3b cross-check resolved as construction, not a
# runtime test: a set-equality asserted against a set derived from the same table
# is a tautology that can never go red.)
# ⚠️ Do NOT hand-declare an AGENTIC AgentSpec anywhere but this comprehension.
# Adding one by hand is the ONLY way to reintroduce the cls↔AGENTIC_AGENTS drift,
# and — precisely because the invariant is structural — no test would catch it.
_AGENTIC = tuple( _agentic_spec( command, entry ) for command, entry in AGENTIC_AGENTS.items() )

# ── Mode-control and the receptionist/none outcomes, as class-labelled specs ──
# So the four template buckets can be DERIVED from cls (§5.1.2). `automatic` clears
# the user's mode and returns early (todo_fifo_queue.py:739-747); it never routes to
# an agent. `receptionist` is a router template command; `none` is the internal
# no-command outcome. None of the three is an agent, so factory stays None and
# resolve() returns None for all of them (unchanged, §4).
_CONTROL = (
    AgentSpec( "agent router go to automatic", cls=CommandClass.CONTROL ),
)
_NONE = (
    AgentSpec( "agent router go to receptionist", cls=CommandClass.NONE ),
    AgentSpec( "none",                            cls=CommandClass.NONE ),
)


# ── The one table (§5.1) ──────────────────────────────────────────────────────
def _build_registry( *groups ):
    """
    Build the command→spec table, FAILING LOUD on a duplicate command (M4).

    A dict comprehension over the spec tuples silently drops a duplicate — last
    one wins, no error — so a command declared twice in two different class groups
    would vanish, and the partition guard would pass on a corrupted table because
    the dedup already happened. Raise instead: a command is declared exactly once,
    in exactly one class. The invariant is now ENFORCED at construction, not
    ASSERTED by a test — so no count-comparison guard sits over it (a violation
    raises at import, before any test could observe an inequality; that guard would
    be vacuous). The falsifiable check that survives is "a dup RAISES".

    Requires:
        - each group is an iterable of AgentSpec

    Ensures:
        - Returns { command: spec } for every spec across the groups
        - Raises ValueError on the first command that appears twice
    """
    registry = {}
    for spec in ( s for group in groups for s in group ):
        if spec.command in registry:
            raise ValueError(
                f"duplicate command in registry: {spec.command!r} — a command may be "
                f"declared exactly once, in one class"
            )
        registry[ spec.command ] = spec
    return registry


REGISTRY = _build_registry( _CONVERSATIONAL, _AGENTIC, _CONTROL, _NONE )


# ── The four template buckets, DERIVED from cls (§5.1.2) ──────────────────────
# These replace the four hand-maintained constants with one label per spec: the
# buckets are now a projection of the table, not a fifth list to keep in sync.
V2_AGENTS            = { c: s for c, s in REGISTRY.items() if s.cls is CommandClass.CONVERSATIONAL }
AGENTIC_COMMANDS     = { c: s for c, s in REGISTRY.items() if s.cls is CommandClass.AGENTIC }
CONTROL_COMMANDS     = frozenset( c for c, s in REGISTRY.items() if s.cls is CommandClass.CONTROL )
RECEPTIONIST_OR_NONE = frozenset( c for c, s in REGISTRY.items() if s.cls is CommandClass.NONE )

# ── DEFERRED_COMMANDS — a deliberate BOUNDED INTERIM, retired in phase 2 ───────
# The §9 drift guard (test_v2_registry.py:59) imports this name and asserts
#   template == V2_AGENTS ∪ DEFERRED_COMMANDS ∪ CONTROL_COMMANDS ∪ RECEPTIONIST_OR_NONE.
# DEFERRED_COMMANDS is the template-EMITTABLE agentic subset (7), NOT the full
# agentic set (10): the three extra AGENTIC_AGENTS commands — `bug fix expediter`,
# `test fix expediter resume`, `test suite` — are the §3 "unreachable by voice"
# drifts and are intentionally absent from the router template, so they cannot sit
# in a bucket the guard equates with the template. Deriving it from cls alone would
# make it the 10 and break the guard; it is therefore kept as an explicit set here.
# `test_deferred_is_template_emittable_agentic_subset` pins it to
# AGENTIC_COMMANDS ∩ template so it cannot silently drift from the owned set.
# Phase 2 retires this name when the drift guard is rewritten class-aware.
DEFERRED_COMMANDS = frozenset( {
    "agent router go to deep research",
    "agent router go to podcast generator",
    "agent router go to research to podcast",
    "agent router go to presentation generator",
    "agent router go to research to presentation",
    "agent router go to claude code",
    "agent router go to swe team",
} )


def resolve( command ):
    """
    Resolve a routing command to its CONVERSATIONAL AgentSpec, or None.

    Scoped to CONVERSATIONAL on purpose (§5.1.3): registering the agentic set must
    not silently change what this router-facing function returns. Agentic commands
    still resolve to None here and the flow routes None to the receptionist,
    exactly as before phase 1; agentic specs are reached via resolve_agentic().

    Requires:
        - command is a routing string: a full form ("agent router go to weather")
          or a registered short-form alias ("weather")

    Ensures:
        - Returns the AgentSpec for a conversational command or one of its aliases
        - Returns None for every non-conversational command — agentic, deferred,
          control, receptionist, none, or unknown — which the flow routes to the
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


def resolve_agentic( command ):
    """
    Resolve a routing command to its AGENTIC AgentSpec, or None.

    Separate reader on the same table (§5.1.3). No caller uses it in phase 1 —
    phase 5's factory dispatch will (§5.5). Alias resolution for agentic commands
    is a phase-1 open (§6 assertion 3 note): agentic specs carry no aliases today,
    so this is a full-string lookup.

    Requires:
        - command is a full routing string

    Ensures:
        - Returns the AGENTIC AgentSpec for the command, or None when it is not a
          registered agentic command
        - Never raises on an unknown command

    Args:
        command: The routing command string from the router.

    Returns:
        AgentSpec or None
    """
    return AGENTIC_COMMANDS.get( command )

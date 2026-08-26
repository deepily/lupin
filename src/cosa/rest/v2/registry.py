"""
CJ Flow v2 — the single command→agent registry (plan §3, §3a; revised by cascade
handoff §3.A, R-A1/R-A2/R-A3; agentic set folded in by the 2026.08.15
single-source design, phase 1).

Replaces the three v1 routing mechanisms the survey found drifting apart — the
LLM-routing if/elif chain reached from `push_job()` / `get_routing_command()` in
`todo_fifo_queue.py`, the `MODE_TO_AGENT` map in `todo_fifo_queue.py`, and the
command if/elif in `create_agentic_job()` in `agentic_job_factory.py`. (Symbols,
not line numbers — grep the name; line numbers drift and mislead.) One map, keyed on
the FULL routing string, is what the §9 registry-guard test defends so that drift
cannot reappear.

Resolution order for `required_args` is the MIGRATION PATH, not a fallback chain
(§3a): the agent declares its own args first (phase 2), then the `JOB_ARG_CONTRACTS`
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

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Callable, Optional

from cosa.agents.math_agent          import MathAgent
from cosa.agents.calculator.agent    import CalculatorAgent
from cosa.agents.date_and_time_agent import DateAndTimeAgent
from cosa.agents.todo_list_agent     import TodoListAgent
from cosa.agents.calendaring_agent   import CalendaringAgent
from cosa.agents.weather_agent       import WeatherAgent
from cosa.crud_for_dataframes.todo_crud_agent     import TodoCrudAgent
from cosa.crud_for_dataframes.calendar_crud_agent import CalendarCrudAgent
from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS
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
        - required_args resolves agent-first (declared_args), then JOB_ARG_CONTRACTS,
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
    job_factory   : Optional[ Callable[ ..., Any ] ] = None   # agentic: builds the Job — wired from JOB_BUILDERS (d2e23ecb)
    cli_module    : Optional[ str ]   = None                  # None ⇒ API-invoked (test_suite)
    cli_style     : Optional[ str ]   = None                  # "package" | "module" — documentation only (§6)
    arg_spec      : Optional[ ArgSpec ] = None                # the expeditor's carrier, §5.1.1
    speakable     : bool              = False                 # belongs in the router prompt — RATIFIED (§2.1a), NOT derived from the template (trap 3)
    # ── added by brain integration (row 10ef4b64, 2026-08-20) ──
    # The CRUD fork, declared here and APPLIED BY resolve() for every caller. These
    # three are the table's statement of what the fork changes; nothing else reads
    # them, and no caller reaches a factory by picking one of these itself.
    label         : Optional[ str ]      = None               # what the user HEARS ("new {label} job..."); None ⇒ derive
    crud_factory  : Optional[ Callable[ ..., Any ] ] = None   # the fork's class when `crud for dataframes agents enabled`
    crud_label    : Optional[ str ]      = None               # the fork's spoken label
    dings         : bool                 = True               # v1 rang the new-job gong for every conversational agent EXCEPT weather
    # ── added by the Q&A-card / submit-panel retirement (2026.08.22 plan §5.1) ──
    # `description` is the one user-facing help string the registry did not carry;
    # the 16 lines lived in MODE_METADATA (todo_fifo_queue.py) and moved here so the
    # dropdown, /api/mode/available and the router all read one table.
    #
    # `user_initiable` means "a person may start this by typing into the Q&A card"
    # — RATIFIED data (Rick, 2026-08-22 ruling 1), deliberately NOT derived from
    # `speakable`. The two answer different questions: `speakable` is "belongs in the
    # voice router prompt", this is "belongs in a mouse-driven dropdown". Deriving one
    # from the other works today by coincidence and breaks on the first command that
    # is typeable but not sayable.
    description   : Optional[ str ]      = None
    user_initiable: bool                 = False
    # `label` vs `display_name` — one string a user HEARS, one a user READS, and they
    # are genuinely different registers. `label` goes into spoken text ("new todo list
    # job..."), so it is lowercase prose. `display_name` is the dropdown's option text,
    # so it is a proper name: "Todo List", "Date & Time". Ruled by Mr Radio 2026-08-22
    # after the first cut rendered `label` in the dropdown and turned "Math Agent" into
    # "math". Deriving one from the other loses either the capitals or the prose.
    # `crud_display_name` is the fork's read-label, applied by resolve() beside
    # crud_label — without it a forked agent would keep announcing itself as the
    # unforked one, which is the exact disagreement honouring the fork is meant to end.
    display_name     : Optional[ str ] = None
    crud_display_name: Optional[ str ] = None

    @property
    def required_args( self ) -> tuple[ str, ... ]:
        """
        Resolve this command's required arguments along the §3a migration path.

        Requires:
            - JOB_ARG_CONTRACTS is importable

        Ensures:
            - Returns the agent's own declared required args when its factory
              implements declared_args() (phase 2 destination)
            - Else the JOB_ARG_CONTRACTS entry's required_user_args when present
            - Else this spec's literal _required_args, or () when unset
        """
        if hasattr( self.factory, "declared_args" ):
            return self.factory.declared_args().required
        entry = JOB_ARG_CONTRACTS.get( self.command )
        if entry:
            return tuple( entry[ "required_user_args" ] )
        return self._required_args or ()


# ── The six conversational (phase-1) agents ──────────────────────────────────
# Keyed on the FULL routing string (R-A1); short forms are aliases. The CRUD fork
# is applied by resolve() itself, for every caller — see its docstring for why the
# old R-A3 pin is gone. The executor calls spec.factory with the shared 11-kwarg
# signature and
# the BARE question for every agent (v2 drops MathAgent's salutation quirk, risk 10).
# ⚠️ THE FULL-FORM ALIASES ARE LOAD-BEARING, not tidiness. The v1 voice ladder
# accepted "agent router go to date and time" and "agent router go to todo list"
# as FULL routing strings; before row 10ef4b64 neither resolved here (measured:
# resolve() returned None for both), so routing voice through this table without
# them would have sent two working commands to the loud-fail branch and told the
# user "I don't know how to run that". Pinned by
# test_registry_voice_binding.py::test_every_v1_ladder_command_resolves.
# `description` on each spec is the string that used to live in MODE_METADATA under
# the matching mode key; all six conversational agents are `user_initiable` because
# all six are in the dropdown today.
_CONVERSATIONAL = (
    AgentSpec( "agent router go to math",       MathAgent,        aliases=( "math", ),             speakable=True,
               label="math",         display_name="Math Agent", description="Direct math calculations", user_initiable=True ),
    AgentSpec( "agent router go to calculator", CalculatorAgent,  aliases=( "calculator", ),       speakable=True,
               label="calculator",   display_name="Calculator", description="Unit conversions, price comparison, mortgage", user_initiable=True ),
    AgentSpec( "agent router go to datetime",   DateAndTimeAgent,
               aliases=( "datetime", "agent router go to date and time" ), speakable=True,
               label="date and time", display_name="Date & Time", description="Date/time queries", user_initiable=True ),
    AgentSpec( "agent router go to todo",       TodoListAgent,
               aliases=( "todo", "todo list", "agent router go to todo list" ), speakable=True,
               label="todo list", crud_factory=TodoCrudAgent,     crud_label="todo (CRUD)",
               display_name="Todo List", crud_display_name="Todo List (CRUD)",
               description="Task management", user_initiable=True ),
    AgentSpec( "agent router go to calendar",   CalendaringAgent, aliases=( "calendar", ),         speakable=True,
               label="calendaring", crud_factory=CalendarCrudAgent, crud_label="calendar (CRUD)",
               display_name="Calendar", crud_display_name="Calendar (CRUD)",
               description="Calendar management", user_initiable=True ),
    AgentSpec( "agent router go to weather",    WeatherAgent,
               aliases=( "weather", ), snapshotable=False, _required_args=( "location", ), speakable=True,
               label="weather", dings=False, display_name="Weather", description="Weather queries", user_initiable=True ),
)


def _agentic_spec( command, entry ):
    """
    Build an AGENTIC AgentSpec from a raw JOB_ARG_CONTRACTS entry (§5.1 / §5.1.1).

    Ensures:
        - arg_spec is ArgSpec.from_entry( entry ) — the eight expeditor fields are
          reused, not re-declared, so the copy semantics (bug 8aa89f42) come along
        - cli_module is the entry's, or None (test_suite is API-invoked)
        - cli_style is "module" for a *.cli module-with-__main__-guard, "package"
          for a package needing __main__.py, or None when there is no CLI. It is
          documentation only in phase 1 — no guard branches on it (§6 assertion 5′)
        - job_factory is the command's builder from agentic_job_factory.JOB_BUILDERS
          (row d2e23ecb, phase 5 step 2), or None if the table has no entry — which
          test_1b_factory_branches_equal_the_owned_agentic_set makes a red test
    """
    cli_module = entry.get( "cli_module" )
    if cli_module is None:
        cli_style = None
    elif cli_module.endswith( ".cli" ):
        cli_style = "module"
    else:
        cli_style = "package"
    # Deferred import, INSIDE the function: `create_agentic_job` looks commands up in
    # this registry, so a module-level import here would close the loop. The factory
    # module itself is cheap to import (its job-class imports are deferred inside the
    # builders), so paying it lazily costs nothing but breaks the cycle.
    from cosa.rest.agentic_job_factory import JOB_BUILDERS
    return AgentSpec(
        command        = command,
        cls            = CommandClass.AGENTIC,
        job_factory    = JOB_BUILDERS.get( command ),
        cli_module     = cli_module,
        cli_style      = cli_style,
        arg_spec       = ArgSpec.from_entry( entry ),
        speakable      = command in _SPEAKABLE_AGENTIC,
        # From the contract itself, so there is no second hand-written list of display
        # names to drift from JOB_ARG_CONTRACTS — the same construction argument the
        # _AGENTIC comprehension above makes about the command set.
        display_name   = entry.get( "display_name" ),
        description    = _AGENTIC_DESCRIPTIONS.get( command ),
        user_initiable = command in _USER_INITIABLE_AGENTIC,
    )


# ── The agentic descriptions, moved out of MODE_METADATA (2026.08.22 plan §5.1) ──
# One line per agentic command, keyed on the command rather than on a mode key, so
# there is nothing left to keep in sync with AGENTIC_MODE_MAP. Eight of these are the
# MODE_METADATA strings verbatim; the three expediter lines are new because those
# commands never had a mode key — they were reached from a card, not a dropdown.
_AGENTIC_DESCRIPTIONS = {
    "agent router go to deep research"            : "Investigate a topic in depth",
    "agent router go to podcast generator"        : "Create a podcast from an existing document",
    "agent router go to research to podcast"      : "Research a topic and create a podcast",
    "agent router go to claude code"              : "Run a coding task",
    "agent router go to presentation generator"   : "Generate slides from a document",
    "agent router go to research to presentation" : "Research a topic and create slides",
    "agent router go to swe team"                 : "Multi-agent engineering team",
    "agent router go to test suite"               : "Run integration and E2E tests",
    "agent router go to bug fix expediter"        : "Fix a job that died",
    "agent router go to test fix expediter"       : "Fix a failing test suite run",
    "agent router go to test fix expediter resume": "Resume a stalled test-fix job",
}


# ── The RATIFIED user-initiable agentic set — Rick's ruling 1, 2026-08-22 ─────
# "A person may start this by typing into the Q&A card." Like `speakable`, this is
# ratified rather than derived: no oracle proves which commands a person should be
# able to start by hand. The TWO held OUT are held out for a stated REASON, not by
# omission — both take a job id produced by a job that already ran and failed, and
# nobody types one of those. You press a button on the failed job's card:
#   • "agent router go to bug fix expediter"  — its only argument is `dead_job_id`
#   • "agent router go to test fix expediter" — its only argument is `source_test_suite_job_id`
# `test fix expediter resume` IS in the set: its `resume_from` is a plan path or a
# description a person genuinely types, which is why it has a submit card today —
# and why that card has no job left once the dropdown can express the command.
_USER_INITIABLE_AGENTIC = frozenset( {
    "agent router go to deep research",
    "agent router go to podcast generator",
    "agent router go to research to podcast",
    "agent router go to presentation generator",
    "agent router go to research to presentation",
    "agent router go to claude code",
    "agent router go to swe team",
    "agent router go to test suite",
    "agent router go to test fix expediter resume",
} )


# ── The RATIFIED speakable-agentic set (§2.1a) ────────────────────────────────
# `speakable` can be neither GENERATED (trap 3 forbids deriving it from today's
# template) nor TESTED (no oracle proves which commands a person should be able to
# say out loud — that is a human design judgement). So it is a RATIFIED, checked-in
# decision, and the generator's pin proves NO DRIFT, never correctness.
#
# The nine below are voice-reachable agentic commands. The TWO agentic commands
# held OUT are held out for a stated REASON, not by omission — set `speakable` from
# the reason, so the prompt file must agree with this list, never the reverse:
#   • "agent router go to bug fix expediter"  — card-reachable only; never an initial voice detection
#   • "agent router go to test fix expediter" — START, system-triggered; its job-id arg is not speakable
_SPEAKABLE_AGENTIC = frozenset( {
    "agent router go to deep research",
    "agent router go to podcast generator",
    "agent router go to research to podcast",
    "agent router go to presentation generator",
    "agent router go to research to presentation",
    "agent router go to claude code",
    "agent router go to swe team",
    "agent router go to test fix expediter resume",   # voice-reachable (phase 3)
    "agent router go to test suite",                  # voice-reachable — ruling B, completion (phase 3)
} )


# ── The agentic set — now OWNED by the registry (§5.1) ────────────────────────
# One spec per JOB_ARG_CONTRACTS entry (10), built by iterating the table itself. So
# JOB_COMMANDS (derived below from the CommandClass.AGENTIC label) equals the
# JOB_ARG_CONTRACTS key set BY CONSTRUCTION — there is no second hand-written list to
# drift from it. (Tiberius's §3b cross-check resolved as construction, not a
# runtime test: a set-equality asserted against a set derived from the same table
# is a tautology that can never go red.)
# ⚠️ Do NOT hand-declare an AGENTIC AgentSpec anywhere but this comprehension.
# Adding one by hand is the ONLY way to reintroduce the cls↔JOB_ARG_CONTRACTS drift,
# and — precisely because the invariant is structural — no test would catch it.
_AGENTIC = tuple( _agentic_spec( command, entry ) for command, entry in JOB_ARG_CONTRACTS.items() )

# ── Mode-control and the receptionist/none outcomes, as class-labelled specs ──
# So the four template buckets can be DERIVED from cls (§5.1.2). `automatic` clears
# the user's mode and returns early (todo_fifo_queue.py:739-747); it never routes to
# an agent. `receptionist` is a router template command; `none` is the internal
# no-command outcome. None of the three is an agent, so factory stays None and
# resolve() returns None for all of them (unchanged, §4).
#
# `agent router go to automatic` is NOT user_initiable, and the distinction matters:
# the dropdown's Auto-Route entry is the SENTINEL below, not this command. Auto-Route
# means "do not name a command, let the router decide" — there is nothing to submit.
# This command is the VOICE way to clear a sticky mode, which is a different act.
# `none` is the internal no-command outcome and is not pickable by anybody.
_CONTROL = (
    AgentSpec( "agent router go to automatic", cls=CommandClass.CONTROL, speakable=True,
               description="Normal LLM-based routing" ),
)
# The receptionist is the ONE stated exception (Rick's ruling 3, 2026-08-22): it is
# genuinely both an agent a person picks on purpose AND the else-branch you land on
# when routing fails. `cls=NONE` describes how the ROUTER reaches it and stays;
# `user_initiable=True` says a person may pick it. Two questions, two fields — had
# the dropdown been driven off `cls`, this case would have had nowhere to live.
_NONE = (
    AgentSpec( "agent router go to receptionist", cls=CommandClass.NONE, speakable=True,
               label="receptionist", display_name="Receptionist", description="General assistance", user_initiable=True ),
    AgentSpec( "none",                            cls=CommandClass.NONE, speakable=True ),
)


# ── The Auto-Route sentinel (2026.08.22 plan §5.2) ────────────────────────────
# Auto-Route is the dropdown's "no command named — let the router decide" entry. It
# is NOT a registry command and must never collide with one, so it is declared here,
# ONCE, and rendered from this constant rather than hand-written into the HTML.
#
# WHY A NAMED CONSTANT AND NOT A HAND-WRITTEN <option>: the guard that keeps agent
# lists out of the front end greps for `<option value=` inside #agent-mode. A
# hand-written Auto-Route option would make that guard fire on legitimate scaffolding,
# and the fix would be an exemption — which is how a guard gets quietly widened later.
# With the sentinel rendered like every other option there is nothing to exempt.
# Its label and description are the "system" row of the retired MODE_METADATA.
AUTO_ROUTE_VALUE       = "__auto_route__"
AUTO_ROUTE_LABEL       = "System (Auto-Route)"
AUTO_ROUTE_DESCRIPTION = "Normal LLM-based routing"


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
# ANSWER_COMMANDS vs JOB_COMMANDS — Rick's ruling, 2026-08-16: "one gives you an answer, the other
# gives you a job." The load-bearing difference is FOLLOW-UP QUESTIONS: an answer command never asks
# one; a job command runs an argument interview first. Then what comes back — an answer, versus an
# artifact (podcast, deck, document, code change) — and answers are snapshotable where jobs are not.
#
# It is NOT a speed distinction, and the code says so: todo_fifo_queue.py:831-834 registers BOTH
# kinds with user_job_tracker and pushes them onto the SAME queue, both surfacing a card. `weather`
# calls an external API; `todo` and `calendar` hit a database. An earlier proposal named these six
# INSTANT_COMMANDS and described them as answering "in the same breath, no job, no card" — that
# would have shipped a name asserting something the implementation contradicts.
ANSWER_COMMANDS      = { c: s for c, s in REGISTRY.items() if s.cls is CommandClass.CONVERSATIONAL }
JOB_COMMANDS         = { c: s for c, s in REGISTRY.items() if s.cls is CommandClass.AGENTIC }
CONTROL_COMMANDS     = frozenset( c for c, s in REGISTRY.items() if s.cls is CommandClass.CONTROL )
NO_MATCH = frozenset( c for c, s in REGISTRY.items() if s.cls is CommandClass.NONE )

# ── SPEAKABLE_JOBS — now DERIVED from the `speakable` field (§2.1, 2026.08.16) ──
# Was a hand-kept frozenset of 9 that had to equal JOB_COMMANDS ∩ template. The
# hand-kept LIST is gone: this is a PROJECTION of the ratified `speakable` field
# (_SPEAKABLE_AGENTIC), the template-emittable agentic subset. The §9 drift guard
# (test_v2_registry.py:59) still imports this name and asserts
#   template == ANSWER_COMMANDS ∪ SPEAKABLE_JOBS ∪ CONTROL_COMMANDS ∪ NO_MATCH.
# Phase 2 retires the NAME when that guard is rewritten class-aware; there is no
# longer a second definition to drift from the owned set.
SPEAKABLE_JOBS = frozenset( c for c, s in JOB_COMMANDS.items() if s.speakable )

# ── USER_INITIABLE_COMMANDS — the set the Q&A dropdown must render, exactly ────
# A projection of the ratified `user_initiable` field across EVERY class, which is
# why it is not scoped to one bucket: it spans the six conversational agents, nine of
# the eleven agentic commands, and the receptionist (cls=NONE, ruling 3). The
# dropdown's option values must set-EQUAL this — see the §6 gate 3 rewrite. It is
# deliberately NOT `SPEAKABLE_JOBS` and not derived from `speakable`: a command that
# is user_initiable but not speakable belongs in the dropdown and in no voice prompt.
USER_INITIABLE_COMMANDS = frozenset( c for c, s in REGISTRY.items() if s.user_initiable )


def resolve( command, crud_enabled ):
    """
    Resolve a routing command to its CONVERSATIONAL AgentSpec, or None, WITH the
    CRUD fork already applied.

    ONE resolver, and it is the only thing that applies the fork. There used to be
    two — this one pinned to the non-CRUD class, and resolve_voice() which forked —
    and the pin existed to protect ONE thing: cache-hit REPORTING. CRUD agents are
    never snapshotted, so a v2 report that counted forked calendar and todo traffic
    read 0% cache-hit and looked like a v2 bug. Rick ruled on 2026-08-21 that a
    reporting constraint does not get to shape the table every request routes
    through: the exclusion moved to whatever READS cache-hit counts, and the fork
    moved here, where a caller cannot reach the wrong class by forgetting which
    resolver to call.

    `crud_enabled` is REQUIRED, not defaulted, for the same reason. A default would
    restore the old failure by another name — a caller that forgets the argument
    would silently get the un-forked class, which is exactly the bug the fold
    removes.

    Scoped to CONVERSATIONAL on purpose (§5.1.3): registering the agentic set must
    not silently change what this router-facing function returns. Agentic commands
    still resolve to None here and the flow routes None to the receptionist,
    exactly as before phase 1; agentic specs are reached via resolve_agentic().

    Requires:
        - command is a routing string: a full form ("agent router go to weather")
          or a registered short-form alias ("weather")
        - crud_enabled is the live value of `crud for dataframes agents enabled`

    Ensures:
        - Returns the AgentSpec for a conversational command or one of its aliases
        - Applies the CRUD fork ONLY when crud_enabled is True AND the spec declares
          a crud_factory — so a flag flip changes calendar and todo and nothing else
        - Forks BOTH user-facing strings together: `label` (heard) and `display_name`
          (read). Forking one and not the other would leave a user reading "Todo List"
          while hearing "todo (CRUD)" about the same request
        - A forked spec carries snapshotable=False, because the writer refuses to
          serialize CRUD agents (running_fifo_queue:1563). The table used to say
          "cache this" about a class the writer would not cache — two sources of
          truth that disagreed by construction.
        - Returns None for every non-conversational command — agentic, deferred,
          control, receptionist, none, or unknown — which the flow routes to the
          receptionist (§4, route_reason="unknown_command")
        - Never raises on an unknown command

    Args:
        command      : The routing command string from the router.
        crud_enabled : Whether the CRUD-for-dataframes agents are enabled.

    Returns:
        AgentSpec or None
    """
    spec = ANSWER_COMMANDS.get( command )
    if spec is None:
        for candidate in ANSWER_COMMANDS.values():
            if command in candidate.aliases:
                spec = candidate
                break
    if spec is None:
        return None
    if crud_enabled and spec.crud_factory is not None:
        return replace( spec, factory=spec.crud_factory, label=spec.crud_label,
                        display_name=spec.crud_display_name, snapshotable=False )
    return spec


def canonical_command( command ):
    """
    Map a routing command OR one of its aliases to the registry's canonical spelling.

    WHY THIS EXISTS (row 759a895b, María 🌸's finding). `math` is a registered alias of
    `agent router go to math` (this file, the conversational table), and `resolve()`
    honours aliases — so a router emitting the short form ROUTES CORRECTLY. What did not
    happen is the record adopting the canonical name: `v2/flow.py:_emit` copied the raw
    router string into `payload.command`, so one route reached the output vocabulary under
    two spellings. Every downstream count grouped by that field then split silently, and an
    exact-match routing score marked a CORRECT route as a miss.

    Measured in `io/v2-flow/eval-2026-08-25-19-31-31/records.jsonl`: 50 records spell it
    `agent router go to math` and 2 spell it `math`, same `route_reason`, and both bare
    records are the same utterance in the cold and warm passes.

    Scoped to the WHOLE registry, not just the conversational class, because the output
    vocabulary is the whole registry — an agentic alias would split a count exactly the
    same way. `resolve()` cannot serve here: it is deliberately conversational-only and
    returns None for every agentic command.

    Requires:
        - command is a string, or None

    Ensures:
        - returns the canonical command when `command` is a registry command or an alias
        - returns `command` UNCHANGED when it is neither, and when it is None — an unknown
          string is not this function's business to invent a spelling for, and callers pass
          None on paths that never had a command
        - never raises
    """
    if not command:
        return command
    if command in REGISTRY:
        return command
    for canonical, spec in REGISTRY.items():
        if command in spec.aliases:
            return canonical
    return command


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
    return JOB_COMMANDS.get( command )

"""
Brain integration (row 10ef4b64) — the voice queue's command→agent binding.

WHAT THIS FILE DEFENDS. Before this change `todo_fifo_queue.push_job` ran the routed
command down a hand-written if/elif ladder of ~10 branches, each naming one agent
class, while `cosa/rest/v2/registry.py` held the same mapping as data and only the
HTTP route asked it. Rick, 2026-08-20: "those agents could be instantiated using a
string key referencing a dictionary of prototypical Agent Objects... that doesn't
take 10 elif branches."

The ladder is gone. These pins exist so it cannot grow back, and so the two
behaviour decisions taken on the way are stated rather than assumed.

EVERY TEST HERE HAS BEEN SEEN FAILING — each names the mutation that reddens it.
A test never observed failing is a comment with a green tick.
"""

import inspect
import io
import tokenize

import pytest

from cosa.rest.v2.registry import resolve
from cosa.agents.math_agent          import MathAgent
from cosa.agents.calculator.agent    import CalculatorAgent
from cosa.agents.date_and_time_agent import DateAndTimeAgent
from cosa.agents.todo_list_agent     import TodoListAgent
from cosa.agents.calendaring_agent   import CalendaringAgent
from cosa.agents.weather_agent       import WeatherAgent
from cosa.crud_for_dataframes.todo_crud_agent     import TodoCrudAgent
from cosa.crud_for_dataframes.calendar_crud_agent import CalendarCrudAgent


def _code_only( source ):
    """
    Strip comments from a source block, keeping the code.

    Written because the first version of test_queue_names_no_conversational_agent_class
    failed on a COMMENT that names MathAgent — the note recording that math
    deliberately stopped receiving the salutation. Scanning raw text would have forced
    a choice between deleting useful documentation and weakening the check; scanning
    code keeps both. The comment is the record of a behaviour change and belongs there.

    Requires:
        - source is a syntactically valid Python block (dedented or not)

    Ensures:
        - returns the source with every COMMENT token removed
        - leaves string literals untouched (a class named in a docstring would still
          be caught, which is the conservative direction)
    """
    out    = []
    reader = io.StringIO( inspect.cleandoc( "\n" + source ) ).readline
    for token in tokenize.generate_tokens( reader ):
        if token.type != tokenize.COMMENT:
            out.append( token.string )
    return " ".join( out )


# Every FULL routing string the v1 ladder accepted, read off the branches before
# they were deleted. Two of these did NOT resolve when this work started —
# "date and time" and "todo list" — so a naive migration would have sent working
# commands to the loud-fail branch.
_V1_LADDER_COMMANDS = (
    "agent router go to calendar",
    "agent router go to calculator",
    "agent router go to math",
    "agent router go to todo",
    "agent router go to todo list",
    "agent router go to date and time",
    "agent router go to datetime",
    "agent router go to weather",
)


class TestEveryV1CommandStillResolves:
    """The migration must not silently drop a routing string that worked."""

    @pytest.mark.parametrize( "command", _V1_LADDER_COMMANDS )
    def test_every_v1_ladder_command_resolves( self, command ):
        """
        RED ON REVERT: drop "agent router go to date and time" (or
        "agent router go to todo list") from its AgentSpec aliases and this fails
        for that command — which is exactly the state the tree was in before
        row 10ef4b64. Measured, not assumed: resolve() returned None for both.
        """
        assert resolve( command, crud_enabled=False ) is not None, (
            f"{command!r} routed to an agent under the v1 ladder and now resolves "
            f"nowhere — it would reach the loud-fail branch and tell the user the "
            f"command is unknown"
        )

    @pytest.mark.parametrize( "command", _V1_LADDER_COMMANDS )
    def test_every_v1_ladder_command_has_a_voice_binding( self, command ):
        """Every ladder command still resolves, with a callable and a spoken label."""
        binding = resolve( command, crud_enabled=False )
        assert binding is not None
        assert callable( binding.factory )
        assert binding.label, f"{command!r} has no spoken label — the user hears 'New  job...'"


class TestCrudForkIsCarriedByTheRegistry:
    """
    Rick's ruling, 2026-08-20: voice keeps its current behaviour and the REGISTRY
    carries the flag. The v2 `factory` stays pinned to the non-CRUD class because
    CRUD agents are never snapshotted (R-A3) — a REPORTING decision, which must not
    change what a spoken command does.
    """

    @pytest.mark.parametrize( "command,crud_cls,plain_cls", [
        ( "agent router go to todo",     TodoCrudAgent,     TodoListAgent ),
        ( "agent router go to calendar", CalendarCrudAgent, CalendaringAgent ),
    ] )
    def test_fork_follows_the_flag( self, command, crud_cls, plain_cls ):
        """
        RED ON REVERT: make resolve() ignore crud_enabled and always return
        spec.factory, and the crud_enabled=True half fails — which is the v2 pin
        leaking onto the voice path, the exact regression Rick ruled against.
        """
        assert resolve( command, crud_enabled=True  ).factory is crud_cls
        assert resolve( command, crud_enabled=False ).factory is plain_cls

    def test_the_forked_spec_says_it_is_not_cacheable( self ):
        """
        Step 2d, and it replaces the old R-A3 pin rather than re-pointing it. That
        pin held resolve() to the non-CRUD class so a v2 report would not read 0%
        cache-hit; the exclusion now lives in the reader (v2_eval), and what the
        table owes instead is the truth about the forked class.

        The writer refuses to serialize CRUD agents (running_fifo_queue:1563), so a
        forked spec claiming snapshotable=True would be two sources of truth
        disagreeing by construction — a flag saying "cache this" about a class the
        writer will not cache.

        RED ON REVERT: drop snapshotable=False from the fork in resolve() and this
        fails.
        """
        for command in ( "agent router go to todo", "agent router go to calendar" ):
            forked = resolve( command, crud_enabled=True )
            plain  = resolve( command, crud_enabled=False )
            assert forked.snapshotable is False, f"{command} forked to CRUD and still claims it caches"
            assert plain.snapshotable is True,   f"{command} unforked lost its cacheability"

    @pytest.mark.parametrize( "command", [
        "agent router go to math", "agent router go to calculator",
        "agent router go to weather", "agent router go to datetime",
    ] )
    def test_flag_moves_nothing_else( self, command ):
        """
        A flag flip changes calendar and todo and NOTHING else.

        RED ON REVERT: give any of these four a crud_factory and it fails.
        """
        assert resolve( command, crud_enabled=True ).factory is \
               resolve( command, crud_enabled=False ).factory


class TestSpokenLabelsAndTheGong:
    """What the user hears. The ladder's strings were load-bearing, not decoration."""

    @pytest.mark.parametrize( "command,crud_enabled,expected", [
        ( "agent router go to math",          False, "math" ),
        ( "agent router go to calculator",    False, "calculator" ),
        ( "agent router go to datetime",      False, "date and time" ),
        ( "agent router go to date and time", False, "date and time" ),
        ( "agent router go to weather",       False, "weather" ),
        ( "agent router go to todo",          False, "todo list" ),
        ( "agent router go to todo",          True,  "todo (CRUD)" ),
        ( "agent router go to calendar",      False, "calendaring" ),
        ( "agent router go to calendar",      True,  "calendar (CRUD)" ),
    ] )
    def test_label_matches_what_v1_said( self, command, crud_enabled, expected ):
        """
        RED ON REVERT: change any label in the table and its row fails. These
        strings are read verbatim off the deleted ladder's
        starting_a_new_job.format( agent_type=... ) calls.
        """
        assert resolve( command, crud_enabled ).label == expected

    def test_weather_alone_does_not_ring_the_gong( self ):
        """
        v1 set ding_for_new_job=True for every conversational agent EXCEPT weather.

        RED ON REVERT: flip weather's `dings` to True (or drop the field and default
        every agent to one value) and this fails.
        """
        assert resolve( "agent router go to weather", False ).dings is False
        for command in ( "agent router go to math", "agent router go to calculator",
                         "agent router go to todo", "agent router go to calendar",
                         "agent router go to datetime" ):
            assert resolve( command, False ).dings is True, command


class TestTheLadderIsGoneAndStaysGone:
    """
    The point of the whole exercise: a seventh conversational command must need no
    edit to the queue.
    """

    def test_queue_names_no_conversational_agent_class( self ):
        """
        RED ON REVERT: restore any deleted branch — e.g. `elif command == "agent
        router go to weather": agent = WeatherAgent( ... )` — and this fails,
        because push_job would name an agent class again.

        Scoped to push_job's source rather than the module: the module still
        imports these classes for MODE_TO_AGENT and the CRUD helpers, and banning
        the imports would be a different (and false) claim.
        """
        from cosa.rest.todo_fifo_queue import TodoFifoQueue
        source = _code_only( inspect.getsource( TodoFifoQueue.push_job ) )
        for cls in ( "MathAgent", "CalculatorAgent", "DateAndTimeAgent",
                     "TodoListAgent", "CalendaringAgent", "WeatherAgent",
                     "TodoCrudAgent", "CalendarCrudAgent" ):
            assert cls not in source, (
                f"push_job names {cls} directly — the if/elif ladder is growing "
                f"back. Add an AgentSpec row instead."
            )

    def test_push_job_asks_the_registry( self ):
        """RED ON REVERT: delete the resolve() call and this fails.

        The pin follows the fold: there is one resolver now, so the name to look
        for changed. Step 6c invalidates this again when push_job stops resolving
        at all.
        """
        from cosa.rest.todo_fifo_queue import TodoFifoQueue
        source = inspect.getsource( TodoFifoQueue.push_job )
        assert "resolve(" in source

    def test_a_new_command_needs_no_queue_edit( self ):
        """
        The claim stated as an executable check: a command registered ONLY in the
        table resolves through the voice reader without push_job knowing its name.

        RED ON REVERT: make resolve() consult a hard-coded command list instead
        of the table and this fails.
        """
        from cosa.rest.v2 import registry as reg
        spec = reg.AgentSpec( "agent router go to seventh thing", MathAgent,
                              label="seventh thing" )
        saved = dict( reg.ANSWER_COMMANDS )
        reg.ANSWER_COMMANDS[ spec.command ] = spec
        try:
            binding = resolve( "agent router go to seventh thing", crud_enabled=True )
            assert binding is not None, "a table-only command did not resolve"
            assert binding.label == "seventh thing"
        finally:
            reg.ANSWER_COMMANDS.clear()
            reg.ANSWER_COMMANDS.update( saved )


class TestUnroutableStillFailsLoud:
    """
    720ce725's loud-fail branch must survive the migration. It is what stopped a
    router miss from silently web-searching the user's question.
    """

    def test_unknown_command_resolves_to_nothing( self ):
        """
        RED ON REVERT: give resolve() a receptionist default instead of None and
        this fails — which would restore the silent-smoothing defect 720ce725 fixed.
        """
        assert resolve( "agent router go to something nobody wired", True ) is None
        assert resolve( "", True ) is None

    def test_agentic_and_control_are_not_voice_conversational( self ):
        """
        resolve() is scoped to CONVERSATIONAL on purpose (§5.1.3). The queue's
        agentic and automatic-mode branches must keep their own handling — if these
        started resolving here, the confirmation prompt before an agentic command
        would silently disappear.

        RED ON REVERT: widen resolve() to the whole REGISTRY and this fails.
        """
        assert resolve( "agent router go to automatic", True ) is None
        assert resolve( "agent router go to receptionist", True ) is None


class TestTheSecondResolverIsGone:
    """
    2b's deletion, stated as a check. `resolve_voice()` existed only to apply the
    CRUD fork beside a resolver pinned against it; with one resolver there is
    nothing for it to do, and leaving it importable would let a caller keep using
    the two-reader shape the fold removes.
    """

    def test_resolve_voice_no_longer_exists( self ):
        """RED ON REVERT: put resolve_voice back and this fails."""
        from cosa.rest.v2 import registry as reg
        assert not hasattr( reg, "resolve_voice" ), (
            "resolve_voice is back — there is one CRUD-aware resolver now, and a second "
            "reader is how the wrong class gets reached again"
        )

    def test_resolve_will_not_answer_without_the_flag( self ):
        """
        The flag is required, not defaulted, for the same reason the second resolver
        is gone: a caller that omits it would silently get the un-forked class.

        RED ON REVERT: give crud_enabled a default in resolve().
        """
        with pytest.raises( TypeError ):
            resolve( "agent router go to todo" )

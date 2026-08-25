"""
Unit tests for the kill guard (row cd332d2b).

The guard denies, from the PreToolUse hook, a Bash command that can signal a
Claude Code seat it does not own — either by naming a PID /proc reports as a
live `claude` process (SHAPE A), or by feeding a fleet-wide `ps`/`pgrep` listing
into a kill (SHAPE B). SHAPE B is the form that took out three seats on
2026-08-21 ten seconds after the CLI's own `pkill` shim refused the same
pattern by name.

Coverage target is 100% lines AND branches on kill_guard.py (Lupin-wide gate).
The one exclusion is the fail-open `except Exception` backstop, which carries a
same-line pragma explaining why it is genuinely unreachable.
"""
import pytest

from lupin_cli.claude_code.hooks.lib.kill_guard import (
    kill_deny_reason,
    build_kill_deny_response,
    _guard_disabled,
    _default_comm_reader,
    _literal_pids,
    _claude_pids_targeted,
    _sweeps_unscoped,
    _strip_heredocs,
    _deny_reason_for,
    CLAUDE_COMM,
    BASH_TOOL_NAMES,
)


# The verbatim command from the incident, copied out of the dead seat's own
# transcript. If the guard ever stops denying THIS string, the guard is gone.
INCIDENT_COMMAND = (
    'ps -eo pid,etimes,args | grep "[p]ytest src/tests/unit" | awk \'{print $1}\' '
    '| while read p; do kill $p 2>/dev/null && echo "killed $p"; done; sleep 1; '
    'ps -eo args | grep -c "[p]ytest src/tests/unit"'
)


def _no_claude( pid ):
    """comm_reader stub: nothing on the box is a seat."""
    return "pytest"


def _all_claude( pid ):
    """comm_reader stub: every probed PID is a seat."""
    return CLAUDE_COMM


def _deny( command, comm_reader=_no_claude, **kw ):
    """Run the guard over one Bash command with the guard forced ON."""
    kw.setdefault( "enabled", True )
    return kill_deny_reason( "Bash", { "command": command }, comm_reader=comm_reader, **kw )


# ---------------------------------------------------------------------------
# The incident itself — the one test that must never be allowed to pass by luck
# ---------------------------------------------------------------------------

def test_the_2026_08_21_command_is_denied_verbatim():
    """The exact sweep that killed three seats, as it appears in the transcript."""
    reason = _deny( INCIDENT_COMMAND )
    assert reason is not None
    assert "fleet-wide" in reason


def test_the_incident_command_is_denied_before_any_pid_is_known():
    """SHAPE B must not depend on /proc — the PIDs are not in the command text."""
    probed = []

    def recording_reader( pid ):
        probed.append( pid )
        return "pytest"

    assert _deny( INCIDENT_COMMAND, comm_reader=recording_reader ) is not None
    assert probed == []


# ---------------------------------------------------------------------------
# SHAPE A — a literal PID that /proc says is a seat
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "command", [
    "kill 127519",
    "kill -9 127519",
    "kill -KILL 127519",
    "kill -s TERM 127519",
    "kill --signal=9 127519",
    "sleep 1; kill 127519",
    "true && kill 127519",
] )
def test_killing_a_live_seat_by_pid_is_denied( command ):

    reason = _deny( command, comm_reader=_all_claude )
    assert reason is not None
    assert "127519" in reason
    assert "LIVE Claude Code sessions" in reason


def test_only_the_seat_pids_are_named():
    """A mixed kill list names the seats and stays quiet about the rest."""
    reason = _deny(
        "kill 111 127519 222",
        comm_reader=lambda pid: CLAUDE_COMM if pid == "127519" else "pytest",
    )
    assert "127519" in reason
    assert "111" not in reason


def test_killing_a_non_seat_pid_is_allowed():

    assert _deny( "kill 4242" ) is None


def test_a_dead_pid_is_allowed():
    """comm_reader returns None for a PID that has already exited."""
    assert _deny( "kill 4242", comm_reader=lambda pid: None ) is None


@pytest.mark.parametrize( "command", [ "kill %1", "kill $!", "kill ${pid}" ] )
def test_job_specs_and_expansions_carry_no_literal_pid( command ):
    """These name no PID in the text, so SHAPE A has nothing to probe."""
    assert _deny( command, comm_reader=_all_claude ) is None


def test_shape_a_wins_over_shape_b_because_it_can_name_the_victims():
    """A command that is BOTH shapes reports the PIDs rather than the sweep."""
    reason = _deny(
        "ps -e | grep x | xargs kill; kill 127519",
        comm_reader=_all_claude,
    )
    assert "127519" in reason


# ---------------------------------------------------------------------------
# SHAPE B — a fleet-wide listing with a kill downstream
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "command", [
    'ps aux | grep pytest | awk "{print $2}" | xargs kill -9',
    "ps -e | xargs kill",
    "ps -A -o pid | xargs kill",
    "ps ax | xargs killall",
    "pgrep -f pytest | xargs -r kill",
    "pgrep pytest | xargs sudo kill",
    "for p in $(pgrep -f pytest); do kill $p; done",
] )
def test_unscoped_sweeps_are_denied( command ):

    reason = _deny( command )
    assert reason is not None
    assert "fleet-wide" in reason


@pytest.mark.parametrize( "command", [
    "pkill -P $$ -f pytest",
    "pgrep -P $$ -f pytest | xargs -r kill",
    "pgrep --parent $$ | xargs kill",
    "ps --ppid $$ -o pid | xargs kill",
] )
def test_own_children_sweeps_are_allowed( command ):

    assert _deny( command ) is None


@pytest.mark.parametrize( "command", [
    "ps aux | grep pytest",
    "ps -ef | head -20",
    "pgrep -f pytest",
    "ps -e | wc -l",
] )
def test_a_listing_with_no_kill_downstream_is_allowed( command ):

    assert _deny( command ) is None


def test_a_kill_upstream_of_the_listing_is_not_downstream_of_it():
    """A kill that ran BEFORE the listing cannot consume the listing's output."""
    assert _deny( "kill %1; ps -e | wc -l" ) is None


def test_a_scoped_listing_does_not_excuse_a_later_unscoped_one():
    """The first listing being safe must not silence the second."""
    reason = _deny( "pgrep -P $$ | wc -l; pgrep -f pytest | xargs kill" )
    assert reason is not None


def test_ps_without_an_all_selector_is_not_a_fleet_wide_listing():
    """A bare `ps` shows this terminal's processes, not the box's."""
    assert _deny( "ps | xargs kill" ) is None


def test_the_word_kill_inside_a_quoted_argument_is_not_a_kill():

    assert _deny( 'echo "ps -e | xargs kill is dangerous" > notes.md' ) is None


# ---------------------------------------------------------------------------
# Heredoc bodies are DATA — writing a file about a sweep is not running one
# ---------------------------------------------------------------------------

def test_a_heredoc_documenting_a_sweep_is_allowed():
    """The false positive that this guard produced against its own test file."""
    command = "cat > notes.py <<'EOF'\nBAD = 'ps -e | xargs kill'\nEOF\necho written"
    assert _deny( command ) is None


def test_an_unquoted_heredoc_body_is_also_data():

    assert _deny( "cat > notes.py <<EOF\nps aux | xargs kill\nEOF" ) is None


def test_a_real_sweep_after_a_heredoc_is_still_denied():
    """Stripping the body must not swallow the commands that follow it."""
    command = "cat > notes.py <<'EOF'\nhello\nEOF\npgrep -f pytest | xargs kill"
    assert _deny( command ) is not None


def test_an_unterminated_heredoc_drops_the_rest_as_data():

    assert _deny( "cat <<'EOF'\npgrep -f pytest | xargs kill" ) is None


def test_strip_heredocs_returns_a_command_without_one_unchanged():

    assert _strip_heredocs( "ps -e | wc -l" ) == "ps -e | wc -l"


def test_strip_heredocs_keeps_the_introducing_and_terminating_lines():

    stripped = _strip_heredocs( "cat <<'EOF'\nbody\nEOF\ntail" )
    assert stripped == "cat <<'EOF'\nEOF\ntail"


def test_a_second_heredoc_after_the_first_closes_is_also_stripped():

    command = "cat <<'A'\nps -e | xargs kill\nA\ncat <<'B'\npgrep x | xargs kill\nB"
    assert _deny( command ) is None


# ---------------------------------------------------------------------------
# Gating: tool name, payload shape, and the escape hatch
# ---------------------------------------------------------------------------

def test_non_bash_tools_are_ignored():

    assert kill_deny_reason( "Read", { "command": INCIDENT_COMMAND }, enabled=True ) is None


def test_bash_is_the_guarded_tool_name():

    assert BASH_TOOL_NAMES == ( "Bash", )


@pytest.mark.parametrize( "tool_input", [ None, "not-a-dict", [] ] )
def test_a_non_dict_tool_input_is_ignored( tool_input ):

    assert kill_deny_reason( "Bash", tool_input, enabled=True ) is None


@pytest.mark.parametrize( "command", [ "", None, 17 ] )
def test_a_missing_or_non_string_command_is_ignored( command ):

    assert kill_deny_reason( "Bash", { "command": command }, enabled=True ) is None


def test_an_absent_command_key_is_ignored():

    assert kill_deny_reason( "Bash", {}, enabled=True ) is None


def test_the_guard_can_be_disabled_explicitly():

    assert kill_deny_reason(
        "Bash", { "command": INCIDENT_COMMAND }, enabled=False
    ) is None


@pytest.mark.parametrize( "value", [ "1", "true", "on", "yes", "YES", " True " ] )
def test_the_escape_hatch_disables_the_guard( value ):

    assert kill_deny_reason(
        "Bash", { "command": INCIDENT_COMMAND },
        env={ "LUPIN_ALLOW_UNSCOPED_KILL": value },
        comm_reader=_no_claude,
    ) is None


@pytest.mark.parametrize( "value", [ "0", "false", "off", "", "maybe" ] )
def test_a_non_truthy_flag_leaves_the_guard_on( value ):

    assert kill_deny_reason(
        "Bash", { "command": INCIDENT_COMMAND },
        env={ "LUPIN_ALLOW_UNSCOPED_KILL": value },
        comm_reader=_no_claude,
    ) is not None


def test_an_absent_flag_leaves_the_guard_on():

    assert _guard_disabled( env={} ) is False


def test_guard_disabled_reads_the_real_environment_when_none_is_injected( monkeypatch ):

    monkeypatch.setenv( "LUPIN_ALLOW_UNSCOPED_KILL", "1" )
    assert _guard_disabled() is True


def test_the_guard_defaults_to_the_real_environment( monkeypatch ):
    """`enabled=None` resolves from os.environ rather than assuming ON."""
    monkeypatch.setenv( "LUPIN_ALLOW_UNSCOPED_KILL", "1" )
    assert kill_deny_reason( "Bash", { "command": INCIDENT_COMMAND } ) is None


def test_the_guard_defaults_to_the_real_proc( monkeypatch ):
    """`comm_reader=None` resolves to /proc — PID 1 is not a seat, so: allowed."""
    monkeypatch.delenv( "LUPIN_ALLOW_UNSCOPED_KILL", raising=False )
    assert kill_deny_reason( "Bash", { "command": "kill 1" } ) is None


# ---------------------------------------------------------------------------
# The helpers, directly
# ---------------------------------------------------------------------------

def test_default_comm_reader_reads_a_live_process():

    import os
    assert _default_comm_reader( str( os.getpid() ) ) is not None


def test_default_comm_reader_returns_none_for_an_unreadable_pid():

    assert _default_comm_reader( "0" ) is None


def test_literal_pids_keeps_bare_digits_and_drops_flags():

    assert _literal_pids( " -9 -s TERM 111 %1 $! 222" ) == [ "111", "222" ]


def test_claude_pids_targeted_returns_empty_without_a_kill():

    assert _claude_pids_targeted( "ps -e", _all_claude ) == []


def test_sweeps_unscoped_is_false_for_an_empty_command():

    assert _sweeps_unscoped( "" ) is False


def test_deny_reason_names_the_substitutes():

    reason = _deny_reason_for( [] )
    assert "pkill -P $$" in reason
    assert "LUPIN_ALLOW_UNSCOPED_KILL=1" in reason


def test_deny_reason_cites_the_incident_row():

    assert "cd332d2b" in _deny_reason_for( [] )


# ---------------------------------------------------------------------------
# The hook envelope
# ---------------------------------------------------------------------------

def test_build_kill_deny_response_shape():

    response = build_kill_deny_response( "because" )
    assert response == {
        "hookSpecificOutput": {
            "hookEventName"            : "PreToolUse",
            "permissionDecision"       : "deny",
            "permissionDecisionReason" : "because",
        }
    }

"""
Census guard: each argument an agent CLI shows the expeditor can be answered unattended.

Commit 8c67765d4 added `review` to the podcast CLI's visible arguments and nothing else.
The expeditor asked for it with the generic "Please provide the 'review' argument." The
proxy answered "", and the batch check rejects an empty answer. The podcast smoke
scenarios then ended "User cancelled unexpectedly" (the row for that failure is in the commit message).

The rule covers every registry entry that has a CLI. Each name its CLI lists under
--user-visible-args needs a `fallback_defaults` value in the registry. Failing that, it
needs an entry with that `arg_name` in a proxy script under
src/conf/notification-proxy-scripts/.

The names come from the CLI itself, through get_user_visible_args(). That is the
`python -m <cli_module> --user-visible-args` call the expeditor makes, not a copy.
"""

import glob
import json

import pytest

import cosa.agents.runtime_argument_expeditor.agent_registry as ar
import cosa.utils.util as cu


SCRIPT_GLOB = "/src/conf/notification-proxy-scripts/*.json"


def _proxy_answered_arg_names():
    """
    Collect every arg_name that any proxy script answers.

    Ensures:
        - returns a set of strings, read from the scripts' own entries
    """
    names = set()
    for path in glob.glob( cu.get_project_root() + SCRIPT_GLOB ):
        with open( path ) as handle:
            for entry in json.load( handle ).get( "entries", [] ):
                if entry.get( "arg_name" ): names.add( entry[ "arg_name" ] )
    return names


def _uncovered( visible_by_command, answered ):
    """
    Return { command: [ arg, ... ] } for visible args with no default and no proxy answer.
    """
    out = {}
    for command, visible in visible_by_command.items():
        defaults = ar.JOB_ARG_CONTRACTS[ command ][ "fallback_defaults" ]
        missing  = [ arg for arg in visible if arg not in defaults and arg not in answered ]
        if missing: out[ command ] = missing
    return out


@pytest.fixture( scope="module" )
def visible_by_command():
    """The CLI-reported visible args of every registry entry that has a CLI."""
    ar._user_visible_cache.clear()
    found = {}
    for command, entry in ar.JOB_ARG_CONTRACTS.items():
        if entry[ "cli_module" ] is None: continue
        visible = ar.get_user_visible_args( command )
        if visible: found[ command ] = visible
    return found


def test_every_expeditor_visible_arg_has_a_default_or_proxy_answer( visible_by_command ):
    # The loop must have found something: a CLI that failed to answer would pass silently.
    assert len( visible_by_command ) >= 6, f"only {sorted( visible_by_command )} reported visible args"
    assert "review" in visible_by_command[ "agent router go to podcast generator" ]
    answered = _proxy_answered_arg_names()
    assert "query" in answered
    assert _uncovered( visible_by_command, answered ) == {}


def test_the_guard_catches_an_arg_with_no_default_and_no_answer( visible_by_command ):
    """Instrument check: a made-up arg added to one CLI's list is reported, by name."""
    command = "agent router go to podcast generator"
    mutated = dict( visible_by_command )
    mutated[ command ] = visible_by_command[ command ] + [ "no_such_arg_zzz" ]
    assert _uncovered( mutated, _proxy_answered_arg_names() ) == { command: [ "no_such_arg_zzz" ] }

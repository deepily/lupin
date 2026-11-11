#!/usr/bin/env python3
"""
Unit tests for the command-line parser of cosa.agents.notification_proxy.__main__.

parse_args takes its shared options (host, port, email, password, session-id, debug, verbose,
dry-run) from proxy_agents.base_cli.add_common_args and adds --profile and --strategy itself.
The expected values below are literals, taken from what the parser answered before it used the helper.
"""

import sys
from unittest.mock import patch

import pytest

from cosa.agents.notification_proxy.__main__ import parse_args


def _parse( *argv ):
    """
    Run parse_args with the given command-line words.

    Ensures:
        - returns the argparse.Namespace for those words
    """
    with patch.object( sys, "argv", [ "notification_proxy", *argv ] ):
        return parse_args()


class TestDefaults:
    """With no words on the command line, every option holds the value the parser always gave it."""

    def test_connection_defaults( self ):
        args = _parse()
        assert args.host       == "localhost"
        assert args.port       == 7999
        assert args.email      is None
        assert args.password   is None

    def test_session_id_keeps_the_notification_proxy_default( self ):
        """The helper's own default is None; this proxy overrides it with its own session id."""
        assert _parse().session_id == "auto proxy"

    def test_flags_default_off( self ):
        args = _parse()
        assert ( args.debug, args.verbose, args.dry_run ) == ( False, False, False )

    def test_profile_and_strategy_defaults( self ):
        args = _parse()
        assert args.profile  == "deep_research"
        assert args.strategy == "llm_script"


class TestOverrides:
    """Each shared option still parses under its old spelling."""

    def test_every_shared_option_is_accepted( self ):
        args = _parse( "--host", "example.test", "--port", "8123", "--email", "a@b.test", "--password", "pw",
                       "--session-id", "mine", "--debug", "--verbose", "--dry-run" )
        assert args.host       == "example.test"
        assert args.port       == 8123
        assert args.email      == "a@b.test"
        assert args.password   == "pw"
        assert args.session_id == "mine"
        assert ( args.debug, args.verbose, args.dry_run ) == ( True, True, True )

    def test_port_is_an_integer( self ):
        with pytest.raises( SystemExit ):
            _parse( "--port", "not-a-number" )

    def test_own_options_still_validate( self ):
        assert _parse( "--strategy", "rules" ).strategy == "rules"
        with pytest.raises( SystemExit ):
            _parse( "--profile", "no-such-profile" )
        with pytest.raises( SystemExit ):
            _parse( "--strategy", "no-such-strategy" )

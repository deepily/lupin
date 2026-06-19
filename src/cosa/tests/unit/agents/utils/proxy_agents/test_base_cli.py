"""
Unit tests for cosa/agents/utils/proxy_agents/base_cli.py.

Pure argparse wiring — no seams, ZERO API spend.
"""
import argparse

from cosa.agents.utils.proxy_agents.base_cli import add_common_args
from cosa.agents.utils.proxy_agents.base_config import DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT


def test_add_common_args_returns_parser_for_chaining():
    parser = argparse.ArgumentParser()
    assert add_common_args( parser ) is parser


def test_add_common_args_defaults():
    parser = add_common_args( argparse.ArgumentParser() )
    args = parser.parse_args( [] )
    assert args.host     == DEFAULT_SERVER_HOST
    assert args.port     == DEFAULT_SERVER_PORT
    assert args.email    is None
    assert args.password is None
    assert args.session_id is None
    assert args.debug    is False
    assert args.verbose  is False
    assert args.dry_run  is False


def test_add_common_args_parses_overrides():
    parser = add_common_args( argparse.ArgumentParser() )
    args = parser.parse_args( [
        "--host", "example.com", "--port", "8123",
        "--email", "a@x.com", "--password", "pw",
        "--session-id", "wise penguin",
        "--debug", "--verbose", "--dry-run",
    ] )
    assert args.host == "example.com"
    assert args.port == 8123
    assert args.email == "a@x.com"
    assert args.password == "pw"
    assert args.session_id == "wise penguin"
    assert args.debug   is True
    assert args.verbose is True
    assert args.dry_run is True

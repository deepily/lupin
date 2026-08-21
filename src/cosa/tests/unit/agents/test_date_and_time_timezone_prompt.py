#!/usr/bin/env python3
"""
Unit tests: the date-and-time agent is told WHICH clock to read.

THE BUG THESE GUARD ( row e7b1e137 ): asked "what time is it" at 11:28 AM EDT on
2026-08-21, the agent answered "It's 3:28 PM" — UTC. The container clock is UTC and
nothing in the prompt said otherwise, so the generated code called a bare
`datetime.now()`. The reasoner template went further and told the model to ASSUME the
host was set to the user's zone.

These tests read the SHIPPING template files, not a copy, so reverting the fix turns
them red. Each assertion below was proven red against the pre-fix templates.
"""
import re
import zoneinfo

import pytest

import cosa.utils.util as du

TEMPLATES = [
    "/src/conf/prompts/agents/date-and-time.txt",            # the wired one (lupin-app.ini:266)
    "/src/conf/prompts/agents/date-and-time-reasoner.txt",   # the unwired variant, same defect text
]

def _read( rel_path: str ) -> str:
    with open( du.get_project_root() + rel_path, encoding="utf-8" ) as handle:
        return handle.read()

@pytest.mark.parametrize( "rel_path", TEMPLATES )
def test_template_carries_a_timezone_placeholder( rel_path ):
    """The zone must be injected, not hardcoded in the prose."""
    body = _read( rel_path )
    assert "{timezone}" in body, f"{rel_path} names no timezone — generated code will read the UTC container clock"

@pytest.mark.parametrize( "rel_path", TEMPLATES )
def test_template_does_not_tell_the_model_to_trust_the_host_clock( rel_path ):
    """The exact instruction that caused the 4-hour error must stay gone."""
    body = _read( rel_path ).lower()
    assert "must assume that server hosting" not in body, (
        f"{rel_path} still tells the model to assume the host has the user's timezone — it does not"
    )

@pytest.mark.parametrize( "rel_path", TEMPLATES )
def test_template_permits_zoneinfo( rel_path ):
    """`zoneinfo` is stdlib; a blanket 'no external libraries' line reads as forbidding it."""
    body = _read( rel_path )
    assert "zoneinfo" in body, f"{rel_path} never permits zoneinfo, so the model has no way to obey the zone rule"

@pytest.mark.parametrize( "rel_path", TEMPLATES )
def test_template_forbids_a_fixed_offset( rel_path ):
    """A named zone follows daylight saving; -04:00 is wrong for half the year."""
    body = _read( rel_path ).lower()
    assert "never a fixed utc offset" in body, f"{rel_path} does not rule out a hardcoded offset"

def test_rendered_prompt_names_the_configured_zone():
    """Rendering the wired template the way the agent renders it puts the zone in front of the model."""
    template = _read( TEMPLATES[ 0 ] )
    rendered = template.format( question="what time is it", timezone="America/New_York" )
    assert "America/New_York" in rendered
    assert "what time is it" in rendered
    assert "{timezone}" not in rendered, "a placeholder survived rendering — the agent would ship a literal brace"

def test_configured_zone_is_a_real_iana_zone():
    """A typo'd zone name fails at runtime inside generated code, where it is hardest to see."""
    import cosa.config.configuration_manager as cm
    config = cm.ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    zone   = config.get( "app timezone", default="America/New_York" )
    zoneinfo.ZoneInfo( zone )                      # raises ZoneInfoNotFoundError if bogus
    assert "/" in zone, f"'{zone}' is not an IANA region/city name"
    assert not re.match( r"^[+-]\d{2}:\d{2}$", zone ), f"'{zone}' is a fixed offset, not a named zone"

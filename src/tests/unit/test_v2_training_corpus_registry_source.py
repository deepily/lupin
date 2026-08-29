#!/usr/bin/env python3
"""
Row 95924f2d step 4: the training row SET and each row's LABEL come from the v2
registry, not from the three agent-router JSONs.

The menu was already single-sourced — every training instruction interpolates
`speakable_commands()`. What was not: the JSONs still decided WHICH commands got
rows, and each row's answer was the JSON key it was built under. So a JSON could
contribute a command the menu inside those very rows never offers, and the model
would learn both halves.

Two changes are pinned here, and every pin below was watched going RED before it
was kept:

  1. `_assert_agent_router_json_commands_match_speakable` compares the JSON key
     union to the speakable set in BOTH directions. The earlier oracle was
     "subset of REGISTRY", which let a registered-but-non-speakable command
     through — `test_the_retired_subset_oracle_accepted_the_case_that_matters`
     shows exactly that, so the reason the oracle moved is itself a test.
  2. The three row loops iterate `registry_ordered_training_commands`, so the
     loop variable — the string that becomes the row's answer — is a registry
     string rather than a JSON key.
"""

import pytest

from cosa.rest.v2.registry import REGISTRY
from cosa.rest.v2.router_prompt_generator import speakable_commands
from cosa.training.xml_prompt_generator import XmlPromptGenerator

import cosa.utils.util as cu


UNREGISTERED = "agent router go to a command nobody registered"


@pytest.fixture( scope="module" )
def generator():
    """A real generator, built against the checked-in JSONs and registry."""
    return XmlPromptGenerator( path_prefix=cu.get_project_root() )


def _non_speakable_registry_command():
    """
    One command the registry knows and the router prompt deliberately omits.

    The expediters are system-triggered: registered on purpose, `speakable=False`
    on purpose. They are the exact shape the retired subset oracle waved through.
    """
    speakable = set( speakable_commands() )
    for command, spec in REGISTRY.items():
        if not spec.speakable: return command
    pytest.skip( "no non-speakable command in the registry to test the exemption path" )


# ── The standing invariant, measured rather than recalled ─────────────────────

def test_json_key_union_equals_the_speakable_command_set( generator ):
    """The corpus trains exactly the commands the served menu offers — no more, no fewer."""
    json_commands = (
        set( generator.agent_router_compound_commands )
        | set( generator.agent_router_simple_commands )
        | set( generator.agent_router_agentic_commands )
    )
    assert json_commands == set( speakable_commands() )


# ── Direction 1: a JSON cannot contribute a command the menu omits ────────────

def test_guard_refuses_a_registered_but_non_speakable_json_key( generator ):
    """
    The case the subset oracle missed. An expediter named in a JSON would build rows
    whose answer is a command the menu interpolated into those same rows never lists.
    """
    exempt = _non_speakable_registry_command()
    generator.agent_router_simple_commands[ exempt ] = "/src/ephemera/prompts/data/does-not-matter.txt"
    try:
        with pytest.raises( ValueError ) as caught:
            generator._assert_agent_router_json_commands_match_speakable()
        assert exempt in str( caught.value )
    finally:
        del generator.agent_router_simple_commands[ exempt ]


def test_the_retired_subset_oracle_accepted_the_case_that_matters( generator ):
    """
    Why the oracle moved, stated as a test rather than a comment: the retired check
    ("every JSON key is somewhere in REGISTRY") passes on the very mutation above.
    """
    exempt        = _non_speakable_registry_command()
    json_commands = set( generator.agent_router_simple_commands ) | { exempt }
    assert not ( json_commands - set( REGISTRY ) )            # the retired oracle: clean
    assert exempt not in set( speakable_commands() )          # the live oracle: refuses


def test_guard_refuses_a_key_the_registry_has_never_heard_of( generator ):
    """The case the subset oracle DID catch still fails — the tightening lost nothing."""
    generator.agent_router_simple_commands[ UNREGISTERED ] = "/src/ephemera/prompts/data/does-not-matter.txt"
    try:
        with pytest.raises( ValueError ) as caught:
            generator._assert_agent_router_json_commands_match_speakable()
        assert UNREGISTERED in str( caught.value )
    finally:
        del generator.agent_router_simple_commands[ UNREGISTERED ]


# ── Direction 2: the menu cannot offer a command with no rows behind it ───────

def test_guard_refuses_a_speakable_command_with_no_phrasings( generator ):
    """
    The starvation half, and it is the silent one: nothing else counts rows per
    command, so a menu entry with zero training examples ships unnoticed.
    """
    victim, path = next( iter( generator.agent_router_simple_commands.items() ) )
    del generator.agent_router_simple_commands[ victim ]
    try:
        with pytest.raises( ValueError ) as caught:
            generator._assert_agent_router_json_commands_match_speakable()
        assert victim in str( caught.value )
    finally:
        generator.agent_router_simple_commands[ victim ] = path


# ── The row set and the label now come from the registry ─────────────────────

def test_row_loops_iterate_the_registry_order_not_the_json_order( generator ):
    """
    The loop variable is the row's answer, so where the loop gets its strings is
    where the labels come from. Served order, registry-decided.
    """
    index   = generator.agent_router_simple_commands
    ordered = generator.registry_ordered_training_commands( index )
    assert ordered == [ c for c in speakable_commands() if c in index ]
    assert set( ordered ) == set( index )                      # nothing silently dropped today


def test_a_non_speakable_key_is_never_iterated_into_a_row( generator ):
    """
    Belt behind the guard: even if the guard were bypassed, the loop would not build
    rows for a command the menu omits.
    """
    exempt = _non_speakable_registry_command()
    index  = dict( generator.agent_router_simple_commands )
    index[ exempt ] = "/src/ephemera/prompts/data/does-not-matter.txt"
    assert exempt not in generator.registry_ordered_training_commands( index )


def test_every_iterated_label_is_a_speakable_registry_command( generator ):
    """Every label a row can carry is a string the registry declared speakable."""
    speakable = set( speakable_commands() )
    for index in ( generator.agent_router_compound_commands,
                   generator.agent_router_simple_commands,
                   generator.agent_router_agentic_commands ):
        for command in generator.registry_ordered_training_commands( index ):
            assert command in speakable
            assert REGISTRY[ command ].command == command


# ── The loops themselves, not just the helper they call ──────────────────────
# The pins above would all stay green if someone reverted the three row loops to
# `.keys()`, because they exercise the helper directly. This one runs a builder
# and reads the labels it actually emitted, so a reverted loop goes red.

def test_the_simple_builder_emits_no_row_for_a_non_speakable_command( tmp_path ):
    """
    Doctor the JSON index with a non-speakable command that has real phrasings, then
    build. The registry-driven loop skips it; a `.keys()` loop trains it.
    """
    from cosa.training.xml_coordinator import XmlCoordinator

    exempt   = _non_speakable_registry_command()
    phrasing = tmp_path / "exempt-phrasings.txt"
    phrasing.write_text( "start the expediter\nkick off the expediter\nrun the expediter now\n" )

    coordinator = XmlCoordinator( path_prefix=cu.get_project_root(), silent=True )
    index       = coordinator.prompt_generator.agent_router_simple_commands
    index[ exempt ] = str( phrasing ).replace( cu.get_project_root(), "" )

    try:
        rows = coordinator.build_simple_agent_router_training_prompts( sample_size_per_command=5 )
    finally:
        del index[ exempt ]

    assert exempt not in set( rows[ "command" ] )
    assert not any( exempt in output for output in rows[ "output" ] )
    assert set( rows[ "command" ] ) <= set( speakable_commands() )

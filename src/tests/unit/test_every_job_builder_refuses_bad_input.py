"""
Row a4014235 — every builder in the registry must refuse bad caller input, not degrade it.

Two of twelve builders were wrapped by hand and ten were not, so a bad-input error from any
of the ten answered status "waiting" for a refused submit. The registry now wraps every entry
itself; this guard reads the registry, so a builder added later is covered or named here.
"""

from cosa.rest.agentic_job_factory import JOB_BUILDERS


def test_every_registered_builder_is_wrapped_to_refuse_bad_input():
    # The population comes from the registry, never from a literal: a builder added tomorrow
    # is in this loop tomorrow. Asserting it found some keeps an emptied registry from
    # passing by iterating over nothing.
    assert len( JOB_BUILDERS ) > 0, "JOB_BUILDERS is empty: the loop below would pass over nothing"

    unwrapped = sorted( command for command, builder in JOB_BUILDERS.items()
                        if not ( hasattr( builder, "refuses_bad_input" ) and builder.refuses_bad_input is True ) )
    assert unwrapped == [ ], f"builders that would degrade bad input to a receptionist job: {unwrapped}"

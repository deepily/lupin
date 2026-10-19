#!/usr/bin/env python3
"""
CalendarCrudAgent — Domain-specific CRUD agent for calendar events.

Thin subclass of CrudForDataFramesAgent with:
    - default_schema_type = "calendar"
    - Calendar-specific routing command, replaceable through routing_command
    - Calendar-specific voice formatting hints
"""

from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent, smoke_check_schema_agent


class CalendarCrudAgent( CrudForDataFramesAgent ):
    """
    CRUD agent specialized for calendar event operations.

    Uses the same intent extraction and dispatch pipeline as the base
    CrudForDataFramesAgent, but defaults to the "calendar" schema.
    It is meant to replace CalendaringAgent in queue routing.

    Requires:
        - Same config keys as CrudForDataFramesAgent

    Ensures:
        - default_schema_type is "calendar"
        - Inherits all CRUD dispatch and fallback behavior
    """

    # Default schema for this domain agent
    DEFAULT_SCHEMA_TYPE = "calendar"


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""
    return smoke_check_schema_agent( CalendarCrudAgent, "calendar" )


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )

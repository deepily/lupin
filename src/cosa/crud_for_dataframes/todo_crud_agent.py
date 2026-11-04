#!/usr/bin/env python3
"""
TodoCrudAgent — Domain-specific CRUD agent for todo lists.

Thin subclass of CrudForDataFramesAgent with:
    - default_schema_type = "todo"
    - Todo-specific routing command, replaceable through routing_command
    - Todo-specific voice formatting hints
"""

from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent, smoke_check_schema_agent


class TodoCrudAgent( CrudForDataFramesAgent ):
    """
    CRUD agent specialized for todo list operations.

    Uses the same intent extraction and dispatch pipeline as the base
    CrudForDataFramesAgent, but defaults to the "todo" schema.
    It is meant to replace TodoListAgent in queue routing.

    Requires:
        - Same config keys as CrudForDataFramesAgent

    Ensures:
        - default_schema_type is "todo"
        - Inherits all CRUD dispatch and fallback behavior
    """

    # Default schema for this domain agent
    DEFAULT_SCHEMA_TYPE = "todo"


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""
    return smoke_check_schema_agent( TodoCrudAgent, "todo" )


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )

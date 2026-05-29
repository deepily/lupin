#!/usr/bin/env python3
"""
TodoCrudAgent — Domain-specific CRUD agent for todo lists.

Thin subclass of CrudForDataFramesAgent with:
    - default_schema_type = "todo"
    - Todo-specific routing command (Phase 3 swap target)
    - Todo-specific voice formatting hints
"""

from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent


class TodoCrudAgent( CrudForDataFramesAgent ):
    """
    CRUD agent specialized for todo list operations.

    Uses the same intent extraction and dispatch pipeline as the base
    CrudForDataFramesAgent, but defaults to "todo" schema and will
    eventually replace TodoListAgent in Phase 3 queue routing.

    Requires:
        - Same config keys as CrudForDataFramesAgent

    Ensures:
        - default_schema_type is "todo"
        - Inherits all CRUD dispatch and fallback behavior
    """

    # Default schema for this domain agent
    DEFAULT_SCHEMA_TYPE = "todo"

    def __init__( self, question="", question_gist="", last_question_asked="",
                  push_counter=-1,
                  routing_command="agent router go to crud for dataframes",
                  user_id="ricardo_felipe_ruiz_6bdc", user_email="", session_id="",
                  debug=False, verbose=False, auto_debug=False, inject_bugs=False ):
        """
        Initialize TodoCrudAgent.

        Requires:
            - Either question or last_question_asked is non-empty

        Ensures:
            - Inherits full CrudForDataFramesAgent initialization
            - self.default_schema_type is "todo"
        """
        super().__init__(
            question            = question,
            question_gist       = question_gist,
            last_question_asked = last_question_asked,
            push_counter        = push_counter,
            routing_command     = routing_command,
            user_id             = user_id,
            user_email          = user_email,
            session_id          = session_id,
            debug               = debug,
            verbose             = verbose,
            auto_debug          = auto_debug,
            inject_bugs         = inject_bugs
        )

        self.default_schema_type = self.DEFAULT_SCHEMA_TYPE


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""

    print( "Testing TodoCrudAgent module..." )

    try:
        assert TodoCrudAgent.DEFAULT_SCHEMA_TYPE == "todo"
        print( "  ✓ DEFAULT_SCHEMA_TYPE is 'todo'" )

        # Verify inheritance
        assert issubclass( TodoCrudAgent, CrudForDataFramesAgent )
        print( "  ✓ Inherits from CrudForDataFramesAgent" )

        print( "  ○ Full constructor: requires config + LLM (tested in unit tests)" )
        print( "✓ TodoCrudAgent module smoke test PASSED" )
        return True

    except Exception as e:
        print( f"✗ TodoCrudAgent module smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )

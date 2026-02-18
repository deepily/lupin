"""
Smoke tests for SolutionSnapshot.answer_is_correct tri-state field.

Tests True/False/None round-trip through SolutionSnapshot creation and
the for_current_user() copy. All tests are offline: no server, no LLM,
no embedding model. Uses pre-computed dummy embeddings to skip CUDA.

Created: 2026-02-17 (Session 221 — Smoke Test Coverage Audit)
Converted to Pattern A: 2026-02-17 (Session 222 — Consistency Cleanup)
"""

from cosa.memory.solution_snapshot import SolutionSnapshot


# Pre-computed dummy embedding to bypass embedding provider (avoids CUDA/model loading)
DUMMY_EMBEDDING = [ 0.0 ] * 768


def _make_snapshot( answer_is_correct=None, **kwargs ):
    """Create a SolutionSnapshot without triggering embedding generation."""
    defaults = {
        "question"                       : "What is 2+2?",
        "question_embedding"             : DUMMY_EMBEDDING,
        "question_normalized_embedding"  : DUMMY_EMBEDDING,
        "question_gist_embedding"        : DUMMY_EMBEDDING,
    }
    defaults.update( kwargs )
    return SolutionSnapshot( answer_is_correct=answer_is_correct, **defaults )


def quick_smoke_test():
    """
    Quick smoke test for answer_is_correct tri-state field.

    Requires:
        - cosa.memory.solution_snapshot importable

    Ensures:
        - answer_is_correct accepts None, True, False
        - for_current_user() preserves all three states
        - Original snapshot is not modified by for_current_user()
        - Returns True on success
    """
    print( "\n" + "=" * 70 )
    print( "  Answer Feedback Tri-State Smoke Test" )
    print( "=" * 70 )

    try:
        # 1. Tri-state field accepts None/True/False
        print( "\n1. Tri-state field values..." )
        snap_none  = _make_snapshot( answer_is_correct=None )
        snap_true  = _make_snapshot( answer_is_correct=True )
        snap_false = _make_snapshot( answer_is_correct=False )
        assert snap_none.answer_is_correct is None
        assert snap_true.answer_is_correct is True
        assert snap_false.answer_is_correct is False
        print( "   PASS: Tri-state field accepts None/True/False" )

        # 2. Default is None
        print( "2. Default value..." )
        snap_default = _make_snapshot()
        assert snap_default.answer_is_correct is None
        print( "   PASS: Default is None" )

        # 3. for_current_user preserves True
        print( "3. for_current_user preserves True..." )
        copy_true = snap_true.for_current_user( user_id="other", session_id="sess" )
        assert copy_true.answer_is_correct is True
        assert copy_true.user_id == "other"
        assert copy_true.session_id == "sess"
        print( "   PASS: Preserves True with correct user/session" )

        # 4. for_current_user preserves False
        print( "4. for_current_user preserves False..." )
        copy_false = snap_false.for_current_user( user_id="user2", session_id="sess2" )
        assert copy_false.answer_is_correct is False
        print( "   PASS: Preserves False" )

        # 5. for_current_user preserves None
        print( "5. for_current_user preserves None..." )
        copy_none = snap_none.for_current_user( user_id="user3", session_id="sess3" )
        assert copy_none.answer_is_correct is None
        print( "   PASS: Preserves None" )

        # 6. Original unchanged after copy
        print( "6. Original unchanged..." )
        snap_orig = _make_snapshot(
            answer_is_correct  = True,
            user_id            = "original_user",
            session_id         = "original_session",
        )
        _copy = snap_orig.for_current_user( user_id="new_user", session_id="new_session" )
        assert snap_orig.user_id == "original_user"
        assert snap_orig.session_id == "original_session"
        print( "   PASS: Original snapshot not modified" )

        print( "\n  ALL ANSWER FEEDBACK SMOKE TESTS PASSED (6/6)" )
        return True

    except Exception as e:
        print( f"\n  FAIL: {e}" )
        import traceback
        traceback.print_exc()
        return False


def test_answer_feedback():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    quick_smoke_test()

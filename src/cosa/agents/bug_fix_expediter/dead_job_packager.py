"""
Dead Job Packager for Bug Fix Expediter.

Extracts forensic context from a failed/interrupted job stored in
the CJ Flow job_history table. Returns a structured DeadJobContext
for the diagnosis phase.
"""

from typing import Optional

from cosa.agents.bug_fix_expediter.state import DeadJobContext


def package_dead_job( dead_job_id: str, debug: bool = False ) -> Optional[ DeadJobContext ]:
    """
    Extract DeadJobContext from a persisted dead job.

    Requires:
        - dead_job_id is a non-empty string (id_hash from job_history)

    Ensures:
        - Returns DeadJobContext if job found and status is failed/interrupted
        - Returns None if job not found
        - Raises ValueError if job exists but is not dead (status not failed/interrupted)

    Args:
        dead_job_id: The id_hash of the dead job
        debug: Enable debug output

    Returns:
        DeadJobContext or None
    """
    from cosa.rest.job_persistence import get_job_by_id_hash

    if not dead_job_id:
        raise ValueError( "dead_job_id must be a non-empty string" )

    row = get_job_by_id_hash( dead_job_id )

    if row is None:
        if debug: print( f"[dead_job_packager] No job found for id_hash: {dead_job_id}" )
        return None

    status = row.get( "status", "" )
    if status not in ( "failed", "interrupted" ):
        raise ValueError(
            f"Job {dead_job_id} has status '{status}' — "
            f"only 'failed' or 'interrupted' jobs can be expedited"
        )

    # Extract stack_trace from metadata_json if available
    metadata    = row.get( "metadata_json" ) or {}
    stack_trace = metadata.get( "stack_trace" )

    context = DeadJobContext(
        id_hash          = row[ "id_hash" ],
        job_type         = row[ "job_type" ],
        user_id          = row[ "user_id" ],
        user_email       = row[ "user_email" ],
        session_id       = row[ "session_id" ],
        status           = status,
        question_text    = row[ "question_text" ],
        error            = row.get( "error" ),
        stack_trace      = stack_trace,
        routing_command  = row[ "routing_command" ],
        duration_seconds = row.get( "duration_seconds" ),
        metadata_json    = metadata,
        created_at       = row.get( "created_at" ),
        started_at       = row.get( "started_at" ),
        completed_at     = row.get( "completed_at" ),
    )

    if debug:
        print( f"[dead_job_packager] Packaged dead job: {context.id_hash} "
               f"(type={context.job_type}, status={context.status})" )

    return context


def quick_smoke_test():
    """Quick smoke test for dead_job_packager."""
    import cosa.utils.util as cu

    cu.print_banner( "Dead Job Packager Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing import..." )
        from cosa.agents.bug_fix_expediter.dead_job_packager import package_dead_job
        print( "✓ Module imported successfully" )

        # Test 2: Empty ID raises ValueError
        print( "Testing empty ID validation..." )
        try:
            package_dead_job( "" )
            print( "✗ Should have raised ValueError!" )
        except ValueError as e:
            assert "non-empty" in str( e )
            print( "✓ Correctly raises ValueError for empty ID" )

        # Test 3: Non-existent job returns None
        print( "Testing non-existent job..." )
        try:
            result = package_dead_job( "nonexistent-id-12345", debug=True )
            assert result is None
            print( "✓ Returns None for non-existent job" )
        except Exception as e:
            print( f"⚠ Skipped (requires Postgres): {e}" )

        # Test 4: DeadJobContext model validation
        print( "Testing DeadJobContext direct construction..." )
        ctx = DeadJobContext(
            id_hash       = "dr-test1234::user1",
            job_type      = "deep_research",
            user_id       = "user1",
            user_email    = "test@test.com",
            session_id    = "session1",
            status        = "failed",
            question_text = "test query",
            error         = "Something broke",
        )
        assert ctx.id_hash == "dr-test1234::user1"
        assert ctx.status == "failed"
        print( "✓ DeadJobContext validates correctly" )

        print( "\n✓ Dead Job Packager smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()

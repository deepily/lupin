"""
State models for the TestFixExpediter pipeline.

Session 1cfcdf73 (2026-04-10): Parallel to BFE's state.py but shaped for
test-failure input (many failures → K clusters) rather than dead-job
input (one crash). Reuses BFE's `DiagnosisResult`, `ProposedFix`, and
`FixResult` types where possible; extends with TFE-specific fields.

See: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/06-phase3-fix-delegation-plan.md
"""

from enum import Enum
from typing import Optional, TypedDict

from pydantic import BaseModel, Field

# Reuse BFE's shared types — DiagnosisResult, FixResult are agent-agnostic.
# ProposedFix gets extended below with an optional cluster_id.
from cosa.agents.bug_fix_expediter.state import (
    DiagnosisResult,
    FixResult,
)


class TFEPhase( Enum ):
    """Phase machine for the TestFixExpediter pipeline."""
    # Active phases
    LOADING              = "loading"              # Parsing remediation snapshot
    CLUSTERING           = "clustering"           # Phase 0: group N failures into K clusters
    DIAGNOSING           = "diagnosing"           # Phase 1: per-cluster diagnose
    PROPOSING            = "proposing"            # Phase 2: propose fixes per cluster
    FIXING               = "fixing"               # Phase 3: delegate to shared FixExecutor
    COMMITTING           = "committing"           # Phase 5: shared GitStrategist
    RESUBMITTING         = "resubmitting"         # Phase 6: queue validation TestSuiteJob

    # Waiting phases
    WAITING_CONFIRMATION = "waiting_confirmation"

    # Terminal phases
    COMPLETED            = "completed"
    FAILED               = "failed"
    PARTIAL              = "partial"              # Some clusters fixed, others failed
    SKIPPED              = "skipped"


class TestRemediationContext( BaseModel ):
    """
    Parsed remediation snapshot from a failed TestSuiteJob.

    Built by `snapshot_loader.load_from_artifacts()` from the
    `remediation_snapshot` artifact on a completed TestSuiteJob whose
    `summary.all_passed == False`.

    Requires:
        - snapshot has schema_version == "1.0"
        - summary.all_passed == False
        - failures is non-empty
        - source_test_suite_job_id is non-empty

    Ensures:
        - All fields populated from the snapshot + original job metadata
        - Duck-typed user_email attribute for PlanWriter compatibility
    """
    source_test_suite_job_id : str
    snapshot_path            : str              # relative to io/
    snapshot                 : dict             # raw parsed JSON
    suites_run               : list[ str ]
    summary                  : dict             # total_passed/failed/skipped/errors/all_passed
    failures                 : list[ dict ]     # flat list of failure records
    original_test_types      : list[ str ]      # for Phase 6 rerun targeting
    original_pytest_args     : list[ str ]      = Field( default_factory=list )
    user_id                  : str
    user_email               : str              # also used as PlanWriter partition key
    session_id               : str


class FailureCluster( BaseModel ):
    """
    A grouped subset of test failures sharing a common root cause.

    Produced by `cluster.py::heuristic_seed()` and optionally refined by
    `cluster.py::llm_refine()` in Phase 0.

    Requires:
        - cluster_id is a non-empty string (e.g., "C1", "C2")
        - failure_indices is a non-empty list of indices into the
          TestRemediationContext.failures list
        - confidence is between 0.0 and 1.0

    Ensures:
        - failure_indices are unique (no duplicates within a cluster)
        - shared_error_signature is a human-readable summary
    """
    cluster_id              : str
    failure_indices         : list[ int ]
    shared_error_signature  : str
    hypothesis              : str                = ""
    affected_files_guess    : list[ str ]        = Field( default_factory=list )
    confidence              : float              = Field( default=0.5, ge=0.0, le=1.0 )


class TestDiagnosisResult( DiagnosisResult ):
    """
    Per-cluster diagnosis result. Extends BFE's DiagnosisResult with
    test-specific fields.

    Requires:
        - All fields of DiagnosisResult (root_cause, error_category, etc.)
        - cluster_id references a valid FailureCluster

    Ensures:
        - test_symptoms captures specific assertion messages / fixture errors
          observed in the cluster
    """
    cluster_id     : str
    test_symptoms  : list[ str ] = Field( default_factory=list )


class TFEProposedFix( BaseModel ):
    """
    A proposed fix for one failure cluster.

    Parallel to BFE's ProposedFix but with a required cluster_id. We don't
    inherit from ProposedFix because Pydantic validators on the BFE class
    would make cluster_id awkwardly optional. Instead we define the fields
    afresh; the shared FixExecutor prompt builders only read attributes,
    so both BFE's ProposedFix and this TFEProposedFix satisfy the contract.
    """
    cluster_id       : str
    title            : str
    description      : str
    fix_type         : str            # config_change | code_patch | test_patch | retry | manual
    confidence       : float          = Field( ge=0.0, le=1.0 )
    risk_level       : str            = "low"
    estimated_effort : str            = "minimal"
    changes          : list[ dict ]   = Field( default_factory=list )


class TFEState( TypedDict ):
    """Complete state for a TestFixExpediter run."""
    # Input
    source_test_suite_job_id : str
    remediation_snapshot_path: str

    # Loading phase
    remediation_context      : Optional[ TestRemediationContext ]

    # Phase 0: Cluster
    clusters                 : list[ FailureCluster ]

    # Phase 1: Diagnose (keyed by cluster_id)
    diagnoses                : dict

    # Phase 2: Propose
    proposed_fixes           : list[ TFEProposedFix ]
    selected_fixes           : list[ TFEProposedFix ]

    # Phase 3: Fix
    fix_results              : list[ FixResult ]
    files_changed_by_cluster : dict

    # Phase 5: Git
    branch_name              : Optional[ str ]
    commit_hashes            : list[ str ]
    pr_url                   : Optional[ str ]

    # Phase 6: Validate
    validation_run_job_id    : Optional[ str ]

    # Meta
    phase                    : str
    error                    : Optional[ str ]


def create_initial_state(
    source_test_suite_job_id: str,
    remediation_snapshot_path: str,
) -> TFEState:
    """
    Create initial TFEState for a new TestFixExpediter run.

    Requires:
        - source_test_suite_job_id is non-empty
        - remediation_snapshot_path is non-empty (relative to io/)

    Ensures:
        - Returns TFEState with phase=LOADING and all fields initialized
    """
    return TFEState(
        source_test_suite_job_id = source_test_suite_job_id,
        remediation_snapshot_path= remediation_snapshot_path,
        remediation_context      = None,
        clusters                 = [],
        diagnoses                = {},
        proposed_fixes           = [],
        selected_fixes           = [],
        fix_results              = [],
        files_changed_by_cluster = {},
        branch_name              = None,
        commit_hashes            = [],
        pr_url                   = None,
        validation_run_job_id    = None,
        phase                    = TFEPhase.LOADING.value,
        error                    = None,
    )


# ---------------------------------------------------------------------------
# Checkpoint-resume infrastructure (Session 9056c113)
# ---------------------------------------------------------------------------

TFE_PHASE_ORDINALS = {
    TFEPhase.LOADING      : 0,
    TFEPhase.CLUSTERING   : 1,
    TFEPhase.DIAGNOSING   : 2,
    TFEPhase.PROPOSING    : 3,
    TFEPhase.FIXING       : 4,
    TFEPhase.COMMITTING   : 5,
    TFEPhase.RESUBMITTING : 6,
}


class CheckpointData( TypedDict ):
    """
    Serialized mid-execution state for resume.

    Stored in metadata_json["checkpoint"] when a TFE job transitions to STALLED.
    Retrieved by the resume factory to reconstruct the orchestrator at the stall
    phase and continue execution from the next phase.

    Requires:
        - phase_ordinal >= 0 and corresponds to a TFEPhase active phase
        - state_snapshot is JSON-serializable (Pydantic models → dicts)

    Ensures:
        - Sufficient data to reconstruct orchestrator state via load_checkpoint()
    """
    phase_ordinal  : int     # Ordinal of last completed phase (0=loading, 1=clustering, ...)
    phase_name     : str     # Human-readable (e.g., "proposing")
    stall_reason   : str     # "voice_gate_timeout" (no answer) | "user_pause" (deferred; resumable) | "user_cancel" (rejected; terminal) | "rate_limit" (infrastructure)
    stalled_at     : str     # ISO timestamp
    state_snapshot : dict    # Serialized TFEState (JSON-safe)
    artifacts      : dict    # Paths to durable artifacts created so far
    resume_count   : int     # How many times this job has been resumed (starts at 0)


class VoiceGateTimeoutError( Exception ):
    """
    Voice gate timed out without user response.

    Raised by cosa_interface when the blocking MCP call returns a timeout
    response. Caught by the orchestrator to trigger checkpoint-and-stall.

    Requires:
        - phase is a valid TFEPhase value string

    Ensures:
        - Carries the phase where timeout occurred
        - Carries `delivered`: True when the ask REACHED a human and no answer
          came back (a real silence-timeout); False when it is unknown whether
          the ask was delivered (default, and the conservative choice for a
          mechanism/transport failure). Row 38a0b373: a log reader must be able
          to tell a delivered-but-unanswered gate from one that never reached
          anyone — both fail open to the default, but for opposite reasons.
    """
    def __init__( self, phase: str, message: str = "", delivered: bool = False ):
        self.phase     = phase
        self.delivered = delivered
        super().__init__( message or f"Voice gate timeout at {phase}" )


class VoiceGateUnreachableError( Exception ):
    """
    Voice gate could not reach the human at all — the call itself failed.

    Distinct from VoiceGateTimeoutError on purpose. A timeout means the
    question was asked and no answer came back; this means the asking
    mechanism broke (transport down, MCP unavailable, serialization error).
    Both mean "no human answered", and both must checkpoint-and-stall — but
    collapsing them into one type would make the record unable to say which
    happened, which is the same defect this exception exists to remove.

    Before this existed, the orchestrator caught the generic exception and
    AUTO-APPROVED: a gate that could not reach a human answered for them,
    in a value indistinguishable from a real approval.

    Requires:
        - phase is a valid BFEPhase/TFEPhase value string
        - cause is the original exception that broke the gate

    Ensures:
        - Carries the phase where the gate failed and the underlying cause
        - Caught by the orchestrator to trigger checkpoint-and-stall
    """
    def __init__( self, phase: str, cause: Exception, message: str = "" ):
        self.phase = phase
        self.cause = cause
        super().__init__( message or f"Voice gate unreachable at {phase}: {cause}" )


class StalledException( Exception ):
    """
    Orchestrator requests a clean stall with checkpoint.

    Raised when a voice gate times out and the orchestrator has saved its state.
    Caught by job._execute() to transition the job to STALLED without treating
    it as a failure.

    Requires:
        - checkpoint is a JSON-serializable dict matching CheckpointData schema
        - phase is a valid TFEPhase value string

    Ensures:
        - job._execute() catches this and transitions to STALLED
        - NOT treated as a failure — this is a clean yield point
    """
    def __init__( self, checkpoint: dict, phase: str, message: str = "" ):
        self.checkpoint = checkpoint
        self.phase      = phase
        super().__init__( message or f"Stalled at {phase}" )


def quick_smoke_test():
    """Quick smoke test for TFE state models."""
    import cosa.utils.util as cu

    cu.print_banner( "TFE State Models Smoke Test", prepend_nl=True )

    try:
        # 1: TFEPhase enum
        assert TFEPhase.LOADING.value == "loading"
        assert TFEPhase.CLUSTERING.value == "clustering"
        assert TFEPhase.COMPLETED.value == "completed"
        assert TFEPhase.PARTIAL.value == "partial"
        assert len( TFEPhase ) == 12
        print( f"✓ TFEPhase enum correct ({len( TFEPhase )} values)" )

        # 2: TestRemediationContext validates
        ctx = TestRemediationContext(
            source_test_suite_job_id = "ts-abc12345",
            snapshot_path            = "test-suite/2026.04.10-at-14:53-e2e-remediation.json",
            snapshot                 = { "schema_version": "1.0" },
            suites_run               = [ "e2e" ],
            summary                  = { "total_failed": 4, "all_passed": False },
            failures                 = [ { "classname": "test.Foo", "name": "test_bar" } ],
            original_test_types      = [ "e2e" ],
            original_pytest_args     = [],
            user_id                  = "u1",
            user_email               = "t@t.com",
            session_id               = "s1",
        )
        assert ctx.user_email == "t@t.com"
        assert len( ctx.failures ) == 1
        print( "✓ TestRemediationContext validates" )

        # 3: FailureCluster
        cluster = FailureCluster(
            cluster_id              = "C1",
            failure_indices         = [ 0, 1, 2 ],
            shared_error_signature  = "AssertionError in auth module",
            hypothesis              = "Token refresh race condition",
            affected_files_guess    = [ "src/cosa/auth/tokens.py" ],
            confidence              = 0.75,
        )
        assert cluster.cluster_id == "C1"
        assert len( cluster.failure_indices ) == 3
        print( "✓ FailureCluster validates" )

        # 4: TestDiagnosisResult inherits from DiagnosisResult
        diag = TestDiagnosisResult(
            cluster_id          = "C1",
            root_cause          = "Race condition in token refresh",
            error_category      = "code_bug",
            confidence          = 0.8,
            evidence            = [ "tokens.py line 42 lacks mutex" ],
            affected_components = [ "src/cosa/auth/tokens.py" ],
            test_symptoms       = [ "AssertionError: Expected 200 got 401" ],
        )
        assert diag.cluster_id == "C1"
        assert diag.error_category == "code_bug"
        assert len( diag.test_symptoms ) == 1
        print( "✓ TestDiagnosisResult validates (extends DiagnosisResult)" )

        # 5: TFEProposedFix
        fix = TFEProposedFix(
            cluster_id  = "C1",
            title       = "Add mutex to token refresh",
            description = "Wrap refresh in a lock to prevent concurrent calls",
            fix_type    = "code_patch",
            confidence  = 0.85,
        )
        assert fix.cluster_id == "C1"
        assert fix.risk_level == "low"
        print( "✓ TFEProposedFix validates" )

        # 6: create_initial_state
        state = create_initial_state( "ts-abc12345", "test-suite/remediation.json" )
        assert state[ "source_test_suite_job_id" ] == "ts-abc12345"
        assert state[ "phase" ] == "loading"
        assert state[ "clusters" ] == []
        assert state[ "remediation_context" ] is None
        print( "✓ create_initial_state works" )

        print( "\n✓ TFE State Models smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()

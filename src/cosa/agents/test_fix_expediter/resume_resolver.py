"""
TFE Resume Resolver — dispatch free-form resume input to a target job ID.

Session 9056c113 (continued, 2026-04-12): Phase D4b-D4d deferred work.
Accepts any of: TFE job ID, plan doc path, checkpoint JSON path, or natural
language description. Returns a ResumeTarget with the resolved job ID and
metadata for UI/voice disambiguation.

Phase 1 scope: Exact-match paths (job ID + plan doc). Fuzzy natural-language
matching via LLM is Phase 2 (needs new INI keys + prompt template + response model).

See: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/15-file-path-resume-and-voice-parsing.md
"""

import os
import re
from typing import Optional

from pydantic import BaseModel, Field


# Regex to extract source TestSuiteJob ID from a TFE plan filename.
# Filename format: YYYY.MM.DD-{N}-clusters-from-{source_ts_id_no_dashes}-c{N}-plan.md
# The source_ts_id is packed without dashes in the filename (e.g., ts86c172f70cf47...)
# but stored in job_history with dashes (ts-86c172f7-...).
_PLAN_FILENAME_PATTERN = re.compile(
    r"^\d{4}\.\d{2}\.\d{2}-\d+-clusters-from-(?P<source_id>[a-zA-Z0-9]+)-c\d+-plan\.md$"
)


class ResumeTarget( BaseModel ):
    """
    Result of dispatching a resume_from string.

    Requires:
        - source_type is one of: "job_id", "plan_path", "checkpoint", "fuzzy", "not_found"
        - confidence is between 0.0 and 1.0

    Ensures:
        - job_id is populated for single-match cases
        - candidates is populated for ambiguous cases
        - diagnostic is always populated with a human-readable explanation
    """
    job_id       : Optional[ str ]    = None
    source_type  : str                = "not_found"
    matched_path : Optional[ str ]    = None
    confidence   : float              = Field( default=1.0, ge=0.0, le=1.0 )
    candidates   : list[ dict ]       = Field( default_factory=list )
    diagnostic   : str                = ""


def resolve_resume_target( resume_from: str, user_email: str ) -> ResumeTarget:
    """
    Dispatch a resume_from string to the right resolver.

    Requires:
        - resume_from is a non-empty string (job ID, file path, or description)
        - user_email is the requesting user's email

    Ensures:
        - Returns ResumeTarget with source_type set appropriately
        - Never raises — reports errors in diagnostic field

    Args:
        resume_from: Free-form input — job ID, plan path, checkpoint path, or description
        user_email: Requesting user's email (for scoping lookups)

    Returns:
        ResumeTarget with the resolved job_id, or source_type="not_found" if unresolvable
    """
    if not resume_from or not resume_from.strip():
        return ResumeTarget( source_type="not_found", diagnostic="Empty resume_from input" )

    s = resume_from.strip()

    # Type 1: TFE job ID (tfe-* with ::user_id suffix, or bare tfe-*)
    if s.startswith( "tfe-" ):
        return _resolve_by_job_id( s, user_email )

    # Type 2: Plan doc path — ends with -plan.md or contains /plans/
    if s.endswith( "-plan.md" ) or "/plans/" in s:
        return _resolve_by_plan_path( s, user_email )

    # Type 3: Checkpoint JSON file (future-proof, low-priority)
    if s.endswith( ".json" ) and "checkpoint" in s.lower():
        return ResumeTarget(
            source_type = "not_found",
            diagnostic  = "Checkpoint JSON resume not yet implemented (Phase 2 follow-up)",
        )

    # Type 4: Natural language fuzzy match via LLM (Phase 2)
    return _resolve_by_fuzzy_match( s, user_email )


# ---------------------------------------------------------------------------
# Type 1: Job ID resolution
# ---------------------------------------------------------------------------

def _resolve_by_job_id( job_id_input: str, user_email: str ) -> ResumeTarget:
    """
    Resolve a tfe-* job ID to a stalled job.

    Accepts both fully-qualified (tfe-abc::user1) and bare (tfe-abc) forms.
    The bare form is scoped to the requesting user_email.

    Requires:
        - job_id_input starts with "tfe-"
        - user_email is a valid email (for scoping when job_id is bare)

    Ensures:
        - Returns ResumeTarget with job_id set if found AND stalled
        - Returns "not_found" with diagnostic if missing, not stalled, or not owned
    """
    from cosa.rest.job_persistence import get_checkpoint_for_job

    # Determine the canonical id_hash
    if "::" in job_id_input:
        # Fully-qualified
        candidate_id = job_id_input
    else:
        # Bare — try user-scoped first
        candidate_id = f"{job_id_input}::{user_email}"

    checkpoint = get_checkpoint_for_job( candidate_id )
    if checkpoint is None:
        return ResumeTarget(
            source_type = "not_found",
            diagnostic  = (
                f"Job {candidate_id} not found, not stalled, or has no checkpoint. "
                f"Only stalled jobs with saved checkpoints can be resumed."
            ),
        )

    return ResumeTarget(
        job_id      = candidate_id,
        source_type = "job_id",
        confidence  = 1.0,
        diagnostic  = f"Resolved via exact job ID match",
    )


# ---------------------------------------------------------------------------
# Type 2: Plan doc path resolution
# ---------------------------------------------------------------------------

def _resolve_by_plan_path( plan_path_input: str, user_email: str ) -> ResumeTarget:
    """
    Resolve a TFE plan doc path to its associated stalled job.

    Parses the source TestSuiteJob ID from the filename pattern:
        YYYY.MM.DD-N-clusters-from-{source_id_no_dashes}-cN-plan.md

    Then queries job_history for any TFE job whose metadata points to this plan.

    Requires:
        - plan_path_input is a non-empty string
        - File must exist on disk (relative or absolute path)

    Ensures:
        - Returns ResumeTarget with job_id if plan maps to a stalled TFE job
        - Returns "not_found" with diagnostic if file missing, filename unparseable,
          or no matching stalled job found
    """
    import cosa.utils.util as cu

    project_root = cu.get_project_root()

    # Normalize to absolute path
    if os.path.isabs( plan_path_input ):
        abs_path = plan_path_input
    else:
        abs_path = os.path.join( project_root, plan_path_input )

    if not os.path.exists( abs_path ):
        return ResumeTarget(
            source_type  = "not_found",
            matched_path = plan_path_input,
            diagnostic   = f"Plan doc not found at {plan_path_input}",
        )

    # Parse the filename to extract source TSJ ID
    filename = os.path.basename( abs_path )
    match = _PLAN_FILENAME_PATTERN.match( filename )
    if not match:
        return ResumeTarget(
            source_type  = "not_found",
            matched_path = plan_path_input,
            diagnostic   = (
                f"Plan filename '{filename}' does not match expected pattern "
                f"YYYY.MM.DD-N-clusters-from-{{source_id}}-cN-plan.md"
            ),
        )

    source_id_packed = match.group( "source_id" )

    # Find a stalled TFE job whose metadata_json.artifacts.plan_path matches this file
    job_id = _find_stalled_tfe_by_plan_path( plan_path_input, user_email )
    if job_id:
        return ResumeTarget(
            job_id       = job_id,
            source_type  = "plan_path",
            matched_path = plan_path_input,
            confidence   = 1.0,
            diagnostic   = f"Resolved via plan path → stalled job {job_id}",
        )

    return ResumeTarget(
        source_type  = "not_found",
        matched_path = plan_path_input,
        diagnostic   = (
            f"Plan exists but no stalled TFE job references it. "
            f"The job may have completed, failed, or never been persisted. "
            f"Source ID in filename: {source_id_packed}"
        ),
    )


def _find_stalled_tfe_by_plan_path( plan_path: str, user_email: str ) -> Optional[ str ]:
    """
    Query job_history for a stalled TFE job whose artifacts.plan_path matches.

    Requires:
        - plan_path is a non-empty string (relative or absolute)
        - user_email is used to scope the query (RLS-style safety)

    Ensures:
        - Returns the first matching stalled TFE id_hash, or None
        - Never raises — returns None on any error
    """
    try:
        from sqlalchemy import select
        from cosa.rest.db.database import get_db
        from cosa.rest.postgres_models import JobHistory
        from cosa.rest.job_state import JobState

        # Normalize: we store relative paths starting with "io/..." in metadata,
        # but users may paste absolute paths. Check against the basename as a
        # fallback since plan filenames are unique per cluster.
        basename = os.path.basename( plan_path )

        with get_db() as session:
            rows = session.execute(
                select( JobHistory )
                .where( JobHistory.job_type == "test_fix_expediter" )
                .where( JobHistory.status == JobState.STALLED.value )
                .where( JobHistory.user_email == user_email )
            ).scalars().all()

            for row in rows:
                metadata = row.metadata_json or {}
                artifacts = metadata.get( "artifacts" ) or {}
                stored_path = artifacts.get( "plan_path" )
                if not stored_path:
                    continue

                # Match exact path OR basename (handles relative vs absolute)
                if stored_path == plan_path or os.path.basename( stored_path ) == basename:
                    return row.id_hash

        return None

    except Exception as e:
        print( f"[resume_resolver] _find_stalled_tfe_by_plan_path error: {e}" )
        return None


# ---------------------------------------------------------------------------
# Type 4: Fuzzy natural-language resolution
# ---------------------------------------------------------------------------

def _resolve_by_fuzzy_match( description: str, user_email: str ) -> ResumeTarget:
    """
    Resolve a natural-language description to a stalled TFE job via LLM fuzzy match.

    Requires:
        - description is a non-empty natural-language string
        - user_email scopes the candidate pool

    Ensures:
        - Returns ResumeTarget with job_id + source_type="fuzzy" if high-confidence match
        - Returns ResumeTarget with candidates populated if multiple low-confidence matches
        - Returns "not_found" if no candidates or LLM failure
    """
    candidates = list_resume_candidates( user_email )
    if not candidates:
        return ResumeTarget(
            source_type = "not_found",
            diagnostic  = "No stalled or recent TFE jobs found for your user account.",
        )

    ranked = fuzzy_match_candidates( description, candidates )
    if not ranked:
        return ResumeTarget(
            source_type = "not_found",
            candidates  = candidates,  # Return full list so UI can show all
            diagnostic  = (
                f"Could not fuzzy-match '{description[:60]}' to any stalled/recent TFE job. "
                f"Listing {len( candidates )} candidates for manual selection."
            ),
        )

    # Auto-select if top match >= 0.9 AND is stalled (resumable)
    top = ranked[ 0 ]
    if top[ "confidence" ] >= 0.9 and top.get( "status" ) == "stalled":
        return ResumeTarget(
            job_id      = top[ "job_id" ],
            source_type = "fuzzy",
            confidence  = top[ "confidence" ],
            diagnostic  = f"Fuzzy match (confidence {top['confidence']:.0%}): {top.get('reason', '')}",
        )

    # Ambiguous — return candidates for UI disambiguation
    return ResumeTarget(
        source_type = "fuzzy",
        candidates  = ranked,
        confidence  = top[ "confidence" ] if ranked else 0.0,
        diagnostic  = (
            f"Found {len( ranked )} possible match(es) for '{description[:60]}'. "
            f"Top confidence: {top['confidence']:.0%}. User disambiguation required."
        ),
    )


# ---------------------------------------------------------------------------
# Phase 2: Candidate listing + LLM fuzzy match
# ---------------------------------------------------------------------------

def list_resume_candidates( user_email: str, max_count: int = 20 ) -> list[ dict ]:
    """
    Build a list of candidate stalled/recent TFE jobs for fuzzy matching.

    Combines two sources:
    1. Stalled TFE jobs (highest priority — resumable)
    2. Recent completed/failed TFE jobs (context for disambiguation)

    Each candidate is a flat dict suitable for JSON serialization into
    an LLM prompt or a UI disambiguation modal.

    Requires:
        - user_email is a non-empty string
        - max_count >= 1

    Ensures:
        - Returns list of dicts with keys: job_id, status, stalled_at, plan_path,
          summary, source_ts
        - Never raises — returns [] on any error
    """
    try:
        from sqlalchemy import select, desc
        from cosa.rest.db.database import get_db
        from cosa.rest.postgres_models import JobHistory
        from cosa.rest.job_state import JobState

        candidates = []

        with get_db() as session:
            # Stalled TFE jobs first (most valuable)
            stalled_rows = session.execute(
                select( JobHistory )
                .where( JobHistory.job_type == "test_fix_expediter" )
                .where( JobHistory.status == JobState.STALLED.value )
                .where( JobHistory.user_email == user_email )
                .order_by( desc( JobHistory.updated_at ) )
                .limit( max_count )
            ).scalars().all()

            for row in stalled_rows:
                candidates.append( _row_to_candidate_dict( row ) )

            # If room, add recent non-stalled TFE jobs (for context)
            remaining = max_count - len( candidates )
            if remaining > 0:
                recent_rows = session.execute(
                    select( JobHistory )
                    .where( JobHistory.job_type == "test_fix_expediter" )
                    .where( JobHistory.status != JobState.STALLED.value )
                    .where( JobHistory.user_email == user_email )
                    .order_by( desc( JobHistory.completed_at ) )
                    .limit( remaining )
                ).scalars().all()

                for row in recent_rows:
                    candidates.append( _row_to_candidate_dict( row ) )

        return candidates

    except Exception as e:
        print( f"[resume_resolver] list_resume_candidates error: {e}" )
        return []


def _row_to_candidate_dict( row ) -> dict:
    """Normalize a JobHistory row to a flat candidate dict."""
    metadata = row.metadata_json or {}
    artifacts = metadata.get( "artifacts" ) or {}
    checkpoint = artifacts.get( "checkpoint" ) or metadata.get( "checkpoint" ) or {}

    # Extract summary from checkpoint state_snapshot if present
    summary_parts = []
    snapshot = checkpoint.get( "state_snapshot" ) or {}
    clusters = snapshot.get( "clusters" ) or []
    if clusters:
        summary_parts.append( f"{len( clusters )} cluster{'s' if len( clusters ) != 1 else ''}" )
    proposed = snapshot.get( "proposed_fixes" ) or []
    if proposed:
        summary_parts.append( f"{len( proposed )} proposed" )

    # Fall back to question_text if nothing else
    if not summary_parts and row.question_text:
        summary_parts.append( row.question_text[:80] )

    return {
        "job_id"     : row.id_hash,
        "status"     : row.status,
        "stalled_at" : checkpoint.get( "stalled_at" ) or (
            row.updated_at.isoformat() if row.updated_at else None
        ),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "plan_path"  : artifacts.get( "plan_path" ),
        "summary"    : ", ".join( summary_parts ) or "(no summary available)",
        "source_ts"  : metadata.get( "original_args", {} ).get( "source_test_suite_job_id" ),
    }


def fuzzy_match_candidates(
    user_description: str,
    candidates: list[ dict ],
    llm_client=None,
    config_mgr=None,
    debug: bool = False,
) -> list[ dict ]:
    """
    Rank candidates by similarity to the user's natural-language description.

    Uses an LLM via the configured `llm spec key for tfe resume matching`
    to score each candidate. Returns candidates ordered by confidence with
    a `confidence` and `reason` field added to each.

    Requires:
        - user_description is a non-empty string
        - candidates is a list of dicts from list_resume_candidates()

    Ensures:
        - Returns at most len(candidates) ranked dicts
        - Each dict gets confidence (0.0-1.0) and reason (str) fields added
        - Never raises — returns [] on LLM or parsing errors
    """
    if not candidates:
        return []

    try:
        import cosa.utils.util as cu
        from cosa.agents.io_models.xml_models import TFEResumeMatchResponse
        from cosa.agents.prompt_template_processor import PromptTemplateProcessor
        from cosa.rest.llm_factory import LlmFactory
        from cosa.config.configuration_manager import ConfigurationManager

        if config_mgr is None:
            config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

        # Load + process template
        template_path = config_mgr.get( "prompt template for tfe resume matching" )
        project_root = cu.get_project_root()
        template = cu.get_file_as_string( project_root + template_path )
        processor = PromptTemplateProcessor( debug=debug )
        template = processor.process_template( template, "tfe resume matching" )

        # Build candidate list for the prompt
        candidate_lines = []
        for i, c in enumerate( candidates ):
            line = (
                f"[{i}] job_id={c['job_id']} status={c['status']} "
                f"stalled_at={c.get('stalled_at')} "
                f"summary={c['summary']}"
            )
            candidate_lines.append( line )
        candidate_list_str = "\n".join( candidate_lines )

        prompt = template.format(
            description    = user_description,
            candidate_list = candidate_list_str,
        )

        # Call LLM
        if llm_client is None:
            llm_factory = LlmFactory( debug=debug )
            llm_client = llm_factory.get_client(
                config_mgr.get( "llm spec key for tfe resume matching" ),
                debug=debug,
            )
        response = llm_client.run( prompt )

        # Parse XML response
        parsed = TFEResumeMatchResponse.from_xml( response )
        raw_matches = parsed.get_matches_list()

        # raw_matches is a list of job_ids (comma-separated in XML).
        # Map back to full candidate dicts in ranked order.
        id_to_candidate = { c[ "job_id" ]: c for c in candidates }
        ranked = []
        for i, jid in enumerate( raw_matches ):
            jid = jid.strip()
            if jid in id_to_candidate:
                c = dict( id_to_candidate[ jid ] )  # copy
                # Linear confidence decay — first match = 0.95, each subsequent drops 0.1
                c[ "confidence" ] = max( 0.5, 0.95 - i * 0.1 )
                c[ "reason" ] = f"LLM ranked match #{i + 1}"
                ranked.append( c )

        return ranked

    except Exception as e:
        if debug: print( f"[resume_resolver] fuzzy_match_candidates error: {e}" )
        import traceback
        if debug: traceback.print_exc()
        return []


def quick_smoke_test():
    """Quick smoke test for resume resolver."""
    import cosa.utils.util as cu
    cu.print_banner( "TFE Resume Resolver Smoke Test", prepend_nl=True )

    try:
        # 1: Empty input
        result = resolve_resume_target( "", "user@test.com" )
        assert result.source_type == "not_found"
        print( "✓ Empty input → not_found" )

        # 2: Whitespace input
        result = resolve_resume_target( "   ", "user@test.com" )
        assert result.source_type == "not_found"
        print( "✓ Whitespace input → not_found" )

        # 3: Filename pattern parser
        filename = "2026.04.12-1-clusters-from-ts86c172f70cf47e2dd5a14cd4addf79810fd32b15-c1-plan.md"
        match = _PLAN_FILENAME_PATTERN.match( filename )
        assert match is not None
        assert match.group( "source_id" ) == "ts86c172f70cf47e2dd5a14cd4addf79810fd32b15"
        print( "✓ Plan filename pattern parses correctly" )

        # 4: Filename that doesn't match
        bad_filename = "some-random-file.md"
        match = _PLAN_FILENAME_PATTERN.match( bad_filename )
        assert match is None
        print( "✓ Non-matching filename rejected" )

        # 5: Unknown input type routes to fuzzy match (returns not_found if no candidates)
        # Skip the DB-dependent path in the smoke test — covered in unit tests

        # 6: Checkpoint JSON not implemented yet
        result = resolve_resume_target( "io/checkpoint.json", "user@test.com" )
        assert result.source_type == "not_found"
        assert "not yet implemented" in result.diagnostic
        print( "✓ Checkpoint JSON → not_found with deferred message" )

        print( "\n✓ Resume Resolver smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()

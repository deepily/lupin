"""
Phase 1 (diagnose) bundle-prompt builder for the TFE-to-CC engine variant.

Builds a single self-contained markdown prompt that instructs Claude Code
to diagnose the root causes of failing pytest-test clusters produced by
Phase 0 clustering, emitting a structured `tfe-diagnosis` JSON block at
end-of-run.

Design: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/19-tfe-to-cc-design.md
Live test: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/20-tfe-to-cc-phase1-live-test.md
"""

from typing import Optional


def build_diagnosis_bundle_prompt( clusters: list, failure_context: Optional[ dict ] = None ) -> str:
    """
    Build the Phase 1 diagnose bundle prompt for Claude Code.

    Requires:
        - clusters is a non-empty list of cluster dicts with:
            - cluster_id : str (e.g., "C1")
            - failing_tests : list of dicts, each with test_name + error_message
                              (optional: error_type, traceback_excerpt)
            - shared_error_signature : str (optional)
            - affected_files_guess : list of file paths (optional)
        - failure_context is an optional dict with 'source_suite' or other
          top-level context metadata

    Ensures:
        - Returns a markdown string with:
            - context + tool/guardrail rules + efficiency expectations
            - one section per cluster with failing tests + metadata
            - output contract (fenced tfe-diagnosis JSON block)
        - The prompt is self-contained — Claude Code does not need any
          other system-prompt augmentation.
    """
    if not clusters:
        raise ValueError( "clusters must be non-empty" )

    ctx = failure_context or {}

    lines: list = []

    lines.append( "# Test Fix Expediter — Phase 1: Diagnose failing test clusters" )
    lines.append( "" )
    lines.append( "You are diagnosing the root causes of failing pytest tests, grouped into clusters." )
    lines.append( "For each cluster below, read the relevant source and emit a concise diagnosis with a" )
    lines.append( "category + confidence. You are NOT applying fixes — diagnosis is read-only." )
    lines.append( "" )

    lines.append( "## Your context" )
    lines.append( "" )
    lines.append( "- Working directory: `/var/lupin/src` (the Lupin project)" )
    source = ctx.get( "source_suite" )
    if source:
        lines.append( f"- Source suite: `{source}`" )
    lines.append( "" )

    lines.append( "## Available tools + guardrails (strict)" )
    lines.append( "" )
    lines.append( "- ✅ Read — for specific files named in cluster metadata or discovered via Grep/Glob" )
    lines.append( "- ✅ Grep — targeted narrow searches (specific identifiers/patterns); NOT broad codebase sweeps" )
    lines.append( "- ✅ Glob — when a specific path is unclear, to find similarly-named files" )
    lines.append( "- ❌ Edit / Write — diagnosis is READ-ONLY; do NOT modify any file" )
    lines.append( "- ❌ Bash — do NOT run shell commands; do NOT run pytest; do NOT attempt to reproduce" )
    lines.append( "- ❌ cosa-voice blocking tools (ask_*, converse) — do NOT block on operator input in this run" )
    lines.append( "" )

    lines.append( "## Efficiency expectations (cost-conscious)" )
    lines.append( "" )
    lines.append( "- Per cluster: read at most 2-3 files. Cluster metadata names the candidate files — trust it." )
    lines.append( "- Commit to a diagnosis within 5-7 tool calls per cluster." )
    lines.append( "- Do not speculate beyond what the evidence supports. If the evidence is ambiguous, say so in `notes` and set `confidence` appropriately low." )
    lines.append( "- Do not speculate about fixes — that's Phase 2's job. Focus on root cause + category only." )
    lines.append( "" )

    lines.append( "## Clusters to diagnose" )
    lines.append( "" )

    for cluster in clusters:
        cid         = cluster[ "cluster_id" ]
        failing     = cluster.get( "failing_tests", [] ) or []
        fcount      = cluster.get( "failure_count", len( failing ) )
        sig         = cluster.get( "shared_error_signature" )
        affected    = cluster.get( "affected_files_guess", [] ) or []

        lines.append( f"### Cluster {cid} — {fcount} failing test(s)" )
        lines.append( "" )

        if sig:
            lines.append( f"**Shared error signature**: `{sig}`" )
            lines.append( "" )

        if affected:
            lines.append( "**Candidate affected files** (from Phase 0 static analysis — verify by reading):" )
            for f in affected:
                lines.append( f"- `{f}`" )
            lines.append( "" )

        lines.append( "**Failing tests**:" )
        lines.append( "" )
        for t in failing:
            test_name = t.get( "test_name", "(unnamed)" )
            lines.append( f"- `{test_name}`" )
            err_type = t.get( "error_type" )
            if err_type:
                lines.append( f"  - Error type: `{err_type}`" )
            err_msg = t.get( "error_message" )
            if err_msg:
                lines.append( f"  - Error message: `{err_msg}`" )
            tb = t.get( "traceback_excerpt" )
            if tb:
                lines.append( "  - Traceback excerpt:" )
                lines.append( "    ```" )
                for ln in str( tb ).splitlines():
                    lines.append( f"    {ln}" )
                lines.append( "    ```" )
        lines.append( "" )

    lines.append( "---" )
    lines.append( "" )
    lines.append( "## Output contract (required — orchestrator parses this)" )
    lines.append( "" )
    lines.append( "After you finish, emit EXACTLY ONE fenced JSON block at the end of your reply, fenced as:" )
    lines.append( "" )
    lines.append( "    ```tfe-diagnosis" )
    lines.append( "    { ... }" )
    lines.append( "    ```" )
    lines.append( "" )
    lines.append( "Schema:" )
    lines.append( "" )
    lines.append( "```" )
    lines.append( "{" )
    lines.append( '  "clusters": {' )
    lines.append( '    "<cluster_id>": {' )
    lines.append( '      "root_cause": "<one-paragraph plain-English explanation>",' )
    lines.append( '      "error_category": "<code_bug|test_bug|fixture_bug|environment_bug>",' )
    lines.append( '      "confidence": <float 0.0-1.0>,' )
    lines.append( '      "affected_components": ["<file_or_path>", ...],' )
    lines.append( '      "notes": "<optional additional context>"' )
    lines.append( "    }" )
    lines.append( "  }" )
    lines.append( "}" )
    lines.append( "```" )
    lines.append( "" )

    lines.append( "### Category guidance" )
    lines.append( "" )
    lines.append( "- `test_bug`: the test assertion is stale or wrong; the production code behaves correctly." )
    lines.append( "- `code_bug`: the production code has a defect the test correctly catches." )
    lines.append( "- `fixture_bug`: a shared fixture or conftest produces bad setup for this test (and likely others)." )
    lines.append( "- `environment_bug`: platform/dependency/data/infra issue, not Python code that can be fixed here." )
    lines.append( "" )

    lines.append( "### Confidence guidance" )
    lines.append( "" )
    lines.append( "- ≥ 0.85 — clear-cut: direct evidence in the source, unambiguous reading of the failure." )
    lines.append( "- 0.6 – 0.84 — strong hypothesis, but one alternative is plausible." )
    lines.append( "- 0.4 – 0.59 — moderate uncertainty; you had to choose between several plausible readings." )
    lines.append( "- < 0.4 — low confidence; significant guessing was required. In this case, populate `notes` with what you'd need to verify." )

    return "\n".join( lines )

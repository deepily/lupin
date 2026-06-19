"""
Phase 3 (apply fixes) bundle-prompt builder for the TFE-to-CC engine variant.

Builds a coordinator prompt for Claude Code that:
- Uses TodoWrite to plan N parallel fix attempts
- Spawns one Task subagent per selected fix with a focused Subagent Brief
- Collects subagent results
- Emits a single structured `tfe-result` fenced JSON block at end-of-run

Design: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/19-tfe-to-cc-design.md
Smoke:  src/rnd/v0.1.6/2026.04.10-test-fix-expediter/21-tfe-to-cc-phase3-live-test.md (execution log)
"""

from typing import Optional


def build_fix_bundle_prompt(
    selected_fixes       : list,
    diagnoses            : dict,
    worktree_path        : str,
    source_suite         : Optional[ str ] = None,
    commit_author_email  : str = "tfe-to-cc@lupin.local",
    commit_author_name   : str = "TFE-to-CC",
    emit_breadcrumbs     : bool = True,
    allow_mcp_escalation : bool = True,
) -> str:
    """
    Build the Phase 3 coordinator prompt for Claude Code.

    Requires:
        - selected_fixes : non-empty list of dicts, each with:
            cluster_id, title, fix_type, confidence, description,
            target_files (list), failing_tests (list of str)
        - diagnoses : dict keyed by cluster_id with root_cause, error_category,
            affected_components (optional), notes (optional)
        - worktree_path : absolute path inside the container that will be CC's cwd
        - commit_author_{email,name} : identity for `git -c user.email=... -c user.name=... commit`
        - emit_breadcrumbs : if True, prompt instructs coordinator + subagents to emit
            progress notifications via mcp__cosa-voice__notify
        - allow_mcp_escalation : if True, prompt permits subagents to escalate ambiguity
            via ask_yes_no / ask_multiple_choice. Coordinator orchestrates.

    Ensures:
        - Returns a self-contained markdown prompt
        - Coordinator instructions come first
        - Per-fix spec sections in deterministic order (as given)
        - Subagent Brief template is embedded verbatim — coordinator passes it into Task
        - Output contract is explicit
    """
    if not selected_fixes:
        raise ValueError( "selected_fixes must be non-empty" )

    n = len( selected_fixes )
    lines: list = []

    # ──────────────────────────────────────────────────────────────
    # Role + context
    # ──────────────────────────────────────────────────────────────
    lines.append( f"# TFE-to-CC Phase 3 — Apply {n} fixes in parallel inside an isolated worktree" )
    lines.append( "" )
    lines.append( f"You are the COORDINATOR for {n} fix attempts. Each fix targets a specific cluster of failing tests." )
    lines.append( "Your job: plan, dispatch one Task subagent per fix, collect results, emit a single structured JSON block at the end." )
    lines.append( "" )
    lines.append( "## Environment" )
    lines.append( "" )
    lines.append( f"- Working directory (CWD): `{worktree_path}` — an isolated git worktree off `origin/main`." )
    lines.append( "- All edits + commits happen INSIDE this worktree. The operator's live tree is untouched." )
    lines.append( f"- Commit identity: `git -c user.email=\"{commit_author_email}\" -c user.name=\"{commit_author_name}\" commit ...`" )
    lines.append( "- Do NOT `git push`. Do NOT run the full test suite. Do NOT touch anything outside the worktree." )
    if source_suite:
        lines.append( f"- Source test suite: `{source_suite}`" )
    lines.append( "" )

    # ──────────────────────────────────────────────────────────────
    # Workflow (coordinator)
    # ──────────────────────────────────────────────────────────────
    lines.append( "## Your workflow" )
    lines.append( "" )
    lines.append( "1. **Plan with TodoWrite**: create one todo item per fix below — title should read like \"Fix Cx: <short title>\"." )
    lines.append( "2. **Dispatch subagents in parallel via Task**: for each fix, spawn a Task subagent using the Subagent Brief below." )
    lines.append( "   - Claude Code will run 2-4 in parallel (internal limit). Dispatch them all; the runtime batches." )
    lines.append( "   - Each Task call's `description` should be \"Apply fix Cx\" and `prompt` is the rendered Subagent Brief for that fix." )
    lines.append( "3. **Collect results**: as each subagent returns, mark its todo item completed (or failed) and record its structured return." )
    if emit_breadcrumbs:
        lines.append( "4. **Emit progress breadcrumbs** via `mcp__cosa-voice__notify` (priority=\"low\", type=\"progress\"):" )
        lines.append( "   - Once at start: `\"TFE-to-CC Phase 3 starting: N fixes queued\"`" )
        lines.append( "   - Once per fix dispatched: `\"Dispatched Cx: <title>\"`" )
        lines.append( "   - Once per fix completed: `\"Cx: <verdict> — <commit_sha or reason>\"`" )
        lines.append( "   - These are fire-and-forget; do NOT use blocking cosa-voice tools for breadcrumbs." )
    else:
        lines.append( "4. Progress notifications not required for this run." )
    lines.append( "5. **Final aggregation**: after ALL subagents return, emit exactly ONE `tfe-result` fenced JSON block per the schema below." )
    lines.append( "" )

    # ──────────────────────────────────────────────────────────────
    # Tools
    # ──────────────────────────────────────────────────────────────
    lines.append( "## Coordinator tool guidance" )
    lines.append( "" )
    lines.append( "- ✅ **TodoWrite** — plan + track the N fixes." )
    lines.append( "- ✅ **Task** — dispatch subagents. Pass the rendered Subagent Brief (below) as the subagent prompt." )
    lines.append( "- ✅ **Read / Grep** — only if you need to resolve ambiguity BEFORE dispatching a subagent (rare). Prefer to pass the ambiguity into the subagent." )
    lines.append( "- ❌ **Edit / Write** — you do NOT edit files directly. Subagents own that." )
    lines.append( "- ❌ **Bash** for git commands — subagents own git commits inside their own fix scope." )
    lines.append( "- ✅ **mcp__cosa-voice__notify** — progress breadcrumbs per above." )
    if allow_mcp_escalation:
        lines.append( "- ℹ️ **mcp__cosa-voice__ask_yes_no** and **mcp__cosa-voice__ask_multiple_choice** — available if a cluster-level decision truly needs the operator. Prefer delegating ambiguity to subagents; only escalate if TWO OR MORE subagents all fail on the same structural issue and a policy call is needed." )
    lines.append( "" )

    # ──────────────────────────────────────────────────────────────
    # Subagent Brief template
    # ──────────────────────────────────────────────────────────────
    lines.append( "## Subagent Brief template — use this as each Task's `prompt`" )
    lines.append( "" )
    lines.append( "Copy this template into each Task dispatch, substituting the per-fix fields from the Fix specs below." )
    lines.append( "" )
    lines.append( "```" )
    lines.append( "You are a focused sub-engineer applying exactly ONE fix inside an isolated git worktree." )
    lines.append( "" )
    lines.append( "## Your fix" )
    lines.append( "" )
    lines.append( "- Cluster: {cluster_id}" )
    lines.append( "- Title: {title}" )
    lines.append( "- Type: {fix_type}" )
    lines.append( "- Confidence: {confidence}" )
    lines.append( "- Target files: {target_files}" )
    lines.append( "- Failing tests (for pytest -k): {failing_tests}" )
    lines.append( "- Description: {description}" )
    lines.append( "- Root cause (from Phase 1): {root_cause}" )
    lines.append( "" )
    lines.append( "## Environment" )
    lines.append( "" )
    lines.append( f"- CWD is `{worktree_path}` — all Read/Edit/Write operate here." )
    lines.append( f"- Commit identity: `git -c user.email=\"{commit_author_email}\" -c user.name=\"{commit_author_name}\" commit -m \"fix(tfe): {{cluster_id}} {{title}}\"`" )
    lines.append( "" )
    lines.append( "## Your steps" )
    lines.append( "" )
    lines.append( "1. **Read the target files** named above. Do NOT broadly Grep the codebase." )
    lines.append( "2. **Make the edit** within 3 tool calls after reading. Stay tightly scoped — apply ONLY what the description asks." )
    lines.append( "3. **Verify** with `pytest -k \"<test_names>\" --tb=short -v`. Use ONLY the failing-test names; do NOT run the full suite." )
    lines.append( "4. **Commit on pass**: `git add <files>` then the commit above. Capture the short SHA via `git rev-parse --short HEAD`." )
    lines.append( "5. **On pytest fail**: inspect output, make ONE retry adjustment. If that fails too, stop — report `verdict=\"failed\"`." )
    lines.append( "6. **If the proposal is unclear or target files don't contain the described code**: stop; report `verdict=\"unclear\"` with notes explaining what you found." )
    if emit_breadcrumbs:
        lines.append( "" )
        lines.append( "## Progress breadcrumbs (optional — nice to have)" )
        lines.append( "" )
        lines.append( "When natural, emit `mcp__cosa-voice__notify` (priority=\"low\", type=\"progress\") at these points:" )
        lines.append( "- \"Sub-engineer {cluster_id}: reading target file(s)\"" )
        lines.append( "- \"Sub-engineer {cluster_id}: applied Edit\"" )
        lines.append( "- \"Sub-engineer {cluster_id}: pytest passed\" OR \"pytest failed — retrying\"" )
        lines.append( "- \"Sub-engineer {cluster_id}: committed <sha>\" OR \"failed after retry\"" )
    lines.append( "" )
    lines.append( "## Return value (required)" )
    lines.append( "" )
    lines.append( "Your final assistant message MUST be a single JSON object on its own (no fence needed):" )
    lines.append( "" )
    lines.append( "{" )
    lines.append( '  "cluster_id": "{cluster_id}",' )
    lines.append( '  "verdict": "fixed" | "failed" | "unclear",' )
    lines.append( '  "commit_sha": "<short sha or null>",' )
    lines.append( '  "files": ["path/to/changed.py", ...],' )
    lines.append( '  "pytest_passed": true | false,' )
    lines.append( '  "notes": "<short free-text explanation>"' )
    lines.append( "}" )
    lines.append( "" )
    lines.append( "## Hard rules" )
    lines.append( "" )
    lines.append( "- Do NOT run `git push`. Do NOT run the full pytest suite. Do NOT touch files outside the worktree." )
    lines.append( "- Do NOT edit test files unless fix_type is `test_patch` (or explicitly allowed by the description)." )
    lines.append( "- Do NOT retry more than once after a pytest failure. Report and exit." )
    lines.append( "```" )
    lines.append( "" )

    # ──────────────────────────────────────────────────────────────
    # Per-fix specs
    # ──────────────────────────────────────────────────────────────
    lines.append( "---" )
    lines.append( "" )
    lines.append( f"## The {n} fixes to apply" )
    lines.append( "" )

    for i, fix in enumerate( selected_fixes, start=1 ):
        cid    = fix[ "cluster_id" ]
        title  = fix[ "title" ]
        ftype  = fix.get( "fix_type", "code_patch" )
        conf   = fix.get( "confidence", "?" )
        desc   = fix.get( "description", "" )
        files  = fix.get( "target_files", [] ) or []
        tests  = fix.get( "failing_tests", [] ) or []

        diag      = diagnoses.get( cid ) or {}
        root      = diag.get( "root_cause", "(no Phase 1 diagnosis — use the description below)" )
        err_cat   = diag.get( "error_category", "unknown" )

        conf_str = f"{conf:.0%}" if isinstance( conf, ( float, int ) ) else str( conf )

        lines.append( f"### Fix {i}: `{cid}` — {title}" )
        lines.append( "" )
        lines.append( f"- **fix_type**: {ftype}" )
        lines.append( f"- **confidence**: {conf_str}" )
        lines.append( f"- **error_category**: {err_cat}" )
        lines.append( f"- **target_files**: {files if files else '(none named — subagent may discover via Grep if needed)'}" )
        lines.append( f"- **failing_tests** (for pytest -k): {tests if tests else '(none captured — subagent may omit -k filter)'}" )
        lines.append( "" )
        lines.append( f"**root_cause**: {root}" )
        lines.append( "" )
        lines.append( "**description**:" )
        lines.append( "" )
        lines.append( desc )
        lines.append( "" )

    # ──────────────────────────────────────────────────────────────
    # Output contract
    # ──────────────────────────────────────────────────────────────
    lines.append( "---" )
    lines.append( "" )
    lines.append( "## Final output contract (required — orchestrator parses this)" )
    lines.append( "" )
    lines.append( "After ALL subagents have returned, emit EXACTLY ONE fenced block at the end of your reply:" )
    lines.append( "" )
    lines.append( "    ```tfe-result" )
    lines.append( "    { ... }" )
    lines.append( "    ```" )
    lines.append( "" )
    lines.append( "Schema:" )
    lines.append( "" )
    lines.append( "```" )
    lines.append( "{" )
    lines.append( '  "clusters": {' )
    lines.append( '    "<cluster_id>": {' )
    lines.append( '      "verdict": "fixed" | "failed" | "unclear",' )
    lines.append( '      "commit_sha": "<short sha or null>",' )
    lines.append( '      "files": ["path/to/changed.py", ...],' )
    lines.append( '      "pytest_passed": true | false,' )
    lines.append( '      "notes": "<short free-text>"' )
    lines.append( "    }" )
    lines.append( "  }," )
    lines.append( '  "summary": "<K>/<N> fixed"' )
    lines.append( "}" )
    lines.append( "```" )
    lines.append( "" )
    lines.append( "The schema MUST include every dispatched cluster_id as a key, even for failed or unclear outcomes." )

    return "\n".join( lines )

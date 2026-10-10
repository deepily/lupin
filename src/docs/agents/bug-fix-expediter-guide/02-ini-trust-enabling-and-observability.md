> Part 2 of 3 of the [Bug Fix Expediter (BFE) Guide](../bug-fix-expediter-guide.md): sections 4 to 7, INI keys, trust-to-git, enabling auto-fix, observability.

## 4. INI Reference

All BFE keys live in `src/conf/lupin-app.ini` under `[Lupin: Baseline]`. Splainer
entries live in `src/conf/lupin-app-splainer.ini`.

| Key | Default | Purpose |
|-----|---------|---------|
| `bug fix expediter enabled` | `false` | Master feature flag. When false, dead-queue watchdog skips BFE entirely and `/api/bug-fix-expediter/submit` returns 503. |
| `bug fix expediter lead model` | `claude-opus-4-6` | Opus model for Phase 1 diagnose and Phase 2 propose. |
| `bug fix expediter worker model` | `claude-sonnet-4-6` | Sonnet model for Phase 3 Coder and Tester agents. |
| `bug fix expediter max diagnosis iterations` | `3` | Upper bound on Phase 1 refinement rounds. |
| `bug fix expediter min diagnosis confidence` | `0.7` | Early-exit threshold for Phase 1 iteration. |
| `bug fix expediter max fix attempts` | `2` | Upper bound on Phase 3 Coder-Tester retry loop. |
| `bug fix expediter max file changes per fix` | `20` | SafetyGuard cap on file modifications per Coder delegation. |
| `bug fix expediter wall clock timeout seconds` | `600` | Overall pipeline timeout (all phases combined). |
| `bug fix expediter budget usd` | `2.00` | Max USD spend per BFE session (enforced by cost tracker). |
| `bug fix expediter feedback timeout seconds` | `300` | Timeout for blocking human feedback via voice gates. |
| `bug fix expediter narrate progress` | `true` | Voice breadcrumbs during each phase. Set false for silent overnight runs. |
| `bug fix expediter auto retry on fix` | `false` | Phase 6 auto-resubmit of the original job after a successful fix. |
| `bug fix expediter require user confirm` | `true` | Ask user confirmation at Phase 1 (diagnosis) and Phase 2 (fix selection) gates. |
| `bug fix expediter trust mode` | `shadow` | Trust proxy mode: `shadow` (level 1, commit_only), `suggest` (level 2, commit_only), `active` (level 3+, branch_and_pr). |
| `bug fix expediter push fix branch enabled` | `false` | Whether trust level 3 and above pushes the fix branch and opens the PR. Off, the fix stays a local commit on its fix branch and the run says nothing was pushed. |

**Config loading**: `BugFixExpediterConfig.from_config(config_mgr)` reads all keys
with type coercion (int/float/bool/string) based on dataclass field annotations.
See `src/cosa/agents/bug_fix_expediter/config.py`.

### Per-invocation model overrides

`lead model` and `worker model` can be overridden per job submission via
`args.lead_model_override` / `args.worker_model_override`. The job class
stores them as `self.lead_model_override` / `self.worker_model_override`
and applies them in `_execute()` after `from_config()` loads the INI defaults.

**Watchdog-spawned BFE**: the originally failed job may carry
`bfe_lead_model_override` / `bfe_worker_model_override` in its
`args_dict`. If so, `DeadQueueWatchdog` propagates them to the spawned BFE (same
pattern as `dry_run` propagation). This lets the E2E script's `--cheap`
flag flow through the full watchdog → BFE path without bypassing dispatch.

**Primary use case**: `./src/tests/e2e/run-bfe-live-e2e.sh --live --cheap`
runs BFE with Sonnet lead + Sonnet worker for ~60-75% cost reduction on
trivially-fixable E2E fixtures. Production dispatch paths (real failures,
not E2E) leave overrides unset → use INI defaults.

---

## 5. Trust-to-Git Mapping

Shared with TFE — see [Shared Primitives Reference §4](../shared-fix-primitives-reference/01-planwriter-gitstrategist-fixexecutor.md#4-gitstrategist--trust-aware-git-operations)
for the canonical table. In summary:

| Trust Level | `trust_mode` value | Git Strategy | Produces |
|-------------|---------------------|--------------|----------|
| Level 1 Shadow | `shadow` | `commit_only` | Commit on current branch |
| Level 2 Suggest | `suggest` | `commit_only` | Commit on current branch |
| Level 3+ Active | `active` | `branch_and_pr` | New `fix/YYYY-MM-DD-{slug}` branch + push + PR via `gh` |
| `gh` missing | any | `branch_only` (degraded) | Branch + commit + push; no PR |
| Proxy down | any | `commit_only` (fallback) | Commit on current branch |

**The push is behind its own flag.**

At trust level 3 and above the `branch_and_pr` row applies only when
`bug fix expediter push fix branch enabled` is `true`. It is `false` by default. With it off, BFE commits the fix on a
new `fix/...` branch, pushes nothing, opens no PR and checks the original branch out again. The result is
`commit_only`. Its error reads "push disabled (bug fix expediter push fix branch enabled is false): nothing was
pushed and no pull request was opened". TFE has its own key. Trust levels 1 and 2 never push.

The trust level is read at Phase 5 time via
`GitStrategist.resolve_trust_level(orchestrator.proxy)`. If the SWE Team Trust
Proxy isn't wired up (e.g., local dev without the proxy DB), the resolver returns
level 1. BFE then operates in commit-only mode regardless of the `trust_mode` INI setting.

**Commit message format**: `[BFE] Fix: {first 60 chars of fix.details}` (or
`[BFE] Fix` if details is empty). PR title follows the same convention.

---

## 6. How to Enable Auto-Fix

### Step 1: Enable the feature flag

Edit `src/conf/lupin-app.ini`:

```ini
bug fix expediter enabled = true
```

This unblocks:
- The dead-queue watchdog's ability to dispatch BFE jobs
- The `/api/bug-fix-expediter/submit` endpoint
- BFE registration in the agent router

Restart the FastAPI server (`src/scripts/run-fastapi-lupin.sh`) or wait for
auto-reload if running in dev mode.

### Step 2: Choose your trust mode

Start with `shadow` (the default). In shadow mode, BFE will:
- Diagnose, propose, and fix as normal
- Commit to your current branch (no automatic branching)
- Never push or create PRs without your explicit intervention

Monitor BFE's behavior for a few runs before moving to `suggest` or `active`.

To graduate to `active` (level 3+ branching + PR):

```ini
bug fix expediter trust mode = active
bug fix expediter push fix branch enabled = true
```

The second line is what allows the push. Left at its default `false`, `active` still branches and commits locally but pushes nothing.

This requires a populated SWE Team Trust Proxy and functional `gh` CLI.
See the [Decision Proxy Admin Guide](../../proxy-admin-guide.md) for how to earn
level 3+ trust through the ratification workflow.

### Step 3: Enable Phase 6 auto-retry (optional)

To have BFE automatically resubmit the original failed job after a successful fix:

```ini
bug fix expediter auto retry on fix = true
```

Without this flag, BFE completes at Phase 5 and you manually re-submit the failed
job when you're satisfied with the fix.

### Step 4: Watch the dead queue

Once enabled, any agentic job that lands in the dead queue becomes a candidate for
BFE. Monitor via:

- **Queue UI** at `http://localhost:7999` — dead queue column shows failed jobs
- **cosa-voice notifications** — BFE sends voice breadcrumbs at every phase
- **Voice gates** — if `require_user_confirm=true`, BFE will ask you to approve the
  diagnosis and select a fix before applying it

### Step 5: Manually invoke BFE on a specific dead job

If you prefer to curate which dead jobs get BFE treatment rather than enabling the
automatic watchdog, submit via the REST API:

```bash
curl -X POST http://localhost:7999/api/bug-fix-expediter/submit \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"dead_job_id": "dr-abc12345::user123", "extra_context": "Optional hint"}'
```

See [REST API Reference](../../rest-api-reference.md) for the full endpoint schema.

---

## 7. Observability

### Queue UI

Failed agentic jobs appear in the dead queue card. When BFE picks one up, a new
`bfe-*` job appears in the todo → run → done pipeline. Clicking the BFE job card
in the Activity Log shows:

- Current phase badge (`diagnosing`, `proposing`, `fixing`, `committing`, `completed`)
- Voice notification history
- Interaction prompts (voice gates)

### Plan documents

Every BFE run produces a Markdown plan document at
`io/swe-team/plans/{user_email}/YYYY.MM.DD-{slug}-plan.md`. This is the canonical
audit trail — diagnosis, proposed fixes, the selected fix, implementation log,
and git references. Read it to understand what BFE did.

### Voice notifications

When `bug fix expediter narrate progress = true` (default), BFE fires cosa-voice
notifications at every phase transition and every Coder/Tester tool use. Messages
include the job_id for WebSocket routing to the Activity Log.

To silence voice notifications (e.g., overnight runs):

```ini
bug fix expediter narrate progress = false
```

### Git history

At level 3+ trust, BFE creates branches named `fix/YYYY-MM-DD-{slug}`. Use `git branch --all`
to find them, or check the PR list on GitHub (`gh pr list --state all`).

At trust levels 1 and 2, fixes land as new commits on your current branch with `[BFE] Fix:`
prefixes. Use `git log --grep="\[BFE\]"` to find them.

### Debug logging

Set `debug=True` on the `BugFixExpediterJob` constructor to enable verbose
`[BFEOrchestrator]` diagnostic prints. Debug output goes to the FastAPI server's
stdout (or `/tmp/lupin-fastapi.log` when running via the run script).

---


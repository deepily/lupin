# Lupin Testing Strategy

Comprehensive six-tier testing approach to ensure code quality, reliability, and security.

## 🔴 BEFORE ANY `--cov` RUN — export COVERAGE_FILE

```bash
export COVERAGE_FILE=/tmp/cov-$USER-$$.data
```

Since `dfb53168`, `pytest --cov` with `COVERAGE_FILE` unset is **refused outright** —
a `pytest.UsageError` raised before any measurement is written, carrying this remedy in
the message. Runs without `--cov` are untouched; an exported `COVERAGE_FILE` behaves
exactly as before. To share the repo-root file on purpose: `LUPIN_ALLOW_SHARED_COVERAGE=1`.

**Why the refusal exists.** Every session was writing the same repo-root `.coverage`,
which pytest-cov erases at startup, so a long run and a short one silently ate each other.
A tier run reported **96.59% — green and false**, with ~28,000 statements gone from the
denominator; because the vanished files were the worse-than-average ones, the mean went
**up** while nothing improved (row `aa41fa66`). A contended run measured **82% / 1320
missing** where the identical tree alone read **89% / 853** — directionally hostile, since
coverage looking *worse* invites tests for a hole that is not there (row noted in TODO.md
Decisions Log, 2026-08-26).

**Scope boundary — `source`, `omit` and `fail_under` were NOT touched by `dfb53168`.**
`fail_under` belongs to the coverage-ramp owner and stays there. The guard decides *where a
run writes*, never *what threshold it must clear*.

## 🔴 EDITING A SOURCE FILE INSIDE A TEST? THE NEXT IMPORT MAY NOT SEE IT

If your test (or your by-hand probe) writes to a `.py` file and then imports or re-runs it, use
the opt-in helper — otherwise the interpreter can keep running the *old* code:

```python
from tests.helpers.pyc_freshness import mutate_source     # the pytest fixture
from tests.helpers.pyc_freshness import refresh_source    # or the bare function

def test_thing( mutate_source ):
    mutate_source( SRC, SRC.read_text().replace( '"todo"', '"dead"' ) )
    ...                                    # every touched file restored at teardown
```

**Why (row `d18ce9ef`, measured 2026-08-29).** CPython validates a `.pyc` on the source's
**whole-second** mtime **plus** its **size**. A mutation edit changes neither — `"todo"` → `"dead"`
is four characters either way, and a scripted loop does the edit and the restore inside one second
— so the stale bytecode is served as valid. Measured on `src/cosa/rest/job_state.py`: source mtime
`21:33:22.780`, pyc built `21:33:22.568`; for minutes `grep` said `todo` and `import` said `dead`.

**The failure points the wrong way.** You restore the file, read it back to confirm, and the
interpreter keeps running the mutant. Mutation testing is how a great deal of this repo earns its
receipts, so a hazard aimed at it is aimed at the evidence.

**It is CROSS-PROCESS** — a *fresh* pytest reads the stale `.pyc` off disk. So this is not
`importlib.reload` staleness, `sys.modules` bookkeeping does not fix it, and neither does
`importlib.invalidate_caches()`, which clears finder caches rather than pyc validation.

⚠️ **`PYTHONDONTWRITEBYTECODE` does NOT fix this** — measured. It only stops pycs being *written*;
one already on disk is still read and still wins. It passes only from a tree cleaned first, which
means the clean is the protection, not the flag. `PYTHONPYCACHEPREFIX` merely relocates the race.

**If you are debugging a red you cannot explain**, clear the cache before concluding anything:

```bash
src/scripts/purge-pycache.sh   # purge AND reconvert to checked-hash (row 866f43ce)
```

**Two sightings in one evening, on different files, with nobody hunting for it** — `job_state.py`
during the AC-G4 mutation sweep, then `tests/helpers/pyc_freshness.py` itself while the helper was
being built. The second went red against code no longer on disk and was nearly logged as a flake;
it failed in the *safe* direction, which is luck, not design — the same collision with a mutant
still live reads as **green**.

Full measurement, six remedies priced, and the still-open repo-wide question:
`src/rnd/v0.2.1/2026.08.29-stale-pyc-defeats-mutation-testing.md`.

## 🔴 A GREEN THAT DEPENDS ON AN UNCOMMITTED FILE IS YOURS, NOT THE BRANCH'S

Some checks read a **recorded artifact from the working tree** rather than from git. The pass
condition is then *"the file exists on disk"* — not *"the file is committed"*, and not *"the fix is
on the branch"*. Drop the artifact in without committing and your tier goes green while **anyone
cloning fresh still gets the red**.

**Measured 2026-08-30** on `test_secret_scan.py::test_a_detector_change_forces_a_full_rescan`, same
tree at `12b4bdb4`, one variable:

| tree state | result |
|---|---|
| clean, fixture not updated | **1 failed** |
| same tree, updated fixture copied in, **uncommitted** | **1 passed** (`git status`: `" M"`) |

That test does `json.load( open( record ) )`. Git never touches the fixture.

⇒ **THE TELL IS MECHANICAL — USE IT INSTEAD OF TRYING TO BE CAREFUL.** Before reporting a suite
green, check whether its recorded artifact is modified:

```bash
git status --porcelain src/tests/unit/fixtures/     # " M" on a recorded artifact = LOCAL green
```

**This is not a warning about dishonesty.** Someone can drop a fixture in, watch the red go away,
and report it in complete good faith — the run really did pass, in the only tree they can see. The
marker is what separates *"I fixed it"* from *"my directory differs from the branch"*, and it costs
one command.

⚠️ **The class is wider than the secret scanner**, and it splits in two. The audit is at
`src/rnd/v0.2.1/2026.08.30-working-tree-artifact-gate-audit.md`; the short version:

- **TRACKED records** — the secret-scan fixture, the parity-oracle goldens, `pyproject.toml`'s
  `fail_under`. Editing one turns red into green, and the `" M"` above catches all of them.
  (`run-coverage-gate.sh` already prints `tracked-dirty=` for exactly this reason.)
- 🔴 **GITIGNORED artifacts — `git status` CANNOT SEE THESE, so the tell above is blind.** An
  ignored path produces no output at all, not even `??`. Two gates read one today:
  `test_freeze.py` reads a DM corpus under `src/tmp/`, and `test_terraform_invariants.py` reads
  a provider cache under `.terraform/`. Present ⇒ the tests run; absent ⇒ they **skip**, and the
  summary still says green. Measured: `test_freeze.py` reports 494 passed on a host that has the
  corpus; seven of its test functions skip on one that does not.

⇒ **If a gate reads a path git ignores, its result is a property of your machine and no marker
will tell you.** That one is answered by the audit above, once — not by a seat before every run.

## Test Hierarchy

### 1. Unit Tests (`src/tests/unit/`)

**Purpose**: Test individual functions and methods in isolation

**Characteristics**:
- Very fast execution (1-10ms per test)
- Test single function behavior
- Use mocks/stubs for dependencies
- Test both success and failure paths
- High coverage of edge cases

**Coverage**: 2,832 tests across 104 test files covering:
- Auth subsystem (JWT, password, user, rate limiter, API keys)
- Agent orchestrators (BFE, SWE Team, Calculator, CRUD)
- Notification system (models, hooks, proxy, predictions)
- Queue management (job state, persistence, filtering, timed execution)
- Presentation generator (renderers, prompts, API client)
- WebSocket validators, session bridge, trust tracking, and more

**Run Command**:
```bash
# Run all unit tests
pytest src/tests/unit/ -v

# Run specific test file
pytest src/tests/unit/test_jwt_service.py

# Run specific test
pytest src/tests/unit/test_jwt_service.py::test_create_access_token_valid_user
```

**Bare-run env** (bug 9fe8b80f): only `LUPIN_ROOT` must be exported —
`LUPIN_ROOT=/path/to/lupin pytest src/tests/unit/`. The top-level
`src/tests/conftest.py` floors `LUPIN_CONFIG_MGR_CLI_ARGS` to the
`Lupin: Development` block (via `os.environ.setdefault`), so files that
instantiate `ConfigurationManager` at import time collect cleanly without a
manual export. Export `LUPIN_CONFIG_MGR_CLI_ARGS` yourself to override the
block (e.g. `Lupin: Testing`); an explicit value always wins over the floor.

---

### 2. Smoke Tests (Inline `quick_smoke_test()` Functions)

**Purpose**: Quick sanity checks that modules load and basic functionality works

**Characteristics**:
- Fast execution (10-100ms per module)
- Module-level validation
- Test core functions exist and can be called
- Minimal dependencies

**Coverage**: ~50 smoke tests across all major modules

**Run Command**:
```bash
# Run smoke test for specific module
python -m cosa.rest.jwt_service

# Run all smoke tests via runner scripts
./src/scripts/run-smoke-tests.sh
./src/scripts/run-smoke-direct.sh    # Direct execution (no pytest)
```

---

### 3. Integration Tests (`src/tests/integration/`)

**Purpose**: Test complete user flows end-to-end across API, database, and authentication

**Characteristics**:
- Medium execution (100-1000ms per test)
- Test full system interaction with real HTTP requests
- Verify database state changes
- Require a running FastAPI server on port 7999
- **CRITICAL**: Always use `--bg` flag from Claude Code (suite can exceed 10min Bash timeout under load)

**Coverage**: 263 tests across 20 test files covering:
- Complete authentication flows (register, login, refresh, logout, password reset)
- Admin user management (listing, roles, status, password reset)
- Queue filtering and job management
- API key operations
- Token validation and proactive refresh

**Run Command**:
```bash
# Recommended (background, avoids Bash timeout)
./src/tests/run-integration-tests.sh --bg -v

# Monitor progress
tail -20 /tmp/integration-latest.log

# Check if still running
kill -0 $(cat /tmp/integration-tests.pid) 2>/dev/null && echo running || echo done

# Quick foreground run (specific pattern only)
./src/tests/run-integration-tests.sh test_auth*.py
```

---

### 4. WebSocket Smoke Tests (`src/tests/websocket_smoke/`)

**Purpose**: Validate WebSocket functionality and event handling

**Characteristics**:
- Custom test runner (not pytest-based)
- Tests WebSocket connections, authentication, event delivery
- Tests both queue and audio WebSocket endpoints

**Coverage**: 50 WebSocket tests

**Run Command**:
```bash
# Run WebSocket smoke tests
./src/scripts/run-websocket-smoke-tests.sh
```

---

### 5. E2E UI Tests (`src/tests/e2e_ui/`)

**Purpose**: End-to-end browser testing with Playwright Chromium headless

**Characteristics**:
- Playwright Chromium headless browser against live server
- Covers all pages (public, auth, admin)
- Parametrized page smoke tests, auth flows, navigation, WebSocket tests
- Visual regression via `pytest-playwright-visual-snapshot`
- **CRITICAL**: Always use `--bg` flag from Claude Code (suite takes ~17min, exceeds 10min Bash timeout)

**Coverage**: 328 tests across 30 test files including:
- Functional tests (page loads, auth flows, navigation, admin, WebSocket, CJ Flow)
- Visual regression snapshot tests (profile, notifications, landing, etc.)
- Pause/resume, scheduling, and job history UI tests

**Run Command**:
```bash
# All E2E tests (background, recommended)
./src/scripts/run-e2e-ui-tests.sh --bg -v

# Visual regression only
./src/scripts/run-e2e-ui-tests.sh --bg -v -k visual

# Update baselines after intentional UI changes
./src/scripts/run-e2e-ui-tests.sh --bg --update-snapshots -k visual

# Monitor progress
tail -20 /tmp/e2e-ui-latest.log

# Check if still running
kill -0 $(cat /tmp/e2e-ui-tests.pid) 2>/dev/null && echo running || echo done
```

**Visual Regression Workflow**:
1. First run creates baseline screenshots in `src/tests/e2e_ui/__snapshots__/`
2. Subsequent runs compare against baselines (10% pixel threshold)
3. After intentional UI changes: `--update-snapshots` to regenerate baselines
4. Failures produce diff images in `src/tests/e2e_ui/snapshot_failures/`
5. Baselines are version-controlled; failure diffs are gitignored

---

### 6. Interactive Proxy Tests (`src/tests/smoke/test_proxy_integration.py`)

**Purpose**: Automated interactive testing with notification proxy auto-answer

**Characteristics**:
- Tests full agent pipelines including notification-driven user interactions
- Notification proxy auto-answers expediter questions and CRUD confirmations
- 12 scenarios across 3 agent groups (Calculator, CRUD, Expediter)
- Validates submit-and-poll pipelines, arg resolution, and proxy auto-confirmation

**Coverage**:
- Calculator: 3 scenarios (unit conversion, mortgage, price comparison)
- CRUD: 5 scenarios (add/list/delete for todo + calendar)
- Expediter: 4 scenarios (deep research, podcast, research-to-podcast, full args)

**Run Command**:
```bash
# Full integration (requires LUPIN_INTERACTIVE_TESTS=true for expediter)
LUPIN_INTERACTIVE_TESTS=true \
python src/tests/smoke/test_proxy_integration.py --group all --auto-proxy --no-confirm

# Calculator only (no proxy needed)
python src/tests/smoke/test_proxy_integration.py --group calculator --no-confirm

# Via pytest
pytest src/tests/smoke/test_proxy_integration.py -v
```

**Full Guide**: See [`src/docs/automated-interactive-testing.md`](../docs/automated-interactive-testing.md)

---

### 7. TypeScript / DOM Tests (`src/tests/unit/**/*.test.ts`)

**Purpose**: Test browser-side modules (multiplexer, notifications, nav) under `happy-dom`

119 `.test.ts` files live under `src/tests/unit/`. Until this section existed they were
absent from this document entirely, so a person writing one had nothing to read.

> 🔴 **THE TIER IS UNDER A STANDING BAN.** Do not run `npm test`, `node --test`, or any
> runner that globs `src/tests/**/*.ts`. The ban followed the 2026-08-22/23 out-of-memory
> kills that took down roughly two dozen sessions. It has not been lifted. Containment work
> is row `92e94cb7`; the ban holds **by filename only**, so any new runner that globs these
> paths silently re-arms the hazard.

#### 🔴 THE RULE — read this BEFORE you write the assertion

**Never pass a DOM node as the ACTUAL value of an assertion.** Assert a **primitive
projection** instead — `.textContent`, `.id`, `.tagName`, a count, a boolean.

```ts
// VIOLATION - when this FAILS, node:assert deep-inspects the node to build its diff,
//   walking element -> ownerDocument -> defaultView -> the whole Window graph, ~2.5 GB/s,
//   without terminating, until the kernel kills the process.
assert.equal( root.querySelector( ".thing" ), null );

// CORRECT - the assertion holds a primitive, so a failure diff is bounded.
assert.equal( root.querySelector( ".thing" )?.textContent ?? null, null );
assert.equal( root.querySelectorAll( ".thing" ).length, 0 );
```

The node may be produced and inspected freely. It must not be **the thing the assertion is
holding at the moment it fails** — a passing assert never builds a diff, which is why these
survive in review and kill in CI.

**Measured** (row `32c58572`, three runs per cell):

| Condition | Outcome |
|---|---|
| happy-dom element + **FAILING** assert | **killed 3/3** |
| happy-dom element + PASSING assert | survives |
| plain object + FAILING assert | survives |
| no happy-dom | survives |

**Enforcement**: `src/tests/dom_assert_lint.py`, ratcheted against
`src/tests/dom_assert_baseline.txt` and run by `src/tests/unit/test_dom_assert_lint.py` in
the **Python** unit tier — because an ESLint rule would be the better instrument and would
run nowhere: no config covers `src/tests`, and the TS tier is banned. Counts may only fall.
A file that gains a violation goes red.

**Known violations**: 276 across 35 files, recorded as a ratchet, not forgiven. Burning them
down is separate work (row `f5768ee4` item 2) and must not be done blind — each is a real
assertion whose intent has to survive the rewrite.

**Background**: [`src/docs/explainers/2026.08.24-oom-debugging-story-explainer.md`](../docs/explainers/2026.08.24-oom-debugging-story-explainer.md)

---

## Red-first commits carry a banner

When a fix lands as two commits — a RED that proves the defect is live, then the GREEN that
fixes it — the RED commit is a **deliberately failing state on the main line**. Anyone who
checks out that sha, or whose tooling does, sees failures and has no way to tell them from a
regression. That has already produced one escalation (2026-08-24, row `9d89afe2`): a peer ran
the file at the RED sha, reported 3 failures, and the report was accurate and the code was
fine.

**The rule**: a test file introduced by a red-first commit carries a banner at the top of its
module docstring naming both shas and both expected outcomes.

```
╔══════════════════════════════════════════════════════════════════════════════╗
║ RED-FIRST FILE. IF THIS IS FAILING, CHECK YOUR SHA BEFORE REPORTING IT.      ║
║                                                                              ║
║   expected to FAIL  at  <red sha>   — N failed, M passed                     ║
║   expected to PASS  from <green sha> onward — K passed                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

Say which failures are expected and how many, and say plainly that a red at or after the
GREEN sha is a real regression worth reporting **with the reporter's sha**. Live example:
`src/tests/unit/test_registry_topic_not_a_file_path.py`.

⚠️ **You cannot write the RED sha into the RED commit.** The sha does not exist until the
commit is made, so a banner naming it must be added afterwards — which means the banner
itself lands in the GREEN commit or later, and the window it protects is exactly the window
where it is absent. Two ways to close that, neither free:

| Approach | Cost |
|---|---|
| Banner with the shas left as `<pending>` in the RED commit, filled in by the GREEN | Two edits; the RED sha is still unnamed while only the RED exists |
| Name the **row id** in the RED commit and the shas in the GREEN | The row is stable and knowable in advance; the shas arrive when they exist |

### How many files this rule does NOT yet describe

**Measured 2026-08-24, and deliberately NOT SWEPT.** Recorded so the next reader inherits the
number instead of rediscovering it, and so this section is not mistaken for a description of
the tree as it stands:

| | count |
|---|---|
| Test files self-describing as red-first | **27** |
| …carrying a sha-naming banner | **1** (`test_registry_topic_not_a_file_path.py`) |
| **Not yet compliant** | **26** |

Method, so the count is re-derivable rather than trusted:

```bash
grep -rlie 'red-first' src/tests/unit/*.py src/cosa/tests -r | sort -u | wc -l
# then, per file: grep -qiE 'expected to (FAIL|PASS)'
```

Red-first is an established practice here, older than this section — the section is its
written home, not its introduction. Bannering the other 26 is real work and is not scheduled;
it is a mechanical edit per file that still needs a human to read each one and name the right
two shas, which is exactly the kind of change that should not be batched at speed.

The second is preferred: `row 9d89afe2, red-first — this file is expected to fail until the
fix commit` is writable at RED time and already answers the reader's question. **A banner that
can only be written after the danger has passed is worth having anyway** — most readers arrive
long after, not during — but do not record it as though it protects the gap. It does not.

---

## Mutation harnesses: restore by BYTE SNAPSHOT, and verify the restore

Row `c0a829a3`, 2026-08-29. Tiberius reported this against his own work while closing
`f42ac20c`, and caught it before it reached a claim:

> "My first mutation harness restored with `git checkout`, which CANNOT restore an
> UNTRACKED file. Three mutations stacked silently and the 'restored' line read
> 4 failed instead of 7 passed. That line is the only reason I noticed."

**The mechanism, measured 2026-08-29 rather than repeated.** `git checkout -- <path>` restores
a file from the index, and a file git does not track has nothing to restore FROM — so the
mutation stays on disk and every mutation after the first lands on a tree still carrying the
one before it. This bites hardest exactly where mutation testing is most common: a test file
added in the same commit is UNTRACKED while you are mutating against it.

⚠️ **But it does NOT fail silently, and that changes where the fix goes.** Run live against an
untracked file, `git checkout --` exits **1** and prints
`error: pathspec '<path>' did not match any file(s) known to git`. So the restore announces
its own failure; what makes the mutations stack is a harness that **does not check the exit
code** — `subprocess.run(...)` without `check=True`, or a shell call whose status is
discarded. Read that as the actual rule: *a restore step whose result you do not check is not
a restore.* The byte-snapshot below is still the right tool, because it is the only one that
works on an untracked file at all — but an unchecked `git checkout` is what turns a loud
failure into a silent one.

**Do this instead** — read the bytes, write them back, and *check*:

```python
import hashlib, pathlib
p        = pathlib.Path( target )
original = p.read_bytes()                      # snapshot BEFORE the first mutation
before   = hashlib.sha256( original ).hexdigest()
try:
    p.write_bytes( mutated )
    ...run the suite, record the result...
finally:
    p.write_bytes( original )                  # restore
    after = hashlib.sha256( p.read_bytes() ).hexdigest()
    if after != before:                        # ⬅ THE CONTROL. Do not skip it.
        raise SystemExit( f"RESTORE FAILED for {p}: {before} != {after}" )
```

### 🔴 A mutation run whose final restore-and-verify control is not CHECKED is not evidence.

That is the transferable sentence; everything above is how you get there. A harness must END
with a restore-and-verify pass and must FAIL LOUDLY when the tree does not come back
byte-identical. Without it you have a list of numbers measured against a tree nobody intended,
and nothing anywhere says so. Tiberius only caught his because he ran a final control **and
read it** — running one and not reading it is the same as not having one.

⚠️ **Never use `git stash` as the restore mechanism.** The stash stack is **repo-global** and
shared across every worktree and every live session — measured 2026-08-23 (bug `1ebc9be3`),
where one seat's pop applied another seat's held work into the wrong tree. A `stash_guard.py`
PreToolUse hook denies the mutating verbs. A byte snapshot held in your own process is the
correct tool, and it is also the only one that works on an untracked file.

⚠️ **Mutate in your own worktree, on files you own.** Never mutate a file in the shared tree
while peers are live in it.

**Scope, measured 2026-08-29 rather than assumed:** no SHARED harness in this repo is exposed.
The only tracked tool with "mutant" in its name — `src/tests/tools/mutant_adequacy_generator.py`
— derives how many mutants a predicate *should* have and performs **no file writes and no
subprocess calls**, so it cannot mutate or restore anything. No `git checkout` / `git restore`
/ `git stash` is used anywhere in this tree as a restore-after-mutation path. Mutation
harnesses here are built ad hoc, per seat, per task — which is exactly why this note exists
rather than a shared module: the next person builds their own, and this is the part they must
not rediscover.

## Test Comparison Matrix

| Test Type | Count | Files | Speed | Dependencies | Purpose |
|-----------|-------|-------|-------|--------------|---------|
| **Unit** | 2,832 | 104 | Very Fast (1-10ms) | Mocked | Function validation |
| **Smoke** | ~50 | Inline | Fast (10-100ms) | Minimal | Module sanity check |
| **Integration** | 263 | 20 | Medium (100-1000ms) | Server + DB | End-to-end validation |
| **WebSocket** | 50 | Custom | Medium | WS server | WebSocket functionality |
| **E2E UI** | 328 | 30 | Slow (~17min total) | Server + Chromium | Visual + functional browser |
| **Interactive Proxy** | 12 | 1 | Slow (5-60s) | Server + Proxy + LLM | Interactive agent validation |

**Total**: ~3,535 tests

---

## Pre-Merge Test Checklist

**All 5 layers MUST pass before merging any branch to main.**

| Step | Suite | Command | Requirement |
|------|-------|---------|-------------|
| 1 | Unit Tests | `pytest src/tests/unit/ -v` | 100% pass |
| 2 | WebSocket Tests | `./src/scripts/run-websocket-smoke-tests.sh` | 100% pass |
| 3 | E2E UI Tests | `./src/scripts/run-e2e-ui-tests.sh --bg -v` | 100% pass |
| 4 | Visual Regression | `./src/scripts/run-e2e-ui-tests.sh --bg -v -k visual` | 100% pass |
| 5 | Integration Tests | `./src/tests/run-integration-tests.sh --bg -v` | 100% pass (FINAL GATE) |

```bash
# Complete pre-merge validation sequence
pytest src/tests/unit/ -v && \
./src/scripts/run-websocket-smoke-tests.sh && \
./src/scripts/run-e2e-ui-tests.sh --bg -v && \
./src/tests/run-integration-tests.sh --bg -v
```

**Note**: E2E UI and integration tests run in background (`--bg`) — monitor via log files. Wait for E2E completion before launching integration tests (the final gate). Both have PID-file overlap protection to prevent concurrent runs.

### Run All Tests (Sequential Pyramid)

```bash
# Run all 7 test tiers sequentially (continues on failure by default)
./src/scripts/run-all-tests.sh
```

---

## Testing Anti-Patterns

| Anti-Pattern | Why It's Prohibited | Use Instead |
|-------------|---------------------|-------------|
| Manual `curl` to `/api/push` + polling | Non-repeatable, no validation, no reporting | `LivePipelineTestBase` or `InteractiveSmokeTest` |
| Bespoke shell scripts with curl | Unmaintainable, no framework integration | Automated smoke test scripts |
| Copy-paste curl from API docs into tests | Fragile, no auth lifecycle management | Test base classes handle auth, submit, poll, validate |
| Running E2E/integration without `--bg` | Exceeds 10min Claude Code Bash timeout | Always use `--bg` flag |
| Overlapping test runs | PID conflicts, unreliable results | PID-file overlap protection prevents this |

**Acceptable curl usage**: API reference documentation, deployment health checks (`curl /health`), one-off debugging (never committed).

---

## Test Credentials

**CRITICAL**: Never hardcode test credentials. Always use environment variables.

```bash
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL="your@email.com"
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD="yourpassword"
```

All smoke tests, proxy tests, and pipeline tests use the `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` prefix to ensure test and proxy authenticate as the same user (same WebSocket channel).

**Reference**: See `src/tests/AUTH-TESTING-GUIDE.md` for credential patterns.

---

## When to Use Each Test Type

| Situation | Recommended Tier |
|-----------|-----------------|
| Testing a specific function or method | Unit |
| Verifying a module loads after changes | Smoke |
| Testing complete user workflows | Integration |
| Testing WebSocket connections/events | WebSocket |
| Testing UI interactions in browser | E2E UI |
| Verifying UI hasn't visually regressed | E2E UI (visual) |
| Testing agents with notification interactions | Interactive Proxy |
| Before merging to main | All 5 layers (pre-merge checklist) |

---

## Test Development Guidelines

### Writing New Unit Tests

1. Create test file in `src/tests/unit/test_<module>.py`
2. Use pytest fixtures for setup/teardown
3. Test one function per test
4. Include success and failure cases
5. Mock external dependencies
6. Use `tempfile.TemporaryDirectory()` for storage isolation

### Writing New Integration Tests

1. Add test to `src/tests/integration/`
2. Use fixtures from `conftest.py`
3. Test complete user flow
4. Verify database state
5. Clean up after test (automatic via fixtures)
6. Document test purpose in docstring

### Writing New E2E UI Tests

1. Add test to `src/tests/e2e_ui/`
2. Use Playwright page fixtures
3. Always run via `run-e2e-ui-tests.sh` (handles server config hot-swap)
4. For visual tests, use snapshot comparison pattern
5. Test against live server on port 7999

---

## Related Documentation

- **Integration Tests**: `src/tests/integration/README.md`
- **Interactive Proxy Tests**: [`src/docs/automated-interactive-testing.md`](../docs/automated-interactive-testing.md)
- **Smoke Tests**: [`src/tests/smoke/README.md`](smoke/README.md)
- **Auth Testing Guide**: `src/tests/AUTH-TESTING-GUIDE.md`
- **Project CLAUDE.md**: Development guidelines and testing section

---

**Last Updated**: April 2026 (Session db376295)

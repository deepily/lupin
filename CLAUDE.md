# Lupin development guide

> Rules only. Measurements and rulings behind a rule live in `src/docs/doctrine/`; they are not required reading.
> The text this file carried before the 2026-10-10 rewrite is kept, by its old heading, in
> `src/docs/doctrine/claude-md-receipts-archive.md` under "Moved out of CLAUDE.md on 2026-10-10".

## Standing rules

### Commands
- Run FastAPI server: `src/scripts/run-fastapi-lupin.sh` (port 7999)
- Regenerate API docs: `src/scripts/generate-api-docs.sh` (server on port 7999; `--offline` for saved JSON)
- Install cosa-voice MCP (global): `src/scripts/install-cosa-voice.sh` (user scope, all repos)
- New agentic service with voice I/O: `/lupin-new-claude-agent-sdk-voice-workflow`; canonical doc `src/workflow/agentic-voice-workflow.md`; reference agents `src/cosa/agents/deep_research/`, `podcast_generator/`
- Baseline and remediation: `/smoke-test-baseline`, `/smoke-test-remediation`; each command file holds its arguments

### CJ Flow
- Every queued job implements the `QueueableJob` protocol (`src/cosa/rest/queue_protocol.py`); pipeline todo → running → done/dead.
- `AgenticJobBase` jobs run in the agentic pool; `AgentBase` and `SolutionSnapshot` run inline on the consumer thread. Re-read the INI key `cj flow max concurrent agentic jobs` before relying on a pool size.
- `FifoQueue` is shared by pool workers and the consumer thread: `running_fifo_queue.py` removes a job with `self.delete_by_id_hash(job.id_hash)`, never `self.pop()`, because the head of the queue is not deterministic under pool-callback concurrency.
- ⚠️ `GET /api/queue/pool-status` describes the pool, not the venue. Do not derive idleness from it; use `cosa.rest.venue_idle` / `GET /api/busy` (§ Testing venues).

### Cost model
- Prefer bounded Claude Code (`ClaudeCodeJob`, `task_type=BOUNDED`, covered by the Max plan) over the direct Anthropic SDK (`ANTHROPIC_API_KEY_FIREWALLED`, billed per token) for LLM-driven agents that fit its tool surface.
- On bounded CC today: BFE (`src/cosa/agents/bug_fix_expediter/`), TFE (`src/cosa/agents/test_fix_expediter/`), podcast script generation (`src/cosa/agents/podcast_generator/`), presentation content generation (`src/cosa/agents/presentation_generator/`), Deep Research (`src/cosa/agents/deep_research/`).
- Never use the bare `ANTHROPIC_API_KEY`; it is reserved for the Claude Code CLI.
- The SDK's `cost_usd` telemetry on a bounded job is a notional figure: the Anthropic console balance does not move for it.
- Deferred and not ratified for migration: OpenAI call sites and the Runtime Argument Expeditor (see TODO.md).
- A migration is a cost-shift, not zero-cost. Say "covered by existing fixed cost", never "free".
- Do not migrate: calls above about 10 QPS, a latency budget under about 2 s, non-Anthropic models, token-by-token streaming.
- Detail: `src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md`.

### Scheduled jobs
The host is usually powered off from about 11 PM to 10 AM EDT, and a job scheduled then runs at the next boot. Re-derive the hours with `journalctl --list-boots --no-pager`, not `last -x reboot`, whose `wtmp` rotates.
To run a job later, submit through `/api/v2/submit` with the command `agent router go to claude code` and a top-level `scheduled_at` (ISO-8601 with offset). `scheduled_at` is top-level because it tells the queue *when* to run; it is not part of the command's argument contract. A job that lands while the host is off drains late, and `job_persistence.py` logs a `[CJ-CATCHUP-LATE]` line.

### Code style
- **Imports**: Group by stdlib, third-party, local
- **Naming**: snake_case for functions, PascalCase for classes, UPPER_SNAKE_CASE for constants
- **File Naming**:
  - Python files: Use underscores as separators (e.g., `example_implementation.py`)
  - All other files: Use dashes as separators (e.g., `websocket-design.md`, `lupin-app.ini`)
  - Date prefixes: Use YYYY.MM.DD format (e.g., `2025.06.03-websocket-design.md`)
- **Formatting**: 4 spaces indentation, spaces around operators, spaces inside brackets
- **Error handling**: Catch specific exceptions, include context in error messages
- **Logging**: Currently uses print() statements rather than a logging framework
- **Types**: Dynamic typing is used (no type annotations)
- **Documentation**: Add docstrings to new functions and classes; the eight rules are in `src/docs/docstring-standard.md`
- **XML formatting**: Use XML tags for structured responses in agent communication

### Configuration
- Config files: `src/conf/lupin-app.ini` and `src/conf/lupin-app-splainer.ini`
- Environment variables override config file settings
- Use `ConfigurationManager` to access config values

### Debugging
- Set `debug=True` and `verbose=True` parameters in class instantiations
- Use `du.print_banner()` from `utils.py` for formatted console messages

### Session start
- The first thing you do in a session is read the global Claude configuration file and follow its instructions.
- Read `history.md` and the implementation document named at its top; older context is in `history/YYYY-MM-history.md`.
- Do not read the sub-repo histories (`src/lupin-plugin-firefox/history.md`, `../lupin-mobile/history.md`). `src/cosa/history.md` is an ordinary in-tree doc and may be read.
- This repo's SHORT_PROJECT_PREFIX is [LUPIN].
- `src/cosa/` is a regular in-tree directory of this repository, not a separate repo or submodule. It keeps its own `README.md` and `CLAUDE.md`.

### Servers
- Assume a server is bound to port 7999; the user starts and stops it. Start another instance only for ephemeral use on port 8000.
- Before clicking Resume on a TFE/BFE stalled job, or before scheduling a live E2E run on `:8000`, run `src/scripts/preflight-test-container.sh`.
- Server lifecycle (when a change lands, when to bounce, which command): skill `server-lifecycle`.
- `uvicorn --reload` is **off by default on `:7999`** (opt in with `LUPIN_RELOAD`). **A `.py` change does not go live on its own; both servers need a bounce.** Anybody may bounce `:7999`, within reason, with `./src/scripts/bounce-dev-server.sh` (`--quiet` for a one-liner), which warns the fleet first and polls `/health`.
- **Database grants after a bounce**: `bounce-dev-server.sh` and `preflight-test-container.sh` run `src/scripts/lib/check-db-grants.sh`, which checks that the three database roles hold every grant in `cosa.utils.db_grants`. A red answer is a warning. `LUPIN_DB_GRANTS_REPAIR=on` makes the helper run `db_roles --grants-only --apply` once and check again. It stays off until the one-time apply has been run by hand.
- **`restart` ≠ `--force-recreate`**: mount specs and env resolve at container **CREATE**. Changed `docker-compose.yml`, a bind mount, or an env var? Use `docker compose up -d --force-recreate <svc>`; a restart reuses the old values and your change silently does not land.

### Git
- Nested repos are separate git repositories, managed in their own sessions: the Firefox plugin (`src/lupin-plugin-firefox/`) and the sibling mobile app (`../lupin-mobile/`, outside `src/`, so absent from Lupin's `git status`). Never run git commands in them from here. `/plan-session-end` filters their paths out of the commit.
- The Firefox plugin repo `lupin-plugin-firefox` is part of the larger project but must be managed separately and cannot be managed by Claude.

#### Committing — never attach a heredoc to the `git commit` line

Commit with `git commit -F <file> -- <paths>`. Write the message file first; a heredoc *there* is fine.

Never attach a heredoc or here-string to the `git commit` invocation itself — `-F /dev/stdin <<EOF`,
`-F - <<EOF`, `<<< 'body'`. The commit scope guard reads the tail after the `git commit` match to find
which paths you are committing; a `<<` in that tail makes it decline, print
`⚠️ Commit scope guard: NOT REVIEWED`, and let the commit through unexamined.

The rule is about attachment, not about heredocs. If you do see `NOT REVIEWED`, either re-run in the
reviewed shape or check the commit yourself with `git show --stat <sha>` — and say which you did.

### Testing venues

Every automated test runs on exactly one of two servers. Pick by rubric, never by habit.

#### :7999 (dev) — AI-discretionary

The AI may run these at any time without asking the user.

Eligible **iff all three**:
- No persistent-state mutation (no DB writes outliving the test, no writes outside `/tmp`, no real-work queue enqueues).
- Runtime ≤ 2 minutes end-to-end.
- No monopoly requirement.

Suites that qualify (unit tests, inline `quick_smoke_test()` blocks, `py_compile` and import checks, the WebSocket smoke runner, and the named read-only smoke files) are listed, with the reasoning for each, in `src/docs/doctrine/testing-venues.md` § "The `:7999` suite list".

#### :8000 (test) — monopolize mode, scheduled only

Submit via `POST /api/v2/submit` with the command `agent router go to test suite` (`src/scripts/submit-test-suite.py` wraps it), and only that way. `/api/test-suite/submit` is retired and answers 410. A refused submit (unknown suite name, malformed or contradictory `pytest_args`) is HTTP 200 with `status: "failed"` and the cause in `error`, so read `status`, not only the HTTP code. Never inject through ad-hoc curl, a direct
queue push, or in-process server instantiation — a side door collides with in-flight scheduled runs and
poisons both.

Eligible if **any** of: it mutates persistent state (DB rows, shared files, LLM API spend, enqueued jobs);
it runs over 2 minutes; it needs server monopoly.

Suites that qualify:
- `src/tests/smoke/test_proxy_integration.py` (any scenario — CRUD and expediter mutate state)
- `src/tests/run-integration-tests.sh` (final merge gate)
- `src/scripts/run-e2e-ui-tests.sh` (functional and visual)
- `src/tests/run-presentation-regression.sh` (all variants)

A verified-idle `:8000` is bounce-then-schedule self-authorized — the user is not a gate, and neither
budget approval nor an idle-slot ask is required. The only user gate is **killing a live in-flight job**.

**Verify idle with one command and read its exit code:**

```bash
PYTHONPATH=src python3 -m cosa.rest.venue_idle --port 8000 ; echo "exit=$?"
```

`0` idle · `1` busy · `2` unknown. It reads the unfiltered, unauthenticated `GET /api/busy` — run depth,
todo depth, shared-pool inflight, monopolize slot — and every lane must be empty.

**Unknown is not idle.** If only `todo_queue_size` is missing, that container predates the field and
cannot see waiting work; bounce it to pick up the code, not `--force-recreate`.

Do not verify idle from `pool-status` or the queue listings. `monopolize_id` only moves for a
monopolize-flagged job that has already started, so it names which job holds the slot and says nothing
about queued or inline work; `/api/get-queue/{q}` is user-filtered and `?user_filter=*` answers 403 for
this account, so a peer's queued job is not in your listing at all.

**Then place it**: empty queue → bounce, schedule, run now. Something already scheduled → still
self-authorized, but set `scheduled_at` after it; never jump an expected-next run. Something running →
queue behind it, no bounce.

#### The `src/tests/smoke/` caveat

The directory name is not a venue marker. Files living in `src/tests/smoke/` can still be destructive or long-running (e.g. `test_proxy_integration.py`). Route each file by the rubric above, not by folder.

#### When in doubt → :8000

:7999 is an optimization for truly fast, truly read-only work. If you cannot prove a test meets all three :7999 criteria, schedule it on :8000.

### 100% coverage mandate

**A Lupin-wide hard gate** ("Everything has to pass at 100%. Full stop."), covering `src/cosa` too.

**The rule**: **100% coverage — lines AND branches AND functions** on all Lupin code. Python via `pytest --cov` (`--cov-fail-under=100`); TypeScript via `c8 --100`.

- **Exceptions**: `# pragma: no cover` (Python) / `c8 ignore` (TS) only for genuinely-unreachable defensive branches, and only with a same-line comment giving the reason. "No time to test" is never valid — fix the test, not the gate.
- **In plan ACs**: write "100% lines/branches/functions" — never ≥90%/≥95%.
- **Excludes**: sub-repos `lupin-mobile`, `lupin-plugin-firefox`, and external-project bind-mounts.

### Testing

Three-tier strategy (unit → integration → E2E). Venue routing (`:7999` vs `:8000`) per § Testing venues; `:8000 (scheduled)` = submit via `POST /api/v2/submit` (command `agent router go to test suite`), self-authorized on a verified-idle server and placed behind any already-scheduled or running job. Counts, timings and per-suite notes are in `src/docs/doctrine/testing-venues.md`.

| Suite | Venue | Command | Rules that matter |
|---|---|---|---|
| Unit | :7999 | `pytest src/tests/unit/` | |
| TypeScript | :8000 (scheduled) | `./src/tests/run-typescript-tests.sh` | runs under c8 at 100% inside the memory-capped `jstest.slice` cgroup, so `test_types: ["all"]` is safe; an `RC=124` is a hang on leaked transports, not memory |
| Docker smoke | :7999 (host only) | `./src/tests/run-docker-smoke-gate.sh` | any skip, error or missing file is a failure; not offered inside a container |
| Smoke (inline) | :7999 | `python -m cosa.rest.<module>` | `quick_smoke_test()` blocks, non-destructive; `src/tests/smoke/` files are heterogeneous, route each by the § Testing venues rubric |
| WebSocket smoke | :7999 | `src/scripts/run-websocket-smoke-tests.sh` | connection, auth, events |
| Integration | :8000 (scheduled) | `./src/tests/run-integration-tests.sh --bg -v` | **final merge gate**; always `--bg` |
| E2E UI (Playwright) | :8000 (scheduled) | `./src/scripts/run-e2e-ui-tests.sh --bg -v`; one half: `--half a` / `--half b` | the merge gate runs two halves, `e2e_a` then `e2e_b`; a new test file must be in `src/tests/e2e_ui/partition/` (`test_e2e_halves_partition.py` fails on a file in neither half or both); `-k visual` for visual only, `--update-snapshots` to rebaseline (snapshots are version-controlled) |
| Interactive proxy | :8000 (scheduled) | `python src/tests/smoke/test_proxy_integration.py --group all --auto-proxy --no-confirm` | mutates state |
| Presentation regression | :8000 (scheduled) | `./src/tests/run-presentation-regression.sh --bg` | real LLM spend; `--include-opus` / `--all` variants |

**Before you ask for review**: run `src/tests/run-census-guards.sh` beside the tests of the files you changed. A census guard counts something across the whole tree, so new code can turn it red while none of its files changed. The set is chosen by file name (`test_every_*`, `*census*`, `*_pin*`, `*pins*`, `*pinned*`), so name a new census guard to match.

**`--bg` mandate**: integration, E2E UI, and presentation regression exceed the 10-min Bash timeout — always launch with `--bg` from Claude Code; monitor the matching `/tmp/*-latest.log`. PID-file overlap guards prevent concurrent runs.

### Working rules

Stated as rules. The measurements behind them are in `src/docs/doctrine/`; you do not need them to follow a rule.

#### Reporting a measurement

- Say what you measured and when. A bare figure ages without ever changing, and a reader cannot tell.
- Name the population before you trust a result. An empty answer from the wrong population looks exactly
  like an empty answer from the right one.
- Prove your instrument can find something. A negative result is worth nothing until you have watched the
  same search return a positive one.
- A census carries a timestamp whether you write one or not. "I looked and found one" and "there can only
  be one" print the same in a summary, and only the second closes a question. Say which you mean.
- Read your conjunctions one at a time. For every *because*, *so*, *which means*, ask whether you measured
  the link or only the two ends. If only the ends, state them as two facts — the reader can draw the arrow.
- Name a gap rather than bridging it. An inferred bridge cannot be audited; a named gap is searchable, and
  whoever holds the other half can close it.
- Never assert a mental state from an artifact. An artifact shows you what was produced, never why.
- Leave an unmeasured lead out of anything durable. A caveat protects the reader of the conversation; only
  omission protects the reader of the artifact. A *measured* don't-know stays — that is a finding.
- A wrong number gets re-derived by the next reader. A wrong mechanism sends them into innocent code, so
  the explanation earns the deeper check.
- Say which you corrected. "4 → 3" reads as a population shrinking even when the floor got firmer.
- Report a partial re-derivation side by side, never as one verdict. Half-refreshed reads as refreshed.

#### Pointing at something

- Name the content, not the coordinate. A line number, a `stash@{N}`, a PID, "the file I edited earlier" —
  all go stale between your reading and someone else's acting, and in a fleet someone always edits.
- Cite a heading or a symbol name over a line number; a heading survives an edit above it.
- When you must point at a position, make the pointer self-checking: give the anchor text, say it must
  match exactly once, and say what to do when it matches zero or twice — come back, never guess.
- Say which space a hash indexes. Row id, content sha, git commit — same shape, three different lookups.
- Mark a closed row as closed when you cite it, or the reader inherits a constraint that no longer exists.
- Identify a process by a property it carries — its cwd, its `comm` — never by a handle you captured when
  it was true. The OS recycles PIDs.
- Send a to-be-pasted artifact bare, one per message. Text between sessions is condensed in transit, and a
  paragraph explaining the paste is what absorbs it.

#### Searching

- A hit is not a use. A name travels through comments, docstrings, route strings and other tests' prose;
  the code that uses it appears once. Open the matches and read what they do.
- Use fixed-string searches. A character class or an alternation quietly under-reports.
- A git pathspec is not shell globstar: `src/docs/**/*.md` requires an intervening directory and silently
  drops every file sitting directly in `src/docs/`. Count the population first — `git ls-files <pathspec> |
  wc -l` — and sanity-check it against what you believe is there.
- `git grep` cannot see untracked or ignored files. Say so when reporting a zero.
- Read the program when the question is what the program does. A corpus of its outputs cannot tell a value
  that was frozen from one regenerated to the same bytes. A corpus is right for *how many* and *how
  widespread*; it can never answer *why*.
- Ask what population your command walks. `src/cosa/.venv` is a vendored virtualenv inside the source tree
  and is about 92% of any disk-derived sweep, so exclude `.venv`, `node_modules` and `site-packages`, or
  derive the population from git.

#### Tests

- Coverage tells you a line ran. It never tells you the test could have noticed it running wrong.
- A fake that ignores its input answers the same however the code behaves, and every assertion written over
  it inherits that. Replace the code under test with a constant; if the fixture still yields the same data,
  the suite is measuring the fixture.
- Read the data before the assertions. If two quantities can be swapped without changing the expected
  output, the test asserts their sum, not their identity — whatever its name says.
- Capture at least one fixture from the real producer through the real reader. A hand-written fixture is
  better-formed than reality, exactly where a parser depends on the mess.
- An assertion satisfiable by more than one path cannot tell you which one ran. Name the path in the
  assertion; when you find several sufficient causes, go and eliminate one rather than reaching for
  sharper words.
- Trace both sides of a comparison back to their origin. If they meet, it is a tautology wearing an
  assertion's clothes — pin one side to a literal, a committed fixture, or a count from `git ls-files`.
- Two sides that derive one value by different routes are coinciding, not agreeing. Ask what would make
  them differ and whether it has ever happened. You cannot fix one side of a coincidence.
- Enter at the layer the incident entered at. A real component exercised at the wrong altitude is still
  the wrong measurement, and it looks like a green end-to-end test.
- Drive the assembled app, not only the class. A component can be complete, correct, fully covered and
  never mounted, and every test that builds the component stays green.
- Enumerate the surface, not the traffic. What got exercised is a history of somebody's clicking. State
  how many siblings exist and how many are watched; a guard that cannot state its denominator is telling
  you about its corpus.
- Assert the loop found something before looping. A loop over nothing passes every assertion in it.
- Unguarded is a third state: the code is right and no test could see it break. Prove which state you are
  in by deleting the guard and watching a named passing test redden. A break list proves unwatched, never
  absent.
- A projection of a gate must ask the gate, not restate its rule. Two pieces of code deciding one rule
  agree until they do not, and the restatement is usually off by one to begin with.

#### Coverage

- Never scope a run whose output you will read as a list. `--cov=<path>` does not narrow the report, it
  narrows what was ever measured, and absence from a scoped report means never-measured, not zero. Scoping
  is fine for one file's number — per-file counts are scope-invariant.
- `--cov=` needs a target that is both importable *and* actually imported by that run. A `.py` path always
  measures zero. Three warnings fire and the run still exits 0, so read the table and grep for
  `module-not-imported`.
- Coverage goes stale from a merge, not a commit. Unmerged work moves nobody's coverage but its author's,
  so state the sha with the list and report "done" and "landed" as separate columns.

#### Mutation testing

- Take a green baseline first and record the failing set. The kill signal is the failing set: a named test
  that was passing now fails. Exit codes 4 and 5 mean pytest could not run the node, and on a branch with a
  deliberate red, `rc == 1` scores every mutant as killed.
- Compare the assertion that fired, not just the test id. An assertion placed behind a currently-failing
  one is carried, not exercised — put a new guard in its own test.
- Assert the mutation applied: the anchor matched exactly once, the on-disk sha changed. End with a restore
  control you actually read.
- Isolate every arm. Rebuilding the sandbox per arm is strongest; `src/scripts/purge-pycache.sh` is the
  practical choice in a working tree. A raw `find … __pycache__ -delete` re-opens the defect.
- A surviving mutant has four explanations — a weak test, a broken harness, an equivalent mutant, or a
  fixture that cannot discriminate. Only the first earns a new test, and the fourth is invisible to
  re-reading the test body.
- Put a ceiling on a kill count as well as a floor. A break aimed at one line should redden the tests that
  reach it; near-total kill is a syntax error until proven otherwise. Compare the run count to baseline,
  not just the failures.
- "I repaired a fixture" is not "I proved the repair discriminates". Two arms off one mutated sha: the old
  fixture survives, the new one is killed by the named test. Neither arm alone counts.
- A clean pass samples the mutation space; it does not survey it. Exchange shas with another harness to
  catch a disagreement, never to manufacture a confirmation.
- Never mutate in a peer's live worktree, or in the shared main tree. Check the sha out into a detached
  worktree of your own — a `cp` restore from your own backup carries the same race as `git checkout`.

#### Bytecode

The tree uses checked-hash invalidation. Without it CPython validates a `.pyc` on the source's
whole-second mtime plus size, so a same-size edit inside one second runs the previous arm's bytecode.

- `src/scripts/purge-pycache.sh` purges **and** reconverts, and refuses before deleting if it cannot
  reconvert. It takes only `--dry-run`. It resolves its tree from its own location, so run the copy that
  lives in the tree you mean; `LUPIN_ROOT` is inert for it, but `PYTHON` is not.
- `src/scripts/migrate-pyc-to-checked-hash.sh --verify` is the read-only report, and it scans
  `$LUPIN_ROOT/src` — not where you are standing. Read its `scanned roots:` line, not its checkmark. Pin
  both `LUPIN_ROOT` and `PYTHON`, since `PYTHON` derives from the root and many worktrees have no `.venv`.
- Its exits: 0 clean, 1 timestamp pycs present (the real finding), 2 it never ran. Only stderr separates
  2's causes.
- A `0` from a tree that has never been used is vacuous, not clean. Use a new worktree once,
  purge-and-reconvert, then verify.
- `-f` is the whole migration — without it `compileall` converts nothing and reports success.
- `PYTHONDONTWRITEBYTECODE` suppresses writing, never trusting. Editing a test file inside a test still
  needs `tests.helpers.pyc_freshness`.

#### Worktrees

- Every worktree goes under `.claude/worktrees/`, never `../`. A spawned seat's tree lands there on its own
  (`seat-<name>`, locked while the seat lives); a hand-made one is
  `git worktree add .claude/worktrees/<persona>-<task>`. That folder is gitignored and swept by the arbiter
  janitor once a tree is idle. Anything next to the repo is swept by nobody. The janitor moves a tree's ignored files that are not build artifacts, the tree's own run
  output (`tmp/`, `io/test-suite/`, `io/swe-team/`, `io/claude_code_hooks/`, `src/docs/index/`, `.claude-session.md`) or mirrored
  mementos into `io/worktree-evacuated/<day>-<tree>-<stamp>/` in the main tree and then removes the tree;
  an unmerged branch moves to `refs/archive/<day>/<name>` (restore with
  `git update-ref refs/heads/<name> <sha>`). Both are deleted 14 days later, so keep data in git or
  somewhere durable. A reap by any other door (a manager's dismiss, a seat's own teardown) still refuses
  such a tree and leaves it for the janitor.
- Pin all three, every time. `LUPIN_ROOT` is inherited from your shell and silently keeps naming the main
  repo:

  ```bash
  cd <worktree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python -m pytest src/tests/unit/ -q
  ```

- `LUPIN_ROOT` decides which tree paths resolve against; `PYTHONPATH` decides which tree modules are
  imported from. Pin one and not the other and your modules come from two checkouts — a tree that exists
  nowhere on disk, pointing toward a false green.
- A worktree is git-identical to the main tree and environment-identical to nothing. Subtract the
  artifacts; do not chase them. `ls -L` first — the file is the coordinate and the count derives from it,
  and every borrowed artifact is a symlink, so a bare `ls -l` reports the link's size.

  | missing | unit-tier failures |
  |---|---|
  | `src/scripts/cloud-run.env` | 9 absent, 0 present |
  | `.venv` | 33 |
  | terraform provider cache | 1 |
  | `LUPIN_ROOT` unpinned | 1 |

- Provisioning runs in the Python spawn path only, so a hand-typed `git worktree add` gets nothing — run
  `src/scripts/link-worktree-artifacts.sh` and `src/scripts/link-worktree-venv.sh` yourself there. The
  first does not link `.venv`; the second does.
- Never symlink anything under `src/conf/keys/**` or the repo-root `.env` into a worktree. A venv is a
  build artifact; a key is a secret, and a worktree gets deleted, copied and shared.
- A failure that passes in the main tree has two explanations — a worktree artifact, or a fix you do not
  have yet. Name the commit to tell them apart:
  `git log --oneline <your-sha>..<main-HEAD> -- <the failing test's path>`.
- A red count or a coverage list about "the tree" must be run at the main line. Your own branch is blind to
  exactly the defects its unmerged work repairs.
- While a tier is running, that worktree is read-only — whatever your reason for touching it. A mutation
  arm feels like measuring, not editing, and the run cannot tell the difference.
- The tier stamp's `run-span=unmoved` compares two HEAD shas; `tracked-dirty` is one sample at the end with
  untracked rows stripped. Neither certifies that the run measured the tree you think it did. Name a run by
  what it measured, not by the sha you asked for.
  `bundle-span=` covers what both are blind to: it hashes the CONTENT of every
  served `.js` and `manifest.json` under `src/lupin_app/static/dist/` (gitignored; `.map` files are not served) at start and end, names the root hashed
  (`bundle=<hash>@seat` or `@main`), leaves out each manifest's `built` time stamp (two builds of one source differ in it alone), and a rebuild that changes what a page loads inside the run reads `bundle-span=<a>..<b> ⚠️ BUNDLE
  REBUILT MID-RUN` beside `run-span`. `@seat` and `@main` are different directories; `:8000` serves main's.

#### Reading a result

- A clean exit is not evidence the work happened. A tool that no-ops and a tool that succeeds print the
  same status, so read the tool's own account: does the coverage table list the file, does the verify name
  your tree, does the purge report a count matching what you planted.
- A tool that cannot finish should refuse the whole operation and name what it did not do, rather than
  half-finishing and returning a status the caller reads as success.
- In a two-arm comparison, give each arm its own freshly built state. An arm that no-ops because the
  previous one consumed its input is indistinguishable from an arm that failed.
- `--bg` makes the exit code meaningless by design — the launcher exits 0 before pytest exists. Read the
  log's summary line and its `FAILED` lines. (`run-presentation-regression.sh` is the exception: `--bg` is
  a no-op there and its code is real.)
- Capture an exit code immediately and re-raise it at the end. A bash command's status is its last
  command's, so the `echo "EXIT=$?"` you added to surface the code is what replaces it:
  `pytest … > /tmp/tier.log 2>&1; rc=$?; tail -20 /tmp/tier.log; exit $rc`.
- A multi-file pytest invocation reports a union. Quote a per-file result from a per-file run, or quote the
  invocation with the number.
- Before offering a mechanism for someone else's number, ask which test produced it and whether your
  mechanism can reach that test. A mechanism true of the file is not thereby true of the assertion.
- Check how old the process you are testing through is. A stdio MCP server is a subprocess started when
  your seat started, so a fix landing afterwards does not reach it — and the stale subprocess reproduces
  an already-fixed defect on demand, forever. No peer can catch this for you.

#### Writing a rule or a guard

- Write the predicate the enumeration is approximating. Any separator run, not four separators; not a word
  character, not eleven characters; the repos the config registers, not the four you remembered. When the
  fix for an enumeration defect is itself an enumeration, you have moved the defect.
- A rule that depends on remembering is not installed. Prefer a tool that refuses.
- Say what a check matches on, and whether your predicate is the whole key or a prefix of it. A check and
  the thing it checks can agree on the field and disagree on the key, and both look correct.
- Sweep for two populations when you retire a name: the passages that *use* it, and the passages that
  *vouch for* it. A wrong instruction gets caught the first time someone follows it; a wrong reassurance
  disarms the reader who would have caught it.
- A row body is the plan as of its writing, not a status. Re-measure before you act on a figure in one.

#### Owning the work

- A red you accept is a row you owe. A finding filed as a state, with no owner, reads as closed —
  acceptance without an owner is deferral wearing acceptance's clothes.
- Wait for the worker to say the memento is on disk, with its path and session id, before calling
  `dismiss_sessions`. A reap reports `prior_holder_present` and proceeds, and a stale file in the slot
  looks exactly like a fresh one.
- A memento has two slots and the two doors read different ones: `self_respin` reads the root slot
  (`.claude-memento-<persona>.md`), a manager's reap reads `io/`. Name the slot when you write:
  `$PLANNING_IS_PROMPTING_ROOT/workflow/scripts/memento_io.py write --slot root|io`. Two records for
  one session is the normal steady state, and the path prefix is not optional — that script lives in
  planning-is-prompting, so a lupin seat handed the bare name cannot run it.
- The root slot resolves to the seat's own tree (`find_seat_root`); the io slot and the mirror stay keyed
  on the repo (`find_repo_root`). The repo-keyed mirror is what keeps a record in a prunable worktree
  durable, so never make the mirror follow the seat for symmetry. When you move where a record lives,
  also move every check that asks about its location, such as `check-ignore` and `ensure_gitignored`.
- A spawn brief is the one document a seat cannot check on arrival, so the obligation is the writer's.
  Give the population a claim was measured on, and mark inherited claims as inherited.
- Declare a hold with the verb, never by hand-writing JSON:
  `python3 -m lupin_cli.claude_code.hooks.lib.heartbeat_hold_io write --session-id <id> …`. A hand-written
  hold lands in the repo root where no reader looks, so the session parks invisibly.

## R&D read rule

Do not read a document under `src/rnd/` or `src/cosa/rnd/` unless it is on the active list: a plan whose `authorized_by:` names a live ticket, a decision record under `src/docs/decisions/`, or a capability page. Every other R&D document is human history: read it only when a person directs you to (for example in a post-game), and never as a source for what the code does now.

The class of each document is in `src/docs/rnd-ledger.tsv` (columns path, class, reason, date, sha; classes in force, superseded, history, new). A document added after the ledger's sha has no row and counts as `new`, that is in force, until the next sweep. `history/`, `todo-history/` and `src/cosa/history/` follow the same rule.

This rule is advisory: nothing blocks the read until archived documents move to a folder that `permissions.deny` can name.

## Where to read more

One row per topic; every path below exists (checked by `src/tests/unit/test_claude_md_pointer_table_targets_exist.py`).

| Topic | Read | When |
|---|---|---|
| Job queue (CJ Flow), pool, sweeper, key files | `src/docs/wiki/capabilities/cj-flow-queue.md` | before touching `src/cosa/rest/*fifo_queue.py` or the consumer |
| Job contract, job types, packaging a new job | `src/docs/wiki/capabilities/agentic-job-contract.md` | adding or changing an agentic job |
| Bounded Claude Code jobs and which agents use them | `src/docs/wiki/capabilities/bounded-claude-code-jobs.md` | choosing how an agent calls a model |
| Cost model: bounded CC against the firewalled SDK | `src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md` | designing or migrating an LLM-driven agent |
| Scheduling test runs and monopolize mode | `src/docs/wiki/capabilities/scheduled-test-suite.md` | scheduling any `:8000` run |
| Server lifecycle, bouncing, compose drift | `src/docs/wiki/capabilities/dev-server-lifecycle.md` | a change must reach a running server |
| Database sessions, roles and grants | `src/docs/wiki/capabilities/db-session-and-schema.md` | after a bounce, or on a grants warning |
| Test database login files and secrets | `src/docs/db-login-files-install.md` | provisioning a new host |
| Configuration and secrets | `src/docs/wiki/capabilities/configuration.md` | adding or reading an INI key |
| WebSocket architecture and events | `src/docs/websocket-architecture.md`, `src/docs/wiki/capabilities/websocket-events.md` | working on a WebSocket path |
| WebSocket troubleshooting and settings | `src/docs/websocket-troubleshooting.md`, `src/docs/websocket-configuration.md` | a socket does not connect or receive events |
| WebSocket auth and transport in the web client | `src/docs/wiki/capabilities/web-client-transport-and-auth.md` | the client cannot authenticate |
| Notification API | `src/docs/notification-api.md` | emitting or routing a notification |
| Decision proxy administration | `src/docs/proxy-admin-guide.md` | trust dashboard, ratification |
| Interactive proxy testing (auto-answer) | `src/docs/automated-interactive-testing.md` | running the interactive proxy suite |
| Voice and MCP onboarding | `src/docs/cosa-voice-onboarding.md` | a seat has no voice or MCP tools |
| Agentic voice workflow | `src/workflow/agentic-voice-workflow.md` | building a new voice-I/O job |
| Session spawn, reap and re-spin | `src/docs/wiki/capabilities/mcp-session-spawn-and-reap.md` | spawning, dismissing or re-spinning a seat |
| Heartbeat, holds and the arbiter | `src/docs/fleet-liveness-and-task-store-architecture.md`, `src/docs/wiki/capabilities/cc-hooks-heartbeat.md` | before touching the liveness path or declaring a hold |
| Worktrees | `src/docs/wiki/capabilities/worktree-lifecycle.md`, `src/docs/doctrine/worktree-tiers.md` | creating, linking or reaping a worktree |
| Test venues, suite lists and timings | `src/docs/doctrine/testing-venues.md` | choosing `:7999` or `:8000` for a named file |
| Coverage and mutation testing | `src/docs/doctrine/coverage-and-mutation.md` | reading or producing a mutation run |
| Docstring rules | `src/docs/docstring-standard.md` | writing a docstring |
| Doc viewer URLs, scopes, upload | `src/docs/wiki/capabilities/doc-viewer.md` | emitting a link or adding a scope |
| Everything this file used to say | `src/docs/doctrine/claude-md-receipts-archive.md` | tracing where a rule came from |
| Index of all documentation | `src/docs/README.md` | looking for a page |

## PR MERGE REQUIREMENTS

<!-- merge-pyramid-suites: typecheck stylelint doclint unit cosa coverage typescript smoke docker_smoke websocket integration e2e_a e2e_b -->
All must pass before merging to main, in this order: typecheck → stylelint → doclint → unit → cosa → coverage → typescript →
smoke → docker_smoke → serial bridge guard → websocket smoke → e2e UI and visual regression, as two halves e2e_a then
e2e_b → integration, which is the final gate. Each requires 100% pass. Venues and commands are in § TESTING above.

**typecheck runs FIRST because it is the cheapest gate** — the three tsc projects, about 3s of static
analysis against the roughly 25 minute TypeScript tier. It is a blocking gate so a type-red branch fails before any slow tier runs. ⚠️ Its summary counts PROJECTS, not
tests: `Failed: 1` means one tsconfig project is red, which may be one type error or four hundred.

**stylelint runs SECOND, for the same reason** — every `git ls-files '*.css'` file, about 1.5s. It is a blocking gate so style errors cannot pile up as "pre-existing" with nothing to stop them. ⚠️ Its summary counts FILES: `Failed: 1` is one red .css file,
and the error count is printed on its own line. A waiver needs a same-line reason
(`stylelint-disable-next-line <rule> -- <why>`); the config refuses one without. Tracked .html inline
`<style>` blocks are NOT covered — that needs postcss-html, which is not installed.

**doclint runs third, for the same reason** — the docstrings of every swept-scope Python file, about 5s.
It is a blocking gate so documentation lint findings cannot come back into files the sweep cleaned. Its
summary counts files: `Failed: 1` is one file with a finding, and `Errors:` is the number of findings.
The swept scope is every tracked `.py` file the documentation standard covers, except the held
`src/lupin_mcp/`; `src/cosa/repo/doc_lint/swept_scope.py` decides it. Exit 2 or 3 means the gate could not check, which is
not a pass. `src/scripts/pre-push-chain.sh` runs the same gate on the tip of a pushed ref.

> The heading above is capitalised and the HTML comment above is machine-read; neither is styling.
> `test_bridge_dir_guard.py` looks for the exact string `## PR MERGE REQUIREMENTS`, and
> `test_typescript_suite_gate.py` parses the `merge-pyramid-suites` marker and compares its set to
> `ALL_SUITE_COMPONENTS` in `src/cosa/agents/test_suite/job.py`, then checks the paragraph beneath it
> names every one. Lowercasing the heading or dropping the marker reddens the unit tier. The marker is a SET, not a sequence: the shell array
> runs integration before e2e while the documented pyramid holds integration back as the final gate,
> and that ordering difference is deliberate.

| # | gate | venue |
|---|---|---|
| 1 | **typecheck — `src/tests/run-typecheck-gate.sh`** — ~3s, fails a type-red branch first | :7999 |
| 2 | **stylelint — `src/tests/run-stylelint-gate.sh`** — ~1.5s, every tracked .css file | :7999 |
| 3 | **doclint — `src/tests/run-doclint-gate.sh`** — ~5s, the docstrings of every swept-scope .py file | :7999 |
| 4 | unit — `pytest src/tests/unit/` | :7999 |
| 5 | cosa — `src/tests/run-cosa-tests.sh` | :7999 |
| 6 | coverage — `src/tests/run-coverage-gate.sh` | :7999 |
| 7 | typescript — `src/tests/run-typescript-tests.sh` | :8000 scheduled |
| 8 | smoke | :7999 |
| 9 | docker_smoke — `src/tests/run-docker-smoke-gate.sh` — the three docker smoke files on the host, a skip is a failure | :7999, host only |
| 10 | serial bridge guard — `src/scripts/run-serial-bridge-guard.sh` | :7999 |
| 11 | websocket smoke | :7999 |
| 12 | E2E UI + visual regression, half A — `e2e_a`, `src/scripts/run-e2e-ui-tests-half-a.sh` | :8000 scheduled |
| 13 | E2E UI + visual regression, half B — `e2e_b`, `src/scripts/run-e2e-ui-tests-half-b.sh` | :8000 scheduled |
| 14 | **integration — the final gate** | :8000 scheduled |

This table's numbering and membership are guarded by
`test_claude_md_numbered_gate_table_carries_every_suite`: rows run 1..n, every suite in
`ALL_SUITE_COMPONENTS` appears in a row, and the count is the suites plus the serial bridge guard.
A new suite therefore needs a row here as well as a marker entry.

The test container does not offer the unit suite (row 2f18ad99) or `docker_smoke`: a request naming either is refused with `status: failed` and the cause in `error`, and `all` there runs the pyramid without them and says `unit: not run here, host tier` and the same for `docker_smoke`. The coverage gate then answers exit 2, because the data file holds no unit tier. Unit runs on the host, as row 4 says, and `docker_smoke` as row 9 says: inside a container the docker files skip, so the smoke step cannot vouch for them.

The coverage gate re-runs nothing: the unit and cosa tiers append to one isolated data file, and it renders
that, checks `fail_under`, and checks the frame still measures every file it claims.

Wait for E2E to finish before launching the integration gate. What serialises them is monopolize mode on
`:8000`, not the PID files: `/tmp/e2e-ui-tests.pid` and `/tmp/integration-tests.pid` each stop only their
own suite.
Integration is last because it exercises complete user workflows across API, DB and auth on a real server.

**Reading the serial bridge guard.** It is the whole-directory contact check the concurrent unit run
deselects, because a live peer's bridge write would false-accuse it. Do not wait for a quiescent box —
there is no such state, and the seat running the guard writes its own bridge while it executes. Read a red
this way instead: re-run and compare the **named file** — the same filename every run means real contact, a
different file or none means peer noise. Then read that file's `session_id` / `cc_pid` and check
`ls /proc/<cc_pid>`; if it belongs to a live seat that is not you, it is noise. One green is also one
sample: the discriminator is determinism, not the colour.

**Test counts move.** Re-derive them rather than quoting one; tests are added between any two readings.

**On failure**: do not merge. Fix the failing tests, then re-run the full suite. A genuinely-flaky failure
that is not your code gets documented plus a separate fix — never a merge bypass.

### 🔴 THE COVERAGE GATE HAS SIX EXIT CODES AND ONLY ONE OF THEM MEANS "COVERAGE IS TOO LOW"

**A code is a contract and a message drifts**, so the gate answers with distinct exit codes, and
`run-all-tests.sh` flattens all six to `coverage FAILED` in its summary.

| exit | meaning | the right response |
|---|---|---|
| **0** | measured, at or above the floor | — |
| **1** | **floor or frame BREACH** | 🔴 the only one that means write more tests |
| **2** | **INCONCLUSIVE** — a tier did not run, denominator short | no number is owed; do not quote one |
| **3** | no interpreter beside the resolved pytest | fix the environment |
| **4** | **REFUSED** — the tree MOVED while the run was measuring it | the number is *unfalsifiable*, not wrong. Re-run on a still tree |
| **6** | refused/contended — a peer tier held the box | wait, then re-run |

⇒ **2, 3, 4 and 6 all mean "no trustworthy number was produced"**, which wants a different
action from "coverage is too low". Reading one of them as a breach sends someone to write
tests for a run that never measured anything.

🔴 **EXIT 4 IS ALSO PYTEST'S `EXIT_USAGE_ERROR`, AND UNDER `--run-tiers` IT IS MISDIAGNOSED.**
`TestSuiteJob` calls `diagnose( exit_code, stdout )` with no gate on suite type, and
`pytest_collection_diagnosis.py` defines `4` as *conftest failed to import*. Two real exit-4 runs gave:

| mode | `conftest` in output | `diagnose( 4, … )` |
|---|---|---|
| pyramid (no tier stdout) | 0 | `None` — safe |
| **`--run-tiers`** | **6** | 🔴 **"unrecognised import-time failure"** |
| its last-400-line **tail** | 2 | 🔴 also misdiagnosed — tailing does not save you |
| positive control (real conftest ImportError) | — | diagnosed correctly |

⇒ **A tree-moved REFUSAL is reported, confidently, as an import failure**, and the reader is
sent hunting a conftest error that does not exist while the real cause — someone edited the
tree mid-run — goes unreported. The protection was never the code; it was
`"conftest" in output.lower()` happening to be false, and the tiers put that word in the
stream themselves. **A message match standing in for a code contract.**

Pyramid mode is safe only because it carries no tier stdout; `--run-tiers`, the mode people actually run, is the broken one.

### Test credentials

Any smoke test hitting authenticated endpoints, any integration test that logs in, and any protocol
verification test needs these. Test and proxy must authenticate as the same user, or they land on
different WebSocket channels and the run fails with "Operation cancelled".

```bash
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL="your@email.com"
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD="yourpassword"
```

```python
email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

if not email or not password:
    raise ValueError( "Set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
```

Patterns: `src/tests/AUTH-TESTING-GUIDE.md`. For pipeline testing use the automated smoke tests, never curl.

## Documentation touchpoints

When modifying code in these areas, update the corresponding documentation:

| Code Area Changed | Update These Docs |
|-------------------|-------------------|
| `routers/*.py` endpoint decorators | `/docs` auto-updates; run `src/scripts/generate-api-docs.sh` to update `src/docs/fastapi/` |
| `websocket_manager.py` | `src/docs/websocket-architecture.md` |
| `routers/websocket.py` | `src/docs/websocket-events.md`, `websocket-architecture.md` |
| `routers/notifications.py` architecture | `src/docs/notification-api.md` |
| `lupin-app.ini` WebSocket keys | `src/docs/websocket-configuration.md` |
| `lupin-app.ini` `websocket available events` | `src/docs/websocket-events.md`, `websocket-configuration.md` |
| New router added | `src/docs/rest-api-reference.md` quick-reference table |
| Auth services (`jwt_service`, `user_service`, etc.) | `src/docs/auth/architecture-overview.md` |
| Decision proxy / trust logic | `src/docs/proxy-admin-guide.md` |
| Frontend page routes | `src/docs/rest-api-reference.md` (Pages section) |
| `src/cosa/agents/bug_fix_expediter/` | `src/docs/agents/bug-fix-expediter-guide.md` |
| `src/cosa/agents/test_fix_expediter/` | `src/docs/agents/test-fix-expediter-guide.md` |
| `src/cosa/agents/shared/` (PlanWriter, GitStrategist, FixExecutor) | `src/docs/agents/shared-fix-primitives-reference.md` |
| `src/cosa/agents/test_suite/` | `src/docs/agents/test-suite-scheduling-guide.md` |
| `src/cosa/rest/test_suite_completion_watchdog.py` | `src/docs/agents/test-fix-expediter-guide.md` |
| `src/lupin_arbiter_app/*` import graph (any NEW third-party import) | **Run `src/scripts/check-arbiter-venv.py` in the arbiter venv and add the package to `src/scripts/requirements-arbiter.txt`.** The standalone `:8001` arbiter runs on a deliberately LIGHT host venv, so an import the venv lacks kills a worker THREAD while the process stays `active (running)` and `/health` returns 200. |
| A feature gated by an INI flag that imports a heavy/optional module | Read the flag **before** the import (pattern: `fleet_arbiter_loop.make_follow_through_watcher_factory`). A disabled feature must not impose its dependencies. |
| `lupin-app.ini` `bug fix expediter *` keys | `src/docs/agents/bug-fix-expediter-guide.md` INI Reference |
| `lupin-app.ini` `test fix expediter *` keys | `src/docs/agents/test-fix-expediter-guide.md` INI Reference |
| BFE/TFE endpoint rows | `src/docs/rest-api-reference.md` sections 17/17a/17b |
| `routers/voice_persona.py` + `voice_persona_helpers.py` | `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md` (architecture, allocation flow, /clear preservation, conversation-mode orthogonality) |
| `lupin-app.ini` `cc session voice persona *` keys | Same design doc, § 3 (Voice Pool) for the base pool. The Sam-overflow keys (`cc session voice persona sam icon/color/profile/display name`) and `stale threshold seconds` configure the overflow persona and the stale-bridge cutoff |
| `lupin_cli/claude_code/hooks/lib/session_bridge.py` `prune_dead_persona_bridges` + `find_active_voice_persona_sessions` TTL guard | The same design doc; the host-side prune runs at SessionStart, a bridge file's mtime TTL decides staleness, and "Sam" is the overflow persona allocated when the base pool is full |
| New LLM-driven agent OR migration of an existing agent between bounded-CC and firewalled-SDK paths | `src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md`, auto-memory `feedback_prefer_bounded_cc_over_anthropic_sdk.md`, and this file's § Cost model if its guardrails or migrated list change |
| `src/scripts/hook-link-tick.sh`, `src/cosa/utils/hook_link_tick.py`, or `pfv_git_hook_status` in `preflight-vm-lib.sh` | The timed check that the commit and push hooks are still links to the shipped scripts. A person installs it with `src/scripts/hook-link-tick.sh --print-install` (a Claude seat installs nothing). It stays silent when clean, never repairs a link, and exits 0 clean, 1 could not look, 2 delivered, 3 a due channel failed, 4 unchanged inside the quiet window, 5 delivery switched off. Delivery is recorded per channel. Keep the case arms of the git hook check in `preflight-vm.sh` in step with the state words. |
| `src/cosa/rest/routers/_scope_registry.py` + `docs_files.py` + `io_files.py` + `lupin-app.ini` `external repo *` keys + `docker-compose.yml` bind-mounts | Update the `docker-compose.yml` mounts and this file's § Doc viewer scope together. Adding a new external scope requires the four-step checklist in auto-memory `feedback_multi_repo_doc_viewer.md`. |

**Documentation index**: `src/docs/README.md` — lists all docs with verification dates.

**Fleet liveness + unified task-store architecture (top-to-bottom)**: `src/docs/fleet-liveness-and-task-store-architecture.md` — the canonical reference for the one-store/three-readers design (Stop-hook self-poke · `:8001` arbiter · human UI card), the heartbeat seam + `heartbeat.owed_source_from_store` cutover flag + fail-safe, the arbiter detectors (staleness 2700s / tap-ACK 600s / whole-fleet-stall 1800s) + how to bounce it (`systemctl --user restart lupin-arbiter-app.service`), the manager/worker spawn→worktree→review→merge-held→push lifecycle, and the migration drain. Read this before touching the liveness path, the task store, or the arbiter.

**Declaring a hold (parking a session) — use the VERB, never hand-write the JSON**: to park a session with a hold, run the `heartbeat_hold_io.py` **write** verb — it records the hold AND verify-reads it back so the hook will actually honor it. **Never hand-write a `.heartbeat-hold-*.json` file** (Write tool or `>`): a hand-written hold lands in the **repo root**, where no reader looks — the arbiter and the Stop hook both resolve holds under `fleet_data_root()` — so the session parks **invisibly** and the poke keeps coming. The arbiter's sweep flags a misplaced hold (`hold_is_misplaced`, the `misplaced` field), but flagging is the backstop, not the instruction. One example beats a paragraph:

```bash
python3 -m lupin_cli.claude_code.hooks.lib.heartbeat_hold_io write \
  --session-id <id> --persona "You 😎" --reason "<why holding>" \
  --ttl-seconds 14400 --awaiting "user:<name>"
```

**Principle**: FastAPI `/docs` and `/redoc` are the authoritative API reference. Hand-written docs cover architecture, concepts, and operations only.

## Doc viewer scope (unified path-prefix routing)

**URL format**: `/app/docs?path=<project>/<rel>` where the first path segment names a registered project. The `?scope=` query param is **retired**: its presence answers HTTP 400 with a pointer to this section.

- **Lupin files**: `/app/docs?path=lupin/<rel>` — e.g. `/app/docs?path=lupin/bug-fix-queue.md`, `/app/docs?path=lupin/src/rnd/foo.md`. Whitelist authority is `lupin/.docview.yml` at repo root.
- **Other registered repos**: `cosa-voice`, `planning-is-prompting`, `lookml`, `par-pacific`, `claude-plans`, `retail-ai-location-strategy`, `lupin-mobile` — same URL shape, scope name is the project name.
- **Source of truth**: `src/conf/lupin-app.ini` § `external repos` plus each repo's `.docview.yml` (when present).

The floor blocklist and upload are described in `src/docs/wiki/capabilities/doc-viewer.md`. Runtime discovery, supported file types, Folder/Roots/Upload and the example URLs are in `src/docs/doctrine/claude-md-receipts-archive.md` § "Doc viewer scope (unified path-prefix routing)".

**For sessions emitting links**: ALWAYS prefix with the project name. `scope=` is dead — do not include it. The endpoint will 400 immediately if you do, with an educational message naming the canonical form + the live registered-project list.

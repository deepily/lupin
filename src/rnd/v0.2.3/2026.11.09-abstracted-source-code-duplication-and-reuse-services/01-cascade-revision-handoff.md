---
authorized_by: task:d8d88860-4d1e-4a79-96a1-0fd67d87fba2
doc_kind: review
---

# Cascade revision handoff: code-health abstraction

Chloé 🗼 (author), 11 Nov 2026. Written for the lupin-resident session that builds §6.3 step 1 and for the `lupin-mobile` session that owns step 2. It is readable without the cascade topic files, DM threads or the Step 8 summary. Measured from lupin at `870c42685`, the revised plan merged by María, and from the commons topic `cascade-code-health-abstraction`.

## 1. Purpose and cross-reference

The input plan is `2026.11.09-abstracted-source-code-duplication-and-reuse-services.md` in this folder (the census of the five code-health services and the proposal to abstract them for other repos). Rick ordered a cascaded review of it (row `898c93d8`). The cascade ran on 11 Nov 2026 and closed all four sections, A to D. Rick then ruled the three open items, and the plan was revised and re-reviewed.

This document is the hand-off, not the plan. It says what the cascade changed, what Rick ruled, what stays open, and who builds what. The plan is the specification; where this document and the plan disagree, the plan wins and this document is the bug.

The task-stub manifest that accompanies it is `src/docs/plan-stubs/2026.11.09-abstracted-source-code-duplication-and-reuse-services.stubs.json` (23 steps in 5 phases, 28 rows with the phase rows). The phase headings it validates against are at the end of this document, because the plan itself carries no `## Phase N` headings.

## 2. Cascade telemetry

Cast: author Chloé, Stage 1 Rachel (usability and reuse), Stage 2 John (viability and gap), Stage 3 Pocholo (ownership), manager María. The cast was spawned at 13:21 EST on 11 Nov; Sections A and B closed at Stage 3 at about 13:35 and C and D at about 13:37 (commons timestamps).

| Section | Content | Stage 1 | Stage 2 | Stage 3 | Total | Inconsistency | Cosmetic |
|---|---|---|---|---|---|---|---|
| A | §4 couplings, §5 per repo versus shared | 6 | 4 | 3 | 13 | 10 | 3 |
| B | §6.1 per-repo settings, Q1 | 8 | 6 | 5 | 19 | 14 | 5 |
| C | §6.2 seams, Q2 | 9 | 6 | 6 | 21 | 21 | 0 |
| D | §6.3 packaging, §7 owed work, Q3, §8 | 7 | 5 | 6 | 18 | 11 | 7 |
| **All** | | 30 | 21 | 20 | **71** | **56** | **15** |

- **Foundational findings: none.** Nothing was escalated during the run.
- **Closure:** every finding was classified `revised` except A's V2 and V4 (`documented`, moved to §7 items 8 and 9), D's D4 (`documented`, then settled by John's read of the code), and D-O6 (`kept`, an item for Rick).
- **One finding was raised in severity** (C9, cosmetic to inconsistency) and **one backflow into a closed section** occurred (A's group 8, cosmetic, found by the author).
- **Rick's rulings** arrived after Stage 3 and needed a revision outside the cascade: commit `2af7b2bba`, then the light-review fixes `870c42685` (§4).
- **Not measured:** verbatim-accept rates, and message counts per section against the budget of 25.

Commit trail (author tip, with the merge where María reported one):

| Step | Commit |
|---|---|
| Cast manifest | `816f4a5b0`, `dfc477f65` (merged `30455b16d`) |
| A, B, C, D Stage 1 fixes | `8c2c09d64`, `235170c07`, `c6e41a276`, `1da17b578`, `377bb93cf` |
| A and B Stage 2 and 3 | `e29d4facd`, `b3089b2bc`, `c58a49baa`, `07acc1c73` (merged `cc9ee3f93`) |
| C and D Stage 2 and 3 | `ba68924cc`, `622465533` (merged `049ccac2d`) |
| Step 8 summary | `8443edd67` (merged `ac0cf9e0a`) |
| Rick's rulings folded in, then the review fixes | `2af7b2bba`, `870c42685` (merged by María) |

## 3. Per-section revision summary

The input plan had no acceptance criteria. Every AC below was created by the cascade, with an `EXECUTOR` tag and the 100% lines, branches and functions assertion (Lupin's coverage rule, `src/tests/run-coverage-gate.sh`). None is verifiable until its code exists.

### 3.1 Section A: couplings, per repo versus shared (13 findings)

- **Findings closed:** 10 inconsistency, 3 cosmetic. The main ones: the nine groups now cite full paths and the real constants (`LUPIN_PY_PACKAGES`, `LUPIN_JS_DIRS`, `TESTS_DIRS`, the `tests_spec` branch); group 6 names both compose mounts and the single-root loader; group 7 is split into "already a parameter" and "still a constant"; §5 states that merge gates are not a per-repo copy, the co-residence assumption with `:7999`, and that the onboarding baseline cost is unmeasured.
- **Documented, not revised:** the nine groups are **sampled, not a census** (§7 item 9), and the `lupin-mobile` baseline cost is **not measured** (§7 item 8).
- **Impact on ACs:** none created in A. §7 items 8 and 9 carry executors and done-signals.

### 3.2 Section B: per-repo settings (19 findings)

- **Findings closed:** 14 inconsistency, 5 cosmetic. The settings are now **eight per-repo INI keys and one global key** in `lupin-app.ini` (§6.1), each with a default equal to today's value, a reader, and a splainer twin. The `.code-health.yml` was dropped after Rick's ruling (§4).
- **Moved out of the settings:** schedules stay in `src/conf/job-registry.json`; judge model and Jev version are code pins; `notify.on`, `doc_lint.standard`, `doc_lint.gates` and `remediation.filing` were dropped because nothing reads them.
- **ACs created:** B-AC1 to B-AC7 (census of keys and twins, defaults, bad values, path refusals, the real INI read through the real reader, key census with a name check, and the ledger sync with its drift check).

### 3.3 Section C: the seams (21 findings)

- **Findings closed:** 21 inconsistency. The direction: **a seam is a name and a contract for an existing thing, never a new class.** Eight seams: `IndexSpec` (widened), `DataRoot` (`fleet_data_root`), `EmbeddingProvider`, `Judge` (duplicate check only; the doc-lint judge is a separate seam), `TaskStoreAdapter`, `Notifier` (`hook_link_tick`), `Scheduler` (`job-registry.json` plus `cron_generate.py`, which gains a repo key), `Gate` (the fixed hook chain).
- **Pinned:** the doc-lint rule list (`rule_lists.py`, ruling `b42eb0de`) is a pin; its drift since the freeze is cited with its rows.
- **ACs created:** C-AC1 to C-AC10, including the one-time mutation arm (C-AC3), the embeddings-route census (C-AC4, red until §7 item 10 lands), and the ceiling move (C-AC10).

### 3.4 Section D: packaging, owed work, Q3, §8 (18 findings)

- **Findings closed:** 11 inconsistency, 7 cosmetic. §6.3 is the one packaging list. The installer composes `install-git-hooks.sh` and `cron_generate --install` and checks `install-cosa-voice.sh --check-only` as a precondition. Q3 states the real mount mechanism (a bind mount cannot take a glob) and the corrected costs of the alternatives. The two-week gate has a start event and a literal pass signal.
- **ACs created:** D-AC1 to D-AC4, plus D-AC3b (the container reads the new repo's vectors after the recreate).

### 3.5 Cross-section dependencies

```mermaid
flowchart LR
    A["A: couplings"] --> B["B: INI keys"]
    B --> C["C: seams read the keys"]
    C --> D["D: packaging order"]
    B --> D
```

- The keys in B are what C's seams read; C's `Scheduler` change (a registry repo key) and `duplicate_check_daily.py` ceiling change both depend on B's keys existing first.
- D's installer writes B's keys and runs C's ledger sync; D's phase order follows from "name existing seams" in C, not from a new package.
- Build order: B's keys, then the sync and the ceiling move, then the seams, then `lupin-mobile`, then the package, then the plugin (§6.3).

## 4. Cross-section ratification summary

**Rick's three rulings, 11 Nov 2026 (card answers):**

| # | Ruling | Effect on the plan |
|---|---|---|
| 1 | **Q3: one read-only mount line per repo** (the plan's stance) | Q3 marked ruled; each onboarding needs a compose edit and `--force-recreate` of `:7999` and `:8000` |
| 2 | **All code-health settings live in Lupin's INI.** In his words: "if these are services that are created or abstracted by Lupin and provided to other repos then yes that information should live in Lupin's configuration file." | `.code-health.yml` retired; keys on the `external repo <name> ...` pattern; the duplicate check's per-run ceiling (800) moves from the registry argument to an INI key; schedules may stay in the registry, and any limit or budget lives in the INI |
| 3 | **Per-repo Jev limit as an INI key is the single source; the lifetime cap is kept** | `external repo <name> jev token limit` (Lupin's default 1428571428, the ledger's limit row read 11 Nov); one new thin sync writes the ledger from it, with a drift check; `reuse shadow audit lifetime token limit` stays as Rick's separate backstop |

**Step 9 light-review fixes S9-1 to S9-6 (`870c42685`, approved by Pocholo):**

- **S9-1:** two guards in `duplicate_check_daily.py` (`:1005`, `:1006`) refused a run without `--ceiling`; they now accept the INI key, a blank key still refuses naming the key, and C-AC10 covers it.
- **S9-2:** a registry row, not a listing in `external repos`, turns code health on for a repo; B-AC6 checks the directory-name match only for repos with a row. `par-pacific` and `claude-plans` do not match their directory names and stay off.
- **S9-3 to S9-6:** coverage wording on B-AC2, B-AC3 and B-AC5; Open sub-question 4; the drift check runs at the start of every Jev run and at the end of onboarding; leftover wording.

**Retired during the cascade:** a second settings file; `TaskSink` and `RepoSpec` as new classes; `Embedder` as a new wrapper; `judges.*`, `schedule.*`, `notify`, `doc_lint` and `repo.branch` as settings.

**Recon checklist, resolved** (every item from the plan's preface):

| Item | State |
|---|---|
| 100% lines, branches and functions | CARRIED: on every AC and every seam's code |
| Coverage does not reach `lupin-mobile` | CARRIED: step 2's lupin-side code is covered, the repo's own code follows its repo's rules |
| `lupin_mcp` is ratcheted, not swept | CARRIED: new code there is held to the ratchet table |
| Nested repos are separate | CARRIED: a `lupin-mobile` session builds step 2 |
| Path management | RESOLVED: every key path is relative to the repo root; the data subdir is a leaf under `fleet_data_root` |
| `REUSE-OUTCOME` per new definition | CARRIED: C-AC6 and the reuse gate; the one new thing is the ledger sync, with its lookup recorded in §6.1 |
| No test or job touches a GPU | CARRIED: C-AC4 states it |
| Seats install nothing in cron | CARRIED: D-AC3 and the Phase 1 gate step are `EXECUTOR: HUMAN` |
| Build belongs to a lupin-resident session | CARRIED (row `898c93d8`) |
| `:8000` serves the main checkout, check idle first | CARRIED at build time: D-AC1 names the scheduled path and `venue_idle` |

## 5. Post-cascade fold bundle: open items

None of these is a decision for Rick. Each has an owner and a done-signal in the plan.

| Item | Where | Owner and done-signal |
|---|---|---|
| **Open sub-question 1**: what carries a third repo's merge gate | §6.3 step 3 | The step 3 builder; done when the choice is written and a test shows a failing merge-gate input refused |
| **Open sub-question 2**: whether `lupin-mobile` retires its vendored doc-lint copy | §6.3 step 3 | Same builder; decided at step 3 |
| **Open sub-question 3**: `module_base` has no INI key | §6.2 | The step 1 builder; one outcome written and tested |
| **Open sub-question 4**: whether the shadow audit's per-drain ceiling becomes per repo | §6.1 | The step 1 builder; outcome written, census count updated if a key is added |
| §7 item 8: `lupin-mobile` baseline cost | §5, §7 | A `lupin-mobile` session |
| §7 item 9: dated census of couplings | §4, §7 | Any lupin seat; a timestamped table replaces the nine-group sample |
| §7 item 10: route `vector_build.py:61` through `EmbeddingProvider` | §6.2, C-AC4 | The step 1 builder; lands before or with C-AC4 |
| **Pocholo's leftover 1:** what `reinstall_command` prints for the ceiling | `duplicate_check_daily.py:523-528` (`limit_flag`, `reinstall_command` print `--ceiling N`) | Not decided. After the ceiling moves to the INI, the printed install text must either omit `--ceiling` or print the INI key; the step 1 builder chooses and adds a test |
| **Pocholo's leftover 2:** a negative control for B-AC6 | §6.1 | Not written. B-AC6 needs a case that fails on purpose (a registry row whose repo name differs from its directory) to prove the check can find a mismatch |
| The `lupin-mobile` owner and manager row | §6.3 step 2 | María files it at Step 9; Phase 2 step 1 in the manifest |
| Whether the 1 Oct change to `rule_lists.py` (`34988c0f7`) carried Rick's word | §6.2 | Filed by María as a separate store row; does not block this plan |

## 6. Workflow-guidance index (candidates; each cites its anchor)

The deeper redline in planning-is-prompting is not written; the Manager files it.

1. **A late direction needs a sweep across sibling sections.** The "registry wins, the file holds no schedule" direction (B Stage 2) contradicted text already in Section A (group 8); found only because a grep for the old key name was run. Anchor: backflow classification on commons, 11 Nov 13:34 EST.
2. **A "move X to Y" ruling needs the reader code read, not only the plan.** Moving the ceiling to the INI hit two argument guards that refuse a run without `--ceiling` (S9-1). Anchor: light review at `2af7b2bba`.
3. **A census AC must be run against the live population before it is written.** B-AC6 was red the day it was written because two registered names differ from their directories (S9-2). Anchor: same review.
4. **A receipt must be a commit on a branch.** The store refused a receipt for a commit that existed only under `refs/archive/`. A seat whose branch is guarded cannot close its row until the manager merges. Anchor: transition refusal on row `b73470ed`, 11 Nov.
5. **`src/rnd/` accepts only `.md`**, so a stub manifest cannot live next to its plan; it lives in `src/docs/plan-stubs/`. The importer's `validate` also needs `## Phase N` headings in the file `plan_ref` names, which a review-cascade plan does not have. Anchor: `plan-stub-manifest.md` §3 and this hand-off.
6. **Reviewer citations drift.** Four of the Stage 1 findings carried a wrong path or line; each cite was re-opened before use. Anchor: author deposit on the `post-game` topic, 11 Nov.
7. **"Add EXECUTOR tags to every AC" is an instruction to create ACs when a section has none.** The review cascade input here had no ACs at all. Anchor: author deposit, same.
8. **A decision made after Stage 3 sits outside the cascade's 1-revision cap.** Rick's rulings needed their own revision and re-review; the workflow does not say how that loop is counted. Anchor: rows `b73470ed` and `d8d88860`.

## 7. Hand-off statement

**Who builds what.** A **lupin-resident session** builds §6.3 step 1 (Phases 0 and 1 in the manifest): row `898c93d8` is Rick's order that the build is lupin-resident. A **`lupin-mobile` session** owns step 2 (Phase 2); María files that row at Step 9. Steps 3 and 4 (Phases 3 and 4) are built after two repos run cleanly, by a lupin-resident session. The manifest's `owner_persona` is `maria` and its correlation key `epic:code-health-abstraction-build` are placeholders for the manager to reassign when the rows are approved.

**Order and gates.** Hold any third repo until two weeks of green scheduled runs on Lupin and `lupin-mobile` (Rick's decision 1; the window is defined in §6.3 step 2). Nothing in the plan is built yet; nothing in Lupin changes behaviour until step 1's ACs pass.

**Standing rules the builder must follow:**

- 100% lines, branches and functions on every file changed; a coverage run is never scoped when its output is read as a list.
- Commit with `git commit -F <file> -- <paths>`; never attach a heredoc to the commit line. Stage only your own files; never `git add .`.
- Seats never install cron lines. Rick runs `cron_generate --install`.
- Venues: unit and inline smoke on `:7999`; the merge pyramid's `:8000` rows go through `POST /api/v2/submit` after `python -m cosa.rest.venue_idle --port 8000` answers idle (exit 0). No test or job touches a GPU.
- Work in a worktree under `.claude/worktrees/`, with `LUPIN_ROOT` and `PYTHONPATH` both pinned to it.
- Every new definition carries a `REUSE-OUTCOME` line; the reuse gate checks it.
- Each new INI key gets a splainer twin in `lupin-app-splainer.ini`.
- `src/conf/lupin-app.ini` is always committed when modified, in its own commit when a merge is blocked on it.

**What the builder can rely on:** every claim in §6.1 and §6.2 cites a file and line at `870c42685`; the figures labelled "not measured" are not guesses. **What the builder must not assume:** that the sync command's name is final (`python -m lupin_mcp.reuse_ledger_sync` is proposed), that any AC is executable before its code exists, or that registering a repo in `external repos` turns code health on.

## Phase 0: Owed work first

The three owed items of §7 (4, 8, 9). Steps `ph0-s1` to `ph0-s3` in the manifest. Run first so the census and the baseline cost are known before the keys are written.

## Phase 1: INI keys and seams in cosa

Section 6.3 step 1. Steps `ph1-s1` to `ph1-s11`: the keys, the ledger sync, the ceiling move, `IndexSpec`, the `Scheduler` repo key, Rick's cron install (a gate), the embeddings route, the contract paragraphs and the merge pyramid. Open sub-questions 3 and 4 are decision steps here.

## Phase 2: lupin-mobile as repo 2

Section 6.3 step 2. Steps `ph2-s1` to `ph2-s3`: the owner row, the registry rows and keys, and the two-week green gate.

## Phase 3: Installable package and installer

Section 6.3 step 3. Steps `ph3-s1` to `ph3-s4`: Open sub-questions 1 and 2 as decisions, the installer, and the mount check after the recreate.

## Phase 4: Claude Code plugin

Section 6.3 step 4. Steps `ph4-s1` and `ph4-s2`: move the wrappers, then the new plugin manifest.

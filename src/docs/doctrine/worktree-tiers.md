# Doctrine — worktree tiers

> Why a tier run from a worktree accuses a branch of breakage it does not have.
>
> **What this file is.** These are the RECEIPTS behind rules that live in `CLAUDE.md`.
> Each entry was moved here verbatim on 2026-09-08 (sha `ed653c8b`, row `f1400995`) so the
> combined `CLAUDE.md` would fit under Claude Code's 150,000-char load limit. **Nothing was
> deleted.** The operative rule — the command, the table, the ⇒ ruling — stayed inline where a
> seat acts on it; what moved is the measurement narrative that explains why the rule is believed.
>
> **Read this when** you want to check a rule against its evidence, when you are about to change
> or retire one, or when you doubt a figure. **You do not need to read it to follow the rule.**


---

## A main-line red count, the worktree remedy block, the split import graph, and the 10/11/43 reconciliations

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 A MAIN-LINE RED COUNT MUST BE RUN AT THE MAIN LINE — A BRANCH CANNOT SEE THE REDS ITS OWN UNMERGED WORK CLOSES

Cheech 🌿, 2026-09-04, on my own sweep, caught only because an unrelated arm ran in a tree that was
not mine. **I swept the unit tier, reported 3 reds and "zero stale tests", and both figures were true
of the tree I ran in and false of the branch the fleet stands on.**

| tree | reds | stale |
|---|---|---|
| `dc96a65b` — my worktree branch | **3** | 0 |
| `cba072f8` — the main line | **4** | **1** |

**Both are correct measurements of different trees.** The fourth red is
`test_the_transition_door_calls_the_promotion_gate.py::test_the_row_records_which_way_rick_answered`
— `assert 'rick-approved' in 'standing'` — a STALE TEST: `6de5fdc4` moved that prose out of
`authority`, a `String(32)` enum column every combination was overflowing at 58-65 chars, and into
`reason`; the assertion stayed pointed at the old column. **My branch carried the fix (`22ea2914`),
so my sweep could not see the red that fix closes.**

⇒ **THIS IS NOT A CARELESSNESS RULE, IT IS STRUCTURAL.** Any seat sweeping from its own branch is
blind to exactly the defects its unmerged work repairs, and the blindness is invisible from inside:
the run is green, the tier is honest, and the number is about a tree nobody else is standing on.
**A denominator claim about "the tree" must be run at the main line, or it is a claim about your
branch wearing the fleet's name.**

⚠️ This is § *A COVERAGE LIST GOES STALE FROM A MERGE, NOT FROM A COMMIT* arriving on a RED COUNT
rather than a coverage list, and one step worse: a coverage list that omits your work UNDER-reports
you, while a red count that omits it **over-reports the branch's health.** The direction is toward
the false green.

⚠️ **AND I DID NOT DISCOVER IT — IT WAS IN SOMEBODY ELSE'S BASELINE ALL ALONG.** Tiberius 👑 had
that same id in his 13-failure baseline twenty minutes earlier, classified as a known unrelated
failure. What I added was the CAUSE and the CLASSIFICATION, not the sighting. **Do not read this
entry as a sweep catching something; read it as a sweep being unable to.**

**Before running a tier from a worktree:**

```bash
cd <your-worktree> \
  && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python -m pytest src/tests/unit/ -q
```

`LUPIN_ROOT="$PWD"` is the one you must not forget — it is inherited from your shell and silently keeps pointing at `/…/lupin`. The other two are unfixable from inside a worktree: **subtract them, do not chase them.**

🔴 **PIN BOTH VARIABLES. THIS BLOCK CARRIED ONLY `LUPIN_ROOT` UNTIL 2026-09-01, AND A READER FOLLOWING IT EXACTLY STILL GOT THE SPLIT-IMPORT GRAPH.** `LUPIN_ROOT` decides which tree the code **resolves paths against**; `PYTHONPATH` decides which tree the code is **imported from**. Two variables, two different jobs — and this file already documented the hazard elsewhere in this section, which did not stop the person who wrote this paragraph from re-deriving it from scratch. **The knowledge was present; the REMEDY BLOCK was what people copied.** That is why the fix belongs in the pasted line.

Nothing is installed, so `sys.path` is the whole story: `pip show cosa` reports *Package(s) not found*, there is no `cosa/` in site-packages, and `env -u PYTHONPATH .venv/bin/python -c "import cosa"` raises `ModuleNotFoundError` **in the main checkout as well as a worktree**. Two entries put a `src` on the path, at two different moments, and a module comes from whichever got there first:

| entry | when | governs |
|---|---|---|
| `PYTHONPATH` | interpreter startup | anything imported at or before startup |
| `LUPIN_ROOT`/src, via `src/tests/unit/conftest.py:26-29` | pytest collection | everything imported after |

⚠️ **AND `cosa` IS ALREADY IMPORTED BEFORE PYTEST EXISTS, SO FOR `cosa` THE CONFTEST INSERT IS INERT.** Measured: at interpreter start `'cosa' in sys.modules` is **True** (`cosa`, `cosa.utils`, `cosa.utils.checked_hash_pyc`, per `-X importtime`), and inserting the worktree's `src` at `sys.path[0]` in a fresh interpreter still leaves `cosa.__path__` naming the main repo — the module object already exists. The chain: `site` imports `sitecustomize` **from anywhere on `sys.path`**, `PYTHONPATH` supplies the MAIN repo's `src/sitecustomize.py`, and its line 32 does `from cosa.utils.checked_hash_pyc import install`. `python -S` skips `site` and `cosa` is then absent — which is how the chain was confirmed rather than assumed. A second, later path exists too (`src/conftest.py:122` imports `cosa.utils.unit_network_guard` with no `sys.path` insert before it), but `sitecustomize` gets there first.

⇒ Pin one and not the other and your run's modules come from **two different checkouts — a tree that exists nowhere on disk.**

⚠️ **A SYMLINKED `.venv` IS NOT THE CULPRIT.** Measured, same tree, one variable: `PYTHONPATH` pinned → **66 passed, 0 failed**; unpinned → 1 failed, 65 passed. Two failures first blamed on the symlink were both `PYTHONPATH`. The guidance to symlink the main repo's `.venv` stands unchanged and is correct — the venv supplies no `cosa` at all, so it cannot be the thing choosing your tree.

🔴 **AND `LUPIN_ROOT` ALONE IS NOT ENOUGH — `PYTHONPATH` SPLITS THE IMPORT GRAPH AND GIVES YOU A
HYBRID APP THAT IS NEITHER TREE.** Measured 2026-09-01 (Rio ⚡). Every seat's shell carries
`PYTHONPATH=/…/lupin/src`. The unit `conftest.py` inserts `$LUPIN_ROOT/src` at position 0, so
anything imported **after** conftest runs comes from your worktree — but anything already resolved
via `PYTHONPATH` **stays** resolved to the main repo, because `sys.modules` is sticky.

**The receipt, from one pytest process in a worktree with `LUPIN_ROOT` correctly pinned:**

```
main module file : /…/lupin-wt-rio-routeaudit/src/lupin_app/main.py   <- WORKTREE
tasks module file: /…/lupin/src/cosa/rest/routers/tasks.py            <- MAIN REPO
```

⇒ **`lupin_app.*` from your tree, `cosa.*` from someone else's.** The assembled app is a mixture
that exists in no checkout, and nothing in the output says so.

**What it cost, and it is the exact failure this page warns about:** a mutation moving
`GET /api/tasks/flow-ratio` below `GET /api/tasks/{task_id}` — the defect that answered **422 in
production all evening** — was applied to the worktree, verified to shadow when imported directly,
and the two guards written for it reported **6 passed**. They looked blind. They are not: the
mutation was never under test. Pin `PYTHONPATH` and the same arm gives **2 failed**, each naming
its own test:

```
FAILED …test_no_literal_route_is_shadowed_by_a_parameterised_sibling.py::test_no_literal_route_in_the_assembled_app_is_shadowed
FAILED …test_task_routes_resolve_literal_paths.py::test_a_literal_task_path_reaches_its_own_route[/api/tasks/flow-ratio]
```

⇒ **Pin all three, always:**

```bash
cd <worktree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python -m pytest src/tests/unit/ -q
```

⚠️ **THIS ONE IS WORSE THAN THE OTHER WRONG-TREE MEMBERS, because it does not merely answer about
the wrong tree — it answers about a tree that does not exist.** The verifier and the purge script
at least describe *some* real checkout. A split import graph reports on a Frankenstein assembled
half from each, and a green result from it is not evidence about either.

⚠️ **And it points the dangerous way: toward a FALSE GREEN.** A mutation that never lands reads as
a guard that holds. I nearly filed two correct, well-built guards — one of which carries its own
positive control — as blind to the defect they were written for.

**WHO IS ACTUALLY EXPOSED — AND "IMPORTS cosa" IS THE RISK INDICATOR, NOT THE VERDICT.** Of the 14
test files added on 2026-09-01, **13 import `cosa` or `lupin_app`**. That number is a starting
point and nothing more, because it does not separate the two ways a test can use an import:

| how the test uses the import | exposed? |
|---|---|
| imports a module and asserts on **its behaviour** (builds the app, calls the function) | 🔴 **yes** — it measures the main repo's code |
| imports only a **path helper**, then reads FILES (`cu.get_project_root()`) | ✅ **no** — the helper reads `LUPIN_ROOT` at CALL time, so it returns your tree |

Both websocket guards in that list are the second kind, and this is **measured, not reasoned**:
their three mutation arms were run with `LUPIN_ROOT` pinned and `PYTHONPATH` **not** pinned, and
all three reddened — so the files being read were the worktree's, even while `cosa.utils.util`
itself had been imported from the main repo.

⇒ **Do not read a bare import list as an exposure list.** Ask what the test does with the import.
A census that skips that step over-reports, in exactly the way the module-name search over
`rest-api-reference.md` over-reported by counting names instead of paths.

**MEASURED END-TO-END, 2026-09-01 — the pins fix TWO of three, and the third is a new artifact.**
Same 14 files, same sha, three configurations, failing SETS rather than counts:

| run | failing set |
|---|---|
| **main tree** | *(empty)* — 143 passed. The control |
| worktree, `LUPIN_ROOT` only | `test_flow_ratio_settings.py::test_override_path_lands_under_the_fleet_data_root` · `…::test_an_empty_env_var_falls_through_to_the_fleet_root` · `test_notify_idempotency_midconnect_smoke.py::test_a_cached_offline_verdict_is_not_replayed_to_a_connected_user` |
| worktree, **all three pinned** | the smoke one only |

⇒ **Pinning `PYTHONPATH` removes both `flow_ratio_settings` failures.** That is the split-import
graph closing, measured on somebody else's tests rather than on my own arm.

⇒ **The survivor is a FIFTH worktree artifact, and it is a gitignored CREDENTIAL — the
`cloud-run.env` shape again**: `src/conf/keys/notification-api-claude-code-dev`, matched by
`.gitignore:71` (`src/conf/keys/**`), present in the main checkout and in no worktree. The smoke
test resolves it from `LUPIN_ROOT`, so **pinning correctly is what makes it look in your tree and
fail** — the pin is right, the file is simply not there. ⚠️ It is a **:7999 smoke** test, so it does
NOT belong in the unit-tier 10/11/43 reconciliation above; that table is a different population and
must not be inflated with this row.

🔴 **DO NOT SYMLINK ANYTHING UNDER `src/conf/keys/` INTO A WORKTREE — FOR ANY REASON.** (Mr. Radio,
2026-09-01, overruling the first cut of this very paragraph, which said "symlink the file". That
advice was wrong and is left visible here rather than quietly deleted, because it is the obvious
move and the next person will reach for it too.) `src/conf/keys/**` is gitignored to keep secrets in
exactly one place; a symlink puts a live credential inside a throwaway tree that gets `rm -rf`'d,
copied, and shared, and the `.venv` symlink precedent makes it look sanctioned. **It is not the same
case: a venv is a build artifact, a key is a secret.**

⇒ **Subtract this one knowingly instead.** It is the same instruction the unit-tier artifacts already
carry — *subtract them, do not chase them* — and the right long-term fix is the test skipping when
the key is absent, not the key being copied to where the test looks.

**RECONCILED 2026-08-30 — a second measurement got 10, and 10 and 11 are the SAME finding.** Rio ⚡
ran the unit tier at sha `cc336880`, root `/mnt/DATA01/include/www.deepily.ai/projects/lupin-wt-rio-8593bf65`,
with `LUPIN_ROOT="$PWD"` exported, and measured a gap of **10** — not 11.

| | 2026-08-29 (row `3d01df71`) | 2026-08-30 (Rio, sha `cc336880`) |
|---|---|---|
| `LUPIN_ROOT` exported? | **no** | **yes** |
| flash-lite / vertex (`cloud-run.env`) | 9 | 9 |
| terraform provider cache | 1 | 1 |
| wrong-tree `LUPIN_ROOT` row | **1** | **0 — never fired** |
| **gap** | **11** | **10** |

⇒ **The third row of the table above is the entire difference, and it is the one this section
already tells you to fix.** Follow the remedy and the gap is 10; skip it and the gap is 11. So the
two counts agree completely once you know which setup produced each — which is why this section is
amended to carry BOTH rather than overwritten to the newer one. **Per this section's own closing
rule: two counts get RECONCILED, not adjudicated, and a mismatch that reconciles is not a
disagreement.** A doc that had simply replaced 11 with 10 would have made the next reader who
forgets the export think they had found a new failure.

**Verified both directions, not asserted.** The four files carrying those 10 artifact failures —
`test_dm_tutor_flash_lite_routing.py`, `test_flash_lite_arm_vertex_markers.py`,
`test_phi4_flash_lite_replay.py`, `test_terraform_invariants.py` — were re-run WHOLE in the MAIN tree
at `625665bb`: **120 passed, 1 skipped, 0 failed**. (120 is every test in those four files, not the
10 failures; the 10 are a subset that passed along with the rest.) and the two missing inputs were checked on both
trees: `src/scripts/cloud-run.env` and `src/terraform/envs/test/.terraform/providers` are PRESENT in
the main tree and ABSENT in the worktree.

🔴 **AND A THIRD MEASUREMENT FOUND A THIRD VARIABLE: WHETHER THE WORKTREE HAS A `.venv` AT ALL.
WITHOUT ONE THE GAP IS 43 OR 44, NOT 10 OR 11 — AND THIS IS THE SAME FINDING AGAIN, NOT A NEW
DISPUTE.** Measured by Maya 🌻 2026-08-30 at sha `a4fd4551`, root
`/mnt/DATA01/include/www.deepily.ai/projects/lupin-wt-maya-5246-mergecheck`, `LUPIN_ROOT="$PWD"`
exported. **The two rows above silently assume a `.venv` is present** — the remedy block prescribes
`.venv/bin/python`, so a tree without one cannot even run the command this section hands you, and
the reader who hits that has no number here to land on. Now they do.

| | 08-29 (`3d01df71`) | 08-30 (Rio, `cc336880`) | 08-30 (Maya, `a4fd4551`) |
|---|---|---|---|
| `LUPIN_ROOT` exported? | no | yes | **yes** |
| worktree has a `.venv`? | **yes** | **yes** | **NO** |
| flash-lite / vertex (`cloud-run.env`) | 9 | 9 | 9 |
| terraform provider cache | 1 | 1 | 1 |
| wrong-tree `LUPIN_ROOT` row | 1 | 0 | 0 |
| **missing-`.venv` rows** | **0** | **0** | **33** |
| **gap** | **11** | **10** | **43** |

**Verified both directions, in one tree, flipping one variable.** The seven files carrying those 33
— `test_coverage_frame_excludes_non_src.py`, `test_coverage_gate_tier_status.py`,
`test_presentation_regression_tier_classification.py`, `test_runner_collection_diagnosis.py`,
`test_runner_coverage_blindness.py`, `test_runner_venv_pytest_guard.py`,
`test_v2_survives_v1_excision.py` — fail with no `.venv` and give **124 passed, 1 skipped, 0 failed**
the moment the main repo's `.venv` is symlinked in. The failure is a plain
`FileNotFoundError: …/<worktree>/.venv/bin/python`. **And the branch under test was exonerated by a
control, not by subtraction**: the same 33 reproduce identically at the base with the branch's merge
absent — `comm` empty in both directions, not merely equal counts.

⚠️ **THE 44th IS NOT AN ARTIFACT.** The raw tier reported **44 failed**; 43 are environment and the
last is `test_secret_scan::test_a_detector_change_forces_a_full_rescan`, a known branch-level red
held until a credential rotation lands. **Subtract 43, never 44** — folding a real held red into an
artifact count is how a genuine signal gets explained away by its neighbours.

🔴 **AND HERE IS THE PART THAT GENERALISES: A POPULATION CHOSEN BY GREP CANNOT FIND BREAKAGE OUTSIDE
THE GREP.** Row `9b2abfb7` carries an earlier count of **14 → 1** across the 25 unit files whose text
mentions `.venv`, and that number was reached the RIGHT way — by running both ways rather than
assuming. Re-running that same method at `a4fd4551` (30 such files today) gives **19**, while the
whole tier gives **33**. The two do not conflict: the grep-derived failures are a strict **subset**
of the tier's, and the **14** extra live in `test_presentation_regression_tier_classification.py`
and `test_runner_collection_diagnosis.py`, which mention `.venv` **zero times** — they shell out to
a runner that resolves the interpreter for them. ⇒ **Running instead of grepping fixed the
verification and left the SELECTION grep-shaped, so the improved instrument still could not see 14
of its own class.** Widen the population before you widen the trust; the honest scope line is *"14
failures across the files that name it"*, never *"14 failures."*

⇒ **Wiring this into the spawn path was row `9b2abfb7`, and it SHIPPED.** Rick ruled yes by voice
2026-08-31 ~20:08 EDT; Rachel 🕊️ landed it at `ee027c8c`. `cosa/utils/worktree_venv.py` shells out to
`link-worktree-venv.sh` from both creators — `spawn_sessions` once `work_dir` resolves, and
`WorktreeContext.__aenter__` once `git worktree add` succeeds. Measured 35 failed → 0 across the seven
unit files that carry it, one tree, one sha, only the symlink flipped. **The measurement above is what
the forgotten step cost while it was manual: 33 red tests that look like a broken branch.**

⚠️ **Still manual for a hand-typed `git worktree add`** — provisioning lives in the PYTHON spawn path,
which is how every `lupin-wt-*` tree on this box came up without one.

🔴 **AND IT CLOSES THE INTERPRETER GAP ONLY — WHICH IS NOT THE IMPORT-GRAPH GAP.** Measured 2026-09-01
(Krishna 🦚) in a worktree whose `.venv` is a symlink to the main repo's: `cosa` is **not in
site-packages**, `pip show cosa` reports not found, and none of the four `.pth` files adds `src/`.
Clearing `PYTHONPATH` gives `ModuleNotFoundError` **in the main checkout too**.

⇒ **So the venv contributes NOTHING to resolving `cosa`, symlinked or built** — *"build a real venv
instead of symlinking"* is not a remedy for the split import graph, because both forms resolve `cosa`
through `PYTHONPATH` or not at all. A seat can pass the spawn's `INTERPRETER OK` **and** Rio's
`venv_alarm` while running the hybrid tree. Those two controls answer different questions and must not
be read as one.

⇒ **For `cosa` specifically the conftest insert is INERT, and the reason is `sitecustomize` — see the
remedy block earlier in this section, which carries the full chain.** Recorded here because I got it
wrong first: I told Pocholo 📣 the trigger was `src/conftest.py:122` and that both pins govern
different modules. **He had it right and I did not.** `python -S -c "'cosa' in sys.modules"` is
`False` and without `-S` it is `True` — `site` imports `sitecustomize.py` off `PYTHONPATH`, and its
line 32 does `from cosa.utils.checked_hash_pyc import install`. That happens **before pytest exists**,
so `cosa` is already bound when any conftest runs. `src/conftest.py:122` is a real second path but
never gets there first. **Both pins are still required — they simply do not divide the way I said.**

⚠️ **A fourth untracked thing a worktree lacks — except it is not a file.** Rachel's list below names
three (`.venv`, `cloud-run.env`, the terraform cache), all provisionable. This one is an inherited
environment variable pointing every tree at the main repo. **Provisioning cannot fix an env var; only
pinning at invocation can.**

⚠️ **AND SUBTRACTING THE ARTIFACTS IS NOT THE WHOLE JOB — CHECK WHETHER THE BRANCH MOVED.** In the
same reconciliation, 8 of the 9 remaining failures also passed in the main tree, and it would have
been wrong to file them as worktree artifacts too: the main tree was a **descendant** of the
worktree's sha, 12 commits ahead, and those 8 had been FIXED in that window (`51950988` for the
manager-figure stamp; the venv-declaration guard across `20dc6b18`, `71637fe1`, `625665bb`). **A
failure that passes in the main tree has TWO explanations — a worktree artifact, or a fix you do not
have yet.** Reporting the second as the first credits your environment for somebody else's repair.

⚠️ **AND THE TWO-STEP THAT SEPARATES THEM IS NOT ONE COMMAND** (Tiberius 👑, reviewing this section
2026-08-30 — the original text said "`git merge-base` tells you which", which OVERSTATES what it
returns). `git merge-base --is-ancestor <your-sha> <main-HEAD>` establishes **ancestry**, which shows
only that a fix **COULD** be missing. What proves one **WAS** is **naming the commit**:
`git log --oneline <your-sha>..<main-HEAD> -- <the failing test's path>`. Ancestry narrows the
suspects; the commit closes it. A section whose whole theme is descriptions drifting from evidence
should not itself claim more than its command returns.

⚠️ **THE SAME MISMATCH IS HARMLESS IN ONE DIRECTION AND SILENT-FATAL IN THE OTHER — SO READ THE
WARNING, THEN ASK WHAT THE CODE WRITES.** Measured by Maya 🌻 2026-08-29, and added here rather than
in a second section because it is a refinement of the three traps above, not a new one. Three cases,
and they are not equally bad:

| What the code writes | With a wrong `LUPIN_ROOT` | How bad |
|---|---|---|
| **Code path** — imports, runs a suite | your edits are not what runs; the tree you stand in is not the tree imported | misreports **your own** work, silently |
| **Shared data, path NOT derived from `LUPIN_ROOT`** | lands correctly anyway | noise — *if* you read the result back |
| **Shared data, path derived from `LUPIN_ROOT`** | writes where nobody reads, or into another repo's state | **worst** — corrupts **another seat**, not you |

🔴 **I FIRST WROTE THIS AS "HARMLESS ON A SHARED-DATA WRITE" AND THAT WAS UNDERBUILT.** Harmless is
a property of the RESOLVER, not of the destination: it holds only when the path does not derive from
`LUPIN_ROOT`, and I had not checked that it doesn't before saying so. The correction is the bottom
row, and it is the one that matters — a code-path mistake misreports your own work, a shared-data
mistake corrupts somebody else's.

**The measured case, and why it is the middle row rather than the bottom one.** The heartbeat-hold
verb printed this section's WRONG-TREE warning at me — shell `LUPIN_ROOT` still naming `/…/lupin`
while the file sat in my worktree — and the hold was still correct. Not by luck: `fleet_data_root()`
calls `_main_repo_path()`, which collapses a worktree to its parent checkout, so the destination is
invariant under the choice. Verified both ways rather than read off the source:

```
LUPIN_ROOT=lupin                    -> …/projects-data/lupin
LUPIN_ROOT=lupin-wt-maya-ba6df71e   -> …/projects-data/lupin      # identical
```

Had that resolver taken `LUPIN_ROOT`'s basename instead, the hold would have gone to
`projects-data/lupin-wt-maya-ba6df71e/`, where the arbiter and the Stop hook never look — a session
parked invisibly, which is the bottom row and the exact failure row `011f1f90` exists to catch.

⇒ **A wrong-tree warning is not one severity.** Ask which row you are in before deciding whether to
act on it — and on the middle row, still read the result back, because "it landed correctly" is a
claim until you have seen it.

⚠️ **AND IT REACHES CONFIGURATION, NOT ONLY COVERAGE.** Measured 2026-08-29: two seats disagreed about whether `"src/scripts"` was in `pyproject.toml`'s coverage source list. It was present at HEAD (1), present in the worktree after a merge (1), absent at that worktree's pre-merge sha (0) — **both readings correct, about different files.** A run under a stale config would have measured none of those files and published an EMPTY zero list, with nothing in the output saying so. ⇒ **Verify the config in the tree you are about to RUN IN, immediately before the run. HEAD is not where the run happens.**

⚠️ **The general shape, which outlives these three:** a worktree is `git`-identical to the main tree and **environment-identical to nothing**. Anything gitignored, untracked, or exported into your shell is a property of *where you are standing*, not of *what you are measuring*. That is why two counts should be **reconciled** rather than adjudicated — 25 − 14 = 11 with every one named is stronger evidence than either count alone, and a mismatch that reconciles is not a disagreement.

⚠️ **Related, same family** — the collected-test-id diff. Some test ids bake an **absolute path** into a parametrize id, so diffing collected ids between two worktrees shows the same test as one removal plus one addition. A raw diff read `+225 / −4` and looked like the merges had deleted four tests; they had not. Compare **counts** as well as ids, and treat the agreement of the two as the check.


---

## A tier run from a worktree — the five reconciliation passes and their arm tables

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 A TIER RUN FROM A WORKTREE REPORTS 10 OR 11 FAILURES THE MAIN TREE DOES NOT HAVE

**Which of the two you get is decided by ONE thing: whether you exported `LUPIN_ROOT="$PWD"`.** Both numbers below are correct; they are measurements of two different setups, not a disagreement. See the reconciliation under the table.

**Measured 2026-08-29** (row `3d01df71`). Two seats ran the unit tier on the same sha `31b2cfce` within the hour and got **25 failures in a worktree** against **14 in the main tree**. Neither number was wrong. The gap is **exactly 11 in that setup** — INFERRED (not measured) to be without `LUPIN_ROOT="$PWD"` exported, from the fact that its third row fired at all; with the export it is 10, and the two reconcile (see below) — and all of it is state that is present in the main tree and absent from every worktree — so a worktree tier accuses the branch of breakage it does not have.

| n | what is missing | how it surfaces |
|---|---|---|
| 9 | `src/scripts/cloud-run.env` — **gitignored** at `.gitignore:79` | `gcp_project.py:115` `RuntimeError: LUPIN_GCP_PROJECT_ID is not set…` ×8, plus `KeyError: 'dm_tutor/flash_lite'`. The whole flash-lite / vertex family. |
| 1 | `src/terraform/envs/test/.terraform/providers` — untracked local cache | `test_terraform_invariants.py` — "provider plugins are NOT cached at …" |
| 1 | nothing missing — **`LUPIN_ROOT` still names the MAIN repo** while you stand in the worktree | the tests catch this one themselves and print `test file` / `its tree` / `LUPIN_ROOT` side by side |

⚠️ **RE-MEASURED 2026-09-04 (Cheech 🌿) — THE `cloud-run.env` ROW IS NOW CONDITIONAL, AND BOTH
FIGURES ARE LIVE. THE TABLE ABOVE STANDS; IT IS THE ROW FOR ONE VALUE OF A VARIABLE NOBODY HAD
NAMED.** Read this before subtracting anything, because the instruction above — *subtract them, do
not chase them* — **makes a seat in a PROVISIONED tree subtract nine reds that are real.**

| `src/scripts/cloud-run.env` | flash-lite / vertex row | when you are here |
|---|---|---|
| **ABSENT** | **9** — the table's original figure, still correct | a hand-typed `git worktree add`; provisioning is in the PYTHON spawn path only |
| **PRESENT** | **0** | a tree the `dde8b87a` borrow provisioned |

🔴 **DO NOT COLLAPSE THIS TO EITHER NUMBER.** The 9 is not stale and the 0 is not a correction of
it — they are two values of one variable, exactly as this table already keys on whether
`LUPIN_ROOT` was exported and whether a `.venv` is present. **`ls src/scripts/cloud-run.env` first;
the file is the coordinate and the count is derived from it.**

**Measured**, unit tier at sha `dc96a65b`, worktree `lupin-wt-cc-author-mr-radio-1`, both variables
pinned, `.venv` and `node_modules` symlinked: **22,282 passed · 3 failed**, and the three are
`test_secret_scan.py::test_a_detector_change_forces_a_full_rescan`,
`test_secret_scan.py::test_the_recorded_counts_are_derived_from_the_same_scan` (two deliberate
rotation holds) and `test_terraform_invariants.py::test_terraform_provider_cache_is_present`.
**The nine flash-lite / vertex failures did not fire at all.**

⇒ **The cause is a FIX, not a different measurement**: `src/scripts/link-worktree-artifacts.sh`
(row `dde8b87a`, 2026-09-04) now borrows `cloud-run.env` into a spawned worktree, so the file is
PRESENT — verified by `ls` in this tree. That row is already recorded in § *THE WORKTREE ARTIFACTS
THE TIER CANNOT SEE*; what nobody did was come back and correct **this** table, which is the one
people copy a subtraction out of.

| row | before | after `dde8b87a` |
|---|---|---|
| flash-lite / vertex (`cloud-run.env`) | 9 | **0 in a SPAWNED worktree** |
| terraform provider cache | 1 | 1 — unchanged, still absent |
| wrong-tree `LUPIN_ROOT` | 1 | 1 — unchanged, fires only if you skip the export |

⚠️ **THE 9 IS NOT DEAD, IT IS CONDITIONAL — AND THE CONDITION IS HOW THE TREE WAS CREATED.**
Provisioning lives in the PYTHON spawn path only, so **a hand-typed `git worktree add` still gets
nothing** and still sees all 9. ⇒ **Do not replace one fixed number with another.** `ls
src/scripts/cloud-run.env` before you subtract anything: present ⇒ expect 0 from that family,
absent ⇒ expect 9. **The file is the coordinate; the count is derived from it.**

✅ **THE HAND-CREATED CASE IS NOW MEASURED, NOT INHERITED — Tiberius 👑, 2026-09-04 at sha
`cba072f8`, and BOTH halves of the conditional were run.** I had marked this clause inherited; he
closed it, and the two claims it contains were checked separately because they are separately
falsifiable:

| the claim | how it was closed |
|---|---|
| a hand-created worktree **lacks the file** | bare `git worktree add`, no python spawn path ⇒ `cloud-run.env` and `node_modules` both ABSENT, both PRESENT in the main checkout |
| that absence **produces nine failures** | he ran the tier: **4 + 3 + 2 = 9**, in `test_dm_tutor_flash_lite_routing.py`, `test_flash_lite_arm_vertex_markers.py`, `test_phi4_flash_lite_replay.py` |

⇒ **The 9 in the table above is now a measurement rather than a figure passed down**, and the
`ls`-then-derive rule is confirmed on the side that matters — the side a reader hits when the borrow
did NOT run.

🔴 **THE ARM RULED OUT ONE CONFOUND, NOT ALL OF THEM — SAY WHAT WAS ACTUALLY MISSING.** The venv
was **LINKED**, so the nine are NOT confounded with the **33** a missing `.venv` produces (see the
reconciliation table above); that much the arm does establish. But **`node_modules` was ALSO
absent**, so the tree differed from the main checkout in **TWO** ways and the arm is not the clean
single-variable isolation an earlier draft of this paragraph claimed it was.

⚠️ **THAT CLAIM WAS MINE AND IT CONTRADICTED THE TABLE TWO LINES ABOVE IT**, which says plainly that
both files were absent. Tiberius 👑 caught it against his own result — the correction makes his arm
weaker, not stronger, which is the direction nobody volunteers. Recorded rather than quietly
reworded, because *"only X was missing"* is the sentence that makes a number look more isolated than
it is.

✅ **CLOSED 2026-09-05 (Tiffany 💍) — `node_modules` CONTRIBUTES NOTHING TO THOSE NINE, AND THE
NINE ARE `cloud-run.env` ALONE. The arm this paragraph asked for was run, plus a third arm nobody
asked for.** The question above was *"same tree, `node_modules` linked, `cloud-run.env` still
absent — if it is still 9, the attribution is clean."* It is still 9.

Detached worktree at `d74f5851`, `LUPIN_ROOT` and `PYTHONPATH` both pinned, the three files
`test_dm_tutor_flash_lite_routing.py` · `test_flash_lite_arm_vertex_markers.py` ·
`test_phi4_flash_lite_replay.py`, **`node_modules` linked in ALL THREE arms** so it is held
constant rather than assumed harmless:

| arm | `cloud-run.env` | `node_modules` | failures | passed | rc |
|---|---|---|---|---|---|
| **A** | linked | linked | **0** | 103 | 0 |
| **B** | **removed** | linked | **9** | 94 | 1 |
| **C** | relinked | linked | **0** | 103 | 0 |

⇒ **`node_modules` was present on the row that gave 9 AND on the rows that gave 0, so it cannot be
a cause of either.** The attribution to `cloud-run.env` is clean, and the obvious
Python-versus-TypeScript mechanism is no longer an unrun arrow — the arm was run rather than
reasoned, which is what § *THE OVERCLAIM HIDES IN THE JOIN* asks for.

⚠️ **ARM C IS A RESTORE CONTROL AND IT IS THE ONE THAT WAS NOT ASKED FOR.** Flipping a variable
once shows an effect; flipping it back shows the effect is **reversible and the tree returned to
its prior state**, which is what rules out *"something else about the tree changed between arms."*
Arm A is also a **positive control for the borrow itself** — 103 passing with the symlink is
`dde8b87a`'s provisioner demonstrably working, measured through the tests rather than through `ls`.

🔴 **THE FINDING IS A CONDITIONAL, NOT A CONSTANT — KEEP `ls`-THEN-DERIVE. THE FILE IS THE
COORDINATE; THE COUNT IS DERIVED FROM IT.** Nothing here makes **9** a number to quote on sight — it
is what this population produces when that one file is missing. `ls src/scripts/cloud-run.env`, then
read the row: readable `⇒ 0` · absent `⇒ 9`. Report presence as **attributes**
(`readable=yes lines=6`), never as the word *present* or *absent*: a condensed message drops a
negation first, and this exact figure was read back inverted twice in one evening before it was sent
as attributes.

🔴 **AND THE ATTRIBUTES MUST BE THE TARGET'S WHEN THE PATH IS A LINK — OTHERWISE THE FORM THAT WAS
SUPPOSED TO BE UNAMBIGUOUS SHIPS A CONFIDENT WRONG NUMBER.** Every worktree gets this file as a
**symlink** (the `dde8b87a` borrow), so a plain `ls -l` reports the **link's** size, which is the
length of its target path:

| what you ran | what it reports |
|---|---|
| `ls -l src/scripts/cloud-run.env` | `lrwxrwxrwx … 75 …` — **75 is the path string's length** |
| `ls -l "$( readlink … )"` | `-rw-rw-r-- … 306 …` — the file |
| `stat -Lc %s` / `wc -l` | `size_bytes=306  lines=6` — the file, via the link |

⇒ **`-L` or `readlink` first, and show BOTH hops.** A single-hop `ls` is how *"75 bytes"* becomes a
fact about a config file that is actually 306. The attribute form removes the **negation** hazard and
does nothing about the **indirection** one, and on this fleet every borrowed artifact is indirect by
construction.

⚠️ **SCOPE OF MY HALF, and it is narrow**: one tree, one sha (`d74f5851`), one moment
(2026-09-05 ~19:56 EDT), three named files, in a worktree created by the **Python spawn path**, which
is why it had the borrow to begin with. It establishes what `node_modules` costs **in this family**
and says **nothing** about what it costs elsewhere — a TypeScript run without it still dies with
`Cannot find package 'tsx'`, a different population. 🔴 **It says nothing about a hand-created
`git worktree add`, which gets no provisioning at all**; that case stays Tiberius 👑's at
`cba072f8` and I did not re-derive it.

⚠️ **His run also carried 4 OTHER failures he identifies as known and unrelated. They are a
different population — do NOT add them to the 9**, and do not read his total as this table's row.

⚠️ **STILL UNMEASURED BY ANYONE, and deliberately left standing**: the terraform row's **1** has
never been re-derived against a tree that HAS the provider cache. That half of the original scope
note is unchanged and still inherited.

⚠️ **SCOPE OF MY OWN HALF.** One tree, one sha, one moment (2026-09-04 19:19–19:32 EDT), on the
PRESENT side of the conditional. The ABSENT side is his, at his sha, in his tree.


---

## The worktree artifacts the tier cannot see — the census, the false fact, the weakened check

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 AND THE WORKTREE ARTIFACTS THE TIER CANNOT SEE — DO NOT ADD THESE TO THE 10/11

The reconciliation above counts **tier failures**. These are the same family — present in the
main checkout, absent from every worktree, gitignored — but **none of them reddens a test in that tier**, so
folding them into that count would corrupt a number this page spent three measurements stabilising.

| what | rule | what it does instead of failing |
|---|---|---|
| `src/lupin_app/static/dist/` — **75 files** in the main checkout, **0 tracked** | `.gitignore:194` | an asset census run in a worktree reports live files as **missing** |
| `<repo-root>/.env`, where the host sets `JWT_SECRET_KEY` | `.gitignore:77` | **`import lupin_app.main` REFUSES** — `jwt_service.py:35` raises at import when the var is unset |
| `<repo-root>/node_modules/` — **215 entries** in the main checkout, **0 tracked** | `.gitignore:193` | a TypeScript run dies with `Cannot find package 'tsx'` — which reads as a broken test, not a missing tree |

🔴 **THE THIRD ONE WAS PROVISIONED BY NOTHING AT ALL** (sam 🎙️, 2026-09-02, who nearly filed his
own environment as a broken test). `link-worktree-venv.sh` supplied the `.venv` from both spawn
creators and **neither it nor anything else supplied `node_modules`**, so a worktree that could run
the Python tier still could not run a single TypeScript file — and the failure named a package
rather than a tree.

✅ **CLOSED 2026-09-04, row `dde8b87a` — `src/scripts/link-worktree-artifacts.sh` now borrows
`node_modules` AND `src/scripts/cloud-run.env`, called from both spawn creators beside the venv
call.** So a freshly SPAWNED worktree is tier-capable on both sides, and the spawn payload carries
an `artifact_alarm` when it is not. ⚠️ **Provisioning still lives in the PYTHON spawn path only, so
a hand-typed `git worktree add` still gets nothing** — run the script yourself in that tree. Guard:
`src/tests/unit/test_the_real_spawn_path_provisions_a_tier_capable_tree.py`, which drives the real
`spawn_sessions` into a real worktree and asserts the link ON DISK; unwire the call site and its two
named tests go red (measured, both directions, restore sha-verified).

⇒ **`INTERPRETER OK` and a TIER-CAPABLE TREE are still different claims** — that is the durable half
and it is why the two provisioners are two fields rather than one. ⚠️ The borrowed links show as
`?? node_modules` in your worktree; that is your link, not content, and a path-scoped commit
excludes it by construction.

🔴 **AND THE SECOND MEMBER IS DELIBERATELY NOT PROVISIONED, WHICH IS NOT AN OVERSIGHT TO FIX.** The
repo-root `.env` carries `JWT_SECRET_KEY` **and `POSTGRES_PASSWORD`** — Mr. Radio's 2026-09-01
ruling on `src/conf/keys/**` governs it for the same reason: a venv is a build artifact, a key is a
secret, and a symlink puts a live credential in a tree that gets `rm -rf`'d. What changed instead is
the REFUSAL: `jwt_service` now appends a sentence naming the worktree you are standing in and the
main checkout that has the file, so the failure stops reading as a setting you forgot. The borrow
list's deny side is pinned by a test with a hand-written forbidden list, so smuggling a key onto it
reddens `test_no_borrowed_path_is_a_secret_or_a_build_output`.

🔴 **THE FIRST IS THE WORST-BEHAVED MEMBER OF THE FAMILY, BECAUSE IT PRODUCES A FALSE *FACT* RATHER
THAN A FALSE *RED*.** Measured 2026-09-02 (Rachel 🕊️): a census of every asset the shells link
reported `parity-harness.js` as a dead 404. The file is **26,015 bytes on disk and the live server
answers 200**. Her classifier had **no logic defect** — it answered correctly about the tree it ran
in, and she reported that answer as a fact about the application.

⇒ **A red gets investigated. A fact gets written into a docstring** — which is where this one was
heading, one merge away, as the stated reason for a test skip.

⚠️ **AND IT FIRED THREE TIMES IN ONE EVENING, ON THREE PEOPLE, THE LAST TWO AFTER READING THE FIRST.**
Rachel's worktree census; then a reviewer's `git check-ignore` sweep that found nothing because the
file is not the variable (below); then María 🌸's own count of `dist/` returning **2 against 75**,
with `parity-harness.js` reported "No such file" — **a shallow `ls` on a directory whose contents sit
one level down in `dist/multiplexer/`.** She was *"one `ls` away from telling you your numbers did not
reproduce."* ⇒ **A query that cannot reach the thing reports its absence as a fact**, and knowing the
rule protects you far less than you would expect: she had read Rachel's instance ten minutes earlier.

🔴 **THE SECOND EXPLAINS WHY NOBODY HIT IT BEFORE: THE TIER IS IMMUNE AND THE ASSEMBLED APP IS NOT**
(sam 🎙️). `src/cosa/tests/conftest.py` does `os.environ.setdefault( "JWT_SECRET_KEY", … )` at
**collection time**, with a comment forbidding its conversion into a fixture — *"fixtures run at
execution time, after the collection-time import that needs it."* So **every worktree tier passes**,
and only something importing `lupin_app.main` **directly** — an end-to-end probe, the assembled-app
check this page keeps asking for — refuses.

⇒ Say that caveat wherever this is listed, **or the next reader will ask why 21,800 passing tests
never noticed.**

⚠️ **AND NOTE HOW IT WAS FOUND, BECAUSE THE OBVIOUS SEARCH FAILS.** A sweep for files naming
`JWT_SECRET_KEY` returns **nothing** — the code reads a **process environment variable**, and `.env`
is merely where this host happens to set it. **Nothing in the repo connects the two.** A sweep for the
KEY finds the reader; a sweep for the FILE finds `.env` only if you already suspect it. ⇒ **The
question that works is not "where is this configured" but "what does the main checkout have that a
worktree does not"** — the same question the `cloud-run.env` row answers, asked in the one direction
that does not require knowing the answer first.

🔴 **AND THAT QUESTION HAS A MECHANICAL ANSWER — STOP EXTENDING THIS LIST ONE INJURY AT A TIME**
(sam 🎙️, 2026-09-02, read-only census at `9efefb5c`). Every artifact above was found by somebody
being bitten by it. They did not have to be. **A fresh worktree contains exactly the tracked files
at that sha ⇒ everything git does not track is, BY CONSTRUCTION, exactly what a worktree lacks.**
The set is computable, not discoverable:

```bash
git ls-files --others --ignored --exclude-standard --directory
```

| stage | count |
|---|---|
| ignored entries in the main checkout | **383,038** |
| after dropping caches, vendored trees, ephemera and logs | **154** |
| config-, credential- or state-shaped | **33** |
| already documented here | 7 |
| **undocumented AND actually reached by code** | **1** |

⇒ **The filter is where the judgement lives, and it is the only place.** The first two steps are
arithmetic; the third is somebody deciding what counts as a cache. Say which you are quoting.

🔴 **AND THE ONE IT FOUND IS A FOURTH SPECIES, NOT A FOURTH INSTANCE — A WEAKENED CHECK THAT
REPORTS SUCCESS.** `src/tests/websocket_smoke/config/baselines/latest_baseline.json` is gitignored
with **0 tracked files in that directory**. It is READ at `smoke_test_runner.py:1190-1194`
— `smoke_test_runner.py:1156` is the SAVE path and was cited here as a read, which it is not —
and reported on at `run-websocket-smoke-tests.sh:302`. Both are **guarded**:

```bash
if [ -f "$baseline_file" ]; then  log_info    "Compared against baseline from: $baseline_time"
else                              log_warning "No baseline file found - comparison may not have been possible"
```

🔴 **AND THE SCOPE IS NARROWER THAN THIS PARAGRAPH FIRST CLAIMED. I went to falsify my own
finding after it merged, and it did not survive intact.** The comparison is **not part of a default
run**: it happens only under `--post-polish`, the one mode that adds `--compare-baseline`
(`run-websocket-smoke-tests.sh:407`, dispatched at `:427`). **A plain worktree run never attempts a
comparison, so it degrades nothing.** The first draft said the suite runs, passes and silently did
less, full stop — that welded a real missing file to a real guarded read without checking whether
the path executes, which is § *THE OVERCLAIM HIDES IN THE JOIN* committed inside the section
reporting it.

⇒ **What survives is still a fourth species, and it is worth the narrower claim: under
`--post-polish` in a worktree the comparison returns `{"status": "no_baseline"}`, logs a WARN, and
the run REPORTS SUCCESS.** Set that beside the three
above and the ranking is uncomfortable:

| species | what it does | who investigates |
|---|---|---|
| a **RED** (`cloud-run.env`) | 9 failures naming the missing variable | everyone |
| a **REFUSAL** (`.env` / `JWT_SECRET_KEY`) | the import raises | everyone |
| a **FALSE FACT** (`static/dist/`) | reports a live file as dead | whoever doubts it |
| 🔴 a **WEAKENED CHECK** (this one) | **passes, having compared nothing** | **nobody** |

**The other three send someone to look. This one does not.** And it is a `:7999` suite — the venue
people genuinely do run from a worktree — so the exposure is ordinary rather than exotic.

⚠️ **AND THE CANDIDATE THAT LOOKED STRONGEST DISSOLVED ON INSPECTION — recorded so nobody re-files
it.** `src/conf/long-term-memory/lupin-auth.db` is gitignored, absent from every worktree, and
carries **8 references in `src/`, 5 of them in tests**. That reads like a live exposure. Every one
is a `tmp_path` or a mocked config: `test_create_api_keys_table.py:48/133/139` build their own,
`test_sqlite_database.py:48/59` feed a mock a string and assert on the string, the rest is README
prose. **Nothing opens the real file**, and the same holds for `lupin-notifications.db`. This is
§ *A HIT IS NOT A USE* firing on the census built to close this family — **the enumeration is
arithmetic, the classification still requires reading the call sites.**

⚠️ **TWO LIMITS, and they are what make the 33 usable rather than quotable:**
- **Nobody has been shown to have taken a reduced websocket result as a pass.** The exposure is
  demonstrated; a victim is not. Hazard, not incident.
- **The 154 is a judgement, not a measured population.** A different notion of "cache" gives a
  different denominator, and the 33 is not claimed to be exhaustive of everything a worktree lacks
  that matters.

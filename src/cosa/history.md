# COSA Development History

### 2026.05.28 - Session 95a47aab (Sam 🎙️) | CoSA wrap of Tiberius 🌑's Extra-N overflow allocator (parent Session 0da441e6)

**Context**: CoSA-context wrap session committing the CoSA-side body of the **Extra-N overflow personas** feature authored by parent-Lupin Session `0da441e6` (Tiberius 🌑, 2026-05-28). Tiberius's Lupin-side commit already landed the parent halves (unit tests in `src/tests/unit/test_voice_persona_helpers.py`, design doc `src/rnd/v0.1.7/2026.05.28-extra-n-overflow-personas.md`, and via parallel commit `908bf21` the INI keys + splainer for the Extra-N color palette), but the CoSA submodule body — the allocator logic itself — was left uncommitted because Lupin-context sessions physically cannot commit the CoSA submodule. Tiberius's Lupin history entry explicitly flagged it: "Managed separately: CoSA submodule `src/cosa/rest/voice_persona_helpers.py` (Extra-N allocator)." This Sam wrap closes that gap per the established CoSA-wrap pattern (cf. Krishna's `b4201d8` for Rio's heartbeat-poker body). Persona: Sam 🎙️ (`G7ILShrCNLfmS0A37SXS`, `#5E35B1` — British male). Branch: `wip-v0.1.7-2026.04.23-tracking-lupin-work`. Commit basis identified by reading parent Lupin `history.md`, `TODO.md`, and `bug-fix-queue.md` per Rick's voice direction at session start.

**CoSA-side body committed** (1 file):

- `rest/voice_persona_helpers.py` (MOD, +183/−17) — generalizes the single-Arnold pool-exhaustion overflow into numbered "Extra N" identities, fixing the latent 2+-overflow collision where concurrent overflow sessions all received the identical Arnold dict and were indistinguishable in the chorus UI. New pieces:
  - `_lowest_free_extra_n( occupied_names )` — stateless lowest-free-index picker (N ≥ 1), gap-reusing so a dead Extra session frees its number for re-use on the next allocation.
  - `_make_extra_persona( base_overflow, n, extra_colors )` — builds a uniquified "Extra N" persona that shares the base overflow voice_id + icon (all speak in Arnold's voice, carry his 🪨 badge) but carries a distinct name/display_name/color. Honest limitation documented in-source: Extras disambiguate the **eye**, not the **ear**.
  - `pick_unallocated_persona(...)` — gained an `extra_colors` param + Arnold-first→Extra-N fallback branch: first overflow hands out Arnold verbatim (unchanged single-overflow case); once Arnold is occupied, additional overflows get the lowest-free Extra-N.
  - `allocate_persona_for_session(...)` — reads the `cc session voice persona extra colors` INI key (cycled by `(n-1) % len`; empty → Extras inherit the overflow color) and threads it through.
  - Smoke test extended: Tests 7a–7f (Arnold verbatim → Extra 1/2, gap-reuse, color cycling, empty-palette fallback) + Test 8 (`_lowest_free_extra_n` unit checks). Two `# pragma: no cover` markers added with same-line rationale (defensive empty-pool guard + CLI entry point).

**Verification**:
- ✅ `py_compile` clean
- ✅ `python -m cosa.rest.voice_persona_helpers` — all smoke tests pass, including the 5 new Extra-N cases
- ✅ No CoSA-side unit test references this file — coverage lives in the Lupin parent (`test_voice_persona_helpers.py`), already committed by Tiberius's session

**Not addressed (deferred, tracked in Lupin TODO.md)**: the green-rule docstring trim (Lupin TODO "Retire-no-green-color-rule sweep" → CoSA item for lines ~301/~423/~513). This diff actually *re-introduces* "Green-rule-compliant palette" wording in the new docstrings; trimming it is a separate CoSA-context task per the standing sweep item, deliberately not folded in here.

**Cross-repo separation**: Per `feedback_session_scope_is_cwd.md` + `feedback_cosa_wrap_commits_all_pending.md`, this CoSA-context wrap commits the pending CoSA-side body. Standing `feedback_never_commit_cosa.md` overridden THIS SESSION ONLY by Rick's explicit voice direction ("use them as the basis for the commits that you'll make after you start the end of session ritual"). The Lupin parent's `history.md` already documents this work (Tiberius's 2026.05.28 entry), so parent history is NOT updated from this session.

**Files** (this session, CoSA repo):
- `rest/voice_persona_helpers.py` (MOD)
- `.claude-session.md` (Session 95a47aab section appended)
- `history.md` (this entry)

**Commit**: `f87666d` (3 files, +251/−17) + [pending hash] (this hash-backfill)

---

### 2026.05.23 - Session 91dcaf1e (Krishna 🦚) | CoSA wrap of Rio ⚡'s heartbeat-poker body (parent Session 76351966)

**Context**: CoSA-context wrap session committing the CoSA-side body of two work items authored by parent-Lupin Session `76351966` (Rio ⚡, 2026-05-22). Rio's Lupin-side commits already landed (`cd37c3f` heartbeat-poker abstraction + TTS limiter; `d58e844` factory-wiring gap-close), but the CoSA submodule body was left uncommitted because Lupin-context sessions physically cannot commit the CoSA submodule. This Krishna wrap closes the gap per the established CoSA-wrap pattern (cf. Rachel's `e582c30` for Tiberius's doc-viewer patch). Persona: Krishna 🦚 (`ogSj7jM4rppgY9TgZMqW`, `#1DE9B6` — reassuring warm male). Branch: `wip-v0.1.7-2026.04.23-tracking-lupin-work`. Commit basis identified by reading parent Lupin `history.md`, `TODO.md`, and `bug-fix-queue.md` per Rick's voice direction at session start.

**CoSA-side body committed** (8 files):

1. **Heartbeat-poker abstraction** — Rio ⚡'s 10-task implementation run of the approved `src/rnd/v0.1.7/2026.05.20-generic-heartbeat-poker-abstraction-design.md` plan:
   - `agents/heartbeat_poker_job.py` (NEW) — `HeartbeatPokerJob` `AgenticJobBase` subclass with three layered exits (clean-signal / dead-man's-switch / hard-cap)
   - `agents/heartbeat_poker_commons_gateway.py` (NEW) — `LupinCommonsGateway` adapter + `from_environment()` constructor (IO-boundary)
   - `tests/unit/agents/test_heartbeat_poker_job.py` (NEW) — 36 unit tests
   - `tests/unit/agents/test_heartbeat_poker_commons_gateway.py` (NEW) — 14 gateway unit tests
   - `tests/smoke/test_heartbeat_poker_smoke.py` (NEW) — 9 smoke tests

2. **CJ Flow ingestion wiring (gap-close)** — Rio ⚡'s follow-on after surfacing the gap mid-run:
   - `rest/agentic_job_factory.py` (MOD) — added `agent router go to heartbeat poker` branch with recipients/termination-kinds parsing and `_parse_optional_int` defaults
   - `tests/unit/rest/test_agentic_job_factory_heartbeat.py` (NEW) — 11 factory-wiring unit tests

3. **TTS limiter boundary-scan cleanup** — Rio ⚡'s same-session TTS fix:
   - `rest/routers/system.py` (MOD) — removed vestigial `tts_preview_include_semicolons` config key (splainer-side removal already shipped Lupin-side in `cd37c3f`)

**Verification**:
- ✅ 78/78 heartbeat-poker tests pass (`pytest tests/unit/agents/test_heartbeat_poker_{job,commons_gateway}.py tests/unit/rest/test_agentic_job_factory_heartbeat.py tests/smoke/test_heartbeat_poker_smoke.py` — 0.88s)
- ✅ py_compile clean on all 2 modified + 2 new source files
- ✅ Both heartbeat modules hold gate-enforced 100% line+branch coverage per Rio's prior verification

**Cross-repo separation**: Per `feedback_session_scope_is_cwd.md` + `feedback_cosa_wrap_commits_all_pending.md`, this CoSA-context wrap commits ALL pending CoSA-side body regardless of authoring Lupin session. Standing `feedback_never_commit_cosa.md` overridden THIS SESSION ONLY by Rick's explicit voice direction ("use them as the basis for the commits that you'll make after you start the end of session ritual").

**Files** (this session, CoSA repo):
- `agents/heartbeat_poker_job.py` (NEW)
- `agents/heartbeat_poker_commons_gateway.py` (NEW)
- `tests/unit/agents/test_heartbeat_poker_job.py` (NEW)
- `tests/unit/agents/test_heartbeat_poker_commons_gateway.py` (NEW)
- `tests/smoke/test_heartbeat_poker_smoke.py` (NEW)
- `rest/agentic_job_factory.py` (MOD)
- `tests/unit/rest/test_agentic_job_factory_heartbeat.py` (NEW)
- `rest/routers/system.py` (MOD)
- `.claude-session.md` (Session 91dcaf1e section appended)
- `history.md` (this entry)

**Commits**:
- `b4201d8` — heartbeat-poker CoSA-side body (8 files, +1,592/-9)
- [pending hash] — daily LoC delta CSV refresh + manifest hash backfill + global-sweep section

#### Global LoC delta sweep — 2026-05-22 → 2026-05-23

Per Rick's voice direction at session start ("run the global GitHub-LOC-Deltas analysis for the day that is Friday May 22 until Saturday May 23 until 12:40 AM EST"). Aggregator: `cosa.repo.run_git_loc_delta_global` (Rachel's CLI from session `e13fed4f`).

**Window**: 2026-05-22 → 2026-05-23 (date-granularity filter — captures Friday's work day plus all of Saturday May 23 commits; broader than the spoken 12:40 AM EDT cutoff because git_loc_delta operates at date granularity, not timestamp granularity).

**Totals**: **+4,900 / -165 lines (net +4,735), 16 commits, 2 days across 3 active repos.**

| Date       | Repo                  | Added | Deleted | Net    | Commits |
|------------|-----------------------|-------|---------|--------|---------|
| 2026-05-22 | lupin                 | 2,278 | 145     | +2,133 | 9       |
| 2026-05-22 | cosa                  | 5     | 1       | +4     | 2       |
| 2026-05-23 | cosa                  | 1,592 | 9       | +1,583 | 2       |
| 2026-05-23 | planning-is-prompting | 975   | 2       | +973   | 1       |
| 2026-05-23 | lupin                 | 50    | 8       | +42    | 2       |

Artifacts (live in **Lupin** parent's `io/loc-delta-global/` per scope-separation):
- `global-2026-05-22_to_2026-05-23-loc-delta.csv` (12 rows)
- `global-2026-05-22_to_2026-05-23-plot.png` (two-panel matplotlib)

---

### 2026.05.21 - Session e13fed4f (Rachel 🕊️) | git_loc_delta v1.1 — per-branch `--plot` + schema v2 + cross-repo aggregator CLI

**Context**: CoSA-context session with a substantive code body (unlike the recent docs-only wraps `eecda1c9` / `a9af9d81`). Persona: Rachel 🕊️ (`21m00Tcm4TlvDq8ikWAM`, `#CE93D8` — calm & clear female). Branch: `wip-v0.1.7-2026.04.23-tracking-lupin-work`. Extends María 🌸's `git_loc_delta` package (originally session `3c9fce51`, 2026-05-16) with plotting + cross-repo aggregation. Designed across 9 commons DMs with María 🌸 (PIP session `d66169f2`) using the parallel-R&D-docs handshake; Rick ratified the schema-scope expansion ("EXPAND FULL") via `ask_multiple_choice`. Commit basis identified by reading parent Lupin `history.md`, `TODO.md`, and `bug-fix-queue.md` per user voice direction.

**Accomplishments**:

- **Per-branch tool v1.1** — `git_loc_delta` extended with a `--plot` flag producing a two-panel matplotlib PNG (top: aggregate insertions/deletions bars + net line; bottom: signed per-file-type net lines). New `plotter.py` is library-shape — `plot_summary(daily, summary, output_path, group_by, title_meta)` takes pre-aggregated dicts and a `group_by` parameter (`file_type` for per-branch, `repo` for the global variant) so the rendering layer is reused with zero duplication.
- **CSV schema v2** — `csv_writer.py` extended with explicit `repo` + `branch` columns (was `date,file_type,added,deleted,files_touched,commits`; now prefixed with `repo,branch`). New `write_sidecar()` emits `{csv}.meta.json` carrying immutable run metadata (`csv_schema_version`, `repo`, `branch`, `rev_range`, `since`, `until`, `generated_at`). Maria's consumer-side asks; enables cross-repo `pd.concat` aggregation without filename parsing.
- **Cross-repo aggregator CLI** — NEW `run_git_loc_delta_global.py` aggregates per-repo CSVs into a global daily roll-up (console / JSON / CSV / PNG via `plot_summary(group_by="repo")`). Schema-v1 backward-compat: legacy CSVs without `repo`/`branch` columns get identity injected from sidecar-or-filename. Today-default window (Maria's §7.4 ratification). Discovery is explicit `--repos PATH ...` (INI auto-discovery deferred indefinitely per Rick).
- **CLI flags** — `run_git_loc_delta.py` gained `--plot`, `--plot-output`, `--repo-name`; refactored git-toplevel resolution into shared `_resolve_target_root` / `_resolve_repo_name` helpers.
- **Docs** — `README.md` v1.1 callout + plot section + schema v2 docs; `rnd/2026.05.16-daily-loc-delta-tool.md` Plot extension section; NEW companion R&D doc `rnd/2026.05.21-cross-repo-loc-delta-aggregator-cli.md` cross-referencing María's PIP-side rollup design (PIP commit `9cdd781`).

**Verification**: 25/25 smoke tests green — 12 aggregator (`run_git_loc_delta_global`), 6 plotter, 7 analyzer (existing test still passes — schema v2 bump did not regress). `py_compile` clean on all 5 modified + 2 new `.py` files. Live integration: CoSA branch (42 CSV rows + sidecar + plot), Lupin branch (147 rows + plot), 3-repo + 5-repo global roll-ups (today-default and 7-day windowed).

**Cross-session collaboration**: María 🌸 (PIP `d66169f2`) authored the PIP-side workflow doc + `/plan-loc-delta-global` slash command + confirmation gate (PIP commits `9cdd781` + `e0ac3aa` + `f054d02`). Tiberius 🌑 (Lupin `bc15c374`) shipped a doc-viewer joint patch earlier this session enabling PNG rendering in the doc viewer.

**Cross-repo separation**: Per `feedback_lupin_only_never_cosa.md` + `feedback_session_scope_is_cwd.md` + `feedback_never_commit_cosa.md` (overridden THIS SESSION ONLY by Rick's explicit voice "the commits that you're going to make" direction). This CoSA-context session commits ONLY files it authored under `src/cosa/`. `rest/routers/docs_files.py` + `rest/routers/pages.py` appear modified in `git status` but are **Tiberius's doc-viewer joint patch** — NOT in this session's manifest Touched Files; explicitly EXCLUDED from this commit. Tiberius's session owns those. The Lupin-parent `TODO.md` Tiberius-emoji entry (added under separate explicit Rick authorization) is a Lupin-context change, not committed here.

#### Checkpoint | 2026.05.21 PM EDT | Session e13fed4f wrap

**Files** (this session, CoSA repo — this commit):
- `repo/git_loc_delta/plotter.py` (NEW)
- `repo/git_loc_delta/csv_writer.py` (MOD — schema v2 + sidecar)
- `repo/git_loc_delta/analyzer.py` (MOD — repo_name plumbing)
- `repo/git_loc_delta/__init__.py` (MOD — v1.1.0 + plot_summary export)
- `repo/git_loc_delta/README.md` (MOD — v1.1 docs)
- `repo/run_git_loc_delta.py` (MOD — --plot/--plot-output/--repo-name)
- `repo/run_git_loc_delta_global.py` (NEW — cross-repo aggregator)
- `rnd/2026.05.16-daily-loc-delta-tool.md` (MOD — Plot extension section)
- `rnd/2026.05.21-cross-repo-loc-delta-aggregator-cli.md` (NEW — companion R&D doc)
- `io/git-loc-delta/cosa-wip-v0.1.7-2026.04.23-tracking-lupin-work-loc-delta.csv` (MOD — schema v2 regen) + `.meta.json` (NEW — sidecar)
- `history.md` (this entry)

**Commits** (4 — all pushed to `github.com:deepily/cosa.git`):
- `f6f8ea0` — git_loc_delta v1.1 + cross-repo aggregator CLI (12 files, +2,189/-142)
- `3d82147` — manifest status-flip + hash backfill
- `e582c30` — doc-viewer PNG-rendering joint patch (`docs_files.py` + `pages.py` — Tiberius 🌑's CoSA-side work; committed by this CoSA wrap because Lupin-context sessions cannot commit the CoSA submodule)
- `baded1f` — git_loc_delta v1.1 dogfood artifacts (3 plot PNGs + design prototype)

---

### 2026.05.20 PM - Session eecda1c9 (Mr. Radio 🦉) | CoSA-context lightweight session-end wrap — daily LoC delta dogfood + history + manifest only (no code body)

**Context**: CoSA-context session-end ritual with NO code work to wrap. Persona: Mr. Radio 🦉 (`Aa6nEBJJMKJwJkCx8VU2`, `#FFA000` — authoritative warm male; third CoSA wrap on this branch after `99fbada3` 2026-05-13 PM + `af54bb12` 2026-05-17 PM). Branch: `wip-v0.1.7-2026.04.23-tracking-lupin-work`. Two-commit wrap (B: session-end docs + daily LoC delta + summary doc, C: manifest hash backfill) — Commit A is omitted because no thematic code body landed in CoSA today. The deliverable IS the ritual artifacts. Commit basis identified by reading parent Lupin `history.md`, `TODO.md`, and `bug-fix-queue.md` per user voice direction at session start ("look at the history to-do and bug tracking list in the Lupin repo and use that as the basis for the commits ... You can push and make sure that you run the Git deltas for the day"). Push authorized.

**Why no code body today**: All CoSA-touching work on 2026-05-20 happened parent-side in Lupin context. Tiberius 🌑 session `173c0b35` shipped two commits today (`e726b64` Session-end + `c9db97c` Checkpoint) wrapping the Phase 7a Run-4 post-game convergence, Rachel's persona-resuscitation bundle (preferred-persona env forwarding + Roscoe → Tiffany rename + LookML allocation diagnostic), and the heartbeat-poker design WIP. None of those touched files inside `src/cosa/`. CoSA's working tree at session start: clean (last CoSA commit was Roscoe 🤠 `a9af9d81`'s wrap from 2026-05-19 PM that crossed UTC midnight into 2026-05-20 — three commits `afe9ff1` + `74075cc` + `e433278`).

**Daily LoC delta dogfood artifacts** (per user voice direction: "make sure that you run the Git deltas for the day"): four artifacts produced by `cosa.repo.git_loc_delta` across both repos:

- `io/git-loc-delta/2026-05-20-loc-delta.csv` (CoSA today — 3 rows capturing Roscoe's UTC-midnight-crossing wrap commits: python 521/-73, markdown 262/-5, other 4/-0; net +709 across 7 files / 3 commits)
- `io/git-loc-delta/cosa-wip-v0.1.7-2026.04.23-tracking-lupin-work-loc-delta.csv` (CoSA branch — REFRESHED to 42 rows; 20 days alive / 82 commits / +13,663 net since 2026-04-24 first commit)
- `rnd/2026.05.20-session-eecda1c9-loc-summary.md` (NEW R&D doc mirroring Roscoe `a9af9d81` precedent; ~140 LOC): §1 today Lupin (+287 net / 2 commits / 13 files / 5 file types — Tiberius's heartbeat + persona-resuscitation), §2 today CoSA (+709 net / 3 commits / Roscoe wrap UTC-midnight crossover), §3 weekly summary 2026-05-14..2026-05-20 (Lupin +31,663 net / 63 commits; CoSA +5,845 net / 18 commits; combined +37,508 / 81), §4 branch-wide (Lupin 28 days / 244 commits / +160,203 net; CoSA 27 days / 82 commits / +13,663 net), §5 commit plan headline (2-commit bundle), §6 persona-attribution footnote
- Lupin-side equivalent CSVs (`io/git-loc-delta/2026-05-20-loc-delta.csv` + `io/git-loc-delta/lupin-wip-...-loc-delta.csv`) saved to Lupin tree via `--save-output` (gitignored under Lupin's `.gitignore` per the `git_loc_delta --save-output` cross-repo path entry filed by Tiberius `b714e138` 2026-05-16 — not committed; for local reference only)

**Cross-repo separation**: Per `feedback_lupin_only_never_cosa.md` + `feedback_session_scope_is_cwd.md`, this CoSA-context session ONLY touches files under `src/cosa/`. Parent Lupin work from Tiberius `173c0b35` (heartbeat-poker design WIP + Rachel's persona-resuscitation + Run-4 post-game TODO close + Lupin history.md update + `start-cc-with-tmux.sh` env var forwarding + Roscoe → Tiffany rename + LookML diagnostic prints in `register_session.py`) is owned by the parent Lupin context and ALREADY landed via commits `e726b64` + `c9db97c`. Lupin parent working tree at session start: clean.

**Memory rules engaged**: `feedback_session_scope_is_cwd` (cwd `…/lupin/src/cosa` → CoSA is this session's scope), `feedback_never_commit_cosa` (overridden THIS SESSION ONLY by Rick's explicit voice "the commits that you're going to make" + "you can push" direction), `feedback_verify_repo_before_commit` (`git status` showed CoSA clean + `git branch --show-current` confirmed `wip-v0.1.7-2026.04.23-tracking-lupin-work` before staging-adjacent action), `feedback_lupin_only_never_cosa` (parent Lupin work already shipped by parent context; CoSA-side ritual is this commit only).

#### Checkpoint | 2026.05.20 PM EDT | Session eecda1c9 wrap-session — push authorized post-Commit-C

**Files** (this session, CoSA repo):
- `history.md` (this entry)
- `.claude-session.md` (Session eecda1c9 section appended + Commit B hash backfilled post-commit + status flipped to `committed`)
- `io/git-loc-delta/2026-05-20-loc-delta.csv` (NEW — daily)
- `io/git-loc-delta/cosa-wip-v0.1.7-2026.04.23-tracking-lupin-work-loc-delta.csv` (REFRESHED — branch)
- `rnd/2026.05.20-session-eecda1c9-loc-summary.md` (NEW — LoC summary R&D doc)

**Commit hashes**: `<B-hash>` (Commit B — session-end docs + LoC delta CSVs + summary doc), `<C-hash>` (Commit C — manifest hash backfill + status flip). Push to `origin` authorized by Rick's voice direction post-Commit-C ("you can push").

---

### 2026.05.19 PM - Session a9af9d81 (Roscoe 🤠) | CoSA-side wrap of parent Tiberius `4e724860` voice-persona work: env-var preferred-persona allocator + pool expansion + Sam↔Arnold overflow swap (single interlocked thematic bundle)

**Context**: CoSA-context session-end commit bundle wrapping a single interlocked body of CoSA-side work produced by parent Lupin session `4e724860` (Tiberius 🌑) across 2026-05-19 (Lupin commits `3bc7b9e` Preferred-persona env-var allocator 13:30 EDT + `f78e81c` Voice persona pool expansion + Sam↔Arnold role swap 14:25 EDT). Persona: Roscoe 🤠 (`DXX4Q5Bh1vqK8CciYVPf`, `#FFD600` — upbeat professional female; new pool member added 2026-05-19 by parent Tiberius's pool expansion). Branch: `wip-v0.1.7-2026.04.23-tracking-lupin-work`. Three-commit wrap (A: voice_persona bundle, B: session-end docs + daily LoC delta + summary doc, C: manifest hash backfill) per `feedback_lupin_only_never_cosa.md` cross-repo separation and `feedback_never_commit_cosa.md` AI-prepares-user-commits separation OVERRIDDEN this session by Rick's explicit voice direction ("use them as the basis for the commits that you'll make"). Mirrors prior Session 60d767ef Rachel / af54bb12 Mr. Radio / 99fbada3 Mr. Radio wrap patterns. Commit basis identified by reading parent Lupin `history.md`, `TODO.md`, and `bug-fix-queue.md` per user voice direction at session start ("Read the contents of the history to-do and bug queue documents in the Lupine repo and use them as the basis for the commits ... You can push after you run your daily git loc delta analysis that starts at 1 AM this morning and ends now, just before midnight").

**Body 1 — Voice persona env-var preferred-persona allocator + pool expansion + Sam↔Arnold overflow swap (CoSA-side)** (parent Tiberius 🌑 session `4e724860` 2026-05-19; references parent Lupin `history.md` §§ "Per-repo preferred-persona env-var allocator — Lupin-side implementation + 7 unit tests" + "Voice persona pool expansion — +2 personas, Sam→pool / Arnold→overflow swap, generalized overflow loader"; design doc `planning-is-prompting/src/rnd/2026.05.19-cosa-voice-preferred-persona-env-var.md` for the env-var body; cross-ref `src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md` for the overflow body now generalized).

Three logically-coupled changes to two files committed as a single thematic bundle — splitting would slice through cohesive code that imports across both files.

- **`rest/voice_persona_helpers.py` (MOD +~285 / -~22 LOC)** — three additions:
  - **(a)** `load_overflow_persona_from_config()` **generalized** (~50 LOC of changes): was Sam-hardcoded reading `elevenlabs tts default voice id` only; now reads new `cc session voice persona overflow name` INI key (default `"sam"` for backward compat) and looks up that persona's pool-style INI keys generically. Backward-compat branch: when overflow_name resolves to "sam" AND no explicit `cc session voice persona sam voice id` key is present, falls back to `elevenlabs tts default voice id` (preserves byte-clean behavior for legacy configs that predate today's Sam-to-pool promotion). Updated Design-by-Contract docstring documenting both the new config-driven mechanism and the backward-compat fallback. Enables today's pool-side Sam promotion (explicit `voice id` key + green-rule-compliant deep-purple color `#5E35B1`) + demotion of Arnold to overflow (via the new `overflow name` INI key) without any code change.
  - **(b)** **Requested-persona allocation primitives** (NEW ~165 LOC) — three functions backing Arnold's pre-existing 42-test request-or-swap slash-command path: `_find_persona_in_pool(pool, requested_name)` does case-insensitive lookup against both pool-key and display_name forms; `pick_requested_persona(pool, occupied_to_session_id, requested_name)` returns `{status: ok|not_in_pool|occupied, persona|None, available, holding_*}` (caller-supplied occupied map keeps the helper pure — no `session_bridge` dependency); `allocate_requested_persona_for_session(config_mgr, stable_session_id, requested_name)` is the end-to-end orchestration that EXCLUDES the requesting session's own current allocation from the occupied scan (the exclude-self semantics is what makes swap semantics work — "I currently hold Arnold, give me María" must not see Arnold as occupied). Stamps `assigned_at` UTC ISO-8601 on success.
  - **(c)** **Per-repo env-var preferred-persona helper** (NEW `pick_preferred_persona_from_env(project)` ~25 LOC, plus new `os` import): reads `COSA_VOICE_PREFERRED_PERSONA__<PROJECT_UPPER>` from the environment with normalization (lowercase→UPPER, hyphens→underscores, empty/None tolerated). Returns the raw string verbatim — the caller's `_find_persona_in_pool` handles case-insensitive + display-name match. Doesn't validate against any pool. Rick's two target defaults per the design doc: `__PLAN=María` and `__LUPIN=Tiberius`.

- **`rest/routers/voice_persona.py` (MOD +~200 / -~45 LOC)** — corresponding `POST /api/cosa-voice/voice-persona/{session_id}/allocate` endpoint extension. New `requested_persona_name` (strict 422/409 path) + `preferred_persona_name` (soft-fallback path) query params with mutual exclusion. Three operating modes in the no-strict-request path covering `/clear`-preserves contract (Path A — env var applies at FIRST allocation only). Strict request-or-swap path with `swapped=True` flag on success. New `voice_persona_conflict` notification (option α inline per Rick's §8 decision 1) pushed when soft-preference falls back. "Voice re-assigned: X → Y" announcement extended to fire for BOTH the hook's `previous_persona_name` AND bridge-side detected swap. Response payload extended with `swapped: bool` + `preference_conflict: Optional[dict]`.

**Verification** (this session):
| Tier | Result |
|---|---|
| `py_compile rest/voice_persona_helpers.py` + `py_compile rest/routers/voice_persona.py` | ✅ 2/2 OK |
| Import chain via cosa venv — 4 new symbols (`pick_preferred_persona_from_env`, `allocate_requested_persona_for_session`, `pick_requested_persona`, `_find_persona_in_pool`) | ✅ all importable from `cosa.rest.voice_persona_helpers` |
| Parent-side test coverage (per parent Lupin `history.md`) — Arnold's 42 pre-existing slash-command tests + Tiberius's 7 new env-var tests (`test_voice_persona_request.py`) + 52 helpers regression (`test_voice_persona_helpers.py`) | ✅ 101/101 PASS in 2.5s, zero regressions |

**Daily LoC delta dogfood artifacts** (this session, per user voice direction: "run your daily git loc delta analysis that starts at 1 AM this morning and ends now, just before midnight"): four artifacts produced by `cosa.repo.git_loc_delta` in daily + branch modes across BOTH Lupin parent and CoSA submodule:

- `io/git-loc-delta/2026-05-19-loc-delta.csv` (CoSA today — 0 commits today, last commit was 2026-05-17 `410b645` Mr. Radio af54bb12 wrap; empty CSV documents the empty window honestly)
- `io/git-loc-delta/cosa-wip-v0.1.7-2026.04.23-tracking-lupin-work-loc-delta.csv` (CoSA branch — REFRESHED; 79 commits since 2026-04-24 = 26 days, 17,160 added / 4,206 deleted = net +12,954)
- `rnd/2026.05.19-session-a9af9d81-loc-summary.md` (NEW R&D doc mirroring Rachel 60d767ef / Mr Radio af54bb12 precedent): today's 10 commits across Lupin (+10,896 / -127 = net +10,769 across 53 files, predominantly Tiberius `4e724860` + Roscoe `b4623e3d` Phase 6c + Mr. Radio `32a6e563` Phase 7 + Tiberius `387b9201` Phase 7a Run 4); zero CoSA activity today; weekly summary (2026-05-13 → 2026-05-19, both repos: Lupin +43,682 net / 84 commits, CoSA +6,083 net / 20 commits); branch-wide summary (Lupin 27 days / 242 commits / +159,916 net; CoSA 26 days / 79 commits / +12,954 net); §5 documents a `--today` mode quirk surfaced today (git's bare-date `--since 2026-05-19` interpretation silently excludes today's commits, workaround `--since 2026-05-18 --until 2026-05-19`); §7 Roscoe persona-attribution footnote.
- Lupin-side equivalent CSVs (`io/git-loc-delta/2026-05-19-loc-delta.csv` + `io/git-loc-delta/lupin-wip-...-loc-delta.csv`) gitignored under Lupin's `.gitignore` (per the bug-fix-queue `git_loc_delta --save-output` cross-repo path entry filed by Tiberius `b714e138` 2026-05-16); used `--save-output` workaround to direct output to the correct Lupin tree.

**Cross-repo separation**: Per `feedback_lupin_only_never_cosa.md`, this CoSA-context session ONLY touches files under `src/cosa/`. Body 1's parent Lupin work — `src/lupin_cli/claude_code/hooks/register_session.py` MOD (env var read + threading through `_allocate_voice_persona_via_http`), `src/tests/unit/test_voice_persona_request.py` (Arnold's 42 pre-existing tests + Tiberius's 7 new = 49 total), `src/conf/lupin-app.ini` pool expansion (Roscoe + Krishna full blocks + Sam block rewrite + new `overflow name` key + Rachel lilac color shift), `src/conf/lupin-app-splainer.ini` paired splainer entries — owned by parent Lupin context and ALREADY landed via Tiberius session `4e724860`'s commits `3bc7b9e` + `f78e81c`. Tiberius's Lupin-parent working-tree edits from later in the session (Phase 6c synthesis docs + Phase 7 planning + Phase 7a Telemetry cascade) — left in Lupin WT for the appropriate Lupin-context session to commit per the cwd-scope rule.

**Memory rules engaged**: `feedback_session_scope_is_cwd` (cwd `…/lupin/src/cosa` → CoSA is this session's scope), `feedback_never_commit_cosa` (overridden THIS SESSION ONLY by Rick's explicit voice "make the commits" + "you can push" direction), `feedback_verify_repo_before_commit` (`git rev-parse --show-toplevel` confirmed CoSA + `git branch --show-current` confirmed wip-v0.1.7-2026.04.23-tracking-lupin-work before staging-adjacent action), `feedback_lupin_only_never_cosa` (parent Lupin work for Body 1 already shipped by parent context; CoSA-side mirror is this commit only).

#### Checkpoint | 2026.05.19 23:55 EDT | Session a9af9d81 wrap-session — push authorized post-Commit-C

**Files** (this session, CoSA repo): rest/voice_persona_helpers.py (Body 1 MOD +~285/-~22), rest/routers/voice_persona.py (Body 1 MOD +~200/-~45), history.md (this entry), .claude-session.md (Session a9af9d81 section appended + Commit A hash backfilled), io/git-loc-delta/2026-05-19-loc-delta.csv (NEW — daily, 0 rows because no CoSA commits today), io/git-loc-delta/cosa-wip-v0.1.7-2026.04.23-tracking-lupin-work-loc-delta.csv (REFRESHED — branch), rnd/2026.05.19-session-a9af9d81-loc-summary.md (NEW LoC summary R&D doc).

**Commit hashes**: `afe9ff1` (Commit A — voice_persona bundle), `<B-hash>` (Commit B — session-end docs), `<C-hash>` (Commit C — manifest hash backfill). Push to `origin` authorized by Rick's voice direction post-Commit-C.

---

### 2026.05.17 PM - Session af54bb12 (Mr. Radio 🦉) | CoSA-side wrap of 2 thematic bodies: Tiberius's history archive carryover + Q8 unicode-broaden of DM topic regex

**Context**: CoSA-context session-end commit bundle wrapping two distinct bodies of CoSA-side work produced earlier on 2026-05-17. Persona: Mr. Radio 🦉 (`Aa6nEBJJMKJwJkCx8VU2`, #FFA000 — authoritative warm male). Branch: `wip-v0.1.7-2026.04.23-tracking-lupin-work`. Four-commit wrap (A: history archive carryover, B: Q8 unicode-broaden, C: session-end docs + LoC dogfood artifact, D: manifest hash backfill) per `feedback_lupin_only_never_cosa.md` cross-repo separation and `feedback_never_commit_cosa.md` AI-prepares-user-commits separation, mirroring prior Session 60d767ef Rachel / 99fbada3 Mr. Radio / 1fb80a1c María wrap patterns. Commit basis identified by reading parent `history.md`, `TODO.md`, and `bug-fix-queue.md` per user voice direction at session start ("read the history, to-do, and bug tracker in the Lupin repo and use that as the basis for the commits").

**Commits Planned** (Plan B — 3 commits, ratified by user voice 2026-05-17 PM; per `feedback_never_commit_cosa.md`, AI prepares everything and stops at "ready for your workflow"; user runs the actual `git add` / `git commit`):
- `<A-hash>` — Commit A: history.md (combined Tiberius archive + Mr. Radio wrap entry) + `history/2026-04-25-to-05-13-history.md` NEW archive file
- `<B-hash>` — Commit B: Q8 unicode-broaden of `_TOPIC_OR_QID_PATTERN` (parent Lupin Session 9ea36cbe Mr Radio executor (Lupin commit `865c69a` wrapper-side helper + migration script), dispatched by Tiberius 225e5b2d coordinator)
- `<C-hash>` — Commit C: `.claude-session.md` (this manifest section with hashes backfilled) + `io/git-loc-delta/cosa-wip-*.csv` dogfood artifact

Plan B trade-off accepted: blended Tiberius+Mr.Radio attribution in history.md's single commit, recovered via the combined Commit A message naming both sessions. Avoids the `git add -p history.md` piecewise stage that Plan A would have required.

**Body 1 — CoSA history.md archive carryover** (CoSA-context: Session 2d916480 Tiberius 🌑 earlier today 17:03→17:55 EDT; references parent Lupin `TODO.md` § "✅ DONE 2026-05-17 AM — history.md archive" priority-1 closure)

Tiberius's single-deliverable CoSA session executed the CoSA history.md archive mirroring the same-day Lupin priority-1 deferred archive (which Tiberius had also executed against Lupin parent earlier in the session before Rick's cwd-scope-rule clarification — those Lupin edits live in the Lupin working tree out of CoSA scope). CoSA-side metrics: 41,269 tok pre-archive → 9,057 tok post-archive (78% reduction). Cut at line 154 (start of 2026.05.13 PM Mr. Radio wrap-session). Followed shape-aware heuristic — CoSA wrap-granularity (one CoSA-session per cluster of related Lupin commits) suggested retaining the 2 most-recent wrap-sessions matches Lupin's "retain most-recent activity bundle" semantics. Token-based fallback per canonical workflow Priority 4 (5-day retention minimum infeasible at this density).

- **`history.md` (TRIM)** — 963 → 153 lines pre-Tiberius-entry, then Tiberius's own session entry added at top per Step 1 of session-end ritual
- **`history/2026-04-25-to-05-13-history.md` (NEW)** — 820 lines / 32,450 tok / 15 wrap-sessions archived (2026-04-25 to 2026-05-13)

Per Tiberius's manifest section (Session 2d916480, below in this file's `.claude-session.md` companion), this work was left in "ready for your workflow" state pending the wrap. This session lands it as Commit A.

**Body 2 — Q8 unicode-broaden of `_TOPIC_OR_QID_PATTERN`** (parent Lupin: Session 225e5b2d Tiberius 🌑 2026-05-17 coordinator dispatch; references parent Lupin `history.md` § "Session 225e5b2d (Tiberius 🌑) | Coordinator dispatch + Phase 5 unit tests + 100% coverage on model-server carve-out" § Q-decisions block — specifically Q8 "(a) unicode all the way down to INI config — persona keys use exact spelling")

Tiberius's coordinator dispatch session on 2026-05-17 ran 13 Q-decisions with Rick. Q8 was one of two binding clarifications: unicode persona keys must be preserved verbatim in DM topic names — `dm-maría` (Latin diacritic), `dm-井上` (CJK), `dm-π` (Greek) should all round-trip exactly as the persona spells their name. The Lupin-side mirror was shipped in parent commit `b550f10` adjacent work (`src/lupin_mcp/cosa_voice_mcp.py:_derive_dm_topic` at line 2154 + call site at line 2318). The CoSA-side mirror landed in this WT — the Pydantic-native regex constraint on `topic` and `question_id` fields needed broadening so 422-validation doesn't reject unicode personas at the server boundary.

- **`rest/routers/commons.py` (MOD, 1 LOC + 5 explanatory comment lines)** — `_TOPIC_OR_QID_PATTERN` regex change at line 100. BEFORE: `r"^[A-Za-z0-9_-]+$"` (ASCII-only). AFTER: `r"^[\w-]+$"` (Python `\w` is unicode-aware by default in Py3, matching letters/digits in any script + underscore; literal `-` outside any character-class shortcut). Path-dangerous characters (path separators, control chars, whitespace) remain excluded because `\w` does not match them. Comment block added documenting the Q8 ratification reference, the unicode rationale, the path-safety contract, and the paired wrapper line in `cosa_voice_mcp.py`.

**Verification** (inline, this session):
| Tier | Result |
|---|---|
| `py_compile rest/routers/commons.py` | ✅ OK |
| Regex contract — 10 unicode + path-sep cases | ✅ **10/10 pass** — `dm-maría`, `dm-Tiberius`, `dm-井上`, `dm-π`, `topic_with_under`, `topic-with-dash` all match; `dm-foo/bar`, `dm-foo bar`, empty string all blocked |
| Paired wrapper presence (`_derive_dm_topic` in Lupin `cosa_voice_mcp.py:2154` + call at `:2318`) | ✅ confirmed shipped Lupin-side |

**LoC delta dogfood artifacts** (this session, per user voice direction at session-end: "don't forget to do your daily and weekly stats for this branch"): three artifacts produced by `cosa.repo.git_loc_delta` in daily + weekly + branch modes across BOTH Lupin parent and CoSA submodule:
- `io/git-loc-delta/cosa-wip-v0.1.7-2026.04.23-tracking-lupin-work-loc-delta.csv` — branch-mode CSV, 36 rows, full CoSA branch history (76 commits, 86 files, +15,907/-3,394 = net +12,513 LoC over 18 active days)
- `io/git-loc-delta/2026-05-17-loc-delta.csv` — date-stamped weekly CSV, 10 rows, 2026-05-12 → 2026-05-17 (22 commits, 39 files, +7,418/-740 = net +6,678 LoC)
- `rnd/2026.05.17-session-af54bb12-loc-summary.md` — NEW R&D doc mirroring Rachel 60d767ef's Commit F summary pattern from 2026-05-16: today's commit-by-commit table (Lupin: 5 commits, +6,576 net; CoSA: 0 commits today, all uncommitted), weekly summary across both repos (Lupin: 88 commits, +45,398 net; CoSA: 22 commits, +6,678 net), branch-wide summary (Lupin: 228 commits, +146,360 net since 2026-04-23; CoSA: 76 commits, +12,513 net since 2026-04-24), session af54bb12 uncommitted delta breakdown, Plan B commit plan, and §6 Q8-cascade headline (wrapper-side Lupin `865c69a` + CoSA-side regex this session + INI config side preserved verbatim).

Committed alongside session-end manifest in Commit C.

**Cross-repo separation**: Per `feedback_lupin_only_never_cosa.md`, this CoSA-context session ONLY touches files under `src/cosa/`. Q8's parent Lupin work (`src/lupin_mcp/cosa_voice_mcp.py:_derive_dm_topic` + `INI` config preservation) — owned by parent Lupin context, shipped per Lupin Session 225e5b2d's coordinator dispatch. Tiberius's Lupin-parent history archive earlier today (Lupin `history.md` trim + new `history/2026-05-12-to-15-history.md` + index + TODO marker) — left uncommitted in Lupin WT for a future Lupin-context session per Rick's directive.

**Memory rules engaged**: `feedback_session_scope_is_cwd` (cwd `…/lupin/src/cosa` → CoSA is this session's scope), `feedback_never_commit_cosa` (AI prepares, user commits — even with direct "make commits" voice direction, scope is preparation through to ready state), `feedback_verify_repo_before_commit` (`git rev-parse --show-toplevel` + `git branch --show-current` both confirmed CoSA + wip-v0.1.7-2026.04.23-tracking-lupin-work before any staging-adjacent action), `feedback_lupin_only_never_cosa` (Q8's Lupin-side already shipped by parent context; CoSA-side mirror is this commit only).

#### Checkpoint | 2026.05.17 19:00 EDT | Mr. Radio af54bb12 wrap-session prep complete

**Files** (this checkpoint, CoSA repo): rest/routers/commons.py (Q8 1-LOC fix), history.md (this entry + Tiberius's earlier archive trim + entry), history/2026-04-25-to-05-13-history.md (Tiberius's NEW archive file), .claude-session.md (Session af54bb12 section appended; Last Updated bumped), io/git-loc-delta/cosa-wip-v0.1.7-2026.04.23-tracking-lupin-work-loc-delta.csv (NEW branch CSV), io/git-loc-delta/2026-05-17-loc-delta.csv (NEW date-stamped weekly CSV), rnd/2026.05.17-session-af54bb12-loc-summary.md (NEW LoC summary R&D doc — daily + weekly + branch stats across both repos)
**Commit hashes**: ⏳ pending Rick's CoSA-context workflow

---

### 2026.05.17 - Session 2d916480 (Tiberius 🌑) | CoSA history.md archive — 41k→9k tok cut at 2026-05-13 PM boundary (mirror of Lupin priority-1 deferred archive)

**Context**: CoSA-context session prompted by Rick's queue-review request, followed by his explicit go on the priority-1 history archive ("affirmative Tiberius let's go ahead and archive the history before anything else"). Persona: Tiberius 🌑 (`pNInz6obpgDQGcFmaJgB`, #3F51B5 — deep male). Branch: `wip-v0.1.7-2026.04.23-tracking-lupin-work`. Single-deliverable session executed under the corrected cwd-based scope rule: CoSA cwd → CoSA session → CoSA repo is mine, Lupin parent is out-of-scope.

**Accomplishments**:
- **Top-5 review of Lupin queues** (parent TODO.md + bug-fix-queue.md) — surfaced (1) priority-1 history-archive deferral, (2) model-server carve-out Phases 4-8 follow-ups, (3) commons DM infrastructure cluster (FunctionTool error + topic-case mismatch + write-truncation sub-bug), (4) daily LoC delta CoSA-commit-pending, (5) persona-completion 4× duplication. Delivered via `notify()` with doc-viewer abstract.
- **CoSA history.md archive** — cut at line 154 (start of 2026.05.13 PM Mr. Radio wrap-session). Pre-archive 41,269 tok / 165% / 🚨 CRITICAL; post-archive 9,057 tok / 36% / ✅ HEALTHY. 78% reduction. Followed shape-aware heuristic — CoSA wrap-granularity (one CoSA-session per cluster of related Lupin commits) suggested 2 most-recent wrap-sessions matches Lupin's "retain most-recent activity bundle" semantics. Token-based fallback (canonical workflow Priority 4) because 5-day retention minimum infeasible at this density.
- **Memory correction** — wrote `feedback_session_scope_is_user_intent_not_cwd.md` mid-session (inverted principle), then immediately deleted it after Rick clarified the rule; replaced with `feedback_session_scope_is_cwd.md` capturing the corrected principle: cwd at claude-code launch IS the source of truth for session responsibility; do not infer scope from where TODO items were filed. Pairs with `feedback_never_commit_cosa.md` (always holds: never commit CoSA, regardless of cwd).
- **Cross-repo footnote** (Lupin parent — out of CoSA scope, untouched by this session-end ritual): earlier in the session, before Rick's scope-rule clarification, I had executed the same archive operation on Lupin parent's `history.md` (`history.md` trim + new `history/2026-05-12-to-15-history.md` + index update + TODO.md priority-1 marker swap). Rick directed to leave those Lupin edits in the Lupin working tree for a future Lupin-context session to commit.

**Files Modified (CoSA repo, uncommitted — per `feedback_never_commit_cosa.md` user runs commits)**:
- `history.md` — TRIMMED 963 → 153 lines pre-this-entry (41,269 → 9,057 tok), then this entry added at top
- `history/2026-04-25-to-05-13-history.md` — NEW archive file, 820 lines / 32,450 tok / 15 wrap-sessions archived (2026-04-25 to 2026-05-13)
- `.claude-session.md` — new Session 2d916480 section appended (pending Step 3.5 of session-end ritual)

**Suggested commit message** (for Rick's CoSA workflow):
```
[COSA] history.md archive — cut at 2026-05-13 PM boundary, 41k → 9k tok (78% reduction, mirror of Lupin priority-1 deferred archive executed same day; Tiberius session 2d916480)
```

---

### 2026.05.16 PM - Session 60d767ef (Rachel 🕊️) | CoSA-side wrap of 5 thematic Lupin bodies: Daily LoC Delta + Broadcast fan-out dedupe + Model-server carve-out + Voice persona Sam-overflow + Doc-viewer cleanup

**Context**: CoSA-context session-end commit bundle wrapping five distinct bodies of CoSA-side work produced by parent Lupin sessions on 2026-05-16. Persona: Rachel 🕊️ (`21m00Tcm4TlvDq8ikWAM`, #7B1FA2 — calm & clear female). Branch: `wip-v0.1.7-2026.04.23-tracking-lupin-work`. Five thematic commits + session-end docs commit + manifest hash-backfill commit per `feedback_lupin_only_never_cosa.md` cross-repo separation, mirroring the prior Session 31c7d1b5 / 99fbada3 / 1fb80a1c / 19d3ce48 wrap pattern. Commit basis identified by reading parent `history.md`, `TODO.md`, and `bug-fix-queue.md` per user voice direction at session start ("read the history, to-do, and bug tracking documents in the Lupin repo and use them as the basis for the commits ... of special importance today is María and Tiberius's work on collaboratively debugging and improving the new DM inter-Claude-code-session communication workflows").

**Meta-narrative — María 🌸 ↔ Tiberius 🌑 cross-session DM collaboration as today's headline (per user voice direction)**:
2026-05-16 produced the first sustained instance of two Claude Code sessions running an iterative design dialogue entirely through cosa-voice MCP DMs, with no Rick-relay required. María (Lupin session `3c9fce51`) and Tiberius (planning-is-prompting session `b714e138`) co-authored a discovery-surface expansion for the cosa-voice MCP server's `instructions` field — grown from ~3k → ~21k chars across 10 sections — with Tiberius running a 5-point prose review via DM and folding 7 priority enrichments back into María's draft. The collaboration shape itself — **DM-thread-as-mini-design-doc**, paired-by-DM-paired-by-commit, iterative correction loop converging on the 5-surface framework (CLAUDE.md / MCP `instructions` / planning-is-prompting workflow / per-tool docstrings / per-turn rider — split by reading timing not content type) — produced sharper output than either of them would have produced alone, and surfaced two latent bugs in the DM substrate itself during execution (topic-file case fragmentation `dm-Tiberius` vs `dm-tiberius`; `commons_post` body truncation observed mid-write — both filed durably to the parent Lupin bug-fix queue). María and Tiberius plan to draft a follow-up workflow R&D doc covering this template, with a pointer from the project README — this CoSA wrap lands the README.md callout in Commit F per user voice direction. The CoSA-side files committed in this wrap are concrete spillover from María's productive day (the LoC Delta tool, the broadcast fan-out dedupe) even though the discovery-surface expansion itself lives in the parent Lupin repo.

**Commits Planned** (this session-end ritual; per `feedback_never_commit_cosa.md` AI prepares everything and stops at "ready for your workflow", user runs the actual `git add` / `git commit`):
- `<A-hash>` — Commit A: Daily LoC Delta tool (parent María 🌸 session `3c9fce51`)
- `<B-hash>` — Commit B: Broadcast fan-out watcher dedupe (parent María 🌸 session `3c9fce51`)
- `<C-hash>` — Commit C: Model-server carve-out CoSA-side (parent Rio ⚡ session `0025f917`)
- `<D-hash>` — Commit D: Voice persona Sam-as-overflow + stale-bridge mtime TTL guard (parent Rio ⚡ session `0025f917`)
- `<E-hash>` — Commit E: Doc-viewer path-prefix routing cleanup + /api/docs/health refactor (parent Mr. Radio 🦉 session `dfd7b2d8`)
- `<F-hash>` — Commit F: session-end docs (history.md + README.md cross-session-collab callout + manifest section)
- `<G-hash>` — Commit G: manifest hash backfill + status flip to committed

**Body 1 — Daily LoC Delta tool** (Lupin parent: María 🌸 session `3c9fce51` AM 2026-05-16; references parent `history.md` § "Daily LoC Delta tool — new `cosa.repo.git_loc_delta` sibling of `branch_analyzer`" + parent `TODO.md` § "📦 NEW — CoSA-side commit pending: Daily LoC Delta tool" closure list + parent Lupin commit `2e0e7e5` carrying the Lupin-side test + TODO entry)

User-initiated voice-first ask to view an unserialized Claude Code plan via the doc viewer surfaced two adjacent issues: the URL referenced a retired `?scope=` param and a non-registered `cosa` project, AND the plan was not yet serialized into any repo. Per the plan-serialization mandate, the fix was serialize-first then implement. María chose CoSA-submodule R&D destination via interactive `ask_multiple_choice` voice gate, ran Reduced PIP review (REUSE pre-pass with 7 reuse-map citations verified + Pass 1 Fitness with 18 ACs derived, 8 fitness findings filed and folded), implemented the 10 source files, and post-ship iterated on a filename-flip after live spin-up on both Lupin and CoSA repos.

- **`repo/git_loc_delta/__init__.py` (NEW)** — package exports
- **`repo/git_loc_delta/exceptions.py` (NEW)** — `GitLocDeltaError`, `DateRangeError`; re-exports `GitCommandError`
- **`repo/git_loc_delta/git_log_parser.py` (NEW)** — `GitLogParser.iter_changes()` over `git log --numstat`, binary-row skip, malformed-row defense
- **`repo/git_loc_delta/daily_aggregator.py` (NEW)** — `DailyAggregator` with `(date, file_type)` bucketing + per-date rollup + summary view; loads `branch_analyzer.FileTypeClassifier` via `ConfigLoader().load()`
- **`repo/git_loc_delta/csv_writer.py` (NEW)** — `write_csv()` tidy-long, 6-column stable schema, sorted by `(date asc, added desc)`
- **`repo/git_loc_delta/report_formatter.py` (NEW)** — `format_console()` two-table layout + `format_json()` nested dict
- **`repo/git_loc_delta/analyzer.py` (NEW)** — `GitLogLocDeltaAnalyzer` orchestrator + `quick_smoke_test()` with 7 ✓/✗ checks
- **`repo/git_loc_delta/README.md` (NEW)** — comprehensive user docs (Use Case A: daily end-of-session ritual; Use Case B: pre-PR summary; CLI reference; architecture; reuse map; edge cases; future enhancements)
- **`repo/run_git_loc_delta.py` (NEW)** — CLI entry with mutually-exclusive date-range group, exit codes 0/1/2, mode-aware default CSV path
- **`rnd/2026.05.16-daily-loc-delta-tool.md` (NEW)** — R&D plan, status flipped from "🟢 APPROVED FOR CODE-WRITE" → "🟢 SHIPPED" through the Reduced PIP review

Parent verification per parent `history.md`: T1 py_compile (9 source + 1 test) 9/9 OK; T2 import chain all resolved; T3 unit tests 4/4 PASSED in 0.31s; T4 quick_smoke_test 7/7 ✓; T5 live CLI on both Lupin (21 days, 216 commits, 532 files, +147,999/−13,171 net +134,828) + CoSA submodule (17 days, 69 commits, 73 files, +12,561/−3,272 net +9,289) — all 3 modes verified. Post-ship filename-flip ratified via `ask_multiple_choice`: `--branch` mode → `{repo}-{branch-slug}-loc-delta.csv` (stable per-branch, daily-overwrite-friendly); `--today`/explicit → date-stamped (archival).

**Body 2 — Broadcast fan-out watcher dedupe** (Lupin parent: María 🌸 session `3c9fce51` PM 2026-05-16; references parent `history.md` § "Checkpoint 3 | Commons DM push-mode + Git LoC Delta cross-target fix arc (F1-F5)" + parent `TODO.md` § "✅ 🟢 FIX SHIPPED 2026-05-16 — Duplicate notification fan-out" + parent R&D doc `src/rnd/v0.1.7/2026.05.16-broadcast-fanout-watcher-dedupe.md` + parent Lupin commit `4439550`)

Bug originally filed by Rio ⚡ session `0025f917` (the model-server carve-out persona) on the morning of 2026-05-16 from observed symptoms, fixed by María 🌸 session `3c9fce51` in the afternoon as part of her F1-F5 fix arc. Root cause: `CommonsActivityWatcher._tick()` was dispatching one `commons_activity` WS event per row read from the `broadcasts` / `broadcast-acks` topics. `perform_fanout` writes N per-recipient rows by design (for `target_session_id`-scoped routing). The HTTP read path already dedupes via `_dedupe_broadcasts_by_id` + `_dedupe_broadcast_acks_by_recipient` in `routers/commons.py`; the WS push path bypassed both → producer/consumer asymmetry → N pushes per broadcast → N rows in Recent Activity.

- **`rest/commons_activity_watcher.py` (MOD, +~100 LOC)** — NEW `_dedupe_for_dispatch( entries )` helper mirroring HTTP-path dedupes for the WS push path. Rules: `broadcasts` topic collapses on `metadata.broadcast_id` (first occurrence kept after the outer DESC sort, `target_session_id` stripped from dispatched copy so the row represents the broadcast-as-a-whole, not any one recipient slice); `broadcast-acks` topic collapses on `(broadcast_id, sender_session_id, metadata.status)` triple (the write-side multiplicity bug shape per Arnold's earlier investigation); other topics passthrough; defensive passthrough on missing/non-string keys (malformed entries must not silently disappear). Cursor-advancement fix: `latest_ts_pre_dedupe = max(ts of original entries)` captured BEFORE dedupe so dropped duplicates don't re-surface on the next tick.

Parent verification per parent `history.md`: T1 py_compile (2 files) OK; T2 import chain resolved; T3 targeted unit (22 watcher tests: 15 pre-existing + 7 new) 22/22 PASS in 0.07s; T4 full commons regression (438 tests) 438/438 PASS in 14.80s, **0 regressions**.

**Body 3 — Model-server carve-out CoSA-side** (Lupin parent: Rio ⚡ session `0025f917` 2026-05-16; references parent `history.md` § "Session 0025f917 (Rio ⚡) | Model-server carve-out: Whisper + 2 encoders moved to lupin-model-server:7998, doom-loop structurally killed" + parent `TODO.md` § "🚀 NEW — Model-server carve-out follow-ups" + design doc `src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md` + parent Lupin commit `03666df`)

Day-long sequenced design + implementation arc. Phases 0-5 shipped: Whisper + code_rank_embed + nomic_embed_text_v1_5 carved out of compute containers into a frozen `lupin-model-server:7998` FastAPI app pinned to GPU 0. Compute (`:7999` dev + `:8000` test) now talks to the model server over HTTP using the existing `ck_live_*` key from `notification-api-claude-code-dev` (per María's brief — no parallel `ck_internal_*` namespace, which Rio had initially overbuilt and then rolled back after María's design DM). Doom-loop layers 1 + 3 structurally killed (no GPU dependency in compute containers). Final state: 19,889 MiB GPU 0 used (was 23,131 — saved 3,250 MiB matching Rick's net-savings math); 4,335 MiB free (was 1,086 — 4× headroom); 9/9 smoke tests passing in 3.02s; native browser ASR confirmed working post-fix. CoSA-side mirrors of the Phase 3.1 HTTP-proxy path landed below.

- **`memory/embedding_provider.py` (MOD, +~70 LOC)** — NEW `_resolve_model_server_url()` env→INI→None chain (compose-injected `LUPIN_MODEL_SERVER_URL` preferred; `model server url` INI key fallback; None falls through to legacy FastAPI path; defends against `docker restart` not re-reading compose, which would leave the env var unset and cause self-recursion). NEW `_resolve_http_target()` returning `(base_url, api_key, endpoint_prefix)` tuple — model-server gets `/embeddings` prefix, legacy FastAPI gets `/api/embeddings`. `_generate_embedding_via_http` and `_generate_batch_embeddings_via_http` migrated to call `_resolve_http_target()` so a single resolver-output drives both URL and endpoint construction. Consolidated to use the existing `_http_api_key()` reading `notification-api-claude-code-dev` for both target branches.
- **`memory/speech_to_text_provider.py` (NEW, ~210 LOC)** — Mirrors `EmbeddingProvider` architecture: singleton, class-level `_is_in_process_owner` flag, INI-driven `speech to text provider` switch (`local` | `model-server`), local + HTTP paths, exp-backoff retry wrapper. `declare_in_process_engine_owner()` + `declare_remote_only()` for the two lifecycle modes. `_call_with_retry()` with 3 attempts + jittered backoff for the HTTP path. Class-level singleton via `_instance` + `get_speech_provider()` factory for FastAPI `Depends()`. Routes `/transcribe` calls to the model-server when configured, otherwise to local Whisper pipeline.
- **`rest/routers/speech.py` (MOD)** — `Depends(get_whisper_pipeline)` → `Depends(get_speech_provider)` swap so the router pulls the singleton without knowing whether it routes local or remote. Legacy `_run_whisper_with_retry` marked deprecated but kept for backward compatibility. NEW `save_upload_to_temp` helper consolidating the multipart-upload-to-temp-file pattern used at multiple call sites.

Parent verification per parent `history.md`: Part 2 bounce ~32s wall-clock total (faster than 45-60s predicted because models baked into image, no HF downloads at boot); three mid-flight bugs caught + fixed in-session (HF cache bind-mount PermissionError, embedding endpoint self-recursion, `/transcribe` 422 from leftover `_authenticated: str` parameter); 9/9 smoke tests on `:7998` passing in 3.02s; native browser ASR confirmed working.

**Body 4 — Voice persona Sam-as-overflow + stale-bridge mtime TTL guard** (Lupin parent: Rio ⚡ session `0025f917` 2026-05-16; references parent `history.md` § "Fix 0025f917 (Rio ⚡): Voice persona stale-bridge pool exhaustion + Sam-as-overflow" + R&D doc `src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md` + parent Lupin commit `a1ccdcf`)

Two interlocking fixes for voice-persona allocation under chorus-mode load. Layer 1 (host-side prune at SessionStart, in `lupin_cli/claude_code/hooks/lib/session_bridge.py` — Lupin-parent owned) and Layer 2 (mtime TTL guard at allocation time, this CoSA-side commit) prevent the pool from exhausting due to phantom bridges left behind by dead host processes. Layer 3 (Sam as overflow persona, this CoSA-side commit) gives the allocator a graceful spillover when the main pool is legitimately exhausted, instead of hash-borrowing an in-use voice (which produced confusing duplicate-persona scenarios in chorus mode).

- **`rest/voice_persona_helpers.py` (MOD, +~50 LOC)** — NEW `load_overflow_persona_from_config()` reads Sam's voice_id from the canonical `elevenlabs tts default voice id` INI key (single source of truth — Sam is both the system TTS default AND the allocatable overflow persona) plus `cc session voice persona sam {display name, icon, color, profile}` INI keys; returns persona dict with `overflow=True` flag, or None when voice_id is unconfigured (in which case the legacy hash-borrow fallback in `pick_unallocated_persona` takes over). `pick_unallocated_persona()` extended with `overflow_persona` kwarg — when pool fully occupied AND overflow_persona is non-None, returns a copy of overflow_persona with `borrowed=False` (preserving `overflow=True`); multiple sessions may legitimately receive Sam this way. Legacy `borrowed_persona_for_sid` hash-borrow path preserved as defensive fallback when Sam is unconfigured. `allocate_persona_for_session()` reads `cc session voice persona stale threshold seconds` from INI (default 43200 = 12h), passes it through to `find_active_voice_persona_sessions(stale_threshold_seconds=...)` as the mtime TTL guard rejecting stale persona-bearing bridges even when the host-side prune at SessionStart didn't fire.
- **`rest/routers/voice_persona.py` (MOD, ~15 LOC)** — `get_voice_persona_pool` endpoint extended to read `stale_threshold_seconds` from INI and pass it through to `find_active_voice_persona_sessions()` so the pool listing honors the same TTL guard as allocation. `voice_persona_sample` endpoint extended to accept Sam's voice_id (system TTS default) into the `pool_ids` set so the persona-reference page can play a Sam sample alongside pool samples.

Parent verification per parent `history.md`: live confirmation that pool exhaustion no longer cascades into hash-borrowed duplicates; Sam allocation observed in chorus-mode load tests; stale-bridge prune at SessionStart visibly clears bridge files older than the TTL.

**Body 5 — Doc-viewer path-prefix routing cleanup + /api/docs/health refactor** (Lupin parent: Mr. Radio 🦉 session `dfd7b2d8` 2026-05-16; references parent `history.md` § "Checkpoint dfd7b2d8 (Mr. Radio 🦉): Doc viewer SPA dispatcher 404 fix + /api/docs/health regression" + parent Lupin commit `5277bcb`)

Post-merge cleanup of the doc-viewer scope unification (parent Session c1cbcd11 Rio ⚡ landed the bulk in CoSA commit `91cba29`; this is the trailing polish). Comments + `_build_view_url` aligned with the 2026-05-15 unification (Q-R2 path-prefix routing, `scope=` query param retired server-side); `/api/docs/health` endpoint refactored to return scope-registry-driven payload (manifest-presence flag + sorted scope dict) instead of the legacy `ALLOWED_FILES` / `ALLOWED_PREFIXES` shape that was retired in Phase 4a.

- **`rest/routers/_dir_listing.py` (MOD)** — module docstring + `_build_view_url` docstring + body updated to reflect path-prefix routing (URLs now `/app/docs?path=<project>/<rel>` not `/app/docs?path=<rel>&scope=<scope>`). io-only direct-binary branch tightened to require `kind == "file"` (directories always route to `/app/docs` regardless of scope). Text-renderable file branch now produces project-prefixed URLs via `quote(f"{scope}/{rel_path}", safe="")`. Comments aligned with the 2026-05-15 unification design doc.
- **`rest/routers/docs_files.py` (MOD)** — `/api/docs/health` rewritten to return `{status, project_root, io: {root, exists}, scopes: {name: {root, exists, allowed_prefixes, manifest}}, media_types}` shape. Per-scope detail uses the manifest's `allowed_prefixes` when present (manifest-bearing repos get authoritative whitelists with their `.docview.yml` overrides), falls back to the registry config's `allowed_prefixes` otherwise. Legacy `allowed_files` / `allowed_prefixes` / `external_scopes` top-level keys retired; the new scope-registry-driven payload is the single source of truth.

Parent verification per parent `history.md`: live `/api/docs/health` returns clean payload across all registered scopes; SPA dispatcher 404 fix verified on `:7999`.

**Cross-repo separation**: Per `feedback_lupin_only_never_cosa.md` and `feedback_never_commit_cosa.md`, this CoSA-context session ONLY edits files under `src/cosa/`. Body 1's parent Lupin work (test file `src/tests/unit/test_git_loc_delta.py` 4 tests + TODO entry + history entry) — landed in parent commit `2e0e7e5`. Body 2's parent Lupin work (test file `src/tests/unit/commons/test_commons_activity_watcher.py` 7 new tests + R&D doc + history entry) — landed in parent commit `4439550`. Body 3's parent Lupin work (12 Lupin files including `src/lupin_model_server/` 440 LOC, `src/tests/smoke/test_model_server_smoke.py` 9 cases, `docker-compose.yml` model-server service, `docker/lupin-model-server/Dockerfile`, INI/splainer keys, `src/fastapi_app/main.py` lifespan switch) — landed in parent commit `03666df`. Body 4's parent Lupin work (host-side prune + Sam INI keys + R&D doc) — landed in parent commit `a1ccdcf`. Body 5's parent Lupin work (SPA dispatcher fix + /api/docs/health regression check) — landed in parent commit `5277bcb`. Plus today's María 🌸 ↔ Tiberius 🌑 cross-session DM collaboration on the cosa-voice MCP discovery-surface expansion — that work landed in parent commit `b550f10` (`src/lupin_mcp/cosa_voice_mcp.py` +313 LOC + 6 commons_* docstring upgrades + R&D doc `src/rnd/v0.1.7/2026.05.16-mcp-discovery-surface-expansion.md`); CoSA submodule itself was untouched by that work, but this CoSA wrap commits the README.md callout in Commit F per user voice direction.

**Pre-commit verification**:
- `py_compile` on all 7 modified + 9 new Python files: ⏳ to be confirmed before each commit
- Import-chain check via cosa `.venv`: ⏳ to be confirmed before each commit
- `git diff --stat HEAD` at session start: ✅ 7 modified + untracked tree of 4 new entries (`memory/speech_to_text_provider.py` + `repo/git_loc_delta/` package + `repo/run_git_loc_delta.py` + `rnd/2026.05.16-daily-loc-delta-tool.md`) match parent attribution exactly
- Branch verification: ✅ `wip-v0.1.7-2026.04.23-tracking-lupin-work` matches expected CoSA wip branch
- Parent-side test coverage: ✅ Body 1 (T1-T5 all green), Body 2 (22/22 targeted + 438/438 regression), Body 3 (9/9 smoke), Body 4 (live verified), Body 5 (live verified)

#### Checkpoint | 2026.05.16 PM | Session-end ritual + 5 thematic commits ready (Rachel 🕊️)

**Files** (21 total): 9 NEW Python under `repo/git_loc_delta/` + `repo/run_git_loc_delta.py` + 1 NEW R&D doc `rnd/2026.05.16-daily-loc-delta-tool.md` + 1 NEW `memory/speech_to_text_provider.py` + 7 MOD (`memory/embedding_provider.py`, `rest/commons_activity_watcher.py`, `rest/routers/_dir_listing.py`, `rest/routers/docs_files.py`, `rest/routers/speech.py`, `rest/routers/voice_persona.py`, `rest/voice_persona_helpers.py`) + 3 session-end docs (`history.md`, `README.md`, `.claude-session.md`).

**Commits**: pending user workflow execution per `feedback_never_commit_cosa.md`.

---

### 2026.05.15 PM - Session 31c7d1b5 (Rio ⚡ borrowed) | CoSA-side wrap of 2 thematic Lupin bodies: Doc-viewer scope unification + Inter-Session DM Phase 0

**Context**: CoSA-context session-end commit bundle wrapping two distinct bodies of CoSA-side work produced by parent Lupin sessions on 2026-05-15. Persona: Rio ⚡ (`AZnzlk1XvdvUeBnXmlld`, #880E4F — borrowed allocation per `voice_persona` field on session info). Branch: `wip-v0.1.7-2026.04.23-tracking-lupin-work`. Two thematic commits + session-end docs commit + manifest hash-backfill commit per `feedback_lupin_only_never_cosa.md` cross-repo separation, mirroring the prior Session 99fbada3 / Session 1fb80a1c / Session 19d3ce48 wrap pattern. Commit basis identified by reading parent `history.md` (3 most recent sessions: c1cbcd11 Rio doc-viewer scope unification + fa2de0ff GPU doom loop diagnosis + 06aba5f7 Arnold broadcast-acks dedupe), parent `TODO.md` § "DONE 2026-05-15 PM Inter-Session DM Phase 0" + § "DONE 2026-05-15 PM doc_scope registry exposure", and parent `bug-fix-queue.md` (top of queue empty; `/api/init` cache invalidation entry already marked RESOLVED-by-side-effect of the doc-viewer unification) per user voice direction at session start ("Read the contents of the history to-do and bug fix files and use them as the basis for the commits").

**Commits Planned** (this session-end ritual; per `feedback_never_commit_cosa.md` AI does NOT execute commits in CoSA cwd, user runs the actual `git add` / `git commit` / `git push`):
- `<A-hash>` — Commit A: Doc-viewer scope unification CoSA-side
- `<B-hash>` — Commit B: Inter-Session DM Phase 0 CoSA-side
- `<C-hash>` — Commit C: session-end docs (history.md + manifest section)
- `<D-hash>` — Commit D: manifest hash backfill + status flip to committed

**Body 1 — Doc-viewer scope unification (CoSA-side)** (Lupin parent: Session c1cbcd11 Rio ⚡, 2026-05-15 PM; references parent `history.md` § "Session c1cbcd11 (Rio ⚡) | Doc-viewer scope unification (Phases 1-6) + speakerphone rider sentinel regression fix" + parent commit `192dad6` "Lupin half — 12 files, 1662 insertions" + parent `TODO.md` § "DONE 2026-05-15 PM `doc_scope` registry exposure for cosa-voice consumption (Rio ⚡, session `c1cbcd11`)" closure list + design doc `src/rnd/v0.1.7/2026.05.15-doc-viewer-scope-unification.md`)

The parent canonical plan (six implementation phases, three plan-review gates ratified via interactive `ask_multiple_choice`) reframed the doc-viewer scope mechanism around a unified URL shape `?path=<project>/<rel>` where the first segment names a registered project. The legacy dual-track (built-in `docs`/`io` scopes vs config-driven registry) collapsed to one path; the `scope=` query param was retired (Q-R2 ratification; Rick "I'm so bored with BC"). Side-effect: resolves Mr. Radio's `/api/init` cache-invalidation bug filed earlier the same day from external project `retail-ai-location-strategy`. Universal floor blocklist extended ~16 → ~46 regex patterns covering credentials, CLAUDE.local.md, .venv/, node_modules/, .ssh/, .aws/, IDE files. Defense-in-depth: cannot be weakened by any repo's `.docview.yml` manifest. CoSA-side files were left modified-but-uncommitted by the parent session per `feedback_lupin_only_never_cosa`.

- **`config/cache_registry.py` (NEW, ~70 LOC)** — generic invalidation registry. `register_invalidator(name, callable)` accepts a name string and a zero-arg callable; `invalidate_all() -> List[str]` calls each registered invalidator under `threading.RLock` and returns the names of caches actually flushed. Replaces the prior pattern where `/api/init` had to know about every cache module by hand. Clients self-register at import time so adding a new cache requires zero edits to `system.py`.

- **`config/docview_manifest.py` (NEW, ~100 LOC)** — Pydantic `DocviewManifest` model with `ConfigDict(extra="forbid")` (typo'd YAML keys raise at parse rather than silently degrading the whitelist). 64 KB file-size cap (DOS-protect). Malformed-regex rejection at parse (no runtime surprises). `load_manifest_for_scope(scope_root)` loads `<scope_root>/.docview.yml` if present, returns `None` otherwise. Fields: `allowed_prefixes`, `allowed_root_files`, `extra_blocklist` (list of regex patterns appended to the universal floor for that scope only).

- **`agents/prediction_engine/prediction_engine.py` (MOD, +6 LOC)** — registers `PredictionEngine.reset` as the invalidator for `/api/init` hot-reload via `register_invalidator("prediction_engine", PredictionEngine.reset)` at module bottom. Mirrors the existing reset semantics (drop singleton, next call rebuilds).

- **`rest/routers/_scope_registry.py` (MOD, +~150 LOC)** — `ScopeConfig` dataclass extended with `manifest: Optional[DocviewManifest] = None` and `extra_blocklist_patterns: tuple = ()` fields (defaults preserve backward compatibility for callers that build registry entries without manifests). `SECRETS_BLOCKLIST_PATTERNS` expanded from ~16 to ~46 regex patterns covering: credentials extensions (`.gpg`, `.asc`, `.credentials`), local-config dotfiles (`CLAUDE.local.md`, `*.local.md/json/yaml`, `.gitconfig-local`), dev artifacts (`.venv`, `node_modules`, `__pycache__`, `*.pyc`, `*.pyo`, `dist/build/target/`), IDE files (`.idea/`, `.vscode/`), OS junk (`.DS_Store`, `Thumbs.db`), and personal config (`.ssh/`, `.aws/`, `.gnupg/`, `.kube/`). All regex case-insensitive where appropriate. `build_scope_registry()` now hydrates `ScopeConfig.manifest` via `load_manifest_for_scope()` for each registered scope so manifest-bearing repos get authoritative whitelists with manifest-defined extra blocklist patterns layered on the universal floor.

- **`rest/routers/docs_files.py` (MOD, +~100/-90 LOC)** — legacy `ALLOWED_FILES` set + `_is_whitelisted_legacy_docs()` helper + `if scope == "docs":` branch DELETED (Phase 4a per Q1-D ratification). URL parser rewritten to path-prefix shape `?path=<project>/<rel>` (Q-R2 retirement of `scope=`). `get_docs_file()` query signature: `path` is now required and must be `<project>/<rel>` form, `scope` is documented as DEPRECATED with `None` default and ignored. New `_invalidate_scope_registry()` helper drops `_SCOPE_REGISTRY` cache so the next `_get_scope_registry()` call rebuilds; registers via `register_invalidator("scope_registry", _invalidate_scope_registry)` at module import. Endpoint summary + description rewritten to reflect path-prefix shape.

- **`rest/routers/system.py` (MOD, +~25/-15 LOC)** — `/api/init` now uses `cache_registry.invalidate_all()` instead of explicit per-cache reset (was: `main_module.snapshot_mgr.reload()` + `PredictionEngine.reset()` hardcoded). Returns `caches_invalidated: List[str]` in payload so the caller sees which caches actually flushed. PredictionEngine eager-rebuild after the generic reset preserves cold-start behavior (first request after `/api/init` doesn't pay the rebuild cost).

Parent verification per parent `history.md`: 4605 unit pass / 1 xfailed / **0 failed** (was 4599/1/6); 100% lines + branches coverage on both NEW modules (`cache_registry.py`, `docview_manifest.py`); 80 parametrized tests on the floor blocklist (all 46 patterns reject; case-insensitivity verified); **15/15 live `:7999` AC sweep pass** (AC1.3 caches_invalidated, AC4b.1-7 URL parser, AC5.1-6 Lupin manifest, scopes endpoint auth+payload). Parent commit: `192dad6` (12 Lupin files, 1662 insertions) + `4502d3f` (speakerphone wrap sentinel invariant + 2 stale exit-reminder tests).

**Body 2 — Inter-Session DM Phase 0 (CoSA-side)** (Lupin parent: Session 3b6be6f9 María 🌸, 2026-05-15 PM; references parent `history.md` § "Session 3b6be6f9 (María 🌸) | Inter-Session DM Phase 0 implementation landed — 8 steps, 28 net-new tests, 514/514 :7999 regression green" + parent `TODO.md` § "DONE 2026-05-15 PM Inter-Session DM Phase 0" closure list + design doc `src/rnd/v0.1.7/2026.05.15-inter-session-direct-messaging-design.md`)

Phase 0 of inter-Claude-Code session communication that lets María DM Mr. Radio directly without Rick relaying, logged to Recent Activity with a `→ @recipient` DM badge. Architecture: Rick correctly pushed back on the initial parallel-mechanism scope, asking "in section 2.2 you say there is no commons_send_to method when in fact you list 2 methods that accomplish just this: commons_ask_sync and commons_ask_async. Why can't you reuse them?" The corrected scope extends `commons_ask_async` with `recipient_session_id` / `recipient_persona` / `expect_reply` kwargs and extends `/api/commons/register-question` to dispatch `commons_question_received` to the recipient at register time when `recipient_*` set; mirrors Phase 3's `commons_answer_received` listener handler. Scope shrunk from ~480 LOC + 4-6 sessions to ~210 LOC + 1 session. CoSA-side files were left modified-but-uncommitted by the parent session per `feedback_lupin_only_never_cosa`. Parent TODO line 28: **"This is the ONLY remaining work before the feature can merge to main."**

- **`rest/routers/commons.py` (MOD, +~360/-15 LOC)** — `RegisterQuestionRequest` extended with three Field-validated kwargs: `recipient_session_id: Optional[str] = Field(default=None, min_length=1, max_length=128)`, `recipient_persona: Optional[str] = Field(default=None, min_length=1, max_length=64)`, `expect_reply: bool = Field(default=True)`. NEW `RecipientResolutionError(BaseModel)` 422 response body per Q3-rev amendment for AI-self-correction: fields `error: str` (categorical failure mode), `supplied_persona: Optional[str]`, `supplied_session_id: Optional[str]`, `resolution_chain_attempted: List[str]` (which resolution levels were tried), `candidate_alternatives: List[str]` (currently-active sessions sourced from `commons_who()` at the moment of failure), `suggested_next_action: str` (one-sentence guidance). NEW `_resolve_dm_recipient` exact → case-insensitive → punct-tolerant → PHI-4-stub resolution chain with T7 isolation try/except wrapping the `match_persona` LLM call (any LLM failure routes to 422 RecipientResolutionError, never raises into the request handler). NEW `_dispatch_commons_question_received` helper that fires `user_initiated_message` with `title="action:commons_question_received"` to the resolved recipient session via the notification queue (fire-and-forget pattern mirroring Phase 2 `failed_recipients` best-effort dispatch). `execute_register_question` extended to call `_resolve_dm_recipient` when `recipient_*` fields are set, returning 422 with `RecipientResolutionError.dict()` body when resolution fails OR proceeding with `_dispatch_commons_question_received` followed by the standard register-question flow when resolution succeeds. Route handler signature unchanged (existing 201/422/409/429 statuses preserved); 422 body shape extended for the new resolution-error case. Imports new `match_persona` from `lupin_mcp.commons_persona_matcher`.

- **`rest/routers/notifications.py` (MOD, +1/-1 LOC)** — single-line addition of `"commons_question_received"` to `valid_types` list (Step 5 of the 8-step Phase 0 implementation), so the notification dispatcher accepts question-received pushes from `_dispatch_commons_question_received`. Listener-side `_handle_commons_question_received` is parent-Lupin owned (`src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py`).

Parent verification per parent `history.md`: 514/514 :7999 regression GREEN; 488/488 :7999 + :8000 DM Phase 0 sweep PASS; 28 net-new tests (16 unit + 7 endpoint smoke + 5 listener smoke + 5 :8000 integration + 3 Playwright E2E + 1 visual regression baseline); parent commits: `9bbf298` (Phase 0 main implementation, 12 files, +1840/-53), `98ab544` (:8000 integration test AC9d), `8e9e144` (Playwright E2E + visual baseline AC9e + AC9f). Closes Lupin TODO line 28 once these CoSA commits land.

**Cross-repo separation**: Per `feedback_lupin_only_never_cosa.md` and `feedback_never_commit_cosa.md`, this CoSA-context session ONLY edits files under `src/cosa/`. Body 1's parent Lupin work — Phases 1-6 (12 Lupin files / 1662 insertions in commit `192dad6`) including `lupin/.docview.yml`, `lupin-app.ini` external-repo registry, retired `bug-fix-queue.md` Mr. Radio entry, retired Rachel TODO `doc_scope` entry, `lupin/CLAUDE.md` § Doc Viewer Scope rewrite — is owned by parent Lupin context and ALREADY landed. Body 2's parent Lupin work — 5 parent Lupin files (~210 LOC) including `commons_ask.py` extensions, `commons_send_to` MCP wrapper, `_handle_commons_question_received` listener handler, `_renderCommonsEntry` DM badge, `.commons-activity-dm-badge` CSS pill — is owned by parent Lupin context and ALREADY landed (commits `9bbf298` + `98ab544` + `8e9e144`). The parent TODO entries at lines 28 + 111 ("[LUPIN-COSA] CoSA-side commit still pending") become resolvable once these CoSA commits land — the parent owns striking those TODO lines through in their next Lupin session.

**Pre-commit verification** (this CoSA wrap):
- `py_compile` on all 8 Python files (6 modified + 2 new): ✅ **8/8 OK**
- Import-chain check via cosa venv: ✅ `cache_registry.register_invalidator` + `invalidate_all` importable; `docview_manifest.DocviewManifest` + `load_manifest_for_scope` importable; `_scope_registry.ScopeConfig` defaults `manifest=None` `extra_blocklist_patterns=()` (manifest-optional Phase 1 invariant verified)
- DM Phase 0 symbol verification on commons.py: ✅ `RecipientResolutionError` present, `_resolve_dm_recipient` present, `_dispatch_commons_question_received` present, `RegisterQuestionRequest` fields = `['asker_session_id', 'expect_reply', 'question_id', 'recipient_persona', 'recipient_session_id', 'topic', 'ttl_seconds']` (3 new DM kwargs added per Phase 0 Q1-rev/Q3-rev contracts)
- `git diff --stat HEAD` at session start: ✅ 6 modified + 2 untracked match parent attribution exactly

**Daily LoC change analysis** (branch-analyzer, current branch vs main):

| Repo | Branch | Files changed | Added | Removed | Net |
|---|---|---|---|---|---|
| **CoSA** | `wip-v0.1.7-2026.04.23-tracking-lupin-work` | 69 | 6,394 | 2,368 | **+4,026** |
| **Lupin** | `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe` | 500 | 17,190 | 3,532 | **+13,658** |

CoSA Python source breakdown (added lines): 3,763 source code (58.9%) + 843 comments (13.2%) + 1,788 docstrings (28.0%) = 6,394 added · 1,239 removed · net +5,155.

**Repo analysis** (directory-analyzer, current `cosa/` tree): 181,395 total lines across 595 files. Python: 160,319 lines across 512 files (88.4%) — 60.9% source code / 8.0% comments / 31.1% docstrings (Design-by-Contract discipline confirmed). Markdown: 17,387 lines across 69 files (9.6%).

#### Checkpoint | 2026.05.15 PM | Session-end ritual + 2 thematic commits ready (Rio ⚡ borrowed)

**Files**: 10 (2 NEW: `config/cache_registry.py` + `config/docview_manifest.py`; 6 MOD: `agents/prediction_engine/prediction_engine.py` + `rest/routers/_scope_registry.py` + `rest/routers/docs_files.py` + `rest/routers/system.py` + `rest/routers/commons.py` + `rest/routers/notifications.py`; 2 docs: `history.md` + `.claude-session.md`)

**Commits**: pending user workflow execution per `feedback_never_commit_cosa.md`

---


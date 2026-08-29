---
name: spin-up-swe-team
description: Bring the standing SWE build crew online from one directive, with each member's role charter pre-loaded into its brief. The Manager slices the per-role charters out of the load document and spawns an Implementer / Reviewer / Tester crew (scalable, N-of-a-role) via the cosa-voice spawn_sessions tool, then runs the implement → adversarial-review → integration-test → green+reviewed gate. Use whenever the user (or a broadcast) says "spin up your SWE team", "spin up the SWE team for X", "stand up a build crew", "assemble the SWE team", "bring up your engineering crew", "spin up your software team", or otherwise asks the Manager to instantiate the standing build crew against a task. The companion teardown phrase "stand down the SWE team" reaps the crew with mementos. Also invocable explicitly as /spin-up-swe-team [task].
---

# Spin Up SWE Team

Instantiate the **spin-up crew** (Implementer · Reviewer · Tester) against a task, each member coming online already knowing its role — no per-session role re-explanation. This is the intent-activation companion to the `/spin-up-swe-team` slash command; both resolve to the same canonical workflow.

## On invocation

1. **Read the canonical workflow docs in full** — `planning-is-prompting → workflow/swe-team-spin-up.md` (model · activation · lifecycle · gates · teardown · §7 load-document spec) and `workflow/swe-team-roles.md` (the load document — one `##` charter section per role). These are the authoritative source; do NOT substitute a summary.

2. **Confirm the task.** The crew needs a concrete build-shaped task (implement → review → test a feature/fix). If the trigger phrase didn't carry one, ask the user for it before spawning.

3. **Become the Manager** under standing spawn/harvest autonomy. The **standing pair (Manager + Steward) pre-exists and is NOT spawned** — instantiate only the crew.

4. **Slice + spawn.** For each crew role (default one each; scalable to N-of-a-role), slice that role's `##` section verbatim from `swe-team-roles.md`, append THE TASK + the governing spec path + the collection-topic reporting instruction + **ANY IN-FORCE PROVISIONAL MANDATE (see 4a)**, and spawn via `spawn_sessions` (`count=1` per member; role enum Implementer→`author`, Reviewer→`reviewer`, Tester→`observer`; `persona_preference` as a preference, not a guarantee — ratified Q2 fresh-person/stable-charter).

4a. **⭐ APPEND EVERY IN-FORCE PROVISIONAL MANDATE — MANDATORY, EVERY ROLE, NO EXCEPTIONS** (canonical: `workflow/swe-team-spin-up.md` §7.1). **A member receives ONLY its own `##` section — a run-wide directive at the top of the load document is sliced away and reaches nobody.**
   - **Check the TARGET PROJECT's repo root for `MANDATE.md`** — NOT this repo, NOT `workflow/`. **Its existence is the in-force flag**: present ⇒ governs; absent ⇒ nothing to append; `rm` ⇒ gone everywhere at once.
   - **If present, append its directive block VERBATIM to every brief** — manager, implementer, reviewer, tester alike. **Never paraphrase it; paraphrase is how a mandate erodes.**
   - **Place it in the Expectations & gates / done-section, NOT the preamble.** *A mandate at the top gets skimmed; a mandate in the acceptance criteria gets executed.*
   - **⚠️ SCOPED BY CONSTRUCTION**: a crew spawned against `lupin` reads `lupin/MANDATE.md`, finds nothing, and is *structurally incapable* of inheriting another project's deadline. **Never carry a mandate from this repo into a target crew** — that pushes one project's directive onto the whole fleet. Mechanism: `workflow/provisional-mandates.md`.
   - **Why not "tell the Manager to tell them"**: 2026-07-16 — a supersession notice reached **2 of 4** workers; a send bounced off a nonexistent persona, **the bounce reported itself with the roster attached, and was read and moved past**; 3 of 4 briefs carried a defect. **Two hops, both lossy. Here the brief IS the delivery.**

5. **Notify + hand to Steward.** `notify()` the user who came online and the collection topic; `commons_send_to` the Steward your spin-up plan so they observe live.

6. **Run the gate.** implement → adversarial review → integration/e2e green → **verify BOTH green AND reviewed** → commit only on the user's word (re-loop on fail). Steward runs the scaled post-game every cycle. Teardown on *"stand down the SWE team"* reaps the crew with mementos; the standing pair persists.

## If the task is "build an agent that runs by voice"

This is the shape Rick asks for most, so it gets named here rather than left for the
crew to discover. **The answer is one contract entry plus two ratified one-line
opt-ins — not four hand-edited files, and never a new `if`/`elif`.**

- **Load `agentic-voice-workflow` into the Implementer's brief** (skill, or
  `src/workflow/agentic-voice-workflow.md` for the long form). Its compliance
  checklist IS the registration process; do not re-derive it in the brief.
- **The four things a crew gets wrong**, each covered there with its measurement:
  1. **Routing goes through the brain** (`AskFlow`, `src/cosa/rest/v2/flow.py`).
     Adding a *routing* branch is the defect that was removed — a reviewer should
     reject a new routing `if command == ...` on sight. ⚠️ **Job *construction* is
     the exception**: `create_agentic_job()` still dispatches by branch until phase 5
     wires registry lookup, so a new agent DOES add one there. Telling a crew "no
     branches anywhere" leaves their agent unbuildable.
  2. **Reachable ≠ dependable.** A prompt line makes the command reachable today;
     the retrain makes it dependable. Measured 0/5 unlisted vs 5/5 listed on the
     same adapter and training set.
  3. **`scheduled_at` and `monopolize` are queue directives, not agent arguments** —
     they arrive in the same dict as real arguments, and left in place they are
     dropped in silence while the caller believes the job is scheduled.
  4. **New commands start in `shadow`**, not live.
- **Tester's bar**: a green pipeline test does NOT mean voice-reachable. Those are
  different claims and the pipeline test cannot make the second one. Route it
  end-to-end, or say plainly that it is unverified.
- **Reviewer's bar**: registration is not done until the command resolves through
  the registry AND the drift guard (`src/tests/unit/test_v2_registry_drift_guard.py`)
  is green.

Whole picture, written for someone who was in none of these sessions:
`src/rnd/v0.2.0/2026.08.25-agentic-voice-workflow-pass-1-and-2.md`.

## Hard rules

- **Standing pair is never spawned** — only the crew is. Teardown reaps only the crew.
- **Charters are sliced verbatim**, not paraphrased — the durable wording is the point.
- **Hard commit gate**: green AND adversarially-reviewed, non-negotiable; commit/push is the user's call.
- **No-confabulation**: every "done" the Manager accepts is backed by a primary artifact (receipts-before-claims).

## Project configuration

- **Working directory**: the Manager's current project (the crew's `--project` defaults to it).
- **Prefix**: use the repo's `[SHORT_PROJECT_PREFIX]` in any TODO items written.

See `workflow/swe-team-spin-up.md` + `workflow/swe-team-roles.md` for the complete specification, and `.claude/commands/spin-up-swe-team.md` for the explicit command surface + flag list.

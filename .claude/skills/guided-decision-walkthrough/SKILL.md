---
name: guided-decision-walkthrough
description: Walk the user through their pending decisions ONE AT A TIME, each with pros, cons, and an explicit recommendation, via the cosa-voice ask_multiple_choice method, in descending priority. Use this whenever the user asks to "walk me through" the pending decisions / their options / the open items, "walk through my options one by one", "go through my pending decisions", "let's decide the open items", "present these as decisions I can make", "give me one informed decision at a time", or otherwise wants to be guided through a batch of open choices with recommendations. Also invocable explicitly as /plan-decide.
---

# Guided Decision Walkthrough

Drive a series of informed decisions for the user, one at a time, framed with pros/cons + a recommendation, via `ask_multiple_choice`. This is the queue-level companion to the Decision-Question Framing Contract.

## On invocation

1. **Read the canonical workflow** — `planning-is-prompting → workflow/decision-walkthrough.md` — and follow it in full. It is the authoritative source for the ritual, the queue convention, and the recording format.

2. **Gather the queue** — read `## Pending Decisions` from this repo's `TODO.md`. Optionally harvest fresh decisions from open plan-docs / `## Open Questions` / "needs a decision" markers and confirm additions with the user.

3. **Order** descending by priority. Apply the decision-class taxonomy — surface only genuine *user-decisions* (irreversible/outward-facing · prod-behavior needing a product/UX call · genuine ambiguity · scope expansion); pure mandated work is *sequencing*, not a gate. Never manufacture a gate.

4. **For each decision** (state "decision N of M"):
   - **Frame live**: 2–4 options; pros AND cons each; **recommended option first** with `(Recommended)` in its label; one-line rationale. All detail in `abstract`; the spoken `question` is a one-line headline (TTS-brevity).
   - **Ask**: `ask_multiple_choice`, `priority="high"`, a sane `timeout_seconds`, and a `default` keyed by header = the recommended option's exact label (AFK-safe). `multiSelect=true` when options aren't mutually exclusive.
   - **Record**: append the ruling to `## Decisions Log` (ADR-lite: `YYYY-MM-DD — decision → ruling. Why: …`) and inline into the relevant doc when one exists; remove the item from `## Pending Decisions`.

5. **Recap** — brief spoken headline + a rulings table in the `abstract`.

## Hard rules

- Framing Contract is mandatory — pros + cons + recommendation every time, never a bare menu.
- TTS-brevity — spoken `question` is a headline; detail in `abstract`.
- No rubber-stamp gates; AFK-safe defaults; one-at-a-time, blocking, descending priority.

## Project configuration

- **Working directory / TODO path**: this repo's root `TODO.md`.
- **Prefix**: use the repo's `[SHORT_PROJECT_PREFIX]` in any TODO items written.

See `workflow/decision-walkthrough.md` for the complete specification.

# Session-End Ritual for Lupin Project

**Project**: Lupin (Genie-in-the-Box)
**Prefix**: [LUPIN]
**Version**: 1.1

---

> **⚠️ Note**: This command's canonical workflow uses cosa-voice notifications. In conversation mode (`get_session_info().conversation_mode_active=true`), all gates are voice-driven AND spoken responses follow the **TTS Brevity Mandate** — re-crafted conversational prose, NOT verbatim copies of markdown terminal replies. See `workflow/cosa-voice-integration.md` §Conversation Mode for full rules.

---

## Instructions to Claude

**On every invocation of this command:**

1. **MUST use the following project-specific configuration**:
   - **[SHORT_PROJECT_PREFIX]**: [LUPIN]
   - **History file**: /mnt/DATA01/include/www.deepily.ai/projects/lupin/history.md
   - **Planning documents**: /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/rnd/
   - **Archive directory**: /mnt/DATA01/include/www.deepily.ai/projects/lupin/history/
   - **Nested repositories**: /src/cosa/, /src/lupin-plugin-firefox/, /src/lupin-mobile/
   - **Nested repository descriptions**:
     * `/src/cosa/` - CoSA framework (git@github.com:deepily/cosa.git)
     * `/src/lupin-plugin-firefox/` - Firefox plugin sub-repository
     * `/src/lupin-mobile/` - Mobile app sub-repository
   - Do NOT proceed without these parameters

2. **MUST read the canonical workflow document**:
   - Location: planning-is-prompting → workflow/session-end.md
   - This is the ONLY authoritative source for ALL session-end steps
   - Do NOT proceed without reading this document in full
   - The canonical workflow contains: TodoWrite tracking list, token count check, history health check, history update, planning document updates, uncommitted changes summary, commit message proposal, and commit execution (with notifications throughout)

3. **MUST execute the complete session-end ritual**:
   - Execute ALL steps exactly as described in the canonical workflow document (Steps 0, 0.4, 0.5, 1-6)
   - Do NOT skip any steps (including notifications, TodoWrite tracking, health checks, or the **LoC Delta Summary** — canonical §6)
   - Do NOT substitute a shortened or summarized version
   - Do NOT commit without user approval
   - Follow the workflow exactly as documented using the configuration parameters from Step 1

4. **MUST honor the LoC Delta Summary MANDATE** (canonical §6 — renamed from "Day's Work Summary" 2026-05-21; the three obligations are non-optional):
   - **MUST fire**: Step 6 runs unless `--no-summary` was explicit OR §6.1 preflight failed with an explicit skip line. Soft-skip ("we're wrapping up") is a violation.
   - **MUST surface the table**: the rendered markdown table (per §6.4) lands in the closing `notify()`'s `abstract` parameter — not terminal-only.
   - **MUST speak a one-line verdict**: the closing `notify()`'s spoken `message` parameter includes a single short LoC verdict (≈8-15 words) replacing the generic "session ended" sign-off.
   - Parse `--summary` / `--no-summary` and `--baseline` / `--no-baseline` from the invocation arguments.
   - **Defaults**: `--summary` ON, `--baseline` ON.
   - `--baseline` ON without `LUPIN_ROOT` set: skip the Repo Baseline subsection silently (cannot be computed via the native fallback) and append the upgrade-path note to the rendered summary.
   - The CSV doc-link in `abstract` MUST use canonical path-only URL form (`/app/docs?path={project}/io/git-loc-delta/...`); the legacy `&scope=` two-param form is dead syntax per `workflow/doc-viewer-links.md`.

5. **MUST clear the Step-6 Accountability Checklist** before declaring session-end complete:
   - Did Step 6 fire? Did the table land in abstract? Did the spoken message carry a LoC verdict? Does the CSV doc-link use canonical URL form?
   - Full checklist: canonical workflow doc § Final Verification → Step-6 Accountability Checklist
   - If any checkbox unchecked: re-fire Step 6, re-issue the closing notify() with the missing elements added.

---

## Usage

```bash
/plan-session-end                             # default: full ritual including LoC Delta Summary + baseline
/plan-session-end --no-summary                # skip Step 6 entirely (fast wrap-up)
/plan-session-end --no-baseline               # render summary without repo-baseline comparison
/plan-session-end --no-summary --no-baseline  # equivalent to --no-summary alone
```

Invoked when ending the **entire work session** for the day.

**Natural language triggers** (any of these should invoke THIS command):
- "Let's end the session"
- "Session end"
- "Wrap up the session"
- "Done for the day"
- "Calling it for today"
- "Close out the session"
- "That's it for today"

**⚠️ DISAMBIGUATION — do NOT confuse with `/plan-bug-fix-mode-wrap`**:
- This command ends the **entire work session** (history archive, full commit, session close)
- `/plan-bug-fix-mode-wrap` wraps a **single bug fix** (document + commit one fix, stay in session)
- Key signal: if the user mentions "session", "done for the day", "calling it" → use THIS command
- Key signal: if the user mentions "bug", "fix", or "this" → use `/plan-bug-fix-mode-wrap`

---

## Notes

This slash command is a **reference wrapper** that reads the canonical workflow document on every invocation. This ensures:
- Always up-to-date implementation when canonical doc is improved
- Single source of truth for the session-end ritual
- Demonstrates the workflow pattern for other projects
- This file serves as a working example for other repos

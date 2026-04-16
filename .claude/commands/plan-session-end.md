# Session-End Ritual for Lupin Project

**Project**: Lupin (Genie-in-the-Box)
**Prefix**: [LUPIN]
**Version**: 1.0

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
   - Execute ALL steps exactly as described in the canonical workflow document (Steps 0, 0.4, 0.5, 1-5)
   - Do NOT skip any steps (including notifications, TodoWrite tracking, or health checks)
   - Do NOT substitute a shortened or summarized version
   - Do NOT commit without user approval
   - Follow the workflow exactly as documented using the configuration parameters from Step 1

---

## Usage

```bash
/plan-session-end
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

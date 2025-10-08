# Session-Start for LUPIN Project

**Project**: LUPIN
**Prefix**: [LUPIN]

---

## Instructions to Claude

**On every invocation of this command:**

1. **Read the canonical workflow**: planning-is-prompting → workflow/session-start.md

2. **Execute the session initialization routine** as described in the canonical document

3. **Apply project-specific configuration**:
   - **[SHORT_PROJECT_PREFIX]**: [LUPIN]
   - **History file**: /mnt/DATA01/include/www.deepily.ai/projects/genie-in-the-box/history.md

4. **Execute the following**:
   - Read history.md file
   - Display current status summary (top 3 lines from history.md)
   - Show most recent TODO list from latest session entry
   - Identify current implementation document (if referenced in history.md header)
   - Provide context for resuming work

---

## Usage

```bash
/plan-session-start
```

Invoked at the beginning of each work session to load context and understand project status.

---

## Notes

This slash command is a **reference wrapper** that reads the canonical workflow document on every invocation. This ensures:
- Always up-to-date implementation when canonical doc is improved
- Single source of truth for session initialization
- Demonstrates the workflow pattern for other projects
- This file serves as a working example for other repos

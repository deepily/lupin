# Session End Ritual for Lupin Project

This document contains the comprehensive end-of-session workflow extracted from the global and local Claude.MD configuration files. This prompt should be executed when wrapping up work sessions.

## Overview

At the end of our work sessions, perform the following wrapup ritual with **[LUPIN]** prefix for all notifications. Send notifications after completing each step to keep me updated on progress:

## 0) Use Notification Script Throughout

**Mandate**: Keep me updated with notifications after completing each step of the end-of-session ritual.

**Script Location**: `./scripts/notify.sh` (from project root)

**Command Format**:
```bash
./scripts/notify.sh "[LUPIN] MESSAGE" --type=TYPE --priority=PRIORITY --target-user=ricardo.felipe.ruiz@gmail.com
```

**When to Send Notifications**:
- After completing each major step
- Task completion milestones
- Progress updates
- When needing approval or blocked

**Priority Levels**:
- `urgent`: Errors, blocked, time-sensitive questions
- `high`: Approval requests, important status updates
- `medium`: Progress milestones
- `low`: Minor updates, todo completions, informational notices

**Types**: task, progress, alert, custom

**Example Notifications**:
```bash
./scripts/notify.sh "[LUPIN] ✅ Session history updated" --type=progress --priority=low
./scripts/notify.sh "[LUPIN] Ready for commit approval" --type=task --priority=medium
./scripts/notify.sh "[LUPIN] 🎉 Session wrap-up complete" --type=task --priority=low
```

## 1) Update Session History

**Target**: Record in main `history.md` under current month section

**Requirements**:
- Use date format: `yyyy.mm.dd`
- Sort newest changes at TOP (reverse chronological)
- Maintain 30-day window in main file
- If `history.md` approaches 25k tokens, archive older months to `history/YYYY-MM-history.md` first

**Content Structure**:
- Current project status summary (top 3 lines)
- Session summary with accomplishments
- Keep track of where we are and write a quick todo list for tomorrow's restart

**3-Tier Hierarchical Structure**:
- **Tier 1**: `history.md` (main index, ~3,000 tokens)
  - Current project status summary
  - Recent 30 days of sessions only
  - Links to archived monthly files
  - Current implementation document reference
  - Active TODO items and immediate next steps

- **Tier 2**: `history/YYYY-MM-history.md` (monthly archives, 8k-12k tokens each)
  - Complete session details for each month
  - Cross-references to session detail files when needed

- **Tier 3**: `history/sessions/YYYY-MM-DD-session-N-title.md` (detailed sessions, 1k-3k tokens)
  - Full session breakdowns for complex/milestone sessions
  - Created only when monthly file exceeds 15k tokens

**Monthly Rotation Rules**:
- **New month starts**: Archive previous month's sessions to `history/YYYY-MM-history.md`
- **Monthly file > 15k tokens**: Extract complex sessions to `sessions/` directory
- **Main history.md approaching 25k**: Archive older months immediately

## 2) Update Planning and Tracking Documents

**Target**: Documents in the repo's `src/rnd` directory

**Requirements**:
- Update any relevant planning documents modified during session
- Add links to new research documents in readme file
- All research documents should begin with date format: `yyyy.mm.dd`

## 3) Summarize Uncommitted Changes

**Command**: Use `git status` to track file changes, creations, and deletions

**Output Format**: Comprehensive summary of:
- Modified files
- New files created
- Deleted files
- Staged vs unstaged changes

**Alternative Command**: For tree view of untracked files:
```bash
git ls-files --others --exclude-standard | tree --fromfile -a
```

## 4) Propose Commit Message

**Format**: Use summary + listed items format

**Guidelines**:
- Concise summary line
- Bullet points listing main changes
- Focus on "why" rather than just "what"

## 5) Commit Changes

**Critical Requirements**:
- **MUST ALWAYS stop and wait for user response** for both commits and push confirmations
- DO NOT continue to next steps until user responds
- After approval, commit and offer to push
- Note: Not all repos can be pushed, but always ask

**Git Safety Protocol**:
- NEVER run destructive/irreversible git commands (like push --force, hard reset, etc) unless user explicitly requests
- NEVER skip hooks (--no-verify, --no-gpg-sign, etc) unless user explicitly requests
- NEVER run force push to main/master, warn user if they request it
- Avoid `git commit --amend` unless (1) user explicitly requested amend OR (2) adding edits from pre-commit hook

**Repository Management**:
- **CRITICAL**: Only manage git operations for the parent Lupin repository
- NEVER attempt to manage git state of the CoSA repository (`/src/cosa/`)
- CoSA is a separate Git repository that must be managed separately


## Final Verification

At the end of every session when user says goodbye, verify completion of the mandatory end-of-session summarization documentation.

## Project-Specific Context

**Project**: Lupin (evolved from Genie-in-the-Box)
**Prefix**: [LUPIN]
**History Location**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin/history.md`
**Current Implementation Document**: Referenced at top of history.md

**Key Archived Periods**:
- 2024.12-2025.05: PEFT training, agent migrations, Flask→FastAPI transition
- 2025.06: Lupin renaming, notification system, WebSocket foundation
- 2025.07: Progressive TTS streaming, user routing architecture
- 2025.08: Unit testing framework, Fresh Queue UI, audio debugging

**Archive Location**: `history/` directory with monthly organization

## Special Considerations

- When working with multiple repos, always use `[LUPIN]` prefix for clarity
- Maintain organization across all steps to demonstrate thoroughness
- Always wait for explicit approval before committing changes
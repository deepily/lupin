---
name: nested-repo-management
description: Git safety rules for nested repositories in Lupin. Use when committing changes, pushing code, running git commands, or working with the Firefox plugin or mobile app repositories.
metadata:
  author: lupin-team
  version: "1.0"
  last-updated: "2026-10-02"
---

# Nested Repository Management

**CRITICAL**: Lupin contains nested Git repositories that must be managed separately.

**CoSA is not one of them.** It was folded into the Lupin mono-repo on 2026-05-29: `src/cosa/` is ordinary in-tree Lupin source, and the old `deepily/cosa` GitHub repository is archived (read-only; the GitHub API reads `archived = True`, read 2026-10-01). Stage and commit its files from Lupin like any other source. The old history is kept off-tree at `/mnt/DATA02/cosa-git-archive-2026.05.29/`.

## Repository Structure

| Repository | Location | Remote | Management |
|------------|----------|--------|------------|
| **Lupin** (parent) | `/` | lupin repo | Normal via `/plan-session-end` |
| **Firefox Plugin** | `/src/lupin-plugin-firefox/` | separate repo | Independent |
| **Mobile App** | `../lupin-mobile/` (a sibling of Lupin, not nested) | separate repo | Independent |

## Safety Rules

### DO ✅
- Stage/commit/push changes in parent Lupin repo
- Use `/plan-session-end` for Lupin commits
- Manage nested repos in their own sessions/contexts
- Read nested repo's CLAUDE.md when working there

### DON'T ❌
- **NEVER** run git commands in nested repo directories from parent context
- **NEVER** commit nested repo changes from Lupin session
- **NEVER** read nested repo history.md from Lupin context

## How /plan-session-end Handles This

The workflow automatically:
1. Detects changes in nested repos
2. Acknowledges but does NOT commit them
3. Filters nested paths from git operations
4. Reminds you to manage them separately

**You'll see**:
```
⚠️ Detected changes in nested repositories:
• /src/lupin-plugin-firefox/ (1 new file)

These are separate Git repositories and will not be included in this commit.
Reminder: Manage nested repositories in their own sessions/contexts.
```

## Detecting Nested Repos

```bash
# Find all nested .git directories
find . -name ".git" -type d | grep -v "^./.git$"
```

## Working in Nested Repositories

### When working in Firefox Plugin
- Manage as independent project
- Has own git history and workflows

### When working in Mobile App
- Manage as independent project
- Has own git history and workflows

## History Files to Ignore

**From Lupin context, do NOT read**:
- `src/lupin-plugin-firefox/history.md`
- `../lupin-mobile/history.md` (sibling repo)

These are managed by their respective repositories.

## Anti-Patterns

- **Don't** try to "fix" untracked files in nested repos
- **Don't** run `git status` expecting nested repo files
- **Don't** commit "all changes" - check what's actually in Lupin

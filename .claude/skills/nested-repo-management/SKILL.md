---
name: nested-repo-management
description: Git safety rules for nested repositories in Lupin. Use when committing changes, pushing code, running git commands, managing CoSA submodule, or working with the Firefox plugin or mobile app repositories.
metadata:
  author: lupin-team
  version: "1.0"
  last-updated: "2026-01-28"
---

# Nested Repository Management

**CRITICAL**: Lupin contains multiple nested Git repositories that must be managed separately.

## Repository Structure

| Repository | Location | Remote | Management |
|------------|----------|--------|------------|
| **Lupin** (parent) | `/` | lupin repo | Normal via `/plan-session-end` |
| **CoSA** | `/src/cosa/` | `git@github.com:deepily/cosa.git` | Separate context |
| **Firefox Plugin** | `/src/lupin-plugin-firefox/` | separate repo | Independent |
| **Mobile App** | `/src/lupin-mobile/` | separate repo | Independent |

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
- **NEVER** offer to stage/commit/push CoSA changes when in Lupin

## How /plan-session-end Handles This

The workflow automatically:
1. Detects changes in nested repos
2. Acknowledges but does NOT commit them
3. Filters nested paths from git operations
4. Reminds you to manage them separately

**You'll see**:
```
⚠️ Detected changes in nested repositories:
• /src/cosa/ (3 modified files)
• /src/lupin-mobile/ (1 new file)

These are separate Git repositories and will not be included in this commit.
Reminder: Manage nested repositories in their own sessions/contexts.
```

## Detecting Nested Repos

```bash
# Find all nested .git directories
find . -name ".git" -type d | grep -v "^./.git$"
```

## Working in Nested Repositories

### When working in CoSA (`cd src/cosa/`)
- Read `/src/cosa/CLAUDE.md` for CoSA-specific guidance
- Use CoSA's own session management
- Commit to CoSA repository separately

### When working in Firefox Plugin
- Manage as independent project
- Has own git history and workflows

### When working in Mobile App
- Manage as independent project
- Has own git history and workflows

## History Files to Ignore

**From Lupin context, do NOT read**:
- `src/lupin-plugin-firefox/history.md`
- `src/cosa/history.md`
- `src/lupin-mobile/history.md`

These are managed by their respective repositories.

## Anti-Patterns

- **Don't** `git add` files in `/src/cosa/` from Lupin
- **Don't** try to "fix" untracked files in nested repos
- **Don't** run `git status` expecting nested repo files
- **Don't** commit "all changes" - check what's actually in Lupin

---
description: Manage TODO.md size with adaptive archival strategy (status × age aware)
allowed-tools: Bash(.*), Read, Write, Edit, Grep
arguments:
  - name: mode
    description: Operation mode (check|archive|analyze|dry-run)
    required: false
    default: check
  - name: stale-pending-days
    description: Threshold (in days) for surfacing stale `[ ]` items in the review report
    required: false
    default: 30
  - name: closed-section-days
    description: Threshold (in days) for considering a fully-`[x]` section archivable
    required: false
    default: 14
---

# TODO Size Management (Lupin Project)

**Canonical Design**: `src/rnd/v0.1.7/2026.05.01-todo-size-management/01-design.md`
**Mirrors**: `/history-management` (same operational pattern)
**Companion R&D**: `src/rnd/v0.1.7/2026.05.01-todo-size-management/90-execution-log.md`

**Project Context**:
- **Project**: Lupin (Genie-in-the-Box)
- **Prefix**: [LUPIN]
- **TODO File**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin/TODO.md`
- **Archive Directory**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin/todo-history/`
- **Notification Target**: ricardo.felipe.ruiz@gmail.com
- **Session-End Command**: `/plan-session-end` (Step 0.5 health-check candidate)

---

## Why This Skill Exists

`history.md` has a well-defined adaptive-archival workflow. `TODO.md` had none — the canonical PIP doc explicitly said "TODO.md is NEVER archived" and the only soft guidance was "prune completed items >7 days old." That proved insufficient: as of 2026-05-01 the file was at **31,518 tokens (126% of the 25k limit)** with **199 pending items**.

This skill closes the gap, with one **important asymmetry** from `history-management`:

> History archival is **mechanical** — cut by date, every entry is immutable past-tense.
> TODO archival is **semantic** — cut by **status × age**. A pending `[ ]` item is load-bearing regardless of age; a completed `[x]` item is dead weight after a couple weeks.

So this skill **only ever archives closed sections by age, never pending items**, and surfaces a separate "stale-pending review" list for human disposition.

---

## Quick Reference

### Modes

- **check** (default): Health check with token count + severity report
- **archive**: Execute adaptive archival of CLOSED sections older than `closed-section-days` + emit stale-pending review (with user confirmation)
- **analyze**: Deep stats — closed-section ratio, pending-age distribution, growth velocity
- **dry-run**: Simulation; prints proposed diffs and never writes

### Usage Examples

```bash
/todo-size-management
/todo-size-management mode=check
/todo-size-management mode=dry-run
/todo-size-management mode=archive
/todo-size-management mode=archive closed-section-days=21 stale-pending-days=45
/todo-size-management mode=analyze
```

---

## Token Thresholds (mirror history-management)

| Severity | Tokens | Notify priority |
|---|---|---|
| 🚨 CRITICAL | ≥19,000 | urgent |
| ⚠️ WARNING | ≥17,000 | high |
| ℹ️ MONITOR | breach forecast <14d | medium |
| ✅ HEALTHY | else | none |

**Retention target after archival**: 8-12k tokens.

---

## Section Classification

Walk `TODO.md` from top to bottom. For each `## ` section, classify it:

| Classification | Definition | Archivable? |
|---|---|---|
| **CLOSED** | All bullets are `[x]` | YES if section date ≥ `closed-section-days` |
| **MIXED** | Both `[x]` and `[ ]` | NO — leave whole section in place |
| **OPEN** | Has `[ ]` items | NO regardless of age |
| **HEADER/META** | Top metadata block | NO |

**Date detection priority**:
1. `(Session XXXXXXXX, YYYY-MM-DD)` in the heading (most common)
2. `— YYYY-MM-DD` or `(YYYY-MM-DD)` in the heading
3. `YYYY.MM.DD` (alternate format)
4. **No date extractable** → fail-safe = NOT archivable (conservative)

---

## Implementation: Check Mode

When invoked with `mode=check` (default):

### Step 1: Count Current Tokens
```bash
TODO_FILE="/mnt/DATA01/include/www.deepily.ai/projects/lupin/TODO.md"
CURRENT_TOKENS=$(/home/rruiz/.claude/scripts/get-token-count.sh "$TODO_FILE" 2>/dev/null \
    || awk '{ words += NF } END { printf "%d\n", words * 1.33 }' "$TODO_FILE")
```

### Step 2: Section Inventory
```bash
TOTAL_SECTIONS=$(grep -c "^## " "$TODO_FILE")
PENDING_BULLETS=$(grep -c "^\s*-\s\[ \]" "$TODO_FILE")
COMPLETED_BULLETS=$(grep -c "^\s*-\s\[x\]" "$TODO_FILE")
```

### Step 3: Determine Severity
```
IF current_tokens >= 19000:
    severity = "🚨 CRITICAL"; notify_priority = "urgent"
ELIF current_tokens >= 17000:
    severity = "⚠️ WARNING"; notify_priority = "high"
ELIF forecast_breach <= 14:
    severity = "ℹ️ MONITOR"; notify_priority = "medium"
ELSE:
    severity = "✅ HEALTHY"; notify_priority = none
```

### Step 4: Display Report
```
📊 TODO Health Report
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Current Size:     {CURRENT_TOKENS} tokens
Sections:         {TOTAL_SECTIONS} (## headings)
Pending bullets:  {PENDING_BULLETS}
Completed bullets:{COMPLETED_BULLETS}
Status:           {SEVERITY}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{If WARNING/CRITICAL: recommend `mode=archive`}
{If HEALTHY: report and exit}
```

### Step 5: Notify (if needed)
For WARNING/CRITICAL — call cosa-voice `notify(...)` with the appropriate priority.

---

## Implementation: Archive Mode

When invoked with `mode=archive`:

### Step 1: Walk Sections + Classify

For each `## ` section, extract:
- Heading text
- Embedded date (per priority list above) → age in days
- Bullet count by status (`[x]` vs `[ ]`)
- Classification (CLOSED / MIXED / OPEN / HEADER)

### Step 2: Identify Archive Candidates

Collect all CLOSED sections with `age_days >= closed_section_days`.

### Step 3: Identify Stale-Pending

Collect all OPEN/MIXED sections with `age_days >= stale_pending_days` and gather the `[ ]` bullets within for the review report.

### Step 4: Preview Diff to User

Show:
- **Will archive**: N sections, M closed bullets, ~X tokens reclaimed
- **Stale-pending review**: Y items in Z sections (NOT archived; user decides)
- Proposed archive filename (e.g., `todo-history/2026-04-10-to-23-todo.md`)
- Date range covered
- Token forecast: before → after

**Wait for explicit user confirmation before writing.**

### Step 5: Execute Archive

1. Build the archive file (verbatim copy of archived sections + metadata header per design §4.4)
2. Excise those sections from `TODO.md`
3. Append a `## 📦 Archived` cross-reference block at the bottom of `TODO.md`
4. Update the `Last updated` line to current date + session ID
5. Verify token count matches forecast

### Step 6: Print Stale-Pending Review

```
🟡 Stale-pending review ({N} items in sections >{stale_pending_days}d old):
  • [LUPIN] {bullet text} — {section heading}
  ...

Recommend: review each → mark resolved / drop / re-stamp into a current section.
NOTE: nothing was auto-archived from this list.
```

### Step 7: Notify Completion
```
notify("[LUPIN] ✅ TODO archived: {ARCHIVE_FILENAME}, {tokens_before}→{tokens_after}",
       priority="medium")
```

---

## Implementation: Analyze Mode

When invoked with `mode=analyze`:

Generate a markdown report saved to `src/rnd/YYYY.MM.DD-todo-analysis.md`:

1. **Section inventory**: count by classification (CLOSED / MIXED / OPEN)
2. **Age distribution**: histogram of section ages in 7-day buckets
3. **Pending-age leaderboard**: top 10 oldest `[ ]` items
4. **Closed-section ratio**: % of sections that could be archived today
5. **Velocity**: tokens added per session over the last 14 days (best-effort from git log)
6. **Recommendations**: suggest threshold tuning if defaults look off

---

## Implementation: Dry-Run Mode

When invoked with `mode=dry-run`:

1. Run full classify + archive-candidate selection (same as Archive mode Steps 1-3)
2. Print everything Archive mode would print at preview stage
3. **Do NOT write any files**
4. Final line: `🔶 Dry-run complete — no changes made`

Perfect for sanity-checking thresholds before committing to an archive.

---

## Integration with Session-End Workflow

This command is a candidate for `/plan-session-end` Step 0.5 (parallel to `/history-management`).

**Invocation**:
```
/todo-size-management mode=check
```

**Behavior**:
- ✅ HEALTHY: Continue normally
- ℹ️ MONITOR: Display warning, continue
- ⚠️ WARNING / 🚨 CRITICAL: Pause and present:
  1. Archive now (`/todo-size-management mode=archive`)
  2. Defer to next session (add to TODO entry)
  3. Continue anyway (log decision)

---

## Technical Implementation Notes

### Token Counting
- Approximation: `word_count × 1.33`
- Actual: Use global `~/.claude/scripts/get-token-count.sh` if present
- Round up to nearest hundred for reports

### Date Extraction Regex
```bash
# Try in order; first match wins:
\(Session [0-9a-f]{8,12},\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\)
—\s*([0-9]{4}-[0-9]{2}-[0-9]{2})
\(([0-9]{4}-[0-9]{2}-[0-9]{2})
([0-9]{4}\.[0-9]{2}\.[0-9]{2})
```

### Section Boundary Detection
- A section runs from one `^## ` line to the next `^## ` line (exclusive)
- Sub-headings (`### `) belong to their parent `## ` section

### Archive Filename Generation
```bash
# Pull min/max dates from sections being archived
FIRST=2026-04-10
LAST=2026-04-23
ARCHIVE_NAME="todo-history/${FIRST}-to-$(echo $LAST | cut -d'-' -f3)-todo.md"
# → "todo-history/2026-04-10-to-23-todo.md"
```

---

## Error Handling

### File Not Found
```bash
[ -f "$TODO_FILE" ] || { echo "❌ TODO.md not found"; exit 1; }
```

### Invalid Mode
```bash
[[ "$MODE" =~ ^(check|archive|analyze|dry-run)$ ]] \
    || { echo "❌ Invalid mode '$MODE' — use check|archive|analyze|dry-run"; exit 1; }
```

### Archive Directory Not Writable
```bash
mkdir -p "$ARCHIVE_DIR"
[ -w "$ARCHIVE_DIR" ] || { echo "❌ Cannot write to $ARCHIVE_DIR"; exit 1; }
```

### Date Extraction Failure
- Section with no extractable date → log warning, treat as NOT archivable, continue

---

## Testing

### Test Check Mode
```bash
/todo-size-management mode=check
# Should display health report; expect 🚨 CRITICAL today
```

### Test Dry-Run Mode
```bash
/todo-size-management mode=dry-run
# Should preview proposed archive + stale-pending list, write nothing
```

### Test Archive Mode (CAUTIOUSLY — use a backup!)
```bash
cp TODO.md TODO.md.backup
/todo-size-management mode=archive
# Confirm prompts; verify ≤12k after; verify cross-reference link added
# Restore if needed: mv TODO.md.backup TODO.md
```

---

## Future Enhancements

1. **Auto-archive** with no confirmation (gate behind explicit `--yes` flag)
2. **MIXED-section partial excision** — pull only the `[x]` bullets out of a MIXED section into the archive (currently leaves whole section in place)
3. **Velocity tracking** — track token counts in git commit messages for accurate forecasting
4. **PIP promotion** — once stable, lift to `planning-is-prompting/workflow/todo-size-management.md` and update PIP's "TODO.md is NEVER archived" stance

---

## References

- **Design**: `src/rnd/v0.1.7/2026.05.01-todo-size-management/01-design.md`
- **Execution log**: `src/rnd/v0.1.7/2026.05.01-todo-size-management/90-execution-log.md`
- **Sibling skill**: `.claude/commands/history-management.md`
- **Canonical TODO doc** (which this extends): `planning-is-prompting/workflow/todo-management.md`
- **Global config**: `~/.claude/CLAUDE.md` (TODO.md MANAGEMENT section)

---

## Version History

**v1.0** (2026-05-01, Session 92ece47c) — Initial implementation
- Mirrors `/history-management` shape
- Adds status × age semantics for safe TODO-specific archival
- Four operational modes
- Stale-pending review surface (never auto-archives pending work)

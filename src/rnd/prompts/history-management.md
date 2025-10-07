# History Management Workflow (Reference Copy)

> **⚠️ SYNC NOTE**: This is a reference copy for convenience.
>
> **Canonical Workflow** (Master): `/mnt/DATA01/include/www.deepily.ai/projects/planning-is-prompting/workflow/history-management.md`
>
> **Executable Slash Command**: `.claude/commands/history-management.md`
>
> **Purpose**: Local reference for understanding the workflow. May be removed in future to reduce redundancy.

---

## Quick Overview

The history-management workflow prevents history.md from exceeding 25,000 token limits through:

- **Real-time monitoring**: Token count + velocity forecasting
- **Adaptive archival**: Smart boundary detection at milestones/week/day breaks
- **Dual notifications**: CLI display + notify-claude alerts
- **Four modes**: check, archive, analyze, dry-run
- **Session-end integration**: Automatic health check before updating history

---

## Usage (Lupin Project)

### Health Check
```bash
/history-management
# or
/history-management mode=check
```

### Create Archive
```bash
/history-management mode=archive
```

### Analyze Trends
```bash
/history-management mode=analyze
```

### Safe Testing
```bash
/history-management mode=dry-run
```

---

## Token Thresholds

- **🚨 CRITICAL** (≥22k tokens): Immediate action required
- **⚠️ WARNING** (≥20k tokens): Archive recommended
- **ℹ️ MONITOR** (breach <14 days): Watch closely
- **✅ HEALTHY**: No action needed

---

## Archive Naming Convention

**Partial month** (during active month):
```
history/2025-09-03-to-23-history.md
history/2025-09-24-to-30-history.md
```

**Complete month** (if archived as single unit):
```
history/2025-08-history.md
```

**Visual Storytelling**: Multiple archives per month = high-intensity period

Example - Busy September (4 archives):
```
history/2025-09-03-to-10-history.md
history/2025-09-11-to-18-history.md
history/2025-09-19-to-23-history.md
history/2025-09-24-to-30-history.md
```

Example - Calm July (1 archive):
```
history/2025-07-01-to-31-history.md
```

---

## Adaptive Granularity

**Target**: Keep 8-12k tokens in main history.md

**Typical retention**: 7-14 days of recent history

**Minimum retention**: 5 days for context

**Calculation** (adaptive based on current size):
- Current ≥25k tokens → Keep 8k (aggressive)
- Current ≥22k tokens → Keep 10k (moderate)
- Current <22k tokens → Keep 12k (conservative)

---

## Boundary Detection Priority

1. **Most recent major milestone** (✅ COMPLETE, 🎯 ACHIEVEMENT)
2. **Most recent week boundary** (Sunday date)
3. **Most recent day boundary** with <3 sessions
4. **Token-based split** keeping last 8-12k tokens

---

## Session-End Integration

Automatically runs as **Step 0.5** during `/lupin-session-end`:

1. Check history health
2. If WARNING/CRITICAL:
   - Pause workflow
   - Present options:
     * [1] Archive now (~3-5 min)
     * [2] Archive next session (add to TODO)
     * [3] Continue anyway (manual handling)
3. Execute choice
4. Resume normal session-end steps

---

## Complete Documentation

For full details, algorithms, templates, and implementation guidance, see:

**Canonical Workflow**: `/mnt/DATA01/include/www.deepily.ai/projects/planning-is-prompting/workflow/history-management.md`

**Slash Command**: `.claude/commands/history-management.md`

**Global Config**: `/home/rruiz/.claude/CLAUDE.md` (HISTORY DOCUMENT MANAGEMENT section)

---

## Version

**v1.0** (2025.09.30) - Initial reference copy

**Sync Status**: In sync with canonical workflow v1.0

**Last Updated**: 2025.09.30

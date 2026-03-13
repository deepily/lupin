---
description: Manage history.md size with adaptive archival strategy
allowed-tools: Bash(.*), TodoWrite, Read, Write, Edit, Grep
arguments:
  - name: mode
    description: Operation mode (check|archive|analyze|dry-run)
    required: false
    default: check
  - name: force-split
    description: Force archive even if not needed (for testing)
    required: false
    default: false
---

# History Management (Lupin Project)

**Canonical Workflow**: This command implements the history management workflow defined in:
`/mnt/DATA01/include/www.deepily.ai/projects/planning-is-prompting/workflow/history-management.md`

**Project Context**:
- **Project**: Lupin (Genie-in-the-Box)
- **Prefix**: [LUPIN]
- **History File**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin/history.md`
- **Archive Directory**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin/history/`
- **Notification Target**: ricardo.felipe.ruiz@gmail.com
- **Session-End Command**: `/lupin-session-end`

---

## Quick Reference

### Modes
- **check** (default): Health check with dual notification (CLI + notify-claude-async)
- **archive**: Execute adaptive archival split with user confirmation
- **analyze**: Deep trend analysis and optimization recommendations
- **dry-run**: Simulation mode showing what would happen without executing

### Usage Examples
```bash
# Health check (default)
/history-management

# Explicit check
/history-management mode=check

# Create archive interactively
/history-management mode=archive

# Analyze trends
/history-management mode=analyze

# Safe testing
/history-management mode=dry-run
```

---

## Implementation: Check Mode

When invoked with `mode=check` (or no mode parameter):

### Step 1: Count Current Tokens
```bash
# Use global token counting script
CURRENT_TOKENS=$(/home/rruiz/.claude/scripts/get-token-count.sh /mnt/DATA01/include/www.deepily.ai/projects/lupin/history.md)
```

### Step 2: Calculate Velocity (7-day)
```bash
# Get token count from 7 days ago (approximation via git log)
# For now, use simplified approach: estimate from current growth rate
# Future enhancement: Track token counts in git history
```

### Step 3: Determine Severity
```
IF current_tokens >= 22000:
    severity = "🚨 CRITICAL"
    notify_priority = "urgent"
ELSE IF current_tokens >= 20000:
    severity = "⚠️ WARNING"
    notify_priority = "high"
ELSE IF forecast_breach <= 14 days:
    severity = "ℹ️ MONITOR"
    notify_priority = "medium"
ELSE:
    severity = "✅ HEALTHY"
    notify_priority = none
```

### Step 4: Display Report
```
📊 History Health Report
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Current Size: {CURRENT_TOKENS} tokens
Velocity: {VELOCITY_7D} tok/day (7d estimate)
Status: {SEVERITY}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{If WARNING/CRITICAL: Recommendations}
```

### Step 5: Send Notification (if needed)
```bash
if [ severity != "HEALTHY" ]; then
    notify-claude-async "[LUPIN] ${severity} History.md at ${CURRENT_TOKENS} tokens" \
        --type=alert --priority=${notify_priority}
fi
```

---

## Implementation: Archive Mode

When invoked with `mode=archive`:

### Step 1: Read & Analyze Current History
```bash
# Read the entire history.md file
history_content=$(cat /mnt/DATA01/include/www.deepily.ai/projects/lupin/history.md)

# Count total lines
total_lines=$(wc -l < /mnt/DATA01/include/www.deepily.ai/projects/lupin/history.md)
```

### Step 2: Find Optimal Split Point

**Use Adaptive Boundary Detection Algorithm** (from canonical workflow):

1. **Search for major milestones** (Priority 1):
   ```bash
   # Find lines with completion markers
   grep -n "✅ COMPLETE\|🎯 ACHIEVEMENT\|PHASE.*COMPLETE" history.md
   ```

2. **Search for week boundaries** (Priority 2):
   ```bash
   # Find Sunday dates (#### YYYY.MM.DD format where day is Sunday)
   # This requires date calculation
   ```

3. **Search for light days** (Priority 3):
   ```bash
   # Find dates with < 3 session entries
   ```

4. **Token-based split** (Fallback):
   ```bash
   # Calculate line number that would leave 8-12k tokens
   TARGET_RETENTION=10000  # Moderate retention
   RETENTION_WORDS=$(echo "$TARGET_RETENTION / 1.33" | bc)
   # Find line number from end that matches this word count
   ```

### Step 3: Preview & Get Confirmation

Show user proposed split with:
- Archive filename (e.g., `2025-09-03-to-23-history.md`)
- Date range
- Session count
- Token counts (before/after)
- Preview of content boundaries

**Wait for user confirmation** before proceeding.

### Step 4: Execute Archive

1. **Extract archive content** (lines from start to split point)
2. **Create archive file** with metadata template
3. **Trim main history.md** (keep lines from split point to end)
4. **Update cross-reference links** in main history.md
5. **Verify token reduction**

### Step 5: Notify Completion
```bash
notify-claude-async "[LUPIN] ✅ History archived: ${ARCHIVE_FILENAME} created" \
    --type=progress --priority=low --target-user=ricardo.felipe.ruiz@gmail.com
```

---

## Implementation: Analyze Mode

When invoked with `mode=analyze`:

### Generate Analysis Report

1. **Session Frequency**:
   - Count sessions per day/week/month
   - Identify patterns

2. **Token Density**:
   - Calculate average tokens per session
   - Find heavy sessions (>500 tokens)

3. **Archive Structure**:
   - List all existing archives
   - Calculate total archived vs. active content

4. **Velocity Trends**:
   - Show growth rate over time
   - Forecast future archival needs

5. **Recommendations**:
   - Suggest optimizations
   - Identify candidates for session detail extraction

**Output**: Markdown report saved to `src/rnd/YYYY.MM.DD-history-analysis.md`

---

## Implementation: Dry-Run Mode

When invoked with `mode=dry-run`:

### Simulation Without Changes

1. Run full archive analysis (as in archive mode)
2. Calculate proposed split point
3. Show all details (filename, dates, token counts)
4. Display "This is a simulation" message
5. **DO NOT create files or modify history.md**

Perfect for testing before committing to an archive.

---

## Integration with Session-End Workflow

This command is automatically invoked during `/lupin-session-end` as **Step 0.5**.

**Invocation**:
```
/history-management mode=check
```

**Behavior**:
- If ✅ HEALTHY: Continue to Step 1 normally
- If ℹ️ MONITOR: Display warning, continue to Step 1
- If ⚠️ WARNING or 🚨 CRITICAL: Pause and present options:
  1. Archive now (invoke `/history-management mode=archive`)
  2. Archive next session (add to TODO)
  3. Continue anyway (log decision)

---

## Technical Implementation Notes

### Token Counting
- **Approximation**: word_count × 1.33
- **Actual**: Use token counter if available
- **Conservative**: Round up to nearest hundred

### Velocity Tracking (Future Enhancement)
- Track token counts in git commit messages
- Build historical velocity database
- Improve forecast accuracy

### Archive Filename Generation
```bash
# Extract first and last session dates from content
FIRST_DATE=$(grep -m 1 "^#### [0-9]" content | sed 's/#### //')
LAST_DATE=$(grep "^#### [0-9]" content | tail -1 | sed 's/#### //')

# Convert YYYY.MM.DD to YYYY-MM-DD
FIRST=$(echo $FIRST_DATE | tr '.' '-')
LAST=$(echo $LAST_DATE | cut -d'-' -f3)  # Just day

ARCHIVE_NAME="history/${FIRST}-to-${LAST}-history.md"
```

### Natural Boundary Detection
```bash
# Example: Find most recent Sunday
# (Implementation would use date arithmetic)
```

---

## Error Handling

### File Not Found
```bash
if [ ! -f "$HISTORY_FILE" ]; then
    echo "❌ Error: history.md not found at $HISTORY_FILE"
    exit 1
fi
```

### Invalid Mode
```bash
if [[ ! "$MODE" =~ ^(check|archive|analyze|dry-run)$ ]]; then
    echo "❌ Error: Invalid mode '$MODE'"
    echo "Valid modes: check, archive, analyze, dry-run"
    exit 1
fi
```

### Permission Issues
```bash
if [ ! -w "$ARCHIVE_DIR" ]; then
    echo "❌ Error: Cannot write to archive directory"
    exit 1
fi
```

---

## Testing

### Test Check Mode
```bash
/history-management mode=check
# Should display health report without errors
```

### Test Dry-Run Mode
```bash
/history-management mode=dry-run
# Should show proposed archive without making changes
```

### Test Archive Mode (Cautiously)
```bash
# Backup first!
cp history.md history.md.backup

/history-management mode=archive
# Follow prompts, verify results

# Restore if needed
mv history.md.backup history.md
```

---

## Future Enhancements

1. **Velocity Database**: Track token counts in git for accurate forecasting
2. **Auto-Archive**: Option to archive automatically without confirmation
3. **Custom Thresholds**: Per-project threshold overrides
4. **Session Detail Extraction**: Tier 3 for extremely detailed sessions
5. **Archive Compression**: Consolidate very old archives
6. **Web Dashboard**: Visual history health monitoring

---

## References

- **Canonical Workflow**: `/mnt/DATA01/include/www.deepily.ai/projects/planning-is-prompting/workflow/history-management.md`
- **Global Configuration**: `/home/rruiz/.claude/CLAUDE.md` (HISTORY DOCUMENT MANAGEMENT section)
- **Session-End Integration**: `.claude/commands/lupin-session-end.md`
- **Reference Copy**: `src/rnd/2025.09.27-prompts/history-management.md`

---

## Version History

**v1.0** (2025.09.30) - Initial Lupin implementation
- References canonical workflow from planning-is-prompting
- Four operational modes
- Integration with lupin-session-end
- Lupin-specific context ([LUPIN] prefix, file paths)

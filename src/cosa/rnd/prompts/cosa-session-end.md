---
name: "COSA Session End Ritual"
description: "Complete end-of-session documentation and cleanup ritual for COSA repository"
author: "COSA Development Team"
version: "1.0"
tags: ["session-management", "documentation", "git", "notifications"]
---

# COSA Session End Ritual

This prompt orchestrates the complete end-of-session ritual for the COSA (Collection of Small Agents) repository, ensuring proper documentation, git management, and user notifications.

## Context: COSA Repository Structure

- **Repository Type**: Git submodule within parent "Lupin" project
- **Location**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/`
- **Parent Project**: Lupin (located at `../..`)
- **Dual History Management**: Both COSA and parent Lupin histories must be maintained
- **Project Prefix**: `[COSA]` for all todo items and notifications

## End-of-Session Ritual

### Step 0: Mandatory Notification System 🔔
**CRITICAL**: Send notifications after completing each subsequent step to keep user informed of progress.

**Notification Configuration**:
- **Script Path**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/notify.sh`
- **Target**: `ricardo.felipe.ruiz@gmail.com`
- **Format**: `[COSA] [Step Description] - [Status]`
- **Priorities**:
  - `urgent`: Errors, blocked states
  - `high`: Approval requests, important status updates
  - `medium`: Progress milestones
  - `low`: Task completions, informational notices

**Notification Examples**:
```bash
# Step completion
/path/to/notify.sh "[COSA] ✅ COSA history.md updated successfully" --type=task --priority=low

# Approval needed
/path/to/notify.sh "[COSA] Commit message ready for approval" --type=task --priority=high

# Error encountered
/path/to/notify.sh "[COSA] Error: Unable to update history file" --type=alert --priority=urgent
```

### Step 1: Update COSA History.md 📝
Update the COSA repository's history.md file with today's session information.

**Requirements**:
- **Date Format**: yyyy.mm.dd (e.g., 2025.09.27)
- **Sorting**: Newest entries at top, chronological descending order
- **Location**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/history.md`
- **Token Management**: If approaching 25k tokens, archive older months to `history/YYYY-MM-history.md`

**Content Structure**:
```markdown
## 2025.09.27 - [Session Title] COMPLETE

### Summary
[Brief summary of major accomplishments]

### Work Performed
[Detailed breakdown of work completed]

#### [Category] - [Status] ✅
- [Specific achievement or task]
- [Technical details]
- [Impact/results]

### Files Created/Modified
- **Created**: [new files with descriptions]
- **Modified**: [changed files with descriptions]

### Current Status
- **[Component]**: ✅ STATUS - [description]
- **Next Session Priorities**: [what to focus on next]
```

**Include**:
- Session accomplishments and technical details
- Files created/modified with line counts
- Current status of major components
- Next session priorities for continuation
- Links to any new research documents in rnd/ directory

**Send Notification**: After updating COSA history

### Step 2: Conditionally Update Parent Lupin History.md 🔍
**CONDITIONAL**: Only update if parent Lupin history doesn't already contain today's COSA session information.

**Check First**:
- Read `/mnt/DATA01/include/www.deepily.ai/projects/lupin/history.md`
- Look for today's date (yyyy.mm.dd format) and COSA-related content
- **ONLY UPDATE** if today's COSA session work is not already documented

**Location**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin/history.md`

**Update Format** (if needed):
```markdown
#### 2025.09.27 - COSA [Session Title] SESSION

**Summary**: [Brief overview of COSA work completed]

**COSA Achievements**:
- ✅ [Major accomplishment 1]
- ✅ [Major accomplishment 2]
- ✅ [Major accomplishment 3]

**Files Modified in COSA**:
- [List of modified COSA files]

**Current COSA Status**: [Brief status update]
```

**Send Notification**: After checking/updating parent history

### Step 3: Update Planning and Tracking Documents 📊
Update relevant planning and tracking documents in the `rnd/` directory.

**Requirements**:
- **Location**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/rnd/`
- **Document Naming**: Always begin with date in yyyy.mm.dd format
- **README Update**: Add links to any new research documents created

**Actions**:
1. Update existing planning documents with progress
2. Create new research documents if significant discoveries were made
3. Update `rnd/README.md` with links to any new documents
4. Mark completed phases/milestones in tracking documents

**Send Notification**: After updating planning documents

### Step 4: Summarize Uncommitted Changes 📋
Generate comprehensive summary of all git changes in COSA repository.

**Git Commands to Run**:
```bash
# Change to COSA directory
cd /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/

# Check status
git status

# Show statistical summary
git diff --stat

# List untracked files
git ls-files --others --exclude-standard
```

**Summary Format**:
```markdown
## Git Changes Summary

### Modified Files (X files):
- `file1.py` (+XX/-YY lines) - [Description of changes]
- `file2.py` (+XX/-YY lines) - [Description of changes]

### New Files (X files):
- `new_file.py` (XXX lines) - [Description of purpose]

### Total Impact:
- XX files changed
- +XXX insertions
- -YY deletions
```

**Send Notification**: After summarizing changes

### Step 5: Propose Commit Message and Commit Changes 💾
Create structured commit message and commit all changes to COSA repository.

**Commit Message Format**:
```
[COSA] [Brief Summary of Main Achievement]

- [Specific change 1 with file/line details]
- [Specific change 2 with file/line details]
- [Specific change 3 with file/line details]
- [Any architectural or performance impacts]

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

**Commit Process**:
1. **Propose commit message** and send notification for approval
2. **WAIT FOR USER APPROVAL** - Never commit without explicit approval
3. **Stage all changes**: `git add .`
4. **Commit with message**: Use heredoc format for proper formatting
5. **Ask about push**: Offer to push to remote (wait for approval)

**Send Notifications**:
- After proposing commit message (high priority - needs approval)
- After successful commit (low priority - confirmation)
- After asking about push (medium priority)

## COSA-Specific Requirements

### Repository Management
- **Submodule Context**: COSA is a submodule within Lupin project
- **Commit Scope**: Only commit to COSA repository, never parent Lupin
- **PYTHONPATH**: Always set when running COSA modules:
  ```bash
  export PYTHONPATH="/mnt/DATA01/include/www.deepily.ai/projects/lupin/src:$PYTHONPATH"
  ```

### Configuration Management
- **Environment Variables**: Always use `LUPIN_CONFIG_MGR_CLI_ARGS` when instantiating ConfigurationManager
- **Configuration Pairs**: When modifying `lupin-app.ini`, ensure corresponding explainer in `lupin-app-splainer.ini`

### Documentation Standards
- **Design by Contract**: All functions require Requires/Ensures/Raises docstrings
- **Code Style**:
  - 4 spaces indentation (not tabs)
  - Spaces inside parentheses and square brackets
  - Vertical alignment of equals signs
  - snake_case for functions, PascalCase for classes
  - Double quotes for strings (except when avoiding escapes)

### Testing Standards
- **Smoke Testing**: All modules should include `quick_smoke_test()` function
- **Output Formatting**: Use `du.print_banner()` for consistent formatting
- **Debugging**: One-line format: `if debug: print( f"Debug: {value}" )`

## History Management Rules

### Token Limits and Archiving
- **Main history.md**: Target ~3,000 tokens, maintain 30-day window
- **Monthly Archives**: 8k-12k tokens each in `history/YYYY-MM-history.md`
- **Archive Trigger**: When main file approaches 25k tokens
- **Session Details**: Create `history/sessions/YYYY-MM-DD-session-N-title.md` for complex sessions

### Directory Structure
```
history/
├── 2025-09-history.md
├── 2025-08-history.md
├── 2025-07-history.md
└── sessions/
    ├── YYYY-MM-DD-session-N-title.md
    └── [additional session files...]
```

## Error Handling and Recovery

### Common Issues
- **Import Failures**: Check PYTHONPATH configuration
- **Permission Errors**: Verify file permissions and ownership
- **Git Conflicts**: Resolve before committing
- **Notification Failures**: Check script path and permissions

### Recovery Procedures
- **Backup Important Changes**: Before major operations
- **Rollback Capability**: Document state before significant changes
- **Error Logging**: Capture error details for troubleshooting
- **User Escalation**: Send urgent notifications for blocking issues

## Session Completion Verification

At the end of the ritual, verify completion of all mandatory steps:

1. ✅ **Notifications**: Sent after each step completion
2. ✅ **COSA History**: Updated with comprehensive session details
3. ✅ **Parent History**: Checked and conditionally updated
4. ✅ **Planning Docs**: Updated with progress and new documents
5. ✅ **Git Summary**: Comprehensive change summary generated
6. ✅ **Commit**: Changes committed with proper message format
7. ✅ **Push Status**: User informed about push options

**Final Notification**: Send completion summary with all accomplished tasks.

---

## Usage Instructions

### As Manual Process
Read through each step and execute in order, ensuring notifications are sent after each step completion.

### As Claude Code Slash Command
Copy this file to `.claude/commands/cosa-session-end.md` for execution as a slash command.

### Integration with Global Configuration
This prompt integrates all requirements from:
- Global Claude configuration (`/home/rruiz/.claude/CLAUDE.md`)
- COSA-specific configuration (`CLAUDE.md` and `CLAUDE.local.md`)
- COSA project requirements and conventions

---

*Generated for COSA (Collection of Small Agents) repository end-of-session automation*
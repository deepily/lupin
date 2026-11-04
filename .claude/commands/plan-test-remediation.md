---
description: Run post-change verification for Lupin project
allowed-tools: Bash(.*), Read, Write, Edit, Grep, Glob
arguments:
  - name: baseline_report
    description: Path to baseline report (auto-detects if not provided)
    required: false
  - name: scope
    description: Remediation scope (FULL recommended for code project)
    required: false
    default: FULL
---

# Post-Change Remediation for Lupin

**Purpose**: Verify code and tests after changes
**Project**: Lupin (AI agent framework)
**Note**: A full scope is recommended (a code project benefits from active remediation)

**Version**: 1.0

---

## Project Configuration

**Identity**:
- **Prefix**: `[LUPIN]`
- **Project Name**: Lupin
- **Working Directory**: /mnt/DATA01/include/www.deepily.ai/projects/lupin

**Arguments**:
- **Baseline Report**: ${1:-auto}
- **Remediation Scope**: ${2:-FULL}

**Baseline Auto-Detection**:
- **Directory**: io/test-suite/
- **Pattern**: *baseline-*-report.md
- **Sort**: Most recent timestamp

**Test Configuration** (same as baseline):
- **Test Types**: smoke, unit, integration, websocket
- **Reports Directory**: io/test-suite/

---

## Instructions to Claude

**On every invocation of this command:**

1. **Must use the following project-specific configuration**:
   - **[SHORT_PROJECT_PREFIX]**: `[LUPIN]`
   - **Project Name**: Lupin
   - **Working Directory**: /mnt/DATA01/include/www.deepily.ai/projects/lupin
   - **Arguments**:
     - Baseline Report: ${1:-auto}
     - Remediation Scope: ${2:-FULL}
   - **Baseline Auto-Detection**:
     - Directory: io/test-suite/
     - Pattern: *baseline-*-report.md
     - Sort: Most recent timestamp
   - **Test Configuration**:
     - Test Types: smoke, unit, integration, websocket
     - Reports Directory: io/test-suite/
   - Never proceed without these parameters

2. **Must read the canonical workflow document**:
   - Location: planning-is-prompting → workflow/testing-remediation.md
   - This is the only authoritative source for all remediation steps
   - Never proceed without reading this document in full

3. **Must execute the complete remediation workflow**:
   - Execute all steps exactly as described in the canonical workflow document
   - Never skip any steps (including notifications or comparison analysis)
   - Never substitute a shortened or summarized version
   - Follow the workflow exactly as documented using the configuration parameters from instruction 1
   - For this code project, a full scope is recommended (runs tests, identifies regressions, applies fixes in priority order)

---

**This wrapper customizes the remediation workflow for the Lupin project.**

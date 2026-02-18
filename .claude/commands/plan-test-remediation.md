---
description: Run post-change verification for Lupin project
allowed-tools: Bash(.*), TodoWrite, Read, Write, Edit, Grep, Glob
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
**Project**: Lupin (AI Agent Framework with CoSA submodule)
**Note**: FULL scope recommended (code project benefits from active remediation)
**Version**: 1.0

---

## Project Configuration

**Identity**:
- **Prefix**: [LUPIN]
- **Project Name**: Lupin
- **Working Directory**: /mnt/DATA01/include/www.deepily.ai/projects/lupin

**Arguments**:
- **Baseline Report**: ${1:-auto}
- **Remediation Scope**: ${2:-FULL}

**Baseline Auto-Detection**:
- **Directory**: src/rnd/
- **Pattern**: *baseline-*-report.md
- **Sort**: Most recent timestamp

**Test Configuration** (same as baseline):
- **Test Types**: smoke, unit, integration, websocket
- **Logs Directory**: src/tests/logs
- **Reports Directory**: src/rnd/

---

## Instructions to Claude

**On every invocation of this command:**

1. **MUST use the following project-specific configuration**:
   - **[SHORT_PROJECT_PREFIX]**: [LUPIN]
   - **Project Name**: Lupin
   - **Working Directory**: /mnt/DATA01/include/www.deepily.ai/projects/lupin
   - **Arguments**:
     - Baseline Report: ${1:-auto}
     - Remediation Scope: ${2:-FULL}
   - **Baseline Auto-Detection**:
     - Directory: src/rnd/
     - Pattern: *baseline-*-report.md
     - Sort: Most recent timestamp
   - **Test Configuration**:
     - Test Types: smoke, unit, integration, websocket
     - Logs Directory: src/tests/logs
     - Reports Directory: src/rnd/
   - Do NOT proceed without these parameters

2. **MUST read the canonical workflow document**:
   - Location: planning-is-prompting → workflow/testing-remediation.md
   - This is the ONLY authoritative source for ALL remediation steps
   - Do NOT proceed without reading this document in full

3. **MUST execute the complete remediation workflow**:
   - Execute ALL steps exactly as described in the canonical workflow document
   - Do NOT skip any steps (including TodoWrite tracking, notifications, or comparison analysis)
   - Do NOT substitute a shortened or summarized version
   - Follow the workflow exactly as documented using the configuration parameters from Step 1
   - For this code project, FULL scope is recommended (runs tests, identifies regressions, applies fixes in priority order)

---

**This wrapper customizes the remediation workflow for the Lupin project.**

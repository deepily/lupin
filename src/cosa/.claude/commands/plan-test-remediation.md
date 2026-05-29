---
description: Remediation scope (FULL|CRITICAL_ONLY|SELECTIVE|ANALYSIS_ONLY)
allowed-tools: Bash(.*), TodoWrite, Read, Write, Edit, Grep, Glob
---

# Test Remediation for COSA

**Purpose**: Post-change verification and remediation
**Project**: COSA (Collection of Small Agents)
**Version**: 1.0

---

## Project Configuration

**Identity**:
- **Prefix**: [COSA]
- **Project Name**: COSA (Collection of Small Agents)
- **Working Directory**: /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa

**Paths**:
- **Logs Directory**: tests/results/logs
- **Reports Directory**: tests/results/reports

**Test Types**: smoke, unit

**Test Scripts**:
- **Smoke**: ./tests/smoke/scripts/run-cosa-smoke-tests.sh
- **Unit**: ./tests/unit/scripts/run-cosa-unit-tests.sh

**Environment**:
- **PYTHONPATH**: /mnt/DATA01/include/www.deepily.ai/projects/lupin/src

**Remediation Settings**:
- **Default Scope**: FULL (fix all issues in priority order)
- **Time Limits**: 10m/issue (CRITICAL), 5m/issue (HIGH), 2m/issue (MEDIUM)
- **Git Backup**: Yes (create safety backup before remediation)

---

## Instructions to Claude

**On every invocation of this command:**

1. **MUST use the following project-specific configuration**:
   - **[SHORT_PROJECT_PREFIX]**: [COSA]
   - **Project Name**: COSA (Collection of Small Agents)
   - **Working Directory**: /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa
   - **Baseline Report**: Auto-detect latest from tests/results/reports/*baseline*.md (or use provided path)
   - **Scope Parameter**: FULL|CRITICAL_ONLY|SELECTIVE|ANALYSIS_ONLY (default: FULL)
   - **Paths, Test Scripts, Environment**: Same as plan-test-baseline
   - Do NOT proceed without these parameters

2. **MUST read the canonical workflow document**:
   - Location: planning-is-prompting → workflow/testing-remediation.md
   - This is the ONLY authoritative source for ALL remediation steps
   - Do NOT proceed without reading this document in full

3. **MUST execute the complete remediation workflow**:
   - Execute ALL steps exactly as described in the canonical workflow document
   - Do NOT skip any steps (including TodoWrite tracking, notifications, or remediation)
   - Do NOT substitute a shortened or summarized version
   - Follow the workflow exactly as documented using the configuration parameters from Step 1
   - Parse scope parameter and apply appropriate remediation strategy

---

## Usage Examples

```bash
/plan-test-remediation                       # Auto-detect baseline, FULL remediation
/plan-test-remediation auto CRITICAL_ONLY    # Fix critical issues only
/plan-test-remediation auto ANALYSIS_ONLY    # Report only, no fixes
/plan-test-remediation path/to/baseline.md FULL  # Explicit baseline path
```

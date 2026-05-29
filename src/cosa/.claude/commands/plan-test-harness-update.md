---
description: Date range for git log analysis (auto-detects last 7 days if not provided)
allowed-tools: Bash(.*), TodoWrite, Read, Write, Edit, Grep, Glob
---

# Test Harness Update for COSA

**Purpose**: Analyze code changes and identify missing/outdated tests
**Project**: COSA (Collection of Small Agents)
**Version**: 1.0

---

## Project Configuration

**Identity**:
- **Prefix**: [COSA]
- **Project Name**: COSA (Collection of Small Agents)
- **Working Directory**: /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa

**Paths**:
- **Reports Directory**: tests/results/reports

**Test Types**: smoke, unit

**Component Classification**:
- **Critical**: agents/*, app/* (require unit + smoke tests)
- **Standard**: memory/*, tools/* (require unit tests)
- **Support**: utils/* (require unit tests)

**Date Range**: Last 7 days (default), or user-provided date/range

---

## Instructions to Claude

**On every invocation of this command:**

1. **MUST use the following project-specific configuration**:
   - **[SHORT_PROJECT_PREFIX]**: [COSA]
   - **Project Name**: COSA (Collection of Small Agents)
   - **Working Directory**: /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa
   - **Date Range**: Last 7 days (default), or parse user-provided date/range
   - **Component Classification**: See above
   - Do NOT proceed without these parameters

2. **MUST read the canonical workflow document**:
   - Location: planning-is-prompting → workflow/testing-harness-update.md
   - This is the ONLY authoritative source for ALL test harness update steps
   - Do NOT proceed without reading this document in full

3. **MUST execute the complete test harness update workflow**:
   - Execute ALL steps exactly as described in the canonical workflow document
   - Do NOT skip any steps (including TodoWrite tracking, notifications, or analysis)
   - Do NOT substitute a shortened or summarized version
   - Follow the workflow exactly as documented using the configuration parameters from Step 1
   - Use git log to discover changed files in date range
   - Classify components and identify missing tests
   - Generate priority-based update plan

---

## Usage Examples

```bash
/plan-test-harness-update                    # Analyze last 7 days
/plan-test-harness-update 2025-10-01         # Since specific date
/plan-test-harness-update 2025-10-01..2025-10-10  # Date range
```

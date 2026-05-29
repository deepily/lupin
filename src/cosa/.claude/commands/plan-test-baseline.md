---
description: Run baseline test collection for COSA project
allowed-tools: Bash(.*), TodoWrite, Read, Write, Edit
---

# Baseline Testing for COSA

**Purpose**: Establish baseline before code changes
**Project**: COSA (Collection of Small Agents)
**Note**: Code project with smoke and unit tests
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

**Health Checks**: None required (framework library, no running services)

**Environment**:
- **PYTHONPATH**: /mnt/DATA01/include/www.deepily.ai/projects/lupin/src

---

## Instructions to Claude

**On every invocation of this command:**

1. **MUST use the following project-specific configuration**:
   - **[SHORT_PROJECT_PREFIX]**: [COSA]
   - **Project Name**: COSA (Collection of Small Agents)
   - **Working Directory**: /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa
   - **Paths**:
     - Logs Directory: tests/results/logs
     - Reports Directory: tests/results/reports
   - **Test Types**: smoke, unit
   - **Test Scripts**:
     - Smoke: ./tests/smoke/scripts/run-cosa-smoke-tests.sh
     - Unit: ./tests/unit/scripts/run-cosa-unit-tests.sh
   - **Health Checks**: None required (framework library, no running services)
   - **Environment**:
     - PYTHONPATH: /mnt/DATA01/include/www.deepily.ai/projects/lupin/src
   - Do NOT proceed without these parameters

2. **MUST read the canonical workflow document**:
   - Location: planning-is-prompting → workflow/testing-baseline.md
   - This is the ONLY authoritative source for ALL baseline testing steps
   - Do NOT proceed without reading this document in full

3. **MUST execute the complete baseline testing workflow**:
   - Execute ALL steps exactly as described in the canonical workflow document
   - Do NOT skip any steps (including TodoWrite tracking, notifications, or test execution)
   - Do NOT substitute a shortened or summarized version
   - Follow the workflow exactly as documented using the configuration parameters from Step 1
   - Set PYTHONPATH before running tests
   - Execute both smoke and unit test scripts

---

**This wrapper demonstrates the thin wrapper pattern for code projects with test suites.**

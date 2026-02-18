---
description: Run baseline test collection for Lupin project
allowed-tools: Bash(.*), TodoWrite, Read, Write, Edit
arguments:
  - name: scope
    description: Test scope (full|lupin|cosa|quick)
    required: false
    default: full
---

# Baseline Testing for Lupin

**Purpose**: Establish baseline before code changes
**Project**: Lupin (AI Agent Framework with CoSA submodule)
**Note**: Code project - tests include smoke, unit, integration, and websocket
**Version**: 1.0

---

## Project Configuration

**Identity**:
- **Prefix**: [LUPIN]
- **Project Name**: Lupin
- **Working Directory**: /mnt/DATA01/include/www.deepily.ai/projects/lupin

**Paths**:
- **Logs Directory**: src/tests/logs
- **Reports Directory**: src/rnd/

**Test Types**: smoke, unit, integration, websocket

**Test Scripts**:
- **Lupin Smoke**: ./src/tests/run-lupin-smoke-tests.sh
- **CoSA Smoke**: ./src/cosa/tests/smoke/scripts/run-cosa-smoke-tests.sh
- **Unit**: pytest src/tests/unit/ -v
- **Integration**: ./src/tests/run-integration-tests.sh -v
- **WebSocket**: ./src/scripts/run-websocket-smoke-tests.sh

**Health Checks**: curl http://localhost:7999/health

**Environment**: LUPIN_ROOT, PYTHONPATH, LUPIN_TEST_EMAIL, LUPIN_TEST_PASSWORD

---

## Instructions to Claude

**On every invocation of this command:**

1. **MUST use the following project-specific configuration**:
   - **[SHORT_PROJECT_PREFIX]**: [LUPIN]
   - **Project Name**: Lupin
   - **Working Directory**: /mnt/DATA01/include/www.deepily.ai/projects/lupin
   - **Paths**:
     - Logs Directory: src/tests/logs
     - Reports Directory: src/rnd/
   - **Test Types**: smoke, unit, integration, websocket
   - **Test Scripts**:
     - Lupin Smoke: ./src/tests/run-lupin-smoke-tests.sh
     - CoSA Smoke: ./src/cosa/tests/smoke/scripts/run-cosa-smoke-tests.sh
     - Unit: pytest src/tests/unit/ -v
     - Integration: ./src/tests/run-integration-tests.sh -v
     - WebSocket: ./src/scripts/run-websocket-smoke-tests.sh
   - **Health Checks**: curl http://localhost:7999/health
   - **Environment**: LUPIN_ROOT, PYTHONPATH, LUPIN_TEST_EMAIL, LUPIN_TEST_PASSWORD
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
   - For this code project, "smoke tests" means actual test execution (run test scripts, collect pass/fail results, capture logs)

---

**This wrapper customizes the baseline testing workflow for the Lupin project.**

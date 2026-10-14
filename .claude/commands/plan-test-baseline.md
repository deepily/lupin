---
description: Run baseline test collection for Lupin project
allowed-tools: Bash(.*), Read, Write, Edit
arguments:
  - name: scope
    description: Test scope (full|lupin|cosa|quick)
    required: false
    default: full
---

# Baseline Testing for Lupin

**Purpose**: Establish baseline before code changes
**Project**: Lupin (AI agent framework)

**Note**: Code project - tests include smoke, unit, integration, and websocket
**Version**: 1.0

---

## Project Configuration

**Identity**:
- **Prefix**: `[LUPIN]`
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

**Health Checks**: GET http://localhost:7999/health through requests or urllib.request, never curl

**Environment**: LUPIN_ROOT, PYTHONPATH, LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL, LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD

---

## Instructions to Claude

**On every invocation of this command:**

1. **Must use the following project-specific configuration**:
   - **[SHORT_PROJECT_PREFIX]**: `[LUPIN]`
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
   - **Health Checks**: GET http://localhost:7999/health through requests or urllib.request, never curl
   - **Environment**: LUPIN_ROOT, PYTHONPATH, LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL, LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD
   - Never proceed without these parameters

2. **Must read the canonical workflow document**:
   - Location: planning-is-prompting → workflow/testing-baseline.md
   - This is the only authoritative source for all baseline testing steps
   - Never proceed without reading this document in full

3. **Must execute the complete baseline testing workflow**:
   - Execute all steps exactly as described in the canonical workflow document
   - Never skip any steps (including notifications or test execution)
   - Never substitute a shortened or summarized version
   - Follow the workflow exactly as documented using the configuration parameters from instruction 1
   - For this code project, "smoke tests" means actual test execution (run test scripts, collect pass/fail results, capture logs)

---

**This wrapper customizes the baseline testing workflow for the Lupin project.**

---
description: Analyze code changes and plan test coverage updates for Lupin
allowed-tools: Bash(.*), Read, Write, Edit, Grep, Glob
arguments:
  - name: date_range
    description: Date range for git log analysis (auto-detects last 7 days if not provided)
    required: false
---

# Test Harness Update for Lupin

**Purpose**: Identify code changes and ensure test coverage is maintained

**Project**: Lupin (AI agent framework)
**Note**: For code repo, test coverage means smoke, unit, and integration tests
**Version**: 1.0

---

## Project Configuration

**Identity**:
- **Prefix**: `[LUPIN]`
- **Project Name**: Lupin
- **Working Directory**: /mnt/DATA01/include/www.deepily.ai/projects/lupin

**Date Range**: ${1:-auto} (defaults to last 7 days)

**Source Directories**:
- src/
- src/cosa/

**Component Classification** (for code):
```yaml
"src/cosa/memory/":
  type: "core_infrastructure"
  criticality: "critical"
  test_kinds: ["unit", "smoke"]
  test_location: "src/cosa/tests/unit/memory/"

"src/cosa/rest/":
  type: "api_integration"
  criticality: "critical"
  test_kinds: ["unit", "smoke"]
  test_location: "src/cosa/tests/unit/rest/"

"src/cosa/agents/":
  type: "business_logic"
  criticality: "non-critical"
  test_kinds: ["unit", "smoke"]
  test_location: "src/cosa/tests/unit/agents/"

"src/lupin_app/":
  type: "lupin_integration"
  criticality: "critical"
  test_kinds: ["smoke"]
  test_location: "src/tests/unit/"

"src/cosa/utils/":
  type: "support"
  criticality: "non-critical"
  test_kinds: ["unit"]
  test_location: "src/cosa/tests/unit/"
```

`test_kinds` names the kinds of test a component needs. It is not the `test_types` argument of the scheduled test-suite door. Unit tests run on the host (`pytest src/tests/unit/`), and the test container refuses a request that names `unit`.

---

## Instructions to Claude

**On every invocation of this command:**

1. **Must use the following project-specific configuration**:
   - **[SHORT_PROJECT_PREFIX]**: `[LUPIN]`
   - **Project Name**: Lupin
   - **Working Directory**: /mnt/DATA01/include/www.deepily.ai/projects/lupin
   - **Date Range**: ${1:-auto} (defaults to last 7 days)
   - **Source Directories**: src/, src/cosa/
   - **Component Classification**:
     - src/cosa/memory/: core_infrastructure, critical (unit + smoke, tests at src/cosa/tests/unit/memory/)
     - src/cosa/rest/: api_integration, critical (unit + smoke, tests at src/cosa/tests/unit/rest/)
     - src/cosa/agents/: business_logic, non-critical (unit + smoke, tests at src/cosa/tests/unit/agents/)
     - src/lupin_app/: lupin_integration, critical (smoke only, tests at src/tests/unit/)
     - src/cosa/utils/: support, non-critical (unit only, tests at src/cosa/tests/unit/)
   - Never proceed without these parameters

2. **Must read the canonical workflow document**:
   - Location: planning-is-prompting → workflow/testing-harness-update.md
   - This is the only authoritative source for all test harness update steps
   - Never proceed without reading this document in full

3. **Must execute the complete test harness update workflow**:
   - Execute all steps exactly as described in the canonical workflow document
   - Never skip any steps (including notifications or analysis)
   - Never substitute a shortened or summarized version
   - Follow the workflow exactly as documented using the configuration parameters from instruction 1
   - For this code project, "test harness updates" means actual test file work: write new tests, update existing suites, and ensure coverage for changed components

---

**This wrapper customizes the test harness update workflow for the Lupin project.**

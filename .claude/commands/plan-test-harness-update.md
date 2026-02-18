---
description: Analyze code changes and plan test coverage updates for Lupin
allowed-tools: Bash(.*), TodoWrite, Read, Write, Edit, Grep, Glob
arguments:
  - name: date_range
    description: Date range for git log analysis (auto-detects last 7 days if not provided)
    required: false
---

# Test Harness Update for Lupin

**Purpose**: Identify code changes and ensure test coverage is maintained
**Project**: Lupin (AI Agent Framework with CoSA submodule)
**Note**: For code repo, test coverage means smoke, unit, and integration tests
**Version**: 1.0

---

## Project Configuration

**Identity**:
- **Prefix**: [LUPIN]
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
  test_types: ["unit", "smoke"]
  test_location: "src/cosa/tests/unit/memory/"

"src/cosa/rest/":
  type: "api_integration"
  criticality: "critical"
  test_types: ["unit", "smoke"]
  test_location: "src/cosa/tests/unit/rest/"

"src/cosa/agents/":
  type: "business_logic"
  criticality: "non-critical"
  test_types: ["unit", "smoke"]
  test_location: "src/cosa/tests/unit/agents/"

"src/fastapi_app/":
  type: "lupin_integration"
  criticality: "critical"
  test_types: ["smoke"]
  test_location: "src/tests/unit/"

"src/cosa/utils/":
  type: "support"
  criticality: "non-critical"
  test_types: ["unit"]
  test_location: "src/cosa/tests/unit/"
```

---

## Instructions to Claude

**On every invocation of this command:**

1. **MUST use the following project-specific configuration**:
   - **[SHORT_PROJECT_PREFIX]**: [LUPIN]
   - **Project Name**: Lupin
   - **Working Directory**: /mnt/DATA01/include/www.deepily.ai/projects/lupin
   - **Date Range**: ${1:-auto} (defaults to last 7 days)
   - **Source Directories**: src/, src/cosa/
   - **Component Classification**:
     - src/cosa/memory/: core_infrastructure, critical (unit + smoke, tests at src/cosa/tests/unit/memory/)
     - src/cosa/rest/: api_integration, critical (unit + smoke, tests at src/cosa/tests/unit/rest/)
     - src/cosa/agents/: business_logic, non-critical (unit + smoke, tests at src/cosa/tests/unit/agents/)
     - src/fastapi_app/: lupin_integration, critical (smoke only, tests at src/tests/unit/)
     - src/cosa/utils/: support, non-critical (unit only, tests at src/cosa/tests/unit/)
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
   - For this code project, "test harness updates" means actual test file creation/modification (write new tests, update existing test suites, ensure coverage for changed components)

---

**This wrapper customizes the test harness update workflow for the Lupin project.**

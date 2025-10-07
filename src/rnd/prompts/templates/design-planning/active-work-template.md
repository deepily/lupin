# {PROJECT_NAME} - Active Work Tracking

**Created**: {DATE}
**Status**: {CURRENT_STATUS}
**Current Phase**: {PHASE_NAME}
**Last Updated**: {LAST_UPDATED}

**Purpose**: Track current implementation tasks, progress, and immediate next steps. For completed work, see [phases/](phases/). For architectural design, see [{PROJECT_NAME}-architecture-reference.md]({PROJECT_NAME}-architecture-reference.md).

---

## Table of Contents

1. [Current Phase Overview](#current-phase-overview)
2. [Task Progress Tracking](#task-progress-tracking)
3. [Testing Status](#testing-status)
4. [Blockers & Dependencies](#blockers--dependencies)
5. [Next Session TODO List](#next-session-todo-list)
6. [Success Criteria](#success-criteria)
7. [Session Notes](#session-notes)

---

## Current Phase Overview

**Phase**: {PHASE_NUMBER} - {PHASE_NAME}
**Status**: {PHASE_STATUS}
**Started**: {PHASE_START_DATE}
**Target Completion**: {PHASE_TARGET_DATE}
**Actual Completion**: {PHASE_ACTUAL_DATE}

### Phase Objectives

1. **{OBJECTIVE_1}**
   - {OBJECTIVE_1_DETAIL}
   - Success metric: {METRIC_1}

2. **{OBJECTIVE_2}**
   - {OBJECTIVE_2_DETAIL}
   - Success metric: {METRIC_2}

3. **{OBJECTIVE_3}**
   - {OBJECTIVE_3_DETAIL}
   - Success metric: {METRIC_3}

### Phase Scope

**In Scope**:
- {IN_SCOPE_1}
- {IN_SCOPE_2}
- {IN_SCOPE_3}

**Out of Scope** (Deferred to later phases):
- {OUT_SCOPE_1}
- {OUT_SCOPE_2}
- {OUT_SCOPE_3}

### Phase Dependencies

**Blocking On**:
- {DEPENDENCY_1}: {DEPENDENCY_1_STATUS}
- {DEPENDENCY_2}: {DEPENDENCY_2_STATUS}

**Unblocks**:
- {UNBLOCKS_1}
- {UNBLOCKS_2}

---

## Task Progress Tracking

### Task Overview

| Task | Priority | Status | Assignee | Progress |
|------|----------|--------|----------|----------|
| {TASK_1} | {PRIORITY_1} | {STATUS_1} | {ASSIGNEE_1} | {PROGRESS_1}% |
| {TASK_2} | {PRIORITY_2} | {STATUS_2} | {ASSIGNEE_2} | {PROGRESS_2}% |
| {TASK_3} | {PRIORITY_3} | {STATUS_3} | {ASSIGNEE_3} | {PROGRESS_3}% |
| {TASK_4} | {PRIORITY_4} | {STATUS_4} | {ASSIGNEE_4} | {PROGRESS_4}% |

**Legend**:
- 🔴 **BLOCKED**: Cannot proceed, requires unblocking
- 🟡 **IN PROGRESS**: Actively working
- 🟢 **COMPLETED**: Done and verified
- ⚪ **PENDING**: Not yet started
- 🔵 **REVIEW**: Awaiting review/approval

### Detailed Task Breakdown

#### Task 1: {TASK_1_NAME}

**Status**: {TASK_1_STATUS}
**Priority**: {TASK_1_PRIORITY}
**Estimated Effort**: {TASK_1_EFFORT}
**Started**: {TASK_1_START}
**Completed**: {TASK_1_END}

**Description**: {TASK_1_DESCRIPTION}

**Subtasks**:
- [x] {SUBTASK_1_1} - ✅ Completed {DATE}
- [x] {SUBTASK_1_2} - ✅ Completed {DATE}
- [ ] {SUBTASK_1_3} - 🟡 In Progress
- [ ] {SUBTASK_1_4} - ⚪ Pending

**Files Modified**:
- `{FILE_PATH_1}` - {CHANGE_DESCRIPTION_1}
- `{FILE_PATH_2}` - {CHANGE_DESCRIPTION_2}

**Testing**:
- [ ] Unit tests: {UNIT_TEST_STATUS}
- [ ] Integration tests: {INTEGRATION_TEST_STATUS}
- [ ] Smoke tests: {SMOKE_TEST_STATUS}

**Notes**: {TASK_1_NOTES}

---

#### Task 2: {TASK_2_NAME}

**Status**: {TASK_2_STATUS}
**Priority**: {TASK_2_PRIORITY}
**Estimated Effort**: {TASK_2_EFFORT}
**Started**: {TASK_2_START}
**Completed**: {TASK_2_END}

**Description**: {TASK_2_DESCRIPTION}

**Subtasks**:
- [ ] {SUBTASK_2_1} - ⚪ Pending
- [ ] {SUBTASK_2_2} - ⚪ Pending
- [ ] {SUBTASK_2_3} - ⚪ Pending

**Dependencies**:
- Blocked by: {BLOCKING_TASK}
- Required for: {DEPENDENT_TASK}

**Notes**: {TASK_2_NOTES}

---

#### Task 3: {TASK_3_NAME}

**Status**: {TASK_3_STATUS}
**Priority**: {TASK_3_PRIORITY}
**Estimated Effort**: {TASK_3_EFFORT}

**Description**: {TASK_3_DESCRIPTION}

**Subtasks**:
- [ ] {SUBTASK_3_1} - ⚪ Pending
- [ ] {SUBTASK_3_2} - ⚪ Pending

**Notes**: {TASK_3_NOTES}

---

## Testing Status

### Test Suite Progress

| Suite | Implemented | Passing | Total Planned | Pass Rate | Status |
|-------|-------------|---------|---------------|-----------|--------|
| {SUITE_1} | {SUITE_1_IMPL} | {SUITE_1_PASS} | {SUITE_1_TOTAL} | {SUITE_1_RATE}% | {SUITE_1_STATUS} |
| {SUITE_2} | {SUITE_2_IMPL} | {SUITE_2_PASS} | {SUITE_2_TOTAL} | {SUITE_2_RATE}% | {SUITE_2_STATUS} |
| {SUITE_3} | {SUITE_3_IMPL} | {SUITE_3_PASS} | {SUITE_3_TOTAL} | {SUITE_3_RATE}% | {SUITE_3_STATUS} |

**Overall**: {TOTAL_PASSING}/{TOTAL_TESTS} tests passing ({OVERALL_PASS_RATE}%)

### Testing Priorities

**Critical (Must Pass Before Phase Completion)**:
- [ ] {CRITICAL_TEST_1}
- [ ] {CRITICAL_TEST_2}
- [ ] {CRITICAL_TEST_3}

**Important (Should Pass)**:
- [ ] {IMPORTANT_TEST_1}
- [ ] {IMPORTANT_TEST_2}

**Nice to Have (Can Defer)**:
- [ ] {NICE_TEST_1}
- [ ] {NICE_TEST_2}

### Test Failures

| Test | Failure Reason | Severity | Action Needed |
|------|----------------|----------|---------------|
| {FAILED_TEST_1} | {FAILURE_1} | {SEVERITY_1} | {ACTION_1} |
| {FAILED_TEST_2} | {FAILURE_2} | {SEVERITY_2} | {ACTION_2} |

---

## Blockers & Dependencies

### Critical Blockers 🔴

| Blocker | Impact | Owner | Status | Resolution |
|---------|--------|-------|--------|------------|
| {BLOCKER_1} | {IMPACT_1} | {OWNER_1} | {STATUS_1} | {RESOLUTION_1} |
| {BLOCKER_2} | {IMPACT_2} | {OWNER_2} | {STATUS_2} | {RESOLUTION_2} |

### External Dependencies

| Dependency | Provider | Status | ETA | Impact if Delayed |
|------------|----------|--------|-----|-------------------|
| {DEP_1} | {PROVIDER_1} | {DEP_STATUS_1} | {ETA_1} | {IMPACT_1} |
| {DEP_2} | {PROVIDER_2} | {DEP_STATUS_2} | {ETA_2} | {IMPACT_2} |

### Internal Dependencies

| Dependency | Owner | Status | Notes |
|------------|-------|--------|-------|
| {INT_DEP_1} | {INT_OWNER_1} | {INT_STATUS_1} | {INT_NOTES_1} |
| {INT_DEP_2} | {INT_OWNER_2} | {INT_STATUS_2} | {INT_NOTES_2} |

---

## Next Session TODO List

### Immediate Actions (Start Here)

- [ ] **[{PROJECT_PREFIX}] {TODO_1}**
  - Priority: {TODO_1_PRIORITY}
  - Effort: {TODO_1_EFFORT}
  - Outcome: {TODO_1_OUTCOME}

- [ ] **[{PROJECT_PREFIX}] {TODO_2}**
  - Priority: {TODO_2_PRIORITY}
  - Effort: {TODO_2_EFFORT}
  - Outcome: {TODO_2_OUTCOME}

- [ ] **[{PROJECT_PREFIX}] {TODO_3}**
  - Priority: {TODO_3_PRIORITY}
  - Effort: {TODO_3_EFFORT}
  - Outcome: {TODO_3_OUTCOME}

### Short-Term Goals (This Week)

- [ ] **[{PROJECT_PREFIX}] {WEEK_TODO_1}**
  - Deadline: {WEEK_DEADLINE_1}
  - Dependencies: {WEEK_DEP_1}

- [ ] **[{PROJECT_PREFIX}] {WEEK_TODO_2}**
  - Deadline: {WEEK_DEADLINE_2}
  - Dependencies: {WEEK_DEP_2}

### Phase Completion Checklist

- [ ] All critical tasks completed
- [ ] All critical tests passing
- [ ] Phase documentation updated
- [ ] Architecture reference updated with decisions
- [ ] Decision log updated
- [ ] Code reviewed and approved
- [ ] Integration tests passing
- [ ] Phase archived to `phases/` directory
- [ ] Next phase planning complete

### Decisions Needed

**Urgent** (Blocking work):
- {DECISION_1}: {DECISION_1_CONTEXT}
- {DECISION_2}: {DECISION_2_CONTEXT}

**Important** (Needed soon):
- {DECISION_3}: {DECISION_3_CONTEXT}

**Can Defer**:
- {DECISION_4}: {DECISION_4_CONTEXT}

---

## Success Criteria

### Phase Completion Criteria

**Technical Requirements**:
- [ ] {TECH_CRITERIA_1}
- [ ] {TECH_CRITERIA_2}
- [ ] {TECH_CRITERIA_3}

**Testing Requirements**:
- [ ] {TEST_CRITERIA_1}
- [ ] {TEST_CRITERIA_2}
- [ ] {TEST_CRITERIA_3}

**Documentation Requirements**:
- [ ] {DOC_CRITERIA_1}
- [ ] {DOC_CRITERIA_2}
- [ ] {DOC_CRITERIA_3}

**Integration Requirements**:
- [ ] {INT_CRITERIA_1}
- [ ] {INT_CRITERIA_2}

### Quality Gates

**Must Pass**:
- All critical tests passing (100%)
- No high-severity bugs
- Code review approved
- Documentation complete

**Should Pass**:
- All important tests passing (>95%)
- No medium-severity bugs
- Performance benchmarks met
- Security review complete

---

## Session Notes

### {SESSION_DATE_1}

**Duration**: {SESSION_DURATION_1}
**Participants**: {SESSION_PARTICIPANTS_1}

**Work Completed**:
- {WORK_1_1}
- {WORK_1_2}
- {WORK_1_3}

**Decisions Made**:
- {DECISION_1_1}: {DECISION_1_1_OUTCOME}
- {DECISION_1_2}: {DECISION_1_2_OUTCOME}

**Issues Encountered**:
- {ISSUE_1_1}: {ISSUE_1_1_RESOLUTION}

**Next Steps**:
- {NEXT_1_1}
- {NEXT_1_2}

---

### {SESSION_DATE_2}

**Duration**: {SESSION_DURATION_2}
**Participants**: {SESSION_PARTICIPANTS_2}

**Work Completed**:
- {WORK_2_1}
- {WORK_2_2}

**Decisions Made**:
- {DECISION_2_1}: {DECISION_2_1_OUTCOME}

**Next Steps**:
- {NEXT_2_1}

---

## Cross-References

### Related Documents

- **Architecture**: [{PROJECT_NAME}-architecture-reference.md]({PROJECT_NAME}-architecture-reference.md)
- **Navigation**: [README.md](README.md)
- **Decisions**: [{PROJECT_NAME}-decision-log.md]({PROJECT_NAME}-decision-log.md)
- **Testing**: [{PROJECT_NAME}-testing-tracking.md]({PROJECT_NAME}-testing-tracking.md)
- **Risks**: [{PROJECT_NAME}-risk-issues.md]({PROJECT_NAME}-risk-issues.md)

### Code References

- **Main Implementation**: `{CODE_PATH}`
- **Tests**: `{TEST_PATH}`
- **Configuration**: `{CONFIG_PATH}`
- **Documentation**: `{DOC_PATH}`

---

## Maintenance Notes

**Update Frequency**: Daily during active development
**Owner**: {OWNER_NAME}
**Reviewers**: {REVIEWER_LIST}

**When to Update**:
- Task status changes
- Blockers identified or resolved
- Testing progress
- Phase transitions
- Session completion

**Archive Trigger**: When phase completes, archive to `phases/phase-{N}-{NAME}.md`

---

**Token Budget**: 3,000-6,000 tokens | Current: ~{CURRENT_TOKEN_COUNT}

**Document Version**: {VERSION}
**Template Version**: 1.0
**Last Updated**: {LAST_UPDATED}
**Maintained By**: {MAINTAINER}

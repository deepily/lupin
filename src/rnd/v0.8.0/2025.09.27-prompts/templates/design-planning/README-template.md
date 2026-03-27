# {PROJECT_NAME} - Project Navigation Hub

**Created**: {DATE}
**Status**: {PROJECT_STATUS}
**Current Phase**: {CURRENT_PHASE}
**Last Updated**: {LAST_UPDATED}

---

## Project Status Dashboard

| Aspect | Status | Notes |
|--------|--------|-------|
| **Overall Progress** | {OVERALL_PERCENT}% | {PROGRESS_SUMMARY} |
| **Current Phase** | {PHASE_STATUS} | {PHASE_NAME} |
| **Next Milestone** | {NEXT_MILESTONE} | {MILESTONE_DATE} |
| **Active Tasks** | {ACTIVE_TASK_COUNT} | See [Active Work](#active-work) |
| **Blocking Issues** | {BLOCKER_COUNT} | See [Risks & Issues](#risks-and-issues) |
| **Testing Status** | {TEST_PASS_RATE}% | {PASSING_TESTS}/{TOTAL_TESTS} passing |

---

## Quick Navigation

### Core Documentation

- **Architecture Reference** → [{PROJECT_NAME}-architecture-reference.md]({PROJECT_NAME}-architecture-reference.md)
  - Timeless design decisions
  - System architecture
  - Database schemas
  - Security considerations

- **Active Work** → [{PROJECT_NAME}-active-work.md]({PROJECT_NAME}-active-work.md)
  - Current implementation status
  - TODO list and task tracking
  - Immediate next steps

- **Phase/Milestone Documentation** → [phases/](phases/)
  - Completed phase archives
  - Milestone tracking
  - Implementation history

### Supporting Documentation

- **Decision Log** → [{PROJECT_NAME}-decision-log.md]({PROJECT_NAME}-decision-log.md)
  - Architectural decisions
  - Trade-off analysis
  - Alternative approaches considered

- **Testing Tracking** → [{PROJECT_NAME}-testing-tracking.md]({PROJECT_NAME}-testing-tracking.md)
  - Test suite status
  - Coverage metrics
  - Testing strategy

- **Risks & Issues** → [{PROJECT_NAME}-risk-issues.md]({PROJECT_NAME}-risk-issues.md)
  - Known issues
  - Risk assessment
  - Mitigation strategies

<!-- [Include if project has research phase] -->
### Research Foundation

- **Research Summary** → [research/synthesis.md](research/synthesis.md)
  - Research findings overview
  - Technology comparisons
  - Recommendations
  - See full research directory: [research/README.md](research/README.md)
<!-- [End conditional section] -->

---

## Project Overview

### Executive Summary

{EXECUTIVE_SUMMARY}

**Key Objectives**:
- {OBJECTIVE_1}
- {OBJECTIVE_2}
- {OBJECTIVE_3}

**Success Criteria**:
- {SUCCESS_CRITERION_1}
- {SUCCESS_CRITERION_2}
- {SUCCESS_CRITERION_3}

### Timeline

| Phase | Dates | Status | Deliverables |
|-------|-------|--------|--------------|
| {PHASE_1_NAME} | {PHASE_1_DATES} | {PHASE_1_STATUS} | {PHASE_1_DELIVERABLES} |
| {PHASE_2_NAME} | {PHASE_2_DATES} | {PHASE_2_STATUS} | {PHASE_2_DELIVERABLES} |
| {PHASE_3_NAME} | {PHASE_3_DATES} | {PHASE_3_STATUS} | {PHASE_3_DELIVERABLES} |

**Overall Timeline**: {START_DATE} → {TARGET_END_DATE} ({TOTAL_DURATION})

---

## Active Work

**Current Focus**: {CURRENT_FOCUS}

### In Progress Tasks

| Task | Assignee | Status | Blocking |
|------|----------|--------|----------|
| {TASK_1} | {ASSIGNEE_1} | {TASK_1_STATUS} | {TASK_1_BLOCKERS} |
| {TASK_2} | {ASSIGNEE_2} | {TASK_2_STATUS} | {TASK_2_BLOCKERS} |
| {TASK_3} | {ASSIGNEE_3} | {TASK_3_STATUS} | {TASK_3_BLOCKERS} |

See [Active Work]({PROJECT_NAME}-active-work.md) for detailed tracking.

### Immediate Next Steps

1. **{NEXT_STEP_1}**
   - Priority: {PRIORITY_1}
   - Estimated effort: {EFFORT_1}
   - Dependencies: {DEPENDENCIES_1}

2. **{NEXT_STEP_2}**
   - Priority: {PRIORITY_2}
   - Estimated effort: {EFFORT_2}
   - Dependencies: {DEPENDENCIES_2}

3. **{NEXT_STEP_3}**
   - Priority: {PRIORITY_3}
   - Estimated effort: {EFFORT_3}
   - Dependencies: {DEPENDENCIES_3}

---

## Testing Status

| Test Suite | Passing | Total | Pass Rate | Notes |
|------------|---------|-------|-----------|-------|
| {TEST_SUITE_1} | {SUITE_1_PASSING} | {SUITE_1_TOTAL} | {SUITE_1_PERCENT}% | {SUITE_1_NOTES} |
| {TEST_SUITE_2} | {SUITE_2_PASSING} | {SUITE_2_TOTAL} | {SUITE_2_PERCENT}% | {SUITE_2_NOTES} |
| {TEST_SUITE_3} | {SUITE_3_PASSING} | {SUITE_3_TOTAL} | {SUITE_3_PERCENT}% | {SUITE_3_NOTES} |

**Overall**: {TOTAL_PASSING}/{TOTAL_TESTS} tests passing ({OVERALL_PASS_RATE}%)

See [Testing Tracking]({PROJECT_NAME}-testing-tracking.md) for detailed test status.

---

## Risks and Issues

### High Priority

| Issue | Severity | Impact | Status |
|-------|----------|--------|--------|
| {HIGH_ISSUE_1} | {SEVERITY_1} | {IMPACT_1} | {STATUS_1} |
| {HIGH_ISSUE_2} | {SEVERITY_2} | {IMPACT_2} | {STATUS_2} |

### Medium Priority

| Issue | Severity | Impact | Status |
|-------|----------|--------|--------|
| {MEDIUM_ISSUE_1} | {SEVERITY_3} | {IMPACT_3} | {STATUS_3} |

See [Risks & Issues]({PROJECT_NAME}-risk-issues.md) for complete tracking.

---

## Recent Updates

### {RECENT_DATE_1}

**Summary**: {UPDATE_1_SUMMARY}

**Changes**:
- {CHANGE_1_1}
- {CHANGE_1_2}
- {CHANGE_1_3}

**Impact**: {UPDATE_1_IMPACT}

### {RECENT_DATE_2}

**Summary**: {UPDATE_2_SUMMARY}

**Changes**:
- {CHANGE_2_1}
- {CHANGE_2_2}

**Impact**: {UPDATE_2_IMPACT}

---

## Key Decisions

| Date | Decision | Rationale | Document |
|------|----------|-----------|----------|
| {DECISION_1_DATE} | {DECISION_1} | {RATIONALE_1} | [Decision Log]({PROJECT_NAME}-decision-log.md#{DECISION_1_ANCHOR}) |
| {DECISION_2_DATE} | {DECISION_2} | {RATIONALE_2} | [Decision Log]({PROJECT_NAME}-decision-log.md#{DECISION_2_ANCHOR}) |
| {DECISION_3_DATE} | {DECISION_3} | {RATIONALE_3} | [Decision Log]({PROJECT_NAME}-decision-log.md#{DECISION_3_ANCHOR}) |

---

## Document Hierarchy

```
{PROJECT_NAME}/
├── README.md (this file) ..................... Navigation hub
├── {PROJECT_NAME}-architecture-reference.md .. Timeless design
├── {PROJECT_NAME}-active-work.md ............. Current tasks
├── {PROJECT_NAME}-decision-log.md ............ Design decisions
├── {PROJECT_NAME}-testing-tracking.md ........ Test status
├── {PROJECT_NAME}-risk-issues.md ............. Issues & risks
├── phases/ ................................... Completed phases
│   ├── phase-1-{PHASE_1_NAME}.md
│   ├── phase-2-{PHASE_2_NAME}.md
│   └── ...
└── research/ ................................. Research materials
    ├── README.md ............................. Research index
    ├── synthesis.md .......................... Research summary
    └── YYYY.MM.DD-{TOPIC}.md ................. Individual research
```

---

## Usage Guidelines

### For Developers Starting Work

1. Read **this README** for project overview
2. Review **Architecture Reference** for design decisions
3. Check **Active Work** for current tasks and TODOs
4. Consult **Decision Log** for rationale behind choices
5. Review **Testing Tracking** before making changes

### For Reviewing Progress

1. Check **Status Dashboard** (top of this file)
2. Review **Recent Updates** section
3. Check **Active Work** document for detailed status
4. Review **Risks & Issues** for blockers

### For Planning New Features

1. Review **Architecture Reference** for constraints
2. Check **Decision Log** for relevant precedents
3. Update **Active Work** with new tasks
4. Add risks to **Risks & Issues** if applicable
5. Update this **README** with status changes

### For Onboarding

1. Start with **Executive Summary** (this file)
2. Read **Architecture Reference** for design understanding
3. Review **phases/** directory for implementation history
4. Check **Testing Tracking** for quality metrics
5. Review **Decision Log** for context on choices

---

## Maintenance Checklist

### Daily (During Active Development)

- [ ] Update **Active Work** task status
- [ ] Update **Status Dashboard** percentages
- [ ] Log any new issues in **Risks & Issues**
- [ ] Update **Recent Updates** section

### Weekly

- [ ] Review and update **Timeline** table
- [ ] Archive completed phases to **phases/** directory
- [ ] Update **Testing Status** with latest metrics
- [ ] Review **Risks & Issues** for status changes

### Phase Completion

- [ ] Archive phase documentation to **phases/**
- [ ] Update **Architecture Reference** with new decisions
- [ ] Update **Decision Log** with phase decisions
- [ ] Update **Timeline** with actual completion dates
- [ ] Update **Overall Progress** percentage

### Project Completion

- [ ] Final update to all status dashboards
- [ ] Archive all active work to phases
- [ ] Complete final testing report
- [ ] Document lessons learned
- [ ] Create project handoff document

---

## Cross-References

### Related Projects

- {RELATED_PROJECT_1}: {RELATIONSHIP_1}
- {RELATED_PROJECT_2}: {RELATIONSHIP_2}

### External Documentation

- {EXTERNAL_DOC_1}: {EXTERNAL_URL_1}
- {EXTERNAL_DOC_2}: {EXTERNAL_URL_2}

### Code Locations

- **Main Implementation**: {CODE_PATH_1}
- **Configuration**: {CONFIG_PATH}
- **Tests**: {TEST_PATH}
- **Scripts**: {SCRIPT_PATH}

---

## Contact & Support

**Project Owner**: {OWNER_NAME}
**Technical Lead**: {TECH_LEAD_NAME}
**Documentation**: {DOC_MAINTAINER}

**Questions?** Check the [Decision Log]({PROJECT_NAME}-decision-log.md) or [Architecture Reference]({PROJECT_NAME}-architecture-reference.md) first.

---

**Token Budget**: 3,000-6,000 tokens | Current: ~{CURRENT_TOKEN_COUNT}

**Document Version**: {VERSION}
**Template Version**: 1.0
**Last Updated**: {LAST_UPDATED}
**Maintained By**: {MAINTAINER}

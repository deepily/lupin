# {PROJECT_NAME} - Risk & Issues Tracking

**Created**: {DATE}
**Status**: LIVING DOCUMENT
**Project**: {PROJECT_FULL_NAME}
**Last Updated**: {LAST_UPDATED}

**Purpose**: Comprehensive tracking of risks, issues, blockers, and mitigation strategies. This document ensures visibility and proactive management of project challenges.

---

## Table of Contents

1. [Risk Overview](#risk-overview)
2. [Critical Risks](#critical-risks)
3. [Active Issues](#active-issues)
4. [Blockers](#blockers)
5. [Resolved Issues](#resolved-issues)
6. [Risk Mitigation Strategies](#risk-mitigation-strategies)
7. [Issue Escalation](#issue-escalation)

---

## Risk Overview

### Risk Dashboard

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| **Technical** | {TECH_CRIT} | {TECH_HIGH} | {TECH_MED} | {TECH_LOW} | {TECH_TOTAL} |
| **Security** | {SEC_CRIT} | {SEC_HIGH} | {SEC_MED} | {SEC_LOW} | {SEC_TOTAL} |
| **Performance** | {PERF_CRIT} | {PERF_HIGH} | {PERF_MED} | {PERF_LOW} | {PERF_TOTAL} |
| **Integration** | {INT_CRIT} | {INT_HIGH} | {INT_MED} | {INT_LOW} | {INT_TOTAL} |
| **Schedule** | {SCHED_CRIT} | {SCHED_HIGH} | {SCHED_MED} | {SCHED_LOW} | {SCHED_TOTAL} |
| **Resource** | {RES_CRIT} | {RES_HIGH} | {RES_MED} | {RES_LOW} | {RES_TOTAL} |
| **Total** | {TOTAL_CRIT} | {TOTAL_HIGH} | {TOTAL_MED} | {TOTAL_LOW} | {TOTAL_RISKS} |

### Risk Severity Definitions

**Critical (P0)**:
- Project cannot proceed
- Security vulnerability
- Data loss risk
- System unavailable

**High (P1)**:
- Major feature impact
- Significant performance degradation
- Integration failure
- Schedule delay risk

**Medium (P2)**:
- Feature limitation
- Workaround exists
- Minor performance impact
- Documentation gap

**Low (P3)**:
- Nice-to-have feature
- Minimal impact
- Future enhancement
- Non-blocking issue

### Risk Trend

| Week | Critical | High | Medium | Low | Total | Trend |
|------|----------|------|--------|-----|-------|-------|
| {WEEK_1} | {W1_CRIT} | {W1_HIGH} | {W1_MED} | {W1_LOW} | {W1_TOTAL} | {W1_TREND} |
| {WEEK_2} | {W2_CRIT} | {W2_HIGH} | {W2_MED} | {W2_LOW} | {W2_TOTAL} | {W2_TREND} |
| {WEEK_3} | {W3_CRIT} | {W3_HIGH} | {W3_MED} | {W3_LOW} | {W3_TOTAL} | {W3_TREND} |
| {WEEK_4} | {W4_CRIT} | {W4_HIGH} | {W4_MED} | {W4_LOW} | {W4_TOTAL} | {W4_TREND} |

**Trend Indicators**: ⬆️ Increasing | ➡️ Stable | ⬇️ Decreasing

---

## Critical Risks

### Risk CRIT-{RISK_ID_1}: {RISK_1_TITLE}

**ID**: CRIT-{RISK_ID_1}
**Severity**: CRITICAL
**Category**: {RISK_1_CATEGORY}
**Status**: {RISK_1_STATUS}
**Identified**: {RISK_1_DATE}
**Owner**: {RISK_1_OWNER}

#### Description

{RISK_1_DESCRIPTION}

#### Impact

**If Realized**:
- {RISK_1_IMPACT_1}
- {RISK_1_IMPACT_2}
- {RISK_1_IMPACT_3}

**Affected Components**:
- {RISK_1_AFFECTED_1}
- {RISK_1_AFFECTED_2}

**Probability**: {RISK_1_PROBABILITY}% (High: >70%, Medium: 30-70%, Low: <30%)

**Impact Assessment**:
- Schedule Impact: {RISK_1_SCHEDULE}
- Cost Impact: {RISK_1_COST}
- Quality Impact: {RISK_1_QUALITY}

#### Mitigation Strategy

**Preventive Actions**:
1. {RISK_1_PREVENT_1}
2. {RISK_1_PREVENT_2}
3. {RISK_1_PREVENT_3}

**Contingency Plan**:
- {RISK_1_CONTINGENCY_1}
- {RISK_1_CONTINGENCY_2}

**Monitoring**:
- {RISK_1_MONITOR_1}
- {RISK_1_MONITOR_2}

**Status Updates**:
- {RISK_1_UPDATE_DATE_1}: {RISK_1_UPDATE_1}
- {RISK_1_UPDATE_DATE_2}: {RISK_1_UPDATE_2}

**Next Review**: {RISK_1_REVIEW_DATE}

---

### Risk CRIT-{RISK_ID_2}: {RISK_2_TITLE}

**ID**: CRIT-{RISK_ID_2}
**Severity**: CRITICAL
**Category**: {RISK_2_CATEGORY}
**Status**: {RISK_2_STATUS}

#### Description

{RISK_2_DESCRIPTION}

#### Impact

**Probability**: {RISK_2_PROBABILITY}%

**If Realized**:
- {RISK_2_IMPACT_1}
- {RISK_2_IMPACT_2}

#### Mitigation Strategy

**Preventive Actions**:
1. {RISK_2_PREVENT_1}
2. {RISK_2_PREVENT_2}

**Status**: {RISK_2_MITIGATION_STATUS}

---

## Active Issues

### ISSUE-{ISSUE_ID_1}: {ISSUE_1_TITLE} (HIGH)

**ID**: ISSUE-{ISSUE_ID_1}
**Severity**: HIGH
**Type**: {ISSUE_1_TYPE}
**Status**: {ISSUE_1_STATUS}
**Reported**: {ISSUE_1_DATE}
**Assignee**: {ISSUE_1_ASSIGNEE}
**Target Resolution**: {ISSUE_1_TARGET}

#### Description

{ISSUE_1_DESCRIPTION}

**Steps to Reproduce** (if applicable):
1. {ISSUE_1_STEP_1}
2. {ISSUE_1_STEP_2}
3. {ISSUE_1_STEP_3}

**Expected Behavior**: {ISSUE_1_EXPECTED}

**Actual Behavior**: {ISSUE_1_ACTUAL}

#### Impact

**Severity Justification**: {ISSUE_1_SEVERITY_REASON}

**Affected Users/Components**:
- {ISSUE_1_AFFECTED_1}
- {ISSUE_1_AFFECTED_2}

**Workaround**: {ISSUE_1_WORKAROUND}

#### Resolution Progress

**Investigation**:
- {ISSUE_1_INVESTIGATION_1}
- {ISSUE_1_INVESTIGATION_2}

**Root Cause**: {ISSUE_1_ROOT_CAUSE}

**Proposed Fix**: {ISSUE_1_FIX}

**Testing Plan**: {ISSUE_1_TESTING}

**Progress Updates**:
- {ISSUE_1_UPDATE_DATE_1}: {ISSUE_1_UPDATE_1}
- {ISSUE_1_UPDATE_DATE_2}: {ISSUE_1_UPDATE_2}

**Related Issues**: {ISSUE_1_RELATED}

**Blocks**: {ISSUE_1_BLOCKS}

---

### ISSUE-{ISSUE_ID_2}: {ISSUE_2_TITLE} (MEDIUM)

**ID**: ISSUE-{ISSUE_ID_2}
**Severity**: MEDIUM
**Status**: {ISSUE_2_STATUS}
**Reported**: {ISSUE_2_DATE}
**Assignee**: {ISSUE_2_ASSIGNEE}

#### Description

{ISSUE_2_DESCRIPTION}

#### Impact

**Affected Components**: {ISSUE_2_AFFECTED}

**Workaround**: {ISSUE_2_WORKAROUND}

#### Resolution

**Proposed Fix**: {ISSUE_2_FIX}

**Target**: {ISSUE_2_TARGET}

---

### ISSUE-{ISSUE_ID_3}: {ISSUE_3_TITLE} (LOW)

**ID**: ISSUE-{ISSUE_ID_3}
**Severity**: LOW
**Status**: {ISSUE_3_STATUS}

#### Description

{ISSUE_3_DESCRIPTION}

**Deferred To**: {ISSUE_3_DEFERRED}

**Rationale**: {ISSUE_3_RATIONALE}

---

## Blockers

### Active Blockers

| ID | Title | Severity | Blocking | Owner | Status | ETA |
|----|-------|----------|----------|-------|--------|-----|
| {BLOCKER_1_ID} | {BLOCKER_1} | {BLOCKER_1_SEV} | {BLOCKER_1_BLOCKS} | {BLOCKER_1_OWNER} | {BLOCKER_1_STATUS} | {BLOCKER_1_ETA} |
| {BLOCKER_2_ID} | {BLOCKER_2} | {BLOCKER_2_SEV} | {BLOCKER_2_BLOCKS} | {BLOCKER_2_OWNER} | {BLOCKER_2_STATUS} | {BLOCKER_2_ETA} |

### Blocker Detail: {BLOCKER_1_ID}

**Title**: {BLOCKER_1_TITLE}

**Description**: {BLOCKER_1_DESCRIPTION}

**Blocking**:
- {BLOCKER_1_BLOCKING_1}
- {BLOCKER_1_BLOCKING_2}

**Impact if Not Resolved**:
- {BLOCKER_1_IMPACT_1}
- {BLOCKER_1_IMPACT_2}

**Resolution Plan**:
1. {BLOCKER_1_PLAN_1}
2. {BLOCKER_1_PLAN_2}
3. {BLOCKER_1_PLAN_3}

**Dependencies**: {BLOCKER_1_DEPS}

**Status**: {BLOCKER_1_DETAIL_STATUS}

---

## Resolved Issues

### Recent Resolutions

| ID | Title | Severity | Resolved | Resolution Time | Notes |
|----|-------|----------|----------|-----------------|-------|
| {RESOLVED_1_ID} | {RESOLVED_1} | {RESOLVED_1_SEV} | {RESOLVED_1_DATE} | {RESOLVED_1_TIME} | {RESOLVED_1_NOTES} |
| {RESOLVED_2_ID} | {RESOLVED_2} | {RESOLVED_2_SEV} | {RESOLVED_2_DATE} | {RESOLVED_2_TIME} | {RESOLVED_2_NOTES} |
| {RESOLVED_3_ID} | {RESOLVED_3} | {RESOLVED_3_SEV} | {RESOLVED_3_DATE} | {RESOLVED_3_TIME} | {RESOLVED_3_NOTES} |

### Resolution Detail: {RESOLVED_1_ID}

**Title**: {RESOLVED_1_TITLE}

**Original Issue**: {RESOLVED_1_ORIGINAL}

**Resolution**: {RESOLVED_1_RESOLUTION}

**Verification**:
- {RESOLVED_1_VERIFY_1}
- {RESOLVED_1_VERIFY_2}

**Lessons Learned**: {RESOLVED_1_LESSONS}

**Prevention for Future**: {RESOLVED_1_PREVENTION}

---

## Risk Mitigation Strategies

### Technical Risk Mitigation

#### Strategy 1: {TECH_STRATEGY_1}

**Addresses Risks**: {TECH_STRATEGY_1_RISKS}

**Approach**:
- {TECH_STRATEGY_1_APPROACH_1}
- {TECH_STRATEGY_1_APPROACH_2}

**Implementation**:
```python
{TECH_STRATEGY_1_CODE}
```

**Monitoring**: {TECH_STRATEGY_1_MONITOR}

**Effectiveness**: {TECH_STRATEGY_1_EFFECT}

---

#### Strategy 2: {TECH_STRATEGY_2}

**Addresses Risks**: {TECH_STRATEGY_2_RISKS}

**Approach**: {TECH_STRATEGY_2_APPROACH}

**Status**: {TECH_STRATEGY_2_STATUS}

---

### Security Risk Mitigation

#### Strategy 1: {SEC_STRATEGY_1}

**Addresses Risks**: {SEC_STRATEGY_1_RISKS}

**Implementation**: {SEC_STRATEGY_1_IMPL}

**Validation**: {SEC_STRATEGY_1_VALID}

---

### Performance Risk Mitigation

#### Strategy 1: {PERF_STRATEGY_1}

**Addresses Risks**: {PERF_STRATEGY_1_RISKS}

**Benchmarks**:
- {PERF_STRATEGY_1_BENCH_1}
- {PERF_STRATEGY_1_BENCH_2}

**Monitoring**: {PERF_STRATEGY_1_MONITOR}

---

### Integration Risk Mitigation

#### Strategy 1: {INT_STRATEGY_1}

**Addresses Risks**: {INT_STRATEGY_1_RISKS}

**Compatibility Testing**: {INT_STRATEGY_1_TEST}

**Fallback Plan**: {INT_STRATEGY_1_FALLBACK}

---

## Issue Escalation

### Escalation Criteria

**Escalate to Project Lead when**:
- Critical (P0) issue identified
- High (P1) issue not resolved in {ESCALATION_TIME_P1} days
- Blocker with no resolution plan
- Risk probability increases significantly

**Escalate to Stakeholders when**:
- Schedule impact > {ESCALATION_SCHEDULE_THRESHOLD} days
- Critical security vulnerability
- Data loss or corruption
- System-wide outage

### Escalation Process

1. **Identify Escalation Need**
   - Assess severity and impact
   - Document urgency
   - Gather context

2. **Notify Appropriate Party**
   - Project Lead: {PROJECT_LEAD_CONTACT}
   - Technical Lead: {TECH_LEAD_CONTACT}
   - Stakeholder: {STAKEHOLDER_CONTACT}

3. **Provide Context**
   - Issue ID and description
   - Impact assessment
   - Attempted resolutions
   - Recommended action

4. **Follow-Up**
   - Track escalation in this document
   - Document decision
   - Update issue status

### Recent Escalations

| Date | Issue | Escalated To | Outcome | Resolution Time |
|------|-------|--------------|---------|-----------------|
| {ESC_DATE_1} | {ESC_ISSUE_1} | {ESC_TO_1} | {ESC_OUTCOME_1} | {ESC_TIME_1} |
| {ESC_DATE_2} | {ESC_ISSUE_2} | {ESC_TO_2} | {ESC_OUTCOME_2} | {ESC_TIME_2} |

---

## Risk Acceptance

### Accepted Risks

Risks consciously accepted with documented justification:

#### Accepted Risk 1: {ACCEPTED_RISK_1}

**Severity**: {ACCEPTED_SEV_1}
**Category**: {ACCEPTED_CAT_1}
**Accepted**: {ACCEPTED_DATE_1}
**Accepted By**: {ACCEPTED_BY_1}

**Description**: {ACCEPTED_DESC_1}

**Justification**: {ACCEPTED_JUST_1}

**Mitigation (if realized)**:
- {ACCEPTED_MIT_1_1}
- {ACCEPTED_MIT_1_2}

**Review Date**: {ACCEPTED_REVIEW_1}

---

#### Accepted Risk 2: {ACCEPTED_RISK_2}

**Severity**: {ACCEPTED_SEV_2}
**Accepted**: {ACCEPTED_DATE_2}

**Description**: {ACCEPTED_DESC_2}

**Justification**: {ACCEPTED_JUST_2}

---

## Monitoring & Review

### Review Schedule

- **Daily**: Critical and high-severity issues
- **Weekly**: All active issues and blockers
- **Bi-weekly**: Risk assessment and mitigation progress
- **Monthly**: Comprehensive risk review and trend analysis
- **Phase Completion**: Full risk and issue retrospective

### Key Metrics to Monitor

| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| Critical Issues | {CURR_CRIT_ISSUES} | 0 | {CRIT_ISSUE_STATUS} |
| High Issues | {CURR_HIGH_ISSUES} | <{TARGET_HIGH} | {HIGH_ISSUE_STATUS} |
| Average Resolution Time (Critical) | {AVG_CRIT_TIME} days | <{TARGET_CRIT_TIME} days | {TIME_CRIT_STATUS} |
| Average Resolution Time (High) | {AVG_HIGH_TIME} days | <{TARGET_HIGH_TIME} days | {TIME_HIGH_STATUS} |
| Active Blockers | {CURR_BLOCKERS} | 0 | {BLOCKER_STATUS} |
| Risk Trend | {CURR_RISK_TREND} | Decreasing | {TREND_STATUS} |

---

## Cross-References

### Related Documents

- **Active Work**: [{PROJECT_NAME}-active-work.md]({PROJECT_NAME}-active-work.md)
- **Architecture**: [{PROJECT_NAME}-architecture-reference.md]({PROJECT_NAME}-architecture-reference.md)
- **Testing**: [{PROJECT_NAME}-testing-tracking.md]({PROJECT_NAME}-testing-tracking.md)
- **Navigation**: [README.md](README.md)

### Issue Tracking

- **Issue Tracker**: {ISSUE_TRACKER_URL}
- **Risk Register**: {RISK_REGISTER_URL}

---

## Maintenance Notes

**Update Frequency**:
- Daily for critical issues
- Weekly for all others
- Continuous for new issues/risks

**Owner**: {OWNER_NAME}
**Reviewers**: {REVIEWER_LIST}

**When to Update**:
- New risk identified
- Risk status changes
- Issue created or resolved
- Blocker identified or cleared
- Mitigation strategy implemented

---

**Token Budget**: 3,000-6,000 tokens | Current: ~{CURRENT_TOKEN_COUNT}

**Document Version**: {VERSION}
**Template Version**: 1.0
**Last Updated**: {LAST_UPDATED}
**Maintained By**: {MAINTAINER}

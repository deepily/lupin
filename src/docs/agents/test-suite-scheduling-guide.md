# Test-Suite Scheduling Guide

How to schedule and run test suites through the TestSuiteJob: suite types, architecture, the /schedule-tests skill, the submit API, the remediation snapshot, monopolize mode, cost, TFE and troubleshooting.

## Contents

This page is an index. The reference itself is in the parts below, in document order.

- [Table of Contents](test-suite-scheduling-guide/01-what-it-does-and-suite-types.md#table-of-contents)
- [1. What the TestSuiteJob Does](test-suite-scheduling-guide/01-what-it-does-and-suite-types.md#1-what-the-testsuitejob-does)
- [2. Supported Suite Types](test-suite-scheduling-guide/01-what-it-does-and-suite-types.md#2-supported-suite-types)
- [3. Architecture](test-suite-scheduling-guide/02-architecture-and-schedule-tests-skill.md#3-architecture)
- [4. The `/schedule-tests` Skill](test-suite-scheduling-guide/02-architecture-and-schedule-tests-skill.md#4-the-schedule-tests-skill)
- [5. REST API: `/api/v2/submit` (command `agent router go to test suite`)](test-suite-scheduling-guide/03-rest-api-and-remediation-snapshot.md#5-rest-api-apiv2submit-command-agent-router-go-to-test-suite)
- [6. Remediation Snapshot Schema (v1.0)](test-suite-scheduling-guide/03-rest-api-and-remediation-snapshot.md#6-remediation-snapshot-schema-v10)
- [7. Monopolize Mode](test-suite-scheduling-guide/04-monopolize-cost-and-tfe.md#7-monopolize-mode)
- [8. Cost Model](test-suite-scheduling-guide/04-monopolize-cost-and-tfe.md#8-cost-model)
- [9. Interaction with TFE](test-suite-scheduling-guide/04-monopolize-cost-and-tfe.md#9-interaction-with-tfe)
- [10. Troubleshooting](test-suite-scheduling-guide/05-troubleshooting-and-related-docs.md#10-troubleshooting)
- [Related Documentation](test-suite-scheduling-guide/05-troubleshooting-and-related-docs.md#related-documentation)

## Parts

| Part | Covers |
|---|---|
| [01-what-it-does-and-suite-types.md](test-suite-scheduling-guide/01-what-it-does-and-suite-types.md) | the table of contents, what the TestSuiteJob does, and the supported suite types |
| [02-architecture-and-schedule-tests-skill.md](test-suite-scheduling-guide/02-architecture-and-schedule-tests-skill.md) | the architecture and the /schedule-tests skill |
| [03-rest-api-and-remediation-snapshot.md](test-suite-scheduling-guide/03-rest-api-and-remediation-snapshot.md) | the REST API for submitting a test suite and the remediation snapshot schema |
| [04-monopolize-cost-and-tfe.md](test-suite-scheduling-guide/04-monopolize-cost-and-tfe.md) | monopolize mode, the cost model and the interaction with TFE |
| [05-troubleshooting-and-related-docs.md](test-suite-scheduling-guide/05-troubleshooting-and-related-docs.md) | troubleshooting and related documentation |

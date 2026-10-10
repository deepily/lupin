# Shared Fix Primitives Reference

The code shared by the Bug Fix Expediter and the Test Fix Expediter, and how to add a new expediter agent.

## Contents

This page is an index. The reference itself is in the parts below, in document order.

- [Table of Contents](shared-fix-primitives-reference/01-planwriter-gitstrategist-fixexecutor.md#table-of-contents)
- [1. Why the Shared Package Exists](shared-fix-primitives-reference/01-planwriter-gitstrategist-fixexecutor.md#1-why-the-shared-package-exists)
- [2. Package Layout](shared-fix-primitives-reference/01-planwriter-gitstrategist-fixexecutor.md#2-package-layout)
- [3. `PlanWriter` — Markdown Plan Docs](shared-fix-primitives-reference/01-planwriter-gitstrategist-fixexecutor.md#3-planwriter--markdown-plan-docs)
- [4. `GitStrategist` — Trust-Aware Git Operations](shared-fix-primitives-reference/01-planwriter-gitstrategist-fixexecutor.md#4-gitstrategist--trust-aware-git-operations)
- [5. `FixExecutor` — Polymorphic Coder+Tester Loop](shared-fix-primitives-reference/01-planwriter-gitstrategist-fixexecutor.md#5-fixexecutor--polymorphic-codertester-loop)
- [6. `FIX_PROMPT_BUILDERS` Registry](shared-fix-primitives-reference/02-prompt-registry-new-agent-and-tests.md#6-fix_prompt_builders-registry)
- [7. How to Add a New Expediter Agent](shared-fix-primitives-reference/02-prompt-registry-new-agent-and-tests.md#7-how-to-add-a-new-expediter-agent)
- [8. Test Coverage](shared-fix-primitives-reference/02-prompt-registry-new-agent-and-tests.md#8-test-coverage)
- [Related Documentation](shared-fix-primitives-reference/02-prompt-registry-new-agent-and-tests.md#related-documentation)

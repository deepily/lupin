# Automated Interactive Testing Guide

How Lupin's notification proxy answers agent questions in tests: architecture, strategy chain, profiles, Q&A scripts, scenarios, CLI and troubleshooting.

## Contents

This page is an index. The reference itself is in the parts below, in document order.

- [Table of Contents](automated-interactive-testing/01-overview-architecture-and-profiles.md#table-of-contents)
- [1. Overview & Purpose](automated-interactive-testing/01-overview-architecture-and-profiles.md#1-overview--purpose)
- [2. Architecture](automated-interactive-testing/01-overview-architecture-and-profiles.md#2-architecture)
- [3. Strategy Chain (3-Tier)](automated-interactive-testing/01-overview-architecture-and-profiles.md#3-strategy-chain-3-tier)
- [4. Test Profiles](automated-interactive-testing/01-overview-architecture-and-profiles.md#4-test-profiles)
- [5. Q&A Scripts (JSON Format)](automated-interactive-testing/02-scripts-responses-and-scenarios.md#5-qa-scripts-json-format)
- [6. Response Type Handling](automated-interactive-testing/02-scripts-responses-and-scenarios.md#6-response-type-handling)
- [7. Base Classes & Mixins](automated-interactive-testing/02-scripts-responses-and-scenarios.md#7-base-classes--mixins)
- [8. Writing New Scenarios](automated-interactive-testing/02-scripts-responses-and-scenarios.md#8-writing-new-scenarios)
- [9. The Integration Test (test_proxy_integration.py)](automated-interactive-testing/02-scripts-responses-and-scenarios.md#9-the-integration-test-test_proxy_integrationpy)
- [10. CLI Reference](automated-interactive-testing/03-cli-environment-and-troubleshooting.md#10-cli-reference)
- [11. Environment Variables](automated-interactive-testing/03-cli-environment-and-troubleshooting.md#11-environment-variables)
- [12. Execution Flow (End-to-End)](automated-interactive-testing/03-cli-environment-and-troubleshooting.md#12-execution-flow-end-to-end)
- [13. Troubleshooting](automated-interactive-testing/03-cli-environment-and-troubleshooting.md#13-troubleshooting)
- [14. Related Documentation](automated-interactive-testing/03-cli-environment-and-troubleshooting.md#14-related-documentation)

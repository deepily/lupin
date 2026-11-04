# Heartbeat-Arbiter Routing & Recipients Guide

Who the fleet arbiter contacts and how: the case-to-tier routing table, the active-manager resolver, the two delivery mechanisms and operations.

## Contents

This page is an index. The reference itself is in the parts below, in document order.

- [Table of Contents](heartbeat-arbiter-routing-guide/01-routing-table-and-tier-execution.md#table-of-contents)
- [1. What This Guide Answers](heartbeat-arbiter-routing-guide/01-routing-table-and-tier-execution.md#1-what-this-guide-answers)
- [2. Two Loops, One Routing Model](heartbeat-arbiter-routing-guide/01-routing-table-and-tier-execution.md#2-two-loops-one-routing-model)
- [3. The 13-Case → 6-Tier Routing Table](heartbeat-arbiter-routing-guide/01-routing-table-and-tier-execution.md#3-the-13-case--6-tier-routing-table)
- [4. How `_route` Executes a Tier (the Non-Actuation Redline)](heartbeat-arbiter-routing-guide/01-routing-table-and-tier-execution.md#4-how-_route-executes-a-tier-the-non-actuation-redline)
- [5. Who Counts as an "Active Manager"? (Resolver + Phantom Guard)](heartbeat-arbiter-routing-guide/02-resolver-delivery-health-and-operations.md#5-who-counts-as-an-active-manager-resolver--phantom-guard)
- [6. The Two Delivery Mechanisms](heartbeat-arbiter-routing-guide/02-resolver-delivery-health-and-operations.md#6-the-two-delivery-mechanisms)
- [7. Does the Health-Check Loop Notify? — Yes (Loop A → Rick-Only)](heartbeat-arbiter-routing-guide/02-resolver-delivery-health-and-operations.md#7-does-the-health-check-loop-notify--yes-loop-a--rick-only)
- [8. End-to-End Flow Diagram](heartbeat-arbiter-routing-guide/02-resolver-delivery-health-and-operations.md#8-end-to-end-flow-diagram)
- [9. Operational Notes](heartbeat-arbiter-routing-guide/02-resolver-delivery-health-and-operations.md#9-operational-notes)
- [10. Code Map](heartbeat-arbiter-routing-guide/02-resolver-delivery-health-and-operations.md#10-code-map)

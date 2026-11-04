# Lupin Notification API Reference

How Lupin notifications are delivered, sent, received and configured, with endpoints, models and lifecycle.

## Contents

This page is an index. The reference itself is in the parts below, in document order.

- [Table of Contents](notification-api/01-overview-layers-and-concepts.md#table-of-contents)
- [1. Overview & Architecture](notification-api/01-overview-layers-and-concepts.md#1-overview--architecture)
- [System Architecture Diagram](notification-api/02-architecture-request-flows-and-history.md#system-architecture-diagram)
- [1.5 Historical Evolution](notification-api/02-architecture-request-flows-and-history.md#15-historical-evolution)
- [2. Quick-Start Examples](notification-api/03-quick-start-examples.md#2-quick-start-examples)
- [3. Authentication](notification-api/04-authentication.md#3-authentication)
- [4. REST API Endpoints](notification-api/05-rest-api-endpoints.md#4-rest-api-endpoints)
- [5. Data Models & Enums](notification-api/06-data-models-enums-requests-responses.md#5-data-models--enums)
- [5.4 SSE Event Models](notification-api/07-sse-events-helpers-and-persistence-models.md#54-sse-event-models)
- [6. Notification Lifecycle / State Machine](notification-api/08-lifecycle-state-machine.md#6-notification-lifecycle--state-machine)
- [7. Sender Identity & Multi-Project Routing](notification-api/09-sender-identity-and-routing.md#7-sender-identity--multi-project-routing)
- [8. Sending Notifications Programmatically](notification-api/10-sending-tiers-1-and-2.md#8-sending-notifications-programmatically)
- [8.3 Tier 3 -- CLI Clients](notification-api/11-sending-tiers-3-and-4.md#83-tier-3----cli-clients)
- [9. Receiving Notifications](notification-api/12-receiving-notifications.md#9-receiving-notifications)
- [10. Voice I/O Integration](notification-api/13-voice-io-integration.md#10-voice-io-integration)
- [11. Notification Proxy Agent](notification-api/14-notification-proxy-agent.md#11-notification-proxy-agent)
- [12. Configuration Reference](notification-api/16-configuration-reference.md#12-configuration-reference)
- [13. Testing Guide](notification-api/17-testing-guide.md#13-testing-guide)

## Parts

| Part | Covers |
|---|---|
| [01-overview-layers-and-concepts.md](notification-api/01-overview-layers-and-concepts.md) | overview, layers and key concepts |
| [02-architecture-request-flows-and-history.md](notification-api/02-architecture-request-flows-and-history.md) | architecture, request flows, history |
| [03-quick-start-examples.md](notification-api/03-quick-start-examples.md) | quick-start examples |
| [04-authentication.md](notification-api/04-authentication.md) | authentication |
| [05-rest-api-endpoints.md](notification-api/05-rest-api-endpoints.md) | REST API endpoints |
| [06-data-models-enums-requests-responses.md](notification-api/06-data-models-enums-requests-responses.md) | enums, requests and responses |
| [07-sse-events-helpers-and-persistence-models.md](notification-api/07-sse-events-helpers-and-persistence-models.md) | SSE events, helpers, persistence models |
| [08-lifecycle-state-machine.md](notification-api/08-lifecycle-state-machine.md) | lifecycle and state machine |
| [09-sender-identity-and-routing.md](notification-api/09-sender-identity-and-routing.md) | sender identity and routing |
| [10-sending-tiers-1-and-2.md](notification-api/10-sending-tiers-1-and-2.md) | sending: MCP tools and cosa_interface |
| [11-sending-tiers-3-and-4.md](notification-api/11-sending-tiers-3-and-4.md) | sending: CLI clients and direct HTTP |
| [12-receiving-notifications.md](notification-api/12-receiving-notifications.md) | receiving notifications |
| [13-voice-io-integration.md](notification-api/13-voice-io-integration.md) | voice I/O integration |
| [14-notification-proxy-agent.md](notification-api/14-notification-proxy-agent.md) | the notification proxy agent: overview, architecture, tiers, running it |
| [15-proxy-agent-test-profiles-scripts-and-listener.md](notification-api/15-proxy-agent-test-profiles-scripts-and-listener.md) | proxy agent test profiles, Q&A scripts, credentials, listener and response submission |
| [16-configuration-reference.md](notification-api/16-configuration-reference.md) | configuration reference |
| [17-testing-guide.md](notification-api/17-testing-guide.md) | testing guide |

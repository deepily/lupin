# Lupin Notification API Reference

Everything about Lupin notifications: how they are delivered, the REST endpoints, data models, lifecycle, sender routing, sending and receiving, voice I/O, the proxy agent, configuration and tests.

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
- [12. Configuration Reference](notification-api/15-configuration-reference.md#12-configuration-reference)
- [13. Testing Guide](notification-api/16-testing-guide.md#13-testing-guide)

## Parts

| Part | Covers |
|---|---|
| [01-overview-layers-and-concepts.md](notification-api/01-overview-layers-and-concepts.md) | the table of contents, the executive summary, the three delivery layers with the FCM wake push side channel, and the key concepts |
| [02-architecture-request-flows-and-history.md](notification-api/02-architecture-request-flows-and-history.md) | the system architecture diagram, the component map, the two request flows and the historical evolution |
| [03-quick-start-examples.md](notification-api/03-quick-start-examples.md) | the quick-start recipes (section 2) |
| [04-authentication.md](notification-api/04-authentication.md) | authentication (section 3) |
| [05-rest-api-endpoints.md](notification-api/05-rest-api-endpoints.md) | the REST API endpoints (section 4) |
| [06-data-models-enums-requests-responses.md](notification-api/06-data-models-enums-requests-responses.md) | enums, request models, the persist query parameter and response models (sections 5.1 to 5.3) |
| [07-sse-events-helpers-and-persistence-models.md](notification-api/07-sse-events-helpers-and-persistence-models.md) | SSE event models, helper functions, the PostgreSQL notification model and the in-memory queue item (sections 5.4 to 5.7) |
| [08-lifecycle-state-machine.md](notification-api/08-lifecycle-state-machine.md) | the notification lifecycle and state machine (section 6) |
| [09-sender-identity-and-routing.md](notification-api/09-sender-identity-and-routing.md) | sender identity and multi-project routing (section 7) |
| [10-sending-tiers-1-and-2.md](notification-api/10-sending-tiers-1-and-2.md) | sending notifications programmatically: the introduction, MCP tools and the cosa_interface pattern (sections 8 to 8.2) |
| [11-sending-tiers-3-and-4.md](notification-api/11-sending-tiers-3-and-4.md) | sending through CLI clients and direct HTTP (sections 8.3 and 8.4) |
| [12-receiving-notifications.md](notification-api/12-receiving-notifications.md) | receiving notifications (section 9) |
| [13-voice-io-integration.md](notification-api/13-voice-io-integration.md) | voice I/O integration (section 10) |
| [14-notification-proxy-agent.md](notification-api/14-notification-proxy-agent.md) | the notification proxy agent (section 11) |
| [15-configuration-reference.md](notification-api/15-configuration-reference.md) | the configuration reference (section 12) |
| [16-testing-guide.md](notification-api/16-testing-guide.md) | the testing guide (section 13) |

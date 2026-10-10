# WebSocket Architecture Overview

How the WebSocket layer is built: the manager API and its state, device slots and frame resume, the authentication flow, the thread-safety model and the CC transcript console channel.

## Contents

This page is an index. The reference itself is in the parts below, in document order.

- [Executive Summary](websocket-architecture/01-overview-and-architecture.md#executive-summary)
- [System Architecture](websocket-architecture/01-overview-and-architecture.md#system-architecture)
- [WebSocketManager — Complete API](websocket-architecture/02-manager-api-attributes-to-device-slots.md#websocketmanager--complete-api)
- [Frame seq, resume, and ack (part 2)](websocket-architecture/03-frame-seq-resume-and-ack.md#frame-seq-resume-and-ack-part-2)
- [2b. CC Transcript Console Watcher Registry](websocket-architecture/04-watcher-registry-emission-and-auth.md#2b-cc-transcript-console-watcher-registry)
- [Authentication Flow](websocket-architecture/04-watcher-registry-emission-and-auth.md#authentication-flow)
- [Session ID Validation](websocket-architecture/04-watcher-registry-emission-and-auth.md#session-id-validation)
- [Thread-Safety Model](websocket-architecture/05-thread-safety-subscriptions-and-transcript-channel.md#thread-safety-model)
- [Dynamic Subscription Updates](websocket-architecture/05-thread-safety-subscriptions-and-transcript-channel.md#dynamic-subscription-updates)
- [CC Transcript Console Channel](websocket-architecture/05-thread-safety-subscriptions-and-transcript-channel.md#cc-transcript-console-channel)
- [Related Documentation](websocket-architecture/05-thread-safety-subscriptions-and-transcript-channel.md#related-documentation)

## Parts

| Part | Covers |
|---|---|
| [01-overview-and-architecture.md](websocket-architecture/01-overview-and-architecture.md) | the executive summary, key architectural principles, the high-level data flow and the dual-session design |
| [02-manager-api-attributes-to-device-slots.md](websocket-architecture/02-manager-api-attributes-to-device-slots.md) | the WebSocketManager API: class attributes, lifecycle, connection management and device slots |
| [03-frame-seq-resume-and-ack.md](websocket-architecture/03-frame-seq-resume-and-ack.md) | frame sequence numbers, resume, replay and ack for a device slot |
| [04-watcher-registry-emission-and-auth.md](websocket-architecture/04-watcher-registry-emission-and-auth.md) | the CC transcript watcher registry, event emission, user routing, subscriptions, session policy, background tasks, the authentication flow and session id validation |
| [05-thread-safety-subscriptions-and-transcript-channel.md](websocket-architecture/05-thread-safety-subscriptions-and-transcript-channel.md) | the thread-safety model, dynamic subscription updates, the CC transcript console channel and related documentation |

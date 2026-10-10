# Lupin REST API Quick Reference

Quick reference to every REST route Lupin serves: method, path, authentication and a one-line summary, grouped by section. The retired queue doors and their replacements come first.

## Contents

This page is an index. The reference itself is in the parts below, in document order.

- [Authentication Legend](rest-api-reference/01-overview-and-retired-doors.md#authentication-legend)
- [🪦 Retired queue doors — gone (410), remove by end of 2026](rest-api-reference/01-overview-and-retired-doors.md#-retired-queue-doors--gone-410-remove-by-end-of-2026)
- [the resume doors, the Claude Code pair and the permanent survivor route](rest-api-reference/02-retired-doors-continued.md)
- [1. Authentication (`/auth/*`)](rest-api-reference/03-core-routes.md#1-authentication-auth)
- [2. Admin (`/admin/*`)](rest-api-reference/03-core-routes.md#2-admin-admin)
- [3. System](rest-api-reference/03-core-routes.md#3-system)
- [4. Queue Management](rest-api-reference/03-core-routes.md#4-queue-management)
- [5. Notifications (`/api/notify/*`)](rest-api-reference/03-core-routes.md#5-notifications-apinotify)
- [6. Speech I/O](rest-api-reference/03-core-routes.md#6-speech-io)
- [7. Jobs (Stubs)](rest-api-reference/03-core-routes.md#7-jobs-stubs)
- [8. Embeddings (`/api/embeddings/*`)](rest-api-reference/04-agents-and-expediters.md#8-embeddings-apiembeddings)
- [9. Mode (`/api/mode/*`)](rest-api-reference/04-agents-and-expediters.md#9-mode-apimode)
- [10. Statistics (`/api/stats/*`)](rest-api-reference/04-agents-and-expediters.md#10-statistics-apistats)
- [11. Deep Research (`/api/deep-research/*`)](rest-api-reference/04-agents-and-expediters.md#11-deep-research-apideep-research)
- [12. Podcast Generator (`/api/podcast-generator/*`)](rest-api-reference/04-agents-and-expediters.md#12-podcast-generator-apipodcast-generator)
- [12a. Presentation Generator (`/api/presentation-generator/*`)](rest-api-reference/04-agents-and-expediters.md#12a-presentation-generator-apipresentation-generator)
- [13. Research-to-Podcast](rest-api-reference/04-agents-and-expediters.md#13-research-to-podcast)
- [13a. Research-to-Presentation](rest-api-reference/04-agents-and-expediters.md#13a-research-to-presentation)
- [14. Claude Code (`/api/claude-code/*`) — retired](rest-api-reference/04-agents-and-expediters.md#14-claude-code-apiclaude-code--retired)
- [15. Claude Code Queue (retired — use `/api/v2/submit`)](rest-api-reference/04-agents-and-expediters.md#15-claude-code-queue-retired--use-apiv2submit)
- [16. SWE Team (`/api/swe-team/*`)](rest-api-reference/04-agents-and-expediters.md#16-swe-team-apiswe-team)
- [17. Test Suite (`/api/test-suite/*`)](rest-api-reference/04-agents-and-expediters.md#17-test-suite-apitest-suite)
- [17a. Bug Fix Expediter (`/api/v2/ask` with BFE command)](rest-api-reference/04-agents-and-expediters.md#17a-bug-fix-expediter-apiv2ask-with-bfe-command)
- [17b. Test Fix Expediter (`/api/v2/ask` with TFE command)](rest-api-reference/04-agents-and-expediters.md#17b-test-fix-expediter-apiv2ask-with-tfe-command)
- [17c. Inter-Session Commons (`/api/commons/*`)](rest-api-reference/05-commons-proxy-mock-job.md#17c-inter-session-commons-apicommons)
- [18. Decision Proxy (`/api/proxy/*`)](rest-api-reference/05-commons-proxy-mock-job.md#18-decision-proxy-apiproxy)
- [19. Mock Job (`/api/mock-job/*`)](rest-api-reference/05-commons-proxy-mock-job.md#19-mock-job-apimock-job)
- [20. I/O Files (`/api/io/*`)](rest-api-reference/06-files-websockets-pages-push.md#20-io-files-apiio)
- [21. WebSocket Admin (`/api/websocket-sessions/*`)](rest-api-reference/06-files-websockets-pages-push.md#21-websocket-admin-apiwebsocket-sessions)
- [22. WebSocket Connections (`/ws/*`)](rest-api-reference/06-files-websockets-pages-push.md#22-websocket-connections-ws)
- [23. Pages (`/app/*`)](rest-api-reference/06-files-websockets-pages-push.md#23-pages-app)
- [24. Multiplexer (`/api/multiplexer/*`)](rest-api-reference/06-files-websockets-pages-push.md#24-multiplexer-apimultiplexer)
- [25. FCM Wake Push (`/api/fcm/*`)](rest-api-reference/06-files-websockets-pages-push.md#25-fcm-wake-push-apifcm)
- [25a. Heartbeat Stop Poke Switch (`/api/heartbeat/*`)](rest-api-reference/06-files-websockets-pages-push.md#25a-heartbeat-stop-poke-switch-apiheartbeat)
- [25b. Podcast Proxy (`/api/podcast-proxy/*`)](rest-api-reference/06-files-websockets-pages-push.md#25b-podcast-proxy-apipodcast-proxy)
- [26. Task Store — Promote/Demote Requests (`/api/tasks/*`)](rest-api-reference/07-task-store-and-cc-transcript.md#26-task-store--promotedemote-requests-apitasks)
- [27. CC Transcript Console (`/api/cc-transcript/*`)](rest-api-reference/07-task-store-and-cc-transcript.md#27-cc-transcript-console-apicc-transcript)
- [Job ID Prefixes](rest-api-reference/08-job-ids-and-cross-reference.md#job-id-prefixes)
- [Cross-Reference: Deep-Dive Documentation](rest-api-reference/08-job-ids-and-cross-reference.md#cross-reference-deep-dive-documentation)

## Parts

| Part | Covers |
|---|---|
| [01-overview-and-retired-doors.md](rest-api-reference/01-overview-and-retired-doors.md) | the authentication legend and the retired queue doors, with the survivors, the table and the test-suite and mock-job doors |
| [02-retired-doors-continued.md](rest-api-reference/02-retired-doors-continued.md) | the resume doors, the Claude Code pair and the permanent survivor route |
| [03-core-routes.md](rest-api-reference/03-core-routes.md) | authentication, admin, system, queue management, notifications, speech I/O and job stubs (sections 1 to 7) |
| [04-agents-and-expediters.md](rest-api-reference/04-agents-and-expediters.md) | embeddings, mode, statistics, deep research, podcast, presentation, research pipelines, Claude Code, SWE team, test suite and the two expediters (sections 8 to 17b) |
| [05-commons-proxy-mock-job.md](rest-api-reference/05-commons-proxy-mock-job.md) | inter-session commons, decision proxy and mock job (sections 17c to 19) |
| [06-files-websockets-pages-push.md](rest-api-reference/06-files-websockets-pages-push.md) | I/O files, WebSocket admin and connections, pages, multiplexer, FCM wake push, heartbeat switch and podcast proxy (sections 20 to 25b) |
| [07-task-store-and-cc-transcript.md](rest-api-reference/07-task-store-and-cc-transcript.md) | task store promote and demote requests, and the CC transcript console (sections 26 and 27) |
| [08-job-ids-and-cross-reference.md](rest-api-reference/08-job-ids-and-cross-reference.md) | job id prefixes and the cross-reference to the deep-dive documents |

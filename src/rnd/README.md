# R&D Documentation Index

This directory contains research and development documents for the Lupin project.

## Recent Additions

### 2026.01.12 - COSA Unified Agent Architecture
- **Architecture Design**: [2026.01.12-cosa-unified-agent-architecture.md](2026.01.12-cosa-unified-agent-architecture.md) - **🔄 IN PROGRESS** - Comprehensive architecture document covering three areas: (1) **Agent Architecture Analysis** - Comparative analysis of COSA agents vs Claude Code Dispatchers with 5 commonalities, 5 differences, and "Parallel with Shared Contracts" recommendation; (2) **Integration Patterns** - Code generation failure escalation to Claude Code, queue integration options; (3) **Conversation Identity Architecture** - Process-centric model for multi-session tracking, active conversation routing, notification UI nested accordion design, AgentBase conversation history integration. Enables distinguishing parallel Claude Code sessions in same project.

### 2026.01.12 - User-Level Mode System
- **Design Document**: [2026.01.12-user-level-mode-system-design.md](2026.01.12-user-level-mode-system-design.md) - **📋 READY TO IMPLEMENT** - Comprehensive design for user-level mode switching. Allows users to bypass LLM router and route directly to specific agents (math, calendar, weather, etc.). Features: in-memory state storage, 4 API endpoints, UI mode selector, session-only persistence. Includes architecture diagrams, API specification, UI mockups, and testing strategy.

### 2026.01.12 - Claude Code CLI Docker Installation
- **Docker Installation Guide**: [2026.01.12-claude-code-cli-docker-installation.md](2026.01.12-claude-code-cli-docker-installation.md) - **✅ IMPLEMENTED** - Level 2 implementation adding Claude Code CLI to Lupin Docker container. Enables Claude Code Dispatcher feature in containerized environments. Covers: Node.js 20.x + npm installation, cosa-voice MCP configuration with container paths, API key handling patterns (local dev prompt-style paste vs GCP Secret Manager), verification procedures. No secrets baked into image. ~200MB image size increase.

### 2026.01.09 - Claude Code Dispatcher Docker Deployment
- **Docker Deployment Analysis**: [2026.01.09-claude-code-dispatcher-docker-deployment.md](2026.01.09-claude-code-dispatcher-docker-deployment.md) - **📊 ANALYSIS COMPLETE** - Comprehensive analysis of deployment options for Claude Code Dispatcher feature. Documents 4 streaming fixes (output format, async subprocess, background task scheduling, CLI environment). Includes trade-off matrix for 4 deployment options: Install CLI in Docker (recommended), Run FastAPI locally, Use Anthropic SDK directly, Hybrid API proxy. Implementation checklist for Docker CLI installation.

### 2026.01.05 - Directory Rename Planning
- **Directory Rename Plan**: [2026.01.05-directory-rename-genie-to-lupin-plan.md](2026.01.05-directory-rename-genie-to-lupin-plan.md) - **⏳ PENDING** - Comprehensive plan for renaming project directory from `lupin` to `lupin`. Covers 76+ internal files, 6 external configs, 2 virtual environments, backup directories. 100% removal of "genie" naming (except legacy Jupyter notebooks). Estimated ~90 minutes execution time. 24-step checklist with rollback plan.

### 2026.01.02 - Claude Code Voice MCP Integration
- **Design Document**: [2025.12.31-claude-code-via-mcp-and-cosa-vox/2025.12.30-claude_code_voice_mcp_guide.md](2025.12.31-claude-code-via-mcp-and-cosa-vox/2025.12.30-claude_code_voice_mcp_guide.md) - **📋 DESIGN COMPLETE** - Comprehensive 935-line architecture guide for voice-enabled MCP server. Covers two operational modes: Option A (Print Mode for bounded tasks) and Option B (SDK Client for interactive sessions), plus Cold Call voice-initiated sessions.
- **Implementation Trajectory**: [2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-00-mcp-voice-implementation-trajectory.md](2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-00-mcp-voice-implementation-trajectory.md) - **📊 STATUS REPORT** - Design-to-implementation journey documenting what was built (MCP Server), what exists but isn't integrated (cosa_dispatcher.py), and gap analysis for remaining work.
- **Option A Planning**: [2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-01-option-a-print-mode-planning.md](2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-01-option-a-print-mode-planning.md) - **📋 READY TO IMPLEMENT** - Roadmap for bounded task execution via `claude -p "task"`. 5 phases: move dispatcher to production, update configs, smoke tests, E2E tests, CI/CD examples. Estimated 6-10 hours.
- **Option B Planning**: [2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-02-option-b-sdk-client-planning.md](2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-02-option-b-sdk-client-planning.md) - **⏸️ DEFERRED (SDK TBD)** - Roadmap for interactive SDK Client sessions. Depends on `claude-agent-sdk` availability. 5 phases covering session lifecycle, inject/interrupt, voice integration.
- **Cold Call Planning**: [2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-03-cold-call-flow-planning.md](2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-03-cold-call-flow-planning.md) - **⏸️ DEFERRED (needs A or B)** - Roadmap for voice-initiated session spawning. 6 phases: voice grammar, intent parser, daemon, wake word, dispatcher integration, E2E testing.
- **MCP Server**: `src/lupin_mcp/` - **✅ COMPLETE** - Production MCP server (372 lines) with 4 tools: notify(), converse(), ask_yes_no(), get_session_info(). Dynamic project detection, 10 smoke tests passing.

### 2025.12.30 - Sender-Aware Notification System
- **Implementation Tracker**: [2025.12.30-sender-aware-notification-tracker.md](2025.12.30-sender-aware-notification-tracker.md) - **🔄 IN PROGRESS** - Execution tracker for 8-phase sender-aware notification system implementation. Adds sender identification (`claude.code@{project}.deepily.ai`) enabling multi-project notification grouping, chat-style UI with collapsible sender cards, and conversation history persistence.
- **Design Document**: [2025.12.29-sender-aware-notification-system-design.md](2025.12.29-sender-aware-notification-system-design.md) - **📋 DESIGN COMPLETE** - Comprehensive 513-line implementation plan covering Queue Layer, CLI Layer, API Layer, PostgreSQL persistence, Frontend JS/CSS, and testing strategy.

### 2025.11.20 - Admin Solution Snapshots Dashboard
- **Admin Interface Planning**: [2025.11.20-admin-snapshots-dashboard.md](2025.11.20-admin-snapshots-dashboard.md) - **📋 READY TO IMPLEMENT** - Comprehensive implementation plan for admin solution snapshots search dashboard. Features: Simple text search (Question/Normalized/Gist), table display with view details modal, delete with confirmation, JWT admin role enforcement. Architecture: 3 new admin.py endpoints (search/details/delete), vanilla HTML/JS/CSS following Fresh Queue patterns. Developed through interactive requirements elicitation (7 questions), includes 5 implementation phases, testing checklists, 7-11 hour timeline. Foundation for future admin tools.

### 2025.11.20 - Math Agent XML Schema Mismatch Investigation
- **XML Pipeline Debugging**: [2025.11.20-math-agent-xml-schema-mismatch.md](2025.11.20-math-agent-xml-schema-mismatch.md) - **🔍 INVESTIGATION IN PROGRESS** - Comprehensive analysis of pydantic_ai integration revealing two-stage XML pipeline schema mismatch. Math agent uses CodeBrainstormResponse (7 required fields) for code generation, but formatter's simple RephraseResponse (`<rephrased-answer>`) is being validated against wrong schema. Includes complete pipeline flow analysis, 4 hypotheses, investigation checklist, and debugging roadmap. Follows successful pydantic_ai 0.6.2 API migration (ModelSettings, `.output`). Ready for next session's debugging.

### 2025.10.17 - SSE Phase 2 Design Session
- **Notification System**: [sse-notifications/05-phase2-design-decisions.md](sse-notifications/05-phase2-design-decisions.md) - **🚧 DESIGN IN PROGRESS** - Interactive design session for Phase 2 SSE notification system (response-required notifications). Completed: Database schema (persistent storage), response types (yes/no with LLM interpretation, open-ended), timeout behavior (multi-modal countdown). Pending: SSE architecture, return value propagation, UI/UX, MVP scoping. Resume point: Area 3 Q3.2 (Timeout handling). Session 1 of design Q&A complete (3/9 areas).
- **Design Questions**: [sse-notifications/98-notification-design-draft.md](sse-notifications/98-notification-design-draft.md) - Original design questions document (answers being captured in 05-phase2-design-decisions.md)

### 2025.10.16 - JWT Token Proactive Refresh
- **Authentication Enhancement**: [2025.10.16-jwt-token-proactive-refresh.md](2025.10.16-jwt-token-proactive-refresh.md) - **✅ COMPLETE** - Hybrid proactive token refresh system eliminating 401 errors during idle periods. Implements dual-mechanism refresh (periodic monitor + heartbeat-triggered), server-driven configuration with explicit unit naming, comprehensive testing strategy (17/17 tests passing). Solves high-priority notification playback after >1 hour inactivity. Production validated!

### 2025.10.04 - Admin User Management Implementation
- **Admin Interface**: [2025.10.04-admin-user-management-implementation-plan.md](2025.10.04-admin-user-management-implementation-plan.md) - **📋 READY TO IMPLEMENT** - Complete MVP plan for administrative user management interface. Includes user listing/search, role management, account status control, and admin password reset. Backend (admin_service.py, routers/admin.py), Frontend (admin/users.html, admin-users.js, admin.css), comprehensive API specs, security requirements, and integration testing strategy. Estimated 6-8 hours implementation.

### 2025.10.03 - User-Filtered Queue Views Implementation
- **Multi-Tenant Feature**: [2025.10.03-user-filtered-queue-views-implementation-plan.md](2025.10.03-user-filtered-queue-views-implementation-plan.md) - **✅ PHASE 1 COMPLETE** - Role-based queue filtering backend infrastructure with 32/32 unit tests passing (100%). Multi-tenant isolation with admin override capability. Phase 2 (Admin UI) and Phase 3 (Documentation) pending.

### 2025.09.28 - Three-Level Testing Framework Design
- **Testing Strategy**: [2025.09.28-three-level-testing-design-and-progress.md](2025.09.28-three-level-testing-design-and-progress.md) - **✅ COMPLETE** - Comprehensive testing implementation complete: 47 unit tests across 6 files, 100% success rate, all phases 1-3 finished

### 2025.09.27 - Three-Level Question Representation Architecture COMPLETE
- **Architecture Implementation**: [2025.09.27-three-level-question-representation-architecture.md](2025.09.27-three-level-question-representation-architecture.md) - **✅ COMPLETE** - Comprehensive implementation fixing critical search failures with hierarchical Verbatim → Normalized → Gist architecture
- **Session-End Automation**: [/src/rnd/prompts/lupin-session-end.md](prompts/lupin-session-end.md) - Automated end-of-session ritual extracted from configuration files

### 2025.09.23 - Smoke Test Prompt Infrastructure
- **Smoke Test Prompts**: [/src/rnd/prompts/](prompts/) - Comprehensive baseline and remediation testing infrastructure with Claude Code integration
- **Universal Templates**: [/src/rnd/prompts/templates/](prompts/templates/) - Reusable smoke test templates for any project
- **Claude Code Commands**: [/src/cosa/.claude/commands/](../cosa/.claude/commands/) - Intelligent slash commands for automated testing workflows

## Project Architecture Overview

Lupin is built on/uses:
- **FastAPI** server architecture
- **PydanticAI** for Agent-based abstractions & data validation
- **WebSockets** support for real-time communication

Lupin contains multiple sub repos:
- **CoSA** support for real-time communication
- **Lupin Mobile** implements queue UI for agent-to-user communication
- **Lupin Plugin for Firefox** provides browser integration for Lupin features

Lupin does a lot of things:
- **Notification system** for agent-to-user feedback
- **Voice drives Firefox with plugin**
- **Text-to-Speech (TTS)** streaming and caching of TTS audio responses
- **Speech-to-Text (STT)** for voice input
- **Abstracted access to LLMs** both local and industrial strength
- **Easy PEFT** High level training object performs all the things before during and after training a new LoRA for you
- **Code is memory** 

## Project Goals for v0.1.0
- **JWT authentication** using firebase? (See RND docs for details)
- **PydanticAI** data validation for XML-based I/O interactions with agents
- **Agentic frameworks** implement high-level abstraction for running the same query on multiple agentic frameworks
  - Google ADK 
  - OpenAI
  - Anthropic 
  - Perplexity 
- **Host on GCP** (Google Cloud Platform) for demoing and R&D purposes
- 

For implementation details, see the specific documents listed below.

## Active Documents

### Current Development (2025.09)

#### 🚀 Authentication System Design
- **[2025.09.29-jwt-oauth-implementation-design-and-tracker.md](2025.09.29-jwt-oauth-implementation-design-and-tracker.md)** - **📋 PLANNING**: Comprehensive JWT/OAuth authentication system design with 10-phase implementation plan, backward-compatible migration strategy, and complete tracking framework for upgrading from mock authentication to production-ready security (⏳ Phase 1-2 ready to begin)

#### 🎉 Major Infrastructure Completions
- **[2025.09.28-three-level-testing-design-and-progress.md](2025.09.28-three-level-testing-design-and-progress.md)** - **🔄 ACTIVE**: Comprehensive testing framework design for three-level representation system with progress tracking, testing patterns documentation, and critical test case specifications (📋 design complete - implementation in progress)
- **[2025.09.27-three-level-question-representation-architecture.md](2025.09.27-three-level-question-representation-architecture.md)** - **✅ COMPLETE**: Comprehensive three-level question representation architecture (Verbatim → Normalized → Gist) with ultrathinking analysis and six-phase implementation plan for systematic question indexing refactoring (🚀 implementation complete - search failures resolved)
- **[2025.09.22-cosa-agents-v010-migration-plan.md](2025.09.22-cosa-agents-v010-migration-plan.md)** - ✅ **COMPLETED**: Comprehensive zero-risk migration plan for moving 25 agent files from v010 subdirectory to main agents directory (✅ successfully executed - all agents consolidated)
- **[2025.09.20-memory-corruption-incident-report.md](2025.09.20-memory-corruption-incident-report.md)** - Complete incident report and recovery documentation for LanceDB database deletion and restoration (✅ completed - 44/44 snapshots recovered, all 4 tables operational with enhanced robustness)
- **[2025.08.22-solution-snapshot-lancedb-interface-migration-plan.md](2025.08.22-solution-snapshot-lancedb-interface-migration-plan.md)** - **🏆 MAJOR MILESTONE**: Complete LanceDB migration project from file-based JSON to vector database (✅ 100% COMPLETE - Phase 5 production deployment finished, enhanced table creation robustness)

### Previous Development (2025.08)

#### 🎉 Major Infrastructure Completions
- **[2025.08.13-smoke-test-data-collection-strategy.md](2025.08.13-smoke-test-data-collection-strategy.md)** - Comprehensive data-collection-first smoke testing methodology for systematic diagnostics (✅ completed - reusable framework established for future test runs)
- **[2025.08.13-smoke-test-execution-report.md](2025.08.13-smoke-test-execution-report.md)** - Complete analysis of 72-test smoke test suite with failure patterns and remediation priorities (✅ completed - critical API endpoint failures identified)
- **[2025.08.13-session-state-for-tomorrow.md](2025.08.13-session-state-for-tomorrow.md)** - Detailed continuation plan for immediate pickup of smoke test remediation work (✅ completed - ready for tomorrow's session)
- **[2025.08.12-template-rendering-investigation.md](2025.08.12-template-rendering-investigation.md)** - Investigation of prompt template rendering approaches: Python dictionaries vs Pydantic objects (✅ completed - current approach documented, future enhancement opportunities identified)
- **[2025.08.12-phase-6-complex-agent-requirements.md](2025.08.12-phase-6-complex-agent-requirements.md)** - Phase 6 complex agent migration requirements for IterativeDebuggingAgent and BugInjector (✅ completed - all complex agents migrated successfully to production)
- **[2025.08.10-xml-compatibility-investigation-findings.md](2025.08.10-xml-compatibility-investigation-findings.md)** - Analysis of baseline vs Pydantic XML parsing discrepancies and data integrity improvements (✅ completed - critical data loss issues resolved)
- **[2025.08.09-pydantic-xml-migration-plan.md](2025.08.09-pydantic-xml-migration-plan.md)** - **🏆 MAJOR MILESTONE**: Complete Pydantic XML migration from legacy util_xml.py to modern structured parsing (✅ 100% COMPLETE - all agents migrated to production with full type safety and zero issues)

#### Audio & UI Systems
- **[2025.08.06-tts-audio-caching-implementation.md](2025.08.06-tts-audio-caching-implementation.md)** - Lightweight TTS audio caching system with cross-mode compatibility and SHA-256 hashing (✅ completed - 71.4% hit rate achieved, ready for browser testing)
- **[2025.08.04-fresh-queue-ui-implementation.md](2025.08.04-fresh-queue-ui-implementation.md)** - Modern Fresh Queue UI with notification system and comprehensive job management (✅ completed)
- **[2025.08.03-qa-audio-silence-mystery.md](2025.08.03-qa-audio-silence-mystery.md)** - Critical technical mystery: Q&A responses produce silence while notifications work, despite identical execution paths (🔍 resolved)
- **[2025.08.01-sequential-audio-production-migration.md](2025.08.01-sequential-audio-production-migration.md)** - Production migration plan for Sequential Audio Element Queue from experimental validation to HybridTTS integration (✅ completed)
- **[2025.08.01-audio-chunk-sequential-playback-analysis.md](2025.08.01-audio-chunk-sequential-playback-analysis.md)** - Root cause analysis and implementation strategy for fixing audio chunk overlap issues (✅ completed - experimental validation successful)

### Current Development (2025.07)
- **[2025.07.30-websocket-branch-polish-tracker.md](2025.07.30-websocket-branch-polish-tracker.md)** - Comprehensive tracking document for debugging, polishing, and documenting completed WebSocket functionality (📋 planning phase)
- **[2025.07.24-websocket-async-bridge-implementation.md](2025.07.24-websocket-async-bridge-implementation.md)** - WebSocket implementation progress tracker through Phases 1, 2, and 2.5 (✅ completed)
- **[2025.07.12-progressive-tts-streaming-experimental-tracker.md](2025.07.12-progressive-tts-streaming-experimental-tracker.md)** - Firefox-first experimental implementation of true progressive audio streaming (✅ completed - integrated into main system)
- **[2025.07.12-tts-mode-switching-design.md](2025.07.12-tts-mode-switching-design.md)** - Add dynamic switching between OpenAI batch TTS and ElevenLabs streaming TTS (✅ completed)
- **[2025.07.12-tts-mode-switching-phase1-tracker.md](2025.07.12-tts-mode-switching-phase1-tracker.md)** - Phase 1 implementation tracker for TTS mode switching (✅ completed)
- **[2025.07.12-audio-to-speech-renaming-design.md](2025.07.12-audio-to-speech-renaming-design.md)** - Rename misleading "audio" terminology to accurate "speech" terminology for TTS functionality (✅ completed)
- **[2025.07.11-websocket-user-routing-architecture.md](2025.07.11-websocket-user-routing-architecture.md)** - User-centric event routing architecture to replace ephemeral WebSocket ID dependencies (✅ core phases completed)
- **[2025.07.01-fastapi-clock-events-research.md](2025.07.01-fastapi-clock-events-research.md)** - Research plan for implementing clock update events using existing WebSocketManager (✅ completed)

### Previous Development (2025.06)
- **[2025.06.20-claude-code-notification-system-design.md](2025.06.20-claude-code-notification-system-design.md)** - Real-time notification system design
- **[2025.06.20-claude-code-to-api-and-cli-integration.md](2025.06.20-claude-code-to-api-and-cli-integration.md)** - Claude Code integration documentation
- **[2025.06.03-websocket-tts-streaming-design.md](2025.06.03-websocket-tts-streaming-design.md)** - Real-time text-to-speech streaming over WebSockets

## Archived Documents

### Completed Work (2025.08)
- **[archived/2025.08.01-websocket-smoke-test-suite-design.md](archived/2025.08.01-websocket-smoke-test-suite-design.md)** - Comprehensive WebSocket smoke test suite implementation (✅ completed - 50 tests deployed with 92% success rate, production-ready regression detection)
- **[archived/2025.08.01-design-by-contract-audit.md](archived/2025.08.01-design-by-contract-audit.md)** - Design by Contract documentation implementation (✅ largely completed - 83 functions documented across 7 high/medium priority files, professional-grade specifications)

### Completed Work (2025.07)
- **[archived/2025.07.31-elevenlabs-tts-quality-optimization-plan.md](archived/2025.07.31-elevenlabs-tts-quality-optimization-plan.md)** - ElevenLabs TTS quality optimization implementation (✅ completed - Flash v2.5 model deployed with <200ms latency, provider switching operational)
- **[archived/2025.07.01-todo-and-running-queues-as-producer-consumer.md](archived/2025.07.01-todo-and-running-queues-as-producer-consumer.md)** - Producer-consumer queue implementation (6700x performance improvement)
- **[archived/2025.07.01-fastapi-clock-implementation-success.md](archived/2025.07.01-fastapi-clock-implementation-success.md)** - Success report documenting asyncio.create_task() pattern implementation
- **[archived/2025.07.01-queue-integration-plan.md](archived/2025.07.01-queue-integration-plan.md)** - Plan for connecting running queue and implementing background tasks in FastAPI

### Completed Work (2025.06)
- **[archived/2025.06.29-cosa-lupin-renaming-completion.md](archived/2025.06.29-cosa-lupin-renaming-completion.md)** - Project renaming completion report
- **[archived/2025.06.28-lupin-renaming-plan.md](archived/2025.06.28-lupin-renaming-plan.md)** - Project rebranding from Genie-in-the-Box to Lupin
- **[archived/2025.06.27-flask-elimination-plan.md](archived/2025.06.27-flask-elimination-plan.md)** - Plan to remove deprecated Flask infrastructure (completed)
- **[archived/2025.06.20-claude-code-notification-system-design-implementation-tracker.md](archived/2025.06.20-claude-code-notification-system-design-implementation-tracker.md)** - Implementation tracking for notification system (Phase 2 complete)
- **[archived/2025.06.17-fastapi-queue-implementation-plan.md](archived/2025.06.17-fastapi-queue-implementation-plan.md)** - Queue-based request handling in FastAPI
- **[archived/2025.06.16-fastapi-modular-refactoring-plan.md](archived/2025.06.16-fastapi-modular-refactoring-plan.md)** - Modular architecture refactoring

### Flask Migration (Completed 2025.06.28)
- **[archived/2025.05.19-flask-to-fastapi-migration-plan.md](archived/2025.05.19-flask-to-fastapi-migration-plan.md)** - Comprehensive Flask to FastAPI migration plan
- **[archived/2025.04.05-flask-to-fastapi-migration.md](archived/2025.04.05-flask-to-fastapi-migration.md)** - Early migration planning and considerations

### Early Development (2025.01)
- **[archived/2025.01.24-fastapi-refactoring-plan.md](archived/2025.01.24-fastapi-refactoring-plan.md)** - Initial FastAPI refactoring plans

## Document Conventions

- All documents follow the `YYYY.MM.DD-description.md` naming format
- Active documents represent ongoing or planned work
- Archived documents represent completed initiatives
- Each document should include a clear purpose and current status


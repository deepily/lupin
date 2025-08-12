# R&D Documentation Index

This directory contains research and development documents for the Lupin project.

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

### Current Development (2025.08)

#### 🎉 Major Infrastructure Completions
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


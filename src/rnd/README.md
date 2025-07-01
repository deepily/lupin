# R&D Documentation Index

This directory contains research and development documents for the Lupin project.

## Active Documents

### Current Development (2025.07)
- **[2025.07.01-queue-integration-plan.md](2025.07.01-queue-integration-plan.md)** - Plan for connecting running queue and implementing background tasks in FastAPI
- **[2025.07.01-fastapi-clock-events-research.md](2025.07.01-fastapi-clock-events-research.md)** - Research plan for implementing clock update events using existing WebSocketManager
- **[2025.07.01-fastapi-clock-implementation-success.md](2025.07.01-fastapi-clock-implementation-success.md)** - Success report documenting asyncio.create_task() pattern implementation

### Previous Development (2025.06)
- **[2025.06.28-lupin-renaming-plan.md](2025.06.28-lupin-renaming-plan.md)** - Project rebranding from Genie-in-the-Box to Lupin
- **[2025.06.27-flask-elimination-plan.md](2025.06.27-flask-elimination-plan.md)** - Plan to remove deprecated Flask infrastructure
- **[2025.06.20-claude-code-notification-system-design.md](2025.06.20-claude-code-notification-system-design.md)** - Real-time notification system design
- **[2025.06.20-claude-code-notification-system-design-implementation-tracker.md](2025.06.20-claude-code-notification-system-design-implementation-tracker.md)** - Implementation tracking for notification system
- **[2025.06.20-claude-code-to-api-and-cli-integration.md](2025.06.20-claude-code-to-api-and-cli-integration.md)** - Claude Code integration documentation
- **[2025.06.17-fastapi-queue-implementation-plan.md](2025.06.17-fastapi-queue-implementation-plan.md)** - Queue-based request handling in FastAPI
- **[2025.06.16-fastapi-modular-refactoring-plan.md](2025.06.16-fastapi-modular-refactoring-plan.md)** - Modular architecture refactoring
- **[2025.06.03-websocket-tts-streaming-design.md](2025.06.03-websocket-tts-streaming-design.md)** - Real-time text-to-speech streaming over WebSockets

### Early Development (2025.01)
- **[2025.01.24-fastapi-refactoring-plan.md](2025.01.24-fastapi-refactoring-plan.md)** - Initial FastAPI refactoring plans

## Archived Documents

### Flask Migration (Completed 2025.06.28)
- **[archived/2025.05.19-flask-to-fastapi-migration-plan.md](archived/2025.05.19-flask-to-fastapi-migration-plan.md)** - Comprehensive Flask to FastAPI migration plan
- **[archived/2025.04.05-flask-to-fastapi-migration.md](archived/2025.04.05-flask-to-fastapi-migration.md)** - Early migration planning and considerations

## Document Conventions

- All documents follow the `YYYY.MM.DD-description.md` naming format
- Active documents represent ongoing or planned work
- Archived documents represent completed initiatives
- Each document should include a clear purpose and current status

## Project Architecture Overview

Lupin is built on:
- **FastAPI** server architecture (Flask completely removed as of 2025.06.28)
- **COSA** (Collection of Small Agents) framework integration
- **WebSocket** support for real-time communication
- **Notification system** for agent-to-user feedback

For implementation details, see the specific documents listed above.
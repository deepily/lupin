# Lupin

_**TBD**: Why I choose this name._

### YOU KNOW THE DREAM

Talk to the computer, and it tells you, or does, something useful.

#### YOU PROBABLY KNOW THE PROBLEM

Currently, AI Agents & Chat Bots are [slow and expensive](https://www.linkedin.com/pulse/langchains-dataframe-agent-why-you-so-slow-r-p-ruiz). 
They [make silly mistakes](https://www.linkedin.com/pulse/meet-my-idiot-savant-intern-chatgpts-advanced-data-analysis-ruiz/). 
They're forgetful. And they work too hard reinventing the wheel.

#### WHAT MOST PEOPLE PROBABLY DON'T REALIZE

Even the simplest of vox in & vox out UX -- especially when coupled with agentic behaviors -- is **_hard_**. It's asynchronous, and usually frustratingly 
slow. It's a new way of interacting with computers, which requires a global re-thinking of how different the UI control and display modalities interact. 

#### I'VE BEEN WORKING ON SOLUTIONs to THESE PROBLEMS FOR A WHILE NOW

I'm working on helping Agents [remember what problems they've already solved](https://www.linkedin.com/pulse/slow-expensive-erratic-problem-whats-solution-r-p-ruiz/), 
or if they've solved something semantically synonymous or computationally analogous before.


#### TECHNICAL ROADMAP & ARCHITECTURE

Lupin is built on a modern FastAPI architecture with WebSocket support for real-time communication. The project integrates with the COSA (Collection of Small Agents) framework to provide intelligent agent capabilities.

**Current Architecture:**
- **FastAPI-only server** running on port 7999 (Flask has been completely eliminated as of 2025.06.28)
- **WebSocket support** for real-time bidirectional communication
- **COSA integration** for modular agent framework
- **Notification system** for agent-to-user feedback

**Key Technical Documents:**
- **[WebSocket Events Documentation](src/docs/websocket-events.md)** - Comprehensive guide to all WebSocket events and their usage
- **[WebSocket Architecture Overview](src/docs/websocket-architecture.md)** - Complete system design and architectural patterns
- **[WebSocket Troubleshooting Guide](src/docs/websocket-troubleshooting.md)** - Common issues, solutions, and debugging procedures
- **[WebSocket TTS Streaming Design](src/rnd/2025.06.03-websocket-tts-streaming-design.md)** - Architecture for real-time text-to-speech streaming
- **[Claude Code Notification System](src/rnd/2025.06.20-claude-code-notification-system-design.md)** - Design for real-time agent notifications
- **[FastAPI Queue Implementation](src/rnd/2025.06.17-fastapi-queue-implementation-plan.md)** - Queue-based request handling
- **[Lupin Renaming Plan](src/rnd/2025.06.28-lupin-renaming-plan.md)** - Project rebranding documentation
- **[Audio Chunk Sequential Playback Analysis](src/rnd/2025.08.01-audio-chunk-sequential-playback-analysis.md)** - Root cause analysis and solution for ElevenLabs audio duplication issues
- **[LanceDB Migration Plan](src/rnd/2025.08.22-solution-snapshot-lancedb-interface-migration-plan.md)** - Complete migration from file-based to vector database storage

**Current Development Status (2026.02.04):**

## What's New in v0.1.3

### Agentic Job System (CJ Flow)
- **Claude Code Job Integration** - Full Claude Agent SDK integration with QueueableJob protocol (22 attributes + 3 methods)
- **Deep Research Agent** - Background research jobs with automatic report generation
- **Podcast Generator** - Convert research documents to audio podcast format
- **Research→Podcast Workflow** - Chained pipeline from research to podcast in one click
- **Dry-Run Mode** - Test all agentic jobs without API costs (enabled by default in UI)

### WebSocket Infrastructure
- **JWT Authentication** - Secure WebSocket connections with JWT tokens (replaces mock tokens)
- **job_state_transition Events** - Real-time job status updates via WebSocket
- **100% WebSocket Test Coverage** - All 50 smoke tests passing (up from 46% before v0.1.3)

### Testing & Quality
- **Unit Tests**: 195/195 (100%) - Complete test infrastructure remediation
- **WebSocket Tests**: 50/50 (100%) - JWT auth migration complete
- **Integration Tests**: Comprehensive API endpoint testing with auth

### Training Pipeline
- **Unified LoRA Training** - Single pipeline for voice commands + agentic job intents
- **40,258 Training Examples** - Including 600 agentic command examples
- **Agentic Intent Recognition** - "Go to deep research", "make a podcast about..."

### Notifications UI
- **Compact Dropdown Controls** - Task Type and Flow Type selectors (replaces cluttered radio buttons)
- **cosa-voice MCP Integration** - Voice I/O for Claude Code workflows via MCP server

### Previous Releases

The project has several **completed milestones from earlier versions**:

1. **✅ LanceDB Migration Complete** (v0.1.2) - Successfully migrated solution snapshots from file-based storage to LanceDB vector database with 100% feature parity and massive performance improvements
2. **✅ Configuration-Based Backend Switching** (v0.1.2) - Implemented seamless switching between storage backends via simple configuration change
3. **✅ WebSocket FastAPI Test Suite** (v0.1.1) - Comprehensive diagnostic and testing tools for WebSocket functionality
4. **✅ FastAPI Migration** (v0.1.0) - Complete Flask elimination, FastAPI-only architecture

## Solution Snapshot Storage

The system supports two storage backends for solution snapshots (agent memory):

### File-Based Storage (Default)
- Stores snapshots as JSON files in `/src/conf/long-term-memory/solutions/`
- Good for small datasets (<100 snapshots)
- No additional dependencies required
- Simple file system operations

### LanceDB Storage (Recommended for Production)
- Vector database with native similarity search
- 100-1000x faster for search operations
- Better memory efficiency and scalability
- Advanced semantic search capabilities

### Switching Between Backends

To switch from file-based to LanceDB storage:

1. **Edit Configuration** - In `src/conf/lupin-app.ini`, change:
   ```ini
   solution snapshots manager type = lancedb
   ```

2. **Optional: Migrate Existing Data** - Run the migration script:
   ```bash
   python src/scripts/migrate_snapshots_to_lancedb.py
   ```

3. **Restart Server** - Restart the FastAPI server to apply changes

To switch back to file-based storage, simply change the config back to:
```ini
solution snapshots manager type = file_based
```

Both backends provide **identical functionality** - the switch is completely transparent to users and agents.

## Performance Comparison

Based on benchmarks with real data:

| Operation | File-Based | LanceDB | Speedup |
|-----------|------------|---------|---------|
| Search (exact) | 96ms | 0.1ms | **960x faster** |
| Add snapshot | 827ms | 15ms | **55x faster** |
| Search (fuzzy) | 120ms | 0.3ms | **400x faster** |

*Note: Performance varies based on dataset size. For small datasets (<100 snapshots), file-based may be faster due to lower overhead.*

## Embedding Performance

Local GPU embedding engines (CodeRankEmbed + nomic-embed-text-v1.5) vs OpenAI API (text-embedding-3-small), benchmarked with N=10 iterations over 3 queries each:

| Operation | Content Type | Local GPU | OpenAI API | Speedup |
|-----------|-------------|-----------|------------|---------|
| Single embedding | prose | 164 ms | 1,146 ms | **7x faster** |
| Single embedding | code | 70 ms | 1,211 ms | **17x faster** |
| Batch (3 items) | prose | 8 ms | 2,989 ms | **374x faster** |
| Batch (3 items) | code | 8 ms | 3,183 ms | **398x faster** |

Toggle between providers via `embedding provider = local | openai` in `lupin-app.ini`. Benchmark harness: `pytest src/tests/smoke/test_embedding_benchmark.py -v -s`

**Quick Start Commands:**
- Run FastAPI server: `src/scripts/run-fastapi-lupin.sh` (port 7999)
- Run GUI client: `src/scripts/run-lupin-gui.sh`
- Run GSM8K benchmarks: `src/scripts/run-gsm8k.sh --help`

**WebSocket Configuration:**

The Lupin system uses WebSocket connections for real-time communication between the server and client applications. Configuration is managed through `src/conf/lupin-app.ini`.

*Key WebSocket Settings:*
```ini
# Enable/disable WebSocket functionality
websocket_enabled = true

# Connection health monitoring
websocket_heartbeat_interval = 30        # Ping interval (seconds)
websocket_cleanup_interval = 3600        # Stale session cleanup (seconds)

# Connection limits
websocket_max_connections_per_user = 5   # Multiple tabs support
websocket_single_session_policy = false  # Allow multiple sessions per user

# Available events (comma-separated)
websocket_available_events = queue_todo_update, queue_done_update, 
                             audio_streaming_chunk, notification_queue_update, 
                             sys_time_update, sys_ping, auth_request, auth_success
```

*WebSocket Endpoints:*
- `ws://localhost:7999/ws/queue/{session_id}` - Main application WebSocket for authenticated users
- `ws://localhost:7999/ws/audio/{session_id}` - Audio-only WebSocket for TTS streaming

*Authentication:* All WebSocket connections require authentication via `auth_request` message with Bearer token format: `Bearer mock_token_email_{your_email}`

For detailed configuration options, troubleshooting, and architecture information, see the WebSocket documentation links above.

#### DISCLAIMER

This [Lupin project]() 
started out as an **_extremely_** large set of working sketches that I've been actively organizing & tidying up so that I can collaborate with others.

And I'm getting closer: I'm currently at v0.1.4, with a plan to share and build upon it RealSoonNow!


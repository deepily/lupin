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
- **[WebSocket TTS Streaming Design](src/rnd/2025.06.03-websocket-tts-streaming-design.md)** - Architecture for real-time text-to-speech streaming
- **[Claude Code Notification System](src/rnd/2025.06.20-claude-code-notification-system-design.md)** - Design for real-time agent notifications
- **[FastAPI Queue Implementation](src/rnd/2025.06.17-fastapi-queue-implementation-plan.md)** - Queue-based request handling
- **[Lupin Renaming Plan](src/rnd/2025.06.28-lupin-renaming-plan.md)** - Project rebranding documentation
- **[Audio Chunk Sequential Playback Analysis](src/rnd/2025.08.01-audio-chunk-sequential-playback-analysis.md)** - Root cause analysis and solution for ElevenLabs audio duplication issues

**Current Development Status (2025.08.01):**

The project currently has **three ongoing parallel development efforts**:

1. **Audio Chunk Sequential Playback Fix** - Resolving ElevenLabs WebSocket audio duplication through sequential scheduling
2. **WebSocket FastAPI Test Suite** - Comprehensive diagnostic and testing tools for WebSocket functionality
3. **FastAPI and Socket Polishing** - Continued refinement of WebSocket infrastructure and API endpoints

**Quick Start Commands:**
- Run FastAPI server: `src/scripts/run-fastapi-lupin.sh` (port 7999)
- Run GUI client: `src/scripts/run-lupin-gui.sh`
- Run GSM8K benchmarks: `src/scripts/run-gsm8k.sh --help`

#### DISCLAIMER

This [Lupin project]() 
started out as an **_extremely_** large set of working sketches that I've been actively organizing & tidying up so that I can collaborate with others.

And I'm getting closer: I'm currently at v0.0.6, with a plan to share and build upon it when I arrive at v0.1.0, coming RealSoonNow!



<picture>
 <img alt="Lupin - Performant Vox 2 Vox Agents" src="https://deepily.ai/images/logo-no-background.svg">
</picture>

# Lupin

### YOU KNOW THE DREAM

Talk to the computer, and it tells you, or does, something useful.

#### YOU PROBABLY KNOW THE PROBLEM

Currently, AI Agents & Chat Bots are [slow and expensive](https://www.linkedin.com/pulse/langchains-dataframe-agent-why-you-so-slow-r-p-ruiz). 
They [make silly mistakes](https://www.linkedin.com/pulse/meet-my-idiot-savant-intern-chatgpts-advanced-data-analysis-ruiz/). 
They're forgetful. And they work too hard reinventing the wheel.

#### WHAT MOST PEOPLE PROBABLY DON'T REALIZE

Even the simplest of vox in & vox out UX -- especially when coupled with agentic behaviors -- is **_hard_**. It's asynchronous, and usually frustratingly 
slow. It's a new way of interacting with computers, which requires a global re-thinking of how different the UI control and display modalities interact. 

#### DEEPILY ~~HAS~~ IS WORKING ON ~~A~~ SOLUTIONs

I'm working on helping Agents [remember what problems they've already solved](https://www.linkedin.com/pulse/slow-expensive-erratic-problem-whats-solution-r-p-ruiz/), 
or if they've solved something semantically synonymous or computationally analogous before.

#### THE RESULT

Fast, real time responses, asynchronous callbacks for big jobs, and more natural, human-like interaction. You _will_ want to talk to your computer!

#### THE VIEW FROM 30,000 FT

There are two ways to answer a question when using agentic vox 2 vox: The fast, or agonizingly slow, way.
<picture><img alt="THE VIEW FROM 30,000 FT" src="https://www.deepily.ai/images/view-from-30k-ft.svg"></picture>
_The green dotted lines and boxes are the quickest way through this flow chart (Deepily.ai Agents), the red dotted lines and boxes take anywhere 
from 100 to 200 times longer to execute (ChatGPT & LangChain)._

#### CURRENT FOCUS

I'm currently working on 
1. Agentic learning (code refactoring) based on previously solved problems stored in long-term memory
2. Using query-to-function mapping similar to what [ChatGPT](https://platform.openai.com/docs/guides/gpt/function-calling) is doing, 
and 
3. Providing human in the loop feedback when agents go awry

#### THE PRESENT REALITY

1. I can perform basic browsing tasks with Firefox using my voice
2. I can edit, spellcheck and proofread documents using my voice
3. I can also interact with PyCharm using my voice

#### THE (NEAR) FUTURE PLAN: EOY 2023

1. Interact seamlessly, asynchronously and in real time, with calendaring and TODO list apps using my voice
2. Do the same with a web research assistant to replace what I'm doing manually with ChatGPT
3. Have my agents speak to me with any of my favorite character voices in multiple languages
4. Host my own internal LLM server for privacy and security

#### THE (FAR) FUTURE DREAM: 2024

1. Interact with my agents, servers & computers using my voice, and have it do what I want it to do, when & how I want it done.  I'm not asking for much, am I? 
2. _Safely and securely, of course_
3. World peace, non X, and all that too

#### TECHNICAL ROADMAP & ARCHITECTURE

Lupin is built on a modern FastAPI architecture with WebSocket support for real-time communication. The project integrates with the COSA (Collection of Small Agents) framework to provide intelligent agent capabilities.

**Current Architecture:**
- **FastAPI-only server** running on port 7999 (Flask has been completely eliminated as of 2025.06.28)
- **WebSocket support** for real-time bidirectional communication
- **COSA integration** for modular agent framework
- **Notification system** for agent-to-user feedback

**Key Technical Documents:**
- **[WebSocket TTS Streaming Design](src/rnd/2025.06.03-websocket-tts-streaming-design.md)** - Architecture for real-time text-to-speech streaming
- **[Claude Code Notification System](src/rnd/2025.06.20-claude-code-notification-system-design.md)** - Design for real-time agent notifications
- **[FastAPI Queue Implementation](src/rnd/2025.06.17-fastapi-queue-implementation-plan.md)** - Queue-based request handling
- **[Lupin Renaming Plan](src/rnd/2025.06.28-lupin-renaming-plan.md)** - Project rebranding documentation

**Quick Start Commands:**
- Run FastAPI server: `src/scripts/run-fastapi-gib.sh`
- Run GUI client: `src/scripts/run-lupin-gui.sh`
- Run GSM8K benchmarks: `src/scripts/run-gsm8k.sh --help`

#### DISCLAIMER

This [Lupin project](https://www.linkedin.com/pulse/ai-virtual-prosthesis-how-i-created-genie-box-myself-r-p-ruiz) 
is currently an **_extremely_** large set of working sketches which I am actively organizing & tidying up so that I can collaborate with others.

So, I'm not there yet, _obviously_. But I'm working on it and getting closer every day.

Interested?

Begin!

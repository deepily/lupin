#!/usr/bin/env python3
"""
Cosa Task Dispatcher - Routes tasks to appropriate Claude Code runtime.

Supports two modes:
    Option A (BOUNDED): Print mode for discrete tasks with natural completion
    Option B (INTERACTIVE): SDK client for open-ended sessions with bidirectional control

Usage:
    from cosa_dispatcher import CosaDispatcher, Task, TaskType
    
    dispatcher = CosaDispatcher()
    
    # Bounded task
    result = await dispatcher.dispatch(Task(
        id="task-001",
        project="lupin", 
        prompt="Run tests and fix failures",
        type=TaskType.BOUNDED
    ))
    
    # Interactive session
    result = await dispatcher.dispatch(Task(
        id="session-001",
        project="lupin",
        prompt="Let's work on the auth refactor",
        type=TaskType.INTERACTIVE
    ))

Requirements:
    pip install claude-agent-sdk
    npm install -g @anthropic-ai/claude-code
"""

import asyncio
import subprocess
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Any
from datetime import datetime

# SDK imports - graceful fallback if not installed
try:
    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        TextBlock,
        ToolUseBlock,
        ToolResultBlock,
        ResultMessage
    )
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False
    print("Warning: claude-agent-sdk not installed. Interactive mode unavailable.", 
          file=__import__('sys').stderr)


class TaskType(Enum):
    """Task execution mode."""
    BOUNDED = "bounded"          # Option A: Print mode, runs to completion
    INTERACTIVE = "interactive"  # Option B: SDK client, bidirectional control


@dataclass
class Task:
    """Task definition for Claude Code execution."""
    id: str
    project: str
    prompt: str
    type: TaskType
    max_turns: int = 50
    timeout_seconds: int = 3600
    working_dir: str = "/home/projects"
    
    @property
    def sender_id(self) -> str:
        """Generate sender_id for session correlation."""
        return f"claude.code@{self.project.lower()}.deepily.ai"


@dataclass
class TaskResult:
    """Result from task execution."""
    task_id: str
    success: bool
    session_id: Optional[str] = None
    result: Optional[str] = None
    cost_usd: Optional[float] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    exit_code: Optional[int] = None


class CosaDispatcher:
    """
    Routes tasks to appropriate Claude Code runtime.
    
    Manages both bounded (print mode) and interactive (SDK client) sessions,
    with voice I/O via MCP server connecting to Lupin.
    """
    
    def __init__(
        self,
        mcp_config_path: str = "~/.claude/cosa_mcp.json",
        mcp_server_path: str = "/opt/cosa/mcp/cosa_voice_mcp.py",
        on_message: Optional[Callable[[str, Any], None]] = None
    ):
        """
        Initialize dispatcher.
        
        Args:
            mcp_config_path: Path to MCP configuration JSON
            mcp_server_path: Path to MCP server Python script
            on_message: Callback for streaming messages (interactive mode)
        """
        self.mcp_config_path = os.path.expanduser(mcp_config_path)
        self.mcp_server_path = mcp_server_path
        self.on_message = on_message or self._default_message_handler
        self.active_sessions: dict[str, Any] = {}  # task_id -> ClaudeSDKClient
    
    def _default_message_handler(self, task_id: str, message: Any) -> None:
        """Default handler that prints messages."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if hasattr(message, 'content'):
            for block in message.content:
                if hasattr(block, 'text'):
                    print(f"[{timestamp}] [{task_id}] {block.text[:100]}...")
                elif hasattr(block, 'name'):
                    print(f"[{timestamp}] [{task_id}] Tool: {block.name}")
        else:
            print(f"[{timestamp}] [{task_id}] {type(message).__name__}")
    
    async def dispatch(self, task: Task) -> TaskResult:
        """
        Dispatch task to appropriate runtime.
        
        Args:
            task: Task definition
            
        Returns:
            TaskResult with execution outcome
        """
        if task.type == TaskType.BOUNDED:
            return await self._run_bounded(task)
        elif task.type == TaskType.INTERACTIVE:
            if not SDK_AVAILABLE:
                return TaskResult(
                    task_id=task.id,
                    success=False,
                    error="claude-agent-sdk not installed. Run: pip install claude-agent-sdk"
                )
            return await self._run_interactive(task)
        else:
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"Unknown task type: {task.type}"
            )
    
    async def _run_bounded(self, task: Task) -> TaskResult:
        """
        Option A: Print mode for bounded tasks.
        
        Runs Claude Code with -p flag, waits for completion.
        Claude can use MCP tools to ask questions, but user cannot
        inject input unprompted.
        """
        env = os.environ.copy()
        env["COSA_PROJECT"] = task.project.lower()
        
        allowed_tools = ",".join([
            "mcp__cosa__converse",
            "mcp__cosa__notify",
            "mcp__cosa__ask_yes_no",
            "Read", "Write", "Bash"
        ])
        
        cmd = [
            "claude", "-p", task.prompt,
            "--mcp-config", self.mcp_config_path,
            "--allowedTools", allowed_tools,
            "--permission-mode", "acceptEdits",
            "--output-format", "json",
            "--max-turns", str(task.max_turns)
        ]
        
        try:
            result = subprocess.run(
                cmd,
                env=env,
                cwd=f"{task.working_dir}/{task.project}",
                capture_output=True,
                text=True,
                timeout=task.timeout_seconds
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return TaskResult(
                    task_id=task.id,
                    success=True,
                    session_id=data.get("session_id"),
                    result=data.get("result"),
                    cost_usd=data.get("total_cost_usd"),
                    duration_ms=data.get("duration_ms"),
                    exit_code=0
                )
            else:
                return TaskResult(
                    task_id=task.id,
                    success=False,
                    error=result.stderr or "Unknown error",
                    exit_code=result.returncode
                )
                
        except subprocess.TimeoutExpired:
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"Task timed out after {task.timeout_seconds}s",
                exit_code=-1
            )
        except json.JSONDecodeError as e:
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"Failed to parse output: {e}",
                exit_code=-1
            )
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                success=False,
                error=str(e),
                exit_code=-1
            )
    
    async def _run_interactive(self, task: Task) -> TaskResult:
        """
        Option B: SDK client for interactive sessions.
        
        Creates persistent session with bidirectional control.
        User can inject messages, interrupt, suspend, and resume.
        """
        options = ClaudeAgentOptions(
            cwd=f"{task.working_dir}/{task.project}",
            permission_mode="acceptEdits",
            allowed_tools=[
                "Read", "Write", "Bash",
                "mcp__cosa__converse",
                "mcp__cosa__notify",
                "mcp__cosa__ask_yes_no"
            ],
            mcp_servers={
                "cosa": {
                    "type": "stdio",
                    "command": "python",
                    "args": [self.mcp_server_path],
                    "env": {"COSA_PROJECT": task.project.lower()}
                }
            },
            system_prompt=f"""Session: {task.sender_id}

Voice tools available:
- converse(): Ask user and wait for voice response
- notify(): Announce status (fire-and-forget)  
- ask_yes_no(): Quick yes/no decisions

Use notify() for progress. Use converse() when you need input."""
        )
        
        try:
            async with ClaudeSDKClient(options=options) as client:
                self.active_sessions[task.id] = client
                
                await client.query(task.prompt)
                
                result_data = None
                async for message in client.receive_response():
                    # Stream to callback
                    self.on_message(task.id, message)
                    
                    # Capture final result
                    if isinstance(message, ResultMessage):
                        result_data = {
                            "session_id": message.session_id,
                            "result": message.result,
                            "cost_usd": message.total_cost_usd,
                            "duration_ms": message.duration_ms
                        }
                
                del self.active_sessions[task.id]
                
                if result_data:
                    return TaskResult(
                        task_id=task.id,
                        success=True,
                        **result_data
                    )
                else:
                    return TaskResult(
                        task_id=task.id,
                        success=False,
                        error="No result received"
                    )
                    
        except Exception as e:
            if task.id in self.active_sessions:
                del self.active_sessions[task.id]
            return TaskResult(
                task_id=task.id,
                success=False,
                error=str(e)
            )
    
    async def inject(self, task_id: str, message: str) -> bool:
        """
        Inject a message into an active interactive session.
        
        Only works for TaskType.INTERACTIVE sessions.
        
        Args:
            task_id: ID of active session
            message: Message to inject
            
        Returns:
            True if message was injected, False if session not found
        """
        client = self.active_sessions.get(task_id)
        if client:
            await client.query(message)
            return True
        return False
    
    async def interrupt(self, task_id: str) -> bool:
        """
        Interrupt an active interactive session.
        
        Session can be resumed later with inject().
        
        Args:
            task_id: ID of active session
            
        Returns:
            True if session was interrupted, False if not found
        """
        client = self.active_sessions.get(task_id)
        if client:
            await client.interrupt()
            return True
        return False
    
    def get_active_sessions(self) -> list[str]:
        """Get list of active interactive session IDs."""
        return list(self.active_sessions.keys())


# ============================================================================
# CLI Interface
# ============================================================================

async def main():
    """Example usage of CosaDispatcher."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Cosa Task Dispatcher")
    parser.add_argument("prompt", help="Task prompt for Claude")
    parser.add_argument("--project", "-p", required=True, help="Project name")
    parser.add_argument("--type", "-t", choices=["bounded", "interactive"], 
                        default="bounded", help="Task type (default: bounded)")
    parser.add_argument("--max-turns", type=int, default=50,
                        help="Maximum turns (default: 50)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout in seconds (default: 3600)")
    parser.add_argument("--working-dir", default="/home/projects",
                        help="Working directory base")
    
    args = parser.parse_args()
    
    dispatcher = CosaDispatcher()
    
    task = Task(
        id=f"{args.project}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        project=args.project,
        prompt=args.prompt,
        type=TaskType(args.type),
        max_turns=args.max_turns,
        timeout_seconds=args.timeout,
        working_dir=args.working_dir
    )
    
    print(f"Dispatching {task.type.value} task: {task.id}")
    print(f"Sender ID: {task.sender_id}")
    print("-" * 60)
    
    result = await dispatcher.dispatch(task)
    
    print("-" * 60)
    if result.success:
        print(f"✓ Success")
        print(f"  Session: {result.session_id}")
        print(f"  Cost: ${result.cost_usd:.4f}" if result.cost_usd else "")
        print(f"  Duration: {result.duration_ms}ms" if result.duration_ms else "")
        if result.result:
            print(f"  Result: {result.result[:200]}...")
    else:
        print(f"✗ Failed: {result.error}")
        if result.exit_code is not None:
            print(f"  Exit code: {result.exit_code}")


if __name__ == "__main__":
    asyncio.run(main())

"""
Claude Code SDK integration subpackage.

This subpackage provides infrastructure for programmatically invoking Claude Code
with voice I/O capabilities via MCP tools.

Classes:
    ClaudeCodeDispatcher: Routes tasks to appropriate Claude Code runtime
    Task: Task definition dataclass
    TaskType: Enum for bounded vs interactive execution modes
    TaskResult: Result dataclass from task execution

Constants:
    SDK_AVAILABLE: Boolean indicating if claude-agent-sdk is installed

Example:
    from cosa.orchestration.claude_code import ClaudeCodeDispatcher, Task, TaskType

    dispatcher = ClaudeCodeDispatcher()
    result = await dispatcher.dispatch( Task(
        id="task-001",
        project="lupin",
        prompt="Run tests and fix failures",
        type=TaskType.BOUNDED
    ) )
"""

from cosa.orchestration.claude_code.dispatcher import (
    ClaudeCodeDispatcher,
    Task,
    TaskType,
    TaskResult,
    SessionInfo,
    SDK_AVAILABLE
)
from cosa.orchestration.claude_code.message_history import MessageHistory

__all__ = [
    "ClaudeCodeDispatcher",
    "Task",
    "TaskType",
    "TaskResult",
    "SessionInfo",
    "SDK_AVAILABLE",
    "MessageHistory"
]

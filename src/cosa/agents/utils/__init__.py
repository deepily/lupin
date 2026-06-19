#!/usr/bin/env python3
"""
COSA Agents Utilities Package.

Shared utilities for COSA agent implementations.

Modules:
    voice_io: Consolidated Voice-First I/O Layer for all COSA agents
    proxy_agents: Shared proxy agent infrastructure (WebSocket listener,
                  responder, strategy protocol, config, CLI helpers)
    sender_id: Shared project detection and sender_id construction
    feedback_analysis: Shared feedback intent analysis (approval/rejection)
"""

from . import voice_io
from . import proxy_agents
from . import sender_id
from . import feedback_analysis

__all__ = [ "voice_io", "proxy_agents", "sender_id", "feedback_analysis" ]

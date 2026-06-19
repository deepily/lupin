"""
Decision Proxy Agent — domain-agnostic trust framework (Layer 3).

Provides graduated-trust autonomous decision-making so agent teams can
operate during off-hours without requiring human approval for every decision.

Decisions are classified by category and risk level, then either acted on
autonomously (at earned trust levels), queued for ratification, or shadowed
for training data.

Modules:
    config: Trust thresholds, decay rates, circuit breaker params
    cosa_interface: Sender ID for decision proxy notifications
    voice_io: Status notifications (connected, deciding, errors)
    listener: WebSocket listener for decision events
    responder: Decision routing with trust-aware strategy chain
    base_decision_strategy: Abstract base for domain-specific strategies
    category_classifier: Abstract interface for category classification
    smart_router: Schedule checking and connectivity probing
    xml_models: Pydantic XML models for trust decision responses

Dependency Rule:
    This package imports from proxy_agents (shared infra) but NEVER
    from notification_proxy or swe_team.
"""

from cosa.agents.decision_proxy.config import (
    TRUST_LEVELS,
    DEFAULT_TRUST_MODE,
    TRUST_MODE_CHOICES,
)
from cosa.agents.decision_proxy.cosa_interface import SENDER_ID
from cosa.agents.decision_proxy.base_decision_strategy import BaseDecisionStrategy
from cosa.agents.decision_proxy.category_classifier import CategoryClassifier
from cosa.agents.decision_proxy.smart_router import SmartRouter

__all__ = [
    "TRUST_LEVELS",
    "DEFAULT_TRUST_MODE",
    "TRUST_MODE_CHOICES",
    "SENDER_ID",
    "BaseDecisionStrategy",
    "CategoryClassifier",
    "SmartRouter",
]

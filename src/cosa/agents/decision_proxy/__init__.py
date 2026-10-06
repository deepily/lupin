"""
Decision Proxy Agent — domain-agnostic trust framework (Layer 3).

Provides graduated-trust autonomous decision-making so agent teams can
operate during off-hours without requiring human approval for every decision.

Decisions are classified by category and risk level, then either acted on
autonomously (at earned trust levels), queued for ratification, or shadowed
for training data.

Modules:
    The config module holds trust thresholds, decay rates and circuit breaker params.
    The cosa_interface module holds the sender ID for decision proxy notifications.
    The voice_io module sends status notifications (connected, deciding, errors).
    The listener module is the WebSocket listener for decision events.
    The responder module routes decisions with a trust-aware strategy chain.
    The base_decision_strategy module is the abstract base for domain-specific strategies.
    The category_classifier module is the abstract interface for category classification.
    The smart_router module checks schedules and probes connectivity.
    The xml_models module holds Pydantic XML models for trust decision responses.

Dependency Rule:
    This package imports from proxy_agents (shared infra) but never
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

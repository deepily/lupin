"""
SWE Engineering Proxy — Domain-specific decision proxy for SWE team operations.

This package provides:
    - Engineering categories (deployment, testing, deps, architecture, destructive, general)
    - Engineering classifier (sender-aware keyword classification)
    - Engineering strategy (full classify → gate → decide pipeline)

Imports from:
    - decision_proxy (Layer 3: base classes, trust tracker, circuit breaker)
    - proxy_agents (Layer 1: shared infra)

NEVER imports from:
    - notification_proxy (Layer 2)
"""

from cosa.agents.swe_team.proxy.engineering_categories import (
    ENGINEERING_CATEGORIES,
    get_category_names,
    get_category_cap_level,
)
from cosa.agents.swe_team.proxy.engineering_classifier import EngineeringClassifier
from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy
from cosa.agents.swe_team.proxy.config import (
    DEFAULT_ACCEPTED_SENDERS,
    DEFAULT_DEPLOYMENT_CAP_LEVEL,
    DEFAULT_DESTRUCTIVE_CAP_LEVEL,
    DEFAULT_ARCHITECTURE_CAP_LEVEL,
)

__all__ = [
    "ENGINEERING_CATEGORIES",
    "get_category_names",
    "get_category_cap_level",
    "EngineeringClassifier",
    "EngineeringStrategy",
    "DEFAULT_ACCEPTED_SENDERS",
    "DEFAULT_DEPLOYMENT_CAP_LEVEL",
    "DEFAULT_DESTRUCTIVE_CAP_LEVEL",
    "DEFAULT_ARCHITECTURE_CAP_LEVEL",
]

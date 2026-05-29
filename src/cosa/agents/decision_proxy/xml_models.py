#!/usr/bin/env python3
"""
Pydantic XML models for the Decision Proxy Agent.

Models for trust decision responses, classification results, and
ratification records.

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import datetime


class ClassificationResult( BaseModel ):
    """Result of classifying a decision question into a category."""

    category   : str   = Field( description="Decision category name" )
    confidence : float = Field( ge=0.0, le=1.0, description="Classification confidence" )
    method     : str   = Field( default="keyword", description="Classification method (keyword, llm, hybrid)" )


class TrustDecision( BaseModel ):
    """A single trust-gated decision record."""

    notification_id : str                 = Field( description="Original notification UUID" )
    domain          : str                 = Field( default="swe", description="Domain (swe, devops, etc.)" )
    category        : str                 = Field( description="Decision category" )
    question        : str                 = Field( description="Original question text" )
    sender_id       : str                 = Field( default="", description="Requesting agent sender ID" )
    action          : str                 = Field( description="Action taken: shadow, suggest, act, defer" )
    decision_value  : Optional[str]       = Field( default=None, description="Decision value if acted" )
    confidence      : float               = Field( ge=0.0, le=1.0, description="Classification confidence" )
    trust_level     : int                 = Field( ge=1, le=5, description="Trust level at decision time" )
    reason          : str                 = Field( default="", description="Human-readable reason" )
    timestamp       : Optional[datetime]  = Field( default=None, description="Decision timestamp" )

    model_config = ConfigDict( json_schema_extra={
        "example": {
            "notification_id" : "abc123",
            "domain"          : "swe",
            "category"        : "testing",
            "question"        : "Should I run the full test suite?",
            "sender_id"       : "swe.coder@lupin.deepily.ai",
            "action"          : "shadow",
            "decision_value"  : None,
            "confidence"      : 0.85,
            "trust_level"     : 1,
            "reason"          : "L1 shadow mode — log only",
            "timestamp"       : "2026-02-14T10:30:00"
        }
    } )


class RatificationRequest( BaseModel ):
    """Request to ratify (approve/reject) a queued decision."""

    decision_id : str  = Field( description="UUID of the decision to ratify" )
    approved    : bool = Field( description="True to approve, False to reject" )
    feedback    : str  = Field( default="", description="Optional user feedback" )


class DecisionSummary( BaseModel ):
    """Summary of pending decisions for ratification UI."""

    total_pending   : int = Field( default=0 )
    by_category     : dict = Field( default_factory=dict, description="Count by category" )
    by_trust_level  : dict = Field( default_factory=dict, description="Count by trust level" )
    oldest_pending  : Optional[datetime] = Field( default=None )

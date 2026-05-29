"""
Middleware components for FastAPI authentication and authorization.
"""

from cosa.rest.middleware.api_key_auth import require_api_key, validate_api_key

__all__ = ['require_api_key', 'validate_api_key']

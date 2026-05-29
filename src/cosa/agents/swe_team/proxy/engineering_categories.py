#!/usr/bin/env python3
"""
SWE engineering decision categories with keyword patterns.

Defines the 6 engineering categories recognized by the SWE decision proxy:
    - deployment: Production deployments, releases, rollbacks
    - testing: Test execution, coverage, test infrastructure
    - deps: Dependency management, package updates, version changes
    - architecture: Design decisions, refactoring, API changes
    - destructive: File deletion, data loss, irreversible operations
    - general: Everything else (catch-all)

Each category defines:
    - keywords: Terms that trigger classification into this category
    - cap_level: Maximum trust level (1-5) for the category
    - description: Human-readable description

Dependency Rule:
    This module NEVER imports from notification_proxy or decision_proxy.
"""

from cosa.agents.swe_team.proxy.config import (
    DEFAULT_DEPLOYMENT_CAP_LEVEL,
    DEFAULT_DESTRUCTIVE_CAP_LEVEL,
    DEFAULT_ARCHITECTURE_CAP_LEVEL,
    DEFAULT_TESTING_CAP_LEVEL,
    DEFAULT_DEPS_CAP_LEVEL,
    DEFAULT_GENERAL_CAP_LEVEL,
)


# ============================================================================
# Engineering Categories
# ============================================================================

ENGINEERING_CATEGORIES = {
    "deployment" : {
        "keywords"    : [
            "deploy", "deployment", "release", "rollback", "production",
            "staging", "docker", "container", "kubernetes", "k8s",
            "push to prod", "ship", "publish", "cd pipeline",
        ],
        "cap_level"   : DEFAULT_DEPLOYMENT_CAP_LEVEL,
        "description" : "Production deployments, releases, and rollbacks",
    },
    "testing" : {
        "keywords"    : [
            "test", "tests", "testing", "pytest", "unittest", "coverage",
            "smoke test", "regression", "integration test", "unit test",
            "test suite", "test runner", "assert", "fixture", "mock",
        ],
        "cap_level"   : DEFAULT_TESTING_CAP_LEVEL,
        "description" : "Test execution, coverage analysis, and test infrastructure",
    },
    "deps" : {
        "keywords"    : [
            "dependency", "dependencies", "package", "pip install", "npm install",
            "requirements", "pip", "npm", "yarn", "poetry", "version",
            "upgrade", "downgrade", "lock file", "requirements.txt",
        ],
        "cap_level"   : DEFAULT_DEPS_CAP_LEVEL,
        "description" : "Dependency management, package updates, and version changes",
    },
    "architecture" : {
        "keywords"    : [
            "architect", "architecture", "design", "refactor", "restructure",
            "api change", "schema", "interface", "pattern", "migration",
            "breaking change", "database schema", "api design", "endpoint",
        ],
        "cap_level"   : DEFAULT_ARCHITECTURE_CAP_LEVEL,
        "description" : "Design decisions, refactoring, and API changes",
    },
    "destructive" : {
        "keywords"    : [
            "delete", "remove", "drop", "truncate", "destroy",
            "rm -rf", "git reset --hard", "force push", "overwrite",
            "irreversible", "purge", "wipe", "clean", "nuke",
        ],
        "cap_level"   : DEFAULT_DESTRUCTIVE_CAP_LEVEL,
        "description" : "File deletion, data loss, and irreversible operations",
    },
    "general" : {
        "keywords"    : [],  # Catch-all — no keywords, everything else
        "cap_level"   : DEFAULT_GENERAL_CAP_LEVEL,
        "description" : "General engineering decisions not matching specific categories",
    },
}


def get_category_names():
    """
    Return list of all category names.

    Ensures:
        - Returns list of strings matching ENGINEERING_CATEGORIES keys

    Returns:
        List of category name strings
    """
    return list( ENGINEERING_CATEGORIES.keys() )


def get_category_cap_level( category_name ):
    """
    Get the trust cap level for a category.

    Requires:
        - category_name is a string

    Ensures:
        - Returns cap_level (1-5) for the category
        - Returns 5 if category not found (no cap)

    Args:
        category_name: Category name

    Returns:
        int: Cap level (1-5)
    """
    cat = ENGINEERING_CATEGORIES.get( category_name )
    if cat is None:
        return 5
    return cat[ "cap_level" ]

#!/usr/bin/env python3
"""
SWE Team workload catalog — 18 small, well-defined engineering tasks.

Each task is designed to exercise the full SWE team pipeline:
    voice command → expeditor → queue → orchestrator → proxy decisions

Tasks span all 6 engineering proxy categories (deployment, testing, deps,
architecture, destructive, general) with 3 tasks per category. Each entry
includes the expected classification and proxy action so the capture harness
can validate correctness.

Usage:
    from scripts.swe_workload_catalog import WORKLOAD_CATALOG, get_tasks_by_category

    for task in WORKLOAD_CATALOG:
        print( task[ "id" ], task[ "category" ], task[ "task" ] )

Session 268: Work Item 2, Step 2.1.
"""

# ---------------------------------------------------------------------------
# Catalog Schema
# ---------------------------------------------------------------------------
# id                   : Unique task identifier (wl-{category_abbrev}-{nnn})
# task                 : Engineering task description (submitted to SWE team)
# category             : Expected proxy classification category
# expected_proxy_action: Expected proxy action (suggest, act, defer, shadow)
# description          : Human explanation of what the task exercises
# keywords             : Keywords the classifier should match on
# risk_level           : low, medium, high — indicates blast radius
# ---------------------------------------------------------------------------

WORKLOAD_CATALOG = [

    # =========================================================================
    # DEPLOYMENT (3 tasks)
    # =========================================================================
    {
        "id"                    : "wl-deploy-001",
        "task"                  : "Deploy the updated health check endpoint to the staging environment",
        "category"              : "deployment",
        "expected_proxy_action" : "suggest",
        "description"           : "Staging deploy — moderate risk, should trigger proxy review",
        "keywords"              : [ "deploy", "staging" ],
        "risk_level"            : "medium",
    },
    {
        "id"                    : "wl-deploy-002",
        "task"                  : "Roll back the last production release to the previous version",
        "category"              : "deployment",
        "expected_proxy_action" : "suggest",
        "description"           : "Production rollback — high risk, proxy should always flag",
        "keywords"              : [ "rollback", "production" ],
        "risk_level"            : "high",
    },
    {
        "id"                    : "wl-deploy-003",
        "task"                  : "Publish the new Docker container image to the staging registry",
        "category"              : "deployment",
        "expected_proxy_action" : "suggest",
        "description"           : "Container publish — moderate risk deployment operation",
        "keywords"              : [ "docker", "container", "publish" ],
        "risk_level"            : "medium",
    },

    # =========================================================================
    # TESTING (3 tasks)
    # =========================================================================
    {
        "id"                    : "wl-test-001",
        "task"                  : "Run the full pytest test suite and report failures",
        "category"              : "testing",
        "expected_proxy_action" : "suggest",
        "description"           : "Standard test execution — low risk, exercises testing classifier",
        "keywords"              : [ "pytest", "test suite" ],
        "risk_level"            : "low",
    },
    {
        "id"                    : "wl-test-002",
        "task"                  : "Add unit tests for the new authentication middleware",
        "category"              : "testing",
        "expected_proxy_action" : "suggest",
        "description"           : "Test creation task — low risk, should classify as testing",
        "keywords"              : [ "unit test", "test" ],
        "risk_level"            : "low",
    },
    {
        "id"                    : "wl-test-003",
        "task"                  : "Run integration tests with coverage report for the queue module",
        "category"              : "testing",
        "expected_proxy_action" : "suggest",
        "description"           : "Integration test + coverage — exercises test classification",
        "keywords"              : [ "integration test", "coverage" ],
        "risk_level"            : "low",
    },

    # =========================================================================
    # DEPS (3 tasks)
    # =========================================================================
    {
        "id"                    : "wl-deps-001",
        "task"                  : "Upgrade the requests package to the latest version",
        "category"              : "deps",
        "expected_proxy_action" : "suggest",
        "description"           : "Package upgrade — standard dependency management",
        "keywords"              : [ "upgrade", "package" ],
        "risk_level"            : "low",
    },
    {
        "id"                    : "wl-deps-002",
        "task"                  : "Add pydantic-settings as a new dependency to requirements.txt",
        "category"              : "deps",
        "expected_proxy_action" : "suggest",
        "description"           : "New dependency addition — exercises deps classifier",
        "keywords"              : [ "dependency", "requirements" ],
        "risk_level"            : "low",
    },
    {
        "id"                    : "wl-deps-003",
        "task"                  : "Downgrade numpy to version 1.26 due to compatibility issues",
        "category"              : "deps",
        "expected_proxy_action" : "suggest",
        "description"           : "Dependency downgrade — higher risk, should flag for review",
        "keywords"              : [ "downgrade", "version" ],
        "risk_level"            : "medium",
    },

    # =========================================================================
    # ARCHITECTURE (3 tasks)
    # =========================================================================
    {
        "id"                    : "wl-arch-001",
        "task"                  : "Refactor the notification system to use the observer design pattern",
        "category"              : "architecture",
        "expected_proxy_action" : "suggest",
        "description"           : "Design pattern refactor — architectural decision needs review",
        "keywords"              : [ "refactor", "design", "pattern" ],
        "risk_level"            : "medium",
    },
    {
        "id"                    : "wl-arch-002",
        "task"                  : "Add a new REST API endpoint for user preferences",
        "category"              : "architecture",
        "expected_proxy_action" : "suggest",
        "description"           : "New API endpoint — additive architecture change",
        "keywords"              : [ "api", "endpoint" ],
        "risk_level"            : "medium",
    },
    {
        "id"                    : "wl-arch-003",
        "task"                  : "Migrate the database schema to add a sessions table for tracking",
        "category"              : "architecture",
        "expected_proxy_action" : "suggest",
        "description"           : "Schema migration — moderate risk architectural change",
        "keywords"              : [ "schema", "migration" ],
        "risk_level"            : "medium",
    },

    # =========================================================================
    # DESTRUCTIVE (3 tasks)
    # =========================================================================
    {
        "id"                    : "wl-destr-001",
        "task"                  : "Delete expired session tokens older than 30 days from the database",
        "category"              : "destructive",
        "expected_proxy_action" : "suggest",
        "description"           : "Safe cleanup — bounded deletion with age filter",
        "keywords"              : [ "delete" ],
        "risk_level"            : "medium",
    },
    {
        "id"                    : "wl-destr-002",
        "task"                  : "Remove all temporary build artifacts from the CI cache directory",
        "category"              : "destructive",
        "expected_proxy_action" : "suggest",
        "description"           : "Cache cleanup — destructive but low-risk",
        "keywords"              : [ "remove", "clean" ],
        "risk_level"            : "medium",
    },
    {
        "id"                    : "wl-destr-003",
        "task"                  : "Truncate the debug_logs table to reclaim disk space",
        "category"              : "destructive",
        "expected_proxy_action" : "suggest",
        "description"           : "Table truncation — high risk, should trigger proxy review",
        "keywords"              : [ "truncate" ],
        "risk_level"            : "high",
    },

    # =========================================================================
    # GENERAL (3 tasks)
    # =========================================================================
    {
        "id"                    : "wl-gen-001",
        "task"                  : "Add a health check endpoint that returns server status",
        "category"              : "general",
        "expected_proxy_action" : "suggest",
        "description"           : "Generic coding task — no strong keyword matches for specific categories",
        "keywords"              : [],
        "risk_level"            : "low",
    },
    {
        "id"                    : "wl-gen-002",
        "task"                  : "Fix the off-by-one error in the pagination logic",
        "category"              : "general",
        "expected_proxy_action" : "suggest",
        "description"           : "Bug fix — generic task, no category-specific keywords",
        "keywords"              : [],
        "risk_level"            : "low",
    },
    {
        "id"                    : "wl-gen-003",
        "task"                  : "Implement rate limiting for the public API routes",
        "category"              : "general",
        "expected_proxy_action" : "suggest",
        "description"           : "Feature implementation — might classify as architecture or general",
        "keywords"              : [ "api" ],
        "risk_level"            : "low",
    },
]


def get_tasks_by_category( category=None ):
    """
    Filter catalog by category.

    Requires:
        - category is None (all) or a valid category string

    Ensures:
        - Returns list of task dicts matching the category
        - Returns all tasks if category is None

    Args:
        category: Optional category filter

    Returns:
        list[dict]: Matching tasks
    """
    if category is None:
        return list( WORKLOAD_CATALOG )
    return [ t for t in WORKLOAD_CATALOG if t[ "category" ] == category ]


def get_categories():
    """
    Get all unique categories in the catalog.

    Returns:
        list[str]: Sorted unique category names
    """
    return sorted( set( t[ "category" ] for t in WORKLOAD_CATALOG ) )


def print_catalog_summary():
    """Print a formatted summary table of the workload catalog."""
    print( f"\nSWE Workload Catalog: {len( WORKLOAD_CATALOG )} tasks\n" )
    print( f"{'ID':<20} {'Category':<15} {'Risk':<8} {'Task':<60}" )
    print( "-" * 105 )
    for task in WORKLOAD_CATALOG:
        truncated = task[ "task" ][ :58 ] + ".." if len( task[ "task" ] ) > 60 else task[ "task" ]
        print( f"{task[ 'id' ]:<20} {task[ 'category' ]:<15} {task[ 'risk_level' ]:<8} {truncated:<60}" )

    print( f"\nBy category:" )
    for cat in get_categories():
        count = len( get_tasks_by_category( cat ) )
        print( f"  {cat:<15}: {count} tasks" )


if __name__ == "__main__":
    print_catalog_summary()

#!/usr/bin/env python3
"""
Seed proxy decisions for preference learning bootstrap (Phases 0-1).

Populates PostgreSQL (proxy_decisions table) and LanceDB (proxy_decisions vector
store) with 50 realistic decision scenarios across all 6 engineering categories,
then optionally batch-ratifies them to create training signal for the CBR engine.

Usage:
    python src/scripts/seed_proxy_decisions.py --dry-run
    python src/scripts/seed_proxy_decisions.py
    python src/scripts/seed_proxy_decisions.py --ratify --user-email you@example.com
    python src/scripts/seed_proxy_decisions.py --verify
    python src/scripts/seed_proxy_decisions.py --clean

Requires:
    - LUPIN_ROOT environment variable set
    - LUPIN_CONFIG_MGR_CLI_ARGS environment variable set
    - PostgreSQL running with proxy_decisions table
    - LanceDB database directory accessible

Ensures:
    - --dry-run prints scenario catalog with no side effects
    - Default mode inserts 50 decisions into PG + LanceDB
    - --ratify applies suggested approve/reject to all seed decisions
    - --verify confirms CBR predictions return non-None verdicts
    - --clean removes all seed data (metadata_json.seed_data == True)
"""

import sys
import os
import argparse
from uuid import uuid4
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Bootstrap: LUPIN_ROOT → sys.path
# ---------------------------------------------------------------------------
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running:\n"
        "  export LUPIN_ROOT=/path/to/project\n"
        "  python src/scripts/seed_proxy_decisions.py"
    )

src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

# ---------------------------------------------------------------------------
# Imports (now that cosa is importable)
# ---------------------------------------------------------------------------
import cosa.utils.util as cu
from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.db.database import get_db
from cosa.rest.db.repositories.proxy_decision_repository import ProxyDecisionRepository
from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings
from cosa.agents.decision_proxy.cbr_decision_store import CBRDecisionStore
from cosa.memory.embedding_provider import get_embedding_provider

# ---------------------------------------------------------------------------
# Scenario Catalog — 50 scenarios across 6 categories
# ---------------------------------------------------------------------------

SCENARIO_CATALOG = [
    # =========================================================================
    # DEPLOYMENT (9): cap L3 — mostly requires human review
    # =========================================================================
    # --- Semantic group: prod-deploy ---
    {
        "id"                     : "seed-deploy-001",
        "question"               : "Should I deploy the auth service hotfix to production?",
        "category"               : "deployment",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "approve",
        "rationale"              : "Hotfix for critical auth bug — correct to flag for review, approve the decision to deploy",
        "semantic_group"         : "prod-deploy",
    },
    {
        "id"                     : "seed-deploy-002",
        "question"               : "Should I push the authentication hotfix release to the production environment?",
        "category"               : "deployment",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "approve",
        "rationale"              : "Semantically similar to deploy-001 — same intent, different phrasing",
        "semantic_group"         : "prod-deploy",
    },
    # --- Semantic group: staging-deploy ---
    {
        "id"                     : "seed-deploy-003",
        "question"               : "Can I deploy the new search feature to the staging environment for QA testing?",
        "category"               : "deployment",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "approve",
        "rationale"              : "Staging deploy is low-risk — safe to approve",
        "semantic_group"         : "staging-deploy",
    },
    # --- Reject: risky rollbacks and broad blast radius ---
    {
        "id"                     : "seed-deploy-004",
        "question"               : "Should I rollback the production database migration from yesterday?",
        "category"               : "deployment",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "DB rollback is high-risk destructive — needs manual oversight",
        "semantic_group"         : "risky-rollback",
    },
    {
        "id"                     : "seed-deploy-005",
        "question"               : "Should I trigger the CD pipeline to release all microservices to production simultaneously?",
        "category"               : "deployment",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Broad blast radius — deploying all services at once is too risky",
        "semantic_group"         : "broad-release",
    },
    {
        "id"                     : "seed-deploy-006",
        "question"               : "Can I deploy the unreviewed feature branch directly to production to meet the deadline?",
        "category"               : "deployment",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Skipping review for production deploy violates safety protocols",
        "semantic_group"         : "risky-deploy",
    },
    {
        "id"                     : "seed-deploy-007",
        "question"               : "Should I ship the new container image with the experimental GPU driver to production?",
        "category"               : "deployment",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Experimental driver in prod is high-risk — reject until validated",
        "semantic_group"         : "risky-deploy",
    },
    {
        "id"                     : "seed-deploy-008",
        "question"               : "Can I rollback the staging environment to last week's release for debugging?",
        "category"               : "deployment",
        "sender_id"              : "swe.tester@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Staging rollback is moderate risk — affects shared test environment",
        "semantic_group"         : "risky-rollback",
    },
    {
        "id"                     : "seed-deploy-009",
        "question"               : "Should I publish the updated kubernetes manifests to the production cluster?",
        "category"               : "deployment",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "K8s manifest changes in prod need careful review",
        "semantic_group"         : "k8s-deploy",
    },

    # =========================================================================
    # TESTING (9): cap L5 — mostly safe to auto-approve
    # =========================================================================
    # --- Semantic group: run-test-suite ---
    {
        "id"                     : "seed-test-001",
        "question"               : "Should I run the full pytest regression suite before merging this PR?",
        "category"               : "testing",
        "sender_id"              : "swe.tester@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Running test suite is always safe — approve",
        "semantic_group"         : "run-test-suite",
    },
    {
        "id"                     : "seed-test-002",
        "question"               : "Should I execute the complete test suite as a pre-merge gate?",
        "category"               : "testing",
        "sender_id"              : "swe.tester@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Semantically similar to test-001 — same intent, different phrasing",
        "semantic_group"         : "run-test-suite",
    },
    # --- Approve: safe testing activities ---
    {
        "id"                     : "seed-test-003",
        "question"               : "Can I add unit tests for the new user registration endpoint?",
        "category"               : "testing",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Adding unit tests is always beneficial — approve",
        "semantic_group"         : "add-tests",
    },
    {
        "id"                     : "seed-test-004",
        "question"               : "Should I update the test fixtures to match the new API response format?",
        "category"               : "testing",
        "sender_id"              : "swe.tester@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Updating fixtures is necessary maintenance — approve",
        "semantic_group"         : "update-fixtures",
    },
    {
        "id"                     : "seed-test-005",
        "question"               : "Can I run the integration tests against the staging database?",
        "category"               : "testing",
        "sender_id"              : "swe.tester@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Integration tests against staging are standard practice — approve",
        "semantic_group"         : "run-test-suite",
    },
    {
        "id"                     : "seed-test-006",
        "question"               : "Should I add smoke tests for the WebSocket notification endpoints?",
        "category"               : "testing",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Adding smoke tests improves coverage — approve",
        "semantic_group"         : "add-tests",
    },
    {
        "id"                     : "seed-test-007",
        "question"               : "Can I increase the test coverage threshold from 80% to 85% in CI config?",
        "category"               : "testing",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Higher coverage threshold is a positive change — approve",
        "semantic_group"         : "test-config",
    },
    # --- Reject: unsafe testing shortcuts ---
    {
        "id"                     : "seed-test-008",
        "question"               : "Should I skip the test suite to speed up the CI pipeline for this urgent fix?",
        "category"               : "testing",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Skipping tests is dangerous even for urgent fixes — reject",
        "semantic_group"         : "skip-tests",
    },
    {
        "id"                     : "seed-test-009",
        "question"               : "Can I remove the flaky integration tests that keep failing intermittently?",
        "category"               : "testing",
        "sender_id"              : "swe.tester@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Removing tests reduces coverage — fix flaky tests instead",
        "semantic_group"         : "remove-tests",
    },

    # =========================================================================
    # DEPS (8): Low-risk but risky upgrades exist
    # =========================================================================
    # --- Semantic group: patch-upgrade ---
    {
        "id"                     : "seed-deps-001",
        "question"               : "Should I upgrade the requests package from 2.31.0 to 2.31.1 (patch)?",
        "category"               : "deps",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Patch version upgrade is low-risk — approve",
        "semantic_group"         : "patch-upgrade",
    },
    {
        "id"                     : "seed-deps-002",
        "question"               : "Can I apply the patch-level security update to the cryptography dependency?",
        "category"               : "deps",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Security patch is both safe and urgent — approve",
        "semantic_group"         : "patch-upgrade",
    },
    # --- Approve: safe dep operations ---
    {
        "id"                     : "seed-deps-003",
        "question"               : "Should I pin the numpy version in requirements.txt to 1.26.4?",
        "category"               : "deps",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Pinning versions improves reproducibility — approve",
        "semantic_group"         : "pin-version",
    },
    {
        "id"                     : "seed-deps-004",
        "question"               : "Can I add the new python-dateutil package as a dependency for timezone handling?",
        "category"               : "deps",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Well-known stable package for a clear need — approve",
        "semantic_group"         : "add-dep",
    },
    {
        "id"                     : "seed-deps-005",
        "question"               : "Should I update the lock file after the minor dependency changes?",
        "category"               : "deps",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Lock file refresh after changes is standard — approve",
        "semantic_group"         : "lock-file",
    },
    # --- Reject: risky dep changes ---
    {
        "id"                     : "seed-deps-006",
        "question"               : "Should I upgrade SQLAlchemy from 1.4 to 2.0 (major version jump)?",
        "category"               : "deps",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Major version jump has breaking changes — needs migration plan",
        "semantic_group"         : "major-upgrade",
    },
    {
        "id"                     : "seed-deps-007",
        "question"               : "Can I remove the deprecated pandas package since we might not need it?",
        "category"               : "deps",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Removing a package without confirmed unused status is risky",
        "semantic_group"         : "remove-dep",
    },
    {
        "id"                     : "seed-deps-008",
        "question"               : "Should I downgrade the pytorch version to fix the GPU compatibility issue?",
        "category"               : "deps",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Downgrading a core ML dependency needs careful evaluation",
        "semantic_group"         : "downgrade",
    },

    # =========================================================================
    # ARCHITECTURE (9): cap L3 — design decisions need oversight
    # =========================================================================
    # --- Semantic group: refactor ---
    {
        "id"                     : "seed-arch-001",
        "question"               : "Should I refactor the authentication module to use the strategy pattern?",
        "category"               : "architecture",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "approve",
        "rationale"              : "Well-known pattern for auth — refactor is reasonable",
        "semantic_group"         : "refactor",
    },
    {
        "id"                     : "seed-arch-002",
        "question"               : "Can I restructure the auth module using the strategy design pattern for cleaner extensibility?",
        "category"               : "architecture",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "approve",
        "rationale"              : "Semantically similar to arch-001 — same refactor intent",
        "semantic_group"         : "refactor",
    },
    # --- Approve: low-risk architecture ---
    {
        "id"                     : "seed-arch-003",
        "question"               : "Should I add a new column to the user_sessions schema for last_active_at tracking?",
        "category"               : "architecture",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "approve",
        "rationale"              : "Additive schema change with no breaking impact — approve",
        "semantic_group"         : "schema-addition",
    },
    # --- Reject: high-risk architecture ---
    {
        "id"                     : "seed-arch-004",
        "question"               : "Should I introduce a breaking change to the /api/v1/users endpoint response format?",
        "category"               : "architecture",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Breaking API change affects all consumers — needs versioning strategy",
        "semantic_group"         : "breaking-api",
    },
    {
        "id"                     : "seed-arch-005",
        "question"               : "Can I rewrite the entire notification system from scratch using a new event-driven architecture?",
        "category"               : "architecture",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Full rewrite is extremely high-risk — needs extensive planning",
        "semantic_group"         : "major-rewrite",
    },
    {
        "id"                     : "seed-arch-006",
        "question"               : "Should I split the monolith into three new microservices for auth, queue, and notifications?",
        "category"               : "architecture",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Microservice decomposition is a major architectural decision",
        "semantic_group"         : "microservice",
    },
    {
        "id"                     : "seed-arch-007",
        "question"               : "Can I change the database schema migration tool from Alembic to a custom solution?",
        "category"               : "architecture",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Replacing proven migration tooling with custom code is risky",
        "semantic_group"         : "tool-change",
    },
    {
        "id"                     : "seed-arch-008",
        "question"               : "Should I redesign the API to use GraphQL instead of REST for all new endpoints?",
        "category"               : "architecture",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Paradigm shift in API design needs team buy-in",
        "semantic_group"         : "api-paradigm",
    },
    {
        "id"                     : "seed-arch-009",
        "question"               : "Can I introduce a new caching layer between the API and the database for all read queries?",
        "category"               : "architecture",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Caching layer adds complexity and invalidation challenges",
        "semantic_group"         : "caching",
    },

    # =========================================================================
    # DESTRUCTIVE (9): Highest-risk — heavily reject
    # =========================================================================
    # --- Semantic group: safe-cleanup ---
    {
        "id"                     : "seed-destr-001",
        "question"               : "Should I delete expired JWT tokens older than 30 days from the token store?",
        "category"               : "destructive",
        "sender_id"              : "swe.tester@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "approve",
        "rationale"              : "Expired token cleanup is routine maintenance — safe to approve",
        "semantic_group"         : "safe-cleanup",
    },
    {
        "id"                     : "seed-destr-002",
        "question"               : "Can I purge old build artifacts from the CI cache that are over 90 days old?",
        "category"               : "destructive",
        "sender_id"              : "swe.tester@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "approve",
        "rationale"              : "Old build artifact cleanup with age filter is safe",
        "semantic_group"         : "safe-cleanup",
    },
    # --- Reject: dangerous destructive operations ---
    {
        "id"                     : "seed-destr-003",
        "question"               : "Should I drop the user_sessions table and recreate it with the new schema?",
        "category"               : "destructive",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "DROP TABLE is irreversible data loss — use ALTER TABLE instead",
        "semantic_group"         : "drop-table",
    },
    {
        "id"                     : "seed-destr-004",
        "question"               : "Can I force push to the main branch to fix the merge conflict?",
        "category"               : "destructive",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Force push to main overwrites shared history — never acceptable",
        "semantic_group"         : "force-push",
    },
    {
        "id"                     : "seed-destr-005",
        "question"               : "Should I delete all user-uploaded files in the /uploads directory to free disk space?",
        "category"               : "destructive",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Bulk deletion of user data is unrecoverable — reject",
        "semantic_group"         : "bulk-delete",
    },
    {
        "id"                     : "seed-destr-006",
        "question"               : "Can I run git reset --hard to discard all uncommitted changes in the working directory?",
        "category"               : "destructive",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Hard reset destroys uncommitted work — reject",
        "semantic_group"         : "git-destructive",
    },
    {
        "id"                     : "seed-destr-007",
        "question"               : "Should I truncate the audit_log table to improve query performance?",
        "category"               : "destructive",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Truncating audit logs destroys compliance data — reject",
        "semantic_group"         : "truncate-table",
    },
    {
        "id"                     : "seed-destr-008",
        "question"               : "Can I wipe the Redis cache to resolve the stale data issue?",
        "category"               : "destructive",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Cache wipe causes performance degradation for all users — reject",
        "semantic_group"         : "cache-wipe",
    },
    {
        "id"                     : "seed-destr-009",
        "question"               : "Should I rm -rf the temporary processing directory to clean up failed job artifacts?",
        "category"               : "destructive",
        "sender_id"              : "swe.tester@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "rm -rf without validation could delete active job data — reject",
        "semantic_group"         : "rm-rf",
    },

    # =========================================================================
    # GENERAL (6): Catch-all, mostly benign
    # =========================================================================
    {
        "id"                     : "seed-gen-001",
        "question"               : "Should I update the README with the new installation instructions?",
        "category"               : "general",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Documentation updates are always safe — approve",
        "semantic_group"         : "docs",
    },
    {
        "id"                     : "seed-gen-002",
        "question"               : "Can I add the .env.example file to .gitignore?",
        "category"               : "general",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Gitignore changes are routine — approve",
        "semantic_group"         : "gitignore",
    },
    {
        "id"                     : "seed-gen-003",
        "question"               : "Should I update the project changelog for the v0.1.5 release?",
        "category"               : "general",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Changelog maintenance is benign — approve",
        "semantic_group"         : "docs",
    },
    {
        "id"                     : "seed-gen-004",
        "question"               : "Can I rename the internal utility module from helpers.py to utils.py for consistency?",
        "category"               : "general",
        "sender_id"              : "swe.coder@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "File rename for consistency is low-risk — approve",
        "semantic_group"         : "rename",
    },
    {
        "id"                     : "seed-gen-005",
        "question"               : "Should I update the team's coding standards document with the new linting rules?",
        "category"               : "general",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "auto_approved",
        "suggested_ratification" : "approve",
        "rationale"              : "Standards documentation update is beneficial — approve",
        "semantic_group"         : "docs",
    },
    {
        "id"                     : "seed-gen-006",
        "question"               : "Should I schedule the database backup job to run at 2 AM instead of 4 AM?",
        "category"               : "general",
        "sender_id"              : "swe.lead@lupin.deepily.ai",
        "expected_decision"      : "requires_review",
        "suggested_ratification" : "reject",
        "rationale"              : "Schedule changes affect operations — needs team discussion",
        "semantic_group"         : "scheduling",
    },

    # =========================================================================
    # CROSS-CATEGORY EDGE CASES (embedded in their primary categories above)
    # These additional scenarios have keywords from multiple categories:
    # =========================================================================
    # Cross: destructive + testing
    # (Already covered: seed-test-009 "remove flaky integration tests" = testing + destructive keywords)
    # Cross: deployment + destructive
    # (Already covered: seed-deploy-004 "rollback production database" = deployment + destructive keywords)
    # Cross: deps + architecture
    # (Already covered: seed-deps-006 "upgrade SQLAlchemy 1.4 to 2.0" = deps + architecture keywords)
]


def _get_category_summary():
    """
    Compute category distribution from the scenario catalog.

    Ensures:
        - Returns dict: { category: { total, approve, reject } }
    """
    summary = {}
    for s in SCENARIO_CATALOG:
        cat = s[ "category" ]
        if cat not in summary:
            summary[ cat ] = { "total": 0, "approve": 0, "reject": 0 }
        summary[ cat ][ "total" ] += 1
        if s[ "suggested_ratification" ] == "approve":
            summary[ cat ][ "approve" ] += 1
        else:
            summary[ cat ][ "reject" ] += 1
    return summary


def _print_distribution_table():
    """Print a formatted category distribution table to stdout."""
    summary = _get_category_summary()

    print( "\n{:<15} {:>5} {:>8} {:>7}".format( "Category", "Total", "Approve", "Reject" ) )
    print( "-" * 40 )

    grand_total   = 0
    grand_approve = 0
    grand_reject  = 0

    for cat in [ "deployment", "testing", "deps", "architecture", "destructive", "general" ]:
        if cat in summary:
            s = summary[ cat ]
            print( "{:<15} {:>5} {:>8} {:>7}".format( cat, s[ "total" ], s[ "approve" ], s[ "reject" ] ) )
            grand_total   += s[ "total" ]
            grand_approve += s[ "approve" ]
            grand_reject  += s[ "reject" ]

    print( "-" * 40 )
    print( "{:<15} {:>5} {:>8} {:>7}".format( "TOTAL", grand_total, grand_approve, grand_reject ) )


def _get_embedding_store():
    """
    Create and return a ProxyDecisionEmbeddings instance using config.

    Ensures:
        - Returns configured ProxyDecisionEmbeddings instance
    """
    config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    db_path    = cu.get_project_root() + config_mgr.get( "solution snapshots lancedb path" )
    table_name = config_mgr.get( "swe team trust proxy lancedb table", default="proxy_decisions" )

    return ProxyDecisionEmbeddings(
        db_path    = db_path,
        table_name = table_name,
        debug      = True,
    )


# ---------------------------------------------------------------------------
# Core Operations
# ---------------------------------------------------------------------------

def seed_decisions( scenarios, dry_run=False, category_filter=None ):
    """
    Insert seed decisions into PostgreSQL and LanceDB.

    Requires:
        - scenarios is a non-empty list of scenario dicts
        - Database is accessible if dry_run is False

    Ensures:
        - Each scenario creates one ProxyDecision in PG + one vector in LanceDB
        - All records have metadata_json.seed_data = True for cleanup
        - Returns list of ( pg_uuid, scenario_id ) tuples

    Args:
        scenarios: List of scenario dicts from SCENARIO_CATALOG
        dry_run: If True, prints catalog without writing
        category_filter: Optional category name to filter scenarios

    Returns:
        list of ( str, str ) tuples: ( pg_decision_id, scenario_id )
    """
    # Filter by category if requested
    if category_filter:
        scenarios = [ s for s in scenarios if s[ "category" ] == category_filter ]
        if not scenarios:
            print( f"No scenarios found for category: {category_filter}" )
            return []

    if dry_run:
        print( f"\n[DRY RUN] Would seed {len( scenarios )} decisions:" )
        _print_distribution_table()

        print( "\nScenarios:" )
        for s in scenarios:
            print( f"  {s[ 'id' ]:<20} [{s[ 'category' ]:<13}] {s[ 'suggested_ratification' ]:<7}  {s[ 'question' ][:70]}" )
        return []

    # Initialize embedding provider
    provider = get_embedding_provider( debug=True )
    store    = _get_embedding_store()

    results = []
    now_iso = datetime.now( timezone.utc ).isoformat()

    with get_db() as session:
        repo = ProxyDecisionRepository( session )

        for i, scenario in enumerate( scenarios ):
            notification_id = str( uuid4() )

            # Step 1: Log decision in PostgreSQL
            decision = repo.log_decision(
                notification_id       = notification_id,
                domain                = "swe",
                category              = scenario[ "category" ],
                question              = scenario[ "question" ],
                action                = "suggest",
                decision_value        = scenario[ "expected_decision" ],
                sender_id             = scenario[ "sender_id" ],
                confidence            = 0.85,
                trust_level           = 2,
                reason                = f"Seed: {scenario[ 'rationale' ]}",
                requires_ratification = True,
                metadata_json         = {
                    "seed_data"       : True,
                    "seed_id"         : scenario[ "id" ],
                    "semantic_group"  : scenario[ "semantic_group" ],
                },
            )

            # Step 2: Generate embedding
            embedding = provider.generate_embedding( scenario[ "question" ], content_type="prose" )

            # Step 3: Store in LanceDB
            store.add_decision(
                id                 = str( decision.id ),
                question           = scenario[ "question" ],
                category           = scenario[ "category" ],
                decision_value     = scenario[ "expected_decision" ],
                ratification_state = "pending",
                question_embedding = embedding,
                created_at         = now_iso,
            )

            results.append( ( str( decision.id ), scenario[ "id" ] ) )
            print( f"  [{i + 1:>2}/{len( scenarios )}] {scenario[ 'id' ]:<20} → PG {decision.id}" )

    print( f"\nSeeded {len( results )} decisions into PostgreSQL + LanceDB" )
    _print_distribution_table()
    return results


def ratify_suggested( user_email ):
    """
    Batch-ratify all seed decisions using their suggested approve/reject values.

    Requires:
        - user_email is a non-empty string
        - Seed decisions exist in PostgreSQL with metadata_json.seed_data == True

    Ensures:
        - Each seed decision is ratified (approved or rejected) per its scenario
        - LanceDB ratification_state is updated to match
        - Returns summary dict: { approved: N, rejected: N }

    Args:
        user_email: Email of the ratifying user
    """
    store = _get_embedding_store()

    # Build a lookup from seed_id → suggested_ratification
    seed_lookup = { s[ "id" ]: s[ "suggested_ratification" ] for s in SCENARIO_CATALOG }

    approved_count = 0
    rejected_count = 0

    with get_db() as session:
        repo    = ProxyDecisionRepository( session )
        pending = repo.get_pending( domain="swe", limit=500 )

        seed_pending = [
            d for d in pending
            if d.metadata_json and d.metadata_json.get( "seed_data" ) is True
        ]

        if not seed_pending:
            print( "No seed decisions found pending ratification." )
            return { "approved": 0, "rejected": 0 }

        print( f"\nRatifying {len( seed_pending )} seed decisions..." )

        for i, decision in enumerate( seed_pending ):
            seed_id    = decision.metadata_json.get( "seed_id", "" )
            suggested  = seed_lookup.get( seed_id, "approve" )
            is_approve = ( suggested == "approve" )

            # Step 1: Ratify in PostgreSQL
            repo.ratify(
                decision_id = decision.id,
                approved    = is_approve,
                ratified_by = user_email,
                feedback    = f"Seed ratification: {suggested}",
            )

            # Step 2: Update LanceDB
            new_state = "approved" if is_approve else "rejected"
            store.update_ratification_state( str( decision.id ), new_state )

            if is_approve:
                approved_count += 1
            else:
                rejected_count += 1

            label = "APPROVE" if is_approve else "REJECT "
            print( f"  [{i + 1:>2}/{len( seed_pending )}] {seed_id:<20} → {label}" )

    print( f"\nRatification complete: {approved_count} approved, {rejected_count} rejected" )
    return { "approved": approved_count, "rejected": rejected_count }


def verify():
    """
    Verify seed data is functioning correctly.

    Ensures:
        - Counts PG decisions (pending + ratified)
        - Tests LanceDB similarity search with a known query
        - Tests CBR prediction returns non-None verdict (if ratified data exists)
        - Prints verification results
    """
    store    = _get_embedding_store()
    provider = get_embedding_provider( debug=True )

    print( "\n=== Seed Data Verification ===" )

    # Check 1: PostgreSQL counts
    print( "\n--- PostgreSQL ---" )
    with get_db() as session:
        repo         = ProxyDecisionRepository( session )
        all_pending  = repo.get_pending( domain="swe", limit=500 )
        seed_pending = [ d for d in all_pending if d.metadata_json and d.metadata_json.get( "seed_data" ) is True ]

        # Count ratified seed decisions
        all_decisions = session.query(
            __import__( "cosa.rest.postgres_models", fromlist=[ "ProxyDecision" ] ).ProxyDecision
        ).filter(
            __import__( "cosa.rest.postgres_models", fromlist=[ "ProxyDecision" ] ).ProxyDecision.domain == "swe"
        ).all()

        seed_ratified = [
            d for d in all_decisions
            if d.metadata_json and d.metadata_json.get( "seed_data" ) is True
            and d.ratification_state in ( "approved", "rejected" )
        ]

        print( f"  Seed pending:  {len( seed_pending )}" )
        print( f"  Seed ratified: {len( seed_ratified )}" )
        print( f"  Total seed:    {len( seed_pending ) + len( seed_ratified )}" )

    # Check 2: LanceDB similarity search
    print( "\n--- LanceDB Similarity Search ---" )
    test_query   = "Should I run the pytest suite?"
    test_embed   = provider.generate_embedding( test_query, content_type="prose" )
    similar      = store.find_similar( test_embed, category="testing", limit=3, threshold=0.0 )

    if similar:
        print( f"  Query: '{test_query}'" )
        print( f"  Results: {len( similar )} matches" )
        for sim_pct, record in similar:
            print( f"    {sim_pct:5.1f}%  [{record.get( 'ratification_state', '?' ):<9}] {record.get( 'question', '' )[:60]}" )
    else:
        print( f"  Query: '{test_query}'" )
        print( "  Results: 0 matches (store may be empty)" )

    # Check 3: Semantic pair similarity
    print( "\n--- Semantic Pair Verification ---" )
    pair_a = "Should I run the full pytest regression suite before merging this PR?"
    pair_b = "Should I execute the complete test suite as a pre-merge gate?"
    emb_a  = provider.generate_embedding( pair_a, content_type="prose" )
    emb_b  = provider.generate_embedding( pair_b, content_type="prose" )

    # Compute cosine similarity
    dot_product = sum( a * b for a, b in zip( emb_a, emb_b ) )
    norm_a      = sum( a * a for a in emb_a ) ** 0.5
    norm_b      = sum( b * b for b in emb_b ) ** 0.5
    cosine_sim  = dot_product / ( norm_a * norm_b ) if ( norm_a * norm_b ) > 0 else 0.0

    status = "PASS" if cosine_sim > 0.80 else "WARN"
    print( f"  Pair A: '{pair_a[:60]}...'" )
    print( f"  Pair B: '{pair_b[:60]}...'" )
    print( f"  Cosine similarity: {cosine_sim:.4f} [{status}] (target > 0.80)" )

    # Check 4: CBR prediction
    print( "\n--- CBR Prediction ---" )
    cbr = CBRDecisionStore( embedding_store=store, top_k=5, debug=True )
    prediction = cbr.predict(
        question        = test_query,
        category        = "testing",
        query_embedding = test_embed,
    )

    if prediction.verdict is not None:
        print( f"  Verdict:    {prediction.verdict}" )
        print( f"  Confidence: {prediction.confidence:.4f}" )
        print( f"  Cases used: {prediction.case_count}" )
    else:
        print( "  Verdict: None (no cases in store — seed + ratify first)" )

    print( "\n=== Verification Complete ===" )


def clean_seed_data():
    """
    Remove all seed data from PostgreSQL and LanceDB.

    Ensures:
        - Deletes PG records where metadata_json.seed_data == True
        - Removes corresponding LanceDB records
        - Prints deletion count
    """
    store = _get_embedding_store()

    deleted_count = 0

    with get_db() as session:
        repo = ProxyDecisionRepository( session )

        # Find all seed decisions (pending and ratified)
        from cosa.rest.postgres_models import ProxyDecision as PD

        all_swe = session.query( PD ).filter( PD.domain == "swe" ).all()
        seed_decisions = [
            d for d in all_swe
            if d.metadata_json and d.metadata_json.get( "seed_data" ) is True
        ]

        if not seed_decisions:
            print( "No seed data found to clean." )
            return

        print( f"\nCleaning {len( seed_decisions )} seed decisions..." )

        for d in seed_decisions:
            decision_id = str( d.id )

            # Remove from LanceDB (best-effort)
            try:
                if store._ensure_table():
                    escaped = decision_id.replace( "'", "''" )
                    store._table.delete( f"id = '{escaped}'" )
            except Exception as e:
                print( f"  Warning: LanceDB delete failed for {decision_id}: {e}" )

            # Remove from PostgreSQL
            # Reset ratification state to pending so delete_pending works
            if d.ratification_state != "pending":
                d.ratification_state = "pending"
                session.flush()

            repo.delete_pending( d.id )
            deleted_count += 1

        print( f"  Deleted {deleted_count} seed decisions from PostgreSQL + LanceDB" )


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    """
    CLI entry point with argparse.

    Ensures:
        - Parses --dry-run, --ratify, --verify, --clean, --category, --user-email
        - Executes the appropriate operation
    """
    parser = argparse.ArgumentParser(
        description="Seed proxy decisions for preference learning bootstrap"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print scenario catalog without writing to databases"
    )
    parser.add_argument(
        "--ratify", action="store_true",
        help="Batch-ratify all seed decisions using suggested approve/reject values"
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Verify seed data is functioning (PG counts, LanceDB search, CBR prediction)"
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Remove all seed data from PostgreSQL and LanceDB"
    )
    parser.add_argument(
        "--category", type=str, default=None,
        help="Filter scenarios by category (deployment, testing, deps, architecture, destructive, general)"
    )
    parser.add_argument(
        "--user-email", type=str, default=None,
        help="Email for ratification (required with --ratify)"
    )

    args = parser.parse_args()

    # Determine operation
    if args.verify:
        verify()
    elif args.clean:
        clean_seed_data()
    elif args.ratify:
        if not args.user_email:
            parser.error( "--user-email is required with --ratify" )
        ratify_suggested( args.user_email )
    else:
        # Default: seed decisions
        seed_decisions(
            scenarios       = SCENARIO_CATALOG,
            dry_run         = args.dry_run,
            category_filter = args.category,
        )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
CJ Flow v2 — the class-aware DRIFT GUARD (design §6, phase 2).

EXPECTED RED. The failing run IS the deliverable: it is the drift inventory the
single-source design exists to produce. Nothing here is to be greened by loosening
an assertion — phase 3 greens it by FIXING the five real drifts (§3), never by
relaxing a check.

What this guards (§6): FOUR-LIST DRIFT CONSISTENCY across the four consumers of a
routing command — the registry (owner), the router prompt template, the training
corpus keys, and the job factory's branches. Three reachability gaps are OUT OF
SCOPE by design and stated in §6 so nobody reads this name as a reachability proof:
(1) no-retrain (training keys on disk vs LoRA weights), (2) runtime template ≠
checked-in template, (3) emitted string ≠ registry key. This guard proves the four
lists agree — it does not prove the deployed router will emit any given string.

Assertions, class-aware (§6):
  1  agentic: registry ⊆ prompt, registry == training keys, registry == factory (1a/1b/1c)
  2  conversational: in prompt + training, in NO factory branch
  3  control + none: in prompt + training only — set-equality BOTH directions
  4  no command in two class buckets (partition)
  5' every cli_module runs: `python -m <mod> --help` returns 0 (catches a missing
     __main__.py, the module-style variant, AND an import-time crash behind a
     __main__ guard — one check, no forms to enumerate; replaces the old
     filesystem/wording checks that could not fail)

Each assertion ships a falsifiability demo (§6): a synthetic broken input on which
the SAME predicate fires, proving the assertion can go red.

Training scoping (§5.3): reads `agent-router-*.json` ONLY. The `vox-cmd-*.json`
files are 23 browser commands — a separate vocabulary — and are excluded; a glob
over `training/*.json` would false-orphan all 23.

Run: PYTHONPATH=src src/cosa/.venv/bin/python -m pytest \
     src/tests/unit/test_v2_registry_drift_guard.py -v
"""

import os
import re
import sys
import json
import subprocess
import unittest
from itertools import combinations

import cosa.utils.util as cu
from cosa.rest.v2.registry import (
    V2_AGENTS,
    AGENTIC_COMMANDS,
    CONTROL_COMMANDS,
    RECEPTIONIST_OR_NONE,
)

ROUTER_TEMPLATE  = "/src/conf/prompts/agent-router-template-completion.txt"
TRAINING_DIR     = "/src/conf/training"
# §5.3 scoping: the routing vocabulary lives in these three files ONLY. The two
# vox-cmd-*.json files are browser commands and are deliberately excluded.
TRAINING_AGENTIC = "/agent-router-agentic-commands.json"
TRAINING_ROUTER  = ( "/agent-router-agentic-commands.json",
                     "/agent-router-compound-commands.json",
                     "/agent-router-simple-commands.json" )
FACTORY_SOURCE   = "/src/cosa/rest/agentic_job_factory.py"


def _template_commands():
    """The routing commands the prompt template can emit (excludes the empty
    answer-slot tag; keeps `none`)."""
    text = cu.get_file_as_string( cu.get_project_root() + ROUTER_TEMPLATE )
    return { c for c in re.findall( r"<command>(.*?)</command>", text ) if c }


def _training_agentic_keys():
    """The keys of the AGENTIC training corpus — the agentic command set the router
    was trained on."""
    path = cu.get_project_root() + TRAINING_DIR + TRAINING_AGENTIC
    return set( json.loads( cu.get_file_as_string( path ) ).keys() )


def _training_all_keys():
    """The union of all THREE agent-router-*.json corpora (§5.3 scope)."""
    keys = set()
    for name in TRAINING_ROUTER:
        path = cu.get_project_root() + TRAINING_DIR + name
        keys |= set( json.loads( cu.get_file_as_string( path ) ).keys() )
    return keys


def _factory_commands():
    """The command strings the job factory has an if/elif branch for — what
    `create_agentic_job` can actually build."""
    text = cu.get_file_as_string( cu.get_project_root() + FACTORY_SOURCE )
    return set( re.findall( r'command\s*==\s*"([^"]+)"', text ) )


def _cli_module_returncode( module, timeout=60 ):
    """Run `python -m <module> --help` in a subprocess; return ( returncode, tail ).
    0 => runnable; non-zero => missing __main__.py, wrong module form, OR an
    import-time crash behind a __main__ guard."""
    env  = { **os.environ, "PYTHONPATH": cu.get_project_root() + "/src" }
    proc = subprocess.run(
        [ sys.executable, "-m", module, "--help" ],
        env=env, capture_output=True, text=True, timeout=timeout,
    )
    blob  = ( proc.stderr or proc.stdout or "" ).strip()
    tail  = blob.splitlines()[ -1 ][ :160 ] if blob else ""
    return proc.returncode, tail


# -- Assertion 1 — the agentic set agrees across all four sources --------------
class TestAgenticDriftGuard( unittest.TestCase ):

    def test_1a_every_owned_agentic_command_is_router_listed( self ):
        missing = set( AGENTIC_COMMANDS ) - _template_commands()
        self.assertEqual(
            missing, set(),
            f"owned agentic commands the router prompt never lists (unreachable by voice): {sorted( missing )}"
        )

    def test_1b_factory_branches_equal_the_owned_agentic_set( self ):
        factory = _factory_commands()
        owned   = set( AGENTIC_COMMANDS )
        self.assertEqual(
            factory, owned,
            f"factory<->registry drift — in factory not owned: {sorted( factory - owned )}; "
            f"owned but no factory branch (dead-end): {sorted( owned - factory )}"
        )

    def test_1c_training_agentic_keys_equal_the_owned_agentic_set( self ):
        training = _training_agentic_keys()
        owned    = set( AGENTIC_COMMANDS )
        self.assertEqual(
            training, owned,
            f"training<->registry drift — in training not owned: {sorted( training - owned )}; "
            f"owned but not trained: {sorted( owned - training )}"
        )


# -- Assertion 2 — conversational: in prompt + training, in NO factory branch --
class TestConversationalDriftGuard( unittest.TestCase ):

    def test_2_conversational_in_prompt_and_training_and_not_factory( self ):
        conv = set( V2_AGENTS )
        self.assertEqual( conv - _template_commands(), set(),
                          "conversational commands missing from the router prompt" )
        self.assertEqual( conv - _training_all_keys(), set(),
                          "conversational commands missing from the training corpus" )
        self.assertEqual( conv & _factory_commands(), set(),
                          "conversational commands must have NO job-factory branch" )


# -- Assertion 3 — control + none: in prompt + training only, BOTH directions --
class TestControlNoneDriftGuard( unittest.TestCase ):

    def test_3_control_and_none_in_prompt_and_training_only( self ):
        cn = set( CONTROL_COMMANDS ) | set( RECEPTIONIST_OR_NONE )
        # Both directions (arnold): the control+none set must EQUAL the prompt∩training
        # commands that are neither conversational nor agentic — catches a missing
        # membership AND an extra one.
        residue = ( _template_commands() & _training_all_keys() ) - set( V2_AGENTS ) - set( AGENTIC_COMMANDS )
        self.assertEqual( cn, residue,
                          f"control/none drift — labelled: {sorted( cn )}; prompt∩training residue: {sorted( residue )}" )
        self.assertEqual( cn & _factory_commands(), set(),
                          "control/none commands must have NO job-factory branch" )


# -- Assertion 4 — class partition ---------------------------------------------
class TestClassPartition( unittest.TestCase ):

    def test_4_no_command_in_two_class_buckets( self ):
        buckets = [ set( V2_AGENTS ), set( AGENTIC_COMMANDS ),
                    set( CONTROL_COMMANDS ), set( RECEPTIONIST_OR_NONE ) ]
        for a, b in combinations( buckets, 2 ):
            self.assertEqual( a & b, set(), f"command in two class buckets: {a & b}" )


# -- Assertion 5' — every cli_module runs --------------------------------------
class TestCliModulesRun( unittest.TestCase ):

    def test_5_every_agentic_cli_module_runs( self ):
        failures = []
        for command, spec in sorted( AGENTIC_COMMANDS.items() ):
            module = spec.cli_module
            if module is None:
                continue                                  # API-invoked (test_suite)
            rc, tail = _cli_module_returncode( module )
            if rc != 0:
                failures.append( f"{module} (rc={rc}: {tail})" )
        self.assertEqual(
            failures, [],
            "cli_modules that do not run (`python -m <mod> --help` returned non-zero):\n  " + "\n  ".join( failures )
        )


# -- Falsifiability — each assertion above can go red (§6) ----------------------
class TestFalsifiability( unittest.TestCase ):
    """Synthetic broken inputs prove each predicate FIRES. These PASS."""

    def test_demo_membership_gap_is_detected( self ):
        # 1a/1c shape: an owned set carrying a command absent from a consumer set
        # yields a non-empty difference — the red the real guard is written to catch.
        owned    = { "agent router go to real", "agent router go to phantom" }
        consumer = { "agent router go to real" }
        self.assertNotEqual( owned - consumer, set() )

    def test_demo_both_direction_equality_is_detected( self ):
        # 1b/3 shape: set-equality fails on an EXTRA member, not only a missing one.
        self.assertNotEqual( { "a", "b" }, { "a", "b", "c" } )

    def test_demo_partition_overlap_is_detected( self ):
        # 4 shape: a command in two buckets yields a non-empty intersection.
        self.assertNotEqual( { "x", "y" } & { "y", "z" }, set() )

    def test_demo_unrunnable_cli_module_returns_nonzero( self ):
        # 5' shape: a module that cannot be imported/run returns non-zero — the exact
        # signal the real check asserts against. Proves the returncode predicate is live.
        rc, _tail = _cli_module_returncode( "cosa.agents.__nonexistent_drift_guard_probe__" )
        self.assertNotEqual( rc, 0 )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""
CJ Flow v2 — the class-aware DRIFT GUARD (design §6, phase 2).

EXPECTED RED. The failing run IS the deliverable: it is the drift inventory the
single-source design exists to produce. Nothing here is to be greened by loosening
an assertion — phase 3 greens it by FIXING the five real drifts (§3), never by
relaxing a check.

What this guards (§6): FOUR-LIST DRIFT CONSISTENCY across the four consumers of a
routing command — the registry (owner), the router prompt template, the training
corpus keys, and the job factory's branches. TWO reachability gaps remain OUT OF
SCOPE by design and stated in §6 so nobody reads this name as a reachability proof:
(1) no-retrain (training keys on disk vs LoRA weights) and (3) emitted string ≠
registry key. A third, (2) runtime template ≠ checked-in template, is VERIFIED
CLOSED (Tiffany, 2026-08-15): the live router loads the template fresh from disk via
config key `prompt template for agent router` = the exact file this guard reads
(todo_fifo_queue.py:124-127; v2 router_client.py; splainer:477). This guard proves
the four lists agree — it does not prove the deployed router will emit any string.

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
    AgentSpec,
    CommandClass,
    REGISTRY,
    ANSWER_COMMANDS,
    JOB_COMMANDS,
    CONTROL_COMMANDS,
    NO_MATCH,
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
TODO_QUEUE_SOURCE = "/src/cosa/rest/todo_fifo_queue.py"   # holds CARD_LABELS (the card)


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


def _card_commands():
    """The confirmation-card alternatives a user can pick — the KEYS of
    CARD_LABELS (todo_fifo_queue.py:1026), each offered as a 'Switch to this
    instead' option by _confirm_agentic_routing:1058. Read from SOURCE (like the
    prompt/factory readers) so this guards what is CHECKED IN, not a live object —
    a live import could resolve CARD_LABELS differently than the tree on disk."""
    text  = cu.get_file_as_string( cu.get_project_root() + TODO_QUEUE_SOURCE )
    block = re.search( r"CARD_LABELS\s*=\s*\{(.*?)\}", text, re.DOTALL ).group( 1 )
    # Match ANY quoted dict KEY (a string immediately followed by a colon), NOT only
    # the "agent router go to …" prefix (Tiffany): a future non-prefixed card key would
    # otherwise be invisible here, and the phantom arm of _card_drift could not flag it.
    return set( re.findall( r'"([^"]+)"\s*:', block ) )


def _card_drift( carded, owned, exempt ):
    """THE card-drift predicate (§7 card surface) — ONE function, called by BOTH the
    live card guard (test_1d) AND its must-fail control, so the control exercises the
    exact code the guard trusts (never a parallel re-implementation). Returns a list
    of problem strings (empty ⇒ clean):
      - PHANTOM: a card entry that is not an owned agentic command.
      - DEAD-CARD: an owned agentic command absent from the card that does NOT waive
        the 'card' surface (Rachel's invariant §2: owned − carded must be empty
        except commands whose exemption names 'card').
    The control drives it with REAL command strings, one side withheld — never an
    invented 'phantom' token (Rachel)."""
    problems = []
    for c in sorted( set( carded ) - set( owned ) ):
        problems.append( f"{c}: on the confirmation card but not an owned agentic command (phantom)" )
    for c in sorted( set( owned ) - set( carded ) - set( exempt ) ):
        problems.append( f"{c}: owned agentic command absent from the card and does not waive 'card'" )
    return problems


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


# -- Exemption facility (§7) — an INTENTIONAL absence, explicit, reasoned, SCOPED --
# A command owned but NEVER an INITIAL ROUTER DETECTION gets an EXPLICIT exemption
# here. Each entry NAMES the surfaces it waives — "prompt" (1a) and/or "training"
# (1c's owned-must-be-trained arm) — so one exemption can NEVER silently silence a
# guard it was not meant to (Rachel). A command may still be user-REACHABLE by another
# path (e.g. a confirmation-card alternative); the surfaces name only the
# initial-detection guards waived. Each reason carries evidence (the call site).
INITIAL_DETECTION_EXEMPTIONS = {
    "agent router go to test fix expediter": {
        "surfaces": [ "prompt", "training", "card" ],   # NOT listed, NOT trained (e5a840c9 executed), OFF the card
        "reason":
            "Never reached by initial router detection; system/card-triggered. START is "
            "SYSTEM-triggered via test_suite_completion_watchdog.py:258 (create_agentic_job) with a "
            "non-speakable source_test_suite_job_id — no fuzzy-human-input path, so not "
            "user-voice-reachable. It is OFF the confirmation card: absent from CARD_LABELS "
            "(todo_fifo_queue.py:1026), so _confirm_agentic_routing:1058 never offers it as a "
            "'Switch to this instead' alternative — correct, because completing a START run needs "
            "a pasted source_test_suite_job_id that no card alternative supplies. Hence it waives 'card'. "
            "It ALSO waives 'training': row e5a840c9 (folded into the 95924f2d step-4 corpus "
            "single-sourcing) DROPPED the START key from agent-router-agentic-commands.json, so the "
            "corpus no longer trains it — the removal of its training examples is the point, not a "
            "side effect. A live A/B probe confirms emission is gated on the PROMPT LINE, not "
            "training presence — 0/5 emitted when unlisted vs 5/5 when listed "
            "(src/rnd/v0.2.0/2026.08.15-router-emission-probe.md); the earlier 6/10 invention rate "
            "did NOT reproduce. START is now absent from BOTH the template and the corpus, holding "
            "the emission risk at the low, prompt-gated end.",
    },
    "agent router go to bug fix expediter": {
        "surfaces": [ "prompt", "training" ],   # NOT router-emittable (waives prompt+training); ON the card (no card waiver)
        "reason":
            "Never reached by initial router detection; system/card-triggered. The prompt AND the "
            "training corpus govern initial-detection emission, and BFE is intentionally neither "
            "listed nor trained, so the router never emits it as an initial detection (waives "
            "'prompt'+'training'). It is reached instead via dead_queue_watchdog.py:470 "
            "(create_agentic_job), the BFE resubmit path, and the confirmation card: CARD_LABELS "
            "(todo_fifo_queue.py:1026) offers BFE as a 'Switch to this instead' alternative via "
            "_confirm_agentic_routing:1058, and its dead_job_id is then collected by the RAE fallback "
            "questions. So BFE does NOT waive 'card' — it must stay ON the card, which is its only "
            "reachability path; losing card membership would invalidate this exemption.",
    },
}

_VALID_SURFACES = { "prompt", "training", "card" }


def _exempt_on( surface ):
    """Commands whose exemption waives the given initial-detection surface."""
    return { c for c, e in INITIAL_DETECTION_EXEMPTIONS.items() if surface in e.get( "surfaces", [] ) }


def _validate_exemptions( exemptions, owned, template, carded ):
    """Problems with an exemption map: surfaces not a non-empty subset of the valid
    set, no reason, command not owned, or STALE on a waived surface. A surface is
    STALE when the command is still PRESENT on the reachability path it claims to
    waive — waiving 'prompt' while in the template, or waiving 'card' while in
    CARD_LABELS — because then the exemption is silencing a guard that has nothing
    to silence. ('training' has no staleness arm here: a training key IS a legitimate
    reason to waive 1c, so presence is not staleness.) Empty ⇒ valid."""
    problems = []
    for command, entry in exemptions.items():
        surfaces = set( entry.get( "surfaces", [] ) )
        reason   = entry.get( "reason", "" )
        if not surfaces or not ( surfaces <= _VALID_SURFACES ):
            problems.append( f"{command}: surfaces must be a non-empty subset of {sorted( _VALID_SURFACES )}, got {sorted( surfaces )}" )
        if not ( reason and reason.strip() ):
            problems.append( f"{command}: exemption has no reason" )
        if command not in owned:
            problems.append( f"{command}: not an owned agentic command" )
        if "prompt" in surfaces and command in template:
            problems.append( f"{command}: waives 'prompt' but IS in the prompt — stale exemption" )
        if "card" in surfaces and command in carded:
            problems.append( f"{command}: waives 'card' but IS on the card — stale exemption" )
    return problems


# -- Assertion 1 — the agentic set agrees across all four sources --------------
class TestAgenticDriftGuard( unittest.TestCase ):

    def test_1a_every_owned_agentic_command_is_router_listed( self ):
        # Owned agentic commands must be router-listed, UNLESS explicitly exempted
        # (§7): an exemption is an intentional, reasoned absence, not a loosening.
        missing = set( JOB_COMMANDS ) - _template_commands() - _exempt_on( "prompt" )
        self.assertEqual(
            missing, set(),
            f"owned agentic commands the router prompt never lists and do not waive 'prompt': {sorted( missing )}"
        )

    def test_1b_factory_branches_equal_the_owned_agentic_set( self ):
        factory = _factory_commands()
        owned   = set( JOB_COMMANDS )
        self.assertEqual(
            factory, owned,
            f"factory<->registry drift — in factory not owned: {sorted( factory - owned )}; "
            f"owned but no factory branch (dead-end): {sorted( owned - factory )}"
        )

    def test_1c_training_agentic_keys_equal_the_owned_agentic_set( self ):
        training = _training_agentic_keys()
        owned    = set( JOB_COMMANDS )
        trained_not_owned = training - owned                             # a training key MUST be owned
        owned_not_trained = owned - training - _exempt_on( "training" )  # owned MUST be trained unless it waives "training"
        self.assertEqual(
            trained_not_owned | owned_not_trained, set(),
            f"training<->registry drift — in training not owned: {sorted( trained_not_owned )}; "
            f"owned (initial-detection) but not trained: {sorted( owned_not_trained )}"
        )


# -- Assertion 2 — conversational: in prompt + training, in NO factory branch --
class TestConversationalDriftGuard( unittest.TestCase ):

    def test_2_conversational_in_prompt_and_training_and_not_factory( self ):
        conv = set( ANSWER_COMMANDS )
        self.assertEqual( conv - _template_commands(), set(),
                          "conversational commands missing from the router prompt" )
        self.assertEqual( conv - _training_all_keys(), set(),
                          "conversational commands missing from the training corpus" )
        self.assertEqual( conv & _factory_commands(), set(),
                          "conversational commands must have NO job-factory branch" )


# -- Assertion 3 — control + none: in prompt + training only, BOTH directions --
class TestControlNoneDriftGuard( unittest.TestCase ):

    def test_3_control_and_none_in_prompt_and_training_only( self ):
        cn = set( CONTROL_COMMANDS ) | set( NO_MATCH )
        # Both directions (arnold): the control+none set must EQUAL the prompt∩training
        # commands that are neither conversational nor agentic — catches a missing
        # membership AND an extra one.
        residue = ( _template_commands() & _training_all_keys() ) - set( ANSWER_COMMANDS ) - set( JOB_COMMANDS )
        self.assertEqual( cn, residue,
                          f"control/none drift — labelled: {sorted( cn )}; prompt∩training residue: {sorted( residue )}" )
        self.assertEqual( cn & _factory_commands(), set(),
                          "control/none commands must have NO job-factory branch" )


# -- Assertion 4 — class partition ---------------------------------------------
class TestClassPartition( unittest.TestCase ):

    def test_4_no_command_in_two_class_buckets( self ):
        buckets = [ set( ANSWER_COMMANDS ), set( JOB_COMMANDS ),
                    set( CONTROL_COMMANDS ), set( NO_MATCH ) ]
        for a, b in combinations( buckets, 2 ):
            self.assertEqual( a & b, set(), f"command in two class buckets: {a & b}" )


# -- M2 — an INDEPENDENT structural oracle on class labels ---------------------
class TestClassStructuralOracle( unittest.TestCase ):
    """M2 (Tiffany's mutation): the class assertions read `cls`, and assertion 3's
    residue subtracts BOTH conversational and agentic — so relabelling a command
    between two of those classes cancels out and is invisible. This adds an oracle
    INDEPENDENT of `cls`: a conversational command carries an agent `factory`;
    control, none, and agentic commands do not. Relabelling `automatic`
    CONTROL->CONVERSATIONAL is then caught (its factory is None).

    STATED BLIND SPOT (§6, named not silent): this does NOT catch a CONTROL<->NONE
    mislabel — both carry `factory=None`, and the registry has no independent oracle
    to separate them. A control command mislabelled `none`, or vice versa, passes
    every check here. Recorded so nobody reads this guard as covering that swap."""

    def test_conversational_iff_spec_has_a_factory( self ):
        for command, spec in REGISTRY.items():
            if spec.cls is CommandClass.CONVERSATIONAL:
                self.assertIsNotNone(
                    spec.factory,
                    f"conversational command {command!r} must carry an agent factory"
                )
            else:
                self.assertIsNone(
                    spec.factory,
                    f"non-conversational command {command!r} must not carry an agent factory (cls={spec.cls})"
                )


# -- Assertion 5' — every cli_module runs --------------------------------------
class TestCliModulesRun( unittest.TestCase ):

    def test_5_every_agentic_cli_module_runs( self ):
        failures = []
        for command, spec in sorted( JOB_COMMANDS.items() ):
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


# -- §4 — cached help must NAME the declared args, not merely exit 0 ------------
class TestCliHelpNamesDeclaredArgs( unittest.TestCase ):
    """§4: 5' proves each cli_module RUNS; this proves it HELPS. `get_cli_help`
    caches `python -m <mod> --help` and feeds it to the phi4 extraction prompt, so
    the check whose ABSENCE let 'No module named …__main__' become an agent's help
    text is: the cached help must NAME that command's declared required args.

    Two arms of the SAME assertion, by how the help is produced:
      - STRUCTURAL — claude_code, bug_fix_expediter, test_fix_expediter: their help
        is GENERATED from the registry entry (cli_help.py), so naming the declared
        args is near-tautological here; this arm confirms the generator, little more.
      - FALSIFIABLE — the six hand-written CLIs (deep_research, podcast_generator,
        deep_research_to_podcast, presentation_generator,
        deep_research_to_presentation, swe_team): an INDEPENDENT source, so this is a
        real cross-check that the CLI documents what the registry declares.

    Arg-name arm ONLY. There is no 'usage' fallback: verified 2026-08-15 (sha
    2564e115), all six hand-written CLIs document the args the registry declares for
    them, so the weaker arm was never needed and is dropped — a fallback nobody uses
    is a branch that cannot go red. If a future CLI genuinely cannot name its args,
    that is a real finding: leave it red, don't reintroduce a soft arm to hide it."""

    # ⚠️ ORDER-DEPENDENT RED, AND IT PREDATES 2026-08-19 — read this before filing a
    # regression. This test PASSES ALONE and FAILS, all nine commands at once, whenever
    # src/cosa/tests/unit/training/test_peft_trainer.py has run earlier in the same
    # process. Bisected across all ten files in that directory; it is the only one that
    # does it, reproducibly. It fails identically with the row-95924f2d step-4 work
    # stashed, so a tier run that goes red here after that push is NOT reporting on it.
    #
    # FOUR OBVIOUS CAUSES ARE ALREADY RULED OUT BY DIRECT PROBE — do not start from them:
    #   (a) the working directory IS restored — measured before and after the peft suite;
    #   (b) subprocess.run still works afterwards — a probe in the same process after the
    #       suite returns 450 bytes of help naming `prompt`;
    #   (c) _help_cache is not stale — cleared and re-read, same good result;
    #   (d) nothing under src/cosa/tests/unit/training or .../infrastructure references
    #       get_cli_help, _help_cache, agent_registry, JOB_ARG_CONTRACTS or subprocess.
    #
    # The surviving suspects are something the peft suite does to the INTERPRETER rather
    # than to the environment — a leaked import-system or `sys` mutation fits the evidence.
    # Full write-up: planning-is-prompting TODO.md, under Pending. (María, 2026-08-19.)
    def test_cached_help_names_each_commands_declared_args( self ):
        from cosa.agents.runtime_argument_expeditor.agent_registry import (
            JOB_ARG_CONTRACTS, get_cli_help,
        )
        failures = []
        for command, spec in sorted( JOB_COMMANDS.items() ):
            if spec.cli_module is None:
                continue                                  # API-invoked (test_suite)
            help_text = ( get_cli_help( command ) or "" ).lower()
            required  = [ a.lower() for a in JOB_ARG_CONTRACTS[ command ][ "required_user_args" ] ]
            missing   = [ a for a in required if a not in help_text ]
            if not help_text or missing:
                failures.append( f"{command} ({spec.cli_module}): help does not name {missing or '(help empty)'}" )
        self.assertEqual(
            failures, [],
            "§4 — cached CLI help does not name declared args:\n  " + "\n  ".join( failures )
        )


# -- Exemption facility validity (§7) ------------------------------------------
class TestInitialDetectionExemptionFacility( unittest.TestCase ):
    """Every exemption must be real (owned), carry a reason, name valid surfaces, and
    not be stale on a waived surface. The validator itself must be able to go red, and
    a surface it does NOT name must NOT be silenced."""

    def test_real_exemptions_are_all_valid( self ):
        problems = _validate_exemptions(
            INITIAL_DETECTION_EXEMPTIONS, set( JOB_COMMANDS ),
            _template_commands(), _card_commands() )
        self.assertEqual( problems, [], f"invalid exemptions: {problems}" )

    def test_validator_flags_bad_surfaces_no_reason_not_owned_and_stale( self ):
        # Falsifiability: bad entries hitting every failure mode.
        # - phantom: empty surfaces AND empty reason AND not an owned command
        # - weather: a real CONVERSATIONAL template command waiving 'prompt' → stale
        # - bug fix expediter: a REAL on-card command waiving 'card' → card-stale
        # Preconditions (Tiffany): the stale arms rely on real membership. Assert both
        # — "weather" really in the template, BFE really on the card — so this test
        # FAILS LOUDLY if either leaves its surface rather than silently ceasing to
        # exercise staleness. BFE is a REAL one-sided entry, not an invented string (Rachel).
        self.assertIn( "agent router go to weather", _template_commands() )
        self.assertIn( "agent router go to bug fix expediter", _card_commands() )
        problems = _validate_exemptions(
            { "agent router go to phantom": { "surfaces": [], "reason": "" },
              "agent router go to weather": { "surfaces": [ "prompt" ], "reason": "x" },
              "agent router go to bug fix expediter": { "surfaces": [ "card" ], "reason": "x" } },
            set( JOB_COMMANDS ), _template_commands(), _card_commands() )
        self.assertTrue( any( "surfaces must be a non-empty subset" in p for p in problems ), problems )
        self.assertIn( "agent router go to phantom: exemption has no reason", problems )
        self.assertIn( "agent router go to phantom: not an owned agentic command", problems )
        self.assertIn( "agent router go to weather: waives 'prompt' but IS in the prompt — stale exemption", problems )
        self.assertIn( "agent router go to bug fix expediter: waives 'card' but IS on the card — stale exemption", problems )

    def test_prompt_only_surface_cannot_silence_the_training_guard( self ):
        # Rachel's control — the proof the `surfaces` field is load-bearing, not
        # decoration. The load-bearing proof is the SYNTHETIC ["prompt"]-only
        # exemption below: it clears 1a's shape but leaves 1c's shape RED, so a
        # prompt waiver cannot silence the training guard. (START no longer serves as
        # that example — e5a840c9 dropped its training key, so it now legitimately
        # waives 'training' too; the real surfaces of the live exemptions are checked
        # here, and the synthetic case carries the invariant.)
        self.assertIn(    "agent router go to test fix expediter", _exempt_on( "prompt" ) )
        self.assertIn(    "agent router go to test fix expediter", _exempt_on( "training" ) )   # e5a840c9: no longer trained
        self.assertIn(    "agent router go to bug fix expediter",  _exempt_on( "prompt" ) )
        self.assertIn(    "agent router go to bug fix expediter",  _exempt_on( "training" ) )
        # card surface is load-bearing too: START is OFF the card so it waives 'card';
        # BFE is ON the card (its only reachability path) so it must NOT waive 'card'.
        self.assertIn(    "agent router go to test fix expediter", _exempt_on( "card" ) )
        self.assertNotIn( "agent router go to bug fix expediter",  _exempt_on( "card" ) )

        synth       = { "agent router go to synth": { "surfaces": [ "prompt" ], "reason": "r" } }
        on_prompt   = { c for c, e in synth.items() if "prompt"   in e[ "surfaces" ] }
        on_training = { c for c, e in synth.items() if "training" in e[ "surfaces" ] }
        owned, trained = { "agent router go to synth" }, set()
        self.assertEqual( owned - on_prompt, set() )                  # 1a-shape: cleared
        self.assertEqual( owned - trained - on_training, owned )      # 1c-shape: STILL red


# -- Card-drift predicate control (§7 card surface) ----------------------------
class TestCardDriftPredicateControl( unittest.TestCase ):
    """The committed must-fail control for the shared `_card_drift` predicate, so the
    instrument is never ungated. The POSITIVE real-data guard (owned − carded − card-
    exempt is clean) is test_1d, owned by the card-guard author and landing on top —
    both call this same `_card_drift`, never a parallel re-implementation.

    Rachel's rule: drive the control with REAL command strings, one side withheld —
    never an invented 'phantom' token. Each arm asserts its real precondition first,
    so it FAILS LOUDLY if the command ever leaves the surface rather than silently
    ceasing to exercise the arm."""

    def test_dead_card_arm_fires_on_a_real_owned_not_carded_command( self ):
        # START is genuinely owned AND off the card — the real dead-card entry. With
        # its 'card' waiver WITHHELD (exempt=set()), the predicate must flag it.
        start = "agent router go to test fix expediter"
        self.assertIn(    start, set( JOB_COMMANDS ) )   # really owned
        self.assertNotIn( start, _card_commands() )          # really off the card
        problems = _card_drift( _card_commands(), set( JOB_COMMANDS ), exempt=set() )
        self.assertTrue(
            any( p.startswith( start ) and "does not waive 'card'" in p for p in problems ),
            f"dead-card arm did not fire on real owned-not-carded {start!r}: {problems}"
        )
        # and WITH its real waiver, the same predicate clears START (no false red).
        self.assertFalse(
            any( p.startswith( start ) for p in
                 _card_drift( _card_commands(), set( JOB_COMMANDS ), exempt=_exempt_on( "card" ) ) )
        )

    def test_phantom_arm_fires_on_a_real_carded_command_when_owned_withheld( self ):
        # A real card entry with the owned set withheld surfaces as a phantom — a real
        # command string, not an invented token.
        real_carded = "agent router go to deep research"
        self.assertIn( real_carded, _card_commands() )       # really on the card
        problems = _card_drift( { real_carded }, owned=set(), exempt=set() )
        self.assertTrue(
            any( p.startswith( real_carded ) and "phantom" in p for p in problems ),
            f"phantom arm did not fire on real carded {real_carded!r} with owned withheld: {problems}"
        )


# -- Assertion 1d — the card surface (§7): the POSITIVE real-data guard ---------
class TestCardSurfaceDriftGuard( unittest.TestCase ):
    """§7 card surface — the live guard on top of Tiberius's facility. CARD_LABELS
    (todo_fifo_queue.py:1026) is the confirmation-card alternatives
    _confirm_agentic_routing:1058 offers as 'Switch to this instead' — a FIFTH
    registration list that was instrumented but not guarded until this. Routed through
    the SHARED `_card_drift` predicate (the same one TestCardDriftPredicateControl
    drives red on both arms), so this guard and its control can never diverge:
      - PHANTOM: a card entry that is not an owned agentic command.
      - DEAD-CARD: an owned agentic command off the card that does NOT waive 'card'.
    Currently clean: owned − carded = {START}, and START waives 'card'. María's framing:
    one registry is the source of truth; a card list that silently drops an owned
    command is the exact defect this consolidation removes."""

    def test_1d_card_surface_agrees_with_the_owned_agentic_set( self ):
        problems = _card_drift(
            _card_commands(), set( JOB_COMMANDS ), exempt=_exempt_on( "card" ) )
        self.assertEqual(
            problems, [],
            "card<->registry drift (§7):\n  " + "\n  ".join( problems ) )


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

    def test_demo_class_mislabel_is_detected( self ):
        # M2 shape: a control command relabelled CONVERSATIONAL keeps factory=None, so
        # the oracle's "conversational => factory is not None" predicate fires red.
        mislabelled = AgentSpec( "agent router go to automatic", cls=CommandClass.CONVERSATIONAL )
        self.assertIsNone( mislabelled.factory )   # what the structural oracle catches


if __name__ == "__main__":
    unittest.main()


# ─────────────────────────────────────────────────────────────────────────────
# THE JSONs CANNOT INVENT A COMMAND — row 95924f2d step 4, cheap version.
#
# The MENU is already single-sourced: XmlPromptGenerator._compile_agent_router_commands
# reads speakable_commands(), and no JSON can move it — measured by deletion, drop one
# from the registry oracle and the menu goes 18 to 17; add one to a JSON and it does
# not move.
#
# The JSONs still decide WHICH commands get rows, though: xml_coordinator iterates
# their keys and formats each row's ANSWER with the key it is on. So a key the registry
# has never heard of yields rows teaching a command the menu inside those same rows
# never offers, and the LoRA learns both halves. The guard below makes that impossible
# to build rather than possible to detect.
# ─────────────────────────────────────────────────────────────────────────────

def _generator():
    import cosa.utils.util as cu
    from cosa.training.xml_prompt_generator import XmlPromptGenerator
    return XmlPromptGenerator( path_prefix=cu.get_project_root() )


def test_the_training_jsons_name_only_commands_the_registry_lists():
    """The state today: every agent-router JSON key is a registered command."""
    from cosa.rest.v2.registry import REGISTRY

    generator = _generator()
    json_commands = (
        set( generator.agent_router_compound_commands )
        | set( generator.agent_router_simple_commands )
        | set( generator.agent_router_agentic_commands )
    )

    assert json_commands, "fixture check — the JSONs must actually have loaded"
    assert not ( json_commands - set( REGISTRY ) )


def test_a_json_key_the_registry_does_not_list_REFUSES_THE_BUILD():
    """
    THE FALSIFICATION, same shape as step 3's: invent a command in a JSON and the
    build must refuse rather than quietly emit rows for it. Proven here rather than
    described, because a guard nobody has watched fail is a comment with a green tick.
    """
    import pytest
    from unittest.mock import patch
    from cosa.training.xml_prompt_generator import XmlPromptGenerator

    with patch.object( XmlPromptGenerator, "_get_simple_agent_router_commands",
                       lambda self: { "agent router go to invented": "x.txt" } ):
        with pytest.raises( ValueError ) as caught:
            _generator()

    message = str( caught.value )
    assert "agent router go to invented" in message
    assert "registry" in message.lower()


def test_a_REGISTERED_but_non_speakable_command_is_REFUSED_IN_THE_CORPUS():
    """
    ⚠️ THIS TEST REVERSES ITS OWN EARLIER VERSION, which asserted the opposite —
    that a registered-but-non-speakable command was ALLOWED in the training JSONs.
    Recorded rather than quietly deleted, because the earlier reasoning was sound
    about the wrong artifact (María, row 95924f2d step 4).

    The earlier version read: "checking against the speakable set would flag a
    documented exemption as drift." True of the ROUTER PROMPT — the expediters are
    system-triggered, deliberately registered and deliberately absent from it, and
    step 3's pin still honours that exemption untouched.

    It is NOT true of the TRAINING CORPUS, and that is the whole of step 4. Every
    training instruction interpolates the SPEAKABLE menu. So a non-speakable command
    with rows teaches the model a label the menu inside those very rows never offers
    — exactly the defect the exemption was invoked to avoid causing. The tree already
    agreed in practice before it agreed in code: commit 14a44cf4 removed the
    expediter-START phrasings from the JSONs for this reason.

    So the oracle for the corpus is speakable_commands(), and the oracle for the
    prompt stays the registry's `speakable` field. Two artifacts, one source, one
    exemption honoured in the only place it means anything.
    """
    import pytest
    from unittest.mock import patch
    from cosa.rest.v2.registry import REGISTRY
    from cosa.rest.v2.router_prompt_generator import speakable_commands
    from cosa.training.xml_prompt_generator import XmlPromptGenerator

    exempt = sorted( set( REGISTRY ) - set( speakable_commands() ) )
    assert exempt, "fixture check — this test is meaningless if nothing is exempt"

    with patch.object( XmlPromptGenerator, "_get_simple_agent_router_commands",
                       lambda self: { exempt[ 0 ]: "x.txt" } ):
        with pytest.raises( ValueError ) as caught:
            _generator()

    assert exempt[ 0 ] in str( caught.value )


def test_the_exemption_still_holds_where_it_was_meant_to___the_router_prompt():
    """
    The half of the earlier ruling that survives: a non-speakable command stays OUT
    of the served router prompt, and nothing here has touched that.
    """
    from cosa.rest.v2.registry import REGISTRY
    from cosa.rest.v2.router_prompt_generator import speakable_commands

    exempt = sorted( set( REGISTRY ) - set( speakable_commands() ) )
    for command in exempt:
        assert command not in speakable_commands()
        assert REGISTRY[ command ].speakable is False

"""
Vertex / Model Garden per-session toggle: environment composition and guards.

Design: src/rnd/v0.1.9/2026.07.13-vertex-model-garden-toggle-search-and-logging.md

The guards are Python, not bash, because the Lupin coverage mandate is 100% of lines, branches and
functions. Bash has no branch-coverage instrument. A shell guard tested only on its happy path would
report full coverage while its failure branches went unmeasured. Those branches are the only thing
standing between the user and a silently mis-billed project, and an unproven guard is decoration.
Here every failure branch can be tested red first, and the shell is a thin wrapper.

Certifying and enforcing a region are different acts:

    Certify a region  once, out of band   `rawPredict` -> 200.  Costs money.
    Enforce a region  every launch        equality + a calibrated free probe.  $0.

The only truthful region oracle is a real inference call, and that costs money. So a free
launch-time region probe cannot exist. This module does not re-derive the region. It enforces a
constant that was certified once. The publisher-model metadata endpoint is not used. It returns 200
for a region that cannot serve the model and 403 for one that can. A guard built on it would open
the gate for the very trap it exists to stop.

The set of instruments that may not certify a region has already grown once. The MaaS OpenAI-compat
endpoint turned out to be region-blind (see the certification map below). So every region must name
the instrument that proved it, and `assert_region_oracle_is_admissible` checks that instrument at
import time. A proof written in prose is not a guard. The import-time call is the guard.
"""

import os


# The Vertex serving region. NOT LUPIN_GCP_REGION — that is the CONTAINER-DEPLOY
# region (Cloud Run / Artifact Registry), and the model is not servable there.
# Two different concepts that shared a word, and now hold different values (§4a-ter).
VERTEX_REGION_ENV_KEY = "LUPIN_VERTEX_REGION"

# C2 — THE ALLOWLIST THE WORD "ENFORCE" WAS STANDING IN FOR.
#
# This module's docstring claimed it "enforces a constant certified once." It did
# not. LUPIN_VERTEX_REGION=us-central1 composed cleanly and exited 0 — the DEAD
# region, where claude-opus-4-8 is NOT SERVABLE (rawPredict -> 400). I wrote the
# certify-vs-enforce doctrine and then shipped a module that did neither.
#
# A region may appear here ONLY after a rawPredict returned 200 from it. Not a
# metadata GET (returns 200 for us-central1, which cannot serve). Not a quota row
# (there is a web-search allocation in us-central1, for a model that cannot run
# there). Not a flatPath. A LISTING IS NOT A CAPABILITY.
#
#   global       rawPredict -> 200   SERVES, and has working quota.  CERTIFIED.
#   us-east5     rawPredict -> 429   Servable but QUOTA-STARVED — deliberately NOT
#                                    certified: it would fail under any real load.
#   us-central1  rawPredict -> 400   NOT SERVABLE. The region this design once froze.
#   us           rawPredict -> 501   An access-scope word from the Model Garden form,
#                                    not an API location.
#
# ---------------------------------------------------------------------------
# WHICH INSTRUMENTS MAY CERTIFY A REGION — and the one that lied on 2026-07-13
# ---------------------------------------------------------------------------
#
# A region oracle is admissible only if it CAN COME OUT OTHERWISE ON THE REGION
# AXIS. Most Vertex surfaces cannot: they answer a question about the MODEL and let
# the region ride along in the URL path, unread.
#
# ADMISSIBLE — rawPredict. It reaches the serving stack for locations/{REGION} and
# 400s when the model cannot run there. It discriminates on the axis we are asking about.
#
# INADMISSIBLE — the MaaS OpenAI-COMPAT ENDPOINT. Newest of the family, and the most
# convincing, because it looks exactly like a real inference call:
#
#     POST /v1/projects/{P}/locations/{REGION}/endpoints/openapi/chat/completions
#
# IT IGNORES ITS OWN locations/{REGION} PATH SEGMENT. Measured (deepseek-v3.2-maas):
#
#     global       -> 200, 1418 bytes, content "OK"
#     us-central1  -> 200, 1418 bytes, content "OK"   <- the DEAD region
#     narnia-1     -> 200, 1418 bytes, content "OK"   <- A REGION THAT DOES NOT EXIST
#     acme/bogus-model @ narnia-1 -> 404
#
# BYTE-IDENTICAL across a real, a dead, and a FICTIONAL region. The MODEL axis
# discriminates; the REGION axis is BLIND. And the TELL is in the 404 body, which
# says "Ensure ... the model is available in the specified region" — IT CLAIMS
# REGION-SENSITIVITY IN ITS ERROR TEXT WHILE BEING BLIND TO REGION IN ITS BEHAVIOUR.
# An error code answering a question nobody asked. DO NOT CERTIFY A REGION WITH IT.
#
# (NOT retroactive: CERTIFIED_VERTEX_REGIONS was built from rawPredict, which
# genuinely 400s on us-central1. This is a trap for FUTURE work, so it is guarded
# below rather than merely written down — a proof is not a guard.)
#
# CONSUMER HAZARDS, if anything downstream ever CALLS this endpoint (calling it is
# fine; only certifying a REGION with it is not). Both measured on the same probe:
#
#   1. CoT SPLICE. openai/gpt-oss-120b-maas streams a SECOND channel,
#      `delta.reasoning_content` — the model's raw chain-of-thought (807 chars on
#      our probe). deepseek streams none. ANY CLIENT THAT NAIVELY CONCATENATES ALL
#      DELTAS SPLICES THE MODEL'S CoT INTO THE USER-VISIBLE ANSWER. Filter on the
#      FIELD NAME (`delta.content`); never on "whatever the deltas contain."
#
#   2. PHANTOM PREAMBLE. The prompt you send is not the prompt the model sees. An
#      identical 9-token user message billed prompt_tokens=9 (deepseek) vs 72
#      (gpt-oss, 64 cached) — ~63 tokens of system preamble we never wrote. You are
#      billed for tokens you did not author, so never compute cost from YOUR count.
ADMISSIBLE_REGION_ORACLES = (
    "rawPredict",
)

# Evidence fragments that PROVE the wrong instrument was used. Kept narrow and
# unambiguous on purpose: a fragment that also appears in a rawPredict URL would
# make this guard fire on a VALID certification, which is the "guard that fires on
# a correct configuration" bug (C4) — the one that teaches people to disable guards.
REGION_BLIND_EVIDENCE_FRAGMENTS = (
    "endpoints/openapi",   # the MaaS OpenAI-compat path — ignores locations/{REGION}
    "chat/completions",    # ...and the same surface named by its other half
)

CERTIFICATION_FIELDS = ( "oracle", "evidence" )

# THE GUARD (see assert_region_oracle_is_admissible): a region cannot enter this
# map anonymously. It must NAME the instrument that certified it, and that
# instrument is checked at IMPORT TIME — so a seat that certifies `us-central1`
# from an OpenAI-compat 200 cannot even load the module, let alone launch.
VERTEX_REGION_CERTIFICATIONS = {
    "global" : {
        "oracle"   : "rawPredict",
        "evidence" : (
            "POST .../locations/global/publishers/anthropic/models/"
            "claude-opus-4-8:rawPredict -> 200 (2026-07-13)"
        ),
    },
}

# Per-model region overrides shipped in the Claude Code binary (15 of them). Each one
# overrides CLOUD_ML_REGION *for a single model* — so one inherited var routes Opus alone
# to another region, where it runs, bills, and logs nothing, while every other model
# behaves normally. The region trap wearing a disguise.
#
# C3 — THIS TUPLE IS A HARVEST FROM SOMEONE ELSE'S RELEASE ARTIFACT, AND A HARVEST HAS A DATE.
#
# The parametrized guard suite proves every key IN this tuple is guarded. It proves NOTHING
# about a key that exists in the WORLD but not in the tuple — and that is the whole risk,
# because the tuple is a point-in-time `strings` scrape of a binary we do not control. Note
# what is in it: CLAUDE_5_SONNET, but no CLAUDE_5_OPUS. Correct today; one release from wrong.
# A completeness claim that cannot fail is a wish with good grammar.
#
# So this tuple's completeness is RE-DERIVED from the shipped binary on every run
# (test_vertex_env_completeness.py), and that scrape FAILS — never skips — when it cannot see
# the binary: a skipped completeness check and a passing one are indistinguishable in a
# 9,000-test run. The re-derivation is the GUARD. The calibration below is a RECORD, not a
# guard: it says which release this harvest was taken from, so that when the drift test goes
# red the reader can see, in one line, what changed underneath them.
#
# The calibration is deliberately NOT asserted against the running binary. A CC upgrade that
# does not touch the key set is a VALID configuration, and a guard that fires on a valid
# configuration teaches people to disable guards (C4, one bucket over). Only DRIFT IN THE KEYS
# is an error; a drift in the version number is merely news.
PER_MODEL_REGION_OVERRIDES_CALIBRATION = {
    "cc_version" : "2.1.284",
    "harvested"  : "2026-09-28",
    "instrument" : "strings $(readlink -f $(which claude)) | grep -oE 'VERTEX_REGION_CLAUDE_[A-Z0-9_]+'",
}

# HOW THIS STAYS CALIBRATED — and why the stamp above is provenance, not the
# mechanism. `test_per_model_region_override_set_matches_the_shipped_binary`
# re-harvests from the CURRENTLY INSTALLED binary on EVERY run and fails on any
# divergence in either direction. So the tuple cannot silently rot: it rots
# loudly, at the next test run after a CC upgrade.
#
# That is deliberate rather than automatic. A new VERTEX_REGION_* key means the
# shipped binary can route ONE model to another region, where it runs, bills and
# logs outside every guard we have — auto-adopting it would let the binary widen
# our exposure without anyone reading the diff. The red is the review request.
#
# History of the stamp, which is the point: harvested at 2.1.207, re-derived
# clean against 2.1.209 on 2026-07-14 (key set held, version moved), and moved
# again here — 2.1.220 added VERTEX_REGION_CLAUDE_5_OPUS, red for however long
# the upgrade predated this run; and again when VERTEX_REGION_CLAUDE_5_5_OPUS was
# harvested from 2.1.283 (2026-09-27).
#
# Moved again 2026-09-28 (Krishna 🦚, row 922b261a): 2.1.284 added
# VERTEX_REGION_CLAUDE_5_5_SONNET. Caught by the unit tier on THREE trees at once — my
# worktree, the main checkout at 5e066058e, and Rio's worktree — which is what told us it
# was a host upgrade rather than one seat's branch. Re-harvested with the documented
# instrument across every version on disk before touching the tuple: 19 keys in 2.1.284
# against 18 guarded, exactly one unguarded and ZERO phantom, so the tuple was correct
# until the upgrade rather than merely stale. Key added first, stamp moved second.
#
# ⚠️ AN ENTRY'S COMMENT SAYS "present by", NOT "added in", AND THE DIFFERENCE IS A
# CLAIM NOBODY HERE CAN MAKE. A harvest reads the versions that happen to be ON
# DISK — three of them on 2026-09-27 — so it can prove a key is PRESENT in the
# oldest one it can see and can never prove the key was ABSENT before that. The
# 5_5_OPUS entry was first written "added 2.1.283" from a single-version reading;
# Rio checked 2.1.281 and 2.1.282 and found the key in both, so the claim was
# false the moment it was written. The older "added" comments above predate this
# note and carry the same unverified shape — read them as "present by".
#
# THE VERSION IS NOT THE INSTRUMENT; the binary
# on disk is. Never "fix" a red here by bumping cc_version alone.
#
# Moved again 2026-09-01 (Mr. Radio 🦉): 2.1.258 added VERTEX_REGION_CLAUDE_FABLE_5_1,
# caught by the unit tier and NOT by anyone reading a release note — which is the
# whole argument for this guard existing. Re-harvested with the documented
# instrument before touching the tuple: 17 keys in the binary against 16 guarded,
# exactly one unguarded and zero phantom, so the tuple was correct until the
# upgrade rather than merely stale. The key was added AND the stamp moved, in that
# order; the stamp alone would have been the "fix" this block forbids.

PER_MODEL_REGION_OVERRIDES = (
    "VERTEX_REGION_CLAUDE_3_5_HAIKU",
    "VERTEX_REGION_CLAUDE_3_5_SONNET",
    "VERTEX_REGION_CLAUDE_3_7_SONNET",
    "VERTEX_REGION_CLAUDE_4_0_OPUS",
    "VERTEX_REGION_CLAUDE_4_0_SONNET",
    "VERTEX_REGION_CLAUDE_4_1_OPUS",
    "VERTEX_REGION_CLAUDE_4_5_OPUS",
    "VERTEX_REGION_CLAUDE_4_5_SONNET",
    "VERTEX_REGION_CLAUDE_4_6_OPUS",
    "VERTEX_REGION_CLAUDE_4_6_SONNET",
    "VERTEX_REGION_CLAUDE_4_7_OPUS",
    "VERTEX_REGION_CLAUDE_4_8_OPUS",
    "VERTEX_REGION_CLAUDE_5_5_OPUS",        # present by 2.1.281, harvested 2.1.283 (2026-09-27)
    # THE ONE ENTRY HERE THAT CAN HONESTLY SAY "added", AND THE REASON IS MEASURED ABSENCE.
    # The note above is right that a harvest normally proves only PRESENCE in the oldest
    # version on disk. This key is the exception: it was scraped as ABSENT from 2.1.281,
    # 2.1.282 AND 2.1.283, and PRESENT in 2.1.284, all four on disk at harvest time. So the
    # lower bound is real — it arrived between .283 and .284 — and that is a stronger claim
    # than "present by", not a looser one. Write "present by" again the moment the older
    # versions are pruned and the absence can no longer be re-measured.
    "VERTEX_REGION_CLAUDE_5_5_SONNET",      # added 2.1.284 (2026-09-28) — absent in .281/.282/.283, measured
    "VERTEX_REGION_CLAUDE_5_OPUS",          # added 2.1.220 (2026-07-27)
    "VERTEX_REGION_CLAUDE_5_SONNET",
    "VERTEX_REGION_CLAUDE_FABLE_5",
    "VERTEX_REGION_CLAUDE_FABLE_5_1",       # added 2.1.258 (2026-09-01)
    "VERTEX_REGION_CLAUDE_HAIKU_4_5",
)

# §5c.2 is "CLEAR **or ASSERT**", and the distinction is load-bearing:
#
#   ASSERTABLE  — GOOGLE_CLOUD_PROJECT / GCLOUD_PROJECT name a project, so they can
#                 be COMPARED to the resolved one. Present-and-agreeing is harmless;
#                 present-and-disagreeing bills someone else, silently. -> assert.
#
#   UNASSERTABLE — GOOGLE_APPLICATION_CREDENTIALS points at a service-account KEY
#                 FILE whose project we cannot know without reading and trusting it.
#                 There is nothing to compare it against, so it cannot be asserted —
#                 only cleared. It is the sharpest of the three precisely because it
#                 defeats the project guard from OUTSIDE the project's namespace.
#
# Collapsing these two categories (banning all three) was a real bug, caught by the
# red-first suite: it made a HARMLESS, AGREEING GOOGLE_CLOUD_PROJECT abort the launch.
# A guard that fires on a correct configuration teaches people to disable guards.
ASSERTABLE_PROJECT_OVERRIDES = (
    "GOOGLE_CLOUD_PROJECT",
    "GCLOUD_PROJECT",
)

UNASSERTABLE_PROJECT_OVERRIDES = (
    "GOOGLE_APPLICATION_CREDENTIALS",
)

# C4 — the assertable/unassertable split, ONE BUCKET OVER. I fixed it for the
# project variables and did not sweep the sibling category: an ANTHROPIC_MODEL that
# AGREES with our pin is harmless, and aborting on it is the same "guard that fires
# on a valid configuration" bug. My own rule — grep for the CLASS, not the line you
# fixed — broken by me, in the fix where I coined it.
#
# These are compared against the pin they would override, not banned.
ASSERTABLE_MODEL_OVERRIDES = {
    "ANTHROPIC_MODEL"            : "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL" : "ANTHROPIC_DEFAULT_HAIKU_MODEL",
}

ENDPOINT_SUBVERTERS = (
    "ANTHROPIC_VERTEX_BASE_URL",    # redirects the endpoint
    "CLAUDE_CODE_SKIP_VERTEX_AUTH", # bypasses auth
)

# Everything the --vertex path must SCRUB from the pane before `claude` starts.
# "Scrub, don't omit" (F-A7): a positive tmux -e allowlist ADDS keys and SUBTRACTS
# NOTHING, so an unlisted key inherits whatever the frozen tmux server env holds.
# Omission is not subtraction.
HOSTILE_ENV_KEYS = (
    PER_MODEL_REGION_OVERRIDES
    + UNASSERTABLE_PROJECT_OVERRIDES
    + ENDPOINT_SUBVERTERS
)

# Everything the PANE must be cleansed of, or have corrected, before `claude` starts.
# C1: the guard runs in the LAUNCHER's process; `claude` runs in the PANE, on the
# FROZEN tmux server env. A guard that fires in the wrong process is not a guard
# (F-A10) — and I closed F-A10 in the doc, then rebuilt it in the code.
# The pane scrub is DELIBERATELY WIDER than the launcher guard set.
#
# In the LAUNCHER we can ASSERT the project vars (compare them to the resolved
# project). In the PANE we cannot: the pane inherits the FROZEN tmux server env,
# whose values the launcher never saw and cannot vouch for. A stale
# GOOGLE_CLOUD_PROJECT sitting on a server started hours ago TAKES PRECEDENCE over
# ANTHROPIC_VERTEX_PROJECT_ID and bills the wrong GCP project, silently, with every
# launcher-side guard green.
#
# So the pane gets them UNSET outright, leaving ANTHROPIC_VERTEX_PROJECT_ID (which we
# forward explicitly via -e) as the single authority. No precedence fight to lose.
PANE_UNSET_KEYS = (
    HOSTILE_ENV_KEYS
    + tuple( ASSERTABLE_MODEL_OVERRIDES )
    + ASSERTABLE_PROJECT_OVERRIDES
)

# The three variables that PUT a session on Vertex. A Max session must never carry
# them — and a tmux server born from a Vertex shell hands them to EVERY later session
# on that socket, Max ones included (OSQ-6, verified live: a Max pane on a tainted
# server read CLAUDE_CODE_USE_VERTEX=1).
#
# That is the INVERSE of the hole this module was written to close, and it is WORSE:
# the other mis-bills a session that already opted into billing; this one bills a
# session that NEVER ASKED. So the launcher scrubs these from the pane on EVERY path,
# and only --vertex re-adds them, explicitly, via `-e`.
#
#   SCRUB ALWAYS. OPT IN DELIBERATELY.
VERTEX_SESSION_KEYS = (
    "CLAUDE_CODE_USE_VERTEX",
    "CLOUD_ML_REGION",
    "ANTHROPIC_VERTEX_PROJECT_ID",
)

# Model pins. Dated snapshots use an "@" version separator on Vertex — NOT the
# hyphenated first-party form. Without the pins, the `opus` alias resolves to an
# OLDER Opus. And a pin alone is not enough: ANTHROPIC_MODEL overrides it, which
# is why ASSERTABLE_MODEL_OVERRIDES is compared against it. A pin you can override
# from the environment is a preference, not a pin.
MODEL_PINS = {
    "ANTHROPIC_DEFAULT_OPUS_MODEL"   : "claude-opus-4-8",
    "ANTHROPIC_DEFAULT_SONNET_MODEL" : "claude-sonnet-4-6",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL"  : "claude-haiku-4-5@20251001",
}

# P0 — THE SCRUB ATE THE FEATURE. The set a pane must be cleansed of DEPENDS ON THE PATH,
# and shipping ONE unconditional set is what made `--vertex` a lie.
#
# The launcher used to prepend `unset <PANE_UNSET_KEYS + VERTEX_SESSION_KEYS>` to the pane
# command ON BOTH PATHS. On the --vertex path it had just forwarded those exact three keys
# via `tmux -e`... and then the pane's own first command DELETED THEM. `--vertex` printed a
# METERED-BILLING banner and ran on Max.
#
# C1 (scrub the pane, not the launcher) and OSQ-6 (scrub on EVERY path, not just --vertex)
# are each CORRECT IN ISOLATION. The defect is their COMPOSITION with the `-e` forward —
# it lives in no single fix, only in the seam between two of them. RIGOR FAILS WHERE RELIEF
# LIVES: both were "done", both were green, and the green could not have come out otherwise
# (a pane that reads <unset> looks identical whether the hole is CLOSED or the feature is DEAD).
#
# It failed SAFE — no money burned. But THE BANNER LIED, AND THE BANNER IS WHAT A HUMAN TRUSTS.
# A guard that silently disables the feature it protects has not protected anything; it has
# just moved the failure somewhere nobody is looking.
#
# ---------------------------------------------------------------------------
# C5 (Rio, 2026-07-14) — THE PINS THEMSELVES ARE FORGEABLE, AND THE TEST HID IT.
# ---------------------------------------------------------------------------
#
# THE RULE, stated properly at last: EVERY KEY WE EMIT IS A KEY A TAINTED SERVER CAN FORGE.
# What --vertex hands the pane via `-e`, a frozen tmux server env can hand a MAX pane for
# free — so the MAX path must scrub EVERYTHING compose emits, not just the three toggle keys.
#
# MODEL_PINS were emitted by compose and scrubbed by NEITHER set. On the MAX path a stale
# ANTHROPIC_DEFAULT_OPUS_MODEL frozen into the tmux server rides straight into the pane and
# SILENTLY CHANGES WHICH MODEL THE SESSION RUNS — with every guard green, because no guard
# was looking. Not a billing leak; a MODEL SUBSTITUTION. Quieter, and harder to notice.
#
# AND THE TEST THAT EXISTED TO CATCH THIS SUBTRACTED THE ANSWER BEFORE ASKING THE QUESTION:
#
#     emitted = set( compose_vertex_env( env=CLEAN_ENV ) ) - set( MODEL_PINS )   # <-- !!
#     assert emitted == set( VERTEX_SESSION_KEYS )
#
# Its docstring said "a key we EMIT but never SCRUB is a key a tainted server can forge" —
# and then it removed, by name, the only keys for which that was true. A TEST WEAKENED UNTIL
# IT PASSED, wearing the docstring of the test that would have failed. Sixth guard-that-
# cannot-fail of this cascade, and it was sitting inside the fix for the fifth.
#
# On the --vertex path the pins are NOT scrubbed: we just forwarded them, and `-e` (session
# env) outranks the frozen server env. SCRUB ALWAYS WHAT IS HOSTILE. NEVER SCRUB WHAT YOU
# JUST FORWARDED. The path-dependence is the whole design, and it now covers every emitted key.
MAX_PANE_UNSET_KEYS = PANE_UNSET_KEYS + VERTEX_SESSION_KEYS + tuple( MODEL_PINS )

# OSQ-6 (restated, rev. 4): "Assert the tmux server env is Vertex-free — and, if NO
# server exists, that the one we create is BORN CLEAN." The launcher ships the
# born-clean half (the SERVER_SCRUB on `tmux new-session`). This constant is the
# EXISTING-server half's refusal set: what may never sit in a tmux server's global
# env, because every session on that socket inherits it — the toggle keys (a Max
# session that never asked gets billed) and the hostile set (Rio's C1 exploit: a
# frozen VERTEX_REGION_CLAUDE_4_8_OPUS routes Opus alone to another region, where
# it runs, bills, and logs nothing, while every launcher-shell guard stays green).
#
# The ASSERTABLE sets are deliberately NOT here: a GOOGLE_CLOUD_PROJECT frozen into
# a server is neutralized in the pane by the unset (PANE_UNSET_KEYS), and refusing
# on a key that some other, non-Lupin workflow legitimately parks in the server env
# is the guard-that-fires-on-a-valid-configuration bug (C4's lesson, one process over).
SERVER_TAINT_REFUSAL_KEYS = VERTEX_SESSION_KEYS + HOSTILE_ENV_KEYS


class VertexEnvError( RuntimeError ):
    """Raised when the Vertex environment cannot be composed safely. Fail loud."""


def assert_region_oracle_is_admissible( oracle, evidence ):
    """
    Refuse a region certification whose instrument cannot see regions.

    The MaaS OpenAI-compat endpoint returns a byte-identical 200 for a live, a dead and a fictional region. Prose warnings do not run, so this check runs at import, in every process that touches the toggle.
    That makes certifying a region from a 200 that could not have come out otherwise impossible, not just discouraged.
    It cannot catch a lie. A seat that probes the OpenAI-compat endpoint and then types oracle="rawPredict" defeats it. It makes the mistake structural and the fabrication an explicit false statement.

    Requires:
        - oracle and evidence are strings

    Ensures:
        - returns None when the oracle is admissible and the evidence corroborates it

    Raises:
        - VertexEnvError when the oracle is not in ADMISSIBLE_REGION_ORACLES, when
          the evidence is empty, when the evidence does not name the oracle it
          claims, or when the evidence carries the fingerprint of a region-blind surface
    """
    if oracle not in ADMISSIBLE_REGION_ORACLES:
        raise VertexEnvError(
            f"Refusing the region certification: '{oracle}' is not an admissible region oracle. "
            f"Admissible: {', '.join( ADMISSIBLE_REGION_ORACLES )}. A region oracle must be able "
            f"to COME OUT OTHERWISE ON THE REGION AXIS. The MaaS OpenAI-compat endpoint "
            f"(endpoints/openapi/chat/completions) cannot: it returned a byte-identical 200 for "
            f"'global', for the DEAD 'us-central1', and for the FICTIONAL 'narnia-1'. The metadata "
            f"GET cannot either (200 for a region that cannot serve). Neither can a quota row or a "
            f"flatPath. A LISTING IS NOT A CAPABILITY."
        )

    if not evidence:
        raise VertexEnvError(
            f"Refusing the region certification: oracle '{oracle}' was named with NO EVIDENCE. "
            f"An unevidenced certification is a claim, and this module exists because a claim "
            f"beat a measurement three revisions running. Record the request and what it returned."
        )

    if oracle not in evidence:
        raise VertexEnvError(
            f"Refusing the region certification: the evidence does not name the oracle it claims "
            f"('{oracle}'). Evidence: {evidence!r}. The evidence must record the call that was "
            f"actually made — an oracle field that no evidence corroborates is decoration."
        )

    for fragment in REGION_BLIND_EVIDENCE_FRAGMENTS:
        if fragment in evidence:
            raise VertexEnvError(
                f"Refusing the region certification: the evidence names '{fragment}' — the MaaS "
                f"OpenAI-compat surface, which IGNORES its own locations/{{REGION}} path segment. "
                f"Measured 2026-07-13: byte-identical 200s from a real region, a dead region, and "
                f"a region that does not exist. It certifies MODELS, never REGIONS. Certify with a "
                f"rawPredict that returned 200, or do not certify."
            )


def assert_certifications_are_provenanced( certifications ):
    """
    Refuse to load when any certified region lacks admissible provenance.

    It is called at import time, below the definition. The allowlist is the surface a future seat will widen.
So the guard sits on the act of widening it, not in a comment beside it.

    Requires:
        - certifications maps a region name to a record with 'oracle' and 'evidence'

    Ensures:
        - returns None when every region's provenance is admissible

    Raises:
        - VertexEnvError naming the offending region (the caller's mistake is a
          region, not a dict), with the instrument failure as the cause
    """
    for region, record in certifications.items():
        for field in CERTIFICATION_FIELDS:
            if field not in record or not record[ field ]:
                raise VertexEnvError(
                    f"Refusing the region certification for '{region}': the record has no "
                    f"'{field}'. A region may not be certified anonymously — name the instrument "
                    f"that proved it and what that instrument returned."
                )
        try:
            assert_region_oracle_is_admissible( record[ "oracle" ], record[ "evidence" ] )
        except VertexEnvError as error:
            raise VertexEnvError( f"Region '{region}': {error}" ) from error


# IMPORT-TIME. Not a test, not a comment — a load-bearing statement. A module that
# certifies a region from a region-blind instrument does not import, so it cannot
# launch, so it cannot bill. CERTIFIED_VERTEX_REGIONS is then DERIVED from the map
# it was validated against, which is why the two can never drift apart.
assert_certifications_are_provenanced( VERTEX_REGION_CERTIFICATIONS )

CERTIFIED_VERTEX_REGIONS = tuple( VERTEX_REGION_CERTIFICATIONS )


def _require( env, key ):
    """
    Read a required key from env, failing loud when absent or empty.

    Requires:
        - env is a mapping
        - key is a non-empty string

    Ensures:
        - returns the non-empty string value of env[ key ]

    Raises:
        - VertexEnvError if the key is absent or empty
    """
    value = env.get( key )
    if not value:
        raise VertexEnvError(
            f"{key} is not set. There is no safe default: guessing it would bill a project "
            f"nobody chose, in a region that may not serve the model."
        )
    return value


def assert_no_hostile_env( env ):
    """
    Refuse to launch when any variable that could silently subvert the toggle is present.

    This is a preflight guard: it runs before the first token, because a guard that fires after the billing event is not a guard.

    Requires:
        - env is a mapping of environment variables

    Ensures:
        - returns None when no hostile key is present

    Raises:
        - VertexEnvError naming every offending key, not just the first, so a caller who fixes one and re-runs should not discover the next one serially
    """
    offenders = [ key for key in HOSTILE_ENV_KEYS if env.get( key ) ]
    if offenders:
        raise VertexEnvError(
            "Refusing to launch: these variables would silently subvert the Vertex toggle — "
            f"{', '.join( sorted( offenders ) )}. They override the region PER MODEL, steal "
            "project precedence, defeat the model pins, redirect the endpoint, or bypass auth. "
            "Unset them (the --vertex path scrubs them inside the pane; this guard catches the "
            "case where scrubbing did not happen)."
        )


def assert_project_agreement( env, project_id ):
    """
    Refuse to launch when any variable disagrees with the resolved project.

    GOOGLE_CLOUD_PROJECT and GCLOUD_PROJECT take precedence over ANTHROPIC_VERTEX_PROJECT_ID, so a mismatch silently bills a different project.

    Requires:
        - env is a mapping; project_id is a non-empty string

    Ensures:
        - returns None when every project-bearing variable agrees with project_id

    Raises:
        - VertexEnvError on any disagreement
    """
    for key in ASSERTABLE_PROJECT_OVERRIDES:
        other = env.get( key )
        if other and other != project_id:
            raise VertexEnvError(
                f"Refusing to launch: {key}={other} disagrees with the resolved project "
                f"{project_id}. {key} takes PRECEDENCE, so this would bill a different "
                f"project — silently."
            )


def assert_region_is_certified( region ):
    """
    Refuse to launch on a region no rawPredict has ever certified.

    The region check is an allowlist because accepting any string let LUPIN_VERTEX_REGION=us-central1 compose cleanly, in a region where the model is not servable. The word "enforce" cannot do an allowlist's work.

    Requires:
        - region is a non-empty string

    Ensures:
        - returns None when region is in CERTIFIED_VERTEX_REGIONS

    Raises:
        - VertexEnvError naming the certified set, because a region that is merely
          listed, or merely has quota, is not a region that runs
    """
    if region not in CERTIFIED_VERTEX_REGIONS:
        raise VertexEnvError(
            f"Refusing to launch: '{region}' is not a CERTIFIED Vertex region. Certified: "
            f"{', '.join( CERTIFIED_VERTEX_REGIONS )}. A region is certified ONLY by a rawPredict "
            f"that returned 200 — never by the publisher-model metadata endpoint (it returns 200 "
            f"for us-central1, which CANNOT SERVE the model), never by the MaaS OpenAI-compat "
            f"endpoint (endpoints/openapi/chat/completions: byte-identical 200s from a real, a "
            f"dead, and a FICTIONAL region — it is BLIND to the region in its own path), never by "
            f"a quota row, never by a flatPath. If you have certified a new region with a real "
            f"call, add it to VERTEX_REGION_CERTIFICATIONS with the instrument and what it returned "
            f"— the import-time guard will check the instrument."
        )


def assert_model_pin_agreement( env ):
    """
    Refuse to launch when a model override disagrees with the pin it would defeat.

    An override that agrees with its pin is harmless (ANTHROPIC_MODEL=claude-opus-4-8 is what the pin asks for). Banning it outright would be a guard that fires on a valid configuration, the same defect as for the project variables.

    Requires:
        - env is a mapping

    Ensures:
        - returns None when every present override matches its pin

    Raises:
        - VertexEnvError on a disagreement, naming both values
    """
    for override_key, pin_key in ASSERTABLE_MODEL_OVERRIDES.items():
        value = env.get( override_key )
        if value and value != MODEL_PINS[ pin_key ]:
            raise VertexEnvError(
                f"Refusing to launch: {override_key}={value} DISAGREES with the pin "
                f"{pin_key}={MODEL_PINS[ pin_key ]}. {override_key} OVERRIDES the pin, so this "
                f"would silently run a different model than the one this session was authorized "
                f"and priced for."
            )


def pane_unset_keys( vertex_path ):
    """
    Return the keys the pane must unset before `claude` starts, which depend on the path.

    Max path: scrub everything, toggle keys included. A tmux server born from a Vertex shell freezes CLAUDE_CODE_USE_VERTEX into its env and hands it to every later session on that socket. A Max session never asked to be billed.
    Vertex path: scrub only the hostile and precedence set. The toggle keys are the feature here. They arrive via `tmux -e`, which sets the session env and outranks the frozen server env, so scrubbing them would kill `--vertex`.
    The rule is to scrub always what is hostile and never what you just forwarded. The decision is a branch, so it lives in Python, where branch coverage is measured; bash has no such instrument.

    Requires:
        - vertex_path is a bool: True on the --vertex path, False on the Max path

    Ensures:
        - returns PANE_UNSET_KEYS on the --vertex path — disjoint from compose_vertex_env()
        - returns MAX_PANE_UNSET_KEYS on the Max path — a strict superset, adding the toggle keys
    """
    if vertex_path:
        return PANE_UNSET_KEYS
    return MAX_PANE_UNSET_KEYS


def parse_tmux_global_env( show_environment_output ):
    """
    Parse `tmux show-environment -g` output into a mapping.

    tmux emits two line shapes: `KEY=value` (set in the server's global env) and `-KEY` (marked unset). Anything else is an instrument failure, for example a value carrying a newline, which line parsing cannot attribute.
    It fails loud rather than skipping, because a dropped line would let a hostile variable through the server check. "I could not parse" must never be reported as "the server is clean".

    Requires:
        - show_environment_output is a string, possibly empty
        - an empty string parses to an empty mapping; whether emptiness is trustworthy is the
          caller's burden, because a failed command and a clean server both print nothing, so
          the caller must check the tmux exit status

    Ensures:
        - returns a dict of the `KEY=value` entries
        - `-KEY` unset markers are excluded (the server saying "unset" is
          the state the guard wants)

    Raises:
        - VertexEnvError on a line that is neither `KEY=value` nor `-KEY`
    """
    server_env = {}
    for line in show_environment_output.splitlines():
        if not line or line.startswith( "-" ):
            continue
        if "=" not in line:
            raise VertexEnvError(
                f"Cannot parse `tmux show-environment -g` line {line!r}: it is neither "
                f"KEY=value nor -KEY. Refusing to guess — a mis-parsed line here is a "
                f"hostile variable silently waved through the server-env check."
            )
        key, _, value = line.partition( "=" )
        server_env[ key ] = value
    return server_env


def assert_server_env_is_vertex_free( server_env ):
    """
    Refuse when the tmux server's existing global env carries a Vertex toggle or hostile key.

    The pane unset cannot fix this. It cleanses one pane's shell, while the server's frozen env keeps handing the same keys to every other session on the socket. Scrubbing around a tainted server moves the failure to whoever looks last.
    The blast radius is intended: while the server env is tainted, every launch on this socket refuses, Max ones included. A tainted server mis-bills sessions that never asked, so the loud failure belongs to the one person who can fix it once.

    Requires:
        - server_env is a mapping (parse_tmux_global_env of the -g output)

    Ensures:
        - returns None when no refusal key carries a truthy value

    Raises:
        - VertexEnvError naming every offender, with per-key remediation
          (`tmux set-environment -g -u <KEY>`), never a server kill, which would
          take down every session on the socket
    """
    offenders = sorted( key for key in SERVER_TAINT_REFUSAL_KEYS if server_env.get( key ) )
    if offenders:
        remedies = "; ".join( f"tmux set-environment -g -u {key}" for key in offenders )
        raise VertexEnvError(
            f"Refusing to launch: the EXISTING tmux server's global env is TAINTED — "
            f"{', '.join( offenders )}. Every session on this socket inherits these keys "
            f"(OSQ-6): a Max session gets billed for a toggle it never asked for, or a "
            f"single model is routed to another region where it runs, bills, and logs "
            f"nothing. NOTE THE BLAST RADIUS: every launch on this socket will refuse "
            f"until the server env is cleansed — deliberately, because the alternative "
            f"is N sessions inheriting the taint silently. Cleanse surgically (no server "
            f"kill): {remedies}."
        )


def pane_guard( env=None, vertex_path=False ):
    """
    Verify inside the pane that its env is what its path promises, before `claude` starts.

    `claude` runs in the pane, on the frozen tmux server env the launcher never saw.
    A check in the launcher's shell guards the wrong process. The launcher writes this call into the pane command after the unset and before `claude`.
    The pane dies non-zero, before the first token, when it is not the environment its banner claims.

    Requires:
        - env is a mapping (defaults to os.environ, the pane's real env)
        - vertex_path is a bool: True on the --vertex path, False on the Max path

    Ensures:
        - returns None when the pane env matches what its path promises
        - on both paths, every key the pane was told to unset is gone; the unset and this check run in
          one shell, so a survivor means the scrub silently did not happen (for example an empty
          derivation, or an error hidden by 2>/dev/null)
        - on the Max path that scrub check is the whole guard: MAX_PANE_UNSET_KEYS includes the toggle
          keys, so a Max pane carrying CLAUDE_CODE_USE_VERTEX dies here instead of being billed
        - on the --vertex path the three toggle keys are present, CLAUDE_CODE_USE_VERTEX is "1", the
          region is certified and every model pin equals its pin, so a pane not on Vertex refuses to
          start instead of running on Max under a metered-billing banner

    Raises:
        - VertexEnvError naming every offending key, before `claude` starts
    """
    if env is None:
        env = os.environ

    survivors = sorted( key for key in pane_unset_keys( vertex_path ) if env.get( key ) )
    if survivors:
        raise VertexEnvError(
            f"Refusing to start claude: the pane scrub DID NOT HAPPEN (or did not cover) — "
            f"{', '.join( survivors )} survived into the pane env. The unset runs in this "
            f"same shell, so a survivor means the scrub list silently failed to derive or "
            f"apply (the F4 class). Fix the scrub; do not launch around it."
        )

    if vertex_path:
        missing = sorted( key for key in VERTEX_SESSION_KEYS if not env.get( key ) )
        if missing:
            raise VertexEnvError(
                f"Refusing to start claude: this pane claims --vertex but "
                f"{', '.join( missing )} never arrived. The `-e` forward failed or was "
                f"scrubbed (the P0: a metered-billing banner over a session running on "
                f"Max). The banner is what a human trusts — it does not get to lie."
            )

        if env[ "CLAUDE_CODE_USE_VERTEX" ] != "1":
            raise VertexEnvError(
                f"Refusing to start claude: CLAUDE_CODE_USE_VERTEX="
                f"{env[ 'CLAUDE_CODE_USE_VERTEX' ]!r} is not the '1' compose emits — this "
                f"value did not come from compose_vertex_env(), so its provenance is the "
                f"frozen server env or a tamper, not the launcher."
            )

        assert_region_is_certified( env[ "CLOUD_ML_REGION" ] )

        wrong_pins = sorted(
            pin for pin in MODEL_PINS if env.get( pin ) != MODEL_PINS[ pin ]
        )
        if wrong_pins:
            raise VertexEnvError(
                f"Refusing to start claude: {', '.join( wrong_pins )} disagree(s) with the "
                f"shipped MODEL_PINS. A --vertex pane whose pins are absent or altered runs "
                f"a model nobody authorized or priced — a SILENT MODEL SUBSTITUTION (C5), "
                f"quieter than a billing leak and harder to notice."
            )


def compose_vertex_env( env=None, project_id=None, region=None ):
    """
    Compose the Vertex environment for one process, failing loud on any hazard.

    It enforces a region that was certified once by a rawPredict call. It does not re-derive servability: the only truthful region oracle costs money, so a free launch-time probe cannot exist.
    The publisher-model metadata endpoint is no substitute, because it returns 200 for a region that cannot serve and 403 for one that can.

    Requires:
        - env is a mapping (defaults to os.environ)
        - project_id and region, when not given, are read from env as LUPIN_GCP_PROJECT_ID and
          LUPIN_VERTEX_REGION; there is no env-file fallback here

    Ensures:
        - returns a dict of the exact variables to export for this process only
        - CLOUD_ML_REGION == the certified LUPIN_VERTEX_REGION
        - ANTHROPIC_VERTEX_PROJECT_ID == the resolved project
        - all three model pins present, Haiku in "@"-form

    Raises:
        - VertexEnvError on a missing project or region, an uncertified region, a hostile
          variable, a project disagreement or a model-pin disagreement
    """
    if env is None:
        env = os.environ

    resolved_project = project_id if project_id else _require( env, "LUPIN_GCP_PROJECT_ID" )
    resolved_region  = region     if region     else _require( env, VERTEX_REGION_ENV_KEY )

    assert_region_is_certified( resolved_region )
    assert_no_hostile_env( env )
    assert_project_agreement( env, resolved_project )
    assert_model_pin_agreement( env )

    composed = {
        "CLAUDE_CODE_USE_VERTEX"      : "1",
        "CLOUD_ML_REGION"             : resolved_region,
        "ANTHROPIC_VERTEX_PROJECT_ID" : resolved_project,
    }
    composed.update( MODEL_PINS )
    return composed


def format_dry_run( composed ):
    """
    Render the composed environment for --dry-run: compose, assert, print, launch nothing.

    Requires:
        - composed is a mapping of environment variables

    Ensures:
        - returns a newline-joined `KEY=VALUE` listing, sorted for stable diffing
    """
    return "\n".join( f"{key}={composed[ key ]}" for key in sorted( composed ) )


def quick_smoke_test():
    """Exercise the happy path and each guard's failure branch."""
    import cosa.utils.util as du

    du.print_banner( "vertex_env smoke test", prepend_nl=True )

    base = { "LUPIN_GCP_PROJECT_ID": "proj-x", VERTEX_REGION_ENV_KEY: "global" }

    composed = compose_vertex_env( env=base )
    assert composed[ "CLOUD_ML_REGION" ]             == "global"
    assert composed[ "ANTHROPIC_VERTEX_PROJECT_ID" ] == "proj-x"
    assert composed[ "ANTHROPIC_DEFAULT_HAIKU_MODEL" ] == "claude-haiku-4-5@20251001"
    print( "✓ composes the happy path" )

    for hostile in ( "VERTEX_REGION_CLAUDE_4_8_OPUS", "GOOGLE_APPLICATION_CREDENTIALS", "ANTHROPIC_MODEL" ):
        try:
            compose_vertex_env( env={ **base, hostile: "x" } )
            raise AssertionError( f"guard did not fire for {hostile}" )
        except VertexEnvError:
            print( f"✓ refuses to launch on {hostile}" )

    try:
        compose_vertex_env( env={ **base, "GOOGLE_CLOUD_PROJECT": "other" } )
        raise AssertionError( "project-disagreement guard did not fire" )
    except VertexEnvError:
        print( "✓ refuses to launch on project disagreement" )

    try:
        compose_vertex_env( env={ VERTEX_REGION_ENV_KEY: "global" } )
        raise AssertionError( "missing-project guard did not fire" )
    except VertexEnvError:
        print( "✓ refuses to launch with no project" )

    print( "\nvertex_env smoke test PASSED" )


if __name__ == "__main__":
    quick_smoke_test()

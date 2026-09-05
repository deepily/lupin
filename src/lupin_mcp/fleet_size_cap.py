#!/usr/bin/env python3
"""
THE FLEET SIZE CAP — one number for the whole fleet, enforced at spawn.

RICK'S REQUEST, by voice 2026-09-03 (row `0ab1a095`). He had set a cap of four by
voice, counted six workers running, and had to read two managers the riot act to get it
back in line. A verbal cap is not a cap: it depends on every manager remembering it AND
doing the arithmetic. Neither happened — and the sentence itself ("four workers between
the two of you") was read three different ways by three sessions, which is why the number
has to live in one place and the control has to say what it counts.

=== HIS THREE RULINGS, answered by keypress. NOT re-derived here. ===

1. SCOPE — ONE NUMBER FOR THE WHOLE FLEET. The cap says 8, the fleet may run 8,
   whoever spawns them. Not per-manager. (The per-manager `spawn_cap` still exists and
   is a DIFFERENT limit: how many one call may launch at once.)

2. OVER CAP — REFUSE NEW SPAWNS, REAP NOBODY. Lowering the cap below the current count
   does not kill anything; the cap bites on the next spawn and the fleet drains
   naturally. ⇒ NOTHING IN THIS MODULE TERMINATES A SESSION, and that is a ruling, not
   an omission. A control that destroys work when dragged is not to be built.

3. WHO COUNTS — EVERY SESSION, MANAGERS INCLUDED. Not workers-only.

🔴 THE CONSEQUENCE OF RULING 3 THAT THE REFUSAL MUST CARRY. Because managers occupy the
cap, a cap at or below the number of live managers leaves ZERO room for workers — and a
manager spawning its own crew is refused by a cap it is itself consuming. That failure is
indistinguishable from a broken spawner unless the refusal says so, so
`refusal_for_spawn` reports the manager/worker split and names the zero-headroom case
outright. We spent 2026-09-03 measuring what a mislabelled failure costs; this one is
labelled at the source.

🔨 THE CEILING IS CONFIGURED, NOT DERIVED — SUPERSEDED 2026-09-03. The paragraph this
replaces is SUMMARISED rather than deleted, because it was right about a real hazard and
a reader who meets only the new rule will not know why the old one existed.

WHAT IT SAID: the ceiling is `len( persona pool )`, because a session needs a persona, so
the pool is the binding constraint — and hardcoding 18 in a second place is what Rick's
earlier ruling forbade.

WHAT HE RULED LATER THE SAME DAY, by voice: the maximum must be CONFIGURABLE in the
configuration manager so he can tweak it over time. That is `cc session fleet size cap
maximum`, shipping as 18. ⇒ Not a second hardcode — the config layer, which is where he
asked for it.

⚠️ THE OLD PARAGRAPH'S HAZARD IS REAL AND HAS NOT GONE AWAY. It has only stopped being
enforced silently. The pool is still the number of seats that can be FILLED; the key is
only the width of the dial. Raise the key above the pool and the spawns above it are
refused for want of a PERSONA, not for want of cap.

🔴 SO IT IS DELIBERATELY NOT CLAMPED TO THE POOL. A dial silently trimmed to 14 when the
operator typed 18 cannot be told apart from a key that was ignored, and this fleet spent
2026-09-03 measuring what a mislabelled failure costs.

⚠️ AND THERE IS NOTHING TO CLAMP TO. A `pool_shortfall()` reporter was written for a gap
that cannot exist and then removed on measurement: allocation falls through the named
pool to the overflow persona and then to UNBOUNDED `Extra-N` seats. 18 requested fills
18; 200 fills 200. The persona pool is not a ceiling on anything.

⚠️ AND THE POOL'S OWN COUNT IS NOT ITS SEAT COUNT: a pool entry with no `voice id` is
silently skipped by the loader, so `pool_size()` counts voice ids rather than names.
"""
from typing import Any, Callable, Dict, Iterable, Optional

# The fleet-wide default. Deliberately the same figure as the per-manager spawn cap so
# a fleet with one manager behaves as it did before this module existed.
DEFAULT_FLEET_CAP = 8

# The dial's ceiling when config cannot be read. Rick named 18 by voice on 2026-09-03 and
# the INI ships that value; this is the fallback for an unreadable config, not a second
# source of truth.
DEFAULT_FLEET_CEILING = 18

FLEET_CAP_KEY      = "cc session fleet size cap"
FLEET_CEILING_KEY  = "cc session fleet size cap maximum"
PERSONA_POOL_KEY   = "cc session voice persona pool"


def pool_size( config_mgr: Any ) -> int:
    """
    How many seats can actually be FILLED — the ALLOCATABLE persona count.

    Ensures:
        - counts only pool names carrying a non-empty `voice id`, because that is
          exactly what the pool loader does
        - returns 0 when config is absent or the pool is unreadable
        - never raises

🔴 A NAME IS NOT A SEAT. The pool loader silently SKIPS a pool entry whose
    `voice id` is missing or empty — right for allocation, a trap for counting.

    ⚠️ THE CONSEQUENCE IS SMALLER THAN IT FIRST LOOKED, NARROWED BY MEASUREMENT
    2026-09-03. The first cut of this module treated the pool as a CEILING on seats and
    shipped a `pool_shortfall()` warning that the dial was wider than the pool. That
    warning was for a gap that CANNOT EXIST: `pick_unallocated_persona` falls through
    the named pool to the overflow persona and then to UNBOUNDED `Extra-N` identities.
    Measured on the live config — 18 requested, 18 distinct seats filled (14 named,
    then `arnold`, then `extra 1/2/3`); 200 requested fills 200.

    ⇒ A VOICELESS POOL ENTRY COSTS A *NAME*, NOT A SEAT. The session still gets a
    persona; it gets `Extra-N` instead of the one somebody meant to add.

    ⚠️ AND THE FALL-THROUGH WAS DOCUMENTED ALL ALONG, in the `spawn_sessions` contract.
    Two of us read past it and went looking at an ElevenLabs key for voice ids nobody
    needed. The mechanism was in plain sight; we did not read it.
    """
    if config_mgr is None:
        return 0
    try:
        raw = config_mgr.get( PERSONA_POOL_KEY, default="", return_type="string", silent=True )
    except Exception:
        return 0
    names = [ n.strip() for n in ( raw or "" ).split( "," ) if n.strip() ]
    fillable = 0
    for name in names:
        try:
            vid = config_mgr.get( f"cc session voice persona {name} voice id",
                                  default="", return_type="string", silent=True )
        except Exception:
            vid = ""
        if ( vid or "" ).strip():
            fillable += 1
    return fillable


def resolve_fleet_ceiling( config_mgr: Any ) -> int:
    """
    The largest value the fleet-size dial may take — READ FROM CONFIGURATION.

    Ensures:
        - returns `cc session fleet size cap maximum` when it can be read
        - returns DEFAULT_FLEET_CEILING when config is absent or the key is unset
        - a value below 1 clamps to 1
        - is NOT clamped to the persona pool size, which is not a ceiling on seats
        - never raises

    🔨 CONFIGURED, PER RICK'S 2026-09-03 RULING BY VOICE: the maximum must be tweakable
    in the configuration manager over time. The module docstring carries the SUPERSEDED
    derive-from-the-pool rule and the hazard it was protecting against — read it before
    "fixing" this back.
    """
    if config_mgr is None:
        return DEFAULT_FLEET_CEILING
    try:
        value = config_mgr.get( FLEET_CEILING_KEY, default=DEFAULT_FLEET_CEILING,
                                return_type="int", silent=True )
    except Exception:
        value = DEFAULT_FLEET_CEILING
    if value is None:
        value = DEFAULT_FLEET_CEILING
    return max( 1, int( value ) )


def resolve_fleet_cap( config_mgr: Any, disk_fn: Optional[ Callable[ [], Optional[ int ] ] ] = None ) -> int:
    """
    The configured fleet cap, clamped into 1..ceiling.

    Ensures:
        - returns DEFAULT_FLEET_CAP when config is absent or the key is unset
        - a value below 1 clamps to 1; a value above the ceiling clamps to the ceiling
        - never raises

    ⚠️ CLAMPED RATHER THAN REJECTED because this is read on the SPAWN path. A malformed
    INI value must not take spawning down for the whole fleet — it must land somewhere
    sane and let the operator see the number on the control.

    🔴 `disk_fn` IS THE SEAM THAT MAKES THE OPERATOR'S DIAL BITE. When supplied and it
    returns an int, that value WINS over the configuration manager. Passing None — the
    default — leaves this function byte-identical to what it was before the slider
    existed, which is why every caller and test written against the old signature is
    unaffected.

    WHY IT IS NEEDED: `ConfigurationManager` is a process-lifetime singleton (the
    `@singleton` decorator caches the instance) with no mtime check and no reload path,
    and the cap is enforced inside the long-running HOST MCP process. Without a fresher
    read, an operator's write reaches the file and the enforcing process keeps its
    boot-time number until somebody bounces the MCP — a control that changes nothing
    until a restart, which is exactly the defect that held this slider back.

    ⚠️ IT IS NOT A SECOND SOURCE OF TRUTH. `default_disk_cap_reader` reads the SAME key
    in the SAME file the configuration manager loaded; it just reads it later. A second
    source would be a value stored somewhere else that has to be kept in step.

    ⚠️ AND THE CEILING IS **NOT** GIVEN THE SAME TREATMENT, deliberately. Only the cap is
    written by the slider; the maximum is Rick's own hand-edited key, and giving it a
    fresh read too would be a mechanism nothing asks for.
    """
    ceiling = resolve_fleet_ceiling( config_mgr )

    if disk_fn is not None:
        try:
            from_disk = disk_fn()
        except Exception:
            from_disk = None
        if from_disk is not None:
            return max( 1, min( int( from_disk ), ceiling ) )

    if config_mgr is None:
        return min( DEFAULT_FLEET_CAP, ceiling )
    try:
        value = config_mgr.get( FLEET_CAP_KEY, default=DEFAULT_FLEET_CAP,
                                return_type="int", silent=True )
    except Exception:
        value = DEFAULT_FLEET_CAP
    if value is None:
        value = DEFAULT_FLEET_CAP
    return max( 1, min( int( value ), ceiling ) )


COUNTING_MANAGER_ROLE = "manager"

# The three states a seat can be in for COUNTING purposes. `unknown` is not a hedge and
# not a default — it is the honest answer for a bridge that could not be read, and it
# exists because resolving that case into "manager" concealed a degraded classifier
# behind a clean-looking split (María's ruling, 2026-09-04).
SEAT_MANAGER = "manager"
SEAT_WORKER  = "worker"
SEAT_UNKNOWN = "unknown"


def counted_as_manager( role: Optional[ str ], spawned_by: Optional[ str ] ) -> bool:
    """
    THE COUNTING DEFINITION OF "MANAGER" — this module's own predicate, and the
    ONLY one `census()` consumes.

    Requires:
        - role is the bridge's `role` field, or None
        - spawned_by is the bridge's `spawned_by` field (the spawning manager's
          session id), or None

    Ensures:
        - returns True iff role == "manager", OR the session declares NEITHER a
          role NOR a lineage
        - returns False for any other declared role, and for any session carrying
          a lineage without an explicit manager role
        - blank/whitespace strings are treated as absent, because that is how they
          reach a bridge
        - a pure function of two fields — no IO, no environment, no name lookup
        - never raises

    🔴 ROLE COMES FROM WHAT A SESSION DECLARES OR FROM ITS LINEAGE. NEVER FROM ITS
    NAME. María's ruling, 2026-09-04 21:04, on a defect measured the same evening:
    `is_manager_figure` classifies a session as a manager when its PERSONA NAME is a
    named entry of `COSA_VOICE_PREFERRED_PERSONA__<PROJECT>`, and that name rule WINS
    OVER an explicit declared role. Measured on nine live seats: Cheech carried
    `role="author"` and `spawned_by=21dff055` — a worker by both of its own inputs —
    and counted as a MANAGER, while John carried the IDENTICAL declared role and
    counted as a worker. The only difference between them was the name.

    ⇒ The census read 4 managers / 5 workers where the bridges say 3 / 6. ONE
    misclassification, and it moves a number Rick spins managers down over.

    🔴 THIS IS DELIBERATELY A SECOND PREDICATE, AND `is_manager_figure` MUST NOT MOVE.
    That one answers an AUTHORIZATION question — the store's managers-first write gate
    — where the fail-CLOSED degrade is ratified and the name rule is the ratified
    §2.1 IMPLICIT source. This one answers a COUNTING question. **A SIMILAR NAME IS
    NOT A SHARED PREDICATE**: folding them together would either loosen a write gate
    or import a name heuristic into a census, and one of those is a security change.
    Two questions, two predicates, each stated where it is answered.

    ⚠️ AN UNPARENTED, UNDECLARED SEAT COUNTS AS A MANAGER, AND THAT IS THE ONE ARM
    HERE THAT IS A POLICY CALL RATHER THAN A MEASUREMENT. It is María's rule applied
    as given: a session in nobody's lineage that declared no role is a top-level seat.
    On the nine measured it is right three times (María, Mr. Radio, Tiffany) and wrong
    never — but Tiffany satisfies the name rule too, so that row has TWO sufficient
    causes and cannot discriminate between them. Whether an unparented seat SHOULD
    count as a manager is open; this encodes the ruling, not a finding.

    ⚠️ AND THE EXPLICIT-MANAGER ARM IS A REFINEMENT OF THE RULE AS SPOKEN, NOT A
    RESTATEMENT OF IT. "Worker if a declared role OR a lineage is present" reproduces
    all nine live seats because NONE of them carries `role == "manager"`. Applied
    literally to a session spawned INTO a manager role it would count that manager as
    a worker. The explicit check is placed FIRST so a declaration is never overruled
    by the fallback — which is the same failure the name rule commits, in the other
    direction.
    """
    declared = ( role or "" ).strip()
    lineage  = ( spawned_by or "" ).strip()

    if declared == COUNTING_MANAGER_ROLE:
        return True
    if declared:
        return False
    return not lineage


def read_counting_fields( session_id: str, _find_path: Optional[ Callable ] = None ):
    """
    Read ( role, spawned_by ) off a session's bridge file, for `counted_as_manager`.

    Requires:
        - session_id is a session id string (full UUID or 8-char prefix)
        - _find_path is the bridge locator, injectable for tests

    🔴 IT RETURNS `None` — NOT `( None, None )` — WHEN THE BRIDGE CANNOT BE READ, AND
    THAT DISTINCTION IS THE WHOLE REASON THIS FUNCTION HAS ITS OWN RETURN CONTRACT.
    A seat whose bridge is corrupt and a seat that genuinely declares nothing are
    DIFFERENT FACTS, and the first cut of this module collapsed them: both arrived as
    ( None, None ) and both counted as managers.

    ⚠️ I DEFENDED THAT COLLAPSE AS "THE SAFE DIRECTION FOR A CAP" — the seat stays in
    `total`, so the cap can only bind EARLIER, never later — and María overruled it on
    2026-09-04. Safe-for-the-cap is not the same as true-for-the-reader: a degraded
    classification rendered as "manager" is a confident answer to a question nobody
    could answer, and it CONCEALS that the classifier is degraded. The seat still
    counts toward `total`; what changes is that the SPLIT says so.

    Ensures:
        - returns ( role_or_None, spawned_by_or_None ) when the bridge was READ
        - returns None when it could not be — missing, unlocatable, or unparseable
        - never raises
    """
    import json

    try:
        if _find_path is None:
            from lupin_cli.claude_code.hooks.lib.session_bridge import find_session_path_by_id
            _find_path = find_session_path_by_id
        path = _find_path( session_id )
        if not path:
            return None
        with open( path ) as f:
            data = json.load( f )
        return data.get( "role" ), data.get( "spawned_by" )
    except Exception:
        return None


def default_counting_classifier( session_id: str, _find_path: Optional[ Callable ] = None ) -> str:
    """
    `census()`'s default classifier: is this session counted as a manager?

    Requires:
        - session_id is a session id string

    Ensures:
        - returns SEAT_UNKNOWN when the bridge could not be read
        - otherwise SEAT_MANAGER / SEAT_WORKER per `counted_as_manager`
        - never raises

    The replacement for `is_manager_figure` at the CENSUS call sites — the spawn gate
    and the arbiter pane. It keeps the one-argument shape, and returns a LABEL rather
    than a bool so the degraded case has somewhere to go.
    """
    fields = read_counting_fields( session_id, _find_path=_find_path )
    if fields is None:
        return SEAT_UNKNOWN
    return SEAT_MANAGER if counted_as_manager( *fields ) else SEAT_WORKER


def census( sessions: Iterable, is_manager_fn: Callable[ [ str ], bool ] ) -> Dict[ str, int ]:
    """
    Split the live fleet into managers and workers.

    Requires:
        - sessions is an iterable of (bridge_path, session_id, persona) triples —
          the shape `find_active_voice_persona_sessions()` returns
        - is_manager_fn( session_id ) -> bool; the canonical `is_manager_figure`

    Ensures:
        - returns { total, managers, workers, unknown } with
          managers + workers + unknown == total
        - a session whose classification RAISES counts as UNKNOWN, never dropped — an
          unclassifiable session still occupies a seat, and losing it from the total
          would let the fleet exceed its own cap through a classifier bug

    🔴 UNKNOWN IS A REAL STATE, NOT A HEDGE (María's ruling, 2026-09-04). This used to
    count a failed classification as a WORKER — a guess, rendered as a fact, in the one
    field whose job is to tell a reader who is occupying the cap. Reported as `unknown`
    it says both things at once: the seat is taken, and we could not read it.

    ⚠️ WHAT DID NOT CHANGE: the seat is still in `total`, so the cap still binds on it.
    The degrade costs the SPLIT, never the ceiling.

    ⚠️ THE CLASSIFIER IS INJECTED so this is testable without a live bridge. It may
    return a LABEL — SEAT_MANAGER / SEAT_WORKER / SEAT_UNKNOWN — or a BOOL, which is the
    shape of the ratified `is_manager_figure`. The bool form can never produce an
    unknown, which is exactly right: that predicate answers an authorization question
    and its fail-CLOSED degrade is deliberate. Accepting both is a compatibility
    boundary, not a second definition of "manager".
    """
    total = managers = workers = unknown = 0
    for entry in sessions:
        total += 1
        session_id = entry[ 1 ] if isinstance( entry, ( tuple, list ) ) and len( entry ) > 1 else entry
        try:
            verdict = is_manager_fn( session_id )
        except Exception:
            unknown += 1              # counted in total; the split says it could not be read
            continue
        if verdict is True or verdict == SEAT_MANAGER:
            managers += 1
        elif verdict == SEAT_UNKNOWN:
            unknown += 1
        else:
            workers += 1
    return { "total": total, "managers": managers, "workers": workers, "unknown": unknown }


def refusal_for_spawn( requested: int, counts: Dict[ str, int ], cap: int ) -> Optional[ str ]:
    """
    The refusal message, or None when the spawn fits.

    Requires:
        - requested >= 1
        - counts is a census() result
        - cap >= 1

    Ensures:
        - returns None iff counts["total"] + requested <= cap
        - otherwise returns a message naming the CAP, the CURRENT TOTAL, the
          MANAGER/WORKER SPLIT, how many were requested and how many would fit
        - names UNCLASSIFIED seats when `counts["unknown"]` is non-zero, and stays
          silent about them when it is zero
        - names the zero-headroom case explicitly when managers alone meet the cap
        - never raises, never reaps

    🔴 EVERY NUMBER A CALLER NEEDS IS IN THE STRING. Rick: "it would simply fail and tell
    you why, that you are already at limit." A spawn that fails without naming the cap
    sends a manager hunting a bug that does not exist.
    """
    total, managers, workers = counts[ "total" ], counts[ "managers" ], counts[ "workers" ]
    unknown = counts.get( "unknown", 0 )
    if total + requested <= cap:
        return None

    # 🔴 THE UNCLASSIFIED CLAUSE APPEARS ONLY WHEN THERE ARE UNCLASSIFIED SEATS. A
    # notice that fires on every refusal carries no information on the one refusal
    # where the classifier was actually degraded.
    split    = f"{managers} manager(s), {workers} worker(s)"
    if unknown:
        split += f", {unknown} unclassified"
    headroom = max( 0, cap - total )
    lines = [
        f"FLEET CAP REFUSED THIS SPAWN — the cap is {cap} and the fleet is already "
        f"running {total} ({split}). "
        f"Requested {requested}; {headroom} seat(s) free."
    ]
    if unknown:
        lines.append(
            f"⚠️ {unknown} SEAT(S) COULD NOT BE CLASSIFIED — their bridge was missing or "
            f"unreadable. They are counted in the total, so the cap is right; the "
            f"manager/worker split above is INCOMPLETE, not wrong."
        )
    if managers >= cap:
        lines.append(
            f"⚠️ THE {managers} LIVE MANAGER(S) ALONE MEET OR EXCEED THE CAP OF {cap}, so "
            f"there is no room for a worker at any time — a manager is being refused by a "
            f"cap it is itself consuming. Raise the cap above {managers} or reap a manager; "
            f"lowering the cap will never free a seat, because it reaps nobody by design."
        )
    lines.append(
        "Nothing was terminated: the cap refuses NEW spawns and leaves running seats "
        "alone (Rick's ruling), so the fleet drains as sessions finish."
    )
    return " ".join( lines )
def config_file_path() -> str:
    """
    The configuration FILE the fleet cap is read from and written to.

    Ensures:
        - returns `<project root>/src/conf/lupin-app.ini`
        - resolves the root at CALL time, so it is correct in the container
          (LUPIN_ROOT=/var/lupin) and on the host (LUPIN_ROOT=<the checkout>)

    🔴 THE CONTAINER AND THE HOST RESOLVE TO THE SAME PHYSICAL FILE, and that is
    what makes a browser write reach the spawn path at all. Measured 2026-09-04:
    `docker inspect lupin-rest-dev` reports `<checkout>/src -> /var/lupin/src` with
    `rw=true`, and the host MCP process carries `LUPIN_ROOT=<checkout>` — so
    `/var/lupin/src/conf/lupin-app.ini` and `<checkout>/src/conf/lupin-app.ini` are
    one file with two names, and both processes load the same `Lupin: Development`
    block.

    ⚠️ THIS CORRECTS A CLAIM SHIPPED WITH THE READ-ONLY DIAL. That pass recorded
    that a write would need "shared storage — a docker-compose mount, an env var,
    and a --force-recreate of both rest services". The mount it asked for already
    exists; the claim was reasoned rather than measured. It is left named here
    rather than quietly deleted, because it is the obvious conclusion and the next
    reader will reach it too.
    """
    import cosa.utils.util as cu
    return cu.get_project_root() + "/src/conf/lupin-app.ini"


def default_disk_cap_reader() -> Optional[ int ]:
    """
    Read `cc session fleet size cap` FRESH from the configuration file.

    Ensures:
        - returns the integer on disk, or None when it cannot be read unambiguously
        - never raises

    🔴 WHY A FRESH READ EXISTS, AND IT IS THE THING THAT MAKES THE DIAL BITE.
    `ConfigurationManager` is a process-lifetime singleton — the `@singleton`
    decorator caches the instance, and the class carries no mtime check and no
    reload path. The cap is enforced inside the HOST MCP process, which is
    long-running. So without this, an operator's write would reach the file and the
    enforcing process would keep its boot-time number until somebody bounced the
    MCP: a control that changes nothing until a restart, which is precisely the
    defect that held this slider back in the first place.

    ⚠️ IT IS NOT A SECOND SOURCE OF TRUTH. It reads the SAME key in the SAME file
    the configuration manager loaded — just later. Two sources would be a value
    stored somewhere else that has to be kept in step; this is one value read at a
    fresher moment.
    """
    try:
        from lupin_mcp import fleet_cap_ini_io
        return fleet_cap_ini_io.read_int_from_disk( config_file_path(), FLEET_CAP_KEY )
    except Exception:
        return None

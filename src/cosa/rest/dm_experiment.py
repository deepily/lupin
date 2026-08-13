"""
DM verbosity two-arm pilot — runtime policy object (plan item 3).

Loads the immutable 28-slot experiment schedule and the pilot config ONCE, never
per request, and resolves the arm covering an arrival instant. `get_dm_feedback_arm()`
in dm.py rebuilds a ConfigurationManager on EVERY DM (dm.py:488-505); this module
exists so the experiment path does NOT copy that anti-pattern — the schedule + config
are read once into a singleton and every send reads the cached object.

⚠️ assignment_at NEVER reads the clock. The caller (execute_dm_send) resolves the
arrival instant ONCE and passes it in, so a send that crosses an hour boundary is
scored against a single arm rather than split across two.

Path indirection mirrors dm.py's `_DM_TRAFFIC_JSONL` / `_DM_TRAFFIC_PRODUCTION_PATH`
pair (dm.py:351-357): tests patch `_DM_SCHEDULE_PATH` to a fixture while the frozen
`_DM_SCHEDULE_PRODUCTION_PATH` stays the value a future self-guard would compare
against — a redirect that never blinds the guard to its own failure.

Fail-safe: a missing or malformed schedule file yields an INACTIVE policy
(assignment_at always None) — the experiment is simply off and ordinary
non-experimental DM behaviour applies. This is why the module never raises at import:
before the schedule JSON is committed, or after a bad edit, the fleet keeps sending.

Design: src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.04-dm-verbosity-pilot-plan.md §3
"""

import json
from datetime import datetime, timedelta, timezone

import cosa.utils.util as cu

# The ONE TRUE schedule path, and its frozen twin the redirect fixture never touches.
_DM_SCHEDULE_PATH            = cu.get_project_root() + "/src/conf/dm-experiment-schedule.json"
_DM_SCHEDULE_PRODUCTION_PATH = _DM_SCHEDULE_PATH

# The two arm labels the schedule may name. An override or a slot arm outside this
# set is treated as no-arm (baseline) rather than silently trusted.
VALID_ARMS = ( "blind", "rejecting" )


def _normalize_exempt( value ):
    """
    Normalize the exempt-sender config into a frozenset of session ids.

    The arbiter presents under more than one identity (arbiter-runner, the dead
    heartbeat-arbiter path, and the lupin-arbiter-app-8001 roster string), so the key
    is a COMMA-SEPARATED list, not one id — setting all three lets the smoke confirm
    which fires without a code change (Cheech, 2026-08-03).

    Requires:
        - value is None, a comma-separated string, or an iterable of strings

    Ensures:
        - returns a frozenset of stripped, non-empty ids (empty for None / blank)
    """
    if value is None:
        return frozenset()
    if isinstance( value, str ):
        value = value.split( "," )
    return frozenset( part.strip() for part in value if part and part.strip() )


def _parse_slots( slot_dicts ):
    """
    Parse raw slot dicts (from the JSON, or a test) into (start, end, public) tuples.

    Requires:
        - slot_dicts is an iterable of dicts each carrying `slot_id`, `arm`,
          `start_utc`, and either `end_utc` or nothing (end defaults to start + 1h)

    Ensures:
        - start/end are timezone-aware UTC datetimes (a naive ISO string is read AS
          UTC rather than rejected — the generator writes "+00:00", this is belt)
        - `public` is the caller-facing slot dict (slot_id, arm, local_hour, start_utc)
        - preserves input order

    Raises:
        - KeyError if a slot lacks slot_id / arm / start_utc (fail loud — a malformed
          schedule must not silently drop slots)
    """
    parsed = []
    for raw in slot_dicts:
        start = datetime.fromisoformat( raw[ "start_utc" ] )
        if start.tzinfo is None: start = start.replace( tzinfo=timezone.utc )
        end_raw = raw.get( "end_utc" )
        end     = datetime.fromisoformat( end_raw ) if end_raw else start + timedelta( hours=1 )
        if end.tzinfo is None: end = end.replace( tzinfo=timezone.utc )
        public = {
            "slot_id"    : raw[ "slot_id" ],
            "arm"        : raw[ "arm" ],
            "local_hour" : raw.get( "local_hour" ),
            "start_utc"  : raw[ "start_utc" ],
        }
        parsed.append( ( start, end, public ) )
    return parsed


class ExperimentPolicy:
    """
    An immutable snapshot of the pilot: the parsed slot table plus the four config
    values (override arm + reason, reject threshold, exempt sender). Built once and
    read by every in-window send; never mutated after construction.
    """

    def __init__( self, *, slots, schedule_id, experiment, override_arm, override_reason,
                  reject_threshold, exempt_sender_session_ids ):
        """
        Requires:
            - slots is a list of (start, end, public) tuples from _parse_slots
            - override_arm is one of VALID_ARMS or None
            - reject_threshold is a positive int (word count)
            - exempt_sender_session_ids is a frozenset of exempt sender session ids

        Ensures:
            - stores each field verbatim; the object is treated as read-only
        """
        self._slots                    = slots
        self.schedule_id               = schedule_id
        self.experiment                = experiment
        self.override_arm              = override_arm
        self.override_reason           = override_reason
        self.reject_threshold          = reject_threshold
        self.exempt_sender_session_ids = exempt_sender_session_ids

    def assignment_at( self, arrival_utc ):
        """
        Resolve the experiment slot covering an instant.

        Requires:
            - arrival_utc is a timezone-aware datetime

        Ensures:
            - returns a COPY of the slot's public dict inside a declared interval
              (start_utc <= arrival_utc < end_utc)
            - returns None outside every interval — the experiment is inactive there
              and ordinary non-experimental behaviour applies
            - never re-reads the clock (arrival_utc is the sole time input)

        Raises:
            - ValueError if arrival_utc is naive (a naive instant cannot be placed on
              the UTC schedule without guessing a zone — fail loud, never guess)
        """
        if not isinstance( arrival_utc, datetime ) or arrival_utc.tzinfo is None:
            raise ValueError( "arrival_utc must be a timezone-aware datetime" )
        arrival_utc = arrival_utc.astimezone( timezone.utc )
        for start, end, public in self._slots:
            if start <= arrival_utc < end:
                return dict( public )
        return None


def make_policy( *, slots=None, schedule_id="dm-verbosity-two-arm-v1", experiment="two-arm-v1",
                 override_arm=None, override_reason="manual override",
                 reject_threshold=150, exempt_sender_session_ids=None ):
    """
    Build an ExperimentPolicy from raw slot dicts + config values.

    The inline/test builder: production goes through load_default_policy (which reads
    the JSON + ini), tests call this directly with fixture slots and pinned config so
    a frozen-clock assertion never depends on the wall clock or the ini.

    Requires:
        - slots is a list of raw slot dicts (start_utc/end_utc/arm/slot_id) or None
        - exempt_sender_session_ids is None, a comma-separated string, or an iterable

    Ensures:
        - override_arm outside VALID_ARMS is coerced to None (no-arm / baseline)
        - exempt ids are normalized to a frozenset
        - returns a ready-to-use ExperimentPolicy
    """
    if override_arm is not None and override_arm not in VALID_ARMS:
        override_arm = None
    return ExperimentPolicy(
        slots                     = _parse_slots( slots or [] ),
        schedule_id               = schedule_id,
        experiment                = experiment,
        override_arm              = override_arm,
        override_reason           = override_reason,
        reject_threshold          = reject_threshold,
        exempt_sender_session_ids = _normalize_exempt( exempt_sender_session_ids ),
    )


def make_inactive_policy():
    """
    An empty-schedule policy: assignment_at always None.

    Ensures:
        - returns a policy that puts EVERY instant outside the window — used by the
          existing send-path test harness so those baseline tests stay deterministic
          regardless of the wall clock (else a run during the live window would flip
          them into the experiment path)
    """
    return make_policy( slots=[], schedule_id=None, experiment=None )


def _load_schedule( path ):
    """
    Read the immutable schedule JSON.

    Ensures:
        - returns ( slots, schedule_id, experiment ) on success
        - returns ( [], None, None ) — an INACTIVE schedule — for a missing or
          malformed file, so the experiment is simply off and DMs keep flowing

    Raises:
        - None (all read/parse failures degrade to the inactive tuple)
    """
    try:
        with open( path, encoding="utf-8" ) as f:
            data = json.load( f )
    except ( FileNotFoundError, OSError, json.JSONDecodeError, ValueError ):
        return [], None, None
    slots       = _parse_slots( data.get( "slots", [] ) )
    schedule_id = data.get( "schedule_id" )
    experiment  = data.get( "experiment", "two-arm-v1" )
    return slots, schedule_id, experiment


def _load_config():
    """
    Read the four pilot config values from lupin-app.ini ONCE.

    Ensures:
        - returns ( override_arm, override_reason, reject_threshold, exempt_session_ids )
        - override_arm is a VALID_ARMS member or None (blank/junk → None); it is
          lower-cased and stripped
        - reject_threshold defaults to 150; exempt_session_ids is a frozenset parsed
          from the comma-separated key (blank → empty set)
        - any config-read failure returns the safe defaults (no override, 150, no
          exemption) rather than raising — the experiment must never fail to load

    Raises:
        - None
    """
    from cosa.config.configuration_manager import ConfigurationManager
    try:
        cm               = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        override_arm     = ( cm.get( "dm experiment arm override", default="", return_type="string" ) or "" ).strip().lower() or None
        if override_arm not in ( None, ) + VALID_ARMS:
            override_arm = None
        override_reason  = cm.get( "dm experiment arm override reason", default="manual override", return_type="string" )
        reject_threshold = cm.get( "dm experiment reject threshold words", default=150, return_type="int" )
        exempt_session   = _normalize_exempt( cm.get( "dm experiment exempt sender session id", default="", return_type="string" ) )
    except Exception:
        return None, "manual override", 150, frozenset()
    return override_arm, override_reason, reject_threshold, exempt_session


def is_suspended():
    """
    True when the two-arm pilot is suspended by config (Rick, 2026-08-13).

    SUSPENDED, NOT DELETED. The schedule JSON stays on disk and every row already
    collected stays analysable — the `blind`-vs-`rejecting` question ("does refusing
    an over-long DM make senders write shorter") remains its own finished study. This
    only stops the pilot from RUNNING, so it cannot interact with the tutor now
    shipping fleet-wide: a rejecting hour would refuse the very messages the tutor
    exists to shorten, and no row could then say which mechanism did the work.

    Ensures:
        - returns the `dm experiment suspended` flag, defaulting to True
        - a config-read failure returns True — the SAFE direction. An experiment that
          silently resumed because a config read failed would gate live fleet traffic
          on an arm nobody chose; the tutor is the live treatment now, so the pilot
          staying off is the state that matches the ruling.

    Raises:
        - nothing
    """
    from cosa.config.configuration_manager import ConfigurationManager
    try:
        cm = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        return cm.get( "dm experiment suspended", default=True, return_type="boolean" )
    except Exception:
        return True


def load_default_policy():
    """
    Build the production policy from the committed schedule JSON + the ini config.

    Ensures:
        - reads _DM_SCHEDULE_PATH (patchable) and the ini exactly once
        - a missing schedule yields an inactive policy (assignment_at always None)
    """
    # SUSPENDED (Rick, 2026-08-13) → an INACTIVE policy, which is the same shape a
    # missing schedule already produces: assignment_at() returns None for every
    # instant, so execute_dm_send takes the baseline path and the tutor is the only
    # treatment in force. Suspending HERE rather than at the call site means every
    # reader of the policy — the gate, the corpus stamp, the pool-status view —
    # agrees the pilot is off, instead of one branch believing it is still running.
    if is_suspended():
        return make_inactive_policy()

    slots, schedule_id, experiment                              = _load_schedule( _DM_SCHEDULE_PATH )
    override_arm, override_reason, reject_threshold, exempt_ids  = _load_config()
    return ExperimentPolicy(
        slots                     = slots,
        schedule_id               = schedule_id,
        experiment                = experiment,
        override_arm              = override_arm,
        override_reason           = override_reason,
        reject_threshold          = reject_threshold,
        exempt_sender_session_ids = exempt_ids,
    )


# The process-wide singleton. Loaded ONCE on first use (application startup imports
# dm.py, whose first in-window send triggers the load), never rebuilt per request.
# reset_policy() / set_policy() are the test + operator seams.
_POLICY = None


def get_policy():
    """
    Return the process singleton policy, loading it once on first use.

    Ensures:
        - the schedule JSON + ini are read at most once across the process lifetime
          (until reset_policy / set_policy replaces the singleton)
    """
    global _POLICY
    if _POLICY is None:
        _POLICY = load_default_policy()
    return _POLICY


def set_policy( policy ):
    """
    Replace the singleton (test/operator seam).

    Ensures:
        - subsequent get_policy() / assignment_at() calls read `policy`
    """
    global _POLICY
    _POLICY = policy


def reset_policy():
    """
    Drop the singleton so the next get_policy() reloads from disk + ini.

    Ensures:
        - _POLICY is None; the next access rebuilds it (used after an operator edits
          the schedule or config and bounces, and by tests to restore the default)
    """
    global _POLICY
    _POLICY = None


def assignment_at( arrival_utc ):
    """
    Module-level convenience: resolve the slot covering `arrival_utc` via the singleton.

    Requires:
        - arrival_utc is a timezone-aware datetime

    Ensures:
        - returns the slot's public dict inside a declared interval, else None
        - never re-reads the clock
    """
    return get_policy().assignment_at( arrival_utc )

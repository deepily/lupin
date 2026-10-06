"""
Cross-check the two env-var families that both answer "who is a manager".

Two independent environment-variable families answer the same question and are
read by different consumers, and nothing compared them:

    `COSA_VOICE_MANAGERS__<PROJECT>` is the declared-manager roster.
        Consumers: the :8001 arbiter's fleet-status render and escalation
        fan-out, reserve-from-random at persona allocation, the crontab tick
        installer. It decides who appears to be a manager.

    `COSA_VOICE_PREFERRED_PERSONA__<PROJECT>` is the per-repo persona chain.
        Consumer: manager_figure.resolve_implicit_manager_figure(), the
        implicit half of is_manager_figure(), which gates task-store writes
        and is fail-closed. It decides who can record owed work.

They drifted apart (`"Mr. Radio, Tiberius"` against `"Mr. Radio,Cheech,*"`).
The disagreement surfaced only when a human read a retired name off a status
card. Nothing failed, which is the whole problem.

The primary fix is derivation, not this check. src/scripts/start-cc-with-tmux.sh
builds every `COSA_VOICE_PREFERRED_PERSONA__<PROJECT>` chain from the sourced
`COSA_VOICE_MANAGERS__<PROJECT>` roster (`<roster>,*`). On the launcher path the
two families therefore cannot disagree, because there is one source,
~/.claude/fleet-roster.env.

This module is the belt for the paths derivation does not own.
Examples are a bare terminal that exported a chain by hand.
Others are a session already alive when the roster changed.
A copy-pasted `export` line from a stale doc is a third.
The SessionStart hook register_session runs it against the real launch env on
every boot. It renders any disagreement into `additionalContext`, where the
session itself reads it.

Degrade direction: silent (no disagreements). This is an advisory alarm, not
a permission predicate, so a crash here must never take a SessionStart down.

See: src/conf/fleet-roster.env.template (roster semantics)
"""

from cosa.rest.voice_persona_helpers import parse_declared_managers
from lupin_mcp.persona_normalization import canonical_persona_key


ROSTER_PREFIX    = "COSA_VOICE_MANAGERS__"
PREFERRED_PREFIX = "COSA_VOICE_PREFERRED_PERSONA__"

# Why a disagreement was raised — carried on each finding so the rendered block
# can say WHICH way the two families parted, not just that they did.
REASON_NAMES_DIFFER = "names_differ"
REASON_NO_ROSTER    = "chain_without_roster"
REASON_NO_CHAIN     = "roster_without_chain"


def _collect( environ, prefix ):
    """
    Map project suffix to declared persona names for one env-var family.

    Both families go through parse_declared_managers, which drops the `*` wildcard and de-duplicates on the canonical key.
    One parser for both sides means a difference in the output can only come from the declaration.

    Requires:
        - environ is a Mapping of env-var name to value
        - prefix is one of ROSTER_PREFIX / PREFERRED_PREFIX

    Ensures:
        - Returns { "<PROJECT>": [ names... ] } for every var carrying the prefix
          whose value is non-blank. A non-blank value that parses to zero names
          (a `*`-only chain) is kept with an empty list: it declares no manager
          and that is itself comparable.
        - Blank / whitespace-only values are treated as unset and omitted, matching
          pick_persona_chain_from_env / pick_declared_managers_from_env.
        - Non-string values are omitted (an env Mapping should not hold them, but
          a test double might).
    """
    out = { }
    for key, value in environ.items():
        if not key.startswith( prefix ):
            continue
        if not isinstance( value, str ) or not value.strip():
            continue
        out[ key[ len( prefix ): ] ] = parse_declared_managers( value )
    return out


def _keys( names ):
    """Canonical identity keys for a name list, order preserved (the compare form)."""
    return [ canonical_persona_key( n ) for n in names ]


def find_roster_disagreements( environ=None ):
    """
    Find every project whose two manager declarations do not match.

    Comparison is ordered on canonical identity keys, because order matters in both families.
    The roster head is the declared fallback manager and the chain is walked first-free-wins.
    Two declarations naming the same people in a different order are different declarations.

    Requires:
        - environ is a Mapping or None (None means os.environ)

    Ensures:
        - Returns [] when either family is entirely absent. That is not drift,
          it is a legitimate deployment shape: the :8001 arbiter's systemd unit
          loads only the roster, and the lupin-rest container carries neither.
          Firing there would train every reader to ignore the alarm.
        - Otherwise returns one dict per disagreeing project, sorted by project:
          { "project", "roster", "chain", "reason" }. The `roster` and `chain` values are the
          verbatim parsed names (display form, for a human to read) and `reason`
          is one of the REASON_* constants.
        - Never raises on a well-formed Mapping.
    """
    if environ is None:
        import os
        environ = os.environ

    roster = _collect( environ, ROSTER_PREFIX )
    chain  = _collect( environ, PREFERRED_PREFIX )

    # One-sided environments are shapes, not drift — see Ensures above.
    if not roster or not chain:
        return [ ]

    findings = [ ]
    for project in sorted( set( roster ) | set( chain ) ):
        roster_names = roster.get( project )
        chain_names  = chain.get( project )
        if roster_names is None:
            findings.append( { "project": project, "roster": [ ], "chain": chain_names,
                               "reason": REASON_NO_ROSTER } )
        elif chain_names is None:
            findings.append( { "project": project, "roster": roster_names, "chain": [ ],
                               "reason": REASON_NO_CHAIN } )
        elif _keys( roster_names ) != _keys( chain_names ):
            findings.append( { "project": project, "roster": roster_names, "chain": chain_names,
                               "reason": REASON_NAMES_DIFFER } )
    return findings


def format_roster_drift_block( findings ):
    """
    Render disagreements as a SessionStart `additionalContext` block.

    This is the same channel as the persona-failure and memento blocks: the session reads it
    at boot, at zero interrupt cost. A drift printed only to stderr is a drift
    nobody reads, which is how the original drift survived.

    Requires:
        - findings is the list returned by find_roster_disagreements

    Ensures:
        - Returns "" for an empty list (no noise on the overwhelmingly common
          boot where the two families agree)
        - Otherwise returns a block naming each project, both declarations, and
          the one-line remedy
    """
    if not findings:
        return ""

    rule  = "=" * 64
    lines = [ "", rule, "🔴 MANAGER ROSTER DRIFT — the two declarations disagree", rule,
              "COSA_VOICE_MANAGERS__<P> decides who APPEARS to be a manager (arbiter",
              "status + escalation, reserve-from-random). COSA_VOICE_PREFERRED_PERSONA__<P>",
              "decides who may WRITE OWED WORK (manager_figure gates the task store,",
              "fail-closed). They are supposed to name the same people.", "" ]
    for f in findings:
        lines.append( f"  {f[ 'project' ]}  [{f[ 'reason' ]}]" )
        lines.append( f"      roster : {', '.join( f[ 'roster' ] ) or '(none)'}" )
        lines.append( f"      chain  : {', '.join( f[ 'chain' ] ) or '(none)'}" )
    lines += [ "",
               "Remedy: edit ~/.claude/fleet-roster.env (the ONE source) and relaunch via",
               "src/scripts/start-cc-with-tmux.sh, which DERIVES the chain from the roster.",
               "A hand-exported COSA_VOICE_PREFERRED_PERSONA__* in this shell overrides that",
               "derivation — unset it.", rule, "" ]
    return "\n".join( lines ) + "\n"

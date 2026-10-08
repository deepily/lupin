"""
The reporting half of the git hook link tick: fingerprint, quiet window, delivery.

`src/scripts/hook-link-tick.sh` looks at the hooks folder and writes one tab-separated line per finding:
hook, state word, hooks folder, where the link lands. This module reads that file and says something
only when there is something to say.

A clean run prints nothing and exits 0. A finding set already delivered stays quiet until the
resend window passes, unless the set changed.

Delivery is recorded per channel: the notification, and the direct message when one is named.
A channel's fingerprint advances only after that channel arrived. A failed direct message is
retried alone, and the notification is not sent again. The tick never repairs a link.

Exit codes, each a different fact:
    0  clean, nothing printed.
    1  the check could not run (the findings file was unreadable, or a setting is not a number).
    2  findings, and every channel that was due arrived.
    3  findings, and at least one due channel failed.
    4  findings, every channel unchanged since its last delivery and inside the quiet window.
    5  findings, and delivery is switched off (HOOK_LINK_DELIVER=0): printed only, nothing sent.
"""

import datetime
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

EXIT_CLEAN, EXIT_CANNOT_LOOK, EXIT_DELIVERED, EXIT_DELIVERY_FAILED, EXIT_UNCHANGED, EXIT_SWITCHED_OFF = 0, 1, 2, 3, 4, 5

DEFAULT_API_BASE     = "http://localhost:7999"
DEFAULT_RESEND_HOURS = 6.0
DEFAULT_STATE_PATH   = "~/.claude/hook-link-tick-state.json"
REMEDY               = "bash src/scripts/install-git-hooks.sh   # a person runs it in the main checkout; a Claude seat is refused"
PROJECT              = "lupin"

_SENTENCES = {
    "ABSENT"               : "is not installed, so git runs no check",
    "NOT_LINK"             : "is a copied file, not a link, so it goes stale on the next update",
    "WRONG_TARGET"         : "links to {lands}, not to the script this checkout ships",
    "DANGLING"             : "is a dangling link to {lands}: nothing exists there, so git runs no check",
    "OUTSIDE"              : "links to {lands}, outside the checkout",
    "NOT_EXECUTABLE"       : "links to the right script, which has no executable bit, so git skips it",
    "NO_SCRIPT"            : "has no script in this checkout, which predates the hook",
    "HOOKS_PATH_MOVED"     : "points git at {folder}, not at this checkout's own hooks folder {lands}",
    "REF_NOT_EXECUTABLE"   : "is present but has no executable bit, so git skips it",
    "REF_NO_MARKER"        : "is present but does not carry the branch-guard marker line",
}


def read_findings( text ):
    """
    Parse the tab-separated findings the shell half wrote.

    Requires:
        - text has one finding per line: hook, state word, hooks folder, where the link lands (may be empty)

    Ensures:
        - returns a list of dicts with keys hook, word, folder, lands; blank lines are skipped

    Raises:
        - ValueError naming the line when it has fewer than three fields
    """
    found = []
    for line in text.splitlines():
        if not line.strip(): continue
        fields = line.split( "\t" )
        if len( fields ) < 3: raise ValueError( f"not a finding line: {line!r}" )
        found.append( { "hook": fields[ 0 ], "word": fields[ 1 ], "folder": fields[ 2 ], "lands": fields[ 3 ] if len( fields ) > 3 else "" } )
    return found


def sentence( finding ):
    """One plain sentence about one finding; an unknown state word is named, never hidden."""
    template = _SENTENCES.get( finding[ "word" ] )
    if template is None: return f"is in state {finding[ 'word' ]}"
    return template.format( lands=finding[ "lands" ] or "nowhere", folder=finding[ "folder" ] )


def fingerprint( findings ):
    """
    A stable identity for a finding set.

    Ensures:
        - the same set in any order gives the same value
        - a changed hook, state word, folder or landing place gives a different value
    """
    parts = sorted( f"{f[ 'hook' ]}|{f[ 'word' ]}|{f[ 'folder' ]}|{f[ 'lands' ]}" for f in findings )
    return hashlib.sha256( "\n".join( parts ).encode() ).hexdigest()[ :16 ]


def decide( fp, state, now, resend_hours ):
    """
    Whether to deliver now, and why.

    Ensures:
        - returns ( send, reason )
        - a different fingerprint sends at once, inside the window or not
        - an unchanged one sends again only after resend_hours, or when the last send time is unreadable
    """
    if state.get( "fingerprint" ) != fp: return True, "new or changed findings"
    try:
        elapsed = ( now - datetime.datetime.fromisoformat( state[ "last_sent_ts" ] ) ).total_seconds() / 3600.0
    except ( KeyError, TypeError, ValueError ):
        return True, "no readable last-send time"
    if elapsed >= resend_hours: return True, f"unchanged findings still open {elapsed:.0f}h after the last alarm"
    return False, f"identical findings delivered {elapsed:.0f}h ago, so not re-sending"


def report_lines( findings, stamp, drill ):
    """The lines printed when there are findings."""
    lines = [ f"=== git hook links @ {stamp.strftime( '%Y-%m-%d %H:%M:%S %Z' )}: {len( findings )} finding(s)" + ( "  [DRILL]" if drill else "" ) ]
    lines += [ f"  hook {f[ 'hook' ]} {sentence( f )} (folder read: {f[ 'folder' ]})" for f in findings ]
    lines.append( f"  remedy: {REMEDY}" )
    return lines


def build_payload( findings, why, drill ):
    """
    The words delivered: ( spoken line, abstract table, direct message ).

    Ensures:
        - names each hook, its state word, the folder that was read and the one remedy
        - carries nothing taken from the environment
    """
    banner = "[DRILL, a test fire and not a real reading. Ignore the findings below.] " if drill else ""
    spoken = ( "Drill, not a real alarm: test fire of the git hook link check." if drill else
               f"Git hook links are broken, {len( findings )} finding(s). The commit or push check may be off for every seat." )
    rows   = "\n".join( f"| {f[ 'hook' ]} | {f[ 'word' ]} | {f[ 'folder' ]} | {f[ 'lands' ] or '-'} |" for f in findings )
    abstract = ( ( "**DRILL, a test fire and not a real reading.**  \n\n" if drill else "" ) +
                 f"**{len( findings )} git hook finding(s)**  \ntrigger: {why}  \n\n"
                 "| hook | state | folder read | lands at |\n|---|---|---|---|\n" + rows + "\n\n"
                 "A hook that is missing, dangling, copied or pointed outside the checkout lets a commit or a push through "
                 "with no check, and git prints no error. This tick never repairs a link.  \n"
                 f"Remedy: `{REMEDY}`" )
    direct = ( banner + "Git hook link check: " + "; ".join( f"{f[ 'hook' ]} {f[ 'word' ]} (read {f[ 'folder' ]})" for f in findings )
               + f". Remedy: {REMEDY}. Nothing was repaired automatically." )
    return spoken, abstract, direct


def _http( request ):
    try:
        with urllib.request.urlopen( request, timeout=30 ) as reply: return reply.status, reply.read().decode()[ :400 ]
    except urllib.error.HTTPError as error: return error.code, error.read().decode()[ :400 ]
    except Exception as error:              return 0, str( error )


def post_query( base, key, path, params ):
    """POST with query parameters (the notify contract); returns ( status, text ), never raises."""
    request = urllib.request.Request( f"{base}{path}?{urllib.parse.urlencode( params )}", data=b"", headers={ "X-API-Key": key }, method="POST" )
    return _http( request )


def post_json( base, key, path, payload ):
    """POST a JSON body; returns ( status, text ) and never raises."""
    request = urllib.request.Request( f"{base}{path}", data=json.dumps( payload ).encode(),
                                      headers={ "X-API-Key": key, "Content-Type": "application/json" }, method="POST" )
    return _http( request )


def _api_key():
    from lupin_cli.claude_code.hooks.lib.task_store_client import read_api_key
    return read_api_key()


def _notify_target( environ ):
    target = environ.get( "LUPIN_DEV_EMAIL" )
    if target: return target
    from cosa.utils.config_loader import get_api_config
    return get_api_config( environ.get( "LUPIN_ENV", "local" ) ).get( "global_notification_recipient" )


def _persona( environ ):
    """The persona named for the direct message, or an empty string."""
    return environ.get( "HOOK_LINK_DM", "" ).strip()


def deliver( findings, why, drill, environ, err, channels=( "notify", ), query=post_query, body=post_json, api_key=_api_key, target_of=_notify_target ):
    """
    Send to each named channel; returns a dict of channel name to whether it arrived.

    Requires:
        - channels holds "notify" and/or "dm"; "dm" is sent only when HOOK_LINK_DM names a persona

    Ensures:
        - one notification to the global recipient for "notify", one direct message for "dm"
        - a missing recipient or a missing key counts as a failed delivery
        - never raises
    """
    base       = environ.get( "HOOK_LINK_API_BASE", DEFAULT_API_BASE ).rstrip( "/" )
    spoken, abstract, direct = build_payload( findings, why, drill )
    results    = { }
    try:
        key = api_key()
    except Exception:
        key = ""
    if "notify" in channels:
        try:
            target = target_of( environ )
        except Exception:
            target = None
        if not target:
            results[ "notify" ] = False
            print( "  DELIVERY FAILED: notify has no target user (set LUPIN_DEV_EMAIL or global_notification_recipient)", file=err )
        else:
            status, detail = query( base, key, "/api/notify", {
                "message": spoken, "type": "alert", "priority": "high", "target_user": target,
                "sender_id": f"claude.code@{PROJECT}.deepily.ai#hook-link-tick", "abstract": abstract, "idempotency_key": str( uuid.uuid4() ),
            } )
            results[ "notify" ] = status == 200
            if status == 200: print( f"  notify to {target}: delivered (HTTP 200)" )
            else:             print( f"  DELIVERY FAILED: notify to {target}: HTTP {status} {detail}", file=err )
    if "dm" in channels:
        persona = _persona( environ )
        status, detail = body( base, key, "/api/dm/send", {
            "sender_session_id": "hook-link-tick", "sender_persona": "hook link DRILL" if drill else "hook link tick", "sender_icon": "🔗",
            "sender_project": PROJECT, "recipient_persona": persona, "body": direct,
        } )
        results[ "dm" ] = status == 201
        if status == 201: print( f"  DM to {persona}: delivered (HTTP 201)" )
        else:             print( f"  DELIVERY FAILED: DM to {persona}: HTTP {status} {detail}", file=err )
    return results


def _write_state( path, ledger, err ):
    try:
        os.makedirs( os.path.dirname( path ), exist_ok=True )
        tmp = path + ".tmp"
        with open( tmp, "w" ) as handle: json.dump( { "channels": ledger }, handle, indent=2 )
        os.replace( tmp, path )
    except OSError as error:
        print( f"  TICK WARNING: could not write the send ledger {path}: {error}", file=err )


def _read_ledger( path ):
    """The per-channel ledger from the state file; anything unreadable reads as empty."""
    try:
        with open( path ) as handle: state = json.load( handle )
    except ( OSError, ValueError ): return { }
    ledger = state.get( "channels" ) if isinstance( state, dict ) else None
    return ledger if isinstance( ledger, dict ) else { }


def main( argv=None, environ=None, now=None, out=sys.stdout, err=sys.stderr, **seams ):
    """
    Run the reporting half.

    Requires:
        - argv is [ findings_file ]; environ carries the HOOK_LINK_* settings

    Ensures:
        - returns one of the six exit codes in the module docstring
        - prints nothing at all when the findings file is empty
        - each channel's fingerprint advances only when that channel arrived
        - a drill with no HOOK_LINK_STATE writes its ledger beside the real one, never over it
    """
    argv    = sys.argv[ 1: ] if argv is None else argv
    environ = os.environ if environ is None else environ
    if len( argv ) != 1:
        print( "hook_link_tick: usage: python -m cosa.utils.hook_link_tick <findings-file>", file=err )
        return EXIT_CANNOT_LOOK
    try:
        with open( argv[ 0 ] ) as handle: findings = read_findings( handle.read() )
    except ( OSError, ValueError ) as error:
        print( f"HOOK-LINK TICK ERROR: the findings could not be read: {error}", file=err )
        return EXIT_CANNOT_LOOK
    if not findings: return EXIT_CLEAN

    try:
        resend = float( environ.get( "HOOK_LINK_RESEND_HOURS", DEFAULT_RESEND_HOURS ) )
    except ValueError:
        print( f"HOOK-LINK TICK ERROR: HOOK_LINK_RESEND_HOURS is not a number: {environ[ 'HOOK_LINK_RESEND_HOURS' ]!r}", file=err )
        return EXIT_CANNOT_LOOK
    stamp    = ( now or datetime.datetime.now().astimezone() )
    drill    = environ.get( "HOOK_LINK_DRILL", "" ) == "1"
    state_p  = os.path.expanduser( environ.get( "HOOK_LINK_STATE", DEFAULT_STATE_PATH + ( ".drill" if drill else "" ) ) )
    fp       = fingerprint( findings )
    ledger   = _read_ledger( state_p )
    channels = [ "notify" ] + ( [ "dm" ] if _persona( environ ) else [ ] )
    verdicts = { c: decide( fp, ledger.get( c, { } ) if isinstance( ledger.get( c ), dict ) else { }, stamp, resend ) for c in channels }
    due      = [ c for c in channels if verdicts[ c ][ 0 ] ]

    for line in report_lines( findings, stamp, drill ): print( line, file=out )
    if not due:
        for c in channels: print( f"  {c}: {verdicts[ c ][ 1 ]}", file=out )
        return EXIT_UNCHANGED
    if environ.get( "HOOK_LINK_DELIVER", "1" ) == "0":
        print( "  delivery disabled (HOOK_LINK_DELIVER=0), printed only, nothing sent", file=out )
        return EXIT_SWITCHED_OFF
    results = deliver( findings, verdicts[ due[ 0 ] ][ 1 ], drill, environ, err, channels=due, **seams )
    for c, arrived in results.items():
        if arrived: ledger[ c ] = { "fingerprint": fp, "last_sent_ts": stamp.isoformat(), "findings": len( findings ) }
    if any( results.values() ): _write_state( state_p, ledger, err )
    failed = [ c for c, arrived in results.items() if not arrived ]
    if not failed: return EXIT_DELIVERED
    print( f"  TICK ERROR: {', '.join( failed )} did not arrive. Detection worked; the alarm did not reach every channel. "
           "Channels that arrived are not sent again.", file=err )
    return EXIT_DELIVERY_FAILED


if __name__ == "__main__":   # pragma: no cover  (thin entry point; main() is what is tested)
    sys.exit( main() )

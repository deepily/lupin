"""
Tie a duplicate found in the code to the lookup that should have caught it.

Two ways, in order:
    - the review document's ruling line names the receipt, and the refusal record keeps the pairs of symbol id and receipt id;
    - failing that, the writing seat's latest `check_exists` receipt before the commit, found through the persona name in the commit message.
The second is a guess and is marked `tie=heuristic`. The tie also gives the session that made the lookup, which the finding step needs to find a manager.
Nothing here sends anything, runs a model, or writes a file.
"""
import datetime
import subprocess

from lupin_mcp import reuse_exit_gate as eg
from lupin_mcp.persona_normalization import canonical_persona_key

RULING_TIE   = "ruling"
HEURISTIC    = "heuristic"
NO_TIE       = "none"
HEURISTIC_TOOL = "check_exists"                                     # only this receipt holds a need text; the other lookup holds a symbol id


def commit_facts( root, sha ):
    """
    Read a commit's time and message.

    Requires:
        - root is a git working tree
    Ensures:
        - returns { time, message }: the committer time as an aware datetime, and the full message
    Raises:
        - ValueError when the commit is not in the repository
    """
    got = subprocess.run( [ "git", "-C", str( root ), "show", "-s", "--format=%cI%n%B", f"{sha}^{{commit}}" ], capture_output=True, text=True )
    if got.returncode != 0: raise ValueError( f"{sha} is not a commit in {root}: {got.stderr.strip()}" )
    stamp, _, message = got.stdout.partition( "\n" )
    return { "time": datetime.datetime.fromisoformat( stamp ), "message": message }


def _persona_of( record ):
    """Ensures: returns the persona key of a record's caller, `<persona> <session id>`, or empty."""
    return canonical_persona_key( str( record.get( "caller", "" ) ).rpartition( " " )[ 0 ] )


def _lookup_record( records, receipt_id ):
    """Ensures: returns the first clean lookup call that returned the receipt, or None."""
    return next( ( r for r in records if r.get( "tool" ) in eg.RECEIPT_TOOLS and not r.get( "error" ) and r.get( "receipt_id" ) == receipt_id ), None )


def _from_ruling( symbol, rows, records ):
    """
    Find the receipt a ruling line named for a symbol.

    Requires:
        - rows are the records of refusals.jsonl, each with `pairs` of [ symbol id, receipt id ]
    Ensures:
        - the latest record that pairs the symbol with a real receipt id wins; a token such as `excluded` is not a receipt
        - returns the tie dict, or None when no record pairs the symbol with a receipt
        - session and tool are None when the call log does not hold the receipt
    """
    for row in reversed( rows ):
        for sym, rid in row.get( "pairs", [] ):
            if sym != symbol or not eg.RECEIPT_ID_RE.fullmatch( rid ): continue
            found = _lookup_record( records, rid )
            return { "tie": RULING_TIE, "receipt_id": rid, "session": found[ "session" ] if found else None, "tool": found[ "tool" ] if found else None }
    return None


def _writer( message, records ):
    """
    Name the persona the commit message gives, among those that made lookups.

    Ensures:
        - returns the persona key whose name appears first in the message as whole words, or None
        - only personas that appear as a caller in the call log are looked for
    """
    text  = f" {canonical_persona_key( message )} "
    found = { key: text.find( f" {key} " ) for key in { _persona_of( r ) for r in records } - { "" } }
    found = { key: at for key, at in found.items() if at >= 0 }
    return min( found, key=found.get ) if found else None


def _from_commit( records, facts ):
    """
    Find the writing seat's latest `check_exists` receipt before the commit.

    Ensures:
        - returns the tie dict marked heuristic, or a `none` tie that says what was missing
        - a lookup counts only if it is a `check_exists` that logged no error, has a receipt id, and was made before the commit time
        - the writer is the first persona the message names, which is a guess: a message that names a reviewer first ties the reviewer's lookups
    """
    persona = _writer( facts[ "message" ], records )
    if persona is None: return { "tie": NO_TIE, "reason": "the commit message names no persona that made a lookup in the call log" }
    before = [ r for r in records if r.get( "tool" ) == HEURISTIC_TOOL and not r.get( "error" ) and r.get( "receipt_id" ) and _persona_of( r ) == persona
               and datetime.datetime.fromisoformat( r[ "ts" ] ) < facts[ "time" ] ]
    if not before: return { "tie": NO_TIE, "reason": f"{persona} made no {HEURISTIC_TOOL} lookup before the commit" }
    last = max( before, key=lambda r: datetime.datetime.fromisoformat( r[ "ts" ] ) )
    return { "tie": HEURISTIC, "receipt_id": last[ "receipt_id" ], "session": last[ "session" ], "tool": last[ "tool" ], "persona": persona }


def find_tie( symbol, rows, records, root, sha ):
    """
    Tie one duplicate to a lookup receipt and the session that made it.

    Requires:
        - symbol is the id of the new definition that proved a duplicate
        - rows is what reuse_behaviour.read_refusals returns; records is what merge_call_logs returns
        - root and sha name the commit that added the definition
    Ensures:
        - returns { tie, receipt_id, session, tool } with tie `ruling` when a ruling line named the receipt
        - otherwise tie is `heuristic` with the persona added, or `none` with a reason when no lookup could be found
        - session is None when the call log does not hold a ruling's receipt; the commit is not read when a ruling names the receipt
        - tool tells the caller whether the receipt holds a need text: only `check_exists` does
    Raises:
        - ValueError when the ruling gives no tie and the commit is not in the repository
    """
    return _from_ruling( symbol, rows, records ) or _from_commit( records, commit_facts( root, sha ) )

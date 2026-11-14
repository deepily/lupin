"""
Reuse a saved judge ruling that another model, or an older shortlist, already gave.

A ruling is looked up by the definition, the prompt and the slot. The model that gave it does not matter.
"""
from cosa.repo.doc_lint import harness_runner
from cosa.repo.duplicate_check import extract

OLD_AT   = 1
NEW_AT   = 2
PROMPT   = 3
MODEL_AT = 4
SLOT_AT  = 5


def saved_rulings( entries, stage ):
    """
    Index the readable rulings of a ledger by the definition they ruled on.

    Requires:
        - entries is a ledger's { key: value } map; stage is the stage name the judge keys with

    Ensures:
        - returns { ( new hash, prompt version, slot ): [ ( old hash, model id, value ) ] } for each ledger key of this stage whose value holds rulings
        - a key of another stage, and a value that is unreadable, are left out
        - the list of a definition runs in key order, so a lookup gives the same answer on every run
    """
    index = {}
    for key in sorted( entries ):
        parts = key.split( "|" )
        if parts[ 0 ] != stage or "rulings" not in entries[ key ]: continue
        index.setdefault( ( parts[ NEW_AT ], parts[ PROMPT ], parts[ SLOT_AT ] ), [] ).append( ( parts[ OLD_AT ], parts[ MODEL_AT ], entries[ key ] ) )
    return index


def lookup( saved, stage, pair, prompt_version, slot, records ):
    """
    Find a ruling for a definition among the saved ones of any model.

    Requires:
        - saved is saved_rulings' answer; pair is the judge's { old, new } of the definition against its candidates
        - records are the full candidate records of the definition, in fused order

    Ensures:
        - returns None, or a ledger value of rulings, each ruling carrying "model", the id of the model that gave it, so no ruling reads as another judge's
        - when a saved ruling has the same candidates' text, that ruling is returned whole, with the model of its entry
        - otherwise, when each candidate has one saved verdict under the definition's hash, a ruling is built from them: the first saved entry that names the candidate gives the reason and the model
        - a candidate saved with two different verdicts counts as not saved, and so does a definition with no candidates, so a call is made for it
        - a candidate is matched by definition id with the origin ignored
        - never makes a model call and never writes
    """
    key    = harness_runner.ledger_key( stage, pair, prompt_version, "", slot ).split( "|" )
    found  = saved.get( ( key[ NEW_AT ], prompt_version, str( slot ) ), [] )
    whole  = [ e for e in found if e[ 0 ] == key[ OLD_AT ] ]
    if whole: return { "rulings": [ { **r, "model": whole[ 0 ][ 1 ] } for r in whole[ 0 ][ 2 ][ "rulings" ] ] }
    if not records: return None
    ours   = {}
    for c in records:
        for origin in extract.ORIGINS: ours.setdefault( extract.definition_id( origin, c[ "file" ], c[ "name" ], c[ "text" ] ), c[ "id" ] )
        ours[ c[ "id" ] ] = c[ "id" ]
    given  = {}
    for _, model, value in found:
        for r in value[ "rulings" ]:
            if r[ "candidate" ] in ours: given.setdefault( ours[ r[ "candidate" ] ], [] ).append( ( r[ "verdict" ], r[ "reason" ], model ) )
    if any( c[ "id" ] not in given or len( { g[ 0 ] for g in given[ c[ "id" ] ] } ) != 1 for c in records ): return None
    return { "rulings": [ { "candidate": c[ "id" ], "verdict": given[ c[ "id" ] ][ 0 ][ 0 ], "reason": given[ c[ "id" ] ][ 0 ][ 1 ], "model": given[ c[ "id" ] ][ 0 ][ 2 ] } for c in records ] }

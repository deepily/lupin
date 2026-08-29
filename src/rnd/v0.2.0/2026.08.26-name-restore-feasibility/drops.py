import json, re, collections, sys

CORPUS = "/mnt/DATA01/include/www.deepily.ai/projects-data/lupin/dm-corpus/dm_traffic.jsonl"

ROSTER = {
    "mr radio": [r"mr\.?\s+radio", r"\bmr_radio\b"],
    "cheech":   [r"\bcheech\b"],
    "maria":    [r"\bmar[ií]a\b"],
    "rachel":   [r"\brachel\b"],
    "tiberius": [r"\btiberius\b"],
    "clayton":  [r"\bclayton\b"],
    "krishna":  [r"\bkrishna\b"],
    "tiffany":  [r"\btiffany\b"],
    "rio":      [r"\brio\b"],
    "sam":      [r"\bsam\b"],
    "pocholo":  [r"\bpocholo\b"],
    "john":     [r"\bjohn\b"],
    "maya":     [r"\bmaya\b"],
    "chloe":    [r"\bchlo[eé]\b"],
    "arnold":   [r"\barnold\b"],
    "rick":     [r"\brick\b"],
    "ricardo":  [r"\bricardo\b"],
    "clara":    [r"\bclara\b"],
    "cesar":    [r"\bc[eé]sar\b"],
}
PATS = { k: re.compile("|".join(v), re.I) for k,v in ROSTER.items() }

def names_in( text ):
    return { k for k,p in PATS.items() if p.search( text ) }

rows = []
for i, line in enumerate( open( CORPUS ) ):
    line = line.strip()
    if not line: continue
    d = json.loads( line )
    d["_lineno"] = i + 1
    rows.append( d )

rw = [ d for d in rows if d.get( "body_was_rewritten" ) ]
drops = []
for d in rw:
    b  = d.get( "body" ) or ""
    db = d.get( "delivered_body" ) or ""
    lost = names_in( b ) - names_in( db )
    if lost:
        d["_lost"] = sorted( lost )
        drops.append( d )

one   = [ d for d in drops if len( d["_lost"] ) == 1 ]
three = [ d for d in drops if len( d["_lost"] ) >= 3 ]

print( "total rows      ", len( rows ) )
print( "rewritten       ", len( rw ) )
print( "dropped >=1 name", len( drops ), "(%.1f%%)" % ( 100*len(drops)/len(rw) ) )
print( "dropped exactly1", len( one ),   "(%.1f%% of drops)" % ( 100*len(one)/len(drops) ) )
print( "dropped >=3     ", len( three ), "(%.1f%% of drops)" % ( 100*len(three)/len(drops) ) )

json.dump( one, open( "single_drops.json", "w" ) )

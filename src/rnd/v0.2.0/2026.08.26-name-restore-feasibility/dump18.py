import json, re
exec( open( "drops.py" ).read().split( "rows = []" )[0] )
c = json.load( open( "classC.json" ) )
PRON = re.compile( r"\b(he|him|his|she|her|hers)\b", re.I )
def sf(t): return t.split( "This DM was condensed in transit." )[0]
k=0
for x in c:
    db = sf( x.get("delivered_body") or "" )
    if not ( PRON.search(db) and not names_in(db) ): continue
    name = x["_lost"][0]; pat = PATS[name]
    chunks = [ ln for ln in re.split( r"(?<=[.!?])\s+|\n", x["body"] ) if pat.search( ln ) ]
    print("="*100)
    print("U%02d  %s  %s -> %s  DROPPED=%s" % (k, x["ts"], x["from"], x["to"], name.upper()))
    print("-- ORIGINAL sentences naming them --")
    for ch in chunks[:4]: print("   | " + ch.strip()[:400])
    print("-- DELIVERED --"); print(db.strip())
    k+=1

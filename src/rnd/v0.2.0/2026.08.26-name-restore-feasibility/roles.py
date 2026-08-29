import json, re, random
exec( open( "drops.py" ).read().split( "rows = []" )[0] )
c = json.load( open( "classC.json" ) )
ROLE = re.compile( r"\b[Tt]he (sender|author|user|developer|agent|peer|recipient|reviewer|implementer|manager)\b" )
def sf(t): return t.split( "This DM was condensed in transit." )[0]
hits = [ x for x in c if ROLE.search( sf( x.get("delivered_body") or "" ) ) ]
random.seed( 7 )
for i, x in enumerate( random.sample( hits, 20 ) ):
    name = x["_lost"][0]; pat = PATS[name]
    ch = [ ln for ln in re.split( r"(?<=[.!?])\s+|\n", x["body"] ) if pat.search( ln ) ]
    print("="*100)
    print("R%02d  %s  %s -> %s  DROPPED=%s  (sender==dropped? %s)" % (
        i, x["ts"], x["from"], x["to"], name.upper(),
        str(x["from"]).strip().lower().replace("í","i") == name ))
    print("-- ORIGINAL sentences naming them --")
    for k in ch[:3]: print("   | " + k.strip()[:350])
    print("-- DELIVERED --"); print(sf(x["delivered_body"]).strip()[:900])

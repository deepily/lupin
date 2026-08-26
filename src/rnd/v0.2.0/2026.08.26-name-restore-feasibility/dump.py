import json, re, sys
exec( open( "drops.py" ).read().split( "rows = []" )[0] )

s = json.load( open( "sample.json" ) )
lo, hi = int( sys.argv[1] ), int( sys.argv[2] )
for i, x in enumerate( s ):
    if not ( lo <= i < hi ): continue
    name = x["_lost"][0]
    pat  = PATS[ name ]
    orig = x["body"]
    chunks = [ ln for ln in re.split( r"(?<=[.!?])\s+|\n", orig ) if pat.search( ln ) ]
    print( "="*100 )
    print( "CASE %02d  %s  %s -> %s  words=%s  DROPPED=%s  named=%s" % ( i, x["ts"], x["from"], x["to"], x["words"], name.upper(), x["_named"] ) )
    print( "-- ORIGINAL sentences naming the dropped person --" )
    for c in chunks: print( "   | " + c.strip() )
    print( "-- DELIVERED (full) --" )
    print( x["delivered_body"] )

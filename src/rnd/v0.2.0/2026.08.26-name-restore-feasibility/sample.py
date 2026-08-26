import json, re, collections, random
exec( open( "drops.py" ).read().split( "rows = []" )[0] )   # reuse ROSTER/PATS/names_in

d = json.load( open( "single_drops.json" ) )
for x in d:
    x["_named"] = sorted( names_in( x["body"] ) )

def lenbin( w ):
    return "S" if w < 116 else ( "M" if w <= 209 else "L" )
def perbin( ts ):
    return "early" if ts < "2026-08-20" else "late"
def nbin( x ):
    return "solo" if len( x["_named"] ) == 1 else "multi"

cells = collections.defaultdict( list )
for x in d:
    cells[ ( lenbin( x["words"] ), perbin( x["ts"] ), nbin( x ) ) ].append( x )

for k in sorted( cells ): print( k, len( cells[k] ) )
print( "cells:", len( cells ), "total:", sum( len(v) for v in cells.values() ) )

random.seed( 20260826 )
sample = []
for k in sorted( cells ):
    v = sorted( cells[k], key=lambda x: (x["ts"], x["_lineno"]) )
    sample += random.sample( v, min( 5, len(v) ) )
print( "sample size:", len( sample ) )
json.dump( sample, open( "sample.json", "w" ), indent=1 )

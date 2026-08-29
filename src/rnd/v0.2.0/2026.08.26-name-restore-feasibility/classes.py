import json, re, collections
exec( open( "drops.py" ).read().split( "rows = []" )[0] )

d = json.load( open( "single_drops.json" ) )

def canon( s ):
    s = str( s ).strip().lower()
    return "maria" if s in ( "maria", "maría" ) else s

IDENT = re.compile( r"[A-Za-z0-9_./=#-]" )

def only_in_identifier( body, name ):
    """True iff EVERY occurrence of the name is glued to identifier punctuation."""
    hits = list( PATS[name].finditer( body ) )
    if not hits: return False
    for m in hits:
        before = body[m.start()-1] if m.start() > 0 else " "
        after  = body[m.end()]     if m.end() < len(body) else " "
        glued  = ( before in "-_./=#" ) or ( after in "-_./=#" )
        if not glued: return False
    return True

self_drop = [ x for x in d if canon( x["from"] ) == x["_lost"][0] ]
ident     = [ x for x in d if x not in self_drop and only_in_identifier( x["body"], x["_lost"][0] ) ]
rest      = [ x for x in d if x not in self_drop and x not in ident ]

print( "single-name drops        ", len( d ) )
print( "  A dropped name == SENDER's own name  ", len( self_drop ), "(%.1f%%)" % (100*len(self_drop)/len(d)) )
print( "  B name only inside an identifier     ", len( ident ),     "(%.1f%%)" % (100*len(ident)/len(d)) )
print( "  C third-party actor drop (the real Q)", len( rest ),      "(%.1f%%)" % (100*len(rest)/len(d)) )
print()
c = collections.Counter( x["_lost"][0] for x in rest )
print( "who gets dropped, class C:", c.most_common() )
json.dump( rest, open( "classC.json", "w" ) )

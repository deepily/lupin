import json, re, random
exec( open( "drops.py" ).read().split( "rows = []" )[0] )

c = json.load( open( "classC.json" ) )
PRON = re.compile( r"\b(he|him|his|she|her|hers)\b", re.I )

def strip_footer( t ):
    return t.split( "This DM was condensed in transit." )[0]

strict = []
for x in c:
    db = strip_footer( x.get( "delivered_body" ) or "" )
    if PRON.search( db ) and not names_in( db ):
        strict.append( x )

print( "class C", len(c) )
print( "delivered text has a he/she/his/her AND names NOBODY  ->", len(strict), "(%.1f%% of C)" % (100*len(strict)/len(c)) )
random.seed( 11 )
json.dump( random.sample( strict, min(12,len(strict)) ), open( "strict_sample.json", "w" ) )

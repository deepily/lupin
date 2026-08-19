import os, sys
lupin_root = os.environ.get( "LUPIN_ROOT", "/mnt/DATA01/include/www.deepily.ai/projects/lupin" )
src_path   = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )
from sqlalchemy import create_engine, text
from cosa.rest.db.database import get_database_url
engine = create_engine( get_database_url() )

POP = """
  direction = 'ai_to_human'
  AND sender_id LIKE 'claude.code@%%'
  AND type IN ('progress','task','alert','custom')
  AND created_at >= '2026-08-01'
"""
with engine.connect() as conn:
    print( "=== top 15 exact-duplicate messages since 2026-08-01 ===" )
    tot = conn.execute( text( f"SELECT count(*) FROM notifications WHERE {POP}" ) ).scalar()
    print( f"population = {tot}" )
    for r in conn.execute( text( f"""
        SELECT left(message,70) AS msg, length(message) len, count(*) n
        FROM notifications WHERE {POP}
        GROUP BY message ORDER BY n DESC LIMIT 15
    """ ) ).mappings():
        print( f"{r['n']:>7}  len={r['len']:<5} {r['msg']!r}" )

    dup = conn.execute( text( f"""
        SELECT sum(n) FROM (
          SELECT count(*) n FROM notifications WHERE {POP} GROUP BY message HAVING count(*) > 5
        ) t
    """ ) ).scalar()
    print( f"\nrows whose exact message repeats >5 times: {dup} / {tot}" )

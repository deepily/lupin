import os, sys
lupin_root = os.environ.get( "LUPIN_ROOT", "/mnt/DATA01/include/www.deepily.ai/projects/lupin" )
src_path   = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )
from sqlalchemy import create_engine, text
from cosa.rest.db.database import get_database_url
engine = create_engine( get_database_url() )

# Same authored filter as the headline run, but type='progress' ONLY.
PROGRESS = """
SELECT n.created_at, n.message, length(n.message) AS len
FROM notifications n
JOIN ( SELECT message FROM notifications
       WHERE direction='ai_to_human' AND sender_id LIKE 'claude.code@%%'
       GROUP BY message HAVING count(*) <= 2 ) u ON u.message = n.message
WHERE n.direction='ai_to_human' AND n.sender_id LIKE 'claude.code@%%'
  AND n.type = 'progress'
  AND n.message NOT LIKE 'Done: %%' AND length(n.message) > 15
  AND n.created_at >= '2026-07-28'
"""
with engine.connect() as conn:
    n = conn.execute( text( f"SELECT count(*) FROM ({PROGRESS}) a" ) ).scalar()
    print( f"authored 'progress' rows in window: {n}\n" )
    print( "="*100 )
    print( "100-ROW SAMPLE, evenly spread across the length range (shortest -> longest)" )
    print( "="*100 )
    for r in conn.execute( text( f"""
        SELECT len, message FROM (
          SELECT len, message, ntile(100) OVER (ORDER BY len) AS bucket,
                 row_number() OVER (PARTITION BY ntile(100) OVER (ORDER BY len) ORDER BY created_at) AS rn
          FROM ({PROGRESS}) a
        ) t WHERE rn = 1 ORDER BY len
    """ ) ).mappings():
        msg = r["message"].replace( "\n", " ⏎ " )
        print( f"[{r['len']:>5}] {msg[:300]}" )

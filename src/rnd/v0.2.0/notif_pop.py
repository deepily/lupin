import os, sys
lupin_root = os.environ.get( "LUPIN_ROOT", "/mnt/DATA01/include/www.deepily.ai/projects/lupin" )
src_path   = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )
from sqlalchemy import create_engine, text
from cosa.rest.db.database import get_database_url
engine = create_engine( get_database_url() )

with engine.connect() as conn:
    print( "=== ai_to_human by type, since 2026-07-15 ===" )
    for r in conn.execute( text( """
        SELECT type, count(*) n, round(avg(length(message))::numeric,1) mean_chars
        FROM notifications
        WHERE direction='ai_to_human' AND created_at >= '2026-07-15'
        GROUP BY type ORDER BY n DESC LIMIT 15
    """ ) ).mappings(): print( dict(r) )

    print( "\n=== ai_to_human by sender_id prefix, since 2026-07-15 ===" )
    for r in conn.execute( text( """
        SELECT split_part(sender_id,'#',1) AS sender, count(*) n,
               round(avg(length(message))::numeric,1) mean_chars,
               count(DISTINCT sender_id) sessions
        FROM notifications
        WHERE direction='ai_to_human' AND created_at >= '2026-07-15'
        GROUP BY 1 ORDER BY n DESC LIMIT 15
    """ ) ).mappings(): print( dict(r) )

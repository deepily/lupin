import os, sys, statistics
lupin_root = os.environ.get( "LUPIN_ROOT", "/mnt/DATA01/include/www.deepily.ai/projects/lupin" )
src_path   = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

from sqlalchemy import create_engine, text
from cosa.rest.db.database import get_database_url

engine = create_engine( get_database_url() )

CUT = "2026-08-13 14:14:00-04"

with engine.connect() as conn:
    # 1. Overall shape of the table
    row = conn.execute( text( """
        SELECT count(*)                       AS total,
               min(created_at)                AS first_ts,
               max(created_at)                AS last_ts,
               count(*) FILTER (WHERE direction = 'ai_to_human') AS to_human,
               count(*) FILTER (WHERE direction = 'ai_to_ai')    AS to_ai,
               count(*) FILTER (WHERE sender_persona IS NOT NULL) AS with_persona
        FROM notifications
    """ ) ).mappings().one()
    print( "TABLE:", dict( row ) )

    # 2. Per-side distribution, ai_to_human only, persona-sent only
    for label, pred in [ ( "BEFORE", "created_at <  :cut" ), ( "AFTER", "created_at >= :cut" ) ]:
        r = conn.execute( text( f"""
            SELECT count(*) AS n,
                   round( avg( length( message ) )::numeric, 1 )   AS mean_chars,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY length( message ) ) AS p50,
                   percentile_cont(0.9) WITHIN GROUP (ORDER BY length( message ) ) AS p90,
                   max( length( message ) )                        AS max_chars,
                   count( DISTINCT sender_persona )                AS personas
            FROM notifications
            WHERE direction = 'ai_to_human'
              AND sender_persona IS NOT NULL
              AND {pred}
        """ ), { "cut": CUT } ).mappings().one()
        print( label, dict( r ) )

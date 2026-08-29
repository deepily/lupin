import os, sys
lupin_root = os.environ.get( "LUPIN_ROOT", "/mnt/DATA01/include/www.deepily.ai/projects/lupin" )
src_path   = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )
from sqlalchemy import create_engine, text
from cosa.rest.db.database import get_database_url
engine = create_engine( get_database_url() )

# Claude-AUTHORED, human-facing, spoken-content notifications.
POP = """
  direction = 'ai_to_human'
  AND sender_id LIKE 'claude.code@%%'
  AND type IN ('progress','task','alert','custom')
"""

with engine.connect() as conn:
    print( "=== daily, all claude.code ai_to_human authored notifications ===" )
    print( f"{'day':<12}{'n':>7}{'mean':>9}{'p50':>7}{'p90':>7}{'sessions':>10}" )
    for r in conn.execute( text( f"""
        SELECT (created_at AT TIME ZONE 'America/New_York')::date AS day,
               count(*) n,
               round(avg(length(message))::numeric,1) mean,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY length(message)) p50,
               percentile_cont(0.9) WITHIN GROUP (ORDER BY length(message)) p90,
               count(DISTINCT sender_id) sessions
        FROM notifications
        WHERE {POP} AND created_at >= '2026-07-25'
        GROUP BY 1 ORDER BY 1
    """ ) ).mappings():
        print( f"{str(r['day']):<12}{r['n']:>7}{r['mean']:>9}{r['p50']:>7.0f}{r['p90']:>7.0f}{r['sessions']:>10}" )

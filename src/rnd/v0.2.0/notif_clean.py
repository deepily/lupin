import os, sys
lupin_root = os.environ.get( "LUPIN_ROOT", "/mnt/DATA01/include/www.deepily.ai/projects/lupin" )
src_path   = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )
from sqlalchemy import create_engine, text
from cosa.rest.db.database import get_database_url
engine = create_engine( get_database_url() )

# AUTHORED population: human-facing, from a CC session, prose types,
# NOT a hook-emitted tool ping, and NOT a message whose exact text recurs
# (a repeated string is a template, not something a model composed).
AUTHORED = """
SELECT n.id, n.created_at, n.sender_id, length(n.message) AS len
FROM notifications n
JOIN ( SELECT message FROM notifications
       WHERE direction='ai_to_human' AND sender_id LIKE 'claude.code@%%'
       GROUP BY message HAVING count(*) <= 2 ) u
  ON u.message = n.message
WHERE n.direction='ai_to_human'
  AND n.sender_id LIKE 'claude.code@%%'
  AND n.type IN ('progress','task','alert','custom')
  AND n.message NOT LIKE 'Done: %%'
  AND length(n.message) > 15
"""

with engine.connect() as conn:
    print( "=== AUTHORED notifications, daily ===" )
    print( f"{'day':<12}{'n':>6}{'mean':>8}{'p50':>6}{'p90':>7}{'sess':>6}" )
    for r in conn.execute( text( f"""
        SELECT (created_at AT TIME ZONE 'America/New_York')::date AS day,
               count(*) n, round(avg(len)::numeric,1) mean,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY len) p50,
               percentile_cont(0.9) WITHIN GROUP (ORDER BY len) p90,
               count(DISTINCT sender_id) sess
        FROM ( {AUTHORED} ) a
        WHERE created_at >= '2026-07-28'
        GROUP BY 1 ORDER BY 1
    """ ) ).mappings():
        print( f"{str(r['day']):<12}{r['n']:>6}{r['mean']:>8}{r['p50']:>6.0f}{r['p90']:>7.0f}{r['sess']:>6}" )

    print( "\n=== pooled before/after cutover 2026-08-13 14:14 EDT ===" )
    for label, pred in [ ("BEFORE","created_at <  '2026-08-13 14:14:00-04'"),
                         ("AFTER" ,"created_at >= '2026-08-13 14:14:00-04'") ]:
        r = conn.execute( text( f"""
            SELECT count(*) n, round(avg(len)::numeric,1) mean,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY len) p50,
                   percentile_cont(0.9) WITHIN GROUP (ORDER BY len) p90,
                   count(*) FILTER (WHERE len > 500) over_cap
            FROM ( {AUTHORED} ) a
            WHERE created_at >= '2026-07-28' AND {pred}
        """ ) ).mappings().one()
        print( label, dict(r) )

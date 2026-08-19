import os, sys
lupin_root = os.environ.get( "LUPIN_ROOT", "/mnt/DATA01/include/www.deepily.ai/projects/lupin" )
src_path   = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )
from sqlalchemy import create_engine, text
from cosa.rest.db.database import get_database_url
engine = create_engine( get_database_url() )

AUTHORED = """
SELECT n.created_at, split_part(split_part(n.sender_id,'@',2),'.',1) AS proj,
       length(n.message) AS len
FROM notifications n
JOIN ( SELECT message FROM notifications
       WHERE direction='ai_to_human' AND sender_id LIKE 'claude.code@%%'
       GROUP BY message HAVING count(*) <= 2 ) u ON u.message = n.message
WHERE n.direction='ai_to_human' AND n.sender_id LIKE 'claude.code@%%'
  AND n.type IN ('progress','task','alert','custom')
  AND n.message NOT LIKE 'Done: %%' AND length(n.message) > 15
  AND n.created_at >= '2026-07-28'
"""
CUT = "'2026-08-13 14:14:00-04'"

with engine.connect() as conn:
    print( "=== by project, before vs after cutover ===" )
    print( f"{'project':<22}{'side':<8}{'n':>6}{'mean':>8}{'p50':>7}{'p90':>8}" )
    for r in conn.execute( text( f"""
        SELECT proj,
               CASE WHEN created_at < {CUT} THEN 'before' ELSE 'after' END AS side,
               count(*) n, round(avg(len)::numeric,1) mean,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY len) p50,
               percentile_cont(0.9) WITHIN GROUP (ORDER BY len) p90
        FROM ( {AUTHORED} ) a
        GROUP BY 1,2 HAVING count(*) >= 40
        ORDER BY proj, side DESC
    """ ) ).mappings():
        print( f"{r['proj']:<22}{r['side']:<8}{r['n']:>6}{r['mean']:>8}{r['p50']:>7.0f}{r['p90']:>8.0f}" )

    # Equal-window comparison: 8 days each side, to kill the ragged-window effect
    print( "\n=== equal 8-day windows (08-05..08-13 vs 08-13..08-21) ===" )
    for label, pred in [ ("before", f"created_at >= '2026-08-05' AND created_at < {CUT}"),
                         ("after",  f"created_at >= {CUT}") ]:
        r = conn.execute( text( f"""
            SELECT count(*) n, round(avg(len)::numeric,1) mean,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY len) p50,
                   percentile_cont(0.9) WITHIN GROUP (ORDER BY len) p90
            FROM ( {AUTHORED} ) a WHERE {pred}
        """ ) ).mappings().one()
        print( label, dict(r) )

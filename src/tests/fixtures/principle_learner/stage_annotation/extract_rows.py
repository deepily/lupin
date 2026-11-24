"""
Pull the 23 re-spin evidence rows from the run 2 archive, labels kept apart.

Run it read-only against the durable copy. It writes two files: the label-free input an annotator reads,
and the labels. The annotator must not open the labels until the annotation file and its sha256 exist.
"""

import json
import sqlite3
import sys

PRINCIPLE_ID = "4615b6f95e9d41ba9035f4d1ce4753d7"
TITLE_MARK   = "context ceiling"
EXPECTED     = 23

QUERY = """select e.id, e.notification_id, n.title, n.message, n.abstract, n.response_value, n.response_default, n.created_at, e.answered_at,
                  e.relation, e.condition
           from preference_evidence e join notifications n on n.id = e.notification_id
           where e.principle_id = ? and n.title like ?
           order by e.answered_at, e.id"""


def answer_text( stored ):
    """
    Read the owner's answer text from a stored response value.

    Requires:
        - stored is a JSON string, a dict or None

    Ensures:
        - returns the dict's "value" when stored holds a dict, else the text of whatever it holds
    """
    value = json.loads( stored ) if isinstance( stored, str ) else stored
    return value.get( "value" ) if isinstance( value, dict ) else str( value )


def extract( db_path ):
    """
    Read the evidence rows of the re-spin principle that sit on re-spin cards.

    Requires:
        - db_path names a SQLite archive with preference_evidence and notifications

    Ensures:
        - opens the file read-only and immutable, so nothing in it changes
        - returns ( label_free, labels ), one entry per row in answer order, numbered from 1
        - label_free carries the card text, the owner's answer, the card default and the two times, and no relation or condition
        - labels carries the evidence id, the relation and the condition

    Raises:
        - ValueError when the row count is not 23, so a changed population is never annotated in silence
    """
    db   = sqlite3.connect( f"file:{db_path}?mode=ro&immutable=1", uri=True )
    rows = db.execute( QUERY, ( PRINCIPLE_ID, f"%{TITLE_MARK}%" ) ).fetchall()
    if len( rows ) != EXPECTED: raise ValueError( f"expected {EXPECTED} rows, the query found {len( rows )}" )
    label_free = [ { "row": number, "evidence_id": row[ 0 ], "notification_id": row[ 1 ], "title": row[ 2 ], "message": row[ 3 ], "abstract": row[ 4 ],
                     "owner_answer": answer_text( row[ 5 ] ), "card_default": row[ 6 ], "asked_at": row[ 7 ], "answered_at": row[ 8 ] }
                   for number, row in enumerate( rows, 1 ) ]
    labels     = [ { "row": number, "evidence_id": row[ 0 ], "relation": row[ 9 ], "condition": row[ 10 ] } for number, row in enumerate( rows, 1 ) ]
    return label_free, labels


def main( argv ):
    """
    Write the label-free input and the labels beside each other.

    Requires:
        - argv is [ archive path, label-free output path, labels output path ]

    Ensures:
        - writes both JSON files and returns 0
    """
    label_free, labels = extract( argv[ 0 ] )
    for path, content in ( ( argv[ 1 ], label_free ), ( argv[ 2 ], labels ) ):
        with open( path, "w", encoding="utf-8" ) as handle: json.dump( content, handle, indent=1 )
    return 0


if __name__ == "__main__":
    sys.exit( main( sys.argv[ 1: ] ) )  # pragma: no cover  (the entry point is the one line the unit test cannot reach)

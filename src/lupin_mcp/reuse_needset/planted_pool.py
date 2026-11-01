"""
The planted pool of the positive control: the search over rewrites held in memory.

The live checker asks the resident search on the Lupin server, which reads the vector set from disk.
This module answers the same two requests in this process instead.
The rewrites get their own vector rows from our embedding server, and those rows exist only here. The live vector set, the symindex and the server are never written.
"""
import os

from cosa.repo.symindex.candidates import resident, search
from cosa.repo.symindex.candidates import vector_build as vb
from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates.errors import CandidateError
from lupin_mcp import reuse_candidates as rc

STATUS_OF = { "BAD_STAGE_UPLOAD": 422, "BAD_SEARCH_REQUEST": 422, "STAGE_UNKNOWN": 409, "VECTOR_SET_REPLACED": 409, "PATH_REFUSED": 403 }
PURPOSE   = ""


def planted_entry( rewrite ):
    """
    Build the index record a rewrite is searched and judged by.

    Requires:
        - rewrite holds id, file, name and sig; line, end_line, public and text may be absent

    Ensures:
        - returns the index fields the candidate stage and the judge read: id, file, module, name, sig, doc, pin, scope, line, end_line
        - doc is empty, because a real rewrite carries no docstring field; module is the file path without its extension
        - pin is the first 10 hex of the sha256 of the rewrite's text, so it changes when the text does
    """
    import hashlib
    text = rewrite[ "text" ] if "text" in rewrite else ""
    return { "id": rewrite[ "id" ], "file": rewrite[ "file" ], "module": os.path.splitext( rewrite[ "file" ] )[ 0 ].replace( "/", "." ), "name": rewrite[ "name" ],
             "sig": rewrite[ "sig" ], "doc": "", "pin": hashlib.sha256( text.encode( "utf-8" ) ).hexdigest()[ :10 ],
             "scope": "public" if ( "public" not in rewrite or rewrite[ "public" ] ) else "private",
             "line": rewrite[ "line" ] if "line" in rewrite else 1, "end_line": rewrite[ "end_line" ] if "end_line" in rewrite else 1 }


class PlantedVectors:
    """
    A loaded vector set with extra rows held in memory.

    Requires:
        - base has ids, matrices ( name to an array of one row per id ) and manifest_hash
        - extra_ids are ids the base lacks; extra_rows maps each matrix name to one row per extra id

    Ensures:
        - ids are the base ids then the extra ids; each matrix is the base rows then the extra rows
        - manifest_hash is the base's, so the live set's hash still matches the one the caller expects
        - the base is not changed
    """

    def __init__( self, base, extra_ids, extra_rows ):
        """Stack the extra rows under the base rows."""
        import numpy as np
        self.ids           = [ *base.ids, *extra_ids ]
        self.matrices      = { name: np.vstack( [ np.asarray( base.matrices[ name ] ), np.asarray( extra_rows[ name ], dtype="<f4" ) ] ) for name in base.matrices }
        self.manifest_hash = base.manifest_hash


def embed_rows( entries, client ):
    """
    Embed the entries as the vector build does, one matrix at a time.

    Requires:
        - entries are index records with file, name, sig and doc; client has embed( texts, content_type, role )

    Ensures:
        - returns { matrix name: one vector per entry, in order }
        - the texts, engines and roles are those of vector_build.build_vectors, so a planted row sits in the same space as the live rows
        - these are embedding calls, not model calls
    """
    texts = [ vb.entry_texts( e, PURPOSE ) for e in entries ]
    out   = {}
    for name in vs.MATRICES:
        content_type, role = vs.DOCUMENT_ROLES[ name ]
        out[ name ] = client.embed( [ t[ name ] for t in texts ], content_type, role )
    return out


class PlantedCandidateStage( rc.CandidateStage ):
    """
    The candidate stage client, answering from this process over planted vector rows.

    Requires:
        - vectors_dir is the live vector set's folder, read for its manifest only
        - planted is a PlantedVectors over that set

    Ensures:
        - every request the parent would send over HTTP is answered by a ResidentSearch in this process
        - no refresher is allowed, so nothing rebuilds or writes the live vector set
    """

    def __init__( self, vectors_dir, query_cache_dir, embed_client, planted, **kwargs ):
        """Hold an in-process resident search that loads the planted vectors, not the disk."""
        if kwargs.get( "refresher" ) is not None: raise ValueError( "a planted stage may not refresh the live vector set" )
        super().__init__( "http://in-process", "", vectors_dir, query_cache_dir, embed_client, **kwargs )
        self._resident = resident.ResidentSearch( os.path.realpath( vectors_dir ), load_vectors=lambda _folder: planted )

    def _call( self, method, path, body ):
        """
        Answer the stage upload and the search the way the server does.

        Ensures:
            - returns ( status, body ) with the router's status for a named candidate error, 503 for any other, and 200 for an answer
        """
        try:
            if method == "PUT": return 200, self._resident.put_stage( body[ "key" ], body[ "entries" ], body[ "purposes" ], body[ "fusion" ] )
            return 200, self._resident.search( body )
        except CandidateError as e:
            return STATUS_OF[ e.code ] if e.code in STATUS_OF else 503, { "error": e.code, "detail": e.detail }

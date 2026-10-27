"""
Pair labelling router: one reviewer labels the pairs of a blind packet from the browser.

Three routes:

- GET /api/pair-labelling/state: how many are labelled, and where to resume.
- GET /api/pair-labelling/item: one pair by position, with the reviewer's label if there is one.
- POST /api/pair-labelling/label: write one label to disk, replacing an earlier label of that pair.

The router reads one file, packet-<reviewer>.jsonl in the packets folder, and writes labels-<reviewer>.jsonl beside it.
It never opens the run's key folder.
A pair is sent as its id and its two texts, with no type and no origin.
"""
import os
import pathlib
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import cosa.utils.util as cu
from cosa.repo.labelling import errors as er
from cosa.repo.labelling import packets as pk
from cosa.repo.labelling import pair_labels as pl
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

router = APIRouter( prefix="/api/pair-labelling", tags=[ "pair-labelling" ] )

DIR_VARIABLE  = "LUPIN_PAIR_LABELLING_DIR"
DEFAULT_DIR   = "io/semdup-labelling/2026.10.25-run5/packets"
DEFAULT_REVIEWER = "rick"


class LabelUpload( BaseModel ):
    """One answer: the pair, same job or not, whether the reviewer is unsure, and a note."""

    item_id  : str
    same_job : bool
    unsure   : bool = False
    note     : str = ""
    reviewer : str = DEFAULT_REVIEWER


def packets_dir():
    """
    Name the folder that holds the packets.

    Ensures:
        - returns the value of LUPIN_PAIR_LABELLING_DIR when it is set, else the packets folder of the default run under the project root
    """
    if os.environ.get( DIR_VARIABLE, "" ).strip(): return pathlib.Path( os.environ[ DIR_VARIABLE ].strip() )
    return pathlib.Path( cu.get_project_root() ) / DEFAULT_DIR


def packet_for( reviewer ):
    """
    Return the packet path of a reviewer.

    Raises:
        - HTTPException 422 for a name that is not letters, digits, _ and -; 404 when the reviewer has no packet
    """
    if not pk.NAME_RE.fullmatch( reviewer ): raise HTTPException( status_code=422, detail="the reviewer name may hold only letters, digits, _ and -" )
    path = pk.packet_path( packets_dir(), reviewer )
    if not path.is_file(): raise HTTPException( status_code=404, detail=f"no packet for {reviewer}" )
    return path


def read_state( reviewer ):
    """
    Read a reviewer's packet and labels.

    Ensures:
        - returns ( path, items, labels )

    Raises:
        - HTTPException from packet_for, and 500 naming the labelling error for a packet or labels file that is not valid
    """
    path = packet_for( reviewer )
    try:
        return path, pl.load_items( path ), pl.read_existing( path )
    except er.LabellingError as e:
        raise HTTPException( status_code=500, detail=str( e ) )


@router.get( "/state", summary="Progress of one reviewer" )
def state( reviewer: str = DEFAULT_REVIEWER, authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ] = None ):
    """
    Report progress.

    Ensures:
        - answers { reviewer, total, labelled, unsure, resume }; resume is the position to open, or null when every pair is labelled and none is unsure
    """
    _, items, labels = read_state( reviewer )
    return { "reviewer": reviewer, **pl.progress( items, labels ) }


@router.get( "/item", summary="One pair" )
def item( position: int, reviewer: str = DEFAULT_REVIEWER, authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ] = None ):
    """
    Send one pair.

    Ensures:
        - answers { position, total, labelled, item_id, a, b, label }; label is null or { same_job, unsure, note }

    Raises:
        - HTTPException 404 for a position outside the packet
    """
    _, items, labels = read_state( reviewer )
    if not 0 <= position < len( items ): raise HTTPException( status_code=404, detail=f"position {position} is outside 0..{len( items ) - 1}" )
    mine  = items[ position ]
    given = next( ( l for l in labels if l[ "item_id" ] == mine[ "item_id" ] ), None )
    label = None if given is None else { "same_job": pl.same_job( given ), "unsure": pl.is_unsure( given ), "note": pl.user_note( given ) }
    return { "position": position, "total": len( items ), "labelled": len( labels ), **mine, "label": label }


@router.post( "/label", summary="Write one label" )
def label( upload: LabelUpload, authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ] = None ):
    """
    Write one label to disk before answering.

    Ensures:
        - answers the progress of the reviewer after the write, as state does

    Raises:
        - HTTPException 404 for a pair not in the packet; 422 for a note over the limit
    """
    path = packet_for( upload.reviewer )
    try:
        pl.save_label( path, upload.item_id, upload.same_job, upload.unsure, upload.note )
    except er.LabellingError as e:
        raise HTTPException( status_code=404 if e.code == er.BAD_ITEM else 422, detail=str( e ) )
    return state( upload.reviewer )

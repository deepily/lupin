"""
Row 081dac6d — the classic task list shows the server's HOLDING AREA note as one line,
"N waiting for your approval", instead of printing the whole session-facing paragraph.

The page recognizes the note by a stable phrase plus its leading count
(`NotificationsUI._holdingAreaWarningCount` in notifications.js). That is a coupling
between two files in two languages, so this test pins it from the server side: it takes
the note the REAL router emits and runs it through the REAL page method under node.
Reword the note in tasks.py so the page no longer recognizes it, and this turns red.

⚠️ A SKIP IS NOT A PASS. Without node on PATH the coupling was not checked.
"""

import json
import shutil
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cosa.rest.routers import tasks
from cosa.rest.postgres_models import TaskItem


HOLDING          = "not_approved"
_NOW             = datetime( 2026, 9, 16, 18, 0, tzinfo=timezone.utc )
NOTIFICATIONS_JS = Path( tasks.__file__ ).resolve().parents[ 2 ].parent / "lupin_app" / "static" / "js" / "notifications.js"

# Loads the page class the same way the TS harness does (sliced before the DOM-ready
# init) and prints the recognizer's answer for each warning passed on stdin.
_NODE_PROBE = """
const fs = require( "fs" ), vm = require( "vm" );
const src = fs.readFileSync( process.argv[ 1 ], "utf8" );
const cut = src.indexOf( "// Initialize when DOM is ready" );
if ( cut <= 0 ) { console.error( "init marker not found" ); process.exit( 3 ); }
vm.runInThisContext( src.slice( 0, cut ) + "\\n;globalThis.NotificationsUI = NotificationsUI;" );
const ui = Object.create( NotificationsUI.prototype );
const warnings = JSON.parse( fs.readFileSync( 0, "utf8" ) );
console.log( JSON.stringify( warnings.map( w => ui._holdingAreaWarningCount( w ) ) ) );
"""


def _item():
    return TaskItem(
        id = uuid.uuid4(), item_class = "task", title = "a row", body = None, project = "lupin",
        owner_persona = "krishna", accountable_manager = "mr radio", created_by = "krishna 056ca4c8",
        status = "queued", blocked_by = [ ], next_chase_ts = None, gate_class = "none", priority = "P2",
        source_qid = None, correlation_key = None, created_ts = _NOW, updated_ts = _NOW, title_trimmed = False,
    )


@pytest.fixture
def api( monkeypatch ):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

    fake = MagicMock()
    # Discriminates on status: the held count must come from the held-rows question only.
    fake.count_tasks.side_effect               = lambda **kw: 7 if kw.get( "status" ) == HOLDING else 1
    fake.query_tasks.side_effect               = lambda **kw: [ _item() ]
    fake.statuses_for_ids.return_value         = { }
    fake.count_tasks_by_project.return_value   = { }
    fake.count_tasks_by_priority.return_value  = { }
    fake.count_tasks_by_status.return_value    = { }
    fake.count_created_and_closed.return_value = { "created": 0, "closed": 0 }

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )

    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app )


def _page_counts( warnings ):
    node = shutil.which( "node" )
    if node is None:
        pytest.skip( "node not on PATH — THE PAGE/SERVER COUPLING WAS NOT CHECKED" )
    assert NOTIFICATIONS_JS.is_file(), f"page script not found at {NOTIFICATIONS_JS}"
    run = subprocess.run(
        [ node, "-e", _NODE_PROBE, str( NOTIFICATIONS_JS ) ],
        input = json.dumps( warnings ), capture_output = True, text = True, timeout = 60,
    )
    assert run.returncode == 0, f"node probe failed: {run.stderr}"
    return json.loads( run.stdout )


def test_the_page_recognizes_the_note_the_server_actually_sends( api ):
    body     = api.get( "/api/tasks" ).json()
    warnings = body.get( "warnings", [ ] )
    held     = [ w for w in warnings if HOLDING in w ]
    assert len( held ) == 1, f"the router must still emit one holding note for this fixture: {warnings}"

    counts = _page_counts( held )
    assert counts == [ 7 ], (
        f"the page no longer recognizes the server's holding-area note, so it would print the "
        f"whole paragraph again. Update _holdingAreaWarningCount in notifications.js to match: {held[ 0 ]!r}"
    )


def test_the_page_leaves_other_warnings_alone():
    assert _page_counts( [ "some unrelated server warning", "⚠️ 3 row(s) are elsewhere" ] ) == [ None, None ]

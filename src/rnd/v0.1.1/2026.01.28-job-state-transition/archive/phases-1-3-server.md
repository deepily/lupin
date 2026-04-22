# Phases 1-3: Server-Side Implementation

**Status**: In Progress
**Completed**: 2026-01-28

## Phase 1: Configuration (Complete)

### Changes Made

**File**: `src/conf/lupin-app.ini` (line 434)

Added `job_state_transition` to websocket available events:
```ini
websocket available events = queue_todo_update, queue_done_update, queue_running_update, queue_dead_update, job_state_transition, ...
```

**File**: `src/conf/lupin-app-splainer.ini` (line 63)

Added explainer text:
```ini
websocket available events = ... Includes job_state_transition for fine-grained job queue movement notifications (todo->run, run->done, run->dead) with optional completion metadata.
```

---

## Phase 2: Emit Method (Complete)

### Changes Made

**File**: `src/cosa/rest/fifo_queue.py` (after line 636)

Added `_emit_job_state_transition()` method:

```python
def _emit_job_state_transition( self, job_id: str, from_queue: str, to_queue: str, user_id: str = None, metadata: dict = None ) -> None:
    """
    Emit job state transition event with optional completion metadata.
    """
    if not self.websocket_mgr:
        return

    from datetime import datetime

    data = {
        'job_id'     : job_id,
        'from_queue' : from_queue,
        'to_queue'   : to_queue,
        'timestamp'  : datetime.now().isoformat()
    }

    if metadata:
        data[ 'metadata' ] = metadata

    try:
        if user_id:
            self.websocket_mgr.emit_to_user_sync( user_id, 'job_state_transition', data )
        else:
            self.websocket_mgr.emit( 'job_state_transition', data )
        if hasattr( self, 'debug' ) and self.debug:
            print( f"[QUEUE] Emitted job_state_transition: {job_id} ({from_queue} -> {to_queue})" )
    except Exception as e:
        print( f"[ERROR] _emit_job_state_transition failed: {e}" )
```

---

## Phase 3: Server Emissions (In Progress)

### Emission Pattern for Success (run → done)

```python
job_id  = getattr( running_job, 'id_hash', None )
user_id = self.user_job_tracker.get_user_for_job( job_id ) if job_id else None
metadata = {
    'response_text' : getattr( running_job, 'answer_conversational', '' ),
    'abstract'      : running_job.artifacts.get( 'abstract' ) if hasattr( running_job, 'artifacts' ) else None,
    'report_link'   : running_job.artifacts.get( 'report_path' ) if hasattr( running_job, 'artifacts' ) else None,
    'cost_summary'  : running_job.artifacts.get( 'cost_summary' ) if hasattr( running_job, 'artifacts' ) else None,
    'error'         : None
}
self._emit_job_state_transition( job_id, 'run', 'done', user_id, metadata )
```

### Emission Pattern for Error (run → dead)

```python
job_id  = getattr( running_job, 'id_hash', None )
user_id = self.user_job_tracker.get_user_for_job( job_id ) if job_id else None
metadata = { 'error': error_msg }
self._emit_job_state_transition( job_id, 'run', 'dead', user_id, metadata )
```

### Completed Emissions

1. **Agentic Success** (line 274): run → done with full metadata
2. **Agentic Failure** (line 307): run → dead with error
3. **Agentic Crash** (line 335): run → dead with error
4. **Base Agent** (line 436): run → done with full metadata

### Remaining Emissions

5. **Solution Snapshot** (~line 480): run → done with full metadata
6. **Cache Hit** (~line 575): run → done with full metadata
7. **Queue Consumer** (~line 64): todo → run (no metadata)

# SSE Notification System - Conceptual Q&A

**Last Updated**: 2025.10.15

## Related Documentation

- **[Index](00-index.md)**: Master navigation
- **[Current Implementation](01-implementation-current.md)**: Active phases
- **[Architecture](02-architecture.md)**: System design
- **[Decisions](03-decisions.md)**: Decision log
- **[Testing](04-testing-validation.md)**: Test strategy

---

## Purpose

This document captures conceptual questions and clarifications about SSE implementation patterns, async/await semantics, and production considerations. These insights emerged during Phase 1 development and are preserved here for future reference.

---

## Q1: Async vs Sync - Isn't the event_generator() blocking?

### The Question

The Phase 1 PoC has this code in `server.py`:

```python
# Simulate async processing with heartbeats
elapsed = 0
while elapsed < processing_time:
    await asyncio.sleep( heartbeat_interval )
    elapsed = asyncio.get_event_loop().time() - start_time

    # Send heartbeat
    heartbeat_event = {
        "type": "heartbeat",
        "elapsed": round( elapsed, 2 )
    }
    yield f"data: {json.dumps( heartbeat_event )}\n\n"
```

**Question**: This while loop doesn't exit until `elapsed < processing_time` is false. Isn't that blocking? Isn't that the very definition of synchronous processing?

### The Answer

**Yes and No** - there are TWO different meanings of "synchronous/asynchronous" at play:

#### 1. Client Perspective (Synchronous Notification)

- **Client blocks and waits** for the server to finish processing
- **Client cannot do other work** while waiting (stuck in SSE stream)
- This is what we mean by "synchronous notification system"

**Example**: The bash wrapper script waits for result:
```bash
# This command BLOCKS until result received or timeout
result=$( ./send-notification-from-claude-sync "Test message" 5 120 )
```

#### 2. Server Perspective (Asynchronous Execution)

- **Event loop is NOT blocked** during processing
- **Server can handle other clients** concurrently
- This is what `await asyncio.sleep()` provides

**Key Distinction**: `await asyncio.sleep()` vs `time.sleep()`

### Blocking vs Non-Blocking on the Server

**Synchronous/Blocking** (BAD for servers):

```python
import time

# This BLOCKS the entire event loop
while elapsed < processing_time:
    time.sleep( heartbeat_interval )  # ❌ NOTHING ELSE CAN RUN
    elapsed = time.time() - start_time
    yield heartbeat_event
```

**Problem**: While this function sleeps, the ENTIRE FastAPI server is frozen. No other requests can be processed.

---

**Asynchronous/Non-Blocking** (GOOD for servers):

```python
import asyncio

# This YIELDS control back to the event loop
while elapsed < processing_time:
    await asyncio.sleep( heartbeat_interval )  # ✅ Event loop runs other tasks
    elapsed = asyncio.get_event_loop().time() - start_time
    yield heartbeat_event
```

**Benefit**: During `await asyncio.sleep()`, the event loop can:
- Handle other SSE connections
- Process other API requests
- Run background tasks
- etc.

### Mental Model

**Client-Side** (Your bash script):
```
Request sent → [WAITING BLOCKING] → Response received
                     ^
                     |
            Client can't do anything else
```

**Server-Side** (FastAPI event loop):
```
Request A → [Process... await... yield control... resume... yield control... done]
Request B →    [Process... await... yield control... resume... done]
Request C →                  [Process... await... resume... done]
                 ^
                 |
         Server handles all three concurrently!
```

### Summary

- **Client**: Synchronous (blocks waiting for response)
- **Server**: Asynchronous (event loop not blocked, handles multiple requests)
- **While loop**: Function doesn't exit until complete (true), but yields control during `await` (non-blocking)

---

## Q2: How do you send heartbeats while doing REAL work?

### The Question

The Phase 1 PoC simulates work by sleeping:

```python
# PoC - FAKE work
while elapsed < processing_time:
    await asyncio.sleep( heartbeat_interval )  # The "work" IS the sleep
    yield heartbeat_event
```

**Question**: In production, you need to do ACTUAL work while ALSO sending heartbeats. That sounds like two separate threads of execution. How does this work?

### The Answer

You don't need threads - you use **cooperative multitasking** with `asyncio.create_task()`.

### The PoC Is Cheating

You're right to be suspicious. The PoC works because the "work" and the "heartbeat" are the **same thing** - we're just sleeping! This doesn't reflect real-world usage.

### Real Production Patterns

#### Pattern 1: If Your Work Is Already Async

```python
async def event_generator_production():
    """
    Real work that's already async-friendly (database queries, HTTP calls, etc.)
    """
    # Start the long-running async work as a Task
    work_task = asyncio.create_task(
        async_database_query()  # Long-running async operation
    )

    # Send ack
    yield f"data: {json.dumps({'type': 'ack', 'message': 'Request received'})}\n\n"

    # While work is running, send heartbeats
    while not work_task.done():
        await asyncio.sleep( heartbeat_interval )
        yield f"data: {json.dumps({'type': 'heartbeat', 'elapsed': elapsed})}\n\n"

    # Work is done, get the result
    result = await work_task
    yield f"data: {json.dumps({'type': 'result', 'data': result})}\n\n"
```

**Key**: `asyncio.create_task()` starts the work **in the background**, then you periodically check if it's done while sending heartbeats.

---

#### Pattern 2: If Your Work Is Synchronous (Blocking)

```python
async def event_generator_production():
    """
    Real work that's blocking/synchronous (legacy code, CPU-bound, etc.)
    """
    from concurrent.futures import ThreadPoolExecutor

    # Run blocking work in a thread pool
    executor = ThreadPoolExecutor()
    loop = asyncio.get_event_loop()
    work_task = loop.run_in_executor(
        executor,
        blocking_database_query  # Synchronous blocking function
    )

    # Send ack
    yield f"data: {json.dumps({'type': 'ack', 'message': 'Request received'})}\n\n"

    # While work is running, send heartbeats
    while not work_task.done():
        await asyncio.sleep( heartbeat_interval )
        yield f"data: {json.dumps({'type': 'heartbeat', 'elapsed': elapsed})}\n\n"

    # Work is done, get the result
    result = await work_task
    yield f"data: {json.dumps({'type': 'result', 'data': result})}\n\n"
```

**Key**: `run_in_executor()` runs the blocking function in a separate thread, returning a Future you can await.

### How Cooperative Multitasking Works

It's all in **ONE thread**, cooperatively switching between tasks:

```python
# Start work (doesn't block!)
task = asyncio.create_task( long_running_work() )

# Periodically check if done
while not task.done():
    await asyncio.sleep(5)  # Yields control to event loop
    yield heartbeat         # Returns to this point after ~5s, checks again
```

**What happens**:
1. `create_task()` schedules work on the event loop (non-blocking)
2. `while not task.done()` checks if work finished (non-blocking check)
3. `await asyncio.sleep(5)` yields control back to event loop
4. Event loop runs the work task, other requests, etc.
5. After ~5 seconds, execution resumes at the heartbeat yield
6. Loop repeats until work completes

**It's all in ONE thread**, cooperatively switching between:
- Your long-running work
- Your heartbeat loop
- Other incoming requests

---

### Concrete Production Example

Here's what Phase 2 might actually look like:

```python
async def event_generator_real_work( user_message: str ):
    """
    Real production SSE endpoint that sends an email notification
    and waits for user response (click link in email).
    """
    # Start async work: send email, poll database for user click
    notification_task = asyncio.create_task(
        send_email_and_wait_for_response( user_message )
    )

    # Send ack
    yield f"data: {json.dumps({'type': 'ack', 'message': 'Email sent'})}\n\n"

    # Send heartbeats while waiting for user to click email link
    start_time = time.time()
    while not notification_task.done():
        await asyncio.sleep( 5 )
        elapsed = time.time() - start_time

        # Check timeout
        if elapsed > 120:
            notification_task.cancel()
            yield f"data: {json.dumps({'type': 'error', 'message': 'Timeout'})}\n\n"
            return

        # Send heartbeat
        yield f"data: {json.dumps({'type': 'heartbeat', 'elapsed': elapsed})}\n\n"

    # User clicked! Get response
    user_response = await notification_task
    yield f"data: {json.dumps({'type': 'result', 'data': user_response})}\n\n"
```

**In this example**:
- **Work**: Send email, poll database for user response (async task)
- **Heartbeats**: Sent every 5s while polling (cooperative loop)
- **Both happen "simultaneously"** via cooperative multitasking (no threads needed)

---

### When Are Heartbeats Necessary?

| Operation Duration | Heartbeat Needed? | Reason |
|-------------------|------------------|--------|
| < 30 seconds | Optional | Client/proxy timeouts usually 30-60s |
| 30-60 seconds | Recommended | Approaching timeout thresholds |
| > 60 seconds | **Required** | Most proxies/browsers will timeout |
| > 120 seconds | **Critical** | Your configured timeout |

**Real-world example**: Database query takes 90 seconds
- **Without heartbeats**: Connection times out at ~60s, client gets error
- **With heartbeats**: Client sees `[HEARTBEAT]` every 5s, knows work is progressing

---

## Key Takeaways

1. **Async/Sync Terminology**:
   - Client perspective: Synchronous (blocks waiting)
   - Server perspective: Asynchronous (event loop not blocked)

2. **PoC Limitation**:
   - Phase 1 simulates work with `asyncio.sleep()` (work = waiting)
   - Phase 2 will do real work with `asyncio.create_task()` (work + heartbeats concurrently)

3. **No Threading Needed**:
   - Cooperative multitasking via async/await
   - Single event loop handles everything

4. **Heartbeats Are Critical**:
   - Required for operations > 60 seconds
   - Prevent connection timeouts
   - Provide progress feedback

---

*Token count target: 2,000-4,000*
*Update as more conceptual questions arise*

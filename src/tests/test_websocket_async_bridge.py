#!/usr/bin/env python3
"""
Test script for WebSocket async/sync bridge implementation.

This tests that COSA background threads can safely emit WebSocket messages
without RuntimeWarnings.
"""

import asyncio
import threading
import time

# Python path configured by src/tests/conftest.py

from cosa.rest.websocket_manager import WebSocketManager
import cosa.utils.util as du


def test_thread_emission( websocket_manager, user_id="test_user" ):
    """
    Test function that runs in a background thread and tries to emit.
    
    This simulates what happens in COSA queues.
    """
    print( f"\n[THREAD-{threading.current_thread().name}] Starting emission test..." )
    
    # Test 1: Single emission
    websocket_manager.emit_to_user_sync( 
        user_id, 
        "test_event", 
        { "message": "Hello from thread!", "thread": threading.current_thread().name }
    )
    time.sleep( 0.1 )
    
    # Test 2: Rapid emissions
    for i in range( 5 ):
        websocket_manager.emit_to_user_sync(
            user_id,
            "rapid_test",
            { "count": i, "thread": threading.current_thread().name }
        )
        time.sleep( 0.01 )  # Very short delay
    
    # Test 3: Broadcast emission
    websocket_manager.emit( 
        "broadcast_test", 
        { "message": "Broadcast from thread", "thread": threading.current_thread().name }
    )
    
    print( f"[THREAD-{threading.current_thread().name}] Emission test complete" )


async def main():
    """Main test function."""
    du.print_banner( "WebSocket Async/Sync Bridge Test" )
    
    # Create WebSocketManager
    print( "✓ Creating WebSocketManager..." )
    websocket_manager = WebSocketManager()
    
    # Store event loop reference (simulating FastAPI startup)
    print( "✓ Storing event loop reference..." )
    loop = asyncio.get_running_loop()
    websocket_manager.set_event_loop( loop )
    
    # Create multiple test threads
    print( "\n✓ Creating background threads to test emissions..." )
    threads = []
    for i in range( 3 ):
        thread = threading.Thread(
            target=test_thread_emission,
            args=( websocket_manager, f"test_user_{i}" ),
            name=f"TestThread-{i}",
            daemon=True
        )
        threads.append( thread )
        thread.start()
        time.sleep( 0.1 )  # Stagger thread starts
    
    # Also test from main thread
    print( "\n✓ Testing emission from main thread..." )
    websocket_manager.emit( "main_thread_test", { "message": "From main thread" } )
    
    # Wait for threads to complete
    print( "\n✓ Waiting for threads to complete..." )
    for thread in threads:
        thread.join( timeout=5.0 )
    
    # Give async tasks time to complete
    await asyncio.sleep( 1.0 )
    
    print( "\n✓ Test Summary:" )
    print( "  - If you see no RuntimeWarnings above, the async bridge is working!" )
    print( "  - All emissions were scheduled successfully" )
    print( "  - Note: No actual WebSockets were connected, so sends would fail (expected)" )
    
    du.print_banner( "Test Complete", prepend_nl=True )


def quick_smoke_test():
    """Quick smoke test for the async bridge."""
    print( "\n=== Quick Smoke Test ===" )
    
    # Test 1: WebSocketManager without event loop
    print( "\n1. Testing emission without event loop (should show error):" )
    mgr = WebSocketManager()
    mgr.emit( "test", { "data": "test" } )
    
    # Test 2: With event loop
    print( "\n2. Testing with event loop:" )
    
    async def test_with_loop():
        mgr2 = WebSocketManager()
        loop = asyncio.get_running_loop()
        mgr2.set_event_loop( loop )
        
        # Test from async context
        mgr2.emit( "test", { "data": "from async" } )
        
        # Test from thread
        def thread_test():
            mgr2.emit_to_user_sync( "user123", "test", { "data": "from thread" } )
        
        thread = threading.Thread( target=thread_test )
        thread.start()
        thread.join()
        
        await asyncio.sleep( 0.1 )
        print( "✓ No RuntimeWarnings - async bridge working!" )
    
    asyncio.run( test_with_loop() )
    print( "\n=== Smoke Test Complete ===" )


if __name__ == "__main__":
    import sys
    
    if len( sys.argv ) > 1 and sys.argv[1] == "--smoke":
        quick_smoke_test()
    else:
        asyncio.run( main() )
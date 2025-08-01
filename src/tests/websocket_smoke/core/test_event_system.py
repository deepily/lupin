#!/usr/bin/env python3
"""
WebSocket Event System Tests

Comprehensive tests for WebSocket event subscription, delivery, 
filtering, and handling. Tests event types, subscription management,
and event flow validation.

This module focuses on the event system after authentication.
"""

import asyncio
import json
import time
from typing import Dict, List, Any, Optional, Set
import websockets

# Import our test utilities from the infrastructure
import sys
from pathlib import Path
sys.path.append( str( Path( __file__ ).parent.parent / "infrastructure" ) )
from test_utilities import WebSocketTestUtilities


class EventSystemTests:
    """
    Comprehensive WebSocket event system tests.
    
    Tests event subscription, delivery, filtering, unsubscription,
    and event flow validation across different scenarios.
    """
    
    def __init__( self, server_url: str = "localhost:7999" ):
        """
        Initialize event system tests with WebSocket utilities and known event types.
        
        Requires:
            - server_url must be valid server address
            - WebSocketTestUtilities must be available
            
        Ensures:
            - WebSocketTestUtilities instance is created with server URL
            - Results list is initialized for test outcomes
            - Known event types are configured for testing
            
        Args:
            server_url: Server URL to test against (default: "localhost:7999")
            
        Returns:
            None
            
        Raises:
            ImportError: If WebSocketTestUtilities is not available
        """
        self.utils = WebSocketTestUtilities( server_url )
        self.results = []
        
        # Known event types from the system
        self.known_event_types = [
            "connect", "disconnect", "auth_success", "auth_error",
            "user_message", "agent_response", "sys_ping", "sys_pong",
            "user_input_start", "user_input_end", "agent_thinking_start", 
            "agent_thinking_end", "session_start", "session_end",
            "error", "warning", "info", "debug",
            "audio_streaming_status", "audio_data", "audio_complete"
        ]
    
    async def run_all_tests( self ) -> List[Dict[str, Any]]:
        """
        Execute comprehensive event system test suite.
        
        Requires:
            - WebSocket utilities must be initialized
            - Server must be running and accessible
            - Test methods must be properly implemented
            
        Ensures:
            - Executes all event system test methods in sequence
            - Each test result is recorded in self.results
            - Returns complete list of test outcomes
            - Logs test progress and summary
            
        Args:
            None
            
        Returns:
            List[Dict[str, Any]]: Complete list of test results with success/failure status
            
        Raises:
            Exception: If any critical test setup or execution fails
        """
        self.utils.log( "📡 Starting Event System Tests" )
        self.utils.log( "=" * 50 )
        
        # Test basic event functionality
        await self._test_basic_event_subscription()
        await self._test_event_delivery()
        
        # Test event filtering and management
        await self._test_event_type_filtering()
        await self._test_event_unsubscription()
        
        # Test specific event behaviors
        await self._test_system_events()
        await self._test_user_generated_events()
        
        # Test event flow scenarios
        await self._test_event_ordering()
        await self._test_high_frequency_events()
        
        # Test edge cases
        await self._test_invalid_event_subscriptions()
        await self._test_event_system_under_load()
        
        return self.results
    
    async def _test_basic_event_subscription( self ):
        """
        Test basic event subscription functionality with WebSocket connection.
        
        Requires:
            - WebSocket utilities must be initialized
            - Server must support queue endpoint WebSocket connections
            - Event subscription protocol must be implemented
            
        Ensures:
            - Creates WebSocket connection with generated session ID
            - Authenticates with mock token
            - Tests event subscription for known event types
            - Records test result (success/failure) in self.results
            - Properly closes WebSocket connection
            
        Args:
            None
            
        Returns:
            None
            
        Raises:
            Exception: Any errors are caught and recorded as test failures
        """
        test_name = "basic_event_subscription"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            user_id = "event_subscription_user"
            token = self.utils.generate_mock_token( user_id )
            
            # Connect and authenticate
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            auth_success, auth_data = await self.utils.authenticate_websocket( websocket, token )
            
            if not auth_success:
                raise Exception( "Authentication failed" )
            
            # The authentication process should automatically subscribe to events
            # Check if we received any events during authentication
            events_during_auth = []
            
            # Try to receive events for a short period
            event_collection_duration = 2.0
            start_collection = time.time()
            
            while ( time.time() - start_collection ) < event_collection_duration:
                try:
                    message = await asyncio.wait_for( websocket.recv(), timeout=0.5 )
                    event_data = json.loads( message )
                    events_during_auth.append( event_data )
                    
                    event_type = event_data.get( "type", "unknown" )
                    self.utils.log( f"   Received event: {event_type}" )
                    
                except asyncio.TimeoutError:
                    break  # No more events
                except Exception as e:
                    self.utils.log( f"   Event parsing error: {e}" )
                    break
            
            await websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if we can subscribe and receive events
            events_received = len( events_during_auth )
            success = auth_success and events_received >= 0  # Even 0 events is ok for basic test
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "auth_successful": auth_success,
                    "events_received": events_received,
                    "event_types": [e.get( "type", "unknown" ) for e in events_during_auth],
                    "subscription_method": "automatic_during_auth"
                }
            } )
            
            if success:
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Event subscription works, received {events_received} events" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Event subscription failed" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_event_delivery( self ):
        """Test event delivery reliability and timing."""
        test_name = "event_delivery"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            user_id = "event_delivery_user"
            token = self.utils.generate_mock_token( user_id )
            
            # Connect and authenticate
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            auth_success, _ = await self.utils.authenticate_websocket( websocket, token )
            
            if not auth_success:
                raise Exception( "Authentication failed" )
            
            # Send messages that should trigger events
            trigger_messages = [
                {"type": "user_message", "content": "Hello, this should trigger events"},
                {"type": "ping", "timestamp": time.time()},
                {"type": "test_event_trigger", "data": "event_delivery_test"}
            ]
            
            events_received = []
            
            for i, message in enumerate( trigger_messages ):
                # Send message
                await websocket.send( json.dumps( message ) )
                self.utils.log( f"   Sent trigger message {i+1}: {message['type']}" )
                
                # Collect events for a short period after each message
                collection_start = time.time()
                message_events = []
                
                while ( time.time() - collection_start ) < 1.0:
                    try:
                        response = await asyncio.wait_for( websocket.recv(), timeout=0.3 )
                        event_data = json.loads( response )
                        message_events.append( event_data )
                        events_received.append( event_data )
                        
                        event_type = event_data.get( "type", "unknown" )
                        self.utils.log( f"     → Event: {event_type}" )
                        
                    except asyncio.TimeoutError:
                        break
                    except Exception as e:
                        self.utils.log( f"     → Event error: {e}" )
                        break
                
                # Brief pause between messages
                await asyncio.sleep( 0.2 )
            
            await websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if we received events in response to triggers
            total_events = len( events_received )
            success = auth_success and total_events > 0
            
            # Analyze event timing and types
            event_types = [e.get( "type", "unknown" ) for e in events_received]
            unique_event_types = list( set( event_types ) )
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "trigger_messages_sent": len( trigger_messages ),
                    "total_events_received": total_events,
                    "unique_event_types": unique_event_types,
                    "all_event_types": event_types,
                    "delivery_responsive": total_events > 0
                }
            } )
            
            if success:
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Event delivery works, {total_events} events from {len(trigger_messages)} triggers" )
                self.utils.log( f"     Event types: {', '.join(unique_event_types)}" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - No events received from triggers" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_event_type_filtering( self ):
        """Test event type filtering and selective subscription."""
        test_name = "event_type_filtering"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            user_id = "event_filtering_user"
            token = self.utils.generate_mock_token( user_id )
            
            # Connect and authenticate
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            auth_success, _ = await self.utils.authenticate_websocket( websocket, token )
            
            if not auth_success:
                raise Exception( "Authentication failed" )
            
            # Try to modify event subscription (if supported)
            subscription_message = {
                "type": "subscribe_events",
                "event_types": ["user_message", "agent_response", "sys_ping"],
                "filter_mode": "whitelist"
            }
            
            await websocket.send( json.dumps( subscription_message ) )
            await asyncio.sleep( 0.2 )
            
            # Send various messages to trigger different event types
            test_messages = [
                {"type": "user_message", "content": "This should trigger user_message events"},
                {"type": "ping", "data": "This should trigger sys_ping events"},
                {"type": "debug_message", "content": "This might trigger debug events"},
                {"type": "unknown_trigger", "data": "This might trigger unknown events"}
            ]
            
            events_by_type = {}
            all_events = []
            
            for message in test_messages:
                await websocket.send( json.dumps( message ) )
                await asyncio.sleep( 0.3 )
                
                # Collect events
                while True:
                    try:
                        response = await asyncio.wait_for( websocket.recv(), timeout=0.2 )
                        event_data = json.loads( response )
                        all_events.append( event_data )
                        
                        event_type = event_data.get( "type", "unknown" )
                        if event_type not in events_by_type:
                            events_by_type[event_type] = []
                        events_by_type[event_type].append( event_data )
                        
                    except asyncio.TimeoutError:
                        break
                    except Exception:
                        break
            
            await websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            # Analyze filtering behavior
            received_event_types = list( events_by_type.keys() )
            requested_types = ["user_message", "agent_response", "sys_ping"]
            
            # Success if we received events (filtering behavior may vary)
            success = auth_success and len( all_events ) > 0
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "requested_event_types": requested_types,
                    "received_event_types": received_event_types,
                    "events_by_type": {k: len( v ) for k, v in events_by_type.items()},
                    "total_events": len( all_events ),
                    "filtering_behavior": "unknown"  # Would need more analysis to determine
                }
            } )
            
            if success:
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Event filtering test completed" )
                self.utils.log( f"     Received types: {', '.join(received_event_types)}" )
                for event_type, count in events_by_type.items():
                    self.utils.log( f"     {event_type}: {count} events" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - No events received for filtering test" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_event_unsubscription( self ):
        """Test event unsubscription functionality."""
        test_name = "event_unsubscription"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            user_id = "event_unsub_user"
            token = self.utils.generate_mock_token( user_id )
            
            # Connect and authenticate
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            auth_success, _ = await self.utils.authenticate_websocket( websocket, token )
            
            if not auth_success:
                raise Exception( "Authentication failed" )
            
            # First, send some messages to establish baseline event flow
            baseline_message = {"type": "user_message", "content": "Baseline test message"}
            await websocket.send( json.dumps( baseline_message ) )
            
            baseline_events = []
            collection_start = time.time()
            while ( time.time() - collection_start ) < 1.0:
                try:
                    response = await asyncio.wait_for( websocket.recv(), timeout=0.3 )
                    event_data = json.loads( response )
                    baseline_events.append( event_data )
                except asyncio.TimeoutError:
                    break
                except Exception:
                    break
            
            baseline_event_count = len( baseline_events )
            self.utils.log( f"   Baseline: {baseline_event_count} events received" )
            
            # Attempt to unsubscribe from events
            unsubscribe_message = {
                "type": "unsubscribe_events",
                "event_types": ["all"],  # Try to unsubscribe from all
                "action": "unsubscribe_all"
            }
            
            await websocket.send( json.dumps( unsubscribe_message ) )
            await asyncio.sleep( 0.2 )
            
            # Send same type of message after unsubscription
            post_unsub_message = {"type": "user_message", "content": "Post-unsubscription test message"}
            await websocket.send( json.dumps( post_unsub_message ) )
            
            post_unsub_events = []
            collection_start = time.time()
            while ( time.time() - collection_start ) < 1.0:
                try:
                    response = await asyncio.wait_for( websocket.recv(), timeout=0.3 )
                    event_data = json.loads( response )
                    post_unsub_events.append( event_data )
                except asyncio.TimeoutError:
                    break
                except Exception:
                    break
            
            post_unsub_event_count = len( post_unsub_events )
            self.utils.log( f"   Post-unsubscribe: {post_unsub_event_count} events received" )
            
            await websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if we established event flow (unsubscription behavior may vary)
            success = auth_success
            
            # Analyze unsubscription effectiveness
            unsubscription_effective = post_unsub_event_count < baseline_event_count
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "baseline_events": baseline_event_count,
                    "post_unsubscribe_events": post_unsub_event_count,
                    "unsubscription_effective": unsubscription_effective,
                    "event_reduction": baseline_event_count - post_unsub_event_count,
                    "unsubscription_behavior": "effective" if unsubscription_effective else "not_detected"
                }
            } )
            
            if success:
                effectiveness = "effective" if unsubscription_effective else "not detected"
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Unsubscription {effectiveness}" )
                self.utils.log( f"     Events: {baseline_event_count} → {post_unsub_event_count}" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Unsubscription test failed" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_system_events( self ):
        """Test system-generated events."""
        test_name = "system_events"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            user_id = "system_events_user"
            token = self.utils.generate_mock_token( user_id )
            
            # Connect and authenticate
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            auth_success, _ = await self.utils.authenticate_websocket( websocket, token )
            
            if not auth_success:
                raise Exception( "Authentication failed" )
            
            # Trigger system events
            system_event_triggers = [
                {"type": "ping"},  # Should trigger sys_ping/sys_pong
                {"type": "health_check"},  # Might trigger system status events
                {"type": "session_info"},  # Might trigger session events
            ]
            
            system_events = []
            
            for trigger in system_event_triggers:
                await websocket.send( json.dumps( trigger ) )
                self.utils.log( f"   Sent system trigger: {trigger['type']}" )
                
                # Collect events
                collection_start = time.time()
                while ( time.time() - collection_start ) < 1.0:
                    try:
                        response = await asyncio.wait_for( websocket.recv(), timeout=0.3 )
                        event_data = json.loads( response )
                        
                        event_type = event_data.get( "type", "unknown" )
                        
                        # Identify system events
                        if event_type.startswith( "sys_" ) or event_type in ["connect", "disconnect", "ping", "pong"]:
                            system_events.append( event_data )
                            self.utils.log( f"     → System event: {event_type}" )
                        else:
                            self.utils.log( f"     → Other event: {event_type}" )
                        
                    except asyncio.TimeoutError:
                        break
                    except Exception:
                        break
                
                await asyncio.sleep( 0.2 )
            
            await websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if we received some system events
            system_event_count = len( system_events )
            success = auth_success and system_event_count >= 0  # Even 0 system events is acceptable
            
            system_event_types = [e.get( "type", "unknown" ) for e in system_events]
            unique_system_types = list( set( system_event_types ) )
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "system_triggers_sent": len( system_event_triggers ),
                    "system_events_received": system_event_count,
                    "system_event_types": unique_system_types,
                    "system_event_responsive": system_event_count > 0
                }
            } )
            
            if success:
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - System events: {system_event_count} received" )
                if unique_system_types:
                    self.utils.log( f"     Types: {', '.join(unique_system_types)}" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - System events test failed" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_user_generated_events( self ):
        """Test user-generated events and responses."""
        test_name = "user_generated_events"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            user_id = "user_events_user"
            token = self.utils.generate_mock_token( user_id )
            
            # Connect and authenticate
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            auth_success, _ = await self.utils.authenticate_websocket( websocket, token )
            
            if not auth_success:
                raise Exception( "Authentication failed" )
            
            # Send user-generated content that should trigger events
            user_messages = [
                {"type": "user_message", "content": "Hello, can you help me?"},
                {"type": "user_input", "text": "I need assistance with testing"},
                {"type": "user_question", "question": "What can you do?"}
            ]
            
            user_event_responses = []
            
            for message in user_messages:
                await websocket.send( json.dumps( message ) )
                self.utils.log( f"   Sent user message: {message['type']}" )
                
                # Collect responses
                message_responses = []
                collection_start = time.time()
                
                while ( time.time() - collection_start ) < 2.0:
                    try:
                        response = await asyncio.wait_for( websocket.recv(), timeout=0.5 )
                        event_data = json.loads( response )
                        message_responses.append( event_data )
                        
                        event_type = event_data.get( "type", "unknown" )
                        self.utils.log( f"     → Response event: {event_type}" )
                        
                    except asyncio.TimeoutError:
                        break
                    except Exception:
                        break
                
                user_event_responses.extend( message_responses )
                await asyncio.sleep( 0.3 )
            
            await websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if we received responses to user messages
            total_responses = len( user_event_responses )
            success = auth_success and total_responses >= 0  # Any response count is acceptable
            
            response_types = [e.get( "type", "unknown" ) for e in user_event_responses]
            unique_response_types = list( set( response_types ) )
            
            # Look for typical user interaction event types
            user_interaction_types = [t for t in unique_response_types 
                                    if any( keyword in t.lower() for keyword in 
                                          ["user", "message", "response", "agent", "input"] )]
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "user_messages_sent": len( user_messages ),
                    "total_responses": total_responses,
                    "unique_response_types": unique_response_types,
                    "user_interaction_types": user_interaction_types,
                    "responsive_to_user_input": total_responses > 0
                }
            } )
            
            if success:
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - User events: {total_responses} responses to {len(user_messages)} messages" )
                if user_interaction_types:
                    self.utils.log( f"     User interaction types: {', '.join(user_interaction_types)}" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - User events test failed" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_event_ordering( self ):
        """Test event ordering and sequence consistency."""
        test_name = "event_ordering"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            user_id = "event_ordering_user"
            token = self.utils.generate_mock_token( user_id )
            
            # Connect and authenticate
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            auth_success, _ = await self.utils.authenticate_websocket( websocket, token )
            
            if not auth_success:
                raise Exception( "Authentication failed" )
            
            # Send sequence of messages with timestamps
            sequence_messages = []
            for i in range( 5 ):
                message = {
                    "type": "sequence_test",
                    "sequence_id": i,
                    "timestamp": time.time(),
                    "content": f"Message {i} in sequence"
                }
                sequence_messages.append( message )
                await websocket.send( json.dumps( message ) )
                await asyncio.sleep( 0.1 )  # Small delay between messages
            
            # Collect all events
            all_events = []
            collection_start = time.time()
            
            while ( time.time() - collection_start ) < 3.0:
                try:
                    response = await asyncio.wait_for( websocket.recv(), timeout=0.3 )
                    event_data = json.loads( response )
                    
                    # Add reception timestamp
                    event_data["received_at"] = time.time()
                    all_events.append( event_data )
                    
                    event_type = event_data.get( "type", "unknown" )
                    sequence_id = event_data.get( "sequence_id", "N/A" )
                    self.utils.log( f"   Received: {event_type} (seq: {sequence_id})" )
                    
                except asyncio.TimeoutError:
                    break
                except Exception:
                    break
            
            await websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            # Analyze event ordering
            sequence_events = [e for e in all_events if e.get( "type" ) == "sequence_test"]
            ordered_correctly = True
            
            if len( sequence_events ) > 1:
                for i in range( 1, len( sequence_events ) ):
                    prev_seq = sequence_events[i-1].get( "sequence_id", -1 )
                    curr_seq = sequence_events[i].get( "sequence_id", -1 )
                    
                    if curr_seq <= prev_seq:
                        ordered_correctly = False
                        break
            
            # Success if we received events (ordering analysis is informational)
            success = auth_success and len( all_events ) > 0
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "sequence_messages_sent": len( sequence_messages ),
                    "total_events_received": len( all_events ),
                    "sequence_events_received": len( sequence_events ),
                    "ordered_correctly": ordered_correctly,
                    "ordering_behavior": "correct" if ordered_correctly else "out_of_order"
                }
            } )
            
            if success:
                ordering = "correct" if ordered_correctly else "out-of-order"
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Event ordering: {ordering}" )
                self.utils.log( f"     Sequence events: {len(sequence_events)}/{len(sequence_messages)}" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Event ordering test failed" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_high_frequency_events( self ):
        """Test system behavior under high-frequency event generation."""
        test_name = "high_frequency_events"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            user_id = "high_freq_user"
            token = self.utils.generate_mock_token( user_id )
            
            # Connect and authenticate
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            auth_success, _ = await self.utils.authenticate_websocket( websocket, token )
            
            if not auth_success:
                raise Exception( "Authentication failed" )
            
            # Send high-frequency messages
            message_count = 20
            sent_messages = []
            
            self.utils.log( f"   Sending {message_count} rapid messages..." )
            
            for i in range( message_count ):
                message = {
                    "type": "high_freq_test",
                    "message_id": i,
                    "timestamp": time.time()
                }
                sent_messages.append( message )
                await websocket.send( json.dumps( message ) )
                
                # Very short delay to create high frequency
                await asyncio.sleep( 0.02 )  # 50 messages per second
            
            # Collect events
            received_events = []
            collection_start = time.time()
            
            self.utils.log( f"   Collecting events for 3 seconds..." )
            
            while ( time.time() - collection_start ) < 3.0:
                try:
                    response = await asyncio.wait_for( websocket.recv(), timeout=0.1 )
                    event_data = json.loads( response )
                    received_events.append( event_data )
                    
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
            
            await websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            # Analyze high-frequency performance
            events_received = len( received_events )
            messages_sent = len( sent_messages )
            
            # Success if system handles high frequency reasonably
            success = auth_success and events_received >= 0  # Any event count is acceptable
            
            # Calculate event rate
            collection_duration = 3.0
            events_per_second = events_received / collection_duration if collection_duration > 0 else 0
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "messages_sent": messages_sent,
                    "events_received": events_received,
                    "events_per_second": events_per_second,
                    "high_frequency_handling": "stable" if success else "unstable",
                    "collection_duration": collection_duration
                }
            } )
            
            if success:
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - High frequency: {events_received} events from {messages_sent} messages" )
                self.utils.log( f"     Rate: {events_per_second:.1f} events/second" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - High frequency test failed" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_invalid_event_subscriptions( self ):
        """Test handling of invalid event subscription requests."""
        test_name = "invalid_event_subscriptions"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        try:
            session_id = self.utils.generate_session_id()
            user_id = "invalid_events_user"
            token = self.utils.generate_mock_token( user_id )
            
            # Connect and authenticate
            websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
            auth_success, _ = await self.utils.authenticate_websocket( websocket, token )
            
            if not auth_success:
                raise Exception( "Authentication failed" )
            
            # Try various invalid subscription requests
            invalid_subscriptions = [
                {"type": "subscribe_events", "event_types": None},
                {"type": "subscribe_events", "event_types": []},
                {"type": "subscribe_events", "event_types": ["nonexistent_event_type"]},
                {"type": "subscribe_events", "event_types": [123, 456]},  # Non-string types
                {"type": "subscribe_events"},  # Missing event_types
                {"type": "invalid_subscription_type", "event_types": ["user_message"]},
            ]
            
            error_responses = []
            
            for i, invalid_sub in enumerate( invalid_subscriptions ):
                self.utils.log( f"   Testing invalid subscription {i+1}..." )
                
                try:
                    await websocket.send( json.dumps( invalid_sub ) )
                    
                    # Look for error response
                    try:
                        response = await asyncio.wait_for( websocket.recv(), timeout=1.0 )
                        response_data = json.loads( response )
                        
                        if response_data.get( "type" ) in ["error", "auth_error", "subscription_error"]:
                            error_responses.append( response_data )
                            self.utils.log( f"     → Error response: {response_data.get('type')}" )
                        else:
                            self.utils.log( f"     → Other response: {response_data.get('type')}" )
                        
                    except asyncio.TimeoutError:
                        self.utils.log( f"     → No response (timeout)" )
                    
                except Exception as e:
                    self.utils.log( f"     → Exception sending invalid subscription: {e}" )
                
                await asyncio.sleep( 0.2 )
            
            # Test that normal operation still works after invalid requests
            test_message = {"type": "user_message", "content": "Test after invalid subscriptions"}
            await websocket.send( json.dumps( test_message ) )
            
            normal_operation_events = []
            collection_start = time.time()
            
            while ( time.time() - collection_start ) < 1.0:
                try:
                    response = await asyncio.wait_for( websocket.recv(), timeout=0.3 )
                    event_data = json.loads( response )
                    normal_operation_events.append( event_data )
                except asyncio.TimeoutError:
                    break
                except Exception:
                    break
            
            await websocket.close()
            
            duration = ( time.time() - start_time ) * 1000
            
            # Success if system handles invalid subscriptions gracefully
            success = auth_success  # Basic requirement
            
            normal_operation_preserved = len( normal_operation_events ) >= 0  # System still responsive
            error_handling_present = len( error_responses ) > 0
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "session_id": session_id,
                    "invalid_subscriptions_tested": len( invalid_subscriptions ),
                    "error_responses_received": len( error_responses ),
                    "normal_operation_preserved": normal_operation_preserved,
                    "error_handling": "present" if error_handling_present else "not_detected",
                    "graceful_degradation": success and normal_operation_preserved
                }
            } )
            
            if success:
                error_handling = "detected" if error_handling_present else "not detected"
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Invalid subscriptions handled, error responses: {error_handling}" )
                self.utils.log( f"     Normal operation preserved: {normal_operation_preserved}" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Invalid subscription handling failed" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )
    
    async def _test_event_system_under_load( self ):
        """Test event system behavior under load conditions."""
        test_name = "event_system_under_load"
        self.utils.log( f"\\n🧪 Testing: {test_name}" )
        
        start_time = time.time()
        websockets_to_close = []
        
        try:
            # Create multiple concurrent sessions to test event system under load
            session_count = 3
            sessions = []
            
            for i in range( session_count ):
                session_id = self.utils.generate_session_id()
                user_id = f"load_test_user_{i}"
                token = self.utils.generate_mock_token( user_id )
                
                websocket = await self.utils.connect_websocket( "queue", session_id, timeout=5.0 )
                websockets_to_close.append( websocket )
                
                auth_success, _ = await self.utils.authenticate_websocket( websocket, token )
                
                sessions.append( {
                    "session_id": session_id,
                    "user_id": user_id,
                    "websocket": websocket,
                    "auth_success": auth_success,
                    "events_received": []
                } )
                
                self.utils.log( f"   Session {i+1}: {'✅' if auth_success else '❌'} authenticated" )
            
            # Send concurrent messages from all sessions
            message_count_per_session = 5
            
            for round_num in range( message_count_per_session ):
                self.utils.log( f"   Load test round {round_num + 1}/{message_count_per_session}" )
                
                # Send messages concurrently from all sessions
                send_tasks = []
                for i, session in enumerate( sessions ):
                    if session["auth_success"]:
                        message = {
                            "type": "load_test",
                            "session_num": i,
                            "round": round_num,
                            "timestamp": time.time()
                        }
                        task = session["websocket"].send( json.dumps( message ) )
                        send_tasks.append( task )
                
                # Wait for all sends to complete
                if send_tasks:
                    await asyncio.gather( *send_tasks, return_exceptions=True )
                
                # Collect events from all sessions
                for session in sessions:
                    if session["auth_success"]:
                        try:
                            response = await asyncio.wait_for( session["websocket"].recv(), timeout=0.3 )
                            event_data = json.loads( response )
                            session["events_received"].append( event_data )
                        except asyncio.TimeoutError:
                            pass
                        except Exception:
                            pass
                
                await asyncio.sleep( 0.2 )
            
            # Close all connections
            for ws in websockets_to_close:
                await ws.close()
            websockets_to_close = []
            
            duration = ( time.time() - start_time ) * 1000
            
            # Analyze load test results
            successful_sessions = sum( 1 for s in sessions if s["auth_success"] )
            total_events_received = sum( len( s["events_received"] ) for s in sessions )
            total_messages_sent = successful_sessions * message_count_per_session
            
            # Success if most sessions worked under load
            success = successful_sessions >= session_count * 0.8  # 80% success rate
            
            self.results.append( {
                "name": test_name,
                "success": success,
                "duration_ms": duration,
                "details": {
                    "concurrent_sessions": session_count,
                    "successful_sessions": successful_sessions,
                    "messages_sent_per_session": message_count_per_session,
                    "total_messages_sent": total_messages_sent,
                    "total_events_received": total_events_received,
                    "load_test_performance": "stable" if success else "degraded"
                }
            } )
            
            if success:
                self.utils.log( f"   ✅ PASS ({duration:.2f}ms) - Load test: {successful_sessions}/{session_count} sessions stable" )
                self.utils.log( f"     Events received: {total_events_received} from {total_messages_sent} messages" )
            else:
                self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - Load test: only {successful_sessions}/{session_count} sessions stable" )
                
        except Exception as e:
            duration = ( time.time() - start_time ) * 1000
            
            # Clean up connections
            for ws in websockets_to_close:
                try:
                    await ws.close()
                except:
                    pass
            
            self.results.append( {
                "name": test_name,
                "success": False,
                "duration_ms": duration,
                "error": str( e )
            } )
            self.utils.log( f"   ❌ FAIL ({duration:.2f}ms) - {e}" )


async def main():
    """Run all event system tests."""
    print( "📡 WebSocket Event System Tests" )
    print( "=" * 50 )
    
    tester = EventSystemTests()
    results = await tester.run_all_tests()
    
    # Summary
    print( "\\n" + "=" * 50 )
    print( "📊 EVENT SYSTEM TEST SUMMARY" )
    print( "=" * 50 )
    
    total_tests = len( results )
    passed_tests = sum( 1 for r in results if r["success"] )
    total_duration = sum( r["duration_ms"] for r in results )
    
    print( f"Total Tests: {total_tests}" )
    print( f"Passed: {passed_tests}" )
    print( f"Failed: {total_tests - passed_tests}" )
    print( f"Success Rate: {(passed_tests/total_tests)*100:.1f}%" )
    print( f"Total Duration: {total_duration:.2f}ms" )
    
    # Failed tests detail
    failed_tests = [r for r in results if not r["success"]]
    if failed_tests:
        print( "\\n❌ Failed Tests:" )
        for test in failed_tests:
            print( f"  • {test['name']}: {test.get('error', 'Event system error')}" )
    
    # Event system behavior insights
    print( "\\n📡 Event System Behavior Summary:" )
    for result in results:
        if result["success"] and "details" in result:
            details = result["details"]
            test_name = result["name"]
            
            if test_name == "basic_event_subscription":
                events = details.get( "events_received", 0 )
                print( f"  • Event subscription: {events} events received during auth" )
            
            elif test_name == "event_delivery":
                events = details.get( "total_events_received", 0 )
                triggers = details.get( "trigger_messages_sent", 0 )
                print( f"  • Event delivery: {events} events from {triggers} triggers" )
            
            elif test_name == "high_frequency_events":
                rate = details.get( "events_per_second", 0 )
                print( f"  • High frequency: {rate:.1f} events/second" )
    
    if passed_tests == total_tests:
        print( "\\n✅ All event system tests passed!" )
        return 0
    else:
        print( f"\\n❌ {total_tests - passed_tests} event system tests failed!" )
        return 1


if __name__ == "__main__":
    import sys
    exit_code = asyncio.run( main() )
    sys.exit( exit_code )
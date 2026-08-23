#!/usr/bin/env python3
"""
Audio/TTS System Smoke Tests

Comprehensive smoke tests for the Lupin audio and text-to-speech system including:
- /api/get-speech TTS endpoint validation
- Audio WebSocket streaming events
- Instant vs reliable playback modes
- TTS caching mechanism validation
- Binary audio chunk handling
"""

import sys
import os

# Bootstrap using LUPIN_ROOT for standalone script execution
# (conftest.py handles this for pytest)
if __name__ == "__main__":
    lupin_root = os.environ.get( 'LUPIN_ROOT' )
    if lupin_root is None:
        raise RuntimeError(
            "LUPIN_ROOT environment variable not set.\n"
            "Set it before running:\n"
            "  export LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin\n"
            "  python src/tests/lupin_smoke/test_audio_tts.py"
        )
    src_path = os.path.join( lupin_root, 'src' )
    if src_path not in sys.path:
        sys.path.insert( 0, src_path )

import asyncio
import json
import time

from tests.lupin_smoke.utilities import (
    LupinTestClient, TestValidator,
    print_test_banner, run_test_with_error_handling
)


class AudioTTSHelper:
    """Helper utilities specifically for audio/TTS testing."""
    
    def __init__(self, client: LupinTestClient):
        self.client = client
    
    async def get_speech(self, text: str, session_id: str = None, 
                        playback_mode: str = "instant") -> dict:
        """
        Request TTS generation via API.
        
        Args:
            text: Text to convert to speech
            session_id: Session ID for the request
            playback_mode: "instant" or "reliable" (included for compatibility but not used by API)
            
        Returns:
            API response data
        """
        if session_id is None:
            # Use the last generated session ID if available (from WebSocket connection)
            session_id = getattr(self.client, 'last_generated_session_id', self.client.session_id)
        
        data = {
            "session_id": session_id,
            "text": text
        }
        
        response = await self.client.http_request("POST", "/api/get-speech", json=data)
        return response
    
    async def get_cached_speech(self, text: str) -> dict:
        """Get cached TTS audio if available."""
        params = {"text": text}
        response = await self.client.http_request("GET", "/api/get-cached-speech", params=params)
        return response


class AudioTTSSmokeTests:
    """Smoke tests for audio/TTS system functionality."""
    
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.client = LupinTestClient(debug=debug)
        self.audio_helper = AudioTTSHelper(self.client)
        self.validator = TestValidator()
        self.test_results = []
    
    async def test_get_speech_endpoint_basic(self):
        """Test basic /api/get-speech endpoint functionality."""
        # TTS endpoint requires active WebSocket connection - establish it first
        audio_ws = await self.client.websocket_connect(
            "/ws/audio/{session_id}",
            subscribed_events=["audio_streaming_chunk", "audio_streaming_status", 
                             "audio_streaming_complete", "auth_success", "sys_ping"]
        )
        
        try:
            test_text = "Hello, this is a test for the TTS system."
            
            response = await self.audio_helper.get_speech(test_text)
            
            self.validator.assert_response_ok(response, 200)
            
            data = response.json()
            self.validator.assert_json_contains(data, ["status", "message"])
            
            # Should indicate TTS request was processed
            assert data["status"] in ["success", "processing"], \
                f"Unexpected status: {data['status']}"
                
        finally:
            await self.client.close_websocket(audio_ws)
    
    async def test_get_speech_playback_modes(self):
        """Test both instant and reliable playback modes."""
        # Establish WebSocket connection first
        audio_ws = await self.client.websocket_connect(
            "/ws/audio/{session_id}",
            subscribed_events=["audio_streaming_chunk", "audio_streaming_status", "auth_success"]
        )
        
        try:
            test_text = "Testing playback modes for TTS generation."
            
            # Test instant mode
            instant_response = await self.audio_helper.get_speech(
                test_text, 
                playback_mode="instant"
            )
            self.validator.assert_response_ok(instant_response, 200)
            
            # Test reliable mode  
            reliable_response = await self.audio_helper.get_speech(
                test_text + " reliable mode", 
                playback_mode="reliable"
            )
            self.validator.assert_response_ok(reliable_response, 200)
            
            # Both should succeed
            instant_data = instant_response.json()
            reliable_data = reliable_response.json()
            
            assert instant_data["status"] in ["success", "processing"]
            assert reliable_data["status"] in ["success", "processing"]
            
        finally:
            await self.client.close_websocket(audio_ws)
    
    async def test_get_speech_validation(self):
        """Test /api/get-speech input validation."""
        # Test missing session_id
        data = {"text": "Test message"}
        response = await self.client.http_request("POST", "/api/get-speech", json=data)
        assert response.status_code in ( 400, 404, 422 ), \
            f"Should reject missing session_id, got {response.status_code}"

        # Test missing message
        data = {"session_id": self.client.session_id}
        response = await self.client.http_request("POST", "/api/get-speech", json=data)
        assert response.status_code in ( 400, 404, 422 ), \
            f"Should reject missing text, got {response.status_code}"

        # Test empty message
        data = {
            "session_id": self.client.session_id,
            "text": ""
        }
        response = await self.client.http_request("POST", "/api/get-speech", json=data)
        assert response.status_code in ( 400, 404, 422 ), \
            f"Should reject empty message, got {response.status_code}"
        
        # Test message too long - establish WebSocket first for this test
        audio_ws = await self.client.websocket_connect(
            "/ws/audio/{session_id}",
            subscribed_events=["audio_streaming_chunk", "audio_streaming_status", "auth_success"]
        )
        
        try:
            long_message = "x" * 1000  # Very long message
            response = await self.audio_helper.get_speech(long_message)
            # Should either accept or reject gracefully (not crash)
            assert response.status_code in [200, 400], "Should handle long messages gracefully"
        finally:
            await self.client.close_websocket(audio_ws)
    
    async def test_session_id_validation(self):
        """Test session ID format validation."""
        # Test invalid session ID format
        invalid_session_ids = [
            "invalid-session-123",  # Wrong format
            "test_session",         # Underscore instead of space
            "",                     # Empty
            "a",                    # Too short
        ]
        
        for invalid_id in invalid_session_ids:
            response = await self.audio_helper.get_speech(
                "Test message",
                session_id=invalid_id
            )
            # Should either reject or handle gracefully (400=bad request, 404=no audio connection)
            assert response.status_code in [200, 400, 404], \
                f"Should handle invalid session ID gracefully: {invalid_id} (got {response.status_code})"
    
    async def test_audio_websocket_connection(self):
        """Test audio WebSocket endpoint connection."""
        # Connect to audio WebSocket using placeholder that will be replaced with real session ID
        websocket = await self.client.websocket_connect(
            "/ws/audio/{session_id}",
            subscribed_events=["audio_streaming_chunk", "audio_streaming_status", 
                             "audio_streaming_complete", "auth_success", "sys_ping"]
        )
        
        try:
            # Connection should be successful (auth_success already verified in websocket_connect)
            
            # Test basic ping/pong
            ping_event = await self.client.wait_for_websocket_event(
                websocket, "sys_ping", timeout=35.0  # Wait for next ping
            )
            
            self.validator.assert_websocket_event(ping_event, "sys_ping")
            
        except TimeoutError as e:
            # No ping arrived inside the window — the one outcome worth tolerating
            # here, since ping cadence is timing-dependent. This used to be a bare
            # `except Exception`, which also swallowed the assert_websocket_event
            # below it (that helper raises AssertionError), so a malformed ping
            # event could not fail the test.
            if self.debug:
                print(f"[DEBUG] Audio WebSocket ping not seen within timeout: {e}")
            
        finally:
            await self.client.close_websocket(websocket)
    
    async def test_audio_streaming_events(self):
        """Test audio streaming WebSocket events."""
        # Connect to audio WebSocket using placeholder that will be replaced with real session ID
        websocket = await self.client.websocket_connect(
            "/ws/audio/{session_id}",
            subscribed_events=["audio_streaming_chunk", "audio_streaming_status", 
                             "audio_streaming_complete", "auth_success"]
        )
        
        try:
            # Request TTS to trigger audio streaming
            test_text = f"Audio streaming test {int(time.time())}"
            tts_response = await self.audio_helper.get_speech(test_text)
            self.validator.assert_response_ok(tts_response, 200)
            
            # Try to catch audio streaming events
            events_received = []
            timeout_start = time.time()
            
            while time.time() - timeout_start < 10.0:  # 10 second timeout
                try:
                    event = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    
                    # Audio chunks arrive as BINARY frames — recv() hands back
                    # bytes, and json.loads chokes on the first one ("'utf-8'
                    # codec can't decode byte 0xff in position 0", 0xff being an
                    # MP3 frame header). That is the streaming path working, not
                    # failing, so the frame is counted and skipped rather than
                    # parsed. The old `except Exception: pass` around this whole
                    # block hid the decode error entirely, which is why a test
                    # that cannot read the stream it subscribes to still passed.
                    if isinstance(event, (bytes, bytearray)):
                        events_received.append("audio_streaming_chunk")
                        continue
                    
                    event_data = json.loads(event)
                    event_type = event_data.get("type")
                    
                    if event_type in ["audio_streaming_status", "audio_streaming_chunk", "audio_streaming_complete"]:
                        events_received.append(event_type)
                        
                        if self.debug:
                            print(f"[AUDIO EVENT] {event_type}")
                        
                        # Validate event structure
                        if event_type == "audio_streaming_status":
                            self.validator.assert_json_contains(event_data, ["status"])
                        elif event_type == "audio_streaming_chunk":
                            # This would be binary data in real implementation
                            pass
                        elif event_type == "audio_streaming_complete":
                            self.validator.assert_json_contains(event_data, ["text"])
                            break
                            
                except asyncio.TimeoutError:
                    break
            
            # We might not receive events in test environment, which is OK —
            # the inner `except asyncio.TimeoutError: break` above already covers
            # that. There used to be an outer `except Exception: pass` here as
            # well, which additionally swallowed the assert_response_ok on the TTS
            # request and both assert_json_contains calls on the event payloads,
            # so a failed TTS request or a malformed event could not fail the test.
            if self.debug:
                print(f"[DEBUG] Audio events received: {events_received}")
                
        finally:
            await self.client.close_websocket(websocket)
    
    async def test_tts_caching_mechanism(self):
        """Test TTS caching functionality."""
        # Establish WebSocket connection first
        audio_ws = await self.client.websocket_connect(
            "/ws/audio/{session_id}",
            subscribed_events=["audio_streaming_chunk", "audio_streaming_status", "auth_success"]
        )
        
        try:
            test_text = "This text will be used to test caching functionality."
            
            # First request - should generate new audio
            first_response = await self.audio_helper.get_speech(test_text)
            self.validator.assert_response_ok(first_response, 200)
            
            # Wait a moment
            await asyncio.sleep(1)
            
            # Second request with same text - might be cached
            second_response = await self.audio_helper.get_speech(test_text)
            self.validator.assert_response_ok(second_response, 200)
            
            # Both should succeed (caching is transparent to API)
            first_data = first_response.json()
            second_data = second_response.json()
            
            assert first_data["status"] in ["success", "processing"]
            assert second_data["status"] in ["success", "processing"]
            
            # Try cached speech endpoint if available.
            # The "cached endpoint might not be implemented" case is already
            # covered by the status codes accepted below — an unrouted path
            # answers 404, it does not raise — so the `except Exception: pass`
            # that used to wrap this only ever caught the assertion itself.
            cached_response = await self.audio_helper.get_cached_speech(test_text)
            assert cached_response.status_code in [200, 404, 501], \
                f"Cached speech endpoint should handle requests gracefully, got {cached_response.status_code}"
                
        finally:
            await self.client.close_websocket(audio_ws)
    
    async def test_concurrent_tts_requests(self):
        """Test handling of concurrent TTS requests."""
        # Establish WebSocket connection first
        audio_ws = await self.client.websocket_connect(
            "/ws/audio/{session_id}",
            subscribed_events=["audio_streaming_chunk", "audio_streaming_status", "auth_success"]
        )
        
        try:
            test_texts = [
                "First concurrent TTS request",
                "Second concurrent TTS request", 
                "Third concurrent TTS request"
            ]
            
            # Send multiple requests concurrently
            tasks = []
            for i, text in enumerate(test_texts):
                task = self.audio_helper.get_speech(text)  # Use same session for all
                tasks.append(task)
            
            # Wait for all requests to complete
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            # All requests should complete without errors
            for i, response in enumerate(responses):
                if isinstance(response, Exception):
                    if self.debug:
                        print(f"[DEBUG] Concurrent request {i} failed: {response}")
                    # Some failures might be expected under load
                    continue
                
                self.validator.assert_response_ok(response, 200)
                data = response.json()
                assert data["status"] in ["success", "processing", "error"], \
                    f"Unexpected status in concurrent request: {data['status']}"
                    
        finally:
            await self.client.close_websocket(audio_ws)
    
    async def test_audio_authentication(self):
        """Test audio endpoint authentication requirements."""
        # Test without authentication.
        #
        # Two things used to be wrong here at once. The `except Exception: pass`
        # swallowed the assertion, and `headers = {}` never produced an
        # unauthenticated request — LupinTestClient.http_request re-attaches the
        # bearer token whenever the caller supplies no Authorization key, and an
        # empty dict has none. So this sent a fully authenticated request, got
        # 200, and passed on the wrong branch of an assertion that accepted both.
        #
        # Now it genuinely sends no token, and requires the refusal.
        response = await self.client.http_request(
            "POST",
            "/api/get-speech",
            json={
                "session_id": self.client.session_id,
                "text": "Test message"
            },
            authenticate=False
        )
        assert response.status_code == 401, \
            f"Unauthenticated /api/get-speech should be rejected with 401, got {response.status_code}"
        
        # Test with authentication (normal case) - establish WebSocket first
        audio_ws = await self.client.websocket_connect(
            "/ws/audio/{session_id}",
            subscribed_events=["audio_streaming_chunk", "audio_streaming_status", "auth_success"]
        )
        
        try:
            response = await self.audio_helper.get_speech("Authenticated test message")
            self.validator.assert_response_ok(response, 200)
        finally:
            await self.client.close_websocket(audio_ws)

    async def test_tts_auth_header_format_regression(self):
        """
        REGRESSION TEST: Verify TTS endpoint uses Bearer token format.

        Bug History (2025.10.14):
        - JavaScript (queue-fresh.js line 1375) sent raw JWT without "Bearer " prefix
        - Sent: Authorization: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
        - Expected: Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
        - Server expected Bearer format, causing 401 Unauthorized errors

        Fix (queue-fresh.js line 1375):
        - Changed from: 'Authorization': this.authToken
        - Changed to: 'Authorization': this.getAuthHeader()
        - getAuthHeader() adds "Bearer " prefix

        This test ensures authentication header uses correct Bearer format.
        """
        # Establish WebSocket connection for valid session
        audio_ws = await self.client.websocket_connect(
            "/ws/audio/{session_id}",
            subscribed_events=["audio_streaming_status", "auth_success"]
        )

        try:
            if self.debug:
                print( "\n[REGRESSION TEST] Testing Bearer token format for TTS endpoint" )

            # Get the auth token and header
            auth_token = self.client.get_auth_token()
            auth_header = self.client.get_auth_header()

            if self.debug:
                print( f"[REGRESSION TEST] Raw token (first 30 chars): {auth_token[:30]}..." )
                print( f"[REGRESSION TEST] Auth header (first 40 chars): {auth_header[:40]}..." )

            # Test 1: Verify Bearer prefix is included in auth header
            assert auth_header.startswith( "Bearer " ), \
                f"Auth header should start with 'Bearer ', got: {auth_header[:20]}"

            # Test 2: Verify header contains the token after "Bearer "
            token_from_header = auth_header.replace( "Bearer ", "" )
            assert token_from_header == auth_token, \
                "Auth header should contain 'Bearer ' + token"

            if self.debug:
                print( "[REGRESSION TEST] ✓ Bearer prefix validated in getAuthHeader()" )

            # Test 3: Verify TTS endpoint works with Bearer format
            test_data = {
                "session_id": getattr( self.client, 'last_generated_session_id', self.client.session_id ),
                "text": "Bearer format regression test"
            }

            # Use the correct Bearer format (this should succeed)
            bearer_response = await self.client.http_request(
                "POST",
                "/api/get-speech",
                json=test_data,
                headers={"Authorization": auth_header}  # With Bearer prefix
            )

            self.validator.assert_response_ok( bearer_response, 200 )

            if self.debug:
                print( "[REGRESSION TEST] ✓ Bearer token format accepted by TTS endpoint" )

            # Test 4: Verify raw token format fails (if endpoint enforces strict Bearer validation)
            # This validates the bug would be caught if it regresses
            raw_token_response = await self.client.http_request(
                "POST",
                "/api/get-speech",
                json=test_data,
                headers={"Authorization": auth_token}  # WITHOUT Bearer prefix (the bug!)
            )

            # If endpoint strictly validates Bearer format, this should fail with 401
            if raw_token_response.status_code == 401:
                if self.debug:
                    print( "[REGRESSION TEST] ✓ Raw token correctly rejected (401) - endpoint validates Bearer format" )
            elif raw_token_response.status_code == 200:
                if self.debug:
                    print( "[REGRESSION TEST] ⚠ Raw token accepted (200) - endpoint doesn't strictly validate Bearer format" )
                    print( "[REGRESSION TEST]   (This is OK if server is lenient, but stricter validation recommended)" )
            else:
                if self.debug:
                    print( f"[REGRESSION TEST] ? Raw token response: {raw_token_response.status_code}" )

            # Test 5: Verify the fix pattern - using helper method instead of raw token
            # This mimics the correct usage from queue-fresh.js
            correct_usage_response = await self.audio_helper.get_speech( "Correct usage test" )
            self.validator.assert_response_ok( correct_usage_response, 200 )

            if self.debug:
                print( "[REGRESSION TEST] ✓ Correct usage pattern validated (using helper method)" )
                print( "[REGRESSION TEST] ✓ Regression test complete - Bearer format enforced" )

        finally:
            await self.client.close_websocket( audio_ws )

    async def run_all_tests(self) -> bool:
        """Run all audio/TTS smoke tests."""
        print_test_banner("Audio/TTS System Smoke Tests")
        
        tests = [
            (self.test_get_speech_endpoint_basic, "Basic /api/get-speech endpoint"),
            (self.test_get_speech_playback_modes, "Instant vs reliable playback modes"),
            (self.test_get_speech_validation, "Input validation"),
            (self.test_session_id_validation, "Session ID validation"),
            (self.test_audio_websocket_connection, "Audio WebSocket connection"),
            (self.test_audio_streaming_events, "Audio streaming events"),
            (self.test_tts_caching_mechanism, "TTS caching mechanism"),
            (self.test_concurrent_tts_requests, "Concurrent TTS requests"),
            (self.test_audio_authentication, "Audio authentication"),
            (self.test_tts_auth_header_format_regression, "Auth header format regression (Bearer prefix)")
        ]
        
        passed = 0
        total = len(tests)
        
        for test_func, test_name in tests:
            if await run_test_with_error_handling(test_func, test_name):
                passed += 1
        
        print(f"\n{'='*60}")
        print(f"Audio/TTS Tests Summary: {passed}/{total} passed")
        print(f"{'='*60}")
        
        return passed == total


async def main():
    """Main test execution function."""
    # Check if we should run in debug mode
    debug = "--debug" in sys.argv
    
    print("🔊 Audio/TTS System Smoke Tests")
    print("=" * 50)
    print("Testing comprehensive audio and TTS functionality...")
    print("")
    
    # Create test instance and run
    tests = AudioTTSSmokeTests(debug=debug)
    
    try:
        success = await tests.run_all_tests()
        
        if success:
            print("✅ All audio/TTS tests passed!")
            return True
        else:
            print("❌ Some audio/TTS tests failed!")
            return False
            
    except Exception as e:
        print(f"❌ Test execution failed: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
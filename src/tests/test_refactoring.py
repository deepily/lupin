#!/usr/bin/env python3
"""
Automated testing for FastAPI refactoring
Ensures endpoints still work after moving to routers

Usage:
    python test_refactoring.py [--baseline|--validate]
    
    --baseline: Capture current endpoint responses
    --validate: Compare against baseline after refactoring
"""

import httpx
import asyncio
import json
import sys
import os
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import argparse

class RefactoringTester:
    def __init__(self, base_url: str = "http://localhost:7999"):
        self.base_url = base_url
        self.baseline_file = "test_baseline.json"
        
        # Define all endpoints to test
        # Format: (method, path, expected_status, requires_auth, test_body)
        self.endpoints: List[Tuple[str, str, int, bool, Optional[Dict]]] = [
            # System endpoints
            ("GET", "/", 200, False, None),
            ("GET", "/health", 200, False, None),
            ("GET", "/api/init", 200, False, None),
            ("GET", "/api/get-session-id", 200, False, None),
            
            # Auth test
            ("GET", "/api/auth-test", 403, False, None),  # Without auth (FastAPI returns 403)
            ("GET", "/api/auth-test", 200, True, None),   # With auth
            
            # Queue endpoints
            ("GET", "/api/push?question=test", 200, True, None),
            ("GET", "/api/get-queue/todo", 200, True, None),
            ("GET", "/api/get-queue/run", 200, True, None),
            ("GET", "/api/get-queue/done", 200, True, None),
            ("GET", "/api/get-queue/dead", 200, True, None),
            
            # Notification endpoints
            ("POST", "/api/notify", 200, False, {
                "message": "Test notification",
                "type": "task",
                "priority": "medium",
                "target_user": "test@example.com"
            }),
            ("GET", "/api/notifications/test@example.com", 200, False, None),
            ("GET", "/api/notifications/test@example.com/next", 200, False, None),
            
            # Job endpoints
            ("GET", "/api/delete-snapshot/test-id", 200, False, None),
            ("GET", "/get-answer/test-id", 404, False, None),  # Expect 404 for non-existent
            
            # Audio endpoints (basic connectivity test)
            ("POST", "/api/get-audio", 400, False, {}),  # Expect 400 without proper body
        ]
        
    def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for protected endpoints"""
        return {
            "Authorization": "Bearer mock_token_test"
        }
    
    async def test_endpoint(
        self, 
        method: str, 
        path: str, 
        expected_status: int,
        requires_auth: bool = False,
        body: Optional[Dict] = None
    ) -> Dict:
        """Test a single endpoint and return result"""
        headers = self.get_auth_headers() if requires_auth else {}
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                if method == "GET":
                    response = await client.get(
                        f"{self.base_url}{path}",
                        headers=headers
                    )
                elif method == "POST":
                    response = await client.post(
                        f"{self.base_url}{path}",
                        headers=headers,
                        json=body
                    )
                elif method == "DELETE":
                    response = await client.delete(
                        f"{self.base_url}{path}",
                        headers=headers
                    )
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                return {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": response.text if response.text else None,
                    "success": response.status_code == expected_status
                }
                
            except Exception as e:
                return {
                    "status_code": None,
                    "error": str(e),
                    "success": False
                }
    
    async def capture_baseline(self) -> Dict:
        """Capture baseline responses for all endpoints"""
        print("📸 Capturing baseline endpoint responses...")
        baseline = {
            "timestamp": datetime.now().isoformat(),
            "endpoints": {}
        }
        
        for method, path, expected_status, requires_auth, body in self.endpoints:
            print(f"Testing {method} {path}...", end=" ")
            result = await self.test_endpoint(method, path, expected_status, requires_auth, body)
            
            endpoint_key = f"{method} {path}"
            baseline["endpoints"][endpoint_key] = result
            
            if result["success"]:
                print("✅")
            else:
                print(f"❌ (expected {expected_status}, got {result.get('status_code', 'error')})")
        
        # Save baseline
        with open(self.baseline_file, "w") as f:
            json.dump(baseline, f, indent=2)
        
        print(f"\n✅ Baseline saved to {self.baseline_file}")
        return baseline
    
    async def validate_against_baseline(self) -> bool:
        """Validate current responses against baseline"""
        if not os.path.exists(self.baseline_file):
            print("❌ No baseline file found. Run with --baseline first.")
            return False
        
        with open(self.baseline_file, "r") as f:
            baseline = json.load(f)
        
        print(f"🔍 Validating against baseline from {baseline['timestamp']}...")
        
        all_passed = True
        results = []
        
        for method, path, expected_status, requires_auth, body in self.endpoints:
            endpoint_key = f"{method} {path}"
            print(f"Testing {endpoint_key}...", end=" ")
            
            current_result = await self.test_endpoint(method, path, expected_status, requires_auth, body)
            baseline_result = baseline["endpoints"].get(endpoint_key, {})
            
            # Compare results
            if current_result["success"] and baseline_result.get("success"):
                # Both successful - compare status codes
                if current_result["status_code"] == baseline_result["status_code"]:
                    print("✅")
                    results.append(f"✅ {endpoint_key}")
                else:
                    print(f"❌ (status changed: {baseline_result['status_code']} → {current_result['status_code']})")
                    results.append(f"❌ {endpoint_key}: Status changed")
                    all_passed = False
            elif not current_result["success"] and not baseline_result.get("success"):
                # Both failed with same error - that's ok
                print("✅ (both failed as expected)")
                results.append(f"✅ {endpoint_key} (expected failure)")
            else:
                # One succeeded, one failed - that's bad
                print("❌ (success state changed)")
                results.append(f"❌ {endpoint_key}: Success state changed")
                all_passed = False
        
        print("\n" + "="*50)
        print("VALIDATION SUMMARY")
        print("="*50)
        for result in results:
            print(result)
        print("="*50)
        
        if all_passed:
            print("✅ All endpoints validated successfully!")
        else:
            print("❌ Some endpoints failed validation!")
        
        return all_passed
    
    async def run_quick_test(self) -> bool:
        """Run a quick connectivity test"""
        print("🚀 Running quick connectivity test...")
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/health")
                if response.status_code == 200:
                    print("✅ Server is running and responsive")
                    return True
                else:
                    print(f"❌ Server returned status {response.status_code}")
                    return False
        except Exception as e:
            print(f"❌ Could not connect to server: {e}")
            return False

async def main():
    parser = argparse.ArgumentParser(description="Test FastAPI refactoring")
    parser.add_argument("--baseline", action="store_true", help="Capture baseline responses")
    parser.add_argument("--validate", action="store_true", help="Validate against baseline")
    parser.add_argument("--quick", action="store_true", help="Quick connectivity test")
    parser.add_argument("--url", default="http://localhost:7999", help="Base URL for testing")
    
    args = parser.parse_args()
    
    tester = RefactoringTester(args.url)
    
    # First, always do a quick connectivity test
    if not await tester.run_quick_test():
        print("\n⚠️  Make sure the FastAPI server is running!")
        print("Run: cd src && python -m uvicorn fastapi_app.main:app --port 7999")
        sys.exit(1)
    
    if args.baseline:
        await tester.capture_baseline()
    elif args.validate:
        success = await tester.validate_against_baseline()
        sys.exit(0 if success else 1)
    elif args.quick:
        # Already done above
        pass
    else:
        # Default: run validation if baseline exists, otherwise capture baseline
        if os.path.exists(tester.baseline_file):
            success = await tester.validate_against_baseline()
            sys.exit(0 if success else 1)
        else:
            await tester.capture_baseline()

if __name__ == "__main__":
    asyncio.run(main())
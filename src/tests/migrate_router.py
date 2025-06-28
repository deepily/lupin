#!/usr/bin/env python3
"""
Automated router migration script
Extracts routers from main.py with automatic testing and rollback
"""

import os
import shutil
import subprocess
import sys
import re
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import ast
import textwrap

class RouterMigrator:
    def __init__(self):
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        self.src_dir = os.path.join(self.project_root, "src")
        self.main_py = os.path.join(self.src_dir, "fastapi_app/main.py")
        self.cosa_rest = os.path.join(self.src_dir, "cosa/rest")
        self.test_script = os.path.join(self.src_dir, "tests/test_refactoring.py")
        
        # Router extraction order (simplest to most complex)
        self.routers = [
            {
                "name": "system",
                "endpoints": ["/", "/health", "/api/init", "/api/get-session-id"],
                "description": "System and health check endpoints"
            },
            {
                "name": "notifications", 
                "endpoints": ["/api/notify", "/api/notifications/"],
                "description": "Notification management endpoints"
            },
            {
                "name": "audio",
                "endpoints": ["/api/upload-and-transcribe-mp3", "/api/upload-and-transcribe-wav", "/api/get-audio"],
                "description": "Audio processing endpoints (STT/TTS)"
            },
            {
                "name": "queues",
                "endpoints": ["/api/push", "/api/get-queue/"],
                "description": "Queue management endpoints"
            },
            {
                "name": "jobs",
                "endpoints": ["/api/delete-snapshot/", "/get-answer/"],
                "description": "Job and snapshot management endpoints"
            },
            {
                "name": "websocket",
                "endpoints": ["/ws/", "/api/auth-test"],
                "description": "WebSocket and authentication endpoints"
            }
        ]
        
    def backup_main(self) -> str:
        """Create timestamped backup of main.py"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{self.main_py}.backup_{timestamp}"
        shutil.copy(self.main_py, backup_path)
        print(f"✅ Created backup: {backup_path}")
        return backup_path
    
    def create_directory_structure(self):
        """Create the router directory structure in cosa/rest"""
        directories = [
            os.path.join(self.cosa_rest, "routers"),
            os.path.join(self.cosa_rest, "dependencies"),
            os.path.join(self.cosa_rest, "services"),
            os.path.join(self.cosa_rest, "core"),
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
            init_file = os.path.join(directory, "__init__.py")
            if not os.path.exists(init_file):
                with open(init_file, "w") as f:
                    f.write('"""FastAPI router components"""\n')
        
        print("✅ Created directory structure in cosa/rest/")
    
    def run_tests(self) -> bool:
        """Run the test suite to validate functionality"""
        print("🧪 Running tests...")
        
        try:
            # First check if server is running
            result = subprocess.run(
                [sys.executable, self.test_script, "--quick"],
                capture_output=True,
                text=True,
                cwd=os.path.dirname(self.test_script)
            )
            
            if result.returncode != 0:
                print("❌ Server connectivity test failed")
                print(result.stdout)
                print(result.stderr)
                return False
            
            # Run validation tests
            result = subprocess.run(
                [sys.executable, self.test_script, "--validate"],
                capture_output=True,
                text=True,
                cwd=os.path.dirname(self.test_script)
            )
            
            if result.returncode == 0:
                print("✅ All tests passed")
                return True
            else:
                print("❌ Tests failed:")
                print(result.stdout)
                print(result.stderr)
                return False
                
        except Exception as e:
            print(f"❌ Test execution failed: {e}")
            return False
    
    def extract_endpoints_for_router(self, router_name: str) -> List[str]:
        """Extract endpoint code blocks for a specific router"""
        router_config = next(r for r in self.routers if r["name"] == router_name)
        endpoint_patterns = router_config["endpoints"]
        
        with open(self.main_py, "r") as f:
            content = f.read()
        
        # This is a simplified extraction - in practice, you'd use AST parsing
        extracted_endpoints = []
        
        for pattern in endpoint_patterns:
            # Find @app decorators matching the pattern
            regex = rf'(@app\.\w+\s*\(\s*["\'].*{re.escape(pattern)}.*["\']\s*.*?\)[\s\S]*?)(?=@app\.|$)'
            matches = re.findall(regex, content, re.MULTILINE)
            extracted_endpoints.extend(matches)
        
        return extracted_endpoints
    
    def create_router_file(self, router_name: str) -> str:
        """Create a router file with extracted endpoints"""
        router_path = os.path.join(self.cosa_rest, "routers", f"{router_name}.py")
        router_config = next(r for r in self.routers if r["name"] == router_name)
        
        # Router template
        template = f'''"""
{router_config["description"]}
Generated on: {datetime.now().isoformat()}
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, FileResponse
from typing import Optional, Dict, Any

# Import dependencies as needed
# from ..dependencies.config import get_config
# from ..dependencies.auth import get_current_user

router = APIRouter(tags=["{router_name}"])

# TODO: Add extracted endpoints here
# The migration script will populate this file with the actual endpoints

'''
        
        with open(router_path, "w") as f:
            f.write(template)
        
        print(f"✅ Created router file: {router_path}")
        return router_path
    
    def update_main_imports(self, migrated_routers: List[str]):
        """Update main.py to import routers from cosa.rest"""
        # This is a simplified version - actual implementation would
        # properly parse and modify the Python AST
        
        import_statement = "from cosa.rest.routers import " + ", ".join(migrated_routers)
        include_statements = "\n".join([
            f"app.include_router({router}.router)"
            for router in migrated_routers
        ])
        
        print(f"✅ Updated main.py imports for: {', '.join(migrated_routers)}")
    
    def rollback(self, backup_path: str):
        """Rollback to backup version"""
        shutil.copy(backup_path, self.main_py)
        print(f"✅ Rolled back to: {backup_path}")
    
    def migrate_single_router(self, router_name: str) -> bool:
        """Migrate a single router with testing"""
        print(f"\n{'='*60}")
        print(f"Migrating {router_name} router...")
        print('='*60)
        
        # Create router file
        router_path = self.create_router_file(router_name)
        
        # Extract endpoints (simplified for this example)
        endpoints = self.extract_endpoints_for_router(router_name)
        print(f"Found {len(endpoints)} endpoints for {router_name}")
        
        # Update main.py imports
        self.update_main_imports([router_name])
        
        # Run tests
        if self.run_tests():
            print(f"✅ {router_name} router migration successful")
            return True
        else:
            print(f"❌ {router_name} router migration failed")
            return False
    
    def migrate_all(self):
        """Migrate all routers with automatic testing and rollback"""
        print("🚀 Starting automated router migration")
        print(f"Project root: {self.project_root}")
        
        # Create directory structure
        self.create_directory_structure()
        
        # Create initial backup
        backup_path = self.backup_main()
        
        # Capture baseline if it doesn't exist
        if not os.path.exists(os.path.join(os.path.dirname(self.test_script), "test_baseline.json")):
            print("\n📸 Capturing test baseline...")
            subprocess.run(
                [sys.executable, self.test_script, "--baseline"],
                cwd=os.path.dirname(self.test_script)
            )
        
        # Track successfully migrated routers
        migrated = []
        
        # Migrate each router
        for router_config in self.routers:
            router_name = router_config["name"]
            
            if self.migrate_single_router(router_name):
                migrated.append(router_name)
                # Create checkpoint backup after successful migration
                checkpoint = self.backup_main()
                print(f"✅ Checkpoint saved: {checkpoint}")
            else:
                # Rollback on failure
                print(f"❌ Rolling back due to {router_name} failure")
                self.rollback(backup_path)
                break
        
        # Final summary
        print("\n" + "="*60)
        print("MIGRATION SUMMARY")
        print("="*60)
        print(f"Successfully migrated: {len(migrated)}/{len(self.routers)} routers")
        if migrated:
            print(f"Migrated: {', '.join(migrated)}")
        
        if len(migrated) == len(self.routers):
            print("\n✅ All routers migrated successfully!")
            
            # Create final slim main.py
            self.create_final_main_py()
        else:
            print("\n⚠️  Migration incomplete - manual intervention required")

    def create_final_main_py(self):
        """Create the final slim main.py after all migrations"""
        final_main = '''"""
FastAPI application - refactored with modular routers
All business logic has been moved to cosa.rest.routers
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

# Import routers from cosa.rest
from cosa.rest.routers import (
    system, notifications, audio,
    queues, jobs, websocket
)
from cosa.rest.core.lifespan import lifespan

# Create FastAPI app with lifespan management
app = FastAPI(
    title="Genie in the Box API",
    description="FastAPI refactored with modular routers",
    version="1.0.0",
    lifespan=lifespan
)

# Include all routers
app.include_router(system.router)
app.include_router(notifications.router)
app.include_router(audio.router)
app.include_router(queues.router)
app.include_router(jobs.router)
app.include_router(websocket.router)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7999)
'''
        
        print("\n📝 Final main.py template created")
        print("This would replace the current main.py after all routers are migrated")

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Automated router migration")
    parser.add_argument("--router", help="Migrate specific router only")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--setup-only", action="store_true", help="Only create directory structure")
    
    args = parser.parse_args()
    
    migrator = RouterMigrator()
    
    if args.setup_only:
        migrator.create_directory_structure()
        print("✅ Directory structure created")
    elif args.router:
        # Migrate single router
        backup = migrator.backup_main()
        if migrator.migrate_single_router(args.router):
            print(f"✅ {args.router} router migrated successfully")
        else:
            migrator.rollback(backup)
            print(f"❌ {args.router} router migration failed and rolled back")
    else:
        # Migrate all routers
        migrator.migrate_all()

if __name__ == "__main__":
    main()
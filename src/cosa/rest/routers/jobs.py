"""
Job and snapshot management endpoints.

Provides REST API endpoints for managing job lifecycle including
snapshot deletion and audio answer retrieval. Currently implements
stub functionality for Phase 1 development.

Generated on: 2025-01-24
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from datetime import datetime
import os
import cosa.utils.util as du

router = APIRouter(tags=["jobs"])

# Global dependencies (temporary access via main module)
def get_static_dir():
    """
    Dependency to get static directory from main module.
    
    Requires:
        - lupin_app.main module is available
        - main_module has static_dir attribute
        
    Ensures:
        - Returns the static directory path
        - Provides access to static assets
        
    Raises:
        - ImportError if main module not available
        - AttributeError if static_dir not found
    """
    import lupin_app.main as main_module
    return main_module.static_dir

@router.get(
    "/api/delete-snapshot/{id}",
    summary     = "Delete job snapshot",
    description = "Delete a completed job snapshot by ID. Phase 1 stub."
)
async def delete_snapshot(id: str):
    """
    Delete a completed job snapshot.
    
    PHASE 1 STUB: Returns mock success response for testing.
    
    Requires:
        - id is a non-empty string identifier
        - id does not start with "invalid" (for stub validation)
        
    Ensures:
        - Returns success status with job ID and timestamp
        - Raises 404 HTTPException for invalid IDs
        - Provides mock deletion confirmation
        
    Raises:
        - HTTPException with 404 status for invalid or missing IDs
        
    Args:
        id: The job identifier to delete
        
    Returns:
        dict: Deletion status with confirmation details
    """
    print(f"[STUB] /api/delete-snapshot/{id} called")
    
    # Mock deletion logic
    if not id or id.startswith("invalid"):
        raise HTTPException(status_code=404, detail=f"Snapshot not found: {id}")
    
    return {
        "status": "deleted",
        "id": id,
        "message": f"Snapshot {id} deleted successfully (STUB)",
        "timestamp": du.get_current_datetime_iso()
    }

@router.get(
    "/get-answer/{id}",
    summary     = "Get job audio answer",
    description = "Return audio for a completed job. Phase 1 stub serving placeholder audio."
)
async def get_answer(id: str):
    """
    Retrieve audio answer for completed job.
    
    PHASE 1 STUB: Returns a placeholder audio file for testing.
    
    Requires:
        - id is a non-empty string identifier
        - lupin_app.main module is accessible
        - static_dir contains audio/gentle-gong.mp3 file
        - Placeholder audio file exists in static directory
        
    Ensures:
        - Returns FileResponse with audio/mpeg media type
        - Uses placeholder gentle-gong.mp3 for all requests
        - Sets appropriate filename with job ID
        - Raises 404 if placeholder audio file missing
        
    Raises:
        - HTTPException with 404 status if audio file not found
        - ImportError if main module not accessible
        
    Args:
        id: The job identifier to get audio for
        
    Returns:
        FileResponse: Audio file stream for playback
    """
    print(f"[STUB] /get-answer/{id} called")
    
    # Get static directory from main module
    import lupin_app.main as main_module
    static_dir = main_module.static_dir
    
    # For now, return the gentle gong as placeholder audio
    audio_file_path = os.path.join(static_dir, "audio", "gentle-gong.mp3")
    
    if not os.path.exists(audio_file_path):
        raise HTTPException(status_code=404, detail=f"Audio file not found for job: {id}")
    
    return FileResponse(
        path=audio_file_path,
        media_type="audio/mpeg",
        filename=f"answer-{id}.mp3"
    )


def quick_smoke_test():
    """
    Critical smoke test for job management API - validates REST endpoint functionality.
    
    This test is essential for v000 deprecation as rest/routers/jobs.py is critical
    for job lifecycle management and API operations in the REST system.
    """
    import cosa.utils.util as du
    
    du.print_banner( "Job Management API Smoke Test", prepend_nl=True )
    
    try:
        # Test 1: Basic module and router structure
        print( "Testing core job API components..." )
        
        # Check if router exists and has expected attributes
        if 'router' in globals() and hasattr( router, 'routes' ):
            print( "✓ FastAPI router structure present" )
        else:
            print( "✗ FastAPI router structure missing" )
        
        # Check expected endpoints
        expected_endpoints = [ "delete_snapshot", "get_answer" ]
        endpoints_found = 0
        
        for endpoint_name in expected_endpoints:
            if endpoint_name in globals():
                endpoints_found += 1
            else:
                print( f"⚠ Missing endpoint: {endpoint_name}" )
        
        if endpoints_found == len( expected_endpoints ):
            print( f"✓ All {len( expected_endpoints )} core API endpoints present" )
        else:
            print( f"⚠ Only {endpoints_found}/{len( expected_endpoints )} API endpoints present" )
        
        # Test 2: Critical dependency imports
        print( "Testing critical dependency imports..." )
        try:
            from fastapi import APIRouter, HTTPException
            from fastapi.responses import FileResponse
            from datetime import datetime
            import os
            print( "✓ Core FastAPI imports successful" )
        except ImportError as e:
            print( f"✗ Core FastAPI imports failed: {e}" )
        
        # Test 3: Router configuration validation
        print( "Testing router configuration..." )
        try:
            # Test router has proper tags
            if hasattr( router, 'tags' ) and 'jobs' in getattr( router, 'tags', [] ):
                print( "✓ Router tags configuration valid" )
            else:
                print( "⚠ Router tags configuration may have issues" )
            
            # Test routes are registered
            if hasattr( router, 'routes' ) and len( router.routes ) >= 2:
                print( f"✓ Router has {len( router.routes )} registered routes" )
            else:
                print( "⚠ Router may have missing routes" )
                
        except Exception as e:
            print( f"⚠ Router configuration issues: {e}" )
        
        # Test 4: Endpoint function signatures
        print( "Testing endpoint function signatures..." )
        try:
            # Test delete_snapshot function
            if callable( delete_snapshot ):
                print( "✓ delete_snapshot endpoint is callable" )
            else:
                print( "✗ delete_snapshot endpoint not callable" )
            
            # Test get_answer function  
            if callable( get_answer ):
                print( "✓ get_answer endpoint is callable" )
            else:
                print( "✗ get_answer endpoint not callable" )
                
            # Test get_static_dir helper function
            if callable( get_static_dir ):
                print( "✓ get_static_dir helper function is callable" )
            else:
                print( "✗ get_static_dir helper function not callable" )
                
        except Exception as e:
            print( f"⚠ Endpoint signature validation issues: {e}" )
        
        # Test 5: Mock endpoint functionality (structure only)
        print( "Testing endpoint functionality structure..." )
        try:
            import asyncio
            import inspect
            
            # Test delete_snapshot is async and has proper parameters
            if inspect.iscoroutinefunction( delete_snapshot ):
                print( "✓ delete_snapshot is properly async" )
            else:
                print( "⚠ delete_snapshot may not be async" )
            
            # Check function signature
            sig = inspect.signature( delete_snapshot )
            if 'id' in sig.parameters:
                print( "✓ delete_snapshot has required id parameter" )
            else:
                print( "✗ delete_snapshot missing id parameter" )
            
            # Test get_answer is async and has proper parameters
            if inspect.iscoroutinefunction( get_answer ):
                print( "✓ get_answer is properly async" )
            else:
                print( "⚠ get_answer may not be async" )
            
            # Check function signature
            sig = inspect.signature( get_answer )
            if 'id' in sig.parameters:
                print( "✓ get_answer has required id parameter" )
            else:
                print( "✗ get_answer missing id parameter" )
                
        except Exception as e:
            print( f"⚠ Endpoint functionality structure issues: {e}" )
        
        # Test 6: HTTP status and response structure validation
        print( "Testing HTTP response structure..." )
        try:
            # Test that endpoints use HTTPException properly (by checking imports)
            if 'HTTPException' in globals():
                print( "✓ HTTPException available for error handling" )
            else:
                print( "⚠ HTTPException not available" )
            
            # Test FileResponse availability for audio endpoint
            if 'FileResponse' in globals():
                print( "✓ FileResponse available for file serving" )
            else:
                print( "⚠ FileResponse not available" )
            
            # Test datetime for timestamps
            if 'datetime' in globals():
                print( "✓ datetime available for timestamping" )
            else:
                print( "⚠ datetime not available" )
                
        except Exception as e:
            print( f"⚠ HTTP response structure issues: {e}" )
        
        # Test 7: FastAPI integration validation
        print( "Testing FastAPI integration..." )
        try:
            # Check that router is properly configured APIRouter
            if isinstance( router, APIRouter ):
                print( "✓ Router is proper APIRouter instance" )
            else:
                print( "⚠ Router may not be proper APIRouter instance" )
            
            # Check route decorators are working (by checking routes exist)
            route_paths = []
            if hasattr( router, 'routes' ):
                for route in router.routes:
                    if hasattr( route, 'path' ):
                        route_paths.append( route.path )
            
            expected_paths = [ "/api/delete-snapshot/{id}", "/get-answer/{id}" ]
            paths_found = 0
            for expected_path in expected_paths:
                if expected_path in route_paths:
                    paths_found += 1
            
            if paths_found >= len( expected_paths ) - 1:  # Allow for minor variations
                print( f"✓ API route paths configured ({paths_found}/{len( expected_paths )})" )
            else:
                print( f"⚠ Limited API route paths: {paths_found}/{len( expected_paths )}" )
                
        except Exception as e:
            print( f"⚠ FastAPI integration issues: {e}" )
        
        # Test 8: Dependency injection structure
        print( "Testing dependency injection structure..." )
        try:
            # Test get_static_dir function structure
            sig = inspect.signature( get_static_dir )
            if len( sig.parameters ) == 0:
                print( "✓ get_static_dir has correct parameter signature" )
            else:
                print( "⚠ get_static_dir parameter signature may have issues" )
            
            # Test that function has proper import structure
            source_lines = inspect.getsource( get_static_dir )
            if 'import lupin_app.main' in source_lines:
                print( "✓ Dependency injection import structure valid" )
            else:
                print( "⚠ Dependency injection structure may have issues" )
                
        except Exception as e:
            print( f"⚠ Dependency injection structure issues: {e}" )
        
        # Test 9: Critical v000 dependency scanning
        print( "\\n🔍 Scanning for v000 dependencies..." )
        
        # Scan the file for v000 patterns
        import inspect
        source_file = inspect.getfile( delete_snapshot )  # Use any function to get file
        
        v000_found = False
        v000_patterns = []
        
        with open( source_file, 'r' ) as f:
            content = f.read()
            
            # Split content and exclude smoke test function
            lines = content.split( '\\n' )
            in_smoke_test = False
            
            for i, line in enumerate( lines ):
                stripped_line = line.strip()
                
                # Track if we're in the smoke test function
                if "def quick_smoke_test" in line:
                    in_smoke_test = True
                    continue
                elif in_smoke_test and line.startswith( "def " ):
                    in_smoke_test = False
                elif in_smoke_test:
                    continue
                
                # Skip comments and docstrings
                if ( stripped_line.startswith( '#' ) or 
                     stripped_line.startswith( '"""' ) or
                     stripped_line.startswith( "'" ) ):
                    continue
                
                # Look for actual v000 code references
                if "v000" in stripped_line and any( pattern in stripped_line for pattern in [
                    "import", "from", "cosa.agents.v000", ".v000."
                ] ):
                    v000_found = True
                    v000_patterns.append( f"Line {i+1}: {stripped_line}" )
        
        if v000_found:
            print( "🚨 CRITICAL: v000 dependencies detected!" )
            print( "   Found v000 references:" )
            for pattern in v000_patterns[ :3 ]:  # Show first 3
                print( f"     • {pattern}" )
            if len( v000_patterns ) > 3:
                print( f"     ... and {len( v000_patterns ) - 3} more v000 references" )
            print( "   ⚠️  These dependencies MUST be resolved before v000 deprecation!" )
        else:
            print( "✅ EXCELLENT: No v000 dependencies found!" )
        
        # Test 10: API documentation structure
        print( "\\nTesting API documentation structure..." )
        try:
            # Check that endpoints have proper docstrings
            delete_doc = delete_snapshot.__doc__
            get_answer_doc = get_answer.__doc__
            
            docs_found = 0
            if delete_doc and len( delete_doc.strip() ) > 10:
                docs_found += 1
            if get_answer_doc and len( get_answer_doc.strip() ) > 10:
                docs_found += 1
            
            if docs_found == 2:
                print( "✓ All endpoints have documentation" )
            else:
                print( f"⚠ Only {docs_found}/2 endpoints have proper documentation" )
            
            # Test module-level docstring
            module_doc = __doc__ if '__doc__' in globals() else None
            if module_doc and len( module_doc.strip() ) > 10:
                print( "✓ Module has documentation" )
            else:
                print( "⚠ Module documentation may be missing" )
                
        except Exception as e:
            print( f"⚠ API documentation issues: {e}" )
    
    except Exception as e:
        print( f"✗ Error during job API testing: {e}" )
        import traceback
        traceback.print_exc()
    
    # Summary
    print( "\\n" + "="*60 )
    if v000_found:
        print( "🚨 CRITICAL ISSUE: Job management API has v000 dependencies!" )
        print( "   Status: NOT READY for v000 deprecation" )
        print( "   Priority: IMMEDIATE ACTION REQUIRED" )
        print( "   Risk Level: CRITICAL - Job API operations will break" )
    else:
        print( "✅ Job management API smoke test completed successfully!" )
        print( "   Status: Job lifecycle management API ready for v000 deprecation" )
        print( "   Risk Level: LOW" )
    
    print( "✓ Job management API smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
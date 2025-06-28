#!/usr/bin/env python3
"""
Quick test to verify static file refactoring is working correctly
"""
import os
import sys

# Add the src directory to the path
sys.path.insert( 0, os.path.join( os.path.dirname( __file__ ), '..' ) )

def test_static_paths():
    """Test that all static file paths are correct"""
    
    # Get project root
    project_root = os.path.dirname( os.path.dirname( os.path.dirname( os.path.abspath( __file__ ) ) ) )
    
    # Test 1: Check new static directory exists
    static_dir = os.path.join( project_root, "src/fastapi_app/static" )
    assert os.path.exists( static_dir ), f"Static directory not found: {static_dir}"
    print( f"✓ Static directory exists: {static_dir}" )
    
    # Test 2: Check all subdirectories exist
    subdirs = ["audio", "images", "css", "js", "html"]
    for subdir in subdirs:
        path = os.path.join( static_dir, subdir )
        assert os.path.exists( path ), f"Subdirectory not found: {path}"
        print( f"✓ Subdirectory exists: {subdir}/" )
    
    # Test 3: Check critical files exist
    critical_files = [
        "audio/gentle-gong.mp3",
        "images/play-16.png",
        "html/queue.html",
        "html/test/test-audio.html"
    ]
    
    for file in critical_files:
        path = os.path.join( static_dir, file )
        assert os.path.exists( path ), f"File not found: {path}"
        print( f"✓ File exists: {file}" )
    
    # Test 4: Check old static directory is gone
    old_static = os.path.join( project_root, "src/static" )
    assert not os.path.exists( old_static ), f"Old static directory still exists: {old_static}"
    print( f"✓ Old static directory removed" )
    
    # Test 5: Check HTML files for updated paths
    queue_html = os.path.join( static_dir, "html/queue.html" )
    with open( queue_html, 'r' ) as f:
        content = f.read()
        assert "/static/audio/gentle-gong.mp3" in content, "HTML not updated with new audio path"
        assert "/static/gentle-gong.mp3" not in content, "Old audio path still in HTML"
    print( f"✓ HTML files updated with new paths" )
    
    print( "\n✓ All static file refactoring tests passed!" )

if __name__ == "__main__":
    test_static_paths()
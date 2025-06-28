# Lupin Session History

## 2025.06.28 - Project Renaming to Lupin

### Summary
Successfully completed comprehensive rebranding of the project from "Genie-in-the-Box" to "Lupin" while maintaining all existing functionality and external dependencies. This included updating documentation, renaming client files, updating configuration, and creating a comprehensive R&D index.

### Work Performed
1. **Created comprehensive renaming plan** - Documented in `src/rnd/2025.06.28-lupin-renaming-plan.md`
2. **Updated core documentation**:
   - README.md: Changed project title, updated technical roadmap, removed Flask references
   - history.md: Updated header and project references
   - CLAUDE.md: Updated development guide header and project references
3. **Renamed Python client files**:
   - `genie_client.py` → `lupin_client.py`
   - `genie_client_gui.py` → `lupin_client_gui.py` 
   - `genie_client_cmd.py` → `lupin_client_cmd.py`
   - Updated all import statements in dependent files
4. **Renamed shell scripts**:
   - `run-genie-gui.sh` → `run-lupin-gui.sh`
   - `run-genie-gui.command` → `run-lupin-gui.command`
   - Updated script contents and references
5. **Updated configuration files**:
   - Changed display names in `gib-app.ini` from "Genie in the Box" to "Lupin"
6. **Created R&D documentation index** - `src/rnd/README.md` with comprehensive overview
7. **Testing and validation**:
   - Verified Python syntax on all renamed files
   - Tested import paths and dependencies
   - Confirmed script executability

### Technical Details
- All file renames maintain compatibility with existing infrastructure
- Directory structure preserved (genie-in-the-box directory name unchanged)
- Firefox plugin references left untouched as requested
- External URLs and dependencies remain functional
- Progress notifications sent throughout the process

### Files Renamed
- Client files: 3 Python files renamed with import updates
- Shell scripts: 2 script files renamed and updated
- No directory structure changes (as requested)

### Current Status
Project successfully rebranded to "Lupin". All functionality preserved, documentation updated, and comprehensive planning documents created for future reference.

### Next Steps
- Monitor for any issues with renamed files
- Update any external references if needed
- Continue development under the new "Lupin" branding

---

## 2025.06.28 - Flask Infrastructure Elimination

### Summary
Successfully completed the removal of deprecated Flask server infrastructure from the Lupin project. This eliminates ~1000+ lines of deprecated code and simplifies the architecture to use only FastAPI.

### Work Performed
1. **Created backup branch** `backup-flask-removal-2025-06-28` for safety
2. **Verified FastAPI coverage** - Confirmed that FastAPI has equivalent endpoints for all critical Flask functionality
   - Identified 4 missing endpoints (get-gists, get-io-stats, get-all-io, load-stt-model) that appear to be non-critical
3. **Deleted Flask infrastructure**:
   - Removed `src/app.py` (508 lines)
   - Removed `src/scripts/run-flask-gib.sh`
   - Removed `src/scripts/run-flask-tts.sh`
4. **Updated client references**:
   - Changed `write_method` parameter from "flask" to "api" in `lupin_client.py` (formerly genie_client.py)
   - Changed `write_method` parameter from "flask" to "api" in `lupin_client_gui.py` (formerly genie_client_gui.py)
   - Updated comment from "flask server" to "API server"
5. **Archived migration documents**:
   - Moved `2025.04.05-flask-to-fastapi-migration.md` to `src/rnd/archived/`
   - Moved `2025.05.19-flask-to-fastapi-migration-plan.md` to `src/rnd/archived/`
6. **Updated documentation**:
   - Updated CLAUDE.md to remove Flask references
   - Changed Flask server command to FastAPI server command
   - Updated project structure section to reflect FastAPI-only architecture

### Technical Details
- FastAPI server continues to run on port 7999 (same as Flask)
- All client code now uses generic "api" terminology instead of Flask-specific terms
- No broken imports or references were found after Flask removal

### Next Steps
- Monitor for any issues with the 4 missing endpoints
- Consider implementing the missing endpoints in FastAPI if they're needed
- Update any remaining documentation that might reference Flask

### Current Status
The Flask elimination is complete. The project now runs entirely on FastAPI, simplifying maintenance and improving consistency.
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import json
from donkeycar.parts.tub_v2 import Tub
from donkeycar.pipeline.types import TubRecord
import logging
from typing import List, Optional, Any, Dict

router = APIRouter()
logger = logging.getLogger(__name__)

# Global state to hold the currently loaded tub
# In a multi-user environment, this should be session-based or handled differently.
# For this local desktop app replacement, a global variable is acceptable.
current_tub: Optional[Tub] = None
current_records: List[TubRecord] = []
current_tub_path: str = ""

class TubLoadRequest(BaseModel):
    path: str

class TubFilterRequest(BaseModel):
    filter_expression: str

class TubDeleteRequest(BaseModel):
    indexes: List[int]

class SessionDeleteRequest(BaseModel):
    tub_path: str
    session_id: str

@router.post("/load")
async def load_tub(request: TubLoadRequest):
    global current_tub, current_records, current_tub_path
    path = request.path
    
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Directory not found")
        
    manifest_path = os.path.join(path, 'manifest.json')
    if not os.path.exists(manifest_path):
        raise HTTPException(status_code=400, detail="Path is not a valid tub (manifest.json missing)")
        
    try:
        if current_tub:
            current_tub.close()
            
        current_tub = Tub(path)
        current_tub_path = path
        
        # Load all records initially
        # Note: For very large tubs, we might want to paginate this or load lazily
        # But for the UI replacement, loading indices is fine.
        # TubRecord needs config, but for basic reading we might get away without full config 
        # or we pass a dummy config if needed. 
        # The original code uses: TubRecord(cfg, self.tub.base_path, record)
        # Let's see if we can just return the underlying dicts for now.
        
        # Iterating over tub yields dictionaries
        records = [record for record in current_tub]
        current_records = records 
        
        fields = current_tub.manifest.inputs
        
        return {
            "status": True,
            "record_count": len(records),
            "total_physical_records": current_tub.manifest.current_index,
            "records": records,
            "fields": fields,
            "path": path,
            "deleted_indexes": sorted(list(current_tub.manifest.deleted_indexes)),
        }
    except Exception as e:
        logger.error(f"Failed to load tub: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/records")
async def get_records(offset: int = 0, limit: int = 100):
    global current_records
    if not current_records:
         return {"records": [], "total": 0}
         
    total = len(current_records)
    end = min(offset + limit, total)
    subset = current_records[offset:end]
    
    return {
        "records": subset,
        "total": total,
        "offset": offset,
        "limit": limit
    }

@router.get("/image")
async def get_image(path: str, tubPath: Optional[str] = None):
    # path is relative to the tub images directory usually, or we assume it's the full path if we constructing it
    # In Tub v2, record contains "cam/image_array": "0_cam_image_array_.jpg"
    # And images are in tub_path/images/
    
    global current_tub_path
    target_tub_path = tubPath if tubPath else current_tub_path
    
    if not target_tub_path:
        raise HTTPException(status_code=400, detail="No tub loaded")
        
    # Security check: ensure path doesn't go outside
    # For a local tool, less critical, but good practice.
    
    # If the path comes from the record, it's just the filename usually
    # But sometimes it might include 'images/' prefix if coming from different sources
    clean_path = path.replace('images/', '').replace('images\\', '')
    
    image_full_path = os.path.join(target_tub_path, 'images', clean_path)
    
    if not os.path.exists(image_full_path):
         # Try without 'images' subdir just in case structure is different
         image_full_path_alt = os.path.join(target_tub_path, clean_path)
         if os.path.exists(image_full_path_alt):
             return FileResponse(image_full_path_alt)
             
         logger.error(f"Image not found: {image_full_path}")
         raise HTTPException(status_code=404, detail=f"Image not found: {clean_path}")
         
    return FileResponse(image_full_path)

@router.get("/sessions")
async def list_sessions(tubPath: str):
    """List recording sessions (videos) inside a tub.

    Groups the tub's live records by ``_session_id`` so the Video Library can
    show one entry per recording run. Sessions are ordered by their first
    record's ``_index`` (chronological write order).
    """
    path = os.path.expanduser(tubPath)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Directory not found")

    manifest_path = os.path.join(path, 'manifest.json')
    if not os.path.exists(manifest_path):
        raise HTTPException(status_code=400, detail="Path is not a valid tub (manifest.json missing)")

    try:
        tub = Tub(path, read_only=True)
        try:
            sessions: Dict[str, Dict[str, Any]] = {}
            for record in tub:
                session_id = str(record.get('_session_id', ''))
                first_index = record.get('_index', 0)
                timestamp_ms = record.get('_timestamp_ms')
                entry = sessions.get(session_id)
                if entry is None:
                    sessions[session_id] = {
                        'session_id': session_id,
                        'record_count': 1,
                        'first_index': first_index,
                        'last_index': first_index,
                        'start_time_ms': timestamp_ms,
                        'end_time_ms': timestamp_ms,
                    }
                else:
                    entry['record_count'] += 1
                    entry['last_index'] = max(entry['last_index'], first_index)
                    if entry['start_time_ms'] is None:
                        entry['start_time_ms'] = timestamp_ms
                    entry['end_time_ms'] = timestamp_ms
        finally:
            tub.close()

        items = sorted(sessions.values(), key=lambda s: s['first_index'])
        return {"status": True, "path": path, "sessions": items}
    except Exception as e:
        logger.error(f"Failed to list sessions for tub {path}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/session_records")
async def get_session_records(tubPath: str, sessionId: str):
    """Return the live records of one recording session inside a tub."""
    path = os.path.expanduser(tubPath)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Directory not found")

    try:
        tub = Tub(path, read_only=True)
        try:
            records = [
                record for record in tub
                if str(record.get('_session_id', '')) == sessionId
            ]
        finally:
            tub.close()

        return {"status": True, "path": path, "records": records}
    except Exception as e:
        logger.error(f"Failed to read session {sessionId} of tub {path}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/delete_session")
async def delete_session(request: SessionDeleteRequest):
    """Soft-delete an entire recording session (all its live records).

    Frames are marked deleted in the manifest (same mechanism as the
    frame-level delete), so other panels stop showing them while undo stays
    possible at the manifest level.
    """
    global current_tub, current_records
    path = os.path.expanduser(request.tub_path)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Directory not found")

    try:
        tub = Tub(path, read_only=True)
        try:
            indexes = [
                record['_index'] for record in tub
                if str(record.get('_session_id', '')) == request.session_id
            ]
        finally:
            tub.close()

        if not indexes:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{request.session_id}' not found in tub",
            )

        deleter = Tub(path)
        try:
            deleter.delete_records(indexes)
        finally:
            deleter.close()

        # Keep the globally loaded tub in sync when the same tub was affected
        if current_tub and current_tub_path == path:
            current_tub = Tub(path)
            current_records = [record for record in current_tub]
            record_count = len(current_records)
            deleted_indexes = sorted(list(current_tub.manifest.deleted_indexes))
        else:
            record_count = None
            deleted_indexes = None

        return {
            "status": True,
            "message": f"Deleted {len(indexes)} records of session '{request.session_id}'",
            "deleted_count": len(indexes),
            "record_count": record_count,
            "deleted_indexes": deleted_indexes,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete session {request.session_id} of tub {path}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/delete")
async def delete_records(request: TubDeleteRequest):
    global current_tub, current_records
    if not current_tub:
        raise HTTPException(status_code=400, detail="No tub loaded")
        
    try:
        current_tub.delete_records(request.indexes)
        # Reload records so deleted indexes are reflected in subsequent reads
        current_records = [record for record in current_tub]
        return {
            "status": True,
            "message": f"Deleted {len(request.indexes)} records",
            "record_count": len(current_records),
            "total_physical_records": current_tub.manifest.current_index,
            "deleted_indexes": sorted(list(current_tub.manifest.deleted_indexes)),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/restore")
async def restore_records(request: TubDeleteRequest):
    global current_tub, current_records
    if not current_tub:
        raise HTTPException(status_code=400, detail="No tub loaded")
        
    try:
        current_tub.restore_records(request.indexes)
        # Reload records so restored indexes are reflected in subsequent reads
        current_records = [record for record in current_tub]
        return {
            "status": True,
            "message": f"Restored {len(request.indexes)} records",
            "record_count": len(current_records),
            "total_physical_records": current_tub.manifest.current_index,
            "deleted_indexes": sorted(list(current_tub.manifest.deleted_indexes)),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

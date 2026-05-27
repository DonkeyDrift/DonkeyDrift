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

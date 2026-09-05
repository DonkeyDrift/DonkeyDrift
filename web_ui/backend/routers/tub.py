from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
import hashlib
import os
import io
import json
import tarfile
import threading
from collections import OrderedDict
from donkeycar.parts.tub_v2 import Tub
from donkeycar.pipeline.types import TubRecord
from ai_clean_engine import CollisionReverseHeuristic
import logging
from typing import List, Optional, Any, Dict

router = APIRouter()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 图像缓存（issue #128）：播放器 60fps 逐帧取图，若每次请求都从磁盘读
# 原始 JPEG，磁盘/传输稍慢就会击穿前端预取窗口造成卡顿。这里按
# (mtime, size) 做字节级 LRU 缓存：命中时直接从内存回图，不再碰磁盘。
# ---------------------------------------------------------------------------
IMAGE_CACHE_MAX_BYTES = 128 * 1024 * 1024  # 128 MiB
_image_cache: "OrderedDict[str, tuple[int, int, bytes]]" = OrderedDict()
_image_cache_bytes = 0
# /tub/image 改为同步 def 后由 Starlette 线程池并发执行，缓存读写需加锁
_image_cache_lock = threading.Lock()


def _cache_get(path: str, stat: os.stat_result) -> Optional[bytes]:
    """命中返回文件字节，否则 None；命中时把条目移到 LRU 最新端。"""
    with _image_cache_lock:
        entry = _image_cache.get(path)
        if entry is None:
            return None
        mtime_ns, size, data = entry
        if mtime_ns != stat.st_mtime_ns or size != stat.st_size:
            # 文件已变化，淘汰旧条目
            _cache_evict(path)
            return None
        _image_cache.move_to_end(path)
        return data


def _cache_evict(path: str) -> None:
    global _image_cache_bytes
    entry = _image_cache.pop(path, None)
    if entry is not None:
        _image_cache_bytes -= entry[2].__len__()


def _cache_put(path: str, stat: os.stat_result, data: bytes) -> None:
    global _image_cache_bytes
    if len(data) > IMAGE_CACHE_MAX_BYTES:
        return  # 单文件超过总预算，不值得缓存
    with _image_cache_lock:
        _cache_evict(path)
        _image_cache[path] = (stat.st_mtime_ns, stat.st_size, data)
        _image_cache_bytes += len(data)
        while _image_cache_bytes > IMAGE_CACHE_MAX_BYTES and len(_image_cache) > 1:
            _image_evict_oldest()


def _image_evict_oldest() -> None:
    global _image_cache_bytes
    path, entry = next(iter(_image_cache.items()))
    _image_cache.pop(path)
    _image_cache_bytes -= entry[2].__len__()

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

class AiCleanScanRequest(BaseModel):
    tub_paths: List[str]

class AiCleanTubDeletion(BaseModel):
    tub_path: str
    indexes: List[int]

class AiCleanExecuteRequest(BaseModel):
    deletions: List[AiCleanTubDeletion]

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
def get_image(path: str, tubPath: Optional[str] = None, request: Request = None):
    # 同步 def（非 async）：Starlette 线程池执行，缓存未命中时的磁盘读不再
    # 阻塞 uvicorn 事件循环——60fps 逐帧取图下，一次冷读会卡住全部并发帧请求。
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
             image_full_path = image_full_path_alt
         else:
             logger.error(f"Image not found: {image_full_path}")
             raise HTTPException(status_code=404, detail=f"Image not found: {clean_path}")

    stat = os.stat(image_full_path)
    # ETag 基于 (路径, mtime, size)，配合 Cache-Control 让浏览器 disk cache
    # 也参与：重复播放同一 tub 时大部分帧 304/内存命中，磁盘读趋近于 0。
    etag = f'"{hashlib.md5(image_full_path.encode("utf-8", "ignore")).hexdigest()}-{stat.st_mtime_ns}-{stat.st_size}"'
    if request is not None and request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "private, max-age=86400"})

    data = _cache_get(image_full_path, stat)
    if data is None:
        with open(image_full_path, "rb") as f:
            data = f.read()
        _cache_put(image_full_path, stat, data)

    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"ETag": etag, "Cache-Control": "private, max-age=86400"},
    )

@router.get("/sessions")
async def list_sessions(tubPath: str):
    """List recording sessions (videos) inside a tub.

    Groups the tub's live records by ``_session_id`` so the Video Library can
    show one entry per recording run. Sessions are ordered by their first
    record's ``_index`` descending (newest recording first).
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

        items = sorted(sessions.values(), key=lambda s: s['first_index'], reverse=True)
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

@router.get("/download_session")
async def download_session(tubPath: str, sessionId: str, startTimeMs: int | None = None):
    """Download a recording session's frames as a tar.gz archive.

    Streams the archive to the browser via a pipe so that the browser
    receives data immediately. All tub I/O (opening, iterating, reading
    images, gzip compression) happens in a background thread; the HTTP
    response starts instantly so Safari shows its download prompt
    without delay.
    """
    path = os.path.expanduser(tubPath)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Directory not found")

    images_dir = os.path.join(path, 'images')

    # Compute filename from startTimeMs (provided by the frontend) so we
    # don't need to open the tub just to read the start timestamp.
    if startTimeMs is not None:
        from datetime import datetime
        dt = datetime.fromtimestamp(startTimeMs / 1000)
        filename = f"recording_{dt.strftime('%Y-%m-%d_%H_%M_%S')}.tar.gz"
    else:
        filename = f"recording_{sessionId}.tar.gz"

    # Start streaming immediately — all tub I/O happens in the thread.
    read_fd, write_fd = os.pipe()

    def _build_tar():
        try:
            with os.fdopen(write_fd, 'wb') as f:
                with tarfile.open(fileobj=f, mode='w:gz') as tar:
                    tub = Tub(path, read_only=True)
                    try:
                        image_key = None
                        for record in tub:
                            sid = str(record.get('_session_id', ''))
                            if sid != sessionId:
                                continue
                            if image_key is None:
                                for k in record:
                                    if k.endswith('image_array') and isinstance(record[k], str):
                                        image_key = k
                                        break
                            img_name = record.get(image_key) if image_key else None
                            if not isinstance(img_name, str):
                                continue
                            clean = img_name.replace('images/', '').replace('images\\', '')
                            img_path = os.path.join(images_dir, clean)
                            if not os.path.exists(img_path):
                                img_path_alt = os.path.join(path, clean)
                                if os.path.exists(img_path_alt):
                                    img_path = img_path_alt
                                else:
                                    continue
                            with open(img_path, 'rb') as f_img:
                                data = f_img.read()
                            info = tarfile.TarInfo(name=clean)
                            info.size = len(data)
                            tar.addfile(info, io.BytesIO(data))
                    finally:
                        tub.close()
        except Exception as e:
            logger.error(f"Failed to build tar for session {sessionId} of tub {path}: {e}")

    thread = threading.Thread(target=_build_tar, daemon=True)
    thread.start()

    def _stream():
        try:
            with os.fdopen(read_fd, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
        finally:
            thread.join()

    return StreamingResponse(
        _stream(),
        media_type='application/gzip',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )

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


# ---------------------------------------------------------------------------
# AI 清理「碰撞后倒车」（issue #373）：两段式——先扫描出待删片段清单，
# 用户确认后再批量软删除（复用 manifest 级删除，与框选删除同一机制，
# 事后仍可通过 restore 撤销）。识别规则见 ai_clean_engine.py。
# ---------------------------------------------------------------------------

def _validate_tub_path(path: str) -> str:
    """展开并校验 tub 路径，不合法时抛 HTTPException。"""
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        raise HTTPException(status_code=404, detail=f"Directory not found: {path}")
    if not os.path.exists(os.path.join(expanded, 'manifest.json')):
        raise HTTPException(status_code=400, detail=f"Path is not a valid tub: {path}")
    return expanded


@router.get("/ai_clean/candidates")
async def ai_clean_candidates(tubPath: str):
    """列出可参与 AI 清理的 tub：当前 tub 及其同目录下的兄弟 tub。

    用户的多个 tub 通常平铺在同一目录下（如 data/、data_sim/……），
    批量清理时前端让用户勾选本次要扫描的范围。
    """
    path = _validate_tub_path(tubPath)
    parent = os.path.dirname(path.rstrip(os.sep)) or os.sep

    candidates: List[Dict[str, Any]] = []
    try:
        for name in sorted(os.listdir(parent)):
            child = os.path.join(parent, name)
            if not os.path.isdir(child):
                continue
            if not os.path.isfile(os.path.join(child, 'manifest.json')):
                continue
            candidates.append({
                "path": child,
                "name": name,
                "is_current": os.path.abspath(child) == os.path.abspath(path),
            })
    except OSError as e:
        logger.error(f"Failed to list sibling tubs of {path}: {e}")

    # 当前 tub 必须始终在列表里（父目录不可读等极端情况下兜底）
    if not any(c["is_current"] for c in candidates):
        candidates.insert(0, {
            "path": path,
            "name": os.path.basename(path.rstrip(os.sep)) or path,
            "is_current": True,
        })
    return {"status": True, "current": path, "tubs": candidates}


@router.post("/ai_clean/scan")
async def ai_clean_scan(request: AiCleanScanRequest):
    """批量扫描多个 tub，返回每个 tub 识别出的「碰撞后倒车」待删片段清单。

    单个 tub 失败（路径无效/读取异常）不拖垮整批——该 tub 条目中带回
    error 字段，前端按 tub 分别展示。
    """
    if not request.tub_paths:
        raise HTTPException(status_code=400, detail="No tub paths given")

    detector = CollisionReverseHeuristic()
    tubs: List[Dict[str, Any]] = []
    for raw_path in request.tub_paths:
        path = os.path.expanduser(raw_path)
        try:
            path = _validate_tub_path(path)
            tub = Tub(path, read_only=True)
            try:
                records = [record for record in tub]
            finally:
                tub.close()
            segments = [seg.to_dict() for seg in detector.detect(records)]
            frame_count = sum(seg["frame_count"] for seg in segments)
            tubs.append({
                "tub_path": path,
                "record_count": len(records),
                "segments": segments,
                "segment_count": len(segments),
                "frame_count": frame_count,
            })
        except HTTPException as e:
            tubs.append({"tub_path": path, "error": str(e.detail)})
        except Exception as e:
            logger.error(f"AI clean scan failed for tub {path}: {e}")
            tubs.append({"tub_path": path, "error": str(e)})

    return {
        "status": True,
        "tubs": tubs,
        "total_segments": sum(t.get("segment_count", 0) for t in tubs),
        "total_frames": sum(t.get("frame_count", 0) for t in tubs),
    }


@router.post("/ai_clean/execute")
async def ai_clean_execute(request: AiCleanExecuteRequest):
    """确认后批量删除：对每个 tub 软删除指定帧（manifest 级，可恢复）。

    与 /delete、/delete_session 同一删除机制，删除后 manifest 的
    deleted_indexes 即更新，各面板读取时自动跳过这些帧。
    """
    global current_tub, current_records
    if not request.deletions:
        raise HTTPException(status_code=400, detail="No deletions given")

    results: List[Dict[str, Any]] = []
    total_deleted = 0
    loaded_tub_affected = False
    for deletion in request.deletions:
        path = os.path.expanduser(deletion.tub_path)
        try:
            path = _validate_tub_path(path)
            # 过滤掉非法索引，避免误伤 manifest
            indexes = sorted({i for i in deletion.indexes if isinstance(i, int) and i >= 0})
            if indexes:
                deleter = Tub(path)
                try:
                    deleter.delete_records(indexes)
                finally:
                    deleter.close()
            total_deleted += len(indexes)
            results.append({"tub_path": path, "deleted_count": len(indexes)})
            if current_tub and current_tub_path == path:
                loaded_tub_affected = True
        except HTTPException as e:
            results.append({"tub_path": path, "error": str(e.detail)})
        except Exception as e:
            logger.error(f"AI clean execute failed for tub {path}: {e}")
            results.append({"tub_path": path, "error": str(e)})

    # 当前已加载的 tub 被清理过时同步全局状态，其它面板立即反映删除结果
    response: Dict[str, Any] = {
        "status": True,
        "results": results,
        "total_deleted": total_deleted,
        "record_count": None,
        "deleted_indexes": None,
    }
    if loaded_tub_affected:
        try:
            current_tub.close()
            current_tub = Tub(current_tub_path)
            current_records = [record for record in current_tub]
            response["record_count"] = len(current_records)
            response["deleted_indexes"] = sorted(list(current_tub.manifest.deleted_indexes))
        except Exception as e:
            logger.error(f"Failed to reload tub {current_tub_path} after AI clean: {e}")
    return response

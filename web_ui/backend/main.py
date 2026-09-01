from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import atexit
import uvicorn
import os
import sys
import logging

# Add project root to sys.path to allow importing donkeycar if not installed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from routers import config, tub, trainer, drive, arena, connector, launch, console, simcollect, drift

DEBUG = os.environ.get("DRIVE_WEB_DEBUG", "").lower() in ("1", "true", "yes")

if not DEBUG:
    # 抑制 uvicorn 访问日志
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # 抑制 aioice ICE 协商日志
    logging.getLogger("aioice").setLevel(logging.WARNING)
    logging.getLogger("aioice.ice").setLevel(logging.WARNING)
    # 抑制 aiortc 底层日志
    logging.getLogger("aiortc").setLevel(logging.WARNING)
    # 抑制后端业务路由日志（连接/断连统计等）
    logging.getLogger("routers.drive").setLevel(logging.WARNING)

app = FastAPI(title="DonkeyDrifter")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development, allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def apply_cache_headers(response, path: str) -> None:
    """静态资源缓存策略：带哈希的 assets 可长期不可变缓存，HTML 每次重新校验。

    前端每次构建产物文件名都带内容哈希，但 index.html 本身会被浏览器
    启发式缓存——没有 Cache-Control 时，用户刷新页面可能仍复用旧的
    index.html，从而加载旧的 JS bundle，导致"修好了却还在跑旧代码"（#135 收尾）。
    """
    content_type = response.headers.get("content-type", "")
    if path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif "text/html" in content_type:
        response.headers["Cache-Control"] = "no-cache"


@app.middleware("http")
async def cache_control_middleware(request, call_next):
    response = await call_next(request)
    apply_cache_headers(response, request.url.path)
    return response

# 挂载 API 路由
app.include_router(config.router, prefix="/api/config", tags=["config"])
app.include_router(tub.router, prefix="/api/tub", tags=["tub"])
app.include_router(trainer.router, prefix="/api/trainer", tags=["trainer"])
app.include_router(drive.router, prefix="/api/drive", tags=["drive"])
app.include_router(arena.router, prefix="/api/arena", tags=["arena"])
app.include_router(connector.router, prefix="/api/connector", tags=["connector"])
app.include_router(launch.router, prefix="/api/launch", tags=["launch"])
app.include_router(console.router, prefix="/api/console", tags=["console"])
app.include_router(simcollect.router, prefix="/api/simcollect", tags=["simcollect"])
app.include_router(drift.router, prefix="/api/drift", tags=["drift"])


@app.on_event("startup")
async def _install_drift_hooks():
    drift.install_drive_hooks()


@app.on_event("shutdown")
async def _stop_drift_engine():
    """应用关闭必须停掉漂移相机循环（释放 DirectShow 句柄）。"""
    drift.drift_engine.stop_camera_loop()


# 进程退出兜底：shutdown 钩子跑不到时（强杀/reload 边缘）也尽力释放相机；
# stop_camera_loop 幂等，重复调用安全。
atexit.register(drift.drift_engine.stop_camera_loop)

# 前端静态文件目录（生产构建输出）
FRONTEND_DIST = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
)
FRONTEND_ASSETS = os.path.join(FRONTEND_DIST, "assets")

if os.path.isdir(FRONTEND_DIST):
    # 静态资源（JS/CSS/图片等）
    if os.path.isdir(FRONTEND_ASSETS):
        app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """根目录静态文件 + SPA fallback。

        不能再用 app.mount("/", StaticFiles(html=True)) 处理根目录：它会拦截所有
        路径，导致 /connector、/drive 等前端深链（无扩展名、非真实文件）被
        StaticFiles 判为 404，刷新/直达时无法回退到 index.html。
        这里改为：真实存在的根目录静态文件（favicon、robots.txt 等）直接返回，
        其余一律回退到 index.html，交给前端路由处理；不存在的 API 路径保持 404。
        """
        if full_path:
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not Found")
            candidate = os.path.realpath(os.path.join(FRONTEND_DIST, full_path))
            if candidate.startswith(FRONTEND_DIST + os.sep) and os.path.isfile(candidate):
                return FileResponse(candidate)
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path)
        return {"message": "DonkeyDrifter is running"}
else:
    @app.get("/")
    async def root():
        return {"message": "DonkeyDrifter is running (frontend not built, run: cd web_ui/frontend && npm run build)"}

if __name__ == "__main__":
    port = int(os.environ.get("DRIVE_WEB_PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)

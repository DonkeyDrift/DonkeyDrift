from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import atexit
import uvicorn
import os
import sys
import logging
from contextlib import asynccontextmanager

# Add project root to sys.path to allow importing donkeycar if not installed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from routers import config, tub, trainer, drive, arena, connector, launch, console, simcollect, zcode_remote, ai_config, harness_updater, drift
from routers import findcar as findcar_router

DEBUG = os.environ.get("DRIVE_WEB_DEBUG", "").lower() in ("1", "true", "yes")

# CORS 白名单默认收敛到回环（生产模式前后端同源，跨域默认不需要；
# dev 模式下 Vite 走同源代理 /api -> 127.0.0.1:backend，同样不需要跨域）。
# 局域网多机部署（浏览器在另一台机器上直连 0.0.0.0 后端）需显式放开：
#   DRIVE_WEB_CORS_ORIGINS="*"                      # 允许任意来源（等同旧行为）
#   DRIVE_WEB_CORS_ORIGINS="http://192.168.1.10:5188,http://car:8000"  # 白名单
#   DRIVE_WEB_CORS_ALLOW_ORIGIN_REGEX="https?://.*\\.lan(:[0-9]+)?$"   # 正则（与白名单取并集）
# 注意：allow_credentials=True 与通配符 origin 组合在浏览器侧会被拒绝
# （Fetch 规范要求凭据模式下 Access-Control-Allow-Origin 不能是 *），
# 因此 "*" 仅作为兼容旧部署的逃生舱，新部署请写明确来源或正则。
#
# Starlette 1.x 的 is_allowed_origin() 对 allow_origins 是**精确匹配**
# （origin in self.allow_origins），不支持 scheme+host 前缀、也不剥端口，
# 所以默认白名单必须列全「回环地址 × 端口」组合（Vite dev 5188 / 生产
# 后端 8000），不能只写 http://localhost 就指望放行 http://localhost:5188。
_DEFAULT_LOOPBACK_SCHEMES = ("http://", "https://")
_DEFAULT_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "[::1]")
_DEFAULT_LOOPBACK_PORTS = ("", ":5188", ":8000")

DEFAULT_CORS_ORIGINS = tuple(
    f"{scheme}{host}{port}"
    for scheme in _DEFAULT_LOOPBACK_SCHEMES
    for host in _DEFAULT_LOOPBACK_HOSTS
    for port in _DEFAULT_LOOPBACK_PORTS
)


def _resolve_cors_config():
    """解析 CORS 配置，返回 (allow_origins, allow_origin_regex)。

    - 未设置 DRIVE_WEB_CORS_ORIGINS → 回环白名单（默认安全行为）。
    - 设置为 "*" → 任意来源（等同旧实现，兼容既有局域网部署）。
    - 设置为逗号分隔列表 → 精确匹配这些来源。
    - DRIVE_WEB_CORS_ALLOW_ORIGIN_REGEX 额外提供正则，与白名单取并集；
      设为 "*" 时等价于任意来源。
    """
    raw = os.environ.get("DRIVE_WEB_CORS_ORIGINS", "").strip()
    regex = os.environ.get("DRIVE_WEB_CORS_ALLOW_ORIGIN_REGEX", "").strip()
    if regex == "*":
        return ["*"], None
    regex = regex or None
    if not raw:
        return list(DEFAULT_CORS_ORIGINS), regex
    if raw == "*":
        return ["*"], regex
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return (origins or list(DEFAULT_CORS_ORIGINS)), regex


def _resolve_cors_origins():
    return _resolve_cors_config()[0]

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动/关闭后台任务（issue #404）。

    Starlette 1.x 在自定义 lifespan 存在时不再触发 on_event 处理器（会静默
    停摆），后台任务统一并入 lifespan：
    - Harness 一键更新周期检查（issue #404）；
    - drift 驱动钩子安装与漂移相机释放（关停必须停相机循环释放 DirectShow 句柄）。

    findcar 主机心跳已迁至常驻 launcher（donkeycar/launcher/server.py），
    不再随本后端启停；本后端只保留 /api/findcar/config 配置接口。
    """
    harness_updater.start_background_check()
    try:
        drift.install_drive_hooks()
    except Exception:
        logging.getLogger(__name__).warning("drift 驱动钩子安装失败", exc_info=True)
    try:
        yield
    finally:
        try:
            drift.drift_engine.stop_camera_loop()
        except Exception:
            logging.getLogger(__name__).warning("drift 相机释放失败", exc_info=True)
        await harness_updater.stop_background_check()


app = FastAPI(title="DonkeyDrifter Web API", lifespan=lifespan)

# Configure CORS（默认仅回环来源，详见 _resolve_cors_config 注释）
_cors_origins, _cors_origin_regex = _resolve_cors_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
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
app.include_router(zcode_remote.router, prefix="/api/zcode-remote", tags=["zcode-remote"])
app.include_router(console.router, prefix="/api/console", tags=["console"])
app.include_router(simcollect.router, prefix="/api/simcollect", tags=["simcollect"])
app.include_router(findcar_router.router, prefix="/api/findcar", tags=["findcar"])
app.include_router(ai_config.router, prefix="/api/ai-config", tags=["ai-config"])
app.include_router(harness_updater.router, prefix="/api/harness", tags=["harness"])
app.include_router(drift.router, prefix="/api/drift", tags=["drift"])


# 进程退出兜底：lifespan 关停钩子跑不到时（强杀/reload 边缘）也尽力释放相机；
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
        return {"message": "DonkeyDrifter Web UI is running"}
else:
    @app.get("/")
    async def root():
        return {"message": "DonkeyDrifter Web UI is running (frontend not built, run: cd web_ui/frontend && npm run build)"}


if __name__ == "__main__":
    port = int(os.environ.get("DRIVE_WEB_PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)

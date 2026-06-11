from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import sys
import logging

# Add project root to sys.path to allow importing donkeycar if not installed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from routers import config, tub, trainer, drive, arena, connector

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

app = FastAPI(title="DonkeyDrifter Web API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development, allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config.router, prefix="/api/config", tags=["config"])
app.include_router(tub.router, prefix="/api/tub", tags=["tub"])
app.include_router(trainer.router, prefix="/api/trainer", tags=["trainer"])
app.include_router(drive.router, prefix="/api/drive", tags=["drive"])
app.include_router(arena.router, prefix="/api/arena", tags=["arena"])
app.include_router(connector.router, prefix="/api/connector", tags=["connector"])

@app.get("/")
async def root():
    return {"message": "DonkeyDrifter Web API is running"}

if __name__ == "__main__":
    port = int(os.environ.get("DRIVE_WEB_PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)

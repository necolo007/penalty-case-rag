"""FastAPI 入口：保险监管处罚案例知识库与合规审查系统。

启动：uvicorn api.main:app --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.dependencies import init_app_state
from api.routes import cases, documents, meta, review, search
from core.db import close_pool
from core.redis_client import close_redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_app_state()
    yield
    await close_pool()
    await close_redis()


app = FastAPI(
    title="保险监管处罚案例知识库与合规审查系统",
    description="知识增强检索：四路混合召回 + RRF 融合 + Cross-Encoder 精排 + 可解释审查",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router, prefix="/api/v1/documents", tags=["文档管理"])
app.include_router(cases.router, prefix="/api/v1/cases", tags=["案例管理"])
app.include_router(search.router, prefix="/api/v1/search", tags=["案例检索"])
app.include_router(review.router, prefix="/api/v1/review", tags=["合规审查"])
app.include_router(meta.router, prefix="/api/v1", tags=["元数据"])

# 前端 SPA：`cd web && npm run build` → web/dist（运行时检测，避免启动早于构建）
_WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"
_SPA_ROUTE_PREFIXES = frozenset({"search", "cases", "documents", "review"})
_STATIC_MOUNTED = False


def _ensure_spa_assets_mounted() -> None:
    """构建产物出现后挂载 /assets（可在首次请求时补挂）。"""
    global _STATIC_MOUNTED
    if _STATIC_MOUNTED:
        return
    assets = _WEB_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
        _STATIC_MOUNTED = True


def _spa_index() -> FileResponse:
    from fastapi import HTTPException

    index = _WEB_DIST / "index.html"
    if not index.is_file():
        raise HTTPException(
            404,
            detail="前端未构建：请在 web/ 下执行 npm run build，或使用 npm run dev",
        )
    _ensure_spa_assets_mounted()
    return FileResponse(index)


# 启动时若已有 dist 则立即挂载静态资源
if (_WEB_DIST / "assets").is_dir():
    _ensure_spa_assets_mounted()


@app.get("/favicon.svg", include_in_schema=False)
async def web_favicon():
    from fastapi import HTTPException

    path = _WEB_DIST / "favicon.svg"
    if path.is_file():
        return FileResponse(path)
    raise HTTPException(404)


@app.get("/", include_in_schema=False)
async def web_index():
    return _spa_index()


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    """客户端路由回退；不拦截 /api、/docs、/openapi 等。"""
    from fastapi import HTTPException

    first = full_path.split("/", 1)[0]
    if first in {"api", "docs", "redoc", "openapi.json", "openapi"}:
        raise HTTPException(404)
    if not _WEB_DIST.is_dir():
        raise HTTPException(
            404,
            detail="前端未构建：请在 web/ 下执行 npm run build，或使用 npm run dev",
        )
    _ensure_spa_assets_mounted()
    file_path = (_WEB_DIST / full_path).resolve()
    try:
        file_path.relative_to(_WEB_DIST.resolve())
    except ValueError as exc:
        raise HTTPException(404) from exc
    if file_path.is_file():
        return FileResponse(file_path)
    if first in _SPA_ROUTE_PREFIXES:
        return _spa_index()
    raise HTTPException(404)

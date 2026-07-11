"""FastAPI 入口：保险监管处罚案例知识库与合规审查系统。

启动：uvicorn api.main:app --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.dependencies import init_app_state
from api.routes import cases, documents, eval as eval_routes, meta, review, search
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
app.include_router(eval_routes.router, prefix="/api/v1/eval", tags=["评测"])
app.include_router(meta.router, prefix="/api/v1", tags=["元数据"])

"""Production AI Agent — Part 6 Final Project."""
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.logging_config import setup_logging
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask

setup_logging()
logger = logging.getLogger("agent")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # SIGTERM do uvicorn xử lý: ngừng nhận kết nối mới, chờ request đang chạy xong, rồi mới
    # chạy phần sau yield. Không tự đăng ký signal handler để khỏi đè mất handler đó.
    logger.info("startup", extra={"environment": settings.environment,
                                  "rate_limit_per_minute": settings.rate_limit_per_minute,
                                  "daily_budget_usd": settings.daily_budget_usd})
    if not settings.agent_api_key:
        logger.warning("AGENT_API_KEY is not set, /ask will reject every request")
    yield
    r.close()
    logger.info("shutdown")


_docs = {} if settings.environment != "production" else {
    "docs_url": None, "redoc_url": None, "openapi_url": None}
app = FastAPI(title="Production AI Agent", version="1.0.0", lifespan=lifespan, **_docs)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = uuid.uuid4().hex[:12]
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # Stack trace chỉ ghi vào log, client nhận thông báo chung kèm request_id để tra
        logger.exception("unhandled_error", extra={"request_id": request_id})
        response = JSONResponse({"detail": "Internal server error", "request_id": request_id}, 500)
    response.headers["X-Request-ID"] = request_id
    logger.info("request", extra={
        "request_id": request_id, "method": request.method, "path": request.url.path,
        "status": response.status_code, "ms": round((time.perf_counter() - start) * 1000, 1)})
    return response


@app.exception_handler(redis.RedisError)
async def redis_unavailable(_: Request, exc: redis.RedisError):
    # Không đếm được lượt gọi và chi phí thì từ chối, thay vì cho gọi LLM không giới hạn
    logger.error("redis_unavailable", extra={"error": type(exc).__name__})
    return JSONResponse({"detail": "Service temporarily unavailable"}, 503, {"Retry-After": "5"})


class AskRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    user_id: str | None = Field(default=None, max_length=100)


class AskResponse(BaseModel):
    question: str
    answer: str
    cost_usd: float


@app.get("/health")
def health():
    """Liveness: process còn chạy là 200. Không gọi Redis, vì restart agent không sửa được Redis."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness: mất Redis → 503 để load balancer ngừng gửi traffic tới instance này."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis unavailable")
    return {"status": "ready"}


# `def` (không async): mock LLM dùng time.sleep, FastAPI chạy trong threadpool nên không chặn event loop
@app.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()
    answer = llm_ask(body.question)
    cost = record_cost(estimate_tokens(body.question), estimate_tokens(answer))
    return AskResponse(question=body.question, answer=answer, cost_usd=round(cost, 8))

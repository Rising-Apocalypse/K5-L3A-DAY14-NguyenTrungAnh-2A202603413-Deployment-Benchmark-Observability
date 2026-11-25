"""
Cost guard — cộng dồn chi phí LLM trong ngày (UTC) vào Redis, hết budget → 402.

Giới hạn đã biết: chi phí chỉ biết sau khi gọi LLM, nên các request đang chạy song song lúc
sắp hết budget có thể vượt nhẹ (tối đa bằng chi phí của số request đang chạy).
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

KEY_TTL_SECONDS = 2 * 24 * 3600


def _today_key() -> str:
    return f"cost:{datetime.now(timezone.utc):%Y-%m-%d}"


def estimate_tokens(text: str) -> int:
    """Ước lượng ~4 ký tự/token (mock LLM không trả số token)."""
    return max(1, len(text) // 4)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → HTTP 402."""
    if float(r.get(_today_key()) or 0) >= settings.daily_budget_usd:
        raise HTTPException(status_code=402, detail="Daily budget exceeded")


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí vào tổng trong ngày, trả về chi phí của request."""
    cost = input_tokens / 1000 * PRICE_INPUT_PER_1K + output_tokens / 1000 * PRICE_OUTPUT_PER_1K
    key = _today_key()
    with r.pipeline() as pipe:
        pipe.incrbyfloat(key, cost)  # không làm tròn: cost rất nhỏ, làm tròn sẽ thành 0
        pipe.expire(key, KEY_TTL_SECONDS)
        pipe.execute()
    return cost

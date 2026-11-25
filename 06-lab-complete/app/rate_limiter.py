"""
Rate limiting — sliding window 60 giây bằng Redis sorted set.

Mỗi request là một phần tử, score là thời điểm request. State nằm trong Redis nên mọi
worker / instance dùng chung và vẫn còn sau khi restart agent.
"""
import hashlib
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60

# Chạy bằng Lua để "đếm rồi ghi" là một thao tác nguyên tử: nếu tách thành nhiều lệnh, 2 worker
# có thể cùng đọc thấy "còn 1 lượt" và cùng cho qua. Dùng giờ của Redis (TIME) để các instance
# lệch đồng hồ vẫn tính chung một cửa sổ.
# Trả về 0 nếu cho qua, ngược lại là số mili giây phải chờ.
_SLIDING_WINDOW = r.register_script("""
local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)
local window = tonumber(ARGV[1]) * 1000
local limit = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
if redis.call('ZCARD', KEYS[1]) >= limit then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  if not oldest[2] then return window end
  return math.max(1, oldest[2] + window - now)
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window)
return 0
""")


def check_rate_limit(key: str) -> None:
    """Vượt RATE_LIMIT_PER_MINUTE request / 60 giây → HTTP 429 kèm Retry-After."""
    # Băm API key để key thật không nằm trong Redis
    bucket = "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:32]
    limit = settings.rate_limit_per_minute
    wait_ms = int(_SLIDING_WINDOW(keys=[bucket], args=[WINDOW_SECONDS, limit, uuid.uuid4().hex]))
    if wait_ms > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {limit} requests per {WINDOW_SECONDS}s",
            headers={"Retry-After": str(-(-wait_ms // 1000))},  # làm tròn lên
        )

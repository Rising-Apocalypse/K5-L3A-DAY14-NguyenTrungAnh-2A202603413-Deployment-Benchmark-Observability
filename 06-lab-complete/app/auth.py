"""API Key authentication: header X-API-Key phải trùng AGENT_API_KEY, thiếu hoặc sai → 401."""
import hmac

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from app.config import settings

# auto_error=False: tự trả 401. Để FastAPI tự xử lý thì thiếu header sẽ ra 403/422.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency cho /ask. Trả về API key hợp lệ."""
    expected = settings.agent_api_key
    # `not expected`: server chưa đặt key thì đóng cửa, không coi "rỗng == rỗng" là hợp lệ.
    # compare_digest: thời gian so sánh không phụ thuộc số ký tự trùng (chống timing attack).
    if not expected or not api_key or not hmac.compare_digest(api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key

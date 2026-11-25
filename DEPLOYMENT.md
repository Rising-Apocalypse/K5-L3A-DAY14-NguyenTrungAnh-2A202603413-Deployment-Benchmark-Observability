# Deployment Information

## Public URL

https://day14-agent-production-95a50df9.up.railway.app

## Platform

Railway: agent build từ `06-lab-complete/Dockerfile` theo `06-lab-complete/railway.toml`, kèm service Redis cùng project. (`06-lab-complete/render.yaml` là phương án thay thế trên Render.)

## Cách deploy

Railway CLI 5.75.0 (chạy bằng `npx`, không cài global), trong thư mục `06-lab-complete/`:

```bash
npx @railway/cli@5.75.0 login                     # đăng nhập trên trình duyệt
npx @railway/cli@5.75.0 init --name day14-agent
npx @railway/cli@5.75.0 add --database redis
npx @railway/cli@5.75.0 add --service day14-agent --variables 'REDIS_URL=${{Redis.REDIS_URL}}' --variables 'ENVIRONMENT=production'   # và các biến ở bảng dưới
npx @railway/cli@5.75.0 variable set AGENT_API_KEY --stdin --service day14-agent --skip-deploys < file-chứa-key
npx @railway/cli@5.75.0 up . --path-as-root --service day14-agent --ci
npx @railway/cli@5.75.0 domain --service day14-agent
```

## Test Commands

`BASE` là URL public, `AGENT_API_KEY` là key đã đặt trên Railway (không có trong repo). Mỗi lệnh chỉ in mã HTTP nên chụp ảnh không lộ key.

```bash
BASE=https://day14-agent-production-95a50df9.up.railway.app
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'
```

Kết quả chạy ngày 25/11/2026:

| Kiểm tra | Kết quả |
|---|---|
| `GET /health` | 200 `{"status":"ok"}` |
| `GET /ready` (Redis trên cloud) | 200 `{"status":"ready"}` |
| `POST /ask` không có key | 401 `{"detail":"Invalid or missing API key"}` |
| `POST /ask` có key | 200, trả `answer` và `cost_usd` |
| Rate limit: đã gọi 1 lần, gọi thêm 12 lần có key | 9 lần 200, rồi 3 lần 429 (giới hạn 10/phút) |
| `http://` | 301 chuyển sang `https://` |
| `GET /docs` | 404 (tắt tài liệu API ở `ENVIRONMENT=production`) |
| `python check_production_ready.py --public-url $BASE` | PASS 12/12, 44/44 checks |

## Environment Variables Set

| Biến | Giá trị | Ghi chú |
|---|---|---|
| `AGENT_API_KEY` | (secret, đặt trên Railway) | Không nằm trong repo |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` | Tham chiếu tới service Redis cùng project |
| `ENVIRONMENT` | `production` | |
| `LOG_LEVEL` | `INFO` | |
| `RATE_LIMIT_PER_MINUTE` | `10` | |
| `DAILY_BUDGET_USD` | `1.0` | |
| `PORT` | Railway tự cấp | App nghe theo biến này |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)

# Deployment Information

> **Trạng thái: chưa deploy.** Mục URL và kết quả test bên dưới sẽ điền sau khi deploy thật.

## Public URL

<!-- URL_PUBLIC -->

## Platform

Railway: agent build từ `06-lab-complete/Dockerfile` theo `06-lab-complete/railway.toml`, kèm service Redis cùng project. (`06-lab-complete/render.yaml` là phương án thay thế trên Render.)

## Cách deploy

```bash
cd 06-lab-complete
npx @railway/cli login          # đăng nhập trên trình duyệt
npx @railway/cli init           # tạo project
npx @railway/cli add --database redis
npx @railway/cli add --service day14-agent
# đặt biến môi trường cho day14-agent (bảng bên dưới), rồi:
npx @railway/cli up --service day14-agent
npx @railway/cli domain --service day14-agent
```

## Test Commands

`BASE` là URL public, `AGENT_API_KEY` là key đã đặt trên Railway. Lệnh chỉ in mã HTTP nên chụp ảnh không lộ key.

```bash
curl -s -o /dev/null -w "%{http_code}\n" $BASE/health          # 200
curl -s -o /dev/null -w "%{http_code}\n" $BASE/ready           # 200
curl -s -o /dev/null -w "%{http_code}\n" -X POST $BASE/ask -H "Content-Type: application/json" -d '{"user_id":"test","question":"Hello"}'   # 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST $BASE/ask -H "X-API-Key: $AGENT_API_KEY" -H "Content-Type: application/json" -d '{"user_id":"test","question":"Hello"}'   # 200
```

Kết quả trên cloud: <!-- TEST_RESULT -->

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

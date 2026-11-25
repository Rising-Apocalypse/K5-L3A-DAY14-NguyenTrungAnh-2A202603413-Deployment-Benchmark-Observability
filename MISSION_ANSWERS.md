# Day 14 Lab - Mission Answers

> Máy chạy: MacBook Air M1 (8 CPU, 8 GB RAM), macOS 27.2.1, Docker 29.9.3 (VM 8 CPU / 3,8 GB), Python 3.13.5.
> Cổng 8000 trên máy đang có service khác dùng nên các app chạy thẳng bằng Python được bật ở cổng 8010–8014, container ở 18080–18081. Ngoài cổng ra, lệnh giữ nguyên như đề.

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

Trong `01-localhost-vs-production/develop/app.py`:

1. **Hardcode API key** (dòng 17, `OPENAI_API_KEY = "sk-..."`). Push lên GitHub là lộ, và xoá file không xoá được khỏi lịch sử git.
2. **Hardcode chuỗi kết nối database kèm mật khẩu** (dòng 18, `admin:password123`).
3. **Ghi secret ra log** (dòng 34, `print(... OPENAI_API_KEY)`). Log thường được gửi sang hệ thống khác và nhiều người đọc được.
4. **Config viết cứng** (dòng 21–22, `DEBUG`, `MAX_TOKENS`). Đổi môi trường phải sửa code và build lại.
5. **Dùng `print()`** thay cho logging: không có mức độ, thời gian, cấu trúc để lọc.
6. **Không có `/health`, `/ready`**. Gọi thử `/health` trả 404 nên platform không biết app còn sống để restart.
7. **`host="localhost"`** (dòng 51): chỉ nhận kết nối từ chính máy đó, chạy trong container thì bên ngoài không gọi được.
8. **Port cố định 8000** (dòng 52): Railway/Render cấp cổng qua biến `PORT`.
9. **`reload=True`** (dòng 53): chế độ dev, tốn tài nguyên và tự khởi động lại khi file đổi.
10. **Không có lifespan / xử lý shutdown** và `question` nằm trên query string, nên nội dung câu hỏi lọt vào access log của mọi proxy.

### Exercise 1.2: Chạy bản develop

```text
$ curl -i -X POST "http://localhost:8010/ask?question=Hello"
HTTP/1.1 200 OK
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}

# gửi JSON: 422 vì bản này nhận question qua query
HTTP/1.1 422 Unprocessable Content
{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}

# GET /health
404

# log của server: secret bị in ra
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
```

Nó chạy, nhưng chưa production-ready: key in ra log, không có health check, chỉ nghe trên localhost.

### Exercise 1.3: Comparison table

| Feature | Develop | Production | Tại sao quan trọng? |
|---------|---------|------------|---------------------|
| Config | Viết cứng (dòng 17–22) | `config.py` đọc `os.getenv` | Cùng một bản build chạy được ở dev, staging, production |
| Secret | Nằm trong code và in ra log | Từ env, `.env` không commit. `ENVIRONMENT=production` mà thiếu `AGENT_API_KEY` thì dừng ngay: `ValueError: AGENT_API_KEY must be set in production!` | Không lộ qua git hay log; thiếu cấu hình thì lỗi lúc khởi động thay vì lúc có khách |
| Health check | Không có (404) | `/health` và `/ready` (dòng 135 trở đi) | Platform biết khi nào restart, load balancer biết khi nào gửi traffic |
| Logging | `print()` | `logging`, không ghi nội dung câu hỏi (chỉ `question_length`) | Lọc, tìm và cảnh báo được; không lộ dữ liệu người dùng |
| Shutdown | Đột ngột | Lifespan + SIGTERM, log "Agent shutting down gracefully" | Deploy bản mới không cắt ngang request |
| Host / Port | `localhost:8000` | `0.0.0.0` và `PORT` từ env | Chạy được trong container và trên cloud |
| CORS | Không cấu hình | Danh sách origin từ env | Chặn web lạ gọi API từ trình duyệt |
| Reload | Luôn bật | Theo `DEBUG` | Không chạy chế độ dev ở production |

Hai điểm phát hiện khi chạy thử bản production (nên nó chưa hẳn là mẫu chuẩn):

- Khi không đặt `OPENAI_API_KEY`, **log INFO dạng JSON biến mất**. Lý do: `config.py` gọi `logging.warning()` trước, Python tự cấu hình root logger, nên `logging.basicConfig(format=...)` sau đó không có tác dụng. Đặt một giá trị giả cho `OPENAI_API_KEY` thì log hiện lại.
- Format `"msg":"%(message)s"` lồng JSON vào chuỗi mà không escape (`"msg":"{"event": ...}"`), nên dòng log **không phải JSON hợp lệ**. Part 6 dùng `Formatter` với `json.dumps` để tránh lỗi này.

## Part 2: Docker

### Exercise 2.1: Dockerfile questions

1. **Base image:** `python:3.11` (bản đầy đủ, đo được 1,60 GB trên máy).
2. **Working directory:** `/app`.
3. **Vì sao COPY requirements.txt trước:** Docker cache theo từng layer. Code đổi thường xuyên, dependencies ít đổi. Copy requirements và `pip install` trước thì sửa code chỉ build lại layer `COPY app.py`, không phải cài lại 53,7 MB thư viện. Nếu `COPY . .` đứng trước, sửa một dòng code cũng làm mất cache của `pip install`.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh mặc định, bị thay hoàn toàn khi truyền lệnh khác vào `docker run image <lệnh>`. `ENTRYPOINT` là chương trình cố định, tham số sau tên image được nối vào sau nó (muốn đổi phải dùng `--entrypoint`). Dùng cả hai thì `CMD` thành tham số mặc định của `ENTRYPOINT`.

### Exercise 2.2: Build và chạy

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ curl -i -X POST "http://127.0.0.1:18081/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
$ docker exec k5p2 id
uid=0(root) gid=0(root) groups=0(root)
```

### Exercise 2.3: Image size comparison

```text
$ docker images | grep my-agent
my-agent:advanced    bc4a4494eb4a    265MB     57.5MB
my-agent:develop     0de7c43f738f    1.67GB    415MB
                                     (dung lượng trên đĩa / phần nội dung nén)
$ docker image inspect -f '{{.Size}}'
develop  1672153436 byte      advanced  265489087 byte
```

- Develop: **1672 MB**
- Production: **265 MB**
- Difference: giảm **84,1%** = (1672,2 − 265,5) / 1672,2

**Stage 1 (builder):** từ `python:3.11-slim`, cài `gcc`, `libpq-dev` và cài thư viện vào `/root/.local`. **Stage 2 (runtime):** bắt đầu lại từ `slim` sạch, chỉ copy `/root/.local` (41,2 MB) và code, chạy bằng `appuser` (`uid=999`) thay vì root.

**Vì sao nhỏ hơn:** phần lớn nhờ base image: `python:3.11` là 1603 MB, `python:3.11-slim` là 213 MB. Multi-stage giữ cho `gcc`, header và cache của apt/pip nằm lại ở builder, không đi vào image cuối. Ít gói hơn cũng là ít lỗ hổng hơn.

### Exercise 2.4: Docker Compose stack

```text
                      máy host
                         │ :80 (:443 có mở nhưng nginx.conf chưa listen)
                  ┌──────▼───────┐
                  │    nginx     │  rate limit 10 r/s mỗi IP, security headers
                  └──────┬───────┘
   mạng "internal"       │ http://agent:8000
                  ┌──────▼───────┐
                  │    agent     │  không mở cổng ra host
                  └──┬────────┬──┘
       REDIS_URL     │        │   QDRANT_URL
              ┌──────▼──┐  ┌──▼───────┐
              │  redis  │  │  qdrant  │   volume redis_data, qdrant_data
              │  :6379  │  │  :6333   │
              └─────────┘  └──────────┘
```

4 service được start: `nginx`, `agent`, `redis`, `qdrant`. Chúng gọi nhau bằng **tên service** qua DNS của Docker. `agent` chờ `redis` và `qdrant` healthy rồi mới chạy (`depends_on: condition: service_healthy`). Chỉ nginx mở cổng ra ngoài.

```text
$ docker compose -p k5-day14-docker ps
agent  | Up (healthy) | 8000/tcp              nginx | Up | 0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant | Up (healthy) | 6333-6334/tcp         redis | Up (healthy) | 6379/tcp

$ curl -i http://localhost/health
HTTP/1.1 200 OK
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
{"status":"ok","uptime_seconds":7.6,"version":"2.0.0",...}

$ curl -i -X POST http://localhost/ask -H 'Content-Type: application/json' -d '{"question":"Explain microservices"}'
HTTP/1.1 200 OK
{"answer":"Đây là câu trả lời từ AI agent (mock). ..."}

# từ trong container agent, mở kết nối TCP theo tên service
redis ('172.22.0.3', 6379)   qdrant ('172.22.0.2', 6333)   nginx ('172.22.0.5', 80)
```

Lưu ý: `main.py` của ví dụ này chưa dùng Redis hay Qdrant; compose mới nối mạng và khai báo URL.

## Part 3: Cloud Deployment

### Exercise 3.1: Deploy agent Part 6

- URL: https://day14-agent-production-95a50df9.up.railway.app (Railway, có Redis riêng; `/health`, `/ready` → 200, `/ask` không key → 401, có key → 200)
- Screenshot: [dashboard](screenshots/dashboard.png), [running](screenshots/running.png), [test](screenshots/test.png)
- Chi tiết: [DEPLOYMENT.md](DEPLOYMENT.md)

### Exercise 3.2: So sánh `railway.toml` với `render.yaml`

So sánh hai file trong `06-lab-complete/` (cùng một agent, cùng Dockerfile):

| | `railway.toml` | `render.yaml` | Vì sao khác |
|---|---|---|---|
| Phạm vi | Cấu hình build và deploy của **một** service | **Blueprint**: khai báo cả hệ thống (web và Redis) | Railway coi project và database là thứ tạo bằng dashboard/CLI; Render coi hạ tầng là code |
| Redis | Không khai báo được, phải tạo riêng rồi trỏ `REDIS_URL` | `type: keyvalue`, web lấy URL qua `fromService` | Render dựng lại được cả hệ thống từ một file; Railway gọn hơn nhưng có bước làm tay |
| Biến môi trường | Không nằm trong file, đặt bằng `railway variables` | `envVars`: giá trị thường ghi thẳng, secret dùng `generateValue: true` hoặc `sync: false` | Cả hai đều giữ secret ngoài git; Render còn tự sinh được key |
| Build | `builder = "DOCKERFILE"` | `runtime: docker`, `rootDir`, `dockerfilePath` | Ví dụ ở `03-cloud-deployment/` dùng Nixpacks và `runtime: python`; Part 6 dùng Docker để image trên cloud giống image đã kiểm ở local |
| Health check | `healthcheckPath`, `healthcheckTimeout` | `healthCheckPath` | Cùng ý nghĩa, khác cách viết hoa |
| Restart | `restartPolicyType = "ON_FAILURE"`, số lần thử | Không khai báo, Render tự restart | Railway cho chỉnh chi tiết hơn |
| Cách deploy | `railway up` đẩy thư mục từ máy | Kết nối repo GitHub, tự deploy khi push | Railway nhanh khi thử; Render hợp GitOps |
| Vị trí file | Trong thư mục deploy | Mặc định ở gốc repo; file nằm thư mục con phải điền *Blueprint Path* | |

Health check trỏ vào `/health` chứ không phải `/ready`: nếu dùng `/ready`, Redis chập chờn sẽ làm platform coi bản deploy là hỏng và restart agent, trong khi restart không sửa được Redis.

### Exercise 3.3: Pipeline Cloud Run

`cloudbuild.yaml` chạy 4 bước nối tiếp bằng `waitFor`: **test** (cài thư viện, chạy `pytest`) → **build** image, gắn tag `$COMMIT_SHA` và `latest`, tái dùng layer bằng `--cache-from` → **push** lên Container Registry → **deploy** lên Cloud Run ở `asia-southeast1`. Test fail thì các bước sau không chạy nên code hỏng không lên production. Deploy dùng tag `$COMMIT_SHA` thay vì `latest` nên biết chính xác bản nào đang chạy và rollback được. `service.yaml` mô tả trạng thái mong muốn của service: 1–10 instance, 80 request đồng thời mỗi instance, 1 CPU / 512 MB, startup probe `/ready`, liveness probe `/health`; secret lấy từ Secret Manager nên không nằm trong repo. (Nếu chạy thật phải có thư mục `tests/`, repo này chưa có nên bước test sẽ fail.)

## Part 4: API Security

### Exercise 4.1: API Key

- **Kiểm ở đâu:** hàm `verify_api_key`, gắn vào `/ask` bằng `Depends(verify_api_key)`; chạy trước thân hàm nên request sai key không tới được LLM.
- **Sai key:** thiếu key → 401, có key nhưng sai → 403. (Part 6 theo hợp đồng của đề: cả hai đều 401.)
- **Rotate key:** key đọc từ env `AGENT_API_KEY` nên chỉ cần đổi env và restart. Để không gián đoạn thì cho server chấp nhận cả key cũ và mới trong một thời gian, đổi client sang key mới rồi bỏ key cũ. Lộ key thì bỏ ngay.

```text
# thiếu key
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
# sai key
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}
# đúng key
HTTP/1.1 200 OK
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). ..."}
```

### Exercise 4.2: JWT

Luồng: `POST /auth/token` kiểm username/password → server ký token HS256 chứa `sub`, `role`, `iat`, `exp` (60 phút) → client gửi `Authorization: Bearer <token>` → `verify_token` kiểm chữ ký và hạn, lấy `username`, `role` mà **không cần tra database**. Đổi lại, token đã phát không thu hồi được trước khi hết hạn nếu không có danh sách chặn. Payload chỉ mã hoá base64, ai có token cũng đọc được, nên không để dữ liệu nhạy cảm trong đó.

```text
# không có token
HTTP/1.1 401 Unauthorized
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -X POST .../auth/token -d '{"username":"student","password":"***"}'
{"access_token":"***","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer ***"}
payload sau khi giải mã: {"sub":"student","role":"user","iat":1795596440,"exp":1795600040}

# có token
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"...","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}

# token hỏng
HTTP/1.1 403 Forbidden
{"detail":"Invalid token."}
```

Lỗi nhỏ của ví dụ: `budget_remaining_usd` trong response thực ra là `total_cost_usd` (đã tiêu), không phải số còn lại. `/me/usage` trả đúng: `cost_usd 0.000186`, `budget_remaining_usd 0.999814`.

### Exercise 4.3: Rate limiting

- **Thuật toán:** sliding window log: mỗi user một `deque` timestamp, bỏ các mốc cũ hơn 60 giây rồi đếm.
- **Giới hạn:** user 10 request/phút, admin 100 request/phút.
- **Admin:** không bỏ qua hẳn mà dùng limiter riêng (`rate_limiter_admin`), chọn theo `role` trong JWT đã kiểm chữ ký nên client không tự nâng quyền được.

```text
# vòng lặp 20 request (trước đó đã gọi 1 lần nên 429 bắt đầu từ request thứ 10)
1:200 2:200 3:200 4:200 5:200 6:200 7:200 8:200 9:200 10:429 11:429 ... 20:429

HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 59
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

Hạn chế: state trong RAM. Chạy 3 instance thì mỗi user được 30 request/phút, restart là mất bộ đếm. Part 6 chuyển sang Redis sorted set.

### Exercise 4.4: Cost guard implementation

Rate limit chặn **tốc độ**, cost guard chặn **tiền**. Cần cả hai: 10 request/phút vẫn là 14.400 request/ngày, mỗi request prompt dài thì vẫn cháy ngân sách; ngược lại chỉ có cost guard thì một đợt bắn dồn vẫn làm sập service trước khi chạm ngân sách.

```python
def check_budget(user_id: str, estimated_cost: float) -> bool:
    key = f"budget:{user_id}:{datetime.now(timezone.utc):%Y-%m}"   # tháng mới = key mới → tự reset
    with r.pipeline() as pipe:                                     # MULTI/EXEC
        pipe.incrbyfloat(key, estimated_cost)                      # giữ chỗ trước
        pipe.expire(key, 32 * 24 * 3600)
        total = pipe.execute()[0]
    if total > MONTHLY_BUDGET_USD + 1e-9:                          # 10 USD, trừ sai số float
        r.incrbyfloat(key, -estimated_cost)                        # vượt → hoàn lại
        return False
    return True
```

Khác lời giải gợi ý ở chỗ **cộng trước rồi mới kiểm tra**. Cách "đọc → so sánh → ghi" có race condition: nhiều request song song cùng đọc thấy còn tiền. Đo với Redis thật, 50 request song song, mỗi cái $1, ngân sách $10:

```text
đọc-rồi-ghi (solution mẫu): cho qua 47
giữ chỗ trước:              cho qua 10
```

Trong Part 6 (`app/cost_guard.py`): ngân sách theo ngày cho toàn service, key `cost:YYYY-MM-DD` (UTC) trong Redis. `check_budget()` chạy trước khi gọi LLM, tổng ≥ `DAILY_BUDGET_USD` → **402**; `record_cost()` chạy sau, tính theo token thật và `INCRBYFLOAT`. Chi phí chỉ biết sau khi gọi nên các request song song lúc sắp hết tiền có thể vượt nhẹ, bị chặn trên bởi rate limit. Redis mất kết nối → **503**, không gọi LLM khi không đếm được tiền.

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks

| | `/health` (liveness) | `/ready` (readiness) |
|---|---|---|
| Câu hỏi | Process còn sống không? | Nhận traffic được chưa? |
| Kiểm gì | Không kiểm dependency | Kiểm Redis (Part 6: `PING`) |
| Fail thì | Platform **restart** container | Load balancer **ngừng gửi traffic**, không restart |

Không kiểm Redis trong `/health`: Redis chết thì restart agent không giúp gì, mà cả 3 instance cùng bị restart liên tục. Test trên Part 6 khi `docker compose stop redis`: `/health` vẫn 200, `/ready` 503, `/ask` 503; bật Redis lại thì tự hồi phục, không cần restart.

Chạy ví dụ `05-scaling-reliability/develop`:

```text
GET /health → {"status":"ok","uptime_seconds":2.8,"version":"1.0.0","environment":"development",...,"checks":{"memory":{"status":"ok","used_percent":82.8}}}
GET /ready  → {"ready":true,"in_flight_requests":1}
```

### Exercise 5.2: Graceful shutdown

Gửi SIGTERM khi một request đang chạy:

```text
INFO:     Shutting down
INFO:     127.0.0.1:63381 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
INFO 🔄 Graceful shutdown initiated...
INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
exit=0
# gọi lại sau khi tắt: curl: (7) Failed to connect
```

Thứ tự đúng: ngừng nhận kết nối mới → chạy xong request đang dở (client vẫn nhận 200) → đóng tài nguyên → thoát với code 0.

Uvicorn đã tự bắt SIGTERM nên phần dọn dẹp để trong `lifespan`, không cần tự đăng ký `signal.signal` (trong ví dụ, dòng "Received signal 15" chỉ in ra **sau khi** mọi thứ đã tắt, chứng tỏ handler tự viết không điều khiển việc tắt). Trong Docker, uvicorn phải là PID 1 mới nhận được SIGTERM: Part 6 dùng `CMD ["sh","-c","exec uvicorn ..."]`, có `exec` để thay thế shell. Kết quả: `docker stop` mất 0,7 giây, exit code 0 (nếu không nhận được tín hiệu thì Docker chờ 10 giây rồi SIGKILL, exit 137).

### Exercise 5.3: Stateless design

Bản `production/app.py` lưu lịch sử chat vào Redis (`session:{id}`, TTL 1 giờ, giữ 20 message gần nhất) thay vì dict trong RAM, nên instance nào cũng đọc được session của bất kỳ user nào. Với dict trong RAM, request thứ hai rơi vào instance khác là mất lịch sử.

Hai điểm chưa chắc chắn trong ví dụ:

1. `append_to_history` đọc → thêm → ghi đè nên hai request song song cùng session có thể mất message; dùng `RPUSH` + `LTRIM` thì không bị.
2. Redis lỗi lúc khởi động thì app âm thầm chuyển sang lưu trong RAM, tức là hết stateless mà không ai biết. Part 6 không có fallback: Redis mất thì `/ready` trả 503.

### Exercise 5.4: Load balancing

`docker compose -p k5-day14-scaling up -d --build --scale agent=3`, gọi 10 request tới `/chat` (ví dụ này không có `/ask`, Nginx mở cổng 8080):

```text
instance-cfcd00 instance-e0a14e instance-f2c21d instance-cfcd00 instance-e0a14e instance-f2c21d
instance-cfcd00 instance-e0a14e instance-f2c21d instance-cfcd00
```

Nginx chia round-robin đều cho 3 instance.

### Exercise 5.5: Test stateless

```text
$ python test_stateless.py
Request 1: [instance-cfcd00]   Request 2: [instance-e0a14e]   Request 3: [instance-f2c21d]
Request 4: [instance-cfcd00]   Request 5: [instance-e0a14e]
Instances used: {'instance-f2c21d', 'instance-cfcd00', 'instance-e0a14e'}
✅ All requests served despite different instances!
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

5 câu hỏi của cùng một session rơi vào 3 instance khác nhau mà lịch sử vẫn đủ 10 message (5 hỏi, 5 đáp), vì lịch sử nằm trong Redis. Script có sẵn không tự kill instance như đề mô tả nên kiểm tra thêm bằng tay: tạo session, `docker kill` một agent, gọi tiếp cùng `session_id`:

```text
$ docker kill k5-day14-scaling-agent-1
instance-f2c21d [200 0.12s]
instance-cfcd00 [200 0.16s]
(không trả lời)  [000 15.0s]   ← curl hết hạn 15 s
instance-f2c21d [200 0.14s]
instance-cfcd00 [200 0.15s]
(không trả lời)  [000 15.0s]
GET /chat/{session}/history → count 10      # 5 request thành công × 2 message, không mất
restart cả 3 agent → history vẫn 10
```

- **Stateless đạt:** session còn nguyên khi instance chết và khi restart toàn bộ agent.
- **Chuyển traffic thì chưa ổn:** cứ 3 request lại có 1 request treo. Nginx chỉ phân giải tên `agent` một lần lúc khởi động nên vẫn giữ IP của container đã chết, và `proxy_connect_timeout` mặc định là 60 giây nên phải chờ rất lâu mới thử instance khác. Cấu hình Part 7 sửa đúng hai chỗ này: `server agent:8000 resolve;` để hỏi lại DNS và `proxy_connect_timeout 2s`.

Kết luận: load balancer cần **phát hiện** instance chết nhanh, chứ nhiều instance và stateless thôi chưa đủ để người dùng không thấy lỗi.

## Part 6: Final Project

Output `python check_production_ready.py` (bản đầy đủ, có Docker, 25/11/2026):

```text
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

Đo thêm: image 297 MB (giới hạn 500 MB), `docker stop` 0,7 giây với exit code 0.

Part 7: xem [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md).

## AI log

Công cụ: Claude Code (model Claude Opus 5.5), chạy trực tiếp trên máy.

| Việc | Hỏi gì | Nhận gì | Kiểm tra bằng gì |
|---|---|---|---|
| Hiểu đề | "Giải thích bài lab": yêu cầu, file được sửa, cách chấm | Tóm tắt 9 mục và thứ tự làm | Đối chiếu `CHECKPOINTS.md`, `RUBRIC.md`, `RULES.md` |
| Part 1–5 | "Làm hết, ghi lại đã làm gì" | AI chạy từng ví dụ, viết câu trả lời | Mọi output trong bài là output của lệnh đã chạy; code cost guard Exercise 4.4 đo với Redis thật (47 so với 10 request lọt) |
| Part 6 | Như trên | **Toàn bộ code `06-lab-complete/app/`, Dockerfile, compose, `railway.toml`, `render.yaml` do AI viết** từ khung `TODO` | `check_production_ready.py` PASS 12/12; test thêm: 40 request song song, Redis chết rồi sống lại, budget nhỏ, key rỗng/sai, key không lộ trong log |
| Part 7 | Như trên | AI thêm metric, sửa `KNOWLEDGE_BASE`, viết `eval.yml`, chạy load test, eval, Locust, 5 thí nghiệm, chụp ảnh, viết report | Số trong report so lại với JSON/CSV; đối chiếu client với Prometheus/Jaeger |

**Chỗ AI làm sai hoặc tài liệu đề chưa chạy được, và cách sửa:**

- Số đo ở 100 concurrency dễ dẫn tới kết luận "agent chỉ chịu được 50"; đo lại bằng metric phía server thì nghẽn ở công cụ đo.
- Lần đo scaling đầu tiên sai (cả hai lần đều chạy 2 instance do `docker compose run` kéo `depends_on`); bỏ số, đo lại với `--no-deps`.
- Dockerfile Part 7 của đề không chạy (`No module named 'uvicorn'`), thêm `PYTHONUSERBASE`.
- Docker Hub giới hạn lượt kéo, lấy image chính thức của nginx và Prometheus từ mirror ECR Public và Quay rồi gắn lại tag.
- File eval JSON lần đầu ghi đường dẫn tuyệt đối có thông tin cá nhân; chạy lại eval với `--dataset eval/golden_dataset.jsonl`.

**Phần tự sửa, tự kiểm tra của người nộp:**

- Tự chạy `check_production_ready.py` (bản đầy đủ, có Docker): PASS 12/12, 43/43 checks; `docker stop` 0,5 giây, exit code 0.
- Tự gọi 12 request có key tới URL Railway: 10 lần 200, sau đó 2 lần 429, đúng giới hạn 10 request/phút.
- Sửa thử `auth.py`, đổi mã lỗi từ 401 sang 403 rồi chạy lại script: dự đoán tiêu chí 6 sẽ fail nhưng **vẫn PASS 12/12**. Nguyên nhân (hỏi AI): tên check ghi "→ 401" nhưng `check_production_ready.py` dòng 645 chấp nhận cả 401 lẫn 403. Vậy PASS 12/12 chưa chứng minh đúng mã 401; lệnh thứ ba của CP6 (`POST /ask` không key, in mã HTTP) mới kiểm được. Đã trả lại như cũ bằng `git restore`.
- Đọc `rate_limiter.py`: Dùng Redis để các worker dùng chung bộ đếm và không bị mất dữ liệu khi restart. Dùng Lua script để gom các bước kiểm tra và ghi thành một thao tác nguyên tử (atomic) trên một mốc giờ chung, ngăn chặn lỗi race condition khiến nhiều request lọt qua cùng lúc.
- Đọc `cost_guard.py`: Kiểm tra trước để chặn ngay request khi đã hết tiền, tránh gọi LLM gây tốn phí oan. Ghi chi phí sau vì trước khi LLM trả lời xong, ta không thể biết chính xác số `output_tokens` sinh ra cũng như liệu request có thành công hay bị lỗi giữa chừng.

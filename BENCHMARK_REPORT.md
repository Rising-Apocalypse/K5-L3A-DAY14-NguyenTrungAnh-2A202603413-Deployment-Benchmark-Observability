# Benchmark & Observability Report — Day 14

**Họ tên:** Nguyễn Trung Anh
**Ngày chạy:** 25/11/2026
**Môi trường:** MacBook Air M1 8 GB RAM, Docker Desktop 8 CPU / 3,8 GB RAM, Python 3.13.5. Máy chạy thêm vài container khác trong lúc đo, nên số tuyệt đối chỉ đúng cho máy này; phần so sánh giữa các cấu hình mới là phần dùng được.

Số liệu gốc: [reports/](reports/) (JSON của `load_test.py`, `run_eval.py`) và [benchmark-results/](benchmark-results/) (CSV của Locust).

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Bình thường p95 khoảng 220–300 ms, 500 ms chừa gần gấp đôi cho tải dao động mà người dùng vẫn thấy nhanh. LLM mock thỉnh thoảng chậm hẳn (~1,7 s, 3% request) nên không đặt theo p99: khi đó SLO sẽ đỏ thường trực và mất tác dụng |
| Error rate `/ask` | < 2 % | Lỗi nền của LLM là 1%. Ngưỡng 2% không báo khi mọi thứ bình thường nhưng bắt được lúc lỗi tăng gấp đôi |
| Accuracy trên golden dataset | ≥ 85 % | v2 ban đầu đạt 91,3% (21/23). Ngưỡng 85% cho phép sai tối đa 3 câu, chặn được bản kém rõ rệt như v1 (4,35%). Câu đang đúng mà thành sai thì bị chặn riêng bằng kiểm tra regression |

Alert trong Prometheus nới hơn SLO (p95 > 1 s, lỗi > 5%) vì alert là để gọi người dậy, SLO là mục tiêu chất lượng.

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

300 request mỗi lần, `MOCK_SLOW_RATE=0.03`, `MOCK_ERROR_RATE=0.01`.

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.87 | 194.6 | 227.4 | 1701.5 | 0.33% | PASS |
| 10 | 43.73 | 190.4 | 221.8 | 1673.2 | 0.33% | PASS |
| 50 | 105.81 | 198.1 | 263.0 | 1717.8 | 0.67% | PASS |
| 100 | 53.39 | 372.8 | 3749.8 | 3927.5 | 1.33% | **FAIL** (p95) |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

Từ 1 lên 10 thì gần như tuyến tính (3,87 → 43,73, gấp 11 lần), vì mỗi request chủ yếu là **chờ** LLM (sleep ~190 ms), không tốn CPU nên chạy song song được. Từ 10 lên 50 chỉ gấp 2,4 lần: với 300 request, vài request chậm 1,7 s ở cuối kéo dài cả lần đo (lần c50 chỉ dài 2,84 s).

Ở 100, RPS giảm còn một nửa và p95 lên 3,7 s. Kết luận vội sẽ là "agent chịu tối đa 50". Chạy lại 3 lần vẫn vậy, nên đo thêm từ phía server:

- Histogram `http_request_duration_seconds` của agent: 286–293 trên 301 request dưới 300 ms, trung bình 230–270 ms. Agent không chậm.
- Chia tải thành 4 process `load_test.py`, mỗi process 25 concurrency (tổng vẫn 100): tổng khoảng 146 req/s, p50 195–201 ms.

Vậy nút thắt ở lần đo c100 là **chính công cụ đo**: một process Python mở 100 kết nối cùng lúc không kịp xử lý. Ngưỡng thật của agent cao hơn 100 concurrency. Bảng vẫn giữ số gốc của lần chạy đã nộp.

### 2.2 Tail latency

300 request, concurrency 20.

| `MOCK_SLOW_RATE` | avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|
| 0 | 189.9 | 189.1 | 218.8 | 224.2 |
| 0.03 (mặc định) | 215.5 | 191.5 | 219.2 | 1663.4 |
| 0.1 | 356.8 | 197.3 | 1692.1 | 1714.7 |

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

Với 3% request chậm, **p99** nhạy nhất: từ 224 lên 1663 ms (gấp 7,4 lần), trong khi avg chỉ tăng 13% và p95 không đổi. Lên 10% thì p95 cũng nhảy lên 1692 ms (gấp 7,7 lần). Quy luật: tỷ lệ request chậm vượt 1% thì p99 thấy, vượt 5% thì p95 thấy.

Avg chia đều phần chậm của một số ít request cho tất cả, nên 10% người dùng phải chờ 1,7 s mà avg vẫn hiện 357 ms, một con số **không request nào gặp thật** (request hoặc ~190 ms hoặc ~1700 ms). SLO nên đặt theo percentile. p50 cũng không dùng được: nó gần như đứng yên ở cả ba dòng.

Với SLO p95 < 500 ms, cấu hình 0,1 FAIL. Lỗi 2,00% vừa đúng ngưỡng nên `load_test.py` (so sánh ≤) vẫn cho qua phần error.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.3% (21/23) | 100% (23/23) |
| Avg tokens / câu | 57.8 | 109.1 | 115.1 |
| Tổng cost (USD) | 0.000414 | 0.000762 | 0.000803 |
| Cost / câu đúng (USD) | 0.00041415 | 0.00003627 | 0.00003492 |
| Latency p50 / p95 (ms) | 170.2 / 191.6 | 191.8 / 213.3 | 193.4 / 224.2 |
| Quality gate | FAIL | PASS | PASS (`--min-accuracy 1.0`, không regression) |

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| `security-02` | thiếu `token`, `hết hạn`, `chữ ký` | Thêm tài liệu so sánh API key với JWT, từ khóa truy hồi `jwt` |
| `scaling-03` | thiếu `cpu`, `memory`, `custom metrics` | Thêm tài liệu về Kubernetes HPA, từ khóa truy hồi `hpa`, `kubernetes`, `autoscal` |

Hai câu sai không phải do model mà do **thiếu tài liệu** trong `KNOWLEDGE_BASE`. Hai mục mới nằm **cuối** danh sách và dùng từ khóa hẹp, vì hàm truy hồi lấy mục khớp **đầu tiên**. Thử đặt từ khóa rộng (`scale`, `request`, `api`) lên đầu danh sách: accuracy tụt còn 19/23, `security-01` và `scaling-01` đang đúng thành sai, và quality gate chặn lại nhờ kiểm tra regression.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

v2 tốn gần gấp đôi token mỗi câu và tổng chi phí cao hơn 84%, nhưng số câu đúng tăng từ 1 lên 21, nên **chi phí mỗi câu đúng rẻ hơn khoảng 11 lần**. Latency p50 thêm khoảng 22 ms vì có bước truy hồi. Nhìn chi phí mỗi request thì v1 "rẻ hơn", nhìn chi phí mỗi câu đúng thì v1 đắt hơn hẳn. Bản sửa KB tốn thêm ít token nhưng chi phí mỗi câu đúng còn thấp hơn v2 gốc.

Giới hạn: eval chấm theo keyword nên câu trả lời đủ từ khóa nhưng sai logic vẫn đạt; 100% ở đây nghĩa là đạt hết 23 câu, không phải agent luôn đúng.

Quality gate chạy tự động ở [.github/workflows/eval.yml](.github/workflows/eval.yml): mỗi pull request chạy eval v2, accuracy < 85% thì job fail. Kiểm tra ngược ở local: chạy v1 với baseline v2 cho exit code 1, 20 câu regression.

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải: [grafana-dashboard.png](screenshots/grafana-dashboard.png)
- [x] Trace chậm trong Jaeger: [jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Trace lỗi trong Jaeger, có event `exception`: [jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus có alert **firing**: [prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

**Câu hỏi Exercise 7.1**

1. *Ví dụ mỗi loại metric:* Counter `http_requests_total` (chỉ tăng), Gauge `agent_in_flight_requests` (lên xuống), Histogram `http_request_duration_seconds` và metric tự thêm `agent_question_length_chars`.
2. *Vì sao label là `route.path` chứ không phải URL thật:* mỗi giá trị label mới tạo một time series mới. Bot quét hàng nghìn URL lạ sẽ tạo hàng nghìn series (nhân thêm số status và bucket histogram), Prometheus phình RAM rồi chết. Đó là **cardinality explosion**, và kẻ tấn công tự gây ra được từ bên ngoài. Thử gọi 3 URL lạ: cả ba gộp vào một series `route="unmatched", status="404"` có giá trị 3.

**Câu hỏi Exercise 7.4** (30 user Locust, 2 instance)

1. *p95 và avg:* p95 = 298 ms, avg = 255 ms, p99 = 1875 ms. p95 gần avg cho thấy đa số request đều nhau; khoảng cách lớn nằm từ p95 lên p99 (hơn 6 lần), tức vài phần trăm request cực chậm. p95 trong Prometheus nội suy trong bucket nên lệch vài chục ms so với số đo chính xác của client.
2. *Nginx chia đều:* có, 9,15 và 9,00 req/s.
3. *Input tokens/s lớn hơn output:* 1408 so với 740 tokens/s. v2 chèn system prompt và tài liệu truy hồi vào prompt, còn câu trả lời thì ngắn. Vì vậy muốn giảm chi phí RAG thì cắt bớt ngữ cảnh trước.
4. *`curl :8080/metrics`:* **404**. Nginx chặn cố ý vì metric lộ route, lưu lượng, chi phí. Prometheus scrape thẳng agent trong mạng nội bộ, không qua Nginx.

### 4.2 Thí nghiệm "phá hệ thống"

Tải nền: Locust 20 user, 2 instance, khoảng 12 req/s. Dùng 20 thay vì 30 user vì ở 30 user chi phí bình thường đã là $2,40/giờ, `LLMCostBurnRateHigh` tự firing dù chưa phá gì. Ở 20 user, chi phí là $1,58/giờ và không alert nào hoạt động trước thí nghiệm. Thời gian tính từ lúc **bắt đầu đổi cấu hình**, hỏi API của Prometheus mỗi giây; giữa hai thí nghiệm chờ tới khi không còn alert nào.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | 90 s (pending ở 31 s) | Error rate (0,44% → 18,1%), Requests/s theo status code |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | 145 s (pending ở 24 s) | Latency p50/p95/p99 (p95 296 ms → 1,96 s), LLM latency p95 theo model |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | 155 s (pending ở 35 s) | Cost burn rate ($1,58 → $11,44/giờ); p95 cũng lên 718 ms nhưng chưa chạm ngưỡng 1 s |
| D | `docker pause` 1 instance | `AgentInstanceDown` | 39 s (pending ở 9 s) | Instances up (2 → 1), Requests/s theo instance |
| E | `AGENT_VERSION=v1` | Không có (theo dõi 5 phút) | — | Phiên bản đang chạy; Retrieval hit ratio mất dữ liệu. Golden Signals đều xanh |

Chạy A và B cùng lúc để chụp ảnh: `AgentHighErrorRate` firing sau 89 s, `AgentHighLatencyP95` sau 150 s (ảnh [prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)).

Giải thích các con số:

- **Thời gian phát hiện = thời gian metric vượt ngưỡng + `for`.** Phần `for` là 1 phút (A), 2 phút (B, C), 30 giây (D). Phần còn lại do khởi động lại container, scrape mỗi 5 s và cửa sổ `rate()`.
- **C có cửa sổ 5 phút mà vẫn báo nhanh** vì model đắt gấp nhiều lần: chỉ cần một phần cửa sổ chứa dữ liệu mới là vượt $2. Chiều ngược lại thì chậm: đổi về model rẻ sau gần 5 phút (298 s) alert mới tắt.
- **D: metric của agent không thấy lỗi mà người dùng thấy.** Trong lúc pause, Locust nhận 22 lỗi 504 (Nginx chờ instance treo 10 s rồi bỏ), nhưng error rate phía agent vẫn 0,6% vì instance treo không ghi nhận được gì. Cần đo thêm ở Nginx hoặc từ bên ngoài (blackbox probe). Sau đó Nginx tránh instance treo và instance còn lại nhận cả 12 req/s.
- **Đổi cấu hình cũng gây lỗi:** mỗi lần `docker compose up -d`, cả hai agent bị tạo lại **cùng lúc**, Locust nhận khoảng 150–165 lỗi 502 ở `/ask` mỗi lần (cộng dồn 1097 lỗi sau 7 lần đổi) và `AgentInstanceDown` chuyển pending vài giây. Alert không firing nhờ `for: 30s`, nhưng người dùng vẫn bị ảnh hưởng, nên production phải rolling update.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Trong 5 phút chạy v1, error rate 0,42%, p95 giảm từ 296 xuống 199 ms, chi phí giảm còn $0,75/giờ: mọi chỉ số kỹ thuật đều **đẹp hơn**. Chạy eval qua Nginx ngay lúc đó thì accuracy chỉ còn 4,3% (1/23), quality gate FAIL. Cách phát hiện:

1. **Trước khi deploy:** eval trên golden dataset trong CI, chặn merge nếu accuracy < 85% hoặc có regression (`.github/workflows/eval.yml`).
2. **Sau khi deploy:** canary vài phần trăm traffic, chạy eval định kỳ trên production (vài phút một lần) và xuất accuracy thành metric `agent_eval_accuracy` để đặt alert.
3. **Tín hiệu gián tiếp:** metric `agent_info` (phiên bản, model) kèm alert khi khác phiên bản mong muốn; alert `absent(agent_retrieval_total)`, vì v1 không truy hồi nên metric này biến mất; token trung bình mỗi câu giảm đột ngột.
4. **Từ người dùng:** tỷ lệ bấm "không hữu ích", hỏi lại cùng một câu; LLM-as-judge chấm trên mẫu traffic thật.

### 4.3 Debug bằng trace

- `trace_id`: `59df5a9abcbc22657508ea5958740826`
- Tổng thời gian: 1764.5 ms
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (1688.8 ms, 95.7%)
- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-25T08:47:51.351981+00:00", "level": "INFO", "service": "observable-agent", "instance": "b89baee4a8c1", "event": "llm_call", "trace_id": "59df5a9abcbc22657508ea5958740826", "span_id": "4f5de3b03ce618f0", "request_id": "a5a96cf6560b", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 76, "output_tokens": 39, "cost_usd": 3.5e-05, "llm_ms": 1688.0}
```

Trong cùng trace, `retrieve_context` chỉ mất 22,6 ms, nên tối ưu truy hồi không có ích; muốn cắt đuôi này phải đặt timeout hoặc retry ở tầng LLM. Đây là thứ metric không nói được: histogram chỉ cho biết "có request 1,7 s", trace mới chỉ ra nó nằm ở lời gọi LLM.

Trace lỗi `982eb8a15601d0cb1f14f24e5097bac3`: 123,2 ms, span `chat mock-llm-small` (94,5 ms) có event `exception`. Tìm ngược từ log sang Jaeger bằng `trace_id`:

```json
{"ts": "2026-11-25T08:53:41.331124+00:00", "level": "INFO", "service": "observable-agent", "instance": "373efed4f4d6", "event": "llm_error", "trace_id": "982eb8a15601d0cb1f14f24e5097bac3", "span_id": "87209dcd04511f01", "request_id": "8d07ce8e5246", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

(Log `llm_error` mà `level` vẫn là `INFO`: lọc log theo level sẽ bỏ sót, nên đổi thành `ERROR`.)

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số của riêng `/ask` (dòng `POST,/ask` trong CSV).

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 59.42 | 200 | 240 | 1700 | 57 / 7095 (0.80%) |
| 3 | 60.00 | 190 | 230 | 1700 | 64 / 7166 (0.89%) |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

Hầu như không: RPS tăng 1%, p95 từ 240 xuống 230 ms (bằng đúng bước làm tròn của Locust). Lý do:

- **Agent không phải nút thắt.** Với 1 instance ở 59,4 req/s, CPU container chỉ 18%. Với 3 instance, mỗi cái nhận khoảng 19,7 req/s. Tài nguyên đã dư sẵn thì thêm instance không có gì để cải thiện.
- **Thời gian nằm ở LLM.** p95 của span LLM khoảng 198 ms ở cả hai lần. Thêm agent không làm LLM trả lời nhanh hơn; p99 1700 ms do LLM chậm ngẫu nhiên 3% nên cũng không đổi.
- **Locust là closed-loop.** 100 user, mỗi user chờ phản hồi, nghỉ rồi mới gửi tiếp, nên RPS bị chặn bởi số user và think time.

Muốn thấy lợi ích của scale phải tăng tải tới khi CPU agent chạm giới hạn 0,5 core. Trong cấu hình này, 3 instance có ích về **độ sẵn sàng** (chết một cái vẫn chạy), không phải tốc độ.

**Lưu ý khi đo:** lệnh trong đề (`docker compose run --rm locust ...`) kéo theo `depends_on`, làm Compose đưa agent về `replicas: 2`, nên lần đầu cả hai lần đo đều chạy trên 2 instance. Số đó đã bỏ; đo lại với `--no-deps` và đếm instance ở Prometheus trong lúc chạy (đúng 1 và 3).

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. **Phải kiểm tra phép đo trước khi tin kết quả.** Hai số đo dễ dẫn tới kết luận sai: c100 nghẽn ở công cụ đo chứ không phải agent, và benchmark scaling ban đầu chạy 2 instance ở cả hai lần. Cả hai chỉ lộ ra khi đối chiếu client với metric phía server.
  2. **Average giấu đúng thứ cần thấy.** 3% request chậm 1,7 s chỉ làm avg tăng 13% nhưng p99 gấp 7 lần. Metric cho biết *có* vấn đề, trace cho biết *ở đâu* (95,7% ở span LLM), log cho biết *chi tiết*.
  3. **Hệ thống khỏe về kỹ thuật vẫn có thể sai.** Agent v1 nhanh hơn, rẻ hơn, không lỗi, mọi alert đều xanh, và trả lời đúng 1/23 câu. Chất lượng phải đo riêng bằng eval.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - Burn-rate alert theo error budget nhiều cửa sổ (5 phút và 1 giờ) thay cho ngưỡng cố định.
  - Chất lượng: tỷ lệ retrieval `miss`, điểm eval trên mẫu traffic thật, tỷ lệ người dùng bấm "không hữu ích".
  - Chi phí theo từng user và chi phí mỗi câu trả lời, thay vì chỉ tổng; ngưỡng $2/giờ của đề bị chạm ngay ở 30 user với cấu hình bình thường (đo $2,40/giờ), nên ngưỡng phải tính theo lưu lượng dự kiến.
  - Số lần bị rate limit (429), hết budget (402), kết nối Redis lỗi; mức bão hòa (in-flight so với giới hạn).
  - Timeout và tỷ lệ lỗi của nhà cung cấp LLM, tách khỏi lỗi của agent; alert khi **mất** metric (`absent()`).

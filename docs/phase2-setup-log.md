# Phase 2 — FastAPI Wrapper + Dockerfile

**Goal:** Build OpenAI-compatible FastAPI inference wrapper and containerize it

---

## ✅ Checklist

| Step | Status |
|------|--------|
| Project directory structure created | ✅ |
| `app/main.py` — FastAPI wrapper | ✅ |
| `app/requirements.txt` | ✅ |
| `docker/Dockerfile` — multi-stage build | ✅ |
| Docker image `llm-inference:v1` built (27s) | ✅ |
| `/health` endpoint | ✅ |
| `/v1/chat/completions` OpenAI-compatible | ✅ |
| `/metrics` Prometheus format | ✅ |

---

## Project Structure

```
lim-inference-platform/
├── app/
│   ├── main.py
│   └── requirements.txt
├── docker/
│   └── Dockerfile
└── docs/
    └── phase1-setup-log.md
```

---

## Key Design Decisions

- **`host.docker.internal:11434`** — Container reaches Ollama running in WSL2 via Docker's host gateway
- **Multi-stage Dockerfile** — Stage 1 installs dependencies, Stage 2 copies only the built artifacts → smaller final image
- **Prometheus metrics** — `llm_requests_total`, `llm_request_latency_seconds`, `llm_tokens_generated_total` exposed at `/metrics`
- **OpenAI-compatible schema** — `POST /v1/chat/completions` returns standard `choices[].message.content` format

---

## Docker Build

```bash
docker build -f docker/Dockerfile -t llm-inference:v1 .
# [+] Building 27.1s (12/12) FINISHED
# => [builder 4/4] RUN pip install --user --no-cache-dir -r requirements.txt   17.7s
# => exporting to image                                                          5.1s
# Successfully tagged llm-inference:v1
```

---

## API Test Results

**Health check:**
```bash
$ curl http://localhost:8000/health
{"status":"ok"}
```

**Inference — OpenAI-compatible response:**
```bash
$ curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"phi3:mini","messages":[{"role":"user","content":"Say hello in one word."}],"stream":false}'

{
    "id": "999b29e7",
    "object": "chat.completion",
    "model": "phi3:mini",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello, or simply \"Hi\"."}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 16, "completion_tokens": 8, "total_tokens": 24}
}
```

**Prometheus metrics (key LLM metrics):**
```
# HELP llm_requests_total Total LLM inference requests
llm_requests_total{status="success"} 1.0

# HELP llm_request_latency_seconds LLM request latency in seconds
llm_request_latency_seconds_bucket{le="30.0"} 1.0
llm_request_latency_seconds_count 1.0
llm_request_latency_seconds_sum 13.947

# HELP llm_tokens_generated_total Total tokens generated
llm_tokens_generated_total 2.0
```

---

## app/requirements.txt

```
fastapi==0.115.12
uvicorn==0.34.2
httpx==0.28.1
pydantic==2.11.4
prometheus-client==0.21.1
```

---

## docker/Dockerfile

```dockerfile
# Stage 1: builder
FROM python:3.11-slim AS builder
WORKDIR /build
COPY app/requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: runtime
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY app/main.py .
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```



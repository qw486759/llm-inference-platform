# Phase 2 — FastAPI Wrapper + Dockerfile

This phase builds an OpenAI-compatible HTTP interface on top of Ollama and packages it as a Docker image using a multi-stage build. The goal is a deployable artifact that exposes structured inference endpoints and Prometheus-compatible metrics.

---

## Checklist

| Step | Status |
|------|--------|
| `app/main.py` — FastAPI wrapper | ✅ |
| `app/requirements.txt` | ✅ |
| `docker/Dockerfile` — multi-stage build | ✅ |
| Docker image `llm-inference:v1` built in 27s | ✅ |
| `/health` endpoint | ✅ |
| `/v1/chat/completions` OpenAI-compatible | ✅ |
| `/metrics` Prometheus format | ✅ |

---

## Design Decisions

- **`host.docker.internal:11434`** — Allows the container to reach Ollama running on the WSL2 host via Docker's internal gateway, without binding Ollama to a public interface
- **Multi-stage Dockerfile** — Stage 1 installs Python dependencies; Stage 2 copies only the installed packages into a slim runtime image, reducing final image size
- **Prometheus metrics** — `llm_requests_total`, `llm_request_latency_seconds`, and `llm_tokens_generated_total` are exposed at `/metrics` for Kubernetes scraping
- **OpenAI schema** — The response envelope follows the `choices[].message.content` structure, making the service compatible with existing OpenAI client libraries

---

## Docker Build

```bash
docker build -f docker/Dockerfile -t llm-inference:v1 .
# [+] Building 27.1s (12/12) FINISHED
```

---

## API Test Results

```bash
$ curl http://localhost:8000/health
{"status":"ok"}

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

**Key Prometheus metrics after one request:**

```
llm_requests_total{status="success"} 1.0
llm_request_latency_seconds_sum 13.947
llm_tokens_generated_total 2.0
```

---

## Dockerfile

```dockerfile
FROM python:3.11-slim AS builder
WORKDIR /build
COPY app/requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY app/main.py .
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```
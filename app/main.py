import time
import uuid
import httpx
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

REQUEST_COUNT = Counter(
    "llm_requests_total",
    "Total LLM inference requests",
    ["status"]
)
REQUEST_LATENCY = Histogram(
    "llm_request_latency_seconds",
    "End-to-end request latency in seconds",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
)
TOKENS_GENERATED = Counter(
    "llm_tokens_generated_total",
    "Total completion tokens generated"
)

app = FastAPI(title="LLM Inference API", version="1.0.0")

# Ollama is expected to run on the host machine.
# In Docker/Kubernetes, host.docker.internal resolves to the host gateway.
OLLAMA_BASE_URL = "http://host.docker.internal:11434"


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "phi3:mini"
    messages: List[Message]
    stream: Optional[bool] = False
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 512


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    request_id = str(uuid.uuid4())[:8]
    start = time.time()

    payload = {
        "model": req.model,
        "messages": [m.dict() for m in req.messages],
        "stream": req.stream,
        "options": {
            "temperature": req.temperature,
            "num_predict": req.max_tokens,
        },
    }

    if req.stream:
        async def stream_generator():
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload
                ) as resp:
                    async for chunk in resp.aiter_text():
                        yield chunk
        return StreamingResponse(stream_generator(), media_type="application/x-ndjson")

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        REQUEST_COUNT.labels(status="error").inc()
        logger.error(f"[{request_id}] Ollama request failed: {e}")
        raise HTTPException(status_code=502, detail=str(e))

    latency = time.time() - start
    tokens = data.get("eval_count", 0)

    REQUEST_COUNT.labels(status="success").inc()
    REQUEST_LATENCY.observe(latency)
    TOKENS_GENERATED.inc(tokens)

    logger.info(f"[{request_id}] latency={latency*1000:.0f}ms tokens={tokens}")

    return {
        "id": request_id,
        "object": "chat.completion",
        "model": req.model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": data["message"]["content"]
            },
            "finish_reason": data.get("done_reason", "stop")
        }],
        "usage": {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": tokens,
            "total_tokens": data.get("prompt_eval_count", 0) + tokens
        }
    }